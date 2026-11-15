#!/usr/bin/env python3
"""DISCOVER-1: decompose the DLF-restore IDP moves and test the mechanism.

usage: rc_decompose.py A.json B.json Bnf.json OUT.json

* A   = production (DLF IDP held), incumbent filter
* B   = DLF IDP restored, incumbent filter
* Bnf = DLF IDP restored, decision-bearing filter stood down on IDP rows
        (diagnostic only)

A -> Bnf is DLF's own vote; Bnf -> B is the filter's reaction to the 4th vote.
Numerical counterfactuals recompute the incumbent statistic (same K, floor,
min_n, <2-survivor guard) on each logged panel -- they are diagnostics, not
proposals.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

A, B, BNF = (json.loads(Path(p).read_text()) for p in sys.argv[1:4])
out_path = Path(sys.argv[4])
K, FLOOR, MIN_N = (A["constants"][k] for k in ("K", "MIN_THRESHOLD", "MIN_N"))
DLF = {"dlfIdp", "dlfRookieIdp"}


def med(xs):
    s = sorted(xs)
    n = len(s)
    return float(s[n // 2]) if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def hampel(pairs):
    """Exact re-implementation of _hampel_filter_per_player (for counterfactuals)."""
    if len(pairs) < MIN_N:
        return [], None
    vals = [v for _, v in pairs]
    m = med(vals)
    mad = med([abs(v - m) for v in vals])
    thr = max(K * mad, FLOOR)
    dropped = [s for s, v in pairs if abs(v - m) > thr]
    if len(pairs) - len(dropped) < 2:
        return [], (m, mad, thr)
    return dropped, (m, mad, thr)


def rows(d):
    return {r["name"]: r for r in d["rows"]}


def calls(d, caller="_compute_unified_rankings"):
    return {c["row"]: c for c in d["hampelCalls"] if c["caller"] == caller}


ra, rb, rn = rows(A), rows(B), rows(BNF)
cb = calls(B)
res: dict = {}

# 1. verify the re-implementation reproduces every logged decision on B
mismatch = 0
for c in B["hampelCalls"]:
    if c["caller"] != "_compute_unified_rankings":
        continue
    d, _ = hampel([(v["source"], v["value"]) for v in c["votes"]])
    if sorted(d) != sorted(c["dropped"]):
        mismatch += 1
res["reimplementationMismatchesOnB"] = mismatch

# 2. decomposition of every IDP row that moved
decomp = []
for n, r in rb.items():
    if r["cls"] != "idp" or n not in ra or n not in rn:
        continue
    a, nf, b = ra[n]["v"], rn[n]["v"], r["v"]
    if not (a and b and nf) or a == b:
        continue
    decomp.append(
        {
            "row": n,
            "pos": r["pos"],
            "A": a,
            "B_noFilter": nf,
            "B": b,
            "total": round((b - a) / a, 4),
            "dlfOwnVote": round((nf - a) / a, 4),
            "filterReaction": round((b - nf) / nf, 4),
            "droppedInB": (cb.get(n) or {}).get("dropped") or [],
        }
    )
res["idpRowsMoved"] = len(decomp)
own = sorted(abs(x["dlfOwnVote"]) for x in decomp)
res["dlfOwnVote_absRel"] = {
    "max": own[-1] if own else None,
    "p90": own[int(0.9 * (len(own) - 1))] if own else None,
    "median": own[len(own) // 2] if own else None,
}
res["filterReactionRows"] = sum(1 for x in decomp if x["droppedInB"])
res["movesGe30pct"] = sorted(
    [x for x in decomp if abs(x["total"]) >= 0.30], key=lambda x: -abs(x["total"])
)
res["movesGe10pct"] = sorted(
    [x for x in decomp if abs(x["total"]) >= 0.10], key=lambda x: -abs(x["total"])
)
res["movesGe10pctAllHaveFilterDrop"] = all(x["droppedInB"] for x in res["movesGe10pct"])

# 3. mechanism counterfactuals on each newly-dropped row of B
cfs = []
for n, c in sorted(cb.items()):
    if c.get("assetClass") != "idp" or not c["dropped"]:
        continue
    pairs = [(v["source"], v["value"]) for v in c["votes"]]
    vals = sorted(v for _, v in pairs)
    no_dlf = [(s, v) for s, v in pairs if s not in DLF]
    dlf_vals = [v for s, v in pairs if s in DLF]
    one_dlf = no_dlf + (
        [("dlf(family-one-obs)", sum(dlf_vals) / len(dlf_vals))] if dlf_vals else []
    )
    uniq: dict = {}
    for s, v in pairs:
        uniq.setdefault(round(v), s)
    dedup = [(s, float(v)) for v, s in uniq.items()]
    d0, _ = hampel(no_dlf)
    d1, st1 = hampel(one_dlf)
    d2, _ = hampel(dedup)
    d3_raw = [s for s, v in pairs if abs(v - c["median"]) > K * c["mad"]]  # floor removed
    # n=4 closed form: MAD = (g/2 + min(m-x1, x4-m)) / 2 -- the farther outer vote
    # never enters the scale.
    closed = None
    if len(vals) == 4:
        x1, x2, x3, x4 = vals
        m = (x2 + x3) / 2
        closed = ((x3 - x2) / 2 + min(m - x1, x4 - m)) / 2
    cfs.append(
        {
            "row": n,
            "n": c["n"],
            "dlfVotes": len(dlf_vals),
            "dropped": c["dropped"],
            "median": c["median"],
            "mad": round(c["mad"], 2),
            "madClosedFormN4": None if closed is None else round(closed, 2),
            "threshold": round(c["threshold"], 2),
            "floorBound": c["floorBound"],
            "droppedVoteRelDistanceFromMedian": [
                round(abs(v["value"] - c["median"]) / c["median"], 3)
                for v in c["votes"]
                if v["source"] in c["dropped"]
            ],
            "cf_withoutDlf_dropped": d0,
            "cf_withoutDlf_filterRuns": len(no_dlf) >= MIN_N,
            "cf_dlfFamilyAsOneObservation_dropped": d1,
            "cf_identicalValuesCountedOnce_dropped": d2,
            "cf_noFloor_wouldDrop": d3_raw,
        }
    )
res["mechanismCounterfactuals"] = cfs
others = [x for x in cfs]
res["mechanismSummary"] = {
    "rowsWithAnyDrop": len(cfs),
    "filterRunsWithoutDlf": sum(1 for x in cfs if x["cf_withoutDlf_filterRuns"]),
    "dropsSurviveWithoutDlf": sum(1 for x in cfs if x["cf_withoutDlf_dropped"]),
    "n4Rows": sum(1 for x in cfs if x["n"] == 4),
    "rowsWithTwoDlfVotes": sum(1 for x in cfs if x["dlfVotes"] >= 2),
    "dropsSurviveDlfAsOneObservation": sum(
        1 for x in cfs if x["cf_dlfFamilyAsOneObservation_dropped"]
    ),
    "dropsSurviveIdenticalValuesOnce": sum(
        1 for x in cfs if x["cf_identicalValuesCountedOnce_dropped"]
    ),
    "floorBound": sum(1 for x in cfs if x["floorBound"]),
    "closedFormMatchesAllN4": all(
        x["madClosedFormN4"] is None or abs(x["madClosedFormN4"] - x["mad"]) < 0.01 for x in cfs
    ),
    "droppedVoteRelDistance_median": med(
        [d for x in cfs for d in x["droppedVoteRelDistanceFromMedian"]]
    ),
}

# 4. the same statistic already runs on production IDP rows inside the B11
#    lost-evidence replay (voting + freshness-withheld panel).  It removes no
#    vote; it decides whether a withheld source counts as lost evidence.
rep = collections.Counter()
rep_rows = set()
for c in A["hampelCalls"]:
    if c["caller"] == "_compute_unified_rankings" or c.get("assetClass") != "idp":
        continue
    for s in c["dropped"]:
        rep[s] += 1
        rep_rows.add(c["row"])
res["productionLostEvidenceReplay_idp"] = {
    "rowsWhereReplayRejectsAVote": len(rep_rows),
    "replayRejectionsBySource": dict(rep),
    "note": "decides only B11 lost-evidence seats (confidence); no vote is removed",
}

out_path.write_text(json.dumps(res, indent=1, default=str))
print(
    json.dumps(
        {k: res[k] for k in res if k not in ("mechanismCounterfactuals", "movesGe10pct")},
        indent=1,
        default=str,
    )
)
