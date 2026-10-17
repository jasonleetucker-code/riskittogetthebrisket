"""P0 (owner master package 2026-10-17): availability-aware best-ball utility.

The reported defect: "Jaxson Dart enters the optimal lineup in 82% of
simulated weeks" while he is out for the remainder of the regular season.
The calendar-free simulation drew every player for every scenario.  These
cases fail on that behaviour and pass once each scenario is a real remaining
week and unavailable player-weeks leave the pool.
"""

from __future__ import annotations

from src.roster_intel.best_ball_utility import UtilityPlayer, evaluate_trade_utility

SF_SLOTS = ["QB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"]
WEEKS = list(range(6, 18))  # 12 remaining fantasy weeks
DRAWS = 360  # 30 per week
OUT = "unavailable"


def P(pid, pos, ppg, availability=None, summary=None):
    return UtilityPlayer(pid, pid, pos, ppg, (), availability, summary)


def all_weeks(state):
    return {w: state for w in WEEKS}


BASE = [
    P("qb1", "QB", 20.0, all_weeks("available")),
    P("rb1", "RB", 15.0, all_weeks("available")),
    P("wr1", "WR", 14.0, all_weeks("available")),
    P("wr2", "WR", 12.0, all_weeks("available")),
    P("te1", "TE", 9.0, all_weeks("available")),
    P("rb2", "RB", 8.0, all_weeks("available")),
]


def run(before, after, **kw):
    ids_b = {p.player_id for p in before}
    ids_a = {p.player_id for p in after}
    roles = {pid: "outgoing" for pid in ids_b - ids_a}
    roles.update({pid: "incoming" for pid in ids_a - ids_b})
    return evaluate_trade_utility(
        before=before, after=after, slots=SF_SLOTS, roles=roles, draws=DRAWS, **kw
    )


def row(result, pid):
    return next(r for r in result["players"] if r["playerId"] == pid)


def test_season_ending_qb_enters_no_lineup_in_any_remaining_week():
    """The Dart case: a high full-season per-game projection, out for every
    remaining week.  Without availability he takes the SUPER_FLEX nearly
    every week; with it, never."""
    dart = P("dart", "QB", 19.0, all_weeks(OUT), {"weeks": 12, "eligibleWeeks": 0})
    after = [*BASE, dart]
    legacy = run(BASE, [*BASE, P("dart", "QB", 19.0)])
    assert row(legacy, "dart")["lineupEntryPctAfter"] > 75  # the reported symptom

    fixed = run(BASE, after, weeks=WEEKS)
    assert row(fixed, "dart")["lineupEntryPctAfter"] == 0.0
    assert row(fixed, "dart")["usablePpgAfter"] == 0.0
    # Adding a player who cannot play changes nothing about the roster.
    assert fixed["impact"]["ppg"] == 0.0
    assert row(fixed, "dart")["availability"] == {"weeks": 12, "eligibleWeeks": 0}
    assert fixed["basis"]["weeks"] == WEEKS


def test_unavailable_is_removed_not_scored_zero():
    """A 0.0 player still fills a slot nobody else can and would count as a
    lineup entry; an unavailable one must leave the slot EMPTY."""
    only_te = [p for p in BASE if p.player_id != "te1"]
    hurt_te = P("te_out", "TE", 10.0, all_weeks(OUT))
    r = run(only_te, [*only_te, hurt_te], weeks=WEEKS)
    assert row(r, "te_out")["lineupEntryPctAfter"] == 0.0


def test_bye_week_removes_exactly_that_weeks_share():
    bye = {**all_weeks("available"), 9: OUT}
    elite = P("elite", "QB", 40.0, bye)
    r = run(BASE, [*BASE, elite], weeks=WEEKS)
    # Elite always starts when he can play: 11 of 12 weeks.
    assert abs(row(r, "elite")["lineupEntryPctAfter"] - 100 * 11 / 12) < 0.5


def test_uncertain_weeks_stay_in_the_pool():
    doubtful = P("q2", "QB", 40.0, {**all_weeks("available"), 6: "uncertain"})
    r = run(BASE, [*BASE, doubtful], weeks=WEEKS)
    assert row(r, "q2")["lineupEntryPctAfter"] == 100.0


def test_pairing_and_determinism_hold_with_a_calendar():
    dart = P("dart", "QB", 19.0, {**all_weeks("available"), **{w: OUT for w in range(6, 12)}})
    a = run(BASE, [*BASE, dart], weeks=WEEKS)
    b = run(BASE, [*BASE, dart], weeks=WEEKS)
    assert a["impact"] == b["impact"]
    assert row(a, "dart")["lineupEntryPctAfter"] <= 50.0


def test_no_remaining_weeks_is_refused_not_simulated():
    r = run(BASE, BASE, weeks=[])
    assert r["available"] is False
    assert r["unavailableReason"] == "no_remaining_fantasy_weeks"


def test_assumptions_say_what_was_modelled():
    legacy = run(BASE, BASE)
    assert "injury / availability probabilities are not modelled" in legacy["assumptions"]
    cal = run(BASE, BASE, weeks=WEEKS)
    assert not any("not modelled" in a for a in cal["assumptions"])
    assert any("remaining fantasy weeks (6-17)" in a for a in cal["assumptions"])
