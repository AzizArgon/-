"""Step 2 of the import pipeline: deterministic cleanup of the Markdown made by markitdown.

What it does before anything is sent to the AI:
- skips duplicate sheets (e.g. "Export");
- drops NaN / "Unnamed: N" placeholders and empty rows;
- turns subheader rows ("DDR", "Блоки питания", table headers) into section markers;
- truncates the long "характеристики" column and any overly long cell;
- takes price, article and stock straight from the table columns (the AI never sees them).
"""

import re
from dataclasses import dataclass, field

SKIP_SHEETS = {"export"}
HEADER_WORDS = (
    "опт", "цена", "розница", "наименование", "характеристик", "коробка", "артикул", "наличие",
    "price", "name",
)
# Column roles detected from header rows; the first matching keyword wins
COLUMN_ROLES = {
    "price": ("цена", "опт", "розн", "стоимость", "price"),
    "name": ("наименование", "название", "товар", "name"),
    "article": ("артикул", "код", "part", "sku"),
    "specs": ("характеристик",),
    "stock": ("наличие", "склад", "остаток", "stock"),
    "index": ("#", "№"),
}
OUT_OF_STOCK_WORDS = ("нет", "под заказ", "ожида", "0")
SPECS_MAX_LEN = 120
CELL_MAX_LEN = 200
ARTICLE_MAX_WORDS = 5

_EMPTY_CELL = re.compile(r"^(nan|none|unnamed: ?\d+|-+|:?-{3,}:?)$", re.IGNORECASE)
_NUMBER = re.compile(r"^\$?\d[\d\s.,]*(\$|сум|sum|у\.?е\.?)?$", re.IGNORECASE)
_THOUSANDS = re.compile(r"^\d{1,3}(,\d{3})+$")
_CYRILLIC = re.compile(r"[а-яё]", re.IGNORECASE)


@dataclass
class CleanRow:
    row: int  # sequential id, used to map AI answers back to rows
    sheet: str
    section: str
    cells: list[str] = field(default_factory=list)
    name: str = ""  # product name cell
    article: str | None = None  # manufacturer part number / model code cell
    price: float | None = None
    is_in_stock: bool = False
    ai_text: str = ""  # what the AI gets: name and other text cells, no price/specs/stock
    # Pasted text only: every line has its own currency; True = none was written, the default one was taken
    currency: str | None = None
    currency_check: bool = False
    condition: str | None = None  # a card post with "Состояние: Б/У": read by code, wins over the AI
    category_hint: str | None = None  # a post tag (#RAM): taken when the AI could not tell the category

    @property
    def raw_name(self) -> str:
        # Text without price-like cells: stays the same when only the price changes
        return " | ".join(c for c in self.cells if not _NUMBER.match(c))


def parse_price(text: str) -> float | None:
    """'1 250 000', '61.0', '35,', '$120', '1,250,000', '12,5' -> float; anything else -> None."""
    if not text or not _NUMBER.match(text):
        return None
    t = re.sub(r"[^\d.,]", "", text).rstrip(".,")
    if "," in t and "." in t:
        t = t.replace(",", "")
    elif _THOUSANDS.match(t):
        t = t.replace(",", "")
    else:
        t = t.replace(",", ".")
    try:
        value = float(t)
    except ValueError:
        return None
    return value if value > 0 else None


def _clean_cell(cell: str) -> str:
    cell = cell.replace("\\n", " ").replace("\\*", "*").replace("\\_", "_")
    cell = re.sub(r"\s+", " ", cell).strip()
    return "" if _EMPTY_CELL.match(cell) else cell


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _is_header_row(cells: list[str]) -> bool:
    """A table header or a subheader like "DDR" / "Блоки питания": sets the category, not a product."""
    filled = [c for c in cells if c]
    if not filled:
        return False
    if any(c.lower().startswith(HEADER_WORDS) for c in filled):
        return True
    # A lone cell without digits ("DDR", "Блоки питания") is a subheader;
    # with digits ("ID Cooling SE-224-XTS") it is a product without a price
    return len(filled) == 1 and not any(ch.isdigit() for ch in filled[0])


def _section_name(cells: list[str]) -> str:
    filled = [c for c in cells if c.strip("#№ ") and not _NUMBER.match(c) and not c.lower().startswith(HEADER_WORDS)]
    return filled[0] if filled else ""


def _column_roles(cells: list[str]) -> dict[int, str]:
    roles: dict[int, str] = {}
    for i, cell in enumerate(cells):
        low = cell.lower()
        for role, words in COLUMN_ROLES.items():
            if low.startswith(words) or (role != "index" and any(w in low for w in words)):
                if role == "price":
                    # Several price columns are kept: wholesale ("опт") is preferred over retail
                    roles[i] = "price_wholesale" if "опт" in low else "price"
                elif role not in roles.values():
                    roles[i] = role
                break
    return roles


def _extract_fields(row: CleanRow, cells: list[str], roles: dict[int, str]) -> None:
    by_role = {role: i for i, role in roles.items()}
    skip = {i for i, role in roles.items() if role in ("specs", "stock", "index", "price", "price_wholesale")}
    texts = [(i, c) for i, c in enumerate(cells) if c and i not in skip and not _NUMBER.match(c)]
    price_cols = [i for i, r in roles.items() if r == "price_wholesale"] + [i for i, r in roles.items() if r == "price"]

    if price_cols:
        # The first filled price column wins: wholesale if there is one, otherwise retail.
        # Numbers in columns without a price header (barcodes, notes) are never guessed as prices
        prices = (parse_price(cells[i]) for i in price_cols if i < len(cells))
        row.price = next((p for p in prices if p is not None), None)
    else:
        # No header: the last number in the row (not the first cell, which may be a row number)
        numbers = [c for i, c in enumerate(cells) if i > 0 and c and _NUMBER.match(c)]
        row.price = parse_price(numbers[-1]) if numbers else None

    name_i = by_role.get("name")
    if name_i is None or not cells[name_i]:
        name_i = max(texts, key=lambda t: len(t[1]))[0] if texts else None
    row.name = cells[name_i] if name_i is not None else ""
    row.ai_text = " | ".join([row.name] + [c for i, c in texts if i != name_i]) if row.name else ""

    article_i = by_role.get("article")
    if article_i is None:
        # A part number is short, Latin and has digits ("i3-12100F"); brands and types are not
        short = [
            i for i, c in texts
            if i != name_i and len(c.split()) <= ARTICLE_MAX_WORDS
            and any(ch.isdigit() for ch in c) and not _CYRILLIC.search(c)
        ]
        article_i = short[0] if short else None
    row.article = cells[article_i] or None if article_i is not None and article_i != name_i else None

    # An explicit stock column wins; otherwise "no price in the file" means "out of stock"
    stock = cells[by_role["stock"]].lower() if "stock" in by_role else ""
    row.is_in_stock = row.price is not None and not (stock and stock.startswith(OUT_OF_STOCK_WORDS))


def clean_markdown(md: str) -> list[CleanRow]:
    rows: list[CleanRow] = []
    sheet, section = "", ""
    skip_sheet = False
    roles: dict[int, str] = {}

    for line in md.splitlines():
        line = line.strip()
        if line.startswith("## "):
            sheet = line[3:].strip()
            section = ""
            skip_sheet = sheet.lower() in SKIP_SHEETS
            roles = {}
            continue
        if skip_sheet or not line or set(line) <= set("|-: "):
            continue

        raw_cells = line.strip("|").split("|") if line.startswith("|") else [line.lstrip("#").strip()]
        cells = [_clean_cell(c) for c in raw_cells]
        if not any(cells):
            continue

        if _is_header_row(cells):
            # Remember which column holds what, so values can be taken by code
            found = _column_roles(cells)
            if found:
                roles = found
            name = _section_name(cells)
            if name:
                section = name
            continue

        specs_cols = {i for i, role in roles.items() if role == "specs"}
        cells = [
            _truncate(c, SPECS_MAX_LEN if i in specs_cols else CELL_MAX_LEN)
            for i, c in enumerate(cells)
        ]
        row = CleanRow(row=len(rows) + 1, sheet=sheet, section=section, cells=[c for c in cells if c])
        _extract_fields(row, cells, roles)
        if row.name:
            rows.append(row)
    return rows



def cache_key(text: str) -> str:
    """Normalized name used as the parse cache key: case, spaces and punctuation ignored."""
    return " ".join(re.findall(r"[a-zа-яё0-9]+", text.lower()))
