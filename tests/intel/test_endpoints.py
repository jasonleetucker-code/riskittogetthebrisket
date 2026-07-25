"""HTTP surface for the intel endpoints: auth gates, 202/409 refresh
semantics, staleness stamping, and payload hygiene (no raw Sleeper
league IDs)."""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import server
from src.intel import service, store
from tests.intel.conftest import DAY_MS, HOUR_MS


@pytest.fixture
def authed(monkeypatch):
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda r: {"username": "jason"})


@pytest.fixture
def league_stub(monkeypatch):
    cfg = SimpleNamespace(key="dynasty_main", sleeper_league_id="999", active=True)
    monkeypatch.setattr(server, "_resolve_league_for_request", lambda *a, **k: cfg)
    return cfg


def _seed_snapshot(now_ms: int | None = None) -> None:
    """Write a small snapshot through the store (respects the
    monkeypatched path from ``intel_snapshot_path``)."""
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    state = store.default_state("2026")
    state["members"] = {
        "A": {
            "leagues": ["L1", "L2"],
            "truncated": False,
            "lastCrawledAt": "2026-07-25T00:00:00+00:00",
            "lastError": None,
        }
    }
    state["memberNames"] = {"A": "Alice"}
    state["leagues"] = {
        "L1": {
            "name": "Alpha League",
            "memberOwnerIds": ["A"],
            "holdings": {"A": ["1234"]},
            "fetchState": {},
        },
        "L2": {"name": "Beta League", "memberOwnerIds": ["A"], "holdings": {}, "fetchState": {}},
    }
    state["events"] = [
        {
            "eventId": "t1:A:add:1234",
            "txId": "t1",
            "leagueId": "L1",
            "ownerId": "A",
            "assetId": "1234",
            "assetType": "player",
            "action": "add",
            "txType": "waiver",
            "ts": now_ms - HOUR_MS,
            "week": 1,
            "faabBid": 5,
        },
        {
            "eventId": "t2:A:drop:5678",
            "txId": "t2",
            "leagueId": "L1",
            "ownerId": "A",
            "assetId": "5678",
            "assetType": "player",
            "action": "drop",
            "txType": "free_agent",
            "ts": now_ms - DAY_MS,
            "week": 1,
            "faabBid": None,
        },
    ]
    store.save_state(state, now_ms=now_ms)
    service.invalidate_cache()


class TestAuthGates:
    def test_summary_requires_auth(self, intel_snapshot_path):
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/intel/summary")
        assert res.status_code == 401

    def test_refresh_requires_auth_or_bearer(self, intel_snapshot_path, monkeypatch):
        monkeypatch.setattr(server, "INTEL_REFRESH_TOKEN", "sekrit")
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.post("/api/intel/refresh")
            assert res.status_code == 401
            res = c.post(
                "/api/intel/refresh",
                headers={"Authorization": "Bearer wrong"},
            )
            assert res.status_code == 401

    def test_status_accepts_bearer_token(self, intel_snapshot_path, monkeypatch):
        monkeypatch.setattr(server, "INTEL_REFRESH_TOKEN", "sekrit")
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get(
                "/api/intel/refresh/status",
                headers={"Authorization": "Bearer sekrit"},
            )
        assert res.status_code == 200
        assert res.headers["cache-control"] == "no-store"


class TestSummary:
    def test_summary_stamps_staleness_and_sorts(self, intel_snapshot_path, authed, monkeypatch):
        two_hours_ago = int(time.time() * 1000) - 2 * HOUR_MS
        _seed_snapshot(now_ms=two_hours_ago)
        with TestClient(server.app, raise_server_exceptions=True) as c:
            # Patch AFTER startup — the app lifespan primes
            # ``latest_contract_data`` and would overwrite an
            # earlier patch.
            monkeypatch.setattr(
                server,
                "latest_contract_data",
                {"sleeper": {"idToPlayer": {"1234": "Test Guy"}}},
            )
            res = c.get("/api/intel/summary")
        assert res.status_code == 200
        body = res.json()
        assert body["staleHours"] == pytest.approx(2.0, abs=0.2)
        assert body["memberCount"] == 1
        assert body["leagueCount"] == 2
        assets = body["assets"]
        assert [a["assetId"] for a in assets] == ["1234", "5678"]  # trendScore desc
        assert assets[0]["displayName"] == "Test Guy"
        assert assets[0]["trendScore"] > 0 > assets[1]["trendScore"]
        # Private endpoint — never a public cache header.
        assert "private" in res.headers["cache-control"]
        # No raw Sleeper league IDs anywhere in the payload.
        assert "L1" not in json.dumps(body)

    def test_summary_with_no_snapshot_is_empty_not_error(self, intel_snapshot_path, authed):
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/intel/summary")
        assert res.status_code == 200
        body = res.json()
        assert body["assets"] == []
        assert body["staleHours"] is None


class TestPlayerAndMember:
    def test_player_intel_by_id(self, intel_snapshot_path, authed):
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/intel/player", params={"playerId": "1234"})
        assert res.status_code == 200
        body = res.json()
        assert body["assetId"] == "1234"
        assert body["staleHours"] is not None
        exposure = body["memberExposure"]
        assert exposure[0]["ownerId"] == "A"
        assert exposure[0]["displayName"] == "Alice"
        assert exposure[0]["heldLeagueCount"] == 1
        assert "L1" not in json.dumps(body)

    def test_player_intel_unknown_asset_404(self, intel_snapshot_path, authed):
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/intel/player", params={"playerId": "does-not-exist"})
        assert res.status_code == 404

    def test_player_intel_missing_params_400(self, intel_snapshot_path, authed):
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/intel/player")
        assert res.status_code == 400

    def test_member_payload(self, intel_snapshot_path, authed):
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/intel/member/A")
        assert res.status_code == 200
        body = res.json()
        assert body["displayName"] == "Alice"
        assert body["leagueCount"] == 2
        assert body["leagueNames"] == ["Alpha League", "Beta League"]
        assert body["truncated"] is False
        assert body["eventCount30d"] == 2
        assert "L1" not in json.dumps(body)

    def test_member_unknown_404(self, intel_snapshot_path, authed):
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/intel/member/nobody")
        assert res.status_code == 404


class TestRefreshLifecycle:
    def test_refresh_202_then_409_while_running(
        self, intel_snapshot_path, authed, league_stub, monkeypatch
    ):
        gate = threading.Event()
        started = threading.Event()

        def slow_refresh(**kwargs):
            started.set()
            gate.wait(timeout=10)
            return {"ok": True, "callsUsed": 0}

        monkeypatch.setattr(service, "_refresh_locked", slow_refresh)
        try:
            with TestClient(server.app, raise_server_exceptions=True) as c:
                res = c.post("/api/intel/refresh")
                assert res.status_code == 202
                assert res.json()["status"]["isRunning"] is True
                assert started.wait(timeout=5)

                res2 = c.post("/api/intel/refresh")
                assert res2.status_code == 409
                assert res2.json()["alreadyRunning"] is True

                status = c.get("/api/intel/refresh/status")
                assert status.status_code == 200
                assert status.json()["isRunning"] is True
        finally:
            gate.set()
        # Wait for the daemon worker to release the lock.
        for _ in range(100):
            if not service.refresh_status()["isRunning"]:
                break
            time.sleep(0.02)
        final = service.refresh_status()
        assert final["isRunning"] is False
        assert final["lastResult"] == {"ok": True, "callsUsed": 0}
        assert final["lastError"] is None

    def test_refresh_error_surfaces_in_status(
        self, intel_snapshot_path, authed, league_stub, monkeypatch
    ):
        def broken_refresh(**kwargs):
            raise RuntimeError("sleeper exploded")

        monkeypatch.setattr(service, "_refresh_locked", broken_refresh)
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.post("/api/intel/refresh")
            assert res.status_code == 202
        for _ in range(100):
            if not service.refresh_status()["isRunning"]:
                break
            time.sleep(0.02)
        status = service.refresh_status()
        assert status["isRunning"] is False
        assert "sleeper exploded" in status["lastError"]

    def test_refresh_status_stamps_snapshot_staleness(self, intel_snapshot_path, authed):
        two_hours_ago = int(time.time() * 1000) - 2 * HOUR_MS
        _seed_snapshot(now_ms=two_hours_ago)
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/intel/refresh/status")
        assert res.status_code == 200
        assert res.json()["snapshotStaleHours"] == pytest.approx(2.0, abs=0.2)


class TestSyncRefreshLock:
    def test_concurrent_sync_refresh_rejected(self, intel_snapshot_path, monkeypatch):
        gate = threading.Event()
        entered = threading.Event()

        def slow_refresh(**kwargs):
            entered.set()
            gate.wait(timeout=10)
            return {}

        monkeypatch.setattr(service, "_refresh_locked", slow_refresh)
        t = threading.Thread(target=lambda: service.refresh_intel(member_ids=["A"]), daemon=True)
        t.start()
        assert entered.wait(timeout=5)
        with pytest.raises(service.RefreshAlreadyRunning):
            service.refresh_intel(member_ids=["A"])
        gate.set()
        t.join(timeout=5)
