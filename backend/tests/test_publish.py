import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import Currency, ImportStatus, Offer, PriceImport, Product, Store, User
from app.db.seed import seed_categories
from app.services.importer import publish_import


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda c, _: c.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        seed_categories(session)
        yield session


def _row(n, name, price, raw=None):
    return {"row": n, "raw_name": raw or name, "category": "ram", "name": name, "price": price,
            "condition": "new", "specs": {}, "is_in_stock": price is not None}


def _store(db, email):
    user = User(email=email, password_hash="x")
    store = Store(owner=user, name=email)
    db.add(store)
    db.commit()
    return store


def _import(db, store, currency=Currency.USD):
    imp = PriceImport(store_id=store.id, filename="p.xlsx", currency=currency, status=ImportStatus.ready)
    db.add(imp)
    db.commit()
    return imp


def test_reimport_updates_prices_and_marks_missing_out_of_stock(db):
    store = _store(db, "a@example.com")
    rows = [_row(1, "Lexar DDR4 8GB 3200MHz", 58), _row(2, "Kingston DDR5 32GB", None)]
    stats = publish_import(db, _import(db, store), store, rows)
    assert stats == {"created": 2, "updated": 0, "out_of_stock": 0}
    no_price = db.scalar(select(Offer).where(Offer.raw_name == "Kingston DDR5 32GB"))
    assert no_price.is_in_stock is False  # no price in the file -> out of stock

    stats = publish_import(db, _import(db, store), store, [_row(1, "Lexar DDR4 8GB 3200MHz", 55)])
    assert stats == {"created": 0, "updated": 1, "out_of_stock": 0}
    lexar = db.scalar(select(Offer).where(Offer.raw_name == "Lexar DDR4 8GB 3200MHz"))
    assert lexar.price == 55
    assert [h.price for h in lexar.price_history] == [58, 55]

    stats = publish_import(db, _import(db, store), store, [_row(1, "Kingston DDR5 32GB", 300)])
    assert stats["out_of_stock"] == 1
    assert lexar.is_in_stock is False


def test_same_product_from_two_stores_shares_one_card(db):
    a, b = _store(db, "a@example.com"), _store(db, "b@example.com")
    publish_import(db, _import(db, a), a, [_row(1, "Lexar DDR4 8GB 3200MHz", 58, raw="Lexar DDR4 8GB 3200MHZ")])
    publish_import(db, _import(db, b, Currency.UZS), b,
                   [_row(1, "lexar ddr4 8gb 3200mhz", 700000, raw="ОЗУ Lexar 8Gb DDR4-3200")])
    assert len(db.scalars(select(Product)).all()) == 1
    offers = db.scalars(select(Offer)).all()
    assert {o.currency for o in offers} == {Currency.USD, Currency.UZS}


def test_duplicate_row_without_price_does_not_erase_price(db):
    store = _store(db, "a@example.com")
    rows = [_row(1, "Jonsbo Fan HF2-120B Black", 10), _row(2, "Jonsbo Fan HF2-120B Black", None)]
    publish_import(db, _import(db, store), store, rows)
    offer = db.scalar(select(Offer).where(Offer.raw_name == "Jonsbo Fan HF2-120B Black"))
    assert offer.price == 10 and offer.is_in_stock is True
