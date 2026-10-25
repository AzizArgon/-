"""Dictionary of product characteristics: the core of standardization.

Every category has a fixed list of keys. Each key has a value kind:
- NUMBER — a number in one fixed unit (capacity is always in GB, frequency in MHz);
- CHOICE — one value from the allowed list (DDR3 / DDR4 / DDR5); `values=None` means an open
  list whose spelling is fixed by the normalizer (GPU chip "RTX 4060 Ti", chipset "B760");
- YESNO — true / false.

Rules, the AI parser and manual input write characteristics only through this dictionary
(see `spec_normalizer.py`): "16GB", "16 ГБ", "16гб" all become `capacity: 16`.
Texts for keys, values and units are in the frontend translations (`specs.*` in ru.json).
"""

from dataclasses import dataclass

NUMBER, CHOICE, YESNO = "number", "choice", "yesno"


@dataclass(frozen=True)
class Spec:
    key: str
    kind: str
    unit: str | None = None  # NUMBER only: GB, MHz, Hz, W, inch, ...
    values: tuple[str, ...] | None = None  # CHOICE only: allowed values in display order
    at_least: bool = False  # filter "from N and above" (refresh rate, power) instead of exact values


DDR = ("DDR3", "DDR4", "DDR5")
BOARD_SIZES = ("E-ATX", "ATX", "mATX", "ITX")
CONNECTION = ("wired", "wireless")
COLORS = ("black", "white", "gray", "silver", "red", "blue", "green", "pink", "yellow", "orange", "purple")
CPU_SERIES = (
    "Core i3", "Core i5", "Core i7", "Core i9", "Core 3", "Core 5", "Core 7",
    "Core Ultra 5", "Core Ultra 7", "Core Ultra 9", "Pentium", "Celeron", "Xeon",
    "Ryzen 3", "Ryzen 5", "Ryzen 7", "Ryzen 9", "Ryzen AI 5", "Ryzen AI 7", "Ryzen AI 9", "Threadripper", "Athlon",
    "Apple M1", "Apple M2", "Apple M3", "Apple M4", "Apple M5",
)

BRAND = Spec("brand", CHOICE)  # open list, every category has it
CPU = Spec("cpu", CHOICE, values=CPU_SERIES)  # processor line inside laptops and PCs
RAM_SIZE = Spec("ram", NUMBER, "GB")
STORAGE = Spec("storage", NUMBER, "GB")
SCREEN = Spec("screen", NUMBER, "inch")
GPU_CHIP = Spec("gpu", CHOICE)  # discrete graphics: "RTX 4060"
RGB = Spec("rgb", YESNO)
COLOR = Spec("color", CHOICE, values=COLORS)

DICTIONARY: dict[str, tuple[Spec, ...]] = {
    "ram": (
        Spec("type", CHOICE, values=DDR),
        Spec("form_factor", CHOICE, values=("DIMM", "SODIMM")),
        Spec("capacity", NUMBER, "GB"),  # total for a kit: 2x8GB -> 16
        Spec("frequency", NUMBER, "MHz"),
        Spec("modules", NUMBER, "modules"),  # how many sticks in the box
        Spec("ecc", YESNO),
        Spec("revision", CHOICE),  # "ver 5.30", "rev 1.0" — a modifier: not part of the model
        RGB, BRAND,
    ),
    "cpu": (
        Spec("brand", CHOICE, values=("Intel", "AMD")),
        Spec("series", CHOICE, values=CPU_SERIES),
        Spec("socket", CHOICE, values=(
            "LGA1150", "LGA1151", "LGA1200", "LGA1700", "LGA1851", "LGA2011", "LGA2011-3", "LGA2066", "LGA3647",
            "AM3+", "AM4", "AM5", "sTRX4", "sTR5",
        )),
        Spec("cores", NUMBER, "cores"),
        Spec("threads", NUMBER, "threads"),
        Spec("graphics", YESNO),  # Intel "F" in the model = no graphics
        Spec("pack", CHOICE, values=("BOX", "OEM")),
    ),
    "gpu": (
        Spec("vendor", CHOICE, values=("NVIDIA", "AMD", "Intel")),
        Spec("chip", CHOICE),
        Spec("memory", NUMBER, "GB"),
        Spec("memory_type", CHOICE, values=("GDDR5", "GDDR6", "GDDR6X", "GDDR7")),
        Spec("revision", CHOICE, values=("LHR", "Full Hash Rate")),  # a modifier: not part of the model
        BRAND,
    ),
    "ssd": (
        Spec("capacity", NUMBER, "GB"),
        Spec("interface", CHOICE, values=("NVMe", "SATA")),
        Spec("form_factor", CHOICE, values=("M.2", "2.5\"")),
        Spec("pcie", CHOICE, values=("3.0", "4.0", "5.0")),
        Spec("external", YESNO),
        BRAND,
    ),
    "hdd": (
        Spec("capacity", NUMBER, "GB"),
        Spec("form_factor", CHOICE, values=("3.5\"", "2.5\"")),
        Spec("rpm", NUMBER, "rpm"),
        Spec("external", YESNO),
        BRAND,
    ),
    "motherboard": (
        Spec("socket", CHOICE, values=(
            "LGA1151", "LGA1200", "LGA1700", "LGA1851", "LGA2011-3", "LGA2066", "AM4", "AM5",
        )),
        Spec("chipset", CHOICE),
        Spec("form_factor", CHOICE, values=BOARD_SIZES),
        Spec("memory_type", CHOICE, values=DDR),
        Spec("wifi", YESNO),
        BRAND,
    ),
    "monitor": (
        Spec("size", NUMBER, "inch"),
        Spec("resolution", CHOICE),  # "2560x1440"
        Spec("refresh_rate", NUMBER, "Hz", at_least=True),
        Spec("panel", CHOICE, values=("IPS", "VA", "TN", "OLED")),
        Spec("curved", YESNO),
        BRAND,
    ),
    "psu": (
        Spec("power", NUMBER, "W", at_least=True),
        Spec("certification", CHOICE, values=("80 PLUS", "White", "Bronze", "Silver", "Gold", "Platinum", "Titanium")),
        Spec("modular", CHOICE, values=("full", "semi", "no")),
        Spec("form_factor", CHOICE, values=("ATX", "SFX")),
        BRAND,
    ),
    "case": (
        Spec("board", CHOICE, values=BOARD_SIZES),  # the largest supported motherboard
        RGB, COLOR, BRAND,
    ),
    "cooling": (
        Spec("type", CHOICE, values=("air", "liquid", "fan", "paste")),
        Spec("radiator", NUMBER, "mm"),
        RGB, COLOR, BRAND,
    ),
    "keyboard": (
        Spec("connection", CHOICE, values=CONNECTION),
        Spec("type", CHOICE, values=("mechanical", "membrane")),
        Spec("with_mouse", YESNO),
        RGB, BRAND,
    ),
    "mouse": (
        Spec("connection", CHOICE, values=CONNECTION),
        Spec("gaming", YESNO),
        RGB, COLOR, BRAND,
    ),
    "headphones": (
        Spec("connection", CHOICE, values=CONNECTION),
        Spec("gaming", YESNO),
        RGB, BRAND,
    ),
    "speakers": (
        Spec("channels", CHOICE, values=("1.0", "2.0", "2.1", "5.1")),
        Spec("power", NUMBER, "W"),
        Spec("bluetooth", YESNO),
        BRAND,
    ),
    "laptop": (CPU, RAM_SIZE, STORAGE, SCREEN, Spec("refresh_rate", NUMBER, "Hz", at_least=True), GPU_CHIP, BRAND),
    "aio": (CPU, RAM_SIZE, STORAGE, SCREEN, BRAND),
    "desktop": (CPU, RAM_SIZE, STORAGE, GPU_CHIP, BRAND),
    "ups": (Spec("power_va", NUMBER, "VA", at_least=True), Spec("power_w", NUMBER, "W"), BRAND),
    "printer": (
        Spec("type", CHOICE, values=("printer", "mfp")),
        Spec("technology", CHOICE, values=("laser", "inkjet")),
        Spec("color_print", YESNO),
        Spec("paper", CHOICE, values=("A4", "A3")),
        Spec("wifi", YESNO),
        BRAND,
    ),
    "projector": (Spec("resolution", CHOICE), Spec("brightness", NUMBER, "lm"), BRAND),
    "flash": (Spec("capacity", NUMBER, "GB"), Spec("type", CHOICE, values=("usb", "microsd", "sd")), BRAND),
    "chair": (COLOR, BRAND),
    "other": (BRAND,),
}

# "Without the box" is possible for any product: the last key of every category
BOX = Spec("box", CHOICE, values=("no_box",))
DICTIONARY = {category: (*specs, BOX) for category, specs in DICTIONARY.items()}

# Modifiers: words that sellers add to a product name, but that do not make it another product. They are removed
# from the name and the match key (so "RTX 3080 Ti LHR" and "RTX 3080 Ti" are one card) and kept as a
# characteristic. OC, Gaming OC, Ti, Super, X3D are NOT modifiers: those are different models.
# (categories or None for all, pattern, key, value or None = the matched text in the "ver 5.30" form)
MODIFIERS: tuple[tuple[tuple[str, ...] | None, str, str, str | None], ...] = (
    (("gpu",), r"\b(?:non|no)[\s-]*lhr\b|\bfull[\s-]*hash[\s-]*rate\b|\bfhr\b", "revision", "Full Hash Rate"),
    (("gpu",), r"\blhr\b", "revision", "LHR"),
    (("ram",), r"\b(ver|rev)\.?\s*(\d+(?:\.\d+)*)\b", "revision", None),
    (None, r"коробки\s+нет|без\s+коробки|только\s+плата|\bno\s+box\b|\bwithout\s+box\b|qutisiz", "box", "no_box"),
)

# 2–4 key characteristics shown right in the catalog tile: "DDR5 · 16 GB · 6000 MHz · SODIMM"
CARD_SPECS: dict[str, tuple[str, ...]] = {
    "ram": ("type", "capacity", "frequency", "form_factor"),
    "cpu": ("series", "socket", "cores", "threads"),
    "gpu": ("chip", "memory", "memory_type"),
    "ssd": ("capacity", "interface", "form_factor"),
    "hdd": ("capacity", "form_factor", "rpm"),
    "motherboard": ("socket", "chipset", "form_factor", "memory_type"),
    "monitor": ("size", "resolution", "refresh_rate", "panel"),
    "psu": ("power", "certification", "modular"),
    "case": ("board", "color"),
    "cooling": ("type", "radiator"),
    "keyboard": ("connection", "type"),
    "mouse": ("connection",),
    "headphones": ("connection",),
    "speakers": ("channels", "power"),
    "laptop": ("cpu", "ram", "storage", "screen"),
    "aio": ("cpu", "ram", "storage", "screen"),
    "desktop": ("cpu", "ram", "storage", "gpu"),
    "ups": ("power_va", "power_w"),
    "printer": ("type", "technology", "paper"),
    "projector": ("resolution", "brightness"),
    "flash": ("capacity", "type"),
    "chair": ("color",),
}


def specs_of(category: str) -> tuple[Spec, ...]:
    return DICTIONARY.get(category, DICTIONARY["other"])


def spec_map(category: str) -> dict[str, Spec]:
    return {s.key: s for s in specs_of(category)}


# Plausible ranges of numbers: a value outside is most likely a typo of the seller ("DDR5 600MHz" instead of 6000).
# It is not corrected and not used in filters: the seller sees "possible typo", the buyer "specs need checking".
# Ranges are wide on purpose (real products only, from the slowest to the newest flagship), in dictionary units.
PLAUSIBLE: dict[str, dict[str, tuple[float, float]]] = {
    "ram": {"capacity": (1, 512), "modules": (1, 8)},
    "cpu": {"cores": (1, 128), "threads": (1, 256)},
    "gpu": {"memory": (1, 48)},
    "ssd": {"capacity": (32, 16000)},
    "hdd": {"capacity": (80, 30000), "rpm": (4200, 15000)},
    "monitor": {"size": (10, 57), "refresh_rate": (48, 750)},  # portable 14", esports 600 Hz exist
    "psu": {"power": (30, 3000)},  # laptop/AIO adapters are in this category too
    "cooling": {"radiator": (80, 480)},
    "speakers": {"power": (1, 2000)},
    "laptop": {"ram": (2, 128), "storage": (64, 8000), "screen": (10, 18.4), "refresh_rate": (60, 300)},
    "aio": {"ram": (2, 128), "storage": (64, 8000), "screen": (19, 34)},
    "desktop": {"ram": (2, 512), "storage": (64, 30000)},
    "ups": {"power_va": (300, 20000), "power_w": (150, 20000)},
    "projector": {"brightness": (100, 15000)},
    "flash": {"capacity": (1, 2000)},
}
# RAM frequency depends on the generation (JEDEC base up to the fastest overclocking kits)
RAM_FREQUENCY = {"DDR3": (800, 2933), "DDR4": (1600, 5333), "DDR5": (4000, 9000), None: (800, 9000)}


def plausible_range(category: str, key: str, specs: dict) -> tuple[float, float] | None:
    if category == "ram" and key == "frequency":
        return RAM_FREQUENCY.get(specs.get("type"), RAM_FREQUENCY[None])
    return PLAUSIBLE.get(category, {}).get(key)


def implausible(category: str, specs: dict) -> dict[str, tuple[float, float]]:
    """{key: (min, max)} of numbers outside their plausible range."""
    result = {}
    for key, value in specs.items():
        limits = plausible_range(category, key, specs)
        if limits and isinstance(value, (int, float)) and not isinstance(value, bool) \
                and not limits[0] <= value <= limits[1]:
            result[key] = limits
    return result
