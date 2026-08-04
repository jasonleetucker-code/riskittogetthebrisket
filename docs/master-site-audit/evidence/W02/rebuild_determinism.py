import json
import hashlib
import sys
import copy
from pathlib import Path

sys.path.insert(0, "/home/user/riskittogetthebrisket")
SCRATCH = Path(
    "/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad"
)
from src.api import data_contract as dc  # noqa: E402 — import follows the sys.path insert above

# Redirect the rank snapshot so the audit never writes into data/
dc._RANK_SNAPSHOT_PATH = SCRATCH / "ranks_last_audit.json"

raw = json.load(open("/home/user/riskittogetthebrisket/data/dynasty_data_2026-08-04.json"))
print("raw players", len(raw.get("players") or {}))


def build():
    return dc.build_api_data_contract(copy.deepcopy(raw))


a = build()
b = build()


def norm(payload):
    p = copy.deepcopy(payload)
    # strip volatile fields
    for k in ("generatedAt", "dataFreshness", "scrapeTimestamp", "meta"):
        p.pop(k, None)
    return p


def h(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()


ha, hb = h(norm(a)), h(norm(b))
print("hash A", ha)
print("hash B", hb)
print("DETERMINISTIC:", ha == hb)

if ha != hb:
    # find diffs
    pa = {r["canonicalName"]: r for r in a["playersArray"]}
    pb = {r["canonicalName"]: r for r in b["playersArray"]}
    diffs = []
    for n, ra in pa.items():
        rb = pb.get(n)
        if rb is None:
            diffs.append((n, "missing", None, None))
            continue
        for k in ra:
            if json.dumps(ra[k], sort_keys=True, default=str) != json.dumps(
                rb.get(k), sort_keys=True, default=str
            ):
                diffs.append((n, k, ra[k], rb.get(k)))
    print("player-level diffs:", len(diffs))
    for d in diffs[:30]:
        print("  ", d)
    # top-level
    for k in norm(a):
        if h(norm(a)[k]) != h(norm(b).get(k)):
            print("TOPLEVEL DIFF", k)

json.dump(a, open(SCRATCH / "rebuild_a.json", "w"), default=str)
json.dump(b, open(SCRATCH / "rebuild_b.json", "w"), default=str)

# Compare against the LIVE served contract
live = json.load(open(SCRATCH / "data_full.json"))
la = {r["canonicalName"]: r.get("rankDerivedValue") for r in live["playersArray"]}
ra_ = {r["canonicalName"]: r.get("rankDerivedValue") for r in a["playersArray"]}
same = sum(1 for n in la if la[n] == ra_.get(n))
print(f"live vs in-process rankDerivedValue identical: {same}/{len(la)}")
mis = [(n, la[n], ra_.get(n)) for n in la if la[n] != ra_.get(n)]
for m in mis[:15]:
    print("   MISMATCH", m)
