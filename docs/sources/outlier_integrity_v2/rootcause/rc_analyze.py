#!/usr/bin/env python3
"""DISCOVER-1 root cause: compare board A (production) and B (DLF IDP restored).

usage: rc_analyze.py A.json B.json OUT_PREFIX

Reads rc_build.py outputs.  Decision-bearing filter calls are the blend loop's
(caller == _compute_unified_rankings); the B11 lost-evidence replay calls are
reported separately (they seat lost evidence, they remove no vote).
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

A = json.loads(Path(sys.argv[1]).read_text())
B = json.loads(Path(sys.argv[2]).read_text())
prefix = Path(sys.argv[3])
DLF = {"dlfIdp", "dlfRookieIdp"}
FOCUS = ["Trevin Wallace", "Myles Garrett", "Aidan Hutchinson"]


def decision_calls(d):
    return {c["row"]: c for c in d["hampelCalls"] if c["caller"] == "_compute_unified_rankings"}


def rows(d):
    return {r["name"]: r for r in d["rows"]}


ca, cb = decision_calls(A), decision_calls(B)
ra, rb = rows(A), rows(B)


def drops(calls, cls=None):
    out = set()
    for name, c in calls.items():
        if cls and c.get("assetClass") != cls:
            continue
        for s in c["dropped"]:
            out.add((name, s))
    return out


res: dict = {
    "inputs": {
        "A": {
            k: A[k]
            for k in ("env", "payloadSha256", "scrapeTimestamp", "policyHoldsInForce", "constants")
        },
        "B": {
            k: B[k]
            for k in ("env", "payloadSha256", "scrapeTimestamp", "policyHoldsInForce", "constants")
        },
    }
}

# IDP rows reaching the filter
for tag, calls in (("A", ca), ("B", cb)):
    idp = [c for c in calls.values() if c.get("assetClass") == "idp"]
    res[f"idpRowsReachingFilter_{tag}"] = len(idp)
    res[f"offenseRowsReachingFilter_{tag}"] = sum(
        1 for c in calls.values() if c.get("assetClass") == "offense"
    )
    res[f"idpDrops_{tag}"] = sum(len(c["dropped"]) for c in idp)
    res[f"offenseDrops_{tag}"] = sum(
        len(c["dropped"]) for c in calls.values() if c.get("assetClass") == "offense"
    )


# IDP n distribution (voting pairs that would enter the filter) from row meta
def idp_vote_counts(d):
    cnt = collections.Counter()
    for r in d["rows"]:
        if r["cls"] != "idp":
            continue
        n = sum(
            1
            for s, m in r["meta"].items()
            if m.get("valueContribution") is not None and s not in set(r.get("fex") or [])
        )
        cnt[n] += 1
    return dict(sorted(cnt.items()))


res["idpVotersPerRow_A"] = idp_vote_counts(A)
res["idpVotersPerRow_B"] = idp_vote_counts(B)

newly = sorted(drops(cb, "idp") - drops(ca, "idp"))
newly_other = [(n, s) for n, s in newly if s not in DLF]
newly_dlf = [(n, s) for n, s in newly if s in DLF]
pos_of = {n: (cb[n].get("position")) for n, _ in newly}
res["newlyDroppedIdp"] = {
    "allNewDrops": len(newly),
    "dlfOwnVotesDropped": [{"row": n, "source": s} for n, s in newly_dlf],
    "otherSourceVotesDropped": len(newly_other),
    "rows": len({n for n, _ in newly_other}),
    "bySource": dict(collections.Counter(s for _, s in newly_other)),
    "byPosition": dict(collections.Counter(pos_of[n] for n, _ in newly_other)),
    "rowsWithTwoDrops": [
        n for n, k in collections.Counter(n for n, _ in newly_other).items() if k > 1
    ],
}
off_changed = sorted(drops(cb, "offense") ^ drops(ca, "offense"))
res["offenseDropSetChanged"] = off_changed


def vote_table(call, row):
    """Every vote with value, deviation and the filter's working."""
    t = []
    for v in sorted(call["votes"], key=lambda x: -x["value"]):
        t.append(
            {
                "source": v["source"],
                "value": round(v["value"], 1),
                "deviation": None if v["deviation"] is None else round(v["deviation"], 1),
                "outsideThreshold": v["deviation"] is not None
                and v["deviation"] > call["threshold"],
                "dropped": v["source"] in call["dropped"],
                "path": v.get("valueContributionPath"),
                "method": v.get("method"),
                "rawRank": v.get("rawRank"),
                "effectiveRank": v.get("effectiveRank"),
                "pool": v.get("rankCoordinatePool"),
                "anchor": v.get("anchor"),
                "weight": v.get("weight"),
            }
        )
    return t


def row_detail(name):
    out = {"row": name}
    for tag, calls, rr in (("A", ca, ra), ("B", cb, rb)):
        r = rr.get(name)
        c = calls.get(name)
        block = {
            "value": r and r["v"],
            "rank": r and r["rank"],
            "confidence": r and r["conf"],
            "droppedSources": r and r["drop"],
            "freshnessExcluded": r and r["fex"],
        }
        if c is None:
            # filter never ran: list the votes the blend used, from meta
            block["filterRan"] = False
            block["votes"] = (
                sorted(
                    [
                        {
                            "source": s,
                            "value": m.get("valueContribution"),
                            "path": m.get("valueContributionPath"),
                            "rawRank": m.get("rawRank"),
                            "effectiveRank": m.get("effectiveRank"),
                            "contributedToBlend": m.get("contributedToBlend"),
                        }
                        for s, m in (r["meta"] if r else {}).items()
                        if m.get("valueContribution") is not None
                    ],
                    key=lambda x: -(x["value"] or 0),
                )
                if r
                else []
            )
            block["n"] = sum(
                1 for v in block["votes"] if v["source"] not in set((r or {}).get("fex") or [])
            )
        else:
            block.update(
                filterRan=True,
                n=c["n"],
                median=c["median"],
                mad=c["mad"],
                kMad=round(c["kMad"], 2),
                threshold=c["threshold"],
                floorBound=c["floorBound"],
                dropped=c["dropped"],
                guardStoodDown=c.get("guardStoodDown"),
                votes=vote_table(c, r),
            )
        out[tag] = block
    va, vb = out["A"]["value"], out["B"]["value"]
    if va and vb:
        out["relChange"] = round((vb - va) / va, 4)
    return out


res["newlyDroppedDetail"] = [row_detail(n) for n in sorted({n for n, _ in newly_other})]
res["focus"] = [row_detail(n) for n in FOCUS]

# movers >= 30% on IDP rows
movers = []
for n, r in rb.items():
    if r["cls"] != "idp" or n not in ra:
        continue
    a, b = ra[n]["v"], r["v"]
    if a and b and abs(b - a) / a >= 0.30:
        movers.append(
            {
                "row": n,
                "pos": r["pos"],
                "A": a,
                "B": b,
                "rel": round((b - a) / a, 4),
                "droppedInB": cb.get(n, {}).get("dropped"),
            }
        )
res["idpMoversGe30pct"] = sorted(movers, key=lambda x: -abs(x["rel"]))

# mechanism census: on each newly dropped row, how tight is the cluster?
mech = []
for n in sorted({n for n, _ in newly_other}):
    c = cb[n]
    vals = sorted(v["value"] for v in c["votes"])
    # identical / near-identical synthetic values (rank-derived, within 1%)
    rank_votes = [v for v in c["votes"] if v.get("valueContributionPath") == "rank_hill"]
    ident = []
    for i, v in enumerate(rank_votes):
        for w in rank_votes[i + 1 :]:
            if abs(v["value"] - w["value"]) <= 0.01 * max(v["value"], w["value"]):
                ident.append((v["source"], w["source"], v["value"], w["value"]))
    mech.append(
        {
            "row": n,
            "n": c["n"],
            "median": c["median"],
            "mad": c["mad"],
            "kMad": round(c["kMad"], 1),
            "threshold": c["threshold"],
            "floorBound": c["floorBound"],
            "dlfVotes": [v["source"] for v in c["votes"] if v["source"] in DLF],
            "nearIdenticalRankDerivedPairs": ident,
            "dropped": c["dropped"],
            "valuesSorted": [round(x) for x in vals],
        }
    )
res["mechanismPerRow"] = mech
res["mechanismSummary"] = {
    "rows": len(mech),
    "floorBound": sum(1 for m in mech if m["floorBound"]),
    "n4": sum(1 for m in mech if m["n"] == 4),
    "n5plus": sum(1 for m in mech if m["n"] >= 5),
    "rowsWithNearIdenticalRankDerivedPair": sum(
        1 for m in mech if m["nearIdenticalRankDerivedPairs"]
    ),
    "rowsWithDlfInNearIdenticalPair": sum(
        1 for m in mech if any(set(p[:2]) & DLF for p in m["nearIdenticalRankDerivedPairs"])
    ),
}

# Counterfactual: with DLF's votes removed from B's panel, would the same
# filter (n<4 -> no filter) have dropped anything?  And with DLF present, what
# MAD would the panel have had without DLF?
cf = []
for n in sorted({n for n, _ in newly_other}):
    c = cb[n]
    others = [v["value"] for v in c["votes"] if v["source"] not in DLF]
    cf.append(
        {"row": n, "nWithoutDlf": len(others), "filterWouldRunWithoutDlf": len(others) >= c["minN"]}
    )
res["counterfactualWithoutDlf"] = cf

prefix.with_suffix(".json").write_text(json.dumps(res, indent=1, default=str))
print(
    json.dumps(
        {
            k: res[k]
            for k in (
                "idpRowsReachingFilter_A",
                "idpRowsReachingFilter_B",
                "idpDrops_A",
                "idpDrops_B",
                "offenseDrops_A",
                "offenseDrops_B",
                "idpVotersPerRow_A",
                "idpVotersPerRow_B",
                "newlyDroppedIdp",
                "mechanismSummary",
            )
        },
        indent=1,
    )
)
print("movers>=30%:")
for m in res["idpMoversGe30pct"]:
    print(" ", m)
print("offense drop set changed:", res["offenseDropSetChanged"])
