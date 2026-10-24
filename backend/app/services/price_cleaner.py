"""Step 2 of the import pipeline: deterministic cleanup of the Markdown made by markitdown.

What it does before anything is sent to the AI:
- skips duplicate sheets (e.g. "Export");
- drops NaN / "Unnamed: N" placeholders and empty rows;
- turns subheader rows ("DDR", "Блоки питания", table headers) into section markers;
- truncates the long "характеристики" column and any overly long cell.
"""

import re
from dataclasses import dataclass, field

SKIP_SHEETS = {"export"}
HEADER_WORDS = ("опт", "цена", "розница", "наименование", "характеристик", "коробка", "price", "name")
SPECS_HEADER = "характеристик"
SPECS_MAX_LEN = 120
CELL_MAX_LEN = 200

_EMPTY_CELL = re.compile(r"^(nan|none|unnamed: ?\d+|-+|:?-{3,}:?)$", re.IGNORECASE)
_NUMBER = re.compile(r"^\d[\d\s.,]*$")


@dataclass
class CleanRow:
    row: int  # sequential id, used to map AI answers back to rows
    sheet: str
    section: str
    cells: list[str] = field(default_factory=list)

    @property
    def raw_name(self) -> str:
        # Text without price-like cells: stays the same when only the price changes
        return " | ".join(c for c in self.cells if not _NUMBER.match(c))

    def to_line(self) -> str:
        return f"r{self.row} | " + " | ".join(self.cells)


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


def clean_markdown(md: str) -> list[CleanRow]:
    rows: list[CleanRow] = []
    sheet, section = "", ""
    skip_sheet = False
    specs_cols: set[int] = set()

    for line in md.splitlines():
        line = line.strip()
        if line.startswith("## "):
            sheet = line[3:].strip()
            section = ""
            skip_sheet = sheet.lower() in SKIP_SHEETS
            specs_cols = set()
            continue
        if skip_sheet or not line or set(line) <= set("|-: "):
            continue

        raw_cells = line.strip("|").split("|") if line.startswith("|") else [line.lstrip("#").strip()]
        cells = [_clean_cell(c) for c in raw_cells]
        if not any(cells):
            continue

        if _is_header_row(cells):
            # Remember which column holds long specs so it can be shortened below
            found = {i for i, c in enumerate(cells) if SPECS_HEADER in c.lower()}
            if found:
                specs_cols = found
            name = _section_name(cells)
            if name:
                section = name
            continue

        cells = [
            _truncate(c, SPECS_MAX_LEN if i in specs_cols else CELL_MAX_LEN)
            for i, c in enumerate(cells)
        ]
        rows.append(CleanRow(row=len(rows) + 1, sheet=sheet, section=section, cells=[c for c in cells if c]))
    return rows


def make_chunks(rows: list[CleanRow], size: int) -> list[str]:
    """Split rows into text chunks; each chunk repeats its sheet/section context."""
    chunks = []
    for start in range(0, len(rows), size):
        lines, ctx = [], None
        for r in rows[start : start + size]:
            if (r.sheet, r.section) != ctx:
                ctx = (r.sheet, r.section)
                lines.append(f"# Sheet: {r.sheet} / Section: {r.section or '-'}")
            lines.append(r.to_line())
        chunks.append("\n".join(lines))
    return chunks
