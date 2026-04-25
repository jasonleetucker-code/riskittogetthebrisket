"""Tests for the direct nflverse CSV fetcher (no nfl_data_py)."""
from __future__ import annotations

import io
import urllib.error
from unittest.mock import patch

import pytest

from src.nfl_data import nflverse_direct as nd
from src.utils import circuit_breaker as cb


@pytest.fixture(autouse=True)
def _reset_cb():
    cb.reset_all_for_tests()
    yield
    cb.reset_all_for_tests()


def _csv_response(csv_text: str):
    """Build a fake urlopen context-manager that returns ``csv_text``."""
    class _R:
        def read(self):
            return csv_text.encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
    return _R()


def test_fetch_csv_parses_rows():
    csv_text = "name,age\nAlice,30\nBob,25\n"
    with patch.object(nd.urllib.request, "urlopen", return_value=_csv_response(csv_text)):
        rows = nd._fetch_csv("https://example.com/data.csv", label="test")  # noqa: SLF001
    assert len(rows) == 2
    assert rows[0]["name"] == "Alice"


def test_fetch_csv_network_error_returns_empty():
    def _raise(*_a, **_kw):
        raise urllib.error.URLError("connection refused")
    with patch.object(nd.urllib.request, "urlopen", side_effect=_raise):
        rows = nd._fetch_csv("https://example.com/x.csv", label="test")  # noqa: SLF001
    assert rows == []


def test_fetch_csv_http_4xx_returns_empty():
    def _raise(*_a, **_kw):
        raise urllib.error.HTTPError(
            "https://x", 404, "Not Found", {}, io.BytesIO(b""),
        )
    with patch.object(nd.urllib.request, "urlopen", side_effect=_raise):
        rows = nd._fetch_csv("https://example.com/x.csv", label="test")  # noqa: SLF001
    assert rows == []


def test_fetch_csv_timeout_returns_empty():
    def _raise(*_a, **_kw):
        raise TimeoutError("slow")
    with patch.object(nd.urllib.request, "urlopen", side_effect=_raise):
        rows = nd._fetch_csv("https://example.com/x.csv", label="test")  # noqa: SLF001
    assert rows == []


def test_fetch_csv_unexpected_exception_returns_empty():
    def _raise(*_a, **_kw):
        raise RuntimeError("unexpected")
    with patch.object(nd.urllib.request, "urlopen", side_effect=_raise):
        rows = nd._fetch_csv("https://example.com/x.csv", label="test")  # noqa: SLF001
    assert rows == []


def test_circuit_breaker_short_circuits_when_open():
    bp = cb.get_or_create("nflverse_direct", failure_threshold=1, failure_window_sec=60)
    bp.report_failure("priming")
    calls = []
    def _never(*_a, **_kw):
        calls.append(1)
        return _csv_response("x")
    with patch.object(nd.urllib.request, "urlopen", side_effect=_never):
        rows = nd._fetch_csv("https://example.com/x.csv", label="test")  # noqa: SLF001
    assert rows == []
    assert calls == []  # no network attempted


def test_coerce_numerics_int_columns():
    rows = [{"yards": "100", "name": "Test", "rate": "0.5"}]
    out = nd._coerce_numerics(rows)  # noqa: SLF001
    assert out[0]["yards"] == 100
    assert isinstance(out[0]["yards"], int)
    assert out[0]["rate"] == 0.5
    assert isinstance(out[0]["rate"], float)
    assert out[0]["name"] == "Test"  # left string


def test_coerce_numerics_handles_empty_string():
    rows = [{"yards": "", "name": "X"}]
    out = nd._coerce_numerics(rows)  # noqa: SLF001
    assert out[0]["yards"] is None


def test_fetch_weekly_stats_round_trips_csv():
    csv_text = (
        "season,week,player_id_gsis,player_name,passing_yards,passing_tds\n"
        "2024,1,00-0034857,Josh Allen,300,2\n"
    )
    with patch.object(nd.urllib.request, "urlopen", return_value=_csv_response(csv_text)):
        rows = nd.fetch_weekly_stats([2024])
    assert len(rows) == 1
    assert rows[0]["player_name"] == "Josh Allen"
    assert rows[0]["passing_yards"] == 300


def test_fetch_snap_counts_round_trips_csv():
    csv_text = "season,week,player,offense_pct\n2024,1,Test,0.95\n"
    with patch.object(nd.urllib.request, "urlopen", return_value=_csv_response(csv_text)):
        rows = nd.fetch_snap_counts([2024])
    assert len(rows) == 1
    assert rows[0]["offense_pct"] == 0.95


def test_fetch_id_map():
    csv_text = "gsis_id,sleeper_id,full_name\n00-1,4017,Josh Allen\n"
    with patch.object(nd.urllib.request, "urlopen", return_value=_csv_response(csv_text)):
        rows = nd.fetch_id_map()
    assert rows[0]["sleeper_id"] == 4017


def test_fetch_pbp():
    csv_text = "season,week,play_type\n2024,1,pass\n"
    with patch.object(nd.urllib.request, "urlopen", return_value=_csv_response(csv_text)):
        rows = nd.fetch_pbp([2024])
    assert rows[0]["play_type"] == "pass"


def test_url_templates_contain_expected_paths():
    """Pin the URL pattern — if nflverse re-organizes their releases
    this test fails fast."""
    assert "player_stats" in nd._URL_TEMPLATES["weekly_stats"]  # noqa: SLF001
    assert "snap_counts" in nd._URL_TEMPLATES["snap_counts"]  # noqa: SLF001
    assert "players.csv" in nd._URL_TEMPLATES["id_map"]  # noqa: SLF001
    assert "play_by_play" in nd._URL_TEMPLATES["pbp"]  # noqa: SLF001
