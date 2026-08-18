"""#802 — the production consumers actually join the supplement.

A producer nothing calls is the defect this unit was opened to fix:
``reception_depth`` had emitted Sleeper's six band keys by name since
2026-07-27, and ``scoring_coverage`` still reported them as impossible to
know, because no realized-points path joined it.

So the seam is not enough. These tests pin that each production caller
threads a resolver through to ``compute_weekly_points``, and — the half
that is easy to get wrong — that the DEFAULT (no resolver) still reports
the shortfall instead of hiding it.
"""

from __future__ import annotations

import pytest

from src.bdvm.actuals import weekly_points_from_rows
from src.bdvm.baseline import realized_ppg_history
from src.league_comparison.scoring_engine import compute_player_season_scores
from src.nfl_data.pbp_weekly import PbpWeeklyStats

CARD = {"rec": 0.08, "rec_0_4": 0.25, "rec_10_19": 0.75}


def _rows(season=2024, weeks=(1, 2)):
    return [
        {
            "player_id": "00-a",
            "player_display_name": "Check Down",
            "position": "RB",
            "season": season,
            "week": w,
            "season_type": "REG",
            "receptions": 4,
            "receiving_yards": 20,
        }
        for w in weeks
    ]


def _stats(season=2024, weeks=(1, 2)):
    return PbpWeeklyStats(
        season,
        {"00-a": {w: {"rec_0_4": 3.0, "rec_10_19": 1.0} for w in weeks}},
        weeks,
    )


def _norm(name):
    return str(name).strip().lower()


# ── bdvm.baseline — the historical path ──────────────────────────────


def test_the_reconstructed_baseline_scores_the_bands_when_the_producer_is_joined():
    stats = _stats()
    without = realized_ppg_history(_rows(), CARD, name_normalizer=_norm)
    joined = realized_ppg_history(
        _rows(), CARD, name_normalizer=_norm, pbp_for_season=lambda _s: stats
    )

    flat = 4 * 0.08
    banded = flat + 3 * 0.25 + 1 * 0.75
    assert without["check down"][1][0].ppg == pytest.approx(flat)
    assert joined["check down"][1][0].ppg == pytest.approx(banded)
    assert banded > flat * 4, "the bands are the majority of a checkdown back's value"


def test_a_season_the_producer_never_built_is_left_alone_not_zeroed():
    """Unlike the season-CARD resolver, an unbuilt play-by-play season does
    NOT drop the season. A partial line is a real lower bound; an unknown
    rule set makes the whole line meaningless. Different missing facts,
    different refusals."""
    joined = realized_ppg_history(
        _rows(), CARD, name_normalizer=_norm, pbp_for_season=lambda _s: None
    )
    assert joined["check down"][1][0].ppg == pytest.approx(4 * 0.08)
    assert joined["check down"][1][0].games == 2.0


# ── bdvm.actuals — the in-season path ────────────────────────────────


def test_in_season_weekly_points_use_the_supplement_when_supplied():
    _week, without = weekly_points_from_rows(_rows(2025), CARD, season=2025, name_normalizer=_norm)
    _week, joined = weekly_points_from_rows(
        _rows(2025), CARD, season=2025, name_normalizer=_norm, pbp_stats=_stats(2025)
    )
    assert without["check down"][0][1] == pytest.approx(4 * 0.08)
    assert joined["check down"][0][1] == pytest.approx(4 * 0.08 + 3 * 0.25 + 0.75)


# ── league_comparison — the card-vs-card path ────────────────────────


def test_league_comparison_scores_the_bands_when_the_producer_is_joined():
    stats = _stats()
    without = compute_player_season_scores(_rows(), CARD, season=2024)
    joined = compute_player_season_scores(
        _rows(), CARD, season=2024, pbp_for_season=lambda _s: stats
    )
    assert without[0].total_points == pytest.approx(2 * 4 * 0.08)
    assert joined[0].total_points == pytest.approx(2 * (4 * 0.08 + 3 * 0.25 + 0.75))


def test_a_host_native_row_is_never_given_a_supplement():
    """The host publishes these keys itself, so the merge would double
    count — and ``compute_weekly_points`` raises on the combination. If
    the consumer did not skip host rows, this would blow up rather than
    silently mis-score, which is the right failure but still a failure."""
    row = {
        "player_id": "00-a",
        "player_id_sleeper": "4046",
        "position": "WR",
        "season": 2024,
        "week": 1,
        "source": "sleeper",
        "rec": 4,
        "rec_0_4": 3,
    }
    out = compute_player_season_scores([row], CARD, season=2024, pbp_for_season=lambda _s: _stats())
    assert out[0].total_points == pytest.approx(4 * 0.08 + 3 * 0.25)
