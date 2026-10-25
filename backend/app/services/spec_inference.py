"""Inference rules: characteristics that the seller did NOT write, but that follow from what they wrote.

The normalizer (`spec_normalizer.py`) reads only what is written in the row. Everything below is added
afterwards, only for keys still empty, and every value is stored with its source: the product keeps
`specs_json["_inferred"] = {key: rule_id}`, the product page marks such values ("выведено правилом",
the reason is in a hover hint: `specs.inferred.<rule_id>` in ru.json). Anti-Fraud never uses inferred values.

Each rule says why it is correct. A rule that is only "usually true" does not belong here: for example, a RAM
kit size is never inferred ("16GB" may be one stick or a kit nobody mentioned).
"""

import re
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Inference:
    rule_id: str  # also the translation key of the hint
    category: str
    key: str
    infer: Callable[[str, dict], object]  # (row text, specs found so far) -> value or None


def _intel_graphics(text: str, specs: dict):
    # Why: Intel marks desktop CPUs without built-in graphics with "F" in the model suffix (12400F, 14600KF,
    # Ultra 7 265KF); all other Core / Core Ultra desktop models have it. This is Intel's naming scheme.
    m = re.search(r"(?:\bi[3579]|ultra\s*[579]|\bcore\s*[357])\s*-?\s*\d{3,5}([a-z]*)\b", text, re.I)
    return None if not m else "f" not in m[1].lower()


def _cpu_brand(text: str, specs: dict):
    # Why: Core, Xeon, Pentium, Celeron are Intel trademarks; Ryzen, Athlon, Threadripper are AMD trademarks.
    # Nobody else sells processors under these names.
    series = specs.get("series") or ""
    if series.startswith(("Core", "Xeon", "Pentium", "Celeron")):
        return "Intel"
    if series.startswith(("Ryzen", "Athlon", "Threadripper")):
        return "AMD"
    return None


def _gpu_vendor(text: str, specs: dict):
    # Why: chip lines belong to one maker each: GeForce RTX/GTX/GT — NVIDIA, Radeon RX — AMD, Arc — Intel.
    chip = specs.get("chip") or ""
    return "NVIDIA" if chip.startswith(("RTX", "GTX", "GT ")) else "AMD" if chip.startswith("RX") \
        else "Intel" if chip.startswith("Arc") else None


def _board_size(text: str, specs: dict):
    # Why: board makers add the size to the chipset in the model name: "M" = Micro-ATX (B760M, B650M-K),
    # "I" = Mini-ITX (B650I). Without a letter the size is not known (most are ATX, but not all) -> no value.
    m = re.search(r"\b[abhqxz]\d{2,3}e?([mi])(?![a-z0-9])", text, re.I)
    return None if not m else "mATX" if m[1].lower() == "m" else "ITX"


RESOLUTION_NAMES = (("3840x2160", r"\b(?:uhd|4k)\b"), ("2560x1440", r"\bqhd\b|\b2k\b"), ("1920x1080", r"\bfhd\b|full\s*hd"))


def _resolution(text: str, specs: dict):
    # Why: FHD, QHD, UHD/4K are fixed standard names: 1920x1080, 2560x1440, 3840x2160.
    # WQHD is left out on purpose: makers use it both for 2560x1440 and the ultrawide 3440x1440.
    return next((value for value, pattern in RESOLUTION_NAMES if re.search(pattern, text, re.I)), None)


def _ram_dimm(text: str, specs: dict):
    # Why: in price lists laptop memory is always marked (SODIMM, SO-DIMM, "для ноутбука", notebook) — a
    # different stick that does not fit a PC, and sellers must say so. Memory without such a mark is the
    # ordinary desktop DIMM. The normalizer has already looked for every laptop mark, so here they are absent.
    return "DIMM"


# Memory series names are trademarks of one maker each (regexes on the row text)
RAM_SERIES = (
    (r"trident\s*z|ripjaws|flare\s*x|aegis|sniper\s*x", "G.Skill"),
    (r"vengeance|dominator", "Corsair"),
    (r"fury|hyperx|valueram", "Kingston"),
    (r"ballistix", "Crucial"),
    (r"xpg|spectrix|gammix|lancer", "ADATA"),
    (r"t-?force|vulcan|delta\s*rgb", "TeamGroup"),
    (r"viper", "Patriot"),
    (r"ares", "Lexar"),
)


def _ram_brand(text: str, specs: dict):
    # Why: Trident Z, Ripjaws (G.Skill), Vengeance, Dominator (Corsair), Fury, HyperX (Kingston), Ballistix
    # (Crucial), XPG (ADATA), T-Force (TeamGroup), Viper (Patriot), Ares (Lexar) are registered names of one
    # maker each: a seller writing "Trident Z Royal" names a G.Skill kit even without the word "G.Skill".
    return next((brand for pattern, brand in RAM_SERIES if re.search(pattern, text, re.I)), None)


INFERENCES = (
    Inference("intel_f_graphics", "cpu", "graphics", _intel_graphics),
    Inference("cpu_brand_by_series", "cpu", "brand", _cpu_brand),
    Inference("gpu_vendor_by_chip", "gpu", "vendor", _gpu_vendor),
    Inference("board_size_by_chipset", "motherboard", "form_factor", _board_size),
    Inference("resolution_by_name", "monitor", "resolution", _resolution),
    Inference("resolution_by_name", "projector", "resolution", _resolution),
    Inference("ram_dimm_by_default", "ram", "form_factor", _ram_dimm),
    Inference("ram_brand_by_series", "ram", "brand", _ram_brand),
)

INFERABLE: dict[str, set[str]] = {}
for _rule in INFERENCES:
    INFERABLE.setdefault(_rule.category, set()).add(_rule.key)


def infer(category: str, text: str, specs: dict) -> dict[str, tuple[object, str]]:
    """{key: (value, rule_id)} for keys that are still empty. Rules run in order, later ones see earlier results."""
    found: dict[str, tuple[object, str]] = {}
    for rule in INFERENCES:
        if rule.category != category or rule.key in specs or rule.key in found:
            continue
        value = rule.infer(text, {**specs, **{k: v for k, (v, _) in found.items()}})
        if value is not None:
            found[rule.key] = (value, rule.rule_id)
    return found
