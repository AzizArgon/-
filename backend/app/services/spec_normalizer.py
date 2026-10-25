"""Normalizer: any spelling from a price row -> one value from the spec dictionary.

"16GB", "16 ГБ", "16Gb", "16гб" -> capacity 16; "2x8GB", "8GB*2", "(8*2)" -> capacity 16, modules 2;
"SODIM", "SO-DIMM", "sodimm" -> SODIMM; "3200MHz", "3200 МГц" -> 3200.

Honesty rule: values are taken only from what the seller wrote (the row, the article and specs already
confirmed by the row). Nothing is guessed: no value in the text -> no value, and the product simply does not
appear under that filter. Values that follow from the written ones (Intel "F" = no graphics, "B760M" =
Micro-ATX) are added by the rules in `spec_inference.py` and stored as "inferred by a rule".
"""

import re
from collections import Counter, defaultdict

from app.services.spec_dictionary import CHOICE, NUMBER, YESNO, Spec, spec_map, specs_of
from app.services.spec_inference import infer

INFERRED = "_inferred"  # specs_json[INFERRED] = {key: rule_id}: values the seller did not write

# Unit words -> multiplier to the dictionary unit (TB -> GB: x1000, like drive makers count)
UNIT_WORDS = {
    "GB": {"tb": 1000, "тб": 1000, "gb": 1, "гб": 1, "gib": 1, "g": 1, "г": 1, "t": 1000},
    "MHz": {"mhz": 1, "мгц": 1, "mt/s": 1, "ghz": 1000, "ггц": 1000},
    "Hz": {"hz": 1, "гц": 1},
    "W": {"w": 1, "вт": 1, "ватт": 1},
    "VA": {"va": 1, "ва": 1},
}
NUM = r"(\d+(?:[.,]\d+)?)"
SIZE = rf"{NUM}\s*(tb|тб|gb|гб|g|г)(?![a-zа-я])"  # "16GB", "1 TB", "16гб", "8G" (not "16GD" in part numbers)


def _number(text: str) -> float | int:
    value = float(text.replace(",", ".").replace(" ", ""))
    return int(value) if value.is_integer() else value


def _gb(m: re.Match, num: int = 1, unit: int = 2) -> float | int:
    return _number(m[num]) * (1000 if m[unit].lower() in ("tb", "тб", "t") else 1)


def _first(*groups):
    return next((g for g in groups if g), None)


# ---- Rules: (category, key) -> [(pattern, value)]. The first pattern found in the text wins.
# The value is a constant or a function of the regex match. The same rules turn a seller's or AI value
# ("SO-DIMM", "80+ Gold") into the dictionary value.

def _ddr(m):
    return f"DDR{m[1]}"


def _socket(m):
    if m["lga"]:
        return f"LGA{m['lga']}" + ("-3" if m["v3"] else "")
    return f"AM{m['am']}" + ("+" if m["plus"] else "")


SOCKET = [(r"\blga\s*-?\s*(?P<lga>\d{4})(?P<v3>-?v?3\b)?|\bam(?P<am>[345])(?P<plus>\+)?(?![\w])", _socket),
          (r"\bstrx4\b", "sTRX4"), (r"\bstr5\b", "sTR5")]
CONNECTION = [(r"беспровод|wireless|bluetooth|\bbt\b|2[.,]4\s*ghz|три вида подключения|tri-?mode", "wireless"),
              (r"проводн|\bwired\b|usb", "wired")]
GAMING = [(r"игров|игравы|gaming|для геймер|\bgam\b", True)]
RGB = [(r"без подсветки|no rgb", False), (r"a?rgb|подсветк|backlit|\bled\b", True)]
COLOR_WORDS = (
    (r"black|черн|\bbk\b", "black"), (r"white|бел(?:ый|ая|ое|ые)\b|\bwh\b", "white"), (r"\bgr[ae]y\b|сер(?:ый|ая|ое|ые)\b", "gray"),
    (r"silver|серебр", "silver"), (r"\bred\b|красн", "red"), (r"\bblue\b|син(?:ий|яя|ее|ие)|голуб", "blue"),
    (r"\bgreen\b|зелен", "green"), (r"\bpink\b|розов", "pink"), (r"\byellow\b|желт", "yellow"),
    (r"\borange\b|оранж", "orange"), (r"\bpurple\b|фиолет", "purple"),
)
CPU_SERIES = [
    (r"core\s*ultra\s*-?\s*([579])|\bultra\s*([579])\b", lambda m: f"Core Ultra {_first(m[1], m[2])}"),
    (r"\bi([3579])\s*-?\s*\d{3,5}|core\s*i([3579])\b", lambda m: f"Core i{_first(m[1], m[2])}"),
    (r"\bcore\s*([357])\s*-\s*\d{3}", lambda m: f"Core {m[1]}"),
    (r"ryzen\W*\s*ai\s*([579])", lambda m: f"Ryzen AI {m[1]}"),
    (r"threadripper", "Threadripper"),
    (r"ryzen\W*\s*([3579])\b", lambda m: f"Ryzen {m[1]}"),
    (r"\bxeon\b", "Xeon"), (r"\bpentium\b", "Pentium"), (r"\bceleron\b", "Celeron"), (r"\bathlon\b", "Athlon"),
    (r"\bapple\s*m([1-5])\b|\(\s*m([1-5])(?:\s*(?:pro|max))?\s*/", lambda m: f"Apple M{_first(m[1], m[2])}"),
]
GPU_SUFFIX = {"ti super": "Ti Super", "ti": "Ti", "super": "Super", "xt": "XT", "xtx": "XTX", "gre": "GRE"}


def _chip(m):
    """"RTX5060Ti", "rtx 5060 ti", "RTX 5060TI" -> "RTX 5060 Ti"; "Arc B580" stays."""
    line = m[1].lower()
    name = f"Arc {line[-1].upper()}{m[2]}" if line.startswith("arc") else f"{m[1].upper()} {m[2]}"
    suffix = GPU_SUFFIX.get(re.sub(r"\s+", " ", (m[3] or "").lower()))
    return f"{name} {suffix}" if suffix else name


GPU_CHIP = [(r"\b(rtx|gtx|gt|rx|arc\s*[ab])\s*-?\s*(\d{3,4})\s*(ti\s*super|ti|super|xtx|xt|gre)?(?![a-z0-9])", _chip)]
RESOLUTION = [(r"(\d{3,4})\s*[x×х*]\s*(\d{3,4})(?!\s*(?:см|cm|мм|mm))", lambda m: f"{m[1]}x{m[2]}")]
LAPTOP_RAM = [(r"(?:lp)?ddr\d?\w*\s*(\d+)\s*gb|(\d+)\s*gb\s*(?:lp)?ddr", lambda m: _number(_first(m[1], m[2])))]
LAPTOP_STORAGE = [(
    rf"(?:ssd|hdd|emmc)\s*{NUM}\s*(gb|tb)|{NUM}\s*(gb|tb)\s*(?:ssd|hdd)",
    lambda m: _gb(m, 1, 2) if m[1] else _gb(m, 3, 4),
)]
SCREEN = [(r"/\s*(\d{2}(?:[.,]\d)?)\s*(?:\"|”|''|\s+(?:[\d.]+k|fhd|qhd|uhd|hd|wuxga|wqxga|wqhd|oled|ips|led|lcd|\d{3,4}\s*[x×]))",
           lambda m: _number(m[1]))]
REFRESH = [(r"(\d{2,3})\s*(?:hz|гц)\b", lambda m: int(m[1]))]
EXTERNAL = [(r"\bext\b|external|внешн|portable|портатив", True)]

RULES: dict[str, dict[str, list]] = {
    "ram": {
        "type": [(r"(?<![a-z])ddr([345])(?![0-9])", _ddr)],
        "form_factor": [(r"so-?\s?dimm?|sodim|для ноутбук|notebook|laptop", "SODIMM"),
                        (r"\b(?:u|long)?dimm\b|для пк|desktop", "DIMM")],
        "frequency": [(r"(\d{4})\s*(?:mhz|мгц|mt/s)|ddr\d-(\d{4})", lambda m: int(_first(m[1], m[2])))],
        "ecc": [(r"non-?ecc", False), (r"\becc\b|\breg(?:istered)?\b|\brdimm\b", True)],
        "rgb": RGB,
    },
    "cpu": {
        "brand": [(r"\bintel\b", "Intel"), (r"\bamd\b", "AMD")],
        "series": CPU_SERIES,
        "socket": SOCKET,
        "cores": [(r"(\d+)\s*(?:cores?|ядер|ядра|ядро)\b|(\d+)\s*c\s*/\s*\d+\s*t\b", lambda m: int(_first(m[1], m[2])))],
        "threads": [(r"(\d+)\s*(?:threads?|потоков|потока)\b|\d+\s*c\s*/\s*(\d+)\s*t\b", lambda m: int(_first(m[1], m[2])))],
        "graphics": [
            (r"\bno\s*gpu\b|без\s*(?:встроенной\s*)?графики", False),
            (r"\bgpu\b|graphics|графика", True),
        ],
        "pack": [(r"\bbox(?:ed)?\b", "BOX"), (r"\boem\b|\btray\b", "OEM")],
    },
    "gpu": {
        "chip": GPU_CHIP,
        "vendor": [(r"geforce|nvidia", "NVIDIA"), (r"radeon", "AMD")],
        "memory": [(SIZE, _gb)],
        "memory_type": [(r"\bgddr(\d)(x?)\b", lambda m: f"GDDR{m[1]}{m[2].upper()}")],
    },
    "ssd": {
        "capacity": [(SIZE, _gb)],
        "interface": [(r"nvme|pcie", "NVMe"), (r"\bsata", "SATA")],
        "form_factor": [(r"\bm\.?2\b", "M.2"), (r"\b2[.,]5\s*(?:\"|”|''|дюйм|inch)", "2.5\"")],
        "pcie": [(r"\bgen\s*([345])\b|pcie\s*([345])\.0", lambda m: f"{_first(m[1], m[2])}.0")],
        "external": EXTERNAL,
    },
    "hdd": {
        "capacity": [(SIZE, _gb)],
        "form_factor": [(r"\b3[.,]5\s*(?:\"|”|''|дюйм|inch)", "3.5\""), (r"\b2[.,]5\s*(?:\"|”|''|дюйм|inch)", "2.5\"")],
        "rpm": [(r"(\d{4,5})\s*(?:rpm|об/мин)", lambda m: int(m[1]))],
        "external": EXTERNAL,
    },
    "motherboard": {
        "socket": SOCKET,
        "chipset": [(r"\b([abhqxz]\d{2,3})(e?)[a-z]?(?![a-z0-9])", lambda m: (m[1] + m[2]).upper())],
        "form_factor": [
            (r"\be-?atx\b", "E-ATX"),
            (r"micro-?\s?atx|\bm-?atx\b", "mATX"),
            (r"mini-?\s?itx|\bitx\b", "ITX"),
            (r"\batx\b", "ATX"),
        ],
        "memory_type": [(r"(?<![a-z])ddr([345])(?![0-9])|\bd([45])\b", lambda m: f"DDR{_first(m[1], m[2])}")],
        "wifi": [(r"wi-?fi", True)],
    },
    "monitor": {
        "size": [(r"(\d{2}(?:[.,]\d)?)\s*(?:\"|”|''|дюйм|inch)", lambda m: _number(m[1]))],
        "resolution": RESOLUTION,
        "refresh_rate": REFRESH,
        "panel": [(r"qd-?oled|\bw?oled\b", "OLED"), (r"\b(?:fast\s*|nano\s*)?ips\b", "IPS"),
                  (r"\bm?va\b", "VA"), (r"\btn\b", "TN")],
        "curved": [(r"curve?r?d|изогнут|\b\d{3,4}r\b", True)],
    },
    "psu": {
        "power": [(r"(\d{3,4})\s*(?:w|вт|ватт)\b", lambda m: int(m[1]))],
        "certification": [(r"80\s*(?:\+|plus)\s*(white|bronze|silver|gold|platinum|titanium)?",
                           lambda m: m[1].title() if m[1] else "80 PLUS")],
        "modular": [(r"semi[-\s]?modular|полумодул", "semi"), (r"non[-\s]?modular|немодул", "no"),
                    (r"modular|модульн", "full")],
        "form_factor": [(r"\bsfx", "SFX"), (r"\batx\b", "ATX")],
    },
    "case": {"rgb": RGB},
    "cooling": {
        "type": [(r"liquid|водян|\bсжо\b|жидкост|\baio\b", "liquid"), (r"термопаст|thermal\s*paste|\bpaste\b", "paste"),
                 (r"\bcooler\b(?!\s*master)|кулер|башн", "air"), (r"\bfans?\b|вентил|вентелят", "fan")],
        "rgb": RGB,
    },
    "keyboard": {
        "connection": CONNECTION,
        "type": [(r"механ|mechanic", "mechanical"), (r"мембран|membrane", "membrane")],
        "with_mouse": [(r"набор|combo|key(?:board)?\s*(?:\+|and|&)\s*mouse|mouse\s*(?:\+|and|&)\s*(?:kb|keyboard)"
                        r"|клавиатура\s*(?:\+|и)\s*мыш|\+\s*мыш", True)],
        "rgb": RGB,
    },
    "mouse": {"connection": CONNECTION, "gaming": GAMING, "rgb": RGB},
    "headphones": {"connection": CONNECTION, "gaming": GAMING, "rgb": RGB},
    "speakers": {
        "channels": [(r"(?<!usb )(?<!bluetooth )(?<!\bv)\b([125])\.([01])\b", lambda m: f"{m[1]}.{m[2]}")],
        "power": [(r"(\d+(?:[.,]\d)?)\s*(?:w|вт)\b", lambda m: _number(m[1]))],
        "bluetooth": [(r"bluetooth|bt\b", True)],
    },
    "laptop": {"cpu": CPU_SERIES, "ram": LAPTOP_RAM, "storage": LAPTOP_STORAGE, "screen": SCREEN,
               "refresh_rate": REFRESH, "gpu": GPU_CHIP},
    "aio": {"cpu": CPU_SERIES, "ram": LAPTOP_RAM, "storage": LAPTOP_STORAGE, "screen": SCREEN},
    "desktop": {"cpu": CPU_SERIES, "ram": LAPTOP_RAM, "storage": LAPTOP_STORAGE, "gpu": GPU_CHIP},
    "ups": {
        "power_va": [(r"(\d{1,2}\s\d{3}|\d{3,5})\s*(?:va|ва)\b", lambda m: _number(m[1]))],
        "power_w": [(r"(\d{1,2}\s\d{3}|\d{3,5})\s*(?:w|вт|ватт)\b", lambda m: _number(m[1]))],
    },
    "printer": {
        "type": [(r"мфу|\bmfp\b", "mfp"), (r"принтер|printer", "printer")],
        "technology": [(r"лаз|laser", "laser"), (r"струйн|inkjet|ink\s*tank", "inkjet")],
        "color_print": [(r"цв\.|цветн", True)],
        "paper": [(r"\ba3\b", "A3"), (r"\ba4\b", "A4")],
        "wifi": [(r"wi-?fi", True)],
    },
    "projector": {
        "resolution": RESOLUTION,
        "brightness": [(r"(\d{3,5})\s*(?:люмен|lm|лм|ansi)", lambda m: int(m[1]))],
    },
    "flash": {
        "capacity": [(SIZE, _gb)],
        "type": [(r"micro\s*sd", "microsd"), (r"\bsd(?:hc|xc)?\b", "sd"), (r"usb|флеш|flash", "usb")],
    },
}

# Brand spelling differs between stores: "GIGABYTE" / "Gigabyte", "Asus" / "ASUS"
BRAND_CASE = {b.lower(): b for b in (
    "ASUS", "MSI", "Gigabyte", "HP", "LG", "AOC", "AMD", "Intel", "NVIDIA", "Lenovo", "Acer", "Dell", "Apple",
    "Samsung", "Deepcool", "Corsair", "Kingston", "ADATA", "Lexar", "Palit", "Sapphire", "Zotac", "PNY", "Inno3D",
    "Redragon", "AULA", "Defender", "Thermaltake", "Lian Li", "Jonsbo", "Montech", "ID-Cooling", "Xiaomi", "Edifier",
)}


def _squash(text: str) -> str:
    return re.sub(r"[^a-zа-я0-9]", "", text.lower().replace("ё", "е"))


def _shape(text: str) -> str:
    """How it was written, without the numbers: "16GB" and "8GB" are one spelling, "16 ГБ" is another."""
    return re.sub(r"\d+(?:[.,]\d+)?", "N", text.strip())


def _apply(rules: list, text: str) -> tuple[object, str] | None:
    for pattern, value in rules:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            result = value(m) if callable(value) else value
            if result is not None:
                return result, m[0]
    return None


def _ram_size(text: str):
    """Total capacity and number of sticks: "2x8GB", "8GB*2", "16GB (8*2)", "32GB 16GB*2" -> 16 / 32."""
    kit = re.search(r"\b([248])\s*[x×х*]\s*(\d+)\s*(?:gb|гб|g)(?![a-zа-я])", text, re.I)
    if kit:
        return int(kit[1]) * int(kit[2]), int(kit[1]), kit[0]
    kit = re.search(r"(\d+)\s*(?:gb|гб|g)?\s*\)?\s*[x×х*]\s*\(?([248])(?![\d.a-zа-я])", text, re.I)
    if kit:
        return int(kit[1]) * int(kit[2]), int(kit[2]), kit[0]
    single = re.search(SIZE, text, re.I)
    return (_gb(single), None, single[0]) if single else (None, None, None)


def _color(text: str):
    found = {name for pattern, name in COLOR_WORDS if re.search(pattern, text, re.I)}
    return found.pop() if len(found) == 1 else None  # "Black/White" — two colors: not a single value


def _case_board(text: str):
    """Case: the largest supported board from "поддержка E-ATX / ATX / Micro-ATX / Mini-ITX"."""
    found = []
    for pattern, size in ((r"\be-?atx\b", "E-ATX"), (r"(?<![-\w])atx\b", "ATX"),
                          (r"micro-?\s?atx|\bm-?atx\b", "mATX"), (r"mini-?\s?itx|\bitx\b", "ITX")):
        m = re.search(pattern, text, re.I)
        if m:
            found.append((size, m[0]))
    return found[0] if found else None


def parse_number(value, unit: str | None):
    """Seller/AI value of a NUMBER spec: "16GB", "1 TB", "3200 МГц", "27\"" -> number in the dictionary unit."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*([a-zа-я/]*)", str(value).lower())
    if not m:
        return None
    words = UNIT_WORDS.get(unit or "", {})
    mult = next((words[w] for w in sorted(words, key=len, reverse=True) if m[2].startswith(w)), 1)
    return _number(m[1]) * mult


def parse_yesno(value) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("no", "нет", "false", "0", "-", "none"):
        return False
    return True if text else None  # "yes", "да" or the word itself from the row ("RGB", "ECC")


def _from_value(category: str, spec: Spec, value):
    """A seller's or AI value written under a dictionary key -> dictionary value, or None if not valid."""
    if spec.kind == NUMBER:
        result = parse_number(value, spec.unit)
    elif spec.kind == YESNO:
        result = parse_yesno(value)
    elif spec.key == "brand":
        result = canonical_brand(str(value))
    elif spec.key == "color":
        result = _color(str(value))
    else:
        # Open lists (chip, chipset) accept only what their rules recognize: "Intel UHD Graphics" is not a GPU chip
        rules = RULES.get(category, {}).get(spec.key)
        found = _apply(rules, str(value)) if rules else None
        result = found[0] if found else None if rules else str(value).strip()
    return result if valid(spec, result) else None


def valid(spec: Spec, value) -> bool:
    if value is None or value == "":
        return False
    if spec.kind == NUMBER:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
    if spec.kind == YESNO:
        return isinstance(value, bool)
    return isinstance(value, str) and (spec.values is None or value in spec.values)


def canonical_brand(brand: str) -> str | None:
    brand = re.sub(r"\s+", " ", brand or "").strip()
    if not brand or brand.lower() in ("noname", "no name", "unknown"):
        return None
    if brand.lower() in BRAND_CASE:
        return BRAND_CASE[brand.lower()]
    return brand.title() if brand.isupper() and len(brand) > 4 else brand


def extract(category: str, text: str, trace: dict | None = None) -> dict:
    """Characteristics written in the text, as dictionary values. `trace` collects spellings for the report."""
    result: dict = {}
    seen: dict[str, str] = {}
    for key, rules in RULES.get(category, {}).items():
        found = _apply(rules, text)
        if found:
            result[key], seen[key] = found
    if category == "ram":
        total, modules, raw = _ram_size(text)
        if total:
            result["capacity"], seen["capacity"] = total, raw
        if modules:
            result["modules"], seen["modules"] = modules, raw
    if category == "cooling" and result.get("type") == "liquid":
        m = re.search(r"\b(120|140|240|280|360|420)(?:\s*(?:mm|мм))?(?![\d.])", text, re.I)
        if m:
            result["radiator"], seen["radiator"] = int(m[1]), m[0]
    if category == "case":
        board = _case_board(text)
        if board:
            result["board"], seen["board"] = board
    if "color" in spec_map(category):
        color = _color(text)
        if color:
            result["color"] = color

    specs = spec_map(category)
    clean = {k: v for k, v in result.items() if k in specs and valid(specs[k], v)}
    if trace is not None:
        for key, raw in seen.items():
            if key in clean:
                trace[(category, key)][_shape(raw)] += 1
    return clean


def normalize_specs(category: str, text: str, given: dict | None = None, brand: str | None = None,
                    trace: dict | None = None) -> dict:
    """The only way characteristics get into a product: dictionary keys, dictionary values.

    text   — what the seller wrote (row, article); values are extracted from it first;
    given  — specs from the rules, the AI (already checked against the row) or the seller: dictionary keys are
             normalized and fill the gaps, other keys are read as extra text ("lighting: ARGB" -> rgb);
    brand  — kept only if the brand is written in the text.
    Then the inference rules fill what follows from the written values; they are listed in result["_inferred"].
    """
    specs = spec_map(category)
    # Values inferred earlier are not "written by the seller": they are inferred again, never trusted as given
    given = {k: v for k, v in (given or {}).items() if not k.startswith("_") and k not in (given or {}).get(INFERRED, {})}
    loose = " ".join(str(v) for k, v in given.items() if k not in specs and not isinstance(v, bool))
    result = extract(category, f"{text} | {loose}" if loose else text, trace)
    for key, value in given.items():
        if key in specs and key not in result:
            normalized = _from_value(category, specs[key], value)
            if normalized is not None:
                result[key] = normalized
    brand_value = canonical_brand(brand or "")
    if brand_value and "brand" in specs and "brand" not in result and _squash(brand_value) in _squash(text):
        result["brand"] = brand_value if valid(specs["brand"], brand_value) else None
    result = {k: v for k, v in result.items() if v is not None}
    inferred = {}
    for key, (value, rule_id) in infer(category, text, result).items():
        if key in specs and valid(specs[key], value):
            result[key], inferred[key] = value, rule_id
    order = [s.key for s in specs_of(category)]
    clean = {k: result[k] for k in order if k in result}
    return {**clean, INFERRED: inferred} if inferred else clean


def merge_specs(card: dict | None, store: dict) -> dict:
    """The card gets the union of all stores: a key the card lacks, or has only inferred by a rule while this
    store wrote it, is taken from this store (with its source)."""
    card = dict(card or {})
    card_rules, store_rules = dict(card.pop(INFERRED, {})), store.get(INFERRED, {})
    for key, value in store.items():
        if key != INFERRED and (key not in card or (key in card_rules and key not in store_rules)):
            card[key] = value
            card_rules.pop(key, None)
            if key in store_rules:
                card_rules[key] = store_rules[key]
    return {**card, INFERRED: card_rules} if card_rules else card


def written_specs(specs: dict) -> dict:
    """Only what the seller wrote: dictionary values without the inferred ones (for Anti-Fraud)."""
    inferred = (specs or {}).get(INFERRED, {})
    return {k: v for k, v in (specs or {}).items() if not k.startswith("_") and k not in inferred}


def source_text(raw_name: str | None, article: str | None = None) -> str:
    """What the seller wrote about one item: the row and the article."""
    return " | ".join(filter(None, [raw_name, article]))


def specs_as_text(category: str, specs: dict) -> str:
    """Specs as plain words for text checks (Anti-Fraud): "DDR5 16GB 6000MHz ecc". "No" values and values
    inferred by rules are left out: Anti-Fraud judges only what the seller wrote."""
    parts = []
    for key, value in written_specs(specs).items():
        spec = spec_map(category).get(key)
        if isinstance(value, bool):
            if value:
                parts.append(key)
        elif spec and spec.kind == NUMBER and spec.unit in UNIT_WORDS:
            parts.append(f"{value}{spec.unit}")
        else:
            parts.append(str(value))
    return " ".join(parts)


def new_trace() -> dict:
    return defaultdict(Counter)
