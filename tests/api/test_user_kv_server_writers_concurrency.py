"""server.py whole-field user_kv writers must not lose concurrent updates.

#1704 made every user_kv writer a ``BEGIN IMMEDIATE`` read-modify-write, but
the push-subscription and custom-alert routes still READ with
``get_user_state`` and then rewrote a whole field from that copy.  A
concurrent write to the same field that landed between the read and the write
was silently discarded: a second device's push subscription vanished, or a
custom-alert sweep resurrected a rule's cooldown the user had just deleted.

The read is widened deterministically (``_read_row`` sleeps after reading) so
the old interleaving loses an update on every run rather than occasionally.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

import server
from src.api import push_delivery, user_kv
from src.news import custom_alerts

USER = "kvrace"


@pytest.fixture()
def kv_path(tmp_path, monkeypatch):
    path = tmp_path / "user_kv.sqlite"
    monkeypatch.setattr(user_kv, "USER_KV_PATH", path)
    user_kv._SETUP_DONE.clear()
    monkeypatch.setattr(server, "_get_auth_session", lambda r: {"username": USER})
    return path


@pytest.fixture()
def slow_reads(monkeypatch):
    """Hold every reader for a beat after it reads the blob."""
    real = user_kv._read_row

    def _slow(conn, username):
        row = real(conn, username)
        time.sleep(0.15)
        return row

    monkeypatch.setattr(user_kv, "_read_row", _slow)


def _sub(endpoint: str) -> dict:
    return {"endpoint": endpoint, "keys": {"p256dh": "p", "auth": "a"}}


def _race(*calls):
    barrier = threading.Barrier(len(calls))
    errors: list[BaseException] = []

    def _run(fn):
        try:
            barrier.wait()
            fn()
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=_run, args=(c,)) for c in calls]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors


def _endpoints() -> set[str]:
    state = user_kv.get_user_state(USER)
    return {s["endpoint"] for s in push_delivery.list_subscriptions(state)}


def _post(path: str, body: dict) -> None:
    res = TestClient(server.app).post(path, json=body)
    assert res.status_code == 200, res.text


def test_concurrent_push_subscribes_keep_both_devices(kv_path, slow_reads):
    _race(
        lambda: _post("/api/push/subscribe", _sub("https://push/a")),
        lambda: _post("/api/push/subscribe", _sub("https://push/b")),
    )
    assert _endpoints() == {"https://push/a", "https://push/b"}


def test_concurrent_subscribe_and_unsubscribe_both_apply(kv_path, slow_reads):
    user_kv.set_user_field(USER, "pushSubscriptions", [_sub("https://push/old")])
    _race(
        lambda: _post("/api/push/subscribe", _sub("https://push/new")),
        lambda: _post("/api/push/unsubscribe", {"endpoint": "https://push/old"}),
    )
    assert _endpoints() == {"https://push/new"}


def test_invalid_subscription_is_still_a_400_and_writes_nothing(kv_path):
    user_kv.set_user_field(USER, "pushSubscriptions", [_sub("https://push/keep")])
    res = TestClient(server.app).post("/api/push/subscribe", json={"endpoint": "x"})
    assert res.status_code == 400
    assert _endpoints() == {"https://push/keep"}


def _rule(rule_id: str) -> dict:
    return custom_alerts.validate_rule(
        {
            "id": rule_id,
            "kind": "value_crosses",
            "displayName": "Player One",
            "params": {"threshold": 5000, "direction": "above"},
            "channels": ["push"],
        }
    )


def test_custom_alert_put_keeps_a_concurrently_recorded_cooldown(kv_path, slow_reads):
    """PUT re-derives ``customAlertsState`` from what it read; a cooldown the
    sweep recorded meanwhile must survive (otherwise the alert re-fires)."""
    rule = _rule("r1")
    user_kv.merge_user_state(USER, {"customAlerts": [rule], "customAlertsState": {}})

    def _record_cooldown():
        def _mark(entry):
            cur = dict(entry.get("customAlertsState") or {})
            cur["r1::player one"] = {"lastFiredAt": "2026-10-08T00:00:00Z"}
            entry["customAlertsState"] = cur

        user_kv.mutate_user_state(USER, _mark)

    _race(
        lambda: TestClient(server.app).put("/api/custom-alerts", json={"rules": [rule]}),
        _record_cooldown,
    )
    state = user_kv.get_user_state(USER)
    assert "r1::player one" in (state.get("customAlertsState") or {})


def _run_sweep(monkeypatch, during_delivery):
    """Drive /api/custom-alerts/run with one push hit whose delivery reports a
    dead endpoint; ``during_delivery`` is a concurrent write landing while the
    sweep is delivering (the window between its snapshot and its write)."""
    monkeypatch.setattr(server, "SIGNAL_ALERT_CRON_TOKEN", "tok")
    monkeypatch.setattr(server, "latest_contract_data", {"playersArray": [{"x": 1}]})
    hit = custom_alerts.Hit(
        rule_id="r1",
        kind="value_crosses",
        display_name="Player One",
        title="t",
        body="b",
        state_key="r1::player one",
        channels=("push",),
    )
    monkeypatch.setattr(server._custom_alerts, "evaluate_alerts", lambda *a, **k: [hit])

    def _fanout(state, **_kw):
        t = threading.Thread(target=during_delivery)
        t.start()
        t.join()
        return 1, ["https://push/dead"]

    monkeypatch.setattr(server._push_delivery, "fanout", _fanout)
    res = TestClient(server.app).post(
        "/api/custom-alerts/run", headers={"Authorization": "Bearer tok"}
    )
    assert res.status_code == 200, res.text


def test_sweep_keeps_a_device_subscribed_during_delivery(kv_path, monkeypatch):
    user_kv.merge_user_state(
        USER,
        {
            "customAlerts": [_rule("r1")],
            "pushSubscriptions": [_sub("https://push/dead"), _sub("https://push/live")],
        },
    )
    _run_sweep(
        monkeypatch,
        lambda: _post("/api/push/subscribe", _sub("https://push/new")),
    )
    # The dead endpoint is pruned; the device that subscribed mid-sweep is kept.
    assert _endpoints() == {"https://push/live", "https://push/new"}
    state = user_kv.get_user_state(USER)
    assert "r1::player one" in state["customAlertsState"]


def test_sweep_does_not_resurrect_a_rule_deleted_during_delivery(kv_path, monkeypatch):
    user_kv.merge_user_state(
        USER,
        {
            "customAlerts": [_rule("r1")],
            "customAlertsState": {},
            "pushSubscriptions": [_sub("https://push/dead")],
        },
    )

    def _delete_rule():
        res = TestClient(server.app).put("/api/custom-alerts", json={"rules": []})
        assert res.status_code == 200

    _run_sweep(monkeypatch, _delete_rule)
    state = user_kv.get_user_state(USER)
    assert state.get("customAlerts") == []
    assert not (state.get("customAlertsState") or {})
