"""The snap-counts join, and the two ways it silently loses data.

PR #591 left ``snap_count`` / ``snap_pct`` unjoined on the stated
grounds that a half-join writes "no snaps played" where it means "not
fetched".  That objection is correct and these tests are what answer it:
absent and zero must stay structurally distinct, all the way through to
the flat rows the usage engine reads.

The join itself has one non-obvious failure mode, measured live
2026-07-27 rather than reasoned about:

* the weekly-stats release spells playoffs ``POST``
* the snap-counts release spells them ``WC`` / ``DIV`` / ``CON`` / ``SB``

An equality join on those strings matches all 18 regular-season weeks
and **no** playoff week — 882 of 19,421 2025 rows — while looking
completely healthy, because the regular season is 95% of the file and
nothing raises.  ``test_a_playoff_week_joins_despite_the_two_releases_disagreeing``
is the guard; it fails against a raw-string join.
"""

from __future__ import annotations

import json

from src.nfl_data import actuals_store
from src.nfl_data.usage_windows import build_rolling_windows


def _stat_row(**over) -> dict:
    row = {
        "player_id": "00-0036322",
        "player_name": "C.Lamb",
        "player_display_name": "CeeDee Lamb",
        "position": "WR",
        "team": "DAL",
        "season": 2025,
        "week": 1,
        "season_type": "REG",
        "targets": 10,
        "receptions": 7,
        "receiving_yards": 92,
        "receiving_tds": 1,
        "carries": 1,
        "rushing_yards": 4,
    }
    row.update(over)
    return row


def _snap_row(**over) -> dict:
    row = {
        "pfr_player_id": "LambCe00",
        "player": "CeeDee Lamb",
        "position": "WR",
        "team": "DAL",
        "season": 2025,
        "week": 1,
        "game_type": "REG",
        "offense_snaps": 60,
        "offense_pct": 0.92,
        "defense_snaps": 0,
        "defense_pct": 0.0,
        "st_snaps": 2,
        "st_pct": 0.08,
    }
    row.update(over)
    return row


def _id_map(pairs=(("LambCe00", "00-0036322"),)) -> list[dict]:
    return [{"pfr_id": p, "gsis_id": g} for p, g in pairs]


def _persist(tmp_path, stat_rows, snap_rows, id_rows=None):
    out = tmp_path / "actuals"
    actuals_store.persist_weekly_actuals(
        [2025],
        actuals_dir=out,
        cache_dir=tmp_path / "cache",
        _offensive_provider=lambda _y: list(stat_rows),
        _defensive_provider=lambda _y: [],
        _snap_provider=lambda _y: list(snap_rows),
        _id_map_provider=lambda: _id_map() if id_rows is None else list(id_rows),
    )
    return out


# ── The index ────────────────────────────────────────────────────────


def test_the_index_joins_pfr_ids_onto_gsis(tmp_path):
    index, report = actuals_store.build_snap_index(
        2025,
        cache_dir=tmp_path / "cache",
        _snap_provider=lambda _y: [_snap_row()],
        _id_map_provider=_id_map,
    )
    assert list(index) == [("00-0036322", 1, "REG")]
    assert index[("00-0036322", 1, "REG")]["offensePct"] == 0.92
    assert report["indexed"] == 1
    assert report["unjoinableSnapRows"] == 0


def test_a_playoff_week_joins_despite_the_two_releases_disagreeing(tmp_path):
    """The whole point.  ``game_type: "WC"`` must land on the same key a
    stat row spelling ``season_type: "POST"`` produces.

    Asserting the KEY rather than just "the index is non-empty" is
    deliberate — an index that keyed playoff snaps under ``"WC"`` would
    also be non-empty, and would then join to nothing downstream.
    """
    index, _ = actuals_store.build_snap_index(
        2025,
        cache_dir=tmp_path / "cache",
        _snap_provider=lambda _y: [
            _snap_row(week=19, game_type="WC"),
            _snap_row(week=22, game_type="SB"),
        ],
        _id_map_provider=_id_map,
    )
    assert set(index) == {("00-0036322", 19, "POST"), ("00-0036322", 22, "POST")}


def test_snap_rows_whose_pfr_id_is_not_in_the_cross_walk_are_counted(tmp_path):
    """Measured live: 56 of 26,612 2025 rows across 8 players.  A join
    that dropped them silently would report 100% coverage of the rows it
    happened to understand."""
    index, report = actuals_store.build_snap_index(
        2025,
        cache_dir=tmp_path / "cache",
        _snap_provider=lambda _y: [_snap_row(), _snap_row(pfr_player_id="GhostXx99")],
        _id_map_provider=_id_map,
    )
    assert report["indexed"] == 1
    assert report["unjoinableSnapRows"] == 1
    assert report["unjoinablePlayers"] == 1
    assert len(index) == 1


def test_an_empty_cross_walk_yields_an_empty_index_not_a_zeroed_one(tmp_path):
    """If ``players.csv`` fails, every snap row is unjoinable.  The
    honest result is nothing indexed — which makes every ``snaps`` block
    ``None`` downstream — not a set of zeros that reads as "nobody
    played"."""
    index, report = actuals_store.build_snap_index(
        2025,
        cache_dir=tmp_path / "cache",
        _snap_provider=lambda _y: [_snap_row(), _snap_row(pfr_player_id="OtherXx01")],
        _id_map_provider=lambda: [],
    )
    assert index == {}
    assert report["crossWalkPairs"] == 0
    assert report["unjoinableSnapRows"] == 2


# ── Absent vs zero, end to end ───────────────────────────────────────


def test_a_joined_week_stores_measured_snaps(tmp_path):
    out = _persist(tmp_path, [_stat_row()], [_snap_row()])
    entry = json.loads(
        actuals_store.season_path(2025, actuals_dir=out).read_text(encoding="utf-8").strip()
    )
    snaps = entry["players"]["00-0036322"]["snaps"]
    assert snaps["offense"] == 60.0
    assert snaps["offensePct"] == 0.92
    # A real measured zero — he played no defense, and that is a fact,
    # not a gap.
    assert snaps["defense"] == 0.0


def test_an_unjoined_week_stores_none_and_never_zero(tmp_path):
    """The distinction PR #591 refused to blur.  ``None`` here means the
    snap release had nothing for this player-week; a stored ``0.0``
    would assert he dressed and took no snaps."""
    out = _persist(tmp_path, [_stat_row()], [], id_rows=[])
    entry = json.loads(
        actuals_store.season_path(2025, actuals_dir=out).read_text(encoding="utf-8").strip()
    )
    assert entry["players"]["00-0036322"]["snaps"] is None


def test_a_player_with_stats_but_no_snap_row_stays_none(tmp_path):
    """The index is populated — so this is not "the fetch failed" — but
    this particular player-week is absent from it.  Still unknown, still
    not zero."""
    out = _persist(
        tmp_path,
        [_stat_row(), _stat_row(player_id="00-0099999", player_name="N.Obody", week=1)],
        [_snap_row()],
    )
    entry = json.loads(
        actuals_store.season_path(2025, actuals_dir=out).read_text(encoding="utf-8").strip()
    )
    assert entry["players"]["00-0036322"]["snaps"] is not None
    assert entry["players"]["00-0099999"]["snaps"] is None


# ── The flat adapter the usage engine reads ──────────────────────────


def test_usage_rows_expose_snap_pct_as_none_when_unjoined(tmp_path):
    out = _persist(tmp_path, [_stat_row()], [], id_rows=[])
    rows = actuals_store.usage_stat_rows(2025, actuals_dir=out)
    assert len(rows) == 1
    assert rows[0]["snap_pct"] is None, "0.0 here would read as 'benched'"
    assert rows[0]["targets"] == 10.0


def test_usage_rows_pick_the_dominant_unit(tmp_path):
    """A player who took 8 offensive snaps on trick plays and 55 on
    defence is a defender.  Reporting the offensive percentage — or both
    — would misfile him for every consumer downstream."""
    out = _persist(
        tmp_path,
        [_stat_row(position="LB", carries=1, targets=0)],
        [
            _snap_row(
                offense_snaps=8,
                offense_pct=0.12,
                defense_snaps=55,
                defense_pct=0.85,
            )
        ],
    )
    row = actuals_store.usage_stat_rows(2025, actuals_dir=out)[0]
    assert row["snapUnit"] == "defense"
    assert row["snap_pct"] == 0.85


def test_usage_rows_are_regular_season_only_by_default(tmp_path):
    out = _persist(
        tmp_path,
        [_stat_row(), _stat_row(week=19, season_type="POST")],
        [_snap_row(), _snap_row(week=19, game_type="WC")],
    )
    assert [r["week"] for r in actuals_store.usage_stat_rows(2025, actuals_dir=out)] == [1]
    both = actuals_store.usage_stat_rows(2025, actuals_dir=out, season_types=None)
    assert [r["week"] for r in both] == [1, 19]
    # And the playoff week's snaps did join — this is the normalisation
    # guard again, now observed through the public read path.
    assert both[1]["snap_pct"] == 0.92


def test_the_flat_rows_actually_drive_the_rolling_window(tmp_path):
    """Non-vacuity.  ``build_rolling_windows`` tolerates missing keys and
    returns zeros for everything, so a shape mismatch between this
    adapter and that function would produce a full-length, entirely
    useless result rather than an error.

    Five weeks of a stable 90% snap share followed by a collapse to 20%
    must show up as a strongly negative z-score.
    """
    stats, snaps = [], []
    for week, pct in enumerate([0.90, 0.91, 0.89, 0.90, 0.20], start=1):
        stats.append(_stat_row(week=week))
        snaps.append(_snap_row(week=week, offense_snaps=int(pct * 65), offense_pct=pct))
    out = _persist(tmp_path, stats, snaps)

    rows = actuals_store.usage_stat_rows(2025, actuals_dir=out)
    assert [r["snap_pct"] for r in rows] == [0.90, 0.91, 0.89, 0.90, 0.20]

    windows = build_rolling_windows(rows)
    assert len(windows) == 5
    final = windows[-1]
    assert final.week == 5
    assert final.snap_pct_mean > 0.85, "the prior four weeks were a real starter workload"
    assert final.snap_pct_z is not None
    assert final.snap_pct_z < -2.0, "a 90%->20% collapse must clear the SELL threshold"
