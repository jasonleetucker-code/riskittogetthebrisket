"""Tests for the Sleeper scoring fetcher's caching + parsing behavior."""
from __future__ import annotations

import json

import pytest

from src.league_comparison import sleeper_scoring as ss


_RESPONSE = {
    "league_id": "L1",
    "name": "Test League",
    "season": "2025",
    "season_type": "regular",
    "scoring_settings": {
        "pass_yd": 0.04,
        "pass_td": 5,
        "rec": 0.75,
        "bonus_rec_te": 0.38,
    },
}


@pytest.fixture(autouse=True)
def clean_cache():
    ss.evict()
    yield
    ss.evict()


def test_fetch_parses_scoring_settings(monkeypatch):
    monkeypatch.setattr(ss, "_fetch_raw", lambda lid: _RESPONSE)
    info = ss.fetch_league_scoring("L1")
    assert info.league_id == "L1"
    assert info.name == "Test League"
    assert info.season == "2025"
    assert info.scoring_settings == {
        "pass_yd": 0.04, "pass_td": 5.0, "rec": 0.75, "bonus_rec_te": 0.38,
    }
    assert len(info.scoring_hash) == 12


def test_fetch_caches_within_ttl(monkeypatch):
    calls = {"n": 0}

    def counting(lid):
        calls["n"] += 1
        return _RESPONSE

    monkeypatch.setattr(ss, "_fetch_raw", counting)
    ss.fetch_league_scoring("L1")
    ss.fetch_league_scoring("L1")
    ss.fetch_league_scoring("L1")
    assert calls["n"] == 1


def test_refresh_bypasses_cache(monkeypatch):
    calls = {"n": 0}

    def counting(lid):
        calls["n"] += 1
        return _RESPONSE

    monkeypatch.setattr(ss, "_fetch_raw", counting)
    ss.fetch_league_scoring("L1")
    ss.fetch_league_scoring("L1", refresh=True)
    assert calls["n"] == 2


def test_two_leagues_cached_separately(monkeypatch):
    calls = {"n": 0}

    def counting(lid):
        calls["n"] += 1
        return {**_RESPONSE, "league_id": lid, "name": f"League {lid}"}

    monkeypatch.setattr(ss, "_fetch_raw", counting)
    a = ss.fetch_league_scoring("A")
    b = ss.fetch_league_scoring("B")
    assert a.name == "League A"
    assert b.name == "League B"
    # Repeat A → should hit cache, not re-fetch
    ss.fetch_league_scoring("A")
    assert calls["n"] == 2


def test_missing_league_id_raises():
    with pytest.raises(ValueError):
        ss.fetch_league_scoring("")


def test_malformed_response_raises(monkeypatch):
    monkeypatch.setattr(ss, "_fetch_raw", lambda lid: {"name": "no scoring"})
    with pytest.raises(ValueError):
        ss.fetch_league_scoring("L1")


def test_scoring_hash_stable_across_key_order(monkeypatch):
    """Two equivalent dicts with different key insertion orders must
    produce the same scoring_hash so cache keys are stable."""
    monkeypatch.setattr(ss, "_fetch_raw", lambda lid: _RESPONSE)
    info_a = ss.fetch_league_scoring("L1")
    ss.evict()

    reordered = {
        "name": "Test League",
        "season": "2025",
        "season_type": "regular",
        "scoring_settings": {
            "rec": 0.75,
            "pass_td": 5,
            "bonus_rec_te": 0.38,
            "pass_yd": 0.04,
        },
    }
    monkeypatch.setattr(ss, "_fetch_raw", lambda lid: reordered)
    info_b = ss.fetch_league_scoring("L1")
    assert info_a.scoring_hash == info_b.scoring_hash
