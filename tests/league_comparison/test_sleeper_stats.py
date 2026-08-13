"""Tests for the Sleeper-stats fallback adapter.

The HTTP boundary is mocked at every test entrypoint via the
``fetcher`` parameter on the public functions, so these tests run
fully offline.
"""

from __future__ import annotations

import urllib.error

import pytest

from src.league_comparison import sleeper_stats as _ss


# ── Field translation ────────────────────────────────────────────────


def test_translate_stats_maps_offense_keys():
    """Sleeper short keys → nflverse long keys for offense scoring."""
    out = _ss._translate_stats(
        {
            "pass_yd": 280,
            "pass_td": 2,
            "pass_int": 1,
            "rush_yd": 35,
            "rush_td": 1,
            "rec": 5,
            "rec_yd": 60,
            "rec_td": 1,
            "fum_lost": 0,
        }
    )
    assert out["passing_yards"] == 280
    assert out["passing_tds"] == 2
    assert out["interceptions"] == 1
    assert out["rushing_yards"] == 35
    assert out["rushing_tds"] == 1
    assert out["receptions"] == 5
    assert out["receiving_yards"] == 60
    assert out["receiving_tds"] == 1
    assert out["fumbles_lost"] == 0


def test_translate_stats_maps_idp_keys():
    """Sleeper idp_* → nflverse def_* for the realized-points engine."""
    out = _ss._translate_stats(
        {
            "idp_tkl": 6,
            "idp_tkl_solo": 4,
            "idp_tkl_ast": 2,
            "idp_sack": 1,
            "idp_qb_hit": 1,
            "idp_int": 1,
        }
    )
    # ``idp_tkl`` must NOT become ``def_tackles``.  Sleeper's idp_tkl is
    # COMBINED; ``realized_points._tackle_view`` reads a published
    # ``def_tackles`` as the pre-2025 gamebook SOLO total, so the old
    # mapping wrote combined into the solo slot and inflated both.
    # Combined is derived from solo + assists, which map correctly.
    assert "def_tackles" not in out
    assert out["def_tackles_solo"] == 4
    assert out["def_tackle_assists"] == 2
    assert out["def_sacks"] == 1
    assert out["def_qb_hits"] == 1
    assert out["def_interceptions"] == 1


def test_translate_stats_passes_through_unmapped_keys():
    """An unknown Sleeper key should round-trip with the same name —
    realized-points ignores it, but it stays available for debugging."""
    out = _ss._translate_stats({"some_random_key": 42, "pass_yd": 300})
    assert out["some_random_key"] == 42
    assert out["passing_yards"] == 300


def test_translate_stats_skips_non_numeric():
    """Sleeper occasionally returns null / strings — those should be
    dropped, not raise."""
    out = _ss._translate_stats(
        {
            "pass_yd": 250,
            "weather_note": "rain",
            "rush_yd": None,
        }
    )
    assert "passing_yards" in out
    assert "weather_note" not in out
    assert "rushing_yards" not in out


# ── fetch_sleeper_weekly_stats end-to-end (mocked HTTP) ───────────────


def _make_fake_fetcher(player_index, weeks):
    """Build a fake fetcher that returns a player index for the
    /players/nfl URL and per-week stat dicts for /stats/* URLs.

    ``weeks`` is ``{week: stats_dict}``; missing weeks raise 404.
    """

    def fetcher(url):
        if "/players/nfl" in url:
            return player_index
        # Parse "...stats/nfl/regular/{season}/{week}"
        parts = url.rstrip("/").split("/")
        try:
            week = int(parts[-1])
        except ValueError:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if week not in weeks:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return weeks[week]

    return fetcher


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Redirect the on-disk cache to a tmp dir so tests don't bleed
    into each other or read real cached data."""
    monkeypatch.setattr(
        "src.nfl_data.cache._default_cache_dir",
        lambda: tmp_path / "nfl_data_cache",
    )
    yield


def test_fetch_sleeper_weekly_stats_returns_nflverse_shaped_rows():
    player_index = {
        "100": {"full_name": "Test QB", "position": "QB", "gsis_id": "00-G100"},
        "200": {"full_name": "Test RB", "position": "RB", "gsis_id": "00-G200"},
    }
    weeks = {
        1: {
            "100": {"pass_yd": 300, "pass_td": 3, "pass_int": 0},
            "200": {"rush_yd": 80, "rush_td": 1, "rec": 4, "rec_yd": 30},
        },
        2: {
            "100": {"pass_yd": 220, "pass_td": 1},
            "200": {"rush_yd": 60, "rush_td": 0, "rec": 5, "rec_yd": 40},
        },
    }
    fetcher = _make_fake_fetcher(player_index, weeks)
    rows = _ss.fetch_sleeper_weekly_stats(2025, fetcher=fetcher)

    # Two players × two weeks = 4 rows.
    assert len(rows) == 4
    qb_rows = [r for r in rows if r["position"] == "QB"]
    rb_rows = [r for r in rows if r["position"] == "RB"]
    assert len(qb_rows) == 2 and len(rb_rows) == 2

    # Shape sanity: nflverse field names present and sleeper keys retained.
    sample = qb_rows[0]
    assert sample["season"] == 2025
    assert sample["week"] in (1, 2)
    assert sample["player_id"] == "00-G100"  # gsis_id is canonical
    assert sample["player_id_gsis"] == "00-G100"
    assert sample["player_id_sleeper"] == "100"
    assert sample["player_name"] == "Test QB"
    assert "passing_yards" in sample  # translated
    assert "pass_yd" in sample  # original retained


def test_fetch_sleeper_weekly_stats_skips_players_without_position():
    """A Sleeper player_id missing from /players/nfl (or with no
    position) should drop rather than crash or pollute output."""
    player_index = {
        "100": {"full_name": "Has Position", "position": "QB"},
        # 200 is intentionally missing from index.
    }
    weeks = {
        1: {
            "100": {"pass_yd": 300, "pass_td": 2},
            "200": {"rush_yd": 80, "rush_td": 1},
        },
    }
    fetcher = _make_fake_fetcher(player_index, weeks)
    rows = _ss.fetch_sleeper_weekly_stats(2025, fetcher=fetcher)
    assert len(rows) == 1
    assert rows[0]["position"] == "QB"


def test_fetch_sleeper_weekly_stats_handles_missing_weeks():
    """A 404 on some weeks shouldn't tank the whole season — earlier
    weeks should still come through."""
    player_index = {"100": {"full_name": "Test QB", "position": "QB"}}
    # Only weeks 1, 3, 5 have data; the rest return 404.
    weeks = {
        1: {"100": {"pass_yd": 200, "pass_td": 1}},
        3: {"100": {"pass_yd": 250, "pass_td": 2}},
        5: {"100": {"pass_yd": 300, "pass_td": 3}},
    }
    fetcher = _make_fake_fetcher(player_index, weeks)
    rows = _ss.fetch_sleeper_weekly_stats(2025, fetcher=fetcher)
    assert len(rows) == 3
    assert sorted(r["week"] for r in rows) == [1, 3, 5]


def test_fetch_sleeper_weekly_stats_uses_sleeper_pid_when_no_gsis():
    """Players without a gsis_id should fall back to Sleeper's pid as
    the canonical player_id so the season-bucket key is still stable."""
    player_index = {
        "999": {"full_name": "Rookie No GSIS", "position": "WR"},
    }
    weeks = {1: {"999": {"rec": 6, "rec_yd": 80, "rec_td": 1}}}
    fetcher = _make_fake_fetcher(player_index, weeks)
    rows = _ss.fetch_sleeper_weekly_stats(2025, fetcher=fetcher)
    assert len(rows) == 1
    assert rows[0]["player_id"] == "999"
    assert rows[0]["player_id_gsis"] == ""


def test_fetch_sleeper_weekly_stats_returns_empty_when_index_empty():
    """If /players/nfl is unreachable / empty, we shouldn't even try
    to fetch weekly stats — fail fast with an empty result."""
    weeks_called = {"n": 0}

    def fetcher(url):
        if "/players/nfl" in url:
            return {}
        weeks_called["n"] += 1
        return {}

    rows = _ss.fetch_sleeper_weekly_stats(2025, fetcher=fetcher)
    assert rows == []
    # Should have short-circuited before attempting any week fetches.
    assert weeks_called["n"] == 0
