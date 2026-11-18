"""Task 13 security hardening: A (placeholder password), B (non-ASCII bearer),
C (CSV formula injection), D (health has no side effects), E (production env
guards).  Each test fails on the pre-fix code."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from src.public_league import csv_export

ROOT = Path(__file__).resolve().parents[2]


# ── A / E: startup guards (fresh interpreter, import server) ─────────────
def _import_server(env_overrides: dict[str, str]) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()}
    for k in ("JASON_LOGIN_PASSWORD", "ALLOW_DEFAULT_LOGIN_DEV", "E2E_TEST_MODE", "RISKIT_ENV"):
        env.pop(k, None)
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", "import server"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
    )


@pytest.mark.parametrize("pw", ["changeme", "password", "ChangeMe"])
def test_placeholder_password_refuses_to_start(pw):
    proc = _import_server({"JASON_LOGIN_PASSWORD": pw})
    assert proc.returncode != 0
    assert "placeholder" in proc.stderr


def test_placeholder_password_allowed_with_explicit_dev_hatch():
    proc = _import_server({"JASON_LOGIN_PASSWORD": "changeme", "ALLOW_DEFAULT_LOGIN_DEV": "1"})
    assert proc.returncode == 0, proc.stderr[-500:]


def test_real_password_starts():
    proc = _import_server({"JASON_LOGIN_PASSWORD": "a-genuinely-unique-pw-91x"})
    assert proc.returncode == 0, proc.stderr[-500:]


@pytest.mark.parametrize("flag", ["E2E_TEST_MODE", "ALLOW_DEFAULT_LOGIN_DEV"])
def test_production_refuses_test_switches(flag):
    proc = _import_server(
        {"JASON_LOGIN_PASSWORD": "a-genuinely-unique-pw-91x", "RISKIT_ENV": "production", flag: "1"}
    )
    assert proc.returncode != 0
    assert flag in proc.stderr


def test_production_marker_without_switches_starts():
    proc = _import_server(
        {"JASON_LOGIN_PASSWORD": "a-genuinely-unique-pw-91x", "RISKIT_ENV": "production"}
    )
    assert proc.returncode == 0, proc.stderr[-500:]


def test_systemd_unit_sets_production_marker_after_env_file():
    text = (ROOT / "deploy/systemd/dynasty.service.template").read_text(encoding="utf-8")
    assert text.index("EnvironmentFile=") < text.index("Environment=RISKIT_ENV=production")


# ── B: non-ASCII bearer must be a 401, not a 500 ─────────────────────────
@pytest.mark.parametrize("path", ["/api/signal-alerts/run", "/api/custom-alerts/run"])
def test_non_ascii_bearer_is_401_not_500(monkeypatch, path):
    monkeypatch.setattr(server, "SIGNAL_ALERT_CRON_TOKEN", "configured-token")
    client = TestClient(server.app, raise_server_exceptions=False)
    resp = client.post(path, headers={"authorization": "Bearer café-töken".encode("latin-1")})
    assert resp.status_code in (401, 403), resp.status_code


def test_constant_time_equals_semantics():
    from src.api.startup_guards import constant_time_equals

    assert constant_time_equals("abc", "abc")
    assert not constant_time_equals("abc", "abd")
    assert not constant_time_equals("café", "cafe")
    assert not constant_time_equals("", "x")
    assert not constant_time_equals("", "")
    assert not constant_time_equals("anything", "")


@pytest.mark.parametrize("path", ["/api/signal-alerts/run", "/api/custom-alerts/run"])
def test_unset_cron_token_never_authorizes(monkeypatch, path):
    monkeypatch.setattr(server, "SIGNAL_ALERT_CRON_TOKEN", "")
    client = TestClient(server.app, raise_server_exceptions=False)
    for hdr in ("Bearer ", "Bearer x", None):
        headers = {"authorization": hdr} if hdr is not None else {}
        assert client.post(path, headers=headers).status_code in (401, 403, 503)


# ── C: CSV formula injection ─────────────────────────────────────────────
@pytest.mark.parametrize(
    "text",
    ["=1+1", "+cmd", "-2+3", "@SUM(A1)", "\t=1", "\r=1", " =1", "\n=1", "\x00=1"],
)
def test_formula_text_is_neutralized(text):
    out = csv_export._cell(text)
    assert out == "'" + text


def test_numbers_stay_numbers_including_negative():
    assert csv_export._cell(-3.5) == "-3.5"
    assert csv_export._cell(-7) == "-7"
    assert csv_export._cell(0.25) == "0.25"
    assert csv_export._cell(True) == "true"
    assert csv_export._cell(None) == ""
    assert csv_export._cell("plain text") == "plain text"


def test_nested_values_are_neutralized_as_a_whole():
    assert csv_export._cell(["=x", "y"]) == "'=x | y"
    assert csv_export._cell([1, -2]) == "1 | -2"


def test_written_csv_neutralizes_text_but_not_numbers():
    text = csv_export._write_csv([{"name": '=HYPERLINK("x")', "delta": -3.5}], ["name", "delta"])
    lines = text.splitlines()
    assert lines[1].startswith("\"'=HYPERLINK")
    assert lines[1].endswith(",-3.5")


def test_auction_export_uses_the_same_owner():
    from src.auction import api as auction_api

    assert auction_api._csv_safe(" =1") == "' =1"
    assert auction_api._csv_safe(-4) == -4


# ── D: anonymous health never mails ──────────────────────────────────────
def test_anonymous_health_never_calls_mailer(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "send_alert", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(
        server,
        "_backup_freshness",
        lambda: {
            "newestBackupAgeHours": None,
            "newestBackupPath": None,
            "backupDirUsed": "none",
            "dbCount": 0,
        },
    )
    client = TestClient(server.app, raise_server_exceptions=False)
    client.get("/api/health")
    assert calls == []


def test_backup_watchdog_is_the_sender(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "send_alert", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(
        server,
        "_backup_freshness",
        lambda: {"newestBackupAgeHours": 99, "backupDirUsed": "x", "dbCount": 1},
    )
    assert server._alert_if_backups_stale() is True
    assert len(calls) == 1
    monkeypatch.setattr(
        server,
        "_backup_freshness",
        lambda: {"newestBackupAgeHours": 2, "backupDirUsed": "x", "dbCount": 1},
    )
    assert server._alert_if_backups_stale() is False
    assert len(calls) == 1
