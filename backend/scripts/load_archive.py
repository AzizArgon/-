"""Loads an old price list (Gshop) as archive prices: only history, not offers, not catalog cards, not Anti-Fraud.

The price date is taken from the file metadata (last saved), unless given. Re-running updates the same rows.
Usage (from backend/):
  .venv/Scripts/python.exe scripts/load_archive.py "F:/claudy/samples/old_store_2023.xlsx" --store Gshop
  .venv/Scripts/python.exe scripts/load_archive.py <file> --store Gshop --date 2023-06-15
  .venv/Scripts/python.exe scripts/load_archive.py --store Gshop --delete
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select  # noqa: E402

from app.db.models import ArchivePrice as A, Product  # noqa: E402


def file_date(path: Path) -> date | None:
    import openpyxl

    modified = openpyxl.load_workbook(path, read_only=True).properties.modified
    return modified.date() if modified else None


if __name__ == "__main__":
    from app.db.database import SessionLocal, init_db
    from app.services.archive import archive_store, load_archive
    from app.services.exchange import ensure_rates

    parser = argparse.ArgumentParser()
    parser.add_argument("file", nargs="?")
    parser.add_argument("--store", required=True)
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--delete", action="store_true", help="remove all archive rows of the store")
    args = parser.parse_args()

    init_db()
    with SessionLocal() as db:
        store = archive_store(db, args.store)
        if args.delete:
            n = db.execute(delete(A).where(A.store_id == store.id)).rowcount
            db.commit()
            print(f"deleted {n} archive rows of {args.store}")
            raise SystemExit
        path = Path(args.file)
        day = args.date or file_date(path)
        if day is None:
            raise SystemExit("No date in the file metadata: pass --date")
        ensure_rates(db, {day})
        stats = load_archive(db, path, args.store, day)
        print(f"{args.store}, prices of {day}: {stats}")
        rows = db.execute(
            select(A.raw_name, Product.normalized_name).outerjoin(Product, A.product_id == Product.id)
            .where(A.store_id == store.id).order_by(A.id)
        ).all()
        print("matched:", *(f"  {a[:60]} -> {p}" for a, p in rows if p), sep="\n")
