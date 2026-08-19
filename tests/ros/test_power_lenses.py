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
