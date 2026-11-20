"""Alerting rules of ``scripts/check_production_slo.py`` (2026-11-20).

A box that cannot reach its owner, or whose daily alert sweep stopped, cannot
report either fact itself -- so the external SLO check reads both from
``/api/status`` and breaches.  Unmeasurable is UNKNOWN, never OK.  Pure rules
over a ``Snapshot``: no network, no git.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
slo = sys.modules.get("check_production_slo")
if slo is None:
    _spec = importlib.util.spec_from_file_location(
        "check_production_slo", _REPO / "scripts/check_production_slo.py"
    )
    slo = importlib.util.module_from_spec(_spec)
    sys.modules["check_production_slo"] = slo
    _spec.loader.exec_module(slo)

CFG = json.loads((_REPO / "config/ops/production_slo.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def delivery(**over) -> dict:
    base = {
        "ntfyConfigured": True,
        "emailConfigured": False,
        "lastDeliveredAt": "2026-11-20T06:00:00+00:00",
        "lastFailedAt": None,
        "consecutiveFailures": 0,
    }
    base.update(over)
    return base


def snap(alerting, reachable=True) -> "slo.Snapshot":
    return slo.Snapshot(now=NOW, alerting=alerting, status_reachable=reachable)


def rules(s) -> dict:
    return {
        r.rule: r for r in slo.evaluate(s, CFG, (slo.rule_alert_delivery, slo.rule_alert_sweep_age))
    }


DELIVERY = "alerting.alert_delivery_failing"
SWEEP = "alerting.alert_sweep_age"


def test_thresholds_come_from_config():
    assert CFG["alerting"]["maxConsecutiveDeliveryFailures"] == 3
    assert CFG["alerting"]["maxAlertSweepAgeHours"] == 30
    assert slo.rule_alert_delivery in slo.RULES and slo.rule_alert_sweep_age in slo.RULES


def test_healthy_alerting_is_ok():
    out = rules(snap({"alertDelivery": delivery(), "alertSweepAgeHours": 3.0}))
    assert out[DELIVERY].status == slo.OK and out[SWEEP].status == slo.OK
    assert all(r.category == slo.ALERTING for r in out.values())


@pytest.mark.parametrize(("failures", "status"), [(2, "OK"), (3, "BREACH"), (9, "BREACH")])
def test_consecutive_delivery_failures_breach_at_the_limit(failures, status):
    r = rules(snap({"alertDelivery": delivery(consecutiveFailures=failures)}))[DELIVERY]
    assert r.status == status and r.threshold == 3
    assert r.measured["consecutiveFailures"] == failures


def test_no_channel_configured_cannot_fail_and_says_so():
    block = delivery(ntfyConfigured=False, emailConfigured=False, lastDeliveredAt=None)
    r = rules(snap({"alertDelivery": block}))[DELIVERY]
    assert r.status == slo.OK and "no owner alert channel" in r.detail


@pytest.mark.parametrize(
    "alerting",
    [
        {},  # deployed build predates the field
        {"alertDelivery": "nope"},
        {"alertDelivery": delivery(consecutiveFailures=None)},
        {"alertDelivery": delivery(consecutiveFailures=True)},
        {"alertDelivery": {"error": "unavailable"}},
    ],
)
def test_unmeasurable_delivery_is_unknown_never_ok(alerting):
    assert rules(snap(alerting))[DELIVERY].status == slo.UNKNOWN


def _no_attempt(ntfy, email, record):
    block = delivery(
        ntfyConfigured=ntfy,
        emailConfigured=email,
        lastDeliveredAt=None,
        lastFailedAt=None,
        consecutiveFailures=None,
    )
    if record is not None:
        block["deliveryRecord"] = record
    return rules(snap({"alertDelivery": block}))[DELIVERY]


@pytest.mark.parametrize("record", ["none", "unreadable", None])
def test_no_channel_configured_is_ok_whatever_the_record(record):
    """Production today: no channel, so nothing is attempted and nothing can
    fail.  The rule must not turn the scheduled health check red forever
    (2026-11-20 re-review: an UNKNOWN here exited 3 on every cron run)."""
    r = _no_attempt(False, False, record)
    assert r.status == slo.OK and "no owner alert channel" in r.detail
    assert r.measured["consecutiveFailures"] is None  # published as unknown, never 0


def test_a_configured_channel_with_no_attempt_yet_is_ok_and_says_so():
    """The box persists every attempt, so ``deliveryRecord: none`` is a
    measured zero attempts: nothing has failed."""
    r = _no_attempt(True, False, "none")
    assert r.status == slo.OK and "no delivery has been attempted yet" in r.detail


@pytest.mark.parametrize(("record", "why"), [("unreadable", "unreadable"), (None, "not reported")])
def test_an_unreadable_or_unreported_record_with_a_channel_is_unknown(record, why):
    r = _no_attempt(True, False, record)
    assert r.status == slo.UNKNOWN and r.measured is None and why in r.detail


@pytest.mark.parametrize(
    ("age", "status"), [(0.5, "OK"), (30.0, "OK"), (30.01, "BREACH"), (90, "BREACH")]
)
def test_an_old_sweep_breaches(age, status):
    r = rules(snap({"alertSweepAgeHours": age}))[SWEEP]
    assert r.status == status and r.measured == age and r.threshold == 30


@pytest.mark.parametrize(
    "alerting", [{}, {"alertSweepAgeHours": None}, {"alertSweepAgeHours": "1h"}]
)
def test_a_missing_sweep_age_is_unknown_never_fresh(alerting):
    r = rules(snap(alerting))[SWEEP]
    assert r.status == slo.UNKNOWN and r.measured is None


def test_absent_fields_name_the_reason():
    out = rules(snap({}))
    assert out[DELIVERY].detail.startswith("status_block_absent")
    assert out[SWEEP].detail.startswith("status_block_absent")


def test_unreachable_status_is_unknown():
    out = rules(snap(None, reachable=False))
    assert {r.status for r in out.values()} == {slo.UNKNOWN}


def test_the_report_has_an_alerting_section_and_no_secret():
    results = slo.evaluate(
        snap({"alertDelivery": delivery(consecutiveFailures=4), "alertSweepAgeHours": 40.0}),
        CFG,
        (slo.rule_alert_delivery, slo.rule_alert_sweep_age),
    )
    text = slo.render(results, NOW)
    assert "alerting:" in text
    assert f"BREACHED: {DELIVERY}, {SWEEP}" in text
    assert "ntfy.sh" not in text and "private-topic" not in text
    assert slo.exit_code(results) == 1


def test_the_live_snapshot_copies_only_present_fields(monkeypatch):
    """``build_live_snapshot`` keeps "absent" distinct from "null"."""
    status = {"alertSweepAgeHours": None, "build": {}}
    monkeypatch.setattr(slo, "fetch_status", lambda url: (status, ""))
    monkeypatch.setattr(slo, "fetch_runs", lambda *a, **k: [])
    args = slo.parse_args(["--url", "https://example.invalid"])
    s = slo.build_live_snapshot(args, CFG)
    assert s.alerting == {"alertSweepAgeHours": None}
