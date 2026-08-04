#!/usr/bin/env python3
"""Record today's canonical board into the as-of history.

Runs on the box that serves the board: it reads the live export from
disk and writes into gitignored ``data/``.

WHY
---
Nothing on this platform has ever been validated for accuracy, and the
reason is mechanical rather than cultural — measuring accuracy needs to
know what the board said in the past, and every board was computed,
served and discarded.  The 2026-08-04 audit's Phase 8.1 asks for this
store first and separately from the other 173 fixes, because it only
records: it blocks nothing, and every day it is not running is a day of
evidence that cannot be recovered afterwards.

Idempotent: re-running on a date replaces that date's rows for the same
pipeline version and leaves every other row alone.  Running it more
than once a day is harmless.

Exit codes (repo convention — see scripts/refresh_playerctx.py):
    0  - snapshot written (or --dry-run parsed cleanly)
    1  - soft failure (no export found, no rows, write error)
    2  - the contract came back structurally wrong
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

from src.snapshots import board_store  # noqa: E402


def log(msg: str) -> None:
    print(f"[board-snapshot] {msg}", flush=True)


def _load_contract() -> dict | None:
    """The live contract, built the way the server builds it.

    The files on disk are the RAW scraper payload; the pipeline fields
    this store exists to record — ``rankDerivedValue``,
    ``canonicalConsensusRank``, ``canonicalTierId`` — are added by
    ``build_api_data_contract``.  Snapshotting the raw payload directly
    would record a history of nulls: an input that never arrived,
    recorded as if it had, which is the defect class this whole audit
    is about.
    """
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

    for directory in (REPO / "exports" / "latest", REPO / "data"):
        if not directory.is_dir():
            continue
        # NEWEST first — the filenames carry a date, and an ascending
        # sort would snapshot the oldest payload in the directory under
        # today's date.
        for path in sorted(directory.glob("dynasty_data*.json"), reverse=True):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                log(f"skip {path.name}: {exc}")
                continue
            if not isinstance(raw, dict):
                continue
            log(f"building contract from {path.relative_to(REPO)}")
            return build_api_data_contract(raw)
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--as-of",
        default=None,
        help="ISO date to file the snapshot under (default: today, UTC)",
    )
    ap.add_argument("--db", type=Path, default=None, help="override the store path")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="build and report, write nothing",
    )
    args = ap.parse_args(argv)

    as_of = args.as_of or datetime.now(timezone.utc).date().isoformat()
    try:
        date.fromisoformat(as_of)
    except ValueError:
        log(f"error: --as-of is not an ISO date: {as_of!r}")
        return 2

    try:
        contract = _load_contract()
    except Exception as exc:  # noqa: BLE001 — a recording job reports, it never crashes the box
        log(f"error: contract build failed: {exc}")
        return 2

    if not contract:
        log("no export found under exports/latest or data/ — nothing to record")
        return 1

    rows = contract.get("playersArray")
    if not isinstance(rows, list):
        log("error: contract has no playersArray — refusing to record a malformed board")
        return 2

    version = board_store.pipeline_version(contract)
    if args.dry_run:
        priced = sum(
            1 for r in rows if isinstance(r, dict) and r.get("rankDerivedValue") is not None
        )
        log(f"dry-run: would record {len(rows)} rows ({priced} priced) as_of={as_of} v={version}")
        return 0

    try:
        result = board_store.write_board(contract, as_of=as_of, path=args.db)
    except Exception as exc:  # noqa: BLE001
        log(f"error: write failed: {exc}")
        return 1

    if result.get("skipped"):
        log(f"nothing recorded: {result.get('reason')}")
        return 1

    log(
        f"recorded {result['written']} rows as_of={result['asOf']} "
        f"v={result['contractVersion']}"
    )
    if result.get("unkeyableRows"):
        # Not a failure, but never silent: a row the store cannot key is
        # a row absent from every future measurement.
        log(f"WARNING: {result['unkeyableRows']} row(s) had no usable player key")

    cov = board_store.coverage(args.db)
    log(f"history now: {cov['dates']} date(s), {cov['rows']} rows, {cov['priced']} priced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
