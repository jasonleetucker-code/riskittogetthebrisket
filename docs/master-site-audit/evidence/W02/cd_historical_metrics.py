#!/usr/bin/env python3
"""Corridor candidates measured on GENUINELY INDEPENDENT historical boards.

Consumes the replay machinery in ``cd_historical_replay`` (current code +
historical inputs, leak-guarded) and, for every usable day, measures the
candidates that survived the synthetic battery.

``--measure``          production tail.
``--measure --tail903`` repeat with the B4 tail enabled experimentally.

What this replaces
------------------

The prior pass measured the hull invariant across 14 archived exports and
got 0 violations in 5,027 rows, then discovered the export bundle carries
2 of 21 voting-source CSVs — so those "historical boards" shared ~90% of
their inputs with today's. That evidence was withdrawn. These boards are
built from per-day historical CSVs recovered from git, so the inputs
really do differ; the replay log shows row counts moving 973-1095 and IDP
populations 276-359, which the contaminated test could not produce.

The fabricated ``HISTORICAL_BAND x 0.35`` reference is gone. The
reference distribution here is measured from real earlier days, and
threshold selection is done on a chronological TRAIN split and scored on a
later HOLDOUT split, so no threshold is chosen and evaluated on the same
board.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent

_spec = importlib.util.spec_from_file_location("cd_replay", OUT / "cd_historical_replay.py")
R = importlib.util.module_from_spec(_spec)
sys.modules["cd_replay"] = R
_spec.loader.exec_module(R)

TOLERANCES = (0.0, 0.005, 0.01, 0.02, 0.05, 0.10)


def _pct(sorted_vals, p):
    if not sorted_vals:
        return 0.0
    return float(sorted_vals[int(round((len(sorted_vals) - 1) * p))])


def day_metrics(contract: dict) -> dict:
    """Everything the pass asks for, on one historical board."""
    from src.api.data_contract import _market_anchor_for_row

    rows = [
        r
        for r in (contract.get("playersArray") or [])
        if r.get("canonicalConsensusRank") and str(r.get("assetClass") or "") != "offense"
    ]
    ranks = sorted(r["canonicalConsensusRank"] for r in rows)
    third = ranks[len(ranks) // 3] if ranks else 0

    # ── current corridor, as it actually fired ──
    clamped = [
        r
        for r in rows
        if isinstance(r.get("marketCorridorClamp"), dict)
        and r["marketCorridorClamp"].get("applied")
    ]
    buckets: dict[str, int] = {}
    anchors: dict[str, int] = {}
    lineage = 0
    effects = []
    for r in clamped:
        c = r["marketCorridorClamp"]
        buckets[str(c.get("confidenceBucket"))] = buckets.get(str(c.get("confidenceBucket")), 0) + 1
        src = str(c.get("marketSource"))
        anchors[src] = anchors.get(src, 0) + 1
        if src in (r.get("sourceRankMeta") or {}):
            lineage += 1
        o, n = c.get("originalValue"), c.get("clampedValue")
        if o:
            effects.append(abs(n - o) / o)
    effects.sort()
    bands = sorted({c["marketCorridorClamp"].get("bandPct") for c in clamped if c})

    # ── hull invariant, across tolerances ──
    hull: dict[str, dict] = {}
    for tol in TOLERANCES:
        viol, sparse, topthird, srccounts, vbuckets = [], 0, 0, [], {}
        for r in rows:
            cs = [
                float(m.get("valueContribution") or 0)
                for m in (r.get("sourceRankMeta") or {}).values()
                if isinstance(m, dict) and float(m.get("valueContribution") or 0) > 0
            ]
            v = float(r.get("rankDerivedValue") or 0)
            if v <= 0:
                continue
            if len(cs) < 2:
                sparse += 1
                continue
            lo, hi = min(cs), max(cs)
            if v > hi * (1 + tol) or v < lo * (1 - tol):
                viol.append(r)
                srccounts.append(len(cs))
                b = str(r.get("confidenceBucket"))
                vbuckets[b] = vbuckets.get(b, 0) + 1
                if r["canonicalConsensusRank"] <= third:
                    topthird += 1
        hull[f"{tol:.3f}"] = {
            "violations": len(viol),
            "ratePct": round(100.0 * len(viol) / len(rows), 3) if rows else 0.0,
            "topThird": topthird,
            "sourceCounts": sorted(srccounts)[:10],
            "byBucket": vbuckets,
            "sparseRowsSkipped": sparse,
        }

    # ── drift distribution, for the reference/change-point family ──
    drifts = []
    for r in rows:
        a, _ = _market_anchor_for_row(r)
        v = float(r.get("rankDerivedValue") or 0)
        if a and v > 0:
            drifts.append(abs(v - a) / a)
    drifts.sort()

    return {
        "idpRows": len(rows),
        "current": {
            "clamped": len(clamped),
            "triggerRatePct": round(100.0 * len(clamped) / len(rows), 2) if rows else 0.0,
            "byBucket": buckets,
            "anchors": anchors,
            "anchorAlsoVotes": lineage,
            "medianValueEffectPct": round(100.0 * effects[len(effects) // 2], 2)
            if effects
            else None,
            "maxValueEffectPct": round(100.0 * effects[-1], 2) if effects else None,
            "distinctBands": [round(b, 4) for b in bands if b is not None],
        },
        "hull": hull,
        "driftP50": round(_pct(drifts, 0.50), 4),
        "driftP90": round(_pct(drifts, 0.90), 4),
        "driftP99": round(_pct(drifts, 0.99), 4),
        "driftN": len(drifts),
    }


def source_change(days: list[dict]) -> list[dict]:
    """How much each source ACTUALLY changed between consecutive days.

    Requirement 6: independent source-state variation is what matters, not
    the number of git commits. Byte-identical CSVs across days would mean
    the extra days add no information.
    """
    out = []
    for prev, cur in zip(days, days[1:]):
        changed = [k for k, h in cur["csvHashes"].items() if prev["csvHashes"].get(k) != h]
        out.append(
            {
                "from": prev["day"],
                "to": cur["day"],
                "sourcesChanged": len(changed),
                "sourcesTotal": len(cur["csvHashes"]),
                "boardChanged": prev["boardSha256"] != cur["boardSha256"],
                "changed": sorted(changed),
            }
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--tail903", action="store_true")
    args = ap.parse_args()
    if not args.measure:
        ap.error("pass --measure")

    from src.canonical import tail_policy

    mat = json.loads((OUT / "cd_historical_matrix.json").read_text())
    usable = [r for r in mat["representativeDays"] if r["usable"] == "usable"]
    usable.sort(key=lambda r: r["day"])
    print(
        f"== usable historical days: {len(usable)}  ({usable[0]['day']} -> {usable[-1]['day']}) =="
    )

    print("\n== temporal independence: how much did the SOURCES actually change? ==")
    sc = source_change(usable)
    print(f"  {'transition':<26}{'sources changed':>17}{'board changed':>15}")
    for s in sc:
        print(
            f"  {s['from']} -> {s['to']:<12}{s['sourcesChanged']:>10} of {s['sourcesTotal']:<4}"
            f"{str(s['boardChanged']):>15}"
        )
    identical = [s for s in sc if s["sourcesChanged"] == 0]
    print(f"\n  transitions with ZERO source change: {len(identical)} of {len(sc)}")
    print("  (a day that changes nothing adds no independent information)")

    prev_tail = tail_policy.TAIL_SATURATION_RANK
    if args.tail903:
        tail_policy.TAIL_SATURATION_RANK = 903
        print(f"\n== B4 COUPLING: TAIL_SATURATION_RANK={tail_policy.TAIL_SATURATION_RANK} ==")
    try:
        per_day = []
        print(
            f"\n{'day':<12}{'idp':>5}{'clamp':>7}{'rate%':>7}{'hull@0':>8}{'hull@2%':>9}"
            f"{'driftP50':>10}{'driftP90':>10}"
        )
        for r in usable:
            c = R.replay_one(r)
            if c is None:
                print(f"  {r['day']}  LEAK — discarded")
                continue
            m = day_metrics(c)
            m["day"] = r["day"]
            m["sha"] = r["sha"]
            m["boardSha256"] = r["boardSha256"]
            m["csvHashes"] = r["csvHashes"]
            per_day.append(m)
            print(
                f"{r['day']:<12}{m['idpRows']:>5}{m['current']['clamped']:>7}"
                f"{m['current']['triggerRatePct']:>7.1f}"
                f"{m['hull']['0.000']['violations']:>8}"
                f"{m['hull']['0.020']['violations']:>9}"
                f"{m['driftP50']:>10.4f}{m['driftP90']:>10.4f}"
            )
    finally:
        tail_policy.TAIL_SATURATION_RANK = prev_tail

    # ── aggregate ──
    tot_rows = sum(m["idpRows"] for m in per_day)
    print(f"\n== aggregate over {len(per_day)} independent days, {tot_rows} IDP rows ==")
    print("\n-- current corridor --")
    rates = [m["current"]["triggerRatePct"] for m in per_day]
    print(
        f"  trigger rate  min {min(rates):.1f}%  median {statistics.median(rates):.1f}%  max {max(rates):.1f}%"
    )
    la = sum(m["current"]["anchorAlsoVotes"] for m in per_day)
    lc = sum(m["current"]["clamped"] for m in per_day)
    print(f"  anchor also votes on {la} of {lc} clamped rows ({100.0 * la / lc:.1f}%)")
    allanch: dict[str, int] = {}
    for m in per_day:
        for k, v in m["current"]["anchors"].items():
            allanch[k] = allanch.get(k, 0) + v
    print(f"  anchors used: {allanch}")

    print("\n-- hull invariant, false positives on REAL healthy boards --")
    print(f"  {'tolerance':<12}{'violations':>12}{'rows':>9}{'rate%':>9}")
    for tol in TOLERANCES:
        k = f"{tol:.3f}"
        v = sum(m["hull"][k]["violations"] for m in per_day)
        print(f"  {tol:<12.3%}{v:>12}{tot_rows:>9}{100.0 * v / tot_rows:>9.4f}")

    print("\n-- reference/change-point family, TRAIN -> HOLDOUT (no reuse) --")
    split = len(per_day) // 2
    train, hold = per_day[:split], per_day[split:]
    if train and hold:
        ref = statistics.median([m["driftP90"] for m in train])
        refmed = statistics.median([m["driftP50"] for m in train])
        print(f"  train  {train[0]['day']} -> {train[-1]['day']}  ({len(train)} days)")
        print(f"         reference P90 = {ref:.4f}   reference median drift = {refmed:.4f}")
        print(f"  holdout {hold[0]['day']} -> {hold[-1]['day']}  ({len(hold)} days)")
        print(f"  {'day':<12}{'P90':>9}{'vs ref':>9}{'median':>9}{'vs ref':>9}{'alarm':>8}")
        for m in hold:
            r90 = m["driftP90"] / ref if ref else 0
            r50 = m["driftP50"] / refmed if refmed else 0
            alarm = r50 > 1.5 or r50 < 0.667
            print(
                f"  {m['day']:<12}{m['driftP90']:>9.4f}{r90:>9.2f}"
                f"{m['driftP50']:>9.4f}{r50:>9.2f}{str(alarm):>8}"
            )
        print("  A change-point rail with a reference from REAL earlier days, not a")
        print("  fabricated constant. Alarms on the healthy holdout are false positives.")

    payload = {
        "codeSha": R._git("rev-parse", "HEAD").strip(),
        "tail": tail_policy.TAIL_SATURATION_RANK if not args.tail903 else 903,
        "usableDays": len(per_day),
        "totalIdpRows": tot_rows,
        "temporalIndependence": sc,
        "perDay": per_day,
    }
    name = "cd_historical_metrics_tail903.json" if args.tail903 else "cd_historical_metrics.json"
    (OUT / name).write_text(json.dumps(payload, indent=1, default=str))
    print(f"\nwrote {OUT / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
