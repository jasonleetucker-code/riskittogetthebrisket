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

import json
from pathlib import Path

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


# ── Where the join actually changes an answer ────────────────────────

LIVE_CARDS = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "live_scoring_cards_2026-07-28.json").read_text(
        "utf-8"
    )
)


def _profile_rows(bands, weeks=17):
    rows = [
        {
            "player_id": "00-x",
            "player_display_name": "Probe",
            "position": "WR",
            "season": 2025,
            "week": w,
            "season_type": "REG",
            "receptions": sum(bands.values()),
            "receiving_yards": 80,
        }
        for w in range(1, weeks + 1)
    ]
    stats = PbpWeeklyStats(
        2025, {"00-x": {w: dict(bands) for w in range(1, weeks + 1)}}, range(1, weeks + 1)
    )
    return rows, stats


def _ratio(bands, *, joined):
    rows, stats = _profile_rows(bands)
    kw = {"pbp_for_season": (lambda _s: stats)} if joined else {}
    mine = compute_player_season_scores(rows, LIVE_CARDS["dynasty_main"], season=2025, **kw)
    base = compute_player_season_scores(rows, LIVE_CARDS["baseline"], season=2025, **kw)
    return mine[0].total_points / base[0].total_points


CHECKDOWN = {"rec_0_4": 4, "rec_5_9": 2}
BALANCED = {"rec_0_4": 1, "rec_5_9": 2, "rec_10_19": 2, "rec_20_29": 1}
DEEP = {"rec_30_39": 3, "rec_40p": 3}


def test_without_the_supplement_the_scoring_fit_measurement_cannot_discriminate():
    """The measurement's whole purpose, absent.

    `scoring_fit` asks how differently two cards price the same
    production. `dynasty_main` bands receptions 0.17→1.92; the baseline
    pays a flat 0.75 and **0.0 for every band**. With the bands unscored
    the difference between a checkdown back and a deep threat vanishes —
    and it does NOT cancel between the arms, because only one arm has
    anything to lose.
    """
    ratios = {
        p: _ratio(b, joined=False)
        for p, b in (("checkdown", CHECKDOWN), ("balanced", BALANCED), ("deep", DEEP))
    }
    assert len(set(round(r, 6) for r in ratios.values())) == 1, ratios
    assert ratios["checkdown"] == pytest.approx(0.678, abs=0.001)


def test_with_the_supplement_the_catch_profile_moves_the_ratio_the_right_way():
    checkdown = _ratio(CHECKDOWN, joined=True)
    balanced = _ratio(BALANCED, joined=True)
    deep = _ratio(DEEP, joined=True)
    assert checkdown < balanced < deep
    assert checkdown == pytest.approx(0.800, abs=0.002)
    assert deep == pytest.approx(1.420, abs=0.002)


def test_the_baseline_card_bands_nothing_which_is_why_gameplan_barely_moves():
    """Pins the correction, not just the fix.

    A review draft placed the sharpest effect on `gameplan.py`'s
    reception-share ratio (5.66% → 30.43%). That share is measured under
    the BASELINE card, and this is the fact that makes the number wrong:
    the baseline pays 0.0 for every band, so joining the supplement moves
    a pure receiver's share by exactly nothing. If a future card change
    makes this false, the justification written beside that call site
    stops being true and this test says so.
    """
    baseline = LIVE_CARDS["baseline"]
    assert all(
        float(baseline.get(b, 0) or 0) == 0.0
        for b in ("rec_0_4", "rec_5_9", "rec_10_19", "rec_20_29", "rec_30_39", "rec_40p")
    )
    assert float(baseline["rec"]) > 0.0, "it pays a flat rate instead — that is the difference"
