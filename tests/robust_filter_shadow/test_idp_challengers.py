"""Evaluation helpers of the two IDP evidence challengers (synthetic records).

Pins the preregistered rules: origins / targets, missing targets counted and never
imputed, the leave-player-out ladder, the verdict tables and the board rails.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from src.robust_filter_shadow import idp_challengers as C


def _n3_row(vi, vc, dlf=None, pos="LB"):
    return {
        "pos": pos,
        "rookie": False,
        "votes": {},
        "inc": {"v": vi, "drop": [], "n": 3},
        "ch": {"v": vc, "drop": ["draftSharksIdp"] if vi != vc else [], "n": 3},
        "dlf": {"dlfIdp": {"v": dlf}} if dlf else {},
    }


def _days(n, rows_fn):
    start = date(2026, 9, 1)
    return {
        start + timedelta(days=i): {"n3": {"rows": rows_fn(i)}, "deepTail": {"rows": {}}}
        for i in range(n)
    }


def test_n3_units_grade_against_the_later_dlf_vote_and_count_missing_targets():
    def rows(i):
        return {
            "A": _n3_row(1000.0, 2000.0, dlf=1900.0),
            "B": _n3_row(1500.0, 900.0, dlf=None),  # no target: counted, not imputed
            "C": _n3_row(800.0, 800.0, dlf=700.0),  # not disputed
        }

    days = _days(30, rows)
    units, census = C.n3_units(days, 7)
    assert census["notEvaluable"] == census["evaluable"] == len(units)
    u = units[0]
    assert u["row"] == "A" and u["dropped"] == ["draftSharksIdp"]
    assert math.isclose(
        u["d"], abs(math.log(2000 / 1900)) - abs(math.log(1000 / 1900)), rel_tol=1e-12
    )


def test_n3_verdict_table():
    def h(point, lo, hi, n=40, days=12, blocks=5):
        return {
            "P1": {"point": point, "lo": lo, "hi": hi},
            "n": n,
            "originDays": days,
            "blocks": blocks,
        }

    sec_neg = [h(-0.1, -0.2, 0.0)] * 2 + [h(0.1, 0, 0.2)]
    assert C.n3_verdict(h(-0.1, -0.2, -0.01), sec_neg)["verdict"] == "PROMOTION-ELIGIBLE"
    assert C.n3_verdict(h(0.1, 0.01, 0.2), sec_neg)["verdict"] == "NOT BETTER"
    assert C.n3_verdict(h(-0.01, -0.1, 0.05), sec_neg)["verdict"] == "INCONCLUSIVE"
    assert C.n3_verdict(h(-0.1, -0.2, -0.01, n=29), sec_neg)["verdict"] == "INSUFFICIENT"


def test_leave_player_out_removes_only_the_players_own_point():
    points = [[501.0, 1000.0], [600.0, 800.0], [700.0, 600.0]]
    full = C.ladder_without(points, None)
    lpo = C.ladder_without(points, 600.0)
    assert full.value_at(600) == 800.0
    assert math.isclose(lpo.value_at(600), 1000.0 - 400.0 * 99.0 / 199.0, rel_tol=1e-12)
    assert lpo.ranks == (501.0, 700.0)


def test_repriceable_mirrors_the_registered_rules():
    vote = {"r": 650.0, "pool": "shared_market", "path": "rank_hill"}
    assert C.repriceable(vote, "draftSharksIdp")
    assert not C.repriceable(vote, "idpTradeCalc")
    assert not C.repriceable({**vote, "r": 500.0}, "draftSharksIdp")
    assert not C.repriceable({**vote, "pool": "idp"}, "draftSharksIdp")
    assert not C.repriceable({**vote, "path": "value_direct"}, "draftSharksIdp")


def test_spearman_and_h1_ratio():
    assert C._spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert C._spearman([1, 2, 3, 4], [4, 3, 2, 1]) == -1.0
    assert C._spearman([1, 1, 1], [1, 2, 3]) is None
    assert C.h1_ratio([{"inc": 0.02, "ch": 0.03}, {"inc": 0.02, "ch": 0.01}]) == 1.0


def test_board_rails_use_the_autopilot_limits():
    limits = {
        "maxUnpricedFraction": 0.05,
        "maxMedianAbsPctValueChange": 0.3,
        "maxP90AbsPctValueChange": 0.45,
        "maxSingleAbsPctValueChange": 0.65,
        "minTop25Overlap": 20,
        "minTop100Overlap": 85,
        "maxMedianAbsRankShift": 30,
        "maxP90AbsRankShift": 125,
    }
    rows = {f"p{i}": [10000.0 - i, 10000.0 - i, i + 1, i + 1, "offense"] for i in range(200)}
    assert C.board_rails(rows, limits)["pass"]
    rows["p0"] = [9999.0, 1000.0, 1, 150, "offense"]
    res = C.board_rails(rows, limits)
    assert not res["pass"] and res["metrics"]["maxAbsPctValueChange"] > 0.65
