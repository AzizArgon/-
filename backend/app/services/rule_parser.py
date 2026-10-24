"""Parses neat, well-formatted price rows with regular expressions, without the AI.

Each rule either understands the whole name confidently or returns None, and the row
goes to the AI. Rules never "fix" contradictions (e.g. DDR5 in the name, DDR4 in the
article) — those are kept for the Anti-Fraud checks.
"""

import re

# Rows with condition markers always go to the AI: it decides used/refurbished
_CONDITION_MARKERS = re.compile(r"б/у|\bused\b|восстан|refurb|\bref\b|уценк", re.IGNORECASE)
# Shop notes in brackets: "(распродажа)", "(Маркировка)", "(без рамки)"
_SHOP_NOTE = re.compile(r"\s*\([^)]*[а-яё][^)]*\)", re.IGNORECASE)
# Cyrillic letters that look like Latin ones, met in model codes ("12700КF")
_LOOKALIKES = str.maketrans("АВЕКМНОРСТХаеорсх", "ABEKMHOPCTXaeopcx")

_INTEL_CPU = re.compile(
    r"^Intel-Core (?P<series>i[3579]|Ultra [3579])\s*-\s*(?P<num>\w+),\s*(?P<ghz>[\d.]+) ?GHz,\s*"
    r"(?P<cache>\d+)MB,\s*(?P<pack>oem|box),\s*(?P<socket>LGA ?\d+),\s*(?P<gen>[\w ]+)$",
    re.IGNORECASE,
)
_AMD_CPU = re.compile(
    r"^AMD Ryzen\W*(?P<tier>\d) [A-Za-z ]+? (?P<num>\d{4}\w*) - (?P<ghz>[\d.]+) ?GHz, (?P<cores>\d+) cores/"
    r"(?P<threads>\d+) threads, (?P<gpu>No GPU|GPU), (?P<socket>AM\d),? \((?P<part>[\d-]+)\)(?:, (?P<pack>oem|box))?$",
    re.IGNORECASE,
)
_RAM = re.compile(
    r"^(?P<brand>[A-Za-z][\w-]*) (?P<type>DDR[345]) (?P<cap>\d+GB) (?P<freq>\d+MHz)(?P<rest>.*)$", re.IGNORECASE
)
_SSD = re.compile(
    r"^(?P<ext>Ext )?SSD (?P<ff>M\.?2 )?(?P<brand>[A-Za-z]+) (?P<cap>\d+(?:GB|TB))(?P<rest>.*)$", re.IGNORECASE
)
_HDD = re.compile(r"^HDD (?P<cap>\d+TB) (?P<brand>[A-Za-z]+) (?P<rest>.+?) (?P<rpm>\d+) ?Rpm", re.IGNORECASE)
_MB = re.compile(r"^MB (?P<brand>[A-Za-z]+) (?P<rest>.+)$")
_GPU = re.compile(
    r"^(?P<brand>[A-Za-z][\w ]*?) - (?P<mem>\d+GB) (?:ATI )?(?P<vendor>GeForce|Radeon) (?P<line>RTX|GTX|RX|GT) ?"
    r"(?P<num>\d{3,4})(?P<rest>.*)$",
    re.IGNORECASE,
)
_MONITOR = re.compile(r"^(?P<brand>[A-Za-z][\w ]*?) - (?P<size>\d+(?:[.,]\d)?)\" (?P<desc>[^,]*?) Monitor, (?P<rest>.+)$")

_PART_IN_BRACKETS = re.compile(r"\s*\(([\w./-]+)\)\s*$")
_GPU_NOISE = re.compile(r"\b(G?DDR\d\w*|\d+ ?bits?|HDMI|\d-DP|DP)\b", re.IGNORECASE)
_GPU_SUFFIX = re.compile(r"^\s*(Ti|Super|XTX|XT|GRE)\b", re.IGNORECASE)


def _item(category, brand, model, name, specs) -> dict:
    return {
        "category": category,
        "brand": brand,
        "model": model,
        "name": re.sub(r"\s+", " ", name).strip(),
        "condition": "new",
        "specs": {k: v for k, v in specs.items() if v},
    }


def _intel_cpu(text: str):
    m = _INTEL_CPU.match(text)
    if not m:
        return None
    num = m["num"].translate(_LOOKALIKES).upper()
    series = m["series"].title() if m["series"].lower().startswith("ultra") else m["series"].lower()
    model = f"{series} {num}" if series.startswith("Ultra") else f"{series}-{num}"
    socket = m["socket"].replace(" ", "").upper()
    return _item("cpu", "Intel", model, f"Intel Core {model} {m['pack'].upper()}", {
        "socket": socket, "frequency": f"{m['ghz']} GHz", "cache": f"{m['cache']} MB", "generation": m["gen"].strip(),
    })


def _amd_cpu(text: str):
    m = _AMD_CPU.match(text)
    if not m:
        return None
    model = f"Ryzen {m['tier']} {m['num'].upper()}"
    pack = f" {m['pack'].upper()}" if m["pack"] else ""
    return _item("cpu", "AMD", model, f"AMD {model}{pack}", {
        "socket": m["socket"].upper(), "frequency": f"{m['ghz']} GHz", "cores": m["cores"],
        "threads": m["threads"], "graphics": "yes" if m["gpu"].upper() == "GPU" else "no",
    })


def _ram(text: str):
    m = _RAM.match(text)
    if not m:
        return None
    rest = m["rest"]
    kit = re.search(r"\(?(\d+)GB\s*\*\s*(\d)\)?|\((\d+)\*(\d)\)", rest)
    if kit:
        size, count = (kit[1], kit[2]) if kit[1] else (kit[3], kit[4])
        rest = rest.replace(kit[0], f"({count}x{size}GB)")
    form = "SODIMM" if re.search(r"SODIMM|SODIM", rest, re.IGNORECASE) else None  # not written = unknown
    rest = re.sub(r"\bSODIMM?\b", "SODIMM", rest, flags=re.IGNORECASE)
    ddr = m["type"].upper()
    name = f"{m['brand']} {ddr} {m['cap'].upper()} {m['freq'].replace('mhz', 'MHz')}{rest}"
    return _item("ram", m["brand"], None, name, {
        "type": ddr, "capacity": m["cap"].upper(), "frequency": m["freq"], "form_factor": form,
    })


def _ssd(text: str):
    m = _SSD.match(text)
    if not m:
        return None
    rest = m["rest"]
    iface = "NVMe" if "nvme" in rest.lower() else "SATA" if "sata" in rest.lower() else None
    form = "M.2" if m["ff"] else "2.5\"" if "2.5" in rest else None
    if not iface and not m["ext"]:
        return None  # unclear drive type: let the AI decide
    prefix = "External SSD " if m["ext"] else "SSD "
    name = f"{prefix}{m['brand']} {m['cap'].upper()}{rest}"
    return _item("ssd", m["brand"], None, name, {
        "capacity": m["cap"].upper(), "interface": iface, "form_factor": form,
    })


def _hdd(text: str):
    m = _HDD.match(text)
    if not m:
        return None
    parts = m["rest"].split()
    model = next((p for p in parts if re.search(r"\d", p) and len(p) >= 8), None)
    name = f"HDD {m['brand']} {m['cap'].upper()} {m['rest']} {m['rpm']} rpm"
    return _item("hdd", m["brand"], model, name, {"capacity": m["cap"].upper(), "rpm": m["rpm"]})


def _motherboard(text: str):
    m = _MB.match(text)
    if not m:
        return None
    rest = m["rest"]
    part = _PART_IN_BRACKETS.search(rest)
    rest = _PART_IN_BRACKETS.sub("", rest)
    socket = re.search(r"\b(LGA\s?\d{4}|AM[45])\b", rest, re.IGNORECASE)
    memory = re.search(r"\b(DDR[345])\b", rest, re.IGNORECASE)
    chipset = re.search(r"\b([ABHXZ]\d{3}[A-Z]?)\b", rest)
    if not chipset:
        return None
    name = re.sub(r"^AMD (AM[45] )?", "", rest)
    return _item("motherboard", m["brand"], part[1] if part else None, f"{m['brand']} {name}", {
        "chipset": chipset[1], "socket": socket[1].replace(" ", "").upper() if socket else None,
        "memory": memory[1].upper() if memory else None,
    })


def _gpu(text: str):
    m = _GPU.match(text)
    if not m:
        return None
    rest = m["rest"]
    part = _PART_IN_BRACKETS.search(rest)
    rest = _PART_IN_BRACKETS.sub("", rest)
    # Part number without brackets: "GAMING OC GV-R9060XTGAMING OC-8GD"
    inline = re.search(r"\s([A-Z]{2,}-\w*\d\w*\S*.*)$", rest)
    if inline and not part:
        part, rest = inline, rest[: inline.start()]
    suffix = _GPU_SUFFIX.match(rest)
    chip_num = m["num"] + (f" {suffix[1].title() if suffix[1].lower() != 'xt' else 'XT'}" if suffix else "")
    if suffix:
        rest = rest[suffix.end():]
    rest = re.sub(r"\s+", " ", _GPU_NOISE.sub("", rest)).strip()
    chip = f"{'GeForce' if m['vendor'].lower() == 'geforce' else 'Radeon'} {m['line'].upper()} {chip_num}"
    name = f"{m['brand']} {chip} {rest} {m['mem'].upper()}"
    return _item("gpu", m["brand"], part[1] if part else None, name, {
        "chip": chip, "memory": m["mem"].upper(),
    })


def _monitor(text: str):
    m = _MONITOR.match(text)
    if not m:
        return None
    rest = m["rest"]
    panel = re.search(r"\b(IPS|VA|TN|OLED|QD-OLED)\b", rest)
    hz = re.search(r"(\d{2,3}) ?Hz", rest, re.IGNORECASE)
    res = re.search(r"(\d{3,4}) ?[xх] ?(\d{3,4})", rest)
    # Series words up to the first one with digits, which is the model code: "TUF Gaming VG249QM1A"
    words = m["desc"].split()
    idx = next((i for i, w in enumerate(words) if re.search(r"\d", w)), None)
    if idx is None:
        return None
    model = words[idx]
    size = m["size"].replace(",", ".")
    name = f"{m['brand']} {' '.join(words[: idx + 1])} {size}\""
    return _item("monitor", m["brand"], model, name, {
        "size": f"{size}\"", "panel": panel[1] if panel else None,
        "refresh_rate": f"{hz[1]} Hz" if hz else None, "resolution": f"{res[1]}x{res[2]}" if res else None,
    })


RULES = (_intel_cpu, _amd_cpu, _ram, _ssd, _hdd, _motherboard, _gpu, _monitor)


def parse_by_rules(name: str) -> dict | None:
    """Structured product for a neat name, or None if the AI is needed."""
    if not name or _CONDITION_MARKERS.search(name):
        return None
    text = _SHOP_NOTE.sub("", name).strip()
    for rule in RULES:
        result = rule(text)
        if result:
            return result
    return None
