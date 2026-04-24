"""Tests for the ESPN injury feed parser + signal diff."""
from __future__ import annotations

import io
import json

import pytest

from src.api import feature_flags
from src.nfl_data import injury_feed


@pytest.fixture(autouse=True)
def _flags():
    feature_flags.reload()
    yield
    feature_flags.reload()


def _sample_payload():
    """Mimics ESPN's /injuries response shape."""
    return {
        "injuries": [
            {
                "team": {"abbreviation": "BUF"},
                "injuries": [
                    {
                        "athlete": {
                            "id": "3918298",
                            "displayName": "Josh Allen",
                            "position": {"abbreviation": "QB"},
                        },
                        "status": "Questionable",
                        "details": {
                            "type": "Knee",
                            "location": "Knee",
                            "returnDate": "2026-11-15",
                        },
                        "date": "2026-11-10T00:00:00Z",
                        "shortComment": "Limited in practice",
                    },
                    {
                        "athlete": {
                            "id": "4242",
                            "displayName": "Healthy Guy",
                            "position": {"abbreviation": "RB"},
                        },
                        "status": "Probable",  # not in ACTIVE_STATUSES after normalize? Let's check.
                        "details": {"type": "Ankle"},
                        "date": "2026-11-10T00:00:00Z",
                    },
                ],
            },
            {
                "team": {"abbreviation": "SF"},
                "injuries": [
                    {
                        "athlete": {
                            "id": "5555",
                            "displayName": "Out Guy",
                            "position": {"abbreviation": "WR"},
                        },
                        "status": "Out",
                        "details": {"type": "Hamstring", "returnDate": "Unknown"},
                        "date": "2026-11-09T00:00:00Z",
                    }
                ],
            },
        ]
    }


def test_flag_off_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("RISKIT_FEATURE_ESPN_INJURY_FEED", "0")
    feature_flags.reload()
    # No network call: opener should never be invoked.
    calls = []
    def opener(req, timeout=None):
        calls.append(req)
        return io.BytesIO(b"{}")
    out = injury_feed.fetch_injuries(_url_opener=opener, cache_dir=tmp_path)
    assert out == []
    assert calls == []


def test_flag_on_parses_and_caches(monkeypatch, tmp_path):
    monkeypatch.setenv("RISKIT_FEATURE_ESPN_INJURY_FEED", "1")
    feature_flags.reload()
    calls = []
    def opener(req, timeout=None):
        calls.append(req)
        return io.BytesIO(json.dumps(_sample_payload()).encode("utf-8"))
    out = injury_feed.fetch_injuries(_url_opener=opener, cache_dir=tmp_path)
    names = {e.full_name for e in out}
    # Questionable + Out = both active; Probable (→ DAY_TO_DAY) is active too.
    assert "Josh Allen" in names
    assert "Out Guy" in names
    # Second call — cache hit, opener not invoked again.
    out2 = injury_feed.fetch_injuries(_url_opener=opener, cache_dir=tmp_path)
    assert len(calls) == 1
    assert len(out2) == len(out)


def test_status_normalization():
    assert injury_feed._normalize_status("Out") == "OUT"  # noqa: SLF001
    assert injury_feed._normalize_status("Injured Reserve") == "IR"  # noqa: SLF001
    assert injury_feed._normalize_status("Questionable") == "QUESTIONABLE"  # noqa: SLF001
    assert injury_feed._normalize_status("Day-to-Day") == "DAY_TO_DAY"  # noqa: SLF001


def test_malformed_payload_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("RISKIT_FEATURE_ESPN_INJURY_FEED", "1")
    feature_flags.reload()
    def opener(req, timeout=None):
        return io.BytesIO(b'{"not": "expected shape"}')
    out = injury_feed.fetch_injuries(_url_opener=opener, cache_dir=tmp_path)
    assert out == []


def test_network_error_returns_empty_not_crash(monkeypatch, tmp_path):
    monkeypatch.setenv("RISKIT_FEATURE_ESPN_INJURY_FEED", "1")
    feature_flags.reload()
    def opener(req, timeout=None):
        raise TimeoutError("upstream")
    out = injury_feed.fetch_injuries(_url_opener=opener, cache_dir=tmp_path)
    assert out == []


def test_diff_new_injury_fires():
    prior = []
    current = [
        injury_feed.InjuryEntry(
            espn_athlete_id="X", full_name="X Y", position="WR",
            team_abbrev="SF", status="OUT", body_part="Knee",
            description="", date_reported="", returning="",
        )
    ]
    signals = injury_feed.diff_for_signals(prior, current)
    assert len(signals) == 1
    assert signals[0]["transition"] == "healthy_to_injured"


def test_diff_worsened_fires():
    prior = [injury_feed.InjuryEntry(
        espn_athlete_id="X", full_name="X Y", position="WR",
        team_abbrev="SF", status="QUESTIONABLE", body_part="",
        description="", date_reported="", returning="",
    )]
    current = [injury_feed.InjuryEntry(
        espn_athlete_id="X", full_name="X Y", position="WR",
        team_abbrev="SF", status="OUT", body_part="",
        description="", date_reported="", returning="",
    )]
    signals = injury_feed.diff_for_signals(prior, current)
    assert len(signals) == 1
    assert signals[0]["transition"] == "injury_worsened"


def test_diff_unchanged_does_not_fire():
    e = injury_feed.InjuryEntry(
        espn_athlete_id="X", full_name="X Y", position="WR",
        team_abbrev="SF", status="OUT", body_part="",
        description="", date_reported="", returning="",
    )
    signals = injury_feed.diff_for_signals([e], [e])
    assert signals == []


def test_diff_recovered_does_not_fire_sell_signal():
    """A player who GETS BETTER → we DON'T emit a SELL transition.
    Recovery is a different signal class covered elsewhere."""
    prior = [injury_feed.InjuryEntry(
        espn_athlete_id="X", full_name="X Y", position="WR",
        team_abbrev="SF", status="OUT", body_part="",
        description="", date_reported="", returning="",
    )]
    current: list[injury_feed.InjuryEntry] = []
    signals = injury_feed.diff_for_signals(prior, current)
    assert signals == []
