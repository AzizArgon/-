import pytest

from app.services.rule_parser import parse_by_rules

CASES = [
    ("Intel-Core i7 - 12700КF, 3.2 GHz, 25MB, oem, LGA1700, Alder Lake", "cpu", "Intel Core i7-12700KF OEM"),
    ("AMD Ryzen™ 5 Raphael 7500F - 3.7 GHz, 6 cores/12 threads, No GPU, AM5 (100-000000597)", "cpu",
     "AMD Ryzen 5 7500F"),
    ("Teamgroup DDR5 64GB 6000MHz (32*2) RGB", "ram", "Teamgroup DDR5 64GB 6000MHz (2x32GB) RGB"),
    ("SSD M.2 Hiksemi 512GB NVMe", "ssd", "SSD Hiksemi 512GB NVMe"),
    ("MB ASUS AMD AM5 TUF GAMING B850-PLUS WIFI7 DDR5 (90MB1J30-M0EAY0)", "motherboard",
     "ASUS TUF GAMING B850-PLUS WIFI7 DDR5"),
    ("MSI - 8GB GeForce RTX5050 VENTUS 2X OC (912-V538-002)", "gpu", "MSI GeForce RTX 5050 VENTUS 2X OC 8GB"),
    ('ASUS - 24" TUF Gaming VG249QM1A Gaming Monitor, FHD (1920x1080), Fast IPS, 270Hz', "monitor",
     'ASUS TUF Gaming VG249QM1A 24"'),
]


@pytest.mark.parametrize("name,category,expected", CASES)
def test_neat_rows(name, category, expected):
    result = parse_by_rules(name)
    assert result["category"] == category
    assert result["name"] == expected


def test_contradictions_are_not_fixed():
    # GTX 3050 does not exist, DDR5 vs DDR4: kept as written for Anti-Fraud
    assert "GTX 3050" in parse_by_rules("OCPC - 8GB GeForce GTX3050 128Bits GDDR6 (OCVN3050G8XM)")["name"]
    assert parse_by_rules("KingBank DDR5 8GB 6000MHz Silver Heatsink")["specs"]["type"] == "DDR5"


@pytest.mark.parametrize("name", [
    "проц i5 12400f б/у",  # slang and condition: AI decides
    "Ext SSD M.2 2TB Kingston XS2000 (Portable)",  # unusual order
    "Мышь Logitech G102 Lightsync черная",  # no rule for this category
])
def test_unclear_rows_go_to_ai(name):
    assert parse_by_rules(name) is None
