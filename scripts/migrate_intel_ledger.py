#!/usr/bin/env python3
"""Migrate existing intel JSON snapshots into the normalized ledger.

Idempotent: the crawler's deterministic ``eventId`` is the ledger's
``movement_id``, so re-running this inserts nothing the second time
(the insert is ``INSERT OR IGNORE`` against a PRIMARY KEY).

Safe to run against production while the service is up.  The import
itself only inserts and never mutates existing rows — but note that
this script is NOT purely additive: after importing it calls
``ledger.prune()``, which issues
``DELETE FROM asset_movements WHERE ts < cutoff`` at
``MOVEMENT_RETENTION_DAYS`` (400) and then deletes any transaction left
with no movements.  On a ledger whose oldest row is well inside the
horizon that removes nothing, and the returned report says so via
``prunedBeyondRetention`` — but it is a delete, so back the file up
first:

    cp -a data/intel/ledger.sqlite3 data/intel/ledger.sqlite3.bak

(An earlier version of this docstring claimed the script "never
mutates or deletes existing rows", which was false for the prune step.
Corrected 2026-07-30.)

Note also that ``--dry-run`` reports ``eventsInSnapshot`` — what the
snapshots CONTAIN, not what would be inserted.  It never consults the
ledger, so the number is an upper bound: the real run drops both
already-present rows and rows missing a required id.

    python scripts/migrate_intel_ledger.py            # all snapshots
    python scripts/migrate_intel_ledger.py --league default
    python scripts/migrate_intel_ledger.py --dry-run  # report only

Exit codes: 0 success, 1 failure.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.intel import ingest, ledger, store  # noqa: E402

log = logging.getLogger("migrate_intel_ledger")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--league",
        action="append",
        dest="leagues",
        help="League key to migrate (repeatable). Default: every snapshot found.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be imported without writing.",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        if args.dry_run:
            keys = args.leagues
            if keys is None:
                files = sorted(store.DATA_DIR.glob("snapshot_*.json"))
                keys = [f.stem.replace("snapshot_", "", 1) for f in files]
            report = {"dryRun": True, "leagues": {}}
            for key in keys:
                state = store.load_state(key)
                events = [e for e in (state.get("events") or []) if isinstance(e, dict)]
                by_type: dict[str, int] = {}
                for e in events:
                    t = str(e.get("txType") or "unknown")
                    by_type[t] = by_type.get(t, 0) + 1
                report["leagues"][key] = {
                    "eventsInSnapshot": len(events),
                    "byTxType": by_type,
                }
            print(json.dumps(report, indent=2))
            return 0

        report = ingest.migrate_snapshots(args.leagues)
        removed = ledger.prune()
        report["prunedBeyondRetention"] = removed
        report["coverage"] = ledger.coverage()
        print(json.dumps(report, indent=2, default=str))
        return 0
    except Exception:  # noqa: BLE001
        log.exception("migration failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
