"""/api/dfs/auto/* — the zero-upload primary workflow through the real endpoints."""

from __future__ import annotations

import json
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
    params_seen = []
    monkeypatch.setattr(
        jobs,
        "submit",
        lambda owner, kind, params: (
            submitted.append((owner, kind)) or params_seen.append(params) or {"state": "queued"}
        ),
    )
    feature_flags.reload()
    app = FastAPI()
    app.include_router(dfs_api.router)
    dfs_api.configure_session_resolver(
        lambda req: {"username": req.headers["x-user"]} if req.headers.get("x-user") else None
    )
    c = TestClient(app)
    c.submitted = submitted
    c.params_seen = params_seen
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
    mma = client.get("/api/dfs/auto/slates?sport=mma", headers=H).json()
    assert mma["state"] == "UNAVAILABLE" and "NFL, NBA and NHL" in mma["reason"]
    assert client.get("/api/dfs/auto/slates?platform=yahoo", headers=H).status_code == 400
    assert client.get("/api/dfs/auto/slates").status_code == 401


def test_flag_off_switches_the_automatic_path_off_and_leaves_manual_import(client, monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_DFS_AUTO_SLATES", "0")
    feature_flags.reload()
    r = client.get("/api/dfs/auto/slates", headers=H)
    assert r.status_code == 503 and r.json()["error"] == "FEATURE_DISABLED"
    assert client.submitted == []  # no refresh queued
    assert client.get("/api/dfs/capabilities", headers=H).status_code == 200


def test_nhl_slate_opens_and_builds_through_the_same_endpoints(
    client, monkeypatch, tmp_path_factory
):
    """DFS-AUTO-19: a daily sport uses the SAME list / select / build path as NFL."""
    from tests.dfs import test_auto_daily as daily_fx

    from src.dfs.auto import approval

    monkeypatch.setattr(refresh, "_now", lambda: daily_fx.NHL_NOW + timedelta(minutes=5))
    # Today the schedule source awaits the owner: nothing queued, nothing selectable.
    waiting = client.get("/api/dfs/auto/slates?sport=nhl&platform=draftkings", headers=H).json()
    assert waiting["state"] == "AWAITING_APPROVAL" and waiting["slates"] == []
    assert "approve" in waiting["reason"] and "off day" not in waiting["reason"]
    assert client.submitted == []
    daily_fx.run("nhl")  # (built directly, as an approved refresh would)
    pending_id = "draftkings:nhl:2026:d20261007:listed"
    r = client.post("/api/dfs/auto/slates/select", json={"autoSlateId": pending_id}, headers=H)
    assert r.status_code == 409 and r.json()["error"] == "AWAITING_OWNER_APPROVAL"
    # Owner approves (recorded with date + evidence) → the same endpoints serve it.
    approved = tmp_path_factory.mktemp("approval") / "auto_sources.json"
    entry = {"approval": "approved", "approvedOn": "2026-10-08", "evidence": "test"}
    approved.write_text(json.dumps({"sports": {"nhl": entry}}), encoding="utf-8")
    monkeypatch.setattr(approval, "PATH", approved)
    monkeypatch.setattr(refresh, "_now", lambda: daily_fx.NHL_NOW + timedelta(hours=3))
    first = client.get("/api/dfs/auto/slates?sport=nhl&platform=draftkings", headers=H).json()
    assert first["state"] == "AVAILABLE" and first["refreshQueued"] == "queued"
    assert client.params_seen[-1] == {"sport": "nhl"}  # the job refreshes THIS sport
    listing = client.get("/api/dfs/auto/slates?sport=nhl&platform=draftkings", headers=H).json()
    assert listing["state"] == "AVAILABLE" and listing["sport"] == "nhl"
    (slate,) = listing["slates"]
    assert slate["slateDate"] == "2026-10-07" and slate["week"] is None
    snap = client.post(
        "/api/dfs/auto/slates/select", json={"autoSlateId": slate["autoSlateId"]}, headers=H
    )
    assert snap.status_code == 201
    fresh = {f["class"]: f for f in snap.json()["freshness"]}
    assert "listed slate" in fresh["salary"]["source"]
    assert "nflverse" not in fresh["sportsbook"]["source"]
    assert "goalie" in fresh["lineups_status"]["note"]
    b = client.post(
        "/api/dfs/builds",
        json={"snapshotId": snap.json()["snapshotId"], "objective": "projection_baseline",
              "constraints": {"lineups": 1}},
        headers=H,
    )  # fmt: skip
    assert b.status_code == 201 and b.json()["result"]["built"] == 1
    ex = client.get(f"/api/dfs/builds/{b.json()['buildId']}/export", headers=H)
    assert ex.status_code == 409 and ex.json()["error"] == "PLATFORM_IDS_UNAVAILABLE"
