"""W22-F007 — operator-grade actions gate on the admin allowlist.

The finding: operator-grade endpoints (production scrape trigger,
outbound email send, intel crawl trigger) were gated on session
PRESENCE only, so a guest-pass holder could trigger them.  The repair
routes each through ``_require_admin_session`` (session + the
``PRIVATE_APP_ALLOWED_USERNAMES`` allowlist).

Per endpoint, three states are pinned:

  (a) no session          → 401 (unchanged — middleware or handler)
  (b) non-allowlisted     → 403 ``admin_required``  ← the RED→GREEN
      session               discriminator: pre-fix this succeeded or
                            attempted the action
  (c) allowlisted admin   → neither 401 nor 403; the heavy action runs
                            (mocked — ONLY the side-effecting action is
                            mocked, never the gate)

The action spies double as proof that a rejected request never reaches
the side effect.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import server


@pytest.fixture(autouse=True)
def _stub_allowlist(monkeypatch):
    monkeypatch.setattr(
        server,
        "PRIVATE_APP_ALLOWED_USERNAMES",
        frozenset({"jasonleetucker"}),
    )
    yield


def _authed_admin(monkeypatch):
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(
        server,
        "_get_auth_session",
        lambda r: {"username": "jasonleetucker"},
    )


def _authed_guest(monkeypatch):
    """A session that exists but is NOT allowlisted — the guest-pass
    shape the finding is about (guest sessions carry username
    ``"guest"``, which is never in the allowlist)."""
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(
        server,
        "_get_auth_session",
        lambda r: {"username": "guest", "auth_method": "guest_pass"},
    )


# ── POST /api/scrape ───────────────────────────────────────────────


def _stub_scrape_environment(monkeypatch, calls):
    """Mock ONLY the side-effecting pieces of the scrape path: the
    scraper itself plus the league/status plumbing needed to reach it
    deterministically in a bare test env."""
    cfg = SimpleNamespace(key="dynasty_main", sleeper_league_id="111")
    monkeypatch.setattr(server, "_resolve_league_for_request", lambda *a, **k: cfg)
    monkeypatch.setattr(server._league_registry, "get_default_league", lambda: cfg)
    monkeypatch.setattr(server, "_scrape_status_payload", lambda: {"is_running": False})
    monkeypatch.setattr(server, "_record_scrape_event", lambda *a, **k: None)

    async def fake_run_scraper(trigger: str = "manual"):
        calls.append(trigger)
        return None

    monkeypatch.setattr(server, "run_scraper", fake_run_scraper)


def test_scrape_no_session_is_401():
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/scrape")
    assert res.status_code == 401
    assert res.json().get("error") == "auth_required"


def test_scrape_guest_session_is_403_and_never_scrapes(monkeypatch):
    calls: list[str] = []
    _stub_scrape_environment(monkeypatch, calls)
    _authed_guest(monkeypatch)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/scrape")
    assert res.status_code == 403, res.text
    assert res.json().get("error") == "admin_required"
    assert calls == [], "a 403'd request must never start the scraper"


def test_scrape_admin_session_starts_the_scrape(monkeypatch):
    calls: list[str] = []
    _stub_scrape_environment(monkeypatch, calls)
    _authed_admin(monkeypatch)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/scrape")
    assert res.status_code not in (401, 403), res.text
    assert res.status_code == 200
    # TestClient runs background tasks before returning.
    assert calls == ["manual_api"]


# ── POST /api/test-alert ───────────────────────────────────────────


def _stub_alert_environment(monkeypatch, sent):
    monkeypatch.setattr(server, "ALERT_ENABLED", True)
    monkeypatch.setattr(server, "ALERT_TO", "ops@example.invalid")
    monkeypatch.setattr(server, "send_alert", lambda subject, body: sent.append((subject, body)))


def test_test_alert_no_session_is_401():
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/test-alert")
    assert res.status_code == 401
    assert res.json().get("error") == "auth_required"


def test_test_alert_guest_session_is_403_and_never_sends(monkeypatch):
    sent: list[tuple[str, str]] = []
    _stub_alert_environment(monkeypatch, sent)
    _authed_guest(monkeypatch)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/test-alert")
    assert res.status_code == 403, res.text
    assert res.json().get("error") == "admin_required"
    assert sent == [], "a 403'd request must never send email"


def test_test_alert_admin_session_sends(monkeypatch):
    sent: list[tuple[str, str]] = []
    _stub_alert_environment(monkeypatch, sent)
    _authed_admin(monkeypatch)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/test-alert")
    assert res.status_code not in (401, 403), res.text
    assert res.status_code == 200
    assert len(sent) == 1


# ── POST /api/intel/refresh ────────────────────────────────────────


def _stub_intel_environment(monkeypatch, calls):
    server._intel_refresh_reset_for_tests()
    cfg = SimpleNamespace(key="dynasty_main", sleeper_league_id="111")
    monkeypatch.setattr(server, "_resolve_league_for_request", lambda *a, **k: cfg)
    monkeypatch.setattr(server._intel_service, "refresh_status", lambda: {"isRunning": False})

    def fake_start(**kwargs):
        calls.append(kwargs)
        return {"isRunning": True}

    monkeypatch.setattr(server._intel_service, "start_refresh_async", fake_start)


def test_intel_refresh_no_session_is_401(monkeypatch):
    # Self-authed path: the middleware defers, the handler's own gate
    # answers.  No bearer header and no session → 401.
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/intel/refresh")
    assert res.status_code == 401
    assert res.json().get("error") == "auth_required"


def test_intel_refresh_guest_session_is_403_and_never_crawls(monkeypatch):
    calls: list[dict] = []
    _stub_intel_environment(monkeypatch, calls)
    _authed_guest(monkeypatch)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/intel/refresh")
    assert res.status_code == 403, res.text
    assert res.json().get("error") == "admin_required"
    assert calls == [], "a 403'd request must never start a crawl"


def test_intel_refresh_admin_session_starts_the_crawl(monkeypatch):
    calls: list[dict] = []
    _stub_intel_environment(monkeypatch, calls)
    _authed_admin(monkeypatch)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/intel/refresh")
    assert res.status_code not in (401, 403), res.text
    assert res.status_code == 202
    assert len(calls) == 1


def test_intel_refresh_bearer_cron_path_is_unchanged(monkeypatch):
    """The cron authenticates with a bearer token and no session; the
    admin gate must not apply to it (it is not a browser session at
    all).  Pins that W22-F007 did not break the scheduled driver."""
    calls: list[dict] = []
    _stub_intel_environment(monkeypatch, calls)
    monkeypatch.setattr(server, "INTEL_REFRESH_TOKEN", "sekrit")
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post(
            "/api/intel/refresh",
            headers={"Authorization": "Bearer sekrit"},
        )
    assert res.status_code == 202, res.text
    assert len(calls) == 1
