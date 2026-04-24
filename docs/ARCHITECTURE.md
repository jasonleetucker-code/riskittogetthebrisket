# ARCHITECTURE — Risk It To Get The Brisket

**Purpose:** one-page orientation for anyone new to the codebase.
Details live in docstrings; this document is the map.

## System at a glance

```
Browser ─► Nginx ─► Next.js (port 3000) ─► FastAPI (port 8000) ─► SQLite
                                                  │
                                                  ├─► Sleeper API (rosters/trades)
                                                  ├─► KTC / DLF / FantasyCalc HTML
                                                  ├─► nflverse parquets (optional)
                                                  └─► ESPN public endpoints (optional)
```

## Two system-critical architectural rules

1. **Scoring profile controls rankings. League key controls context.**
   Two leagues with identical scoring (e.g., PPR superflex TEP 1.5)
   share ONE ranking pipeline and ONE output. Per-league rosters,
   trades, and draft picks are separate. See `CLAUDE.md` for the
   full field-split table.

2. **Every new behavior ships behind a feature flag** (default OFF).
   Registry at `src/api/feature_flags.py`. Env override via
   `RISKIT_FEATURE_<NAME>=1`. Nothing in production changes until
   a flag flips.

## Modules + what they own

### Backend — `src/`

| Module | Owns |
|---|---|
| `api/` | HTTP endpoints, feature flags, session store, league registry, rate limiting |
| `adapters/` | Source ingestion (DLF CSV, KTC, manual CSV, scraper bridge) |
| `canonical/` | Hill-curve value pipeline, confidence intervals, rank-history band |
| `backtesting/` | Spearman source accuracy, dynamic weight fitting |
| `scoring/` | Feature engineering, signal math, positional tiering |
| `trade/` | Trade suggestions, KTC arbitrage finder, Monte Carlo simulator, correlation matrix |
| `news/` | Signal alerts, usage signals, news providers |
| `nfl_data/` | nflverse ingest, ESPN injuries, depth charts, usage windows, realized points |
| `identity/` | Player/pick matcher, unified ID mapper (Sleeper ↔ GSIS ↔ ESPN) |
| `public_league/` | Public `/league` page pipeline (fork-isolated from private) |
| `pool/` | Pool builder (legacy — being absorbed into canonical) |
| `league/` | League context (placeholder) |
| `utils/` | Name/position normalization, config loading |
| `data_models/` | Dataclass contracts shared across modules |

### Frontend — `frontend/`

| Path | Owns |
|---|---|
| `app/` | Next.js App Router pages: `/rankings`, `/trade`, `/league`, `/admin`, etc. |
| `components/` | Shared React components + hooks (`useDynastyData`, `useTeam`, `useLeague`, `useSettings`) |
| `lib/` | Data materializers (`dynasty-data.js`), helpers, chart primitives |
| `__tests__/` | Vitest unit tests |

### Configuration — `config/`

| Dir | Owns |
|---|---|
| `leagues/registry.json` | Active leagues + per-league scoring profile / Sleeper ID / IDP flag |
| `weights/` | Static source weights (plus `dynamic_source_weights.json` when flag is on) |
| `tiers/thresholds.json` | Per-position Cohen's-d tier cutoffs |
| `identity/id_overrides.json` | Manual player ID overrides for the unified mapper |
| `source_staleness.json` | Per-source stale-alert hour thresholds |
| `espn_schema_baseline.json` | Shape-hash baseline for ESPN endpoint drift detection |
| `sources/` | Per-source ingestion templates |

## Data flow: one request, end-to-end

### Anonymous `/league` page load

```
Browser GET /league
  │
  ▼
Nginx ─► Next.js renders shell (SSR) ─► FastAPI for data
  │                                          │
  ▼                                          ▼
Next.js hydrates ◄──────────────────── /api/public/league
                                              │
                                              ▼
                                    public_league snapshot cache
                                              │ (rebuild every 5 min)
                                              ▼
                                    Sleeper API (rosters/trades)
```

### Signed-in `/trade` page load

```
Browser GET /trade (with jason_session cookie)
  │
  ▼
_private_api_gate middleware (rate-limit public, auth-gate private)
  │
  ▼
Next.js renders shell ─► /api/data?view=delta
                                │
                                ▼
                       build_rankings_delta_payload(...)
                                │
                                ▼
                       latest_contract_data (in-memory)
                       ▲ rebuilt by scrape/overlay pipelines
```

## The scrape + overlay pipelines

Two paths populate `latest_contract_data`:

1. **Primary scrape** (default league): runs on a schedule +
   on-demand via `/api/scrape`. Pulls from every source adapter,
   builds the canonical contract, stamps the default league's
   Sleeper block.
2. **Per-league overlay** (non-default leagues): on-demand fetch of
   just that league's Sleeper rosters + trades + picks. Attaches
   to the shared canonical contract as a swappable `sleeper`
   block when the frontend asks for that `leagueKey`. Cached
   15 min per league.

## Auth model

Two gates stack:

1. `PRIVATE_APP_ALLOWED_USERNAMES` — allowlist for Sleeper login.
   Only listed usernames can even *create* a session.
2. `_private_api_gate` middleware — every `/api/*` path except a
   small public allowlist returns 401 without a session. Public
   allowlist is explicitly enumerated in `server.py` and covered
   by `tests/api/test_private_auth.py`.

Sessions are now persisted to SQLite (`data/session_store.sqlite`)
so deploys don't log users out. TTL 30 days. Allowlist rotation
invalidates all sessions atomically via the
`allowlist_version` stamp.

## Testing layout

| Layer | Framework | Location |
|---|---|---|
| Backend unit / integration | pytest | `tests/api/`, `tests/canonical/`, etc. |
| Frontend unit | Vitest | `frontend/__tests__/` |
| E2E | Playwright | `tests/e2e/specs/` |
| E2E signed-in | Playwright + `/api/test/create-session` | `tests/e2e/specs/signed-in-*.spec.js` |

Run everything:
```bash
python3 -m pytest tests/ --ignore=tests/e2e -q      # 2200+ tests
cd frontend && npx vitest run                         # ~50 frontend tests
npm run regression                                     # full E2E pipeline
```

## Deploy model

GitHub Actions workflow `.github/workflows/deploy.yml` on push to
main:

1. Validate build inputs (frontend build must pass).
2. Deploy to Hetzner via SSH + systemd.
3. Post-deploy smoke test hits `/api/health` + `/api/public/league`.

Rollback: `git revert` the breaking commit and push; the deploy
pipeline redeploys. For a flag-gated feature, setting
`RISKIT_FEATURE_<NAME>=0` in the systemd unit + bouncing the
service is faster.

## Deep-dive docs

- [`CLAUDE.md`](../CLAUDE.md) — architectural rules + endpoint inventory + non-negotiables.
- [`docs/upgrade_phases_1_10.md`](upgrade_phases_1_10.md) — the big April 2026 upgrade.
- [`docs/backtest_methodology.md`](backtest_methodology.md) — dynamic weight fitting methodology.
- [`docs/ONBOARDING.md`](ONBOARDING.md) — how to add a league, source, flag.
- `src/api/data_contract.py` docstring — the live value pipeline, step by step.
