"""Real-world Anti-Fraud cases. They define what the future checker must detect."""

import json
import re
from pathlib import Path

import pytest

from app.services.antifraud import AI_TYPES, check_offer

CASES = json.loads((Path(__file__).parent / "fixtures" / "antifraud_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_antifraud_case(case):
    flags = check_offer(case["row"])
    if not case["expected_flags"]:
        assert flags == []
    for expected in case["expected_flags"]:
        match = [f for f in flags if f["type"] == expected["type"]]
        assert match, f"expected flag {expected['type']}"
        flag = match[0]
        assert flag["level"] == expected["level"]
        assert flag["source"] == expected["source"]
        assert flag["reason_key"] == expected["reason_key"]
        params = " ".join(str(v) for v in flag["params"].values())
        for word in expected.get("params_contain", []):
            assert word in params


def test_every_reason_key_has_a_russian_text():
    source = (Path(__file__).parents[1] / "app" / "services" / "antifraud.py").read_text(encoding="utf-8")
    keys = set(re.findall(r'_flag\("\w+", "\w+", "(\w+)"', source))
    keys |= set(re.findall(r'key(?:, params)? = "(\w+)"', source)) | {f"ai_{t}" for t in AI_TYPES}
    keys |= {k for pair in re.findall(r'"(\w+)" if category == "\w+" else "(\w+)"', source) for k in pair}  # mining_psu / _gpu
    ru = json.loads((Path(__file__).parents[2] / "frontend" / "src" / "locales" / "ru.json").read_text(encoding="utf-8"))
    assert len(keys) > 15
    assert keys <= set(ru["flags"]["reason"]), keys - set(ru["flags"]["reason"])
