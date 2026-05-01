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


def test_uses_nflverse_when_available(monkeypatch):
    """If nflverse returns rows, Sleeper must not be called and
    sources['<season>'] must be 'nflverse'."""
    sleeper_calls = {"n": 0}

    def fake_nflverse(years):
        return [{"player_id": "x", "season": years[0], "week": 1}]

    def fake_sleeper(season):
        sleeper_calls["n"] += 1
        return [{"sleeper_only": True}]

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
        _hs._sleeper_stats, "fetch_sleeper_weekly_stats",
        lambda s: [{"player_id": "y", "season": s, "week": 1}],
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
        _hs._sleeper_stats, "fetch_sleeper_weekly_stats",
        lambda s: [{"player_id": "z", "season": s, "week": 1}],
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
        _hs._ingest, "fetch_weekly_stats",
        lambda yrs: [{"x": 1}] if yrs[0] != 2025 else [],
    )
    monkeypatch.setattr(
        _hs._sleeper_stats, "fetch_sleeper_weekly_stats",
        lambda s: [{"x": 1}] if s == 2025 else [],
    )
    seasons_map = _hs.load_all_seasons([2023, 2024, 2025])
    avail = _hs.summarize_availability(seasons_map)
    assert avail["available"] == [2023, 2024, 2025]
    assert avail["unavailable"] == []
    assert avail["sources"] == {2023: "nflverse", 2024: "nflverse", 2025: "sleeper"}
