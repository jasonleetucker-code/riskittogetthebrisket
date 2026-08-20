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


# ── #802: host-native emission, and the team-entry drop ───────────────


def _host_native_fixture():
    """One WR, one team DST, one week — the minimum that shows both defects.

    ``st_tkl_solo`` is on BOTH entries under one key name, which is exactly
    why the team row must be dropped by ENTRY KIND rather than by key.
    """
    player_index = {
        "4034": {"full_name": "Return Man", "position": "WR", "gsis_id": "00-G4034"},
        "PHI": {"full_name": "Philadelphia", "position": "DEF", "gsis_id": ""},
    }
    weeks = {
        1: {
            "4034": {"rec": 4, "rec_yd": 51, "kr_yd": 88, "st_tkl_solo": 2, "rec_5_9": 2},
            "PHI": {"pts_allow": 13, "int": 2, "st_tkl_solo": 9, "kr_yd": 60},
        }
    }
    return _make_fake_fetcher(player_index, weeks)


def test_team_defense_entries_are_dropped(monkeypatch):
    """Sleeper gives a DST the position ``DEF`` — non-empty — so the position
    join alone would let it through and pay DST rules to a roster asset."""
    rows = _ss.fetch_sleeper_weekly_stats(2025, fetcher=_host_native_fixture())
    assert rows, "fixture produced no rows"
    assert all(r["player_id_sleeper"] != "PHI" for r in rows)
    assert not any("pts_allow" in r for r in rows)


def test_flag_off_still_translates_to_nflverse_names(monkeypatch):
    from src.api import feature_flags

    monkeypatch.delenv("RISKIT_FEATURE_HOST_NATIVE_SCORING", raising=False)
    feature_flags.reload()
    rows = _ss.fetch_sleeper_weekly_stats(2025, fetcher=_host_native_fixture())
    row = next(r for r in rows if r["player_id_sleeper"] == "4034")
    assert row["source"] == "nflverse"
    assert row["receptions"] == 4
    assert row["receiving_yards"] == 51
    # The champion path's loss, stated as a test rather than as prose:
    # the host published these and the nflverse vocabulary has no name
    # for them, so nothing downstream can score them.
    assert "rec_5_9" in row  # retained verbatim for debugging...
    from src.nfl_data.realized_points import sleeper_stat_line_from_row

    assert "rec_5_9" not in sleeper_stat_line_from_row(row, position="WR")  # ...but unscorable


def test_flag_on_emits_the_hosts_own_vocabulary(monkeypatch):
    from src.api import feature_flags

    monkeypatch.setenv("RISKIT_FEATURE_HOST_NATIVE_SCORING", "1")
    feature_flags.reload()
    try:
        rows = _ss.fetch_sleeper_weekly_stats(2025, fetcher=_host_native_fixture())
        row = next(r for r in rows if r["player_id_sleeper"] == "4034")
        assert row["source"] == "sleeper"
        for key in ("rec", "rec_yd", "kr_yd", "st_tkl_solo", "rec_5_9"):
            assert row[key], f"{key} lost on the host-native path"
        assert "receptions" not in row, "host-native rows must not be translated"
    finally:
        monkeypatch.delenv("RISKIT_FEATURE_HOST_NATIVE_SCORING", raising=False)
        feature_flags.reload()


def test_the_flag_changes_what_can_be_scored(monkeypatch):
    """End to end: the same real player-week, both paths, one card."""
    from src.api import feature_flags
    from src.nfl_data.realized_points import compute_weekly_points

    card = {"rec": 1.0, "rec_yd": 0.1, "kr_yd": 0.0333, "st_tkl_solo": 1.33, "rec_5_9": 0.42}

    monkeypatch.delenv("RISKIT_FEATURE_HOST_NATIVE_SCORING", raising=False)
    feature_flags.reload()
    champ_row = next(
        r
        for r in _ss.fetch_sleeper_weekly_stats(2025, fetcher=_host_native_fixture())
        if r["player_id_sleeper"] == "4034"
    )
    champ = compute_weekly_points(champ_row, card, position="WR", source=champ_row["source"])

    monkeypatch.setenv("RISKIT_FEATURE_HOST_NATIVE_SCORING", "1")
    feature_flags.reload()
    try:
        host_row = next(
            r
            for r in _ss.fetch_sleeper_weekly_stats(2025, fetcher=_host_native_fixture())
            if r["player_id_sleeper"] == "4034"
        )
        host = compute_weekly_points(host_row, card, position="WR", source=host_row["source"])
    finally:
        monkeypatch.delenv("RISKIT_FEATURE_HOST_NATIVE_SCORING", raising=False)
        feature_flags.reload()

    # Three rules are unreachable on the champion path and real on the host
    # path.  ``kr_yd`` is the one worth reading twice: #802 wired it into the
    # nflverse path from ``kickoff_return_yards``, so it scores fine there —
    # but on the SLEEPER path the host publishes it as ``kr_yd``, _FIELD_MAP
    # has no entry to rename it, and the normalizer is looking for the
    # nflverse spelling.  The category the issue was raised about is still
    # lost, on the one path that will be live when the 2026 season starts.
    assert host.fantasy_points > champ.fantasy_points
    assert host.fantasy_points - champ.fantasy_points == pytest.approx(
        2 * 1.33 + 2 * 0.42 + 88 * 0.0333, abs=1e-6
    )
    # And the champion path scored ONLY the two rules _FIELD_MAP can carry.
    assert champ.fantasy_points == pytest.approx(4 * 1.0 + 51 * 0.1, abs=1e-6)


# ── #802: an explicitly-enabled flag must fail visibly ────────────────


def test_an_unresolvable_flag_raises_when_explicitly_requested(monkeypatch):
    """The operator asked for the challenger; refusing loudly is the only
    honest answer.

    The old behaviour swallowed every exception and returned False, so a box
    where the registry could not be imported scored every season through the
    lossy _FIELD_MAP round trip while the operator believed host-native
    scoring was active — publishing one quantity under the belief it was
    another, with nothing saying so.
    """
    import builtins

    monkeypatch.setenv("RISKIT_FEATURE_HOST_NATIVE_SCORING", "1")
    real_import = builtins.__import__

    def _boom(name, *a, **k):
        if name == "src.api.feature_flags":
            raise ImportError("registry unavailable")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _boom)
    with pytest.raises(RuntimeError, match="RISKIT_FEATURE_HOST_NATIVE_SCORING"):
        _ss._host_native_enabled()


@pytest.mark.parametrize("override", ["1", "true", "YES", "on"])
def test_every_truthy_spelling_counts_as_an_explicit_request(monkeypatch, override):
    """The env parser accepts four spellings; all four are a request."""
    import builtins

    monkeypatch.setenv("RISKIT_FEATURE_HOST_NATIVE_SCORING", override)
    real_import = builtins.__import__

    def _boom(name, *a, **k):
        if name == "src.api.feature_flags":
            raise ImportError("registry unavailable")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _boom)
    with pytest.raises(RuntimeError):
        _ss._host_native_enabled()


@pytest.mark.parametrize("override", [None, "0", "false", "off", ""])
def test_an_unresolvable_flag_stays_fail_closed_when_not_requested(monkeypatch, override):
    """Nobody asked for the challenger, so the champion path IS the right
    answer — raising here would take down a working install over an
    unused feature."""
    import builtins

    if override is None:
        monkeypatch.delenv("RISKIT_FEATURE_HOST_NATIVE_SCORING", raising=False)
    else:
        monkeypatch.setenv("RISKIT_FEATURE_HOST_NATIVE_SCORING", override)
    real_import = builtins.__import__

    def _boom(name, *a, **k):
        if name == "src.api.feature_flags":
            raise ImportError("registry unavailable")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _boom)
    assert _ss._host_native_enabled() is False


def test_a_resolvable_flag_never_raises(monkeypatch):
    """Non-vacuity: the guard must not fire on the normal path."""
    from src.api import feature_flags

    monkeypatch.delenv("RISKIT_FEATURE_HOST_NATIVE_SCORING", raising=False)
    feature_flags.reload()
    assert _ss._host_native_enabled() is False
    monkeypatch.setenv("RISKIT_FEATURE_HOST_NATIVE_SCORING", "1")
    feature_flags.reload()
    try:
        assert _ss._host_native_enabled() is True
    finally:
        monkeypatch.delenv("RISKIT_FEATURE_HOST_NATIVE_SCORING", raising=False)
        feature_flags.reload()
