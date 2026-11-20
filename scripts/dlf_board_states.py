#!/usr/bin/env python3
"""Persist and read the DLF per-board refresh states.

``merge``: fold one fetch run's ``--board-states`` output into the committed
``data/scrape_state/dlf_board_states.json``.  A board keeps its ``since`` while
its state is unchanged, so the file changes only when a state or its
reason changes, never merely because another run happened.

``report``: print one line per board (state, since, reason) for CI and the
staleness reports.  Exit 0 always; it reports, it does not judge.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "dlf-board-states/v1"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": SCHEMA, "boards": {}}
    if not isinstance(data, dict) or not isinstance(data.get("boards"), dict):
        return {"schema": SCHEMA, "boards": {}}
    return data


def merge(previous: dict, run: dict, now: str) -> dict:
    """New state document: one entry per board seen this run, ``since`` kept on no change."""
    boards = dict(previous.get("boards") or {})
    for key, entry in sorted((run or {}).items()):
        if not isinstance(entry, dict) or not entry.get("state"):
            continue
        old = boards.get(key) or {}
        same = old.get("state") == entry["state"]
        boards[key] = {
            "state": str(entry["state"]),
            "reason": str(entry.get("reason") or "")[:300],
            "since": old.get("since") if same and old.get("since") else now,
        }
    return {"schema": SCHEMA, "boards": boards}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge")
    m.add_argument("--run", type=Path, required=True)
    m.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("report")
    r.add_argument("--path", type=Path, default=Path("data/scrape_state/dlf_board_states.json"))
    args = ap.parse_args(argv)
    if args.cmd == "merge":
        try:
            run = json.loads(args.run.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[dlf-board-states] unreadable run file: {type(exc).__name__}", file=sys.stderr)
            return 1
        doc = merge(load(args.out), run, _now())
        args.out.parent.mkdir(parents=True, exist_ok=True)
        new = json.dumps(doc, indent=2, sort_keys=True) + "\n"
        if not args.out.exists() or args.out.read_text(encoding="utf-8") != new:
            args.out.write_text(new, encoding="utf-8")
        return 0
    doc = load(args.path)
    for key, entry in sorted((doc.get("boards") or {}).items()):
        print(f"{key}: {entry.get('state')} since {entry.get('since')} — {entry.get('reason')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
