from sqlalchemy import func, select

from app.db.models import FraudFlag, Offer, PriceHistory, Store, User
from app.services.importer import publish_import
from scripts.seed_demo import seed_demo
from tests.test_publish import _import, _row, db  # noqa: F401  (db is a fixture)


def _count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_demo_stores_share_cards_flag_cheap_items_and_rerun_without_duplicates(db):
    user = User(email="seller1@example.com", password_hash="x")
    age = Store(owner=user, name="Age Computers")
    db.add(age)
    db.commit()
    rows = [
        {**_row(1, "Intel Core i5-12400F, 2.7 GHz, 18MB, OEM, LGA1700", 114), "category": "cpu", "brand": "Intel"},
        {**_row(2, "Samsung 990 PRO 1TB M.2 NVMe SSD", 225), "category": "ssd", "brand": "Samsung"},
        *[_row(n, f"Kingston DDR5 {n}GB", 10 + n) for n in range(3, 40)],
    ]
    publish_import(db, _import(db, age), age, rows)

    report = seed_demo(db, 12_000)
    assert [r["store"] for r in report] == ["Silicon Plus", "Byte Market", "PC Galaxy"]
    i5 = db.scalars(select(Offer).where(Offer.raw_name.like("%i5-12400F%"))).all()
    assert len({o.product_id for o in i5}) == 1 and len(i5) == 4  # Age + 3 demo stores, one card
    byte_market = next(o for o in i5 if o.store.name == "Byte Market")
    assert byte_market.currency.value == "UZS" and byte_market.price > 1_000_000

    # PC Galaxy sells the SSD at half price: flagged, the showcase CPU is not
    cheap = db.scalars(select(FraudFlag).where(FraudFlag.type == "price_below_market")).all()
    assert [f.offer.store.name for f in cheap] == ["PC Galaxy"]
    assert "990 PRO" in cheap[0].offer.raw_name

    counts = [_count(db, m) for m in (User, Store, Offer, PriceHistory, FraudFlag)]
    seed_demo(db, 12_000)
    assert [_count(db, m) for m in (User, Store, Offer, PriceHistory, FraudFlag)] == counts
