import json
import sys
import collections

sys.path.insert(0, "/home/user/riskittogetthebrisket")
from src.api.data_contract import _compute_identity_confidence

S = "/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad"
d = json.load(open(S + "/data_full.json"))
pa = d["playersArray"]
c = collections.Counter(r.get("identityConfidence") for r in pa)
print("identityConfidence distribution:", c.most_common())
bad = []
for r in pa:
    exp, _ = _compute_identity_confidence(r)
    got = r.get("identityConfidence")
    if got is None or abs(exp - got) > 1e-9:
        bad.append((r["displayName"], r.get("assetClass"), r.get("playerId"), exp, got))
print("mismatch", len(bad))
print(bad[:8])
# how many rows have a playerId
n_id = sum(1 for r in pa if (r.get("playerId") or "").strip())
print("rows with playerId", n_id, "/", len(pa))
# sourceSpread / hillValueSpread
ss = [r.get("sourceSpread") for r in pa if r.get("sourceSpread") is not None]
print("sourceSpread present", len(ss), "min", min(ss), "max", max(ss))
hv = [r.get("hillValueSpread") for r in pa if r.get("hillValueSpread") is not None]
print("hillValueSpread present", len(hv))
mp = collections.Counter(r.get("madPenaltyApplied") for r in pa)
print("madPenaltyApplied", mp.most_common(5))
q = collections.Counter(r.get("quarantined") for r in pa)
print("quarantined", q.most_common())
af = collections.Counter()
for r in pa:
    for f in r.get("anomalyFlags") or []:
        af[f] += 1
print("anomalyFlags counts", af.most_common())
print("contract anomalySummary", json.dumps(d.get("anomalySummary"))[:600])
print("validationSummary", json.dumps(d.get("validationSummary"))[:800])
