#!/usr/bin/env python3
"""Dump what PRODUCTION computes and serves for the rookie-auction dollars (Batch G).

The input to the independent checker (``scripts/check_draft_valuation_independent.py``),
which must not import production itself.  Read-only: generations are read
with ``persist=False``, so nothing is written to any store.

Usage::

    python3 scripts/draft_valuation_dump_production.py --out prod.json [--years 2027 2028 2029]

Contents:

* ``golden`` — ``curve.compute_curve`` over the owner workbook's own inputs
  (column B and the F/G/H spine, from the pinned fixture): the half-dollar
  reference curve and the whole dollars;
* ``classes[<year>]`` — ``generation.read_class_generation("dynasty_main", year)``:
  the SERVED allocation (state, reference and whole dollars, record checksum)
  and its receipt (spine years, input mode).

Exit codes: 0 written; 2 bad input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.draft.rookie_auction.curve import compute_curve  # noqa: E402
from src.draft.rookie_auction.generation import read_class_generation  # noqa: E402

LEAGUE_KEY = "dynasty_main"
FIXTURE = ROOT / "tests" / "fixtures" / "draft_valuation" / "workbook_2026_10_17.json"


def _dstr(d) -> str:
    return format(d.normalize(), "f")


def production_dump(years) -> dict:
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))["curve"]["rows"]
    result = compute_curve([r["B"] for r in rows], [[r[c] for r in rows] for c in "FGH"])
    out: dict = {
        "schema": "draft_valuation_production_dump_v1",
        "leagueKey": LEAGUE_KEY,
        "golden": {
            "referenceDollars": [_dstr(d) for d in result.reference_dollars],
            "finalWholeDollars": list(result.final_whole_dollars),
        },
        "classes": {},
    }
    for year in years:
        gen = read_class_generation(LEAGUE_KEY, int(year), persist=False)
        alloc = gen.allocation
        receipt = gen.receipt()
        out["classes"][str(int(year))] = {
            "allocationState": gen.allocation_state,
            "referenceDollars": list(alloc.reference_dollars or []),
            "finalWholeDollars": list(alloc.final_whole_dollars or []),
            "recordChecksum": alloc.record_checksum,
            "spineYears": receipt.get("spineYears"),
            "inputMode": receipt.get("inputMode"),
            "unavailableReason": alloc.unavailable_reason,
        }
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--years", type=int, nargs="+", default=[2027, 2028, 2029])
    args = ap.parse_args(argv)
    Path(args.out).write_text(
        json.dumps(production_dump(args.years), indent=1) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
