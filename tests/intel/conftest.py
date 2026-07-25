"""Shared fixtures for the intel test suite.

Everything runs against ``FakeSleeper`` — an in-memory url→payload
map with a call log.  NO live network calls anywhere in these tests.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from src.intel import service
from src.intel.crawler import SLEEPER_BASE

NOW_MS = 1_760_000_000_000  # fixed "now" for deterministic windows
HOUR_MS = 3600 * 1000
DAY_MS = 24 * HOUR_MS


class FakeSleeper:
    """url → payload stub with a call log.  Missing urls return None
    (the same contract as the live ``_http_get_json``: any failure is
    a None)."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.responses = dict(responses or {})
        self.calls: list[str] = []

    def __call__(self, url: str) -> Any:
        self.calls.append(url)
        return copy.deepcopy(self.responses.get(url))

    def count(self, url: str) -> int:
        return sum(1 for c in self.calls if c == url)


def state_url() -> str:
    return f"{SLEEPER_BASE}/state/nfl"


def leagues_url(owner_id: str, season: str) -> str:
    return f"{SLEEPER_BASE}/user/{owner_id}/leagues/nfl/{season}"


def rosters_url(league_id: str) -> str:
    return f"{SLEEPER_BASE}/league/{league_id}/rosters"


def users_url(league_id: str) -> str:
    return f"{SLEEPER_BASE}/league/{league_id}/users"


def tx_url(league_id: str, week: int) -> str:
    return f"{SLEEPER_BASE}/league/{league_id}/transactions/{week}"


def make_league(league_id: str, name: str | None = None, season: str = "2026") -> dict[str, Any]:
    return {
        "league_id": league_id,
        "name": name or f"League {league_id}",
        "season": season,
        "total_rosters": 12,
    }


def make_roster(
    roster_id: int,
    owner_id: str | None,
    players: list[str] | None = None,
    co_owners: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "roster_id": roster_id,
        "owner_id": owner_id,
        "co_owners": co_owners or [],
        "players": players or [],
    }


def make_trade_tx(
    tx_id: str,
    created_ms: int,
    adds: dict[str, int] | None = None,
    drops: dict[str, int] | None = None,
    draft_picks: list[dict[str, Any]] | None = None,
    status: str = "complete",
) -> dict[str, Any]:
    return {
        "transaction_id": tx_id,
        "type": "trade",
        "status": status,
        "created": created_ms,
        "status_updated": created_ms,
        "adds": adds or {},
        "drops": drops or {},
        "draft_picks": draft_picks or [],
        "roster_ids": sorted({*(adds or {}).values(), *(drops or {}).values()}),
    }


def make_waiver_tx(
    tx_id: str,
    created_ms: int,
    roster_id: int,
    add_player: str | None = None,
    drop_player: str | None = None,
    bid: int = 0,
    tx_type: str = "waiver",
    status: str = "complete",
) -> dict[str, Any]:
    return {
        "transaction_id": tx_id,
        "type": tx_type,
        "status": status,
        "created": created_ms,
        "status_updated": created_ms,
        "adds": {add_player: roster_id} if add_player else {},
        "drops": {drop_player: roster_id} if drop_player else {},
        "settings": {"waiver_bid": bid} if tx_type == "waiver" else {},
        "roster_ids": [roster_id],
    }


@pytest.fixture(autouse=True)
def _reset_service_state():
    """Isolate the service module's process-global lock/status/cache
    between tests."""
    yield
    if service._REFRESH_LOCK.locked():  # pragma: no cover — defensive
        service._REFRESH_LOCK.release()
    with service._STATUS_LOCK:
        service._STATUS.update(
            {
                "isRunning": False,
                "startedAt": None,
                "finishedAt": None,
                "lastError": None,
                "lastResult": None,
            }
        )
    service.invalidate_cache()


@pytest.fixture
def intel_snapshot_path(tmp_path, monkeypatch):
    """Point the store at a per-test snapshot file."""
    from src.intel import store

    path = tmp_path / "intel" / "snapshot.json"
    monkeypatch.setattr(store, "SNAPSHOT_PATH", path)
    monkeypatch.setattr(store, "DATA_DIR", path.parent)
    service.invalidate_cache()
    return path
