import json
import sys
import collections

sys.path.insert(0, "/home/user/riskittogetthebrisket")
from src.api.data_contract import _DELTA_PLAYER_FIELDS

S = "/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad"
full = json.load(open(S + "/full_noop.json"))
delta = json.load(open(S + "/delta_noop.json"))
fp = {r["displayName"]: r for r in full["playersArray"]}
dp = {r["id"]: r for r in delta["rankingsDelta"]["players"]}
print("full rows", len(fp), "delta rows", len(dp))
print("key sets equal:", set(fp) == set(dp))
missing_field = collections.Counter()
mismatch = collections.Counter()
ex = collections.defaultdict(list)
for k, dr in dp.items():
    fr = fp.get(k)
    if fr is None:
        continue
    for f in _DELTA_PLAYER_FIELDS:
        inf = f in fr
        ind = f in dr
        if inf and not ind:
            missing_field[f] += 1
            ex[f].append((k, "absent-in-delta"))
        elif ind and not inf:
            missing_field[f + "(extra)"] += 1
        elif inf and ind and fr[f] != dr[f]:
            mismatch[f] += 1
            if len(ex[f]) < 3:
                ex[f].append((k, fr[f], dr[f]))
print("\nFIELDS PRESENT IN FULL BUT ABSENT IN DELTA:", dict(missing_field))
print("\nFIELD VALUE MISMATCHES full vs delta:", dict(mismatch))
for f, v in ex.items():
    if f in mismatch:
        print(" ", f, v[:3])
# also compare full_noop vs GET /api/data (the base the client merges onto)
base = json.load(open(S + "/data_full.json"))
bp = {r["displayName"]: r for r in base["playersArray"]}
mm = collections.Counter()
ex2 = collections.defaultdict(list)
for k, br in bp.items():
    fr = fp.get(k)
    if fr is None:
        mm["MISSING_ROW"] += 1
        continue
    for f in _DELTA_PLAYER_FIELDS:
        if f in br and f in fr and br[f] != fr[f]:
            mm[f] += 1
            if len(ex2[f]) < 3:
                ex2[f].append((k, br[f], fr[f]))
print("\nGET /api/data vs POST overrides(view=full, empty overrides) mismatches:", dict(mm))
for f, v in ex2.items():
    print("  ", f, v[:2])
