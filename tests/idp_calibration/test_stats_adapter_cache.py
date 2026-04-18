"""The `HistoricalStatsAdapter` base class memoizes per-season results
so the adapter-selection probe (`available()` calls `fetch()`) does not
force a duplicate fetch during `run_analysis`.
"""
from __future__ import annotations

from src.idp_calibration.stats_adapter import HistoricalStatsAdapter, PlayerSeason


class _CountingAdapter(HistoricalStatsAdapter):
    name = "counting"

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def _fetch_impl(self, season: int):
        self.calls += 1
        return [
            PlayerSeason(
                player_id=f"p{season}",
                name="X",
                position="DL",
                games=16,
                stats={"idp_tkl_solo": 10},
            )
        ]


def test_available_then_fetch_hits_backend_once_per_season():
    adapter = _CountingAdapter()
    # The plain old subclass pattern: one call to available() then fetch().
    assert adapter.available(2024) is True
    first = adapter.fetch(2024)
    second = adapter.fetch(2024)
    assert first == second
    assert adapter.calls == 1  # One impl call, not three.


def test_cache_is_per_season():
    adapter = _CountingAdapter()
    adapter.fetch(2024)
    adapter.fetch(2025)
    adapter.fetch(2024)
    assert adapter.calls == 2  # 2024 and 2025 each hit the impl exactly once.


def test_get_stats_adapter_defaults_network_off_under_pytest(monkeypatch):
    """Because these tests import pytest, _detect_test_context() should
    return True and the factory should skip ``SleeperStatsAdapter``
    automatically unless the env var or explicit arg overrides."""
    from src.idp_calibration import stats_adapter

    monkeypatch.delenv("IDP_CALIBRATION_ALLOW_NETWORK", raising=False)
    _, attempts = stats_adapter.get_stats_adapter(2025)
    assert any("skipped (network disabled)" in a for a in attempts)


def test_get_stats_adapter_env_var_forces_network_on(monkeypatch):
    from src.idp_calibration import stats_adapter

    # Stub _fetch_impl so the adapter-selection probe doesn't perform
    # a real HTTP call against api.sleeper.app. The assertion only
    # cares which branch the factory takes, not whether the sleeper
    # endpoint is reachable from the test runner — a real call would
    # make this test flaky on no-egress or slow CI networks.
    def _fail(self, season):
        raise stats_adapter.AdapterUnavailable("stubbed: no network in tests")

    monkeypatch.setattr(stats_adapter.SleeperStatsAdapter, "_fetch_impl", _fail)
    monkeypatch.setenv("IDP_CALIBRATION_ALLOW_NETWORK", "1")

    _, attempts = stats_adapter.get_stats_adapter(2025)
    # We forced network on, so the sleeper branch must NOT have been
    # marked as skipped — it was attempted (and failed deterministically
    # via our stub).
    assert not any("skipped (network disabled)" in a for a in attempts)
    # The sleeper branch entry must appear in the attempt log.
    assert any(a.startswith("sleeper:") for a in attempts)


def test_get_stats_adapter_env_var_forces_network_off(monkeypatch):
    """Explicit "0" still overrides even if someone flipped the default."""
    from src.idp_calibration import stats_adapter

    monkeypatch.setenv("IDP_CALIBRATION_ALLOW_NETWORK", "0")
    _, attempts = stats_adapter.get_stats_adapter(2025)
    assert any("skipped (network disabled)" in a for a in attempts)


def test_detect_test_context_sees_pytest():
    # Sanity check: our detector fires inside the test process.
    from src.idp_calibration.stats_adapter import _detect_test_context

    assert _detect_test_context() is True
