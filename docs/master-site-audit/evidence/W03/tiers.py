import json
import sys
import collections

sys.path.insert(0, "/home/user/riskittogetthebrisket")
from src.canonical.player_valuation import detect_tiers

S = "/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad"
d = json.load(open(S + "/data_full.json"))
pa = d["playersArray"]
ranked = [r for r in pa if r.get("canonicalConsensusRank")]
ranked.sort(key=lambda r: r["canonicalConsensusRank"])
# contiguity
ranks = [r["canonicalConsensusRank"] for r in ranked]
print("contiguous 1..N:", ranks == list(range(1, len(ranks) + 1)))
# monotone value?
vals = [r.get("rankDerivedValue") for r in ranked]
bad = [i for i in range(len(vals) - 1) if (vals[i] or 0) < (vals[i + 1] or 0)]
print("value inversions along rank order:", len(bad), bad[:10])
series = [-float(r.get("rankDerivedValue") or 0) for r in ranked]
ids = [str(r.get("canonicalName") or "") for r in ranked]
tids, gaps, scores, bounds = detect_tiers(series, ids)
got = [r.get("canonicalTierId") for r in ranked]
mism = [(i + 1, ids[i], got[i], tids[i]) for i in range(len(ranked)) if got[i] != tids[i]]
print("tier reproduce mismatches:", len(mism), mism[:10])
c = collections.Counter(got)
print("n tiers", len(c), "sizes (tier:count) first 15", sorted(c.items())[:15])
sizes = sorted(c.values())
print(
    "max tier size",
    max(sizes),
    "min",
    min(sizes),
    "singleton tiers",
    sum(1 for s in sizes if s == 1),
)
# where do boundaries fall
print("boundaries", bounds[:25] if hasattr(bounds, "__getitem__") else bounds)
