"""Parse cache of the live demo files (samples/demo): the show doesn't depend on the internet and AI limits.

Parses dirty_price.xlsx, national_currency.xlsx and every post of posts.txt like an upload does
(cache -> rules -> AI; only rows the cache doesn't know go to the AI) and writes the cache entries
of their rows to samples/demo/cache.json. demo.bat loads it into the clean DB ("demo.bat live" doesn't).
Usage (from backend/): .venv/Scripts/python.exe scripts/demo_cache.py
"""

import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db.database import SessionLocal, init_db  # noqa: E402
from app.db.models import ParseCache  # noqa: E402
from app.services.importer import file_to_markdown, parse_clean_rows  # noqa: E402
from app.services.price_cleaner import cache_key, clean_markdown  # noqa: E402
from app.services.text_import import text_to_rows  # noqa: E402

DEMO = Path(__file__).resolve().parents[2] / "samples" / "demo"
FILES = ["dirty_price.xlsx", "national_currency.xlsx"]


def demo_posts() -> list[str]:
    parts = re.split(r"^=== .* ===$", (DEMO / "posts.txt").read_text(encoding="utf-8"), flags=re.M)
    return [p.strip() for p in parts if p.strip()]


def demo_rows() -> list[tuple[str, list]]:
    sets = [(f, clean_markdown(file_to_markdown((DEMO / f).read_bytes(), f, []))) for f in FILES]
    return sets + [(f"post {i + 1}", text_to_rows(p)) for i, p in enumerate(demo_posts())]


async def parse_all() -> set[str]:
    keys: set[str] = set()
    with SessionLocal() as db:
        for name, rows in demo_rows():
            stats: dict = {}
            parsed = await parse_clean_rows(db, rows, stats) if rows else []
            print(f"{name}: {len(parsed)} rows, cache {stats.get('cache', 0)}, rules {stats.get('rule', 0)}, "
                  f"AI {stats.get('ai_rows', 0)}, failed {stats.get('failed_rows', 0)}")
            keys |= {cache_key(r.ai_text) for r in rows}
    return keys


if __name__ == "__main__":
    init_db()
    keys = asyncio.run(parse_all())
    with SessionLocal() as db:
        entries = db.scalars(select(ParseCache).where(ParseCache.key.in_(keys))).all()
    data = {"parse_cache": {c.key: {"data": c.data, "source": c.source} for c in entries}}
    (DEMO / "cache.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"cache.json: {len(entries)} entries")
