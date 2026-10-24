"""Step 3 of the import pipeline: Gemini turns cleaned rows into structured products.

The AI only normalizes text and picks a category slug from our list.
MXIK codes, stock status and currency are decided by code, not by the AI.
"""

import asyncio
import json
import logging
import re
import time
from datetime import date
from typing import Literal

from google import genai
from google.genai import types
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.core.config import settings
from app.db.seed import CATEGORIES, CATEGORY_SLUGS
from app.services.price_cleaner import CleanRow

log = logging.getLogger(__name__)

MAX_RETRIES = 5


class Spec(BaseModel):
    key: str
    value: str


class ParsedItem(BaseModel):
    row: int
    category: str
    brand: str | None = None
    model: str | None = None
    name: str
    price: float | None = None
    condition: Literal["new", "used", "refurbished"] = "new"
    specs: list[Spec] = []


_items_adapter = TypeAdapter(list[ParsedItem])

_CATEGORY_LIST = "\n".join(f"- {slug}: {name}" for slug, name, _ in CATEGORIES)

PROMPT = f"""Ты разбираешь прайс-лист магазина компьютерной техники из Узбекистана.
Каждая строка начинается с идентификатора вида r123, ячейки разделены " | ".
Строки "# Sheet: ... / Section: ..." — это контекст (лист и подзаголовок), они подсказывают категорию для строк ниже.

Для каждой строки, которая является ТОВАРОМ, верни объект:
- row: число из идентификатора (r123 -> 123);
- category: один slug из списка ниже (если не подходит ни один — other);
- brand: производитель (Intel, Kingston, MSI…), без лишних слов;
- model: модель/артикул производителя, если есть;
- name: чистое нормализованное название: бренд, модель, ключевые характеристики. Исправь опечатки и сленг, убери пометки магазина ("распродажа", "акция", "new!");
- price: цена из столбца с ценой (если цен несколько — первая, обычно "опт"); если цены нет — null. Не путай цену с номером строки, объёмом или частотой;
- condition: new, used (б/у) или refurbished (восстановленный); по умолчанию new;
- specs: 2–6 ключевых характеристик парами key/value (например: socket, memory, capacity, frequency, power).

Не придумывай данные, которых нет в строке. Если в строке противоречие (например, в названии DDR5, а в артикуле DDR4) — оставь как есть, не исправляй.
Строки, которые не являются товарами (заголовки, примечания, контакты, условия доставки), пропусти.

Категории:
{_CATEGORY_LIST}
"""

_client: genai.Client | None = None
# model -> day its free daily quota ran out (free tier: ~20 requests per day per model)
_exhausted_on: dict[str, date] = {}


class QuotaExhausted(RuntimeError):
    """Every configured model has used up its daily quota."""


def _available_models() -> list[str]:
    models = [settings.gemini_model, *settings.gemini_fallback_models]
    return [m for m in models if _exhausted_on.get(m) != date.today()]
_request_times: list[float] = []
_rate_lock = asyncio.Lock()


async def _wait_for_rate_limit() -> None:
    """Keeps us under settings.gemini_rpm requests per rolling minute."""
    async with _rate_lock:
        while True:
            now = time.monotonic()
            _request_times[:] = [t for t in _request_times if now - t < 60]
            if len(_request_times) < settings.gemini_rpm:
                _request_times.append(now)
                return
            await asyncio.sleep(60 - (now - _request_times[0]) + 0.5)


def _retry_delay(error: Exception, attempt: int) -> float:
    """429 tells how long to wait ("retry in 6.5s"); otherwise back off linearly."""
    match = re.search(r"retry in ([\d.]+)s", str(error))
    return float(match.group(1)) + 1 if match else 10 * (attempt + 1)


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


async def parse_chunk(chunk: str) -> list[ParsedItem]:
    config = types.GenerateContentConfig(
        system_instruction=PROMPT,
        response_mime_type="application/json",
        response_schema=list[ParsedItem],
        temperature=0,
        thinking_config=types.ThinkingConfig(thinking_level=settings.gemini_thinking_level),
    )
    last_error: Exception | None = None
    attempt = 0
    while attempt < MAX_RETRIES:
        models = _available_models()
        if not models:
            raise QuotaExhausted("Daily quota exhausted for all Gemini models")
        model = models[0]
        await _wait_for_rate_limit()
        try:
            resp = await _get_client().aio.models.generate_content(model=model, contents=chunk, config=config)
            items = _items_adapter.validate_python(json.loads(resp.text))
            for item in items:
                if item.category not in CATEGORY_SLUGS:
                    item.category = "other"
            return items
        except (ValidationError, json.JSONDecodeError, TypeError) as e:
            last_error = e  # malformed answer: just ask again
        except Exception as e:  # network errors, 429 rate limits, 503 overload
            if "PerDay" in str(e):
                # Waiting hours makes no sense: switch to the next model right away
                log.warning("Gemini %s: daily quota exhausted, switching model", model)
                _exhausted_on[model] = date.today()
                continue
            last_error = e
            await asyncio.sleep(_retry_delay(e, attempt))
        attempt += 1
        log.warning("Gemini %s attempt %s failed: %s", model, attempt, str(last_error)[:300])
    raise RuntimeError(f"Gemini failed after {MAX_RETRIES} attempts: {last_error}")


def merge_rows(rows: list[CleanRow], items: list[ParsedItem]) -> list[dict]:
    """Join AI answers with the original rows. Rows the AI skipped are not products."""
    by_row = {r.row: r for r in rows}
    result = []
    for item in sorted(items, key=lambda i: i.row):
        src = by_row.get(item.row)
        if src is None:
            continue  # AI invented a row id
        result.append(
            {
                "row": item.row,
                "raw_name": src.raw_name,
                "section": src.section,
                "category": item.category,
                "brand": item.brand,
                "model": item.model,
                "name": item.name,
                "price": item.price,
                "condition": item.condition,
                "specs": {s.key: s.value for s in item.specs},
                # No price in the file means "out of stock"
                "is_in_stock": item.price is not None,
            }
        )
    return result
