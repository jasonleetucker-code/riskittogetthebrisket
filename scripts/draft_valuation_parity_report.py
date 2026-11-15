#!/usr/bin/env python3
"""Draft-valuation parity report: workbook vs canonical curve vs legacy server.

Read-only evidence for ``docs/draft/DRAFT_DATA_WORKBOOK_MAP.md``.  Loads the
golden workbook fixture (``tests/fixtures/draft_valuation/``) and prints:

1. canonical ``src/draft/rookie_auction/curve.py`` vs the workbook's cached
   values — per column (C, D, E, I, J, K, L), how many of 72 picks match;
2. the legacy ``server.py::_rookie_dollars_from_values`` vs the workbook in
   the scenarios that function actually runs in, with every pick that differs.

The legacy function is NOT imported through ``server`` (that would start the
app's module-level machinery): its source is lifted out of ``server.py`` with
``ast`` and executed against the spine column it would have read from the
synced workbook (the fixture's cached column E).  Nothing is modified.

Usage: ``python scripts/draft_valuation_parity_report.py [--json]``.  Exit 0.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.draft.rookie_auction.curve import compute_curve  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "draft_valuation" / "workbook_2026_10_17.json"


def _sig10(x) -> float:
    return float(f"{float(x):.10g}")


def _legacy_function(spine: list[float], workbook_readable: bool = True):
    tree = ast.parse((ROOT / "server.py").read_text(encoding="utf-8"))
    node = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_rookie_dollars_from_values"
    )
    module = ast.Module(body=[node], type_ignores=[])

    def _read_sheet_spine_and_floor(n: int = 72):
        if not workbook_readable:  # the function's own unreadable-workbook fallback
            return [1.0] * n, 0
        return list(spine[:n]), n

    ns = {"DRAFT_TOTAL_BUDGET": 1200, "_read_sheet_spine_and_floor": _read_sheet_spine_and_floor}
    exec(compile(module, "server.py", "exec"), ns)  # noqa: S102 — repo source, read-only
    return ns["_rookie_dollars_from_values"]


def _diff(label: str, got: list[float], want: list[float], labels: list[str]) -> dict:
    rows = [
        {"pick": labels[i], "legacy": got[i], "expected": want[i], "delta": got[i] - want[i]}
        for i in range(min(len(got), len(want)))
        if not math.isclose(got[i], want[i], abs_tol=1e-9)
    ]
    return {
        "scenario": label,
        "picks": len(got),
        "matching": min(len(got), len(want)) - len(rows),
        "differing": len(rows),
        "legacyTotal": sum(got),
        "maxAbsDelta": max((abs(r["delta"]) for r in rows), default=0.0),
        "rows": rows,
    }


def build_report() -> dict:
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows = fx["curve"]["rows"]
    labels = [f"{int(r['A'])}.{round((r['A'] - int(r['A'])) * 100):02d}" for r in rows]
    b = [r["B"] for r in rows]
    curves = [[r[c] for r in rows] for c in "FGH"]
    spine_cached = [r["E"] for r in rows]
    workbook_l = [float(r["L"]) for r in rows]

    canon = compute_curve(b, curves)
    cols = {}
    for col in "CDEIJKL":
        match = 0
        for prow, wrow in zip(canon.rows, rows):
            ours = {
                "C": prow.curve_value,
                "D": prow.final_dollars,
                "E": prow.spine,
                "I": prow.floor_units,
                "J": prow.fraction,
                "K": prow.monotone_units,
                "L": prow.final_dollars,
            }[col]
            if col in "CEJ":
                match += _sig10(ours) == wrow[col]
            else:
                match += Decimal(str(wrow[col])) == Decimal(ours)
        cols[col] = match

    legacy = _legacy_function(spine_cached)
    scenarios = [
        _diff("A: workbook column B in sheet order", legacy(b, 1200), workbook_l, labels),
    ]
    sorted_b = sorted(b, reverse=True)
    canon_sorted = [float(d) for d in compute_curve(sorted_b, curves).dollars]
    scenarios.append(
        _diff(
            "B: column B sorted descending (how server feeds board values) vs canonical on the same input",
            legacy(sorted_b, 1200),
            canon_sorted,
            labels,
        )
    )
    scenarios.append(
        _diff(
            "C: column B sorted descending vs the workbook's published L column",
            legacy(sorted_b, 1200),
            workbook_l,
            labels,
        )
    )
    scenarios.append(
        _diff(
            "D: workbook unreadable (legacy flat-spine fallback) vs workbook L",
            _legacy_function(spine_cached, workbook_readable=False)(b, 1200),
            workbook_l,
            labels,
        )
    )
    short = legacy(b[:60], 1200)
    scenarios.append(
        {
            "scenario": "E: 60 values (a vendor list shorter than 72) — canonical refuses",
            "picks": len(short),
            "legacyTotal": sum(short),
            "legacyFirst12": short[:12],
            "legacyLast12": short[-12:],
            "canonical": "CurveInputError: expected 72 rookie values",
        }
    )
    return {
        "fixtureSha256": fx["source"]["sha256"],
        "canonical": {
            "columnsMatching72": cols,
            "decayRate": str(canon.decay_rate),
            "residualAfterFloorUnits": canon.residual_after_floor_units,
            "residualAfterCapsUnits": canon.residual_after_caps_units,
            "carryQuotient": canon.carry_quotient,
            "carryMod": canon.carry_mod,
            "precisionMargin": str(canon.precision_margin),
            "totalDollars": str(canon.total_dollars),
        },
        "legacy": scenarios,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    report = build_report()
    if args.json:
        print(json.dumps(report, indent=1))
        return 0
    print(f"fixture sha256 {report['fixtureSha256']}")
    print("canonical vs workbook cached values (picks matching out of 72):")
    for col, n in report["canonical"]["columnsMatching72"].items():
        print(f"  {col}: {n}/72")
    for k, v in report["canonical"].items():
        if k != "columnsMatching72":
            print(f"  {k}: {v}")
    for sc in report["legacy"]:
        print(f"\n{sc['scenario']}")
        if "rows" not in sc:
            for k, v in sc.items():
                if k != "scenario":
                    print(f"  {k}: {v}")
            continue
        print(
            f"  matching {sc['matching']}/{sc['picks']}, differing {sc['differing']}, "
            f"legacy total {sc['legacyTotal']}, max |delta| {sc['maxAbsDelta']}"
        )
        for r in sc["rows"]:
            print(f"   {r['pick']}: legacy {r['legacy']} vs {r['expected']} ({r['delta']:+})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
