"""Resolve the board's optional inputs, in exactly one place.

:func:`consensus_edge.service.build_board` takes three optional inputs —
the sharp-money ledger, board rank history, and player context. Each is
absent in some environments and present in others, and each degrades to
``None`` rather than to a neutral zero.

**Why this is a module and not two copies of three functions.** There
are two callers: the API, which answers requests, and
``scripts/snapshot_consensus_edge.py``, the daily job that records what
the model actually said. The snapshot job passed *none* of the three, so
the history it accrued was a board built from strictly less evidence
than the one users were served — and the whole purpose of that history
is to answer "was what we showed right". A recorded board that was never
shown answers nothing. Worse, the discrepancy is invisible: both boards
are well-formed, and the components the job dropped simply report
themselves absent, which is a legitimate state.

So the resolution lives here and both callers spend it whole. Adding a
fourth input means adding it to :func:`resolve` and both callers get it.

**Every resolver is total.** A missing file, a schema change, a locked
database — all return ``None``. Consensus Edge degrades to "this
component is dark" and never takes the board down with it.

**``None`` and ``{}`` are different answers.** ``None`` is "we could not
look"; ``{}`` is "we looked and found nothing". Only the second is a
finding, so an unreadable or empty source returns ``None`` and the
dependent component reports itself unavailable rather than neutral.
"""

from __future__ import annotations

from typing import Any

# Days of board history the momentum-risk axis considers. Matches the
# retention the snapshot log is written with.
RANK_HISTORY_DAYS = 30


def _ledger_movement_rows(conn: Any) -> list[tuple]:
    """Trade movements in canonical identity terms where available.

    Two shapes exist in the same table. The legacy Sleeper-only schema
    (``src/intel/ledger.py``) has ``asset_id`` / ``user_id`` /
    ``league_id``; the additive platform migration
    (``src/intel/platform_ledger.py``) adds ``canonical_asset_id`` /
    ``manager_key`` / ``league_key`` and backfills the Sleeper rows as
    ``'sleeper:' || user_id``.

    The canonical columns are the ones the rest of the sharp stack joins
    on, so they are preferred; the legacy fallback constructs the same
    ``sleeper:`` prefix rather than emitting a bare id that would match
    no cohort key. Which shape is present is read off ``PRAGMA
    table_info`` rather than by attempting the query and catching — a
    caught error here would look identical to an empty ledger.
    """
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(asset_movements)")}
    if {"canonical_asset_id", "manager_key", "league_key"} <= columns:
        sql = """
            SELECT COALESCE(canonical_asset_id, asset_id),
                   action,
                   COALESCE(manager_key, 'sleeper:' || user_id),
                   COALESCE(league_key, 'sleeper:' || league_id),
                   COALESCE(timestamp_ms, ts)
              FROM asset_movements
             WHERE tx_type = 'trade'
        """
    else:
        sql = """
            SELECT asset_id,
                   action,
                   'sleeper:' || user_id,
                   'sleeper:' || league_id,
                   ts
              FROM asset_movements
             WHERE tx_type = 'trade'
        """
    return conn.execute(sql).fetchall()


def _qualified_cohort() -> dict[str, float] | None:
    """``{manager_key: quality}`` for the qualified cohort, or None.

    Delegates to ``src.sharp.market.cohort_members`` — the one definition
    of who is qualified — rather than reimplementing the criteria. A
    second, subtly different cohort is how a repo ends up with two
    answers to "is this manager sharp", and the failure is silent.

    Note this may trigger the additive platform-schema migration on
    first use, exactly as a Sharp Tracker request does; the migration
    takes its own backup.
    """
    try:
        from src.sharp.market import cohort_members  # noqa: PLC0415

        members, _coverage = cohort_members()
    except Exception:  # noqa: BLE001 — a dark component must never 500 the board
        return None
    return {m.manager_key: float(m.quality) for m in members if m.manager_key}


def sharp_movements() -> tuple[dict[str, Any] | None, str | None]:
    """``(movements_by_asset, unavailable_reason)`` for the qualified cohort.

    Reads only; imports the ledger lazily so this module stays free of
    ``src/intel`` at import time (PR #670 is rewriting that package).

    **The cohort filter is applied here.** It used to be claimed and not
    applied: this docstring said "qualified-manager trade movements" and
    ``sharp_flow.py``'s said "qualified-manager", while the query was
    ``WHERE tx_type = 'trade'`` and nothing else. The filtering was real
    but *incidental* — ``scripts/crawl_sharp_activity.py`` only crawls
    managers who are qualified at crawl time, so the corpus arrives
    pre-conditioned. Relying on that is fragile in the way that matters:
    the day anything else writes to the ledger, Sharp Flow silently
    starts counting unqualified managers under a name that says it does
    not.

    **``managerQuality`` is supplied.** It was not, so
    ``movements_from_ledger_rows`` defaulted every manager to 1.0 and
    ``aggregate_asset``'s quality weighting was inert — a term in the
    formula that could not vary. The quality comes from the same
    ``CohortMember`` records the Sharp Tracker weights by.

    **What this does NOT fix**, and it is the larger problem: the corpus
    is conditioned on TODAY's cohort, not the cohort at the time of each
    trade. A manager qualified in March but not now had their movements
    never collected; one who qualified later carries only a ~30-day
    backfill. That is survivorship on a proxy for the outcome, it is
    upstream of this function, and no filter applied here can undo it.
    It is why Sharp Flow stays unvalidated even with a populated ledger —
    see ``docs/consensus-edge/METHODOLOGY.md``.
    """
    try:
        from src.consensus_edge import sharp_flow  # noqa: PLC0415
        from src.intel import ledger  # noqa: PLC0415

        path = ledger.default_path()
        if not path.exists():
            return None, sharp_flow.STATUS_NO_LEDGER
        quality = _qualified_cohort()
        if not quality:
            # A corpus we cannot attribute to qualified managers is not
            # a qualified-manager corpus. Reported as its own status
            # rather than as "no ledger", which would be a different
            # (and wrong) explanation for the same blank panel.
            return None, sharp_flow.STATUS_NO_COHORT
        with ledger.connect(path) as conn:
            rows = _ledger_movement_rows(conn)
    except Exception:  # noqa: BLE001 — a dark component must never 500 the board
        return None, "ledger_unreadable"

    scoped = [r for r in rows if r[2] in quality]
    if not scoped:
        # The ledger exists but holds no trades by the cohort. Still
        # None: with zero observations every posterior is the prior, and
        # reporting that as a measured neutral would be a finding we
        # have not earned.
        from src.consensus_edge import sharp_flow  # noqa: PLC0415

        return None, sharp_flow.STATUS_NO_LEDGER

    return (
        sharp_flow.movements_from_ledger_rows(
            {
                "asset_id": r[0],
                "action": r[1],
                "user_id": r[2],
                "league_id": r[3],
                "ts": r[4],
                "managerQuality": quality[r[2]],
            }
            for r in scoped
        ),
        None,
    )


def rank_history() -> dict[str, list[dict[str, Any]]] | None:
    """Per-player board history, or None when the log is absent.

    The log IS written in production on every fresh scrape
    (``src/api/rank_history.py``); it simply never reached the board.
    Absent outside production because ``data/`` is gitignored.

    Keys are ``{canonicalName}::{assetClass}`` — see
    ``service.rank_history_key``, which is the only correct way to index
    this dict.
    """
    try:
        from src.api import rank_history as rh  # noqa: PLC0415

        history = rh.load_history(days=RANK_HISTORY_DAYS)
    except Exception:  # noqa: BLE001 — same posture as the ledger
        return None
    return history or None


def player_context(contract: dict[str, Any] | None) -> dict[str, dict[str, Any]] | None:
    """Snap share and depth per board player, or None when there is none.

    ``data/playerctx/snapshot.json`` is refreshed weekly in production by
    an unconditional systemd timer and is gitignored, so this is
    populated there and empty everywhere else.
    """
    if not contract:
        return None
    try:
        from src.consensus_edge import identity_join  # noqa: PLC0415
        from src.playerctx.service import load_playerctx  # noqa: PLC0415

        snapshot = load_playerctx()
        if not snapshot:
            return None
        joined = identity_join.player_context_index(contract, snapshot)
    except Exception:  # noqa: BLE001 — same posture as the ledger
        return None
    return joined or None


def fingerprint() -> str:
    """A cheap string that changes when any optional input changes.

    Exists for one caller — the API's board cache — and for one reason:
    that cache was keyed on ``scrapeTimestamp|paramSetId`` and its
    docstring said "nothing else invalidates it", which is a statement
    of the bug rather than of the design. The ledger moves per trade and
    the playerctx snapshot moves weekly, both on their own schedules;
    between two scrapes the served board could not see either. The API
    would go on serving a board built before the data arrived.

    Deliberately a **stat**, not a read: mtime and size of the two files
    that back the two file-shaped inputs. Hashing their contents on
    every request would cost more than rebuilding the board. Rank
    history is covered by the scrape timestamp already — it is written
    by the same scrape.

    Unreadable inputs contribute a stable ``-``, matching the resolvers'
    own posture: "we could not look" is a state, not an error, and it
    must not churn the cache key every request.
    """
    parts: list[str] = []
    try:
        from src.intel import ledger  # noqa: PLC0415

        path = ledger.default_path()
        stat = path.stat()
        parts.append(f"ledger:{stat.st_mtime_ns}:{stat.st_size}")
    except Exception:  # noqa: BLE001 — a missing input is a state, not a failure
        parts.append("ledger:-")
    try:
        from src.playerctx import store as playerctx_store  # noqa: PLC0415

        stat = playerctx_store.SNAPSHOT_PATH.stat()
        parts.append(f"playerctx:{stat.st_mtime_ns}:{stat.st_size}")
    except Exception:  # noqa: BLE001
        parts.append("playerctx:-")
    return "|".join(parts)


def resolve(contract: dict[str, Any] | None) -> dict[str, Any]:
    """All three inputs, ready to splat into ``build_board``.

    Returned as kwargs precisely so a caller cannot take two of the
    three: ``build_board(contract, **resolve(contract))`` is the whole
    calling convention, and a partially-fed board is what this module
    exists to make impossible.
    """
    movements, reason = sharp_movements()
    return {
        "movements_by_asset": movements,
        "movements_unavailable_reason": reason,
        "rank_history_by_player": rank_history(),
        "player_context_by_player": player_context(contract),
    }
