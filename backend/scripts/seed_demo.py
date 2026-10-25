"""Demo stores for the catalog: 3 invented shops built from the Age Computers assortment.

Each store gets part of the assortment (popular items overlap, so cards show 2-4 offers),
prices +-5-15%, some items out of stock, its own price-list freshness; one store sells in UZS,
one is verified, one has a few items far below the market (Anti-Fraud "price below market").
Goes through publish_import, so flags and price history work as for a real upload.
Re-running updates the same stores and offers, no duplicates. Usage (from backend/):
  .venv/Scripts/python.exe scripts/seed_demo.py
"""

import random
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session, selectinload  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.models import (  # noqa: E402
    Currency, ImportStatus, Offer, PriceImport, Product, Store, User, UserRole, utcnow,
)

SOURCE_EMAIL = "seller1@example.com"  # Age Computers: the real price list the demo is built from
DEMO_PASSWORD = "demo12345"
DEMO_FILENAME = "demo_seed.xlsx"
# Showcase items every demo store sells (matched by name, ids change on a clean DB)
SHOWCASE = ["Core i5-12400F", "Ryzen 5 7500F", "RTX 5060 TWIN EDGE OC", "990 PRO 1TB"]
POPULAR = {"cpu", "gpu", "ram", "ssd", "motherboard", "psu", "monitor"}
FALLBACK_USD_RATE = 12_000.0

STORES = [
    {"email": "demo1@example.com", "name": "Silicon Plus", "district": "Юнусабад", "address": "ул. Амира Темура, 107",
     "phone": "+998900000101", "telegram": "@silicon_plus_demo", "is_verified": True,
     "currency": Currency.USD, "days_old": 0, "below_market": []},
    {"email": "demo2@example.com", "name": "Byte Market", "district": "Мирзо-Улугбек", "address": "Малика, ряд 3",
     "phone": "+998900000202", "telegram": "@byte_market_demo", "is_verified": False,
     "currency": Currency.UZS, "days_old": 4, "below_market": []},
    # Published last: its cheap items are compared with all the other stores
    {"email": "demo3@example.com", "name": "PC Galaxy", "district": "Яккасарай", "address": "ул. Шота Руставели, 41",
     "phone": "+998900000303", "telegram": None, "is_verified": False,
     "currency": Currency.USD, "days_old": 25, "below_market": ["Ryzen 5 7500F", "RTX 5060 TWIN EDGE OC", "990 PRO 1TB"]},
]


def _store(db: Session, spec: dict) -> Store:
    user = db.scalar(select(User).where(User.email == spec["email"]))
    if user is None:
        user = User(email=spec["email"], password_hash=hash_password(DEMO_PASSWORD), role=UserRole.seller)
        db.add(user)
    store = db.scalar(select(Store).where(Store.user_id == user.id)) if user.id else None
    if store is None:
        store = Store(owner=user)
        db.add(store)
    for field in ("name", "district", "address", "phone", "telegram", "is_verified"):
        setattr(store, field, spec[field])
    db.commit()
    return store


def _demo_import(db: Session, store: Store, currency: Currency) -> PriceImport:
    """One import record per demo store, reused on every run."""
    imp = db.scalar(select(PriceImport).where(PriceImport.store_id == store.id, PriceImport.filename == DEMO_FILENAME))
    if imp is None:
        imp = PriceImport(store_id=store.id, filename=DEMO_FILENAME, currency=currency)
        db.add(imp)
    imp.currency = currency
    imp.status = ImportStatus.ready
    db.commit()
    return imp


def _source_offers(db: Session) -> list[Offer]:
    source = db.scalar(select(Store).join(Store.owner).where(User.email == SOURCE_EMAIL))
    if source is None:
        raise SystemExit(f"No store of {SOURCE_EMAIL}: publish the Age Computers price list first")
    return db.scalars(
        select(Offer).where(Offer.store_id == source.id, Offer.is_in_stock.is_(True), Offer.price.is_not(None),
                            Offer.currency == Currency.USD)
        .options(selectinload(Offer.product).selectinload(Product.category)).order_by(Offer.id)
    ).all()


def _rows(spec: dict, offers: list[Offer], usd_rate: float) -> list[dict]:
    rng = random.Random(spec["email"])  # same assortment and prices on every run
    rows = []
    for o in offers:
        p = o.product
        category = p.category.slug if p.category else "other"
        showcase = any(s in p.normalized_name for s in SHOWCASE)
        if not showcase and rng.random() >= (0.55 if category in POPULAR else 0.2):
            continue
        sign = rng.choice((-1, 1))
        factor = 1 + sign * rng.uniform(0.05, 0.15)
        if any(s in p.normalized_name for s in spec["below_market"]):
            factor = 0.5
        price_usd = o.price * factor
        price = round(price_usd * usd_rate, -3) if spec["currency"] == Currency.UZS else round(price_usd)
        rows.append({
            "row": len(rows) + 1, "raw_name": p.normalized_name, "category": category, "brand": p.brand,
            "model": p.model, "name": p.normalized_name, "price": price, "condition": o.condition.value,
            "specs": p.specs_json or {}, "is_in_stock": showcase or rng.random() < 0.88,
        })
    return rows


def seed_demo(db: Session, usd_rate: float | None) -> list[dict]:
    from app.services.importer import publish_import

    usd_rate = usd_rate or FALLBACK_USD_RATE
    offers = _source_offers(db)
    report = []
    for spec in STORES:
        store = _store(db, spec)
        rows = _rows(spec, offers, usd_rate)
        stats = publish_import(db, _demo_import(db, store, spec["currency"]), store, rows)
        # Price list freshness differs between stores ("recommended" order uses it)
        updated = utcnow() - timedelta(days=spec["days_old"])
        for offer in db.scalars(select(Offer).where(Offer.store_id == store.id)):
            offer.updated_at = updated
        db.commit()
        report.append({"store": spec["name"], "rows": len(rows), **stats})
    return report


if __name__ == "__main__":
    from app.db.database import SessionLocal, init_db
    from app.services.exchange import get_usd_rate

    init_db()
    with SessionLocal() as db:
        rate = get_usd_rate(db)
        for line in seed_demo(db, rate.rate if rate else None):
            print(line)
