"""Roster Age-Value Portfolio / Young Core Index (row 1.6, #838).

The addendum's guardrail is the thing worth testing hardest: this
describes roster construction and **must not** become a second
age-adjusted valuation. After that, the three ways the metric goes
wrong — low-value youth dominating, position-blind youth, and missing
age reading as young.
"""

from __future__ import annotations

from src.ros.lineup import RosterPlayer
from src.roster_intel.core import build_meaningful_core
from src.roster_intel.age_portfolio import (
    YOUNG_CORE_INDEX_STATUS,
    build_age_portfolio,
    build_youth_curve,
    rank_age_portfolios,
)


def P(pid, pos, val, **kw):
    return RosterPlayer(player_id=pid, canonical_name=pid, position=pos, ros_value=val, **kw)


_SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE"]


def _roster():
    return [
        P("QB1", "QB", 9000),
        P("RB1", "RB", 8000),
        P("RB2", "RB", 4000),
        P("RB3", "RB", 1000),
        P("WR1", "WR", 7000),
        P("WR2", "WR", 6000),
        P("WR3", "WR", 2000),
        P("TE1", "TE", 5000),
        P("TE2", "TE", 500),
    ]


_AGES = {
    "QB1": 26.0,
    "RB1": 23.0,
    "RB2": 29.0,
    "RB3": 22.0,
    "WR1": 24.0,
    "WR2": 30.0,
    "WR3": 21.0,
    "TE1": 27.0,
    "TE2": 25.0,
}


def _curve():
    """A league population wide enough to express relative youth."""
    rows = []
    for pos, lo in (("QB", 22), ("RB", 21), ("WR", 21), ("TE", 23)):
        rows += [(pos, float(lo + i * 0.5)) for i in range(24)]
    return build_youth_curve(rows)


def _portfolio(pool=None, ages=None, **kw):
    core = build_meaningful_core(pool or _roster(), _SLOTS)
    return build_age_portfolio(core, _AGES if ages is None else ages, youth=_curve(), **kw)


# ══ THE guardrail: it never alters a player value ══════════════════


def test_scaling_every_value_leaves_every_age_statistic_unchanged():
    """A value-weighted MEAN is scale-invariant. If a future change
    slipped an age term into the value itself, this breaks."""
    base = _portfolio()
    scaled_pool = [P(p.player_id, p.position, p.ros_value * 7) for p in _roster()]
    scaled = _portfolio(scaled_pool)
    assert round(scaled.value_weighted_core_age, 9) == round(base.value_weighted_core_age, 9)
    assert round(scaled.core_youth_score, 9) == round(base.core_youth_score, 9)


def test_changing_an_age_never_changes_a_position_group_value():
    """Age moves the age statistics and nothing else."""
    base = _portfolio()
    older = _portfolio(ages={**_AGES, "QB1": 38.0})
    assert older.value_weighted_core_age > base.value_weighted_core_age
    assert {p: v.value for p, v in older.by_position.items()} == {
        p: v.value for p, v in base.by_position.items()
    }


def test_index_ships_labelled_a_prior():
    """The addendum requires validation "against intuitive league
    examples before treating it as canonical"; that has not run."""
    assert YOUNG_CORE_INDEX_STATUS == "PRIOR"
    assert _portfolio().to_dict()["youngCoreIndexStatus"] == "PRIOR"


# ══ Value-weighted core age ════════════════════════════════════════


def test_value_weighted_core_age_is_the_addendum_formula():
    """sum(age × value) / sum(value) over the meaningful core."""
    core = build_meaningful_core(_roster(), _SLOTS)
    expected = sum(_AGES[m.player_id] * m.value for m in core.members) / sum(
        m.value for m in core.members
    )
    assert round(_portfolio().value_weighted_core_age, 9) == round(expected, 9)


def test_core_age_is_weighted_not_arithmetic():
    """An arithmetic mean would let a worthless veteran age the roster
    as much as its franchise player."""
    pool = [P("STAR", "QB", 9000), P("SCRUB", "QB", 1)]
    # 1 QB slot ⇒ reserve demand ceil(1.5·1) − 1 = 1, so BOTH are in the
    # core and the weighting is what separates them.
    core = build_meaningful_core(pool, ["QB"])
    assert len(core.members) == 2
    p = build_age_portfolio(core, {"STAR": 22.0, "SCRUB": 40.0})
    # Arithmetic mean would be 31.0. Weighted by value it is 22.00.
    assert abs(p.value_weighted_core_age - 22.0) < 0.01
    assert abs(p.value_weighted_core_age - 31.0) > 8


def test_full_roster_age_is_secondary_context_and_optional():
    # A roster deeper than the core demand, so the two populations
    # genuinely differ. The bench is old, which is exactly the case the
    # addendum wants the CORE version to be immune to.
    bench = [P(f"OLD{i}", "WR", 40) for i in range(6)]
    pool = _roster() + bench
    ages = {**_AGES, **{f"OLD{i}": 33.0 for i in range(6)}}
    core = build_meaningful_core(pool, _SLOTS)
    assert len(core.members) < len(pool)

    without = build_age_portfolio(core, ages, youth=_curve())
    assert without.value_weighted_roster_age is None  # never 0

    with_roster = build_age_portfolio(
        core, ages, youth=_curve(), full_roster=[(p.player_id, p.ros_value) for p in pool]
    )
    assert with_roster.value_weighted_roster_age is not None
    assert with_roster.value_weighted_roster_age != with_roster.value_weighted_core_age
    # The old bench ages the full-roster figure and not the core one.
    assert with_roster.value_weighted_roster_age > with_roster.value_weighted_core_age


# ══ Missing age is never young ═════════════════════════════════════


def test_ageless_players_leave_both_sums():
    """Excluded from numerator AND denominator, so they neither pull the
    average nor dilute it."""
    partial = {k: v for k, v in _AGES.items() if k != "WR2"}
    core = build_meaningful_core(_roster(), _SLOTS)
    aged_only = [m for m in core.members if m.player_id in partial]
    expected = sum(partial[m.player_id] * m.value for m in aged_only) / sum(
        m.value for m in aged_only
    )
    assert round(_portfolio(ages=partial).value_weighted_core_age, 9) == round(expected, 9)


def test_no_ages_at_all_yields_none_not_zero():
    """0.0 would read as an impossibly young roster."""
    p = _portfolio(ages={})
    assert p.value_weighted_core_age is None
    assert p.core_youth_score is None
    assert p.to_dict()["valueWeightedCoreAge"] is None


def test_a_zero_age_is_treated_as_missing():
    """Sleeper carries 0 for an unresolved record, and 0 is exactly the
    value that would make a roster look historically young."""
    with_zero = _portfolio(ages={**_AGES, "QB1": 0.0})
    without = _portfolio(ages={k: v for k, v in _AGES.items() if k != "QB1"})
    assert with_zero.value_weighted_core_age == without.value_weighted_core_age


def test_coverage_reports_how_much_could_be_aged():
    """A value-weighted age over 40% of a roster is a different claim
    from one over all of it."""
    full = _portfolio()
    assert full.coverage.value_share == 1.0
    partial = _portfolio(ages={k: v for k, v in _AGES.items() if k in ("QB1", "RB1")})
    assert partial.coverage.aged_players == 2
    assert 0 < partial.coverage.value_share < 1


def test_picks_never_enter_the_age_maths():
    """Picks are excluded from age math rather than treated as age zero.
    Structural: they are not eligible players, so the core never holds
    them — and even if one were passed with no age, it is excluded."""
    pool = _roster() + [P("2027 Pick 1.01", "PICK", 6000)]
    p = _portfolio(pool)
    assert "PICK" not in p.by_position or p.by_position["PICK"].value_weighted_age is None
    assert round(p.value_weighted_core_age, 6) == round(_portfolio().value_weighted_core_age, 6)


# ══ Youth is position-relative ═════════════════════════════════════


def test_youth_is_scored_within_position():
    """A 27-year-old QB is young; a 27-year-old running back is not."""
    curve = _curve()
    qb27 = curve.youth_score("QB", 27.0)
    rb27 = curve.youth_score("RB", 27.0)
    assert qb27 is not None and rb27 is not None
    assert qb27 > rb27


def test_youth_score_is_none_without_a_population():
    """Position-relative youth is undefined with nothing to be relative
    to. 0.0 would mean "oldest in the league"."""
    empty = build_youth_curve([])
    assert empty.youth_score("QB", 24.0) is None
    core = build_meaningful_core(_roster(), _SLOTS)
    assert build_age_portfolio(core, _AGES).core_youth_score is None


def test_ageless_players_do_not_shift_the_curve_they_are_measured_against():
    with_none = build_youth_curve([("QB", 25.0), ("QB", 27.0), ("QB", None)])
    without = build_youth_curve([("QB", 25.0), ("QB", 27.0)])
    assert with_none.by_position == without.by_position


# ══ Low-value youth cannot dominate ════════════════════════════════


def test_low_value_youth_barely_moves_the_index():
    """The failure the addendum names: "a roster full of low-value youth
    cannot dominate the index"."""
    base = _portfolio()
    # Add the youngest possible player at a trivial value. He is in the
    # core only if he displaces someone; give him a fringe value so he
    # does not, and the score must be unchanged.
    padded = _portfolio(_roster() + [P("BABY", "WR", 5)], ages={**_AGES, "BABY": 20.0})
    assert round(padded.core_youth_score, 6) == round(base.core_youth_score, 6)


def test_a_valuable_young_player_moves_it_a_lot():
    """The other direction — the metric must still respond."""
    swapped = [p for p in _roster() if p.player_id != "WR2"]
    swapped.append(P("WR2", "WR", 6000))
    younger = _portfolio(swapped, ages={**_AGES, "WR2": 21.0})
    assert younger.core_youth_score > _portfolio().core_youth_score


# ══ Distribution ═══════════════════════════════════════════════════


def test_value_by_age_sums_to_the_aged_value():
    p = _portfolio()
    assert round(sum(p.value_by_age.values()), 6) == round(p.coverage.aged_value, 6)


def test_bands_partition_the_per_age_series():
    """Bands are for reading; the per-age series is the data. They must
    agree."""
    p = _portfolio()
    assert round(sum(p.value_by_band.values()), 6) == round(sum(p.value_by_age.values()), 6)


def test_position_shares_sum_to_one():
    p = _portfolio()
    assert round(sum(v.value_share for v in p.by_position.values()), 6) == 1.0


# ══ League-relative ════════════════════════════════════════════════


def _league():
    young = [P(f"{p}{i}", p, 9000 - i * 100) for p in ("QB", "RB", "WR", "TE") for i in range(3)]
    old_ages = {pl.player_id: 30.0 for pl in young}
    young_ages = {pl.player_id: 22.0 for pl in young}
    mid_ages = {pl.player_id: 26.0 for pl in young}
    return {
        "youngest": build_age_portfolio(
            build_meaningful_core(young, _SLOTS), young_ages, youth=_curve()
        ),
        "middling": build_age_portfolio(
            build_meaningful_core(young, _SLOTS), mid_ages, youth=_curve()
        ),
        "oldest": build_age_portfolio(
            build_meaningful_core(young, _SLOTS), old_ages, youth=_curve()
        ),
    }


def test_index_is_zero_to_one_hundred_and_ordered_by_youth():
    ranked = rank_age_portfolios(_league())
    assert ranked["youngest"].young_core_index == 100.0
    assert ranked["oldest"].young_core_index == 0.0
    assert 0 < ranked["middling"].young_core_index < 100


def test_index_is_none_before_ranking():
    """A team alone has no league-relative index, and 50.0 would be an
    invented middle."""
    assert _portfolio().young_core_index is None


def test_a_single_team_league_gets_no_index():
    ranked = rank_age_portfolios({"only": _portfolio()})
    assert ranked["only"].young_core_index is None
    assert ranked["only"].league_percentile is None


def test_an_unaged_team_is_excluded_from_ranking_not_ranked_last():
    """Its position would be an artifact of the join, not of the
    roster."""
    league = _league()
    league["unaged"] = _portfolio(ages={})
    ranked = rank_age_portfolios(league)
    assert ranked["unaged"].young_core_index is None
    assert ranked["unaged"].league_rank is None
    # The measurable teams still span the full range among themselves.
    assert ranked["youngest"].young_core_index == 100.0


def test_league_median_age_and_old_flag_are_measured_not_assumed():
    ranked = rank_age_portfolios(_league())
    old_qb = ranked["oldest"].by_position["QB"]
    assert old_qb.league_median_age is not None
    assert old_qb.age_vs_league_median > 0
    assert old_qb.is_old_for_league is True
    assert ranked["youngest"].by_position["QB"].is_old_for_league is False


def test_position_leaderboards_rank_the_youngest_valuable_room():
    ranked = rank_age_portfolios(_league())
    assert ranked["youngest"].by_position["RB"].league_rank == 1
    assert ranked["oldest"].by_position["RB"].league_rank == 3


def test_ranking_is_deterministic_and_does_not_mutate_its_input():
    league = _league()
    first = {k: v.young_core_index for k, v in rank_age_portfolios(league).items()}
    assert {k: v.young_core_index for k, v in rank_age_portfolios(league).items()} == first
    assert all(v.young_core_index is None for v in league.values())


# ══ Refusal ════════════════════════════════════════════════════════


def test_a_refused_core_propagates_refusal():
    core = build_meaningful_core(_roster(), [])
    p = build_age_portfolio(core, _AGES, youth=_curve())
    assert p.available is False
    assert p.unavailable_reason == "no_starter_slots"
    assert p.value_weighted_core_age is None
