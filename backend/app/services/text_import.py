"""Pasted text (e.g. a Telegram post) -> rows for the same pipeline as a price list file.

Sellers in Uzbekistan publish goods as posts of two kinds:
- a list, one line = one product:
    🔥 Новое поступление!
    i5 12400f б/у — 110$
    SSD 1TB Samsung 980 — 1 250 000 сум
- a card of one product: a title, lines "Key: value" and one price, often twice — in Russian and in Uzbek:
    Комплект памяти Corsair Vengeance LPX 16GB (2x8GB) DDR4 3000MHz
    Состояние: Б/У ...  Объем: 16 GB ...  Цена: 950.000 сум
    Holati: B/U ...  Hajmi: 16 GB ...  Narxi: 950.000 so'm
Code removes emojis, hashtags and advert lines (delivery, contacts, @username), decides the kind of the post and
reads price, currency (and for a card the condition) itself; the AI later sees only the product words, as with files.
"""

import re
import unicodedata

from app.services.price_cleaner import CleanRow

NUM = r"(\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d{1,3}(?:[.,]\d{3}){2,}|\d+(?:[.,]\d+)?)"
SUM = r"(?:сум|сўм|so['’ʻ`]?m|sum)"
# The last match in a line is its price. Marked currencies win over a bare number
_PRICE = re.compile(
    rf"\$\s*(?P<n1>{NUM})"
    rf"|(?P<n2>{NUM})\s*(?:(?P<usd>\$|у\.?\s?е\.?|usd\b|долл\w*|dollar\w*|бакс\w*)"
    rf"|(?P<mln>млн|mln\b|million\w*|миллион\w*)\.?(?:\s*{SUM}\b)?"
    rf"|(?P<thousand>тыс\w*|минг\b|ming\b)\.?(?:\s*{SUM}\b)?"
    rf"|(?P<uzs>сум\w*|сўм|so['’ʻ`]?m\b|sum\b|uzs\b))",
    re.IGNORECASE,
)
# A number without a currency counts as a price only after a separator at the end: "i5 12400f — 110"
# ("ddr4-3200" or "ddr4 3200" is a frequency, not a price)
_BARE_PRICE = re.compile(rf"(?:\s[-=]|[—–:])\s*(?P<num>{NUM})\s*$")
# "950.000" / "1,250,000" in sums: the dot or comma separates thousands (sums have no fractions)
_DOTTED_THOUSANDS = re.compile(r"^\d{1,3}(?:[.,]\d{3})+$")
_PHONE_PART = re.compile(r"\+?\d[\d \-()]{7,}\d")
_HASHTAG = re.compile(r"#\w+")
_BULLET = re.compile(r"^[\s\-–—•*·▪►→>]+")
_TAIL = re.compile(r"[\s\-–—:=,;|/.]+$")
# "Ключ: значение" of a card post: a short key without digits ("XMP профиль", "Holati")
_KEY_VALUE = re.compile(r"^(?P<key>[^\W\d_][^:\d]{0,28}):\s*(?P<value>\S.*)$")
# Lines that are about the shop, not a product, even if they have a number. A header ("Доставка:") also hides
# the bullet lines under it ("• По Фергане — Такси")
AD_WORDS = (
    "поступлени", "доставк", "звоните", "звонит", "телефон", "тел.", "тел:", "адрес", "ориентир", "пишите",
    "заказ", "гарантия", "t.me", "http", "@", "instagram", "telegram", "скидк", "акция", "купить", "самовывоз",
    "manzil", "aloqa", "yetkazib", "sotib olish", "buyurtma", "murojaat", "chegirma",
)
PRICE_WORDS = {"цена", "цены", "price", "narxi", "narx", "нарх"}
# Uzbek (Latin) words of posts -> the Russian ones the rules and the AI prompt know
UZ_WORDS = {
    "b/u": "б/у", "narxi": "цена", "narx": "цена", "to'plam": "комплект", "holati": "состояние",
    "yangi": "новый", "ishlatilgan": "б/у", "brend": "бренд", "seriya": "серия", "hajmi": "объём",
    "xotira": "память", "chastotasi": "частота", "rangi": "цвет",
}
_UZ_WORD = re.compile(r"(?<![\w'’ʻ])(" + "|".join(re.escape(w) for w in UZ_WORDS) + r")(?![\w'’ʻ])", re.IGNORECASE)
CONDITION_KEYS = ("состояние", "holati", "holat", "condition")
CONDITION_VALUES = (("восстан", "refurb", "tiklangan"), "refurbished"), (("б/у", "b/u", "бу", "used", "ishlatilgan"), "used"), \
    (("нов", "new", "yangi"), "new")


def _strip_symbols(text: str) -> str:
    """Emojis, flags and other pictographs out; letters, digits, punctuation and "$" stay."""
    return "".join(
        ch for ch in text
        if unicodedata.category(ch) not in ("So", "Sk", "Cs", "Co", "Cf", "Mn") or ch in "'’ʻ"
    )


def _has_phone(line: str) -> bool:
    """+998 90 123 45 67, 90-123-45-67: a plus sign or 9+ digits (a price has fewer: 12 500 000)."""
    return any(m[0].startswith("+") or sum(ch.isdigit() for ch in m[0]) >= 9 for m in _PHONE_PART.finditer(line))


def uz_to_ru(text: str) -> str:
    text = re.sub(r"[’ʻ`]", "'", text)
    return _UZ_WORD.sub(lambda m: UZ_WORDS[m[1].lower()], text)


def _amount(text: str, sums: bool = False) -> float | None:
    if sums and _DOTTED_THOUSANDS.match(text):
        text = re.sub(r"[.,]", "", text)
    text = re.sub(r"[   ]", "", text).replace(",", ".")
    if text.count(".") > 1:
        text = text.replace(".", "")
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value > 0 else None


def find_price(line: str, default_currency: str) -> tuple[float | None, str | None, bool, str]:
    """(price, currency, check currency?, line without the price). "1.2 млн" = 1 200 000, "950.000 сум" = 950 000."""
    matches = list(_PRICE.finditer(line))
    if matches:
        m = matches[-1]
        currency = "USD" if m["n1"] or m["usd"] else "UZS"
        value = _amount(m["n1"] or m["n2"], sums=bool(m["uzs"]))
        if value is None:
            return None, None, False, line
        if m["mln"]:
            value *= 1_000_000
        elif m["thousand"]:
            value *= 1_000
        return round(value, 2), currency, False, line[: m.start()] + line[m.end():]
    bare = _BARE_PRICE.search(line)
    if bare:
        # No currency in the line: the one chosen above the text field, and the seller is asked to check it
        value = _amount(bare["num"], sums=default_currency == "UZS")
        return value, default_currency, True, line[: bare.start()]
    return None, None, False, line


def _clean_name(text: str) -> str:
    text = _BULLET.sub("", text)
    return _TAIL.sub("", re.sub(r"\s+", " ", text)).strip()


def _is_ad(line: str) -> bool:
    low = line.lower()
    return _has_phone(line) or any(w in low for w in AD_WORDS)


def clean_lines(text: str) -> list[str]:
    """Post lines without emojis, hashtags, adverts and contacts. Blank lines are kept: they end an advert block."""
    result, in_ad = [], False
    for raw in unicodedata.normalize("NFC", text).splitlines():
        line = re.sub(r"\s+", " ", _HASHTAG.sub(" ", _strip_symbols(raw))).strip()
        if not line:
            in_ad = False
            result.append("")
        elif _is_ad(line):
            in_ad = True
        elif not (in_ad and _BULLET.match(line)):
            in_ad = False
            result.append(line)
    return result


def _key_value(line: str) -> tuple[str, str] | None:
    m = _KEY_VALUE.match(_BULLET.sub("", line))
    return (m["key"].strip(), m["value"].strip()) if m else None


def _prices(lines: list[str], default_currency: str) -> list[tuple[float, str, bool, int]]:
    found = []
    for i, line in enumerate(lines):
        price, currency, check, _ = find_price(line, default_currency)
        if price is not None:
            found.append((price, currency, check, i))
    return found


def is_card_post(lines: list[str], default_currency: str) -> bool:
    """One product on many lines: 2+ "Key: value" lines and one price (a bilingual post repeats the same price).
    A list has a price on almost every line, and different ones."""
    specs = [line for line in lines if _key_value(line) and not find_price(line, default_currency)[0]]
    prices = {(p, c) for p, c, _, _ in _prices(lines, default_currency)}
    return len(specs) >= 2 and len(prices) == 1


def _condition(value: str) -> str | None:
    low = uz_to_ru(value).lower()
    for words, condition in CONDITION_VALUES:
        if any(w in low for w in words):
            return condition
    return None


def card_row(lines: list[str], default_currency: str) -> CleanRow | None:
    """The whole post is one product: the title is its name, "Key: value" lines are its characteristics.

    A bilingual post says everything twice: if there are Russian keys, the Uzbek (Latin) duplicates are dropped.
    Price and condition are read by code; the AI gets the title and the characteristics.
    """
    price, currency, check, price_line = _prices(lines, default_currency)[0]
    pairs = [(i, kv) for i, line in enumerate(lines) if i != price_line and (kv := _key_value(line))]
    title = next((_clean_name(line) for i, line in enumerate(lines)
                  if line and i != price_line and not _key_value(line) and re.search(r"[^\W\d_]", line)), "")
    if not title:
        return None
    has_russian = any(re.search("[а-яё]", key.lower()) for _, (key, _) in pairs)
    specs, condition = [], None
    for i, (key, value) in pairs:
        if key.lower() in PRICE_WORDS or find_price(lines[i], default_currency)[0] is not None:
            continue
        if key.lower() in CONDITION_KEYS:
            condition = condition or _condition(value)
        if has_russian and not re.search("[а-яё]", key.lower()):
            continue  # the Uzbek copy of a Russian line
        specs.append(uz_to_ru(f"{key}: {_TAIL.sub('', value)}"))
    title = uz_to_ru(title)
    cells = [title, *specs]
    return CleanRow(
        row=1, sheet="", section="", cells=cells, name=title, price=price, is_in_stock=True,
        ai_text=" | ".join(cells), currency=currency, currency_check=check, condition=condition,
    )


def list_rows(lines: list[str], default_currency: str) -> list[CleanRow]:
    rows: list[CleanRow] = []
    waiting_name = ""  # "i5 12400f" on one line and "Цена: 110$" on the next
    for line in lines:
        line = uz_to_ru(line)
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


def text_to_rows(text: str, default_currency: str) -> list[CleanRow]:
    lines = clean_lines(text)
    if is_card_post(lines, default_currency):
        row = card_row(lines, default_currency)
        return [row] if row else []
    return list_rows(lines, default_currency)
