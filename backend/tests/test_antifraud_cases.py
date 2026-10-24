"""Real-world Anti-Fraud cases. They define what the future checker must detect."""

import json
from pathlib import Path

import pytest

CASES = json.loads((Path(__file__).parent / "fixtures" / "antifraud_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_antifraud_case(case):
    antifraud = pytest.importorskip("app.services.antifraud", reason="Anti-Fraud is not implemented yet")
    flags = antifraud.check_offer(case["row"])
    for expected in case["expected_flags"]:
        match = [f for f in flags if f["type"] == expected["type"]]
        assert match, f"expected flag {expected['type']}"
        flag = match[0]
        assert flag["level"] == expected["level"]
        assert flag["source"] == expected["source"]
        for word in expected["reason_contains"]:
            assert word in flag["reason"]
