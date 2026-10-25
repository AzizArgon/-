"""Manual adding: "find in the catalog" offers and new cards by the dictionary."""

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import Category, Condition, Currency, Offer, PriceHistory, PriceImport, Product, Store, User
from app.db.seed import seed_categories
from app.services import manual
from app.services.catalog import product_card
from app.services.importer import publish_import
from app.services.spec_normalizer import INFERRED


@pytest.fixture(autouse=True)
def no_rate(monkeypatch):
    monkeypatch.setattr(manual, "get_usd_rate", lambda db: None)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda c, _: c.execute("PRAGMA foreign_keys=ON"))
    event.listen(engine, "connect", lambda c, _: c.create_function("py_lower", 1, lambda s: s and s.lower()))
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        seed_categories(session)
        yield session


def _store(db, email):
    store = Store(owner=User(email=email, password_hash="x"), name=email)
    db.add(store)
    db.commit()
    return store


def _cpu_row(n, name, price):
    return {"row": n, "raw_name": name, "category": "cpu", "brand": "Intel", "name": name, "price": price,
            "condition": "new", "specs": {}, "is_in_stock": True}


@pytest.fixture
def catalog(db):
    """Store A published a price list with i5-12400F and a RAM stick."""
    a = _store(db, "a@example.com")
    imp = PriceImport(store_id=a.id, filename="p.xlsx", currency=Currency.USD)
    db.add(imp)
    db.commit()
    publish_import(db, imp, a, [_cpu_row(1, "Intel Core i5-12400F OEM", 120), _cpu_row(2, "Intel Core i3-12100F OEM", 80)])
    return a


def test_suggest_understands_short_queries_and_shows_my_offer(db, catalog):
    b = _store(db, "b@example.com")
    found = manual.suggest_products(db, b, "12400f")
    assert [p["name"] for p in found] == ["Intel Core i5-12400F OEM"]
    assert found[0]["category"] == "cpu" and found[0]["my_offer"] is None
    assert {s["key"] for s in found[0]["specs"]} <= {"series", "socket", "cores"}
    assert len(manual.suggest_products(db, b, "процессор i5")) == 1
    assert manual.suggest_products(db, catalog, "12400f")[0]["my_offer"]["price"] == 120


def test_add_offer_then_update_without_duplicate(db, catalog):
    b = _store(db, "b@example.com")
    product = db.scalar(select(Product).where(Product.normalized_name == "Intel Core i5-12400F OEM"))
    first = manual.save_offer(db, b, product, 1_500_000, Currency.UZS, Condition.used, True)
    assert first["created"] is True
    second = manual.save_offer(db, b, product, 1_450_000, Currency.UZS, Condition.used, True)
    assert second["created"] is False
    offers = db.scalars(select(Offer).where(Offer.store_id == b.id)).all()
    assert len(offers) == 1 and offers[0].price == 1_450_000
    assert len(db.scalars(select(PriceHistory).where(PriceHistory.offer_id == offers[0].id)).all()) == 2
    sources = db.scalars(select(PriceImport.source).where(PriceImport.store_id == b.id)).all()
    assert sources == ["manual", "manual"]
    card = product_card(db, product.id, None)
    assert {o["store"]["name"] for o in card["offers"]} == {"a@example.com", "b@example.com"}


def test_manual_offer_does_not_touch_other_offers(db, catalog):
    product = db.scalar(select(Product).where(Product.normalized_name == "Intel Core i5-12400F OEM"))
    manual.save_offer(db, catalog, product, 115, Currency.USD, Condition.new, True)
    assert all(o.is_in_stock for o in db.scalars(select(Offer).where(Offer.store_id == catalog.id)))


def test_offer_far_below_market_is_flagged(db, catalog):
    b = _store(db, "b@example.com")
    product = db.scalar(select(Product).where(Product.normalized_name == "Intel Core i5-12400F OEM"))
    manual.save_offer(db, _store(db, "c@example.com"), product, 125, Currency.USD, Condition.new, True)
    result = manual.save_offer(db, b, product, 40, Currency.USD, Condition.new, True)
    assert "price_below_market" in {f["type"] for f in result["flags"]}


def test_create_card_by_dictionary(db, catalog):
    b = _store(db, "b@example.com")
    ram = db.scalar(select(Category).where(Category.slug == "ram"))
    product, created = manual.create_product(
        db, b, ram, "Kingston", "KF560C36BBE-16", "Kingston Fury Beast DDR5 16GB 6000MHz",
        {"type": "DDR5", "capacity": "16", "frequency": 6000, "form_factor": "DIMM", "unknown": "x", "ecc": None},
    )
    assert created and product.manual_store_id == b.id
    assert product.specs_json["type"] == "DDR5" and product.specs_json["capacity"] == 16
    assert "unknown" not in product.specs_json
    assert "form_factor" not in product.specs_json.get(INFERRED, {})  # chosen by the seller, not inferred

    again, created = manual.create_product(db, b, ram, "Kingston", None, "Kingston Fury Beast DDR5 16GB 6000MHz", {})
    assert not created and again.id == product.id


def test_create_card_that_exists_returns_it(db, catalog):
    cpu = db.scalar(select(Category).where(Category.slug == "cpu"))
    existing, created = manual.create_product(db, catalog, cpu, "Intel", None, "Процессор Intel Core i5-12400F OEM", {})
    assert not created and existing.normalized_name == "Intel Core i5-12400F OEM"
