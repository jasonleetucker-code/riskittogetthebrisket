"""Topology, fit suitability and VA-correct residuals over underlying trades."""

from __future__ import annotations

from datetime import date

import pytest

from src.trade import market_trade_eval as E
from src.trade.ktc_va import adjusted_pair_totals


def P(cid, position="WR"):
    return {"kind": "player", "canonicalId": cid, "matchKey": cid, "position": position}


SF_FORMAT = {
    "general": {"dynastyState": "dynasty"},
    "offense": {"superflex": True},
    "vendor": {"tepLevel": 2},
}
ONEQB_FORMAT = {
    "general": {"dynastyState": "dynasty"},
    "offense": {"superflex": False},
    "vendor": {},
}


def trade(sides, fmt=None, state="CONFIRMED_UNIQUE", d="2026-10-01", **extra):
    return {
        "underlyingTradeId": "utrade:x",
        "dedupeState": state,
        "sides": sides,
        "marketFormat": fmt or SF_FORMAT,
        "occurredDate": d,
        **extra,
    }


@pytest.mark.parametrize(
    "sizes,expected",
    [
        ((1, 1), E.TOPO_1_FOR_1),
        ((2, 1), E.TOPO_2_FOR_1),
        ((3, 1), E.TOPO_N_FOR_1),
        ((2, 3), E.TOPO_MULTI),
    ],
)
def test_topology_classes(sizes, expected):
    sides = [[P(f"player:{i}{j}") for j in range(n)] for i, n in enumerate(sizes)]
    assert E.classify_topology(trade(sides))["topology"] == expected


def test_multi_team_and_one_sided():
    assert (
        E.classify_topology(trade([[P("player:1")], [P("player:2")], [P("player:3")]]))["topology"]
        == E.TOPO_MULTI_TEAM
    )
    assert E.classify_topology(trade([[P("player:1")], []]))["topology"] == E.TOPO_ONE_SIDED


def test_three_for_one_is_never_a_clean_equality():
    t = trade([[P("player:1")], [P("player:2"), P("player:3"), P("player:4")]])
    fit = E.fit_suitability(t, E.classify_topology(t))
    assert fit["fit"] == E.FIT_PACKAGE
    assert fit["reasons"] == ["consolidation_effects_require_package_model"]


def test_unsuitable_reasons_are_named():
    unresolved = {"kind": "unresolved", "canonicalId": None, "matchKey": "unresolved:9"}
    t = trade(
        [[P("player:1")], [unresolved]],
        fmt=ONEQB_FORMAT | {"offense": {"superflex": None}},
        state="POSSIBLE_OVERLAP",
    )
    fit = E.fit_suitability(t, E.classify_topology(t))
    assert fit["fit"] == E.FIT_UNSUITABLE
    assert {"includes_unresolved", "dedupe_state:POSSIBLE_OVERLAP", "qb_format_unknown"} <= set(
        fit["reasons"]
    )


def test_unresolved_asset_never_makes_a_trade_picks_only():
    unresolved = {"kind": "unresolved", "canonicalId": None, "matchKey": "u"}
    pick = {
        "kind": "pick",
        "canonicalId": "mpick:2027:r1",
        "matchKey": "mpick:2027:r1",
        "pick": {"round": 1},
    }
    flags = E.classify_topology(trade([[pick], [unresolved]]))["flags"]
    assert "picks_only" not in flags and "players_and_picks" in flags


class FakeBoard(E.BoardIndex):
    def __init__(self, values):  # noqa: D401 - bypass contract parsing
        self._vals = values

    def values(self, asset):
        return dict(self._vals.get(asset.get("canonicalId"), {}))


BOARD = FakeBoard(
    {
        "player:1": {"canonical": 6000.0, "srcA": 5800.0},
        "player:2": {"canonical": 3000.0, "srcA": 3100.0},
        "player:3": {"canonical": 2800.0},  # srcA does not price player:3
    }
)


def test_residual_uses_value_adjustment_not_raw_sums():
    t = trade([[P("player:2"), P("player:3")], [P("player:1")]])
    r = E.trade_residual(t, BOARD, "canonical")
    adj_a, adj_b, _, _ = adjusted_pair_totals([6000.0], [3000.0, 2800.0])
    assert r["adjustedA"] == round(adj_a, 1) and r["adjustedB"] == round(adj_b, 1)
    assert r["valueAdjustment"] > 0, "the consolidation side is credited"
    raw_rel = (6000.0 - 5800.0) / 5900.0
    assert r["relativeResidual"] != pytest.approx(raw_rel), "a raw-sum equality would be wrong"


def test_residual_coverage_is_all_or_nothing():
    t = trade([[P("player:2"), P("player:3")], [P("player:1")]])
    assert E.trade_residual(t, BOARD, "srcA") is None


def test_residual_report_excludes_1qb_and_lookahead_boards():
    one = trade([[P("player:1")], [P("player:2")]])
    oneqb = trade([[P("player:1")], [P("player:2")]], fmt=ONEQB_FORMAT)
    early = trade([[P("player:1")], [P("player:2")]], d="2026-09-01")
    rep = E.residual_report(
        [one, oneqb, early], BOARD, board_date=date(2026, 9, 30), sources=["canonical"]
    )
    assert rep["eligibleTrades"] == 1
    assert rep["excludedByReason"] == {
        "board_after_trade_lookahead": 1,
        "board_basis_superflex_mismatch_or_unknown": 1,
    }
    assert rep["perSource"]["canonical"]["inSampleRisk"] is True


def test_latent_readiness_reports_counts_and_builds_no_model():
    t1 = trade([[P("player:1")], [P("player:2")]])
    out = E.latent_fit_readiness([t1, t1])
    assert out["clean1for1Trades"] == 2 and out["shadowPrototypeBuilt"] is False
