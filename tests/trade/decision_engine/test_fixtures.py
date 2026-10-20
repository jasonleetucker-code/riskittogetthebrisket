"""The committed camelCase TwoSidedDecision fixtures.

The integration lane's frontend parity test reads these files, so they are
pinned here: each must equal what the engine produces for its scenario today
and validate against the committed JSON schema.  Regenerate deliberately with
``DECISION_ENGINE_REGEN=1 python -m pytest tests/trade/decision_engine/test_fixtures.py``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.trade.decision_engine import engine, policy, serialize
from tests.trade.decision_engine.scenarios import SCENARIOS
from tests.trade.decision_engine.schema_check import validate

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "decision_engine"
SCHEMA = json.loads((FIXTURES / "two_sided_decision.schema.json").read_text(encoding="utf-8"))
PARAMS = policy.load_params()


def _payload(name: str) -> dict:
    a, b = SCENARIOS[name]()
    return serialize.to_payload(engine.evaluate_two_sided(a, b, params=PARAMS))


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_fixture_matches_engine_and_schema(name):
    payload = json.loads(json.dumps(_payload(name)))  # JSON round trip: plain types only
    path = FIXTURES / f"{name}.json"
    if os.environ.get("DECISION_ENGINE_REGEN") == "1":
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    committed = json.loads(path.read_text(encoding="utf-8"))
    assert validate(committed, SCHEMA) == []
    assert committed == payload


def test_schema_rejects_a_headline_or_probability_payload():
    payload = json.loads(json.dumps(_payload("both_gain")))
    payload["teams"][0]["predictiveProbability"] = 0.62
    assert validate(payload, SCHEMA)
    payload = json.loads(json.dumps(_payload("both_gain")))
    payload["executes"] = True
    assert validate(payload, SCHEMA)
    payload = json.loads(json.dumps(_payload("both_gain")))
    payload["teams"][0]["headlineText"] = "anything"
    assert validate(payload, SCHEMA)


def test_pinned_shapes():
    expected = {
        "both_gain": "good_for_both",
        "both_lose": "bad_for_both",
        "insufficient": "insufficient",
        "va_overlap": "good_for_both",
        "all_stub": "insufficient",
    }
    for name, shape in expected.items():
        committed = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
        assert committed["shape"] == shape, name
