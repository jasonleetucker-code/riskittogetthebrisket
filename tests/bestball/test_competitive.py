from __future__ import annotations

import dataclasses

import pytest

from src.bestball.competitive import BASIS_MISMATCH_REASON, championship_delta
from src.bestball.contracts import CompetitiveOutcome


def test_championship_delta_is_explicitly_unavailable_for_every_team():
    out = championship_delta(
        ["owner01", "owner02"],
        {"owner01": {"deltaPpg": 3.2}, "owner02": {"deltaPpg": -3.2}},
        snapshot={"teams": []},
    )
    assert set(out) == {"owner01", "owner02"}
    for oid, outcome in out.items():
        assert outcome.owner_id == oid
        assert outcome.state == "unavailable"
        assert outcome.reason == BASIS_MISMATCH_REASON
        assert outcome.horizon == "current_season"


def test_championship_delta_never_returns_a_number():
    out = championship_delta(["a", "b", "c"], {"a": 99.0})
    for outcome in out.values():
        for f in dataclasses.fields(outcome):
            value = getattr(outcome, f.name)
            assert not isinstance(value, (int, float)) or isinstance(value, bool), f.name
        d = outcome.to_dict()
        for key in ("titleProbBefore", "titleProbAfter", "delta", "ciLow", "ciHigh"):
            assert d[key] is None


def test_unavailable_outcome_refuses_to_carry_a_number():
    with pytest.raises(ValueError):
        CompetitiveOutcome(
            "a", 0.1, 0.2, 0.1, None, None, "current_season", "x", "unavailable", "r"
        )
