"""Public diagnostics serve no host internals (W22-F005, Workstream A1).

``/api/status`` and ``/api/health`` are anonymous.  Production served, on
2026-10-27 (read-only ``curl https://chaseupside.com/api/status``):

* ``data_runtime.active_data_source.path`` -- the board file's absolute path;
* ``rankHistoryCoverage.path`` / ``playerctxHistoryCoverage.path``;
* ``leagues[].sleeperLeagueId`` -- the raw ids ``/api/leagues`` never serves;
* ``uptime.target_url`` -- the env-derived probe target;

and ``/api/health`` served ``startupChecks.checks[].name ==
"dir:/home/<user>/<checkout>/data"`` three times.

These tests drive the REAL handlers with those internals planted in the
server's own globals -- plus the error branches a healthy box never shows
(a traceback in ``last_error``, a startup-validation crash, a check whose
exception names a path, a secret env value echoed into an error) -- and walk
the WHOLE served response recursively.  The last group plants a field nobody
has written yet, so a future addition to either payload is covered without
anyone remembering this module.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

import server
from src.api import public_diagnostics as pd

_REPO = Path(__file__).resolve().parents[2]
SECRET = "sentinel-Secret-Value-9f3c2a"
HOST_ROOT = "/home/someuser/trade-calculator"


# -- the guard itself ----------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "/home/dynasty/trade-calculator/data/rank_history.jsonl",
        "dir:/var/lib/riskit",
        "not writable: [Errno 13] Permission denied: '/srv/app/data/.probe'",
        "C:\\Users\\jason\\code\\repo\\data",
        "D:/data/file.json",
        "\\\\fileserver\\share\\backups",
        "~/backups/riskit-state",
    ],
)
def test_the_detector_finds_absolute_paths(text):
    assert pd.contains_absolute_path(text)


@pytest.mark.parametrize(
    "text",
    [
        "http://127.0.0.1:8000/api/health",
        "/api/admin/diagnostics",
        "1/30",
        "superflex_tep15_ppr1",
        "2026-10-27T08:37:00+00:00",
        "dynasty_data_2026-10-27.json",
        "dir:data/nfl_data_cache",
        "Scraping KTC",
    ],
)
def test_the_detector_leaves_ordinary_status_text_alone(text):
    assert not pd.contains_absolute_path(text)


def test_the_guard_reports_keys_values_and_depth():
    payload = {
        "a": [{"b": {"path": "x"}}],
        "c": {"/etc/shadow": 1},
        "d": "Traceback (most recent call last):\n  boom",
        "e": f"token={SECRET}",
        "logDir": "x",
    }
    found = dict(pd.unsafe_public_values(payload, environ={"API_TOKEN": SECRET}))
    assert found["$.a[0].b.path"] == "withheld_key"
    assert found["$.c./etc/shadow<key>"] == "absolute_path"
    assert found["$.d"] == "traceback"
    assert found["$.e"] == "env_value"
    assert found["$.logDir"] == "withheld_key"


def test_backup_dir_used_is_a_label_not_a_path():
    assert not pd.is_path_key("backupDirUsed")
    for key in ("path", "newestBackupPath", "log_path", "stateDir", "data_dir", "sleeperLeagueId"):
        assert pd.is_path_key(key), key


def test_short_and_ordinary_env_values_are_not_scrubbed():
    values = pd.secret_env_values(
        {"APP_HOST": "127.0.0.1", "SMTP_PORT_PASS": "1", "MY_TOKEN": SECRET, "PATHEXT": ".EXE;.BAT"}
    )
    assert values == (SECRET,)


# -- named projections -------------------------------------------------------
def test_startup_check_names_become_checkout_relative():
    assert pd.public_check_name(f"dir:{HOST_ROOT}/data", HOST_ROOT) == "dir:data"
    assert (
        pd.public_check_name(f"dir:{HOST_ROOT}/data/nfl_data/actuals", HOST_ROOT)
        == "dir:data/nfl_data/actuals"
    )
    # Outside the checkout: the kind survives, the location does not.
    assert pd.public_check_name("dir:/var/lib/other", HOST_ROOT) == f"dir:{pd.PATH_PLACEHOLDER}"
    assert pd.public_check_name("sqlite:user_kv.sqlite", HOST_ROOT) == "sqlite:user_kv.sqlite"
    assert pd.public_check_name("env:SLEEPER_LEAGUE_ID", HOST_ROOT) == "env:SLEEPER_LEAGUE_ID"


def test_projection_keeps_the_operational_facts():
    raw = {
        "data_runtime": {
            "last_data_refresh_at": "2026-10-27T08:37:00+00:00",
            "active_data_source": {
                "type": "scrape_run",
                "path": f"{HOST_ROOT}/data/dynasty_data_2026-10-27.json",
                "loadedAt": "t",
            },
        },
        "rankHistoryCoverage": {"path": f"{HOST_ROOT}/data/rank_history.jsonl", "snapshots": 99},
        "uptime": {"enabled": True, "target_url": "http://127.0.0.1:8000/api/health"},
        "leagues": [{"key": "dynasty_main", "sleeperLeagueId": "1312006700437352448"}],
    }
    out = pd.public_status_payload(raw, base_dir=HOST_ROOT, environ={})
    src = out["data_runtime"]["active_data_source"]
    assert src == {
        "type": "scrape_run",
        "loadedAt": "t",
        "fileName": "dynasty_data_2026-10-27.json",
        "filesystemPaths": "withheld",
    }
    assert out["rankHistoryCoverage"] == {"snapshots": 99, "filesystemPaths": "withheld"}
    assert out["uptime"] == {"enabled": True, "targetKind": "loopback"}
    assert out["leagues"] == [{"key": "dynasty_main", "externalIds": "withheld"}]
    assert out["publicDiagnostics"]["schemaVersion"] == pd.SCHEMA_VERSION
    assert out["publicDiagnostics"]["fullDiagnostics"] == "/api/admin/diagnostics"
    # The input is a live global's view: never mutated.
    assert "path" in raw["data_runtime"]["active_data_source"]
    assert "sleeperLeagueId" in raw["leagues"][0]
    assert pd.unsafe_public_values(out, environ={}) == []


@pytest.mark.parametrize(
    "url,kind",
    [
        ("http://127.0.0.1:8000/api/health", "loopback"),
        ("http://localhost:8000/x", "loopback"),
        ("https://user:pw@monitor.example.com/ping", "external"),
        ("", "unset"),
        (None, "unset"),
    ],
)
def test_target_kind(url, kind):
    assert pd._target_kind(url) == kind


# -- the served responses, end to end -----------------------------------------
@pytest.fixture
def planted(monkeypatch):
    """Plant every known internal, and the error branches, in server state."""
    monkeypatch.setenv("SMTP_PASSWORD", SECRET)
    monkeypatch.setattr(server, "BASE_DIR", Path(HOST_ROOT))
    monkeypatch.setattr(
        server,
        "latest_data_source",
        {
            "type": "scrape_run",
            "path": f"{HOST_ROOT}/data/dynasty_data_2026-10-27.json",
            "loadedAt": "2026-10-27T08:37:06+00:00",
            "producedAt": "2026-10-27T08:37:00+00:00",
        },
    )
    monkeypatch.setitem(server.uptime_status, "target_url", "http://127.0.0.1:8000/api/health")
    monkeypatch.setitem(server.uptime_status, "last_error", f"connect failed: {HOST_ROOT}/sock")
    traceback_text = (
        "Traceback (most recent call last):\n"
        f'  File "{HOST_ROOT}/server.py", line 10, in run\n'
        f"RuntimeError: password={SECRET}"
    )
    monkeypatch.setitem(server.scrape_status, "last_error", traceback_text)
    monkeypatch.setitem(server.scrape_status, "error", f"open failed: {HOST_ROOT}/data/x.json")
    monkeypatch.setattr(
        server,
        "_startup_checks_summary",
        {
            "total": 3,
            "ok": 1,
            "failed": 2,
            "fatal": 0,
            "checks": [
                {"name": f"dir:{HOST_ROOT}/data", "ok": True, "message": "writable", "context": {}},
                {
                    "name": "dir:/var/lib/elsewhere",
                    "ok": False,
                    "message": "not writable: [Errno 13] Permission denied: '/var/lib/elsewhere/.p'",
                    "context": {"error": "[Errno 13] Permission denied: '/var/lib/elsewhere/.p'"},
                },
                {
                    "name": "sqlite:user_kv.sqlite",
                    "ok": False,
                    "message": f"open failed: unable to open {HOST_ROOT}/data/user_kv.sqlite",
                    "context": {"error": f"C:\\Users\\op\\repo\\data\\user_kv.sqlite {SECRET}"},
                },
            ],
        },
    )
    monkeypatch.setattr(
        server,
        "_rank_history_coverage_safe",
        lambda: {"path": f"{HOST_ROOT}/data/rank_history.jsonl", "exists": True, "snapshots": 9},
    )
    monkeypatch.setattr(
        server,
        "_playerctx_history_coverage_safe",
        lambda: {"path": f"{HOST_ROOT}/data/playerctx/history", "exists": True, "pendingPush": 1},
    )
    monkeypatch.setattr(server, "send_alert", lambda *a, **k: None)
    return monkeypatch


def _served(handler) -> tuple[int, dict, str]:
    response = asyncio.run(handler())
    text = response.body.decode("utf-8")
    return response.status_code, json.loads(text), text


@pytest.mark.parametrize("handler_name", ["get_status", "get_health"])
def test_served_response_carries_no_internal_anywhere(planted, handler_name):
    _code, body, text = _served(getattr(server, handler_name))
    problems = pd.unsafe_public_values(body)
    assert problems == [], problems
    # Belt and braces over the raw bytes, independent of the walker.
    assert HOST_ROOT not in text
    assert SECRET not in text
    assert "/var/lib/elsewhere" not in text
    assert "Traceback" not in text
    assert "1312006700437352448" not in text
    assert "127.0.0.1:8000" not in text
    assert body["publicDiagnostics"]["filesystemPaths"] == "withheld"


def test_status_keeps_what_monitoring_reads(planted):
    """deploy.yml, health-check.yml, verify-deploy.sh, verify_owner_held_flags
    and verify_lane4_production read these; none of them reads a path."""
    _code, body, _text = _served(server.get_status)
    for key in (
        "build",
        "contract",
        "data_runtime",
        "source_health",
        "backup_health",
        "served_source_coverage",
        "served_seasonal_inactive",
        "served_private_absent_by_design",
        "featureFlags",
        "has_data",
        "player_count",
        "leagues",
        "rankHistoryCoverage",
        "playerctxHistoryCoverage",
    ):
        assert key in body, key
    assert "commit" in body["build"] and "release" in body["build"]
    runtime = body["data_runtime"]
    assert runtime["last_data_refresh_at"] == "2026-10-27T08:37:00+00:00"
    assert runtime["last_payload_loaded_at"] == "2026-10-27T08:37:06+00:00"
    assert runtime["active_data_source"]["fileName"] == "dynasty_data_2026-10-27.json"
    assert body["rankHistoryCoverage"]["snapshots"] == 9
    assert body["playerctxHistoryCoverage"]["pendingPush"] == 1
    assert "newestBackupAgeHours" in body["backup_health"]


def test_health_keeps_its_verdicts_and_status_code(planted):
    code, body, _text = _served(server.get_health)
    full_code, full = server._health_content(send_alerts=False)
    assert code == full_code
    for key in ("status", "has_data", "data_stale", "contract_ok", "source_health_ok"):
        assert body[key] == full[key], key
    names = [c["name"] for c in body["startupChecks"]["checks"]]
    assert names == ["dir:data", f"dir:{pd.PATH_PLACEHOLDER}", "sqlite:user_kv.sqlite"]
    assert body["startupChecks"]["failed"] == 2
    assert body["uptime_watchdog"] == {
        "enabled": server.uptime_status["enabled"],
        "targetKind": "loopback",
    }


def test_startup_validation_crash_branch_is_safe(planted):
    planted.setattr(
        server,
        "_startup_checks_summary",
        {"error": f"[Errno 2] No such file: '{HOST_ROOT}/config/x.json'", "total": 0, "failed": 1},
    )
    _code, body, text = _served(server.get_health)
    assert pd.unsafe_public_values(body) == []
    assert HOST_ROOT not in text
    assert body["startupChecks"]["failed"] == 1


@pytest.mark.parametrize("handler_name", ["get_status", "get_health"])
def test_a_field_added_later_is_public_safe_without_anyone_remembering(planted, handler_name):
    """The guard for the future: a new diagnostic that leaks is scrubbed."""
    future = {
        "brandNewPath": "/opt/whatever",
        "storeDir": "/var/lib/riskit/store",
        "note": f"cache at {HOST_ROOT}/data/cache and ~/.config/riskit",
        "nested": [{"deeper": {"why": f"C:\\Users\\op\\data {SECRET}"}}],
        f"{HOST_ROOT}/keyed": 1,
    }
    planted.setattr(server, "_nfl_data_provider_status_safe", lambda: future)
    if handler_name == "get_health":
        from src.utils import circuit_breaker as cb

        planted.setattr(
            cb, "snapshot_all", lambda: [{"name": "x", "lastError": future["note"], **future}]
        )
    _code, body, text = _served(getattr(server, handler_name))
    assert pd.unsafe_public_values(body) == []
    assert HOST_ROOT not in text and SECRET not in text and "/opt/whatever" not in text


# -- the private side ----------------------------------------------------------
def _admin_session(monkeypatch, result):
    monkeypatch.setattr(server, "_require_admin_session", lambda request: result)


def test_admin_diagnostics_requires_the_admin_session(planted):
    denied = server.JSONResponse(status_code=403, content={"error": "admin_required"})
    _admin_session(planted, denied)
    response = asyncio.run(server.get_admin_diagnostics(object()))
    assert response.status_code == 403


def test_admin_diagnostics_serves_the_unredacted_content(planted):
    alerts: list = []
    planted.setattr(server, "send_alert", lambda *a, **k: alerts.append(a))
    _admin_session(planted, {"username": "operator"})
    response = asyncio.run(server.get_admin_diagnostics(object()))
    body = json.loads(response.body)
    assert body["redaction"] == "none"
    assert body["status"]["data_runtime"]["active_data_source"]["path"].startswith(HOST_ROOT)
    assert body["status"]["rankHistoryCoverage"]["path"].startswith(HOST_ROOT)
    assert body["health"]["startupChecks"]["checks"][0]["name"] == f"dir:{HOST_ROOT}/data"
    assert body["health"]["httpStatus"] in (200, 503)
    assert response.headers["cache-control"] == "no-store"
    assert alerts == [], "reading diagnostics must never send the stale-backup e-mail"


def test_admin_diagnostics_route_is_registered_and_private():
    paths = server.app.openapi()["paths"]
    assert "/api/admin/diagnostics" in paths
    assert not server._is_public_api_path("/api/admin/diagnostics")
    assert server._is_public_api_path("/api/status")
    assert server._is_public_api_path("/api/health")


def test_anonymous_admin_diagnostics_is_401():
    from fastapi.testclient import TestClient

    with TestClient(server.app, raise_server_exceptions=True) as client:
        res = client.get("/api/admin/diagnostics")
    assert res.status_code == 401
    assert res.json().get("error") == "auth_required"


# -- consumers ---------------------------------------------------------------
_CONSUMERS = [
    ".github/workflows/deploy.yml",
    ".github/workflows/health-check.yml",
    ".github/workflows/smoke-test.yml",
    "deploy/verify-deploy.sh",
    "deploy/deploy.sh",
    "scripts/verify_owner_held_flags.py",
    "scripts/verify_live_source_coverage.py",
    "scripts/verify_lane4_production.py",
    "frontend/components/admin/ServerStatusPanel.jsx",
    "frontend/components/StaleDataBanner.jsx",
    "frontend/components/SourceHealthStrip.jsx",
]


@pytest.mark.parametrize("rel", _CONSUMERS)
def test_no_status_consumer_reads_a_withheld_field(rel):
    """Every reader of /api/status and /api/health keeps working: none of them
    reads a field this projection withholds.  A consumer that needs one must
    move to ``/api/admin/diagnostics``."""
    text = (_REPO / rel).read_text(encoding="utf-8", errors="replace")
    for field in ("active_data_source", "sleeperLeagueId", "target_url"):
        assert not re.search(rf"[\"'\[.]{field}[\"'\]]", text), (rel, field)
    assert "HistoryCoverage" not in text or '"path"' not in text, rel
