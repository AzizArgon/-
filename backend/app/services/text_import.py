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
Code removes emojis, hashtags, Telegram service lines and advert lines (delivery, contacts, @username), decides the
kind of the post and reads price, currency and condition itself; the AI later sees only the product words, as with
files. Several forwarded posts pasted at once ("[25.10.2026 17:58] Имя:" before each) are split and read one by one.
"""

import re
import unicodedata

from app.services.price_cleaner import CleanRow
from app.services.spec_normalizer import BRAND_CASE

NUM = r"(\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d{1,3}(?:[.,]\d{3}){2,}|\d+(?:[.,]\d+)?)"
SUM = r"(?:сум|сўм|so['’ʻ`]?m|sum)"
# The last match in a line is its price ("ЦЕНА:120У.Е. 115У.Е." = old -> new). Marked currencies win
_PRICE = re.compile(
    rf"\$\s*(?P<n1>{NUM})"
    rf"|(?P<n2>{NUM})\s*(?:(?P<usd>\$|у\.?\s?е\.?|y\.?\s?e\.?(?![a-z])|usd\b|долл\w*|dollar\w*|бакс\w*)"
    rf"|(?P<mln>млн|mln\b|million\w*|миллион\w*)\.?(?:\s*{SUM}\b)?"
    rf"|(?P<thousand>тыс\w*|минг\b|ming\b)\.?(?:\s*{SUM}\b)?"
    rf"|(?P<uzs>сум\w*|сўм|so['’ʻ`]?m\b|sum\b|uzs\b))",
    re.IGNORECASE,
)
# A number without a currency is a price only after a separator at the end ("i5 12400f — 110") or after the word
# "Цена" ("Цена 140.000"); "ddr4-3200", "6pin", "192-bit", "68-69°" are not prices
_BARE_PRICE = re.compile(rf"(?:\s[-=]|[—–:])\s*(?P<num>{NUM})\s*$")
_WORD_PRICE = re.compile(rf"(?:^|\s)(?:цена|цены|price|narxi|narx|нархи|нарх)\s*:?\s*(?P<num>{NUM})\s*$", re.IGNORECASE)
# No currency written: sums are big numbers, dollars small ones; the seller is asked to check
UZS_FROM = 10_000
# "950.000" / "1,250,000" in sums: the dot or comma separates thousands (sums have no fractions)
_DOTTED_THOUSANDS = re.compile(r"^\d{1,3}(?:[.,]\d{3})+$")
_PHONE_PART = re.compile(r"\+?\d[\d \-()]{7,}\d")
_HASHTAG = re.compile(r"#\w+")
_BULLET = re.compile(r"^[\s\-–—•*·▪►→>]+")
_TAIL = re.compile(r"[\s\-–—:=,;|/.]+$")
# "Ключ: значение" of a card post: a short key without digits ("XMP профиль", "Holati")
_KEY_VALUE = re.compile(r"^(?P<key>[^\W\d_][^:\d]{0,28}):\s*(?P<value>\S.*)$")
# Telegram copies: a header "[25.10.2026 17:58] Имя:" before every message, "Переслано из ...", "[ 3 фото ]"
_TG_HEADER = re.compile(r"^\[\d{1,2}\.\d{1,2}\.\d{2,4},? \d{1,2}:\d{2}(?::\d{2})?\][^\n:]*:", re.MULTILINE)
_SERVICE = re.compile(
    r"^(?:переслано из|forwarded from|пересланное сообщение)\b"
    r"|^\[\s*(?:\d+\s+)?(?:фото|фотографи\w*|видео|файл\w*|стикер|photos?|videos?|sticker|gif|альбом)\s*\]$",
    re.IGNORECASE,
)
# Lines that are about the shop, not a product, even if they have a number. A header ("Доставка:") also hides
# the bullet lines under it ("• По Фергане — Такси")
AD_WORDS = (
    "поступлени", "доставк", "звоните", "звонит", "телефон", "тел.", "тел:", "адрес", "ориентир", "пишите",
    "заказ", "гарантия", "t.me", "http", "@", "instagram", "telegram", "скидк", "акция", "купить", "самовывоз",
    "manzil", "aloqa", "yetkazib", "sotib olish", "buyurtma", "murojaat", "chegirma",
    "гарант", "рассрочк", "админ", "uzum", "kafolat", "muddatli", "nasiya", "kanal", "канал", "подпис",
)
WARRANTY_WORDS = ("гарантия", "гарант", "kafolat")
# A second price for some buyers ("Подписчикам 13$", "Опт: 100$"): a note to the main price, not a product
DISCOUNT_WORDS = ("подписчик", "obunachi", "скидк", "chegirma", "опт", "ulgurji", "для своих", "при покупке")
NOT_DISCOUNT = ("доставк", "yetkazib", "самовывоз", "такси")
CURRENCY_WORDS = {"сум", "сўм", "so'm", "som", "sum", "uzs", "usd", "долл", "доллар", "долларов", "уе", "ye"}
HASHTAG_CATEGORIES = {
    "ram": "ram", "озу": "ram", "оперативка": "ram", "ddr4": "ram", "ddr5": "ram", "gpu": "gpu", "видеокарта": "gpu",
    "cpu": "cpu", "процессор": "cpu", "ssd": "ssd", "hdd": "hdd", "monitor": "monitor", "монитор": "monitor",
    "psu": "psu", "motherboard": "motherboard", "материнка": "motherboard", "laptop": "laptop", "ноутбук": "laptop",
}
# "3 tb Hitachi": a drive in terabytes of a hard disk maker is an HDD
_HDD_HINT = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:tb|тб)\b.*\b(hitachi|hgst|seagate|toshiba|wd|western digital)\b"
                       r"|\b(hitachi|hgst|seagate|toshiba|wd|western digital)\b.*\b\d+(?:[.,]\d+)?\s*(?:tb|тб)\b"
                       r"|\b(?:hdd|винт|жёсткий|жесткий)\b", re.IGNORECASE)
PRICE_WORDS = {"цена", "цены", "price", "narxi", "narx", "нарх", "нархи", "розница", "розн", "chakana"}
# Uzbek words of posts (Latin and Cyrillic) -> the Russian ones the rules and the AI prompt know
UZ_WORDS = {
    "b/u": "б/у", "narxi": "цена", "narx": "цена", "to'plam": "комплект", "holati": "состояние",
    "yangi": "новый", "ishlatilgan": "б/у", "brend": "бренд", "seriya": "серия", "hajmi": "объём",
    "xotira": "память", "chastotasi": "частота", "rangi": "цвет", "sotiladi": "продаётся",
    "нархи": "цена", "нарх": "цена", "ҳолати": "состояние", "холати": "состояние", "янги": "новый",
    "ишлатилган": "б/у", "сотилади": "продаётся", "хотира": "память",
}
_UZ_WORD = re.compile(r"(?<![\w'’ʻ])(" + "|".join(re.escape(w) for w in UZ_WORDS) + r")(?![\w'’ʻ])", re.IGNORECASE)
# Condition only from explicit words (checked in this order); "обслужена", "не шумит", "Holati zor" say nothing
CONDITION_WORDS = (
    ("refurbished", re.compile(r"восстановлен|refurb|tiklangan", re.IGNORECASE)),
    ("used", re.compile(r"(?<![\w/])(?:б/у|б\.у\.?|бу|used|ishlatilgan)(?![\w/])", re.IGNORECASE)),
    ("new_openbox", re.compile(r"open\s?-?box|вскрыт|ochilgan", re.IGNORECASE)),
    ("new", re.compile(r"(?<![\w])(?:нов(?:ый|ая|ое|ые|ую|ого|ой|\.)|new|yangi)(?![\w])|в\s+пл[её]нке|запечатан"
                       r"|muhrlangan|sealed", re.IGNORECASE)),
)
_LIKE_NEW = re.compile(r"(?:как|почти|словно|практически)\s+(?:нов\w*|new)", re.IGNORECASE)
# "Пизже i5-12400f", "лучше чем 3060": another model is compared, it is not a second product
_COMPARISON = re.compile(r"(?<!\w)(?:лучше|пизже|круче|быстрее|мощнее|уделывает|не хуже|аналог|vs\.?|versus"
                         r"|dan yaxshi|kuchliroq)(?!\w)", re.IGNORECASE)
# A model: a word with digits that is not only a size/unit ("16гб", "100 ват", "6pin") or a short number
_SPEC_TOKEN = re.compile(r"^\d+(?:[.,]\d+)?(?:gb|гб|tb|тб|mb|мб|mhz|мгц|ghz|ггц|w|вт|ват|hz|гц|mm|мм|pin|bit|бит|шт"
                         r"|ядер|ядра|потоков|дюйм\w*|\"|см|cm|м|m|%|°)$", re.IGNORECASE)
_EXTRA_BRANDS = {"hitachi", "hgst", "seagate", "wd", "axle", "peladin", "arktek", "afox", "biostar", "asrock",
                 "teamgroup", "t-force", "hyperx", "logitech", "razer", "a4tech", "cougar", "zalman", "sven", "gmoc"}


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
    text = re.sub(r"[   ]", "", text).replace(",", ".")
    if text.count(".") > 1:
        text = text.replace(".", "")
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value > 0 else None


def find_price(line: str) -> tuple[float | None, str | None, bool, str]:
    """(price, currency, check currency?, line without the price). "1.2 млн" = 1 200 000, "950.000 сум" = 950 000.

    Without a currency: 10 000 and more = sums, less = dollars ("Цена 140.000" -> 140 000 сум), to be checked."""
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
    bare = _BARE_PRICE.search(line) or _WORD_PRICE.search(line)
    if bare:
        value = _amount(bare["num"], sums=True)
        if value is None:
            return None, None, False, line
        return value, "UZS" if value >= UZS_FROM else "USD", True, line[: bare.start("num")]
    return None, None, False, line


def _clean_name(text: str) -> str:
    text = _BULLET.sub("", text)
    return _TAIL.sub("", re.sub(r"\s+", " ", text)).strip()


def _is_discount(line: str) -> bool:
    low = line.lower()
    return (any(w in low for w in DISCOUNT_WORDS) and not any(w in low for w in NOT_DISCOUNT)
            and find_price(line)[0] is not None)


def _is_ad(line: str) -> bool:
    low = line.lower()
    return _has_phone(line) or any(w in low for w in AD_WORDS)


def _only_warranty(line: str) -> bool:
    """The only advert words of the line are about the warranty ("новая, гарантия 1 год")."""
    low = line.lower()
    return not _has_phone(line) and not any(w in low for w in AD_WORDS if w not in WARRANTY_WORDS)


def split_posts(text: str) -> list[str]:
    """Several forwarded posts pasted at once: one text per Telegram header; without headers the text as is."""
    starts = [m.start() for m in _TG_HEADER.finditer(text)]
    if not starts:
        return [text]
    parts = [text[a:b] for a, b in zip([0, *starts], [*starts, len(text)])]
    return [_TG_HEADER.sub("", p, count=1) for p in parts if p.strip()]


def clean_lines(text: str) -> list[str]:
    """Post lines without emojis, hashtags, service lines, adverts and contacts. Blank lines are kept: they end an
    advert block. A discount price ("Подписчикам 13$") stays: it becomes a note to the main price."""
    result, in_ad = [], False
    for raw in unicodedata.normalize("NFC", _TG_HEADER.sub("", text)).splitlines():
        line = re.sub(r"\s+", " ", _HASHTAG.sub(" ", _strip_symbols(raw))).strip()
        if not line:
            in_ad = False
            result.append("")
        elif _SERVICE.search(line):
            continue
        elif _is_discount(line) and not _has_phone(line):
            result.append(line)
        elif _only_warranty(line) and condition_of(line) != "unknown":
            result.append(line)  # "Состояние: новая, гарантия 1 год" says the condition, it is not an advert
        elif _is_ad(line):
            in_ad = True
        elif not (in_ad and _BULLET.match(line)):
            in_ad = False
            result.append(line)
    return result


def _key_value(line: str) -> tuple[str, str] | None:
    m = _KEY_VALUE.match(_BULLET.sub("", line))
    return (m["key"].strip(), m["value"].strip()) if m else None


def _prices(lines: list[str]) -> list[tuple[float, str, bool, int]]:
    found = []
    for i, line in enumerate(lines):
        price, currency, check, _ = find_price(line)
        if price is not None:
            found.append((price, currency, check, i))
    return found


def _is_named(rest: str) -> bool:
    """What is left of a price line names a product ("i5 12400f б/у —"), not just "Цена:" / "Narxi:"."""
    words = [w for w in re.findall(r"[\w'.]+", uz_to_ru(rest).lower()) if re.search(r"[^\W\d_]", w)]
    return any(w.strip(".") not in PRICE_WORDS and w.replace(".", "") not in CURRENCY_WORDS for w in words)


def is_card_post(lines: list[str]) -> bool:
    """One price in the post = one product, whatever the layout ("Key: value" lines are not required).

    A list names a product on each priced line ("i5 12400f — 110$", "rtx 3060 — 290$"); a card has one price,
    often on its own line ("Цена : 190 У.Е", repeated in Uzbek: "Narxi: ..."), maybe with a discount price."""
    named = [line for line in lines if not _is_discount(line) and find_price(line)[0] is not None
             and _is_named(find_price(line)[3])]
    return bool(_prices(lines)) and len(named) <= 1


def condition_of(text: str) -> str:
    """used / refurbished / new_openbox / new only from explicit words, otherwise "unknown" (the seller is asked)."""
    low = _LIKE_NEW.sub(" ", uz_to_ru(text).lower())
    return next((condition for condition, pattern in CONDITION_WORDS if pattern.search(low)), "unknown")


def has_model(text: str) -> bool:
    """A brand or a model code is named: "Ryzen 5 5600", "3 tb Hitachi". Not: "топовая видюха", "оперативка 16гб"."""
    words = re.findall(r"[\w.\-/\"+]+", text.lower())
    if any(w.strip(".-/") in BRAND_CASE or w.strip(".-/") in _EXTRA_BRANDS for w in words):
        return True
    for w in words:
        w = w.strip(".-/\"")
        if re.search(r"\d", w) and not _SPEC_TOKEN.match(w) and (re.search(r"[^\W\d_]", w) or re.fullmatch(r"\d{3,6}", w)):
            return True
    return False


def _title(lines: list[str], price_line: int) -> str:
    """The product name: the priced line if it names the product, else the first line with a model (letters and
    digits: "Corsair ... 16GB"), else the first line with words."""
    rest = _clean_name(find_price(lines[price_line])[3])
    if _is_named(rest) and not _key_value(lines[price_line]):
        return rest
    texts = [_clean_name(line) for i, line in enumerate(lines)
             if line and i != price_line and not _key_value(line) and re.search(r"[^\W\d_]", line)
             and not _COMPARISON.search(line) and not _is_discount(line)]
    return next((t for t in texts if re.search(r"\d", t)), texts[0] if texts else "")


def card_row(lines: list[str], max_len: int = 1000) -> CleanRow | None:
    """The whole post is one product: the AI gets all of it (title first), code reads price and condition.

    The main price is the regular one (the new one of "120 115"); discount prices and an old price are a note.
    A bilingual post says everything twice: if there are Russian "Key: value" lines, their Uzbek (Latin)
    copies are dropped, so the AI sees one product and the row text is not doubled.
    """
    prices = _prices(lines)
    regular = [p for p in prices if not _is_discount(lines[p[3]])] or prices
    price, currency, check, price_line = regular[0]
    title = _title(lines, price_line)
    if not title:
        return None
    notes = [_clean_name(lines[p[3]]) for p in prices if _is_discount(lines[p[3]])]
    if len(_PRICE.findall(lines[price_line])) > 1:
        notes.insert(0, _clean_name(lines[price_line]))  # "ЦЕНА:120У.Е. 115У.Е.": the old price is kept as said
    pairs = [kv for line in lines if (kv := _key_value(line))]
    has_russian = any(re.search("[а-яё]", key.lower()) for key, _ in pairs)
    cells = [uz_to_ru(title)]
    for line in lines:
        kv = _key_value(line)
        if not line or _clean_name(line) == title or find_price(line)[0] is not None or _COMPARISON.search(line):
            continue
        if kv:
            key, value = kv
            if has_russian and not re.search("[а-яё]", key.lower()):
                continue  # the Uzbek copy of a Russian line
            line = f"{key}: {value}"
        cells.append(uz_to_ru(_TAIL.sub("", _BULLET.sub("", line))))
    text = " | ".join(cells)
    return CleanRow(
        row=1, sheet="", section="", cells=cells, name=cells[0], price=price, is_in_stock=True,
        ai_text=text[:max_len], currency=currency, currency_check=check,
        condition=condition_of(" ".join(line for line in lines if not _COMPARISON.search(line))),
        note="; ".join(notes) or None,
    )


def list_rows(lines: list[str]) -> list[CleanRow]:
    rows: list[CleanRow] = []
    waiting_name = ""  # "i5 12400f" on one line and "Цена: 110$" on the next
    for line in lines:
        line = uz_to_ru(line)
        price, currency, check, rest = find_price(line)
        name = _clean_name(rest)
        if price is not None and _is_discount(line):
            if rows:
                rows[-1].note = "; ".join(filter(None, [rows[-1].note, _clean_name(line)]))
            continue
        if price is None:
            # A line with letters and digits may be a product whose price is on the next line
            waiting_name = name if re.search(r"\d", name) and re.search(r"[^\W\d_]", name) else ""
            continue
        if not name or name.lower().strip(" :") in PRICE_WORDS:
            name, waiting_name = waiting_name, ""
        if not name or not re.search(r"[^\W\d_]", name) or not has_model(name):
            continue
        rows.append(CleanRow(
            row=len(rows) + 1, sheet="", section="", cells=[name], name=name, price=price, is_in_stock=True,
            ai_text=name, currency=currency, currency_check=check, condition=condition_of(line),
        ))
    return rows


def category_hint(text: str) -> str | None:
    """#RAM, #GPU, #видеокарта: the seller's own category tag; "3 tb Hitachi" -> HDD (used when the AI is not sure)."""
    for tag in re.findall(r"#(\w+)", text.lower()):
        if tag in HASHTAG_CATEGORIES:
            return HASHTAG_CATEGORIES[tag]
    return "hdd" if _HDD_HINT.search(text) else None


def _post_rows(text: str) -> list[CleanRow]:
    lines = clean_lines(text)
    if is_card_post(lines):
        row = card_row(lines)
        # A card that names no brand and no model ("Продаю видеокарту, 150$") is not a product card
        words = " ".join(find_price(line)[3] for line in lines if not _COMPARISON.search(line))
        rows = [row] if row and has_model(words) else []
    else:
        rows = list_rows(lines)
    hint = category_hint(text)
    for row in rows:
        row.category_hint = hint
    return rows


def text_to_rows(text: str) -> list[CleanRow]:
    rows = [row for post in split_posts(text) for row in _post_rows(post)]
    for i, row in enumerate(rows, 1):
        row.row = i
    return rows


def no_rows_reason(text: str) -> str:
    """Why nothing was found: no product named at all ("топовая видюха, пишите в лс") or no price."""
    lines = [line for post in split_posts(text) for line in clean_lines(post)]
    return "no_prices" if has_model(" ".join(find_price(line)[3] for line in lines)) else "no_model"
