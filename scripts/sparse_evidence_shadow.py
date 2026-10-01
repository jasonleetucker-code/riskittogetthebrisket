"""Record the sparse-evidence estimator in shadow on the newest served board.

    python scripts/sparse_evidence_shadow.py record [--payload PATH] [--dir DIR]

Builds the board twice in memory -- the served incumbent (flag
``sparse_evidence_estimator`` OFF) and candidate C (ON) -- and appends one line
per (payload, code revision, inputs, estimator version) to the append-only
``data/sparse_evidence_shadow/ledger.jsonl`` (gitignored). A re-run on an
unchanged board is a no-op. SHADOW ONLY: nothing is served, flipped or promoted
(``src/api/sparse_evidence_shadow.py``).

Exit codes: 0 recorded (or already recorded); 1 no payload found or a write
error; 2 a built contract came back structurally wrong.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.api import sparse_evidence_shadow as shadow  # noqa: E402


def log(msg: str) -> None:
    print(f"[sparse-evidence-shadow] {msg}", flush=True)


def cmd_record(args: argparse.Namespace) -> int:
    path = Path(args.payload) if args.payload else shadow.newest_live_payload(REPO)
    if path is None or not path.exists():
        log("no payload under exports/latest or data/ -- nothing to record")
        return 1
    try:
        raw = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        log(f"cannot read {path}: {exc}")
        return 1
    try:
        source = str(path.resolve().relative_to(REPO)).replace("\\", "/")
    except ValueError:
        source = path.name
    try:
        result = shadow.record_board(raw, path, base=Path(args.dir), source=source)
    except OSError as exc:
        log(f"write failed: {exc}")
        return 1
    if result is None:
        log("a built contract had no playersArray")
        return 2
    record, written = result
    log(
        f"{'recorded' if written else 'already recorded'} {source} "
        f"scoped={record['counts'].get('scoped', 0)} states={record['evidenceStates']}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record", help="record the newest served board")
    rec.add_argument("--payload", help="a payload file instead of the newest served one")
    rec.add_argument("--dir", default=str(shadow.DEFAULT_DIR), help="ledger directory")
    rec.set_defaults(func=cmd_record)
    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
