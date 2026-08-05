# W27 reproduction commands

Every command below was run against the live stack described in
`docs/master-site-audit/AUDIT_PROTOCOL.md` (backend `127.0.0.1:8000`,
Next `127.0.0.1:3000`, HEAD `e96c06ef`).  Mint the cookie first:

```bash
SECRET=$(cat /tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/e2e_secret.txt)
curl -s -c /tmp/audit-cookies.txt -X POST http://127.0.0.1:8000/api/test/create-session \
  -H "Authorization: Bearer $SECRET"
curl -s -b /tmp/audit-cookies.txt "http://127.0.0.1:8000/api/data" -o /tmp/w27-contract.json
```

| id | what | command |
|---|---|---|
| W27-R1 | board IDP census | `python -c "import json,collections;d=json.load(open('/tmp/w27-contract.json'));print(collections.Counter(r['position'] for r in d['playersArray']))"` |
| W27-R2 | page render census | `python <scratch>/w27_page_probe.py docs/master-site-audit/evidence/W27/page-idp-probe.json` (Playwright + `/api/*` request interception per AUDIT_PROTOCOL) |
| W27-R3 | edge filter | read `frontend/lib/player-filters.js:176-185` against the `marketGapDirection` census in W27-R20 |
| W27-R4 | /edge DOM | `python <scratch>/w27_edge_probe.py docs/master-site-audit/evidence/W27/edge-rankings-dom.json docs/master-site-audit/evidence/W27/edge-page.png` |
| W27-R5 | trade suggestions, all 12 teams | see `trade-suggestions-12-teams.json`; body = `{"roster": <team.players>, "league_rosters": [...]}` POSTed to `/api/trade/suggestions` |
| W27-R6 | trade simulate w/ IDP | `curl -s -b /tmp/audit-cookies.txt -X POST http://127.0.0.1:8000/api/trade/simulate -H 'Content-Type: application/json' -d '{"teamName":"Jason","playersIn":["Micah Parsons"],"playersOut":["Chris Olave"]}'` |
| W27-R7 | arbitrage finder | `curl -s -b /tmp/audit-cookies.txt -X POST http://127.0.0.1:8000/api/trade/finder -H 'Content-Type: application/json' -d '{"myTeam":"Jason","opponentTeams":["all"]}'` |
| W27-R8 | angle 1-for-1 on an IDP | `curl -s -b /tmp/audit-cookies.txt -X POST http://127.0.0.1:8000/api/angle/find -H 'Content-Type: application/json' -d '{"ownerId":"468418790212759552","playerName":"Carson Schwesinger","limit":200,"minMyGainPct":0,"maxMarketGainPct":100}'` |
| W27-R9 | angle packages ± includeIdp | `curl ... /api/angle/packages -d '{"ownerId":"468418790212759552","playerNames":["Justin Jefferson"],"limit":50,"includeIdp":false}'` then `true` |
| W27-R10 | waivers | `curl -s -b /tmp/audit-cookies.txt -X POST http://127.0.0.1:8000/api/waiver/suggestions -H 'Content-Type: application/json' -d '{"myTeam":"Jason"}'` |
| W27-R11 | ROS player values | `curl -s -b /tmp/audit-cookies.txt "http://127.0.0.1:8000/api/ros/player-values"` |
| W27-R12 | ROS team strength / hybrid slotting | `curl -s -b /tmp/audit-cookies.txt "http://127.0.0.1:8000/api/ros/team-strength"` |
| W27-R13 | phases top-25 | recompute `frontend/lib/team-phase.js::teamSnapshot` over `sleeper.teams` × `rankDerivedValue` |
| W27-R14 | draft rookie board | `curl -s -b /tmp/audit-cookies.txt "http://127.0.0.1:8000/api/draft-capital"` |
| W27-R15 | terminal | `curl -s -b /tmp/audit-cookies.txt "http://127.0.0.1:8000/api/terminal?team=Jason"` |
| W27-R16 | movers | `curl -s -b /tmp/audit-cookies.txt "http://127.0.0.1:8000/api/movers"` |
| W27-R17 | sharp roster % | `curl -s -b /tmp/audit-cookies.txt "http://127.0.0.1:8000/api/sharp/roster-percentage"` |
| W27-R18 | sharp market | `curl -s -b /tmp/audit-cookies.txt "http://127.0.0.1:8000/api/sharp/market"` |
| W27-R19 | BDVM | `curl -s -b /tmp/audit-cookies.txt "http://127.0.0.1:8000/api/bdvm/values"` |
| W27-R20 | marketGapDirection census by position | `python -c "import json,collections;d=json.load(open('/tmp/w27-contract.json'));c=collections.Counter((r['position'],r.get('marketGapDirection')) for r in d['playersArray']);print(sorted(c.items(),key=str))"` |
| W27-R21 | cross-market overlap re-measure | `.venv/bin/python docs/master-site-audit/evidence/W27/measure_cross_market.py /tmp/w27-contract.json` |
| W27-R22 | TE-premium exactly-once audit | `python -c "import json,collections;d=json.load(open('/tmp/w27-contract.json'));f=collections.Counter();[f.__setitem__((k,'boost' if m.get('tepBoostApplied') else ('native' if m.get('tepNativeCorrectionApplied') else 'NONE')),f[(k,'boost' if m.get('tepBoostApplied') else ('native' if m.get('tepNativeCorrectionApplied') else 'NONE'))]+1) for r in d['playersArray'] if r['position']=='TE' for k,m in (r.get('sourceRankMeta') or {}).items()];print(sorted(f.items()))"` |
| W27-R23 | rank-space retail-vs-consensus gap by position | `python -c "import json,statistics,collections;d=json.load(open('/tmp/w27-contract.json'));res=collections.defaultdict(list)"` — see `te-rank-gap.json` for the computed output |
| W27-R24 | DB depth per team vs the 'need DB' verdict | `python -c "import json,collections;d=json.load(open('/tmp/w27-contract.json'));p=d['sleeper']['positions'];[print(t['name'],collections.Counter(p.get(n) for n in t['players'])['DB']) for t in d['sleeper']['teams']]"` |
| W27-R25 | Sleeper hybrid census | `curl -s https://api.sleeper.app/v1/players/nfl` then intersect `fantasy_positions` with `contract.sleeper.idToPlayer` |
