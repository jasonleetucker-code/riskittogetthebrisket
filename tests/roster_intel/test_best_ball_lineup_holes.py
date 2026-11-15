"""TC-B / TCM-H12 — holes and bye coverage in the roster lens.

``evaluate_trade_utility`` reports, beside the lineup it explains, how many
starting slots sit EMPTY per simulated week (a bye, a stated injury absence,
or no projected eligible player) and which slots the roster cannot fill at
all.  Reported, never a second vote: BBLI already scores an empty slot as
zero points.
"""

from __future__ import annotations

from src.roster_intel.best_ball_utility import UtilityPlayer, evaluate_trade_utility

SLOTS = ["QB", "RB", "WR", "TE", "FLEX"]
WEEKS = list(range(6, 18))  # 12 remaining weeks
DRAWS = 240  # 20 per week
OUT = "unavailable"


def P(pid, pos, ppg, availability=None):
    return UtilityPlayer(pid, pid, pos, ppg, (), availability, None)


def weeks(state, **overrides):
    out = {w: state for w in WEEKS}
    out.update({int(k[1:]): v for k, v in overrides.items()})
    return out


FULL = [
    P("qb", "QB", 20.0, weeks("available")),
    P("rb", "RB", 15.0, weeks("available")),
    P("wr", "WR", 14.0, weeks("available")),
    P("te", "TE", 9.0, weeks("available")),
    P("rb2", "RB", 8.0, weeks("available")),
]


def run(before, after, **kw):
    ids_b = {p.player_id for p in before}
    ids_a = {p.player_id for p in after}
    roles = {pid: "outgoing" for pid in ids_b - ids_a}
    roles.update({pid: "incoming" for pid in ids_a - ids_b})
    return evaluate_trade_utility(
        before=before, after=after, slots=SLOTS, roles=roles, draws=DRAWS, weeks=WEEKS, **kw
    )


def test_a_full_roster_has_no_holes_measured_as_zero():
    r = run(FULL, FULL)
    holes = r["lineupHoles"]
    assert holes["before"]["emptySlotsPerWeek"] == 0.0
    assert holes["before"]["emptyBySlot"] == {}
    assert holes["before"]["noEligiblePlayer"] == []
    assert holes["before"]["onlyUnprojected"] == []
    assert holes["emptySlotsPerWeekDelta"] == 0.0


def test_trading_away_the_only_te_opens_a_structural_hole():
    after = [p for p in FULL if p.player_id != "te"] + [P("wr2", "WR", 10.0, weeks("available"))]
    r = run(FULL, after)
    h = r["lineupHoles"]
    assert h["after"]["noEligiblePlayer"] == ["TE"]
    # Empty every simulated week.
    assert h["after"]["emptyBySlot"] == {"TE": 1.0}
    assert h["after"]["emptySlotsPerWeek"] == 1.0
    assert h["emptySlotsPerWeekDelta"] == 1.0


def test_a_bye_week_is_one_twelfth_of_an_empty_slot():
    """The only TE on a bye in week 9: his slot is empty in exactly that
    week's share of the simulation — bye coverage, measured."""
    bye_te = P("te", "TE", 9.0, weeks("available", w9=OUT))
    roster = [p for p in FULL if p.player_id != "te"] + [bye_te]
    h = run(roster, roster)["lineupHoles"]["before"]
    assert h["emptyBySlot"] == {"TE": round(1 / 12, 2)}
    assert h["noEligiblePlayer"] == []


def test_adding_bye_coverage_closes_the_hole():
    bye_te = P("te", "TE", 9.0, weeks("available", w9=OUT))
    roster = [p for p in FULL if p.player_id != "te"] + [bye_te]
    cover = P("te2", "TE", 5.0, weeks("available"))
    h = run(roster, [*roster, cover])["lineupHoles"]
    assert h["before"]["emptySlotsPerWeek"] > 0
    assert h["after"]["emptySlotsPerWeek"] == 0.0
    assert h["emptySlotsPerWeekDelta"] < 0


def test_a_slot_only_an_unprojected_player_fits_is_named_not_hidden():
    """Missing is never zero: a TE with no projection cannot be simulated, so
    the slot reads empty every week — and the report says WHY."""
    roster = [p for p in FULL if p.player_id != "te"] + [P("te_np", "TE", None)]
    h = run(roster, roster)["lineupHoles"]["before"]
    assert h["onlyUnprojected"] == ["TE"]
    assert h["noEligiblePlayer"] == []
    assert h["emptyBySlot"] == {"TE": 1.0}


def test_no_projected_player_at_all_is_unknown_not_all_empty():
    roster = [P("x", "QB", None), P("y", "RB", None)]
    h = run(roster, roster)["lineupHoles"]
    assert h["before"]["emptySlotsPerWeek"] is None
    assert h["before"]["emptyBySlot"] is None
    assert h["emptySlotsPerWeekDelta"] is None


def test_holes_never_change_the_utility_numbers():
    """Reported beside BBLI, never folded into it a second time."""
    after = [p for p in FULL if p.player_id != "te"]
    r = run(FULL, after)
    # BBLI already lost the TE's points; the report adds a block, not a term.
    assert r["impact"]["ppg"] < 0
    assert set(r) >= {"impact", "lineupHoles", "before", "after"}
    assert "lineupHoles" not in r["impact"]
