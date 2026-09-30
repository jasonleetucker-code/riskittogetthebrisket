"""/api/dfs/* — auth, owner scoping, capability honesty, export."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import feature_flags
from src.dfs import api as dfs_api

pytest.importorskip("scipy")

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DFS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("RISKIT_FEATURE_DFS_WORKSPACE", raising=False)
    feature_flags.reload()
    app = FastAPI()
    app.include_router(dfs_api.router)
    dfs_api.configure_session_resolver(
        lambda req: {"username": req.headers["x-user"]} if req.headers.get("x-user") else None
    )
    yield TestClient(app)
    feature_flags.reload()


def _slate(client, user="alice", **extra):
    body = {
        "ruleset": "draftkings.nfl.classic",
        "salaryCsv": (FIX / "synthetic_dk_nfl_classic_salaries.csv").read_text(encoding="utf-8"),
        "projectionCsv": (FIX / "synthetic_dk_nfl_classic_projections.csv").read_text(
            encoding="utf-8"
        ),
        **extra,
    }
    return client.post("/api/dfs/slates", json=body, headers={"x-user": user})


def test_no_session_is_401(client):
    assert client.get("/api/dfs/capabilities").status_code == 401


def test_flag_off_is_503(client, monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_DFS_WORKSPACE", "0")
    feature_flags.reload()
    r = client.get("/api/dfs/capabilities", headers={"x-user": "alice"})
    assert r.status_code == 503 and r.json()["error"] == "FEATURE_DISABLED"


def test_capabilities_are_honest(client):
    body = client.get("/api/dfs/capabilities", headers={"x-user": "alice"}).json()
    objectives = {o["id"]: o for o in body["objectives"]}
    assert objectives["projection_baseline"]["available"] is True
    assert objectives["contest_ev"]["available"] is False
    assert {r["sport"] for r in body["matrix"]} == {"nfl", "nba", "nhl", "mma"}


def test_full_flow_research_build_and_export(client):
    snap = _slate(client).json()
    assert snap["coverage"] == {"athletes": 84, "projected": 84, "unprojected": 0}
    r = client.post(
        "/api/dfs/builds",
        json={
            "snapshotId": snap["snapshotId"],
            "objective": "projection_baseline",
            "constraints": {"lineups": 3},
        },
        headers={"x-user": "alice"},
    )
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["researchOnly"] is True and b["contestEvaluated"] is False
    assert b["capabilityLevel"] == "projection_only" and b["submitted"] is False
    assert b["result"]["built"] == 3 and b["snapshot"]["contentHash"] == snap["contentHash"]
    ex = client.get(f"/api/dfs/builds/{b['buildId']}/export", headers={"x-user": "alice"})
    assert ex.status_code == 200
    assert ex.headers["x-dfs-export-verified"] == "false"
    assert "UNVERIFIED-FORMAT" in ex.headers["content-disposition"]
    lines = ex.text.strip().splitlines()
    assert lines[0] == "QB,RB,RB,WR,WR,WR,TE,FLEX,DST"
    assert len(lines) == 4
    first = b["result"]["lineups"][0]["players"]
    assert lines[1].split(",") == [p["playerId"] for p in first]


def test_contest_ev_is_refused_not_substituted(client):
    snap = _slate(client).json()
    r = client.post(
        "/api/dfs/builds",
        json={"snapshotId": snap["snapshotId"], "objective": "contest_ev"},
        headers={"x-user": "alice"},
    )
    assert r.status_code == 409 and r.json()["error"] == "CAPABILITY_UNAVAILABLE"


def test_money_mode_fails_closed_on_unverified_rules(client):
    snap = _slate(client).json()
    r = client.post(
        "/api/dfs/builds",
        json={
            "snapshotId": snap["snapshotId"],
            "objective": "projection_baseline",
            "mode": "money",
        },
        headers={"x-user": "alice"},
    )
    assert r.status_code == 409 and r.json()["error"] == "RULESET_UNVERIFIED"


def test_another_owner_cannot_read_or_build_from_my_records(client):
    snap = _slate(client).json()
    b = client.post(
        "/api/dfs/builds",
        json={"snapshotId": snap["snapshotId"], "objective": "projection_baseline"},
        headers={"x-user": "alice"},
    ).json()
    for path in (
        f"/api/dfs/slates/{snap['snapshotId']}",
        f"/api/dfs/builds/{b['buildId']}",
        f"/api/dfs/builds/{b['buildId']}/export",
    ):
        assert client.get(path, headers={"x-user": "mallory"}).status_code == 404
    r = client.post(
        "/api/dfs/builds",
        json={"snapshotId": snap["snapshotId"], "objective": "projection_baseline"},
        headers={"x-user": "mallory"},
    )
    assert r.status_code == 404
    assert client.get("/api/dfs/builds", headers={"x-user": "mallory"}).json()["builds"] == []


def test_import_errors_are_structured(client):
    r = client.post(
        "/api/dfs/slates",
        json={"ruleset": "draftkings.nfl.classic", "salaryCsv": "a,b\n1,2\n"},
        headers={"x-user": "alice"},
    )
    assert r.status_code == 422 and r.json()["error"] == "HEADER_MISMATCH"
    r = client.post(
        "/api/dfs/slates", json={"ruleset": "nope", "salaryCsv": "x"}, headers={"x-user": "alice"}
    )
    assert r.json()["error"] == "RULESET_UNKNOWN"


def test_infeasible_constraints_explain_themselves(client):
    snap = _slate(client).json()
    qbs = [a["player_id"] for a in snap["athletes"] if a["positions"] == ["QB"]][:2]
    r = client.post(
        "/api/dfs/builds",
        json={
            "snapshotId": snap["snapshotId"],
            "objective": "projection_baseline",
            "constraints": {"locks": qbs},
        },
        headers={"x-user": "alice"},
    )
    res = r.json()["result"]
    assert res["status"] == "infeasible" and res["built"] == 0
    assert len(res["shortfall"]["conflict"]["described"]) == 2


def test_server_mounts_dfs_behind_the_private_gate():
    """The real server registers /api/dfs/* and keeps it private.

    Checked in a FRESH interpreter: this suite shares one ``server`` module with
    hundreds of tests, and on CI an earlier test left ``server.app`` without the
    DFS routes while this passed locally — in-process state is not evidence of
    how the process boots.  (A 401 alone proves nothing either: the private gate
    answers 401 for unknown /api paths too, so the route list is what counts.)
    """
    import os
    import subprocess
    import sys

    repo = Path(__file__).resolve().parents[2]
    probe = (
        "import json, server; "
        "paths = sorted({getattr(r, 'path', '') for r in server.app.routes if getattr(r, 'path', '').startswith('/api/dfs')}); "
        "print(json.dumps({'paths': paths, 'public': server._is_public_api_path('/api/dfs/capabilities')}))"
    )
    env = {**os.environ, "ALLOW_DEFAULT_LOGIN_DEV": "1", "UPTIME_CHECK_ENABLED": "false"}
    out = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert out.returncode == 0, out.stderr[-2000:]
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert "/api/dfs/capabilities" in result["paths"]
    assert "/api/dfs/builds/{build_id}/export" in result["paths"]
    assert result["public"] is False


def test_guest_pass_sessions_are_scoped_per_pass_not_shared():
    from src.dfs.api import owner_key

    assert (
        owner_key({"username": "guest", "auth_method": "guest_pass", "guest_pass_id": 7})
        == "guest-pass:7"
    )
    assert (
        owner_key({"username": "guest", "auth_method": "guest_pass", "guest_pass_id": 8})
        == "guest-pass:8"
    )
    refused = owner_key({"username": "guest", "auth_method": "guest_pass"})
    assert refused.status_code == 403
    assert owner_key({"username": "jason", "auth_method": "password"}) == "user:jason"


def test_nan_and_malformed_bodies_never_poison_a_stored_build(client):
    snap = _slate(client).json()
    raw = (
        '{"snapshotId": "%s", "objective": "projection_baseline", "constraints": {"maxExposure": NaN}}'
        % snap["snapshotId"]
    )
    r = client.post(
        "/api/dfs/builds",
        content=raw,
        headers={"x-user": "alice", "content-type": "application/json"},
    )
    assert r.status_code == 400 and r.json()["error"] == "INVALID_JSON"
    r = client.post(
        "/api/dfs/builds",
        json={
            "snapshotId": snap["snapshotId"],
            "objective": "projection_baseline",
            "constraints": [1],
        },
        headers={"x-user": "alice"},
    )
    assert r.status_code == 422 and r.json()["error"] == "INVALID_CONSTRAINT"
    assert client.get("/api/dfs/builds", headers={"x-user": "alice"}).json()["builds"] == []
