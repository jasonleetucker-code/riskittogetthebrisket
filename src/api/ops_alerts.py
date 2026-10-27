"""Operator alerts for critical production conditions.

Fires SMTP emails (reusing the existing signal-alert SMTP pipe)
when any of these conditions hold:

    * Scrape success rate over the last 24h drops below 50%
    * Any circuit breaker has been OPEN for > 10 minutes
    * Contract health reports ``ok=False``
    * Signal-alert cron hasn't run in > 36h (expected every 12h)
    * Session-store SQLite integrity check fails
    * Data freshness > 3 × scrape interval
    * A draft-capital dollars generation serving last-known-good or
      unavailable (Batch F, one alert per league + draft class)
    * A Game Day pregame-projections archive that could not be built, so
      its week's raw weekly-projection log is being kept (one alert per
      league + season + week)

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
    """Alert when under half the scrapes in 24h succeeded.

    Audit O-1: this could never fire, for two independent reasons, and
    the combination meant there was NO email path for sustained
    ingestion failure.

    1. ``scrape_success_rate_24h`` was attached only inside the
       ``/api/status`` route.  The payload ``check_and_alert`` is
       actually called with — ``_scrape_status_payload()`` — never
       carried the key, so this returned ``None`` on every sweep.
    2. Even when present the value is a **dict**
       (``{"total", "success", "failure", "rate"}``), not a float, so
       ``float(rate)`` raised ``TypeError``, was caught, and returned
       ``None`` again.

    Both are fixed: server.py now attaches the key, and this reads
    either shape.  A bare float is still accepted because the /api/status
    contract is public and callers may pass either.
    """
    raw = status_payload.get("scrape_success_rate_24h")
    if raw is None:
        return None

    sample_total: int | None = None
    if isinstance(raw, dict):
        rate = raw.get("rate")
        # ABSENT total means unknown sample size, NOT zero samples.  The
        # first cut of this wrote ``int(raw.get("total") or 0)``, which
        # collapsed the two — and since a zero sample size suppresses
        # the alert below, a payload carrying a valid rate but no
        # ``total`` would have silently stopped alerting. The repo's own
        # coercion gate caught it in review, in the batch whose subject
        # is exactly this substitution.
        total = raw.get("total")
        sample_total = int(total) if isinstance(total, (int, float)) else None
    else:
        rate = raw

    # NO DATA IS NOT A 0% SUCCESS RATE.  ``_scrape_success_rate_24h``
    # returns ``rate: None`` with ``total: 0`` when no scrape has been
    # recorded in the window — a fresh boot, or a restarted process.
    # Coercing that to zero would page the operator for an empty
    # history, which is the "missing data becomes a confident number"
    # pattern this whole audit is about, pointed at the alerting layer.
    if rate is None:
        return None
    if sample_total is not None and sample_total <= 0:
        return None

    try:
        r = float(rate)
    except (TypeError, ValueError):
        return None
    if r >= 0.5:
        return None

    sample_note = f" over {sample_total} run(s)" if sample_total else ""
    return OpsAlert(
        severity="critical" if r < 0.25 else "warning",
        category="scrape_failure",
        title=f"Scrape success rate 24h = {r:.0%}{sample_note}",
        detail=(
            "Fewer than half of the scheduled scrapes in the last 24 hours "
            "succeeded.  Rankings may be stale.  Check "
            "/api/status.last_n_scrapes for the failure pattern.  Note a "
            "scrape whose output was refused for being too degraded to "
            "publish counts as 'blocked', not 'success', so this rate "
            "falls when the partial-scrape guard is firing repeatedly."
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
        alerts.append(
            OpsAlert(
                severity="warning",
                category=f"circuit_open:{c.get('name')}",
                title=f"Circuit breaker '{c.get('name')}' has been OPEN {int(age/60)}m",
                detail=(
                    f"External dependency {c.get('name')!r} is failing repeatedly. "
                    f"Last error: {c.get('lastError') or '(none captured)'}.  "
                    f"Fast-fail count: {c.get('counters',{}).get('fastFail',0)}."
                ),
            )
        )
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


def _check_draft_valuation(rows: list[dict[str, Any]]) -> list[OpsAlert]:
    """Draft-capital dollars generations that are not serving a fresh answer.

    One alert per (league, draft class), keyed ``draft_valuation:<league>:<year>``
    so the existing cooldown and recovery bookkeeping apply per class.  A row
    comes from ``src/draft/rookie_auction/generation.generation_health``:
    ``last_known_good`` (a refresh failed; the class still serves its last
    verified allocation) is a warning; ``unavailable`` for an unexpected
    reason (no verified allocation at all — the board is refused) is
    critical.  Expected answers (retired class, unconfigured league) arrive
    with ``degraded: False`` and never alert.  No rows means "not checked",
    never "healthy".
    """
    alerts: list[OpsAlert] = []
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("degraded"):
            continue
        league = row.get("leagueKey")
        year = row.get("draftYear")
        state = row.get("allocationState")
        reason = row.get("reason") or "unknown"
        if state == "last_known_good":
            alerts.append(
                OpsAlert(
                    severity="warning",
                    category=f"draft_valuation:{league}:{year}",
                    title=f"Draft capital {year} ({league}) serving last known good",
                    detail=(
                        f"The {year} class's rookie-auction refresh failed ({reason}); the last "
                        f"verified whole-dollar allocation from {row.get('lastValidAt')} is "
                        "being served, labelled last_known_good.  Check "
                        "/api/draft-capital budgetPolicy.classes."
                    ),
                )
            )
        else:
            alerts.append(
                OpsAlert(
                    severity="critical",
                    category=f"draft_valuation:{league}:{year}",
                    title=f"Draft capital {year} ({league}) unavailable",
                    detail=(
                        f"No verified whole-dollar allocation exists for the {year} class "
                        f"({reason}).  Its picks are unpriced or the board is refused — "
                        "never $0, never another year's curve."
                    ),
                )
            )
    return alerts


def _check_pregame_archive(rows: list[dict[str, Any]]) -> list[OpsAlert]:
    """Game Day pregame-projections archives that could not be established.

    One alert per (league, season, week), keyed
    ``pregame_archive:<league>:<season>:<week>`` so the cooldown and recovery
    bookkeeping apply per week.  A row comes from
    ``src/ros/game_day_live.pregame_archive_health``: it exists exactly while
    ``ensure_pregame_archive`` is keeping that week's raw log because the
    archive could not be built, written, read back or made durable (fail closed
    -- nothing is deleted).  The row disappears when that is established, which
    is how the recovery notice fires.  No rows means "nothing failing"; the
    sweep passes ``None`` -- never an empty list -- when the store could not be
    read.

    Three reasons are not build failures and say so: ``archive_unreadable`` (a
    file at the archive path that does not read back, which the collector never
    overwrites), ``archive_directory_unflushed`` (the verified archive is in
    place; only making its rename durable is pending -- a byte-identical
    rewrite of the archive followed by a directory flush while the raw weekly
    log remains, whatever step failed last; only a re-flush once it is gone)
    and ``raw_log_prune_failed`` (the archive is in place; only removing the
    raw log failed).

    Every text is chosen by what is still on disk, which the row states in two
    fields: ``weeklyLogRetained`` (the raw weekly-projection log itself) and
    ``rawLogRetained`` (the week's ``observations/`` directory, which holds
    every source's log).  Three states: the weekly log is retained (what the
    byte-identical rewrite protects); only other sources' raw observations are
    left (nothing to protect or rebuild from -- e.g. a prune that removed the
    weekly log but not the rest); or nothing is.  The weekly log lives inside
    ``observations/``, so it implies that directory.  A row without
    ``weeklyLogRetained`` (built before the field existed) is read the way its
    reader meant it: ``rawLogRetained`` for both.
    """
    alerts: list[OpsAlert] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        league, season, week = row.get("leagueKey"), row.get("season"), row.get("week")
        reason = row.get("reason") or "unknown"
        failure = f"could not be established ({reason}; failed {row.get('failedAt')})."
        since = row.get("firstFailedAt") or row.get("failedAt")
        weekly = row.get("weeklyLogRetained")
        if not isinstance(weekly, bool):
            weekly = bool(row.get("rawLogRetained"))
        observations = weekly or bool(row.get("rawLogRetained"))
        if weekly and reason == "archive_directory_unflushed":
            kind = row.get("flushFailure")
            if kind == "rewrite":
                # The latest attempt never reached a flush: the rewrite itself
                # (a write, a read or the sha256 check) could not complete.
                lead = (
                    f"The verified pregame weekly-projections archive for {league} {season} week "
                    f"{week} is in place, but the byte-identical rewrite that re-establishes the "
                    f"rename that put it there could not complete ({reason}; flush failure: "
                    f"rewrite; failing since {since}).  Until that rewrite and its directory "
                    "flush succeed a power loss could undo the rename"
                )
                cause = (
                    "The rewrite stopped before any directory flush ran (an I/O error, or a copy "
                    "whose sha256 did not match), and the accepted archive was left untouched."
                )
                closing = (
                    "This resolves when the byte-identical rewrite and its directory flush succeed."
                )
            else:
                lead = (
                    f"The verified pregame weekly-projections archive for {league} {season} week "
                    f"{week} is in place, but the directory holding it could not be flushed to disk "
                    f"({reason}; flush failure: {kind or 'unrecorded'}; failing since "
                    f"{since}).  Until a flush succeeds a power loss could undo the rename that put "
                    "it there"
                )
                cause = {
                    "open": "The directory could not be opened, so no fsync ran.",
                    "fsync": "fsync reported an error.",
                }.get(kind, "The failed step is not on record.")
                closing = "This resolves when the directory flush succeeds."
            title = (
                f"Pregame projections archive for {season} week {week} "
                "awaiting a durable directory flush"
            )
            detail = (
                f"{lead}, so the raw weekly-projection log is retained -- the prune keeps it "
                "rather than delete evidence the archive may not yet durably hold.  "
                f"{cause}  Whatever the failed step, the Game Day collector's retry, at most "
                "hourly, rewrites the accepted archive byte for byte -- its own bytes, read back "
                "and checked by sha256, never rebuilt from the raw log -- renames that copy over "
                "it and flushes the directory again: no bare re-flush is trusted, because Linux "
                "reports a write error to only one fsync and the marker that would record it is "
                "best effort.  See pregame_projections.retained.json beside the week.  "
                f"{closing}"
            )
        elif weekly and reason == "raw_log_prune_failed":
            title = (
                f"Pregame projections archive for {season} week {week} in place; "
                "raw log not removed"
            )
            detail = (
                f"The verified pregame weekly-projections archive for {league} {season} week "
                f"{week} is in place, but the week's raw observations could not be removed after "
                f"it was established ({reason}; failing since {since}).  Nothing is lost: the raw "
                "log simply stays on disk.  The Game Day collector retries at most hourly -- each "
                "retry first makes the archive's rename durable again (by a byte-identical "
                "rewrite of its own bytes, checked by sha256, while the raw weekly log remains; "
                "never a rebuild), then removes the raw log again.  See "
                "pregame_projections.retained.json beside the week.  This resolves when the raw "
                "log is removed."
            )
        elif weekly and reason == "archive_unreadable":
            title = f"Pregame projections archive for {season} week {week} unreadable"
            detail = (
                f"The pregame weekly-projections archive for {league} {season} week {week} "
                f"{failure}  A file is at the archive path but does not read back, and the Game "
                "Day collector never overwrites an unreadable archive, so it is not rebuilt.  The "
                "raw weekly-projection log is retained -- the prune keeps it rather than delete "
                "evidence it has not archived -- and that week's pregame baseline is not "
                "preserved for the projection scorecard until the archive reads back.  The "
                "collector re-checks the file on every pass; see pregame_projections.retained.json "
                "beside the week.  This resolves when the file at the archive path reads back, or "
                "once it is removed and the next hourly build succeeds."
            )
        elif weekly:
            title = f"Pregame projections archive for {season} week {week} not built"
            detail = (
                f"The pregame weekly-projections archive for {league} {season} week {week} "
                f"{failure}  The raw weekly-projection log is retained -- the prune keeps it "
                "rather than delete evidence it has not archived -- but until the archive "
                "exists that week's pregame baseline is not preserved for the projection "
                "scorecard, and its raw observations stay on disk.  The Game Day collector "
                "retries hourly; see pregame_projections.retained.json beside the week.  This "
                "resolves when a build succeeds."
            )
        elif observations and reason == "archive_directory_unflushed":
            # Only other sources' raw observations are left: the weekly log the
            # byte-identical rewrite protects is gone, so the retry re-flushes only.
            kind = row.get("flushFailure")
            if kind == "rewrite":
                lead = (
                    f"The verified pregame weekly-projections archive for {league} {season} week "
                    f"{week} is in place, but the byte-identical rewrite that re-establishes the "
                    f"rename that put it there could not complete ({reason}; flush failure: "
                    f"rewrite; failing since {since})"
                )
                cause = (
                    "That rewrite stopped before any directory flush ran (an I/O error, or a copy "
                    "whose sha256 did not match), and the accepted archive was left untouched."
                )
            else:
                lead = (
                    f"The verified pregame weekly-projections archive for {league} {season} week "
                    f"{week} is in place, but the directory holding it could not be flushed to disk "
                    f"({reason}; flush failure: {kind or 'unrecorded'}; failing since {since})"
                )
                cause = {
                    "open": "The directory could not be opened, so no fsync ran.",
                    "fsync": "fsync reported an error.",
                }.get(kind, "The failed step is not on record.")
            title = (
                f"Pregame projections archive for {season} week {week} "
                "awaiting a durable directory flush"
            )
            detail = (
                f"{lead}.  {cause}  The raw weekly-projection log is no longer on disk, so there "
                "is nothing left to protect: the archive is the only record of that week's pregame "
                "projections, and the Game Day collector's retry, at most hourly, only re-flushes "
                "the directory -- it never rewrites or rebuilds the archive.  The week's other raw "
                "observations stay on disk until that flush succeeds.  See "
                "pregame_projections.retained.json beside the week.  This resolves when the "
                "directory flush succeeds."
            )
        elif observations and reason == "raw_log_prune_failed":
            title = (
                f"Pregame projections archive for {season} week {week} in place; "
                "raw observations not fully removed"
            )
            detail = (
                f"The verified pregame weekly-projections archive for {league} {season} week "
                f"{week} is in place, but the week's raw observations could not be fully removed "
                f"after it was established ({reason}; failing since {since}).  The raw "
                "weekly-projection log itself is already gone, and the archive was established "
                "before the prune ran, so nothing is lost; the week's other raw observations stay "
                "on disk.  The Game Day collector retries at most hourly -- with no weekly log left "
                "to protect, each retry only re-flushes the directory holding the archive (never a "
                "rewrite or a rebuild), then removes the remaining observations again.  See "
                "pregame_projections.retained.json beside the week.  This resolves when the "
                "remaining raw observations are removed."
            )
        elif observations and reason == "archive_unreadable":
            title = f"Pregame projections archive for {season} week {week} unreadable"
            detail = (
                f"The pregame weekly-projections archive for {league} {season} week {week} "
                f"{failure}  A file is at the archive path but does not read back, and the Game "
                "Day collector never overwrites an unreadable archive.  The raw weekly-projection "
                "log is no longer on disk either, so the archive cannot be rebuilt: unless that "
                "file is repaired, the week's pregame baseline is lost from the projection "
                "scorecard.  The week's other raw observations are kept while the file is "
                "unreadable.  The collector re-checks the file on every pass; see "
                "pregame_projections.retained.json beside the week.  This resolves when the file "
                "at the archive path reads back, or once it is removed -- the week is then left "
                "with no archive and nothing to build one from."
            )
        elif observations:
            title = (
                f"Pregame projections archive for {season} week {week} not built; "
                "raw weekly log gone"
            )
            detail = (
                f"The pregame weekly-projections archive for {league} {season} week {week} "
                f"{failure}  The raw weekly-projection log it is built from is no longer on disk, "
                "so no build can run and none is retried: unless an archive is already in place, "
                "the week's pregame baseline is not preserved for the projection scorecard.  The "
                "week's other raw observations are still on disk.  The Game Day collector's next "
                "pass clears this marker (or replaces it, if a file is at the archive path); see "
                "pregame_projections.retained.json beside the week."
            )
        else:
            # No raw log and no readable archive: nothing is left to rebuild
            # from and the prune never revisits a week without observations/,
            # so there is no retry and no automatic resolution.
            title = f"Pregame projections archive for {season} week {week} cannot be rebuilt"
            detail = (
                f"The pregame weekly-projections archive for {league} {season} week {week} "
                f"{failure}  The raw weekly-projection log is gone and no readable archive "
                "exists, so the week cannot be rebuilt: its pregame baseline is permanently "
                "missing from the projection scorecard.  The Game Day collector does not "
                "retry a week that has no raw log.  This alert keeps firing until the failure "
                "marker (pregame_projections.retained.json beside the week) is removed."
            )
        alerts.append(
            OpsAlert(
                severity="warning",
                category=f"pregame_archive:{league}:{season}:{week}",
                title=title,
                detail=detail,
            )
        )
    return alerts


def _load_ops_state(path: Any = None) -> dict[str, Any]:
    state = user_kv.get_user_state(_OPS_STATE_USER, path=path)
    return dict(state.get("opsAlertState") or {})


def _save_ops_state(state: dict[str, Any], categories: set[str], path: Any = None) -> None:
    """Write back ONLY the categories this sweep changed, onto the CURRENT
    stored state, under the user_kv write lock.

    The sweep reads its state, then delivers (seconds), then writes.  Writing
    the whole ``opsAlertState`` copy back discarded every category another
    sweep recorded meanwhile -- including a delivered alert's cooldown, which
    then fired again.  A category this sweep did not touch keeps its stored
    value; one it removed is removed.
    """
    if not categories:
        return

    def _apply(entry: dict[str, Any]) -> None:
        current = entry.get("opsAlertState")
        current = dict(current) if isinstance(current, dict) else {}
        for category in categories:
            if category in state:
                current[category] = state[category]
            else:
                current.pop(category, None)
        entry["opsAlertState"] = current

    user_kv.mutate_user_state(_OPS_STATE_USER, _apply, path=path)


def _should_fire(
    alert: OpsAlert,
    state: dict[str, Any],
    *,
    now: float,
) -> bool:
    """Cooldown check.  Returns True when an alert should fire,
    False when it's within the re-alert window."""
    last = state.get(alert.category) or {}
    # Audit F-20: the window is spent by a DELIVERED alert, never by the
    # decision to send one.  "We decided to alert", "we attempted delivery"
    # and "the operator was told" are three different facts, and only the
    # third may silence the next sweep — an unconfigured or failing mailer
    # used to consume the cooldown and the operator was never told at all.
    # ``firedAt`` is still read so a state file written by the previous
    # implementation keeps suppressing what it already suppressed rather
    # than producing a burst on upgrade.
    # No delivery on record means the operator has never been told, so there
    # is no window to be inside — fire.  Written as an explicit branch rather
    # than ``or 0.0``: an epoch of zero would work arithmetically, but it
    # states "delivered at the start of 1970" where the truth is "never
    # delivered", and this file is precisely about not conflating those.
    delivered_at = last.get("deliveredAt")
    if delivered_at is None:
        # Legacy state written before deliveredAt existed.  Honour it so an
        # upgrade does not re-fire everything that was already suppressed.
        delivered_at = last.get("firedAt")
    if delivered_at is None:
        return True
    try:
        last_at = float(delivered_at)
    except (TypeError, ValueError):
        return True
    if now - last_at < _ALERT_COOLDOWN_SEC:
        return False
    return True


def _detect_recovery(
    active_categories: set[str],
    state: dict[str, Any],
    *,
    now: float,
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
        recovery.append(
            OpsAlert(
                severity="info",
                category=category,
                title=f"[RECOVERY] {category} resolved",
                detail="Condition cleared.  No action required.",
            )
        )
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
    lines.append("Status: https://chaseupside.com/api/status")
    lines.append("Health: https://chaseupside.com/api/health")
    return subject, "\n".join(lines)


def check_and_alert(
    *,
    status_payload: dict[str, Any] | None = None,
    circuit_snapshots: list[dict[str, Any]] | None = None,
    contract_health: dict[str, Any] | None = None,
    data_age_hours: float | None = None,
    scrape_interval_hours: float = 2.0,
    draft_valuation: list[dict[str, Any]] | None = None,
    pregame_archive: list[dict[str, Any]] | None = None,
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
    alerts.extend(_check_draft_valuation(draft_valuation or []))
    alerts.extend(_check_pregame_archive(pregame_archive or []))

    active_categories = {a.category for a in alerts}
    now = time.time()
    state = _load_ops_state(path=kv_path)
    if draft_valuation is None:
        # Not checked this sweep is UNKNOWN, not recovered: keep any firing
        # draft-valuation class out of the recovery notices.
        active_categories |= {c for c in state if str(c).startswith("draft_valuation:")}
    if pregame_archive is None:
        # Likewise: an unreadable Game Day store is UNKNOWN, not recovered.
        active_categories |= {c for c in state if str(c).startswith("pregame_archive:")}

    # Recovery alerts first — for conditions that were firing but
    # aren't now.
    recovery_alerts = _detect_recovery(active_categories, state, now=now)

    # Apply cooldown to new alerts.
    firing: list[OpsAlert] = []
    for a in alerts:
        if _should_fire(a, state, now=now):
            firing.append(a)
            # ``attemptedAt`` only — ``deliveredAt`` is written below, and
            # only if an email actually went out (audit F-20).
            state[a.category] = {
                "attemptedAt": now,
                "severity": a.severity,
                "recoveryFired": False,
            }

    delivery_configured = delivery is not None and bool(to_email)

    summary = {
        "active": len(alerts),
        "fired": len(firing),
        "recovered": len(recovery_alerts),
        "delivered": False,
        # "nothing to send" and "could not send" must not read the same.
        "deliveryConfigured": delivery_configured,
        "categories": [a.category for a in firing],
    }

    to_deliver = firing + recovery_alerts
    delivered = False
    if to_deliver and delivery_configured:
        subject, body = format_ops_email(to_deliver)
        try:
            delivered = bool(delivery(to_email, subject, body))
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("ops alert delivery failed: %s", exc)
            delivered = False
    summary["delivered"] = delivered

    if delivered:
        # The operator has now been told, so the window starts and the
        # recovery notice this incident will eventually earn is legitimate.
        for a in firing:
            entry = state.get(a.category) or {}
            entry["deliveredAt"] = now
            state[a.category] = entry
        for r in recovery_alerts:
            if r.category in state:
                state[r.category] = {
                    **(state[r.category] or {}),
                    "recoveryFired": True,
                    "recoveredAt": now,
                }
    else:
        # Nothing was sent.  Drop the bookkeeping for categories that fired
        # for the FIRST time this sweep, so the next one is free to try
        # again; a category already carrying a delivered notice keeps it.
        for a in firing:
            entry = state.get(a.category) or {}
            if not entry.get("deliveredAt"):
                state.pop(a.category, None)

    # Only what this sweep changed: every firing category (recorded or rolled
    # back), and recoveries only when their notice was actually delivered.
    touched = {a.category for a in firing}
    if delivered:
        touched |= {r.category for r in recovery_alerts}
    _save_ops_state(state, touched, path=kv_path)
    return summary
