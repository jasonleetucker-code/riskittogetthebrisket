"""Hybrid Value Adjustment research harness (owner directive 2026-10-19).

Pins the findings the research memo rests on, so they cannot drift silently:

* every KTC/geometric blend inherits KTC's non-monotonicity — adding a one-point
  asset to B makes B's result WORSE, at every tested weight;
* the blend is ONE signed gap shown as ONE positive-only adjustment (never two
  stacked bonuses);
* the monotone candidates (floored geometric, power weights, HYBRID_50) pass the
  owner's §4 properties on a seeded suite;
* the box-only market-ledger scorer uses the eligibility owner and agrees with
  ``market_trade_eval.trade_residual`` for the incumbent.

Nothing here touches the active model (``geom_q078_v1``).
"""

from __future__ import annotations

import importlib.util
import random
from datetime import date
from pathlib import Path

import pytest

from src.trade import market_trade_eval as E
from src.valuation_math import package_model

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "package_model_hybrid_research", REPO / "scripts" / "package_model_hybrid_research.py"
)
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

BLENDS = [m for m, s in R.MODELS.items() if s["family"] == "blend"]
MONOTONE = [m for m, s in R.MODELS.items() if s["monotoneByConstruction"]]


def test_production_model_is_unchanged():
    assert package_model.active_model_id() == package_model.GEOM_Q078_V1
    assert package_model.shadow_model_ids() == [package_model.KTC_2026_04]
    assert set(package_model.PACKAGE_MODELS) == {"ktc_2026_04", "geom_q078_v1"}


def test_all_five_owner_weights_are_evaluated():
    assert sorted(BLENDS) == sorted(
        ["BLEND_G75_K25", "BLEND_G60_K40", "BLEND_G50_K50", "BLEND_G40_K60", "BLEND_G25_K75"]
    )


@pytest.mark.parametrize("model", BLENDS + ["KTC"])
def test_every_ktc_blend_fails_the_owner_mandatory_case(model):
    gap = R.MODELS[model]["gap"]
    base = gap([7200], [6000])
    after = gap([7200], [6000, 1])
    assert base == pytest.approx(1200)
    # B added a positive asset and A's lead GREW: B's result got worse.
    assert after > base + 500


@pytest.mark.parametrize("model", ["GEOM_78", "FGEOM_70_20", "FGEOM_75_15", "ZIPF_75", "HYBRID_50"])
def test_monotone_candidates_pass_the_owner_mandatory_case(model):
    gap = R.MODELS[model]["gap"]
    assert gap([7200], [6000, 1]) <= gap([7200], [6000]) + 1e-6


def test_blend_is_one_gap_shown_as_one_adjustment():
    a, b = [8200], [5500, 4900]
    g = R.MODELS["BLEND_G50_K50"]["gap"](a, b)
    assert g == pytest.approx(0.5 * R.GEOM78_DISPATCH(a, b) + 0.5 * R.KTC_DISPATCH(a, b))
    value, side = R.as_adjustment(a, b, R.MODELS["BLEND_G50_K50"]["gap"])
    raw_gap = sum(a) - sum(b)
    adjusted_gap = raw_gap + (value if side == 1 else -value)
    assert adjusted_gap == pytest.approx(g)
    assert side in (1, 2) and value > 0


@pytest.mark.parametrize("model", MONOTONE)
def test_monotone_candidates_hold_every_property(model):
    rng = random.Random(4242)
    gap = R.MODELS[model]["gap"]
    eps = 1.0 if model == "GEOM_78" else 1e-6
    for _ in range(300):
        A = [float(rng.randint(100, 9999)) for _ in range(rng.randint(1, 8))]
        B = [float(rng.randint(100, 9999)) for _ in range(rng.randint(1, 8))]
        g = gap(A, B)
        add = float(rng.randint(1, 9999))
        assert gap(A + [add], B) >= g - eps
        assert gap(A, B + [add]) <= g + eps
        assert gap(B, A) == pytest.approx(-g, abs=eps)
        assert gap(A[::-1], B[::-1]) == pytest.approx(g, abs=eps)
        assert gap([2 * v for v in A], [2 * v for v in B]) == pytest.approx(2 * g, abs=3 * eps)
        assert abs(gap(A, B + [1.0]) - g) <= 1.0 + eps  # no jump from a 1-point asset
    assert gap([5000.0], [4000.0]) == pytest.approx(1000.0, abs=eps)


def test_floored_geometric_keeps_a_depth_floor_the_incumbent_lacks():
    deep = [1000.0] * 30
    geom = R.MODELS["GEOM_78"]["gap"](deep, [1.0]) + 1.0
    floored = R.MODELS["FGEOM_70_20"]["gap"](deep, [1.0]) + 1.0
    assert geom < 4600  # saturates near 1 / (1 - 0.78) top-piece equivalents
    assert floored > 0.2 * 30_000  # every extra piece keeps >= 20% of its value


# ── box-only market-ledger scorer ─────────────────────────────────────────


def _p(cid):
    return {"kind": "player", "canonicalId": cid, "matchKey": cid, "position": "WR"}


SF = {"general": {"dynastyState": "dynasty"}, "offense": {"superflex": True}, "vendor": {}}


class FakeBoard(E.BoardIndex):
    def __init__(self, values):  # bypass contract parsing
        self._vals = values

    def values(self, asset):
        return dict(self._vals.get(asset.get("canonicalId"), {}))


def _trade(sides, fmt=SF, d="2026-10-01"):
    return {"underlyingTradeId": "utrade:x", "dedupeState": "CONFIRMED_UNIQUE",
            "sides": sides, "marketFormat": fmt, "occurredDate": d}  # fmt: skip


def test_market_scorer_uses_the_eligibility_owner_and_agrees_with_it():
    board = FakeBoard({"player:1": {"canonical": 6000.0}, "player:2": {"canonical": 3000.0},
                       "player:3": {"canonical": 2800.0}})  # fmt: skip
    one_qb = {**SF, "offense": {"superflex": False}}
    graded = [
        (_trade([[_p("player:2"), _p("player:3")], [_p("player:1")]]), board, date(2026, 9, 30)),
        (_trade([[_p("player:1")], [_p("player:2")]], fmt=one_qb), board, date(2026, 9, 30)),
        (_trade([[_p("player:1")], [_p("player:9")]]), board, date(2026, 9, 30)),
        (_trade([[_p("player:1")], [_p("player:2")]], d="2026-09-01"), board, date(2026, 9, 30)),
    ]
    rows, census = R.score_market_trades(graded)
    assert census["graded"] == 1 and census["ownerMismatch"] == 0
    assert census["notFullyPriced"] == 1
    assert census["board_basis_superflex_mismatch_or_unknown"] == 1
    assert census["board_after_trade_lookahead"] == 1
    assert rows[0]["A"] == [6000.0] and sorted(rows[0]["B"]) == [2800.0, 3000.0]
    assert "assetsA" not in rows[0]  # aggregates only: no trade contents


def test_market_evidence_publishes_no_trade_contents():
    rows = [{"ts": i, "A": [5000.0], "B": [3000.0, 2500.0], "shape": "1v2"} for i in range(10)]
    ev = R.trade_evidence(rows, seed=1, detail=False)
    assert ev["multiPieceTrades"] is None
