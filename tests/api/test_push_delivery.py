"""Push subscription storage + dispatch shape tests.

We don't drive an actual webpush server here — we monkeypatch the
``send_push`` function to confirm the fanout helper walks every
subscription and forwards prune signals correctly.
"""
from __future__ import annotations

import pytest

from src.api import push_delivery as pd


def test_upsert_dedupes_by_endpoint():
    state: dict = {}
    sub_a = {
        "endpoint": "https://example.com/push/a",
        "keys": {"p256dh": "p", "auth": "a"},
        "ua": "iPhone",
    }
    state["pushSubscriptions"] = pd.upsert_subscription(state, sub_a)
    # Re-subscribing on the same endpoint should replace, not duplicate.
    state["pushSubscriptions"] = pd.upsert_subscription(state, sub_a)
    assert len(state["pushSubscriptions"]) == 1


def test_upsert_appends_distinct_endpoints():
    state: dict = {}
    state["pushSubscriptions"] = pd.upsert_subscription(state, {
        "endpoint": "https://example.com/push/a",
        "keys": {"p256dh": "p1", "auth": "a1"},
    })
    state["pushSubscriptions"] = pd.upsert_subscription(state, {
        "endpoint": "https://example.com/push/b",
        "keys": {"p256dh": "p2", "auth": "a2"},
    })
    assert len(state["pushSubscriptions"]) == 2


@pytest.mark.parametrize(
    "bad",
    [
        {"keys": {"p256dh": "p", "auth": "a"}},                     # no endpoint
        {"endpoint": "https://x", "keys": {}},                       # no key fields
        {"endpoint": "https://x", "keys": {"p256dh": "p"}},          # missing auth
        {"endpoint": "https://x"},                                    # no keys
    ],
)
def test_upsert_rejects_malformed_subscription(bad):
    with pytest.raises(ValueError):
        pd.upsert_subscription({}, bad)


def test_remove_subscription_filters_by_endpoint():
    state = {"pushSubscriptions": [
        {"endpoint": "https://x/a", "keys": {"p256dh": "p", "auth": "a"}},
        {"endpoint": "https://x/b", "keys": {"p256dh": "p", "auth": "a"}},
    ]}
    new = pd.remove_subscription(state, "https://x/a")
    assert [s["endpoint"] for s in new] == ["https://x/b"]


def test_list_subscriptions_filters_invalid_records():
    state = {"pushSubscriptions": [
        {"endpoint": "https://x/a", "keys": {"p256dh": "p", "auth": "a"}},
        "not-a-dict",
        {"endpoint": None, "keys": {}},
    ]}
    out = pd.list_subscriptions(state)
    assert len(out) == 1
    assert out[0]["endpoint"] == "https://x/a"


def test_fanout_walks_every_subscription_and_collects_prunes(monkeypatch):
    state = {"pushSubscriptions": [
        {"endpoint": "https://x/a", "keys": {"p256dh": "p", "auth": "a"}},
        {"endpoint": "https://x/b", "keys": {"p256dh": "p", "auth": "a"}},
        {"endpoint": "https://x/c", "keys": {"p256dh": "p", "auth": "a"}},
    ]}

    def fake_send(sub, **_):
        if sub["endpoint"].endswith("a"):
            return (True, False)
        if sub["endpoint"].endswith("b"):
            return (False, True)  # gone — prune
        return (False, False)

    monkeypatch.setattr(pd, "send_push", fake_send)

    delivered, prune = pd.fanout(state, title="t", body="b", url="/")
    assert delivered == 1
    assert prune == ["https://x/b"]


def test_is_configured_false_when_env_missing(monkeypatch):
    monkeypatch.setattr(pd, "_VAPID_PUBLIC", "")
    monkeypatch.setattr(pd, "_VAPID_PRIVATE", "x")
    monkeypatch.setattr(pd, "_VAPID_CONTACT", "mailto:x")
    assert not pd.is_configured()


def test_is_configured_true_when_all_three_set(monkeypatch):
    monkeypatch.setattr(pd, "_VAPID_PUBLIC", "pub")
    monkeypatch.setattr(pd, "_VAPID_PRIVATE", "priv")
    monkeypatch.setattr(pd, "_VAPID_CONTACT", "mailto:test@example.com")
    assert pd.is_configured()
