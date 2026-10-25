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
from app.services.text_import import find_price, text_title, text_to_rows

POSTS = json.loads((Path(__file__).parent / "fixtures" / "telegram_posts.json").read_text(encoding="utf-8"))["posts"]


@pytest.mark.parametrize("post", POSTS, ids=lambda p: p["text"].splitlines()[1][:20])
def test_posts_are_cleaned_and_priced_per_line(post):
    rows = text_to_rows(post["text"], post["default_currency"])
    assert [[r.name, r.price, r.currency, r.currency_check] for r in rows] == post["expected"]
    assert all(r.is_in_stock for r in rows)


@pytest.mark.parametrize("line, price, currency, check", [
    ("Монитор 27 LG 1.2 млн", 1_200_000, "UZS", False),
    ("Кулер — 280 тыс. сум", 280_000, "UZS", False),
    ("Корпус Zalman $40", 40, "USD", False),
    ("Мышь G102 - 25", 25, "UZS", True),  # no currency: the default one, the seller is asked to check
    ("Мышь G102 25 sum", 25, "UZS", False),
    ("ddr4-3200 16gb", None, None, False),  # a frequency, not a price
])
def test_find_price(line, price, currency, check):
    assert find_price(line, "UZS")[:3] == (price, currency, check)


def test_adverts_and_contacts_are_not_products():
    text = "🔥 Акция!\nДоставка по городу 30 000 сум\nтел 90-123-45-67\n#пк\nhttps://t.me/shop\ni3 12100f — 80$"
    assert [r.name for r in text_to_rows(text, "USD")] == ["i3 12100f"]
    assert text_title(text) == "i3 12100f"


def test_price_on_the_next_line():
    rows = text_to_rows("Монитор Samsung 24\"\nЦена: 1 300 000 сум", "USD")
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
    return asyncio.run(parse_clean_rows(db, text_to_rows(post["text"], post["default_currency"]), {}))


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
