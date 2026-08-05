#!/usr/bin/env bash
# W18 reproduction driver.  READ-ONLY.  Run from the repo root.
set -euo pipefail
cd "$(dirname "$0")/../../../.."
E=docs/master-site-audit/evidence/W18
SECRET=$(cat /tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/e2e_secret.txt)
curl -s -c /tmp/w18.txt -X POST http://127.0.0.1:8000/api/test/create-session -H "Authorization: Bearer $SECRET" >/dev/null

echo "── R1: host ground truth (already captured; re-fetch only to prove no drift)"
curl -s "https://api.sleeper.app/v1/league/1312006700437352448" | python3 -c "import json,sys;d=json.load(sys.stdin);print('scoring keys',len(d['scoring_settings']),'| roster slots',len(d['roster_positions']),'| teams',d['total_rosters'])"

echo "── R2: repo snapshot vs host (expect: zero behaviour-relevant drift)"
python3 - <<'EOF'
import json
s=json.load(open('config/league_intel/sleeper_league_snapshot_2026-07-26.json'))
l=json.load(open('docs/master-site-audit/evidence/W18/sleeper_league_1312006700437352448.json'))
d={k:(s['scoring_settings'].get(k),l['scoring_settings'].get(k)) for k in set(s['scoring_settings'])|set(l['scoring_settings']) if s['scoring_settings'].get(k)!=l['scoring_settings'].get(k)}
print("scoring drift:",d,"| roster_positions equal:",s['roster_positions']==l['roster_positions'])
EOF

echo "── R3: two leagues, one profile, identical board (W18-F001)"
for lk in dynasty_main dynasty_new; do
  curl -s -b /tmp/w18.txt "http://127.0.0.1:8000/api/data?view=app&leagueKey=$lk" -o "/tmp/w18_$lk.json"
done
python3 -c "
import json
a=json.load(open('/tmp/w18_dynasty_main.json'));b=json.load(open('/tmp/w18_dynasty_new.json'))
pa,pb=a['players'],b['players']
same=sum(1 for k in pa if k in pb and pa[k].get('rankDerivedValue')==pb[k].get('rankDerivedValue'))
print('identical rankDerivedValue rows:',same,'of',len(pa))
print('dynasty_new meta:',json.dumps(b['meta']))
print('dynasty_new sleeper: leagueId',b['sleeper']['leagueId'],'teams',len(b['sleeper']['teams']),
      '| num_teams',b['sleeper']['leagueSettings']['num_teams'],'| slots',len(b['sleeper']['rosterPositions']),
      '| rec',b['sleeper']['scoringSettings']['rec'],'| idp_sack',b['sleeper']['scoringSettings'].get('idp_sack'))
"
curl -s "https://api.sleeper.app/v1/league/1320092771247222784" | python3 -c "import json,sys;d=json.load(sys.stdin);print('TRUE dynasty_new: num_teams',d['settings']['num_teams'],'| slots',len(d['roster_positions']),'| rec',d['scoring_settings']['rec'],'| idp_sack',d['scoring_settings'].get('idp_sack'))"

echo "── R4: exact scorer vs host players_points (W18-F009)"
.venv/bin/python - <<'EOF'
import json
from src.league_intel.scorer import score_stat_line
E='docs/master-site-audit/evidence/W18/'
sc=json.load(open(E+'sleeper_league_2025_prev.json'))['scoring_settings']
n=0;worst=0.0
for w in (5,9,14):
    m=json.load(open(E+f'sleeper_matchups_2025_wk{w}.json'));st=json.load(open(E+f'sleeper_stats_2025_wk{w}.json'))
    for mm in m:
        for pid,pts in (mm.get('players_points') or {}).items():
            line=st.get(pid)
            if line is None: continue
            n+=1; worst=max(worst,abs(score_stat_line(line,sc).total_points-float(pts)))
print(f"player-weeks={n}  max|delta|={worst:.4f}  (tolerance 0.011)")
EOF

echo "── R5: realized_points vs the host's own scoring (W18-F003)"
.venv/bin/python - <<'EOF'
import json,statistics
from collections import defaultdict
from src.nfl_data import ingest as ing
from src.nfl_data.realized_points import compute_weekly_points
from src.league_intel.scorer import score_stat_line
E='docs/master-site-audit/evidence/W18/'
sc=json.load(open(E+'sleeper_league_1312006700437352448.json'))['scoring_settings']
slim=json.load(open(E+'sleeper_players_slim.json'))
g2s={v['gsis_id']:k for k,v in slim.items() if v.get('gsis_id')}
sl={w:json.load(open(E+f'sleeper_stats_2025_wk{w}.json')) for w in (5,9,14)}
res=defaultdict(list)
IDP={'DL','DE','DT','NT','EDGE','LB','ILB','OLB','MLB','DB','CB','S','FS','SS'}
for r in ing.fetch_weekly_stats([2025]):
    w=int(r.get('week') or 0)
    if w not in (5,9,14): continue
    sid=g2s.get(str(r.get('player_id') or ''))
    if not sid or not sl[w].get(sid): continue
    pos=(slim[sid].get('position') or '').upper()
    e=score_stat_line(sl[w][sid],sc).total_points
    rp=compute_weekly_points(r,sc,position=pos)
    if rp is None: continue
    g='IDP' if pos in IDP else (pos if pos in {'QB','RB','WR','TE','K'} else 'other')
    res[g].append(rp.fantasy_points-e)
for g in sorted(res,key=lambda g:-len(res[g])):
    v=res[g];ok=sum(1 for x in v if abs(x)<=0.011)
    print(f"  {g:<6} n={len(v):<4} agree={ok:<4} ({100*ok/len(v):5.1f}%)  meanSigned={statistics.mean(v):+7.3f}")
EOF

echo "── R6: /api/player/{id}/realized is dead in both directions (W18-F004)"
curl -s -b /tmp/w18.txt "http://127.0.0.1:8000/api/player/5849/realized"; echo
curl -s -o /dev/null -w "Next bridge route :3000 -> HTTP %{http_code}\n" "http://127.0.0.1:3000/api/player/5849/realized"
