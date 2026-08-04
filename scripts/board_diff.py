#!/usr/bin/env python3
"""Diff two ``golden_board.py`` captures and report what moved.

WHY THIS EXISTS
---------------
Part B of the 2026-08-04 audit sequences 173 Critical/High fixes, and
records an EXPECTED movement for each phase before it runs — e.g. the
pick-year discount gate should move 2027 firsts +22% and touch nothing
else; the shared-threshold work should change labels and **no values at
all**.  This script is what turns that expectation into a check.

A diff that does not match the recorded expectation stops the phase.

USAGE
-----
    python scripts/board_diff.py BEFORE.json AFTER.json
    python scripts/board_diff.py BEFORE.json AFTER.json --expect-no-value-change

Exit codes: 0 diff produced (or matched the assertion), 1 assertion
violated, 2 error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_LABEL_FIELDS = (
    "canonicalTierId",
    "confidenceBucket",
    "confidenceLabel",
    "marketGapDirection",
    "isSingleSource",
    "hasSourceDisagreement",
    "quarantined",
)


def _pct(new, old):
    if old in (None, 0) or new is None:
        return None
    try:
        return (float(new) - float(old)) / abs(float(old)) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _quantiles(vals: list[float]) -> dict:
    if not vals:
        return {}
    s = sorted(vals)
    n = len(s)

    def q(p):
        return s[min(n - 1, int(p * n))]

    return {"p50": q(0.50), "p90": q(0.90), "max": s[-1], "n": n}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("before", type=Path)
    ap.add_argument("after", type=Path)
    ap.add_argument(
        "--expect-no-value-change",
        action="store_true",
        help="exit 1 if any rankDerivedValue moved (use on label-only phases)",
    )
    ap.add_argument("--top", type=int, default=15, help="largest movers to list")
    args = ap.parse_args()

    for p in (args.before, args.after):
        if not p.exists():
            print(f"error: not found: {p}", file=sys.stderr)
            return 2

    b = json.loads(args.before.read_text(encoding="utf-8"))
    a = json.loads(args.after.read_text(encoding="utf-8"))

    if b.get("scrapeTimestamp") != a.get("scrapeTimestamp"):
        print(
            "WARNING: captures are from different input scrapes "
            f"({b.get('scrapeTimestamp')} vs {a.get('scrapeTimestamp')}) — "
            "differences below mix data churn with code change.",
            file=sys.stderr,
        )

    rb, ra = b.get("rows") or {}, a.get("rows") or {}
    added = sorted(set(ra) - set(rb))
    removed = sorted(set(rb) - set(ra))
    common = sorted(set(rb) & set(ra))

    print("=" * 68)
    print(f"BOARD DIFF  {args.before.name} -> {args.after.name}")
    print("=" * 68)
    for k in ("rows", "ranked", "priced", "picks", "idp"):
        ob, oa = (b.get("totals") or {}).get(k), (a.get("totals") or {}).get(k)
        flag = "" if ob == oa else "   <-- CHANGED"
        print(f"  {k:>8}: {ob} -> {oa}{flag}")
    if added:
        print(f"\n  rows ADDED   ({len(added)}): {', '.join(added[:8])}")
    if removed:
        print(f"  rows REMOVED ({len(removed)}): {', '.join(removed[:8])}")

    # ── value movement ────────────────────────────────────────────────
    moves, newly_priced, newly_unpriced = [], [], []
    for k in common:
        ov, nv = rb[k].get("rankDerivedValue"), ra[k].get("rankDerivedValue")
        if ov is None and nv is not None:
            newly_priced.append(k)
        elif ov is not None and nv is None:
            newly_unpriced.append(k)
        elif ov != nv and ov is not None and nv is not None:
            moves.append((k, ov, nv, _pct(nv, ov)))

    print(
        f"\n  VALUES: {len(moves)} moved, {len(newly_priced)} newly priced, "
        f"{len(newly_unpriced)} newly unpriced"
    )
    if moves:
        pcts = [abs(m[3]) for m in moves if m[3] is not None]
        q = _quantiles(pcts)
        if q:
            print(
                f"    |pct change|  p50={q['p50']:.1f}%  p90={q['p90']:.1f}%  max={q['max']:.1f}%"
            )
        for k, ov, nv, p in sorted(moves, key=lambda m: -abs(m[3] or 0))[: args.top]:
            print(f"    {k[:34]:<34} {ov:>7} -> {nv:>7}  ({p:+.1f}%)")
    if newly_unpriced:
        print(f"    newly UNPRICED: {', '.join(newly_unpriced[:10])}")

    # ── rank churn ────────────────────────────────────────────────────
    rank_moves = [
        (k, rb[k].get("canonicalConsensusRank"), ra[k].get("canonicalConsensusRank"))
        for k in common
        if rb[k].get("canonicalConsensusRank") != ra[k].get("canonicalConsensusRank")
    ]
    print(f"\n  RANKS: {len(rank_moves)} changed")

    # ── label flips ───────────────────────────────────────────────────
    print("\n  LABELS:")
    for f in _LABEL_FIELDS:
        flips = [k for k in common if rb[k].get(f) != ra[k].get(f)]
        if flips:
            print(
                f"    {f:<24} {len(flips):>5} flipped   e.g. "
                f"{flips[0][:22]}: {rb[flips[0]].get(f)} -> {ra[flips[0]].get(f)}"
            )

    # ── source coverage ───────────────────────────────────────────────
    src = [k for k in common if rb[k].get("_sourceKeys") != ra[k].get("_sourceKeys")]
    if src:
        print(f"\n  SOURCE COVERAGE: {len(src)} rows vote differently")

    if args.expect_no_value_change:
        bad = len(moves) + len(newly_priced) + len(newly_unpriced)
        print()
        if bad:
            print(f"ASSERTION FAILED: expected no value change, got {bad} rows moved.")
            return 1
        print("ASSERTION OK: no value changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
