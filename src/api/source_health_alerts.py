"""Stale-source health alerts.

Detects when a ranking source hasn't refreshed in longer than its
configured ``maxStaleHours`` and emits a one-shot alert (email,
reusing the existing SMTP pipe from signal alerts).

Per-source staleness thresholds live in
``config/source_staleness.json`` — DLF gets 31 days (monthly
refresh), KTC 48 hours, FantasyCalc 7 days, etc.  Rationale: a
DLF source that's "stale" for 30 days is perfectly normal;
flagging it would be pure alert fatigue.

Cooldown: once an alert fires for a source, don't re-fire until
either (a) the source recovers (fresh fetch observed) or (b)
``_REALERT_COOLDOWN_HOURS`` have passed.  Cooldown state lives
in ``user_kv`` keyed under ``sourceHealthAlertState`` so it
survives restart.

Recovery alerts: when a previously-stale source comes back, emit
a one-shot "is back" email.  Bi-directional so Jason always
knows the current health state.

Integration point: the signal-alert cron calls ``check_and_alert()``
as part of its sweep — no new cron required.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.api import user_kv

_LOGGER = logging.getLogger(__name__)

# Default cooldown between re-alerts for the same source.
_REALERT_COOLDOWN_HOURS = 72.0

_DEFAULT_STALENESS_HOURS: dict[str, float] = {
    # Daily refresh sources.
    "ktc": 48,
    "idpTradeCalc": 48,
    "fantasyCalc": 168,  # 7 days — updates weekly
    # Monthly / slow sources.
    "dlf": 31 * 24,  # 31 days
    "dynastyDaddy": 168,
    "dynastyNerds": 168,
    "fantasyPros": 168,
    "pff": 168,
}


@dataclass(frozen=True)
class StaleSourceAlert:
    source: str
    last_seen_iso: str
    hours_stale: float
    threshold_hours: float
    transition: str  # "stale" | "recovered"


def load_thresholds(path: Path | None = None) -> dict[str, float]:
    if path is None:
        repo = Path(__file__).resolve().parents[2]
        path = repo / "config" / "source_staleness.json"
    out = dict(_DEFAULT_STALENESS_HOURS)
    if not path.exists():
        return out
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return out
    if isinstance(raw, dict):
        core = raw.get("thresholds") if "thresholds" in raw else raw
        if isinstance(core, dict):
            for k, v in core.items():
                try:
                    out[str(k)] = float(v)
                except (TypeError, ValueError):
                    continue
    return out


def _iso_to_epoch(ts: str) -> float:
    if not ts:
        return 0.0
    try:
        from datetime import datetime
        # Handle both Z suffix and +00:00.
        clean = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(clean).timestamp()
    except Exception:  # noqa: BLE001
        return 0.0


def detect_stale_sources(
    source_health: dict[str, Any],
    *,
    thresholds: dict[str, float] | None = None,
    now_epoch: float | None = None,
) -> list[StaleSourceAlert]:
    """Given the ``/api/status.source_health`` shape, return the
    stale-source alerts (no cooldown consideration — that's the
    caller's concern)."""
    thresholds = thresholds or load_thresholds()
    now = now_epoch or time.time()
    out: list[StaleSourceAlert] = []
    if not isinstance(source_health, dict):
        return out
    # source_health shape: {"sourceName": {"lastFetched": "iso", ...}, ...}
    # Can be nested under "sources" or flat — tolerate both.
    sources = source_health.get("sources") if "sources" in source_health else source_health
    if not isinstance(sources, dict):
        return out
    for src, entry in sources.items():
        if not isinstance(entry, dict):
            continue
        last_seen_iso = str(
            entry.get("lastFetched")
            or entry.get("lastSeen")
            or entry.get("lastFetchedAt")
            or ""
        )
        if not last_seen_iso:
            continue
        last_epoch = _iso_to_epoch(last_seen_iso)
        if last_epoch <= 0:
            continue
        hours_stale = (now - last_epoch) / 3600.0
        threshold = thresholds.get(src, 168.0)  # default 7d
        if hours_stale > threshold:
            out.append(StaleSourceAlert(
                source=src, last_seen_iso=last_seen_iso,
                hours_stale=round(hours_stale, 1),
                threshold_hours=threshold,
                transition="stale",
            ))
    return out


def check_and_alert(
    source_health: dict[str, Any],
    *,
    delivery: Callable[[str, str, str], bool] | None = None,
    to_email: str | None = None,
    thresholds: dict[str, float] | None = None,
    kv_path: Any = None,
    cooldown_hours: float = _REALERT_COOLDOWN_HOURS,
) -> dict[str, Any]:
    """Full pipeline: detect staleness, apply cooldown, deliver
    alerts.  Writes state to user_kv under the synthetic username
    ``_system_source_health``.

    Returns a summary dict for logging::

        {"stale": int, "recovered": int, "delivered": int,
         "skipped_cooldown": int}
    """
    state_user = "_system_source_health"
    state = user_kv.get_user_state(state_user, path=kv_path)
    alert_state = dict(state.get("sourceHealthAlertState") or {})
    now = time.time()
    stale = detect_stale_sources(
        source_health, thresholds=thresholds, now_epoch=now,
    )
    stale_sources = {a.source for a in stale}

    # Detect recovery transitions — sources in alert_state marked stale
    # that are NO longer stale now.
    recovery_alerts: list[StaleSourceAlert] = []
    for src, entry in list(alert_state.items()):
        if not isinstance(entry, dict):
            continue
        if entry.get("currentlyStale") and src not in stale_sources:
            recovery_alerts.append(StaleSourceAlert(
                source=src,
                last_seen_iso=str(entry.get("lastAlertedAt") or ""),
                hours_stale=0.0,
                threshold_hours=0.0,
                transition="recovered",
            ))

    summary = {"stale": 0, "recovered": 0, "delivered": 0, "skipped_cooldown": 0}
    to_send: list[StaleSourceAlert] = []

    # Stale alerts — apply cooldown.
    for alert in stale:
        prev = alert_state.get(alert.source) or {}
        last_alerted = float(prev.get("lastAlertedAt") or 0)
        cooldown_sec = cooldown_hours * 3600.0
        if prev.get("currentlyStale") and (now - last_alerted) < cooldown_sec:
            summary["skipped_cooldown"] += 1
            continue
        to_send.append(alert)
        alert_state[alert.source] = {
            "currentlyStale": True,
            "lastAlertedAt": now,
            "lastSeenIso": alert.last_seen_iso,
            "hoursStale": alert.hours_stale,
        }
        summary["stale"] += 1

    # Recovery alerts always fire (they're inherently rate-limited by
    # the "was previously stale" precondition).
    for r in recovery_alerts:
        to_send.append(r)
        alert_state[r.source] = {
            "currentlyStale": False,
            "lastAlertedAt": now,
        }
        summary["recovered"] += 1

    # Persist state BEFORE sending so a delivery crash doesn't cause
    # re-alerts next pass.
    user_kv.merge_user_state(
        state_user, {"sourceHealthAlertState": alert_state}, path=kv_path,
    )

    if not to_send:
        return summary
    if delivery is None or not to_email:
        return summary
    subject = _format_subject(to_send)
    body = _format_body(to_send)
    try:
        if delivery(to_email, subject, body):
            summary["delivered"] = len(to_send)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("source_health alert delivery failed: %s", exc)
    return summary


def _format_subject(alerts: list[StaleSourceAlert]) -> str:
    stale = [a for a in alerts if a.transition == "stale"]
    recovered = [a for a in alerts if a.transition == "recovered"]
    if stale and recovered:
        return f"[Brisket Ops] {len(stale)} stale / {len(recovered)} recovered sources"
    if stale:
        return f"[Brisket Ops] {len(stale)} source{'s' if len(stale)!=1 else ''} stale"
    return f"[Brisket Ops] {len(recovered)} source{'s' if len(recovered)!=1 else ''} recovered"


def _format_body(alerts: list[StaleSourceAlert]) -> str:
    lines = []
    stale = [a for a in alerts if a.transition == "stale"]
    recovered = [a for a in alerts if a.transition == "recovered"]
    if stale:
        lines.append("Stale sources:")
        for a in stale:
            lines.append(
                f"  • {a.source}: {a.hours_stale:.1f}h stale "
                f"(threshold {a.threshold_hours:.0f}h) — last seen {a.last_seen_iso}"
            )
        lines.append("")
    if recovered:
        lines.append("Recovered sources:")
        for a in recovered:
            lines.append(f"  • {a.source}: back")
        lines.append("")
    lines.append("See https://riskittogetthebrisket.org/tools/source-health")
    return "\n".join(lines)
