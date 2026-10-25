"""Step 3 of the import pipeline: the AI normalizes product names it gets in chunks.

The AI only sees names ("id|name" lines) and answers with compact JSON. Price, article
and stock are taken from the table by code; MXIK codes come from our own directory.
Providers: Gemini (several models, each with its own free daily quota), then Groq.
"""

import asyncio
import json
import logging
import re
import time
from datetime import date
from typing import Literal

import httpx
from google import genai
from google.genai import types
from pydantic import BaseModel, TypeAdapter, ValidationError, field_validator

from app.core.config import settings
from app.db.seed import CATEGORIES, CATEGORY_SLUGS
from app.services.price_cleaner import CleanRow
from app.services.spec_dictionary import CHOICE, NUMBER, DICTIONARY

log = logging.getLogger(__name__)

MAX_RETRIES = 5
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# Rough token estimates used to respect tokens-per-minute limits
CHARS_PER_TOKEN = 3.5
OUTPUT_TOKENS_PER_ROW = 45


RiskCode = Literal["spec_mismatch", "server_hardware", "mining", "used_as_new", "fake_capacity", "noname_psu"]
RISK_CODES = set(RiskCode.__args__)


class CompactItem(BaseModel):
    """Short keys keep the answer small: i=row, c=category, b=brand, m=model, n=name, s=condition, p=specs, f=risks."""

    i: int
    c: str
    b: str | None = None
    m: str | None = None
    n: str
    s: Literal["new", "used", "refurbished"] = "new"
    p: list[str] = []
    # Anti-Fraud hints: only types, the wording is added by our code
    f: list[RiskCode] = []

    # A model may answer in a slightly different shape (Groq: "p" as an object, an unknown risk code): one odd field
    # must not throw away the whole chunk of 60-400 rows
    @field_validator("p", mode="before")
    @classmethod
    def _specs_as_list(cls, value):
        if isinstance(value, dict):
            return [f"{k}:{v}" for k, v in value.items() if v not in (None, "")]
        return [str(v) for v in value] if isinstance(value, list) else []

    @field_validator("f", mode="before")
    @classmethod
    def _known_risks(cls, value):
        return [v for v in value if v in RISK_CODES] if isinstance(value, list) else []

    @field_validator("s", mode="before")
    @classmethod
    def _known_condition(cls, value):
        return value if value in ("new", "used", "refurbished") else "new"


class GroqAnswer(BaseModel):
    items: list[CompactItem]


_items_adapter = TypeAdapter(list[CompactItem])

_CATEGORY_LIST = ", ".join(f"{slug} ({name})" for slug, name, _ in CATEGORIES)


def _spec_hint(spec) -> str:
    if spec.kind == NUMBER:
        return spec.key if spec.unit in ("modules", "cores", "threads") else f"{spec.key}({spec.unit})"
    if spec.kind == CHOICE:
        return f"{spec.key}({'/'.join(spec.values)})" if spec.values and len(spec.values) <= 7 else spec.key
    return f"{spec.key}(признак)"  # yes/no: the word from the row ("rgb:ARGB"), so it can be checked


# Spec keys from the dictionary (brand has its own field "b")
_SPEC_KEYS = "\n".join(
    f"{cat}: {', '.join(_spec_hint(s) for s in specs if s.key != 'brand')}"
    for cat, specs in DICTIONARY.items() if any(s.key != "brand" for s in specs)
)

PROMPT = f"""Ты нормализуешь названия товаров из прайс-листа магазина компьютерной техники (Узбекистан).
Вход: строки "id|название | доп. текст". Строки "# лист / раздел" — контекст, подсказка категории.
Для каждой строки-ТОВАРА верни объект:
i — id; c — категория (slug из списка); b — бренд; m — модель/артикул производителя;
n — чистое название в стиле "Тип Бренд Модель параметры" на русском (как "Блок питания Aerocool KCAS Plus 600W"); не переводи на английский; исправь опечатки и сленг; убери пометки магазина ("распродажа", "акция"); если в строке комплект — перечисли все его части (плата + процессор);
s — состояние: used (б/у) или refurbished (восстановленный); для новых не указывай;
p — характеристики строками "ключ:значение", ТОЛЬКО ключи из списка для категории ниже и только то, что написано в строке (capacity:16GB, socket:AM5, rgb:ARGB); значение пиши как в строке, без пересчёта; чего нет в строке — не указывай.
f — подозрения, ТОЛЬКО если они явно видны в строке, обычно не указывай: spec_mismatch (характеристики противоречат друг другу), server_hardware (серверное: Xeon, ECC, китайская X99), mining (после майнинга), used_as_new (признаки б/у при s новом), fake_capacity (неправдоподобный объём, напр. флешка 2TB), noname_psu (БП без бренда).
Не указывай b и m, если их нет. Не придумывай данные. Противоречия (в названии DDR5, в артикуле DDR4) не исправляй.
Не-товары (заголовки, примечания, условия) пропусти. Товар без подходящей категории (коврик, кронштейн, руль, роутер, веб-камера) не пропускай: c — other.
Категории: {_CATEGORY_LIST}
Ключи характеристик по категориям:
{_SPEC_KEYS}
"""

GROQ_FORMAT = 'Ответ — JSON-объект {"items": [ ... ]} с объектами из ключей i, c, b, m, n, s, p, f.'


class QuotaExhausted(RuntimeError):
    """Every configured model has used up its daily quota."""


class TruncatedAnswer(RuntimeError):
    """The answer hit the output token limit: the chunk must be split."""


class RateLimiter:
    """Keeps a provider under its requests-per-minute and tokens-per-minute limits."""

    def __init__(self, rpm: int, tpm: int | None = None):
        self.rpm, self.tpm = rpm, tpm
        self._events: list[tuple[float, int]] = []
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 0) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._events = [(t, n) for t, n in self._events if now - t < 60]
                used = sum(n for _, n in self._events)
                if len(self._events) < self.rpm and (not self.tpm or not self._events or used + tokens <= self.tpm):
                    self._events.append((now, tokens))
                    return
                await asyncio.sleep(60 - (now - self._events[0][0]) + 0.5)


_gemini_limiter = RateLimiter(settings.gemini_rpm)
_groq_limiter = RateLimiter(settings.groq_rpm, settings.groq_tpm)
# model -> day its free daily quota ran out (free tier: ~20 requests per day per model)
_exhausted_on: dict[str, date] = {}
_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def _available_models() -> list[str]:
    models = [settings.gemini_model, *settings.gemini_fallback_models]
    return [m for m in models if _exhausted_on.get(m) != date.today()]


def _retry_delay(error: Exception, attempt: int) -> float:
    """429 tells how long to wait ("retry in 6.5s"); otherwise back off linearly."""
    match = re.search(r"retry in ([\d.]+)s", str(error))
    return float(match.group(1)) + 1 if match else 10 * (attempt + 1)


def format_chunk(rows: list[CleanRow]) -> str:
    """"id|name" lines; the sheet/section context line is repeated when it changes."""
    lines, ctx = [], None
    for r in rows:
        if (r.sheet, r.section) != ctx:
            ctx = (r.sheet, r.section)
            lines.append(f"# {r.sheet} / {r.section or '-'}")
        lines.append(f"{r.row}|{r.ai_text}")
    return "\n".join(lines)


def _normalize(text: str) -> str:
    # "1,5м" -> "1.5м", but a list "1Gb,33стр" keeps its comma
    return re.sub(r"(?<=\d),(?=\d)", ".", text.lower().replace("ё", "е"))


# Units may differ between the AI answer and the row ("1.5m" / "1,5м"): only the number must match
_UNITS = {
    "gb", "mb", "tb", "kb", "w", "вт", "hz", "гц", "ghz", "mhz", "ггц", "мгц", "m", "м", "mm", "мм", "cm", "см",
    "a", "а", "v", "в", "mah", "dpi", "ppm", "rpm", "ms", "мс", "inch", "дюйм", "шт", "pcs", "мин", "стр",
    "va", "ва", "стр/мин",
}
# The AI answers in English, rows are often Russian: English word start -> Russian stem
_SYNONYMS = (
    ("wireless", "беспровод"), ("wired", "провод"), ("mechanic", "механ"), ("laser", "лаз"), ("inkjet", "струй"),
    ("black", "черн"), ("white", "бел"), ("grey", "сер"), ("gray", "сер"), ("red", "красн"), ("blue", "син"),
    ("green", "зелен"), ("pink", "розов"), ("silver", "серебр"), ("gold", "золот"), ("headphone", "наушн"),
    ("headset", "гарнитур"), ("keyboard", "клав"), ("mouse", "мыш"), ("fan", "вентил"), ("cooler", "кулер"),
    ("speaker", "акуст"), ("speaker", "колон"), ("monitor", "монитор"), ("printer", "принтер"), ("mfp", "мфу"),
    ("curved", "изогн"), ("used", "б/у"), ("membrane", "мембран"), ("gaming", "игров"), ("liquid", "водян"),
    ("water", "водян"), ("color", "цв"), ("bronze", "бронз"), ("platinum", "платин"), ("titanium", "титан"),
)


def _stem_in(tok: str, norm: str) -> bool:
    """Russian endings differ ("струйный" / "струйное"): compare the word stem."""
    return bool(re.fullmatch(r"[а-я]{5,}", tok)) and tok[: max(4, len(tok) - 3)] in norm


def spec_in_text(value: str, text: str) -> bool:
    """Is the spec value written in the row itself? Every number and every word must be found there.

    "4GB DDR4" matches "DDR4 4GB", "16A" matches "16 ампер", "wireless" matches "беспроводные";
    "80 PLUS Bronze" does not match "Блок питания 600W", "6" does not match "1660".
    """
    norm = _normalize(text)
    compact = re.sub(r"[^a-zа-я0-9.+/]", "", norm)
    tokens = [t.strip(".") for t in re.findall(r"[a-zа-я0-9.+/]+", _normalize(value))]
    tokens = [t for t in tokens if t]
    if not tokens:
        return False
    for tok in tokens:
        num = re.fullmatch(r"(\d+(?:\.\d+)?)([a-zа-я]*)", tok)
        if num and (not num[2] or num[2] in _UNITS):
            # a standalone number: not a part of "DDR4" or "1660"
            if not re.search(rf"(?<![\d.a-zа-я]){re.escape(num[1])}(?!\d)", norm):
                return False
        elif tok in _UNITS or len(tok) < 2 or tok in compact or _stem_in(tok, norm):
            continue
        elif not any(tok.startswith(en) and ru in norm for en, ru in _SYNONYMS):
            return False
    return True


def split_specs(specs: dict, text: str) -> tuple[dict, dict]:
    """(confirmed by the row text, AI guesses). Guesses are shown but never saved or used by Anti-Fraud."""
    confirmed, guessed = {}, {}
    for key, value in specs.items():
        (confirmed if spec_in_text(str(value), text) else guessed)[key] = value
    return confirmed, guessed


def _estimate_tokens(text: str, rows: int) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + rows * OUTPUT_TOKENS_PER_ROW


def _to_dicts(items: list[CompactItem]) -> list[dict]:
    result = []
    for it in items:
        specs = dict(p.split(":", 1) for p in it.p if ":" in p)
        result.append({
            "row": it.i,
            "category": it.c if it.c in CATEGORY_SLUGS else "other",
            "brand": it.b or None,
            "model": it.m or None,
            "name": it.n,
            "condition": it.s,
            "specs": {k.strip(): v.strip() for k, v in specs.items()},
            "risks": list(dict.fromkeys(it.f)),
        })
    return result


async def _call_gemini(model: str, text: str) -> tuple[str, bool]:
    """Returns (answer text, truncated?). A separate function so tests can replace it."""
    config = types.GenerateContentConfig(
        system_instruction=PROMPT,
        response_mime_type="application/json",
        response_schema=list[CompactItem],
        temperature=0,
        max_output_tokens=settings.gemini_max_output_tokens,
        thinking_config=types.ThinkingConfig(thinking_level=settings.gemini_thinking_level),
    )
    resp = await _get_client().aio.models.generate_content(model=model, contents=text, config=config)
    finish = resp.candidates[0].finish_reason if resp.candidates else None
    return resp.text or "", finish == types.FinishReason.MAX_TOKENS


async def _gemini(rows: list[CleanRow], stats: dict) -> list[dict]:
    text = format_chunk(rows)
    last_error: Exception | None = None
    attempt = 0
    while attempt < MAX_RETRIES:
        models = _available_models()
        if not models:
            raise QuotaExhausted("Daily quota exhausted for all Gemini models")
        model = models[0]
        await _gemini_limiter.acquire()
        stats["requests"] = stats.get("requests", 0) + 1
        try:
            answer, truncated = await _call_gemini(model, text)
            if truncated:
                raise TruncatedAnswer(f"{len(rows)} rows did not fit into the answer")
            items = _to_dicts(_items_adapter.validate_python(json.loads(answer)))
            models_used = stats.setdefault("models", {})
            models_used[model] = models_used.get(model, 0) + 1
            return items
        except TruncatedAnswer:
            raise
        except (ValidationError, json.JSONDecodeError, TypeError) as e:
            last_error = e  # malformed answer: just ask again
        except Exception as e:  # network errors, 429 rate limits, 503 overload
            if "PerDay" in str(e):
                # Waiting hours makes no sense: switch to the next model right away
                log.warning("Gemini %s: daily quota exhausted, switching model", model)
                _exhausted_on[model] = date.today()
                stats["requests"] -= 1  # rejected before any work, not counted
                continue
            last_error = e
            await asyncio.sleep(_retry_delay(e, attempt))
        attempt += 1
        log.warning("Gemini %s attempt %s failed: %s", model, attempt, str(last_error)[:300])
    raise RuntimeError(f"Gemini failed after {MAX_RETRIES} attempts: {last_error}")


async def _call_groq(text: str) -> tuple[str, bool]:
    """Returns (answer text, truncated?). A separate function so tests can replace it."""
    payload = {
        "model": settings.groq_model,
        "messages": [{"role": "system", "content": PROMPT + GROQ_FORMAT}, {"role": "user", "content": text}],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "reasoning_effort": "low",
        "max_completion_tokens": settings.groq_max_output_tokens,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(GROQ_URL, json=payload, headers={"Authorization": f"Bearer {settings.groq_api_key}"})
    if resp.status_code == 429:
        raise RuntimeError(f"Groq 429, retry in {resp.headers.get('retry-after', '10')}s")
    resp.raise_for_status()
    choice = resp.json()["choices"][0]
    return choice["message"]["content"] or "", choice.get("finish_reason") == "length"


async def _groq(rows: list[CleanRow], stats: dict) -> list[dict]:
    text = format_chunk(rows)
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        await _groq_limiter.acquire(_estimate_tokens(text, len(rows)))
        stats["requests"] = stats.get("requests", 0) + 1
        stats["groq_requests"] = stats.get("groq_requests", 0) + 1
        try:
            answer, truncated = await _call_groq(text)
            if truncated:
                raise TruncatedAnswer(f"{len(rows)} rows did not fit into the answer")
            return _to_dicts(GroqAnswer.model_validate_json(answer).items)
        except TruncatedAnswer:
            raise
        except (ValidationError, json.JSONDecodeError, KeyError) as e:
            last_error = e
        except Exception as e:
            last_error = e
            await asyncio.sleep(_retry_delay(e, attempt))
        log.warning("Groq attempt %s failed: %s", attempt + 1, str(last_error)[:300])
    raise RuntimeError(f"Groq failed after {MAX_RETRIES} attempts: {last_error}")


async def _split_on_truncation(call, rows: list[CleanRow], stats: dict) -> list[dict]:
    try:
        return await call(rows, stats)
    except TruncatedAnswer:
        if len(rows) == 1:
            raise RuntimeError("A single row does not fit into the answer")
        half = len(rows) // 2
        stats["splits"] = stats.get("splits", 0) + 1
        return await _split_on_truncation(call, rows[:half], stats) + await _split_on_truncation(call, rows[half:], stats)


async def parse_rows(rows: list[CleanRow], stats: dict) -> list[dict]:
    """Gemini first; if every Gemini model is out of quota or failing, Groq in smaller pieces."""
    try:
        return await _split_on_truncation(_gemini, rows, stats)
    except RuntimeError as e:
        if not settings.groq_api_key:
            raise
        log.warning("Gemini unavailable (%s), using Groq", str(e)[:200])
    size = settings.groq_chunk_rows
    result = []
    for start in range(0, len(rows), size):
        result += await _split_on_truncation(_groq, rows[start : start + size], stats)
    return result
