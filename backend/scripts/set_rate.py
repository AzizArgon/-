"""Stores the CBU USD rate given on stdin: the JSON answer of cbu.uz ([{"Rate": "...", "Date": "dd.mm.yyyy"}]).

cbu.uz answers only Uzbek addresses, so the public server gets the rate from the laptop (deploy/deploy.sh).
Usage (from backend/): python scripts/set_rate.py < usd.json
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.database import SessionLocal  # noqa: E402
from app.services.exchange import save_usd_rate  # noqa: E402

if __name__ == "__main__":
    data = json.load(sys.stdin)[0]
    rate, day = float(data["Rate"]), datetime.strptime(data["Date"], "%d.%m.%Y").date()
    with SessionLocal() as db:
        save_usd_rate(db, rate, day)
    print(f"USD rate {rate} of {day} saved")
