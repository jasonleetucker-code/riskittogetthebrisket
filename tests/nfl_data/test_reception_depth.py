"""Tests for per-player reception-depth histograms.

The band mapping is the whole point of this module, so most of these
test boundaries rather than plumbing. Sleeper's bands are
0-4 / 5-9 / 10-19 / 20-29 / 30-39 / 40+, and an off-by-one at any edge
silently moves catches between bands worth 0.25 and 2.00 a piece.

``test_the_column_guard_fires_on_a_renamed_schema`` is the §6.15 guard:
nflverse renamed six weekly-stat columns in 2025 and the breakage was
invisible for a season because a missing column reads as a zero. This
module raises instead, and the test proves it raises.
"""

from __future__ import annotations

import json

import pytest

from src.nfl_data.reception_depth import (
    BAND_KEYS,
    band_for_yards,
    load_reception_depth,
    persist_reception_depth,
    summarise_histogram,
)

_HEADER = (
    "season,week,season_type,complete_pass,receiver_player_id,"
    "receiver_player_name,receiving_yards,yards_gained"
)


def _play(pid, name, yards, *, complete=1, week=1, stype="REG", gained=None):
    return (
        f"2025,{week},{stype},{complete},{pid},{name},{yards},"
        f"{yards if gained is None else gained}"
    )


def _lines(*plays):
    def _src(_season):
        return iter([_HEADER, *plays])

    return _src


# ── Band boundaries ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "yards,expected",
    [
        (0, "rec_0_4"),
        (4, "rec_0_4"),
        (4.9, "rec_0_4"),
        (5, "rec_5_9"),
        (9, "rec_5_9"),
        (10, "rec_10_19"),
        (19, "rec_10_19"),
        (20, "rec_20_29"),
        (29, "rec_20_29"),
        (30, "rec_30_39"),
        (39, "rec_30_39"),
        (40, "rec_40p"),
        (99, "rec_40p"),
    ],
)
def test_every_band_boundary(yards, expected):
    """Each edge is worth real money: a catch that slides from
    rec_10_19 (0.75) to rec_20_29 (1.00) is a 33% per-catch swing."""
    assert band_for_yards(yards) == expected


@pytest.mark.parametrize("yards", [-1, -2, -6, -0.5])
def test_a_lost_yardage_catch_belongs_to_no_band(yards):
    """Measured against the host, not assumed.

    This asserted ``rec_0_4`` until 2026-08-18, when it was checked
    against Sleeper's own weekly dumps for 2025 REG weeks 1, 3, 5, 8, 11,
    14 and 17. Week 14: play-by-play has 537 completed passes, the host
    reports ``rec`` 537 and bands totalling 523, and the difference is
    exactly that week's 14 negative-yard receptions. Aaron Rodgers is
    credited ``rec: 1`` / ``rec_yd: -9`` with no ``rec_0_4`` key at all.

    Excluding them makes all six bands reconcile to the host exactly on
    every sampled week; including them paid a band the host does not pay,
    to two quarterbacks among others.
    """
    assert band_for_yards(yards) is None


def test_the_bands_partition_without_gaps_or_overlap():
    """Sweeping every integer 0..60 must land in exactly one band, and
    the sequence must be monotone — a gap would silently drop catches."""
    seen = [band_for_yards(y) for y in range(0, 61)]
    assert set(seen) == set(BAND_KEYS)
    order = {k: i for i, k in enumerate(BAND_KEYS)}
    assert all(order[a] <= order[b] for a, b in zip(seen, seen[1:]))


# ── Accumulation ─────────────────────────────────────────────────────


def test_a_players_catches_land_in_the_right_bands(tmp_path):
    src = _lines(
        _play("00-1", "Deep.Guy", 45),
        _play("00-1", "Deep.Guy", 12),
        _play("00-1", "Deep.Guy", 3),
    )
    persist_reception_depth([2025], depth_dir=tmp_path, _line_source=src)
    d = load_reception_depth(2025, depth_dir=tmp_path)
    bands = d["players"]["00-1"]["bands"]
    assert bands["rec_40p"] == 1
    assert bands["rec_10_19"] == 1
    assert bands["rec_0_4"] == 1
    assert d["players"]["00-1"]["receptions"] == 3
    assert d["players"]["00-1"]["receivingYards"] == pytest.approx(60.0)


def test_incomplete_passes_are_not_receptions(tmp_path):
    src = _lines(
        _play("00-1", "A", 20),
        _play("00-1", "A", 30, complete=0),
    )
    persist_reception_depth([2025], depth_dir=tmp_path, _line_source=src)
    d = load_reception_depth(2025, depth_dir=tmp_path)
    assert d["players"]["00-1"]["receptions"] == 1


def test_plays_without_a_receiver_id_are_skipped(tmp_path):
    src = _lines(_play("", "", 20), _play("00-1", "A", 8))
    persist_reception_depth([2025], depth_dir=tmp_path, _line_source=src)
    d = load_reception_depth(2025, depth_dir=tmp_path)
    assert list(d["players"]) == ["00-1"]


def test_receiving_yards_wins_over_yards_gained(tmp_path):
    """They diverge on laterals, where yards_gained includes yardage the
    receiver was never credited with. Bucketing on the wrong one would
    promote a short catch into a long band."""
    src = _lines(_play("00-1", "A", 4, gained=48))
    persist_reception_depth([2025], depth_dir=tmp_path, _line_source=src)
    d = load_reception_depth(2025, depth_dir=tmp_path)
    assert d["players"]["00-1"]["bands"]["rec_0_4"] == 1
    assert d["players"]["00-1"]["bands"]["rec_40p"] == 0


def test_postseason_is_excluded_by_default(tmp_path):
    """Fantasy regular seasons end before the NFL playoffs, so playoff
    catches are not part of the scoring sample."""
    src = _lines(_play("00-1", "A", 8), _play("00-1", "A", 44, week=20, stype="POST"))
    persist_reception_depth([2025], depth_dir=tmp_path, _line_source=src)
    d = load_reception_depth(2025, depth_dir=tmp_path)
    assert d["players"]["00-1"]["receptions"] == 1
    assert d["players"]["00-1"]["bands"]["rec_40p"] == 0


def test_postseason_can_be_opted_in(tmp_path):
    src = _lines(_play("00-1", "A", 8), _play("00-1", "A", 44, week=20, stype="POST"))
    persist_reception_depth(
        [2025], depth_dir=tmp_path, season_types=("REG", "POST"), _line_source=src
    )
    d = load_reception_depth(2025, depth_dir=tmp_path)
    assert d["players"]["00-1"]["receptions"] == 2


# ── The schema guard ─────────────────────────────────────────────────


def test_the_column_guard_fires_on_a_renamed_schema(tmp_path):
    """§6.15. nflverse renamed six weekly-stat columns in 2025 and the
    break went unnoticed for a season because a missing column reads as
    a zero — indistinguishable from 'this player caught nothing'.

    A renamed pbp column must therefore RAISE, not return an empty
    histogram. ``persist_reception_depth`` catches it and logs, so the
    observable outcome is 'no file written' rather than 'a file full of
    zeroes presented as a measurement'.
    """
    from src.nfl_data.reception_depth import _iter_receptions

    renamed = "season,week,season_type,made_the_catch,catcher_id,name,receiving_yards"
    with pytest.raises(ValueError, match="missing expected columns"):
        list(_iter_receptions(iter([renamed, "2025,1,REG,1,00-1,A,12"])))


def test_a_renamed_schema_writes_no_file_rather_than_an_empty_one(tmp_path):
    """The caller-visible half of the guard above. A histogram of zeroes
    would be consumed downstream as a real measurement."""
    renamed = "season,week,season_type,made_the_catch,catcher_id,name,receiving_yards"

    def _src(_season):
        return iter([renamed, "2025,1,REG,1,00-1,A,12"])

    result = persist_reception_depth([2025], depth_dir=tmp_path, _line_source=_src)
    assert result["seasons"] == []
    assert load_reception_depth(2025, depth_dir=tmp_path) is None


def test_a_missing_yardage_column_also_raises():
    from src.nfl_data.reception_depth import _iter_receptions

    no_yards = "season,week,season_type,complete_pass,receiver_player_id,receiver_player_name"
    with pytest.raises(ValueError, match="neither receiving_yards nor yards_gained"):
        list(_iter_receptions(iter([no_yards, "2025,1,REG,1,00-1,A"])))


# ── Summary shape ────────────────────────────────────────────────────


def test_shares_sum_to_one_and_describe_shape_not_volume():
    """Two receivers with the same shape and different volume must read
    as the same FIT — volume is priced separately by whatever consumes
    this."""
    small = summarise_histogram({"rec_0_4": 1, "rec_40p": 1})
    large = summarise_histogram({"rec_0_4": 50, "rec_40p": 50})
    assert small["shares"] == large["shares"]
    assert sum(small["shares"].values()) == pytest.approx(1.0)
    assert small["receptions"] == 2
    assert large["receptions"] == 100


def test_an_empty_histogram_is_zeroes_not_a_divide_by_zero():
    s = summarise_histogram({})
    assert s["receptions"] == 0
    assert all(v == 0.0 for v in s["shares"].values())


def test_rerunning_replaces_the_season_rather_than_appending(tmp_path):
    persist_reception_depth([2025], depth_dir=tmp_path, _line_source=_lines(_play("00-1", "A", 8)))
    persist_reception_depth(
        [2025],
        depth_dir=tmp_path,
        _line_source=_lines(_play("00-1", "A", 8), _play("00-1", "A", 44)),
    )
    from src.nfl_data.reception_depth import depth_path

    text = depth_path(2025, depth_dir=tmp_path).read_text(encoding="utf-8").strip()
    assert len(text.splitlines()) == 1
    assert json.loads(text)["players"]["00-1"]["receptions"] == 2


def test_load_of_a_missing_season_is_none_not_an_error(tmp_path):
    assert load_reception_depth(1999, depth_dir=tmp_path) is None
