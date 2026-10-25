import pytest

from app.services.spec_dictionary import CARD_SPECS, CHOICE, DICTIONARY, NUMBER
from app.services.spec_inference import INFERENCES
from app.services.spec_normalizer import merge_specs, new_trace, normalize_specs, specs_as_text


@pytest.mark.parametrize("text", ["Lexar DDR4 16GB 3200MHz", "Lexar DDR4 16 ГБ 3200 МГц", "Lexar DDR4 16Gb 3200mhz",
                                  "Lexar ddr4 16гб 3200Mhz"])
def test_ram_capacity_spellings(text):
    specs = normalize_specs("ram", text)
    assert specs["capacity"] == 16 and specs["frequency"] == 3200 and specs["type"] == "DDR4"
    assert "modules" not in specs  # a single stick is not written -> not guessed


@pytest.mark.parametrize("text", ["Kingston DDR5 2x8GB 6000MHz", "Kingston DDR5 16GB (8*2) 6000MHz",
                                  "Kingston DDR5 8GB*2 6000MHz", "Kingston DDR5 16GB 8GB×2 6000MHz"])
def test_ram_kit_is_total_capacity(text):
    specs = normalize_specs("ram", text)
    assert specs["capacity"] == 16 and specs["modules"] == 2


@pytest.mark.parametrize("word", ["SODIMM", "SODIM", "SO-DIMM", "sodimm", "So-Dimm"])
def test_sodimm_spellings(word):
    assert normalize_specs("ram", f"Hiksemi DDR5 32GB 5600MHz {word}")["form_factor"] == "SODIMM"


def test_ram_without_mark_is_dimm_inferred_by_rule():
    specs = normalize_specs("ram", "Lexar DDR5 16GB 5600MHz")
    assert specs["form_factor"] == "DIMM" and specs["_inferred"] == {"form_factor": "ram_dimm_by_default"}
    assert "modules" not in specs  # "1 stick" is never inferred
    # Written by the seller: no inference mark
    assert "_inferred" not in normalize_specs("ram", "Lexar DDR5 16GB 5600MHz SODIMM")
    assert "_inferred" not in normalize_specs("ram", "Kingston DDR4 8GB 3200MHz UDIMM")
    assert normalize_specs("ram", "Samsung DDR4 32GB 3200MHz ECC REG")["ecc"] is True
    assert normalize_specs("ram", "Lexar DDR4 8GB 3600MHz RGB")["rgb"] is True


def test_intel_f_means_no_graphics():
    specs = normalize_specs("cpu", "Intel-Core i5 - 12400F, 2.5 GHz, 18MB, oem, LGA1700, Alder Lake")
    assert specs == {"brand": "Intel", "series": "Core i5", "socket": "LGA1700", "graphics": False, "pack": "OEM",
                     "_inferred": {"graphics": "intel_f_graphics"}}
    assert normalize_specs("cpu", "Intel-Core i5 - 14400, 2.5 GHz, 20MB, BOX, LGA1700")["graphics"] is True
    assert normalize_specs("cpu", "Intel-Core Ultra 7-265KF, 5.5 GHz, 30MB, oem, LGA 1851")["series"] == "Core Ultra 7"


def test_amd_cpu():
    specs = normalize_specs("cpu", "AMD Ryzen™ 5 Vermeer 5600X - 3.7 GHz, 6 cores/12 threads, No GPU, AM4 (100-000000065), oem")
    assert specs == {"brand": "AMD", "series": "Ryzen 5", "socket": "AM4", "cores": 6, "threads": 12,
                     "graphics": False, "pack": "OEM"}
    assert normalize_specs("cpu", "AMD Ryzen 7 7700 - 3.8 GHz, 8C/16T, GPU, AM5")["graphics"] is True


def test_slang_cpu_gets_only_what_is_written():
    # "проц i5 12400f б/у": the socket is not written, so there is no socket
    assert normalize_specs("cpu", "проц i5 12400f б/у") == {
        "brand": "Intel", "series": "Core i5", "graphics": False,
        "_inferred": {"brand": "cpu_brand_by_series", "graphics": "intel_f_graphics"}}


@pytest.mark.parametrize("text,chip,vendor", [
    ("PNY - 16GB GeForce RTX5060Ti GDDR7 128bit", "RTX 5060 Ti", "NVIDIA"),
    ("MSI RTX 4060 Ventus 2X 8GB", "RTX 4060", "NVIDIA"),
    ("Gigabyte - 16GB ATI Radeon RX9070XT GAMING GV-R9070XTGAMING-16GD", "RX 9070 XT", "AMD"),
    ("ASRock Arc B580 Challenger 12GB", "Arc B580", "Intel"),
])
def test_gpu_chip(text, chip, vendor):
    specs = normalize_specs("gpu", text)
    assert specs["chip"] == chip and specs["vendor"] == vendor


def test_gpu_memory_and_brand():
    specs = normalize_specs("gpu", "Palit - 16GB GeForce RTX5080 INFINITY 3 GDDR7 256bit", brand="PALIT")
    assert specs["memory"] == 16 and specs["memory_type"] == "GDDR7" and specs["brand"] == "Palit"
    # A brand the row does not mention is not added
    assert "brand" not in normalize_specs("gpu", "RTX 4060 8GB", brand="MSI")


def test_ssd_and_hdd():
    assert normalize_specs("ssd", "SSD M2 Gigabyte 2000GB AORUS Gen4 7000E M2 NVMe") == {
        "capacity": 2000, "interface": "NVMe", "form_factor": "M.2", "pcie": "4.0"}
    assert normalize_specs("ssd", "SSD Adata 1TB SATAIII 2.5\"")["capacity"] == 1000
    hdd = normalize_specs("hdd", "Ext HDD Transcend 2TB StoreJet 25M3 2.5\" (TS2TSJ25M3S)")
    assert hdd == {"capacity": 2000, "form_factor": "2.5\"", "external": True}
    assert normalize_specs("hdd", "HDD 8TB Toshiba S300 HDWT380UZSVA 7200Rpm 256MB")["rpm"] == 7200


def test_motherboard():
    assert normalize_specs("motherboard", "MB ASUS AMD AM5 PRIME B650M-K DDR5 (90MB1F60-M0EAY0)") == {
        "socket": "AM5", "chipset": "B650", "form_factor": "mATX", "memory_type": "DDR5",
        "_inferred": {"form_factor": "board_size_by_chipset"}}
    specs = normalize_specs("motherboard", "MB Gigabyte AMD AM5 X870E AORUS ELITE X DDR5 WIFI7")
    assert specs["chipset"] == "X870E" and specs["wifi"] is True and "form_factor" not in specs


def test_monitor():
    specs = normalize_specs("monitor", "LG - 34\" 34U640B-B UltraWide Curved Monitor, VA, 5mc, 144Hz, WQHD (3440×1440)")
    assert specs == {"size": 34, "resolution": "3440x1440", "refresh_rate": 144, "panel": "VA", "curved": True}
    assert normalize_specs("monitor", "Titan Army - 25\" KG257H Monitor, Fast IPS, 340Hz, FHD")["resolution"] == "1920x1080"
    assert normalize_specs("monitor", "Titan Army - 49\" Curved, QD-OLED, 144Hz")["panel"] == "OLED"


def test_psu():
    specs = normalize_specs("psu", "Lian-Li SP850 850W SFX 80 Plus Gold Full Modular White")
    assert specs == {"power": 850, "certification": "Gold", "modular": "full", "form_factor": "SFX"}
    assert normalize_specs("psu", "Блок питание Deepcool PF450 (450W, 80+, APFC)")["certification"] == "80 PLUS"


def test_laptop():
    specs = normalize_specs("laptop", "ASUS ROG Strix G16 (Intel Core i7-14650HX/ DDR5 16GB/ SSD 1TB/ 16\" WUXGA 240Hz/ "
                                      "8GB RTX5050/ Backlit/ NoOS/ RU)")
    assert specs == {"cpu": "Core i7", "ram": 16, "storage": 1000, "screen": 16, "refresh_rate": 240, "gpu": "RTX 5050"}


def test_peripherals():
    assert normalize_specs("keyboard", "Клавиатура механическая беспроводная AULA F99 RGB") == {
        "connection": "wireless", "type": "mechanical", "rgb": True}
    assert normalize_specs("mouse", "Мышь игровая проводная AULA S80 (black)") == {
        "connection": "wired", "gaming": True, "color": "black"}
    assert normalize_specs("cooling", "Liquid cooler | Jonsbo TF 240 ARGB")["radiator"] == 240
    assert normalize_specs("cooling", "Кулер для процессора Redragon CC-1013 (12cm RGB Fan)")["type"] == "air"
    assert normalize_specs("speakers", "Акустические системы 2.1 | F380X (USB) | Мощность 54 Вт")["channels"] == "2.1"
    assert normalize_specs("case", "Поддержка E-ATX / ATX / Micro-ATX / Mini-ITX, Black")["board"] == "E-ATX"


def test_given_specs_are_normalized_and_unknown_dropped():
    # Values under dictionary keys (AI / seller) are normalized, invalid ones and AI-only keys never get in
    specs = normalize_specs("ram", "Some memory", {"capacity": "32 ГБ", "type": "ddr5", "form_factor": "So-Dimm",
                                                    "ecc": "maybe?", "voltage": "1.1V", "frequency": "abc"})
    assert specs == {"type": "DDR5", "form_factor": "SODIMM", "capacity": 32, "ecc": True}
    assert "gpu" not in normalize_specs("laptop", "HP 15 (Core i5)", {"gpu": "Intel UHD Graphics"})


def test_trace_counts_spellings():
    trace = new_trace()
    for text in ("A DDR4 16GB 3200MHz", "B DDR4 8GB 2666MHz", "C DDR4 16 ГБ 3200 МГц", "D DDR4 2x8GB 3200MHz"):
        normalize_specs("ram", text, trace=trace)
    assert set(trace[("ram", "capacity")]) == {"NGB", "N ГБ", "NxNGB"}


def test_specs_text_for_antifraud():
    assert specs_as_text("ram", {"type": "DDR5", "capacity": 16, "ecc": False, "rgb": True}) == "DDR5 16GB rgb"


def test_dictionary_is_consistent():
    for category, specs in DICTIONARY.items():
        keys = [s.key for s in specs]
        assert len(keys) == len(set(keys)), category
        assert set(CARD_SPECS.get(category, ())) <= set(keys), category
        for s in specs:
            assert (s.unit is not None) == (s.kind == NUMBER), (category, s.key)
            assert s.values is None or s.kind == CHOICE


def test_inferred_values_are_redone_not_trusted_and_lose_to_written():
    first = normalize_specs("ram", "Lexar DDR5 16GB 5600MHz")
    # The same specs coming back (preview -> publish) stay inferred, not "written by the seller"
    assert normalize_specs("ram", "Lexar DDR5 16GB 5600MHz", first) == first
    # Another store wrote SODIMM: the written value replaces the inferred one on the card
    card = merge_specs(first, normalize_specs("ram", "Lexar DDR5 16GB 5600MHz SO-DIMM"))
    assert card["form_factor"] == "SODIMM" and "_inferred" not in card
    # A written value is never replaced by an inferred one
    assert merge_specs(card, first) == card


def test_antifraud_text_ignores_inferred():
    specs = normalize_specs("cpu", "проц i5 12400f б/у")
    assert specs_as_text("cpu", specs) == "Core i5"


def test_every_inference_has_a_hint_text():
    import json
    from pathlib import Path
    ru = json.loads((Path(__file__).parents[2] / "frontend/src/locales/ru.json").read_text(encoding="utf-8"))
    assert {r.rule_id for r in INFERENCES} <= set(ru["specs"]["inferred"])


def test_cyrillic_ddr_from_posts():
    assert normalize_specs("ram", "озу 16гб ддр4 3200")["type"] == "DDR4"
