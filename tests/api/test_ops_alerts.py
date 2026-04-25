"""Tests for the operator alerting hook."""
from __future__ import annotations

import pytest

from src.api import ops_alerts as oa
from src.api import user_kv


@pytest.fixture()
def kv(tmp_path):
    path = tmp_path / "kv.sqlite"
    user_kv._SETUP_DONE.clear()
    yield path
    user_kv._SETUP_DONE.clear()


def test_scrape_rate_above_threshold_no_alert():
    a = oa._check_scrape_rate({"scrape_success_rate_24h": 0.9})  # noqa: SLF001
    assert a is None


def test_scrape_rate_below_50_warns():
    a = oa._check_scrape_rate({"scrape_success_rate_24h": 0.4})  # noqa: SLF001
    assert a is not None
    assert a.severity == "warning"
    assert a.category == "scrape_failure"


def test_scrape_rate_below_25_critical():
    a = oa._check_scrape_rate({"scrape_success_rate_24h": 0.1})  # noqa: SLF001
    assert a.severity == "critical"


def test_circuit_breaker_open_briefly_not_alerted():
    alerts = oa._check_circuit_breakers([{  # noqa: SLF001
        "name": "sleeper", "state": "open", "stateAgeSec": 60,
    }])
    assert alerts == []


def test_circuit_breaker_open_long_alerts():
    alerts = oa._check_circuit_breakers([{  # noqa: SLF001
        "name": "sleeper", "state": "open", "stateAgeSec": 900,
        "lastError": "Connection refused",
        "counters": {"fastFail": 50},
    }])
    assert len(alerts) == 1
    assert alerts[0].category == "circuit_open:sleeper"
    assert "sleeper" in alerts[0].title


def test_contract_unhealthy_fires():
    a = oa._check_contract_health({  # noqa: SLF001
        "ok": False,
        "errors": ["partial_run_critical:KTC", "schema_drift"],
    })
    assert a is not None
    assert a.severity == "critical"


def test_data_freshness_below_threshold_no_alert():
    a = oa._check_data_freshness(5.0, scrape_interval_hours=2.0)  # noqa: SLF001
    # 5h < 6h (2×3), no alert.
    assert a is None


def test_data_freshness_over_threshold_warns():
    a = oa._check_data_freshness(10.0, scrape_interval_hours=2.0)  # noqa: SLF001
    assert a is not None
    assert a.category == "data_stale"


def test_cooldown_prevents_re_fire(kv):
    delivered = []
    def _send(to, subj, body):
        delivered.append((to, subj))
        return True
    status = {"scrape_success_rate_24h": 0.1}
    s1 = oa.check_and_alert(
        status_payload=status, delivery=_send,
        to_email="a@b.com", kv_path=kv,
    )
    s2 = oa.check_and_alert(
        status_payload=status, delivery=_send,
        to_email="a@b.com", kv_path=kv,
    )
    assert s1["fired"] == 1
    assert s2["fired"] == 0  # cooled down
    assert len(delivered) == 1


def test_recovery_alert_fires_when_condition_clears(kv):
    delivered = []
    def _send(to, subj, body):
        delivered.append((to, subj, body))
        return True
    # First pass: scrape rate low → alert.
    oa.check_and_alert(
        status_payload={"scrape_success_rate_24h": 0.1},
        delivery=_send, to_email="a@b.com", kv_path=kv,
    )
    assert len(delivered) == 1
    assert "critical" in delivered[0][1].lower()
    # Second pass: scrape rate healthy → recovery alert.
    s = oa.check_and_alert(
        status_payload={"scrape_success_rate_24h": 0.95},
        delivery=_send, to_email="a@b.com", kv_path=kv,
    )
    assert s["recovered"] == 1
    assert len(delivered) == 2
    assert "recovered" in delivered[1][1].lower()


def test_format_ops_email_has_sections():
    alerts = [
        oa.OpsAlert(severity="critical", category="x", title="Bad", detail="Very bad"),
        oa.OpsAlert(severity="warning", category="y", title="Meh", detail="Meh-ish"),
    ]
    subject, body = oa.format_ops_email(alerts)
    assert "critical" in subject.lower()
    assert "warning" in subject.lower()
    assert "CRITICAL" in body
    assert "WARNING" in body
    assert "status" in body.lower()


def test_no_alerts_no_delivery(kv):
    delivered = []
    def _send(to, subj, body):
        delivered.append(1)
        return True
    s = oa.check_and_alert(
        status_payload={"scrape_success_rate_24h": 0.99},
        delivery=_send, to_email="a@b.com", kv_path=kv,
    )
    assert s["fired"] == 0
    assert delivered == []


def test_never_crashes_on_missing_delivery(kv):
    # No delivery callable → just returns summary.
    s = oa.check_and_alert(
        status_payload={"scrape_success_rate_24h": 0.1},
        delivery=None, kv_path=kv,
    )
    assert s["delivered"] is False
    assert s["fired"] == 1
