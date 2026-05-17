"""Tests for the nflverse → Sleeper fallback chain in
:mod:`src.league_comparison.historical_stats`."""

from __future__ import annotations

import pytest

from src.league_comparison import historical_stats as _hs


@pytest.fixture(autouse=True)
def _reset_source_map():
    _hs._LAST_SOURCE.clear()
    yield
    _hs._LAST_SOURCE.clear()


def _row(season, week, **extras):
    """Build a stat-row stub with a real week so the regular-season
    filter doesn't drop it."""
    return {"player_id": "x", "season": season, "week": week, **extras}


def test_uses_nflverse_when_available(monkeypatch):
    """If nflverse returns rows, Sleeper must not be called and
    sources['<season>'] must be 'nflverse'."""
    sleeper_calls = {"n": 0}

    def fake_nflverse(years):
        return [_row(years[0], 1)]

    def fake_sleeper(season):
        sleeper_calls["n"] += 1
        return [_row(season, 1, sleeper_only=True)]

    monkeypatch.setattr(_hs._ingest, "fetch_weekly_stats", fake_nflverse)
    monkeypatch.setattr(_hs._sleeper_stats, "fetch_sleeper_weekly_stats", fake_sleeper)

    rows = _hs.load_season_rows(2024)
    assert rows is not None
    assert rows[0]["player_id"] == "x"
    assert sleeper_calls["n"] == 0
    assert _hs.get_source_for(2024) == "nflverse"


def test_falls_back_to_sleeper_when_nflverse_empty(monkeypatch):
    """When nflverse returns an empty list, Sleeper kicks in and the
    source map records 'sleeper'."""
    monkeypatch.setattr(_hs._ingest, "fetch_weekly_stats", lambda yrs: [])
    monkeypatch.setattr(
        _hs._sleeper_stats,
        "fetch_sleeper_weekly_stats",
        lambda s: [_row(s, 1, player_id="y")],
    )
    rows = _hs.load_season_rows(2025)
    assert rows is not None
    assert rows[0]["player_id"] == "y"
    assert _hs.get_source_for(2025) == "sleeper"


def test_falls_back_to_sleeper_when_nflverse_raises(monkeypatch):
    """A nflverse exception (network error, schema bust) shouldn't
    prevent the Sleeper fallback."""

    def fake_nflverse_raises(years):
        raise RuntimeError("nflverse connector dead")

    monkeypatch.setattr(_hs._ingest, "fetch_weekly_stats", fake_nflverse_raises)
    monkeypatch.setattr(
        _hs._sleeper_stats,
        "fetch_sleeper_weekly_stats",
        lambda s: [_row(s, 1, player_id="z")],
    )
    rows = _hs.load_season_rows(2025)
    assert rows is not None
    assert rows[0]["player_id"] == "z"
    assert _hs.get_source_for(2025) == "sleeper"


def test_returns_none_when_both_sources_empty(monkeypatch):
    """All sources empty → ``None`` (not ``[]``) so the orchestrator
    can split available vs unavailable cleanly."""
    monkeypatch.setattr(_hs._ingest, "fetch_weekly_stats", lambda yrs: [])
    monkeypatch.setattr(_hs._sleeper_stats, "fetch_sleeper_weekly_stats", lambda s: [])
    assert _hs.load_season_rows(2025) is None
    assert _hs.get_source_for(2025) is None


def test_summarize_availability_includes_sources(monkeypatch):
    """The summary must surface which sources actually fed each
    available season so the API meta block can show provenance."""
    monkeypatch.setattr(
        _hs._ingest,
        "fetch_weekly_stats",
        lambda yrs: [_row(yrs[0], 1)] if yrs[0] != 2025 else [],
    )
    monkeypatch.setattr(
        _hs._sleeper_stats,
        "fetch_sleeper_weekly_stats",
        lambda s: [_row(s, 1)] if s == 2025 else [],
    )
    seasons_map = _hs.load_all_seasons([2023, 2024, 2025])
    avail = _hs.summarize_availability(seasons_map)
    assert avail["available"] == [2023, 2024, 2025]
    assert avail["unavailable"] == []
    assert avail["sources"] == {2023: "nflverse", 2024: "nflverse", 2025: "sleeper"}


# ── Regular-season week filter ───────────────────────────────────────


def test_filter_drops_week_18_and_postseason(monkeypatch):
    """Both nflverse and Sleeper should be cut to weeks 1-17 inclusive."""
    monkeypatch.setattr(
        _hs._ingest,
        "fetch_weekly_stats",
        lambda yrs: [
            _row(yrs[0], 1, player_id="w1"),
            _row(yrs[0], 17, player_id="w17"),
            _row(yrs[0], 18, player_id="w18"),  # starter-rest week
            _row(yrs[0], 19, player_id="wpost"),  # nflverse postseason
        ],
    )
    monkeypatch.setattr(_hs._sleeper_stats, "fetch_sleeper_weekly_stats", lambda s: [])

    rows = _hs.load_season_rows(2024)
    assert rows is not None
    weeks = {r["week"] for r in rows}
    assert weeks == {1, 17}


def test_filter_drops_rows_with_missing_week(monkeypatch):
    """Defensive: a row missing the week field shouldn't crash the
    filter — just drop quietly."""
    monkeypatch.setattr(
        _hs._ingest,
        "fetch_weekly_stats",
        lambda yrs: [
            {"player_id": "good", "season": yrs[0], "week": 5},
            {"player_id": "bad", "season": yrs[0]},  # no week
            {"player_id": "string", "season": yrs[0], "week": "wat"},
        ],
    )
    monkeypatch.setattr(_hs._sleeper_stats, "fetch_sleeper_weekly_stats", lambda s: [])
    rows = _hs.load_season_rows(2024)
    assert rows is not None
    assert {r["player_id"] for r in rows} == {"good"}
