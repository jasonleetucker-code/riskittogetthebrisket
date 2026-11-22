"""How fresh are the rosters a contract carries?  (Brisket Trade Advisor B0-f)

The baked ``sleeper`` block is rebuilt by every scrape (~2 h).  When a
Sleeper fetch fails the scraper restores the last-good snapshot instead of
dropping the block, and until now nothing IN the contract said so: a restored
block read exactly like a live one.  The scraper now stamps the block itself
(``Dynasty Scraper.py::_stamp_roster_source``):

* ``rosterSource`` — ``"live"`` (fetched this run) or ``"last_good"``
  (restored after a failed fetch);
* ``rosterFetchedAt`` — when those rosters were actually fetched (ISO UTC);
* ``rosterSnapshotAgeHours`` — their age at the run that published them.

This module is the ONE reader of that evidence.  Rule:

* ``current`` — live rosters fetched no more than
  ``SCORING_SNAPSHOT_MAX_AGE_HOURS`` (6 h, the repo's existing scrape-cadence
  staleness rule) before ``now``;
* ``stale`` — restored rosters, or live rosters older than that;
* ``unknown`` — the contract carries no provable stamp (an older build, a
  malformed timestamp).  Unknown is never reported as current.

Only the DATE is exposed as ``asOf`` (``YYYY-MM-DD``) — the advisor's public
payload needs no finer clock.  :func:`roster_age` is the same verdict with the
exact fetch time and age, for operator measurement (``/api/status``
``freshness_slo``); it never feeds the advisor payload.  Pure: reads the passed
contract, writes nothing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

ROSTER_STATES = ("current", "stale", "unknown")

#: Tolerated clock disagreement between the scrape host and the server.
_CLOCK_SKEW_HOURS = 0.25


def _parse_iso(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None  # an unzoned clock cannot be compared honestly
    return dt.astimezone(timezone.utc)


def roster_age(contract: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """``{"state", "source", "fetchedAt", "ageHours", "maxAgeHours"}``.

    The one verdict (see the module docstring), with the exact fetch time and
    age.  ``fetchedAt`` / ``ageHours`` are ``None`` whenever the state is
    ``unknown``: an unprovable age is never reported as a number.
    """
    from src.api.league_registry import SCORING_SNAPSHOT_MAX_AGE_HOURS

    budget = float(SCORING_SNAPSHOT_MAX_AGE_HOURS)
    unknown = {"state": "unknown", "source": None, "fetchedAt": None, "ageHours": None}
    sleeper = contract.get("sleeper") if isinstance(contract, dict) else None
    if not isinstance(sleeper, dict):
        return {**unknown, "maxAgeHours": budget}
    source = sleeper.get("rosterSource")
    source = source if source in ("live", "last_good") else None
    fetched = _parse_iso(sleeper.get("rosterFetchedAt"))
    if source is None or fetched is None:
        return {**unknown, "source": source, "maxAgeHours": budget}
    now = now or datetime.now(timezone.utc)
    age_hours = (now - fetched).total_seconds() / 3600.0
    if age_hours < -_CLOCK_SKEW_HOURS:
        # A fetch time in the future is not evidence of anything.
        return {**unknown, "source": source, "maxAgeHours": budget}
    current = source == "live" and age_hours <= budget
    return {
        "state": "current" if current else "stale",
        "source": source,
        "fetchedAt": fetched.isoformat(),
        "ageHours": round(max(0.0, age_hours), 2),
        "maxAgeHours": budget,
    }


def served_roster_freshness(
    contract: Any,
    *,
    from_overlay: bool,
    overlay_fetched_at: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The :func:`roster_age` verdict for the rosters a private route SERVED.

    Waiver routes answer from one of two roster snapshots: the live Sleeper
    teams overlay when it answered, else the contract's own block.  A merged
    contract keeps the BAKED block's ``rosterSource`` / ``rosterFetchedAt``
    stamps beside the overlay's teams, so judging it by those stamps would
    describe rosters it is not serving.  The overlay's own fetch time
    (``overlayFetchedAt``, which stays honest on its stale-fallback path) is
    judged instead, by the same rule and budget: a live fetch is ``current``
    within ``SCORING_SNAPSHOT_MAX_AGE_HOURS``, older is ``stale``, and an
    unparseable or missing stamp is ``unknown`` — never current.

    Returns :func:`roster_age`'s fields plus ``delivery``
    (``"live_overlay"`` / ``"contract"``).  Private routes only: it carries
    the exact fetch time, which the public advisor shape deliberately omits.
    """
    if from_overlay:
        evidence = {"sleeper": {"rosterSource": "live", "rosterFetchedAt": overlay_fetched_at}}
        return {**roster_age(evidence, now=now), "delivery": "live_overlay"}
    return {**roster_age(contract, now=now), "delivery": "contract"}


def roster_freshness(contract: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """``{"state", "asOf", "source"}`` for the contract's own roster block.

    The advisor-facing shape (date only).  Same verdict as :func:`roster_age`.
    """
    age = roster_age(contract, now=now)
    fetched = _parse_iso(age["fetchedAt"])
    return {
        "state": age["state"],
        "asOf": fetched.date().isoformat() if fetched is not None else None,
        "source": age["source"],
    }
