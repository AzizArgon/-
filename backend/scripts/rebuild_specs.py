"""Recomputes characteristics of all products by the spec dictionary, without AI requests.

Prints the coverage table (what share of products got each key) and how many spellings the
normalizer brought to one format. Back up database.db first. Usage (from backend/):
  .venv/Scripts/python.exe scripts/rebuild_specs.py [--dry-run]
"""

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db.database import SessionLocal  # noqa: E402
from app.db.models import Product, Store, User  # noqa: E402
from app.services.catalog import rebuild_specs  # noqa: E402
from app.services.spec_dictionary import DICTIONARY  # noqa: E402
from app.services.spec_normalizer import new_trace  # noqa: E402


def coverage(db) -> None:
    products = db.scalars(select(Product)).all()
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for p in products:
        by_cat[p.category.slug if p.category else "other"].append(p.specs_json or {})
    print("| Категория | Товаров | Характеристики (% товаров со значением) |\n|---|---|---|")
    for cat, specs in sorted(by_cat.items(), key=lambda x: -len(x[1])):
        keys = [s.key for s in DICTIONARY.get(cat, DICTIONARY["other"])]
        cells = ", ".join(f"{k} {round(100 * sum(k in s for s in specs) / len(specs))}%" for k in keys)
        print(f"| {cat} | {len(specs)} | {cells} |")


def spellings(db, trace) -> None:
    """Spellings without numbers ("NGB", "N ГБ", "NxNGB") -> how many dictionary values they became."""
    values: dict[tuple, set] = defaultdict(set)
    for p in db.scalars(select(Product)):
        for key, value in (p.specs_json or {}).items():
            values[(p.category.slug if p.category else "other", key)].add(value)
    print("\n| Категория / характеристика | Написаний | Значений в словаре | Примеры написаний |\n|---|---|---|---|")
    for (cat, key), shapes in sorted(trace.items(), key=lambda x: -len(x[1])):
        if len(shapes) > 1:
            examples = "; ".join(f"«{s}»" for s, _ in Counter(shapes).most_common(6))
            print(f"| {cat} / {key} | {len(shapes)} | {len(values[(cat, key)])} | {examples} |")


if __name__ == "__main__":
    trace = new_trace()
    with SessionLocal() as db:
        demo = set(db.scalars(select(Store.id).join(User).where(User.email.like("demo%@example.com"))))
        dry = "--dry-run" in sys.argv
        print(rebuild_specs(db, trace, demo, commit=not dry))
        coverage(db)
        spellings(db, trace)
        db.rollback()
