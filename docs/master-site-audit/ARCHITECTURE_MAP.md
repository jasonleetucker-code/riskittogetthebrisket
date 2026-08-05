# Repository and Runtime Map

Master site audit, deliverable section 2. Commit `ba9f348b`, branch
`claude/fantasy-football-master-audit-umvex5`, generated 2026-08-05.

This document describes what exists and how a request moves through it. It is a
map, not a verdict list — defects appear here only where they change the shape of
the system, and every one carries its finding id. Findings live in
`findings.json` (431 published, 1 refuted and withdrawn); the per-feature verdict
table is `FEATURE_STATUS_MATRIX.md` and is not duplicated here.

**Verification status of this document's claims.** As of the `findings.json`
snapshot at commit `ba9f348b`, the adversarial verification pass had issued 24
verdicts (18 rescoped, 5 upheld, 1 overturned). The pass was still running while
this document was written — re-run the check below rather than trusting that
count, and re-read §8 and §11 if a new verdict lands on a finding cited here.
**Two of the 42 findings cited in this document carry a
verdict, and both were rescoped downward from P1 to P2** — `W23-F003` (the
partial-scrape guard) and `W26-F002` (the app-shell contract fetch). This
document reports the verifier's corrected position for both, in §8 and §11
respectively, and says so at each site.

The other 40 cited findings are author-published and were **not** re-tested by
the verification pass. Any priority shown against one of them (`P1`, `P2`, …) is
the **authored** priority, not an adjudicated one — read it as the author's
severity claim, not as a settled fact. The two rescoped findings are the only
ones whose priority here has been through an adversarial pass.

Every number in this document is either re-measured against the running stack
while writing it or read directly out of a captured evidence artifact. Which one
is stated inline, with a re-run command.

Re-run the verdict check: `.venv/bin/python -c "import json,glob,re; v={json.loads(l)['id']: json.loads(l)['verdict'] for f in glob.glob('docs/master-site-audit/evidence/verify/verdicts-*.jsonl') for l in open(f)}; c=set(re.findall(r'W\d\d-F\d\d\d', open('docs/master-site-audit/ARCHITECTURE_MAP.md').read())); print({k:v[k] for k in c if k in v})"`

---

## 1. The topology fact, stated once and properly

Three processes, one reverse proxy, and an asymmetry that makes local testing lie.

```
                       ┌──────────────────────────────────────────────┐
   browser ──HTTPS──►  │  nginx   deploy/nginx/chaseupside-proxy.conf  │
                       │                                              │
                       │  location /api/          ──► dynasty_backend │
                       │  location /_next/static/ ──► dynasty_frontend │ (proxy_cache)
                       │  location /_next/        ──► dynasty_frontend │
                       │  location = /favicon.ico ──► dynasty_frontend │
                       │  location /              ──► dynasty_frontend │
                       └───────────┬──────────────────────┬───────────┘
                                   │                      │
                    ┌──────────────▼──────┐   ┌───────────▼─────────────┐
                    │ dynasty.service     │   │ dynasty-frontend.service│
                    │ FastAPI / uvicorn   │   │ Next.js 16.2.12         │
                    │ :8000 — 100 ops     │   │ :3000 — 41 pages        │
                    │ server.py 12,954 ln │   │ + 36 dev bridge routes  │
                    └──────────┬──────────┘   └─────────────────────────┘
                               │  importlib
                    ┌──────────▼────────────────────┐
                    │ Dynasty Scraper.py  7,741 ln  │
                    │ 21 ranking sources → snapshot │
                    └───────────────────────────────┘
```

**In production, no `/api/*` request ever reaches Next.** nginx routes `/api/`
straight to FastAPI. Next's 36 `frontend/app/api/**/route.js` handlers are thin
proxies that exist for the dev flow only, and the repo says so in
`frontend/app/api/dynasty-data/route.js`'s own header comment.

**`frontend/next.config.mjs` declares no `rewrites()`.** It declares `distDir`,
`turbopack.root` and one `redirects()` entry. `npm run dev` is `next dev -p 3000`
with nothing in front of it. So under `next dev` only the 36 bridged paths
resolve; the other 63 backend operations return a Next 404 — and 40 of those 63
are fetched directly by client code (W01-F001, `evidence/W01/bridge-coverage.md`).

Re-measured now, all three origins with the same session:

| path | `:3000` (Next alone) | `:8000` (FastAPI) |
|---|---|---|
| `/api/health` | **404** | 200 |
| `/api/leagues` | **404** | 200 |
| `/api/terminal` | **404** | 200 |
| `/api/user/state` | **404** | 200 |
| `/api/dynasty-data` (bridged) | 200 | 200 |

Re-run: `for r in /api/health /api/leagues /api/terminal /api/user/state /api/dynasty-data; do printf '%-22s %s %s\n' $r $(curl -s -o /dev/null -w '%{http_code}' -b /tmp/arch-cookies.txt http://127.0.0.1:3000$r) $(curl -s -o /dev/null -w '%{http_code}' -b /tmp/arch-cookies.txt http://127.0.0.1:8000$r); done`

### Why this matters for anyone testing locally

A browser pointed at `:3000` produces a cascade of `/api/*` 404s that production
never produces, and downstream of those 404s the frontend correctly takes its
fail-fast path and logs `buildRows received a payload with zero backend rank
stamps`. **That console error is a topology artifact, not a product defect.**
`AUDIT_PROTOCOL.md` pre-declares both as non-findings, and this audit measured
the difference three ways on the same two pages:

| method | `/rankings` HTML | `<h1>` | table rows |
|---|---|---|---|
| plain `:3000` | large, but 222 console errors / 261 failed requests across 41 pages | present | present |
| hand-rolled HTTP proxy on `:3001` | 5,895 b — dead pre-hydration shell | `None` | **0** |
| **Playwright request interception** | **593,422 b** | `Rankings` | **230** |

Only the third reproduces production. `evidence/page-probe-direct-next-INVALID.json`
and `evidence/page-probe-via-proxy-INVALID.json` are retained and both invalid;
`evidence/page-probe.json` is the valid capture.

### One dev-only consequence worth knowing

The `/api/dynasty-data` bridge is 264 lines and adds a disk-snapshot fallback,
per-chunk idle abort, and header filtering the backend does not have. Because it
treats a backend **401** as "backend errored", an anonymous request to the bridge
under `next dev` is answered from disk:

```
backend  anon GET /api/dynasty-data  →  401
:3000    anon GET /api/dynasty-data  →  200, 540,035 bytes of the scrape snapshot
```

Re-run: `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/dynasty-data; curl -s http://127.0.0.1:3000/api/dynasty-data -o /dev/null -w '%{http_code} %{size_download}\n'`

Measured while writing this map; **not** among the 431 published findings. It is
confined to `npm run dev` — nginx never routes to that handler — but it means the
dev path is strictly more permissive *and* more fault-tolerant than production,
which is the wrong direction for both properties.

---

## 2. The route surface: 100 operations, and why grep undercounts

The authoritative census is the live OpenAPI document
(`evidence/openapi.json`, byte-identical to the running server's `/openapi.json`
as of this writing).

* **97 unique path templates**
* **100 method+path operations** — 65 GET, 32 POST, 2 PUT, 1 HEAD
* The single HEAD is the auto-generated sibling of `GET /api/health`, which is
  declared `@app.api_route("/api/health", methods=["GET", "HEAD"])`. Excluding
  it gives the **99 distinct GET/POST/PUT operations** the W01 shard counts.

Re-run: `curl -s http://127.0.0.1:8000/openapi.json | .venv/bin/python -c "import json,sys; d=json.load(sys.stdin); print(len(d['paths']), sum(len(v) for v in d['paths'].values()))"`

### Where the 100 come from

| registration site | mechanism | declarations | operations |
|---|---|---|---|
| `server.py` | `@app.<verb>(...)` | 84 | 84 |
| `server.py` | `@app.api_route("/api/health", methods=["GET","HEAD"])` | 1 | 2 |
| `src/ros/api.py` | `APIRouter(prefix="/api/ros")`, mounted `server.py:2685` | 7 | 7 |
| `src/consensus_edge/api.py` | `APIRouter(prefix="/api/consensus-edge")`, mounted `server.py:2696` | 5 | 5 |
| `src/sharp/service.py` | `app.add_api_route(...)` at `service.py:266` | 2 | 2 |
| **total** | | **99** | **100** |

### Four census methods, three of them wrong

| method | result | what it misses |
|---|---|---|
| `grep -cE '@app\.(get\|post\|put\|delete\|patch)' server.py` | **84** | `api_route`, both routers, both imperative registrations |
| + `@app.api_route` | 85 decls / 86 ops | both routers, both imperative |
| + both `APIRouter` modules | 98 ops | the 2 imperative sharp routes |
| `GET /openapi.json` | **100** | nothing |

A grep-based census undercounts by **16 operations (16%)**. The two hardest to
find are `GET /api/sharp/market` and `GET /api/sharp/market/audit`, which exist
only because `server.py` calls `_sharp_service.register_http_routes()` explicitly
after importing the module.

**That registration works, and it is now triple-guarded** (W15-F014,
`Implemented and verified`): the module-level call at `service.py:284`, the
explicit `server.py:12743` call, and a self-heal inside `cohort_status`
(`service.py:57`) that re-runs the idempotent registrar on every
`/api/sharp/cohort` request. `_server_app()` resolves the app under both
`server` and `__main__`, which is the production start mode. All five sharp paths
are present in the live schema, all five 401 anonymously and 200 authenticated.
The two roster-percentage routes were deliberately moved to plain `@app.get`
decorators in `server.py` because of this exact ordering hazard.

### Route surface by prefix

| prefix | ops | prefix | ops | prefix | ops |
|---|---|---|---|---|---|
| `/api/public/*` | 8 | `/api/bdvm/*` | 4 | `/api/rankings/*` | 2 |
| `/api/ros/*` | 7 | `/api/user/*` | 4 | `/api/waiver/*` | 2 |
| `/api/intel/*` | 7 | `/api/data/*` | 3 | `/api/angle/*` | 2 |
| `/api/scaffold/*` | 6 | `/api/auth/*` | 3 | `/api/league/*` | 3 |
| `/api/trade/*` | 6 | `/api/push/*` | 3 | 20 singletons | 20 |
| `/api/admin/*` | 6 | `/api/custom-alerts/*` | 3 | | |
| `/api/consensus-edge/*` | 5 | | | | |
| `/api/sharp/*` | 5 | | | | |

This table sums to **99** — it counts GET/POST/PUT only; the HEAD alias on
`/api/health` is the hundredth operation.

Re-run: `.venv/bin/python -c "import json,collections; d=json.load(open('docs/master-site-audit/evidence/openapi.json')); c=collections.Counter('/'.join(p.split('/')[:3]) for p,v in d['paths'].items() for m in v if m!='head'); print(sum(c.values()), c.most_common())"`

### What the routes actually return

`evidence/route-probe.json` probed all 100 operations anonymously and
authenticated; the 66 GET routes were exercised, the 34 non-GET ones were probed
separately (POST routes that mutate were deliberately not called — see the
protocol's read-only rule).

| authenticated status | count | anonymous status | count |
|---|---|---|---|
| 200 | 48 | 200 | 20 |
| 503 | 9 | 401 | 44 |
| 400 (missing required param) | 6 | 400 | 1 |
| 404 (no snapshot on disk) | 2 | 503 | 1 |
| 403 (`admin_required`) | 1 | | |

Every 503 is a documented, honest degradation, not a fault: 4 ×
`consensus-edge` (`feature_disabled`, flag off), 4 × `intel/*`
(`data_not_ready`, no intel snapshot in this container), 1 ×
`push/public-key` (`push_not_configured`). The 2 404s are
`/api/scaffold/{league,report}` with no snapshot file. The single 403 is
`/api/admin/guest-passes` correctly refusing the audit's non-allowlisted test
user.

Re-run: `.venv/bin/python -c "import json,collections; d=json.load(open('docs/master-site-audit/evidence/route-probe.json')); g=[r for r in d if not r.get('skipped')]; print(collections.Counter(r['auth']['status'] for r in g), collections.Counter(r['anon']['status'] for r in g))"`

### Routes nothing calls

**16 of 99 operations (16.2%) have no caller outside the test suite** — no
frontend fetch, no bridge consumer, no reference in `.github/workflows/`,
`deploy/` or `scripts/` (W01-F003, `Scaffolded only`,
`evidence/W01/dead-routes.txt`). Six are the `/api/scaffold/*` introspection
family. `POST /api/test-alert` has **zero references anywhere in the repository,
including tests**. Four of the sixteen have a Next bridge built for them —
dev plumbing for an endpoint nobody calls: `/api/angle/find`,
`/api/consensus-edge/health`, `/api/rankings/sources`,
`/api/sharp/roster-percentage/audit`.

`GET /api/metrics` is public with no in-repo consumer but is plausibly scraped by
an external monitor; W01-F003 classifies it ops rather than dead, which is the
right call.

One module registers nothing at all: `src/api/chat.py` ships a documented private
endpoint that no module imports and that declares no router. `/api/chat` returns
404 on the running server and is absent from the 100 live operations (W30-F011).

---

## 3. Pages and bridge routes

**41 pages** (`frontend/app/**/page.jsx`), **36 bridge routes**
(`frontend/app/api/**/route.js`).

Re-run: `find frontend/app -name page.jsx | wc -l; find frontend/app/api -name route.js | wc -l`

### Page inventory

| group | pages |
|---|---|
| board / value | `/rankings`, `/rankings/[position]`, `/edge`, `/trending`, `/players/compare`, `/idptc-rookies` |
| trade | `/trade`, `/trades`, `/arbitrage`, `/angle` |
| roster / season | `/rosters`, `/waivers`, `/draft`, `/phases`, `/league-comparison` |
| intel / market | `/bdvm`, `/consensus-edge`, `/market/sharp-tracker`, `/market/sharp-roster-percentage`, `/news` |
| public league (10) | `/league`, `/league/activity`, `/league/insider-trading`, `/league/franchise/[owner]`, `/league/player/[playerId]`, `/league/rivalry/[pair]`, `/league/week/[season]/[week]`, `/league/weekly/[…]`, `/league/articles/[season]/[week]`, `/league/articles/[…]/[mode]` |
| system / admin | `/admin`, `/settings`, `/more`, `/login`, `/tools/source-health`, `/tools/ros-data-health`, `/tools/trade-coverage` |
| shims and orphans | `/finder` → `/rankings`, `/intel` → `/league/insider-trading`, `/design` |
| landing | `/` |

**All 41 pages return 200 authenticated and 38 render an `<h1>`**
(W00-F009, `Implemented and verified`). Median DOM-ready 83 ms, max 609 ms across
the 41 authenticated loads. Of 55 console errors in the authenticated capture,
the only non-artifact ones are three distinct strings: a 401 on `/`, a 403 on
`/admin` (correct — the test user is not allowlisted) and a 503 on
`/consensus-edge` (correct — the flag is off). All 149 failed requests resolve to
`ERR_ABORTED` from the probe navigating away mid-flight, plus `sleepercdn.com`
avatar images this container cannot reach. Three redirects are by design:
`/finder` → `/rankings`, `/intel` → `/league/insider-trading`, `/rankings/[position]`
→ `/rankings?pos=QB`.

Re-run: `.venv/bin/python -c "import json,statistics; d=json.load(open('docs/master-site-audit/evidence/page-probe.json')); a=[e for e in d if e['mode']=='auth']; print(len(a), all(e['status']==200 for e in a), sum(1 for e in a if e['h1']), statistics.median(e['navMs'] for e in a), max(e['navMs'] for e in a), sum(len(e['consoleErrors']) for e in a), sum(len(e['failedRequests']) for e in a))"`
(W00-F009's prose says max 695 ms; re-measuring the artifact gives 609 ms. The
median, the 41/41, the 38 h1s and the 55/149 error counts all reproduce exactly.)

### Navigation vs. reality

Three pages are reachable from no navigation at all — `/finder`, `/intel` and
`/design`. The first two are self-documented legacy redirect shims and are fine.
`/design` is a live design-system gallery with no redirect, `robots: {index:
false}`, **present in the production Next build**, and gated only by session
presence (W01-F005, `Scaffolded only`).

Two of the four navigation surfaces ignore the `adminOnly` flag: `/more` and the
command palette render *Admin*, *Source Health*, *ROS Data Health* and *Trade
Coverage* to a session with `isAdmin: false`. Only `TopBar.jsx:58` and
`MobileChrome.jsx:106` call `systemItemsFor({isAdmin})`; `app/more/page.jsx` maps
`group.items` unfiltered and `CommandPalette.jsx:42` calls `paletteTargets()`
with no `isAdmin` argument available (W01-F004). This is a nav-visibility defect,
not an authorization bypass on its own — but see §9, where the pages behind those
links turn out to be gated on session presence rather than the admin allowlist.

There is **no private player page and no private team page**. The only routable
player and franchise pages (`/league/player/[playerId]`,
`/league/franchise/[owner]`) sit in the *public* league subtree and are served by
the isolated `src/public_league/` pipeline, which never reads the private
contract. On the private side a player opens `PlayerPopup.jsx` — a modal with no
URL, so the richest per-player view in the app cannot be linked, shared,
bookmarked or reached with browser back (W01-F007).

### Bridge coverage

All 36 bridges have a real backend counterpart; there are no orphan bridges
pointing at routes that do not exist (W01-F001, checked by path-template
normalisation across both sets). The gap is one-directional: 63 backend
operations have no bridge.

One bridge is defective in a way that reaches the browser: the
`/api/trade/suggestions` bridge is the only one of the four trade/angle bridges
that does not forward the session cookie, so the suggestions feed returns 401
through `:3000` while returning 200 with a full payload against `:8000`
(W09-F007, P1). Its abort timeout is 5 s where the finder's is 30 s — inverted
relative to the measured backend cost (suggestions 0.04 s, finder 5.48 s).

`/api/sharp/market/audit` is the only one of the five sharp routes with no bridge
(W15-F018). `/api/consensus-edge/player/{player_key}` likewise has none, while
`/top` and `/health` have bridges nothing calls (W14-F009).

---

## 4. `src/` — 26 packages, 300 modules

Re-run: `ls -d src/*/ | grep -v __pycache__ | wc -l; find src -name '*.py' | wc -l`

| package | modules | role |
|---|---|---|
| `api` | 32 | data contract, endpoints, feature flags, league registry, caches |
| `public_league` | 29 | isolated public-league pipeline (never reads the private contract) |
| `bdvm` | 27 | Brisket Dynasty Valuation Model — fundamentals engine |
| `ros` | 21 | rest-of-season projections and team strength |
| `news` | 17 | news providers, signal engine |
| `consensus_edge` | 17 | consensus-edge board (flag off) |
| `nfl_data` | 16 | nflverse ingest, realized points, usage |
| `league_intel` | 16 | league-adjusted overlay, TE premium, scarcity |
| `trade` | 15 | suggestions engine + arbitrage finder |
| `sharp` | 12 | sharp cohort, market, roster percentage |
| `intel` | 12 | insider-trading ledger and crawl |
| `scoring` | 11 | exact scoring, archetypes, backtesting |
| `platforms` | 10 | platform records/adapters |
| `roster_intel` | 9 | roster intelligence / gameplan |
| `utils` | 8 | config loading, name/position normalization |
| `league_comparison` | 8 | cross-league comparison |
| `canonical` | 7 | Hill curves, tiering, calibration |
| `model_registry` | 6 | challenger/promotion (script-only by design) |
| `playerctx` | 5 | player context enrichment |
| `identity` | 5 | player/pick master identity |
| `adapters` | 5 | frozen adapter contract + 3 live adapters |
| `backtesting` | 4 | backtest harness |
| `pool` | 2 | pool audit |
| `maintenance` | 2 | maintenance tasks |
| `data_models` | 2 | dataclass contracts |
| `league` | 1 | empty placeholder (README only) |

**Reachability.** An AST import closure from `server.py` (absolute, relative and
`importlib.import_module` edges, package `__init__` normalised) reaches **243 of
300** modules. **27 are reachable only from `scripts/`** — legitimate for refit,
crawl and fetch tooling. **30 are reachable from nothing**, notably
`src/api/chat.py`, `src/api/auction_power.py`, `src/api/espn_schema_drift.py`,
`src/news/unified_signal_engine.py`, `src/trade/correlation_matrix.py`,
`src/league_intel/{sim,twin,calibration}.py`, `src/backtesting/harness.py`,
`src/canonical/{confidence_intervals,rank_history_band}.py`, five
`src/nfl_data/*` modules and `src/platforms/sleeper.py` (W30-F022,
`evidence/W30/module-reachability.json`).

Re-run: `.venv/bin/python -c "import json; d=json.load(open('docs/master-site-audit/evidence/W30/module-reachability.json')); print(d['srcModules'], d['reachableFromServer'], len(d['scriptOnly']), len(d['neither']))"`

Two dead-code cases are worth naming because they invert the documented
relationship: `src/api/auction_power.py` has no Python caller, and the JS file
whose comment calls itself a "mirror" of it is the only live implementation
(W30-F013). And five of the seven functions in `src/canonical/calibration.py` —
including the entire legacy pick curve and `calibrate_canonical_values` itself —
have zero production references and are held alive only by their own tests
(W30-F015).

### The two entry points outside `src/`

* **`server.py`** — 12,954 lines. The FastAPI app, 85 inline route declarations,
  the auth/rate-limit middleware pair, the scrape scheduler, and the in-memory
  contract global.
* **`Dynasty Scraper.py`** — 7,741 lines. Loaded by `server.py:2141` via
  `importlib.util.spec_from_file_location`, not imported as a module. It is
  production, not legacy: `POST /api/scrape`, the scheduled loop, server startup
  and `scheduled-refresh.yml` all run it.

---

## 5. Data stores and snapshots

Nothing in `data/` is a database of record for player values. The value pipeline
is snapshot-driven: the scraper writes one JSON file, the server reads it at
startup, and everything else is a cache, a history log or a subsystem's own
store.

### The primary chain

```
21 external sources  ──►  Dynasty Scraper.py  ──►  data/dynasty_data_2026-08-04.json
                                                        1,074 raw players
                                                             │
                                       build_api_data_contract / _compute_unified_rankings
                                                             │
                                                   latest_contract_data (module global)
                                                        1,092 contract rows
                                                   contractVersion 2026-03-10.v2
```

Re-run: `curl -s -b /tmp/arch-cookies.txt "http://127.0.0.1:8000/api/data?view=array" | .venv/bin/python -c "import json,sys; d=json.load(sys.stdin); print(len(d['playersArray']), d['contractVersion'], d['meta']['leagueKey'], d['meta']['scoringProfile'])"`
→ `1092 2026-03-10.v2 dynasty_main superflex_tep15_ppr1`

The 1,074 → 1,092 expansion is picks and pool rows the contract adds on top of
the scraped player set.

### Stores on disk

| store | kind | size / state here | what it holds |
|---|---|---|---|
| `data/dynasty_data_2026-08-04.json` | JSON snapshot | 1,074 players, 2 site entries | the live scrape the server booted from |
| `data/ros/` | JSON, **git-tracked** | 877 MB | rest-of-season projections and history |
| `data/nfl_data_cache/` | JSON + `.meta.json` | 648 MB, 7 entries | nflverse download cache |
| `data/raw_sources/` | JSON snapshots | 100 MB | per-run raw source captures |
| `data/public_league/` | JSON | 18 MB | public-league pipeline outputs |
| `data/session_store.sqlite` | SQLite | — | sessions |
| `data/user_kv.sqlite` | SQLite | — | per-user state, watchlists, alert state |
| `data/guest_passes.sqlite` | SQLite | — | guest passes |
| `data/intel/ledger.sqlite3` | SQLite | present | insider-trading / platform ledger |
| `data/source_value_history.jsonl` | JSONL | — | per-source value history |
| `data/snapshots/`, `data/identity/`, `data/player_map/`, `data/scrape_state/`, `data/validation/`, `data/idp_fit_snapshots/`, `data/league_comparison_cache/`, `data/comparison/`, `data/raw/`, `data/nfl_data/` | mixed | — | subsystem stores |
| `exports/latest/` + `exports/archive/` | release artifacts | **140 files git-tracked** | `dynasty_data.js`, `dynasty_full.csv`, `dynasty_values.csv`, `manifest.json` |

Re-run: `du -sh data/nfl_data_cache data/ros data/public_league data/raw_sources; git ls-files exports | wc -l`

### What is absent in this container — and what that does and does not prove

| absent path | consequence | status |
|---|---|---|
| `data/bdvm/` | `/api/bdvm/*` answers with no projection snapshot | **Blocked by data**, not Missing |
| intel snapshot for `dynasty_main` | 4 × `/api/intel/*` return 503 `data_not_ready` | **Blocked by data** |
| `nfl_data_py` package (deliberately excluded from `requirements.txt`) | `nflverse_direct` fallback is the live path | by design |

These are pre-declared non-findings in `AUDIT_PROTOCOL.md`. **We could not test
the BDVM engine or the intel subsystem end to end in this container.** That is a
gap in coverage, not evidence that either is broken — and it is not the same
result as the defects reported elsewhere in this audit.

---

## 6. Caches

Roughly two dozen cache globals across `server.py`, `src/api/`,
`src/league_comparison/` and `src/roster_intel/`, in four layers:

| layer | examples | notes |
|---|---|---|
| the contract itself | `latest_contract_data` | shared mutable module global; nothing may mutate it in place (the valuation overlay works on shallow copies for exactly this reason) |
| encoded-payload byte caches | `_PUBLIC_CONTRACT_BYTES_CACHE`, `_OVERLAY_RESPONSE_CACHE`, `_OVERRIDES_RESPONSE_CACHE` | serve pre-gzipped bytes per view |
| in-process TTL caches | `_LEAGUE_CONTEXT_CACHE`, `_LEAGUE_ROSTER_CACHE`, `_DRAFT_CAPITAL_CACHE`, `_TEAMS_CACHE`, `sleeper_overlay._CACHE`, `gameplan._BUNDLE_CACHE`, `bdvm_api._VALUES_CACHE` | mixed TTLs, mostly unlocked |
| disk caches | `data/nfl_data_cache/`, `data/league_comparison_cache/` (7-day) | unbounded |

Re-run: `grep -rnoE "^_[A-Z_]*CACHE[A-Z_]*" server.py src/api/*.py src/league_comparison/*.py src/roster_intel/*.py | sort -u`

Four cache defects change the shape of the runtime:

* **No stampede protection on the slowest cold paths** (W26-F005). Four caches
  hold their lock across the dict get/put only, never across the build:
  `bdvm_api._context_for` / `_schedule_for` (N concurrent cold requests each
  launch a full nflverse download — 433 MB per attempt, measured 47,994 ms),
  `bdvm_api.get_bdvm_values`, `league_comparison.service.build_comparison`
  (7-day disk cache, **no lock at all**, 26,577 ms cold), and
  `gameplan.get_league_bundle`.
* **The nflverse disk cache has no last-known-good fallback and no size bound**
  (W26-F007). `cache.get()` returns `None` the instant the entry passes TTL, and
  every ingest wrapper then returns `[]` if the refetch fails — a perfectly
  usable 61.7 MB file on disk is ignored, so a transient nflverse outage takes
  `/api/player/{id}/realized` and every ROS/BDVM consumer from full data to no
  data with no intermediate degradation. There is no prune, no LRU and no
  total-bytes cap; the finding measured 590 MB across 7 entries, three of them
  byte-identical copies of the same 61.7 MB file under three keys. Re-measured
  while writing this map: **648 MB**, same 7 entries — which is the growth the
  finding predicts.
* **`_LEAGUE_CONTEXT_CACHE` is a single global slot with no league key**
  (W26-F018). `_resolve_league_context()` takes no league argument, resolves via
  `get_sleeper_league_id()` (which returns the *default* league) and caches
  globally with a 1-hour TTL. Any second league on the same scoring profile reads
  the default league's roster count and TE bonus.
* **`/api/draft-capital` serves auth-varying bodies with no `Vary: Cookie`**
  (W22-F009). It stamps `Cache-Control: private, max-age=60,
  stale-while-revalidate=300` and `Vary: Accept-Encoding` only, while returning
  two different bodies for the same URL depending on the session cookie. A
  browser that loaded the public `/league` draft-capital tab and then signed in
  serves the redacted body from its private cache for up to 60 s.

Separately, `/api/bdvm/*` and `/api/valuation/league-adjusted` send **no**
`Cache-Control` and **no** `ETag` (W26-F009), so a 48,555-byte league-scoped
payload measured at 7,267 ms cold is re-requested and re-serialised on every
navigation.

**What works here:** the byte-cache layer is effective. Repeat-latency
measurement over five consecutive authenticated calls shows
`/api/draft-capital` going 2.735 s → 0.005 s and `/api/data?view=app` steady at
0.007-0.009 s. Cold-path cost, not warm-path cost, is the problem.

Re-run: `head -12 docs/master-site-audit/evidence/W26/repeat-latency-auth.txt`

---

## 7. External sources

**21 ranking sources** feed the live contract. Row counts served, from the
running server:

| source | rows | source | rows | source | rows |
|---|---|---|---|---|---|
| `idpTradeCalc` | 770 | `flockFantasySf` | 378 | `dlfSf` | 277 |
| `ktcSfTep` | 425 | `fantasyCalc` | 377 | `draftSharksIdp` | 273 |
| `fantasyProsSf` | 412 | `fantasyNavigatorSf` | 371 | `fantasyProsIdp` | 166 |
| `pfkDynasty` | 395 | `yahooBoone` | 364 | `dlfIdp` | 137 |
| `draftSharks` | 381 | `dynastyDaddySf` | 358 | `flockFantasySfRookies` | 70 |
| | | `otcffbSf` | 342 | `dlfRookieSf` | 52 |
| | | `fantasyProsFitzmaurice` | 298 | `dlfRookieIdp` | 24 |
| | | `dynastyNerdsSfTep` | 293 | | |
| | | `idpShow` | 279 | | |

Re-run: `curl -s http://127.0.0.1:8000/api/status | .venv/bin/python -c "import json,sys; d=json.load(sys.stdin); print(len(d['served_source_coverage']), d['served_source_coverage'])"`

Outbound hosts referenced across `Dynasty Scraper.py`, `scripts/*.py`,
`src/news/` and `src/nfl_data/`, by reference count:

`www.fantasypros.com` (13), `api.sleeper.app` (12), `datawrapper.dwcdn.net` (8),
`www.draftsharks.com` (7), `dynastyleaguefootball.com` (7), `keeptradecut.com` (6),
`www.theidpshow.com` (5), `sports.yahoo.com` (4), `site.api.espn.com` (4),
`api.flockfantasy.com` (4), `otcffb.com` (3), `github.com` (3, nflverse releases),
`g.espncdn.com` (2), `fantasy-navigator-latest.onrender.com` (2),
`dynasty-daddy.com` (2), `api.fantasycalc.com` (2), plus single references to
`idptradecalculator.com`, `myffpc.com`, `playforkeepsdynasty.com`,
`www.dynastynerds.com`, `docs.google.com` and a Supabase endpoint.

Re-run: `grep -rhoE "https://[a-z0-9.-]+\.[a-z]{2,}" "Dynasty Scraper.py" scripts/*.py src/news/*.py src/nfl_data/*.py | sed 's|https://||' | sort | uniq -c | sort -rn`

**21 dedicated fetchers** live under `scripts/` as `fetch_*.py` (18) and
`crawl_*.py` (4, sharp/FFPC). Source ingestion is *not* in `src/adapters/` —
that package holds the frozen contract (`base.py`, imported by tests only) plus
exactly three live adapters: `scraper_bridge_adapter.py`, `sleeper_trending.py`
and `ktc_crowd_faab.py`.

---

## 8. Scheduled work

Three independent schedulers, and they are not equivalent in reliability.

### GitHub Actions — 22 workflows, 14 cron entries

| workflow | cron (UTC) | workflow | cron (UTC) |
|---|---|---|---|
| `public-league-warmup.yml` | `*/20 * * * *` | `smoke-test.yml` | `15 6 * * *` |
| `scheduled-refresh.yml` | `42 */2 * * *` | `e2e.yml` | `23 6 * * *` |
| `prod-e2e-smoke.yml` | `17 */4 * * *` | `audit-identity-matches.yml` | `17 8 * * *` |
| `health-check.yml` | `17 */6 * * *` | `intel-refresh.yml` | `10 9 * * *` |
| `refit-hill-curves.yml` | `17 6 * * 2` | `audit-rank-form-drift.yml` | `41 7 * * 2` |
| `consensus-edge-revalidate.yml` | `40 5 * * 3` | `audit-dropped-sources.yml` | `23 7 * * 1` |
| `weekly-narratives.yml` | `0 14 * * 2` + `0 13 * * 3` | | |

The remaining 8 are event-triggered (`deploy.yml`, `pr-validation.yml`,
`claude.yml`) or manual sharp-operations workflows.

Re-run: `grep -rn "cron:" .github/workflows/*.yml`

### systemd — 17 timers + 2 long-running services

Timers (all `deploy/systemd/*.timer.template` unless noted): sharp discovery
04:20 → sharp records 04:50 → FFPC sharp 05:20 → sharp rosters 05:50 → sharp
activity 06:30 (a deliberate dependency chain: find managers, then their
results, then what they own); `dynasty-dlf-fetch` and `dynasty-idpshow-fetch` on
even hours; `dynasty-playerctx-refresh` Tue 05:40; `dynasty-bdvm-refresh` Tue
06:10; `dynasty-reception-depth` Wed 07:20; `dynasty-consensus-edge-snapshot`
daily 07:30; `dynasty-custom-alerts` every 2 h at :13;
`dynasty-signal-alerts`; `dynasty-healthcheck`; `riskit-backup` and
`riskit-backup-restore-test`; plus `chase-upside-ffpc-sharp` in
`deploy/ffpc-systemd/`. Services: `dynasty.service` (backend) and
`dynasty-frontend.service` (Next) — **production needs both**, because nginx
requires the Next upstream.

Re-run: `ls deploy/systemd/ deploy/ffpc-systemd/`

Two scheduling defects:

* **The FFPC sharp crawl ships as two byte-identical timer templates in two
  directories** with two different installers and the same 05:20 UTC schedule
  (W23-F013). `diff deploy/systemd/dynasty-ffpc-sharp.timer.template
  deploy/ffpc-systemd/chase-upside-ffpc-sharp.timer.template` returns nothing.
  On a host where both installers have run, the crawl fires twice in the same
  15-minute randomized window every day.
* **`dynasty-custom-alerts.timer`'s `Description` says "Hourly custom-alert
  sweep" while its `OnCalendar` is `*-*-* 0/2:13:00`** — every two hours
  (W23-F014). The body comment two lines below says "Fire every two hours", so
  the file contradicts itself, and `Description` is the string
  `systemctl list-timers` shows an operator.

### Actions vs. systemd reliability

The GitHub-Actions 2 h refresh cron **misses roughly a quarter of its cycles
while the prod systemd fetch timers hit every one** (W05-F012). Over the 26.7 h
window 2026-08-03T15:37Z → 2026-08-04T18:21Z, the workflow's own freshness-stamp
commits show 10 runs where 13-14 are scheduled — gaps of 2.87, 1.85, 1.53, 2.08,
4.00, 3.50, 3.75, 4.00, 3.13 hours. Over the same window `dlf` (:27) and
`idpShow` (:32) on every even UTC hour landed 14/14 with zero misses.

Re-run: `git log --since='2026-08-02' --format='%s' -- data/scrape_state | grep 'freshness stamps'`

### `scripts/` — 89 entry points, 28 with no scheduler

Of 89 top-level scripts, **39 are reachable** from a workflow, systemd template,
deploy script, Makefile/`.bat`, another script or `src/`; **28 have no such
reference at all**; 3 more are referenced only by tests (W23-F015,
`evidence/W23/schedule-map.csv`). Most of the 28 are legitimately one-off
research (`backtest_*`, `measure_*`). The ones that matter are five **validators**
that no scheduler runs and no gate calls:
`validate_sharp_roster_percentage.py`, `validate_va_v2.py`,
`validate_scoring_fit.py`, `board_invariance_hash.py` and `golden_board.py`.

Re-run: `awk -F, 'NR>1 && $2=="none" && ($5=="NOTHING"||$5=="TESTS ONLY")' docs/master-site-audit/evidence/W23/schedule-map.csv | wc -l`

### The refresh pipeline's guard ordering

`scheduled-refresh.yml` commits the data (step 8) and dispatches the production
deploy (step 9), **then** runs the DLF-freshness assertion and both watchdogs
(steps 10-13, all `if: always()`) (W23-F010). Only step 6, "Validate scrape
sanity", is a true pre-commit gate. When a post-deploy guard goes red the
workflow opens a `stale-sources` tracking issue and stops — there is no revert,
no re-deploy of the prior commit, and no call to `deploy/rollback`.

Two scrape-lifecycle defects compound this:

* **A partial scrape the promotion guard REFUSES to publish is recorded as a
  success** (W23-F002, P1). On the blocked branch `server.py:2380` calls
  `_mark_scrape_success(...)` before returning the old data — setting
  `last_success_at`, clearing `error`, incrementing `scrape_count`, emitting
  `scrape_succeeded` and appending `outcome='success'` to `scrape_history`. The
  only distinguishing artifact is a `partial_scrape_blocked` warning event.
  `/api/health`, `/api/metrics` and `_scrape_success_rate_24h()` all count it
  clean.
* **The "fewer than half the sites returned" guard degenerates to "block only on
  total loss"** (W23-F003 — **rescoped P1 → P2 by the verifier**, verdict in
  `evidence/verify/verdicts-B*.jsonl`). The headline reproduces verbatim:
  `server.py:2358-2363` computes `total_sites = len(result['sites'])` and blocks
  on `site_count < total_sites/2`; `sites` is a 2-element list on the live
  snapshot, so the predicate is `site_count < 1.0` and fires only on total loss.
  The path is live (`initial_scrape` at `server.py:2619`, `schedule_loop` at
  `:2622`).

  **The author's two supporting claims did not survive re-testing, and this
  document does not repeat them.** (a) The claim that `sites_meta` is built from
  "the sources that actually ran, so a skipped source shrinks the denominator
  with the numerator" is wrong: `Dynasty Scraper.py:4251` defines
  `active_sites` as the *config-enabled* list, fixed before any run outcome, and
  an enabled site that fails still emits an entry with `playerCount 0` —
  shrinking the numerator only, which is what the guard wants. `KTC_TradeDB` and
  `KTC_WaiverDB` are absent from `sites` because they are KTC sub-fetches, not
  `SITES` keys. (b) The claim that "a scrape in which 20 of 21 sources collapse
  promotes cleanly to production" is false for the production refresh path:
  `scheduled-refresh.yml:190` runs the scraper directly — `server.py`'s guard is
  not in that pipeline — and gates the commit step on
  `scripts/validate_scrape_sanity.py`, a per-source CSV gate that exits 1 on a
  >50% row collapse, an all-zero value column, or a sub-minimum row count.

  **The verified defect that remains** is narrower and still real: on the
  in-process path only ~6 sources refresh at all, so the escape it permits is
  "one of KTC / IDPTradeCalc dies and the board promotes on the survivor" —
  `1 < 1.0` is False. KTC is the TE++ basis anchor and one of the two pick
  markets, so that matters. Realized impact today is **zero**: no such event is
  present in the live snapshot.

---

## 9. Feature flags

**15 flags** in `src/api/feature_flags.py`, each carrying a self-documented
`_GATE_STATUS` classification. Live state:

| flag | enabled | gate | flag | enabled | gate |
|---|---|---|---|---|---|
| `nfl_data_ingest` | ✅ | LIVE | `unified_id_mapper` | ❌ | NO_GATE |
| `realized_points_api` | ✅ | LIVE | `value_confidence_intervals` | ❌ | NO_GATE |
| `monte_carlo_trade` | ✅ | LIVE | `positional_tiers` | ❌ | NO_GATE |
| `te_basis_conversion` | ✅ | LIVE | `dynamic_source_weights` | ❌ | NO_GATE |
| `idp_scoring_fit` | ✅ | LIVE | `usage_signals` | ❌ | UNREACHABLE |
| `reception_scoring_fit` | ✅ | LIVE | `espn_injury_feed` | ❌ | UNREACHABLE |
| `bdvm_engine` | ✅ | LIVE | `depth_chart_validation` | ❌ | SCRIPT_ONLY |
| `consensus_edge` | ❌ | LIVE | | | |

Re-run: `curl -s http://127.0.0.1:8000/api/status | .venv/bin/python -c "import json,sys; f=json.load(sys.stdin)['featureFlags']; print(len(f)); [print(k, v['enabled'], v['gateStatus']) for k,v in f.items()]"`

**The registry's own honesty claim is true, and this audit proved it at runtime**
(W01-F009, `Implemented and verified`). `_GATE_STATUS` claims 7 of 15 flags
cannot change a response. A second FastAPI process was booted on port 8001 (port
8000 untouched, `run_scraper` neutralised before uvicorn start) with all seven
claimed-inert flags forced ON, and diffed against a defaults boot:

```
rows compared                                        1092
rows with a changed rankDerivedValue                    0
rows with a changed canonicalConsensusRank              0
new fields appearing in playersArray                    0
fields disappearing from playersArray                   0
```

The only non-timestamp difference across the whole 12 MB `view=full` payload was
`players.*.rankChange`, and a third defaults boot reproduced the same change —
proving it is a function of accumulated rank-history snapshots since boot, not of
any flag. All 8 LIVE flags were separately shown to change a response;
`te_basis_conversion` moves 135 of 1,092 rows' `rankDerivedValue` and 627 rows'
`canonicalConsensusRank`.

Re-run: `evidence/W01/flag-differential.md` carries the full four-boot procedure
and `evidence/W01/flag-differential-rankvalues.json` the row diff.

**The one thing wrong with the flag layer is documentation, in two places.**
`server.py`'s router-mount comment says `consensus_edge` defaults **ON** since
2026-08-04; `feature_flags.py:260` sets it `False` under a 20-line ADR-023
rationale, and every gated route 503s (W00-F004, W25-F001). The stale comment
sits at the registration site a reader hits first. Separately, the docstrings in
`feature_flags.py` and `tests/api/test_feature_flag_reachability.py` both say
"13 registered flags" where `_DEFAULTS` now holds 15 — the 7/15 ratio and every
per-flag classification are current; only the prose total is stale.

The consensus-edge OFF state is itself correct and self-consistent (W14-F007,
`Implemented and verified`): both committed validation runs carry
`decision.recommendation: "do not ship yet"`, `score.COMPONENT_VALIDATION` marks
all three components `validated: false`, and the live stack returns 503 on
players/top/health/player and 200 on methodology exactly as ADR-012 specifies.

---

## 10. The public/private boundary

Two independent gates, one per process. They are not the same list and do not
need to be, but four consumers of the *page* half currently disagree.

### Page gate — Next only

`frontend/middleware.js` + `frontend/lib/public-routes.js` are the **only** page
auth gate. Since #555, `server.py` registers no page routes at all; a page path
requested from `:8000` returns a JSON 404.

```
PUBLIC_EXACT        = { "/", "/login", "/draft-capital" }
PUBLIC_PREFIXES     = [ "/league" ]
PRIVATE_EXCEPTIONS  = [ "/league/insider-trading" ]   # checked BEFORE prefixes
ALWAYS_ALLOWED      = /_next, /api, /static, robots.txt, sitemap.xml,
                      manifest.webmanifest, favicon.ico, sw.js
```

Measured: **31 of 41 pages 307 to `/login?next=…` anonymously; 10 serve 200** —
`/`, `/login` and the eight public `/league/*` pages.

Re-run: `curl -s -o /dev/null -D- http://127.0.0.1:3000/rankings | head -2` → `307` + `location: /login?next=%2Frankings`

Three defects on this boundary:

* **`frontend/app/sitemap.js` is an unwired fourth consumer** (W22-F006). It
  imports nothing from `public-routes.js` and hardcodes its own list containing
  `/trades` — the one route whose privacy that module's header spends a paragraph
  explaining. The live `sitemap.xml` publishes `https://chaseupside.com/trades`
  while middleware 307s that path to `/login`. Separately, `robots.js` spreads
  `PUBLIC_PREFIXES` and ignores `PRIVATE_EXCEPTIONS`, so `robots.txt` is
  `Allow: /league/` + `Disallow: /` with no `Disallow: /league/insider-trading`.
* **Page-side authorization is session presence, not the admin allowlist**
  (W22-F007). `middleware.js` checks cookie presence only, so `/admin` and all
  three `/tools/*` pages render for any session — which is what makes the nav
  leak in W01-F004 consequential rather than cosmetic. Server-side, the six
  `/api/admin/*` routes correctly 403 a non-admin, but operator-grade actions
  *outside* that prefix have no allowlist check at all: `POST /api/scrape` never
  calls `_require_admin_session`, `POST /api/test-alert` is declared with no
  `Request` parameter so it structurally cannot check anything, and
  `POST /api/intel/refresh` accepts any session with only a per-user cooldown.
* **`/login?next=/\evil.com` is a working post-authentication open redirect**
  (W22-F001, P1). `_sanitize_next_path` rejects `http://`, `https://`, a leading
  `//`, a non-`/` prefix and CR/LF — but not a backslash. Next resolves the href
  with the WHATWG URL parser, which normalises `\` to `/`, so
  `new URL('/\\evil.com', location.href)` is `http://evil.com/`. Driven end to
  end in Chromium against the real login form, the browser navigated to
  `http://evil.com/` immediately after a successful login.

### API gate — FastAPI only

`_private_api_gate` (`server.py:2823`) is default-deny: any `/api/*` without a
session 401s unless the path is in one of three allowlists.

| allowlist | members |
|---|---|
| `_PUBLIC_API_EXACT` (12) | `/api/health`, `/api/status`, `/api/uptime`, `/api/metrics`, `/api/leagues`, `/api/rankings/sources`, `/api/auth/{status,login,logout}`, `/api/scaffold/status`, `/api/draft-capital`, `/api/news` |
| `_SELF_AUTHED_API_EXACT` (4) | `/api/signal-alerts/run`, `/api/custom-alerts/run`, `/api/test/create-session`, `/api/push/public-key` — bearer-token auth of their own |
| `_PUBLIC_API_PREFIXES` (2) | `/api/public/league*`, `/api/league/articles*` |

That produces the 20 anonymous 200s in §2. **The default-deny half works** — 44
of 66 probed GETs 401 anonymously, including every value-bearing private route.
Three problems with what is *on* the allowlist:

* **`/api/status`, `/api/health` and `/api/scaffold/status` hand deploy internals
  to anonymous callers** (W22-F005). `/api/leagues` honours the no-Sleeper-IDs
  invariant exactly (808 bytes, zero Sleeper ids), but `/api/status` emits
  `leagues[].sleeperLeagueId` for both registry leagues plus absolute deploy
  paths, the complete `featureFlags` map with `gateStatus`, `served_source_coverage`
  naming all 21 sources with per-source row counts, `source_health.source_failures`
  with free-text reasons, `run_events` and payload byte sizes.
  `/api/scaffold/status` adds absolute snapshot filenames and timestamps — and
  has **no caller of any kind**: no UI, no bridge, no ops, no test (W01-F010).
* **`/api/draft-capital` is public with a redaction that is correct but
  under-scoped** (W00-F001 P1, W10-F010). The redaction itself works: the
  anonymous response is 17,400 bytes against 25,472 authenticated,
  `rookieName`/`rookiePos`/`rookieKtcValue`/`rookieKtcDollar`/`rookieIdpDollar`
  are stripped and `rookieBoardRedacted: true` is stamped. But of the three field
  groups the code comment calls "already viewable on Sleeper", only two are —
  `dollarValue`/`adjustedDollarValue`/`originalDollarValue` come from column L of
  `CSVs/Draft Data.xlsx`, a hand-maintained valuation Sleeper does not publish.
  The anonymous call also takes 13,188 ms cold.
* **The public-league payload's safety guard is a name blocklist, so it is blind
  to derived values** (W22-F008). `assert_public_payload_safe` walks every dict
  key at every depth against a 39-name blocklist, and 0 hits were confirmed
  across ten anonymous endpoints totalling 2.6 MB — the literal claim holds. But
  `/api/public/league` serves 191 graded trades / 393 graded sides anonymously,
  and each grade letter is a five-band quantisation of
  `package_value(received)/package_value(sent)` computed from the private
  contract's values. A value derived from a blocked field and stored under an
  unblocked name passes the guard.

**What the public-league boundary gets right** (W19-F011): a recursive key scan
of the 2,081,957-byte anonymous response for value/grade/score/dollar/price/
rank/edge/proj/tier/confidence/recommend/target/buy/sell/surplus/market finds
**no** `rankDerivedValue`, no `canonicalSiteValues`, no edge signals, no trade
suggestions and no dollar values. The isolated `src/public_league/` pipeline does
what it claims. Its real exposures are the trade grades above and raw Sleeper
league/owner IDs — which contradicts CLAUDE.md's "no Sleeper IDs leaked" claim,
though that claim is written about `/api/leagues`, which honours it.

Finally, **the rate limiter that is supposed to protect the whole public surface
keys on an unvalidated client-supplied header** (W22-F002, P1).
`_client_ip_from_request` returns the first comma-separated entry of
`X-Forwarded-For` whenever present, with no trusted-proxy check; nginx sets
`X-Forwarded-For $proxy_add_x_forwarded_for`, which *appends* `$remote_addr`, so
in production the first entry is entirely attacker-controlled. Measured on a
second backend without `RATE_LIMIT_BYPASS_IPS`: the real client IP was driven to
a hard 429, then 20 requests from that same socket with rotating
`X-Forwarded-For: 203.0.113.N` all returned 200. Compounding it, login has no
throttle of its own (W22-F003): 200 wrong-password POSTs with a rotating header
landed 200 × 401 in 0.9 s with zero 429.

---

## 11. Request path, end to end: one authenticated load of `/rankings`

```
 1  browser        GET https://chaseupside.com/rankings   Cookie: jason_session=…
 2  nginx          location /  →  proxy_pass http://dynasty_frontend      (:3000)
 3  Next middleware  isInfrastructurePath? no · isPublicPath("/rankings")? no
                     session cookie present → allow
                     (anonymous → 307 /login?next=%2Frankings — measured)
 4  Next App Router  streams the RSC shell for app/rankings/page.jsx
 5  hydration        PrivateAppShell mounts; AppShell.jsx:61 fires the
                     unconditional contract fetch
 6  9 XHRs           each goes back out to nginx → location /api/ → :8000
 7  FastAPI          rate limiter (X-Forwarded-For keyed)
                     _private_api_gate → not on the allowlist → session required
 8  handler          reads latest_contract_data (module global, built at startup
                     from data/dynasty_data_2026-08-04.json via
                     _compute_unified_rankings); response bytes come from the
                     per-view byte cache
 9  wire             ?view=array  6,515,205 raw / 669,214 gzip
10  client           buildRows() materializes rows verbatim from backend stamps —
                     no value is recomputed, no rank engine runs
11  paint            230 data rows
```

The nine API calls `/rankings` issues, and their dev-topology fate:

| call | Next bridge exists? | under `next dev` |
|---|---|---|
| `/api/dynasty-data?view=array` | yes | 200 |
| `/api/rankings/overrides?view=delta` | yes | 200 |
| `/api/auth/status` | yes | 200 |
| `/api/news?limit=100` | yes | 200 |
| `/api/bdvm/values` | yes | 200 |
| `/api/health` | **no** | **404** |
| `/api/leagues` | **no** | **404** |
| `/api/terminal?windowDays=30` | **no** | **404** |
| `/api/user/state` | **no** | **404** |

Five of nine bridged, four not. In production all nine reach FastAPI.

Measured through the production topology (desktop, request interception):

| metric | value |
|---|---|
| DOMContentLoaded | 211 ms |
| First Contentful Paint | 304 ms |
| load | 492 ms |
| resources | 71 |
| transferred (all 71 resources) | 1,040,158 b |
| decoded (all 71 resources) | 11,767,159 b |
| — of which the player contract | **671,811 b wire / 6,515,205 b decoded** |
| unique API calls | 9 (zero duplicates) |
| table rows rendered | 231 `<tr>` (W26 DOM probe); the protocol's interception capture counts 230 data rows |

Re-run: `.venv/bin/python -c "import json; d=json.load(open('docs/master-site-audit/evidence/W26/page-ux-probe.json')); r=[e for e in d if e['route']=='/rankings' and e['viewport']=='desktop'][0]; print(r['timing'], r['apiUnique'])"`

**The contract fetch is not specific to `/rankings`.** `AppShell` fetches the
full player contract on **every** private page, including pages that render no
player row (W26-F002 — **rescoped P1 → P2 by the verifier**). `AppShell.jsx:33-75`
gates the fetch on exactly one prefix list, `PUBLIC_ONLY_ROUTE_PREFIXES =
['/league']`, added for data-leak reasons, so `PrivateAppShell` calls
`useDynastyData()` on every other route — including board-less pages and Next's
not-found. The verifier re-measured a cold `/news` hard load and confirmed it
fetches `/api/dynasty-data?view=array`. 30 pages are affected.

**Three parts of the author's version did not survive re-measurement, and this
document does not repeat them.**

1. **The 12.5 MB per-page figures are not the contract's cost.** They are the sum
   of `decodedBodySize` over *all* resource entries (`w26_probe.py:245`). The
   player contract is **671,811 b on the wire / 6,515,205 b decoded**. A further
   369,861 b wire / 3,897,831 b decoded is a *second* request, `POST
   /api/rankings/overrides?view=delta`, which is conditional on the user having
   customized source weights — a default user never posts it
   (`dynasty-data.js:2017-2035`). The remaining ~1.3 MB decoded is app JS/CSS any
   page must load.
2. **It is not "the dominant cost of every navigation".** `AppShell` lives in the
   root layout and does not remount on client-side navigation, and
   `dynasty-data.js:1413-1440` adds a module-level cache with a 30 s TTL plus
   in-flight dedupe. Measured: clicking from `/rankings` to `/news` produced
   **exactly one** `/api/dynasty-data` request in total. The per-page cost in the
   original probe is an artifact of `page.goto` per route.
3. The flagship `/terminal` example is a Next 404 (no directory under
   `frontend/app`), so its cost is a cold-context cost only.

**The verified defect**: a cold entry on a board-less page pays ~672 KB over the
wire and a 6.5 MB JSON parse it does not use, to keep global search and the
player popup working. No number a user acts on is wrong, and the module cache
bounds the repeat cost at zero additional bytes per in-session navigation.

For scale, the available views:

| view | raw | gzip |
|---|---|---|
| (full) | 11,953,535 | 1,176,186 |
| `?view=compact` | 7,363,760 | 764,718 |
| `?view=array` | 6,514,536 | 669,214 |
| `?view=app` | 5,818,304 | 576,583 |
| `?view=startup` | 5,817,724 | 576,383 |

Re-run: `cat docs/master-site-audit/evidence/W26/data-view-sizes.txt`

---

## 12. What works

Stated plainly, because a map of only defects is not a map.

| claim | evidence |
|---|---|
| All 41 pages return 200 authenticated; 38 render an `<h1>`; median DOM-ready 83 ms | W00-F009 `Implemented and verified`, `evidence/page-probe.json` |
| The default-deny API gate holds: 44 of 66 probed GETs 401 anonymously, including every value-bearing private route | `evidence/route-probe.json` |
| The feature-flag registry's self-assessment is accurate — 7 of 15 flags provably cannot change a response, proved by a runtime differential over 1,092 rows, not by reading imports | W01-F009 `Implemented and verified` |
| The consensus-edge OFF state is correct and internally consistent with its committed "do not ship yet" gate | W14-F007 `Implemented and verified` |
| Both imperatively registered sharp routes are present in the live app and triple-guarded against the ordering hazard | W15-F014 `Implemented and verified` |
| No orphan bridge routes — all 36 point at a backend route that exists | W01-F001, path-template normalisation across both sets |
| The public-league pipeline leaks no private valuation, ranking or recommendation field into its 2.08 MB anonymous payload | W19-F011, recursive key scan |
| `/api/leagues` honours the no-Sleeper-IDs invariant exactly — 808 bytes, zero ids | W22-F005 |
| The warm-path byte caches work: `/api/draft-capital` 2.735 s → 0.005 s over five consecutive calls | `evidence/W26/repeat-latency-auth.txt` |
| Frontend test suite: 104 files / 1,754 tests, all passing | `evidence/vitest.txt` |
| The audit wrote nothing outside `docs/master-site-audit/` | `evidence/source-corpus-mtimes-BEFORE.txt`, re-checked at close |

---

## 13. What this map could not establish

| gap | why | what would close it |
|---|---|---|
| BDVM engine behaviour end to end | `data/bdvm/` does not exist in this container — **Blocked by data**, not Missing | run `scripts/bdvm_build_baseline.py` against a real season, then re-probe `/api/bdvm/*` |
| Intel / insider-trading subsystem | no intel snapshot for `dynasty_main`; 4 routes 503 `data_not_ready` | populate the snapshot, re-run `route-probe` |
| The 34 non-GET operations' behaviour | the protocol forbids POSTing to mutating routes (`/api/user/*`, `/api/admin/*`, `/api/*/refresh`, `/api/*/run`) | a disposable staging instance |
| Whether production's nginx config matches `deploy/nginx/chaseupside-proxy.conf` | no deploy-side access from this container; all topology claims are read from the committed config | fetch the live `nginx -T` output |
| Whether external monitors consume `/api/metrics` | no in-repo consumer; classified ops rather than dead on that basis | check the monitor's config |
| Whether the 22 GitHub workflows all still run | only the commit stream of `scheduled-refresh.yml` was inspected | `gh run list` per workflow |
| Whether `server.py`'s in-process scrape guard is reachable in production at all | if only `scheduled-refresh.yml` ever promotes, W23-F003's guard is unreachable and drops from a defect to `Scaffolded only` — the verifier flagged this as the deciding question | check `dynasty.service` / prod logs for `Scheduled scrape triggered` |
| Whether the >30 s-TTL contract revalidation returns 304 | would settle whether W26-F002's per-navigation cost is genuinely ~0 or only cached-window ~0 | cold-cache mobile trace of first app entry with the contract fetch isolated from the bundle |

None of these are "we proved this is broken". They are "we did not test this",
and the difference is the point.
