"""Records a real AI answer for tests/fixtures/dirty_price.md, so tests never call the AI.

Usage (from backend/): .venv/Scripts/python.exe scripts/record_ai_fixture.py [model]
"""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.services.ai_parser import _call_gemini, format_chunk  # noqa: E402
from app.services.price_cleaner import clean_markdown  # noqa: E402
from app.services.rule_parser import parse_by_rules  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else settings.gemini_model
    rows = clean_markdown((FIXTURES / "dirty_price.md").read_text(encoding="utf-8"))
    pending = [r for r in rows if not parse_by_rules(r.name)]
    answer, truncated = asyncio.run(_call_gemini(model, format_chunk(pending)))
    assert not truncated
    out = {"model": model, "items": json.loads(answer)}
    (FIXTURES / "ai_answer.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
