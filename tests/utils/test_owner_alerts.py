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
