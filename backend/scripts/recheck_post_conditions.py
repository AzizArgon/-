"""One-off: condition of goods from pasted posts by the Phase 7 rule (only explicit words, otherwise "unknown").

Before, a post without a word about the condition got "new" (or the AI's guess). Published offers and the rows of
text imports still in the preview are recalculated. The post text is stored since Phase 5.2.2; older imports are
read from the row text (the whole card post is in it). Make a DB copy first.
Usage (from backend/): .venv/Scripts/python.exe scripts/recheck_post_conditions.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm.attributes import flag_modified  # noqa: E402

from app.db.database import SessionLocal  # noqa: E402
from app.db.models import Condition, Offer, PriceImport  # noqa: E402
from app.services.text_import import condition_of, text_to_rows  # noqa: E402


def main() -> None:
    changed = []
    with SessionLocal() as db:
        for imp in db.scalars(select(PriceImport).where(PriceImport.source == "text", PriceImport.rows_json.is_not(None))):
            by_raw = {r.raw_name: r.condition for r in text_to_rows(imp.text)} if imp.text else {}
            rows = list(imp.rows_json)
            for row in rows:
                new = by_raw.get(row["raw_name"]) or condition_of(row["raw_name"])
                if row.get("condition") != new:
                    changed.append((imp.id, row["raw_name"][:60], row.get("condition"), new))
                    row["condition"] = new
                if imp.status.value == "published":
                    for offer in db.scalars(select(Offer).where(Offer.store_id == imp.store_id,
                                                                Offer.raw_name == row["raw_name"])):
                        offer.condition = Condition(new)
            imp.rows_json = rows
            flag_modified(imp, "rows_json")
        db.commit()
    print(f"{'import':>6}  {'was':12} {'now':12} row")
    for imp_id, raw, old, new in changed:
        print(f"{imp_id:6}  {old or '-':12} {new:12} {raw}")
    print(f"changed: {len(changed)}")


if __name__ == "__main__":
    main()
