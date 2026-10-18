#!/usr/bin/env python3
"""Report-only rookie-class readiness for dynasty_main (draft valuation Batch B).

Builds the canonical contract from a raw export (or reads an already-built
``/api/data`` contract) and prints, as JSON, the class-input snapshot and the
readiness gates for one target class.  It writes nothing, schedules nothing
and promotes nothing (``readiness.PROMOTION_ENABLED`` is ``False``).

The NFL season the export's Sleeper ``yearsExp`` values belong to must be
given explicitly — this script never infers it from the clock.

Usage::

    python scripts/draft_valuation_readiness_report.py --target 2027 \
        --observed-nfl-season 2026 [--export exports/latest/dynasty_data_*.json | --contract FILE]

Exit codes: 0 report printed; 2 no input could be read.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.draft.rookie_auction.class_snapshot import build_class_candidate  # noqa: E402
from src.draft.rookie_auction.readiness import evaluate_class_readiness  # noqa: E402


def _load(args) -> tuple[dict, str | None]:
    if args.contract:
        contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
        return contract, (contract.get("meta") or {}).get("generatedAt") or contract.get("date")
    exports = (
        [args.export]
        if args.export
        else sorted(glob.glob(str(ROOT / "exports/latest/dynasty_data_*.json")))
    )
    if not exports:
        raise FileNotFoundError("no export found")
    raw = json.loads(Path(exports[-1]).read_text(encoding="utf-8"))
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

    return build_api_data_contract(raw), raw.get("scrapeTimestamp")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", type=int, required=True)
    ap.add_argument("--observed-nfl-season", type=int, required=True)
    ap.add_argument("--league", default="dynasty_main")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--export")
    src.add_argument("--contract")
    ap.add_argument("--entries", action="store_true", help="include the 72 entries")
    args = ap.parse_args(argv)
    try:
        contract, as_of = _load(args)
    except (OSError, ValueError) as exc:
        print(f"cannot read input: {exc}", file=sys.stderr)
        return 2
    snap = build_class_candidate(
        contract,
        target_draft_year=args.target,
        league_key=args.league,
        observed_nfl_season=args.observed_nfl_season,
        as_of=as_of,
    )
    report = evaluate_class_readiness(snap, league_key=args.league).to_dict()
    body = snap.to_dict()
    if not args.entries:
        body.pop("entries", None)
    print(json.dumps({"candidate": body, "readiness": report}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
