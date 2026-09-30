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
    assert r.status_code == 422 and r.json()["error"] == "UNSUPPORTED_SLATE"
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

    Checked in a FRESH interpreter, and through ``app.openapi()["paths"]`` —
    the public answer to "what routes does this app expose" (same method as
    ``tests/consensus_edge/test_endpoint.py::_registered_paths``).  Walking
    ``app.routes`` is version-dependent: on FastAPI 0.141 ``include_router``
    leaves an ``_IncludedRouter`` wrapper with no ``.path``, so a walk sees
    NO included routes at all.  That — not test-order state — is why this
    test failed twice in CI (0.141) while passing locally (0.135); reproduced
    deterministically on 0.141.1.  A bare 401 would prove nothing either: the
    private gate answers 401 for unknown /api paths too.
    """
    import os
    import subprocess
    import sys

    repo = Path(__file__).resolve().parents[2]
    probe = (
        "import json, server; "
        "paths = sorted(p for p in (server.app.openapi().get('paths') or {}) if p.startswith('/api/dfs')); "
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


def test_distribution_import_is_reported_in_freshness_and_bad_labels_are_422(client):
    proj = (FIX / "synthetic_dk_nfl_classic_projections.csv").read_text(encoding="utf-8")
    snap = _slate(client).json()
    row = next(f for f in snap["freshness"] if f["class"] == "distribution")
    assert row["state"] == "unavailable" and row["coverage"] is None  # none supplied ≠ zero-width

    lines = proj.strip().splitlines()
    with_sd = "\n".join([lines[0] + ",Floor,Ceiling"] + [ln + ",1,30" for ln in lines[1:]]) + "\n"
    snap = _slate(client, projectionCsv=with_sd).json()
    row = next(f for f in snap["freshness"] if f["class"] == "distribution")
    assert row["state"] == "unavailable" and "say which percentiles" in row["note"]

    snap = _slate(client, projectionCsv=with_sd, floorPercentile=15, ceilingPercentile=85).json()
    row = next(f for f in snap["freshness"] if f["class"] == "distribution")
    assert row["state"] == "as_imported" and row["coverage"].startswith("84 of")

    r = _slate(client, projectionCsv=with_sd, floorPercentile=85, ceilingPercentile=15)
    assert r.status_code == 422 and r.json()["error"] == "INVALID_PERCENTILE"


def test_builds_carry_an_outcome_range_only_when_every_player_has_one(client):
    proj = (FIX / "synthetic_dk_nfl_classic_projections.csv").read_text(encoding="utf-8")
    lines = proj.strip().splitlines()
    with_sd = "\n".join([lines[0] + ",StDev"] + [ln + ",5" for ln in lines[1:]]) + "\n"
    for csv_text, expected in ((proj, "unavailable"), (with_sd, "available")):
        snap = _slate(client, projectionCsv=csv_text).json()
        b = client.post(
            "/api/dfs/builds",
            json={"snapshotId": snap["snapshotId"], "objective": "projection_baseline"},
            headers={"x-user": "alice"},
        ).json()
        out = b["result"]["lineups"][0]["outcome"]
        assert out["state"] == expected
        if expected == "available":
            assert out["p10"] < out["p50"] < out["p90"] and out["sd"] == 15.0  # sqrt(9 x 25)
            assert "independent" in b["limits"][0]
        else:
            assert "import player ranges" in b["limits"][0]
