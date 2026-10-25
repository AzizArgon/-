"""Pasted text (e.g. a Telegram post) -> rows for the same pipeline as a price list file.

Sellers in Uzbekistan publish goods as posts:
    🔥 Новое поступление!
    i5 12400f б/у — 110$
    SSD 1TB Samsung 980 — 1 250 000 сум
    📍 Чиланзар, тел +998...
Code removes emojis, hashtags and advert lines (no price, phone, address) and reads price and currency of every
line itself; the AI later sees only the product words, as with files.
"""

import re
import unicodedata

from app.services.price_cleaner import CleanRow

NUM = r"(\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
# The last match in a line is its price. Marked currencies win over a bare number
_PRICE = re.compile(
    rf"\$\s*(?P<n1>{NUM})"
    rf"|(?P<n2>{NUM})\s*(?:(?P<usd>\$|у\.?\s?е\.?|usd\b|долл\w*|dollar\w*|бакс\w*)"
    rf"|(?P<mln>млн|mln\b|million\w*|миллион\w*)\.?(?:\s*(?:сум|сўм|so['’ʻ`]?m|sum)\b)?"
    rf"|(?P<thousand>тыс\w*|минг\b|ming\b)\.?(?:\s*(?:сум|сўм|so['’ʻ`]?m|sum)\b)?"
    rf"|(?P<uzs>сум\w*|сўм|so['’ʻ`]?m\b|sum\b|uzs\b))",
    re.IGNORECASE,
)
# A number without a currency counts as a price only after a separator at the end: "i5 12400f — 110"
# ("ddr4-3200" or "ddr4 3200" is a frequency, not a price)
_BARE_PRICE = re.compile(rf"(?:\s[-=]|[—–:])\s*(?P<num>{NUM})\s*$")
_PHONE_PART = re.compile(r"\+?\d[\d \-()]{7,}\d")
_HASHTAG = re.compile(r"#\w+")
_BULLET = re.compile(r"^[\s\-–—•*·▪►→>]+")
_TAIL = re.compile(r"[\s\-–—:=,;|/]+$")
# Lines that are about the shop, not a product, even if they have a number
AD_WORDS = (
    "поступлени", "доставк", "звоните", "звонит", "телефон", "тел.", "тел:", "адрес", "ориентир", "пишите",
    "заказ", "гарантия", "t.me", "http", "@", "instagram", "telegram", "скидк", "акция", "manzil", "aloqa",
)
PRICE_WORDS = {"цена", "цены", "price", "narxi", "нарх"}


def _strip_symbols(text: str) -> str:
    """Emojis and other pictographs out; letters, digits, punctuation and "$" stay."""
    return "".join(
        ch for ch in text
        if unicodedata.category(ch) not in ("So", "Sk", "Cs", "Co", "Cf", "Mn") or ch in "'’ʻ"
    )


def _has_phone(line: str) -> bool:
    """+998 90 123 45 67, 90-123-45-67: a plus sign or 9+ digits (a price has fewer: 12 500 000)."""
    return any(m[0].startswith("+") or sum(ch.isdigit() for ch in m[0]) >= 9 for m in _PHONE_PART.finditer(line))


def _amount(text: str) -> float | None:
    text = re.sub(r"[   ]", "", text).replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value > 0 else None


def find_price(line: str, default_currency: str) -> tuple[float | None, str | None, bool, str]:
    """(price, currency, check currency?, line without the price). "1.2 млн" = 1 200 000 сум."""
    matches = list(_PRICE.finditer(line))
    if matches:
        m = matches[-1]
        value = _amount(m["n1"] or m["n2"])
        if value is None:
            return None, None, False, line
        if m["mln"]:
            value, currency = value * 1_000_000, "UZS"
        elif m["thousand"]:
            value, currency = value * 1_000, "UZS"
        elif m["uzs"]:
            currency = "UZS"
        else:
            currency = "USD"
        return round(value, 2), currency, False, line[: m.start()] + line[m.end():]
    bare = _BARE_PRICE.search(line)
    if bare:
        # No currency in the line: the one chosen above the text field, and the seller is asked to check it
        return _amount(bare["num"]), default_currency, True, line[: bare.start()]
    return None, None, False, line


def _clean_name(text: str) -> str:
    text = _BULLET.sub("", text)
    return _TAIL.sub("", re.sub(r"\s+", " ", text)).strip()


def text_to_rows(text: str, default_currency: str) -> list[CleanRow]:
    rows: list[CleanRow] = []
    waiting_name = ""  # "i5 12400f" on one line and "Цена: 110$" on the next
    for raw in unicodedata.normalize("NFC", text).splitlines():
        line = _HASHTAG.sub(" ", _strip_symbols(raw)).strip()
        low = line.lower()
        if not line or _has_phone(line) or any(w in low for w in AD_WORDS):
            waiting_name = ""
            continue
        price, currency, check, rest = find_price(line, default_currency)
        name = _clean_name(rest)
        if price is None:
            # A line with letters and digits may be a product whose price is on the next line
            waiting_name = name if re.search(r"\d", name) and re.search(r"[^\W\d_]", name) else ""
            continue
        if not name or name.lower().strip(" :") in PRICE_WORDS:
            name, waiting_name = waiting_name, ""
        if not name or not re.search(r"[^\W\d_]", name):
            continue
        rows.append(CleanRow(
            row=len(rows) + 1, sheet="", section="", cells=[name], name=name, price=price, is_in_stock=True,
            ai_text=name, currency=currency, currency_check=check,
        ))
    return rows


def text_title(text: str, limit: int = 60) -> str:
    """A name for the import history: the first product line of the post."""
    rows = text_to_rows(text, "USD")
    title = rows[0].name if rows else _clean_name(_strip_symbols(text.strip().splitlines()[0]))
    return title if len(title) <= limit else title[: limit - 1] + "…"
