"""Import pipeline on a dirty price list with a recorded AI answer: no live AI requests."""

import asyncio
import json
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.database import Base
from app.services import ai_parser
from app.services.importer import parse_clean_rows
from app.services.price_cleaner import clean_markdown

FIXTURES = Path(__file__).parent / "fixtures"
RECORDED = json.loads((FIXTURES / "ai_answer.json").read_text(encoding="utf-8"))["items"]


def _answer_for(text: str) -> list[dict]:
    """The recorded items for the row ids present in the request."""
    ids = {int(m) for m in re.findall(r"^(\d+)\|", text, re.MULTILINE)}
    return [it for it in RECORDED if it["i"] in ids]


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session


@pytest.fixture
def rows():
    return clean_markdown((FIXTURES / "dirty_price.md").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    calls = []

    async def fake_gemini(model, text):
        calls.append(text)
        return json.dumps(_answer_for(text)), False

    async def no_groq(text):
        raise AssertionError("Groq must not be called")

    monkeypatch.setattr(ai_parser, "_call_gemini", fake_gemini)
    monkeypatch.setattr(ai_parser, "_call_groq", no_groq)
    monkeypatch.setattr(ai_parser, "_exhausted_on", {})
    monkeypatch.setattr(ai_parser, "_gemini_limiter", ai_parser.RateLimiter(1000))
    monkeypatch.setattr(ai_parser, "_groq_limiter", ai_parser.RateLimiter(1000))
    return calls


def test_rules_ai_and_cache(db, rows, offline):
    stats = {}
    result = {r["name"]: r for r in asyncio.run(parse_clean_rows(db, rows, stats))}
    assert stats["rule"] == 2 and stats["requests"] == 1
    # Neat rows never reach the AI, and the AI gets names only: no prices
    assert "KingBank" not in offline[0] and "Intel-Core" not in offline[0]
    assert "|95" not in offline[0] and "| 95" not in offline[0]

    kingbank = next(r for r in result.values() if r["source"] == "rule" and r["category"] == "ram")
    assert kingbank["price"] == 140 and kingbank["model"] == "KJXS DDR4 6000MHz 8GB UDIMM"
    assert "DDR5" in kingbank["name"]  # the contradiction is kept for Anti-Fraud

    by_source = [r for r in result.values() if r["source"] == "ai"]
    assert {r["condition"] for r in by_source} >= {"used"}
    psu = next(r for r in by_source if r["category"] == "psu")
    assert psu["price"] is None and psu["is_in_stock"] is False
    assert not any("Доставка" in r["name"] for r in result.values())  # not a product

    # Second upload of the same file: everything comes from cache and rules, no AI
    stats2 = {}
    again = asyncio.run(parse_clean_rows(db, rows, stats2))
    assert stats2["requests"] == 0 and len(offline) == 1
    assert {r["source"] for r in again} == {"cache", "rule"}


def test_truncated_answer_is_split(db, rows, monkeypatch):
    async def truncating(model, text):
        items = _answer_for(text)
        return json.dumps(items), len(re.findall(r"^\d+\|", text, re.MULTILINE)) > 2

    monkeypatch.setattr(ai_parser, "_call_gemini", truncating)
    stats = {}
    result = asyncio.run(parse_clean_rows(db, rows, stats))
    assert stats["splits"] >= 1 and stats["failed_rows"] == 0
    assert sum(r["source"] == "ai" for r in result) == len(RECORDED)


def test_groq_fallback_when_gemini_quota_is_over(db, rows, monkeypatch):
    async def quota_over(model, text):
        raise RuntimeError("429 RESOURCE_EXHAUSTED GenerateRequestsPerDayPerProjectPerModel-FreeTier")

    async def fake_groq(text):
        return json.dumps({"items": _answer_for(text)}), False

    monkeypatch.setattr(ai_parser, "_call_gemini", quota_over)
    monkeypatch.setattr(ai_parser, "_call_groq", fake_groq)
    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    stats = {}
    result = asyncio.run(parse_clean_rows(db, rows, stats))
    assert stats["groq_requests"] == 1 and stats["requests"] == 1
    assert sum(r["source"] == "ai" for r in result) == len(RECORDED)


def test_without_any_ai_rows_are_kept_as_failed(db, rows, monkeypatch):
    async def quota_over(model, text):
        raise RuntimeError("429 RESOURCE_EXHAUSTED GenerateRequestsPerDayPerProjectPerModel-FreeTier")

    monkeypatch.setattr(ai_parser, "_call_gemini", quota_over)
    monkeypatch.setattr(settings, "groq_api_key", "")
    stats = {}
    result = asyncio.run(parse_clean_rows(db, rows, stats))
    assert stats["quota_hit"] is True
    failed = [r for r in result if r["source"] == "failed"]
    # Failed rows stay in the preview with the price from the file, ready for a retry
    assert stats["failed_rows"] == len(failed) > 0
    assert any(r["price"] == 95 for r in failed)


def test_ai_specs_not_in_row_are_guesses(db, rows):
    result = asyncio.run(parse_clean_rows(db, rows, {}))
    psu = next(r for r in result if r["category"] == "psu")
    # "600W" is in the row; "80 PLUS Bronze" was invented by the AI
    assert "600W" in psu["specs"].values()
    assert "certification" in psu["specs_guess"] and "certification" not in psu["specs"]
    cpu = next(r for r in result if r["source"] == "ai" and r["category"] == "cpu")
    assert "socket" in cpu["specs_guess"]  # LGA1700 is not written in "проц i5 12400f б/у"


@pytest.mark.parametrize("value,text,expected", [
    ("4GB DDR4", "Lenovo (Intel Core i3/ DDR4 4GB/ HDD 1TB)", True),
    ("1.5m", "SPG5-C-5 1,5м", True),
    ("16A", "для нагрузки до 16 ампер", True),
    ("wireless", "беспроводные наушники", True),
    ("33 стр/мин", "(A4, 1Gb,33стр/мин, цв.лаз.МФУ)", True),
    ("80 PLUS Bronze", "Блок питания 600W Aerocool KCAS Plus", False),
    ("6", "б/у видюха gtx 1660 super 6gb", True),
    ("6", "gtx 1660 super", False),
    ("LGA1700", "проц i5 12400f б/у", False),
])
def test_spec_in_text(value, text, expected):
    assert ai_parser.spec_in_text(value, text) is expected
