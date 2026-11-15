"""Synthetic reception-band split detection (``src.nfl_data.synthetic_splits``).

Ground truth on both sides, never a hand-made line alone:

* provider side — the committed RotoWire sample and a live 2026 week-7/8
  capture of every banded row (``tests/fixtures/li_scoring``);
* realized side — reception bands derived from real 2025 play-by-play
  (``tests/nfl_data/fixtures/pbp_2025_wk*_slice.csv``) by the canonical
  producer :func:`src.nfl_data.pbp_weekly.accumulate_weekly`.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from src.nfl_data.pbp_weekly import accumulate_weekly
from src.nfl_data.synthetic_splits import (
    RECEPTION_BAND_KEYS,
    SLEEPER_RECEPTION_BAND_SHARES,
    detect_synthetic_reception_split,
    synthetic_band_keys,
)

ROOT = Path(__file__).resolve().parents[2]
ROTOWIRE_SAMPLE = ROOT / "tests/fixtures/game_day/sleeper_projections/2026_w3_rotowire_sample.json"
LIVE_BANDS = ROOT / "tests/fixtures/li_scoring/sleeper_projection_band_lines_2026_w7_w8.json"
PBP_SLICES = [ROOT / f"tests/nfl_data/fixtures/pbp_2025_wk{w}_slice.csv" for w in (1, 5, 11, 14)]


def test_shares_are_the_measured_split_and_read_only():
    assert dict(SLEEPER_RECEPTION_BAND_SHARES) == {
        "rec_0_4": 0.2,
        "rec_5_9": 0.2,
        "rec_10_19": 0.3,
        "rec_20_29": 0.2,
        "rec_30_39": 0.1,
        "rec_40p": 0.1,
    }
    assert tuple(SLEEPER_RECEPTION_BAND_SHARES) == RECEPTION_BAND_KEYS
    # The split over-allocates by 10% — not a partition of the receptions.
    assert math.isclose(sum(SLEEPER_RECEPTION_BAND_SHARES.values()), 1.1)
    with pytest.raises(TypeError):
        SLEEPER_RECEPTION_BAND_SHARES["rec_0_4"] = 0.5  # type: ignore[index]


def test_every_pass_catcher_in_the_rotowire_sample_is_synthetic():
    rows = json.loads(ROTOWIRE_SAMPLE.read_text(encoding="utf-8"))
    catchers = [r["stats"] for r in rows if (r.get("stats") or {}).get("rec")]
    assert len(catchers) >= 5  # non-vacuous: RB, WR, TE and an IDP line
    for stats in catchers:
        assert detect_synthetic_reception_split(stats), stats
        assert synthetic_band_keys(stats) == RECEPTION_BAND_KEYS


def test_every_banded_row_of_a_live_two_week_capture_is_synthetic():
    data = json.loads(LIVE_BANDS.read_text(encoding="utf-8"))
    counts = data["_provenance"]["rowsPerWeek"]
    assert counts == {"7": 349, "8": 356}
    for week, rows in data["weeks"].items():
        assert len(rows) == counts[week]
        misses = [r for r in rows if not detect_synthetic_reception_split(r["stats"])]
        assert misses == [], (week, misses[:3])


def test_double_rounding_case_from_the_live_feed_is_detected():
    # rec published 0.18 but rec_10_19 0.06: the provider split ~0.185 and
    # rounded both.  A single-rounding tolerance would miss it.
    stats = {
        "rec": 0.18,
        "rec_0_4": 0.04,
        "rec_5_9": 0.04,
        "rec_10_19": 0.06,
        "rec_20_29": 0.04,
        "rec_30_39": 0.02,
        "rec_40p": 0.02,
    }
    assert detect_synthetic_reception_split(stats)


def _realized_band_lines() -> list[dict[str, float]]:
    lines = []
    for path in PBP_SLICES:
        with path.open("r", encoding="utf-8", newline="") as fh:
            by_player, _weeks = accumulate_weekly(fh)
        for weeks in by_player.values():
            for events in weeks.values():
                bands = {k: v for k, v in events.items() if k in RECEPTION_BAND_KEYS}
                if not bands:
                    continue
                # Each catch lands in exactly one band, so the bands
                # partition the receptions.
                lines.append({"rec": sum(bands.values()), **bands})
    return lines


def test_no_realized_pbp_band_line_is_synthetic():
    lines = _realized_band_lines()
    assert len(lines) > 300  # non-vacuous across four real weeks
    assert any(line["rec"] >= 10 for line in lines)
    for line in lines:
        assert not detect_synthetic_reception_split(line), line
        assert synthetic_band_keys(line) == ()


@pytest.mark.parametrize(
    "stats",
    [
        {},
        {"rec": 0.0, "rec_0_4": 0.0},
        {"rec": 0},
        {"rec_0_4": 0.2, "rec_5_9": 0.2},  # bands with no receptions
        {"rec": None, "rec_0_4": 0.2},
        {"rec": -1.0, "rec_0_4": -0.2},
        {"rec": float("nan"), "rec_0_4": 0.2},
        {"rec": 5.0},  # receptions but no bands: nothing to detect
    ],
)
def test_zero_absent_or_unusable_receptions_never_match(stats):
    assert detect_synthetic_reception_split(stats) is False
    assert synthetic_band_keys(stats) == ()


def test_a_single_deviating_band_breaks_the_match():
    base = {k: round(v * 6.0, 2) for k, v in SLEEPER_RECEPTION_BAND_SHARES.items()}
    base["rec"] = 6.0
    assert detect_synthetic_reception_split(base)
    for key in RECEPTION_BAND_KEYS:
        bent = dict(base)
        bent[key] = bent[key] + 0.05
        assert not detect_synthetic_reception_split(bent), key


def test_non_numeric_band_is_not_a_match():
    stats = {k: round(v * 6.0, 2) for k, v in SLEEPER_RECEPTION_BAND_SHARES.items()}
    stats["rec"] = 6.0
    stats["rec_40p"] = "n/a"
    assert not detect_synthetic_reception_split(stats)


def test_absent_band_matches_only_where_the_split_rounds_to_zero():
    # rec 0.02: rec_30_39 / rec_40p are 0.002 -> published 0 -> omitted.
    tiny = {"rec": 0.02, "rec_0_4": 0.0, "rec_5_9": 0.0, "rec_10_19": 0.01, "rec_20_29": 0.0}
    assert detect_synthetic_reception_split(tiny)
    assert synthetic_band_keys(tiny) == ("rec_0_4", "rec_5_9", "rec_10_19", "rec_20_29")
    # rec 6: an omitted rec_40p (expected 0.6) cannot be read as zero.
    big = {k: round(v * 6.0, 2) for k, v in SLEEPER_RECEPTION_BAND_SHARES.items()}
    big["rec"] = 6.0
    del big["rec_40p"]
    assert not detect_synthetic_reception_split(big)


def test_detection_does_not_mutate_the_line():
    stats = {k: round(v * 4.0, 2) for k, v in SLEEPER_RECEPTION_BAND_SHARES.items()}
    stats["rec"] = 4.0
    before = dict(stats)
    synthetic_band_keys(stats)
    assert stats == before
