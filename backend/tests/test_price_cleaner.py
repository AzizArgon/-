import pytest

from app.services.price_cleaner import cache_key, clean_markdown, parse_price

SAMPLE = """## CPU, DDR, HDD
| CPU | Unnamed: 1 | опт |
| --- | --- | --- |
| Intel-Core i3 - 12100F, 3.3 GHz, oem | i3-12100F | 87 |
| Intel-Core i3 - 13100F, 3.4 GHz, oem | i3-13100F | NaN |
| NaN | NaN | NaN |
| DDR | NaN | опт |
| KingBank DDR5 8GB 6000MHz Silver Heatsink | KJXS DDR4 6000MHz 8GB UDIMM | 140 |
| Блоки питания | NaN | NaN |
| ID Cooling SE-224-XTS | NaN | NaN |
## Fenda
| NaN | наименование | NaN | характеристики | цена |
| --- | --- | --- | --- | --- |
| Колонки | F&D T-60X | NaN | {specs} | 55 |
## Export
| Intel-Core i3 - 12100F, 3.3 GHz, oem | i3-12100F | 87, |
""".replace("{specs}", "Мощность 2,2 Вт; " * 30)


def test_cleanup_rules():
    rows = clean_markdown(SAMPLE)
    names = [r.cells[0] for r in rows]
    # Export sheet is a duplicate, empty and header rows are dropped
    assert names == [
        "Intel-Core i3 - 12100F, 3.3 GHz, oem",
        "Intel-Core i3 - 13100F, 3.4 GHz, oem",
        "KingBank DDR5 8GB 6000MHz Silver Heatsink",
        "ID Cooling SE-224-XTS",
        "Колонки",
    ]
    assert all("NaN" not in c and "Unnamed" not in c for r in rows for c in r.cells)
    # Subheaders set the section for the rows below
    assert [r.section for r in rows] == ["CPU", "CPU", "DDR", "Блоки питания", ""]
    # Long specs column is truncated
    assert len(rows[-1].cells[2]) <= 120


def test_raw_name_ignores_price():
    rows = clean_markdown(SAMPLE)
    assert rows[0].raw_name == "Intel-Core i3 - 12100F, 3.3 GHz, oem | i3-12100F"


def test_price_article_and_stock_come_from_columns():
    rows = clean_markdown(SAMPLE)
    cpu, no_price, kingbank, _, speakers = rows
    assert (cpu.price, cpu.article, cpu.is_in_stock) == (87, "i3-12100F", True)
    assert (no_price.price, no_price.is_in_stock) == (None, False)
    assert kingbank.article == "KJXS DDR4 6000MHz 8GB UDIMM"
    # Header "наименование ... цена": name and price by column, specs never reach the AI
    assert (speakers.name, speakers.price) == ("F&D T-60X", 55)
    assert "Мощность" not in speakers.ai_text


@pytest.mark.parametrize("text,value", [
    ("1 250 000", 1250000), ("61.0", 61), ("35,", 35), ("$120", 120), ("1,250,000", 1250000),
    ("12,5", 12.5), ("NaN", None), ("0", None), ("i3-12100F", None),
])
def test_parse_price(text, value):
    assert parse_price(text) == value


def test_cache_key_ignores_case_and_punctuation():
    assert cache_key("Lexar DDR4 8GB, 3200MHz!") == cache_key("lexar  ddr4 8gb 3200mhz")


def test_second_price_column_is_used_when_wholesale_is_empty():
    md = """## Sharkoon
| NaN | NaN | наименование | NaN | Розница | опт |
| --- | --- | --- | --- | --- | --- |
| Sharkoon | Игровая мышь | Mouse Sharkoon Light 180 black | NaN | NaN | 10 |
| Sharkoon | Игровая мышь | Mouse Sharkoon Force II | NaN | 12 | 11 |
| Sharkoon | Игровая мышь | Mouse Sharkoon Light 200 | NaN | 15 | NaN |
| Gigabyte | MB Gigabyte B850 EAGLE | 4719331871239 | NaN | NaN | NaN |
"""
    rows = clean_markdown(md)
    # wholesale preferred, retail as fallback, a barcode is never a price
    assert [r.price for r in rows] == [10, 11, 15, None]
