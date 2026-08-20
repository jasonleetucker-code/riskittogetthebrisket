"""V1-52: retiring ``power.py`` needs its raw PPG/recent-form magnitudes.

THE CLAIM THIS CORRECTS.

``docs/power/V1_52_CANONICAL_POWER_ENGINE.md`` (Step 5) argued retirement was
blocked because ``power.jsx`` renders raw magnitudes (``pointsPerGame``,
``recentAvg``) that ``power_v2`` "only ever published as percentiles" -- and
that recovering them would mean "a second computation ... becoming a second
owner one layer down". #996 already found one third of that claim overstated
(``components.all_play`` was never a percentile at all). This file closes the
other two thirds.

``_score_state`` computes the exact raw magnitudes (``inputs[oid]["ppg"]``,
``inputs[oid]["recent"]``, from the SAME ``career``/``recent`` accumulators
``power.py`` reads) as an unavoidable intermediate step BEFORE converting them
to the percentiles it publishes as ``components.ppg``/``components.recent``.
Storing that already-computed local instead of discarding it is not a second
engine and not "recomputing from a percentile" (the thing the assignment
forbids) -- it is the exact same category of change #996 made for
``record``/``teamName``: surfacing a value this one canonical function already
built.

Present on the headline rows, every trend-week row (both flow through the same
``_score_state``, so this is not a second code path for the week-by-week
history the retirement's week-selector UI needs), and the refuse-to-rank rows
(a magnitude is a fact independent of whether a score could be computed, same
posture ``record`` already has).

Display-only: excluded from ``WEIGHTS``/``active_weights`` by construction, so
publishing it must never move ``powerScore``.
"""

from __future__ import annotations

from src.ros import power_v2
from tests.ros.test_power_lenses import _scored_snapshot
from tests.public_league.fixtures import build_test_snapshot

# Hand-computed from the ``_scored_snapshot`` fixture: 4 owners, 3 weeks,
# points = {o1: 121/122/123, o2: 101/102/103, o3: 96/97/98, o4: 81/82/83}.
# All 3 weeks fall inside the recent-form window (3), so ppg == recentAvg
# for every owner in this fixture -- a useful property for pinning both
# fields against one hand-derived number per owner.
_EXPECTED_PPG = {"o1": 122.0, "o2": 102.0, "o3": 97.0, "o4": 82.0}


def test_raw_ppg_and_recent_avg_are_present_and_correct_on_headline_rows():
    out = power_v2.build_section(_scored_snapshot(), lens=power_v2.LENS_FORWARD_LOOKING)
    assert out["unrankable"] is None, "fixture must exercise the NORMAL scoring path"
    seen = set()
    for row in out["currentRanking"]:
        oid = row["ownerId"]
        seen.add(oid)
        c = row["components"]
        assert c["pointsPerGame"] == _EXPECTED_PPG[oid]
        assert c["recentAvg"] == _EXPECTED_PPG[oid]
    assert seen == set(_EXPECTED_PPG)


def test_raw_fields_are_a_different_quantity_from_the_percentile_fields():
    """The percentile keys ``ppg``/``recent`` must survive unchanged --
    this is an ADDITION, not a rename."""
    out = power_v2.build_section(_scored_snapshot(), lens=power_v2.LENS_FORWARD_LOOKING)
    for row in out["currentRanking"]:
        c = row["components"]
        assert 0.0 <= c["ppg"] <= 1.0, "percentile key must stay a 0-1 percentile"
        assert 0.0 <= c["recent"] <= 1.0
        assert c["pointsPerGame"] > 1.0, "raw magnitude must not be mistaken for a percentile"


def test_raw_fields_do_not_move_the_weighted_score():
    """Display-only: not in ``WEIGHTS``, so they cannot move ``powerScore``."""
    assert "pointsPerGame" not in power_v2.WEIGHTS
    assert "recentAvg" not in power_v2.WEIGHTS
    out = power_v2.build_section(_scored_snapshot(), lens=power_v2.LENS_FORWARD_LOOKING)
    for row in out["currentRanking"]:
        assert set(row["weightsApplied"]).isdisjoint({"pointsPerGame", "recentAvg"})


def test_raw_fields_are_present_on_every_trend_week_row():
    """The week-selector UI needs a full historical table, not just the
    headline -- and the trend series runs through the SAME ``_score_state``,
    so this is one function's output, not a second computation for history."""
    out = power_v2.build_section(_scored_snapshot(), lens=power_v2.LENS_FORWARD_LOOKING)
    weeks = out["trend"]["weeks"]
    assert weeks, "fixture must have real trend history"
    for week in weeks:
        assert week["rankings"], f"week {week['season']}/{week['week']} has no rankings"
        for row in week["rankings"]:
            assert "pointsPerGame" in row["components"]
            assert "recentAvg" in row["components"]
            assert row["components"]["pointsPerGame"] > 1.0


def test_raw_fields_are_present_even_when_the_engine_refuses_to_rank():
    """A magnitude is a fact independent of whether a weighted score
    survives -- same posture ``record`` already has (see
    ``test_power_v2_headline_fields.py``)."""
    out = power_v2.build_section(build_test_snapshot(), lens=power_v2.LENS_FORWARD_LOOKING)
    assert out["unrankable"] is not None, "fixture must exercise the REFUSAL path"
    assert out["currentRanking"], "the refusal still lists every owner"
    for row in out["currentRanking"]:
        assert row["powerScore"] is None
        assert "pointsPerGame" in row["components"]
        assert "recentAvg" in row["components"]
