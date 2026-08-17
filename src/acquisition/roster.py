"""Roster reconstruction — ``C1-ACQ-02``.

WHAT "ROSTER AT A DATE" CAN AND CANNOT MEAN
───────────────────────────────────────────
A holding period is an interval, so "who owned what at time T" is a
straightforward interval query.  What is NOT straightforward is how
confident the answer is, and a reconstruction that does not say so is
worse than none — it invites at-the-time analysis on a roster the
platform is guessing at.

So every answer carries a fidelity label, in the same vocabulary
``src/history/asof.py`` already uses for values:

``exact``            every holding covering T has a dated acquisition
``partial``          at least one covering holding is undated
                     (``IMPORT_UNKNOWN``, or an event Sleeper gave no
                     stamp for), so membership at T is inferred
``unavailable``      T precedes every recorded event for this league:
                     there is nothing to reconstruct FROM, which is a
                     different statement from an empty roster

The last one is the one worth being careful about.  An empty list and
"we have no evidence covering this instant" render identically and mean
opposite things.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FIDELITY_EXACT = "exact"
FIDELITY_PARTIAL = "partial"
FIDELITY_UNAVAILABLE = "unavailable"

REASON_NO_EVENTS = "no_recorded_events"
REASON_BEFORE_FIRST_EVENT = "before_first_recorded_event"


def _covers(holding: dict[str, Any], at_ms: int) -> bool:
    """Is this holding period open at ``at_ms``?

    An undated acquisition is treated as covering any instant up to its
    disposal — it is the conservative reading (the asset was held at
    some point before we learned of it) and it is what forces the
    ``partial`` label rather than being hidden inside an ``exact`` one.
    """
    acquired = holding.get("acquired_at_ms")
    disposed = holding.get("disposed_at_ms")
    if acquired is not None and int(acquired) > at_ms:
        return False
    if disposed is not None and int(disposed) <= at_ms:
        return False
    return True


def roster_at(
    league_key: str,
    instant: datetime,
    *,
    owner_rid: int | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Reconstruct roster membership at ``instant``.

    ``instant`` must be timezone-aware — the same contract
    ``value_known_before`` enforces, and for the same reason: a naive
    instant is a guess about the caller's timezone, and a guess has no
    place in a historical reconstruction.
    """
    if instant.tzinfo is None:
        raise ValueError(
            "naive datetime passed to roster_at; historical instants must be UTC-aware"
        )
    at_ms = int(instant.astimezone(timezone.utc).timestamp() * 1000)

    from src.acquisition.store import connect

    conn = connect(path)
    try:
        rows = conn.execute(
            "SELECT asset_id, owner_rid, sequence_num, acquired_at_ms, acquired_method, "
            "disposed_at_ms, basis_value, basis_missing_reason "
            "FROM holdings WHERE league_key = ? ORDER BY asset_id, owner_rid, sequence_num",
            (league_key,),
        ).fetchall()
        earliest = conn.execute(
            "SELECT MIN(occurred_at_ms) FROM acquisition_events "
            "WHERE league_key = ? AND occurred_at_ms IS NOT NULL",
            (league_key,),
        ).fetchone()[0]
    finally:
        conn.close()

    base = {
        "leagueKey": league_key,
        "instant": instant.astimezone(timezone.utc).isoformat(),
        "ownerRosterId": owner_rid,
        "assets": [],
    }

    if not rows:
        return {**base, "fidelity": FIDELITY_UNAVAILABLE, "missingReason": REASON_NO_EVENTS}

    if earliest is not None and at_ms < int(earliest):
        return {
            **base,
            "fidelity": FIDELITY_UNAVAILABLE,
            "missingReason": REASON_BEFORE_FIRST_EVENT,
            "earliestEventMs": int(earliest),
        }

    cols = (
        "asset_id",
        "owner_rid",
        "sequence_num",
        "acquired_at_ms",
        "acquired_method",
        "disposed_at_ms",
        "basis_value",
        "basis_missing_reason",
    )
    assets: list[dict[str, Any]] = []
    inferred = 0
    for row in rows:
        holding = dict(zip(cols, row))
        if not _covers(holding, at_ms):
            continue
        if owner_rid is not None and int(holding["owner_rid"]) != int(owner_rid):
            continue
        if holding["acquired_at_ms"] is None:
            inferred += 1
        assets.append(
            {
                "assetId": holding["asset_id"],
                "ownerRosterId": int(holding["owner_rid"]),
                "acquiredAtMs": holding["acquired_at_ms"],
                "acquiredMethod": holding["acquired_method"],
                "basisValue": holding["basis_value"],
                "basisMissingReason": holding["basis_missing_reason"],
            }
        )

    return {
        **base,
        "assets": assets,
        "fidelity": FIDELITY_PARTIAL if inferred else FIDELITY_EXACT,
        "inferredMemberships": inferred,
        "missingReason": None,
    }
