"""The depth-disclosure owner (``src/trade/depth_disclosure.py``): definitions
and rule A-guarded, design ``docs/trade/LOW_VALUE_DEPTH_DISCLOSURE_DESIGN_2026-10-20.md``
§2-§3 as chosen by the owner on 2026-10-21 (LVA Package 4, V4)."""

from __future__ import annotations

import ast
import json
import random
from pathlib import Path

import pytest

from src.trade import depth_disclosure as dd
from src.trade.analyze_trade import _market_lens, equity_verdict
from tests.trade import depth_disclosure_fixture as F

REPO = Path(__file__).resolve().parents[2]


def _lines(**over):
    base = dict(
        league_key="main",
        replacement={"QB": 1923.0, "WR": 1802.0, "TE": 2061.0, "DB": 2156.0},
        lowest_starter={"QB": 1988.0, "WR": 1510.0, "TE": 1671.0, "DB": 1335.0},
        pick_line=1687.0,
        include_picks=True,
        guard=True,
        version="lvd_disclosure_v1",
    )
    base.update(over)
    return dd.DepthLines(**base)


# ── config: only the owner's choices exist ─────────────────────────────────


def test_config_is_the_owners_v4_choice():
    cfg = dd.load_config()
    assert cfg["rule"] == "A_guarded" and cfg["threshold"] == "floor"
    assert cfg["includePicks"] is True and cfg["guard"] is True
    assert cfg["surfaces"] == ["calculator", "war_room"]
    assert cfg["teamContextIntegration"] == "held_until_pr_1890"


@pytest.mark.parametrize(
    "patch", [{"threshold": "prereg"}, {"rule": "B_share25"}, {"guard": "yes"}, {"version": ""}]
)
def test_config_refuses_a_choice_the_owner_did_not_make(tmp_path, patch):
    cfg = json.loads(dd.CONFIG_PATH.read_text(encoding="utf-8"))
    cfg.update(patch)
    p = tmp_path / "c.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    with pytest.raises(dd.DepthDisclosureConfigError):
        dd.load_config(p)


# ── §2.2 classification (floor threshold) ─────────────────────────────────


@pytest.mark.parametrize(
    "asset,expected",
    [
        (F.asset("x", 1500, "WR"), "lvd"),  # below min(1802, 1510)
        (F.asset("x", 1510, "WR"), "not_lvd"),  # exactly the lowest starter
        (F.asset("x", 1700, "WR"), "not_lvd"),  # below R, above S: the floor protects it
        (F.asset("x", 1900, "QB"), "lvd"),  # min(1923, 1988)
        (F.asset("x", 1300, "DB"), "lvd"),
        (F.asset("x", 1340, "DB"), "not_lvd"),
        (F.asset("x", 1000, "RB"), "unknown"),  # no line for the position
        (F.asset("x", 900, "K"), "unknown"),
        (F.asset("x", 0, "WR"), "unknown"),  # unpriced is never zero, never LVD
        (F.asset("x", None, "WR"), "unknown"),
        (F.asset("x", 1500, "WR", quarantined=True), "unknown"),
        (F.asset("p", 1686, "PICK"), "lvd"),
        (F.asset("p", 1687, "PICK"), "not_lvd"),  # a pick at exactly R_* is not LVD
    ],
)
def test_classification_table(asset, expected):
    assert dd.classify_piece(asset, _lines()) == expected


def test_pick_line_unavailable_is_unknown_and_picks_excluded_is_not_lvd():
    pick = F.asset("p", 900, "PICK")
    assert dd.classify_piece(pick, _lines(pick_line=None)) == "unknown"
    assert dd.classify_piece(pick, _lines(include_picks=False)) == "not_lvd"


def test_no_optimal_lineup_starter_is_ever_lvd_under_the_floor():
    """Property over the fixture board: every starter's value >= S_pos."""
    c = F.contract()
    lines = dd.league_depth_lines(c, "main", F.SETTINGS)
    assert isinstance(lines, dd.DepthLines)
    rows = {r["displayName"]: r for r in c["playersArray"]}
    for team in c["sleeper"]["teams"]:
        for name in team["optimalLineup"]["starters"]:
            r = rows[name]
            a = F.asset(name, r["rankDerivedValue"], r["position"])
            assert dd.classify_piece(a, lines) == "not_lvd", name


# ── §2.1 league lines ─────────────────────────────────────────────────────


def test_league_lines_come_from_the_canonical_owners():
    lines = dd.league_depth_lines(F.contract(), "main", F.SETTINGS)
    assert isinstance(lines, dd.DepthLines)
    assert lines.replacement["WR"] == 1802.0  # best unrostered WR
    assert lines.lowest_starter["WR"] == 5197.0  # min over both lineups
    assert lines.pick_line is not None and lines.pick_line > 0


@pytest.mark.parametrize(
    "mutate,reason",
    [
        (lambda c: c["sleeper"]["teams"][1].pop("optimalLineup"), "no_lineups"),
        (lambda c: c["sleeper"]["teams"].pop(), "no_rosters"),
        (lambda c: c.pop("playersArray"), "no_board"),
    ],
)
def test_league_lines_fail_closed(mutate, reason):
    c = F.contract()
    mutate(c)
    assert dd.league_depth_lines(c, "main", F.SETTINGS) == f"lines_unavailable:{reason}"


def test_league_lines_need_the_leagues_own_starter_counts():
    out = dd.league_depth_lines(F.contract(), "main", {"teamCount": 2})
    assert out == "lines_unavailable:no_starter_counts"


# ── §3.1 rule A-guarded ───────────────────────────────────────────────────


def test_worked_example_1_fires_for_the_receiver_only():
    lines = dd.league_depth_lines(F.contract(), "main", F.SETTINGS)
    out = dd.evaluate_two_team(F.HURTS_FOR_EGBUKA_HODGINS, lines)
    me, partner = out["self"], out["partner"]
    assert me.fires and me.region == "fair" and me.counterfactual_region == "against"
    assert me.extra_groups == ("offense",)
    assert not partner.fires and partner.reason == "no_low_value_depth"


def test_real_region_is_the_served_market_lens_band():
    """The rule's real result is the market lens's own, not a second band."""
    lines = dd.league_depth_lines(F.contract(), "main", F.SETTINGS)
    sim = F.HURTS_FOR_EGBUKA_HODGINS
    me = dd.evaluate_two_team(sim, lines)["self"]
    assert me.band == _market_lens(dict(sim)).detail["band"]["level"]


def test_the_top_piece_is_never_removed():
    # A 1-for-1 of two low-value pieces is not a padding question.
    d = dd.team_depth_disclosure(
        [F.asset("a", 900, "WR")], [F.asset("b", 1400, "WR")], _lines(), verdict=equity_verdict
    )
    assert d.reason == "no_low_value_depth"


def test_top_piece_ties_go_to_the_lowest_asset_id():
    rcv = [F.asset("a", 1000, "WR", asset_id="z"), F.asset("b", 1000, "WR", asset_id="a")]
    assert dd.top_piece_index(rcv) == 1


def test_the_guard_suppresses_a_swap_of_low_value_pieces():
    rcv = [F.asset("a", 1400, "WR"), F.asset("b", 1300, "WR")]
    gv = [F.asset("c", 1450, "WR")]
    d = dd.team_depth_disclosure(rcv, gv, _lines(), verdict=equity_verdict)
    assert d.region != d.counterfactual_region  # dependence alone would fire
    assert d.state == dd.STATE_NOT_SHOWN and d.reason == "only_low_value_pieces"
    unguarded = dd.team_depth_disclosure(rcv, gv, _lines(guard=False), verdict=equity_verdict)
    assert unguarded.fires


def test_result_that_does_not_depend_on_the_depth_does_not_fire():
    rcv = [F.asset("star", 9000, "WR"), F.asset("f", 600, "WR")]
    gv = [F.asset("g", 3000, "WR")]
    d = dd.team_depth_disclosure(rcv, gv, _lines(), verdict=equity_verdict)
    assert d.reason == "result_does_not_depend" and d.region == d.counterfactual_region


def test_one_sided_and_unknown_pieces_are_not_evaluated():
    lines = _lines()
    assert dd.team_depth_disclosure([], [F.asset("a", 5000, "WR")], lines).reason == "one_sided"
    d = dd.team_depth_disclosure(
        [F.asset("a", 5000, "WR"), F.asset("k", 900, "K")], [F.asset("b", 5000, "WR")], lines
    )
    assert d.state == dd.STATE_NOT_EVALUATED and d.reason == "unknown_piece"


def test_preconditions_refuse_both_teams():
    sim = F.HURTS_FOR_EGBUKA_HODGINS
    out = dd.evaluate_two_team(sim, "lines_unavailable:no_lineups")
    assert {d.reason for d in out.values()} == {"lines_unavailable:no_lineups"}
    unpriced = F.simulation(
        [*sim["receiving"], F.asset("Ghost", 0, "WR")], sim["sending"], unresolvedIn=[]
    )
    lines = dd.league_depth_lines(F.contract(), "main", F.SETTINGS)
    out = dd.evaluate_two_team(unpriced, lines)
    assert {d.reason for d in out.values()} == {"unknown_piece:unpriced_assets"}
    off_board = F.simulation(sim["receiving"], sim["sending"], unresolvedIn=["Nobody"])
    out = dd.evaluate_two_team(off_board, lines)
    assert {d.reason for d in out.values()} == {"unknown_piece:off_board_assets"}


def test_package_model_rollback_is_not_evaluated(monkeypatch):
    from src.trade import analyze_service

    monkeypatch.setattr(analyze_service, "package_model_ready", lambda: False)
    lines = dd.league_depth_lines(F.contract(), "main", F.SETTINGS)
    out = dd.evaluate_two_team(F.HURTS_FOR_EGBUKA_HODGINS, lines)
    assert {d.reason for d in out.values()} == {"package_model_unavailable"}


def test_monotonicity_removing_received_pieces_never_helps_the_receiver():
    """Guards the design's no-lean argument: the counterfactual can only move
    a team AGAINST itself (an added piece never hurts, geom_q078_v1)."""
    order = {"against": -1, "fair": 0, "favour": 1}
    rng = random.Random(1102)
    lines = _lines()
    for _ in range(400):
        rcv = [F.asset(f"r{i}", rng.randint(300, 9000), "WR") for i in range(rng.randint(2, 4))]
        gv = [F.asset(f"g{i}", rng.randint(300, 9000), "WR") for i in range(rng.randint(1, 3))]
        d = dd.team_depth_disclosure(rcv, gv, lines, verdict=equity_verdict)
        if d.counterfactual_region is not None:
            assert order[d.counterfactual_region] <= order[d.region], (rcv, gv)


def test_locality_permuting_pieces_gives_the_same_answer():
    rng = random.Random(7)
    lines = _lines()
    for _ in range(100):
        rcv = [F.asset(f"r{i}", rng.randint(300, 9000), "WR") for i in range(3)]
        gv = [F.asset(f"g{i}", rng.randint(300, 9000), "WR") for i in range(2)]
        a = dd.team_depth_disclosure(rcv, gv, lines, verdict=equity_verdict)
        b = dd.team_depth_disclosure(rcv[::-1], gv[::-1], lines, verdict=equity_verdict)
        assert a == b


# ── structure: no second band, utility or threshold ────────────────────────


def test_the_owner_defines_no_fairness_math():
    """AST: the module calls no band, utility or package-model function and
    holds no numeric threshold -- the verdict and the band are the owners'."""
    src = (REPO / "src/trade/depth_disclosure.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden_calls = {
        "classify",
        "classify_packages",
        "larger_package_utility",
        "package_utilities",
        "fair_threshold",
        "geom_utility",
        "adjusted_pair_totals",
        "fairness_base",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            assert name not in forbidden_calls, name
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [getattr(node, "module", "") or ""] + [a.name for a in node.names]
            # The readiness probe is the N-team engine's (analyze_service);
            # importing the package-model module itself is what is forbidden.
            assert not any(m.endswith("package_model") for m in mods), mods
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            assert node.value == 0.0, node.value
        if isinstance(node, ast.Constant) and type(node.value) is int:
            assert node.value in (0, 1, 2), node.value
