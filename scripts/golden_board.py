#!/usr/bin/env python3
"""Capture a canonical snapshot of every user-facing number on the board.

WHY THIS EXISTS
---------------
The 2026-08-04 decision-intelligence audit
(``docs/audits/decision-intelligence-audit-2026-08-04.md``) found 43
Critical and 130 High findings, and its Part B remediation plan opens with
a blocking prerequisite: **nothing else starts until a board change is
measurable.**  Several of the fixes deliberately move values — the IDP
re-fit, the pick-year discount gate, the TE-premium default — and several
others must move *nothing*.  Without a baseline those two cases are
indistinguishable, and a regression reads exactly like an intended repricing.

This script builds the real contract through the real entry point
(``build_api_data_contract``) from a pinned input export, and serializes
the decision-bearing fields to a stable, diffable JSON.  Pair it with
``scripts/board_diff.py``.

USAGE
-----
    # capture the pre-change baseline
    python scripts/golden_board.py --out tests/fixtures/golden/baseline.json

    # after a change
    python scripts/golden_board.py --out /tmp/after.json
    python scripts/board_diff.py tests/fixtures/golden/baseline.json /tmp/after.json

The input export is pinned (``--input``) rather than "whatever is latest",
because a scrape landing mid-comparison would show up as a code change.

Exit codes: 0 success, 1 nothing built, 2 error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_INPUT = REPO_ROOT / "exports" / "latest" / "dynasty_data_2026-08-04.json"

# The fields that constitute a user-facing decision.  Deliberately NOT
# every field on the row: diagnostics that carry a timestamp or a
# build-order artifact would make every capture differ from every other
# and the diff would be useless.
_ROW_FIELDS = (
    "assetClass",
    "position",
    "rankDerivedValue",
    "canonicalConsensusRank",
    "canonicalTierId",
    "confidenceBucket",
    "confidenceLabel",
    "marketGapDirection",
    "marketGapMagnitude",
    "sourceRankSpread",
    "isSingleSource",
    "hasSourceDisagreement",
    "quarantined",
    "pickYearDiscount",
    "anchorValue",
    "alphaShrinkage",
)


def _num(v):
    """Round floats so float noise is not reported as a board change."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, float):
        return round(v, 6)
    return v


def capture(input_path: Path) -> dict:
    from src.api.data_contract import build_api_data_contract

    raw = json.loads(input_path.read_text(encoding="utf-8"))
    contract = build_api_data_contract(raw)
    arr = contract.get("playersArray") or []

    rows: dict[str, dict] = {}
    for r in arr:
        if not isinstance(r, dict):
            continue
        key = str(r.get("displayName") or r.get("canonicalName") or "").strip()
        if not key:
            continue
        rows[key] = {f: _num(r.get(f)) for f in _ROW_FIELDS}
        # source coverage drives confidence and the single-source haircut,
        # so a change in WHICH sources voted is a board change even when
        # the resulting value happens to land the same.
        eff = r.get("effectiveSourceRanks") or {}
        rows[key]["_sourceKeys"] = sorted(eff) if isinstance(eff, dict) else []

    ranked = [r for r in arr if r.get("canonicalConsensusRank")]
    return {
        "inputExport": input_path.name,
        "scrapeTimestamp": (raw.get("scrapeTimestamp") or raw.get("date")),
        "totals": {
            "rows": len(arr),
            "ranked": len(ranked),
            "priced": sum(1 for r in arr if r.get("rankDerivedValue") is not None),
            "picks": sum(1 for r in arr if r.get("assetClass") == "pick"),
            "idp": sum(1 for r in arr if r.get("assetClass") == "idp"),
        },
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    if not args.input.exists():
        print(f"error: input export not found: {args.input}", file=sys.stderr)
        return 2
    try:
        snap = capture(args.input)
    except Exception as exc:  # noqa: BLE001 — the harness must report, not crash
        print(f"error: contract build failed: {exc}", file=sys.stderr)
        return 2

    if not snap["rows"]:
        print("error: contract produced zero rows", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(snap, indent=1, sort_keys=True), encoding="utf-8")
    t = snap["totals"]
    print(
        f"captured {t['rows']} rows ({t['ranked']} ranked, {t['priced']} priced, "
        f"{t['picks']} picks, {t['idp']} idp) -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
