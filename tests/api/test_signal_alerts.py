"""Tests for ``src.api.signal_alerts``."""
from __future__ import annotations

import time

import pytest

from src.api import signal_alerts, user_kv


@pytest.fixture()
def kv_path(tmp_path):
    return tmp_path / "user_kv.sqlite"


@pytest.fixture(autouse=True)
def _reset_setup_cache():
    user_kv._SETUP_DONE.clear()
    yield
    user_kv._SETUP_DONE.clear()


def _sig(name, tag, signal, sid="", dismissed=False):
    return {
        "name": name,
        "pos": "QB",
        "signal": signal,
        "reason": f"{signal} reason",
        "tag": tag,
        "signalKey": f"{name}::{tag}",
        "aliasSignalKey": f"sid:{sid}::{tag}" if sid else "",
        "sleeperId": sid,
        "dismissed": dismissed,
    }


def test_first_time_signal_fires(kv_path):
    transitions = signal_alerts.detect_signal_transitions(
        "alice",
        [_sig("Josh Allen", "elite_stable", "SELL", sid="4017")],
        path=kv_path,
    )
    assert len(transitions) == 1
    assert transitions[0]["name"] == "Josh Allen"
    assert transitions[0]["signal"] == "SELL"
    assert transitions[0]["priorSignal"] is None


def test_unchanged_signal_does_not_fire(kv_path):
    signals = [_sig("Josh Allen", "elite_stable", "SELL", sid="4017")]
    signal_alerts.detect_signal_transitions("alice", signals, path=kv_path)
    second = signal_alerts.detect_signal_transitions("alice", signals, path=kv_path)
    assert second == []


def test_changed_signal_fires_after_cooldown(kv_path, monkeypatch):
    signal_alerts.detect_signal_transitions(
        "alice",
        [_sig("Josh Allen", "elite_stable", "SELL", sid="4017")],
        path=kv_path,
    )
    # Fast-forward well beyond the 12-hour cooldown.
    import src.api.signal_alerts as mod
    fake_now = mod._utc_now_ms() + 24 * 3600 * 1000
    monkeypatch.setattr(mod, "_utc_now_ms", lambda: fake_now)
    transitions = signal_alerts.detect_signal_transitions(
        "alice",
        [_sig("Josh Allen", "elite_stable", "BUY", sid="4017")],
        path=kv_path,
    )
    assert len(transitions) == 1
    assert transitions[0]["priorSignal"] == "SELL"
    assert transitions[0]["signal"] == "BUY"


def test_cooldown_suppresses_rapid_flicker(kv_path):
    # First transition: fires.
    signal_alerts.detect_signal_transitions(
        "alice",
        [_sig("Josh Allen", "elite_stable", "SELL", sid="4017")],
        path=kv_path,
    )
    # Immediate re-evaluation with a different signal — should be
    # suppressed by the 12-hour cooldown guard.
    result = signal_alerts.detect_signal_transitions(
        "alice",
        [_sig("Josh Allen", "elite_stable", "BUY", sid="4017")],
        path=kv_path,
    )
    assert result == []


def test_hold_signals_never_fire(kv_path):
    transitions = signal_alerts.detect_signal_transitions(
        "alice",
        [_sig("Josh Allen", "default_hold", "HOLD", sid="4017")],
        path=kv_path,
    )
    assert transitions == []


def test_dismissed_signal_never_fires(kv_path):
    transitions = signal_alerts.detect_signal_transitions(
        "alice",
        [_sig("Josh Allen", "elite_stable", "SELL", sid="4017", dismissed=True)],
        path=kv_path,
    )
    assert transitions == []


def test_monitor_signal_fires(kv_path):
    transitions = signal_alerts.detect_signal_transitions(
        "alice",
        [_sig("Josh Allen", "alert_present", "MONITOR", sid="4017")],
        path=kv_path,
    )
    assert len(transitions) == 1
    assert transitions[0]["signal"] == "MONITOR"


def test_format_alert_email_contains_all_transitions():
    transitions = [
        {
            "signalKey": "Josh Allen::elite_stable",
            "name": "Josh Allen",
            "pos": "QB",
            "signal": "SELL",
            "priorSignal": "HOLD",
            "reason": "Sustained downtrend.",
            "sleeperId": "4017",
        },
        {
            "signalKey": "Bijan::elite_stable",
            "name": "Bijan Robinson",
            "pos": "RB",
            "signal": "BUY",
            "priorSignal": None,
            "reason": "Uptrend.",
            "sleeperId": "9479",
        },
    ]
    formatted = signal_alerts.format_alert_email("Alice", transitions)
    assert "2 signal updates" in formatted["subject"]
    assert "Josh Allen" in formatted["body"]
    assert "Bijan Robinson" in formatted["body"]
    assert "HOLD → SELL" in formatted["body"]
    assert "— → BUY" in formatted["body"]


def test_process_user_alerts_invokes_delivery(kv_path):
    calls = []

    def fake_delivery(to, subject, body):
        calls.append({"to": to, "subject": subject, "body": body})
        return True

    result = signal_alerts.process_user_alerts(
        "alice",
        signals=[_sig("Josh Allen", "elite_stable", "SELL", sid="4017")],
        display_name="Alice",
        email="alice@example.com",
        delivery=fake_delivery,
        path=kv_path,
    )
    assert result["transitions"] == 1
    assert result["delivered"] is True
    assert len(calls) == 1
    assert calls[0]["to"] == "alice@example.com"
    assert "Josh Allen" in calls[0]["body"]


def test_process_user_alerts_skips_when_no_email(kv_path):
    result = signal_alerts.process_user_alerts(
        "alice",
        signals=[_sig("Josh Allen", "elite_stable", "SELL", sid="4017")],
        email=None,
        delivery=lambda t, s, b: True,
        path=kv_path,
    )
    assert result["delivered"] is False
    assert result["reason"] == "no_email"


def test_process_user_alerts_honors_delivery_error(kv_path):
    def boom(to, s, b):
        raise RuntimeError("smtp unreachable")

    result = signal_alerts.process_user_alerts(
        "alice",
        signals=[_sig("Josh Allen", "elite_stable", "SELL", sid="4017")],
        email="alice@example.com",
        delivery=boom,
        path=kv_path,
    )
    assert result["delivered"] is False
    assert "delivery_error" in result["reason"]


# ── /api/signal-alerts/run endpoint auth tests ────────────────────
# These exercise the auth-gating on the HTTP layer.  We stub out
# ``latest_contract_data`` so the endpoint gets past the 503 guard
# and can reach the auth branch.  No SMTP is touched because no
# users in the user_kv have ``notificationsEnabled`` set.


def test_signal_alerts_run_rejects_unauthenticated(monkeypatch):
    from fastapi.testclient import TestClient

    import server

    monkeypatch.setattr(server, "latest_contract_data", {"stub": True})
    monkeypatch.setattr(server, "SIGNAL_ALERT_CRON_TOKEN", "")
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/signal-alerts/run")
    assert res.status_code == 401


def test_signal_alerts_run_accepts_bearer_token(monkeypatch, tmp_path):
    """With SIGNAL_ALERT_CRON_TOKEN set and a matching bearer header,
    the endpoint processes the sweep (even though no users qualify)."""
    from fastapi.testclient import TestClient

    import server

    monkeypatch.setattr(server, "latest_contract_data", {"players": {}})
    monkeypatch.setattr(server, "SIGNAL_ALERT_CRON_TOKEN", "test-token-abc123")
    # all_user_states() returns {} in a fresh temp env; stub it so
    # we don't depend on the real user_kv.sqlite on this box.
    monkeypatch.setattr(server._user_kv, "all_user_states", lambda: {})
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post(
            "/api/signal-alerts/run",
            headers={"Authorization": "Bearer test-token-abc123"},
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["processed"] == 0


def test_signal_alerts_run_rejects_wrong_bearer_token(monkeypatch):
    from fastapi.testclient import TestClient

    import server

    monkeypatch.setattr(server, "latest_contract_data", {"players": {}})
    monkeypatch.setattr(server, "SIGNAL_ALERT_CRON_TOKEN", "real-token")
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post(
            "/api/signal-alerts/run",
            headers={"Authorization": "Bearer wrong-token"},
        )
    assert res.status_code == 401


def test_signal_alerts_run_ignores_bearer_when_token_unset(monkeypatch):
    """Sanity check: an empty server token must never authorize an
    arbitrary bearer header — otherwise a blank .env would make the
    endpoint open to the internet."""
    from fastapi.testclient import TestClient

    import server

    monkeypatch.setattr(server, "latest_contract_data", {"players": {}})
    monkeypatch.setattr(server, "SIGNAL_ALERT_CRON_TOKEN", "")
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post(
            "/api/signal-alerts/run",
            headers={"Authorization": "Bearer anything"},
        )
    assert res.status_code == 401
