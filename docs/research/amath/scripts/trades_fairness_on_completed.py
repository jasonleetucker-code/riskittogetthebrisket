import zipfile
import glob
import csv
import io
import math
import random
import sys
import json
import datetime as dt

root = sys.argv[1]
fs = sorted(glob.glob(root + "/exports/archive/*.zip"))


def load(z, n):
    try:
        s = z.read(n).decode("utf-8")
    except KeyError:
        return None
    out = {}
    for r in csv.DictReader(io.StringIO(s)):
        nm = (r.get("name") or "").strip()
        if not nm or nm[:4].isdigit():
            continue  # skip picks
        try:
            v = float(r["value"])
        except Exception:  # noqa: BLE001 — exploratory diagnostic
            continue
        if v > 0:
            out[nm.lower()] = v
    return out


days = {}
for f in fs:
    d = f.split("_")[-2]
    z = zipfile.ZipFile(f)
    k = load(z, "site_raw/ktcSfTep.csv")
    i = load(z, "site_raw/idpTradeCalc.csv")
    if k and i:
        days[d] = (k, i)  # last archive of the day wins
dates = sorted(days)
D = [dt.date(int(x[:4]), int(x[4:6]), int(x[6:])) for x in dates]
# staleness: share of common players whose IDPTC value changed vs previous date
ch_i = ch_k = 0
tot = 0
for a, b in zip(dates, dates[1:]):
    ka, ia = days[a]
    kb, ib = days[b]
    com = set(ia) & set(ib) & set(ka) & set(kb)
    tot += 1
    ch_i += any(ia[p] != ib[p] for p in com)
    ch_k += any(ka[p] != kb[p] for p in com)
print(
    json.dumps(
        {
            "dates": len(dates),
            "first": dates[0],
            "last": dates[-1],
            "transitions": tot,
            "idptc_changed_transitions": ch_i,
            "ktc_changed_transitions": ch_k,
        }
    )
)
H = int(sys.argv[2]) if len(sys.argv) > 2 else 30
STEP = int(sys.argv[3]) if len(sys.argv) > 3 else 14
origins = []
t = 0
while t < len(D):
    origins.append(t)
    nxt = [j for j in range(t + 1, len(D)) if (D[j] - D[t]).days >= STEP]
    if not nxt:
        break
    t = nxt[0]
rows = []
for o in origins:
    tgt = [j for j in range(o + 1, len(D)) if (D[j] - D[o]).days >= H]
    if not tgt:
        continue
    j = tgt[0]
    k0, i0 = days[dates[o]]
    k1, _ = days[dates[j]]
    for p in set(k0) & set(i0) & set(k1):
        if k0[p] < 1500 or i0[p] < 1500:
            continue  # top-ish, avoid floor noise
        g = math.log(i0[p] / k0[p])
        y = math.log(k1[p] / k0[p])
        rows.append((p, dates[o], g, y))


def ols(rs):
    n = len(rs)
    mx = sum(r[2] for r in rs) / n
    my = sum(r[3] for r in rs) / n
    sxx = sum((r[2] - mx) ** 2 for r in rs)
    sxy = sum((r[2] - mx) * (r[3] - my) for r in rs)
    return sxy / sxx


b = ols(rows)
players = sorted({r[0] for r in rows})
byp = {}
for r in rows:
    byp.setdefault(r[0], []).append(r)
random.seed(20261101)
bs = []
for _ in range(2000):
    samp = []
    for _p in range(len(players)):
        samp += byp[players[random.randrange(len(players))]]
    bs.append(ols(samp))
bs.sort()
print(
    json.dumps(
        {
            "horizonDays": H,
            "originStepDays": STEP,
            "origins": len(set(r[1] for r in rows)),
            "n_obs": len(rows),
            "n_players": len(players),
            "slope_future_ktc_logchange_on_log_idptc_over_ktc": round(b, 4),
            "player_cluster_bootstrap_95ci": [round(bs[49], 4), round(bs[1949], 4)],
        }
    )
)
