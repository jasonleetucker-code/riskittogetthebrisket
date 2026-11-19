"""``send_alert`` reaches the owner through ntfy first, e-mail second (STAB-2).

Before: ``send_alert`` (backup and uptime watchdogs, scrape failures, low disk)
returned at once unless Gmail SMTP was configured, and outbound 465 is firewalled
on the production VPS -- so with only ``NOTIFY_WEBHOOK_URL`` set those alerts
reached no one.  Pinned here: push is tried first and, when it delivers, sets the
cooldown and skips SMTP; a failed push falls back to SMTP; with neither channel
configured nothing is started.
"""

from __future__ import annotations

import threading
import time

import pytest

import server
from src.utils import owner_notify


class _RecordingSMTP:
    instances: list[dict] = []

    def __init__(self, host, port, **kwargs):
        type(self).instances.append({"host": host, "port": port})

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, *_a):
        return None

    def send_message(self, *_a):
        return None


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    _RecordingSMTP.instances = []
    monkeypatch.setattr(server, "_last_alert_time", 0)
    monkeypatch.setattr(server, "_alert_in_flight", False)
    monkeypatch.setattr(server.smtplib, "SMTP_SSL", _RecordingSMTP)
    monkeypatch.setattr(server, "ALERT_ENABLED", False)
    monkeypatch.setattr(server, "ALERT_FROM", "")
    monkeypatch.setattr(server, "ALERT_PASSWORD", "")
    monkeypatch.setattr(server, "ALERT_TO", "")
    monkeypatch.delenv("NOTIFY_WEBHOOK_URL", raising=False)
    yield
    for t in threading.enumerate():
        if t.name == "alert-smtp":
            t.join(timeout=5)


def _settle():
    for t in threading.enumerate():
        if t.name == "alert-smtp":
            t.join(timeout=5)


def _email_on(monkeypatch):
    monkeypatch.setattr(server, "ALERT_ENABLED", True)
    monkeypatch.setattr(server, "ALERT_FROM", "box@example.invalid")
    monkeypatch.setattr(server, "ALERT_PASSWORD", "not-a-real-password")
    monkeypatch.setattr(server, "ALERT_TO", "owner@example.invalid")


def test_push_only_delivers_and_sets_the_cooldown(monkeypatch):
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "https://ntfy.sh/private-topic-for-tests")
    pushed = []
    monkeypatch.setattr(owner_notify, "send", lambda title, body, **k: pushed.append(title) or True)
    server.send_alert("Backups stale", "body")
    _settle()
    assert pushed == ["[Dynasty Server] Backups stale"]
    assert server._last_alert_time > 0
    assert _RecordingSMTP.instances == [], "a delivered push must not also send e-mail"


def test_failed_push_falls_back_to_email(monkeypatch):
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "https://ntfy.sh/private-topic-for-tests")
    monkeypatch.setattr(owner_notify, "send", lambda *a, **k: False)
    _email_on(monkeypatch)
    server.send_alert("Uptime failing", "body")
    _settle()
    assert len(_RecordingSMTP.instances) == 1
    assert server._last_alert_time > 0


def test_failed_push_without_email_records_no_cooldown(monkeypatch):
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "https://ntfy.sh/private-topic-for-tests")
    monkeypatch.setattr(owner_notify, "send", lambda *a, **k: False)
    server.send_alert("Uptime failing", "body")
    _settle()
    assert _RecordingSMTP.instances == []
    assert server._last_alert_time == 0, "an undelivered alert must be retried, not cooled down"
    assert server._alert_in_flight is False


def test_nothing_configured_starts_nothing(monkeypatch):
    called = []
    monkeypatch.setattr(owner_notify, "send", lambda *a, **k: called.append(1) or True)
    before = {t.ident for t in threading.enumerate()}
    server.send_alert("anything", "body")
    time.sleep(0.05)
    assert called == []
    assert not [
        t for t in threading.enumerate() if t.name == "alert-smtp" and t.ident not in before
    ]


def test_sweep_recipient_and_delivery(monkeypatch):
    # No channel -> the sweeps report "not configured".
    assert server._owner_alert_recipient() is None
    # Push only -> the stand-in recipient, and the sweep delivery pushes.
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "https://ntfy.sh/private-topic-for-tests")
    from src.utils import owner_alerts

    assert server._owner_alert_recipient() == owner_alerts.OWNER_CHANNEL
    pushed = []
    monkeypatch.setattr(owner_notify, "send", lambda title, body, **k: pushed.append(title) or True)
    assert server._deliver_owner_alert(owner_alerts.OWNER_CHANNEL, "Ops: freshness", "b") is True
    assert pushed == ["Ops: freshness"]
