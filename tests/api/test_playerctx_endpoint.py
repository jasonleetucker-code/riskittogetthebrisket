"""Tests for the R2 player-context read endpoint.

GET /api/playerctx/player serves per-player contract/snaps/depth blocks
from the ``src/playerctx`` snapshot.  Global player metadata — no league
resolution, no auth gate (public NFL data, same posture as intel reads).
Missing snapshot / unknown player are NORMAL states → clean 404 the UI
degrades on silently, never a 5xx.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import server
from src.playerctx import store as playerctx_store


@pytest.fixture()
def client():
    return TestClient(server.app)


@pytest.fixture(autouse=True)
def _authed(monkeypatch):
    # /api/playerctx/* sits behind the session gate like the other
    # private reads (intel, terminal). Tests run as a signed-in user.
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    yield


@pytest.fixture(autouse=True)
def _reset_cache():
    server._playerctx_cache["snapshot"] = None
    server._playerctx_cache["mtime"] = None
    yield
    server._playerctx_cache["snapshot"] = None
    server._playerctx_cache["mtime"] = None


def _write_snapshot(tmp_path, monkeypatch):
    snapshot = {
        "schemaVersion": "playerctx.v1",
        "generatedAt": "2026-07-26T00:00:00+00:00",
        "counts": {},
        "sources": {},
        "sleeperIndex": {"4034": "00-0033280", "9999": "sleeper:9999"},
        "players": {
            "00-0033280": {
                "gsisId": "00-0033280",
                "sleeperId": "4034",
                "name": "Christian McCaffrey",
                "team": "SF",
                "position": "RB",
                "contract": {
                    "apy": 16015853,
                    "total": 64063412,
                    "guaranteed": 36346412,
                    "years": 4,
                    "yearSigned": 2020,
                    "endYear": 2023,
                    "team": "CAR",
                },
                "snaps": {
                    "season": 2025,
                    "games": 19,
                    "side": "offense",
                    "pct": 81.7,
                    "recentPct": 75.3,
                    "trend": -6.4,
                },
                "depth": {
                    "position": "RB",
                    "rank": 1,
                    "depthPosition": "RB",
                    "team": "SF",
                },
            },
            # Fallback-keyed record (no gsis id) — ~1/3 of joined
            # players key this way; the endpoint must resolve them too.
            "sleeper:9999": {
                "sleeperId": "9999",
                "name": "Fallback Player",
                "team": "MIN",
                "position": "LB",
                "snaps": {"season": 2025, "games": 10, "side": "defense", "pct": 55.0},
            },
        },
    }
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    monkeypatch.setattr(playerctx_store, "SNAPSHOT_PATH", path)
    return snapshot


class TestPlayerctxEndpoint:
    def test_returns_player_blocks_by_sleeper_id(self, client, tmp_path, monkeypatch):
        _write_snapshot(tmp_path, monkeypatch)
        res = client.get("/api/playerctx/player", params={"playerId": "4034"})
        assert res.status_code == 200
        body = res.json()
        assert body["player"]["name"] == "Christian McCaffrey"
        assert body["player"]["contract"]["apy"] == 16015853
        assert body["player"]["snaps"]["pct"] == 81.7
        assert body["player"]["depth"]["rank"] == 1
        assert body["generatedAt"] == "2026-07-26T00:00:00+00:00"
        # weekly-cadence data → cacheable, but private
        assert "private" in res.headers.get("cache-control", "")

    def test_resolves_sleeper_fallback_keys(self, client, tmp_path, monkeypatch):
        _write_snapshot(tmp_path, monkeypatch)
        res = client.get("/api/playerctx/player", params={"playerId": "9999"})
        assert res.status_code == 200
        body = res.json()
        assert body["player"]["name"] == "Fallback Player"
        # optional blocks stay optional — no contract/depth for this one
        assert "contract" not in body["player"]

    def test_unknown_player_is_404_no_context(self, client, tmp_path, monkeypatch):
        _write_snapshot(tmp_path, monkeypatch)
        res = client.get("/api/playerctx/player", params={"playerId": "0000"})
        assert res.status_code == 404
        assert res.json()["error"] == "no_context"

    def test_missing_snapshot_is_404_not_500(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(playerctx_store, "SNAPSHOT_PATH", tmp_path / "absent.json")
        res = client.get("/api/playerctx/player", params={"playerId": "4034"})
        assert res.status_code == 404
        assert res.json()["error"] == "no_context"

    def test_missing_param_is_400(self, client):
        res = client.get("/api/playerctx/player")
        assert res.status_code == 400
        assert res.json()["error"] == "missing_param"

    def test_snapshot_cache_reloads_on_mtime_change(self, client, tmp_path, monkeypatch):
        snapshot = _write_snapshot(tmp_path, monkeypatch)
        assert client.get("/api/playerctx/player", params={"playerId": "4034"}).status_code == 200
        # rewrite with a new player under the same path + bump mtime
        snapshot["sleeperIndex"]["1234"] = "sleeper:1234"
        snapshot["players"]["sleeper:1234"] = {"sleeperId": "1234", "name": "New Guy"}
        path = tmp_path / "snapshot.json"
        path.write_text(json.dumps(snapshot), encoding="utf-8")
        import os

        os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 10))
        res = client.get("/api/playerctx/player", params={"playerId": "1234"})
        assert res.status_code == 200
        assert res.json()["player"]["name"] == "New Guy"
