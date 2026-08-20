#!/usr/bin/env python3
"""The durable record of the Sharp production smoke — state, not runs.

WHY THIS EXISTS
===============
``Verify Sharp Production Population`` committed
``data/ops/sharp-production-smoke.json`` to ``main`` on **every** run,
because ``checkedAt`` is a timestamp and a timestamp always changes.
Measured on 2026-08-20: **42 of 66 bot commits to main in 24 hours**,
every one of them recording the same ``unverifiable_unauthenticated``
status that has not changed once in the file's recorded history.

Each of those commits moves ``main`` under every open pull request. The
repository's own HEAD FREEZE policy (``CLAUDE.md``) classifies that as
class-C drift and spends real effort bounding it. A *verification*
workflow manufacturing 42 of them a day to say "still the same" is the
cause, not the weather.

WHY NOT SIMPLY "COMMIT ONLY WHEN SOMETHING CHANGES"
===================================================
Because that freezes the file. A record last written on 2026-08-05 reads
as the current state forever, and "the workflow silently stopped firing"
becomes undetectable from the tree — a failure mode this repository has
hit, and one that had to be actively disproved for ``retention-health``
on the morning this was written (its cron is delayed 35-57 minutes by
GitHub, so a missing run and a late run look identical).

So the record answers two different questions with two different fields,
and neither can stand in for the other:

    lastObservedOn   are we still checking?      (advances daily)
    stateSince       how long has it been this?  (advances on change)

A write happens when the state changed **or** the day rolled over. That
bounds the volume to the thing being asserted — "we are still checking,
daily" — at <= 1 commit/day instead of 42, and **0** when the workflow
stops, which is itself the signal.

Per-run visibility is not lost: every run writes its full result to
``$GITHUB_STEP_SUMMARY``, in the run ledger, where a stale file cannot
fake it.

THE FINGERPRINT EXCLUDES TIME BY CONSTRUCTION
=============================================
``stateFingerprint`` is taken over ``(status, cohort, ffpcMarket,
lastError.type)`` only. Timestamps, run ids and error *messages* are
excluded structurally rather than by remembering to exclude them —
folding any clock-derived value in would restore the every-run write
while looking like it had been fixed. ``lastError.type`` is in and
``lastError.message`` is out deliberately: ``Unauthenticated`` is the
state, while ``"401 from https://…"`` carries a URL that could churn.

MISSING IS NOT ZERO
===================
``measured`` is an explicit boolean, and ``cohort`` / ``ffpcMarket`` stay
``{}`` when nothing was read. They are never filled with zeroed counters:
"the cohort has 0 qualified managers" and "we could not ask" are opposite
statements, and this repository's decision-path coercion gate exists
precisely to stop the second being written as the first.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

SCHEMA = 2

#: Statuses that mean the endpoints answered and we read real numbers.
#: Everything else — ``waiting``, ``deploy_failed``, ``endpoint_retry``,
#: ``degraded_timeout``, ``unverifiable_unauthenticated`` — means we did
#: NOT measure the population, which is a different claim from measuring
#: it and finding it empty.
MEASURED_STATUSES = frozenset({"healthy", "population_in_progress"})


def is_measured(status: str | None) -> bool:
    return status in MEASURED_STATUSES


def state_fingerprint(result: dict[str, Any]) -> str:
    """A content hash of the STATE, with every time-varying field excluded.

    Excluded by construction, not by convention: ``checkedAt``,
    ``attempts``, ``deployRunId``, ``deployHeadSha``, ``eventName`` and
    the error *message*.  Including any of them would silently restore
    the every-run write.
    """
    error = (result.get("errors") or [{}])[-1] if result.get("errors") else {}
    material = {
        "status": result.get("status"),
        "cohort": result.get("cohort") or {},
        "ffpcMarket": result.get("ffpcMarket") or {},
        "lastErrorType": error.get("type"),
    }
    blob = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_previous(text: str | None) -> dict[str, Any] | None:
    """Parse the committed record, tolerating absence and schema drift.

    A corrupt or older-schema file is treated as *no previous record*, so
    the next run rewrites it in the current shape.  It is never treated
    as evidence — an unparseable record cannot testify to a state.
    """
    if not text:
        return None
    try:
        previous = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(previous, dict) or previous.get("schema") != SCHEMA:
        return None
    return previous


def build_record(
    previous: dict[str, Any] | None,
    result: dict[str, Any],
    *,
    now_iso: str,
    today: str,
) -> dict[str, Any]:
    """The record this run would leave, given what came before it."""
    status = result.get("status")
    fingerprint = state_fingerprint(result)
    measured = is_measured(status)

    unchanged = bool(previous) and previous.get("stateFingerprint") == fingerprint
    state_since = previous["stateSince"] if unchanged else now_iso

    # Carried forward across runs: the last time this check could actually
    # see production.  ``None`` means it never has -- which is the live
    # situation, and is why R7's regression branch cannot fire spuriously.
    last_measured_on = (previous or {}).get("lastMeasuredOn")
    if measured:
        last_measured_on = today

    error = (result.get("errors") or [{}])[-1] if result.get("errors") else None

    return {
        "schema": SCHEMA,
        "status": status,
        "measured": measured,
        "stateFingerprint": fingerprint,
        "stateSince": state_since,
        "lastObservedOn": today,
        "lastObservedAt": now_iso,
        "lastMeasuredOn": last_measured_on,
        "credentialRegression": credential_regression(previous, result),
        "lastRun": {
            "event": result.get("eventName"),
            "deployRunId": result.get("deployRunId"),
            "deployHeadSha": result.get("deployHeadSha"),
            "deployConclusion": result.get("deployConclusion"),
            "attempts": result.get("attempts"),
        },
        "cohort": result.get("cohort") or {},
        "ffpcMarket": result.get("ffpcMarket") or {},
        "lastError": error,
    }


def credential_regression(previous: dict[str, Any] | None, result: dict[str, Any]) -> bool:
    """True when a check that COULD once measure production no longer can.

    This is the one tooth in an otherwise non-enforcing gate.  A standing
    ``unverifiable_unauthenticated`` is not a failure — the workflow was
    never issued a credential, and failing 12x a day for that is how a
    gate gets deleted.  But *losing* a capability the record shows it once
    had is a regression, and regressions are red.

    It reads history, which the enforce gate deliberately does not.  That
    is safe in the direction that matters: this can only ADD a failure
    condition, never remove one, so it cannot manufacture a green.
    """
    if result.get("status") != "unverifiable_unauthenticated":
        return False
    return bool((previous or {}).get("lastMeasuredOn"))


def decide_write(previous: dict[str, Any] | None, record: dict[str, Any]) -> bool:
    """Whether this run should rewrite (and therefore commit) the record.

    Two reasons, and only two:

    * the state changed  -> the record is wrong until it is rewritten;
    * the day rolled over -> the heartbeat proves we are still checking.

    Anything else is a commit that says "still the same", and 42 of those
    a day is what this module exists to stop.
    """
    if previous is None:
        return True
    if previous.get("stateFingerprint") != record.get("stateFingerprint"):
        return True
    return previous.get("lastObservedOn") != record.get("lastObservedOn")
