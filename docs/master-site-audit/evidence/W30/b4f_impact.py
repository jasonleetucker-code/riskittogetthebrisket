#!/usr/bin/env python3
"""B4-FINAL — current-board impact, pick chains, and integrity check.

Steps 9, 10 and 11 on the fresh pin: production (``TAIL_SATURATION_RANK
= None``) versus the candidate bounded tail, on identical inputs.

The part that earns its keep is the **second-order attribution**. A row
can move without any of its own rank-Hill contributions changing, and
until #799 the stock explanation for that was the market corridor. The
corridor is gone, so every such row now needs a real mechanism. This
harness classifies each mover by comparing its own per-source
contributions under both policies, and anything it cannot attribute is
reported as ``unexplained`` rather than rounded off — an unexplained
second-order change is a stop condition, not a footnote.

Writes ``b4f_impact*.json``. Touches no prior evidence file.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent

POSITION_BUCKETS = (
    ("QB", {"QB"}),
    ("RB", {"RB"}),
    ("WR", {"WR"}),
    ("TE", {"TE"}),
    ("DL/EDGE", {"DL", "EDGE", "DE", "DT"}),
    ("LB", {"LB"}),
    ("DB", {"DB", "CB", "S"}),
)

CORRIDOR_SYMBOLS = (
    "_apply_market_corridor_clamp",
    "_market_anchor_for_row",
    "_market_anchor_value_for_row",
    "_MARKET_ANCHOR_BY_ASSET_CLASS",
    "_MARKET_ANCHOR_FALLBACKS",
    "_MARKET_CORRIDOR_",
)


def bucket_for(position: str, asset_class: str) -> str:
    if asset_class == "pick":
        return "picks"
    pos = (position or "").upper()
    for name, members in POSITION_BUCKETS:
        if pos in members:
            return name
    return "other"


def latest_board() -> Path:
    return sorted((ROOT / "exports" / "latest").glob("dynasty_data_*.json"), reverse=True)[0]


def build(raw: dict, tail: int | None):
    from src.api.data_contract import build_api_data_contract
    from src.canonical import tail_policy

    prev = tail_policy.TAIL_SATURATION_RANK
    tail_policy.TAIL_SATURATION_RANK = tail
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return build_api_data_contract(raw)
    finally:
        tail_policy.TAIL_SATURATION_RANK = prev


def contributions(row: dict) -> dict[str, tuple[float, str, float]]:
    """(valueContribution, path, effectiveRank) per source."""
    out = {}
    for k, m in (row.get("sourceRankMeta") or {}).items():
        if not isinstance(m, dict):
            continue
        c = m.get("valueContribution")
        if c is None:
            continue
        try:
            cf = float(c)
        except (TypeError, ValueError):
            continue
        eff = m.get("effectiveRank")
        out[str(k)] = (
            cf,
            str(m.get("valueContributionPath") or "unknown"),
            float(eff) if isinstance(eff, (int, float)) else -1.0,
        )
    return out


def quant(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    return xs[min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))]


def corridor_symbol_scan() -> dict:
    """Step 11: the corridor must be gone from EXECUTABLE code.

    Evidence and test files legitimately name the retired symbols — the
    tests exist precisely to pin their absence — so a repo-wide grep would
    report the mechanism as alive. Only ``src/`` and ``server.py`` count.
    """
    hits: dict[str, list[str]] = {}
    targets = [p for p in (ROOT / "src").rglob("*.py")] + [ROOT / "server.py"]
    for sym in CORRIDOR_SYMBOLS:
        found = []
        for p in targets:
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for i, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if sym in line and not stripped.startswith("#"):
                    found.append(f"{p.relative_to(ROOT)}:{i}")
        hits[sym] = found
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", type=int, default=904)
    args = ap.parse_args()

    board = latest_board()
    raw = json.loads(board.read_bytes())
    base = build(raw, None)
    cand = build(raw, args.candidate)

    a = {str(r.get("displayName")): r for r in (base.get("playersArray") or [])}
    b = {str(r.get("displayName")): r for r in (cand.get("playersArray") or [])}
    names = sorted(set(a) & set(b))

    print(f"== B4-FINAL steps 9-11: board impact at boundary {args.candidate} ==")
    print(f"   board {board.name}   rows compared {len(names)}")

    deltas, rank_moves = {}, {}
    for nm in names:
        va, vb = a[nm].get("rankDerivedValue"), b[nm].get("rankDerivedValue")
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and va != vb:
            deltas[nm] = vb - va
        ra, rb = a[nm].get("canonicalConsensusRank"), b[nm].get("canonicalConsensusRank")
        if isinstance(ra, int) and isinstance(rb, int) and ra != rb:
            rank_moves[nm] = rb - ra

    absd = sorted(abs(v) for v in deltas.values())
    rel = sorted(
        abs(deltas[nm]) / a[nm]["rankDerivedValue"]
        for nm in deltas
        if a[nm].get("rankDerivedValue")
    )
    moves = sorted(abs(v) for v in rank_moves.values())

    print("\n-- value movement --")
    print(f"   values changed          {len(deltas)}")
    print(f"   mean abs change         {sum(absd) / len(absd):.1f}" if absd else "   none")
    print(f"   median abs change       {quant(absd, 0.5):.0f}")
    print(f"   P90 abs change          {quant(absd, 0.9):.0f}")
    print(f"   max abs change          {absd[-1] if absd else 0:.0f}")
    print(f"   median relative change  {100 * quant(rel, 0.5):.2f}%")
    print(f"   P90 relative change     {100 * quant(rel, 0.9):.2f}%")
    print(f"   max relative change     {100 * (rel[-1] if rel else 0):.2f}%")

    print("\n-- rank movement --")
    print(f"   ranks changed           {len(rank_moves)}")
    print(f"   median movement         {quant(moves, 0.5):.0f}")
    print(f"   P10 movement            {quant(moves, 0.1):.0f}")
    print(f"   P90 movement            {quant(moves, 0.9):.0f}")
    print(f"   max movement            {moves[-1] if moves else 0:.0f}")

    def topn(idx, n):
        rk = [
            (r["canonicalConsensusRank"], nm)
            for nm, r in idx.items()
            if isinstance(r.get("canonicalConsensusRank"), int)
        ]
        return {nm for _, nm in sorted(rk)[:n]}

    def served(idx):
        return {nm for nm, r in idx.items() if r.get("canonicalConsensusRank") is not None}

    print("\n-- served membership --")
    member = {}
    for n in (50, 100, 200, 400):
        diff = topn(a, n) ^ topn(b, n)
        member[f"top{n}"] = len(diff)
        print(f"   top {n:<4} membership changed  {len(diff)}")
    sa, sb = served(a), served(b)
    member["servedCut"] = len(sa ^ sb)
    member["servedBefore"], member["servedAfter"] = len(sa), len(sb)
    print(f"   full served cut          {len(sa)} -> {len(sb)}  (churn {len(sa ^ sb)})")
    if sa ^ sb:
        print(f"     entered: {sorted(sb - sa)[:8]}")
        print(f"     left:    {sorted(sa - sb)[:8]}")

    print("\n-- position effects --")
    by_bucket = Counter()
    bucket_abs = defaultdict(list)
    for nm in deltas:
        bk = bucket_for(str(a[nm].get("position") or ""), str(a[nm].get("assetClass") or ""))
        by_bucket[bk] += 1
        bucket_abs[bk].append(abs(deltas[nm]))
    print(f"   {'bucket':<10}{'changed':>9}{'median |Δ|':>12}{'max |Δ|':>10}")
    for name in [x[0] for x in POSITION_BUCKETS] + ["picks", "other"]:
        if not by_bucket.get(name):
            continue
        xs = sorted(bucket_abs[name])
        print(f"   {name:<10}{by_bucket[name]:>9}{quant(xs, 0.5):>12.0f}{xs[-1]:>10.0f}")

    # ── second-order attribution ──
    print("\n-- attribution: did the row's OWN rank-Hill contributions change? --")
    direct, second_order, unexplained = [], [], []
    for nm in deltas:
        ca, cb = contributions(a[nm]), contributions(b[nm])
        own_changed = [
            k for k in set(ca) | set(cb) if ca.get(k, (None,))[0] != cb.get(k, (None,))[0]
        ]
        own_hill_changed = [k for k in own_changed if ca.get(k, (0, "", 0))[1] == "rank_hill"]
        rec = {
            "name": nm,
            "position": a[nm].get("position"),
            "assetClass": a[nm].get("assetClass"),
            "delta": deltas[nm],
            "before": a[nm].get("rankDerivedValue"),
            "after": b[nm].get("rankDerivedValue"),
            "rank": a[nm].get("canonicalConsensusRank"),
            "ownContributionsChanged": sorted(own_changed),
        }
        if own_hill_changed:
            direct.append(rec)
        elif own_changed:
            rec["mechanism"] = "own value-direct contribution moved"
            second_order.append(rec)
        else:
            unexplained.append(rec)

    # ── attribute the indirect movers to a DEMONSTRATED chain ──
    #
    # "It must be the pick tether" is an assertion. The tether reads the
    # merged (offense + IDP) rookie pool, so the chain is only real if the
    # rookies actually moved, moved the same way, and the affected picks
    # are confined to the tethered year. All three are checked here; a
    # pick that fails any of them stays unexplained.
    rookie_moves = [
        (nm, a[nm].get("assetClass"), deltas[nm]) for nm in deltas if a[nm].get("rookie")
    ]
    rookie_down = sum(1 for _, _, d in rookie_moves if d < 0)
    pick_recs = [r for r in unexplained if str(r["assetClass"] or "") == "pick"]
    pick_years = sorted({str(r["name"]).split()[0] for r in pick_recs})
    pick_down = sum(1 for r in pick_recs if r["delta"] < 0)
    chain_holds = (
        bool(rookie_moves)
        and len(pick_years) == 1
        and (rookie_down == len(rookie_moves)) == (pick_down == len(pick_recs))
    )
    if chain_holds:
        for r in pick_recs:
            r["mechanism"] = "rookie repricing -> merged rookie pool -> pick tether (Phase 5.2b)"
            second_order.append(r)
        unexplained = [r for r in unexplained if r not in pick_recs]

    print(f"   direct (own rank-Hill contribution moved)   {len(direct)}")
    print(f"   second-order with a DEMONSTRATED mechanism  {len(second_order)}")
    print(f"   UNEXPLAINED                                 {len(unexplained)}")

    print("\n   pick-tether chain, checked rather than assumed:")
    print(f"     rookies whose value moved      {len(rookie_moves)} ({rookie_down} down)")
    print(
        f"     of which IDP / offense         "
        f"{sum(1 for _, ac, _ in rookie_moves if str(ac) == 'idp')} / "
        f"{sum(1 for _, ac, _ in rookie_moves if str(ac) == 'offense')}"
    )
    print(f"     picks moved                    {len(pick_recs)} ({pick_down} down)")
    print(f"     pick years affected            {pick_years}  (tether is current-year only)")
    print(f"     chain holds                    {chain_holds}")

    if unexplained:
        print("\n   !! rows with NO attributed mechanism — this is a stop condition:")
        for rec in sorted(unexplained, key=lambda r: -abs(r["delta"]))[:10]:
            print(
                f"     {str(rec['name'])[:26]:<27}{str(rec['position']):<6}"
                f"{rec['before']:>6} -> {rec['after']:>6}  ({rec['delta']:+6})"
            )

    print("\n-- largest movers --")
    for rec in sorted((direct + second_order + unexplained), key=lambda r: -abs(r["delta"]))[:15]:
        print(
            f"   {str(rec['name'])[:26]:<27}{str(rec['position']):<6}"
            f"{rec['before']:>6} -> {rec['after']:>6}  ({rec['delta']:+6})  rank {rec['rank']}"
        )

    # ── step 10: picks ──
    print("\n-- step 10: pick impact --")
    picks = [
        r for r in (direct + second_order + unexplained) if str(r["assetClass"] or "") == "pick"
    ]
    if not picks:
        print("   no pick row changed value")
    else:
        print(f"   {'pick':<24}{'before':>8}{'after':>8}{'Δ':>8}  own contributions changed")
        for rec in sorted(picks, key=lambda r: -abs(r["delta"])):
            print(
                f"   {str(rec['name'])[:23]:<24}{rec['before']:>8}{rec['after']:>8}"
                f"{rec['delta']:>8}  {rec['ownContributionsChanged'] or 'none (indirect)'}"
            )

    # ── step 11: corridor gone + integrity silent ──
    print("\n-- step 11: corridor absence and blend integrity --")
    scan = corridor_symbol_scan()
    total_hits = sum(len(v) for v in scan.values())
    for sym, found in scan.items():
        print(f"   {sym:<36}{len(found)} executable reference(s)")
    print(f"   TOTAL executable corridor references: {total_hits}")

    from src.api.data_contract import validate_api_data_contract

    integ = {}
    for label, contract in (("tail=None", base), (f"tail={args.candidate}", cand)):
        rows = contract.get("playersArray") or []
        viol = [r for r in rows if isinstance(r.get("blendIntegrityViolation"), dict)]
        flags = [r for r in rows if "blend_integrity_violation" in (r.get("anomalyFlags") or [])]
        quar = [r for r in rows if r.get("quarantined")]
        rep = validate_api_data_contract(contract)
        integ[label] = {
            "violations": len(viol),
            "flagged": len(flags),
            "quarantined": len(quar),
            "contractStatus": rep["status"],
            "contractOk": rep["ok"],
            "blendErrors": [e for e in rep["errors"] if "blend" in e.lower()],
        }
        print(
            f"   {label:<14} violations={len(viol)} flags={len(flags)} "
            f"quarantined={len(quar)} contract={rep['status']} ok={rep['ok']}"
        )

    payload = {
        "boundary": args.candidate,
        "board": board.name,
        "rowsCompared": len(names),
        "valuesChanged": len(deltas),
        "meanAbsChange": round(sum(absd) / len(absd), 2) if absd else 0,
        "medianAbsChange": quant(absd, 0.5),
        "p90AbsChange": quant(absd, 0.9),
        "maxAbsChange": absd[-1] if absd else 0,
        "medianRelPct": round(100 * quant(rel, 0.5), 4),
        "p90RelPct": round(100 * quant(rel, 0.9), 4),
        "maxRelPct": round(100 * (rel[-1] if rel else 0), 4),
        "ranksChanged": len(rank_moves),
        "medianRankMove": quant(moves, 0.5),
        "p10RankMove": quant(moves, 0.1),
        "p90RankMove": quant(moves, 0.9),
        "maxRankMove": moves[-1] if moves else 0,
        "membership": member,
        "byBucket": dict(by_bucket),
        "attribution": {
            "direct": len(direct),
            "secondOrder": len(second_order),
            "unexplained": len(unexplained),
            "pickTetherChain": {
                "rookiesMoved": len(rookie_moves),
                "rookiesDown": rookie_down,
                "picksMoved": len(pick_recs),
                "picksDown": pick_down,
                "pickYears": pick_years,
                "chainHolds": chain_holds,
            },
        },
        "unexplainedRows": unexplained,
        "pickRows": picks,
        "corridorScan": {k: v for k, v in scan.items()},
        "integrity": integ,
        "largestMovers": sorted(
            (direct + second_order + unexplained), key=lambda r: -abs(r["delta"])
        )[:25],
    }
    name = f"b4f_impact_{args.candidate}.json"
    (OUT / name).write_text(json.dumps(payload, indent=1, default=str))
    print(f"\nwrote {OUT / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
