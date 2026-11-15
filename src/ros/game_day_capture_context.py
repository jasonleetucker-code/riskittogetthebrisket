"""What each Game Day capture RUN was taken alongside -- script-only.

The injury report as known at capture time and the identity of the canonical
board current on the host, built as the two blocks
:func:`src.ros.game_day_archive.record_capture_context` records once per run.

**Why this is not in** ``src/ros/game_day_capture.py``.  That module is on
the request path (``src/api/matchup_intel.py`` imports it for
``estimate_index_from_ensemble``), and the injury block reads
``src/nfl_data/injury_history.py``, whose fetch-side helpers reference
``src/nfl_data/injury_feed.py`` -- the module behind the ``espn_injury_feed``
gate.  The capture only READS the stored as-known ledger; it never fetches
and never consults that gate.  Importing the ledger from a served module put
the feed module inside the server's import graph anyway, which
``tests/api/test_feature_flag_reachability.py`` correctly measured as a LIVE
gate that no request can actually reach.  So these builders live here,
imported only by ``scripts/capture_game_day_predictions.py``, and the gate
stays honestly ``SCRIPT_ONLY``.  Do not import this module from anything a
request reaches.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

#: Owners named in the records, so a reader knows which module's rules the
#: block follows.  Neither is re-implemented here.
INJURY_CONTEXT_OWNER = "src/nfl_data/injury_history.py::as_known_at"
BOARD_CONTEXT_OWNER = "src/api/sparse_evidence_shadow.py::newest_live_payload"


def injury_context_from_as_known(
    as_known: Mapping[str, Any] | None, *, error: str | None = None
) -> dict[str, Any]:
    """The injury report as this system knew it at capture time.

    ``as_known`` is :func:`src.nfl_data.injury_history.as_known_at`'s answer
    for the capture instant -- the latest PROVEN ESPN fetch at or before it
    (never a later one).  This module does not fetch: the injury refresh
    timer owns fetching and fetch proof, and a second fetch path would be a
    second definition of "what ESPN said".

    MISSING IS NEVER "NO INJURIES": no ledger, no record at or before the
    instant, or a reader error is ``state: "unavailable"`` with the reason.
    ``state: "known"`` with zero entries is a different statement -- a proven
    fetch whose report was empty -- and is kept as such.

    ``contentSha256`` is the ledger's own hash (``injury_history.content_sha256``
    over the provider's fields); it is recomputed from the copied entries and
    ``contentVerified`` says whether they still agree.  A disagreement is
    recorded, never repaired.
    """
    if error:
        return {"state": "unavailable", "reason": str(error), "owner": INJURY_CONTEXT_OWNER}
    if not isinstance(as_known, Mapping) or as_known.get("state") != "known":
        reason = as_known.get("reason") if isinstance(as_known, Mapping) else None
        return {
            "state": "unavailable",
            "reason": str(reason) if reason else "as_known_result_missing",
            "owner": INJURY_CONTEXT_OWNER,
        }
    snap = as_known.get("snapshot")
    entries = snap.get("entries") if isinstance(snap, Mapping) else None
    if not isinstance(entries, list):
        return {
            "state": "unavailable",
            "reason": "injury_snapshot_without_entries",
            "owner": INJURY_CONTEXT_OWNER,
        }
    from src.nfl_data.injury_history import content_sha256, provider_entries  # noqa: PLC0415

    recorded = snap.get("contentSha256")
    return {
        "state": "known",
        "owner": INJURY_CONTEXT_OWNER,
        "selection": "latest injury-history record fetched at or before the capture instant",
        "provider": snap.get("provider"),
        "endpoint": snap.get("endpoint"),
        "snapshotKey": snap.get("key"),
        "snapshotFetchedAt": snap.get("fetchedAt"),
        "lastObservedAt": as_known.get("lastObservedAt"),
        "observedAgeSeconds": as_known.get("observedAgeSeconds"),
        "providerAsOf": snap.get("providerAsOf"),
        "nullReasons": snap.get("nullReasons"),
        "contentSha256": recorded,
        "hashScheme": "injury-history/v1 content_sha256 (provider fields, sorted)",
        "contentVerified": bool(recorded) and recorded == content_sha256(provider_entries(entries)),
        "entryCount": len(entries),
        "identityDirectory": snap.get("identityDirectory"),
        "entries": entries,
    }


def board_context_from_payload(
    found: Sequence[Any] | None,
    *,
    stale_budget_hours: float | None,
    repo_root: Any = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Which canonical board was current on this host when the capture ran.

    ``found`` is ``newest_live_payload(with_bytes=True)``'s
    ``(path, raw payload, age hours, bytes)``.  The identity is the scheme
    the sparse-evidence shadow ledger already records for a board -- the
    sha256 of the payload FILE BYTES, the payload's own ``scrapeTimestamp``,
    its age against the repo's existing staleness budget -- not a new one.

    ``usedByEstimates`` is ``False`` and says so on purpose: Game Day point
    estimates come from the projection ensemble
    (``src/ros/projection_ensemble.py``, which never reads
    ``rankDerivedValue``), not from the canonical board.  This block pins the
    point-in-time SOURCE-RANKING context the capture was taken in; reading it
    as an input of the forecast would be wrong.
    """
    if error:
        return {"state": "unavailable", "reason": str(error), "owner": BOARD_CONTEXT_OWNER}
    if not found:
        return {
            "state": "unavailable",
            "reason": "no_served_board_payload_on_this_host",
            "owner": BOARD_CONTEXT_OWNER,
        }
    import hashlib  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    path, raw, age, data = found[0], found[1], found[2], found[3]
    source = str(path)
    if repo_root is not None:
        try:
            source = Path(path).resolve().relative_to(Path(repo_root).resolve()).as_posix()
        except ValueError:
            pass
    raw = raw if isinstance(raw, Mapping) else {}
    return {
        "state": "known",
        "owner": BOARD_CONTEXT_OWNER,
        "source": source,
        "payloadSha256": hashlib.sha256(data).hexdigest(),
        "hashScheme": "sha256 of the payload file bytes (sparse-evidence shadow board identity)",
        "scrapeTimestamp": raw.get("scrapeTimestamp") or raw.get("date"),
        "payloadAgeHours": None if age is None else round(float(age), 3),
        "staleBudgetHours": stale_budget_hours,
        # Unknown age is never "fresh".
        "stale": (
            None
            if age is None or stale_budget_hours is None
            else float(age) > float(stale_budget_hours)
        ),
        "usedByEstimates": False,
    }
