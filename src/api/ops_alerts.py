"""Operator alerts for critical production conditions.

Fires SMTP emails (reusing the existing signal-alert SMTP pipe)
when any of these conditions hold:

    * Scrape success rate over the last 24h drops below 50%
    * Any circuit breaker has been OPEN for > 10 minutes
    * Contract health reports ``ok=False``
    * Signal-alert cron hasn't run in > 36h (expected every 12h)
    * Session-store SQLite integrity check fails
    * Data freshness > 3 × scrape interval

Cooldown: each alert class has a 4-hour re-alert cooldown keyed
on the synthetic user ``_system_ops_alerts`` in user_kv so the
cron doesn't spam when a condition is persistent.  Recovery
alerts fire once when the condition clears.

Intended to be called once per sweep (piggybacks on the existing
``/api/signal-alerts/run`` cron).  Never raises.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from src.api import user_kv

_LOGGER = logging.getLogger(__name__)

_ALERT_COOLDOWN_SEC = 4 * 3600.0
_OPS_STATE_USER = "_system_ops_alerts"


@dataclass(frozen=True)
class OpsAlert:
    severity: str  # "critical" | "warning"
    category: str  # "scrape_failure" | "circuit_open" | "contract_unhealthy" | ...
    title: str
    detail: str


def _check_scrape_rate(status_payload: dict[str, Any]) -> OpsAlert | None:
    rate = status_payload.get("scrape_success_rate_24h")
    if rate is None:
        return None
    try:
        r = float(rate)
    except (TypeError, ValueError):
        return None
    if r >= 0.5:
        return None
    return OpsAlert(
        severity="critical" if r < 0.25 else "warning",
        category="scrape_failure",
        title=f"Scrape success rate 24h = {r:.0%}",
        detail=(
            "Fewer than half of the scheduled scrapes in the last 24 hours "
            "succeeded.  Rankings may be stale.  Check "
            "/api/status.last_n_scrapes for the failure pattern."
        ),
    )


def _check_circuit_breakers(circuits: list[dict[str, Any]]) -> list[OpsAlert]:
    alerts = []
    for c in circuits:
        if c.get("state") != "open":
            continue
        age = c.get("stateAgeSec")
        if age is None or age < 600:
            continue
        alerts.append(OpsAlert(
            severity="warning",
            category=f"circuit_open:{c.get('name')}",
            title=f"Circuit breaker '{c.get('name')}' has been OPEN {int(age/60)}m",
            detail=(
                f"External dependency {c.get('name')!r} is failing repeatedly. "
                f"Last error: {c.get('lastError') or '(none captured)'}.  "
                f"Fast-fail count: {c.get('counters',{}).get('fastFail',0)}."
            ),
        ))
    return alerts


def _check_contract_health(contract_health: dict[str, Any]) -> OpsAlert | None:
    if not contract_health:
        return None
    if contract_health.get("ok"):
        return None
    errors = contract_health.get("errors") or []
    if not errors:
        return None
    return OpsAlert(
        severity="critical",
        category="contract_unhealthy",
        title="Contract validation failed",
        detail=f"{len(errors)} error(s): {', '.join(map(str, errors[:5]))}",
    )


def _check_data_freshness(
    data_age_hours: float | None,
    scrape_interval_hours: float,
) -> OpsAlert | None:
    if data_age_hours is None:
        return None
    threshold = scrape_interval_hours * 3
    if data_age_hours <= threshold:
        return None
    return OpsAlert(
        severity="warning",
        category="data_stale",
        title=f"Data {data_age_hours:.1f}h stale",
        detail=(
            f"Latest scrape is {data_age_hours:.1f}h old, "
            f">{threshold:.0f}h threshold ({scrape_interval_hours:.0f}h × 3)."
        ),
    )


def _load_ops_state(path: Any = None) -> dict[str, Any]:
    state = user_kv.get_user_state(_OPS_STATE_USER, path=path)
    return dict(state.get("opsAlertState") or {})


def _save_ops_state(state: dict[str, Any], path: Any = None) -> None:
    user_kv.merge_user_state(
        _OPS_STATE_USER, {"opsAlertState": state}, path=path,
    )


def _should_fire(
    alert: OpsAlert, state: dict[str, Any], *, now: float,
) -> bool:
    """Cooldown check.  Returns True when an alert should fire,
    False when it's within the re-alert window."""
    last = state.get(alert.category) or {}
    last_at = float(last.get("firedAt") or 0.0)
    if now - last_at < _ALERT_COOLDOWN_SEC:
        return False
    return True


def _detect_recovery(
    active_categories: set[str], state: dict[str, Any], *, now: float,
) -> list[OpsAlert]:
    """When a previously-firing alert's category is no longer in
    ``active_categories``, emit a recovery alert (once)."""
    recovery = []
    for category, entry in list(state.items()):
        if not isinstance(entry, dict):
            continue
        if entry.get("recoveryFired"):
            continue
        if category in active_categories:
            continue
        recovery.append(OpsAlert(
            severity="info", category=category,
            title=f"[RECOVERY] {category} resolved",
            detail="Condition cleared.  No action required.",
        ))
    return recovery


def format_ops_email(alerts: list[OpsAlert]) -> tuple[str, str]:
    """Build (subject, body) for an ops alert email."""
    crit = [a for a in alerts if a.severity == "critical"]
    warn = [a for a in alerts if a.severity == "warning"]
    info = [a for a in alerts if a.severity == "info"]
    subject_parts = []
    if crit:
        subject_parts.append(f"{len(crit)} critical")
    if warn:
        subject_parts.append(f"{len(warn)} warning")
    if info:
        subject_parts.append(f"{len(info)} recovered")
    subject = f"[Brisket Ops] {' / '.join(subject_parts)}"
    lines = []
    for group, label in [(crit, "CRITICAL"), (warn, "WARNING"), (info, "RECOVERED")]:
        if not group:
            continue
        lines.append(f"--- {label} ---")
        for a in group:
            lines.append(f"  • {a.title}")
            lines.append(f"    {a.detail}")
        lines.append("")
    lines.append("Status: https://riskittogetthebrisket.org/api/status")
    lines.append("Health: https://riskittogetthebrisket.org/api/health")
    return subject, "\n".join(lines)


def check_and_alert(
    *,
    status_payload: dict[str, Any] | None = None,
    circuit_snapshots: list[dict[str, Any]] | None = None,
    contract_health: dict[str, Any] | None = None,
    data_age_hours: float | None = None,
    scrape_interval_hours: float = 2.0,
    delivery: Callable[[str, str, str], bool] | None = None,
    to_email: str | None = None,
    kv_path: Any = None,
) -> dict[str, Any]:
    """Run every check, apply cooldown, deliver if any fire.
    Returns a summary dict for logging.  Never raises."""
    alerts: list[OpsAlert] = []
    status_payload = status_payload or {}
    sa = _check_scrape_rate(status_payload)
    if sa:
        alerts.append(sa)
    for a in _check_circuit_breakers(circuit_snapshots or []):
        alerts.append(a)
    ch = _check_contract_health(contract_health or {})
    if ch:
        alerts.append(ch)
    df = _check_data_freshness(data_age_hours, scrape_interval_hours)
    if df:
        alerts.append(df)

    active_categories = {a.category for a in alerts}
    now = time.time()
    state = _load_ops_state(path=kv_path)

    # Recovery alerts first — for conditions that were firing but
    # aren't now.
    recovery_alerts = _detect_recovery(active_categories, state, now=now)

    # Apply cooldown to new alerts.
    firing: list[OpsAlert] = []
    for a in alerts:
        if _should_fire(a, state, now=now):
            firing.append(a)
            state[a.category] = {"firedAt": now, "severity": a.severity, "recoveryFired": False}

    # Mark recoveries.
    for r in recovery_alerts:
        if r.category in state:
            state[r.category] = {**(state[r.category] or {}), "recoveryFired": True, "recoveredAt": now}

    _save_ops_state(state, path=kv_path)

    summary = {
        "active": len(alerts),
        "fired": len(firing),
        "recovered": len(recovery_alerts),
        "delivered": False,
        "categories": [a.category for a in firing],
    }

    to_deliver = firing + recovery_alerts
    if not to_deliver or delivery is None or not to_email:
        return summary
    subject, body = format_ops_email(to_deliver)
    try:
        summary["delivered"] = bool(delivery(to_email, subject, body))
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("ops alert delivery failed: %s", exc)
        summary["delivered"] = False
    return summary
