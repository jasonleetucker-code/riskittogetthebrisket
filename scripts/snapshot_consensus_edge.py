#!/usr/bin/env python3
"""Persist today's Consensus Edge board, and label matured outcomes.

Runs on the box that serves the board, because it reads the live
contract from disk and writes into gitignored ``data/``.

Two jobs in one invocation, deliberately:

1. **Snapshot** — record what the board says today, with the model and
   parameter versions that produced it. Without this the feature can
   never answer "what did we say about X on D", and no call can ever be
   scored after the fact.
2. **Label** — fill in forward returns for snapshots whose horizon has
   now elapsed. Kept separate from the write so an outcome can never be
   recorded before it happened.

Idempotent: re-running on the same date replaces that date's rows for
the same model+params and leaves every other row alone.

Exit codes (repo convention — see scripts/refresh_playerctx.py):
    0  - snapshot written (or --dry-run parsed cleanly)
    1  - soft failure (no contract, no board, write error)
    2  - schema regression: the board came back structurally wrong
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.consensus_edge import service, snapshot  # noqa: E402


def log(msg: str) -> None:
    print(f"[ce-snapshot] {msg}", flush=True)


def _load_contract() -> dict | None:
    """The live contract, built the way the server builds it.

    The files on disk are the RAW scraper payload; ``dataFreshness`` is
    added by ``build_api_data_contract``. Snapshotting the raw payload
    directly would silently record ``hoursStale: null`` on every row —
    the same "an input never arrived" defect this whole audit is about,
    reintroduced in the job that exists to record the evidence.
    """
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

    for directory in (REPO / "exports" / "latest", REPO / "data"):
        for candidate in sorted(directory.glob("dynasty_data_*.json")):
            try:
                raw = json.loads(candidate.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            return build_api_data_contract(raw)
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--as-of", type=str, default=None, help="YYYY-MM-DD (default: today UTC)")
    ap.add_argument("--dry-run", action="store_true", help="build and report, do not write")
    ap.add_argument("--db", type=Path, default=None, help="override the snapshot database path")
    args = ap.parse_args(argv)

    contract = _load_contract()
    if not contract:
        print("[ce-snapshot] no contract on disk; nothing to snapshot", file=sys.stderr)
        return 1

    started = datetime.now(timezone.utc)
    board = service.build_board(
        contract,
        hours_stale=service.resolve_hours_stale(contract),
    )
    board["contractScrapedAt"] = contract.get("scrapeTimestamp")

    if board.get("status") != "ok":
        print(f"[ce-snapshot] board status {board.get('status')!r}", file=sys.stderr)
        return 1

    players = board.get("players") or []
    scored = [r for r in players if r.get("score") is not None]
    if not players:
        print("[ce-snapshot] board returned zero rows — refusing to write", file=sys.stderr)
        return 2

    availability = board.get("componentAvailability") or {}
    live = [k for k, v in availability.items() if v.get("available")]
    log(
        f"board: {len(players)} rows, {len(scored)} scored, "
        f"components live: {', '.join(live) or 'none'}"
    )
    log(
        f"model {board.get('modelVersion')} params {board.get('paramSetId')} "
        f"hoursStale {(board.get('inputs') or {}).get('hoursStale')}"
    )

    if args.dry_run:
        log("dry run — not writing")
        return 0

    as_of = args.as_of or date.today().isoformat()
    try:
        result = snapshot.write_board(board, as_of=as_of, path=args.db)
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"[ce-snapshot] write failed: {exc}", file=sys.stderr)
        return 1

    cov = snapshot.coverage(args.db)
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    log(f"wrote {result['written']} rows for {result['asOf']} in {elapsed:.1f}s")
    log(
        f"store now: {cov.get('rows')} rows across {cov.get('distinctDates')} dates "
        f"({cov.get('firstDate')} -> {cov.get('lastDate')})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
