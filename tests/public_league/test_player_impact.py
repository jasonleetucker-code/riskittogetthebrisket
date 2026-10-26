"""C5-WAR-01 deterministic core — hand-computed fixtures.

Every expected number below is worked out by hand in the comment beside
it, from ``docs/PLAYER_IMPACT_WAR_MVP_SPEC.md`` §2/§3/§5/§6/§11/§12.  The
replacement level is an INPUT to ``evaluate_league_week`` so the WAR/VORP/
WAB arithmetic is pinned independently of the replacement owner; the
replacement derivation is pinned separately at the bottom.
"""

from __future__ import annotations

import copy
import random

import pytest

from src.public_league import player_impact as pi
from src.public_league.identity import build_manager_registry
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot

QB_ONLY = pi.WeekRules(starter_slots=("QB",), best_ball=True, median_enabled=True)


def _players(spec: dict[str, str]) -> dict[str, pi.PlayerInfo]:
    return {
        pid: pi.PlayerInfo(position=pos, host_position=pos, fantasy_positions=(pos,))
        for pid, pos in spec.items()
    }


def _team(rid, opp, counted, points, score=None):
    return pi.TeamWeek(
        roster_id=rid,
        owner_id=f"o{rid}",
        score=round(sum(points[p] for p in counted), 2) if score is None else score,
        counted=tuple(counted),
        points=dict(points),
        roster=tuple(points),
        opponent=opp,
    )


# A one-slot (QB) best-ball, median-on league-week.  Pairs 1v2, 3v4.
#   T1 50 (q1 50, bench b1 3)   T2 45 (q2 45, bench b2 2)
#   T3 10 (q3 10, bench b3 1)   T4 20 (q4 20, bench b4 15)
# Actual median = (20 + 45) / 2 = 32.5.
WEEK = [
    _team(1, 2, ["q1"], {"q1": 50.0, "b1": 3.0}),
    _team(2, 1, ["q2"], {"q2": 45.0, "b2": 2.0}),
    _team(3, 4, ["q3"], {"q3": 10.0, "b3": 1.0}),
    _team(4, 3, ["q4"], {"q4": 20.0, "b4": 15.0}),
]
QBS = _players({p: "QB" for t in WEEK for p in t.points})


def _rec(records, pid):
    (rec,) = [r for r in records if r["playerId"] == pid]
    return rec


def _eval(repl, *, rules=QB_ONLY, week=WEEK, players=QBS, expected=4):
    return pi.evaluate_league_week(
        1, week, rules, players, {"QB": repl}, expected_team_count=expected
    )


# ── Actual WAR (spec §3 / §12) ─────────────────────────────────────────
def test_no_result_flip_is_zero_war_even_for_a_big_vorp():
    # q1, R=46: cf 46 > 45 (H2H win) ; pool 46,45,10,20 -> 32.5, 46 wins.
    rec = _rec(_eval(46.0), "q1")
    assert rec["vorp"]["value"] == 4.0
    assert rec["war"]["value"] == 0.0
    assert (rec["war"]["h2hDelta"], rec["war"]["medianDelta"]) == (0.0, 0.0)


def test_h2h_only_flip_is_plus_one():
    # q1, R=40: cf 40 < 45 H2H loss ; pool 40,45,10,20 -> median 30, 40 wins.
    rec = _rec(_eval(40.0), "q1")
    assert rec["war"]["value"] == 1.0
    assert (rec["war"]["h2hDelta"], rec["war"]["medianDelta"]) == (1.0, 0.0)
    assert rec["war"]["median"]["counterfactualThreshold"] == 30.0


def test_median_only_flip_is_plus_one():
    # q2 (lost H2H 45-50 either way), R=15: cf 15 ; pool 50,15,10,20 ->
    # median 17.5, 15 loses; actual 45 beat 32.5.
    rec = _rec(_eval(15.0), "q2")
    assert rec["vorp"]["value"] == 30.0
    assert rec["war"]["value"] == 1.0
    assert (rec["war"]["h2hDelta"], rec["war"]["medianDelta"]) == (0.0, 1.0)


def test_both_flips_is_plus_two():
    # q1, R=15: cf 15 < 45 ; pool 15,45,10,20 -> 17.5, 15 loses.
    rec = _rec(_eval(15.0), "q1")
    assert rec["war"]["value"] == 2.0


def test_below_replacement_performance_gives_negative_war_and_vorp():
    # q3 scored 10, R=30: cf 30 beats T4's 20 (H2H 0 -> 1) ; median pool
    # 50,45,30,20 -> 37.5, 30 still loses.  WAR = 0 - 1 = -1.
    rec = _rec(_eval(30.0), "q3")
    assert rec["vorp"]["value"] == -20.0
    assert rec["war"]["value"] == -1.0


def test_ties_use_the_canonical_half_credit():
    # q4 20 vs T3 10, R=10: cf 10 == 10 -> H2H tie 0.5 ; median pool
    # 50,45,10,10 -> 27.5, loses as the actual 20 did.  WAR = 1 - 0.5.
    rec = _rec(_eval(10.0), "q4")
    assert rec["war"]["h2h"] == {"actual": 1.0, "counterfactual": 0.5}
    assert rec["war"]["value"] == 0.5


def test_counterfactual_median_is_recalculated_not_held_fixed():
    # q2, R=30: cf 30.  Stale median 32.5 would call it a LOSS (+1 WAR);
    # recomputed pool 50,30,10,20 -> 25, 30 WINS -> 0 WAR.
    rec = _rec(_eval(30.0), "q2")
    assert rec["war"]["median"]["counterfactualThreshold"] == 25.0
    assert rec["war"]["value"] == 0.0


def test_counterfactual_score_replaces_the_team_by_roster_id_not_by_value():
    # T3 and T4 both score 20.  The counterfactual team is located by its
    # roster id (spec §12), never by searching the week for the value 20.
    # q3 (T3, 20) with R=0 -> cf 0 ; pool 50,45,0,20 -> 32.5.
    week = [
        WEEK[0],
        WEEK[1],
        _team(3, 4, ["q3"], {"q3": 20.0, "b3": 1.0}),
        _team(4, 3, ["q4"], {"q4": 20.0, "b4": 15.0}),
    ]
    rec = _rec(_eval(0.0, week=week), "q3")
    assert rec["war"]["counterfactualScore"] == 0.0
    # H2H was a 20-20 tie (0.5) -> loss (0) ; median loses both ways.
    assert rec["war"]["value"] == 0.5


# ── non-counted / missing / rules ──────────────────────────────────────
def test_non_counted_week_is_a_known_zero_not_missing():
    rec = _rec(_eval(15.0), "b1")
    assert rec["counted"] is False
    for key in ("vorp", "war", "wab", "gameChangerPoints"):
        assert rec[key] == {"value": 0.0, "reason": None}


def test_missing_replacement_is_unavailable_never_zero():
    rec = _rec(_eval(None), "q1")
    assert rec["vorp"] == {"value": None, "reason": pi.R_REPLACEMENT_UNAVAILABLE}
    assert rec["war"]["value"] is None


def test_missing_counted_score_is_unavailable_never_zero():
    week = list(WEEK)
    week[0] = pi.TeamWeek(1, "o1", 50.0, ("q1",), {"b1": 3.0}, ("q1", "b1"), 2)
    rec = _rec(_eval(15.0, week=week), "q1")
    for key in ("vorp", "war", "wab", "gameChangerPoints"):
        assert rec[key] == {"value": None, "reason": pi.R_COUNTED_SCORE_MISSING}


def test_unknown_team_score_makes_the_median_unknown_for_everyone():
    week = list(WEEK)
    week[3] = pi.TeamWeek(4, "o4", None, ("q4",), {"q4": 20.0}, ("q4",), 3)
    rec = _rec(_eval(40.0, week=week), "q1")
    assert rec["war"]["value"] is None
    assert rec["war"]["reason"] == pi.R_LEAGUE_WEEK_INCOMPLETE
    assert rec["war"]["h2hDelta"] == 1.0  # the H2H half is still known


def test_an_absent_team_row_makes_the_median_unknown_not_a_smaller_league():
    # Team 4's whole row is missing: the median must not be retaken over the
    # three rows that exist (that published 1.5 for q1 with no reason).
    week = [t for t in WEEK if t.roster_id != 4]
    rec = _rec(_eval(30.0, week=week, expected=4), "q1")
    assert rec["war"]["value"] is None
    assert rec["war"]["reason"] == pi.R_LEAGUE_WEEK_INCOMPLETE
    assert rec["war"]["h2hDelta"] is not None  # the H2H half is still known


def test_an_unknown_league_size_withholds_the_median():
    rec = _rec(_eval(30.0, expected=None), "q1")
    assert rec["war"]["value"] is None
    assert rec["war"]["reason"] == pi.R_LEAGUE_WEEK_INCOMPLETE


def test_a_score_mismatch_makes_bench_players_unknown_not_known_zero():
    week = list(WEEK)
    # Host says 53; the counted lineup sums to 50 -> the lineup is unproven.
    week[0] = pi.TeamWeek(1, "o1", 53.0, ("q1",), {"q1": 50.0, "b1": 3.0}, ("q1", "b1"), 2)
    rec = _rec(_eval(15.0, week=week), "b1")
    for key in ("vorp", "war", "wab", "gameChangerPoints"):
        assert rec[key] == {"value": None, "reason": pi.R_TEAM_SCORE_MISMATCH}


def test_unverified_median_rule_withholds_the_total_but_keeps_h2h():
    rules = pi.WeekRules(starter_slots=("QB",), best_ball=True, median_enabled=None)
    rec = _rec(_eval(40.0, rules=rules), "q1")
    assert rec["war"]["value"] is None
    assert rec["war"]["reason"] == pi.R_MEDIAN_RULE_UNVERIFIED
    assert rec["war"]["h2hDelta"] == 1.0


def test_median_off_counts_h2h_only():
    rules = pi.WeekRules(starter_slots=("QB",), best_ball=True, median_enabled=False)
    rec = _rec(_eval(15.0, rules=rules), "q1")
    assert rec["war"]["value"] == 1.0
    assert rec["war"]["median"]["actual"] is None


def test_bye_team_scores_median_only():
    # Five teams; T5 has no game.  T5 30 (q5 30).  Pool 50,45,10,20,30 ->
    # median 30 -> actual tie (0.5).  R=5: cf 5 ; pool 50,45,10,20,5 -> 20,
    # loss.  WAR = 0.5 (median only, no H2H game in either world).
    week = list(WEEK) + [_team(5, None, ["q5"], {"q5": 30.0, "b5": 1.0})]
    players = _players({p: "QB" for t in week for p in t.points})
    rec = _rec(_eval(5.0, week=week, players=players, expected=5), "q5")
    assert rec["war"]["h2h"] == {"actual": None, "counterfactual": None}
    assert rec["war"]["h2hDelta"] == 0.0
    assert rec["war"]["value"] == 0.5


# ── WAB + Game Changer (spec §5 / §6) ──────────────────────────────────
def test_wab_resolves_the_lineup_and_recomputes_the_median():
    # Remove q1 -> bench b1 3 starts -> score 3.  GC = 50 - 3 = 47.
    # 3 < 45 H2H loss ; pool 3,45,10,20 -> 15, loss.  WAB = 2.
    rec = _rec(_eval(15.0), "q1")
    assert rec["gameChangerPoints"]["value"] == 47.0
    assert rec["wab"]["value"] == 2.0
    assert rec["wab"]["counterfactualScore"] == 3.0


def test_wab_zero_when_bench_still_wins():
    # Remove q4 -> b4 15 starts.  GC = 5.  15 > 10 still wins H2H ; median
    # pool 50,45,10,15 -> 30, loses like the actual 20 did.  WAB = 0.
    rec = _rec(_eval(15.0), "q4")
    assert rec["gameChangerPoints"]["value"] == 5.0
    assert rec["wab"]["value"] == 0.0


def test_wab_resolves_superflex_and_idp_flex_not_the_next_player_at_the_position():
    # Slots QB, SUPER_FLEX, RB, DL, IDP_FLEX.
    # Roster: qa 30, qb 18 (QB) ; ra 15, rb 12 (RB) ; da 10, db 6 (DL) ; la 8 (LB)
    # Optimal: QB qa30, SF qb18, RB ra15, DL da10, IDP_FLEX la8 = 81.
    # Remove qa: QB qb18, SF rb12 (an RB moves into SUPER_FLEX), RB ra15,
    #   DL da10, IDP_FLEX la8 = 63 -> GC 18.  A "next QB" substitution has
    #   no third QB and would leave a slot empty or score 51.
    # Remove da: DL db6, IDP_FLEX la8 -> 77 -> GC 4.
    slots = ("QB", "SUPER_FLEX", "RB", "DL", "IDP_FLEX")
    pts = {"qa": 30.0, "qb": 18.0, "ra": 15.0, "rb": 12.0, "da": 10.0, "db": 6.0, "la": 8.0}
    pos = {"qa": "QB", "qb": "QB", "ra": "RB", "rb": "RB", "da": "DL", "db": "DL", "la": "LB"}
    me = _team(1, 2, ["qa", "qb", "ra", "da", "la"], pts)
    opp = _team(2, 1, ["x"], {"x": 70.0}, score=70.0)
    players = _players({**pos, "x": "QB"})
    rules = pi.WeekRules(starter_slots=slots, best_ball=True, median_enabled=False)
    recs = pi.evaluate_league_week(1, [me, opp], rules, players, {}, expected_team_count=2)
    assert _rec(recs, "qa")["gameChangerPoints"]["value"] == 18.0
    assert _rec(recs, "qa")["wab"]["value"] == 1.0  # 81 beat 70 ; 63 does not
    assert _rec(recs, "da")["gameChangerPoints"]["value"] == 4.0
    assert _rec(recs, "da")["wab"]["value"] == 0.0


def test_game_changer_equals_actual_minus_resolved_score_exactly():
    for pid in ("q1", "q2", "q3", "q4"):
        rec = _rec(_eval(15.0), pid)
        assert rec["gameChangerPoints"]["value"] == round(
            rec["teamScore"] - rec["wab"]["counterfactualScore"], 2
        )


def test_infeasible_counterfactual_lineup_is_a_state_not_a_zero_score():
    week = [
        _team(1, 2, ["q1"], {"q1": 50.0}),  # no bench QB
        _team(2, 1, ["q2"], {"q2": 45.0}),
    ]
    players = _players({"q1": "QB", "q2": "QB"})
    rules = pi.WeekRules(starter_slots=("QB",), best_ball=True, median_enabled=False)
    rec = _rec(
        pi.evaluate_league_week(
            1, week, rules, players, {"QB": 15.0}, expected_team_count=len(week)
        ),
        "q1",
    )
    assert rec["wab"] == {"value": None, "reason": pi.R_COUNTERFACTUAL_INFEASIBLE}
    assert rec["war"]["value"] == 1.0  # league replacement still answers


def test_wab_requires_best_ball_and_never_guesses_the_format():
    for flag, reason in ((False, pi.R_NOT_BEST_BALL), (None, pi.R_BEST_BALL_UNVERIFIED)):
        rules = pi.WeekRules(starter_slots=("QB",), best_ball=flag, median_enabled=True)
        rec = _rec(_eval(15.0, rules=rules), "q1")
        assert rec["wab"] == {"value": None, "reason": reason}
        assert rec["war"]["value"] == 2.0


def test_host_lineup_that_the_solver_cannot_reproduce_withholds_wab():
    # The host counted b1 (3) over q1 (50): not a best-ball optimum.
    week = list(WEEK)
    week[0] = _team(1, 2, ["b1"], {"q1": 50.0, "b1": 3.0})
    rec = _rec(_eval(1.0, week=week), "b1")
    assert rec["wab"] == {"value": None, "reason": pi.R_LINEUP_NOT_REPRODUCED}
    assert rec["vorp"]["value"] == 2.0


def test_negative_realized_points_are_never_floored():
    # A kicker-style -2.0 counted score: the realized-points objective keeps
    # it (the adjusted objective would floor it to 0 and mis-sum the team).
    week = [
        _team(1, 2, ["q1"], {"q1": -2.0, "b1": -3.0}),
        _team(2, 1, ["q2"], {"q2": -2.5, "b2": -9.0}),
    ]
    players = _players({"q1": "QB", "b1": "QB", "q2": "QB", "b2": "QB"})
    rules = pi.WeekRules(starter_slots=("QB",), best_ball=True, median_enabled=False)
    rec = _rec(
        pi.evaluate_league_week(
            1, week, rules, players, {"QB": 1.0}, expected_team_count=len(week)
        ),
        "q1",
    )
    assert rec["vorp"]["value"] == -3.0
    assert rec["gameChangerPoints"]["value"] == 1.0  # -2 vs -3
    assert rec["wab"]["value"] == 1.0  # -2 beat -2.5 ; -3 does not


def test_evaluation_is_order_independent():
    shuffled = list(WEEK)
    random.Random(7).shuffle(shuffled)
    assert _eval(15.0) == _eval(15.0, week=shuffled)


# ── snapshot adapter: finished weeks, traded attribution, replacement ──
_OWNERS = ["oA", "oB"]
_USERS = [{"user_id": o, "display_name": o, "metadata": {}} for o in _OWNERS]
_ROSTERS = [
    {"roster_id": 1, "owner_id": "oA", "players": [], "settings": {"wins": 1, "losses": 1}},
    {"roster_id": 2, "owner_id": "oB", "players": [], "settings": {"wins": 1, "losses": 1}},
]
# Eight QBs; "t" is traded from roster 1 (week 1) to roster 2 (week 2).
_NFL = {
    p: {"full_name": p.upper(), "position": "QB", "fantasy_positions": ["QB"]}
    for p in ("a", "b", "c", "d", "e", "f", "g", "t")
}
_NFL["k"] = {"full_name": "K", "position": "K", "fantasy_positions": ["K"]}


def _entry(mid, rid, pts, starters):
    return {
        "matchup_id": mid,
        "roster_id": rid,
        "points": round(sum(pts[s] for s in starters), 2),
        "starters": list(starters),
        "players": list(pts),
        "players_points": dict(pts),
    }


# Week 1: R1 {t 30, a 20, b 16, c 12, k 5}  R2 {d 25, e 18, f 14, g 10}
# Week 2: R1 {a 20, b 16, c 12, k 5}        R2 {t 30, d 25, e 18, f 14, g 10}
WEEKS = {
    1: [
        _entry(1, 1, {"t": 30.0, "a": 20.0, "b": 16.0, "c": 12.0, "k": 5.0}, ["t"]),
        _entry(1, 2, {"d": 25.0, "e": 18.0, "f": 14.0, "g": 10.0}, ["d"]),
    ],
    2: [
        _entry(1, 1, {"a": 20.0, "b": 16.0, "c": 12.0, "k": 5.0}, ["a"]),
        _entry(1, 2, {"t": 30.0, "d": 25.0, "e": 18.0, "f": 14.0, "g": 10.0}, ["t"]),
    ],
    # Week 3 is LIVE: Thursday sliver for R1, nothing for R2.
    3: [
        _entry(1, 1, {"a": 44.0, "b": 0.0, "c": 0.0, "k": 0.0}, ["a"]),
        _entry(1, 2, {"t": 0.0, "d": 0.0, "e": 0.0, "f": 0.0, "g": 0.0}, ["t"]),
    ],
}


def _snapshot(weeks=WEEKS, *, last_scored_leg=2, best_ball=1, median=0):
    league = {
        "league_id": "L1",
        "season": "2026",
        "status": "in_season",
        "total_rosters": 2,
        "roster_positions": ["QB", "BN", "BN", "BN", "BN"],
        "settings": {
            "playoff_week_start": 15,
            "last_scored_leg": last_scored_leg,
            "best_ball": best_ball,
            "league_average_match": median,
        },
    }
    season = SeasonSnapshot(
        season="2026",
        league_id="L1",
        league=league,
        users=_USERS,
        rosters=_ROSTERS,
        matchups_by_week=copy.deepcopy(weeks),
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )
    snap = PublicLeagueSnapshot(
        root_league_id="L1",
        generated_at="2026-10-07T00:00:00Z",
        seasons=[season],
        managers=build_manager_registry([{"league": league, "users": _USERS, "rosters": _ROSTERS}]),
        nfl_players=copy.deepcopy(_NFL),
    )
    return snap, season


def test_in_progress_week_is_excluded_entirely():
    snap, season = _snapshot()
    out = pi.compute_season(snap, season)
    assert out["scope"]["weeks"] == [1, 2]
    assert out["scope"]["excludedRegularSeasonWeeks"] == [3]
    assert {r["week"] for r in out["_records"]} == {1, 2}
    # Identical to the snapshot taken before week 3 existed at all.
    pre_snap, pre_season = _snapshot({1: WEEKS[1], 2: WEEKS[2]})
    assert pi.compute_season(pre_snap, pre_season)["players"] == out["players"]


def test_replacement_is_the_band_below_measured_demand():
    # 2 teams x 1 QB slot -> 2 QBs started per week -> cutoff 2.
    # Season paces: t 30, d 25, a 20, e 18, b 16, f 14, c 12, g 10.
    # Band = ranks 3..7 = 20, 18, 16, 14, 12 -> mean 16.
    snap, season = _snapshot()
    repl = pi.compute_season(snap, season)["replacement"]
    assert repl["QB"]["starterCutoff"] == 2
    assert repl["QB"]["replacementPerGame"] == 16.0
    # K is rostered but no slot starts one: not a 0, a named state.
    assert repl["K"] == {
        "replacementPerGame": None,
        "reason": pi.REPL_NO_DEMAND,
        "leagueStartersPerWeek": 0.0,
        "starterCutoff": 0,
        "poolSize": 1,
        "bandSize": 5,
    }


def test_traded_player_is_attributed_per_franchise_week():
    # t: week 1 for R1 (30 vs d 25 -> win), week 2 for R2 (30 vs a 20 -> win).
    # R = 16.  VORP 14 each.  WAR: cf 30-30+16 = 16 loses both (to 25 / 20).
    # WAB: wk1 R1 without t -> a 20 < 25 (lose, +1) ; wk2 R2 without t ->
    # d 25 > 20 still wins (0).
    snap, season = _snapshot()
    rows = {(r["playerId"], r["rosterId"]): r for r in pi.compute_season(snap, season)["players"]}
    r1, r2 = rows[("t", 1)], rows[("t", 2)]
    assert (r1["weeks"], r1["ownerId"]) == ([1], "oA")
    assert (r2["weeks"], r2["ownerId"]) == ([2], "oB")
    assert r1["vorp"]["total"] == r2["vorp"]["total"] == 14.0
    assert r1["war"]["total"] == r2["war"]["total"] == 1.0
    assert r1["wab"]["total"] == 1.0
    assert r2["wab"]["total"] == 0.0
    assert r1["gameChangerPoints"]["total"] == 10.0  # 30 - 20
    assert r2["gameChangerPoints"]["total"] == 5.0  # 30 - 25


def test_thin_replacement_band_makes_war_unavailable_not_zero():
    weeks = {
        wk: [
            {**e, "players_points": {p: v for p, v in e["players_points"].items() if p in "tad"}}
            for e in entries
        ]
        for wk, entries in WEEKS.items()
        if wk < 3
    }
    for entries in weeks.values():
        for e in entries:
            e["players"] = list(e["players_points"])
    snap, season = _snapshot(weeks)
    out = pi.compute_season(snap, season)
    assert out["replacement"]["QB"]["reason"] == pi.REPL_INSUFFICIENT_BAND
    row = next(r for r in out["players"] if r["playerId"] == "t")
    assert row["war"]["total"] is None
    assert row["war"]["coverage"] == "unavailable"
    assert row["war"]["unavailableReasons"] == {pi.R_REPLACEMENT_UNAVAILABLE: 1}
    # League-wide: 2 weeks x 2 counted QBs, none priceable.  WAB does not use
    # the league replacement: wk1 R1 {t, a} and wk2 R2 {t, d} re-solve; wk1
    # R2 {d} and wk2 R1 {a} hold one QB, so removing him is infeasible.
    assert out["coverage"]["war"] == {
        "countedPlayerWeeks": 4,
        "known": 0,
        "unavailableReasons": {pi.R_REPLACEMENT_UNAVAILABLE: 4},
    }
    assert out["coverage"]["wab"]["known"] == 2
    assert out["coverage"]["wab"]["unavailableReasons"] == {pi.R_COUNTERFACTUAL_INFEASIBLE: 2}


def test_season_computation_is_deterministic():
    snap, season = _snapshot()
    first = pi.compute_season(snap, season)
    shuffled = {wk: list(reversed(es)) for wk, es in WEEKS.items()}
    snap2, season2 = _snapshot(shuffled)
    assert pi.compute_season(snap2, season2) == first


def test_payload_hides_weekly_records_unless_a_player_is_requested():
    snap, season = _snapshot()
    payload = pi.build_payload(snap, season)
    assert "_records" not in payload and "playerWeeks" not in payload
    one = pi.build_payload(snap, season, player_id="t")
    assert {r["rosterId"] for r in one["players"]} == {1, 2}
    assert [r["week"] for r in one["playerWeeks"]] == [1, 2]
    assert one["xWar"]["state"] == "unavailable"
    assert {p["id"] for p in one["priors"]} >= {"replacement_season_to_date"}


@pytest.mark.parametrize("teams, verified", [(2, True), (3, False)])
def test_median_threshold_verification_is_stamped_by_league_size(teams, verified):
    snap, season = _snapshot()
    season.league["total_rosters"] = teams
    assert pi.compute_season(snap, season)["rules"]["medianThreshold"]["hostVerified"] is verified


# ── the private read-only route ────────────────────────────────────────
@pytest.fixture
def impact_client(monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    import server

    snap, _season = _snapshot()
    league = SimpleNamespace(key="main", sleeper_league_id="L1")
    monkeypatch.setattr(server, "_get_public_snapshot", lambda force_refresh=False: snap)
    monkeypatch.setattr(server, "_resolve_league_for_request", lambda request: league)
    server._player_impact_cache.clear()
    with TestClient(server.app) as c:
        yield c, server, league, monkeypatch
    server._player_impact_cache.clear()


def test_route_is_private(impact_client):
    client, *_ = impact_client
    assert client.get("/api/league/player-impact").status_code == 401


def test_route_serves_the_owner_contract_for_the_requested_league(impact_client):
    client, server, _league, monkeypatch = impact_client
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda request: {"username": "t"})
    body = client.get("/api/league/player-impact?playerId=t").json()
    assert body["leagueKey"] == "main"
    assert body["calcVersion"] == pi.CALC_VERSION
    assert body["scope"]["weeks"] == [1, 2]
    assert [r["week"] for r in body["playerWeeks"]] == [1, 2]
    assert "_records" not in body


def test_route_refuses_another_leagues_snapshot(impact_client):
    client, server, league, monkeypatch = impact_client
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda request: {"username": "t"})
    league.sleeper_league_id = "L-OTHER"
    r = client.get("/api/league/player-impact")
    assert r.status_code == 503
    assert r.json()["reason"] == "league_snapshot_mismatch"


# ── review round 1: settings contradictions fail closed ────────────────
def _with_starters(weeks, fn):
    out = copy.deepcopy(weeks)
    for wk, entries in out.items():
        for e in entries:
            fn(wk, e)
    return out


def _managed_week_1(wk, e):
    if wk == 1 and e["roster_id"] == 1:
        e["starters"] = ["a"]
        e["points"] = 20.0


def test_starter_count_contradicting_the_league_object_fails_the_season_closed():
    # The 2025 shape: the league object says 1 QB slot (its FINAL settings)
    # while every matchup recorded TWO starters.  Nothing may be computed on
    # the configured layout, and coverage may never read complete.
    def two_starters(_wk, e):
        bench = [p for p in e["players"] if p not in e["starters"] and p != "k"][0]
        e["starters"] = e["starters"] + [bench]
        e["points"] = round(sum(e["players_points"][p] for p in e["starters"]), 2)

    snap, season = _snapshot({wk: WEEKS[wk] for wk in (1, 2)})
    season.matchups_by_week = _with_starters(season.matchups_by_week, two_starters)
    out = pi.compute_season(snap, season)
    assert out["settings"]["state"] == pi.SETTINGS_CONTRADICTED
    assert out["settings"]["contradictedWeeks"] == [
        {"week": 1, "reasons": [pi.CONTRA_SLOT_COUNT]},
        {"week": 2, "reasons": [pi.CONTRA_SLOT_COUNT]},
    ]
    assert out["replacement"]["QB"] == {
        "replacementPerGame": None,
        "reason": pi.REPL_CONTRADICTED,
    }
    for key in ("vorp", "war", "wab", "gameChangerPoints"):
        cov = out["coverage"][key]
        assert cov["known"] == 0
        assert cov["unavailableReasons"] == {pi.R_CONTRADICTED_SETTINGS: 8}
    assert all(r["vorp"]["coverage"] == "unavailable" for r in out["players"])


def test_best_ball_flag_contradicted_by_host_lineups_fails_the_week_closed():
    # The 2024 shape: best_ball=1, but in week 1 R1 counted a (20) while t
    # (30) sat on its roster -- a managed lineup.  Week 1 is withheld; week
    # 2 agrees with the flag and is computed, and the replacement level is
    # measured from week 2 alone (cutoff 2 ; paces t 30, d 25, a 20, e 18,
    # b 16, f 14, c 12, g 10 -> band 20,18,16,14,12 -> 16).
    snap, season = _snapshot({wk: WEEKS[wk] for wk in (1, 2)})
    season.matchups_by_week = _with_starters(season.matchups_by_week, _managed_week_1)
    out = pi.compute_season(snap, season)
    assert out["settings"]["contradictedWeeks"] == [{"week": 1, "reasons": [pi.CONTRA_BEST_BALL]}]
    assert out["replacementTemporalScope"]["weeks"] == [2]
    assert out["replacement"]["QB"]["replacementPerGame"] == 16.0
    wk1 = [r for r in out["_records"] if r["week"] == 1]
    assert wk1 and all(r["war"]["reason"] == pi.R_CONTRADICTED_SETTINGS for r in wk1)
    t2 = next(r for r in out["_records"] if r["week"] == 2 and r["playerId"] == "t")
    assert t2["vorp"]["value"] == 14.0


def test_a_managed_league_is_not_contradicted_by_a_suboptimal_lineup():
    snap, season = _snapshot({wk: WEEKS[wk] for wk in (1, 2)}, best_ball=0)
    season.matchups_by_week = _with_starters(season.matchups_by_week, _managed_week_1)
    out = pi.compute_season(snap, season)
    assert out["settings"]["state"] == pi.SETTINGS_CONSISTENT
    a1 = next(r for r in out["_records"] if r["week"] == 1 and r["playerId"] == "a")
    assert a1["vorp"]["value"] == 4.0  # 20 - 16
    assert a1["wab"]["reason"] == pi.R_NOT_BEST_BALL


def test_replacement_pace_counts_games_played_not_zero_weeks():
    # b scores 16 in week 1 and a literal 0.0 (bye/inactive) in week 2.  Per
    # game played b is 16, the band stays 20,18,16,14,12 -> 16.  Counting the
    # 0.0 as a game would make b 8 and the band 20,18,14,12,10 -> 14.8.
    def b_bye(wk, e):
        if wk == 2 and "b" in e["players_points"]:
            e["players_points"]["b"] = 0.0

    snap, season = _snapshot({wk: WEEKS[wk] for wk in (1, 2)})
    season.matchups_by_week = _with_starters(season.matchups_by_week, b_bye)
    assert pi.compute_season(snap, season)["replacement"]["QB"]["replacementPerGame"] == 16.0


def _season_week(entries):
    snap, season = _snapshot({1: entries})
    snap.nfl_players = {
        p: {"full_name": p, "position": "QB", "fantasy_positions": ["QB"]}
        for e in entries
        for p in e["players"]
    }
    season.league["total_rosters"] = 4
    weeks, _excluded = pi.season_team_weeks(snap, season)
    return weeks[1]


def test_broken_matchup_group_is_unavailable_not_a_bye():
    # T4's partner row is missing from matchup 2 (an unpaired group); T3 has
    # no matchup_id at all and a score: a real bye.
    week = [
        _entry(1, 1, {"q1": 50.0, "b1": 3.0}, ["q1"]),
        _entry(1, 2, {"q2": 45.0, "b2": 2.0}, ["q2"]),
        _entry(None, 3, {"q3": 10.0, "b3": 1.0}, ["q3"]),
        _entry(2, 4, {"q4": 20.0, "b4": 15.0}, ["q4"]),
    ]
    teams = {t.roster_id: t for t in _season_week(week)}
    assert teams[4].matchup_issue == "unpaired" and teams[4].opponent is None
    assert teams[3].matchup_issue is None and teams[3].opponent is None
    players = _players({p: "QB" for t in teams.values() for p in t.points})
    recs = pi.evaluate_league_week(
        1, list(teams.values()), QB_ONLY, players, {"QB": 5.0}, expected_team_count=len(teams)
    )
    q4 = _rec(recs, "q4")
    assert q4["war"]["value"] is None
    assert q4["war"]["reason"] == pi.R_MATCHUP_STRUCTURE
    q3 = _rec(recs, "q3")  # bye: median only, H2H delta a known 0
    assert q3["war"]["h2hDelta"] == 0.0 and q3["war"]["value"] is not None


def test_unknown_league_size_leaves_median_verification_unknown():
    snap, season = _snapshot()
    season.league["total_rosters"] = 0
    season.rosters = []
    assert pi.compute_season(snap, season)["rules"]["medianThreshold"]["hostVerified"] is None


def test_route_never_echoes_exception_text(impact_client):
    client, server, _league, mp = impact_client
    mp.setattr(server, "_is_authenticated", lambda request: True)
    mp.setattr(server, "_get_auth_session", lambda request: {"username": "t"})

    def boom(*_a, **_k):
        raise RuntimeError("C:/secret/path leaked")

    mp.setattr(pi, "compute_season", boom)
    r = client.get("/api/league/player-impact")
    assert r.status_code == 503
    assert "secret" not in r.text
