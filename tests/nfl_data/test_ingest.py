"""Tests for src.nfl_data.ingest.

Key invariants:
  * Feature flag OFF → every fetch returns [] (no network calls).
  * With flag ON + stub provider, values round-trip via cache.
  * Provider exceptions are swallowed; return [].
  * The absence of nfl_data_py is NEVER a crash.
"""
from __future__ import annotations

import pytest

from src.api import feature_flags
from src.nfl_data import ingest


@pytest.fixture(autouse=True)
def _flags(monkeypatch):
    # Default: flag off; specific tests enable as needed.
    feature_flags.reload()
    yield
    feature_flags.reload()


def test_flag_off_returns_empty_without_provider_call(monkeypatch, tmp_path):
    # Force flag OFF — post-2026-04-25 the default is ON, but the
    # gate behavior must still work when explicitly disabled.
    monkeypatch.setenv("RISKIT_FEATURE_NFL_DATA_INGEST", "0")
    from src.api import feature_flags
    feature_flags.reload()
    calls = []
    def provider(years):
        calls.append(years)
        return [{"stub": True}]
    out = ingest.fetch_weekly_stats(
        [2024], _provider=provider, cache_dir=tmp_path,
    )
    assert out == []
    assert calls == [], "flag off must not call provider"


def test_flag_on_runs_provider_and_caches(monkeypatch, tmp_path):
    monkeypatch.setenv("RISKIT_FEATURE_NFL_DATA_INGEST", "1")
    feature_flags.reload()
    calls = []
    def provider(years):
        calls.append(years)
        return [{"player_id_gsis": "00-1", "season": 2024, "week": 1}]
    # First call: hits provider.
    out = ingest.fetch_weekly_stats(
        [2024], _provider=provider, cache_dir=tmp_path,
    )
    assert out and out[0]["player_id_gsis"] == "00-1"
    assert len(calls) == 1
    # Second call: cache hit, provider not called again.
    out2 = ingest.fetch_weekly_stats(
        [2024], _provider=provider, cache_dir=tmp_path,
    )
    assert out2 == out
    assert len(calls) == 1


def test_provider_exception_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("RISKIT_FEATURE_NFL_DATA_INGEST", "1")
    feature_flags.reload()
    def boom(years):
        raise RuntimeError("upstream 503")
    out = ingest.fetch_weekly_stats(
        [2024], _provider=boom, cache_dir=tmp_path,
    )
    assert out == []


def test_snap_counts_flag_gated(monkeypatch, tmp_path):
    monkeypatch.setenv("RISKIT_FEATURE_NFL_DATA_INGEST", "0")
    feature_flags.reload()
    def provider(years):
        return [{"pfr_id": "A", "week": 1}]
    assert ingest.fetch_snap_counts(
        [2024], _provider=provider, cache_dir=tmp_path,
    ) == []


def test_id_map_flag_gated(monkeypatch, tmp_path):
    monkeypatch.setenv("RISKIT_FEATURE_NFL_DATA_INGEST", "0")
    feature_flags.reload()
    def provider():
        return [{"gsis_id": "00-1", "sleeper_id": "4017"}]
    assert ingest.fetch_id_map(
        _provider=provider, cache_dir=tmp_path,
    ) == []


def test_provider_status_without_pandas_is_not_a_crash():
    status = ingest.provider_status()
    assert "feature_flag" in status
    assert "nfl_data_py_installed" in status


def test_dataframe_to_rows_tolerates_list_input():
    # Callers with a stub that returns list[dict] directly should work.
    rows = ingest._dataframe_to_rows([{"a": 1}, {"a": 2}])  # noqa: SLF001
    assert rows == [{"a": 1}, {"a": 2}]


def test_dataframe_to_rows_handles_none():
    assert ingest._dataframe_to_rows(None) == []  # noqa: SLF001
