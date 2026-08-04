# W20 evidence — roster intelligence, terminal, gameplan, team direction

## How to re-run the node harnesses

The `.mjs` scripts in this directory import the *unmodified* frontend libraries
from `lib/`, which are byte-copies of `frontend/lib/*.js` with only the `@/lib/`
path alias rewritten to a relative import (nothing else is changed). They read
`contract.json` from the working directory.

```bash
cd docs/master-site-audit/evidence/W20
SECRET=$(cat /tmp/claude-0/.../scratchpad/e2e_secret.txt)
curl -s -c /tmp/audit-cookies.txt -X POST http://127.0.0.1:8000/api/test/create-session -H "Authorization: Bearer $SECRET"
curl -s -b /tmp/audit-cookies.txt 'http://127.0.0.1:8000/api/data?view=app' -o contract.json
node tp.mjs        # W20-F008 — analyzeLeaguePhases on the live contract
node perturb.mjs   # W20-F009 — age vs value perturbation
node rosters2.mjs  # W20-F007 — three asset scopes for all 12 teams
node pickall.mjs   # W20-F005 — per-team A/B of the two client pick joins
node pickdiff.mjs  # W20-F005 — per-label breakdown for one team
node pf.mjs        # W20-F004 — server/local merge arithmetic (needs w20/term-<ownerId>.json)
```

`pf.mjs` also needs the terminal payload:
`curl -s -b /tmp/audit-cookies.txt 'http://127.0.0.1:8000/api/terminal?team=468418790212759552' -o w20/term-468418790212759552.json`

## Artifacts

| file | finding |
|---|---|
| `three-classifiers.txt` | W20-F006 — the four classifiers side by side on 12 teams |
| `window-grid.txt` | W20-F006 — reachability of window.py's five states over (competitiveness, trajectory) |
| `direction-reachability.txt` | W20-F016 — direction.py label reachability + dead inputs |
| `ros-trade-deadline.json` | W20-F002 — the live board with Brent at strength 100% labelled Seller |
| `gameplan-jason.json` | W20-F001/F010/F011/F012/F015 — a full /api/gameplan payload |
| `gameplan-windows-12teams.json` | W20-F006/F010 — window + values rollup for all 12 |
| `terminal-12teams-summary.json` | W20-F003/F014 — aggregates, insight cards, signal tags for all 12 |
| `rosters-scopes.txt` | W20-F007 — full / players / starters orderings |
| `perturb-teamphase.txt` | W20-F009 |
| `pick-join-divergence.txt` | W20-F005 |
| `pages-phases-rosters-tradedeadline.json` | W20-F002/F007/F008 — rendered page text via request interception |
