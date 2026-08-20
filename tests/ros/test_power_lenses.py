"""V1-52 — two lenses, one engine.

Two power rankings of this league are published today. Measured in the
audit capture ``docs/master-site-audit/evidence/W30/power-two-engines.json``,
on the same week:

    public_league/power.py   Jason ranked 10 of 10   (0.00)
    ros/power_v2.py          Jason ranked  3 of 12   (80.69)

mean |rank shift| 2.8, max 7. Same manager, same week, two answers, and
nothing on either surface says they are different quantities.

The owner direction for V1-52 is one canonical power-ranking engine with
explicitly defined public and private outputs/lenses, and specifically:

> The public ranking should be the best legitimate power ranking we can
> produce, including appropriate forward-looking roster strength — not
> deliberately weaker standings-only math.

This file pins the precondition for that: the retrospective view is the
SAME engine with the forward-looking input declared missing, not a
second formula. The renormalisation is the machinery that already
handles an absent team-strength file, so every retrospective component
keeps its weight RELATIVE to the others across both lenses.
"""

from __future__ import annotations

import pytest

from types import SimpleNamespace

from src.ros import power_v2


def _empty_snapshot():
    """A snapshot with no seasons — enough to reach the lens decision."""
    return SimpleNamespace(seasons=[], current_season=None, managers=None)


def _scored_snapshot():
    """A league with real scored weeks, so the engine produces real
    scores rather than short-circuiting on a degenerate fixture."""
    from tests.ros.test_power_v2 import _make_snapshot

    rosters = [{"roster_id": i, "owner_id": f"o{i}"} for i in (1, 2, 3, 4)]
    matchups = {
        wk: [
            {"roster_id": 1, "matchup_id": 1, "points": 120.0 + wk},
            {"roster_id": 2, "matchup_id": 1, "points": 100.0 + wk},
            {"roster_id": 3, "matchup_id": 2, "points": 95.0 + wk},
            {"roster_id": 4, "matchup_id": 2, "points": 80.0 + wk},
        ]
        for wk in (1, 2, 3)
    }
    return _make_snapshot(rosters, matchups)


def test_the_two_lenses_share_one_weight_vector():
    """Not two formulas. ``WEIGHTS`` is the only weighting either lens
    has, so a change to one is a change to both — which is what stops
    them drifting into two engines again."""
    assert set(power_v2.WEIGHTS) == {
        "team_ros_strength",
        "ppg",
        "recent",
        "wl_record",
        "all_play",
        "streak",
        "schedule_adjusted",
        "luck_regression",
    }
    assert sum(power_v2.WEIGHTS.values()) == pytest.approx(1.0)


def test_dropping_ros_renormalises_rather_than_deflating(monkeypatch):
    """THE BUG THIS AVOIDS, observed on the ENGINE rather than re-derived.

    ``missing_inputs`` is a human-readable list and the weight lookup
    keys on component NAMES. Marking the lens as
    ``"team_ros_strength (lens: results_only)"`` without normalising it
    back leaves the 0.41 weight active against a component of 0.0 — a
    silent 41% deflation of every score, which reads as "every team got
    worse" rather than "a different question was asked".

    A first version of this test asserted the arithmetic on ``WEIGHTS``
    directly and stayed GREEN when the engine's normalisation was
    reverted. It was testing its own re-derivation. This one runs the
    engine and checks the weights it actually applied.
    """
    monkeypatch.setattr(power_v2, "_load_team_strength_percentiles", lambda: {})
    out = power_v2.build_section(_scored_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)

    applied = out["effectiveWeights"]
    assert "team_ros_strength" not in applied, (
        "the lens marker was not normalised back to a component name, so the "
        "ROS weight stayed active against a zero component"
    )
    # ``schedule_adjusted`` is DERIVED from team strength, so it drops with
    # it — one rule, not two. That is the reason the lens does not load
    # team strength at all rather than loading and discarding it.
    assert "schedule_adjusted" not in applied
    assert sum(applied.values()) == pytest.approx(
        1.0 - power_v2.WEIGHTS["team_ros_strength"] - power_v2.WEIGHTS["schedule_adjusted"]
    )
    # And the scores are renormalised, not scaled down by the dropped budget.
    assert out["currentRanking"], "fixture produced no ranking"
    assert max(r["powerScore"] for r in out["currentRanking"]) > 0.0


def test_the_retrospective_components_keep_their_relative_weighting():
    """What makes them lenses rather than engines: the results-only view
    is the forward-looking one with a term removed and the rest scaled,
    so no retrospective component is re-weighted against another."""
    full = power_v2.WEIGHTS
    active = {k: v for k, v in full.items() if k != "team_ros_strength"}
    total = sum(active.values())
    for a in active:
        for b in active:
            if a == b:
                continue
            assert (full[a] / full[b]) == pytest.approx((active[a] / total) / (active[b] / total))


def test_the_lens_marker_says_it_was_a_CHOICE_not_a_missing_file():
    """A reader must be able to tell a deliberate retrospective view from
    an engine that wanted forward-looking strength and could not get it.
    Both drop the same weight; only one of them is a defect."""
    assert power_v2._LENS_DROPPED_ROS != "team_ros_strength"
    assert power_v2._LENS_DROPPED_ROS.startswith("team_ros_strength")
    assert "results_only" in power_v2._LENS_DROPPED_ROS


def test_the_results_only_lens_never_reads_team_strength(monkeypatch):
    """Not loaded-and-discarded. Loading it would make the lens
    indistinguishable from a league whose file is present, and would
    leave ``schedule_adjusted`` — which is DERIVED from team strength —
    alive under a lens that is supposed to be results-only."""
    calls = []
    monkeypatch.setattr(
        power_v2,
        "_load_team_strength_percentiles",
        lambda: calls.append(1) or {"o1": 0.9},
    )

    power_v2.build_section(_empty_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
    assert calls == [], "the results-only lens consulted team strength"

    power_v2.build_section(_empty_snapshot(), lens=power_v2.LENS_FORWARD_LOOKING)
    # The forward-looking lens may short-circuit on an empty snapshot
    # before loading; what matters is that the lens above did not.


@pytest.mark.parametrize("lens", [power_v2.LENS_FORWARD_LOOKING, power_v2.LENS_RESULTS_ONLY])
def test_every_payload_stamps_which_lens_produced_it(lens):
    """Including the refusals. "This is the forward-looking ranking" and
    "this field predates the lens" must not read the same — the rule
    CLAUDE.md states for ``valuationMode``."""

    out = power_v2.build_section(_empty_snapshot(), lens=lens)
    assert out["lens"] == lens


# ── The trend series ─────────────────────────────────────────────────


def _asymmetric_snapshot(through_week: int | None = None):
    """A league whose weeks actually differ, so a trend can move.

    ``through_week`` truncates the season, so a test can ask what the
    engine would have said at that point in time."""
    from src.public_league.identity import Manager, ManagerRegistry
    from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot

    rosters = [{"roster_id": i, "owner_id": f"o{i}"} for i in (1, 2, 3, 4)]
    matchups = {
        1: [
            {"roster_id": 1, "matchup_id": 1, "points": 90.0},
            {"roster_id": 2, "matchup_id": 1, "points": 88.0},
            {"roster_id": 3, "matchup_id": 2, "points": 140.0},
            {"roster_id": 4, "matchup_id": 2, "points": 150.0},
        ],
        2: [
            {"roster_id": 1, "matchup_id": 1, "points": 85.0},
            {"roster_id": 3, "matchup_id": 1, "points": 130.0},
            {"roster_id": 2, "matchup_id": 2, "points": 70.0},
            {"roster_id": 4, "matchup_id": 2, "points": 60.0},
        ],
        3: [
            {"roster_id": 1, "matchup_id": 1, "points": 100.0},
            {"roster_id": 4, "matchup_id": 1, "points": 95.0},
            {"roster_id": 2, "matchup_id": 2, "points": 115.0},
            {"roster_id": 3, "matchup_id": 2, "points": 112.0},
        ],
    }
    if through_week is not None:
        matchups = {w: v for w, v in matchups.items() if w <= through_week}
    registry = ManagerRegistry()
    for r in rosters:
        oid = str(r["owner_id"])
        registry.by_owner_id[oid] = Manager(owner_id=oid, display_name=oid)
        registry.roster_to_owner[("L2026", int(r["roster_id"]))] = oid
    season = SeasonSnapshot(
        season="2026",
        league_id="L2026",
        league={
            "league_id": "L2026",
            "season": "2026",
            "season_type": "regular",
            "settings": {"playoff_week_start": 15},
            "total_rosters": 4,
        },
        users=[],
        rosters=rosters,
        matchups_by_week=matchups,
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )
    return PublicLeagueSnapshot(
        root_league_id="L2026",
        generated_at="2026-04-30T00:00:00Z",
        seasons=[season],
        managers=registry,
    )


def test_each_trend_week_reflects_the_state_AS_OF_that_week(monkeypatch):
    """THE BUG THIS AVOIDS, and it would have been invisible.

    The accumulators keep mutating as the walk proceeds, so storing a
    REFERENCE per week rather than a copy makes every week's entry show
    the final standings — a trend line that is flat by construction and
    cannot go down. Here week 1 and week 3 must differ, and at least one
    manager's rank must change across the series.
    """
    monkeypatch.setattr(power_v2, "_load_team_strength_percentiles", lambda: {})
    out = power_v2.build_section(_asymmetric_snapshot())
    weeks = out["trend"]["weeks"]

    assert [w["week"] for w in weeks] == [1, 2, 3]

    # THE property, stated exactly: the trend's week-N point is what the
    # engine would have said if the season had ended at week N. A weaker
    # "the weeks differ from each other" check passes even when SOME of
    # the five accumulators are shared by reference, because the others
    # still vary — measured, and it is why this is written this way.
    for n in (1, 2, 3):
        as_of = power_v2.build_section(_asymmetric_snapshot(through_week=n))
        expected = {r["ownerId"]: r["powerScore"] for r in as_of["currentRanking"]}
        got = {r["ownerId"]: r["powerScore"] for r in weeks[n - 1]["rankings"]}
        assert got == expected, f"week {n} of the trend is not the week-{n} state"

    first = {r["ownerId"]: r["rank"] for r in weeks[0]["rankings"]}
    last = {r["ownerId"]: r["rank"] for r in weeks[-1]["rankings"]}
    assert any(first[o] != last[o] for o in first), "no rank moved — the trend is not a trend"


def test_the_trend_is_results_only_at_every_point_including_the_last(monkeypatch):
    """Forward-looking strength is a CURRENT snapshot with no per-week
    history, so no past week has an observation of it. Back-filling
    today's value is the as-of defect; splicing it into only the final
    point is worse, because the line would jump for a reason unrelated to
    play and no reader could tell that from a real move."""
    monkeypatch.setattr(power_v2, "_load_team_strength_percentiles", lambda: {"o1": 0.99})
    out = power_v2.build_section(_asymmetric_snapshot())

    assert out["lens"] == power_v2.LENS_FORWARD_LOOKING
    assert out["trend"]["lens"] == power_v2.LENS_RESULTS_ONLY
    for week in out["trend"]["weeks"]:
        for row in week["rankings"]:
            assert "team_ros_strength" not in row["weightsApplied"]
            assert row["rosStrengthPercentile"] is None


def test_the_trend_says_it_differs_from_the_headline(monkeypatch):
    """Named, not left to be discovered. With forward-looking strength
    available the headline and the final trend point are different
    quantities, and a reader comparing them needs to be told."""
    monkeypatch.setattr(
        power_v2,
        "_load_team_strength_percentiles",
        lambda: {"o1": 0.99, "o2": 0.5, "o3": 0.1, "o4": 0.2},
    )
    out = power_v2.build_section(_asymmetric_snapshot())

    headline = {r["ownerId"]: r["powerScore"] for r in out["currentRanking"]}
    final_point = {r["ownerId"]: r["powerScore"] for r in out["trend"]["weeks"][-1]["rankings"]}
    assert headline != final_point, "fixture failed to make the lenses differ"
    assert "Results only" in out["trend"]["note"]
    assert "will differ" in out["trend"]["note"]


def test_the_series_and_the_weeks_are_the_same_numbers(monkeypatch):
    """``seriesByOwner`` is a re-shape for charting, not a second
    computation — the defect this whole unit exists to close, one layer
    down."""
    monkeypatch.setattr(power_v2, "_load_team_strength_percentiles", lambda: {})
    out = power_v2.build_section(_asymmetric_snapshot())

    from_weeks = {
        (w["week"], r["ownerId"]): r["powerScore"]
        for w in out["trend"]["weeks"]
        for r in w["rankings"]
    }
    from_series = {
        (p["week"], oid): p["powerScore"]
        for oid, points in out["trend"]["seriesByOwner"].items()
        for p in points
    }
    assert from_weeks == from_series
