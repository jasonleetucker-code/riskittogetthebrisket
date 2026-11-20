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


# ── delivery health ─────────────────────────────────────────────────────────


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
    # No attempt is recorded anywhere: the count is UNKNOWN, never 0.
    assert _health() == {
        "ntfyConfigured": False,
        "emailConfigured": False,
        "lastDeliveredAt": None,
        "lastFailedAt": None,
        "consecutiveFailures": None,
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


# ── the record survives a restart (2026-11-20 review) ──────────────────────
#
# Each daily sweep attempts at most a couple of deliveries, so the three
# failures the SLO rule breaches on take several sweeps -- and an in-memory
# record reset by a deploy or restart in between read 0 ("OK") while delivery
# was failing.  The record now persists in user_kv under the ops-alert system
# user, best-effort.

T0 = 1_800_000_000.0


@pytest.fixture()
def store(tmp_path, monkeypatch):
    path = tmp_path / "user_kv.sqlite"
    monkeypatch.setattr(A, "HEALTH_STORE_PATH", path)
    A.reset_delivery_health_for_tests()
    yield path
    A.reset_delivery_health_for_tests()


def _restart():
    """A new process: the in-memory record is gone, the store is not."""
    A.reset_delivery_health_for_tests(store=False)


def _fail_once():
    assert A.deliver(None, "s", "b", push=lambda s, b: False) is False


def test_the_record_survives_a_restart(store):
    A._record(False, now=T0)
    A._record(False, now=T0 + 60)
    _restart()
    h = _health()
    assert h["consecutiveFailures"] == 2
    assert h["lastFailedAt"].startswith("2027-01-15T") and h["lastDeliveredAt"] is None


def test_failures_accumulate_across_sweeps_and_restarts_until_a_delivery(store):
    _fail_once()  # sweep 1
    _restart()  # deploy
    _fail_once()  # sweep 2
    _restart()
    _fail_once()  # sweep 3
    assert _health()["consecutiveFailures"] == 3, "the SLO rule's breach count is reachable"
    _restart()
    assert _health()["consecutiveFailures"] == 3
    assert A.deliver(None, "s", "b", push=lambda s, b: True) is True
    _restart()
    h = _health()
    assert h["consecutiveFailures"] == 0 and h["lastDeliveredAt"] and h["lastFailedAt"]


def test_no_record_anywhere_is_unknown_and_reading_creates_nothing(store):
    h = _health()
    assert h["consecutiveFailures"] is None
    assert h["lastDeliveredAt"] is None and h["lastFailedAt"] is None
    assert not store.exists(), "a diagnostic read must not create the store"


def test_the_record_lives_beside_the_sweep_stamp_under_the_ops_system_user(store):
    from src.api import ops_alerts, user_kv

    assert A.HEALTH_STATE_USER == ops_alerts._OPS_STATE_USER
    A._record(False, now=T0)
    ops_alerts.record_sweep(now=T0 + 5, kv_path=store)
    entry = user_kv.get_user_state(ops_alerts._OPS_STATE_USER, path=store)
    assert entry[A.HEALTH_STATE_KEY] == {
        "lastDeliveredEpoch": None,
        "lastFailedEpoch": T0,
        "consecutiveFailures": 1,
    }
    assert ops_alerts.SWEEP_STATE_KEY in entry
    _restart()
    assert _health()["consecutiveFailures"] == 1


def test_a_newer_event_in_the_store_wins_over_this_process(store):
    """Another writer (or an earlier persist this process missed) is merged:
    the most recent event decides the streak, timestamps take the latest."""
    from src.api import user_kv

    A._record(False, now=T0)

    def _delivered_later(entry):
        entry[A.HEALTH_STATE_KEY] = {
            "lastDeliveredEpoch": T0 + 30,
            "lastFailedEpoch": T0,
            "consecutiveFailures": 0,
        }

    user_kv.mutate_user_state(A.HEALTH_STATE_USER, _delivered_later, path=store)
    h = _health()
    assert h["consecutiveFailures"] == 0 and h["lastDeliveredAt"] and h["lastFailedAt"]


@pytest.mark.parametrize(
    "stored",
    [
        "garbage",
        {"consecutiveFailures": -1},
        {"consecutiveFailures": True},
        {"consecutiveFailures": "3"},
        {"lastFailedEpoch": "yesterday", "consecutiveFailures": 2},
    ],
)
def test_an_unreadable_stored_record_is_unknown_not_zero(store, stored):
    from src.api import user_kv

    user_kv.mutate_user_state(
        A.HEALTH_STATE_USER, lambda e: e.update({A.HEALTH_STATE_KEY: stored}), path=store
    )
    assert _health()["consecutiveFailures"] is None


def test_a_store_failure_never_breaks_delivery(store, monkeypatch, caplog):
    import logging
    import sqlite3

    from src.api import user_kv

    def boom(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(user_kv, "mutate_user_state", boom)
    monkeypatch.setattr(user_kv, "get_user_state", boom)
    with caplog.at_level(logging.WARNING):
        assert A.deliver(None, "s", "b", push=lambda s, b: True) is True
        assert A.deliver(None, "s", "b", push=lambda s, b: False) is False
        h = _health()
    # This process's own record still answers.
    assert h["consecutiveFailures"] == 1 and h["lastDeliveredAt"] and h["lastFailedAt"]
    messages = [r.getMessage() for r in caplog.records]
    assert any("not persisted" in m and "OperationalError" in m for m in messages)
    assert not any("database is locked" in m for m in messages)


def test_an_unpersisted_delivery_does_not_write_the_store(store):
    """The out-of-process operator script is not the server: it must not write
    the server's store (``persist=False``); its result stays in its memory."""
    assert A.deliver_each(None, "s", "b", push=lambda s, b: False, persist=False) == {
        "ntfy": False,
        "email": None,
    }
    assert not store.exists()
    assert _health()["consecutiveFailures"] == 1
