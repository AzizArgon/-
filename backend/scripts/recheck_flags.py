"""Runs the Anti-Fraud rules over everything already in the DB: published offers and ready previews.

Needed once after the rules appear or change (no AI requests). Usage (from backend/):
  .venv/Scripts/python.exe scripts/recheck_flags.py
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm.attributes import flag_modified  # noqa: E402

from app.db.database import SessionLocal  # noqa: E402
from app.db.models import ImportStatus, Offer, PriceImport  # noqa: E402
from app.services.antifraud import check_offer, market_prices, save_offer_flags  # noqa: E402
from app.services.exchange import get_usd_rate  # noqa: E402
from app.services.importer import flag_rows  # noqa: E402


def main() -> None:
    with SessionLocal() as db:
        rate = get_usd_rate(db)
        usd_rate = rate.rate if rate else None
        counts: Counter = Counter()
        offers = db.scalars(select(Offer)).all()
        for offer in offers:
            p = offer.product
            row = {
                "raw_name": offer.raw_name, "category": p.category.slug, "brand": p.brand, "model": p.model,
                "name": p.normalized_name, "specs": p.specs_json, "condition": offer.condition.value,
                "price": offer.price, "currency": offer.currency.value,
            }
            market = market_prices(db, {p.match_key}, offer.store_id, usd_rate).get(p.match_key)
            flags = check_offer(row, market, usd_rate)
            save_offer_flags(offer, flags)
            counts.update(f"{f['type']}/{f['level']}" for f in flags)
        for imp in db.scalars(select(PriceImport).where(PriceImport.status.in_([ImportStatus.ready, ImportStatus.published]))):
            rows = list(imp.rows_json or [])
            flag_rows(db, rows, imp.store_id, imp.currency)
            imp.rows_json = rows
            flag_modified(imp, "rows_json")
        db.commit()
    print(f"Offers checked: {len(offers)}")
    for key, n in counts.most_common():
        print(f"  {key}: {n}")


if __name__ == "__main__":
    main()
