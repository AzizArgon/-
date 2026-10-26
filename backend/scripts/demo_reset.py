"""Demo mode from scratch: backup -> clean DB -> categories -> cache -> real price list -> demo stores -> Gshop archive.

An empty store (live@example.com) is made for uploading the demo files during the show.
No live AI requests: the full price list is parsed from the parse cache (rows the cache doesn't know fail and are
reported, not sent to the AI). The cache and CBU rates are kept in a snapshot outside the repo
(F:/claudy/samples/demo_cache.json), so the demo works without the internet and AI limits.
The cache of the live demo files (samples/demo/cache.json) is loaded too, unless --live is given:
then those files go through the rules and the real AI during the show.
Usage (from backend/, servers stopped):
  .venv/Scripts/python.exe scripts/demo_reset.py [--live]
"""

import argparse
import asyncio
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

DB_FILE = BACKEND / "database.db"
BACKUPS = Path("F:/claudy/backups")
SAMPLES = Path("F:/claudy/samples")
SNAPSHOT = SAMPLES / "demo_cache.json"
DEMO_CACHE = BACKEND.parent / "samples" / "demo" / "cache.json"
PRICE_FILE = SAMPLES / "Price of Age Computers (9).xlsx"
ARCHIVE_FILE = SAMPLES / "old_store_2023.xlsx"
SELLER = {"email": "seller1@example.com", "password": "seller12345", "name": "Age Computers",
          "phone": "+998901234567", "district": "Чиланзар"}
# An empty store for the live upload: a file published by a store marks its other goods "out of stock",
# so the demo files must not go to a store with a full price list
LIVE_SELLER = {"email": "live@example.com", "password": "demo12345", "name": "Tech Point",
               "phone": "+998900000404", "district": "Шайхантахур"}


def backup() -> Path | None:
    if not DB_FILE.exists():
        return None
    BACKUPS.mkdir(parents=True, exist_ok=True)
    target = BACKUPS / f"{date.today().isoformat()}_before_demo_reset.db"
    if target.exists():
        target = target.with_name(f"{target.stem}_{datetime.now():%H%M%S}.db")
    shutil.copy2(DB_FILE, target)
    return target


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"parse_cache": {}, "exchange_rates": {}}


def save_snapshot(demo_keys: set[str]) -> dict:
    """Merges the cache and rates of the current DB into the snapshot (demo-file rows stay in their own file)."""
    snap = load_json(SNAPSHOT)
    if DB_FILE.exists():
        con = sqlite3.connect(DB_FILE)
        for key, data, source in con.execute("select key, data, source from parse_cache"):
            if key not in demo_keys:
                snap["parse_cache"][key] = {"data": json.loads(data), "source": source}
        for currency, rate, day in con.execute("select currency, rate, rate_date from exchange_rates"):
            snap["exchange_rates"][f"{currency}:{day}"] = rate
        con.close()
    SNAPSHOT.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    return snap


def restore(db, snap: dict, demo: dict) -> None:
    from app.db.models import ExchangeRate, ParseCache

    for key, rate in snap["exchange_rates"].items():
        currency, day = key.split(":")
        db.add(ExchangeRate(currency=currency, rate=rate, rate_date=date.fromisoformat(day),
                            fetched_on=date.fromisoformat(day)))
    for key, entry in {**snap["parse_cache"], **demo["parse_cache"]}.items():
        db.add(ParseCache(key=key, data=entry["data"], source=entry["source"]))
    db.commit()


def add_seller(db, spec: dict):
    from app.core.security import hash_password
    from app.db.models import Store, User, UserRole

    user = User(email=spec["email"], password_hash=hash_password(spec["password"]), role=UserRole.seller)
    store = Store(owner=user, name=spec["name"], phone=spec["phone"], district=spec["district"])
    db.add_all([user, store])
    db.flush()
    return store


def import_price_list(db) -> dict:
    from sqlalchemy import select

    from app.db.models import Currency, PriceImport
    from app.services import importer

    async def offline(rows, stats):
        raise RuntimeError("demo mode: no live AI")

    importer.parse_rows = offline
    store = add_seller(db, SELLER)
    imp = PriceImport(store_id=store.id, filename=PRICE_FILE.name, currency=Currency.USD)
    db.add(imp)
    db.commit()
    asyncio.run(importer.run_import(imp.id, PRICE_FILE.read_bytes(), PRICE_FILE.name))
    db.expire_all()
    imp = db.scalar(select(PriceImport).where(PriceImport.id == imp.id))
    rows = [r for r in imp.rows_json if r.get("source") != "failed"]
    stats = importer.publish_import(db, imp, store, rows)
    return {**{k: imp.stats_json.get(k) for k in ("rows", "cache", "rule", "ai_rows")},
            "failed": len(imp.rows_json) - len(rows), **stats}


def run_script(*args: str) -> None:
    subprocess.run([sys.executable, *args], cwd=BACKEND, check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="don't load the cache of the live demo files")
    args = parser.parse_args()
    for f in (PRICE_FILE, ARCHIVE_FILE):
        if not f.exists():
            raise SystemExit(f"Not found: {f}")

    started = time.monotonic()
    print("backup:", backup())
    demo = load_json(DEMO_CACHE)
    snap = save_snapshot(set(demo["parse_cache"]))
    print(f"snapshot: {len(snap['parse_cache'])} cached rows, {len(snap['exchange_rates'])} rates")
    DB_FILE.unlink(missing_ok=True)

    from app.db.database import SessionLocal, init_db

    init_db()  # tables + categories with MXIK codes
    with SessionLocal() as db:
        restore(db, snap, {"parse_cache": {}} if args.live else demo)
        print("price list:", import_price_list(db))
        add_seller(db, LIVE_SELLER)
        db.commit()
    run_script("scripts/seed_demo.py")
    run_script("scripts/load_archive.py", str(ARCHIVE_FILE), "--store", "Gshop")
    print(f"demo data ready in {time.monotonic() - started:.0f} s")
