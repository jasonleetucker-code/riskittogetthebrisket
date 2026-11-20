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
    monkeypatch.setattr(server, "_alert_incident_open", set())
    monkeypatch.setattr(server, "_alert_recovery_deferred", {})
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
    """Join every delivery thread, including one started by another (a deferred
    recovery is sent from the thread that delivered its failure alert)."""
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        threads = [t for t in threading.enumerate() if t.name == "alert-smtp"]
        if not threads:
            return
        for t in threads:
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


FAILING = "Uptime check failing (2 consecutive)"
RECOVERED = "Uptime recovered"


def _fail():
    server.send_alert(FAILING, "b", key=server.ALERT_KEY_UPTIME)
    _settle()


def _recover():
    server.send_alert(RECOVERED, "b", key=server.ALERT_KEY_UPTIME_RECOVERY)
    _settle()


def test_one_outage_is_one_failure_and_one_recovery_inside_the_window(monkeypatch):
    pushed = _pushes(monkeypatch)
    _fail()
    # Minutes later -- well inside the one-hour window -- the site is back.
    _recover()
    assert pushed == [f"[Dynasty Server] {FAILING}", f"[Dynasty Server] {RECOVERED}"]
    assert server._alert_incident_open == set()


def test_a_recovery_does_not_rearm_the_failure_cooldown(monkeypatch):
    """2026-11-20 review: clearing the cooldown on recovery let a flapping
    check push a failure + recovery every cycle (8/hour at 300 s)."""
    pushed = _pushes(monkeypatch)
    _fail()
    _recover()
    # It flaps: down again inside the window -- cooled down, not announced...
    _fail()
    # ...so its recovery has no announced incident to resolve and is not sent.
    _recover()
    assert len(pushed) == 2
    assert server._last_alert_time_by_key.get(server.ALERT_KEY_UPTIME)


def test_a_recovery_without_an_announced_incident_is_not_sent(monkeypatch):
    pushed = _pushes(monkeypatch)
    _recover()
    assert pushed == []


def test_an_undelivered_failure_opens_no_incident_and_is_retried(monkeypatch):
    pushed = _pushes(monkeypatch, results=[False, True, True])
    _fail()  # channel down: nothing announced, no cooldown, no incident
    assert server._alert_incident_open == set()
    assert server._last_alert_time_by_key == {}
    _recover()  # the owner never heard of that outage
    assert pushed == [f"[Dynasty Server] {FAILING}"]
    _fail()  # the next outage is retried at once and delivered
    _recover()
    assert pushed[1:] == [f"[Dynasty Server] {FAILING}", f"[Dynasty Server] {RECOVERED}"]


def test_an_undelivered_recovery_keeps_the_incident_open_for_the_next_one(monkeypatch):
    pushed = _pushes(monkeypatch, results=[True, False, True])
    _fail()
    _recover()  # not delivered: the incident stays open
    assert server._alert_incident_open == {server.ALERT_KEY_UPTIME}
    _recover()
    assert pushed[-1] == f"[Dynasty Server] {RECOVERED}" and len(pushed) == 3
    assert server._alert_incident_open == set()


def test_a_long_outage_reannounced_each_window_gets_one_recovery(monkeypatch):
    pushed = _pushes(monkeypatch)
    _fail()
    # An hour later it is still down: the cooldown has expired, so it is re-announced.
    server._last_alert_time_by_key[server.ALERT_KEY_UPTIME] -= server.ALERT_COOLDOWN_SEC
    _fail()
    _recover()
    _recover()
    assert pushed == [f"[Dynasty Server] {FAILING}"] * 2 + [f"[Dynasty Server] {RECOVERED}"]


@pytest.mark.parametrize("failure_delivers", [True, False])
def test_a_recovery_during_the_failure_delivery_waits_for_its_outcome(
    monkeypatch, failure_delivers
):
    """A recovery requested while its failure alert is still in flight is sent
    once that alert is delivered, and dropped if it is not."""
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", PUSH)
    release = threading.Event()
    pushed: list[str] = []

    def fake_send(title, body, **_k):
        if title.endswith(FAILING):
            release.wait(timeout=5)
            pushed.append(title)
            return failure_delivers
        pushed.append(title)
        return True

    monkeypatch.setattr(owner_notify, "send", fake_send)
    server.send_alert(FAILING, "b", key=server.ALERT_KEY_UPTIME)
    server.send_alert(RECOVERED, "b", key=server.ALERT_KEY_UPTIME_RECOVERY)
    assert pushed == [], "the recovery must not overtake the failure it resolves"
    release.set()
    _settle()
    if failure_delivers:
        assert pushed == [f"[Dynasty Server] {FAILING}", f"[Dynasty Server] {RECOVERED}"]
    else:
        assert pushed == [f"[Dynasty Server] {FAILING}"]
    assert server._alert_incident_open == set()
    assert server._alert_recovery_deferred == {}


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


class _RefusingSMTP(_RecordingSMTP):
    """``send_message`` refuses the recipient, the way Gmail does: smtplib's
    ``SMTPRecipientsRefused`` carries the address in its message."""

    def send_message(self, *_a):
        raise server.smtplib.SMTPRecipientsRefused(
            {"owner@example.invalid": (550, b"5.1.1 <owner@example.invalid> unknown user")}
        )


def test_smtp_failure_logs_the_exception_class_never_the_recipient(monkeypatch, caplog):
    import logging

    _email_on(monkeypatch)
    monkeypatch.setattr(server.smtplib, "SMTP", _RefusingSMTP)
    monkeypatch.setattr(server.smtplib, "SMTP_SSL", _RefusingSMTP)
    with caplog.at_level(logging.DEBUG):
        delivered = server._deliver_email_smtp("owner@example.invalid", "subject-text", "body")
    assert delivered is False
    assert [i["port"] for i in _RefusingSMTP.instances] == [587, 465]
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "SMTPRecipientsRefused" in text
    for leaked in ("owner@example.invalid", "unknown user", "550", "subject-text"):
        assert leaked not in text, leaked
