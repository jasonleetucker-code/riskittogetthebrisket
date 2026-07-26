#!/usr/bin/env python3
"""Measure how far apart the two trade engines' asset values are.

WS-J F-6 (``docs/roster-trade-intelligence/F-6-finder-valuation-path.md``)
records that the two live trade engines read *different* values for the
same player:

    src/trade/suggestions.py  ->  playersArray[...]["rankDerivedValue"]
                                  the Final Framework output
    src/trade/finder.py       ->  players[name]["_finalAdjusted"]
                                  a verbatim deep copy of the raw
                                  scraper composite

``docs/CLAUDE_SESSION_AUDIT_HANDOFF.md`` §16.9 #3 recorded that nobody
had measured the resulting divergence.  This script measures it.

It is deliberately a **measurement**, not a fix.  It changes nothing and
recommends nothing.  It produces the numbers the F-6 migration decision
needs as an input — in particular F-6's own precondition, "confirm the
two scales are comparable at all".

Method
------
Load one raw scrape payload, build the API contract from *that same
payload*, then compare per asset:

    board  = row["rankDerivedValue"]              (suggestions.py)
    finder = contract["players"][name]["_finalAdjusted"]  (finder.py)

``contract["players"]`` is what ``server.py`` hands the finder, so this
reads the same dict the endpoint does.

Holding the input scrape constant is the point: any difference is
attributable to the transformation path alone, not to two data vintages.

What the numbers can and cannot support
---------------------------------------
Both values descend from the **same** upstream scrape.  Per
``docs/ORCHESTRATION.md`` §2b, agreement between them is therefore
**not** independent corroboration that either value is right — a shared
input reflected back through two transforms is exactly the failure mode
that rule exists to catch.  What this measurement *can* establish is the
magnitude and shape of the divergence between two code paths with the
input held constant.  It cannot say which value is more accurate; there
is no ground truth here.

Cohorts
-------
Offense and picks are carried as **controls**.  The IDP-specific
machinery (calibration post-pass, hierarchical anchoring, corridor
clamp) applies only to IDP and picks, so if offense diverges just as
much then the story is "the two pipelines differ everywhere", not "the
IDP machinery causes it".  Reporting IDP alone would invite precisely
the false attribution §2b warns about.

Usage
-----
    python scripts/measure_engine_value_divergence.py
    python scripts/measure_engine_value_divergence.py --json
"""

from __future__ import annotations

import argparse
import itertools
import json
import statistics
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# Thresholds are the live engines' own constants, so "would this change a
# verdict" is answered in the units the engines actually decide in.
from src.trade.finder import (  # noqa: E402
    EXCLUDED_POSITIONS,
    MAX_BOARD_LOSS,
    MIN_ASSET_VALUE,
)
from src.trade.suggestions import FAIRNESS_TOLERANCE  # noqa: E402

# suggestions.py::_fairness_label — the "even" band edge.
FAIRNESS_EVEN_EDGE = 256

DEFAULT_PAYLOAD = REPO / "exports" / "latest" / "dynasty_data_2026-07-26.json"


def _num(v: Any) -> float | None:
    """Coerce to a strictly positive float, else None."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _pct(sorted_vals: list[float], p: float) -> float:
    """Linear-interpolated percentile on a pre-sorted list."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = p * (len(sorted_vals) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def _spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman rank correlation with average ranks for ties."""

    def ranks(v: list[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        out = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    a, b = ranks(xs), ranks(ys)
    n = len(a)
    if n < 2:
        return 0.0
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5
    return num / den if den else 0.0


def collect(contract: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Join contract rows to the players dict the finder receives.

    Returns (comparable rows, coverage report).  Coverage matters
    independently of valuation: an asset only one engine can see is a
    divergence that no value comparison would surface.
    """
    players = contract.get("players") or {}
    rows: list[dict[str, Any]] = []
    only_finder: list[dict[str, Any]] = []
    only_board: list[dict[str, Any]] = []

    for row in contract.get("playersArray") or []:
        name = row.get("displayName") or row.get("canonicalName")
        if not name:
            continue
        asset_class = str(row.get("assetClass") or "unknown")
        position = str(row.get("position") or "")
        board = _num(row.get("rankDerivedValue"))
        src = players.get(name)
        finder = _num(src.get("_finalAdjusted")) if isinstance(src, dict) else None

        if board is not None and finder is not None:
            clamp = row.get("marketCorridorClamp")
            clamp_applied = bool(isinstance(clamp, dict) and clamp.get("applied"))
            rows.append(
                {
                    "name": name,
                    "assetClass": asset_class,
                    "position": position,
                    "board": board,
                    "finder": finder,
                    "diff": board - finder,
                    "absDiff": abs(board - finder),
                    "ratio": board / finder,
                    "clampApplied": clamp_applied,
                    "sourceCount": row.get("sourceCount"),
                }
            )
        elif finder is not None and board is None:
            # Visible to the finder, no board value at all.  Only count it
            # if the finder would actually trade it.
            if finder >= MIN_ASSET_VALUE and position.upper() not in EXCLUDED_POSITIONS:
                only_finder.append(
                    {
                        "name": name,
                        "assetClass": asset_class,
                        "position": position,
                        "finder": finder,
                        "sourceCount": row.get("sourceCount"),
                        "hasConsensusRank": bool(row.get("canonicalConsensusRank")),
                        "pickGenericSuppressed": bool(row.get("pickGenericSuppressed")),
                    }
                )
        elif board is not None and finder is None:
            only_board.append(
                {"name": name, "assetClass": asset_class, "position": position, "board": board}
            )

    from collections import Counter

    coverage = {
        "comparable": len(rows),
        "tradeableToFinderOnly": len(only_finder),
        "tradeableToFinderOnlyByClass": dict(Counter(r["assetClass"] for r in only_finder)),
        "tradeableToFinderOnlyWithConsensusRank": sum(
            1 for r in only_finder if r["hasConsensusRank"]
        ),
        "boardOnly": len(only_board),
        "boardOnlyByClass": dict(Counter(r["assetClass"] for r in only_board)),
        "boardOnlyExamples": [r["name"] for r in only_board[:6]],
        "topFinderOnly": sorted(only_finder, key=lambda r: -r["finder"])[:10],
    }
    return rows, coverage


def summarize(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    if not rows:
        return {"cohort": label, "n": 0}

    ratios = sorted(r["ratio"] for r in rows)
    absdiffs = sorted(r["absDiff"] for r in rows)
    signed = [r["diff"] for r in rows]
    xs = [r["board"] for r in rows]
    ys = [r["finder"] for r in rows]

    # A single scale factor explains the level difference; the residual
    # around it is the part that a rescale could NOT reconcile.
    scale = statistics.median(ratios)
    residual = sorted(abs(x - scale * y) for x, y in zip(xs, ys))

    # Ordering disagreement: a pair the two engines rank oppositely.  This
    # is the shape of divergence that survives any rescaling, and it is
    # what flips the finder's board_delta sign.
    inversions = 0
    material = 0
    pairs = 0
    for i, j in itertools.combinations(range(len(rows)), 2):
        pairs += 1
        if (xs[i] - xs[j]) * (ys[i] - ys[j]) < 0:
            inversions += 1
            if abs(xs[i] - xs[j]) >= FAIRNESS_EVEN_EDGE or abs(ys[i] - ys[j]) >= FAIRNESS_EVEN_EDGE:
                material += 1

    return {
        "cohort": label,
        "n": len(rows),
        "spearman": _spearman(xs, ys),
        "scaleFactor": scale,
        "residualMedian": statistics.median(residual),
        "residualP90": _pct(residual, 0.90),
        "ratioP10": _pct(ratios, 0.10),
        "ratioP90": _pct(ratios, 0.90),
        "absDiffMedian": statistics.median(absdiffs),
        "absDiffP90": _pct(absdiffs, 0.90),
        "absDiffMax": absdiffs[-1],
        "meanSignedDiff": statistics.fmean(signed),
        "boardHigherPct": 100.0 * sum(1 for d in signed if d > 0) / len(signed),
        "overBoardLossPct": 100.0
        * sum(1 for r in rows if r["absDiff"] >= abs(MAX_BOARD_LOSS))
        / len(rows),
        "overEvenPct": 100.0
        * sum(1 for r in rows if r["absDiff"] >= FAIRNESS_EVEN_EDGE)
        / len(rows),
        "overFairnessPct": 100.0
        * sum(1 for r in rows if r["absDiff"] >= FAIRNESS_TOLERANCE)
        / len(rows),
        "pairs": pairs,
        "inversions": inversions,
        "inversionPct": 100.0 * inversions / pairs if pairs else 0.0,
        "materialInversions": material,
        "materialInversionPct": 100.0 * material / pairs if pairs else 0.0,
        "clampedN": sum(1 for r in rows if r["clampApplied"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Measure trade-engine value divergence (F-6).")
    ap.add_argument("--payload", type=Path, default=DEFAULT_PAYLOAD)
    ap.add_argument("--top", type=int, default=12, help="worst-case rows to list")
    ap.add_argument("--json", action="store_true", help="emit JSON only")
    args = ap.parse_args()

    if not args.payload.exists():
        print(f"payload not found: {args.payload}", file=sys.stderr)
        return 2

    payload = json.loads(args.payload.read_text())

    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

    contract = build_api_data_contract(payload)
    rows, coverage = collect(contract)

    by_class: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_class.setdefault(r["assetClass"], []).append(r)

    idp = by_class.get("idp", [])
    summaries = [
        summarize(idp, "IDP"),
        summarize(by_class.get("offense", []), "offense"),
        summarize(by_class.get("pick", []), "pick"),
        summarize(rows, "ALL"),
    ]

    result = {
        "payload": str(args.payload),
        "scrapeTimestamp": payload.get("scrapeTimestamp"),
        "contractVersion": contract.get("contractVersion"),
        "thresholds": {
            "maxBoardLoss": abs(MAX_BOARD_LOSS),
            "fairnessEvenEdge": FAIRNESS_EVEN_EDGE,
            "fairnessTolerance": FAIRNESS_TOLERANCE,
            "minAssetValue": MIN_ASSET_VALUE,
        },
        "coverage": coverage,
        "cohorts": summaries,
        "idpClampSplit": {
            "clamped": summarize([r for r in idp if r["clampApplied"]], "IDP-clamped"),
            "unclamped": summarize([r for r in idp if not r["clampApplied"]], "IDP-unclamped"),
        },
        "worstIdp": [
            {
                k: r[k]
                for k in ("name", "position", "board", "finder", "diff", "ratio", "clampApplied")
            }
            for r in sorted(idp, key=lambda r: -r["absDiff"])[: args.top]
        ],
    }

    if args.json:
        print(json.dumps(result, indent=2, default=float))
        return 0

    print(f"payload : {args.payload.name}")
    print(f"scrape  : {payload.get('scrapeTimestamp')}")
    print()
    print("board = rankDerivedValue (suggestions.py) | finder = _finalAdjusted (finder.py)")
    print("Same scrape, same build. Differences are the transformation path only.")
    print()
    print("COVERAGE — assets only one engine can value")
    print(f"  comparable on both              : {coverage['comparable']}")
    print(
        f"  tradeable to finder, no board   : {coverage['tradeableToFinderOnly']}"
        f"  {coverage['tradeableToFinderOnlyByClass']}"
    )
    print(
        f"    ...of which carry a consensus rank: "
        f"{coverage['tradeableToFinderOnlyWithConsensusRank']}"
    )
    print(
        f"  board only, finder cannot see   : {coverage['boardOnly']}"
        f"  {coverage['boardOnlyByClass']}  e.g. {coverage['boardOnlyExamples'][:3]}"
    )
    print()
    print("VALUATION — level, shape and ordering")
    for s in summaries:
        if not s.get("n"):
            continue
        print(
            f"  {s['cohort']:<8} n={s['n']:<4} rho={s['spearman']:.4f}  k={s['scaleFactor']:.3f}  "
            f"resid med={s['residualMedian']:>5.0f} p90={s['residualP90']:>5.0f}  "
            f"|diff| med={s['absDiffMedian']:>5.0f} p90={s['absDiffP90']:>5.0f} max={s['absDiffMax']:>5.0f}"
        )
    print()
    print("  k = median(board/finder): a single scale factor.")
    print("  resid = |board - k*finder|: what a pure rescale could NOT reconcile.")
    print()
    print("ORDERING DISAGREEMENT — pairs the two engines rank oppositely")
    for s in summaries:
        if not s.get("n"):
            continue
        print(
            f"  {s['cohort']:<8} {s['inversions']:>6}/{s['pairs']:<7} pairs "
            f"({s['inversionPct']:5.2f}%)   material (>= {FAIRNESS_EVEN_EDGE} apart): "
            f"{s['materialInversions']:>5} ({s['materialInversionPct']:.2f}%)"
        )
    print()
    print("SHARE DIVERGING BY MORE THAN THE ENGINES' OWN DECISION UNITS")
    for s in summaries:
        if not s.get("n"):
            continue
        print(
            f"  {s['cohort']:<8} >={abs(MAX_BOARD_LOSS)}: {s['overBoardLossPct']:5.1f}%   "
            f">={FAIRNESS_EVEN_EDGE}: {s['overEvenPct']:5.1f}%   "
            f">={FAIRNESS_TOLERANCE}: {s['overFairnessPct']:5.1f}%"
        )
    print()
    print("IDP SPLIT — did the market corridor clamp fire?")
    for key in ("clamped", "unclamped"):
        s = result["idpClampSplit"][key]
        if not s.get("n"):
            continue
        print(
            f"  {s['cohort']:<14} n={s['n']:<4} k={s['scaleFactor']:.3f}  "
            f"|diff| med={s['absDiffMedian']:>5.0f} p90={s['absDiffP90']:>5.0f} "
            f"max={s['absDiffMax']:>5.0f}"
        )
    print()
    print(f"WORST {args.top} IDP DIVERGENCES")
    print(f"  {'player':<26}{'pos':<5}{'board':>7}{'finder':>8}{'diff':>8}{'ratio':>8}  clamped")
    for r in result["worstIdp"]:
        print(
            f"  {r['name'][:25]:<26}{r['position']:<5}{r['board']:>7.0f}{r['finder']:>8.0f}"
            f"{r['diff']:>+8.0f}{r['ratio']:>8.3f}  {'yes' if r['clampApplied'] else ''}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
