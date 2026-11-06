"""Permanent regression tests for private / admin / mutating routes (CW-50 / CW-07).

The 2026-11-06 feature census found these routes with no test at all:

* ``POST /api/ros/refresh``            (admin)
* ``POST /api/auth/logout``
* ``POST /api/user/signals/restore``
* ``GET  /api/admin/scrape-telemetry`` (admin)
* ``GET  /api/ros/sources``
* ``GET  /api/sharp/roster-percentage/audit``

Real sessions are minted through ``server._create_auth_session`` and replayed as
a ``Cookie`` header (the production cookie is ``Secure``, which the plain-http
TestClient jar would refuse to send back).  Every external effect (scrape,
telemetry files, sharp store, user_kv, session store) is stubbed or redirected
to ``tmp_path`` — offline and deterministic.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server
from src.api import session_store, user_kv

ADMIN = "jasonleetucker"
OTHER = "randomuser"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "PRIVATE_APP_ALLOWED_USERNAMES", frozenset({ADMIN}))
    monkeypatch.setattr(session_store, "_DEFAULT_DB_PATH", tmp_path / "sessions.sqlite")
    session_store._setup_done.clear()  # noqa: SLF001
    monkeypatch.setattr(user_kv, "USER_KV_PATH", tmp_path / "user_kv.sqlite")
    saved = dict(server.auth_sessions)
    yield
    server.auth_sessions.clear()
    server.auth_sessions.update(saved)
    session_store._setup_done.clear()  # noqa: SLF001


def _cookie(username: str) -> dict[str, str]:
    sid = server._create_auth_session(username)  # noqa: SLF001
    return {"Cookie": f"{server.JASON_AUTH_COOKIE_NAME}={sid}"}


@pytest.fixture
def client():
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c


# ── POST /api/ros/refresh ──────────────────────────────────────────────


@pytest.fixture
def ros_runs(monkeypatch):
    import src.ros.scrape as ros_scrape

    calls: list[dict] = []

    def _fake_run_all(*, overrides=None, **_kw):
        calls.append({"overrides": overrides})
        return {"ok": True, "ran": 0}

    monkeypatch.setattr(ros_scrape, "run_all", _fake_run_all)
    return calls


def test_ros_refresh_anonymous_is_401_and_runs_nothing(client, ros_runs):
    res = client.post("/api/ros/refresh", json={})
    assert res.status_code == 401
    assert ros_runs == []


def test_ros_refresh_non_admin_is_refused_and_runs_nothing(client, ros_runs):
    """Authenticated but not allowlisted: must NOT trigger the orchestrator.

    Regression: the handler tested ``not _require_admin_session(...)`` but that
    helper returns a (truthy) JSONResponse on failure, so any signed-in user
    could start a scrape.
    """
    res = client.post("/api/ros/refresh", json={}, headers=_cookie(OTHER))
    assert res.status_code in (401, 403)
    assert ros_runs == []


def test_ros_refresh_admin_runs_with_sanitized_overrides(client, ros_runs):
    body = {
        "sourceOverrides": {
            "a": {"enabled": 0, "weight": "2.5"},
            "b": {"weight": -1},
            "c": "junk",
        }
    }
    res = client.post("/api/ros/refresh", json=body, headers=_cookie(ADMIN))
    assert res.status_code == 200
    assert res.json() == {"ok": True, "ran": 0}
    assert ros_runs == [{"overrides": {"a": {"enabled": False, "weight": 2.5}}}]


def test_ros_refresh_admin_bad_body_is_not_a_500(client, ros_runs):
    res = client.post(
        "/api/ros/refresh",
        content=b"{not json",
        headers={**_cookie(ADMIN), "Content-Type": "application/json"},
    )
    assert res.status_code == 200
    assert ros_runs == [{"overrides": None}]


# ── GET /api/ros/sources ───────────────────────────────────────────────


def test_ros_sources_anonymous_is_401(client):
    assert client.get("/api/ros/sources").status_code == 401


def test_ros_sources_authenticated_shape_hides_scraper_internals(client):
    from src.ros.sources import ROS_SOURCES

    res = client.get("/api/ros/sources", headers=_cookie(OTHER))
    assert res.status_code == 200
    sources = res.json()["sources"]
    assert [s["key"] for s in sources] == [s["key"] for s in ROS_SOURCES]
    for s in sources:
        assert "scraper" not in s
        assert isinstance(s["effectivelyEnabled"], bool)


# ── POST /api/auth/logout ──────────────────────────────────────────────


def test_logout_invalidates_session_server_side_and_clears_cookie(client):
    headers = _cookie(OTHER)
    sid = headers["Cookie"].split("=", 1)[1]
    assert client.get("/api/ros/sources", headers=headers).status_code == 200
    assert sid in server.auth_sessions

    res = client.post("/api/auth/logout", headers=headers)
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    # Cleared with the same name + path, immediately expired.
    set_cookie = res.headers["set-cookie"].lower()
    assert f"{server.JASON_AUTH_COOKIE_NAME}=" in set_cookie
    assert "path=/" in set_cookie
    assert "max-age=0" in set_cookie
    # Server-side: memory AND the persisted store no longer know the session.
    assert sid not in server.auth_sessions
    assert session_store.hydrate(db_path=session_store._DEFAULT_DB_PATH) == {}  # noqa: SLF001
    # Replaying the OLD cookie is anonymous.
    assert client.get("/api/ros/sources", headers=headers).status_code == 401


def test_logout_only_ends_the_callers_session(client):
    a, b = _cookie(OTHER), _cookie("someoneelse")
    assert client.post("/api/auth/logout", headers=a).status_code == 200
    assert client.get("/api/ros/sources", headers=b).status_code == 200


def test_logout_without_session_is_safe_and_idempotent(client):
    for _ in range(2):
        res = client.post("/api/auth/logout")
        assert res.status_code == 200
        assert res.json() == {"ok": True}
    bogus = {"Cookie": f"{server.JASON_AUTH_COOKIE_NAME}=does-not-exist"}
    assert client.post("/api/auth/logout", headers=bogus).status_code == 200


# ── POST /api/user/signals/restore ─────────────────────────────────────


def test_signals_restore_anonymous_is_401_and_changes_nothing(client):
    user_kv.dismiss_signal(OTHER, "sig1")
    before = user_kv.get_user_state(OTHER)
    res = client.post("/api/user/signals/restore", json={"signalKey": "sig1"})
    assert res.status_code == 401
    assert user_kv.get_user_state(OTHER) == before
    assert "sig1" in user_kv.active_dismissals(OTHER)


def test_signals_restore_removes_only_the_callers_dismissal(client):
    user_kv.dismiss_signal("alice", "sigX")
    user_kv.dismiss_signal("bob", "sigX")
    res = client.post(
        "/api/user/signals/restore", json={"signalKey": "sigX"}, headers=_cookie("alice")
    )
    assert res.status_code == 200
    assert res.json()["username"] == "alice"
    assert "sigX" not in user_kv.active_dismissals("alice")
    # Cross-user isolation: bob's dismissal is untouched.
    assert "sigX" in user_kv.active_dismissals("bob")


def test_signals_restore_ignores_body_supplied_username(client):
    """The target user comes from the session, never the request body."""
    user_kv.dismiss_signal("victim", "sigY")
    res = client.post(
        "/api/user/signals/restore",
        json={"signalKey": "sigY", "username": "victim"},
        headers=_cookie("attacker"),
    )
    assert res.status_code == 200
    assert res.json()["username"] == "attacker"
    assert "sigY" in user_kv.active_dismissals("victim")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"content": b"{broken", "headers": {"Content-Type": "application/json"}},
        {"json": ["not", "a", "dict"]},
        {"json": None},
        {"json": {}},
        {"json": {"signalKey": "   "}},
    ],
)
def test_signals_restore_bad_body_is_4xx_never_500(client, kwargs):
    kwargs = dict(kwargs)
    extra = kwargs.pop("headers", {})
    res = client.post("/api/user/signals/restore", headers={**_cookie(OTHER), **extra}, **kwargs)
    assert 400 <= res.status_code < 500


def test_signals_restore_league_scoped_bucket_only(client):
    from src.api import league_registry

    cfg = league_registry.get_league_by_key("dynasty_main")
    if cfg is None or not cfg.active:
        pytest.skip("dynasty_main not active in this registry")
    user_kv.dismiss_signal(OTHER, "s", league_key=cfg.key)
    user_kv.dismiss_signal(OTHER, "s")  # flat bucket
    res = client.post(
        "/api/user/signals/restore",
        json={"signalKey": "s", "leagueKey": cfg.key},
        headers=_cookie(OTHER),
    )
    assert res.status_code == 200
    assert "s" not in user_kv.active_dismissals(OTHER, league_key=cfg.key)
    assert "s" in user_kv.active_dismissals(OTHER)


# ── GET /api/admin/scrape-telemetry ────────────────────────────────────


@pytest.fixture
def telemetry_files(monkeypatch, tmp_path):
    from src.diagnostics import scrape_telemetry as tel

    events = tmp_path / "events.jsonl"
    samples = tmp_path / "samples.jsonl"
    events.write_text('{"e":1}\n{"e":2}\n{"e":3}\n', encoding="utf-8")
    samples.write_text('{"s":1}\n', encoding="utf-8")
    monkeypatch.setattr(tel, "EVENTS_PATH", events)
    monkeypatch.setattr(tel, "SAMPLES_PATH", samples)
    monkeypatch.setattr(tel, "read_phase", lambda: {"phase": "idle"})


def test_scrape_telemetry_anonymous_is_401(client, telemetry_files):
    assert client.get("/api/admin/scrape-telemetry").status_code == 401


def test_scrape_telemetry_non_admin_is_403_without_leaking(client, telemetry_files):
    res = client.get("/api/admin/scrape-telemetry", headers=_cookie(OTHER))
    assert res.status_code == 403
    assert res.json()["error"] == "admin_required"
    assert "serverPid" not in res.text and "events" not in res.json()


def test_scrape_telemetry_admin_shape_and_limit_cap(client, telemetry_files):
    res = client.get("/api/admin/scrape-telemetry?limit=2", headers=_cookie(ADMIN))
    assert res.status_code == 200
    body = res.json()
    assert body["limit"] == 2
    assert body["events"] == [{"e": 2}, {"e": 3}]
    assert body["samples"] == [{"s": 1}]
    assert body["eventCount"] == 2 and body["sampleCount"] == 1
    assert body["currentPhase"] == {"phase": "idle"}
    assert body["files"]["events"]["exists"] is True
    big = client.get("/api/admin/scrape-telemetry?limit=999999", headers=_cookie(ADMIN))
    assert big.json()["limit"] == 5000
    low = client.get("/api/admin/scrape-telemetry?limit=-5", headers=_cookie(ADMIN))
    assert low.status_code == 200 and low.json()["limit"] == 1


# ── GET /api/sharp/roster-percentage/audit ─────────────────────────────


@pytest.fixture
def sharp_audit(monkeypatch):
    seen: list[tuple] = []

    def _fake(asset_id, **kw):
        seen.append((asset_id, kw))
        if asset_id == "bad":
            raise ValueError("unknown asset")
        if asset_id == "boom":
            raise RuntimeError("db down")
        return {"assetId": asset_id, "rosters": [], "excluded": []}

    monkeypatch.setattr(server._sharp_service, "roster_percentage_audit_payload", _fake)  # noqa: SLF001
    return seen


def test_sharp_audit_anonymous_is_401_and_never_reaches_the_store(client, sharp_audit):
    res = client.get("/api/sharp/roster-percentage/audit?assetId=p:1")
    assert res.status_code == 401
    assert sharp_audit == []
    assert "rosters" not in res.text


def test_sharp_audit_authenticated_shape_and_params(client, sharp_audit):
    res = client.get(
        "/api/sharp/roster-percentage/audit?assetId=p:1&qualification=curated",
        headers=_cookie(OTHER),
    )
    assert res.status_code == 200
    assert res.json() == {"assetId": "p:1", "rosters": [], "excluded": []}
    assert sharp_audit == [("p:1", {"qualification": "curated"})]


def test_sharp_audit_missing_asset_is_400(client, sharp_audit):
    res = client.get("/api/sharp/roster-percentage/audit", headers=_cookie(OTHER))
    assert res.status_code == 400
    assert res.json()["error"] == "missing_param"
    assert sharp_audit == []


def test_sharp_audit_error_mapping(client, sharp_audit):
    h = _cookie(OTHER)
    assert (
        client.get("/api/sharp/roster-percentage/audit?assetId=bad", headers=h).status_code == 400
    )
    boom = client.get("/api/sharp/roster-percentage/audit?assetId=boom", headers=h)
    assert boom.status_code == 503
    assert boom.json()["error"] == "sharp_roster_percentage_unavailable"


# ── structural guard: the admin gate's refusal is truthy ─────────────────
#
# ``_require_admin_session`` returns the session dict on success and a truthy
# ``JSONResponse`` on failure, so ``if not _require_admin_session(...)`` can never
# refuse anyone — the exact defect /api/ros/refresh shipped with.  Scan every
# backend module so the pattern cannot return anywhere.


def _admin_gate_truthiness_tests() -> list[str]:
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    files = [root / "server.py", *sorted((root / "src").rglob("*.py"))]
    offenders: list[str] = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.If, ast.IfExp, ast.While, ast.Assert, ast.BoolOp)):
                continue
            tests = node.values if isinstance(node, ast.BoolOp) else [node.test]
            for test in tests:
                if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
                    test = test.operand
                if not isinstance(test, ast.Call):
                    continue
                fn = test.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if name == "_require_admin_session":
                    offenders.append(f"{path.relative_to(root)}:{node.lineno}")
    return offenders


def test_no_code_tests_the_admin_gate_for_truthiness():
    assert _admin_gate_truthiness_tests() == []
