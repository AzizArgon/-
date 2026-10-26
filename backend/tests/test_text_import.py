"""'Paste as text': Telegram posts -> rows -> the import pipeline, with recorded AI answers (no live requests)."""

import asyncio
import json
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import Currency, ImportStatus, Offer, PriceImport, Store, User
from app.db.seed import seed_categories
from app.services import ai_parser
from app.services.importer import parse_clean_rows, publish_import
from app.services.text_import import find_price, text_to_rows

POSTS = json.loads((Path(__file__).parent / "fixtures" / "telegram_posts.json").read_text(encoding="utf-8"))["posts"]


@pytest.mark.parametrize("post", POSTS, ids=lambda p: p["text"].splitlines()[1][:20])
def test_posts_are_cleaned_and_priced_per_line(post):
    rows = text_to_rows(post["text"])
    assert [[r.name, r.price, r.currency, r.currency_check] for r in rows] == post["expected"]
    assert all(r.is_in_stock for r in rows)


@pytest.mark.parametrize("line, price, currency, check", [
    ("Монитор 27 LG 1.2 млн", 1_200_000, "UZS", False),
    ("Кулер — 280 тыс. сум", 280_000, "UZS", False),
    ("Корпус Zalman $40", 40, "USD", False),
    ("Мышь G102 - 25", 25, "USD", True),  # no currency: a small number is dollars, the seller is asked to check
    ("Мышь G102 25 sum", 25, "UZS", False),
    ("ddr4-3200 16gb", None, None, False),  # a frequency, not a price
])
def test_find_price(line, price, currency, check):
    assert find_price(line)[:3] == (price, currency, check)


def test_adverts_and_contacts_are_not_products():
    text = "🔥 Акция!\nДоставка по городу 30 000 сум\nтел 90-123-45-67\n#пк\nhttps://t.me/shop\ni3 12100f — 80$"
    assert [r.name for r in text_to_rows(text)] == ["i3 12100f"]


def test_price_on_the_next_line():
    rows = text_to_rows("Монитор Samsung 24\"\nЦена: 1 300 000 сум")
    assert [(r.name, r.price, r.currency) for r in rows] == [("Монитор Samsung 24\"", 1_300_000, "UZS")]


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda c, _: c.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        seed_categories(session)
        yield session


@pytest.fixture
def recorded_ai(monkeypatch):
    """Answers the AI request with the recorded items of the current post."""
    answer: list[dict] = []

    async def fake_gemini(model, text):
        ids = {int(m) for m in re.findall(r"^(\d+)\|", text, re.MULTILINE)}
        return json.dumps([it for it in answer if it["i"] in ids]), False

    async def no_groq(text):
        raise AssertionError("Groq must not be called")

    monkeypatch.setattr(ai_parser, "_call_gemini", fake_gemini)
    monkeypatch.setattr(ai_parser, "_call_groq", no_groq)
    monkeypatch.setattr(ai_parser, "_exhausted_on", {})
    monkeypatch.setattr(ai_parser, "_gemini_limiter", ai_parser.RateLimiter(1000))
    monkeypatch.setattr(ai_parser, "_groq_limiter", ai_parser.RateLimiter(1000))
    return answer


def _parse(db, post, answer):
    answer[:] = post["ai"]
    return asyncio.run(parse_clean_rows(db, text_to_rows(post["text"]), {}))


def test_pipeline_keeps_currency_per_line(db, recorded_ai):
    rows = _parse(db, POSTS[0], recorded_ai)
    assert len(rows) == 4 and not any(r["source"] == "failed" for r in rows)
    assert [r["currency"] for r in rows] == ["USD", "USD", "USD", "UZS"]
    cpu = next(r for r in rows if r["category"] == "cpu")
    assert cpu["condition"] == "used" and cpu["price"] == 110


def test_text_publish_keeps_other_goods_in_stock(db, recorded_ai):
    store = Store(owner=User(email="s@example.com", password_hash="x"), name="S")
    db.add(store)
    db.commit()
    old = PriceImport(store_id=store.id, filename="p.xlsx", currency=Currency.USD, status=ImportStatus.ready)
    db.add(old)
    db.commit()
    publish_import(db, old, store, [{"row": 1, "raw_name": "Lexar DDR4 8GB", "category": "ram", "name": "Lexar DDR4 8GB",
                                     "price": 20, "condition": "new", "specs": {}, "is_in_stock": True}])

    rows = _parse(db, POSTS[0], recorded_ai)
    imp = PriceImport(store_id=store.id, filename="post", source="text", currency=Currency.UZS, status=ImportStatus.ready)
    db.add(imp)
    db.commit()
    stats = publish_import(db, imp, store, rows)
    assert stats == {"created": 4, "updated": 0, "out_of_stock": 0}
    offers = {o.raw_name: o for o in db.scalars(select(Offer))}
    assert offers["Lexar DDR4 8GB"].is_in_stock
    assert offers["i5 12400f б/у"].currency == Currency.USD and offers["SSD 1TB Samsung 980"].currency == Currency.UZS


def test_text_updates_the_store_offer_on_the_same_card(db, recorded_ai):
    store = Store(owner=User(email="s@example.com", password_hash="x"), name="S")
    db.add(store)
    db.commit()
    first = PriceImport(store_id=store.id, filename="p.xlsx", currency=Currency.UZS, status=ImportStatus.ready)
    db.add(first)
    db.commit()
    publish_import(db, first, store, [{"row": 1, "raw_name": "Intel Core i5-12400F", "category": "cpu", "brand": "Intel",
                                       "name": "Intel Core i5-12400F", "price": 1_430_000, "condition": "new",
                                       "specs": {}, "is_in_stock": True}])
    imp = PriceImport(store_id=store.id, filename="post", source="text", currency=Currency.UZS, status=ImportStatus.ready)
    db.add(imp)
    db.commit()
    stats = publish_import(db, imp, store, _parse(db, POSTS[0], recorded_ai))
    assert stats["updated"] == 1 and stats["created"] == 3
    cpu = db.scalars(select(Offer).where(Offer.price == 110)).one()
    assert cpu.currency == Currency.USD and len(cpu.price_history) == 2


CARDS = json.loads((Path(__file__).parent / "fixtures" / "telegram_posts.json").read_text(encoding="utf-8"))["cards"]


@pytest.mark.parametrize("post", CARDS, ids=lambda p: p["title"])
def test_card_post_is_one_product(db, recorded_ai, post):
    rows = _parse(db, post, recorded_ai)
    assert len(rows) == 1
    row, want = rows[0], post["expected"]
    assert (row["name"], row["category"], row["condition"], row["price"], row["currency"]) == (
        want["name"], want["category"], want["condition"], want["price"], want["currency"])
    specs = {k: v for k, v in row["specs"].items() if not k.startswith("_")}
    assert specs == want["specs"]  # chips and timings are not in the dictionary: dropped
    assert sorted(row["specs"].get("_inferred", {})) == want["inferred"]


def test_bilingual_card_keeps_one_language_and_skips_adverts():
    row = text_to_rows(CARDS[0]["text"])[0]
    assert row.price == 950_000 and row.condition == "used"
    assert not any("Holati" in c or "Hajmi" in c or "Доставка" in c or "Фергане" in c or "@" in c for c in row.cells)
    assert row.cells[0].startswith("Комплект оперативной памяти Corsair")


@pytest.mark.parametrize("line, price", [("Цена: 950.000 сум", 950_000), ("Narxi: 950 000 so'm", 950_000),
                                         ("Narxi: 1.250.000 so’m", 1_250_000), ("Монитор 1.2 млн", 1_200_000)])
def test_sum_thousand_separators(line, price):
    assert find_price(line)[:2] == (price, "UZS")


def test_uzbek_words():
    from app.services.text_import import uz_to_ru
    assert uz_to_ru("Holati: B/U, 2x8 GB to’plam, Narxi: 950 000 so'm") == "состояние: б/у, 2x8 GB комплект, цена: 950 000 so'm"


def test_list_is_not_a_card():
    assert len(text_to_rows(POSTS[2]["text"])) == 3  # "Цена:" on its own line is still a list


def test_any_layout_with_one_price_is_one_card():
    row, = text_to_rows(CARDS[3]["text"])
    assert (row.price, row.currency, row.category_hint) == (190, "USD", "ram")
    assert row.name.startswith("Trident Z Royal DDR4 32GB")
    text = " ".join(row.cells).lower()
    assert not any(w in text for w in ("гарант", "рассрочк", "uzum", "998", "t.me", "админ", "@"))


@pytest.mark.parametrize("line", ["Цена : 190 У.Е", "Цена: 190 у.е.", "190 уе", "190 USD"])
def test_dollar_spellings(line):
    assert find_price(line)[:2] == (190, "USD")


BENCH_POSTS = json.loads((Path(__file__).parent / "benchmark" / "posts" / "posts.json").read_text(encoding="utf-8"))["posts"]


@pytest.mark.parametrize("post", BENCH_POSTS, ids=lambda p: p["id"])
def test_benchmark_posts_code_fields(post):
    """Price, currency, condition and "model not specified" are read by code: checked on every labelled post."""
    from app.services.text_import import no_rows_reason
    rows = text_to_rows(post["text"])
    if post["expected"] == "no_model":
        assert rows == [] and no_rows_reason(post["text"]) == "no_model"
        return
    got = [(r.price, r.currency, r.condition, r.currency_check) for r in rows]
    assert got == [(e["price"], e["currency"], e["condition"], e.get("currency_check", False)) for e in post["expected"]]


def test_telegram_copy_is_split_into_posts_without_service_lines():
    text = ("[25.10.2026 17:58] Продавец 1:\nПереслано из PC Store\n[ 3 фото ]\n\nAMD Ryzen 5 5600\nЦЕНА: 120$\n"
            "[25.10.2026 19:11] Продавец 2: [ 2 фото ]\n\nKingston Fury DDR4 16GB\nЦена: 40$")
    rows = text_to_rows(text)
    assert [(r.name, r.price) for r in rows] == [("AMD Ryzen 5 5600", 120), ("Kingston Fury DDR4 16GB", 40)]
    assert not any("фото" in c or "Переслано" in c or "Продавец" in c for r in rows for c in r.cells)


@pytest.mark.parametrize("text, price, note", [
    ("AMD Ryzen 5 5600\nЦЕНА:120У.Е. 115У.Е.", 115, "ЦЕНА:120У.Е. 115У.Е"),  # old -> new
    ("Intel Core i5-3330\n💵 Цена: 15$\n🔥 Подписчикам 13$🔥", 15, "Подписчикам 13$"),  # regular + discount
    ("Монитор LG 24GN60R\nОпт: 100$\nРозница: 110$", 110, "Опт: 100$"),  # wholesale is a note
])
def test_two_prices_are_one_product(text, price, note):
    row, = text_to_rows(text)
    assert (row.price, row.note) == (price, note)


@pytest.mark.parametrize("line, price, currency", [
    ("Цена 140.000", 140_000, "UZS"), ("Цена 140", 140, "USD"), ("Narxi: 1 250 000", 1_250_000, "UZS")])
def test_price_without_currency_by_size(line, price, currency):
    assert find_price(line)[:3] == (price, currency, True)


@pytest.mark.parametrize("line", ["Тел: 903339966", "+998999957866", "6pin 100 ват", "⚡ 192-bit", "Furmark 10 minut 68-69°",
                                  "8/16", "32мб кеш", "Осталось 1шт"])
def test_noise_numbers_are_not_prices(line):
    assert text_to_rows(f"AMD Ryzen 7 8700F\n{line}") == []


@pytest.mark.parametrize("text, condition", [
    ("б/у", "used"), ("бу, рабочая", "used"), ("used", "used"), ("ishlatilgan", "used"), ("Холати: ишлатилган", "used"),
    ("новый", "new"), ("в плёнке", "new"), ("запечатан", "new"), ("yangi", "new"), ("Состояние новое, openbox", "new_openbox"),
    ("open box", "new_openbox"), ("коробка вскрыта", "new_openbox"), ("восстановленный", "refurbished"),
    ("Полностью обслужена, не шумит", "unknown"), ("полностью рабочий", "unknown"), ("Holati zor", "unknown"),
    ("Гарантия неделя, Furmark 10 минут", "unknown"), ("как новая", "unknown"),
])
def test_condition_only_from_explicit_words(text, condition):
    from app.services.text_import import condition_of
    assert condition_of(text) == condition


def test_compared_model_is_not_a_second_product():
    row, = text_to_rows("Процессор\nAMD Ryzen 5 5600\n6/12\nПизже i5-12400f\nЦЕНА:115$")
    assert row.name == "AMD Ryzen 5 5600" and not any("12400" in c for c in row.cells)


def test_uzbek_cyrillic_words():
    row, = text_to_rows("Axle Gtx 1650 Super 4gb\nҲолати: янги\nНархи 99$")
    assert (row.price, row.currency, row.condition) == (99, "USD", "new")


def test_disk_in_terabytes_is_hdd_and_t_force_is_teamgroup():
    from app.services.spec_normalizer import canonical_brand
    row, = text_to_rows("3 tb Hitachi\nЦена: 42$")
    assert row.category_hint == "hdd"
    assert canonical_brand("T-Force") == "TeamGroup" and canonical_brand("Axle") == "Axle"


@pytest.mark.parametrize("text, reason", [
    ("Топовая видюха, пишите в лс", "no_model"), ("Продаю комп, цена договорная", "no_model"),
    ("RTX 3060 Ventus 12GB, торг", "no_prices")])
def test_no_rows_reason(text, reason):
    from app.services.text_import import no_rows_reason
    assert text_to_rows(text) == [] and no_rows_reason(text) == reason


def test_card_without_model_is_not_a_product():
    assert text_to_rows("Продаю видеокарту, состояние отличное\nЦена: 150$") == []


def test_condition_line_with_warranty_is_kept():
    # "гарантия" is an advert word, but this line is the only one that says the card is new
    post = "Видеокарта MSI GeForce RTX 4060 Ti VENTUS 2X 8G OC\n✅ Состояние: новая, в коробке, гарантия 1 год\n" \
           "💰 Цена: 4 950 000 сум\nГарантия, доставка — звоните +998 90 000 00 00"
    [row] = text_to_rows(post)
    assert row.condition == "new"
    assert "доставка" not in row.ai_text
