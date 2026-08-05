#!/usr/bin/env python3
"""W06 reproduction: find real players SPLIT across two live board rows.

Run:  .venv/bin/python docs/master-site-audit/evidence/W06/repro_duplicates.py

A "split identity" is one human occupying two rows in playersArray:
one row that resolved to a Sleeper id (the priced row) and one that did
not (a ghost). It is the INVERSE of the collision the contract's own
detector looks for, which is why validationSummary reports 0.

Two tiers:
  CONFIRMED  — ghost and real row agree on team AND age, or the ghost
               carries source values byte-identical to the real row's
               (same vendor row grafted onto both).
  REVIEW     — same surname, name similarity >= 0.78, and the ghost's
               only vendor votes are ones the real row is missing.
"""

from __future__ import annotations
import difflib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
HERE = REPO / "docs/master-site-audit/evidence/W06"
full = json.loads((HERE / "contract-full.json").read_text())
app = json.loads((HERE / "contract-app.json").read_text())["players"]

rows = [r for r in full["playersArray"] if r.get("assetClass") != "pick"]
ghosts = [r for r in rows if not r.get("playerId")]
real = [r for r in rows if r.get("playerId")]


def n(s):
    return "".join(c for c in s.lower() if c.isalnum() or c == " ")


def vals(r):
    return {k: v for k, v in (r.get("canonicalSiteValues") or {}).items() if v}


out = []
for g in ghosts:
    ga = app.get(g["displayName"], {})
    gv, gr = vals(g), set(g.get("sourceOriginalRanks") or {})
    for r in real:
        ra = app.get(r["displayName"], {})
        score = difflib.SequenceMatcher(None, n(g["displayName"]), n(r["displayName"])).ratio()
        if score < 0.78 or n(g["displayName"]).split()[-1] != n(r["displayName"]).split()[-1]:
            continue
        rv, rr = vals(r), set(r.get("sourceOriginalRanks") or {})
        shared_identical = [k for k in gv if k in rv and gv[k] == rv[k]]
        same_meta = ra.get("team") == ga.get("team") and ra.get("age") == ga.get("age")
        stranded = sorted(gr - rr)
        tier = None
        if same_meta or len(shared_identical) >= 2:
            tier = "CONFIRMED"
        elif stranded and not (gr & rr):
            tier = "REVIEW"
        if not tier:
            continue
        out.append(
            {
                "tier": tier,
                "ghostRow": g["displayName"],
                "realRow": r["displayName"],
                "nameSimilarity": round(score, 4),
                "ghostTeam": ga.get("team"),
                "ghostAge": ga.get("age"),
                "realTeam": ra.get("team"),
                "realAge": ra.get("age"),
                "realPlayerId": r.get("playerId"),
                "identicalSourceValuesOnBothRows": shared_identical,
                "realSourceCount": r.get("sourceCount"),
                "realRank": r.get("canonicalConsensusRank"),
                "realRankDerivedValue": r.get("rankDerivedValue"),
                "vendorVotesStrandedOnGhost": stranded,
                "ghostOriginalRanks": g.get("sourceOriginalRanks"),
            }
        )

print(json.dumps(out, indent=1))
print(
    f"\nSPLIT IDENTITIES: {sum(1 for x in out if x['tier']=='CONFIRMED')} confirmed, "
    f"{sum(1 for x in out if x['tier']=='REVIEW')} review"
)
vs = full["validationSummary"]
print(
    "contract validationSummary reports duplicateCanonicalIdentityCount =",
    vs["duplicateCanonicalIdentityCount"],
    "and nearNameMismatchCount =",
    vs["nearNameMismatchCount"],
)
