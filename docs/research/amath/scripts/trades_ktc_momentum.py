import zipfile, glob, csv, io, math, random, sys, json, datetime as dt
root = sys.argv[1]; H = int(sys.argv[2])
fs = sorted(glob.glob(root + '/exports/archive/*.zip'))
def load(z, n):
    try: s = z.read(n).decode('utf-8')
    except KeyError: return None
    out = {}
    for r in csv.DictReader(io.StringIO(s)):
        nm = (r.get('name') or '').strip()
        if not nm or nm[:4].isdigit(): continue
        try: v = float(r['value'])
        except: continue
        if v > 0: out[nm.lower()] = v
    return out
days = {}
for f in fs:
    d = f.split('_')[-2]; k = load(zipfile.ZipFile(f), 'site_raw/ktcSfTep.csv')
    if k: days[d] = k
dates = sorted(days); D = [dt.date(int(x[:4]), int(x[4:6]), int(x[6:])) for x in dates]
def at(t, delta):
    c = [j for j in range(len(D)) if (D[j] - D[t]).days >= delta] if delta > 0 else [j for j in range(len(D)) if (D[t] - D[j]).days >= -delta]
    if not c: return None
    return c[0] if delta > 0 else c[-1]
rows = []
used = []
t = 0
while t < len(D):
    p = at(t, -H); f = at(t, H)
    if p is not None and f is not None:
        used.append(dates[t])
        a, b, c = days[dates[p]], days[dates[t]], days[dates[f]]
        for n in set(a) & set(b) & set(c):
            if b[n] < 1500: continue
            rows.append((n, math.log(b[n] / a[n]), math.log(c[n] / b[n])))
    nx = [j for j in range(t + 1, len(D)) if (D[j] - D[t]).days >= H]
    if not nx: break
    t = nx[0]
def ols(rs):
    n = len(rs); mx = sum(r[1] for r in rs) / n; my = sum(r[2] for r in rs) / n
    return sum((r[1] - mx) * (r[2] - my) for r in rs) / sum((r[1] - mx) ** 2 for r in rs)
byp = {}
for r in rows: byp.setdefault(r[0], []).append(r)
ps = sorted(byp); random.seed(7); bs = []
for _ in range(2000):
    s = []
    for _p in ps: s += byp[ps[random.randrange(len(ps))]]
    bs.append(ols(s))
bs.sort()
print(json.dumps({'source': 'ktcSfTep players value>=1500', 'horizonDays': H, 'nonOverlappingOrigins': used, 'n_obs': len(rows), 'n_players': len(ps), 'slope_future_on_past_logchange': round(ols(rows), 4), 'player_cluster_bootstrap_95ci': [round(bs[49], 4), round(bs[1949], 4)]}))
