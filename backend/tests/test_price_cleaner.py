from app.services.price_cleaner import clean_markdown, make_chunks

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


def test_chunks_repeat_context():
    rows = clean_markdown(SAMPLE)
    chunks = make_chunks(rows, 2)
    assert len(chunks) == 3
    assert chunks[1].startswith("# Sheet: CPU, DDR, HDD / Section: DDR")
    assert "r3 | KingBank DDR5" in chunks[1]
