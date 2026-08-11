#!/usr/bin/env python3
"""Board impact of removing the value-coercing corridor.

Step 6/7 of the final pass. Compares production (corridor on) against the
candidate (no value coercion) on the current board and on all 17
validated historical days, reporting the full distribution rather than a
reassuring adjective.

``--current``     current board.
``--historical``  all 17 replayed days.
``--tail903``     repeat experimentally under the B4 tail.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent

_spec = importlib.util.spec_from_file_location("cd_replay", OUT / "cd_historical_replay.py")
R = importlib.util.module_from_spec(_spec)
sys.modules["cd_replay"] = R
_spec.loader.exec_module(R)

BUCKETS = (
    ("QB", {"QB"}),
    ("RB", {"RB"}),
    ("WR", {"WR"}),
    ("TE", {"TE"}),
    ("DL/EDGE", {"DL", "EDGE", "DE", "DT"}),
    ("LB", {"LB"}),
    ("DB", {"DB", "CB", "S"}),
)


def bucket(pos: str, ac: str) -> str:
    if ac == "pick":
        return "picks"
    p = (pos or "").upper()
    for n, m in BUCKETS:
        if p in m:
            return n
    return "other"


def build_current(corridor: bool):
    from src.api.data_contract import build_api_data_contract

    board = sorted((ROOT / "exports/latest").glob("dynasty_data_*.json"), reverse=True)[0]
    raw = json.loads(board.read_bytes())
    with contextlib.redirect_stdout(io.StringIO()):
        return build_api_data_contract(raw, suppress_market_corridor_clamp=not corridor)


def compare(on, off) -> dict:
    a = {str(r.get("displayName")): r for r in (on.get("playersArray") or [])}
    b = {str(r.get("displayName")): r for r in (off.get("playersArray") or [])}
    names = sorted(set(a) & set(b))

    deltas, rank_moves = {}, {}
    for nm in names:
        va, vb = a[nm].get("rankDerivedValue"), b[nm].get("rankDerivedValue")
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and va != vb:
            deltas[nm] = vb - va
        ra, rb = a[nm].get("canonicalConsensusRank"), b[nm].get("canonicalConsensusRank")
        if isinstance(ra, int) and isinstance(rb, int) and ra != rb:
            rank_moves[nm] = rb - ra

    absd = sorted(abs(v) for v in deltas.values())
    relf = sorted(
        abs(deltas[nm]) / a[nm]["rankDerivedValue"]
        for nm in deltas
        if a[nm].get("rankDerivedValue")
    )

    def topn(idx, n):
        rk = [
            (r["canonicalConsensusRank"], nm)
            for nm, r in idx.items()
            if isinstance(r.get("canonicalConsensusRank"), int)
        ]
        return {nm for _, nm in sorted(rk)[:n]}

    def idp_topn(idx, n):
        rk = [
            (r["canonicalConsensusRank"], nm)
            for nm, r in idx.items()
            if isinstance(r.get("canonicalConsensusRank"), int)
            and str(r.get("assetClass") or "") == "idp"
        ]
        return {nm for _, nm in sorted(rk)[:n]}

    bybucket = Counter()
    for nm in deltas:
        bybucket[bucket(str(a[nm].get("position") or ""), str(a[nm].get("assetClass") or ""))] += 1

    clamped_now = [
        nm
        for nm, r in a.items()
        if isinstance(r.get("marketCorridorClamp"), dict)
        and r["marketCorridorClamp"].get("applied")
    ]
    srccounts = Counter(
        len(
            [
                1
                for m in (a[nm].get("sourceRankMeta") or {}).values()
                if isinstance(m, dict) and float(m.get("valueContribution") or 0) > 0
            ]
        )
        for nm in deltas
    )
    conf = Counter(str(a[nm].get("confidenceBucket")) for nm in deltas)

    movers = sorted(deltas, key=lambda n: -abs(deltas[n]))[:15]
    return {
        "rowsCompared": len(names),
        "clampedInProduction": len(clamped_now),
        "valuesChanged": len(deltas),
        "meanAbsChange": round(sum(absd) / len(absd), 1) if absd else 0,
        "medianAbsChange": absd[len(absd) // 2] if absd else 0,
        "p90AbsChange": absd[int(0.9 * (len(absd) - 1))] if absd else 0,
        "maxAbsChange": absd[-1] if absd else 0,
        "medianRelChangePct": round(100 * relf[len(relf) // 2], 2) if relf else 0,
        "p90RelChangePct": round(100 * relf[int(0.9 * (len(relf) - 1))], 2) if relf else 0,
        "maxRelChangePct": round(100 * relf[-1], 2) if relf else 0,
        "ranksChanged": len(rank_moves),
        "meanRankMove": round(sum(abs(v) for v in rank_moves.values()) / len(rank_moves), 2)
        if rank_moves
        else 0,
        "maxRankMove": max((abs(v) for v in rank_moves.values()), default=0),
        "top50Changed": len(topn(a, 50) ^ topn(b, 50)),
        "top100Changed": len(topn(a, 100) ^ topn(b, 100)),
        "top200Changed": len(topn(a, 200) ^ topn(b, 200)),
        "idpTop50Changed": len(idp_topn(a, 50) ^ idp_topn(b, 50)),
        "idpTop100Changed": len(idp_topn(a, 100) ^ idp_topn(b, 100)),
        "idpTop200Changed": len(idp_topn(a, 200) ^ idp_topn(b, 200)),
        "byBucket": dict(bybucket),
        "bySourceCount": dict(sorted(srccounts.items())),
        "byConfidence": dict(conf),
        "offenseAffected": bybucket["QB"] + bybucket["RB"] + bybucket["WR"] + bybucket["TE"],
        "picksAffected": bybucket["picks"],
        "largestMovers": [
            {
                "name": nm,
                "position": a[nm].get("position"),
                "production": a[nm].get("rankDerivedValue"),
                "noCorridor": b[nm].get("rankDerivedValue"),
                "delta": deltas[nm],
                "rank": a[nm].get("canonicalConsensusRank"),
                "sources": len(
                    [
                        1
                        for m in (a[nm].get("sourceRankMeta") or {}).values()
                        if isinstance(m, dict) and float(m.get("valueContribution") or 0) > 0
                    ]
                ),
            }
            for nm in movers
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", action="store_true")
    ap.add_argument("--historical", action="store_true")
    ap.add_argument("--tail903", action="store_true")
    args = ap.parse_args()

    from src.canonical import tail_policy

    prev = tail_policy.TAIL_SATURATION_RANK
    if args.tail903:
        tail_policy.TAIL_SATURATION_RANK = 903
    out: dict = {"tail": tail_policy.TAIL_SATURATION_RANK}
    try:
        if args.current:
            print(
                f"== CURRENT BOARD: production vs no-corridor (tail={tail_policy.TAIL_SATURATION_RANK}) =="
            )
            m = compare(build_current(True), build_current(False))
            out["current"] = m
            for k in (
                "rowsCompared",
                "clampedInProduction",
                "valuesChanged",
                "meanAbsChange",
                "medianAbsChange",
                "p90AbsChange",
                "maxAbsChange",
                "medianRelChangePct",
                "p90RelChangePct",
                "maxRelChangePct",
                "ranksChanged",
                "meanRankMove",
                "maxRankMove",
                "top50Changed",
                "top100Changed",
                "top200Changed",
                "idpTop50Changed",
                "idpTop100Changed",
                "idpTop200Changed",
                "offenseAffected",
                "picksAffected",
            ):
                print(f"  {k:<24} {m[k]}")
            print(f"  byBucket        {m['byBucket']}")
            print(f"  bySourceCount   {m['bySourceCount']}")
            print(f"  byConfidence    {m['byConfidence']}")
            print("\n  largest movers (production -> no corridor):")
            for x in m["largestMovers"]:
                print(
                    f"    {x['name']:<24}{str(x['position']):<5}{x['production']:>6} ->"
                    f" {x['noCorridor']:>6}  ({x['delta']:+5})  rank {x['rank']}  src {x['sources']}"
                )

        if args.historical:
            mat = json.loads((OUT / "cd_historical_matrix.json").read_text())
            days = sorted(
                [r for r in mat["representativeDays"] if r["usable"] == "usable"],
                key=lambda r: r["day"],
            )
            print(f"\n== HISTORICAL: {len(days)} days, production vs no-corridor ==")
            print(
                f"  {'day':<12}{'clamped':>9}{'changed':>9}{'medAbs':>8}{'maxAbs':>8}{'maxRel%':>9}"
            )
            hist = []
            import src.api.data_contract as dc
            import tempfile

            for d in days:
                with tempfile.TemporaryDirectory(prefix="cd_rm_") as td:
                    dest = Path(td)
                    R.materialise(d, dest)
                    raw = json.loads(R.board_at(d["sha"])[1])
                    rp = R.Replay(d["sha"], d["timestamp"], dest)
                    sc, ss = dc._resolve_league_context, dc._RANK_SNAPSHOT_PATH
                    dc._resolve_league_context = lambda *a, **k: dict(R.PINNED_LEAGUE_CONTEXT)
                    dc._RANK_SNAPSHOT_PATH = dest / "data" / "snapshots" / "ranks_last.json"
                    try:
                        with rp.guard(), contextlib.redirect_stdout(io.StringIO()):
                            on = dc.build_api_data_contract(raw, csv_root=dest)
                            off = dc.build_api_data_contract(
                                raw, csv_root=dest, suppress_market_corridor_clamp=True
                            )
                    finally:
                        dc._resolve_league_context, dc._RANK_SNAPSHOT_PATH = sc, ss
                m = compare(on, off)
                m["day"] = d["day"]
                hist.append(m)
                print(
                    f"  {d['day']:<12}{m['clampedInProduction']:>9}{m['valuesChanged']:>9}"
                    f"{m['medianAbsChange']:>8}{m['maxAbsChange']:>8}{m['maxRelChangePct']:>9.2f}"
                )
            out["historical"] = hist
            tot = sum(m["valuesChanged"] for m in hist)
            print(f"\n  total values the corridor altered across 17 days: {tot}")
            print(f"  max single-value change seen: {max(m['maxAbsChange'] for m in hist)}")
            print(f"  offense rows ever affected:   {sum(m['offenseAffected'] for m in hist)}")
            print(f"  pick rows ever affected:      {sum(m['picksAffected'] for m in hist)}")
    finally:
        tail_policy.TAIL_SATURATION_RANK = prev

    name = "cd_removal_impact_tail903.json" if args.tail903 else "cd_removal_impact.json"
    (OUT / name).write_text(json.dumps(out, indent=1, default=str))
    print(f"\nwrote {OUT / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
