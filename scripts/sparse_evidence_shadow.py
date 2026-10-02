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

Each recorded (or already recorded) line also yields prospective learning
receipts (AL-1a, ``src/model_registry/producer_receipts.py``) in
``data/learning/receipts.sqlite``: OBSERVATION / FEATURES / MODEL / CHALLENGER /
one PREDICTION per side, pointing at the stored line. A receipt failure is logged
and never changes the exit code or the ledger; ``--no-learning-receipts`` skips it.

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
    emit_learning_receipts(args, record)
    return 0


def _stored_line(base: Path, key: str) -> tuple[str, dict] | None:
    """The line AS STORED for ``key`` and the file holding it.

    A re-run on a recorded board returns a freshly stamped copy, not the stored
    line, so receipts are always built from what the ledger actually holds."""
    for path in shadow.ledger_files(base):
        for rec in shadow.iter_records(path):
            if rec.get("key") == key:
                return path.name, rec
    return None


def emit_learning_receipts(args: argparse.Namespace, record: dict) -> None:
    """AL-1a prospective receipts for the stored line. Never raises, never changes
    the exit code: the ledger line is already durable when this runs."""
    if getattr(args, "no_learning_receipts", False) or not record.get("key"):
        return
    try:
        from src.model_registry import producer_receipts as pr  # noqa: PLC0415
        from src.model_registry.feature_dictionary import load_dictionary  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 -- receipts must never break the recorder
        log(f"WARNING: learning receipts NOT written: {type(exc).__name__}: {exc}")
        return

    def build():
        found = _stored_line(Path(args.dir), str(record["key"]))
        if found is None:
            raise LookupError(f"ledger line {record['key']} not found under {args.dir}")
        name, stored = found
        return pr.sparse_evidence_receipts(stored, ledger_name=name, dictionary=load_dictionary())

    store = getattr(args, "learning_store", None)
    pr.emit_safely(
        build,
        label="sparse-evidence shadow",
        path=Path(store) if store else None,
        log=log,
    )


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
    rec.add_argument(
        "--learning-store",
        default=None,
        help="learning-receipt store (default data/learning/receipts.sqlite)",
    )
    rec.add_argument(
        "--no-learning-receipts",
        action="store_true",
        help="do not emit AL-1a learning receipts for the recorded line",
    )
    rec.set_defaults(func=cmd_record)
    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
