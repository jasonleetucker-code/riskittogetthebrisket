#!/usr/bin/env python3
"""Build / refresh the canonical temporal ledger (C1-U4).

Runs the three ingest stages in their canonical order and reports full
counts.  Every stage is deterministic and idempotent — re-running this
script against unchanged inputs writes zero new rows, and the summary
proves it (``written: 0, duplicates: N``).

Order matters and is fixed:

1. ``exports/archive/`` backfill — raw vendor values + scraper blend,
   plus the identity evidence (``_sleeperId`` ↔ display name) later
   stages resolve names against.
2. ``data/board_history.sqlite`` migration — canonical board rows
   (players AND picks) recorded by the C1-RET-02 recorder.
3. ``data/rank_history.jsonl`` migration — the long canonical rank/value
   log; names resolve to platform-id keys through the evidence stages
   1–2 ingested.  Only RECORDED values migrate; the read-time Hill
   reconstruction is refused by design.

Stages 2–3 skip cleanly (with a printed reason) where the production
stores don't exist — on a CI checkout only stage 1 has input.

Usage:
    python scripts/build_temporal_ledger.py             # full build
    python scripts/build_temporal_ledger.py --dry-run   # archive counts only
    python scripts/build_temporal_ledger.py --ledger /tmp/l.sqlite
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.history import backfill, migrate, store  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive-dir", type=Path, default=None)
    parser.add_argument("--ledger", type=Path, default=None, help="ledger DB path override")
    parser.add_argument("--board-history", type=Path, default=None)
    parser.add_argument("--rank-history", type=Path, default=None)
    parser.add_argument("--since", default=None, help="only archive dates >= YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-archive", action="store_true")
    parser.add_argument("--skip-migrations", action="store_true")
    args = parser.parse_args(argv)

    ledger = args.ledger

    print(f"Ledger:        {ledger or store.DB_PATH}")
    print(f"History floor: {store.HISTORY_FLOOR} (permanent — nothing earlier exists)")
    before = store.coverage(ledger)
    print(f"Before:        rows={before.get('rows', 0)} dates={before.get('dates', 0)}")
    print()

    ok = True

    if not args.skip_archive:
        print("[1/3] exports/archive backfill…")
        result = backfill.backfill_archive(
            args.archive_dir, path=ledger, dry_run=args.dry_run, since=args.since
        )
        t = result["totals"]
        print(
            f"      dates={t['dates']} written={t['written']} duplicates={t['duplicates']} "
            f"conflicts={t['contentConflicts']} rejected={t['rejected']} "
            f"unresolved={t['unresolved']} unreadableDates={t['unreadableDates']}"
        )
        if t["contentConflicts"]:
            ok = False
            print("      CONTENT CONFLICTS — the same observation identity arrived with")
            print("      different content.  Nothing was overwritten; investigate before rerun.")

    if not args.skip_migrations and not args.dry_run:
        print("[2/3] board_history.sqlite migration…")
        r2 = migrate.migrate_board_history(args.board_history, path=ledger)
        if r2.get("skipped"):
            print(f"      skipped: {r2['reason']}")
        else:
            print(
                f"      sourceRows={r2['sourceRows']} written={r2['written']} "
                f"duplicates={r2['duplicates']} conflicts={len(r2['contentConflicts'])} "
                f"unresolved={r2['unresolved']} empty={r2['empty']}"
            )
            if r2["contentConflicts"]:
                ok = False

        print("[3/3] rank_history.jsonl migration…")
        r3 = migrate.migrate_rank_history(args.rank_history, path=ledger)
        if r3.get("skipped"):
            print(f"      skipped: {r3['reason']}")
        else:
            print(
                f"      entries={r3['entries']} written={r3['written']} "
                f"duplicates={r3['duplicates']} conflicts={len(r3['contentConflicts'])} "
                f"nameKeyed={r3['nameKeyed']} unresolvedPicks={r3['unresolvedPicks']} "
                f"unkeyable={r3['unkeyable']}"
            )
            if r3["contentConflicts"]:
                ok = False

    print()
    after = store.coverage(ledger)
    print("After:")
    print(json.dumps(after, indent=1, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
