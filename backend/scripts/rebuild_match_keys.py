"""Recomputes product match keys (brand + model words) and merges cards that now match.

Needed once after make_match_key changes. Usage (from backend/):
  .venv/Scripts/python.exe scripts/rebuild_match_keys.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.database import SessionLocal  # noqa: E402
from app.services.catalog import rebuild_match_keys  # noqa: E402

if __name__ == "__main__":
    with SessionLocal() as db:
        print(rebuild_match_keys(db))
