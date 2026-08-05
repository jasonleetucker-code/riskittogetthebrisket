#!/usr/bin/env bash
# W29 — value architecture reproduction. Read-only. Run from repo root.
set -euo pipefail
SECRET=$(cat /tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/e2e_secret.txt)
OUT=${OUT:-/tmp/w29}
mkdir -p "$OUT"
curl -s -c "$OUT/cookies.txt" -X POST http://127.0.0.1:8000/api/test/create-session -H "Authorization: Bearer $SECRET" >/dev/null
curl -s -b "$OUT/cookies.txt" "http://127.0.0.1:8000/api/data"                    -o "$OUT/contract.json"
curl -s -b "$OUT/cookies.txt" "http://127.0.0.1:8000/api/valuation/league-adjusted" -o "$OUT/overlay.json"
curl -s -b "$OUT/cookies.txt" "http://127.0.0.1:8000/api/ros/player-values"        -o "$OUT/ros.json"

.venv/bin/python - "$OUT" <<'PY'
import json,sys,csv,statistics
O=sys.argv[1]
c=json.load(open(f"{O}/contract.json")); ov=json.load(open(f"{O}/overlay.json")); ros=json.load(open(f"{O}/ros.json"))
pa=c["playersArray"]; fac=ov["factors"]
board={r["displayName"]:(r.get("rankDerivedValue"),r.get("offenseOnlyRankDerivedValue")) for r in pa}

print("== F001/F002: /api/trade/suggestions displayValue vs the board ==")
import subprocess
tot=m=0; la_tot=la_un=0; worst=None
for t in (c.get("sleeper") or {}).get("teams") or []:
    for mode in ("market","leagueAdjusted"):
        body=json.dumps({"roster":t["players"],"myTeam":t["name"],"valuation_mode":mode})
        r=json.loads(subprocess.run(["curl","-s","-b",f"{O}/cookies.txt","-X","POST",
            "http://127.0.0.1:8000/api/trade/suggestions","-H","Content-Type: application/json",
            "--data-binary",body],capture_output=True,text=True).stdout)
        for k in ("sellHigh","buyLow","consolidation","positionalUpgrades"):
            for s in (r.get(k) or []):
                for side in ("give","receive"):
                    for x in (s.get(side) or []):
                        dv=x.get("displayValue"); rdv,oo=board.get(x["name"],(None,None))
                        if dv is None: continue
                        if mode=="market":
                            tot+=1
                            if rdv is not None and dv!=rdv:
                                m+=1
                                d=(dv-rdv)/rdv*100
                                if worst is None or abs(d)>abs(worst[2]): worst=(x["name"],dv,d,rdv)
                        else:
                            la_tot+=1
                            f=fac.get(x["name"])
                            if oo is not None and dv==oo and rdv and f and int(round(rdv*f))!=dv: la_un+=1
print(f"  market mode : {m}/{tot} legs disagree with rankDerivedValue")
print(f"  worst       : {worst[0]} shown={worst[1]} board={worst[3]} ({worst[2]:+.2f}%)")
print(f"  adjusted    : {la_un}/{la_tot} legs still at the UNADJUSTED offense-only market value")

print("\n== F003: exports/latest/dynasty_full.csv vs the board ==")
rows=list(csv.DictReader(open("exports/latest/dynasty_full.csv")))
b={n:v[0] for n,v in board.items() if v[0]}
rr=[float(r["Composite"])/b[r["Player"]] for r in rows if r["Player"] in b]
print(f"  matched {len(rr)} | exact-equal {sum(1 for x in rr if abs(x-1)<1e-9)} | median ratio {statistics.median(rr):.4f}")

print("\n== F005: 'Seller cash-out' scale mix (dynastyValue < rosValue*0.7) ==")
rv=[p["rosValue"] for p in ros["players"] if p.get("rosValue")]
bv=[v for v in b.values()]
print(f"  max(rosValue*0.7)={max(rv)*0.7:.1f}  min(rankDerivedValue)={min(bv)}  rows able to fire: {sum(1 for v in bv if v<max(rv)*0.7)}")

print("\n== F006: PRIOR-A01-F00 retest ==")
n=sum(1 for r in pa if (r.get("values") or {}).get("displayValue") is None
      and ((r.get("values") or {}).get("overall") is not None or (r.get("values") or {}).get("finalAdjusted") is not None))
print(f"  rows with values.displayValue null but overall/finalAdjusted set: {n} (prior claimed 260)")
PY
