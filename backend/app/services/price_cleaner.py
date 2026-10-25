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
    "price", "name", "раздел", "примечание", "бренд", "производитель",
)
# Column roles detected from header rows; the first matching keyword wins
COLUMN_ROLES = {
    "price": ("цена", "опт", "розн", "стоимость", "price"),
    "name": ("наименование", "название", "товар", "name"),
    "article": ("артикул", "код", "part", "sku"),
    "brand": ("бренд", "производитель", "brand", "vendor"),
    "specs": ("характеристик",),
    "stock": ("наличие", "склад", "остаток", "stock"),
    "index": ("#", "№"),
    "section": ("раздел",),
    "note": ("примечание", "комментарий"),
}
OUT_OF_STOCK_WORDS = ("нет", "под заказ", "ожида", "0")
SPECS_MAX_LEN = 120
CELL_MAX_LEN = 200
ARTICLE_MAX_WORDS = 5

_EMPTY_CELL = re.compile(r"^(nan|none|unnamed: ?\d+|-+|:?-{3,}:?)$", re.IGNORECASE)
_CURRENCY = r"\$|сум|сўм|sum|so['’ʻ]?m|uzs|usd|у\.?\s?е\.?|y\.?\s?e\.?"
_NUMBER = re.compile(rf"^\$?\s?\d[\d\s.,]*\s?({_CURRENCY})?$", re.IGNORECASE)
_THOUSANDS = re.compile(r"^\d{1,3}(,\d{3})+$")
_DOT_THOUSANDS = re.compile(r"^\d{1,3}(\.\d{3})+$")
_USD_MARK = re.compile(r"\$|usd|у\.?\s?е|y\.?\s?e", re.IGNORECASE)
_UZS_MARK = re.compile(r"сум|сўм|sum|so['’ʻ]?m|uzs", re.IGNORECASE)
# A shop remark in the name: the price holds only in a PC build. Kept as a note, not a part of the model
_ONLY_IN_BUILDS = re.compile(r"\s*\(\s*только в сборках?\s*\)", re.IGNORECASE)
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
    note: str | None = None  # the seller's words next to the price: "Подписчикам 13$", "(только в сборках)"

    @property
    def raw_name(self) -> str:
        # Text without price-like cells: stays the same when only the price changes
        return " | ".join(c for c in self.cells if not _NUMBER.match(c))


def parse_price(text: str) -> float | None:
    """'1 250 000', '61.0', '35,', '$120', '1,250,000', '12,5', '1.250.000 сум', '110,00' -> float; else None."""
    if not text or not _NUMBER.match(text):
        return None
    t = re.sub(r"[^\d.,]", "", text).rstrip(".,")
    if "," in t and "." in t:
        t = t.replace(",", "")
    elif _THOUSANDS.match(t) or t.count(".") > 1 or (_DOT_THOUSANDS.match(t) and _UZS_MARK.search(text)):
        t = t.replace(",", "").replace(".", "")  # sums have no fractions: "1.250.000", "140.000 сум"
    else:
        t = t.replace(",", ".")
    try:
        value = float(t)
    except ValueError:
        return None
    return value if value > 0 else None


def price_currency(text: str) -> str | None:
    """The currency written next to the price: "110$", "110 у.е." -> USD, "1 250 000 сум" -> UZS."""
    return "USD" if _USD_MARK.search(text or "") else "UZS" if _UZS_MARK.search(text or "") else None


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
    skip = {i for i, role in roles.items()
            if role in ("specs", "stock", "index", "price", "price_wholesale", "section", "note", "brand")}
    texts = [(i, c) for i, c in enumerate(cells) if c and i not in skip and not _NUMBER.match(c)]
    price_cols = [i for i, r in roles.items() if r == "price_wholesale"] + [i for i, r in roles.items() if r == "price"]

    if price_cols:
        # The first filled price column wins: wholesale if there is one, otherwise retail.
        # Numbers in columns without a price header (barcodes, notes) are never guessed as prices
        price_cell = next((cells[i] for i in price_cols if i < len(cells) and parse_price(cells[i]) is not None), None)
    else:
        # No header: the last number in the row (not the first cell, which may be a row number)
        numbers = [c for i, c in enumerate(cells) if i > 0 and c and _NUMBER.match(c)]
        price_cell = numbers[-1] if numbers else None
    row.price = parse_price(price_cell) if price_cell else None
    # "110$" / "1 250 000 сум" in the cell: the currency of this row; nothing written = the import's currency
    row.currency = price_currency(price_cell) if row.price is not None else None
    for role, attr in (("section", "section"), ("note", "note")):
        i = by_role.get(role)
        if i is not None and i < len(cells) and cells[i]:
            setattr(row, attr, cells[i])

    name_i = by_role.get("name")
    if name_i is None or not cells[name_i]:
        name_i = max(texts, key=lambda t: len(t[1]))[0] if texts else None
    row.name = cells[name_i] if name_i is not None else ""
    brand_i = by_role.get("brand")
    brand = cells[brand_i] if brand_i is not None and brand_i < len(cells) else ""
    if row.name and brand and brand.lower() not in row.name.lower():
        row.name = f"{brand} {row.name}"  # a "Бренд" column: "Kingston" + "DDR4 16GB 3200MHz"
    if _ONLY_IN_BUILDS.search(row.name):
        row.name, row.note = _ONLY_IN_BUILDS.sub("", row.name).strip(), row.note or "только в сборках"
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


def _price_at_line_end(row: CleanRow) -> None:
    """A text line, not a table (a PDF without a grid): "MB ASUS B850M DDR5 158$" -> the price is at the end."""
    from app.services.text_import import find_price  # text_import builds on this module

    price, currency, check, rest = find_price(row.cells[0])
    name = rest.strip(" -–—:|")
    if price is not None and name:
        row.cells, row.name, row.ai_text = [name], name, name
        row.price, row.currency, row.currency_check, row.is_in_stock = price, currency, check, True


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
        if not line.startswith("|") and row.price is None:
            _price_at_line_end(row)
        if row.name:
            rows.append(row)
    return rows



def cache_key(text: str) -> str:
    """Normalized name used as the parse cache key: case, spaces and punctuation ignored."""
    return " ".join(re.findall(r"[a-zа-яё0-9]+", text.lower()))
