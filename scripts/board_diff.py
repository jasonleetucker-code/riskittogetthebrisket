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

    # decision surfaces (scripts/golden_surfaces.py captures)
    python scripts/board_diff.py BEFORE.json AFTER.json --surfaces

``--surfaces`` diffs a ``golden_surfaces.py`` capture instead of a
board capture: same ``{"rows": {...}}`` shape, different field names.
Deliberately a flag on this script rather than a second differ — two
implementations would be two definitions of "changed", and a phase
gate is only worth something when there is exactly one.

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

# ``scripts/golden_surfaces.py`` emits the same {"rows": {...}} shape for
# the decision surfaces the contract capture cannot see (trade verdict,
# FAAB bid, ROS ladder, news polarity).  Those rows carry different
# field names, so the value field and the label set are overridable
# rather than forked into a second differ — one diff implementation
# means one definition of "changed", which is the property that makes a
# phase gate mean anything.
_SURFACE_VALUE_FIELD = "value"
_SURFACE_LABEL_FIELDS = (
    "label",
    "meterLabel",
    "meterLevel",
    "meterFavours",
    "verdictFromGap",
    "impact",
    "severity",
    "recommendation",
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
    ap.add_argument(
        "--surfaces",
        action="store_true",
        help="diff a golden_surfaces.py capture (value field + label set differ)",
    )
    ap.add_argument(
        "--allow-input-change",
        action="store_true",
        help="compare captures built from different input exports (data churn WILL appear as movement)",
    )
    args = ap.parse_args()

    value_field = _SURFACE_VALUE_FIELD if args.surfaces else "rankDerivedValue"
    label_fields = _SURFACE_LABEL_FIELDS if args.surfaces else _LABEL_FIELDS

    for p in (args.before, args.after):
        if not p.exists():
            print(f"error: not found: {p}", file=sys.stderr)
            return 2

    b = json.loads(args.before.read_text(encoding="utf-8"))
    a = json.loads(args.after.read_text(encoding="utf-8"))

    # Two captures built from different inputs are not comparable: the
    # differences are data churn, code change, or both, and nothing in
    # the output distinguishes them.  This used to be a WARNING, which
    # is how the batch-C0 rebase nearly shipped a baseline whose input
    # had been swapped under it by a routine 2-hourly refresh — the
    # warning goes to stderr and reads like noise next to a diff that
    # looks plausible.  Refuse instead.
    if not args.surfaces:
        mismatched = []
        # A capture that never recorded its inputs cannot be shown
        # comparable, and "cannot verify" must not read the same as
        # "verified equal" — that is the audit's own central defect
        # class, and it bit here first: the stale baseline predated the
        # source-CSV hash, so the guard skipped it and the comparison
        # went through reporting 290 moved values as though the code
        # had moved them.
        for label, cap in (("before", b), ("after", a)):
            if not cap.get("inputSha256") or not cap.get("sourceCsvSha256"):
                mismatched.append(
                    f"the {label} capture does not record its inputs "
                    "(built by an older harness) — re-capture it"
                )
        sb, sa = b.get("inputSha256"), a.get("inputSha256")
        if sb and sa and sb != sa:
            mismatched.append(
                f"export {sb[:12]} vs {sa[:12]} "
                f"(scrapes {b.get('scrapeTimestamp')} vs {a.get('scrapeTimestamp')})"
            )
        # The SECOND input. build_api_data_contract reads the per-source
        # boards from CSVs/site_raw/ at build time, and the 2-hourly
        # refresh rewrites those tracked files — nine times in one day,
        # measured. Guarding only the export produced a diff reporting
        # 290 moved values against a main that had not touched the
        # pipeline at all.
        cb, ca = b.get("sourceCsvSha256"), a.get("sourceCsvSha256")
        if cb and ca and cb != ca:
            mismatched.append(
                f"source CSVs {cb[:12]} vs {ca[:12]} "
                f"({b.get('sourceCsvCount')} vs {a.get('sourceCsvCount')} files)"
            )
        if mismatched:
            print(
                "ERROR: captures were built from different inputs — "
                + "; ".join(mismatched)
                + ". Differences below are data churn, code change, or both, and "
                "nothing here separates them. Re-capture both on one tree state, "
                "or pass --allow-input-change if the change is the point.",
                file=sys.stderr,
            )
            if not args.allow_input_change:
                return 2

    rb, ra = b.get("rows") or {}, a.get("rows") or {}
    added = sorted(set(ra) - set(rb))
    removed = sorted(set(rb) - set(ra))
    common = sorted(set(rb) & set(ra))

    print("=" * 68)
    print(f"BOARD DIFF  {args.before.name} -> {args.after.name}")
    print("=" * 68)
    for k in ("rows",) if args.surfaces else ("rows", "ranked", "priced", "picks", "idp"):
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
        ov, nv = rb[k].get(value_field), ra[k].get(value_field)
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
    for f in label_fields:
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
