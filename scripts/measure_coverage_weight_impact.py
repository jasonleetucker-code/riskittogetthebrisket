#!/usr/bin/env python3
"""Measure what APPLYING the depth-scaled coverage weight would do.

WHY THIS EXISTS
===============
``/api/data`` publishes, under ``methodology.idpTranslation.coverageWeight``:

    effective_weight = declared_weight * min(1, depth / min_full_depth)

with ``min_full_depth = 60``.  It is computed per source, stamped as
``sourceRankMeta.effectiveWeight`` — and never applied to the blend.
The 2026-07-29 audit labelled it DIAGNOSTIC ONLY rather than wiring it
in, because wiring it in changes the board and nothing had measured by
how much.

This script answers that.  It builds the board twice from one payload —
once at the registry defaults (all weights 1.0), once with every
source's weight set to its ``coverage_weight(...)`` value — and diffs.
It relies on the weighted blend added in the same audit; before that,
weights could not be applied at all.

WHAT IT FOUND (2026-07-29, live payload)
========================================
Only 3 of 21 sources are affected, because only three declare a depth
under 60 — the rookie lists ``dlfRookieSf``, ``dlfRookieIdp`` and
``flockFantasySfRookies``, each at depth 50, each scaled to 50/60 =
0.8333.  Every other source declares depth >= 100 (or None) and is
unchanged.

That small input change is NOT a small output change:

    rows moved              297 of 1094  (27%)
    ranks changed           221          (20%)
    max value delta         1072 points  (~11% of the 1-9999 scale)
    median value delta      0            (most moves are rank-only)
    board membership        1 row enters, 1 row leaves

The movement concentrates in ranks ~500-750 — deep players and rookies,
where coverage is thinnest.  Direction VARIES per player: down-weighting
a rookie source raises a player the source was bearish on and lowers one
it was bullish on, so this is not a uniform haircut.

RECOMMENDATION: do not apply it without a holdout backtest.  The
rationale ("a 50-deep list should count less than a 500-deep board") is
defensible, but it reprices 221 ranks on no accuracy evidence, and the
three affected sources are rookie lists that already ladder-translate
into combined-pool space before reaching the blend — so some of the
depth penalty they would take is arguably already handled.

USAGE
=====
    python scripts/measure_coverage_weight_impact.py
    python scripts/measure_coverage_weight_impact.py --out docs/measurements/x.json

Exit codes: 0 success, 1 error (missing payload / no rows).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.canonical.idp_backbone import (  # noqa: E402
    MIN_FULL_COVERAGE_DEPTH,
    coverage_weight,
)


def _default_payload_path() -> Path | None:
    latest = REPO_ROOT / "exports" / "latest"
    if not latest.is_dir():
        return None
    candidates = sorted(latest.glob("dynasty_data_*.json"))
    return candidates[-1] if candidates else None


def _index(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in contract.get("playersArray") or []:
        name = row.get("displayName") or row.get("canonicalName")
        if name:
            out[str(name)] = row
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    payload_path = args.payload or _default_payload_path()
    if payload_path is None or not payload_path.is_file():
        print(f"ERROR: no payload found (looked for {payload_path})", file=sys.stderr)
        return 1

    from src.api.data_contract import _RANKING_SOURCES, build_api_data_contract  # noqa: PLC0415

    payload = json.loads(payload_path.read_text())

    affected: list[dict[str, Any]] = []
    overrides: dict[str, dict[str, float]] = {}
    for src in _RANKING_SOURCES:
        key = str(src.get("key") or "")
        declared = float(src.get("weight") or 1.0)
        effective = coverage_weight(declared, src.get("depth"))
        overrides[key] = {"weight": effective}
        if abs(effective - declared) > 1e-9:
            affected.append(
                {
                    "key": key,
                    "depth": src.get("depth"),
                    "declared": declared,
                    "effective": round(effective, 4),
                }
            )

    base = build_api_data_contract(payload)
    weighted = build_api_data_contract(payload, source_overrides=overrides)

    a, b = _index(base), _index(weighted)
    moved: list[dict[str, Any]] = []
    entered: list[str] = []
    left: list[str] = []
    for name in sorted(set(a) & set(b)):
        va, vb = a[name].get("rankDerivedValue"), b[name].get("rankDerivedValue")
        ra, rb = a[name].get("canonicalConsensusRank"), b[name].get("canonicalConsensusRank")
        if va == vb and ra == rb:
            continue
        if va is None and vb is not None:
            entered.append(name)
        if va is not None and vb is None:
            left.append(name)
        moved.append(
            {
                "name": name,
                "valueBefore": va,
                "valueAfter": vb,
                "rankBefore": ra,
                "rankAfter": rb,
                "valueDelta": (vb or 0) - (va or 0),
            }
        )

    deltas = [abs(m["valueDelta"]) for m in moved]
    rank_changed = [m for m in moved if m["rankBefore"] != m["rankAfter"]]

    summary = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "payload": str(payload_path.relative_to(REPO_ROOT)),
        "minFullCoverageDepth": MIN_FULL_COVERAGE_DEPTH,
        "sourcesTotal": len(_RANKING_SOURCES),
        "sourcesAffected": affected,
        "rowsTotal": len(a),
        "rowsMoved": len(moved),
        "ranksChanged": len(rank_changed),
        "maxAbsValueDelta": max(deltas) if deltas else 0,
        "medianAbsValueDelta": statistics.median(deltas) if deltas else 0,
        "boardEntered": entered,
        "boardLeft": left,
        "largestMoves": sorted(moved, key=lambda m: -abs(m["valueDelta"]))[:20],
    }

    print(f"payload                 : {summary['payload']}")
    print(f"min_full_depth          : {MIN_FULL_COVERAGE_DEPTH}")
    print(f"sources affected        : {len(affected)} of {len(_RANKING_SOURCES)}")
    for row in affected:
        print(f"    {row['key']:26s} depth={row['depth']}  {row['declared']} -> {row['effective']}")
    print(f"rows total              : {summary['rowsTotal']}")
    print(f"rows moved              : {summary['rowsMoved']}")
    print(f"ranks changed           : {summary['ranksChanged']}")
    print(f"max |value delta|       : {summary['maxAbsValueDelta']}")
    print(f"median |value delta|    : {summary['medianAbsValueDelta']}")
    print(f"board entered / left    : {len(entered)} / {len(left)}")
    if entered or left:
        print(f"    entered: {entered}")
        print(f"    left   : {left}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, indent=2) + "\n")
        print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
