"""One owner-alert routing: push (ntfy) first, e-mail fallback (STAB-2, 2026-11-19)."""

from __future__ import annotations

import pytest

from src.utils import owner_alerts as A

NTFY = "https://ntfy.sh/private-topic-for-tests"
EMAIL_ENV = {
    "ALERT_ENABLED": "true",
    "ALERT_TO": "owner@example.invalid",
    "ALERT_FROM": "box@example.invalid",
    "ALERT_PASSWORD": "not-a-real-password",
}


def test_channels_configured_reports_presence_only():
    assert A.channels_configured({}) == {"ntfy": False, "email": False}
    assert A.channels_configured({"NOTIFY_WEBHOOK_URL": NTFY}) == {"ntfy": True, "email": False}
    assert A.channels_configured(EMAIL_ENV) == {"ntfy": False, "email": True}
    out = A.channels_configured({**EMAIL_ENV, "NOTIFY_WEBHOOK_URL": NTFY})
    assert out == {"ntfy": True, "email": True}
    assert all(isinstance(v, bool) for v in out.values())


@pytest.mark.parametrize(
    "url",
    ["http://ntfy.sh/topic", "ftp://x/y", "not a url", "   "],
)
def test_a_non_https_webhook_is_not_a_channel(url):
    assert A.channels_configured({"NOTIFY_WEBHOOK_URL": url})["ntfy"] is False


def test_email_needs_every_setting():
    for missing in EMAIL_ENV:
        env = {k: v for k, v in EMAIL_ENV.items() if k != missing}
        assert A.channels_configured(env)["email"] is False, missing
    assert A.channels_configured({**EMAIL_ENV, "ALERT_ENABLED": "false"})["email"] is False


def test_recipient_prefers_the_address_then_the_owner_channel_then_none():
    assert A.recipient("owner@example.invalid", {}) == "owner@example.invalid"
    assert A.recipient("", {"NOTIFY_WEBHOOK_URL": NTFY}) == A.OWNER_CHANNEL
    assert A.recipient(None, {}) is None


def test_push_first_and_email_is_not_tried_after_a_push_delivers():
    calls = []
    ok = A.deliver(
        "owner@example.invalid",
        "s",
        "b",
        push=lambda s, b: calls.append("push") or True,
        email=lambda t, s, b: calls.append("email") or True,
    )
    assert ok is True and calls == ["push"]


def test_email_is_the_fallback_when_push_fails_or_raises():
    calls = []

    def boom(s, b):
        calls.append("push")
        raise RuntimeError("network")

    ok = A.deliver(
        "owner@example.invalid", "s", "b", push=boom, email=lambda t, s, b: calls.append(t) or True
    )
    assert ok is True and calls == ["push", "owner@example.invalid"]


def test_the_owner_channel_stand_in_is_never_mailed():
    calls = []
    ok = A.deliver(
        A.OWNER_CHANNEL,
        "s",
        "b",
        push=lambda s, b: False,
        email=lambda t, s, b: calls.append(t) or True,
    )
    assert ok is False and calls == []


def test_unconfigured_push_is_skipped(monkeypatch):
    monkeypatch.delenv("NOTIFY_WEBHOOK_URL", raising=False)
    assert A.deliver(None, "s", "b") is False


def test_deliver_each_tries_every_channel_and_marks_unconfigured_none():
    out = A.deliver_each(
        "owner@example.invalid", "s", "b", push=lambda s, b: True, email=lambda t, s, b: False
    )
    assert out == {"ntfy": True, "email": False}
    out = A.deliver_each(A.OWNER_CHANNEL, "s", "b", push=lambda s, b: True, email=lambda *a: True)
    assert out == {"ntfy": True, "email": None}


def test_deliver_each_with_no_channel_is_all_none(monkeypatch):
    monkeypatch.delenv("NOTIFY_WEBHOOK_URL", raising=False)
    assert A.deliver_each(None, "s", "b") == {"ntfy": None, "email": None}


# ── the one validator, and why a channel is off (2026-11-20) ──────────────


@pytest.mark.parametrize(
    ("raw", "state"),
    [
        (None, "unset"),
        (NTFY, "ok"),
        ("http://ntfy.sh/topic", "rejected:scheme"),
        ("https://u:p@ntfy.sh/topic", "rejected:userinfo"),
        ("https://ntfy.sh/a b", "rejected:whitespace"),
    ],
)
def test_ntfy_state_is_the_validators_answer(raw, state):
    env = {} if raw is None else {"NOTIFY_WEBHOOK_URL": raw}
    assert A.ntfy_state(env) == state
    assert A.channels_configured(env)["ntfy"] is (state == "ok")


def test_the_gmail_app_password_alias_counts_like_server_py():
    env = {k: v for k, v in EMAIL_ENV.items() if k != "ALERT_PASSWORD"}
    assert A.channels_configured(env)["email"] is False
    env["GMAIL_APP_PASSWORD"] = "not-a-real-password"
    assert A.channels_configured(env)["email"] is True


# ── in-process delivery health ─────────────────────────────────────────────


@pytest.fixture()
def health():
    A.reset_delivery_health_for_tests()
    yield
    A.reset_delivery_health_for_tests()


def _health():
    return A.delivery_health({})


def test_attempted_failures_count_and_a_success_resets(health):
    A.deliver(None, "s", "b", push=lambda s, b: False)
    A.deliver("owner@example.invalid", "s", "b", push=lambda s, b: False, email=lambda *a: False)
    h = _health()
    assert h["consecutiveFailures"] == 2 and h["lastFailedAt"] and h["lastDeliveredAt"] is None
    A.deliver("owner@example.invalid", "s", "b", push=lambda s, b: False, email=lambda *a: True)
    h = _health()
    assert h["consecutiveFailures"] == 0 and h["lastDeliveredAt"]


def test_a_raising_channel_is_a_failure_not_a_crash(health):
    def boom(s, b):
        raise RuntimeError("network")

    assert A.deliver(None, "s", "b", push=boom) is False
    assert _health()["consecutiveFailures"] == 1


def test_nothing_configured_attempts_nothing_and_counts_nothing(health, monkeypatch):
    monkeypatch.delenv("NOTIFY_WEBHOOK_URL", raising=False)
    assert A.deliver(None, "s", "b") is False
    assert A.deliver(A.OWNER_CHANNEL, "s", "b", email=lambda *a: True) is False
    assert A.deliver_each(None, "s", "b") == {"ntfy": None, "email": None}
    assert _health() == {
        "ntfyConfigured": False,
        "emailConfigured": False,
        "lastDeliveredAt": None,
        "lastFailedAt": None,
        "consecutiveFailures": 0,
    }


def test_an_operator_test_is_delivery_evidence_too(health):
    A.deliver_each(None, "s", "b", push=lambda s, b: False)
    assert _health()["consecutiveFailures"] == 1
    A.deliver_each(None, "s", "b", push=lambda s, b: True)
    assert _health()["consecutiveFailures"] == 0


def test_delivery_health_publishes_presence_and_never_a_value(health):
    env = {**EMAIL_ENV, "NOTIFY_WEBHOOK_URL": NTFY}
    out = A.delivery_health(env)
    assert out["ntfyConfigured"] is True and out["emailConfigured"] is True
    text = repr(out)
    for secret in (NTFY, "owner@example.invalid", "not-a-real-password", "private-topic"):
        assert secret not in text
