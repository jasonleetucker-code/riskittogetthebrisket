"""Dead-man's switch for the daily alert sweep, and alert delivery health in
``/api/status`` (2026-11-20).

Every ops, source-staleness and backup-coverage alert -- and the Signals
reconnect backstop -- rides on ``POST /api/signal-alerts/run`` (the
``dynasty-signal-alerts`` timer).  A wrong bearer token, a disabled timer or a
backend that is down at 15:00 UTC stops ALL of them, silently: a sweep that never
runs cannot say so.  Pinned here: the sweep stamps its end, ``/api/status``
publishes the age and the in-process delivery record as public-safe values, and
an unknown age is ``None`` -- never 0.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

import server
from src.api import ops_alerts as oa
from src.api import public_diagnostics as pd
from src.api import user_kv
from src.utils import owner_alerts

T0 = 1_800_000_000.0


@pytest.fixture()
def kv(tmp_path):
    path = tmp_path / "kv.sqlite"
    user_kv._SETUP_DONE.clear()
    yield path
    user_kv._SETUP_DONE.clear()


# ── the stamp ───────────────────────────────────────────────────────────────


def test_the_age_is_measured_from_the_last_recorded_sweep(kv):
    oa.record_sweep(now=T0, kv_path=kv)
    assert oa.alert_sweep_age_hours(now=T0 + 2 * 3600, kv_path=kv) == 2.0
    stamp = user_kv.get_user_state(oa._OPS_STATE_USER, path=kv)[oa.SWEEP_STATE_KEY]
    assert stamp["lastSweepAt"].startswith("2027-01-15T") and stamp["lastSweepEpoch"] == T0


def test_no_store_is_unknown_and_reading_creates_nothing(tmp_path):
    missing = tmp_path / "nope.sqlite"
    assert oa.alert_sweep_age_hours(kv_path=missing) is None
    assert not missing.exists(), "a diagnostic read must not create the store"


def test_a_store_without_a_stamp_is_unknown_not_zero(kv):
    user_kv.mutate_user_state(oa._OPS_STATE_USER, lambda e: e.update(other=1), path=kv)
    assert oa.alert_sweep_age_hours(kv_path=kv) is None


@pytest.mark.parametrize("bad", [None, "yesterday", True, {"x": 1}])
def test_an_unreadable_stamp_is_unknown(kv, bad):
    def _apply(entry):
        entry[oa.SWEEP_STATE_KEY] = {"lastSweepEpoch": bad}

    user_kv.mutate_user_state(oa._OPS_STATE_USER, _apply, path=kv)
    assert oa.alert_sweep_age_hours(kv_path=kv) is None


def test_the_stamp_never_touches_the_ops_alert_state(kv):
    def _send(to, subj, body):
        return True

    oa.check_and_alert(data_age_hours=100.0, delivery=_send, to_email="a@b.c", kv_path=kv)
    before = user_kv.get_user_state(oa._OPS_STATE_USER, path=kv)["opsAlertState"]
    oa.record_sweep(kv_path=kv)
    after = user_kv.get_user_state(oa._OPS_STATE_USER, path=kv)["opsAlertState"]
    assert before == after and "data_stale" in after


def test_the_real_sweep_stamps_its_end(monkeypatch, tmp_path):
    """Drive the REAL handler (sections stubbed) and read the stamp back."""
    path = tmp_path / "user_kv.sqlite"
    monkeypatch.setattr(oa, "check_and_alert", lambda **_k: {"fired": 0})
    with TestClient(server.app, raise_server_exceptions=True) as c:
        monkeypatch.setattr(user_kv, "USER_KV_PATH", path)
        monkeypatch.setattr(server, "latest_contract_data", {"players": {}})
        monkeypatch.setattr(server, "SIGNAL_ALERT_CRON_TOKEN", "test-token-deadman")
        monkeypatch.setattr(server._user_kv, "all_user_states", lambda: {})
        res = c.post(
            "/api/signal-alerts/run", headers={"Authorization": "Bearer test-token-deadman"}
        )
    assert res.status_code == 200, res.text
    assert res.json()["sweepRecorded"] is True
    age = oa.alert_sweep_age_hours(kv_path=path)
    assert age is not None and 0.0 <= age < 0.1


def test_a_refused_sweep_stamps_nothing(monkeypatch, tmp_path):
    """401 (bad token) is exactly the outage the switch exists to catch."""
    path = tmp_path / "user_kv.sqlite"
    with TestClient(server.app, raise_server_exceptions=True) as c:
        monkeypatch.setattr(user_kv, "USER_KV_PATH", path)
        monkeypatch.setattr(server, "SIGNAL_ALERT_CRON_TOKEN", "the-right-token")
        res = c.post("/api/signal-alerts/run", headers={"Authorization": "Bearer wrong"})
    assert res.status_code == 401
    assert oa.alert_sweep_age_hours(kv_path=path) is None


# ── /api/status ─────────────────────────────────────────────────────────────


@pytest.fixture()
def status_env(monkeypatch):
    owner_alerts.reset_delivery_health_for_tests()
    monkeypatch.setattr(server, "send_alert", lambda *a, **k: None)
    monkeypatch.delenv("NOTIFY_WEBHOOK_URL", raising=False)
    for name in ("ALERT_ENABLED", "ALERT_TO", "ALERT_FROM", "ALERT_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    yield monkeypatch
    owner_alerts.reset_delivery_health_for_tests()


def _public_status() -> dict:
    return json.loads(asyncio.run(server.get_status()).body)


def test_status_publishes_the_sweep_age_and_unknown_as_null(status_env):
    status_env.setattr(oa, "alert_sweep_age_hours", lambda **_k: 7.25)
    assert _public_status()["alertSweepAgeHours"] == 7.25
    status_env.setattr(oa, "alert_sweep_age_hours", lambda **_k: None)
    body = _public_status()
    assert "alertSweepAgeHours" in body and body["alertSweepAgeHours"] is None


def test_status_publishes_delivery_health_as_booleans_timestamps_and_a_count(status_env):
    status_env.setenv("NOTIFY_WEBHOOK_URL", "https://ntfy.sh/private-topic-for-tests")
    status_env.setattr(oa, "alert_sweep_age_hours", lambda **_k: None)
    owner_alerts.deliver(None, "s", "b", push=lambda s, b: False)
    owner_alerts.deliver(None, "s", "b", push=lambda s, b: False)
    body = _public_status()
    block = body["alertDelivery"]
    assert set(block) == {
        "ntfyConfigured",
        "emailConfigured",
        "lastDeliveredAt",
        "lastFailedAt",
        "consecutiveFailures",
    }
    assert block["ntfyConfigured"] is True and block["emailConfigured"] is False
    assert block["consecutiveFailures"] == 2 and block["lastDeliveredAt"] is None
    assert isinstance(block["lastFailedAt"], str)
    text = json.dumps(body)
    assert "ntfy.sh" not in text and "private-topic" not in text
    assert pd.unsafe_public_values(block) == []


def test_unconfigured_channels_attempt_nothing_and_are_not_failures(status_env):
    status_env.setattr(oa, "alert_sweep_age_hours", lambda **_k: None)
    assert owner_alerts.deliver(None, "s", "b") is False
    block = _public_status()["alertDelivery"]
    assert block == {
        "ntfyConfigured": False,
        "emailConfigured": False,
        "lastDeliveredAt": None,
        "lastFailedAt": None,
        "consecutiveFailures": 0,
    }


def test_a_success_resets_the_failure_streak():
    owner_alerts.reset_delivery_health_for_tests()
    try:
        owner_alerts._record(False, now=T0)
        owner_alerts._record(False, now=T0 + 1)
        owner_alerts._record(True, now=T0 + 2)
        health = owner_alerts.delivery_health({})
        assert health["consecutiveFailures"] == 0
        assert health["lastDeliveredAt"].startswith("2027-01-15T")
        assert health["lastFailedAt"].startswith("2027-01-15T")
    finally:
        owner_alerts.reset_delivery_health_for_tests()
