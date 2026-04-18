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
