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

# 2–4 key characteristics shown right in the catalog tile: "DDR5 · 16 GB · 6000 MHz · SODIMM"
CARD_SPECS: dict[str, tuple[str, ...]] = {
    "ram": ("type", "capacity", "frequency", "form_factor"),
    "cpu": ("socket", "cores", "threads", "pack"),
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
