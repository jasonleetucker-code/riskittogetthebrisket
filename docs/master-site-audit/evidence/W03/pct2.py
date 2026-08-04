import json
import collections

S = "/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad"
d = json.load(open(S + "/data_full.json"))
pa = d["playersArray"]
pools = collections.Counter()
for r in pa:
    for k in r.get("sourceRanks") or {}:
        pools[k] += 1


def pspread(esr, meta, pools):
    if not esr or len(esr) < 2:
        return None
    pcts = []
    for k in esr:
        m = meta.get(k) or {}
        raw = m.get("rawRank") or m.get("effectiveRank") or esr[k]
        depth = pools.get(k) or m.get("depth") or 0
        if depth <= 0:
            continue
        pcts.append(max(0.0, min(1.0, float(raw) / float(depth))))
    if len(pcts) < 2:
        return None
    if len(pcts) >= 5:
        s = sorted(pcts)
        return s[-2] - s[1]
    return max(pcts) - min(pcts)


ok = 0
bad = 0
ex = []
for r in pa:
    if not r.get("canonicalConsensusRank"):
        continue
    got = r.get("sourceRankPercentileSpread")
    exp = pspread(r.get("effectiveSourceRanks") or {}, r.get("sourceRankMeta") or {}, pools)
    if exp is None and got is None:
        ok += 1
        continue
    if exp is None or got is None:
        bad += 1
        ex.append((r["displayName"], exp, got))
        continue
    if abs(round(exp, 4) - got) <= 0.0002:
        ok += 1
    else:
        bad += 1
        if len(ex) < 10:
            ex.append((r["displayName"], round(exp, 4), got))
print("percentileSpread reproduce ok", ok, "bad", bad)
for e in ex[:10]:
    print(" ", e)
