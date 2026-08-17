#!/usr/bin/env python3
"""Build the acquisition ledger from evidence already on disk (C1-U8).

THE ONE BRIDGE BETWEEN RAW EVIDENCE AND THE PROJECTION
──────────────────────────────────────────────────────
``src/retention/__init__.py`` states that nothing in that package may be
read by a decision path.  This script is that boundary, and it is
deliberately the only thing that crosses it: it reads raw transaction
PAYLOADS (not retention's read API, and never a value), normalises them
through ``src/acquisition/events.py``, and writes them into the
acquisition store.  Everything downstream is then a pure function of the
acquisition store alone.

Reading transaction payloads is not the circularity that rule exists to
prevent — a trade is not something our valuation produced.  Reading a
retained VALUE would be, and nothing here does.

DETERMINISTIC AND IDEMPOTENT
────────────────────────────
Re-running is always safe.  Events are INSERT-only with conflicts
surfaced rather than applied; holdings and pick lineage are rebuilt
wholesale per league from those events, so a rebuild from scratch is a
valid repair for any derived-table corruption.

Exit codes (the ``playerctx`` convention used across ``scripts/``):
  0  work done, or nothing to do
  1  a real failure
  2  refused — a precondition was not met
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.acquisition.basis import attach_basis  # noqa: E402
from src.acquisition.events import events_from_draft_picks, events_from_transaction  # noqa: E402
from src.acquisition.holdings import derive_holdings, derive_pick_lineage  # noqa: E402
from src.acquisition.store import (  # noqa: E402
    coverage,
    read_events,
    replace_derivations,
    write_events,
)


def _log(msg: str) -> None:
    print(msg, flush=True)


def _transactions_for(league_key: str) -> list[tuple[dict[str, Any], str | None, str | None]]:
    """``(payload, sleeper_league_id, season)`` from the retention ledger.

    Rows written before C1-U8 carry a NULL ``league_key`` (the call site
    did not pass it), so those are matched by the registry's Sleeper ids
    instead of being silently skipped — a backfill that ignored the
    existing 288 rows would be starting from nothing for no reason.
    """
    from src.retention import league_events

    if not league_events.DB_PATH.exists():
        return []

    from src.api.league_registry import all_leagues

    chain_ids = {
        cfg.sleeper_league_id
        for cfg in all_leagues()
        if cfg.key == league_key and cfg.sleeper_league_id
    }

    conn = league_events.connect()
    try:
        rows = conn.execute(
            "SELECT payload_json, sleeper_league_id, season, league_key " "FROM league_transactions"
        ).fetchall()
    finally:
        conn.close()

    out: list[tuple[dict[str, Any], str | None, str | None]] = []
    for payload_json, sleeper_id, season, row_key in rows:
        if row_key and row_key != league_key:
            continue
        if not row_key and str(sleeper_id) not in chain_ids:
            continue
        try:
            payload = json.loads(payload_json)
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict):
            out.append((payload, sleeper_id, season))
    return out


def _draft_picks_for(league_key: str) -> list[dict[str, Any]]:
    """One record per draft: picks plus the metadata that identifies it.

    Draft is the one asset-origin class with no durable record anywhere,
    and a completed auction's realized prices become unrecoverable once
    Sleeper ages the draft object out — so this is a fetch, not a read
    of something we already kept.  Network failures degrade to "no draft
    evidence" rather than failing the build.
    """
    from src.api.league_registry import all_leagues
    from src.api.sleeper_overlay import _http_get_json, _walk_league_chain

    cfg = next((c for c in all_leagues() if c.key == league_key), None)
    if cfg is None or not cfg.sleeper_league_id:
        return []

    out: list[dict[str, Any]] = []
    for lid in _walk_league_chain(cfg.sleeper_league_id, max_depth=2):
        info = _http_get_json(f"https://api.sleeper.app/v1/league/{lid}")
        season = None
        if isinstance(info, dict):
            season = str(info.get("season") or "").strip() or None
        owners = _owner_by_roster(str(lid))
        drafts = _http_get_json(f"https://api.sleeper.app/v1/league/{lid}/drafts")
        for draft in drafts or []:
            if not isinstance(draft, dict):
                continue
            draft_id = str(draft.get("draft_id") or "").strip()
            if not draft_id:
                continue
            picks = _http_get_json(f"https://api.sleeper.app/v1/draft/{draft_id}/picks")
            if isinstance(picks, list) and picks:
                out.append(
                    {
                        "draft_id": draft_id,
                        "picks": picks,
                        "sleeper_league_id": str(lid),
                        # The draft object's OWN season, not the
                        # league's -- a startup draft can sit in a
                        # season the league object no longer reports.
                        "season": str(draft.get("season") or "").strip() or season,
                        # Sleeper's own draft type.  Previously fetched
                        # and discarded, which made a startup auction
                        # indistinguishable from a rookie draft.
                        "draft_kind": str(draft.get("type") or "").strip() or None,
                        "owner_by_roster": owners,
                    }
                )
    return out


def _owner_by_roster(sleeper_league_id: str) -> dict[Any, str]:
    """``roster_id -> Sleeper user id`` for one chain member.

    Reuses the overlay's own lookup so there is one definition of the
    roster->owner map.  Empty on failure: an unattributed event is
    honest, an invented manager is not.
    """
    try:
        from src.api.sleeper_overlay import _league_rid_lookup

        _names, rid_to_owner = _league_rid_lookup(str(sleeper_league_id))
        return {k: str(v) for k, v in (rid_to_owner or {}).items() if v}
    except Exception as exc:  # noqa: BLE001
        _log(f"[acquisition] WARNING: roster->owner map unavailable for {sleeper_league_id}: {exc}")
        return {}


def _draft_slots_for(sleeper_league_id: str) -> dict[tuple[int, int], int]:
    """``(season, origin_roster_id) -> draft slot`` for one chain member.

    Reuses ``sleeper_overlay._league_draft_slot_lookup``, the existing
    owner of slot resolution, rather than re-deriving draft order here.
    Empty on failure -- an unknown slot resolves a pick at its GENERIC
    grade, which is correct, so this degrades rather than guesses.
    """
    try:
        from src.api.sleeper_overlay import _league_draft_slot_lookup

        return _league_draft_slot_lookup(str(sleeper_league_id)) or {}
    except Exception as exc:  # noqa: BLE001
        _log(f"[acquisition] WARNING: draft-slot map unavailable for {sleeper_league_id}: {exc}")
        return {}


def _current_rosters(league_key: str) -> dict[str, int]:
    """``asset_id -> roster_id`` for what is held right now.

    Feeds the ``IMPORT_UNKNOWN`` pass: an asset on a roster with no
    explaining event is a fact worth recording as explicitly unexplained,
    rather than being left out so the projection looks complete.
    """
    from src.api.league_registry import all_leagues
    from src.api.sleeper_overlay import _http_get_json

    cfg = next((c for c in all_leagues() if c.key == league_key), None)
    if cfg is None or not cfg.sleeper_league_id:
        return {}

    rosters = _http_get_json(f"https://api.sleeper.app/v1/league/{cfg.sleeper_league_id}/rosters")
    out: dict[str, int] = {}
    for roster in rosters or []:
        if not isinstance(roster, dict):
            continue
        rid = roster.get("roster_id")
        if rid is None:
            continue
        for pid in roster.get("players") or []:
            out[f"player:{pid}"] = int(rid)
    return out


def build(league_key: str, *, offline: bool, dry_run: bool) -> int:
    _log(f"[acquisition] league={league_key} offline={offline} dry_run={dry_run}")

    events = []
    txs = _transactions_for(league_key)
    owner_cache: dict[str, dict[Any, str]] = {}
    slot_cache: dict[str, dict[tuple[int, int], int]] = {}
    for payload, sleeper_id, season in txs:
        lid = str(sleeper_id or "")
        if lid and not offline:
            if lid not in owner_cache:
                owner_cache[lid] = _owner_by_roster(lid)
            if lid not in slot_cache:
                slot_cache[lid] = _draft_slots_for(lid)
        events.extend(
            events_from_transaction(
                payload,
                league_key=league_key,
                sleeper_league_id=sleeper_id,
                season=season,
                owner_by_roster=owner_cache.get(lid),
                slot_by_origin=slot_cache.get(lid),
            )
        )
    _log(f"[acquisition] {len(txs)} retained transactions -> {len(events)} asset movements")

    rosters: dict[str, int] = {}
    if not offline:
        drafts = _draft_picks_for(league_key)
        for draft in drafts:
            events.extend(
                events_from_draft_picks(
                    draft["picks"],
                    league_key=league_key,
                    draft_id=draft["draft_id"],
                    sleeper_league_id=draft["sleeper_league_id"],
                    season=draft["season"],
                    draft_kind=draft["draft_kind"],
                    owner_by_roster=draft["owner_by_roster"],
                )
            )
        _log(f"[acquisition] {len(drafts)} drafts fetched")
        rosters = _current_rosters(league_key)
        _log(f"[acquisition] {len(rosters)} assets on current rosters")

    if dry_run:
        _log(f"[acquisition] DRY RUN — would offer {len(events)} events")
        return 0

    report = write_events(events)
    _log(
        f"[acquisition] events: inserted={report['inserted']} "
        f"unchanged={report['unchanged']} conflicts={len(report['conflicts'])}"
    )
    for conflict in report["conflicts"][:10]:
        _log(f"[acquisition]   CONFLICT (not applied): {conflict}")

    stored = read_events(league_key)
    holdings = derive_holdings(league_key, stored, current_rosters=rosters or None)
    attach_basis(holdings)
    lineage = derive_pick_lineage(league_key, stored)
    written = replace_derivations(league_key, holdings, lineage)
    _log(f"[acquisition] derived: holdings={written['holdings']} lineage={written['lineage']}")

    cov = coverage()
    _log(f"[acquisition] coverage: {json.dumps(cov, sort_keys=True)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--league", help="registry league key; default = every active league")
    ap.add_argument(
        "--offline",
        action="store_true",
        help="use only what is already on disk (no Sleeper fetch, so no draft or roster evidence)",
    )
    ap.add_argument("--dry-run", action="store_true", help="normalise and report, write nothing")
    args = ap.parse_args()

    try:
        from src.api.league_registry import active_leagues

        keys = [args.league] if args.league else [c.key for c in active_leagues()]
    except Exception as exc:  # noqa: BLE001
        print(f"[acquisition] REFUSED: cannot resolve the league registry: {exc}")
        return 2

    if not keys:
        print("[acquisition] REFUSED: no active leagues configured")
        return 2

    for key in keys:
        try:
            rc = build(key, offline=args.offline, dry_run=args.dry_run)
        except Exception as exc:  # noqa: BLE001
            print(f"[acquisition] FAILED for {key}: {exc}")
            return 1
        if rc:
            return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
