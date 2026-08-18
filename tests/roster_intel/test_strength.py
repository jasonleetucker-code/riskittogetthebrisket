"""Canonical Team Strength (feature-inventory row 1.1).

The claims worth pinning are the boundaries, not the arithmetic: that
Team Strength aggregates the meaningful core rather than the roster,
that it creates no value, that FLEX contributes without becoming a
column, that an unreadable roster is not a weak one, and that ranks are
measured against a real cohort rather than invented.
"""

from __future__ import annotations

from src.ros.lineup import RosterPlayer
from src.roster_intel.core import build_meaningful_core
from src.roster_intel.strength import (
    POSITION_GROUPS,
    build_team_strength,
    rank_team_strengths,
)


def P(pid, pos, val, **kw):
    return RosterPlayer(player_id=pid, canonical_name=pid, position=pos, ros_value=val, **kw)


_SLOTS = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"]


def _roster(scale=1.0):
    """A full, priced roster deep enough to fill every reserve slot."""
    out = [P(f"QB{i}", "QB", (900 - i * 100) * scale) for i in range(1, 4)]
    out += [P(f"RB{i}", "RB", (800 - i * 60) * scale) for i in range(1, 7)]
    out += [P(f"WR{i}", "WR", (850 - i * 55) * scale) for i in range(1, 8)]
    out += [P(f"TE{i}", "TE", (600 - i * 90) * scale) for i in range(1, 4)]
    return out


def _strength(pool=None, slots=None, **kw):
    core = build_meaningful_core(pool or _roster(), slots or _SLOTS)
    return build_team_strength(core, **kw)


# ══ It aggregates the CORE, not the roster ═════════════════════════


def test_total_is_the_core_not_the_whole_roster():
    """The W20-F003 distinction. A raw roster sum is a PORTFOLIO total;
    Team Strength is the meaningful core, and on a deep roster they are
    far apart by construction."""
    pool = _roster()
    core = build_meaningful_core(pool, _SLOTS)
    s = build_team_strength(core, full_roster_values=[p.ros_value for p in pool])
    assert s.total == sum(m.value for m in core.members)
    assert s.full_roster_value == sum(p.ros_value for p in pool)
    assert s.total < s.full_roster_value
    # Not a rounding difference: the roster carries real bench value the
    # core deliberately excludes.
    assert s.full_roster_value - s.total > 500


def test_full_roster_value_is_none_when_not_supplied():
    """Absent portfolio must not read as a portfolio worth nothing."""
    assert _strength().full_roster_value is None


def test_total_equals_starters_plus_reserves():
    s = _strength()
    assert s.total == s.starter_value + s.reserve_value
    assert s.starter_value > 0 and s.reserve_value > 0


def test_position_values_sum_to_the_total():
    """The parts must sum to the whole — otherwise a group quietly
    dropped out of the breakdown."""
    s = _strength()
    assert round(sum(p.value for p in s.by_position.values()), 6) == round(s.total, 6)


# ══ It creates no value ════════════════════════════════════════════


def test_strength_never_alters_a_canonical_value():
    """Every number is a sum of values handed in. Scaling every input by
    k scales the total by exactly k — no floor, no cap, no curve."""
    base = _strength(_roster(1.0))
    scaled = _strength(_roster(3.0))
    assert round(scaled.total, 6) == round(base.total * 3, 6)


def test_aggregates_are_not_capped_at_9999():
    """Inventory row 7.5: individual values are a 1-9999 scale, but
    aggregates "must not be clamped"."""
    pool = [P(f"QB{i}", "QB", 9999) for i in range(1, 4)]
    pool += [P(f"RB{i}", "RB", 9999) for i in range(1, 7)]
    pool += [P(f"WR{i}", "WR", 9999) for i in range(1, 8)]
    pool += [P(f"TE{i}", "TE", 9999) for i in range(1, 4)]
    s = _strength(pool)
    assert s.total > 9999
    assert s.to_dict()["total"] > 9999


# ══ FLEX contributes without becoming a column ═════════════════════


def test_flex_starter_counts_under_its_native_position():
    """Addendum §5: the value belongs to the team, and FLEX is not a
    sortable position."""
    s = _strength()
    assert "FLEX" not in s.by_position
    assert "SUPER_FLEX" not in s.by_position
    assert set(s.by_position) <= set(POSITION_GROUPS)


def test_flex_participation_raises_the_total():
    pool = _roster()
    without = _strength(pool, [s for s in _SLOTS if s not in ("FLEX", "SUPER_FLEX")])
    with_flex = _strength(pool, _SLOTS)
    assert with_flex.total > without.total


def test_position_order_puts_owner_groups_first():
    s = _strength()
    order = s.to_dict()["positionOrder"]
    declared = [p for p in order if p in POSITION_GROUPS]
    assert declared == [p for p in POSITION_GROUPS if p in order]


def test_a_group_outside_the_owner_list_still_counts_toward_the_total():
    """POSITION_GROUPS is a display order, not a filter. Dropping an
    unlisted group would stop the parts summing to the whole."""
    pool = _roster() + [P("K1", "K", 120)]
    s = _strength(pool, _SLOTS + ["K"])
    assert "K" in s.by_position
    assert s.by_position["K"].value == 120
    assert round(sum(p.value for p in s.by_position.values()), 6) == round(s.total, 6)
    assert s.to_dict()["positionOrder"][-1] == "K"


def test_idp_families_collapse_onto_their_slot_group():
    """DE/DT/EDGE are all DL rooms. Two native positions landing on one
    group must accumulate, not overwrite."""
    pool = [P("E1", "DE", 700), P("T1", "DT", 650), P("E2", "EDGE", 600)]
    s = _strength(pool, ["DL", "DL"])
    assert set(s.by_position) == {"DL"}
    assert s.by_position["DL"].count == 3  # 2 starters + 1 reserve
    assert s.by_position["DL"].value == 1950


# ══ Unreadable is not weak ═════════════════════════════════════════


def test_a_refused_core_propagates_refusal_not_a_zero_strength():
    core = build_meaningful_core(_roster(), [])
    s = build_team_strength(core)
    assert s.available is False
    assert s.unavailable_reason == "no_starter_slots"
    assert s.to_dict()["available"] is False


def test_unpriced_players_are_reported_and_mark_the_total_incomplete():
    pool = _roster() + [P("GHOST", "WR", None)]
    s = _strength(pool)
    assert s.unpriced_ids == frozenset({"GHOST"})
    assert s.is_complete is False
    assert s.to_dict()["unpricedCount"] == 1


def test_unfilled_slots_mark_the_total_incomplete():
    """A team missing starters is not simply weaker — part of its
    strength is UNMEASURED, and a consumer must be able to say so."""
    s = _strength([P("QB1", "QB", 900)])
    assert s.is_complete is False
    assert s.unfilled_starter_slots
    assert s.total == 900


def test_a_complete_roster_reports_complete():
    assert _strength().is_complete is True


# ══ League-relative ranking ════════════════════════════════════════


def _league(n=4):
    return {f"team{i}": _strength(_roster(scale=1.0 + i * 0.1)) for i in range(n)}


def test_rank_is_one_for_the_strongest_and_n_for_the_weakest():
    ranked = rank_team_strengths(_league(4))
    by_rank = {v.league_rank: k for k, v in ranked.items()}
    assert by_rank[1] == "team3"  # largest scale
    assert by_rank[4] == "team0"


def test_percentile_spans_the_full_range():
    """1.0 for best, 0.0 for worst — the share of OTHER teams at or
    below. Bottoming out at 1/n would understate the spread."""
    ranked = rank_team_strengths(_league(4))
    pcts = sorted(v.league_percentile for v in ranked.values())
    assert pcts[0] == 0.0
    assert pcts[-1] == 1.0


def test_a_single_team_has_no_percentile():
    """Nothing to compare to. Returning 1.0 would dress a missing
    comparison up as dominance."""
    ranked = rank_team_strengths(_league(1))
    only = next(iter(ranked.values()))
    assert only.league_rank == 1
    assert only.league_percentile is None


def test_ties_share_the_better_rank():
    league = {"a": _strength(), "b": _strength(), "c": _strength(_roster(0.5))}
    ranked = rank_team_strengths(league)
    assert ranked["a"].league_rank == 1
    assert ranked["b"].league_rank == 1
    assert ranked["c"].league_rank == 3  # competition style: 2 is skipped


def test_an_unreadable_roster_is_excluded_from_ranking_not_ranked_last():
    """Ranking it last would state it is the weakest — a claim about
    evidence we do not have."""
    league = _league(3)
    league["broken"] = build_team_strength(build_meaningful_core(_roster(), []))
    ranked = rank_team_strengths(league)
    assert ranked["broken"].league_rank is None
    assert ranked["broken"].league_percentile is None
    # The measurable teams rank among themselves, 1..3 — the broken one
    # did not consume a rank.
    assert sorted(v.league_rank for k, v in ranked.items() if k != "broken") == [1, 2, 3]


def test_per_position_ranks_are_measured_per_group():
    league = {
        "qbrich": _strength(
            [P("QB1", "QB", 9000), P("QB2", "QB", 8000), P("QB3", "QB", 7000)] + _roster()[3:]
        ),
        "qbpoor": _strength(_roster()),
    }
    ranked = rank_team_strengths(league)
    assert ranked["qbrich"].by_position["QB"].league_rank == 1
    assert ranked["qbpoor"].by_position["QB"].league_rank == 2
    # And the per-group rank is independent of the overall one.
    assert ranked["qbrich"].by_position["QB"].league_percentile == 1.0


def test_ranking_is_deterministic():
    league = _league(5)
    first = {k: v.league_rank for k, v in rank_team_strengths(league).items()}
    for _ in range(5):
        assert {k: v.league_rank for k, v in rank_team_strengths(league).items()} == first


def test_ranking_does_not_mutate_its_input():
    """`rank_team_strengths` returns new objects; a caller holding the
    unranked map must not see ranks appear."""
    league = _league(3)
    rank_team_strengths(league)
    assert all(v.league_rank is None for v in league.values())
