# Codebase Handoff: Risk It To Get The Brisket
*Generated 2026-03-21 | Full codebase review*

---

## What This Project Is

A **dynasty fantasy football trade calculator and league management tool** built for a private 12-team Superflex TEP league. It scrapes trade values from 11 external sites, blends them into a composite score, applies league-specific scoring adjustments, and serves a web dashboard with trade evaluation, rankings, roster analysis, and draft capital tracking.

**Live at:** `https://riskittogetthebrisket.org` (HTTPS via Caddy reverse proxy)

---

## Repository Layout

```
/
├── server.py                  # FastAPI server (2550 lines) — main process
├── Dynasty Scraper.py         # Async scraper (11,489 lines) — run by server
├── Static/                    # Legacy vanilla JS frontend (archived — use FRONTEND_RUNTIME=static to revert)
│   ├── index.html             # Main app (~10k lines)
│   ├── landing.html           # Entry router / login
│   ├── league.html            # Public draft capital page
│   └── js/
│       ├── 00-core-shell.js   # Constants, helpers, tab management
│       ├── 10-rankings-and-picks.js
│       ├── 20-data-and-calculator.js
│       ├── 30-more-surfaces.js  # League analytics dashboards
│       ├── 35-draft-capital.js
│       ├── 40-runtime-features.js  # Server integration, player popup, LAM
│       └── 50-bootstrap.js    # Startup sequence
├── frontend/                  # Next.js 15 / React 19 (primary frontend)
│   ├── app/
│   │   ├── page.jsx           # Home dashboard
│   │   ├── rankings/page.jsx  # Rankings table
│   │   ├── trade/page.jsx     # Trade builder
│   │   ├── login/page.jsx     # Auth (demo only)
│   │   └── api/dynasty-data/route.js  # Backend proxy + file fallback
│   ├── components/useDynastyData.js
│   └── lib/dynasty-data.js    # Data normalization
├── src/                       # Python pipeline modules
│   ├── adapters/              # Data ingestion adapters (DLF, KTC stub, manual)
│   ├── api/data_contract.py   # API payload builder + validator
│   ├── canonical/             # Pipeline orchestration + value transform
│   ├── data_models/contracts.py
│   ├── identity/              # Player identity resolution
│   ├── scoring/               # LAM scoring system
│   └── utils/
├── data/                      # Runtime data files (dynasty_data_*.json)
├── exports/                   # Scraper output bundles
├── scripts/                   # Utility scripts
│   ├── ingest_dlf.py
│   ├── run_canonical_pipeline.py
│   ├── run_identity_pipeline.py
│   └── validate_ingest.py
├── tests/                     # pytest suite
├── Caddyfile                  # Reverse proxy config
└── dynasty_data.js            # Embedded fallback data (served statically)
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────┐
│                  server.py                  │
│  FastAPI  ·  Auth  ·  Scheduler  ·  State   │
│                                             │
│  Every 2h: run_scraper() ──────────────────►│──► Dynasty Scraper.py
│                                             │         │
│  Serves:                                    │         ▼
│   /api/data      (pre-serialized JSON)      │   scrapes 11 sites
│   /api/status    (health/metrics)           │   computes composites
│   /api/draft-capital                        │   writes dynasty_data*.json
│   /api/auth/*                               │
│   /app, /rankings, /trade (frontend)        │
└─────────────────────────────────────────────┘
         │                        │
         ▼                        ▼
   Static/ (archived)      frontend/ (default)
   Vanilla JS SPA          Next.js React
```

### Data Flow
1. **Scraper** fetches values from KTC, FantasyCalc, DynastyDaddy, DynastyNerds, DraftSharks, FantasyPros, Yahoo, IDPTradeCalc, PFF IDP, Flock, DLF
2. Blends into per-player composite (Z-score weighted average)
3. Applies **LAM** (League Adjustment Multiplier) for custom scoring
4. Writes `dynasty_data_YYYY-MM-DD_HHMMSS.json` to `data/`
5. **Server** loads it, builds API contract payload, pre-serializes 3 views (full / runtime / startup)
6. **Frontend** fetches `/api/data?view=app` and renders

---

## Key Configuration (Environment Variables)

| Variable | Default | Purpose |
|---|---|---|
| `JASON_LOGIN_PASSWORD` | `Elliott21!` ⚠️ | App password — **change this, default is hardcoded** |
| `SLEEPER_LEAGUE_ID` | `1312006700437352448` | Primary league for roster/picks/trades |
| `BASELINE_LEAGUE_ID` | — | Test league for LAM baseline scoring |
| `CANONICAL_DATA_MODE` | `off` | `off` / `shadow` / `primary` — pipeline integration |
| `FRONTEND_RUNTIME` | `next` | `next` / `static` / `auto` |
| `FRONTEND_URL` | `http://127.0.0.1:3000` | Next.js dev server URL |
| `SCRAPE_INTERVAL_HOURS` | `2` | How often to auto-scrape |
| `SCRAPE_RUN_TIMEOUT_SECONDS` | `7200` | Max scrape wall time |
| `ALERT_ENABLED` | `false` | Email alerts on failures |
| `ALERT_TO` / `ALERT_FROM` | — | Gmail alert recipients |
| `ALERT_PASSWORD` | — | Gmail app password |
| `DN_EMAIL` / `DN_PASS` | — | DynastyNerds login |
| `DS_EMAIL` / `DS_PASS` | — | DraftSharks login |
| `ALERT_THRESHOLD` | `5.0` | Value movement % to trigger alert |
| `UPTIME_CHECK_ENABLED` | `true` | Self-ping health watchdog |

---

## How to Run

```bash
# Install Python deps
pip install fastapi uvicorn playwright requests

# Install Playwright browsers
playwright install chromium

# Start server (serves on :8000)
python server.py

# Or with gunicorn
uvicorn server:app --host 0.0.0.0 --port 8000

# Frontend (Next.js dev mode)
cd frontend && npm install && npm run dev  # runs on :3000
```

### Trigger a manual scrape
```
POST /api/scrape
# or via admin UI at /app (More tab → Update Values)
```

---

## The Scraper (`Dynasty Scraper.py`) — 11,489 lines

### What It Does
- Launches a headless Chromium browser via Playwright
- Runs ~10 scrapers in parallel + sequential groups
- Each scraper has 3–5 fallback extraction strategies
- Applies name matching (exact → normalized → fuzzy) to unify player names
- Builds composite values, pick model, scoring adjustments
- Exports JSON + CSV + ZIP bundle

### Site Inventory

| Site | Method | Timeout | Risk |
|---|---|---|---|
| KTC | API interception → DOM → regex | 300s | 🔴 Regex fragile |
| FantasyCalc | JSON API | 90s | 🟡 Schema change |
| DynastyDaddy | Table DOM | 300s | 🟡 Column detection |
| DynastyNerds | Session → JS → text → top10 → cache | 300s | 🔴 Paywalled |
| DraftSharks | Infinite scroll + JS | 360s | 🟡 Race condition |
| FantasyPros | Article URL auto-discovery | 300s | 🟡 URL patterns |
| Yahoo | Article URL auto-discovery | 300s | 🟡 URL patterns |
| IDPTradeCalc | Google Sheets API → toggle → React Fiber → autocomplete | 480s | 🔴 Very fragile |
| PFF IDP | Unknown — likely paywalled | 300s | 🔴 Often fails |
| Flock | Saved session (`flock_session.json`) | 300s | 🔴 Session expires |
| DLF | Local CSV files | n/a | 🟡 Files must be fresh |

### Required Files in Script Directory
```
dlf_superflex.csv
dlf_idp.csv
dlf_rookie_superflex.csv
dlf_rookie_idp.csv
rookie_must_have.txt        # One player name per line
flock_session.json          # Manual login required
dynastynerds_session.json   # Manual login required
```

### Name Matching Pipeline
`clean_name()` → `normalize_lookup_name()` → 5-stage match:
1. Exact
2. Period-stripped
3. Lookup-normalized (suffixes, apostrophes, unicode)
4. Initial expansion (`J. Smith-Njigba` → `Jaxon Smith-Njigba`)
5. Fuzzy (`SequenceMatcher` ≥ 0.78 threshold with safety guards)

### Pick Model
- **2026:** 1:1 mapping to top 72 rookie composites, extrapolated with 6% decay
- **2027/2028:** Tier-based (Early/Mid/Late) with calibrated discounts (84% / 70% defaults)
- Discount recalibrated against live market data when available

### Data Quality Guarantees
- Every Sleeper-rostered player gets a composite (floor = positional median × 0.35)
- Every player in `rookie_must_have.txt` gets a composite (curve-derived fallback)
- Target pools: 350 offensive + 275 IDP players
- Partial scrape block: if <50% of sites return data, server rejects result and keeps last-known-good

---

## The Server (`server.py`) — 2,550 lines

### Endpoints

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /api/data?view=` | ✅ | Main data feed (`full`/`startup`/`runtime`) |
| `GET /api/status` | ✅ | Scrape state, source health, payload sizes |
| `GET /api/health` | ❌ | 200/503 for reverse proxy |
| `GET /api/metrics` | ✅ | Request count, scrape stats, disk space |
| `GET /api/draft-capital?refresh=1` | ✅ | Draft pick values per team |
| `POST /api/scrape` | ✅ | Trigger manual scrape |
| `POST /api/auth/login` | ❌ | Set session cookie |
| `POST /api/auth/logout` | ❌ | Clear session |
| `GET /api/auth/status` | ❌ | Check auth |
| `GET /app`, `/rankings`, `/trade` | ✅ | Frontend (static or Next proxy) |
| `GET /` | ❌ | Landing page |
| `GET /league` | ❌ | Public draft capital page |
| `GET /api/scaffold/*` | ✅ | Raw pipeline debug data |

### Auth System
- Single user (`jason`) with password from env
- In-memory session dict (UUID keys)
- Sessions never expire — **no TTL** (known gap)
- No CSRF protection on login POST (mitigated by SameSite=lax)
- No rate limiting on login

### State Management
```python
latest_data              # Raw scraper output
latest_contract_data     # Validated API contract payload
latest_data_bytes        # Pre-serialized (full view)
latest_runtime_data_bytes  # Pre-serialized (runtime view)
latest_startup_data_bytes  # Pre-serialized (startup view)
# + gzip versions of each
```
Memory note: 6 copies of payload in RAM. For a 50MB payload this is ~300MB.

### Canonical Data Modes
- `off` (default): Pure scraper data
- `shadow`: Load pipeline data, log comparison, serve scraper data
- `primary`: Serve pipeline data, fallback to scraper

### Scrape Lifecycle
```
idle → lock acquired → import scraper → run with timeout
  → progress_callback updates UI
  → partial-data check (reject if <50% sites)
  → disk-space check (skip write if <500MB free)
  → pre-serialize 3 payload views
  → release lock
```

### Draft Capital Endpoint
- Reads pick dollar values from `Copy of Draft Data.xlsx - Draft Data.csv`
- Fetches KTC rookie rankings (live scrape → CSV fallback, cached 6h)
- Queries Sleeper for pick ownership + team rosters
- Exponential decay curve to extend rookie list to 72 picks

---

## The Frontend

### Dual Runtime
`FRONTEND_RUNTIME` controls which frontend is served:
- `next` (default): Proxies to Next.js on :3000 — primary UI
- `static`: Reverts to legacy `Static/index.html` (archived, all features still functional)
- `auto`: Tries Next proxy, falls back to static on error

### Static App Features
| Feature | Status |
|---|---|
| Trade Calculator (2-3 sides) | ✅ |
| Rankings (filter/sort/tiers/export) | ✅ |
| League Edge (BUY/SELL signals) | ✅ |
| Roster Dashboard | ✅ |
| Trade History (Sleeper) | ✅ |
| Waiver Wire Gems | ✅ |
| Draft Capital | ✅ |
| Settings (site weights, anchors) | ✅ |
| Mobile UI | ✅ |

### Next.js App (Primary Frontend)
| Feature | Status |
|---|---|
| Trade Calculator | ✅ |
| Rankings | ✅ |
| Home Dashboard | ✅ |
| Login | ✅ (demo-only — no backend validation yet) |
| Trade History | ❌ not yet migrated |
| League Edge | ❌ not yet migrated |
| Roster Dashboard | ❌ not yet migrated |
| Draft Capital | ❌ not yet migrated |
| Settings Panel | ❌ not yet migrated |

> **Note**: Unmigrated features are still available via `FRONTEND_RUNTIME=static`.

### Data Loading (Static)
```
fetchFromServer()
  → /api/data?view=startup  (fast first paint)
  → deferred: /api/data?view=app  (full hydration)
  → fallback: embedded window.DYNASTY_DATA (dynasty_data.js)
```

### Key Global State (Static JS)
- `loadedData` — current dataset
- `sleeperTeams` — league rosters
- Session storage: calculator state (`dynastyCalcV5`)
- Local storage: site settings, recent players, trade workspace, mobile prefs

---

## The `src/` Pipeline Modules

These are an **in-progress canonical pipeline** — not yet in production flow. They sit alongside the scraper.

| Module | Purpose | Status |
|---|---|---|
| `adapters/dlf_csv_adapter.py` | Ingest DLF CSV rankings | ✅ Complete |
| `adapters/ktc_stub_adapter.py` | KTC adapter | ⚠️ Stub only |
| `adapters/manual_csv_adapter.py` | Generic CSV | ⚠️ Stub only |
| `canonical/pipeline.py` | Orchestrate value computation | ✅ Complete |
| `canonical/transform.py` | Z-score blending, universe split | ✅ Complete |
| `identity/matcher.py` | Player identity resolution | ✅ Complete |
| `scoring/player_adjustment.py` | Scoring multiplier computation | ✅ Complete |
| `scoring/sleeper_ingest.py` | Fetch + normalize Sleeper config | ✅ Complete |
| `api/data_contract.py` | API payload builder + validator | ✅ Complete |

Scripts to run them:
```bash
python scripts/ingest_dlf.py
python scripts/run_canonical_pipeline.py
python scripts/run_identity_pipeline.py
python scripts/validate_ingest.py
```

---

## Tests & CI

```bash
pytest tests/           # Full suite
pytest tests/ -x -q     # Fast fail
```

Tests cover: adapters, canonical transform, identity matcher, scoring modules, data contract, utils.

No CI/CD configured — tests run manually. Deployment is manual SSH + restart.

---

## Deployment

```
Server: Linux VPS
Process: uvicorn via systemd (assumed) or manual
Proxy: Caddy (Caddyfile in repo root)
```

**Caddy handles:** HTTPS termination, reverse proxy to :8000, static file serving for `/static`, `/js`, `/Static`.

---

## Known Issues & Things to Fix

### Security (Fix First)
1. **Hardcoded password** — `server.py:103`: `"Elliott21!"` is the default. Set `JASON_LOGIN_PASSWORD` env var and remove the fallback.
2. **No session TTL** — sessions never expire. Add a 24h max lifetime check.
3. **No login rate limiting** — brute-force possible.

### Operational
4. **Old data files accumulate** — `data/dynasty_data_*.json` grows forever. Add a retention policy (keep last N).
5. **Memory footprint** — 6 pre-serialized payload copies in RAM. Fine for current data size but watch if it grows.
6. **Alert cooldown is global** — one 1h cooldown covers all alert types. Scrape failure + uptime failure in same hour = only one email sent.
7. **Flock session expires** — requires manual re-login. No automated refresh.
8. **DynastyNerds requires credentials** — without `DN_EMAIL`/`DN_PASS` or a valid `dynastynerds_session.json`, falls back to public top-10 only.

### Frontend
9. **Some features not yet in Next.js** — League Edge, Roster Dashboard, Trade History, Draft Capital, Settings still in legacy `Static/` only. Use `FRONTEND_RUNTIME=static` to access them.
10. **Next.js login is demo-only** — does not call backend. Don't use as real auth.

### Pipeline
11. **KTC and Manual CSV adapters are stubs** — not functional, listed in adapter registry but return empty data.
12. **`save_json()` uses `ensure_ascii=True`** — drops non-ASCII characters from JSON output.

---

## Glossary

| Term | Meaning |
|---|---|
| **Composite** | Blended trade value (0–9999 scale) from all active sites |
| **LAM** | League Adjustment Multiplier — adjusts player values for custom scoring rules |
| **SF / Superflex** | Superflex format (can start 2 QBs) |
| **TEP** | Tight End Premium — extra points for TE receptions |
| **KTC** | KeepTradeCut — primary dynasty value site |
| **DLF** | Dynasty League Football — CSV rankings source |
| **IDP** | Individual Defensive Player |
| **Canonical pipeline** | `src/` Python modules — alternative value computation path, not yet primary |
| **CANONICAL_DATA_MODE** | `off`/`shadow`/`primary` — controls whether pipeline data is used |
| **Pick model** | Derived pick values using rookie composite curve + year discounts |
| **Roster guarantee** | Every Sleeper-rostered player is guaranteed a non-zero composite |
| **Partial scrape block** | Server rejects scrape result if <50% of sites returned data |

---

*End of handoff — covers all 11,489 lines of scraper, 2,550 lines of server, all src/ modules, Static JS, and Next.js frontend.*
