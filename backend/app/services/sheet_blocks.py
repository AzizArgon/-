"""Sheets with several "name | price" tables side by side (Gshop): split into vertical blocks.

Each block has its own section headers ("ПРОЦЕССОРЫ INTEL", sometimes two levels: "ПЕРИФЕРИЯ JBL" -> "НАУШНИКИ"),
so sections are followed in every block apart. Shop notices ("Оплата ... в национальной валюте!!!") are not goods.
"""

import re
from dataclasses import dataclass

_NOTICE = re.compile(r"оплат|валют|курс|цены указаны|!!!", re.IGNORECASE)
_HEADER_WORDS = re.compile(r"^(наименование|название|товар|цена|price|name)$", re.IGNORECASE)
_ONLY_IN_BUILDS = re.compile(r"\s*\(\s*только в сборках\s*\)", re.IGNORECASE)
MIN_PRICE_SHARE = 0.3  # a price column: at least 30% of its filled cells are numbers


@dataclass
class BlockItem:
    block: int
    row: int
    section: str | None
    name: str
    price: float | None
    note: str | None = None  # "only_in_builds": the price holds only inside a PC build


def _text(value) -> str:
    return re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip() if value is not None else ""


def _number(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = _text(value).replace(" ", "").replace(",", ".")
    return float(text) if re.fullmatch(r"\d+(\.\d+)?", text) else None


def find_blocks(rows: list[list]) -> list[tuple[int, int]]:
    """(name column, price column) pairs. Price columns hold mostly numbers; the name is the column to the left."""
    width = max((len(r) for r in rows), default=0)
    pairs = []
    for col in range(1, width):
        filled = [r[col] for r in rows if col < len(r) and _text(r[col])]
        names = [r[col - 1] for r in rows if _text(r[col - 1]) and _number(r[col - 1]) is None]
        numbers = sum(1 for v in filled if _number(v) is not None)
        if filled and numbers / len(filled) >= MIN_PRICE_SHARE and len(names) >= numbers:
            if not pairs or pairs[-1][1] != col - 1:
                pairs.append((col - 1, col))
    return pairs


def _is_section(name: str) -> bool:
    # Headers are written in capitals and have no price: "ПРОЦЕССОРЫ INTEL", "LG", "STREAM DECK", "TOSHIBA 3TB".
    # A capitalised item without a price has a model code among several words: "MSI PRO B660M-E LGA 1700 DDR4"
    words = name.split()
    has_code = any(re.search(r"\d", w) and re.search(r"[A-ZА-ЯЁ]", w) for w in words)
    return (len(name) <= 60 and not re.search(r"[a-zа-яё]", name) and re.search(r"[A-ZА-ЯЁ]", name) is not None
            and not (has_code and len(words) >= 3))


def block_items(rows: list[list]) -> tuple[list[BlockItem], list[str]]:
    """Goods of all blocks (top to bottom, block by block) and shop notices found on the sheet."""
    items, notices = [], []
    for b, (name_col, price_col) in enumerate(find_blocks(rows)):
        section, prev_header = None, None
        for i, row in enumerate(rows):
            name = _text(row[name_col]) if name_col < len(row) else ""
            price = _number(row[price_col]) if price_col < len(row) else None
            if not name or _HEADER_WORDS.match(name):
                prev_header = None
                continue
            if price is None and _NOTICE.search(name):
                notices.append(name)
                continue
            if price is None and _is_section(name):
                # Two headers in a row: brand -> type ("ПЕРИФЕРИЯ JBL" / "НАУШНИКИ")
                section = f"{prev_header} / {name}" if prev_header else name
                prev_header = name if not prev_header else prev_header
                continue
            prev_header = None
            note = "only_in_builds" if _ONLY_IN_BUILDS.search(name) else None
            items.append(BlockItem(b, i, section, _ONLY_IN_BUILDS.sub("", name).strip(), price, note))
    return items, list(dict.fromkeys(notices))
