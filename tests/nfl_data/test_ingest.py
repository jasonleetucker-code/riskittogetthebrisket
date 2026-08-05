"""Tests for src.nfl_data.ingest.

Key invariants:
  * Feature flag OFF → every fetch returns [] (no network calls).
  * With flag ON + stub provider, values round-trip via cache.
  * Provider exceptions are swallowed; return [].
  * The absence of nfl_data_py is NEVER a crash.
"""

from __future__ import annotations

import threading
import time

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
        [2024],
        _provider=provider,
        cache_dir=tmp_path,
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
        [2024],
        _provider=provider,
        cache_dir=tmp_path,
    )
    assert out and out[0]["player_id_gsis"] == "00-1"
    assert len(calls) == 1
    # Second call: cache hit, provider not called again.
    out2 = ingest.fetch_weekly_stats(
        [2024],
        _provider=provider,
        cache_dir=tmp_path,
    )
    assert out2 == out
    assert len(calls) == 1


def test_provider_exception_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("RISKIT_FEATURE_NFL_DATA_INGEST", "1")
    feature_flags.reload()

    def boom(years):
        raise RuntimeError("upstream 503")

    out = ingest.fetch_weekly_stats(
        [2024],
        _provider=boom,
        cache_dir=tmp_path,
    )
    assert out == []


def test_snap_counts_flag_gated(monkeypatch, tmp_path):
    monkeypatch.setenv("RISKIT_FEATURE_NFL_DATA_INGEST", "0")
    feature_flags.reload()

    def provider(years):
        return [{"pfr_id": "A", "week": 1}]

    assert (
        ingest.fetch_snap_counts(
            [2024],
            _provider=provider,
            cache_dir=tmp_path,
        )
        == []
    )


def test_id_map_flag_gated(monkeypatch, tmp_path):
    monkeypatch.setenv("RISKIT_FEATURE_NFL_DATA_INGEST", "0")
    feature_flags.reload()

    def provider():
        return [{"gsis_id": "00-1", "sleeper_id": "4017"}]

    assert (
        ingest.fetch_id_map(
            _provider=provider,
            cache_dir=tmp_path,
        )
        == []
    )


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


class TestConcurrentMissesFetchOnce:
    """A cold cache must produce ONE fetch, not one per caller.

    Every fetch in ``ingest`` was check-then-fill with a multi-second
    network call in the gap::

        cached = _cache.get(key, ...)
        if cached is not None: return cached
        rows = _try_fetch_with_fallback(...)   # seconds
        _cache.put(key, rows, ...)

    The module docstring says "the first call each day hits nflverse and
    subsequent calls hit disk", which holds for calls made in SEQUENCE.
    Concurrently, everyone who arrives before the first ``put()`` also
    misses, and they all fetch.

    Measured on E2E run 31027451127 with a cold cache in one uvicorn
    process: ``snap_counts_2020.csv`` downloaded 4 times, ``2022`` 6
    times, and the full 157,615-row snap set completing 3 times inside
    6 seconds.  That saturated the backend while the suite was loading
    pages -- ``POST /api/trade/finder`` measured 66s against 7.7s on a
    quiet run.  Tracked as #753.

    These tests pin the repair.  Without the single-flight in
    ``_cached_or_fetch`` the first assertion below reports the thread
    count instead of 1.
    """

    @staticmethod
    def _slow_provider(calls, barrier=None):
        def provider(*args):
            calls.append(args)
            # Hold the "network call" open long enough that every other
            # thread is guaranteed to be inside the miss window.  This
            # is what makes the test deterministic rather than timing
            # dependent: without single-flight they ALL fetch.
            time.sleep(0.25)
            return [{"row": len(calls)}]

        return provider

    def _run_threads(self, target, n=8):
        results: list[object] = [None] * n
        errors: list[BaseException] = []

        def run(i):
            try:
                results[i] = target()
            except BaseException as exc:  # noqa: BLE001 - surfaced below
                errors.append(exc)

        threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert not errors, f"threads raised: {errors}"
        assert all(not t.is_alive() for t in threads), "a thread never finished"
        return results

    def test_snap_counts_fetches_once_under_concurrency(self, monkeypatch, tmp_path):
        monkeypatch.setenv("RISKIT_FEATURE_NFL_DATA_INGEST", "1")
        feature_flags.reload()
        calls: list[object] = []
        provider = self._slow_provider(calls)

        results = self._run_threads(
            lambda: ingest.fetch_snap_counts(
                [2023, 2024],
                _provider=provider,
                cache_dir=tmp_path,
            )
        )

        assert len(calls) == 1, (
            f"cold cache produced {len(calls)} fetches for one key — the "
            "single-flight in _cached_or_fetch is gone, and every concurrent "
            "caller is re-downloading the same nflverse dataset (#753)"
        )
        # Followers must return the leader's cached value, not [].
        assert all(r == [{"row": 1}] for r in results), results

    def test_distinct_keys_are_not_serialised_into_one_fetch(self, monkeypatch, tmp_path):
        """The single-flight must be PER KEY, not global.

        A global lock would also collapse the duplicate count to a small
        number, so this is what distinguishes a correct repair from one
        that merely makes the symptom smaller — and it is the difference
        between different seasons sharing a fetch and each getting its
        own.
        """
        monkeypatch.setenv("RISKIT_FEATURE_NFL_DATA_INGEST", "1")
        feature_flags.reload()
        calls: list[object] = []
        provider = self._slow_provider(calls)

        for years in ([2023], [2024], [2025]):
            ingest.fetch_snap_counts(years, _provider=provider, cache_dir=tmp_path)

        assert len(calls) == 3, (
            "three distinct year-keys must each fetch — a global lock or an "
            f"over-broad cache key would collapse them (saw {len(calls)})"
        )

    def test_a_failed_leader_does_not_poison_followers(self, monkeypatch, tmp_path):
        """A fetch that fails must not be cached, and must not block.

        The pre-existing contract is that a failure returns [] and writes
        nothing so the next caller retries.  The single-flight preserves
        it because a follower re-reads the CACHE rather than taking the
        leader's return value: a failed leader leaves no entry, so the
        follower simply misses and becomes the next leader.
        """
        monkeypatch.setenv("RISKIT_FEATURE_NFL_DATA_INGEST", "1")
        feature_flags.reload()
        attempts: list[int] = []

        def failing(*_args):
            attempts.append(1)
            raise RuntimeError("nflverse down")

        first = ingest.fetch_snap_counts([2024], _provider=failing, cache_dir=tmp_path)
        assert first == [], "a failed fetch must still return []"

        # The next caller must be free to try again — i.e. the failure
        # was neither cached nor left holding the in-flight slot.
        def ok(*_args):
            return [{"row": "recovered"}]

        second = ingest.fetch_snap_counts([2024], _provider=ok, cache_dir=tmp_path)
        assert second == [
            {"row": "recovered"}
        ], "a failed leader left the key wedged or cached an empty result"
        assert len(attempts) == 1
