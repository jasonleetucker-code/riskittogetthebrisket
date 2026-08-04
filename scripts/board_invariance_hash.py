#!/usr/bin/env python3
"""Byte-stable fingerprint of the live board, for default-board invariance checks.

WHY THIS EXISTS
===============
Every standing constraint in this repo's audit process says the same
thing: a change to any stage of ``_compute_unified_rankings`` must not
move a live value unless that move is intentional, explained and
measured.  Proving that requires comparing the board before and after a
change *on the same input*, and the trap documented in the audit prompt
is that a naive before/after diff picks up the prod refresh timer
landing new market data mid-session — one such run showed 379 "moved"
rows that were entirely a payload roll, not a code change.

So this script takes the raw scraper payload as an explicit argument,
never globbing ``exports/latest/`` for "the newest one".  Pin one file,
byte-compare it across runs (the script prints its md5 so a roll is
loud), and diff the board hash.

USAGE
=====
    # pin the payload first — the filename rolls daily
    cp exports/latest/dynasty_data_2026-07-30.json /tmp/pinned.json

    # before your change
    python3 scripts/board_invariance_hash.py /tmp/pinned.json --out /tmp/before.json

    # after your change
    python3 scripts/board_invariance_hash.py /tmp/pinned.json --out /tmp/after.json

    # compare
    python3 scripts/board_invariance_hash.py --compare /tmp/before.json /tmp/after.json

Exit codes: 0 = identical (or single-run success), 1 = board moved,
2 = usage/IO error.

WHAT IS FINGERPRINTED
=====================
``(displayName, assetClass, rankDerivedValue, canonicalConsensusRank)``
for every row of ``playersArray``, in payload order.  Those are the four
numbers a user actually trades on; a diagnostic-only field moving is not
a board move and deliberately does not trip this check.  ``--full`` adds
every scalar field on the row, for when you want to know whether a
change was truly inert rather than merely board-inert.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

# The contract build reads the operator's Sleeper league for roster count
# and TE premium.  A live fetch would make this fingerprint depend on
# whatever the commissioner set today, which is precisely the kind of
# hidden input this script exists to exclude.  Same isolation
# ``tests/conftest.py`` applies.
os.environ.setdefault("ALLOW_DEFAULT_LOGIN_DEV", "1")
os.environ.pop("SLEEPER_LEAGUE_ID", None)
os.environ.setdefault("LEAGUE_REGISTRY_PATH", "/nonexistent/path/for/invariance.json")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _board_rows(contract: dict[str, Any], full: bool) -> list[Any]:
    rows = contract.get("playersArray") or []
    if full:
        return [
            {
                k: v
                for k, v in sorted(r.items())
                if isinstance(v, (str, int, float, bool, type(None)))
            }
            for r in rows
        ]
    return [
        [
            r.get("displayName"),
            r.get("assetClass"),
            r.get("rankDerivedValue"),
            r.get("canonicalConsensusRank"),
        ]
        for r in rows
    ]


def _fingerprint(payload_path: Path, full: bool) -> dict[str, Any]:
    raw_bytes = payload_path.read_bytes()
    payload_md5 = hashlib.md5(raw_bytes).hexdigest()

    from src.api.data_contract import build_api_data_contract

    contract = build_api_data_contract(json.loads(raw_bytes))
    rows = _board_rows(contract, full)
    blob = json.dumps(rows, sort_keys=True, default=str)
    return {
        "payloadPath": str(payload_path),
        "payloadMd5": payload_md5,
        "rowCount": len(rows),
        "mode": "full" if full else "board",
        "boardHash": hashlib.sha256(blob.encode()).hexdigest(),
        "rows": rows,
    }


def _compare(before_path: Path, after_path: Path) -> int:
    before = json.loads(before_path.read_text())
    after = json.loads(after_path.read_text())

    if before["payloadMd5"] != after["payloadMd5"]:
        print(
            "REFUSING TO COMPARE: the two runs used different payload bytes\n"
            f"  before md5 {before['payloadMd5']}\n"
            f"  after  md5 {after['payloadMd5']}\n"
            "The exports/ filename rolls daily and a prod refresh timer can land\n"
            "new market data mid-session.  Pin ONE file, re-run both sides.",
            file=sys.stderr,
        )
        return 2

    if before["boardHash"] == after["boardHash"]:
        print(f"IDENTICAL — {before['rowCount']} rows, hash {before['boardHash'][:16]}")
        return 0

    b_rows, a_rows = before["rows"], after["rows"]
    print(f"BOARD MOVED — before {len(b_rows)} rows, after {len(a_rows)} rows")

    b_by_name = {
        json.dumps(r[:2] if isinstance(r, list) else r.get("displayName")): r for r in b_rows
    }
    a_by_name = {
        json.dumps(r[:2] if isinstance(r, list) else r.get("displayName")): r for r in a_rows
    }

    moved = [k for k in b_by_name if k in a_by_name and b_by_name[k] != a_by_name[k]]
    added = [k for k in a_by_name if k not in b_by_name]
    dropped = [k for k in b_by_name if k not in a_by_name]

    print(f"  moved:   {len(moved)}")
    print(f"  added:   {len(added)}")
    print(f"  dropped: {len(dropped)}")
    for k in moved[:20]:
        print(f"    {k}\n      before {b_by_name[k]}\n      after  {a_by_name[k]}")
    if len(moved) > 20:
        print(f"    ... and {len(moved) - 20} more")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("payload", nargs="?", help="raw scraper payload JSON (pin it; do not glob)")
    ap.add_argument("--out", help="write the fingerprint JSON here")
    ap.add_argument(
        "--full",
        action="store_true",
        help="fingerprint every scalar row field, not just the board four",
    )
    ap.add_argument(
        "--compare", nargs=2, metavar=("BEFORE", "AFTER"), help="diff two fingerprint files"
    )
    args = ap.parse_args()

    if args.compare:
        return _compare(Path(args.compare[0]), Path(args.compare[1]))

    if not args.payload:
        ap.error("payload is required unless --compare is used")

    payload_path = Path(args.payload)
    if not payload_path.is_file():
        print(f"no such payload: {payload_path}", file=sys.stderr)
        return 2

    fp = _fingerprint(payload_path, args.full)
    print(f"payload  {fp['payloadPath']}  md5 {fp['payloadMd5']}")
    print(f"rows     {fp['rowCount']}  mode {fp['mode']}")
    print(f"board    {fp['boardHash']}")
    if args.out:
        Path(args.out).write_text(json.dumps(fp, indent=2, default=str))
        print(f"wrote    {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
