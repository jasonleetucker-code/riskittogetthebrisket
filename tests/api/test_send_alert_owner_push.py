"""``send_alert`` reaches the owner through ntfy first, e-mail second (STAB-2).

Before: ``send_alert`` (backup and uptime watchdogs, scrape failures, low disk)
returned at once unless Gmail SMTP was configured, and outbound 465 is firewalled
on the production VPS -- so with only ``NOTIFY_WEBHOOK_URL`` set those alerts
reached no one.  Pinned here: push is tried first and, when it delivers, sets the
cooldown and skips SMTP; a failed push falls back to SMTP (587 first, through the
one e-mail owner); with neither channel configured nothing is started.

2026-11-20: the cooldown is PER ALERT CLASS (``key``) -- one global window used
to let a delivered uptime alert silence a stale-backup alert and swallow "Uptime
recovered" -- and recovery classes are never cooled down.
"""

from __future__ import annotations

import threading
import time

import pytest

import server
from src.utils import owner_alerts, owner_notify

PUSH = "https://ntfy.sh/private-topic-for-tests"


class _RecordingSMTP:
    instances: list[dict] = []

    def __init__(self, host, port, **kwargs):
        type(self).instances.append({"host": host, "port": port})

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, *_a, **_k):
        return None

    def login(self, *_a):
        return None

    def send_message(self, *_a):
        return None


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    _RecordingSMTP.instances = []
    monkeypatch.setattr(server, "_last_alert_time_by_key", {})
    monkeypatch.setattr(server, "_alerts_in_flight", set())
    monkeypatch.setattr(server, "_alert_unconfigured_logged_at", {})
    monkeypatch.setattr(server.smtplib, "SMTP", _RecordingSMTP)
    monkeypatch.setattr(server.smtplib, "SMTP_SSL", _RecordingSMTP)
    owner_alerts.reset_delivery_health_for_tests()
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
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", PUSH)
    pushed = []
    monkeypatch.setattr(owner_notify, "send", lambda title, body, **k: pushed.append(title) or True)
    server.send_alert("Backups stale", "body", key=server.ALERT_KEY_BACKUP_STALE)
    _settle()
    assert pushed == ["[Dynasty Server] Backups stale"]
    assert server._last_alert_time_by_key.get(server.ALERT_KEY_BACKUP_STALE)
    assert _RecordingSMTP.instances == [], "a delivered push must not also send e-mail"


def test_failed_push_falls_back_to_email_587_first(monkeypatch):
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", PUSH)
    monkeypatch.setattr(owner_notify, "send", lambda *a, **k: False)
    _email_on(monkeypatch)
    server.send_alert("Uptime failing", "body", key=server.ALERT_KEY_UPTIME)
    _settle()
    # The one e-mail owner (``_deliver_email_smtp``): 587 STARTTLS delivered,
    # so the firewalled 465 was never tried.
    assert [i["port"] for i in _RecordingSMTP.instances] == [587]
    assert server._last_alert_time_by_key.get(server.ALERT_KEY_UPTIME)


def test_failed_push_without_email_records_no_cooldown(monkeypatch):
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", PUSH)
    monkeypatch.setattr(owner_notify, "send", lambda *a, **k: False)
    server.send_alert("Uptime failing", "body", key=server.ALERT_KEY_UPTIME)
    _settle()
    assert _RecordingSMTP.instances == []
    assert (
        server._last_alert_time_by_key == {}
    ), "an undelivered alert must be retried, not cooled down"
    assert server._alerts_in_flight == set()


def _pushes(monkeypatch, results=None):
    """Record every push title; ``results`` (a list) scripts each outcome."""
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", PUSH)
    pushed: list[str] = []

    def fake_send(title, body, **_k):
        pushed.append(title)
        return results.pop(0) if results else True

    monkeypatch.setattr(owner_notify, "send", fake_send)
    return pushed


def test_different_classes_do_not_suppress_each_other(monkeypatch):
    pushed = _pushes(monkeypatch)
    server.send_alert("Uptime failing", "b", key=server.ALERT_KEY_UPTIME)
    _settle()
    server.send_alert("Risk It: SQLite backups stale", "b", key=server.ALERT_KEY_BACKUP_STALE)
    _settle()
    server.send_alert("Scrape failed: X", "b", key=server.ALERT_KEY_SCRAPE_FAILURE)
    _settle()
    assert pushed == [
        "[Dynasty Server] Uptime failing",
        "[Dynasty Server] Risk It: SQLite backups stale",
        "[Dynasty Server] Scrape failed: X",
    ]
    # ...while the SAME class is still cooled down.
    server.send_alert("Uptime failing", "b", key=server.ALERT_KEY_UPTIME)
    _settle()
    assert len(pushed) == 3


def test_recovery_is_sent_inside_the_window_and_rearms_its_class(monkeypatch):
    pushed = _pushes(monkeypatch)
    server.send_alert("Uptime check failing (2 consecutive)", "b", key=server.ALERT_KEY_UPTIME)
    _settle()
    # Minutes later -- well inside the one-hour window -- the site is back.
    server.send_alert("Uptime recovered", "b", key=server.ALERT_KEY_UPTIME_RECOVERY)
    _settle()
    assert pushed[-1] == "[Dynasty Server] Uptime recovered"
    # The incident is closed, so a NEW failure is announced at once.
    server.send_alert("Uptime check failing (2 consecutive)", "b", key=server.ALERT_KEY_UPTIME)
    _settle()
    assert len(pushed) == 3
    # And a recovery is never cooled down by an earlier recovery.
    server.send_alert("Uptime recovered", "b", key=server.ALERT_KEY_UPTIME_RECOVERY)
    _settle()
    assert len(pushed) == 4


def test_an_undelivered_alert_sets_no_cooldown_and_is_retried(monkeypatch):
    pushed = _pushes(monkeypatch, results=[False, True])
    server.send_alert("Disk low", "b", key=server.ALERT_KEY_DISK_LOW)
    _settle()
    assert server._last_alert_time_by_key == {}
    server.send_alert("Disk low", "b", key=server.ALERT_KEY_DISK_LOW)
    _settle()
    assert len(pushed) == 2
    assert server._last_alert_time_by_key.get(server.ALERT_KEY_DISK_LOW)


def test_every_caller_names_its_class():
    """No production ``send_alert`` call may fall back to the shared default
    class -- that would bring back one window silencing another."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path(server.__file__).read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "send_alert"
    ]
    assert len(calls) >= 6
    unnamed = [c.lineno for c in calls if not any(k.arg == "key" for k in c.keywords)]
    assert unnamed == [], f"send_alert without key= at server.py lines {unnamed}"


def test_delivery_is_recorded_in_alert_delivery_health(monkeypatch):
    _pushes(monkeypatch, results=[False, False, True])
    for _ in range(2):
        server.send_alert("Disk low", "b", key=server.ALERT_KEY_DISK_LOW)
        _settle()
    health = owner_alerts.delivery_health()
    assert health["consecutiveFailures"] == 2 and health["lastFailedAt"]
    assert health["lastDeliveredAt"] is None
    server.send_alert("Disk low", "b", key=server.ALERT_KEY_DISK_LOW)
    _settle()
    health = owner_alerts.delivery_health()
    assert health["consecutiveFailures"] == 0 and health["lastDeliveredAt"]


def test_nothing_configured_logs_once_per_class_window(monkeypatch, caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        server.send_alert("Uptime failing", "b", key=server.ALERT_KEY_UPTIME)
        server.send_alert("Uptime failing", "b", key=server.ALERT_KEY_UPTIME)
    lines = [r.getMessage() for r in caplog.records if "no owner alert channel" in r.getMessage()]
    assert len(lines) == 1
    assert "ntfy.sh" not in lines[0]


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
