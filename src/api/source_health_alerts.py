"""Stale-source health alerts.

Detects when a ranking source hasn't refreshed in longer than its
configured ``maxStaleHours`` and emits a one-shot owner alert through the
caller's delivery callable -- in production ``server._deliver_owner_alert``
(``src/utils/owner_alerts.py``: push first, e-mail as the fallback).

Per-source staleness thresholds live in
``config/source_staleness.json``.  Default policy: every source is
24h.  The 2h scheduled-refresh cron writes each source's CSV
unconditionally on a successful fetch, so a >24h gap means
roughly twelve consecutive fetches failed — actionable, not
alert fatigue.  Slower vendor cadences are irrelevant because the
fetcher overwrites the CSV with whatever the page currently
serves; mtime tracks scrape health, not vendor publish events.

Cooldown: once an alert is DELIVERED for a source, don't re-fire until
either (a) the source recovers (fresh fetch observed) or (b)
``_REALERT_COOLDOWN_HOURS`` have passed.  Cooldown state lives
in ``user_kv`` keyed under ``sourceHealthAlertState`` so it
survives restart.  "We decided to alert" (``attemptedAt``) and "the
owner was told" (``lastDeliveredAt``) are different facts, and only the
second spends the window -- the rule ``ops_alerts`` has followed since
audit F-20.  An unconfigured, failing or raising delivery therefore
spends nothing: the next sweep tries again.  A pre-upgrade entry
carrying only ``lastAlertedAt`` keeps suppressing what it already
suppressed, so an upgrade does not burst.

Recovery alerts: when a stale source the owner was TOLD about comes
back, emit a one-shot "is back" notice; it is retried every sweep until
it is delivered.  A stale episode the owner never heard about ends silently --
a recovery for an incident nobody announced is noise.

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

# Default cooldown between re-alerts for the same source.  Measured from the
# last DELIVERED alert, never from a decision or an attempt.
_REALERT_COOLDOWN_HOURS = 72.0

# A sweep holds a short claim (``sendingAt``) on what it is delivering, so an
# overlapping sweep does not send the same notice twice.  Delivery is bounded
# (ntfy 5 s, SMTP 15 s per port); a claim older than this belongs to a sweep
# that died mid-delivery and is ignored.
_IN_FLIGHT_CLAIM_SEC = 900.0

# When the owner was last TOLD about a source's current episode.
# ``lastAlertedAt`` is the pre-2026-11-20 field, written at DECISION time
# whether or not anything was delivered; it is honoured so an upgrade keeps
# suppressing what it already suppressed, and never written again.
_LEGACY_TOLD_KEY = "lastAlertedAt"
_TOLD_KEYS = ("lastDeliveredAt", _LEGACY_TOLD_KEY)


def _told_at(entry: dict[str, Any]) -> float | None:
    """Epoch the owner was last told about this episode, or ``None`` (never)."""
    for key in _TOLD_KEYS:
        if key not in entry:
            continue
        value = entry.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            # An unreadable stamp is "never told": fire rather than stay silent.
            return None
        return float(value)
    return None


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
    hours_stale: float | None  # None: a state alert with no age (health, coverage)
    threshold_hours: float | None
    transition: str  # "stale" | "recovered"
    # The age is measured from a FIRST OBSERVATION (a fetch time), so it is a
    # lower bound and ``last_seen_iso`` is when we first saw the content, not
    # when the vendor published it (freshness D1).
    age_is_lower_bound: bool = False


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
    seasonally_inactive: "set[str] | None" = None,
) -> list[StaleSourceAlert]:
    """Given the ``/api/status.source_health`` shape, return the
    stale-source alerts (no cooldown consideration — that's the
    caller's concern).

    ``seasonally_inactive`` names sources in a DECLARED seasonal window
    whose inactive state was re-verified within threshold (resolved by
    ``src/sources/seasonal_policy.watchdog_seasonal_split``, owner decision
    2026-10-03).  They are not stale sources and do not page.  Default
    ``None`` = no exclusions (fail closed)."""
    thresholds = thresholds or load_thresholds()
    skip = seasonally_inactive or set()
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
        if not isinstance(entry, dict) or src in skip:
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


#: Content-freshness states that page (src/sources/freshness.py bands).
_CONTENT_ALERT_STATES = {"SEVERELY_STALE", "QUARANTINED"}


def _number(value: Any) -> float | None:
    """A real number, or ``None`` — an unknown age is never 0 hours."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _at_least(value: Any, floor: float) -> bool:
    number = _number(value)
    return number is not None and number >= floor


def detect_content_alerts(weighting: dict[str, Any] | None) -> list[StaleSourceAlert]:
    """Valuation-infrastructure alerts from the board's ``sourceWeighting``.

    Fetch staleness (above) says a JOB stopped; these say the DATA a source
    contributes is stale relative to its own rhythm, broken, or thin — the
    conditions the owner asked to hear about before discovering them by
    comparing trades to other sites (directive 2026-09-23).  Keys are
    namespaced (``content:`` / ``health:`` / ``coverage:`` / ``board:``) so
    they share this module's cooldown and recovery state without colliding
    with fetch alerts.
    """
    out: list[StaleSourceAlert] = []
    if not isinstance(weighting, dict):
        return out
    sources = weighting.get("sources") or {}
    healthy_offense_voters = 0
    for key, entry in sources.items():
        if not isinstance(entry, dict):
            continue
        for subset, sub in (entry.get("subsets") or {}).items():
            if not isinstance(sub, dict) or sub.get("state") not in _CONTENT_ALERT_STATES:
                continue
            baseline = sub.get("clockIsObservationBaseline") is True
            out.append(
                StaleSourceAlert(
                    source=f"content:{key}/{subset}",
                    last_seen_iso=str(
                        (sub.get("observationBaselineAt") if baseline else None)
                        or sub.get("sourceDataAsOf")
                        or ""
                    ),
                    hours_stale=_number(sub.get("ageHours")),
                    threshold_hours=_number(sub.get("expectedCadenceHours")),
                    transition="stale",
                    age_is_lower_bound=baseline,
                )
            )
        if entry.get("health") not in (None, "HEALTHY"):
            out.append(
                StaleSourceAlert(
                    source=f"health:{key}:{entry.get('health')}",
                    last_seen_iso="",
                    hours_stale=None,
                    threshold_hours=None,
                    transition="stale",
                )
            )
        if isinstance(entry.get("coverageFactor"), (int, float)) and entry["coverageFactor"] < 1.0:
            out.append(
                StaleSourceAlert(
                    source=f"coverage:{key}",
                    last_seen_iso="",
                    hours_stale=None,
                    threshold_hours=None,
                    transition="stale",
                )
            )
        if entry.get("role") == "model_input" and _at_least(entry.get("excludedRows"), 1):
            # Votes WITHHELD on some rows (freshness quarantine / FAILED
            # health): the subset states above can miss this, because a
            # board pricing several universes is quarantined per universe —
            # IDP Trade Calculator's offense rows age out while its players
            # subset stays ON_SCHEDULE on IDP-only publications.  Degraded
            # evidence, not an outage (owner 2026-10-07): an alert, never an
            # error.
            out.append(
                StaleSourceAlert(
                    source=f"content:{key}:votes_withheld",
                    last_seen_iso="",
                    hours_stale=None,
                    threshold_hours=None,
                    transition="stale",
                )
            )
        if (
            entry.get("role") == "model_input"
            and key.startswith("ktc")
            and not entry.get("votingRows")
        ):
            out.append(
                StaleSourceAlert(
                    source=f"content:{key}:unavailable",
                    last_seen_iso="",
                    hours_stale=None,
                    threshold_hours=None,
                    transition="stale",
                )
            )
        players = (entry.get("subsets") or {}).get("players") or {}
        if (
            entry.get("role") == "model_input"
            and _at_least(entry.get("votingRows"), 100)
            and _at_least(players.get("freshness"), 0.3)
            and entry.get("health") in (None, "HEALTHY")
        ):
            healthy_offense_voters += 1
    if sources and healthy_offense_voters <= 1:
        out.append(
            StaleSourceAlert(
                source="board:single_major_source_remaining",
                last_seen_iso="",
                hours_stale=None,
                threshold_hours=None,
                transition="stale",
            )
        )
    return out


def _verified_seasonally_inactive(
    thresholds: dict[str, float] | None, now_epoch: float
) -> set[str]:
    """Sources re-verified seasonally inactive within their threshold.

    Same owner and same rule as ``scripts/watchdog_freshness.py``.  Any
    failure reading the policy/state returns the empty set — i.e. the
    source is alerted on normally (fail closed), never silently muted.
    """
    try:
        from datetime import datetime, timezone  # noqa: PLC0415

        from src.sources.seasonal_policy import watchdog_seasonal_split  # noqa: PLC0415

        th = thresholds or load_thresholds()
        verified, _lapsed = watchdog_seasonal_split(
            None,
            datetime.fromtimestamp(now_epoch, tz=timezone.utc),
            lambda key: resolve_threshold(key, th),
        )
        return set(verified)
    except Exception:  # noqa: BLE001 — alerting must not crash on this
        return set()


def check_and_alert(
    source_health: dict[str, Any],
    *,
    source_weighting: dict[str, Any] | None = None,
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
         "skipped_cooldown": int, "skipped_in_flight": int,
         "deliveryConfigured": bool}

    ``deliveryConfigured`` keeps "nothing to send" and "nobody to send it to"
    apart, as ``ops_alerts`` does.
    """
    state_user = "_system_source_health"
    now = time.time()
    cooldown_sec = cooldown_hours * 3600.0
    stale = detect_stale_sources(
        source_health,
        thresholds=thresholds,
        now_epoch=now,
        seasonally_inactive=_verified_seasonally_inactive(thresholds, now),
    ) + detect_content_alerts(source_weighting)
    stale_sources = {a.source for a in stale}

    delivery_configured = delivery is not None and bool(to_email)
    summary: dict[str, Any] = {
        "stale": 0,
        "recovered": 0,
        "delivered": 0,
        "skipped_cooldown": 0,
        "skipped_in_flight": 0,
        # "nothing to send" and "could not send" must not read the same.
        "deliveryConfigured": delivery_configured,
    }
    to_send: list[StaleSourceAlert] = []

    def _claimed(entry: dict[str, Any]) -> bool:
        """Another sweep is delivering this entry right now."""
        sending = entry.get("sendingAt")
        return _number(sending) is not None and now - float(sending) < _IN_FLIGHT_CLAIM_SEC

    # The cooldown / recovery DECISION is made on the CURRENT state, inside the
    # user_kv write lock, and a short in-flight claim (``sendingAt``) is
    # persisted in the same transaction BEFORE sending, so two overlapping
    # sweeps cannot both send the same alert.  What the decision may NOT do is
    # record the owner as told: ``lastDeliveredAt`` is written only by
    # ``_settle`` below, after the delivery callable returned True.
    def _decide(state: dict[str, Any]) -> None:
        to_send.clear()
        for k in ("stale", "recovered", "skipped_cooldown", "skipped_in_flight"):
            summary[k] = 0
        alert_state = dict(state.get("sourceHealthAlertState") or {})

        # Recovery transitions -- sources marked stale that are NO longer stale.
        recovery_alerts: list[StaleSourceAlert] = []
        for src, entry in list(alert_state.items()):
            if not isinstance(entry, dict) or not entry.get("currentlyStale"):
                continue
            if src in stale_sources:
                continue
            if _claimed(entry):
                summary["skipped_in_flight"] += 1
                continue
            if _told_at(entry) is None:
                # The owner never heard about this episode, so there is
                # nothing to un-say: it ends silently.
                alert_state[src] = {"currentlyStale": False, "clearedAt": now}
                continue
            recovery_alerts.append(
                StaleSourceAlert(
                    source=src,
                    last_seen_iso=str(entry.get("lastSeenIso") or ""),
                    hours_stale=0.0,
                    threshold_hours=0.0,
                    transition="recovered",
                )
            )
            # Still stale on record until the recovery is DELIVERED, so an
            # undelivered recovery is found again (and retried) next sweep.
            alert_state[src] = {**entry, "attemptedAt": now, "sendingAt": now}

        # Stale alerts -- the cooldown is measured from the last DELIVERY.
        for alert in stale:
            prev = alert_state.get(alert.source)
            prev = prev if isinstance(prev, dict) else {}
            if _claimed(prev):
                summary["skipped_in_flight"] += 1
                continue
            told = _told_at(prev) if prev.get("currentlyStale") else None
            if told is not None and (now - told) < cooldown_sec:
                summary["skipped_cooldown"] += 1
                continue
            to_send.append(alert)
            entry: dict[str, Any] = {
                "currentlyStale": True,
                "attemptedAt": now,
                "sendingAt": now,
                "lastSeenIso": alert.last_seen_iso,
                "hoursStale": alert.hours_stale,
            }
            if prev.get("currentlyStale"):
                # Same episode: keep when the owner was last told (an
                # undelivered re-alert must not erase the previous delivery).
                for key in _TOLD_KEYS:
                    if key in prev:
                        entry[key] = prev[key]
            alert_state[alert.source] = entry
            summary["stale"] += 1

        # Recoveries are rate-limited by their own precondition (a told,
        # currently-stale episode), so no cooldown applies.
        for r in recovery_alerts:
            to_send.append(r)
            summary["recovered"] += 1

        state["sourceHealthAlertState"] = alert_state

    user_kv.mutate_user_state(state_user, _decide, path=kv_path)

    if not to_send:
        return summary

    delivered = False
    if not delivery_configured:
        _LOGGER.warning(
            "source_health alerts: %d notice(s) to deliver but no owner alert channel is "
            "configured (NOTIFY_WEBHOOK_URL or ALERT_*); nothing sent, retried next sweep",
            len(to_send),
        )
    else:
        subject = _format_subject(to_send)
        body = _format_body(to_send)
        try:
            delivered = bool(delivery(to_email, subject, body))
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("source_health alert delivery failed: %s", exc)
            delivered = False
        if not delivered:
            _LOGGER.warning(
                "source_health alerts: %d notice(s) NOT delivered (every channel failed); "
                "retried next sweep",
                len(to_send),
            )
    if delivered:
        summary["delivered"] = len(to_send)

    def _settle(state: dict[str, Any]) -> None:
        """Release this sweep's claims; on delivery, record the owner as told."""
        alert_state = dict(state.get("sourceHealthAlertState") or {})
        for a in to_send:
            entry = alert_state.get(a.source)
            if not isinstance(entry, dict) or entry.get("sendingAt") != now:
                continue  # not our claim any more: leave the newer record alone
            entry = {k: v for k, v in entry.items() if k != "sendingAt"}
            if delivered and a.transition == "recovered":
                entry = {"currentlyStale": False, "recoveredAt": now}
            elif delivered:
                entry = {k: v for k, v in entry.items() if k != _LEGACY_TOLD_KEY}
                entry["lastDeliveredAt"] = now
            alert_state[a.source] = entry
        state["sourceHealthAlertState"] = alert_state

    try:
        user_kv.mutate_user_state(state_user, _settle, path=kv_path)
    except Exception as exc:  # noqa: BLE001 -- a stale claim expires on its own
        _LOGGER.warning("source_health alert state not settled: %s", exc)
    return summary


#: The pseudo-source a producer TEST notice names.  It is never written to the
#: alert state, so it can neither spend a cooldown nor earn a recovery notice.
TEST_SOURCE = "owner_alert_producer_test (no source is stale)"


def format_test_notice() -> tuple[str, str]:
    """``(subject, body)`` of one labelled TEST notice, built by the sweep's own
    formatters, for ``POST /api/test-alert?producers=1``.  Pure: it reads and
    writes no state."""
    from src.utils import owner_alerts  # noqa: PLC0415

    alert = StaleSourceAlert(
        source=TEST_SOURCE,
        last_seen_iso="",
        hours_stale=None,
        threshold_hours=None,
        transition="stale",
    )
    return owner_alerts.mark_test(_format_subject([alert]), _format_body([alert]))


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
            if a.hours_stale is None:
                # A state alert (health, coverage, board) — it has no age.
                lines.append(f"  • {a.source}")
                continue
            threshold = "unknown" if a.threshold_hours is None else f"{a.threshold_hours:.0f}h"
            if a.age_is_lower_bound:
                lines.append(
                    f"  • {a.source}: at least {a.hours_stale:.1f}h stale "
                    f"(threshold {threshold}) — first observed {a.last_seen_iso}, "
                    "publication time unknown"
                )
                continue
            lines.append(
                f"  • {a.source}: {a.hours_stale:.1f}h stale "
                f"(threshold {threshold}) — last seen {a.last_seen_iso}"
            )
        lines.append("")
    if recovered:
        lines.append("Recovered sources:")
        for a in recovered:
            lines.append(f"  • {a.source}: back")
        lines.append("")
    lines.append("See https://chaseupside.com/tools/source-health")
    return "\n".join(lines)
