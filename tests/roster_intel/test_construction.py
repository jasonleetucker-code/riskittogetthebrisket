"""Roster Construction V1 — Phase 5 acceptance scenarios on deterministic fixtures.

Owner directive 2026-10-30, PHASE 5 scenarios 1-10 (scenario 10 is a
cross-reference; see ``test_scenario_10_*``).  Every league here is a real
``PublicLeagueSnapshot`` run through the production path
(snapshot -> player_impact -> construction).
"""

from __future__ import annotations

import copy

import pytest

from src.roster_intel import construction as rc
from tests.roster_intel.rc_support import (
    DYNASTY_MAIN_SLOTS,
    WEEKS,
    build_snapshot,
    compute,
    league_of,
    make_contract,
    positions_of,
)

_TX_KEYS = {"add", "adds", "drop", "drops", "transaction", "transactions", "trade", "claim"}


def _contract_for(teams, values=None, ages=None, key="k"):
    pos = positions_of(teams)
    vals = {pid: 1000.0 for pid in pos}
    vals.update(values or {})
    return make_contract(key, {rid: list(t) for rid, t in teams.items()}, vals, pos, ages)


def _position(payload, g):
    return next(p for p in payload["positions"] if p["position"] == g)


def _player(payload, pid):
    return next(p for p in payload["players"] if p["playerId"] == pid)


def _diag(payload, rule, g=None):
    return next(d for d in payload["diagnoses"] if d["rule"] == rule and d["position"] == g)


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


# ── Scenario 1: real configured starters and defensive scoring ───────────
def test_scenario_1_real_slots_and_idp_are_respected():
    teams = league_of(4)
    payload, ls = compute(build_snapshot(teams), contract=_contract_for(teams))
    assert payload["rules"]["starterSlots"] == DYNASTY_MAIN_SLOTS
    assert payload["rules"]["slotSource"] == "sleeper_roster_positions"
    assert payload["rules"]["lineupBasis"] == rc.BASIS_HOST_BEST_BALL
    assert payload["rules"]["positionGroups"] == ["QB", "RB", "WR", "TE", "K", "DL", "LB", "DB"]
    for wk in WEEKS:
        for rid, sol in ls.solutions[wk].items():
            assert sol.valid and sol.parity == rc.PARITY_REPRODUCED
            assert not sol.unfilled_slots
            fams = [rc.group_of(ls.si.players[pid]) for _i, _s, pid, _p in sol.assigned]
            assert (fams.count("DL"), fams.count("LB"), fams.count("DB")) == (3, 3, 3)
            assert fams.count("TE") >= 2 and fams.count("K") == 1
    # The production groups add up to the lineup, exactly.
    for rid in ls.team_ids:
        total = sum(ls.production[rid][g]["points"] for g in ls.groups)
        lineups = sum(ls.solutions[wk][rid].score for wk in WEEKS)
        assert total == pytest.approx(lineups, abs=0.05)


def test_scenario_1_every_team_is_ranked_with_its_denominator():
    teams = league_of(4)
    payload, _ = compute(build_snapshot(teams), contract=_contract_for(teams))
    for pos in payload["positions"]:
        assert pos["production"]["of"] == 4
        assert 1 <= pos["production"]["rank"] <= 4
        assert pos["value"]["of"] == 4


# ── Scenario 2: player acquired / traded halfway through the season ──────
def test_scenario_2_midseason_trade_splits_ownership_and_denominators():
    teams = league_of(4)
    star = "t1-wr1"
    own = {star: {w: (1 if w <= 4 else 2) for w in WEEKS}}
    snap = build_snapshot(teams, ownership=own)
    p1, ls = compute(snap, roster_id=1)
    p2, _ = compute(snap, roster_id=2)
    a, b = _player(p1, star), _player(p2, star)
    assert a["ownedWeeks"] == 4 and a["ownershipSpells"] == [{"fromWeek": 1, "toWeek": 4}]
    assert b["ownedWeeks"] == 4 and b["ownershipSpells"] == [{"fromWeek": 5, "toWeek": 8}]
    assert a["starts"]["of"] == 4 and b["starts"]["of"] == 4
    # Team 1's WR production never includes his weeks on team 2.
    for wk in (5, 6, 7, 8):
        assert star not in ls.solutions[wk][1].assigned_ids
        assert star in ls.solutions[wk][2].roster
    # League startability is a property of the player, over every observed week.
    assert a["leagueStartable"]["of"] == b["leagueStartable"]["of"] == 8


# ── Scenario 3: a FLEX contributor counts once, at his own position ──────
def test_scenario_3_flex_wr_counts_once_as_wr():
    teams = league_of(4)
    teams[1]["t1-wr4"] = ("WR", lambda _w: 25.0)  # a 4th WR good enough for FLEX
    payload, ls = compute(build_snapshot(teams))
    wr = _position(payload, "WR")["production"]
    assert wr["slotAllocation"]["FLEX"]["starts"] >= 1
    assert "FLEX" not in payload["rules"]["positionGroups"]
    for wk in WEEKS:
        sol = ls.solutions[wk][1]
        ids = [pid for _i, _s, pid, _p in sol.assigned]
        assert len(ids) == len(set(ids))
        wr_pts = sum(p for _i, _s, pid, p in sol.assigned if pid.split("-")[1].startswith("wr"))
        week_row = next(r for r in wr["weekly"] if r["week"] == wk)
        assert week_row["points"] == pytest.approx(wr_pts, abs=0.01)
    assert sum(v["starts"] for v in wr["slotAllocation"].values()) == wr["appearances"]


# ── Scenario 4: a valuable injured player with no current points ─────────
def test_scenario_4_injured_valuable_player_explains_the_gap_no_action():
    teams = league_of(4)
    for pid in [p for p, s in teams[1].items() if s[0] == "TE"]:
        teams[1][pid] = ("TE", lambda _w: 1.0)
    teams[1]["t1-te9"] = ("TE", lambda _w: 0.0)
    values = {"t1-te9": 9000.0}
    snap = build_snapshot(teams)
    snap.nfl_players["t1-te9"]["injury_status"] = "IR"
    payload, _ = compute(snap, contract=_contract_for(teams, values))
    te = _position(payload, "TE")
    assert te["value"]["rank"] == 1 and te["production"]["rank"] == 4
    inj = _player(payload, "t1-te9")
    assert "injured" in inj["tags"]
    assert inj["zeroPointWeeks"] == 8 and inj["starts"]["of"] == 8
    d = _diag(payload, "RC-D1", "TE")
    assert d["status"] == rc.STATUS_FIRED and d["verdict"] == rc.VERDICT_NO_ACTION
    assert "injured" in d["explanation"]
    assert d["evidence"]["valueRank"] == [1, 4] and d["evidence"]["productionRank"] == [4, 4]


def test_scenario_4b_unexplained_gap_is_review_with_evidence():
    teams = league_of(4)
    for pid in [p for p, s in teams[1].items() if s[0] == "TE"]:
        teams[1][pid] = ("TE", lambda _w: 1.0)
    vals = {p: 8000.0 for p, s in teams[1].items() if s[0] == "TE"}
    payload, _ = compute(build_snapshot(teams), contract=_contract_for(teams, vals))
    d = _diag(payload, "RC-D1", "TE")
    assert d["verdict"] == rc.VERDICT_REVIEW
    assert d["evidence"]["holders"]


# ── Scenario 5: simultaneous spike weeks, only some enter ────────────────
def test_scenario_5_simultaneous_spikes_only_the_optimum_enters():
    teams = league_of(4)
    teams[1]["t1-wr7"] = ("WR", lambda w: 44.0 if w == 3 else 1.0)
    teams[1]["t1-wr8"] = ("WR", lambda w: 43.0 if w == 3 else 1.0)
    for pid, (p, fn) in list(teams[1].items()):
        if p == "WR" and pid not in ("t1-wr7", "t1-wr8"):
            teams[1][pid] = (p, lambda w, fn=fn: 40.0 + int(fn(w)) if w == 3 else fn(w))
    payload, ls = compute(build_snapshot(teams))
    sol = ls.solutions[3][1]
    wr_started = [p for _i, _s, pid, p in sol.assigned if pid.split("-")[1].startswith("wr")]
    wr_bench = [
        sol.points[pid]
        for pid in sol.roster
        if pid.split("-")[1].startswith("wr") and pid not in sol.assigned_ids
    ]
    assert len(wr_started) < 8 and wr_bench
    assert min(wr_started) >= max(wr_bench)
    assert _position(payload, "WR")["depth"]["redundantStartableWeeks"] >= 1


# ── Scenario 6: great starters, inadequate backup coverage ───────────────
def test_scenario_6_great_starters_thin_backups_flags_coverage():
    teams = league_of(4)
    for pid in [p for p, s in teams[1].items() if s[0] == "RB"]:
        del teams[1][pid]
    teams[1]["t1-rbx"] = ("RB", lambda w: 0.0 if w in (2, 5) else 40.0)
    teams[1]["t1-rby"] = ("RB", lambda w: 0.0 if w in (3, 6) else 40.0)
    payload, _ = compute(build_snapshot(teams), contract=_contract_for(teams))
    rb = _position(payload, "RB")
    assert rb["production"]["rank"] == 1
    assert rb["depth"]["holes"]["dedicated"] >= 2
    d = _diag(payload, "RC-D2", "RB")
    assert d["status"] == rc.STATUS_FIRED and d["verdict"] == rc.VERDICT_REVIEW
    assert d["evidence"]["depthInsuranceRatio"] <= d["evidence"]["leagueP25"]
    assert "Waiver Advisor" in d["explanation"]
    deep, _ = compute(build_snapshot(teams), contract=_contract_for(teams), roster_id=2)
    assert _diag(deep, "RC-D2", "RB")["status"] != rc.STATUS_FIRED


# ── Scenario 7: overfilled roster that must make a legal drop ────────────
def test_scenario_7_overfilled_roster_is_reported_never_resolved():
    teams = league_of(4)
    teams[1]["t1-extra"] = ("WR", lambda _w: 1.0)
    payload, ls = compute(build_snapshot(teams), roster_limit=30)
    assert payload["team"]["rosterOverLimitWeeks"] == WEEKS
    assert payload["rules"]["rosterLimit"] == 30
    assert all(not ls.solutions[wk][1].unfilled_slots for wk in WEEKS)
    assert not (_TX_KEYS & set(_keys(payload)))


# ── Scenario 8: missing historical ownership or weekly actuals ───────────
def test_scenario_8_missing_points_are_unobserved_not_zero():
    teams = league_of(4)
    snap = build_snapshot(teams, missing_points={("t1-wr6", 2)})
    payload, ls = compute(snap)
    row = _player(payload, "t1-wr6")
    assert row["unobservedWeeks"] == 1
    assert row["eligibleOwnedWeeks"] == 7
    assert ls.solutions[2][1].valid  # host score still reproduced
    assert "t1-wr6" not in ls.league_points or 2 not in ls.league_points["t1-wr6"]


def test_scenario_8_unprovable_team_weeks_are_excluded_and_ranked_honestly():
    teams = league_of(4)
    missing = {("t4-qb1", w) for w in WEEKS}
    snap = build_snapshot(teams, best_ball=None, missing_points=missing)
    payload, ls = compute(snap, roster_id=4)
    assert payload["rules"]["lineupMode"] == rc.LINEUP_UNVERIFIED
    assert ls.team_stats[4]["validWeeks"] == []
    assert {e["reason"] for e in payload["team"]["excludedWeeks"]} == {rc.X_POINTS_INCOMPLETE}
    qb = _position(payload, "QB")["production"]
    assert qb["rank"] is None and qb["of"] == 3
    assert all(r["points"] is None for r in qb["weekly"])
    assert _diag(payload, "RC-D2", "QB")["status"] == rc.STATUS_NOT_EVALUATED


def test_scenario_8_unpriced_value_is_listed_never_zero():
    teams = league_of(4)
    vals = {p: None for p, s in teams[1].items() if s[0] == "K"}
    payload, _ = compute(build_snapshot(teams), contract=_contract_for(teams, vals))
    k = _position(payload, "K")["value"]
    assert k["total"] is None and k["pricedCount"] == 0 and k["unpricedIds"] == ["t1-k1"]
    assert k["rank"] is None


def test_scenario_8_contract_for_another_league_is_not_used():
    teams = league_of(4)
    payload, _ = compute(build_snapshot(teams), contract=_contract_for(teams, key="other"))
    assert payload["valueBlock"] == {
        "available": False,
        "reason": "contract_league_mismatch",
        "asOf": None,
    }
    assert _position(payload, "QB")["value"]["available"] is False


# ── Scenario 9: valuable in the market, redundant on this roster ─────────
def test_scenario_9_valuable_but_redundant_is_review_and_value_untouched():
    teams = league_of(4)
    qbs = [p for p, s in teams[1].items() if s[0] == "QB"]
    for pid, v in zip(qbs, (40.0, 38.0, 36.0)):
        teams[1][pid] = ("QB", lambda _w, v=v: v)
    teams[1]["t1-qb4"] = ("QB", lambda w: 21.0 + (w % 2))
    contract = _contract_for(teams, {"t1-qb4": 9500.0, "t1-qb3": 100.0})
    before = copy.deepcopy(contract)
    payload, _ = compute(build_snapshot(teams), contract=contract)
    qb4 = _player(payload, "t1-qb4")
    assert qb4["starts"]["value"] == 0 and qb4["redundantStartableWeeks"] > 0
    assert qb4["marginalPoints"]["value"] == 0.0
    d = _diag(payload, "RC-D6", "QB")
    assert d["status"] == rc.STATUS_FIRED and d["verdict"] == rc.VERDICT_REVIEW
    assert [p["playerId"] for p in d["evidence"]["players"]] == ["t1-qb4"]
    assert "valuable in trade" in d["explanation"].lower()
    assert qb4["rankDerivedValue"] == 9500.0
    assert contract == before  # no value write-back


# ── Scenario 10: waiver gain vs dynasty loss — cross-reference ───────────
def test_scenario_10_construction_never_proposes_a_transaction():
    """The add/drop decision under a zero dynasty-loss budget is owned and tested
    by the Waiver Advisor's drop assessment (``src/waivers/drop_assessment.py``,
    ``tests/waivers/test_drop_assessment.py``).  Roster Construction only
    diagnoses; it must never emit a transaction, and its depth diagnosis must
    route the decision there."""
    teams = league_of(4)
    for pid in [p for p, s in teams[1].items() if s[0] == "RB"]:
        del teams[1][pid]
    teams[1]["t1-rbx"] = ("RB", lambda w: 0.0 if w in (2, 5) else 40.0)
    teams[1]["t1-rby"] = ("RB", lambda w: 0.0 if w in (3, 6) else 40.0)
    payload, _ = compute(build_snapshot(teams), contract=_contract_for(teams))
    assert not (_TX_KEYS & set(_keys(payload)))
    assert all(
        d["verdict"] in (None, rc.VERDICT_REVIEW, rc.VERDICT_NO_ACTION)
        for d in payload["diagnoses"]
    )


# ── Invariants ───────────────────────────────────────────────────────────
def test_no_action_is_a_valid_overall_result():
    teams = league_of(4)
    vals = {pid: 1000.0 + i for i, pid in enumerate(positions_of(teams))}
    payload, _ = compute(build_snapshot(teams), contract=_contract_for(teams, vals), roster_id=4)
    fired = [d for d in payload["diagnoses"] if d["verdict"] == rc.VERDICT_REVIEW]
    assert payload["overall"]["verdict"] == (rc.VERDICT_REVIEW if fired else rc.VERDICT_NO_ACTION)
    for d in payload["diagnoses"]:
        assert d["status"] in (rc.STATUS_FIRED, rc.STATUS_NOT_FIRED, rc.STATUS_NOT_EVALUATED)
        if d["status"] == rc.STATUS_NOT_EVALUATED:
            assert d["notEvaluatedReason"]
        if d["status"] == rc.STATUS_FIRED:
            assert d["evidence"] and d["explanation"]


def test_no_future_leakage_into_earlier_weeks():
    teams = league_of(4)
    a_payload, a = compute(build_snapshot(teams))
    later = copy.deepcopy(teams)
    for t in later.values():
        for pid, (p, fn) in list(t.items()):
            t[pid] = (p, lambda w, fn=fn, pid=pid: (fn(w) * 3 + len(pid)) if w >= 7 else fn(w))
    b_payload, b = compute(build_snapshot(later))
    for wk in range(1, 7):
        assert a.thresholds[wk] == b.thresholds[wk]
        for rid in a.team_ids:
            assert a.solutions[wk][rid].assigned == b.solutions[wk][rid].assigned
    for pa, pb in zip(a_payload["positions"], b_payload["positions"]):
        assert pa["production"]["weekly"][:6] == pb["production"]["weekly"][:6]


def test_managed_league_is_labelled_hypothetical_and_kept_separate():
    teams = league_of(4)

    def submitted(rid, wk, roster):
        # A real manager's lineup: last week's choice, so it lags the optimum.
        from tests.roster_intel.rc_support import _starters

        pos = positions_of(teams)
        prev = {p: teams[rid][p][1](max(1, wk - 1)) for p in roster if p in teams[rid]}
        return _starters(prev, pos, list(DYNASTY_MAIN_SLOTS))[0]

    snap = build_snapshot(teams, best_ball=0, managed_starters=submitted)
    payload, _ = compute(snap)
    assert payload["rules"]["lineupMode"] == rc.LINEUP_MANAGED
    assert payload["lineupBasis"] == rc.BASIS_HYPOTHETICAL
    assert any("HYPOTHETICAL" in a for a in payload["assumptions"])
    total_opt = sum(p["production"]["points"] for p in payload["positions"])
    total_obs = sum(p["production"]["observedSubmittedPoints"] for p in payload["positions"])
    assert total_obs <= total_opt + 0.01
    row = _player(payload, "t1-qb1")
    assert row["marginalPoints"]["value"] is None
    assert "wab_requires_best_ball" in row["marginalPoints"]["unavailableWeeks"]


def test_include_playoffs_adds_playoff_weeks_and_names_marginal_scope():
    teams = league_of(4)
    snap = build_snapshot(teams, playoff_week_start=7)
    regular, _ = compute(snap)
    assert regular["coverage"]["weeksIncluded"] == [1, 2, 3, 4, 5, 6]
    full, _ = compute(snap, include_playoffs=True)
    assert full["coverage"]["weeksIncluded"] == WEEKS
    assert full["rules"]["includePlayoffs"] is True
    row = _player(full, "t1-qb1")
    assert row["marginalPoints"]["unavailableWeeks"] == {"player_impact_regular_season_only": 2}


def test_hypothetical_counterfactual_is_labelled_and_bounded():
    teams = league_of(4)
    own = {"t2-wr1": {w: (2 if w <= 4 else 1) for w in WEEKS}}
    payload, _ = compute(build_snapshot(teams, ownership=own))
    meta = payload["hypotheticalScenario"]
    assert meta["scenario"] == rc.SCENARIO_END_ROSTER and meta["expost"] is True
    row = _player(payload, "t2-wr1")
    h = row["hypotheticalStarts"]
    assert h["of"] == 8 and 0 <= h["value"] <= 8
    assert row["ownedWeeks"] == 4  # actual starts keep their own denominator


def test_hypothetical_with_unknown_teammates_only_counts_decided_weeks():
    teams = league_of(4)
    # t1-te3 is on the end roster but was on NO roster in weeks 1-4.
    own = {"t1-te3": {w: (99 if w <= 4 else 1) for w in WEEKS}}
    payload, _ = compute(build_snapshot(teams, ownership=own))
    meta = payload["hypotheticalScenario"]
    assert [r["week"] for r in meta["weeksWithUnknownTeammates"]] == [1, 2, 3, 4]
    qb1 = _player(payload, "t1-qb1")["hypotheticalStarts"]
    assert qb1["of"] == 8  # a QB's slot cannot be taken by a tight end's unknown week
    te3 = _player(payload, "t1-te3")["hypotheticalStarts"]
    assert te3["unobservedWeeksExcluded"] == 4 and te3["of"] <= 4


def test_startability_standard_uses_measured_league_starters():
    teams = league_of(4)
    _, ls = compute(build_snapshot(teams))
    for wk in WEEKS:
        started = sum(
            1
            for sol in ls.solutions[wk].values()
            for _i, _s, pid, _p in sol.assigned
            if rc.group_of(ls.si.players[pid]) == "WR"
        )
        assert ls.thresholds[wk]["WR"]["starters"] == started
        assert ls.thresholds[wk]["WR"]["starters"] != 24 or started == 24


def test_deterministic_for_identical_inputs():
    teams = league_of(4)
    a, _ = compute(build_snapshot(teams), contract=_contract_for(teams))
    b, _ = compute(build_snapshot(teams), contract=_contract_for(teams))
    assert a == b


def test_construction_module_is_pure_and_never_writes_canonical_value():
    import ast
    import inspect

    src = inspect.getsource(rc)
    tree = ast.parse(src)
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    assert not imported & {"requests", "httpx", "sqlite3", "os", "time", "datetime", "pathlib"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
            sl = node.slice
            assert not (isinstance(sl, ast.Constant) and sl.value == "rankDerivedValue")
    assert "solve_optimal_assignment" in src and "optimize_lineup" not in src
