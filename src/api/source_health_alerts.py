"""Stale-source health alerts.

Detects when a ranking source hasn't refreshed in longer than its
configured ``maxStaleHours`` and emits a one-shot alert (email,
reusing the existing SMTP pipe from signal alerts).

Per-source staleness thresholds live in
``config/source_staleness.json``.  Default policy: every source is
24h.  The 2h scheduled-refresh cron writes each source's CSV
unconditionally on a successful fetch, so a >24h gap means
roughly twelve consecutive fetches failed — actionable, not
alert fatigue.  Slower vendor cadences are irrelevant because the
fetcher overwrites the CSV with whatever the page currently
serves; mtime tracks scrape health, not vendor publish events.

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
    # Universal 24h policy: every source is fetched on the 2h cron
    # and overwrites its CSV on success, so a >24h mtime gap means
    # ~12 consecutive failed fetches and warrants investigation.
    # Per-source overrides live in ``config/source_staleness.json``.
    "ktc": 24,
    "idpTradeCalc": 24,
    "fantasyCalc": 24,
    "dlf": 24,
    "dynastyDaddy": 24,
    "dynastyNerds": 24,
    "fantasyPros": 24,
    "draftSharks": 24,
    "flockFantasy": 24,
    "yahooBoone": 24,
    "idpShow": 24,
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


def resolve_threshold(src: str, thresholds: dict[str, float]) -> float:
    """Look up the staleness threshold for ``src``.

    Match order (matches the contract documented in
    ``config/source_staleness.json``):

    1. **Exact key** — ``thresholds["dlfSf"]`` wins for
       ``src="dlfSf"``.  Lets operators pin a single board if a
       vendor's other boards refresh on a different cadence.
    2. **Vendor prefix** — ``thresholds["dlf"]`` matches every
       ``dlfSf`` / ``dlfIdp`` / ``dlfRookieSf`` / ``dlfRookieIdp``
       registry key.  The prefix must end at a word boundary (the
       character after the prefix in ``src`` must be uppercase) so
       ``ktc`` doesn't accidentally swallow a future ``ktcdraft`` —
       only camel-cased suffixes like ``ktcSfTep`` match.  Longest
       matching prefix wins so ``dynastyDaddy`` beats a hypothetical
       ``dynasty``.
    3. **Default** — 24 hours, matching the universal policy in
       ``config/source_staleness.json`` (every source is fetched
       every 2h; >24h means scrape failure).
    """
    if src in thresholds:
        return thresholds[src]
    best_prefix = ""
    for key in thresholds:
        if not key or not src.startswith(key) or len(src) <= len(key):
            continue
        # Word-boundary check: the next char in ``src`` must start a
        # new camel-case segment so we don't match unrelated keys
        # that happen to share leading letters.
        if not src[len(key)].isupper():
            continue
        if len(key) > len(best_prefix):
            best_prefix = key
    if best_prefix:
        return thresholds[best_prefix]
    return 24.0


def _matches_source(src: str, keys: "set[str] | dict[str, Any]") -> bool:
    """True when ``src`` matches ``keys`` by the same exact-then-
    vendor-prefix rule :func:`resolve_threshold` uses, so soft-source
    membership and threshold lookup never drift apart."""
    if src in keys:
        return True
    for key in keys:
        if not key or not src.startswith(key) or len(src) <= len(key):
            continue
        if not src[len(key)].isupper():
            continue
        return True
    return False


def load_soft_sources(path: Path | None = None) -> set[str]:
    """Sources listed under ``soft`` in ``config/source_staleness.json``.

    A *soft* source is one whose staleness is expected to recur for
    reasons outside the cron's control — e.g. ``idpShow`` authenticates
    with a browser-minted cookie that the operator must periodically
    re-mint, unlike credential/API sources that never lapse.  Soft
    sources are still surfaced everywhere (on-site banner, email
    alerts with their existing cooldown, the freshness-watchdog
    summary) so the outage is never hidden — they are only exempted
    from *hard-failing* the scheduled-refresh workflow, so one
    expiring cookie can't turn every 2h run red and open a failure
    issue each cycle.  Matched by exact key or vendor prefix, same as
    thresholds.
    """
    if path is None:
        repo = Path(__file__).resolve().parents[2]
        path = repo / "config" / "source_staleness.json"
    if not path.exists():
        return set()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return set()
    soft = raw.get("soft") if isinstance(raw, dict) else None
    if not isinstance(soft, list):
        return set()
    return {str(s) for s in soft if s}


def is_soft_source(src: str, soft_sources: "set[str]") -> bool:
    """True when ``src`` is operator-flagged soft (see
    :func:`load_soft_sources`)."""
    return _matches_source(src, soft_sources)


DEFAULT_SOFT_ESCALATION_HOURS = 72.0
"""How long a soft source may stay stale before it hard-fails anyway.

Soft-flagging exists so one lapsed cookie does not turn every 2h run
red while the operator gets to it.  Left uncapped, though, it means a
source can die permanently and CI will never say so — the exemption
stops being "don't nag about a known chore" and becomes "this source
is unmonitored".  ``idpShow`` sat soft-flagged with no upper bound
until 2026-07-27; the flag was doing exactly that.

Three days is the deliberate shape: quiet for the first day past
threshold (a re-mint is a chore, not an incident), loud after three
(nobody is coming; treat it as an outage).
"""


def load_soft_escalation_hours(path: Path | None = None) -> float:
    """``softEscalateHours`` from the staleness config.

    Falls back to :data:`DEFAULT_SOFT_ESCALATION_HOURS` when absent or
    unparseable.  A non-positive value disables escalation, which is a
    legitimate operator choice for a source that genuinely may lapse
    indefinitely — but it has to be written down to take effect, rather
    than being the accidental default it used to be.
    """
    if path is None:
        repo = Path(__file__).resolve().parents[2]
        path = repo / "config" / "source_staleness.json"
    if not path.exists():
        return DEFAULT_SOFT_ESCALATION_HOURS
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return DEFAULT_SOFT_ESCALATION_HOURS
    value = raw.get("softEscalateHours") if isinstance(raw, dict) else None
    if isinstance(value, (int, float)):
        return float(value)
    return DEFAULT_SOFT_ESCALATION_HOURS


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
            entry.get("lastFetched") or entry.get("lastSeen") or entry.get("lastFetchedAt") or ""
        )
        if not last_seen_iso:
            continue
        last_epoch = _iso_to_epoch(last_seen_iso)
        if last_epoch <= 0:
            continue
        hours_stale = (now - last_epoch) / 3600.0
        threshold = resolve_threshold(src, thresholds)
        if hours_stale > threshold:
            out.append(
                StaleSourceAlert(
                    source=src,
                    last_seen_iso=last_seen_iso,
                    hours_stale=round(hours_stale, 1),
                    threshold_hours=threshold,
                    transition="stale",
                )
            )
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
        source_health,
        thresholds=thresholds,
        now_epoch=now,
    )
    stale_sources = {a.source for a in stale}

    # Detect recovery transitions — sources in alert_state marked stale
    # that are NO longer stale now.
    recovery_alerts: list[StaleSourceAlert] = []
    for src, entry in list(alert_state.items()):
        if not isinstance(entry, dict):
            continue
        if entry.get("currentlyStale") and src not in stale_sources:
            recovery_alerts.append(
                StaleSourceAlert(
                    source=src,
                    last_seen_iso=str(entry.get("lastAlertedAt") or ""),
                    hours_stale=0.0,
                    threshold_hours=0.0,
                    transition="recovered",
                )
            )

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
        state_user,
        {"sourceHealthAlertState": alert_state},
        path=kv_path,
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
    lines.append("See https://chaseupside.com/tools/source-health")
    return "\n".join(lines)
