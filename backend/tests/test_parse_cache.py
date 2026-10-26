"""Parse cache: weak AI answers are not remembered, publish caches seller edits, a row can be re-parsed without cache."""

import asyncio
import json

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import Currency, ImportStatus, ParseCache, PriceImport, Store, User
from app.db.seed import seed_categories
from app.services import ai_parser
from app.services.importer import parse_clean_rows, publish_import, reparse_row
from app.services.price_cleaner import CleanRow, cache_key

TFORCE = "T-FORCE DELTA RGB DDR5 — 32GB | Частота: 6000 МГц"
KINGSTON = "Kingston Fury Beast 16GB DDR5 5600"
GOOD = {"c": "ram", "b": "TeamGroup", "m": "T-Force Delta RGB DDR5", "n": "TeamGroup T-Force Delta RGB DDR5 32GB"}
WEAK = {"c": "other", "n": "T-FORCE DELTA RGB DDR5 — 32GB"}


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda c, _: c.create_function("py_lower", 1, lambda s: s and s.lower()))
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        seed_categories(session)
        yield session


@pytest.fixture
def ai(monkeypatch):
    """Fake Gemini: answers[row text] -> item without "i"; calls are counted."""
    state = {"answers": {}, "calls": 0}

    async def fake_gemini(model, text):
        state["calls"] += 1
        items = []
        for line in text.splitlines():
            if "|" in line and not line.startswith("#"):
                row, row_text = line.split("|", 1)
                if row_text in state["answers"]:
                    items.append({"i": int(row), **state["answers"][row_text]})
        return json.dumps(items), False

    async def no_groq(text):
        raise RuntimeError("no Groq in tests")

    monkeypatch.setattr(ai_parser, "_call_gemini", fake_gemini)
    monkeypatch.setattr(ai_parser, "_call_groq", no_groq)
    monkeypatch.setattr(ai_parser.settings, "groq_api_key", "")
    monkeypatch.setattr(ai_parser, "_exhausted_on", {})
    monkeypatch.setattr(ai_parser, "_gemini_limiter", ai_parser.RateLimiter(1000))
    return state


def _row(n: int, text: str, price: float = 100) -> CleanRow:
    return CleanRow(row=n, sheet="", section="", cells=[text], name=text, price=price, is_in_stock=True, ai_text=text)


def _cached(db, text: str) -> ParseCache | None:
    return db.scalar(select(ParseCache).where(ParseCache.key == cache_key(text)))


def _import(db, rows: list[dict]) -> tuple[Store, PriceImport]:
    store = Store(owner=User(email="s@example.com", password_hash="x"), name="S")
    db.add(store)
    db.commit()
    imp = PriceImport(store_id=store.id, filename="p.xlsx", currency=Currency.USD, status=ImportStatus.ready,
                      rows_json=rows)
    db.add(imp)
    db.commit()
    return store, imp


def test_weak_ai_answer_is_not_cached(db, ai):
    ai["answers"] = {TFORCE: WEAK, KINGSTON: {"c": "ram", "b": "Kingston", "n": KINGSTON}}
    rows = asyncio.run(parse_clean_rows(db, [_row(1, TFORCE), _row(2, KINGSTON)], {}))
    assert [r["category"] for r in rows] == ["other", "ram"]
    assert _cached(db, TFORCE) is None and _cached(db, KINGSTON).data["brand"] == "Kingston"

    # Next upload: the weak row goes to the AI again (and gets a better answer), the good one comes from the cache
    ai["answers"][TFORCE] = GOOD
    again = asyncio.run(parse_clean_rows(db, [_row(1, TFORCE), _row(2, KINGSTON)], {}))
    assert [(r["source"], r["category"]) for r in again] == [("ai", "ram"), ("cache", "ram")]
    assert ai["calls"] == 2


def test_publish_caches_seller_edits_but_not_failed_defaults(db, ai, monkeypatch):
    async def no_ai(model, text):
        raise RuntimeError("no key")

    monkeypatch.setattr(ai_parser, "_call_gemini", no_ai)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(ai_parser.asyncio, "sleep", lambda *_: real_sleep(0))
    parsed = asyncio.run(parse_clean_rows(db, [_row(1, TFORCE), _row(2, KINGSTON)], {}))
    assert {r["source"] for r in parsed} == {"failed"}
    store, imp = _import(db, parsed)

    # The seller fixed only Kingston; T-FORCE is published with the defaults of a failed row
    published = [dict(r) for r in parsed]
    published[1].update(category="ram", brand="Kingston")
    publish_import(db, imp, store, published)
    assert _cached(db, TFORCE) is None
    entry = _cached(db, KINGSTON)
    assert entry.source == "seller" and entry.data["category"] == "ram"


def test_seller_edit_overwrites_a_wrong_cache_entry(db, ai):
    db.add(ParseCache(key=cache_key(TFORCE), data={"category": "gpu", "brand": "Zotac", "name": "x"}, source="ai"))
    db.commit()
    parsed = asyncio.run(parse_clean_rows(db, [_row(1, TFORCE)], {}))
    assert parsed[0]["source"] == "cache" and parsed[0]["category"] == "gpu"
    store, imp = _import(db, parsed)
    fixed = [{**parsed[0], "category": "ram", "brand": "TeamGroup"}]
    publish_import(db, imp, store, fixed)
    entry = _cached(db, TFORCE)
    assert (entry.source, entry.data["category"], entry.data["brand"]) == ("seller", "ram", "TeamGroup")


def test_reparse_row_skips_the_cache(db, ai):
    db.add(ParseCache(key=cache_key(TFORCE), data={"category": "other", "brand": None, "name": TFORCE}, source="seller"))
    db.commit()
    ai["answers"] = {KINGSTON: {"c": "ram", "b": "Kingston", "n": KINGSTON}}
    parsed = asyncio.run(parse_clean_rows(db, [_row(1, TFORCE), _row(2, KINGSTON, 60)], {}))
    assert parsed[0]["source"] == "cache" and ai["calls"] == 1  # Kingston only
    _, imp = _import(db, parsed)

    ai["answers"][TFORCE] = GOOD
    new = asyncio.run(reparse_row(db, imp, parsed[0]))
    assert (new["source"], new["category"], new["brand"]) == ("ai", "ram", "TeamGroup")
    assert new["price"] == 100 and "flags" in new  # price from the file, Anti-Fraud done
    assert _cached(db, TFORCE).data["category"] == "ram"  # the wrong entry is replaced
    db.refresh(imp)
    assert imp.rows_json[0]["category"] == "ram" and imp.rows_json[1]["raw_name"] == KINGSTON


def test_reparse_not_a_product(db, ai):
    parsed = [{"row": 1, "raw_name": "Доставка по городу", "name": "Доставка по городу", "price": 5,
               "ai_text": "Доставка по городу", "cache_key": cache_key("Доставка по городу"), "source": "failed"}]
    _, imp = _import(db, parsed)
    assert asyncio.run(reparse_row(db, imp, parsed[0])) is None
