"""Batch-1 provider stubs: unavailable + reason, never a number."""

from __future__ import annotations

from typing import Any

from src.trade.decision_engine import providers as pv


def _numbers(obj: Any) -> list[Any]:
    if isinstance(obj, bool):
        return []
    if isinstance(obj, (int, float)):
        return [obj]
    if isinstance(obj, dict):
        return [n for v in obj.values() for n in _numbers(v)]
    if isinstance(obj, (list, tuple)):
        return [n for v in obj for n in _numbers(v)]
    return []


def test_stubs_never_return_numbers():
    p = pv.stub_providers()
    outs = [
        p.scoring.weekly_summary("4046", 2026, 7),
        p.scoring.season_summary("4046", 2026),
        p.bestball.two_sided_lineup_deltas(["a", "b"]),
        p.bestball.marginal("4046"),
        p.bestball.team_horizon("a"),
        p.competitive.championship_delta(["a", "b"], {}),
        p.valuation.fair_value_for("Josh Allen"),
        p.valuation.board_pins(),
    ]
    for out in outs:
        assert _numbers(out) == []
    assert p.scoring.observation("4046", 2026, 7) is None
    for out in (outs[0], outs[1], outs[3], outs[4], outs[6], outs[7]):
        assert out["state"] == "unavailable" and out["reason"]
    for out in (outs[2], outs[5]):
        assert all(v["state"] == "unavailable" and v["reason"] for v in out.values())


def test_stubs_satisfy_the_local_protocols():
    p = pv.stub_providers()
    assert isinstance(p.scoring, pv.ScoringProvider)
    assert isinstance(p.bestball, pv.BestBallProvider)
    assert isinstance(p.competitive, pv.CompetitiveProvider)
    assert isinstance(p.valuation, pv.ValuationProvider)
