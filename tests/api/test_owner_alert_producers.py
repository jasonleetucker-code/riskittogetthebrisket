"""``POST /api/test-alert?producers=1`` exercises every REAL alert producer (E2E-TEST).

Before, the operator tests proved only the channels: ``/api/test-alert`` sent one
generic message, and the box's ``notify-test`` pushed titles with the ``.env``
URL, so it passed even when the backend had never been restarted onto that URL.
Neither ran ``send_alert``, the ops sweep, the staleness sweep or the Signals
reconnect notice.

Pinned here, with transport stubs only (nothing leaves the process):

* each producer sends EXACTLY one notice, through its own formatter and its own
  delivery path, titled ``[TEST] ...``;
* the test reads and writes no cooldown, in-flight, incident, episode or
  delivery-health state, so it can neither silence nor fake a real alert;
* the answer is booleans and reason codes -- never a URL, an address or a
  secret, not even inside a producer's exception message.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server
from src.api import ops_alerts, source_health_alerts, user_kv
from src.sources import signals_auth
from src.utils import owner_alerts, owner_notify

TOPIC = "https://ntfy.sh/private-topic-for-tests"
ADDRESS = "owner@example.invalid"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(server, "PRIVATE_APP_ALLOWED_USERNAMES", frozenset({"jasonleetucker"}))
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda r: {"username": "jasonleetucker"})
    monkeypatch.setattr(server, "ALERT_ENABLED", False)
    monkeypatch.setattr(server, "ALERT_TO", "")
    monkeypatch.setattr(server, "ALERT_FROM", "")
    monkeypatch.setattr(server, "ALERT_PASSWORD", "")
    monkeypatch.delenv("NOTIFY_WEBHOOK_URL", raising=False)
    # Fresh send_alert bookkeeping, so "untouched" is checkable.
    monkeypatch.setattr(server, "_last_alert_time_by_key", {})
    monkeypatch.setattr(server, "_alerts_in_flight", set())
    monkeypatch.setattr(server, "_alert_incident_open", set())
    monkeypatch.setattr(server, "_alert_recovery_deferred", {})
    monkeypatch.setattr(server, "_alert_unconfigured_logged_at", {})
    owner_alerts.reset_delivery_health_for_tests()
    yield
    owner_alerts.reset_delivery_health_for_tests()


@pytest.fixture()
def no_state_writes(monkeypatch):
    """Fail the test if anything writes alert state or opens the Signals store."""
    writes: list[str] = []
    real_mutate = user_kv.mutate_user_state

    def spy(user, fn, **kw):
        writes.append(user)
        return real_mutate(user, fn, **kw)

    monkeypatch.setattr(user_kv, "mutate_user_state", spy)

    def no_store(*_a, **_k):
        raise AssertionError("the producer test must never open the Signals store")

    monkeypatch.setattr(signals_auth.SignalsStore, "open", classmethod(no_store))
    return writes


def _pushes(monkeypatch, result=True):
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", TOPIC)
    sent: list[tuple[str, str]] = []

    def fake_send(title, body, **_k):
        sent.append((title, body))
        return result

    monkeypatch.setattr(owner_notify, "send", fake_send)
    return sent


def _email(monkeypatch, result=True):
    monkeypatch.setattr(server, "ALERT_ENABLED", True)
    monkeypatch.setattr(server, "ALERT_TO", ADDRESS)
    monkeypatch.setattr(server, "ALERT_FROM", "box@example.invalid")
    monkeypatch.setattr(server, "ALERT_PASSWORD", "not-a-real-password")
    mailed: list[tuple[str, str]] = []

    def fake_smtp(to, subject, body):
        assert to == ADDRESS
        mailed.append((subject, body))
        return result

    monkeypatch.setattr(server, "_deliver_email_smtp", fake_smtp)
    return mailed


def _post():
    with TestClient(server.app, raise_server_exceptions=True) as c:
        return c.post("/api/test-alert?producers=1")


def _assert_state_untouched(writes):
    assert writes == [], f"alert state written by the producer test: {writes}"
    assert server._last_alert_time_by_key == {}
    assert server._alerts_in_flight == set()
    assert server._alert_incident_open == set()
    assert server._alert_recovery_deferred == {}
    health = owner_alerts.delivery_health()
    assert health["deliveryRecord"] == "none" and health["consecutiveFailures"] is None


def test_each_producer_sends_exactly_one_test_notice_through_its_own_formatter(
    monkeypatch, no_state_writes
):
    sent = _pushes(monkeypatch)
    res = _post()
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["mode"] == "producers"
    assert list(body["producers"]) == list(server.OWNER_ALERT_PRODUCERS)
    assert all(p == {"delivered": True, "reason": "delivered"} for p in body["producers"].values())
    titles = [title for title, _ in sent]
    assert len(sent) == len(server.OWNER_ALERT_PRODUCERS) == 4
    assert titles == [
        "[TEST] [Brisket Ops] 1 warning",
        "[TEST] [Brisket Ops] 1 source stale",
        "[TEST] [Dynasty Server] Server alert producer test (no condition fired)",
        f"[TEST] [Brisket Ops] Signals connection needs attention "
        f"({signals_auth.TEST_NOTICE_CLASS})",
    ]
    for _, text in sent:
        assert text.startswith(owner_alerts.TEST_BODY_BANNER)
    # Each body is the producer's real formatting, not a generic stand-in.
    assert "--- WARNING ---" in sent[0][1]
    assert "Stale sources:" in sent[1][1]
    assert "Signals authenticated collection has STOPPED." in sent[3][1]
    _assert_state_untouched(no_state_writes)


def test_failed_channels_report_failed_502_and_record_nothing(monkeypatch, no_state_writes):
    sent = _pushes(monkeypatch, result=False)
    res = _post()
    assert res.status_code == 502
    assert all(
        p == {"delivered": False, "reason": "all_channels_failed"}
        for p in res.json()["producers"].values()
    )
    assert len(sent) == 4
    # Four failed sends, and the delivery-health streak is still unknown.
    _assert_state_untouched(no_state_writes)


def test_no_channel_is_400_and_every_producer_not_configured(no_state_writes):
    res = _post()
    assert res.status_code == 400
    body = res.json()
    assert body["configured"] == {"ntfy": False, "email": False}
    assert all(
        p == {"delivered": None, "reason": "not_configured"} for p in body["producers"].values()
    )
    _assert_state_untouched(no_state_writes)


def test_email_only_box_sends_one_mail_per_producer_and_never_returns_the_address(
    monkeypatch, no_state_writes
):
    mailed = _email(monkeypatch)
    res = _post()
    assert res.status_code == 200, res.text
    assert len(mailed) == 4 and all(s.startswith("[TEST] ") for s, _ in mailed)
    assert ADDRESS not in res.text and "example.invalid" not in res.text
    _assert_state_untouched(no_state_writes)


def test_a_push_failure_falls_back_to_email_once_per_producer(monkeypatch, no_state_writes):
    sent = _pushes(monkeypatch, result=False)
    mailed = _email(monkeypatch)
    res = _post()
    assert res.status_code == 200, res.text
    assert len(sent) == 4 and len(mailed) == 4
    _assert_state_untouched(no_state_writes)


def test_the_response_never_carries_the_webhook(monkeypatch):
    _pushes(monkeypatch)
    res = _post()
    assert "ntfy.sh" not in res.text and "private-topic" not in res.text


def test_a_raising_producer_reports_its_class_never_its_message(monkeypatch, no_state_writes):
    sent = _pushes(monkeypatch)

    def boom():
        raise RuntimeError(f"failed posting to {TOPIC}")

    monkeypatch.setattr(ops_alerts, "format_test_notice", boom)
    res = _post()
    assert res.status_code == 502
    producers = res.json()["producers"]
    assert producers["opsAlerts"] == {
        "delivered": False,
        "reason": "producer_error",
        "errorClass": "RuntimeError",
    }
    assert all(producers[k]["delivered"] is True for k in producers if k != "opsAlerts")
    assert len(sent) == 3
    assert "ntfy.sh" not in res.text and "private-topic" not in res.text
    _assert_state_untouched(no_state_writes)


def test_every_reason_is_declared():
    assert {"delivered", "all_channels_failed", "not_configured", "producer_error"} == (
        server.OWNER_ALERT_PRODUCER_REASONS
    )


# -- the producers' own test formatters ----------------------------------------------
def test_ops_test_notice_is_the_sweep_formatter_and_titled_test():
    subject, body = ops_alerts.format_test_notice()
    assert subject == "[TEST] [Brisket Ops] 1 warning"
    assert body.startswith(owner_alerts.TEST_BODY_BANNER)
    assert "--- WARNING ---" in body and "Ops-alert producer test" in body


def test_source_health_test_notice_uses_the_sweep_formatters():
    subject, body = source_health_alerts.format_test_notice()
    assert subject == "[TEST] [Brisket Ops] 1 source stale"
    assert source_health_alerts.TEST_SOURCE in body


def test_signals_test_notice_follows_the_sweep_channel_order_and_opens_no_store(monkeypatch):
    def no_store(*_a, **_k):
        raise AssertionError("must not open the store")

    monkeypatch.setattr(signals_auth.SignalsStore, "open", classmethod(no_store))
    calls: list[str] = []

    def ntfy(subject, body):
        calls.append("ntfy")
        return False

    def mail(to, subject, body):
        calls.append(f"email:{to}")
        return True

    out = signals_auth.send_test_reconnect_notice(
        channels=[("ntfy", ntfy)], delivery=mail, to_email="o@example.invalid"
    )
    assert out == {
        "delivered": True,
        "deliveredVia": "email",
        "channelsAttempted": ["ntfy", "email"],
    }
    assert calls == ["ntfy", "email:o@example.invalid"]
    assert signals_auth.send_test_reconnect_notice(channels=[("ntfy", None)])["delivered"] is None


# -- end to end: the box's notify-test against this route ----------------------------
def test_notify_test_backend_check_against_the_real_route(monkeypatch, tmp_path, no_state_writes):
    """``scripts/send_owner_test_alert.py``'s backend check, posted through the
    real app (auth gate, producers, status mapping) with only the transport
    stubbed: the RUNNING process's channels decide, not the ``.env`` file."""
    from scripts import send_owner_test_alert as T

    token = "cron-token-for-tests-0123456789"
    monkeypatch.setattr(server, "SIGNAL_ALERT_CRON_TOKEN", token)
    # No session at all: the bearer alone must authorize.
    monkeypatch.setattr(server, "_get_auth_session", lambda r: None)
    sent = _pushes(monkeypatch)

    def post(url, bearer, timeout):
        path = url.split("127.0.0.1:8000", 1)[1]
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.post(path, headers={"Authorization": f"Bearer {bearer}"})
        return res.status_code, res.json()

    env = {"SIGNAL_ALERT_CRON_TOKEN": token}
    report, passed = T.backend_producer_check(env, post=post)
    assert passed is True and report["state"] == "ok", report
    assert set(report["producers"]) == set(server.OWNER_ALERT_PRODUCERS)
    assert len(sent) == 4
    _assert_state_untouched(no_state_writes)

    # A backend on another token refuses, and the check fails rather than passes.
    report, passed = T.backend_producer_check({"SIGNAL_ALERT_CRON_TOKEN": "stale"}, post=post)
    assert passed is False and report["state"] == "refused" and report["httpStatus"] == 401
    assert len(sent) == 4

    # A process that never loaded the webhook (not restarted): not_configured.
    monkeypatch.delenv("NOTIFY_WEBHOOK_URL")
    report, passed = T.backend_producer_check(env, post=post)
    assert passed is False and report["state"] == "not_configured"
    assert report["ntfyState"] == "unset"
