"""Record the sparse-evidence estimator in shadow on the newest served board.

    python scripts/sparse_evidence_shadow.py record [--payload PATH] [--dir DIR] [--allow-stale]

Builds the board twice in memory -- the served incumbent (flag
``sparse_evidence_estimator`` OFF) and candidate C (ON) -- and appends one line
per (payload, code revision, inputs, estimator version) to the append-only
monthly ``data/sparse_evidence_shadow/ledger-YYYY-MM.jsonl`` (gitignored). A
re-run on an unchanged board is a no-op. SHADOW ONLY: nothing is served,
flipped or promoted (``src/api/sparse_evidence_shadow.py``).

The board is the freshest payload by its own ``scrapeTimestamp``. One older than
the scrape-cadence budget (``SCORING_SNAPSHOT_MAX_AGE_HOURS``, 6 h) -- or with no
scrape time at all -- is refused with exit 3 rather than reported as "already
recorded"; ``--allow-stale`` records it anyway (an operator backfill).

Exit codes: 0 recorded (or already recorded); 1 no payload found or a write
error; 2 a built contract came back structurally wrong; 3 the newest payload is
stale or its age is unknown.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.api import sparse_evidence_shadow as shadow  # noqa: E402


def log(msg: str) -> None:
    print(f"[sparse-evidence-shadow] {msg}", flush=True)


def cmd_record(args: argparse.Namespace) -> int:
    if args.payload:
        path = Path(args.payload)
        if not path.exists():
            log(f"no payload at {path} -- nothing to record")
            return 1
        try:
            raw = json.loads(path.read_bytes())
        except (OSError, ValueError) as exc:
            log(f"cannot read {path}: {exc}")
            return 1
        at = shadow.payload_scraped_at(raw) if isinstance(raw, dict) else None
        age = None if at is None else (datetime.now(timezone.utc) - at).total_seconds() / 3600
    else:
        picked = shadow.newest_live_payload(REPO)
        if picked is None:
            log("no payload under exports/latest or data/ -- nothing to record")
            return 1
        path, raw, age = picked
    budget = shadow.stale_budget_hours()
    if (age is None or age > budget) and not args.allow_stale:
        shown = "unknown (no scrapeTimestamp)" if age is None else f"{age:.1f}h"
        log(
            f"STALE: newest payload {path} is {shown} old, past the {budget}h "
            "scrape-cadence budget -- not recorded (the feed may have stopped; "
            "--allow-stale to record it anyway)"
        )
        return 3
    try:
        source = str(path.resolve().relative_to(REPO)).replace("\\", "/")
    except ValueError:
        source = path.name
    try:
        result = shadow.record_board(
            raw, path, base=Path(args.dir), source=source, payload_age_hours=age
        )
    except OSError as exc:
        log(f"write failed: {exc}")
        return 1
    if result is None:
        log("a built contract had no playersArray")
        return 2
    record, written = result
    log(
        f"{'recorded' if written else 'already recorded'} {source} "
        f"age={record['board'].get('payloadAgeHours')}h "
        f"scoped={record['counts'].get('scoped', 0)} states={record['evidenceStates']}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record", help="record the newest served board")
    rec.add_argument("--payload", help="a payload file instead of the newest served one")
    rec.add_argument("--dir", default=str(shadow.DEFAULT_DIR), help="ledger directory")
    rec.add_argument(
        "--allow-stale",
        action="store_true",
        help="record a payload older than the staleness budget (operator backfill)",
    )
    rec.set_defaults(func=cmd_record)
    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
