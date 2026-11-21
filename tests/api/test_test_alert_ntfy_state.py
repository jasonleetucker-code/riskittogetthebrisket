"""``POST /api/test-alert`` says WHY the push channel is off (2026-11-20).

A ``NOTIFY_WEBHOOK_URL`` the validator rejects used to read exactly like an
unset one (``400 no_alert_channel_configured``).  The response now carries
``ntfyState`` (``ok`` / ``unset`` / ``rejected:<reason>``) beside the
``configured`` booleans, and the hint names the reason -- never the value.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server
from src.utils import owner_alerts, owner_notify

TOPIC = "https://ntfy.sh/private-topic-for-tests"


@pytest.fixture(autouse=True)
def _admin(monkeypatch):
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda r: {"username": "jasonleetucker"})
    monkeypatch.setattr(server, "ALERT_ENABLED", False)
    monkeypatch.setattr(server, "ALERT_TO", "")
    monkeypatch.delenv("NOTIFY_WEBHOOK_URL", raising=False)
    owner_alerts.reset_delivery_health_for_tests()
    yield
    owner_alerts.reset_delivery_health_for_tests()


def _post():
    with TestClient(server.app, raise_server_exceptions=True) as c:
        return c.post("/api/test-alert")


def test_a_rejected_webhook_is_reported_with_its_reason(monkeypatch):
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "http://ntfy.sh/private-topic-for-tests")
    res = _post()
    assert res.status_code == 400
    body = res.json()
    assert body["error"] == "no_alert_channel_configured"
    assert body["ntfyState"] == "rejected:scheme"
    assert body["configured"] == {"ntfy": False, "email": False}
    assert "rejected (scheme)" in body["hint"]
    assert "private-topic" not in res.text


def test_an_unset_webhook_is_reported_as_unset():
    res = _post()
    assert res.status_code == 400
    assert res.json()["ntfyState"] == "unset"
    assert "rejected" not in res.json()["hint"]


def test_a_valid_webhook_is_ok_and_sends(monkeypatch):
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", TOPIC)
    sent = []
    monkeypatch.setattr(owner_notify, "send", lambda title, body, **k: sent.append(title) or True)
    res = _post()
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ntfyState"] == "ok"
    assert body["delivered"] == {"ntfy": True, "email": None}
    assert sent == ["Risk It test alert"]
    assert "private-topic" not in res.text
