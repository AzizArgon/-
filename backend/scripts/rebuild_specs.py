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
from app.services.spec_dictionary import DICTIONARY, plausible_range  # noqa: E402
from app.services.spec_normalizer import INFERRED, SUSPECT, new_trace, written_specs  # noqa: E402


def coverage(db) -> None:
    products = db.scalars(select(Product)).all()
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for p in products:
        by_cat[p.category.slug if p.category else "other"].append(p.specs_json or {})
    print("| Категория | Товаров | Характеристики (% товаров со значением) |\n|---|---|---|")
    for cat, specs in sorted(by_cat.items(), key=lambda x: -len(x[1])):
        keys = [s.key for s in DICTIONARY.get(cat, DICTIONARY["other"])]
        pct = lambda n: round(100 * n / len(specs))  # noqa: E731
        inferred = lambda k: sum(k in s.get(INFERRED, {}) for s in specs)  # noqa: E731
        cells = ", ".join(f"{k} {pct(sum(k in s for s in specs))}%"
                          + (f" (выведено правилом {pct(inferred(k))}%)" if inferred(k) else "") for k in keys)
        print(f"| {cat} | {len(specs)} | {cells} |")


def spellings(db, trace) -> None:
    """Spellings without numbers ("NGB", "N ГБ", "NxNGB") -> how many dictionary values they became."""
    values: dict[tuple, set] = defaultdict(set)
    for p in db.scalars(select(Product)):
        for key, value in written_specs(p.specs_json).items():
            values[(p.category.slug if p.category else "other", key)].add(value)
    print("\n| Категория / характеристика | Написаний | Значений в словаре | Примеры написаний |\n|---|---|---|---|")
    for (cat, key), shapes in sorted(trace.items(), key=lambda x: -len(x[1])):
        if len(shapes) > 1:
            examples = "; ".join(f"«{s}»" for s, _ in Counter(shapes).most_common(6))
            print(f"| {cat} / {key} | {len(shapes)} | {len(values[(cat, key)])} | {examples} |")


def suspects(db) -> None:
    """Numbers outside their plausible range (typos?): kept apart from the filters, listed for the report."""
    found = [(p, k, v) for p in db.scalars(select(Product)) for k, v in (p.specs_json or {}).get(SUSPECT, {}).items()]
    print(f"\nПохоже на опечатку: {len(found)} значений у {len({p.id for p, _, _ in found})} товаров")
    print("| Категория | Товар | Характеристика | Значение | Допустимо |\n|---|---|---|---|---|")
    for p, key, value in sorted(found, key=lambda x: (x[0].category.slug if x[0].category else "", x[1])):
        cat = p.category.slug if p.category else "other"
        lo, hi = plausible_range(cat, key, p.specs_json) or ("?", "?")
        print(f"| {cat} | {p.normalized_name} | {key} | {value} | {lo}–{hi} |")


if __name__ == "__main__":
    trace = new_trace()
    with SessionLocal() as db:
        demo = set(db.scalars(select(Store.id).join(User).where(User.email.like("demo%@example.com"))))
        dry = "--dry-run" in sys.argv
        print(rebuild_specs(db, trace, demo, commit=not dry))
        coverage(db)
        spellings(db, trace)
        suspects(db)
        db.rollback()
