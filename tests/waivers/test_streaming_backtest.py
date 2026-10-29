"""IDP streaming backtest harness (research / shadow, W3).

Synthetic fixtures only — no network, no live board.  Pins: roster
reconstruction and change attribution, the hold/rule scenarios, the leakage
boundary (a week-``w`` decision never reads data dated at or after week
``w``'s kickoff), harness legality enforcement for any policy (the interface
W4's solver will be called through), statistics/sample-size rules, slot
inference, isolation, and the committed evidence's privacy.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.waivers import streaming_backtest as sb

REPO = Path(__file__).resolve().parents[2]
MODULE = REPO / "src" / "waivers" / "streaming_backtest.py"
EVIDENCE = REPO / "docs" / "waivers" / "evidence" / "idp_streaming"

T0 = datetime(2026, 9, 10, 0, 20, tzinfo=timezone.utc)


def _cutoffs(weeks):
    first = {w: T0 + timedelta(days=7 * (w - 1)) for w in weeks}
    last = {w: first[w] + timedelta(days=4) for w in weeks}
    return first, last


def _tx(tx_id, tx_type, at, adds=None, drops=None, bid=None, rid=1):
    ms = int(at.timestamp() * 1000)
    return sb.Transaction(
        tx_id=tx_id,
        tx_type=tx_type,
        status="complete",
        leg=1,
        created_ms=ms,
        status_updated_ms=ms,
        roster_ids=(rid,),
        adds=adds or {},
        drops=drops or {},
        waiver_bid=bid,
    )


PLAYERS = {
    "q1": sb.PlayerInfo("QB", ("QB",)),
    "d1": sb.PlayerInfo("DL", ("DL",)),
    "d2": sb.PlayerInfo("DE", ("DL",)),  # sub-position -> DL group
    "d3": sb.PlayerInfo("DL", ("DL",)),
    "d4": sb.PlayerInfo("DT", ("DL",)),
    "l1": sb.PlayerInfo("LB", ("LB",)),
    "l2": sb.PlayerInfo("LB", ("LB",)),
    "l3": sb.PlayerInfo("LB", ("DL", "LB")),
    "b1": sb.PlayerInfo("DB", ("DB",)),
    "b2": sb.PlayerInfo("CB", ("DB",)),
    "b3": sb.PlayerInfo("S", ("DB",)),
}


def _data(points=None, projections=None, transactions=(), rosters=None):
    weeks = (1, 2, 3, 4)
    first, last = _cutoffs(weeks)
    base_rosters = {
        1: {"q1", "d1", "l1", "b1", "d2"},
        2: {"q1", "d1", "l1", "b1", "d2"},
    }
    rosters = rosters or {
        w: {rid: frozenset(players) for rid, players in base_rosters.items()} for w in weeks
    }
    pts = points or {
        w: {"q1": 20.0, "d1": 5.0, "d2": 2.0, "d3": 9.0, "l1": 6.0, "l2": 1.0, "b1": 4.0}
        for w in weeks
    }
    return sb.SeasonData(
        season=2026,
        scoring={"idp_tkl_solo": 1.0},
        roster_positions=["QB", "DL", "LB", "DB", "BN", "BN"],
        weeks=weeks,
        rosters=rosters,
        host_team_points={w: {} for w in weeks},
        host_player_points={w: {} for w in weeks},
        transactions=list(transactions),
        points=pts,
        played={w: frozenset(pts[w]) for w in weeks},
        projections=projections or {w: {} for w in weeks},
        players=dict(PLAYERS),
        cutoffs=first,
        week_ends=last,
    )


# ── lineup ──


def test_optimal_lineup_is_best_ball_on_realized_points_including_negative():
    pts = {"d1": -1.5, "d2": 0.0, "l1": 3.0, "b1": 2.0, "q1": 10.0}
    total, starters = sb.optimal_lineup(
        ["d1", "d2", "l1", "b1", "q1"], pts, PLAYERS, ["QB", "DL", "LB", "DB"]
    )
    assert starters == {"q1", "d2", "l1", "b1"}
    assert total == pytest.approx(15.0)


def test_scenario_lineup_keeps_actual_offense_and_swaps_only_defenders():
    data = _data()
    base, _ = sb.scenario_lineup(data, 1, 2, {"d1", "l1", "b1"})
    better, starters = sb.scenario_lineup(data, 1, 2, {"d3", "l1", "b1"})
    assert "q1" in starters
    assert better - base == pytest.approx(9.0 - 5.0)


# ── roster reconstruction + attribution ──


def test_effective_week_uses_the_weeks_last_kickoff():
    _, last = _cutoffs((1, 2, 3))
    first, _ = _cutoffs((1, 2, 3))
    # a Sunday free-agent add of week 2 (after week 2's first kickoff) is a week-2 move
    assert sb.effective_week(first[2] + timedelta(days=3), last) == 2
    assert sb.effective_week(last[2] + timedelta(hours=1), last) == 3


def test_forward_reconstruction_matches_host_rosters():
    first, last = _cutoffs((1, 2, 3))
    txs = [
        _tx("a", "waiver", last[1] + timedelta(days=1), adds={"d3": 1}, drops={"d2": 1}),
        _tx("b", "trade", first[3] + timedelta(days=1), adds={"l2": 1}, drops={"l1": 1}),
        sb.Transaction("c", "waiver", "failed", 1, 0, 0, (1,), {"b3": 1}, {}, None),
    ]
    start = {1: frozenset({"d1", "d2", "l1", "b1"})}
    recon = sb.reconstruct_rosters(start, 1, (1, 2, 3), txs, last)
    assert recon[2][1] == {"d1", "d3", "l1", "b1"}
    assert recon[3][1] == {"d1", "d3", "l2", "b1"}
    truth = {w: {1: recon[w][1]} for w in (1, 2, 3)}
    assert sb.reconstruction_agreement(recon, truth)["exactShare"] == 1.0


def test_classify_roster_changes_attributes_by_window_and_reports_unattributed():
    first, last = _cutoffs((1, 2, 3, 4))
    txs = [
        _tx("w1", "waiver", last[1] + timedelta(days=1), adds={"d3": 1}, drops={"d2": 1}, bid=4.0),
        _tx("t1", "trade", last[2] + timedelta(days=1), adds={"l2": 1}, drops={"l1": 1}),
    ]
    rosters = {
        1: {1: frozenset({"d1", "d2", "l1", "b1"})},
        2: {1: frozenset({"d1", "d3", "l1", "b1"})},
        3: {1: frozenset({"d1", "d3", "l2", "b1"})},
        4: {1: frozenset({"d1", "d3", "l2", "b1", "b2"})},  # nothing explains b2
    }
    data = _data(transactions=txs, rosters=rosters)
    got = {
        (c.week, c.player_id, c.direction): (c.kind, c.waiver_bid)
        for c in sb.classify_roster_changes(data)
    }
    assert got[(2, "d3", "add")] == ("waiver", 4.0)
    assert got[(2, "d2", "drop")] == ("waiver", None)
    assert got[(3, "l2", "add")] == ("trade", None)
    assert got[(4, "b2", "add")] == ("unattributed", None)


def test_hold_applies_trades_but_not_waiver_streaming():
    first, last = _cutoffs((1, 2, 3, 4))
    txs = [
        _tx("w1", "waiver", last[1] + timedelta(days=1), adds={"d3": 1}, drops={"d2": 1}),
        _tx("t1", "trade", last[2] + timedelta(days=1), adds={"l2": 1}, drops={"l1": 1}),
    ]
    rosters = {
        1: {1: frozenset({"q1", "d1", "d2", "l1", "b1"})},
        2: {1: frozenset({"q1", "d1", "d3", "l1", "b1"})},
        3: {1: frozenset({"q1", "d1", "d3", "l2", "b1"})},
        4: {1: frozenset({"q1", "d1", "d3", "l2", "b1"})},
    }
    data = _data(transactions=txs, rosters=rosters)
    hold = sb.simulate_hold(data, 1, sb.classify_roster_changes(data))
    assert [r.idp_set for r in hold] == [
        {"d1", "d2", "l1", "b1"},
        {"d1", "d2", "l2", "b1"},
        {"d1", "d2", "l2", "b1"},
    ]
    actual = sb.simulate_actual(data, 1)
    assert actual[0].idp_set == {"d1", "d3", "l1", "b1"}


# ── pool + rule policies ──


def test_pool_excludes_other_rosters_and_masked_excludes_this_weeks_claims():
    rosters = {
        1: {1: frozenset({"d1"}), 2: frozenset({"l1"})},
        2: {1: frozenset({"d1"}), 2: frozenset({"l1", "d3"})},
        3: {1: frozenset({"d1"}), 2: frozenset({"l1"})},
        4: {1: frozenset({"d1"}), 2: frozenset({"l1"})},
    }
    data = _data(rosters=rosters)
    unmasked = sb.available_pool(data, 1, 2, {"d1"}, masked=False)
    masked = sb.available_pool(data, 1, 2, {"d1"}, masked=True)
    assert "l1" not in unmasked and "d1" not in unmasked and "d3" in unmasked
    assert "d3" not in masked


def _ctx(data, week, roster, pool, max_swaps=3, **kw):
    return sb.build_decision_context(
        data, week=week, team_index=0, idp_roster=roster, pool=pool, max_swaps=max_swaps, **kw
    )


def test_previous_week_rule_swaps_within_group_on_strict_improvement_only():
    data = _data()
    ctx = _ctx(data, 2, {"d1", "d2", "l1", "b1"}, {"d3", "l2", "b2"})
    swaps = sb.MetricSwapPolicy("p", sb.metric_previous_week).decide(ctx)
    # d3 (9) replaces the lowest DL (d2, 2); l2 (1) < l1 (6): no LB swap;
    # b2 has no stat line -> unknown -> never added (unknown is not zero)
    assert swaps == [sb.Swap("d2", "d3", 0.0)]


def test_rule_respects_max_swaps_and_never_readds_a_same_week_release():
    pts = {
        w: {"d1": 1.0, "d2": 2.0, "d3": 9.0, "d4": 8.0, "l1": 1.0, "l2": 7.0} for w in (1, 2, 3, 4)
    }
    data = _data(points=pts)
    ctx = _ctx(data, 2, {"d1", "d2", "l1"}, {"d3", "d4", "l2"}, max_swaps=2)
    swaps = sb.MetricSwapPolicy("p", sb.metric_previous_week).decide(ctx)
    assert len(swaps) == 2
    assert swaps[0] == sb.Swap("d1", "d3", 0.0)
    released = {s.drop_id for s in swaps}
    assert not released & {s.add_id for s in swaps}


def test_rolling_metric_needs_two_played_weeks():
    pts = {1: {"d1": 4.0}, 2: {"d1": 8.0, "d3": 30.0}, 3: {"d1": 6.0}, 4: {}}
    data = _data(points=pts)
    ctx = _ctx(data, 4, {"d1"}, {"d3"})
    assert sb.metric_rolling("d1", ctx) == pytest.approx(6.0)
    assert sb.metric_rolling("d3", ctx) is None


def test_dynasty_release_drops_unpriced_first_then_lowest_value():
    proj = {
        2: {
            p: sb.Projection(v, None)
            for p, v in {"d1": 3.0, "d2": 4.0, "d4": 2.0, "d3": 9.0}.items()
        }
    }
    data = _data(projections={**{w: {} for w in (1, 2, 3, 4)}, **proj})
    values = {"d1": 500.0, "d2": 100.0}

    ctx = _ctx(data, 2, {"d1", "d2", "d4"}, {"d3"}, dynasty_lookup=lambda p, _t: values.get(p))
    assert sb.DynastyReleasePolicy().decide(ctx)[0] == sb.Swap("d4", "d3", 0.0)
    ctx2 = _ctx(data, 2, {"d1", "d2"}, {"d3"}, dynasty_lookup=lambda p, _t: values.get(p))
    assert sb.DynastyReleasePolicy().decide(ctx2)[0] == sb.Swap("d2", "d3", 0.0)


# ── leakage boundary ──


def test_decision_context_never_reads_week_w_or_later():
    data = _data()
    ctx = _ctx(data, 3, {"d1", "d2"}, {"d3"})
    assert all(w < 3 for hist in ctx.realized_before.values() for w in hist)
    assert ctx.cutoff_utc == data.cutoffs[3]
    assert ctx.projection_point_in_time_verified is False


def test_future_data_cannot_change_a_decision():
    """Rewrite every realized score of weeks >= w and every projection of
    weeks > w: the week-w context and decision must be identical."""
    proj = {
        w: {"d3": sb.Projection(9.0, None), "d1": sb.Projection(3.0, None)} for w in (1, 2, 3, 4)
    }
    a = _data(projections=proj)
    future_pts = {w: dict(p) for w, p in a.points.items()}
    future_proj = {w: dict(p) for w, p in a.projections.items()}
    for w in (3, 4):
        future_pts[w] = {pid: 1000.0 - v for pid, v in future_pts[w].items()} | {"l2": 500.0}
    future_proj[4] = {"l2": sb.Projection(999.0, None)}
    b = replace(
        a,
        points=future_pts,
        played={w: frozenset(future_pts[w]) for w in a.weeks},
        projections=future_proj,
    )
    for metric in (sb.metric_previous_week, sb.metric_rolling, sb.metric_projection):
        ca = _ctx(a, 3, {"d1", "d2", "l1"}, {"d3", "l2"})
        cb = _ctx(b, 3, {"d1", "d2", "l1"}, {"d3", "l2"})
        assert ca == cb
        policy = sb.MetricSwapPolicy("p", metric)
        assert policy.decide(ca) == policy.decide(cb)


def test_dynasty_lookup_is_asked_only_for_the_cutoff_instant():
    data = _data()
    asked = []

    def lookup(pid, instant):
        asked.append(instant)
        return None

    _ctx(data, 2, {"d1"}, {"d3"}, dynasty_lookup=lookup)
    assert asked and all(t == data.cutoffs[2] for t in asked)


# ── harness legality (the W4 / baseline-7 interface) ──


class _BadPolicy:
    name = "bad"

    def decide(self, ctx):
        return [
            sb.Swap("nobody", "d3"),  # drop not rostered
            sb.Swap("d1", "q1"),  # add not in pool
            sb.Swap("d2", "d3"),  # legal
            sb.Swap("d1", "d4"),  # beyond max_swaps=3: never applied
            sb.Swap("l1", "l2"),  # beyond max_swaps
        ]


def test_harness_rejects_illegal_swaps_and_caps_swaps():
    data = _data()
    res = sb.simulate_policy(data, 1, 0, _BadPolicy(), [], max_swaps=3, masked=True)
    week2 = res[0]
    assert week2.adds == ("d3",) and week2.drops == ("d2",)
    assert week2.rejected_swaps == 2
    assert week2.faab == 0.0


def test_policy_protocol_shape():
    for policy in (sb.MetricSwapPolicy("x", sb.metric_projection), sb.DynastyReleasePolicy()):
        assert isinstance(policy.name, str) and callable(policy.decide)
    fields = set(sb.DecisionContext.__dataclass_fields__)
    assert {
        "season",
        "week",
        "cutoff_utc",
        "idp_roster",
        "pool",
        "realized_before",
        "projection",
        "dynasty_value",
        "max_swaps",
    } <= fields


# ── statistics ──


def test_bootstrap_is_deterministic_and_verdicts_follow_the_ci():
    vals = [5.0, 6.0, 7.0, 4.0, 8.0, 5.5]
    assert sb.bootstrap_ci(vals) == sb.bootstrap_ci(vals)
    assert sb.verdict(sb.bootstrap_ci(vals)) == "gains"
    assert sb.verdict(sb.bootstrap_ci([-v for v in vals])) == "loses"
    assert sb.verdict((-1.0, 1.0)) == "no_detectable_effect"


def test_below_minimum_is_insufficient_never_a_ci():
    out = sb.summarize_deltas([10.0] * 5, minimum=6)
    assert out["verdict"] == "INSUFFICIENT" and out["ci95"] is None and out["n"] == 5
    clustered = sb.summarize_deltas([1.0] * 10, minimum=6, clusters=[[1.0] * 5, [1.0] * 5])
    assert clustered["verdict"] == "INSUFFICIENT" and clustered["nClusters"] == 2


# ── slot inference ──


def test_slot_inference_recovers_slots_and_flags_manager_set_lineups():
    starters = {
        1: {1: ["q1", "d2", "l3", "b1"], 2: ["q1", "d1", "l1", "b2"]},
    }
    slots = sb.infer_slots_from_starters(starters, PLAYERS)
    assert slots == ["QB", "DL", "LB", "DB"]
    data = _data()
    data.host_starters = starters
    assert sb.host_lineups_legal(data, slots)
    assert not sb.host_lineups_legal(data, ["QB", "LB", "LB", "DB"])


# ── isolation + privacy ──

ALLOWED_SRC_IMPORTS = {
    "src.league_intel.scorer",
    "src.ros.lineup",
    "src.history.asof",
    "src.history.keys",
    "src.history.store",
    "src.public_league",
    "src.public_league.sleeper_client",
    "src.league_comparison.sleeper_stats",
    "src.nfl_data.realized_points",
    "src.nfl_data",
    "src.nfl_data.ingest",
    "src.ros.sleeper_weekly_projections",
}


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module, {a.name for a in node.names}
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, set()


def test_nothing_live_imports_the_backtest():
    target = "src.waivers.streaming_backtest"
    offenders = []
    roots = [REPO / "src", REPO / "scripts", REPO / "deploy"]
    files = [p for root in roots if root.exists() for p in root.rglob("*.py")]
    files.append(REPO / "server.py")
    for path in files:
        if path == MODULE:
            continue
        for module, names in _imports(path):
            if module == target or (module == "src.waivers" and "streaming_backtest" in names):
                offenders.append(str(path.relative_to(REPO)))
    assert offenders == []


def test_backtest_imports_only_allowlisted_owners():
    bad = []
    for module, _names in _imports(MODULE):
        if module.startswith("src.") and module not in ALLOWED_SRC_IMPORTS:
            bad.append(module)
        if module in ("server",) or module.startswith("src.api"):
            bad.append(module)
    assert bad == []


def test_committed_evidence_carries_no_platform_ids_or_names():
    files = list(EVIDENCE.glob("*.json")) if EVIDENCE.exists() else []
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\d{12,}", text), f"{path.name}: long numeric id"
        blob = json.loads(text)
        keys = set()

        def walk(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    keys.add(k)
                    walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    walk(v)

        walk(blob)
        assert not keys & {"owners", "rosterOwners", "display_name", "managerRosterId", "_rid"}


def test_privacy_guard_flags_names_team_names_and_ids():
    blob = '{"label": "manager B", "note": "Team Tacos", "x": 1312006700437352448}'
    leaks = sb.privacy_violations(blob, {"Team Tacos", "someone", ""})
    assert "Team Tacos" in leaks and "1312006700437352448" in leaks and "someone" not in leaks
    assert sb.privacy_violations('{"label": "manager B", "v": 12.5}', {"someone"}) == []
