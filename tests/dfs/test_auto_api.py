"""/api/dfs/auto/* — the zero-upload primary workflow through the real endpoints."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import feature_flags
from src.dfs import api as dfs_api
from src.dfs import jobs
from src.dfs.auto import refresh
from tests.dfs.test_auto_nfl import NOW, run_refresh

pytest.importorskip("scipy")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DFS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("RISKIT_FEATURE_DFS_WORKSPACE", raising=False)
    monkeypatch.setattr(refresh, "_now", lambda: NOW + timedelta(minutes=5))
    submitted = []
    monkeypatch.setattr(
        jobs,
        "submit",
        lambda owner, kind, params: submitted.append((owner, kind)) or {"state": "queued"},
    )
    feature_flags.reload()
    app = FastAPI()
    app.include_router(dfs_api.router)
    dfs_api.configure_session_resolver(
        lambda req: {"username": req.headers["x-user"]} if req.headers.get("x-user") else None
    )
    c = TestClient(app)
    c.submitted = submitted
    yield c
    feature_flags.reload()


H = {"x-user": "alice"}


def test_nothing_built_yet_is_unavailable_and_queues_a_refresh(client):
    body = client.get("/api/dfs/auto/slates?platform=draftkings", headers=H).json()
    assert body["state"] == "UNAVAILABLE" and body["slates"] == []
    assert body["refreshQueued"] == "queued"
    assert client.submitted == [("system:auto", "dfs_auto_refresh")]


def test_open_dfs_select_main_build_with_no_upload(client):
    run_refresh()
    listing = client.get("/api/dfs/auto/slates?platform=draftkings", headers=H).json()
    assert listing["state"] == "AVAILABLE" and listing["refreshQueued"] is None
    assert {s["platform"] for s in listing["slates"]} == {"draftkings"}
    main = next(s for s in listing["slates"] if s["slateKey"] == "main")
    r = client.post(
        "/api/dfs/auto/slates/select", json={"autoSlateId": main["autoSlateId"]}, headers=H
    )
    assert r.status_code == 201
    snap = r.json()
    assert snap["contentHash"] == main["contentHash"] and snap["coverage"]["unprojected"] == 0
    fresh = {f["class"]: f for f in snap["freshness"]}
    assert fresh["salary"]["state"] == "automatic" and fresh["projection"]["state"] == "automatic"
    # Selecting again reuses the owner's copy instead of piling up snapshots.
    again = client.post(
        "/api/dfs/auto/slates/select", json={"autoSlateId": main["autoSlateId"]}, headers=H
    )
    assert again.status_code == 200 and again.json()["snapshotId"] == snap["snapshotId"]
    # Another user gets their own copy; the system namespace is never exposed.
    other = client.post(
        "/api/dfs/auto/slates/select",
        json={"autoSlateId": main["autoSlateId"]},
        headers={"x-user": "bob"},
    ).json()
    assert other["snapshotId"] != snap["snapshotId"]
    b = client.post(
        "/api/dfs/builds",
        json={
            "snapshotId": snap["snapshotId"],
            "objective": "projection_baseline",
            "constraints": {"lineups": 1},
        },
        headers=H,
    )
    assert b.status_code == 201 and b.json()["result"]["built"] == 1
    ex = client.get(f"/api/dfs/builds/{b.json()['buildId']}/export", headers=H)
    assert ex.status_code == 409 and ex.json()["error"] == "PLATFORM_IDS_UNAVAILABLE"


def test_unknown_auto_slate_and_other_sports(client):
    assert (
        client.post("/api/dfs/auto/slates/select", json={"autoSlateId": "x"}, headers=H).status_code
        == 404
    )
    nba = client.get("/api/dfs/auto/slates?sport=nba", headers=H).json()
    assert nba["state"] == "UNAVAILABLE" and "NFL only" in nba["reason"]
    assert client.get("/api/dfs/auto/slates?platform=yahoo", headers=H).status_code == 400
    assert client.get("/api/dfs/auto/slates").status_code == 401


def test_flag_off_switches_the_automatic_path_off_and_leaves_manual_import(client, monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_DFS_AUTO_SLATES", "0")
    feature_flags.reload()
    r = client.get("/api/dfs/auto/slates", headers=H)
    assert r.status_code == 503 and r.json()["error"] == "FEATURE_DISABLED"
    assert client.submitted == []  # no refresh queued
    assert client.get("/api/dfs/capabilities", headers=H).status_code == 200
