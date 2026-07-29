"""Bridge from the crawl snapshot into the normalized ledger.

The crawler and its JSON snapshot keep doing exactly what they do well
— budgeted, resumable acquisition, plus the crawl bookkeeping (cursor,
fetchState, holdings) that is inherently state-machine-shaped and does
not belong in a relational store.

What moves here is the ANALYTICAL half: every event the crawl has ever
seen is written to :mod:`src.intel.ledger`, which owns history,
retention, and all window queries.  Two consequences:

* Reads stop re-deriving aggregates from raw JSON on every request.
* History is no longer capped at the snapshot's 45-day prune, so 90-day
  and season-scale windows become answerable.

The migration is idempotent by construction — it reuses the crawler's
deterministic ``eventId`` as the ledger's ``movement_id``, so importing
the same snapshot any number of times inserts each movement once.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable

from src.intel import ledger, store

log = logging.getLogger(__name__)


def ingest_state(
    state: dict[str, Any],
    *,
    league_key: str | None = None,
    path: Path | None = None,
) -> ledger.IngestResult:
    """Write one crawl state's events + entities into the ledger."""
    if not isinstance(state, dict):
        return ledger.IngestResult()

    conn = ledger.connect(path)
    try:
        result = ledger.ingest_events(state.get("events") or [], conn=conn)

        # Entities, so the ledger can answer "who is this" and "which
        # leagues do we observe" without reopening the snapshot.
        names = state.get("memberNames") or {}
        ledger.upsert_users(
            [
                {"user_id": oid, "display_name": name}
                for oid, name in names.items()
                if str(oid or "").strip()
            ],
            conn=conn,
        )

        leagues = state.get("leagues") or {}
        ledger.upsert_leagues(
            [
                {
                    "league_id": lid,
                    "season": (lg or {}).get("season"),
                    "name": (lg or {}).get("name"),
                    "total_rosters": (lg or {}).get("totalRosters"),
                }
                for lid, lg in leagues.items()
                if isinstance(lg, dict)
            ],
            conn=conn,
        )

        memberships: list[tuple[str, str, str | None]] = []
        for lid, lg in leagues.items():
            if not isinstance(lg, dict):
                continue
            for oid in lg.get("memberOwnerIds") or []:
                memberships.append((str(lid), str(oid), None))
        ledger.upsert_memberships(memberships, conn=conn)
        return result
    finally:
        conn.close()


def migrate_snapshots(
    league_keys: Iterable[str] | None = None,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Import every existing ``data/intel/snapshot_*.json`` file.

    Safe to re-run: the deterministic movement id makes a second pass a
    no-op.  Returns a per-league report so the migration's effect is
    inspectable rather than assumed.
    """
    if league_keys is None:
        try:
            files = sorted(store.DATA_DIR.glob("snapshot_*.json"))
        except OSError:
            files = []
        keys = [f.stem.replace("snapshot_", "", 1) for f in files]
    else:
        keys = [str(k) for k in league_keys]

    report: dict[str, Any] = {"leagues": {}, "movementsInserted": 0, "movementsSeen": 0}
    for key in keys:
        state = store.load_state(key)
        result = ingest_state(state, league_key=key, path=path)
        report["leagues"][key] = {
            "movementsSeen": result.movements_seen,
            "movementsInserted": result.movements_inserted,
            "movementsSkipped": result.movements_skipped,
        }
        report["movementsInserted"] += result.movements_inserted
        report["movementsSeen"] += result.movements_seen
        log.info(
            "intel.ingest: migrated league=%s seen=%d inserted=%d",
            key,
            result.movements_seen,
            result.movements_inserted,
        )
    return report
