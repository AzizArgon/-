"""Parser benchmark: AI requests, input size and time before/after the optimization.

Usage (from backend/):
  .venv/Scripts/python.exe scripts/benchmark_parser.py <price file>           # dry run, no AI calls
  .venv/Scripts/python.exe scripts/benchmark_parser.py <price file> --tokens  # + exact input tokens (free API)
  .venv/Scripts/python.exe scripts/benchmark_parser.py <price file> --live    # + real AI run, empty cache
"""

import argparse
import asyncio
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.database import Base  # noqa: E402
from app.services import ai_parser  # noqa: E402
from app.services.importer import file_to_markdown, parse_clean_rows  # noqa: E402
from app.services.price_cleaner import clean_markdown  # noqa: E402
from app.services.rule_parser import parse_by_rules  # noqa: E402

OLD_CHUNK_ROWS = 250  # Phase 3 version: every row, all cells, 250 rows per request


def count_tokens(texts: list[str]) -> int:
    client = ai_parser._get_client()
    return sum(client.models.count_tokens(model=settings.gemini_model, contents=t).total_tokens for t in texts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--tokens", action="store_true")
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args()

    path = Path(args.file)
    rows = clean_markdown(file_to_markdown(path.read_bytes(), path.name))

    # Before: whole rows ("r12 | name | article | price") were sent, 250 per request
    old_lines = [f"r{r.row} | " + " | ".join(r.cells) for r in rows]
    old_chunks = ["\n".join(old_lines[i : i + OLD_CHUNK_ROWS]) for i in range(0, len(old_lines), OLD_CHUNK_ROWS)]

    # After: rules first, only names of the remaining rows, big chunks
    pending = [r for r in rows if not parse_by_rules(r.name)]
    size = settings.parser_chunk_rows
    new_chunks = [ai_parser.format_chunk(pending[i : i + size]) for i in range(0, len(pending), size)]

    report = {
        "rows": len(rows),
        "before": {"ai_rows": len(rows), "requests": math.ceil(len(rows) / OLD_CHUNK_ROWS),
                   "input_chars": sum(map(len, old_chunks))},
        "after": {"rule_rows": len(rows) - len(pending), "ai_rows": len(pending), "requests": len(new_chunks),
                  "input_chars": sum(map(len, new_chunks))},
    }
    if args.tokens:
        report["before"]["input_tokens"] = count_tokens(old_chunks)
        report["after"]["input_tokens"] = count_tokens(new_chunks)
    if args.live:
        # Empty in-memory cache: measures a cold run, the real cache is not touched
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        stats: dict = {}
        with sessionmaker(bind=engine)() as db:
            parsed = asyncio.run(parse_clean_rows(db, rows, stats))
        report["after_live"] = stats | {"parsed_rows": len(parsed)}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
