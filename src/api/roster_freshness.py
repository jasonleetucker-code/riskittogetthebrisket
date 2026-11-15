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
payload needs no finer clock.  Pure: reads the passed contract, writes nothing.
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


def roster_freshness(contract: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """``{"state", "asOf", "source"}`` for the contract's own roster block."""
    from src.api.league_registry import SCORING_SNAPSHOT_MAX_AGE_HOURS

    sleeper = contract.get("sleeper") if isinstance(contract, dict) else None
    if not isinstance(sleeper, dict):
        return {"state": "unknown", "asOf": None, "source": None}
    source = sleeper.get("rosterSource")
    fetched = _parse_iso(sleeper.get("rosterFetchedAt"))
    if source not in ("live", "last_good") or fetched is None:
        return {
            "state": "unknown",
            "asOf": None,
            "source": source if source in ("live", "last_good") else None,
        }
    now = now or datetime.now(timezone.utc)
    age_hours = (now - fetched).total_seconds() / 3600.0
    if age_hours < -_CLOCK_SKEW_HOURS:
        # A fetch time in the future is not evidence of anything.
        return {"state": "unknown", "asOf": None, "source": source}
    current = source == "live" and age_hours <= float(SCORING_SNAPSHOT_MAX_AGE_HOURS)
    return {
        "state": "current" if current else "stale",
        "asOf": fetched.date().isoformat(),
        "source": source,
    }
