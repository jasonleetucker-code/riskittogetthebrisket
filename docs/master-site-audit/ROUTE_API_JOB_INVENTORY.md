# Route, API, Page and Job Inventory

Every backend route, every page and every scheduled job on this platform, with what
was measured about each. Three census tables plus a disposition section.

This document is an **inventory**, not a defect list. Where a surface works, it says so.
Where a surface could not be exercised in this container, it says that instead of
guessing. Findings are cited by id; numbers are cited by evidence file.

**Provenance.** Commit `ba9f348b`, branch `claude/fantasy-football-master-audit-umvex5`.
Backend on `:8000` (FastAPI, booted from `data/dynasty_data_2026-08-04.json`), pages on
`:3000` (Next.js 16.2.12 production build). Python `3.11.15` in this container; CI pins
3.12 — no claim below is version-sensitive.

| Census | Count | Source |
|---|---:|---|
| Backend route operations | 99 (100 with the auto-generated `HEAD /api/health`) | `evidence/openapi.json` |
| … probed live, anon + authenticated | 66 (65 GET + the auto `HEAD /api/health`) | `evidence/route-probe.json` |
| … not probed (POST/PUT, read-only protocol) | 34 | `evidence/route-probe.json` |
| Next bridge routes | 36 | `frontend/app/api/**/route.js` |
| Next pages probed in a real browser | 41 | `evidence/page-probe.json` |
| GitHub workflow files | 22 (13 with a `schedule:`, 14 cron expressions) | `.github/workflows/` |
| systemd timer units | 19 | `deploy/**/*.timer*` |
| `scripts/` Python entrypoints | 89 (93 files including `.sh/.R/.mjs/.ps1`) | `evidence/W23/schedule-map.csv` |

Two counts in the audit brief are corrected here from the files themselves: there are
**19** systemd timer units, not 20; and of the **22** workflow files only **13** carry a
`schedule:` — "the 22 GitHub workflows with crons" conflates the file count with the
scheduled count. Both corrected numbers are reproducible with the commands below.

Re-run the censuses:

```bash
curl -s localhost:8000/openapi.json | .venv/bin/python -c \
  "import json,sys; d=json.load(sys.stdin); print(sum(len(v) for v in d['paths'].values()))"
find frontend/app/api -name route.js | wc -l      # 36
ls .github/workflows/*.yml | wc -l                # 22
grep -l "cron:" .github/workflows/*.yml | wc -l   # 13
find deploy -name '*.timer*' | wc -l              # 19
ls scripts/*.py | wc -l                           # 89
```

---

## 1. Backend routes

99 operations. Columns:

- **Auth** — the gate the route declares (`public` / `session` / `admin`).
- **anon / auth** — HTTP status from an anonymous request and from a request carrying an
  `e2e-test-user` session cookie. `n/p` = not probed: POST and PUT routes were left alone
  under the audit's read-only rule, except the pure-computation ones exercised by W08–W11
  and W27 with real bodies.
- **ms / bytes** — the authenticated response, **single cold sample**. These are not
  steady-state latencies; see the note under the table.
- **Bridge** — a `frontend/app/api/**/route.js` proxy exists. Bridges are **dev-only**:
  `deploy/nginx/chaseupside-proxy.conf` sends `location /api/` to FastAPI in production, so
  no `/api/*` request ever reaches Next there.
- **Called by** — the page or component that fetches it, from a repo-wide grep of
  `frontend/app/**` and `frontend/components/**`.
- **Disposition** — W01's classification. `**DEAD**` = no caller outside the test suite.

| Method | Path | Auth | anon | auth | ms | bytes | Bridge | Called by | Disposition |
|---|---|---|---|---|---:|---:|:---:|---|---|
| POST | `/api/admin/guest-pass` | admin | n/p | n/p | n/p | n/p | — | settings, cmp/admin/GuestPassPanel | UI |
| POST | `/api/admin/guest-pass/{pass_id}/revoke` | admin | n/p | n/p | n/p | n/p | — | cmp/admin/GuestPassPanel | UI |
| GET | `/api/admin/guest-passes` | admin | 401 | 403 | 4 | 62 | — | settings, cmp/admin/GuestPassPanel | UI |
| POST | `/api/admin/nfl-data/flush` | admin | n/p | n/p | n/p | n/p | — | admin | UI |
| POST | `/api/admin/sessions/force-logout-all` | admin | n/p | n/p | n/p | n/p | — | admin | UI |
| POST | `/api/admin/signal-state/migrate` | admin | n/p | n/p | n/p | n/p | — | admin | UI |
| POST | `/api/angle/find` | session | n/p | n/p | n/p | n/p | yes | **nothing** | **DEAD** |
| POST | `/api/angle/packages` | session | n/p | n/p | n/p | n/p | yes | angle | UI |
| POST | `/api/auth/login` | public | n/p | n/p | n/p | n/p | — | login | UI |
| POST | `/api/auth/logout` | public | n/p | n/p | n/p | n/p | yes | cmp/useAuth | UI |
| GET | `/api/auth/status` | public | 200 | 200 | 3 | 154 | yes | cmp/useAuth | UI |
| GET | `/api/bdvm/roster` | session | 401 | 200 | 47994 | 310 | yes | bdvm, lib/bdvm | UI |
| POST | `/api/bdvm/trade-eval` | session | n/p | n/p | n/p | n/p | yes | cmp/BdvmTradePanel | UI |
| GET | `/api/bdvm/trades` | session | 401 | 200 | 5 | 309 | yes | bdvm, lib/bdvm | UI |
| GET | `/api/bdvm/values` | session | 401 | 200 | 6 | 792 | yes | bdvm, draft +2 | UI |
| GET | `/api/consensus-edge/health` | session | 401 | 503 | 5 | 279 | yes | **nothing** | **DEAD** |
| GET | `/api/consensus-edge/methodology` | session | 401 | 200 | 3 | 1,965 | yes | consensus-edge | UI |
| GET | `/api/consensus-edge/player/{player_key}` | session | 401 | 503 | 3 | 279 | — | **nothing** | **DEAD** |
| GET | `/api/consensus-edge/players` | session | 401 | 503 | 3 | 279 | yes | consensus-edge | UI |
| GET | `/api/consensus-edge/top` | session | 401 | 503 | 3 | 279 | yes | cmp/useConsensusEdge | UI |
| GET | `/api/custom-alerts` | session | 401 | 200 | 4 | 12 | — | cmp/CustomAlertsConfigurator | UI |
| PUT | `/api/custom-alerts` | session | n/p | n/p | n/p | n/p | — | cmp/CustomAlertsConfigurator | UI |
| POST | `/api/custom-alerts/run` | self-authed (bearer) | n/p | n/p | n/p | n/p | — | **nothing** | ops/cron |
| GET | `/api/data` | session | 401 | 200 | 574 | 11,953,535 | — | draft, league +2 | UI |
| GET | `/api/data/player-source-history` | session | 401 | 400 | 5 | 48 | — | cmp/PlayerRankHistoryChart | UI |
| GET | `/api/data/rank-history` | session | 401 | 200 | 4 | 24 | — | lib/signal-engine, lib/value-history | UI |
| GET | `/api/draft-capital` | public | 200 | 200 | 6 | 24,061 | yes | draft, league/sections/draft-capital +2 | UI |
| GET | `/api/dynasty-data` | session | 401 | 200 | 95 | 11,953,535 | yes | lib/dynasty-data, frontend/public/sw | UI |
| GET | `/api/gameplan` | session | 401 | 400 | 9 | 203 | — | **nothing** | **DEAD** |
| GET | `/api/health` | public | 200 | 200 | 5 | 2,259 | — | cmp/StaleDataBanner | UI |
| POST | `/api/intel/leads` | session | n/p | n/p | n/p | n/p | — | league/insider-trading, cmp/InsiderLeads | UI |
| GET | `/api/intel/member/{owner_id}` | session | 401 | 503 | 6 | 177 | — | **nothing** | **DEAD** |
| GET | `/api/intel/player` | session | 401 | 503 | 6 | 177 | — | league/insider-trading, cmp/PlayerPopup +1 | UI |
| POST | `/api/intel/refresh` | session | n/p | n/p | n/p | n/p | — | **nothing** | ops/cron |
| GET | `/api/intel/refresh/status` | session | 401 | 200 | 4 | 194 | — | **nothing** | ops/cron |
| GET | `/api/intel/summary` | session | 401 | 503 | 5 | 177 | — | league/insider-trading, lib/public-routes | UI |
| GET | `/api/intel/waiver-interest` | session | 401 | 503 | 6 | 177 | — | **nothing** | **DEAD** |
| GET | `/api/league-comparison` | session | 401 | 200 | 26577 | 48,464 | yes | league-comparison | UI |
| GET | `/api/league/articles` | session | 200 | 200 | 6 | 1,383 | yes | league/articles/[season]/[week], league/sections/articles | UI |
| POST | `/api/league/articles/generate` | session | n/p | n/p | n/p | n/p | — | **nothing** | ops/manual |
| GET | `/api/league/articles/{season}/{week}/{matchup_id}/{mode}` | session | 400 | 400 | 5 | 62 | yes | league/articles/[season]/[week]/[matchupId]/[mode] | UI (SSR) |
| GET | `/api/leagues` | public | 200 | 200 | 5 | 840 | — | cmp/LeagueSwitcher, cmp/useLeague +2 | UI |
| GET | `/api/metrics` | public | 200 | 200 | 3 | 309 | — | **nothing** | ops/monitor |
| GET | `/api/movers` | session | 401 | 200 | 9 | 106 | — | cmp/terminal/MoversPanel | UI |
| GET | `/api/news` | public | 200 | 200 | 10 | 46,473 | yes | league/player/[playerId], cmp/terminal/MarketTicker +2 | UI |
| GET | `/api/player/{sleeper_id}/realized` | session | 401 | 200 | 5362 | 85 | — | cmp/PlayerPopup | UI |
| GET | `/api/playerctx/player` | session | 401 | 400 | 4 | 55 | — | cmp/PlayerPopup | UI |
| GET | `/api/public/league` | public | 200 | 200 | 94 | 2,081,957 | yes | league/LeagueClient, league +2 | UI |
| GET | `/api/public/league/matchup/{season}/{week}/{matchup_id}` | public | 200 | 200 | 9 | 17,006 | yes | league/weekly/[season]/[week]/[matchup], lib/public-league-data | UI |
| GET | `/api/public/league/matchups` | public | 200 | 200 | 7 | 14,672 | — | sitemap | UI |
| GET | `/api/public/league/metrics` | public | 200 | 200 | 4 | 795 | — | **nothing** | ops/cron |
| GET | `/api/public/league/player/{player_id}` | public | 200 | 200 | 20 | 19,176 | yes | league/player/[playerId]/opengraph-image, league/player/[playerId] +1 | UI |
| GET | `/api/public/league/players` | public | 200 | 200 | 20 | 63,323 | — | sitemap | UI |
| GET | `/api/public/league/{section}` | public | 200 | 200 | 1569 | 15,229 | yes | league/franchise/[owner]/opengraph-image, league/franchise/[owner] +2 | UI |
| GET | `/api/public/league/{section}.csv` | public | 200 | 200 | 1515 | 192 | — | **nothing** | **DEAD** |
| GET | `/api/push/public-key` | self-authed (bearer) | 503 | 503 | 3 | 31 | — | lib/push-subscription | UI |
| POST | `/api/push/subscribe` | session | n/p | n/p | n/p | n/p | — | lib/push-subscription | UI |
| POST | `/api/push/unsubscribe` | session | n/p | n/p | n/p | n/p | — | lib/push-subscription | UI |
| POST | `/api/rankings/overrides` | session | n/p | n/p | n/p | n/p | yes | rankings, cmp/useDynastyData +2 | UI |
| GET | `/api/rankings/sources` | public | 200 | 200 | 3 | 7,709 | yes | **nothing** | **DEAD** |
| GET | `/api/ros/health` | session | 401 | 200 | 293 | 2,640 | — | tools/ros-data-health, lib/ros-data | UI |
| GET | `/api/ros/pick-projections` | session | 401 | 200 | 9 | 35,100 | yes | league/sections/_pick-projector | UI |
| GET | `/api/ros/player-values` | session | 401 | 200 | 35 | 289,483 | — | cmp/PlayerPopup, cmp/RosTradeFitPanel +2 | UI |
| POST | `/api/ros/refresh` | session | n/p | n/p | n/p | n/p | — | settings, tools/ros-data-health | UI |
| GET | `/api/ros/sources` | session | 401 | 200 | 4 | 2,069 | — | tools/ros-data-health, lib/ros-data | UI |
| GET | `/api/ros/status` | session | 401 | 200 | 4 | 1,368 | — | lib/ros-data | UI |
| GET | `/api/ros/team-strength` | session | 401 | 200 | 11 | 56,010 | — | league/sections/ros-team-strength, lib/ros-data | UI |
| GET | `/api/scaffold/identity` | session | 401 | 200 | 177 | 2,522,120 | — | **nothing** | **DEAD** |
| GET | `/api/scaffold/league` | session | 401 | 404 | 4 | 45 | — | **nothing** | **DEAD** |
| GET | `/api/scaffold/raw` | session | 401 | 200 | 153 | 2,767,269 | — | **nothing** | **DEAD** |
| GET | `/api/scaffold/report` | session | 401 | 404 | 4 | 36 | — | **nothing** | **DEAD** |
| GET | `/api/scaffold/status` | public | 200 | 200 | 64 | 756 | — | **nothing** | **DEAD** |
| GET | `/api/scaffold/validation` | session | 401 | 200 | 4 | 91 | — | **nothing** | **DEAD** |
| POST | `/api/scrape` | session | n/p | n/p | n/p | n/p | yes | cmp/admin/ServerStatusPanel | UI |
| GET | `/api/sharp/cohort` | session | 401 | 200 | 36 | 1,848 | yes | market/sharp-tracker, lib/nav-model | UI |
| GET | `/api/sharp/market` | session | 401 | 200 | 14 | 1,356 | yes | market/sharp-tracker | UI |
| GET | `/api/sharp/market/audit` | session | 401 | 400 | 4 | 54 | — | **nothing** | operator |
| GET | `/api/sharp/roster-percentage` | session | 401 | 200 | 25 | 2,163 | yes | market/sharp-roster-percentage, lib/nav-model | UI |
| GET | `/api/sharp/roster-percentage/audit` | session | 401 | 400 | 4 | 54 | yes | **nothing** | operator |
| POST | `/api/signal-alerts/run` | self-authed (bearer) | n/p | n/p | n/p | n/p | — | **nothing** | ops/cron |
| GET | `/api/sleeper/draft/picks` | session | 401 | 200 | 1525 | 155 | yes | cmp/useSleeperDraftSync | UI |
| GET | `/api/status` | public | 200 | 200 | 7 | 7,477 | yes | admin, tools/source-health +2 | UI |
| GET | `/api/terminal` | session | 401 | 200 | 27 | 18,845 | — | tools/trade-coverage, cmp/terminal/PortfolioSummary +2 | UI |
| POST | `/api/test-alert` | session | n/p | n/p | n/p | n/p | — | **nothing** | **DEAD** |
| POST | `/api/test/create-session` | self-authed (bearer) | n/p | n/p | n/p | n/p | — | **nothing** | ops/cron |
| POST | `/api/trade/export-ktc` | session | n/p | n/p | n/p | n/p | — | trade | UI |
| POST | `/api/trade/finder` | session | n/p | n/p | n/p | n/p | yes | arbitrage | UI |
| POST | `/api/trade/import-ktc` | session | n/p | n/p | n/p | n/p | yes | trade | UI |
| POST | `/api/trade/simulate` | session | n/p | n/p | n/p | n/p | — | cmp/useTradeSimulator, frontend/public/sw | UI |
| POST | `/api/trade/simulate-mc` | session | n/p | n/p | n/p | n/p | — | cmp/ui/MonteCarloButton | UI |
| POST | `/api/trade/suggestions` | session | n/p | n/p | n/p | n/p | yes | trade | UI |
| GET | `/api/uptime` | public | 200 | 200 | 3 | 167 | — | **nothing** | ops/cron |
| POST | `/api/user/signals/dismiss` | session | n/p | n/p | n/p | n/p | — | cmp/useUserState | UI |
| POST | `/api/user/signals/restore` | session | n/p | n/p | n/p | n/p | — | cmp/useUserState | UI |
| GET | `/api/user/state` | session | 401 | 200 | 4 | 39 | — | cmp/useLeague, cmp/useUserState | UI |
| PUT | `/api/user/state` | session | n/p | n/p | n/p | n/p | — | cmp/useLeague, cmp/useUserState | UI |
| GET | `/api/valuation/league-adjusted` | session | 401 | 200 | 7267 | 48,555 | yes | cmp/useSettings | UI |
| POST | `/api/waiver/faab-recommend` | session | n/p | n/p | n/p | n/p | — | cmp/waivers/FaabRecommendation | UI |
| POST | `/api/waiver/suggestions` | session | n/p | n/p | n/p | n/p | — | **nothing** | **DEAD** |
### What the route census shows

| | |
|---|---:|
| Reachable from the UI | 71 |
| **Dead** — no caller outside tests, four with a bridge built for them anyway | **16** |
| Ops / cron / operator / monitoring only | 11 |
| Server-rendered only | 1 |

Anonymous behaviour across all 66 probed operations (`evidence/W22/anon-get-sweep.json`,
transcript §1): **44 × 401, 20 × 200 public, 1 × 400, 1 × 503**. Zero private-contract
fields reached an anonymous caller — W22 grepped the raw bytes of ten anonymous public
endpoints (2.08 MB) against a blocklist of eleven private field names and got **0 hits**.
Path-traversal, case and encoding bypasses against the gate were all refused (12 variants,
transcript §3). `/api/draft-capital` redacts five rookie-value keys anonymously and stamps
`rookieBoardRedacted: true`, on all 72 picks, without poisoning the shared TTL cache.
**The auth boundary holds.**

Authenticated non-200s are all honest refusals, not failures:

| status | routes | why |
|---|---:|---|
| 503 `feature_disabled` | 4 × `/api/consensus-edge/*` | `consensus_edge` flag defaults off (ADR-023) |
| 503 `data_not_ready` | 4 × `/api/intel/*` | no crawl has run in this container |
| 503 `push_not_configured` | `/api/push/public-key` | no VAPID keys here |
| 400 missing-param | 6 | probe sent no required query param |
| 404 | `/api/scaffold/league`, `/api/scaffold/report` | no snapshot on disk |
| 403 `admin_required` | `/api/admin/guest-passes` | `e2e-test-user` is deliberately not allowlisted |

**Latency.** Median authenticated 200 is **9 ms** across 48 routes. The four slow entries in
the table are cold-path artifacts, and W26 re-measured them warm
(`evidence/W26/repeat-latency-auth.txt`, 5 consecutive calls):

| route | cold (route-probe) | warm p50 (W26) |
|---|---:|---:|
| `/api/bdvm/roster` | 47,994 ms | 4.4 ms |
| `/api/league-comparison` | 26,577 ms | 6.7 ms |
| `/api/valuation/league-adjusted` | 7,267 ms | 62 ms |
| `/api/draft-capital` | — | 2,735 ms first, then 5 ms |

The 48 s BDVM cold path is real work thrown away: `evidence/W26/bdvm-cold-path-timing.txt`
measures 1.27 s of schedule build and 7.41 s of player context (23,934 players) that
`run_valuation` never reads, because it returns `no_projection_snapshot` first —
8.69 s of provably wasted work per cold call.

**Payload size.** `/api/data` with no `view` param is **11,953,535 bytes** raw / 1,176,186
gzipped. The app does not use that shape: `?view=app` is 5,818,304 raw / 576,583 gzipped
(`evidence/W26/data-view-sizes.txt`). `?view=compact` is 7,363,760 bytes — *larger* than
`view=app`, which is finding W03-F013 (`src/api/compact_view.py` has no caller and its
documented savings are off by 14×).

Re-run (mint the cookie exactly as `AUDIT_PROTOCOL.md` specifies, then time a route):

```bash
SECRET=$(cat /tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/e2e_secret.txt)
curl -s -c /tmp/audit-cookies.txt -X POST http://127.0.0.1:8000/api/test/create-session \
  -H "Authorization: Bearer $SECRET"
for i in 1 2 3 4 5; do
  curl -s -b /tmp/audit-cookies.txt -o /dev/null \
    -w '%{http_code} %{time_total}s %{size_download}b\n' 'http://127.0.0.1:8000/api/data?view=app'
done
```

**One correction to the shard.** `evidence/W01/surface-inventory.csv` records
`has bridge? = no` for `POST /api/angle/find`, contradicting its own verdict string on the
same row ("bridge exists, no UI caller") and contradicting the filesystem —
`frontend/app/api/angle/find/route.js` is present. The Bridge column above is computed from
the filesystem, not from the CSV. All 35 other bridge assignments agree, and there are **no
orphan bridges**: every one of the 36 proxies a backend route that exists.

---

## 2. Pages

41 Next pages, each loaded twice in a real Chromium — once anonymous, once with a session —
via **Playwright request interception**. This is the only valid topology. `AUDIT_PROTOCOL.md`
records the proof: loading pages straight from `:3000` produces 404s on the 63 backend routes
Next has no bridge for, and a hand-rolled `:3001` proxy returns a 5,895-byte pre-hydration
shell that never hydrates. Both earlier captures are retained as
`page-probe-direct-next-INVALID.json` and `page-probe-via-proxy-INVALID.json` and **neither is
used here**. Everything below comes from `evidence/page-probe.json` (`/rankings` authenticated:
**593,768 bytes**, `h1` = "Rankings" — matching the protocol's own validated interception capture,
which measured 593,422 bytes and 230 rendered table rows; the signature of a hydrated page).

`render outcome` is read from the h1, the HTML byte count and the extracted text length.
`navMs` is DOM-ready time. `settleMs` is not reported: it hit the probe's own 25 s
`networkidle` ceiling on 41 of 41 pages, which is a property of the probe, not the pages
(`evidence/INTEGRITY.md`, correction 3).

| Page (route) | probed URL | anon | auth | h1 | render outcome | HTML b | navMs | console err | in nav? |
|---|---|---|---|---|---|---:|---:|:---:|:---:|
| `/` | `/` | 200 public | 200 | Pick your team | full render (1,437 chars) | 37,610 | 145 | 0 | yes |
| `/admin` | `/admin` | 307 → /login?next=%2Fadmin | 200 | Admin | full render (2,004 chars) | 34,975 | 208 | 1 | yes |
| `/angle` | `/angle` | 307 → /login?next=%2Fangle | 200 | Package Builder | full render (1,681 chars) | 55,219 | 42 | 0 | yes |
| `/arbitrage` | `/arbitrage` | 307 → /login?next=%2Farbitrage | 200 | Arbitrage | full render (593 chars) | 38,949 | 70 | 0 | yes |
| `/bdvm` | `/bdvm` | 307 → /login?next=%2Fbdvm | 200 | Fundamental Values | full render (551 chars) | 29,546 | 86 | 0 | yes |
| `/consensus-edge` | `/consensus-edge` | 307 → /login?next=%2Fconsensus-edge | 200 | Consensus Edge | full render (512 chars) | 27,942 | 81 | 1 | yes |
| `/design` | `/design` | 307 → /login?next=%2Fdesign | 200 | Design system | full render (3,996 chars) | 73,620 | 88 | 0 | no |
| `/draft` | `/draft` | 307 → /login?next=%2Fdraft | 200 | Draft Board | full render (7,796 chars) | 174,098 | 121 | 0 | yes |
| `/edge` | `/edge` | 307 → /login?next=%2Fedge | 200 | Source Disagreement | full render (2,620 chars) | 141,767 | 77 | 0 | yes |
| `/finder` | `/finder` | 307 → /login?next=%2Ffinder | 200 → /rankings | Rankings | redirect, then full render (17,963 chars) | 583,490 | 56 | 6 | no |
| `/idptc-rookies` | `/idptc-rookies` | 307 → /login?next=%2Fidptc-rookies | 200 | Rookie Board | full render (41,710 chars) | 153,029 | 90 | 0 | yes |
| `/intel` | `/intel` | 307 → /login?next=%2Fintel | 200 → /league/insider-trading | Insider Trading | redirect, then full render (672 chars) | 40,558 | 151 | 1 | no |
| `/league` | `/league` | 200 public | 200 | Risk It To Get The Brisket | full render (2,793 chars) | 84,731 | 192 | 6 | yes |
| `/league-comparison` | `/league-comparison` | 307 → /login?next=%2Fleague-comparison | 200 | Scoring Comparison | full render (2,572 chars) | 44,819 | 115 | 0 | yes |
| `/league/activity` | `/league/activity` | 200 public | 200 | Activity | full render (15,525 chars) | 108,845 | 69 | 0 | yes |
| `/league/articles/[season]/[week]` | `/league/articles/2025/1` | 200 public | 200 | Week 1 · 2025 | full render (438 chars) | 40,361 | 102 | 0 | no |
| `/league/articles/[season]/[week]/[matchupId]/[mode]` | `/league/articles/2025/1/1/preview` | 200 public | 200 | _(none)_ | **not-found card** (249 chars) — probe param, see below | 40,304 | 104 | 0 | no |
| `/league/franchise/[owner]` | `/league/franchise/jasonleetucker` | 200 public | 200 | _(none)_ | **not-found card** (216 chars) — probe param, see below | 39,493 | 94 | 0 | no |
| `/league/insider-trading` | `/league/insider-trading` | 307 → /login?next=%2Fleague%2Finsider-trading | 200 | Insider Trading | full render (672 chars) | 40,157 | 74 | 1 | yes |
| `/league/player/[playerId]` | `/league/player/4046` | 200 public | 200 | Patrick Mahomes | full render (1,683 chars) | 75,485 | 211 | 5 | no |
| `/league/rivalry/[pair]` | `/league/rivalry/jasonleetucker-vs-blaine` | 200 public | 200 | _(none)_ | **not-found card** (229 chars) — probe param, see below | 39,314 | 77 | 0 | no |
| `/league/week/[season]/[week]` | `/league/week/2025/1` | 200 public | 200 | Roy put Eric on a milk carton, | full render (4,055 chars) | 176,185 | 221 | 6 | no |
| `/league/weekly/[season]/[week]/[matchup]` | `/league/weekly/2025/1/1` | 200 public | 200 | 2025 · Week 1 | full render (1,570 chars) | 86,073 | 104 | 2 | no |
| `/login` | `/login` | 200 public | 200 | Sign in | full render (263 chars) | 28,208 | 80 | 0 | yes |
| `/market/sharp-roster-percentage` | `/market/sharp-roster-percentage` | 307 → /login?next=%2Fmarket%2Fsharp-roster-percentage | 200 | Sharp Roster Percentage | full render (2,047 chars) | 35,788 | 70 | 0 | yes |
| `/market/sharp-tracker` | `/market/sharp-tracker` | 307 → /login?next=%2Fmarket%2Fsharp-tracker | 200 | Sharp Tracker | full render (1,398 chars) | 31,755 | 51 | 0 | yes |
| `/more` | `/more` | 307 → /login?next=%2Fmore | 200 | All destinations | full render (1,757 chars) | 35,302 | 42 | 0 | yes |
| `/news` | `/news` | 307 → /login?next=%2Fnews | 200 | News | full render (4,470 chars) | 51,892 | 66 | 0 | yes |
| `/phases` | `/phases` | 307 → /login?next=%2Fphases | 200 | Win-now vs Rebuild | full render (749 chars) | 32,818 | 39 | 0 | yes |
| `/players/compare` | `/players/compare` | 307 → /login?next=%2Fplayers%2Fcompare | 200 | Compare Players | full render (417 chars) | 29,731 | 101 | 0 | yes |
| `/rankings` | `/rankings` | 307 → /login?next=%2Frankings | 200 | Rankings | full render (17,960 chars) | 593,768 | 83 | 6 | yes |
| `/rankings/[position]` | `/rankings/qb` | 307 → /login?next=%2Frankings%2Fqb | 200 → /rankings?pos=QB | Rankings | redirect, then full render (7,741 chars) | 248,521 | 113 | 6 | no |
| `/rosters` | `/rosters` | 307 → /login?next=%2Frosters | 200 | Team Strength | full render (4,832 chars) | 119,432 | 67 | 8 | yes |
| `/settings` | `/settings` | 307 → /login?next=%2Fsettings | 200 | Settings | full render (4,688 chars) | 151,737 | 78 | 0 | yes |
| `/tools/ros-data-health` | `/tools/ros-data-health` | 307 → /login?next=%2Ftools%2Fros-data-health | 200 | ROS Data Health | full render (1,245 chars) | 36,371 | 50 | 0 | yes |
| `/tools/source-health` | `/tools/source-health` | 307 → /login?next=%2Ftools%2Fsource-health | 200 | Source Health | full render (282 chars) | 28,515 | 609 | 0 | yes |
| `/tools/trade-coverage` | `/tools/trade-coverage` | 307 → /login?next=%2Ftools%2Ftrade-coverage | 200 | Trade Coverage Audit | full render (1,191 chars) | 48,669 | 80 | 0 | yes |
| `/trade` | `/trade` | 307 → /login?next=%2Ftrade | 200 | Trade Calculator | full render (965 chars) | 47,548 | 84 | 0 | yes |
| `/trades` | `/trades` | 307 → /login?next=%2Ftrades | 200 | Trade History | full render (54,026 chars) | 857,729 | 62 | 6 | yes |
| `/trending` | `/trending` | 307 → /login?next=%2Ftrending | 200 | Trending | full render (414 chars) | 30,585 | 386 | 0 | yes |
| `/waivers` | `/waivers` | 307 → /login?next=%2Fwaivers | 200 | Waivers | full render (700 chars) | 40,536 | 46 | 0 | yes |


### What the page census shows

**All 41 pages return 200 with a session and render.** No 500s, no blank shells, no page that
fails to hydrate. The auth gate is uniform: **30 private** pages 307 to `/login?next=<path>`
anonymously and **11 public** pages (`/`, `/login`, and the nine-route `/league` public subtree)
serve anonymously, and `frontend/middleware.js` + `frontend/lib/public-routes.js`
are the single gate — there is no backend half to disagree with, since `server.py` registers
no page routes at all.

**Console errors are clean.** **51 of the 55** console errors across all 41 authenticated page
loads are `net::ERR_CONNECTION_RESET` on `sleepercdn.com` images and avatars — a container
egress limit, pre-declared as a non-finding. The other four are honest backend refusals
surfacing in devtools: 503 on `/consensus-edge` (flag off), 503 × 2 on `/intel` and
`/league/insider-trading` (no intel crawl), 403 on `/admin` (`e2e-test-user` is not an admin).
**Zero application JavaScript errors were recorded on any page.** Most `failedRequests`
entries are Next RSC prefetches to `/league` aborting on navigation, not failures.

**Three "empty" rows in the table are probe-parameter artifacts, not page defects.**
`/league/franchise/[owner]`, `/league/rivalry/[pair]` and
`/league/articles/[season]/[week]/[matchupId]/[mode]` show no `<h1>` and 216–249 characters of
text because the probe passed a *username* (`jasonleetucker`) where the route wants a Sleeper
owner id, and asked for a `preview` article that does not exist. W19 re-probed the same routes
with real parameters and they render fully — `/league/franchise/468418790212759552` gives 1,283
characters including record, points-for and 59 owned picks; `/league/rivalry/468…-vs-711…` gives
a full head-to-head; `/league/articles/2025/17/1/recap` gives a 5,227-character generated
article (`evidence/W19/deeplink-probe.json`). With a bad parameter all three render an explicit
"not found" card, which is the correct behaviour. **These are not defects and are not counted as
such.**

**Five pages are in no navigation.** `frontend/lib/nav-model.js` is the single IA source (6
groups, 23 leaves + 6 system items); the desktop bar, mobile tabs, drawer, palette and the
`/more` site map all derive from it, and **all 31 nav hrefs resolve to a real 200 page** — no nav
entry points at nothing. The unlisted five (`evidence/W01/nav-vs-reality.md`, W01-F005):

| page | what it is |
|---|---|
| `/finder` | legacy screener, now a client redirect into `/rankings?screen=…` — self-documented bookmark shim |
| `/intel` | retired route, server `redirect()` → `/league/insider-trading` |
| `/design` | **dev-only design-system gallery, shipped in the production build**, `robots:{index:false}`, behind the ordinary session gate — any signed-in user who guesses the URL gets it |
| `/rankings/[position]` | deep-link shim → `/rankings?pos=X` |
| `/draft-capital` | `next.config.mjs` 308 → `/league?tab=draft-capital`; named in `pageTitleFor`, in no menu. Not in the probe table — it is a config redirect, not an app page |

Re-run the page sweep: the interception recipe is in `AUDIT_PROTOCOL.md` ("Browser page loads
MUST re-route `/api/*` to the backend"). Any page observation taken without it is void.

---

## 3. Scheduled jobs

Three schedulers run this platform and they do not overlap: **GitHub Actions** owns source
fetching, model refits and audits; **systemd timers on the VPS** own crawls, snapshots and
backups; **`scripts/`** is the code both invoke plus a large research tail nothing invokes.
The W23 shard mapped all three (`evidence/W23/schedule-map.csv`,
`evidence/W23/script-invocation-map.txt`, 1,358 files scanned).

### 3.1 GitHub workflows — all 22

**STALE COUNT, flagged rather than silently rewritten (2026-08-20, C10-CLOSE-04 audit).** This
table is a point-in-time census at this document's own provenance commit (`ba9f348b`,
2026-08-04) and is left as that historical record rather than edited row-by-row to match today's
tree — rewriting a dated census to describe a different day would make its own provenance line
false. The current count is **31 workflow files**, not 22: `force-sharp-production-now.yml`,
`trigger-sharp-now-via-merge.yml`, `trigger-sharp-no-environment.yml` and
`check-sharp-production-now.yml` (all 4 listed below) have since been **deleted**, and
`dynasty-pbp-weekly`, `dynasty-faab-history`, `dynasty-sharp-cohort-snapshot`,
`dynasty-sharp-transactions`, `chase-upside-curated-sharps` and several others shipped since. For
the CURRENT enumeration, see `docs/ops/C10_CLOSE_04_BACKGROUND_JOBS_MATRIX.md` §A, built and kept
current by that closure pass rather than this frozen audit.

| Workflow | Trigger | Cadence (UTC) | Runs | Note |
|---|---|---|---|---|
| `scheduled-refresh.yml` | cron | `42 */2 * * *` — every 2 h | 20 scripts: 15 `fetch_*`, `validate_scrape_sanity`, both watchdogs, `check_env` | **The data pipeline.** Guards are mostly post-deploy — W23-F010 |
| `deploy.yml` | push to `main` (`paths-ignore: data/**, exports/**`) + dispatch | on push | `check_env`, `validate_api_contract` | production deploy |
| `pr-validation.yml` | pull_request | on PR | `check_env`, `validate_api_contract`, whole-repo `ruff` gates | blocking |
| `e2e.yml` | cron | `23 6 * * *` — daily | Playwright E2E | `SKIP_VISUAL_REGRESSION=1` skips all 13 visual-spec tests — W24-F004 |
| `smoke-test.yml` | cron | `15 6 * * *` — daily | `check_env`, `validate_api_contract` | 2 jobs incl. production smoke |
| `prod-e2e-smoke.yml` | cron | `17 */4 * * *` — every 4 h | public `/league` smoke | |
| `health-check.yml` | cron | `17 */6 * * *` — every 6 h | inline source-coverage check | floor of 8 covered sources out of 21 — W05-F008 |
| `public-league-warmup.yml` | cron | `*/20 * * * *` — every 20 min | warms public-league cache | highest-frequency job on the platform |
| `audit-identity-matches.yml` | cron + push on identity paths | `17 8 * * *` — daily | `audit_identity_matches` | opens/closes an issue idempotently |
| `intel-refresh.yml` | cron | `10 9 * * *` — daily | `POST /api/intel/refresh` | idempotent issue handling |
| `audit-dropped-sources.yml` | cron | `23 7 * * 1` — weekly Mon | `audit_dropped_sources` | |
| `refit-hill-curves.yml` | cron | `17 6 * * 2` — weekly Tue | `auto_refit_hill_curves`, `model_registry` | records a challenger; **cannot ship constants** (W04-F016, status `Implemented and verified`). Opens duplicate issues forever — W23-F009 |
| `audit-rank-form-drift.yml` | cron | `41 7 * * 2` — weekly Tue | `check_rank_form_drift` | |
| `consensus-edge-revalidate.yml` | cron | `40 5 * * 3` — weekly Wed | `validate_consensus_edge_board` | output read by nothing but an exit code — W14-F008 |
| `weekly-narratives.yml` | cron ×2 | `0 14 * * 2` + `0 13 * * 3` | `generate_weekly_narratives` | preview Wed, recap Tue |
| `claude.yml` | issue/PR comment events | event-driven | Claude Code agent | |
| `sharp-records-bootstrap.yml` | `workflow_run` after Deploy Production + dispatch | post-deploy | remote sharp records pass | the one legitimate sharp chain |
| `verify-sharp-production.yml` | **every push to `main`** + `workflow_run` | on push | sharp health smoke | **always fails before its own assertion** — W23-F004 / W15-F011 |
| `force-sharp-production-now.yml` | push touching **its own file** + dispatch | manual | restart backend, populate sharp | scaffolding — W15-F012 |
| `trigger-sharp-now-via-merge.yml` | push touching **its own file** | manual | kick sharp refresh | scaffolding — W15-F012 |
| `trigger-sharp-no-environment.yml` | push touching **its own file** | manual | kick sharp, no environment gate | scaffolding — W15-F012 |
| `check-sharp-production-now.yml` | dispatch only | manual | read-only prod sharp check | scaffolding — W15-F012 |

Re-run: `for f in .github/workflows/*.yml; do echo "== $f"; grep -A4 '^on:' "$f"; done`

**Measured schedule slip.** The 2 h refresh cron does not keep its cadence. Reading the commit
stream the workflow itself produces (`chore: freshness stamps <UTC>`), over the 26.7 h window
2026-08-03T15:37Z → 2026-08-04T18:21Z there are **10 runs where 13–14 are scheduled**, with gaps
of 2.87, 1.85, 1.53, 2.08, 4.00, 3.50, 3.75, 4.00 and 3.13 hours. Over the identical window the
prod-side systemd fetch timers land 14/14 with zero misses (W05-F012). Re-run:
`git log --since='2026-08-02' --format='%s' -- data/scrape_state | grep 'freshness stamps'`.

**One verified negative worth recording:** all 22 workflow files parse cleanly as YAML and none
contains a duplicate mapping key, so no workflow is silently unrunnable for that reason
(W23-F016, status `Implemented and verified`).

### 3.2 systemd timers — all 19

**STALE COUNT, flagged rather than silently rewritten (2026-08-20, C10-CLOSE-04 audit).** Same
provenance-preservation reasoning as §3.1 above — this table is a point-in-time census at
`ba9f348b` and is not edited to match today's tree. The current count is **27 systemd units**
(20 `dynasty-*` template-rendered + 5 fixed non-template units + 2 units in separately-installed
directories `curated-sharps-systemd/`/`ffpc-systemd/`), not 19. For the current enumeration and
each unit's health-tracking mechanism (or lack of one), see
`docs/ops/C10_CLOSE_04_BACKGROUND_JOBS_MATRIX.md` §B.

| Unit | OnCalendar (UTC) | ExecStart | Installed by |
|---|---|---|---|
| `dynasty-sharp-discovery` | daily 04:20 | `scripts/discover_sharp_graph.py` | `install-systemd-service.sh`, `bootstrap-sharp-records.sh` |
| `dynasty-sharp-records` | daily 04:50 | `scripts/crawl_sharp_records.py` | `install-systemd-service.sh`, `bootstrap-sharp-records.sh` |
| `dynasty-ffpc-sharp` | daily 05:20 | `scripts/crawl_ffpc_sharp.py` | `install-systemd-service.sh` |
| `chase-upside-ffpc-sharp` | daily 05:20 | `scripts/crawl_ffpc_sharp.py` | `install-ffpc-sharp-service.sh` — **byte-identical duplicate**, W23-F013 |
| `dynasty-playerctx-refresh` | weekly Tue 05:40 | `scripts/refresh_playerctx.py` | `install-systemd-service.sh` |
| `dynasty-sharp-rosters` | daily 05:50 | `scripts/crawl_sharp_rosters.py` | `install-systemd-service.sh` |
| `dynasty-bdvm-refresh` | weekly Tue 06:10 | `scripts/refresh_bdvm_projections.py` | `install-systemd-service.sh` |
| `dynasty-sharp-activity` | daily 06:30 | `scripts/crawl_sharp_activity.py` | `bootstrap-sharp-records.sh` **only** |
| `dynasty-reception-depth` | weekly Wed 07:20 | `scripts/refresh_reception_depth.py` | `install-systemd-service.sh` |
| `dynasty-consensus-edge-snapshot` | daily 07:30 | `scripts/snapshot_consensus_edge.py` | `install-systemd-service.sh` |
| `dynasty-signal-alerts` | daily 15:00 | `curl POST /api/signal-alerts/run` | `install-systemd-service.sh` (needs `SIGNAL_ALERT_CRON_TOKEN`) |
| `dynasty-custom-alerts` | every 2 h at :13 | `curl POST /api/custom-alerts/run` | `install-systemd-service.sh` (needs token). Description says **"Hourly"** — W23-F014 |
| `dynasty-dlf-fetch` | every 2 h at :27 | `deploy/dlf_fetch_and_push.sh` | `install-systemd-service.sh` |
| `dynasty-idpshow-fetch` | every 2 h at :32 | `deploy/idpshow_fetch_and_push.sh` | `install-systemd-service.sh` |
| `riskit-backup` | daily 02:00 | `deploy/backup_user_kv.sh` | `install-systemd-service.sh` |
| `riskit-backup-restore-test` | weekly Mon 03:30 | `backup_user_kv.sh --restore-test` | `install-systemd-service.sh` |
| `riskit-state-backup` | daily 02:30 | `riskit-state-backup.sh` | **`apply_hardening.sh` only** — W23-F011 |
| `dynasty-healthcheck` | `OnUnitActiveSec=1min` | backend liveness watchdog | **`apply_hardening.sh` only** — W23-F011 |
| `riskit-uptime` | `OnUnitActiveSec=5min` | `deploy/monitoring/uptime_check.sh` | **`apply_hardening.sh` only** — W23-F011 |

Re-run: `for f in $(find deploy -name '*.timer*'); do echo "-- $f"; grep -E 'Description|OnCalendar|OnUnitActiveSec' "$f"; done`

The three units in bold are installed by no automation. `deploy/deploy.sh` and
`deploy/bootstrap-production.sh` both call `install-systemd-service.sh`, which never mentions
them; `apply_hardening.sh`'s only documented invocation is a hand-typed `sudo bash
deploy/apply_hardening.sh`, and a repo-wide grep for `apply_hardening` outside docs and its own
body returns **zero callers**. If that manual step was ever missed or the host rebuilt, the
1-minute liveness watchdog, the 5-minute uptime probe and the 02:30 state backup do not exist.
Re-run: `grep -rn apply_hardening --include='*.sh' --include='*.yml' . | grep -v apply_hardening.sh:`

### 3.3 `scripts/` — 89 Python entrypoints

Reachability measured by scanning 1,358 non-vendored files for `scripts/<name>` and
`scripts.<module>` invocation forms, across workflows, systemd unit templates, deploy scripts,
`Makefile`/`Jenkinsfile`/`.bat`, sibling scripts and `src/`.

| Bucket | Count | Meaning |
|---|---:|---|
| Scheduled | **39** | 28 by a workflow, 9 by a timer, 6 by a deploy script (overlapping) |
| Called but not scheduled | **25** | a library or a step inside another script |
| Referenced by tests only | **3** | `backtest_ktc_volatility`, `backtest_percentile_reference_n`, `convert_dlf_csv` |
| **No scheduler, no caller, not even a test** | **22** | listed in §4.2 |

Adding the four non-Python entrypoints (`setup.sh`, `prep_scoring_data.R`,
`test_ktc_va_port.mjs`, `verify_lockstep.ps1`) gives the 93-row `schedule-map.csv`, and 28
unreferenced entries across all extensions — the number W23-F015 reports.

Re-run:
```bash
awk -F, 'NR>1 && $2=="none" && ($5=="NOTHING"||$5=="TESTS ONLY"){print $1}' \
  docs/master-site-audit/evidence/W23/schedule-map.csv
```

---

## 4. What nothing reaches

### 4.1 Dead routes — 16 of 99 (16.2%)

Zero callers in frontend code, zero bridge consumers, zero references in
`.github/workflows/`, `deploy/` or `scripts/`. Referenced only by tests, or by nothing at all
(W01-F003, `evidence/W01/dead-routes.txt`). Twelve rows below; the `/api/scaffold/*` row
collapses five routes, giving sixteen.

| Route | Why it is dead |
|---|---|
| `POST /api/angle/find` | `/angle` posts only to `/api/angle/packages`. **Has a bridge.** |
| `GET /api/consensus-edge/health` | `/consensus-edge` reads `players` + `methodology` only. **Has a bridge.** |
| `GET /api/consensus-edge/player/{player_key}` | tests only |
| `GET /api/gameplan` | **the whole `src/roster_intel/` engine — 4,385 lines — with zero frontend consumers** (W01-F002, W20-F001) |
| `GET /api/intel/member/{owner_id}` | tests only |
| `GET /api/intel/waiver-interest` | tests only; waiver/FAAB activity is fully modelled, ingested and served, and no route reaches it (W16-F007) |
| `GET /api/public/league/{section}.csv` | no export link anywhere; the four in-app CSV exports are client-side blobs (W01-F012) |
| `GET /api/rankings/sources` | CLAUDE.md calls this the "runtime check" for registry lockstep. Nothing calls it at runtime; the parity test parses the frontend JS statically (W01-F011). **Has a bridge.** |
| `GET /api/scaffold/status` | no caller — and it is in `_PUBLIC_API_EXACT`, so it is **unauthenticated and its payload contains absolute server filesystem paths** |
| `GET /api/scaffold/{raw,league,identity,validation,report}` | tests only |
| `POST /api/test-alert` | **zero references anywhere in the repository, including tests** |
| `POST /api/waiver/suggestions` | no UI caller — CLAUDE.md concedes this. Additionally sizes bids against the manager's remaining balance where the UI uses the starting budget (W11-F017) |

Two more that are not "dead" but are worth naming beside them: `GET /api/metrics` is public,
unauthenticated and has no in-repo consumer (plausibly scraped by an external monitor, so
classified ops); `GET /api/sharp/market/audit` and `GET /api/sharp/roster-percentage/audit` are
operator-only with no UI entry point, one of them with a bridge built for it.

Separately, `src/api/chat.py` ships a documented private endpoint that is **never registered** —
`/api/chat` is absent from the 100 live operations and returns 404 on both verbs (W30-F011).

Four bridges exist for routes nothing calls: `angle/find`, `consensus-edge/health`,
`rankings/sources`, `sharp/roster-percentage/audit`. Dev plumbing written for dead endpoints.

Re-run: `cat docs/master-site-audit/evidence/W01/dead-routes.txt`

### 4.2 Dead scripts — 22 of 89

No scheduler, no production caller, no test reference. Seventeen research one-offs plus five
guards.

**Most of these are legitimately one-off research and calling them "dead" would be wrong**:
`backtest_adjusted_board`, `backtest_alpha_lambda_joint`, `backtest_alpha_shrinkage`,
`backtest_consensus_edge_composite`, `backtest_scoring_adjustment`, `backtest_soft_fallback`,
`measure_bdvm_dispersion_scale`, `measure_consensus_edge_panel`, `measure_coverage_weight_impact`,
`inspect_anomalies`, `build_historical_scoring_dataset`, `backfill_ktc_sftep_raw`,
`export_player_map`, `generate_test_seeds`, `migrate_intel_platform_v2`, `refit_source_weights`,
plus `scripts/__init__.py`.

**Five are guards, and a guard nothing runs is indistinguishable from a guard that does not
exist** (W23-F015):

| script | what it is supposed to guard |
|---|---|
| `validate_sharp_roster_percentage.py` | the Sharp Roster Percentage board's counting rules |
| `validate_va_v2.py` | the v2 value-adjustment formula |
| `validate_scoring_fit.py` | the scoring-adjustment fit |
| `board_invariance_hash.py` | that the board did not change when it should not have |
| `golden_board.py` | the golden-board comparison |

Adjacent, same shape: `tests/fixtures/golden/baseline.json` is a 722 KB committed golden
baseline that no test and no workflow reads (W24-F009).

### 4.3 Jobs whose output nothing reads

| Job | Output | Who reads it |
|---|---|---|
| `verify-sharp-production.yml` | `data/ops/sharp-production-smoke.json` | **CORRECTED 2026-08-20 (C10-CLOSE-04 audit) — this row is stale and the defect it describes is fixed.** As of this document's own provenance commit (`ba9f348b`) the claim was accurate; `.github/workflows/verify-sharp-production.yml:303` now runs `git add -f data/ops/sharp-production-smoke.json`, and `git ls-files data/ops/` confirms the file is tracked. The "nobody, ever" / "0 commits" claim below no longer holds and should not be re-cited as current |
| `force-sharp-production-now.yml`, `trigger-sharp-now-via-merge.yml`, `trigger-sharp-no-environment.yml` | three more `data/ops/*.json` | **CORRECTED 2026-08-20 — these three workflows have since been DELETED.** `data/ops/sharp-force-production-live.json`, `sharp-merge-trigger-result.json` and `sharp-no-environment-result.json` are still git-tracked (their commit step, from whenever it last ran, is not undone by deleting the workflow) but nothing in the current tree regenerates them — they are frozen artifacts that read as current ops state. §3.1 below still lists these three workflows in its inventory table; that table is a point-in-time census at `ba9f348b` and is not corrected row-by-row here — see the note at the top of §3.1 |
| `consensus-edge-revalidate.yml` (weekly Wed) | `pooled.topBuys.medianExcess` and a full validation JSON | printed and discarded. The gate compares only `decision.recommendation`, a string — it stays green while the measured excess moves from −0.006 to −0.30 or to +0.20 (W14-F008). And the surface it validates, `/consensus-edge`, is **behind a flag that defaults off** |
| `refit-hill-curves.yml` (weekly Tue) | a GitHub issue | read by a human, but `gh issue create` with no `gh issue list` dedupe and **zero** `gh issue close` steps — alone among the six issue-opening workflows. A persistent condition mints one duplicate issue every Tuesday forever (W23-F009) |
| the ops "scrape success rate < 50%" alert | an SMTP email | **can never fire.** The payload handed to `_check_scrape_rate` never carries `scrape_success_rate_24h` (an AST scan of all 23 keys written into `scrape_status` confirms it), and where the key *does* exist — on `/api/status` — its value is a dict, so `float()` raises and the `except` swallows it. Both routes to the alert are closed (W23-F001) |
| `scheduled-refresh.yml` steps 10–13 | DLF-freshness assertion + both watchdogs | they run, but **after** step 8 commits the data and step 9 dispatches the production deploy. There is no revert, no re-deploy of the prior commit, no call to `deploy/rollback.sh` anywhere in the workflow (W23-F010) |

The three sharp *crawl* timers are the counterexample and deserve saying plainly: `schedule-map.csv`
records `read_by: NOTHING` for `discover_sharp_graph.py` and `crawl_sharp_records.py`, but that
column measures **script-name references**, not output consumption. Those crawls write the
platform ledger, which `src/sharp/score.py` and `src/sharp/cohort.py` read on every request to
`/api/sharp/*`. Their output is read.

Re-run: `bash docs/master-site-audit/evidence/W23/gitignore-repro.sh; git log --all --oneline -- data/ops/ | wc -l`

### 4.4 The five "kick sharp in prod" workflows — yes, the evidence supports calling them scaffolding

W15-F012, status **`Scaffolded only`**. The claim is falsifiable and it holds:

| Workflow | `schedule:`? | Actual trigger |
|---|:---:|---|
| `check-sharp-production-now.yml` | no | `workflow_dispatch` only |
| `force-sharp-production-now.yml` | no | push to `main` **restricted to its own `.yml` path** |
| `trigger-sharp-now-via-merge.yml` | no | push to `main` **restricted to its own `.yml` path** |
| `trigger-sharp-no-environment.yml` | no | push to `main` **restricted to its own `.yml` path** |
| `verify-sharp-production.yml` | no | push to `main` (`paths-ignore`) — so it fires on unrelated commits and always fails at its `git add` |

Three of them only run when somebody edits the workflow that runs them: a manual kick dressed as
automation. The names encode their own debugging history — "force", "now", "via merge",
"without environment gate". The real recurring cadence for Sharp lives entirely in the
five systemd timers in §3.2 (discovery 04:20, records 04:50, ffpc 05:20, rosters 05:50, activity
06:30), none of which is referenced by any workflow.

`verify-sharp-production.yml` is the expensive one. It runs on essentially every code push to
`main`, its wait loop is `range(1,81)` with `time.sleep(30)` — **2,400 s = 40 minutes of billed
runner time per push**, under a 50-minute job timeout — and it ends in a red X that says nothing
about Sharp's actual health, because the assertion step never executes (W23-F004). It also
reports `unmappedAssets` out of a `dataQuality` key that `/api/sharp/market` has never emitted,
so that figure is hard-zero on every run (W23-F005).

`sharp-records-bootstrap.yml` is a **sixth** sharp workflow and is *not* in this category: it is
`workflow_run`-chained to Deploy Production plus dispatch, which is a legitimate post-deploy
bootstrap. W15-F012's title says "five" while its body counts six — the five above are the
scaffolding; the bootstrap is not.

Re-run:
```bash
for f in .github/workflows/*sharp*.yml; do echo "== $f"; sed -n '1,12p' "$f"; done \
  | grep -E '^(==|name:|on:|  schedule|  workflow_dispatch|  push|  workflow_run)'
ls deploy/systemd/ | grep sharp
```

---

## 5. Confidence and limits

**Verification status.** Of the 431 published findings, 30 have been through adversarial
verification: 24 recorded in `findings.json` (5 upheld, 18 rescoped, 1 overturned) plus 6 more
landed since it was generated (`evidence/verify/verdicts-C1.jsonl`, `-C2.jsonl`: W11-F001 and
W26-F001 upheld; W11-F002, W23-F003, W23-F006 and W26-F002 rescoped). Verification was still
running when this document was written.

**None of the 28 findings cited here has been verified or disputed.** Every one carries status
`unverified` — meaning not selected for verification, not that it failed. Each rests on the
reproduction command printed beside it, and the severities are reported as authored. Two W23
findings *were* rescoped in the latest pass — W23-F003 (partial-scrape guard) and W23-F006
(data-age metric) — and **neither is cited in this document**, so no claim above needs the
verified-position treatment. A reader re-checking this inventory after verification completes
should re-read §4.3 first: it carries the highest concentration of unverified mechanism claims.

**What this inventory could not establish:**

- **34 of 99 route operations were never exercised.** All POST and PUT routes outside the pure
  computation endpoints were left alone under the read-only rule. Their auth behaviour, latency
  and payload size are unmeasured — the `n/p` cells are absence of data, not evidence of health.
- **Production schedule adherence is inferred, not observed.** The systemd timer table is read
  from unit files in the repo. Nothing in this container ran `systemctl list-timers` against the
  VPS, so which units are actually *installed and enabled* on the deploy host is unknown. The
  three `apply_hardening.sh`-only units may well be present; the finding is that no automation
  guarantees it.
- **Workflow run history was not read.** Claims about `verify-sharp-production.yml` always
  failing rest on static analysis of the step order plus the reproducible `git add` exit code and
  the fact that `data/ops/` has zero commits across all refs — not on GitHub Actions run logs.
- **`/api/metrics` may have an external consumer.** No in-repo caller exists; an outside monitor
  scraping it would be invisible to this audit. It is classified ops, not dead, for that reason.
- **Two workflows could not be run here.** `consensus-edge-revalidate` correctly refuses on a
  shallow clone (this container has `.git/shallow`, 409 commits), and nothing that fetches an
  external source was permitted to run at all.
