# CLAUDE.md — Risk It To Get The Brisket

## Project Overview

Dynasty fantasy football valuation and trade calculator platform. Ingests external rankings sources (DLF, KTC, FantasyCalc, DynastyDaddy, etc.), normalizes them to a canonical scale, and serves a web UI for trade analysis and rankings.

## Working Copy Coordination

- Active working copy: `C:\Users\jason\code\riskittogetthebrisket`.
- GitHub `main` is the shared source of truth for Claude, ChatGPT/Codex, and local work.
- Before starting work, run `git pull --ff-only origin main` from the active working copy.
- Use a task branch for meaningful changes (`claude/...` for Claude, `codex/...` for Codex).
- Do not edit OneDrive repo copies unless the user explicitly asks; treat them as backups/archive only.
- Do not let multiple assistants edit the same branch at the same time.
- See `ASSISTANT_COORDINATION.md` for the shared start-of-session checklist and handoff rules.

## Tech Stack

- **Backend**: Python 3, FastAPI, Uvicorn (port 8000)
- **Frontend**: Next.js 15 + React 19 (port 3000)
- **Scraping**: Playwright (browser automation), legacy Selenium/requests (`Dynasty Scraper.py`)
- **CI/CD**: GitHub Actions (`.github/workflows/`)
- **Testing**: pytest (unit/integration), Playwright E2E regression
- **Platform**: Windows (primary dev via `.bat` files), Linux/Unix (production + CI)

## Directory Structure

```
├── server.py                  # FastAPI backend entry point
├── Dynasty Scraper.py         # Legacy scraper (Selenium/requests)
├── .github/workflows/         # GitHub Actions CI/CD pipelines
│
├── frontend/                  # Next.js app (App Router)
│   ├── app/                   # Pages: rankings/, trade/, login/
│   │   └── api/dynasty-data/  # Backend data bridge route
│   ├── components/            # React components + hooks
│   └── lib/                   # Data utilities
│
├── src/                       # Modular canonical engine
│   ├── adapters/              # Source ingestion (DLF CSV, KTC stub, manual CSV)
│   ├── api/                   # API data contract (versioned)
│   ├── canonical/             # Core valuation pipeline + player_valuation.py
│   ├── identity/              # Player/pick master identity mapping
│   ├── scoring/               # Scoring adjustments, archetypes, backtesting
│   ├── league/                # League context (placeholder — scarcity/replacement removed)
│   ├── trade/                 # Trade engines: suggestions + KTC arbitrage finder
│   ├── data_models/           # Dataclass contracts
│   └── utils/                 # Config loading, name/position normalization
│
├── config/
│   ├── sources/               # Source ingestion templates
│   ├── weights/               # Source blending weights
│   ├── leagues/               # League profile templates
│   └── promotion/             # Canonical mode promotion thresholds
│
├── scripts/                   # Pipeline helper scripts (source fetches, fit, etc.)
├── deploy/                    # Deployment configs (nginx, systemd, deploy scripts)
├── tests/                     # pytest unit/integration + Playwright E2E
├── data/                      # Generated pipeline outputs (not committed)
├── exports/                   # Release artifacts (latest/ + archive/)
└── docs/                      # Architecture blueprints, status docs
```

## Key Commands

### Starting the Stack

```powershell
.\start_dynasty.bat          # Start Python backend (port 8000)
.\start_frontend.bat         # Start Next.js dev server (port 3000)
.\start_stack.bat            # Start both in separate windows
```

### Testing & Validation

```bash
# Python tests (primary test suite)
python -m pytest tests/ -q

# E2E regression
npm install                          # Install root + frontend deps
npm run regression:install           # Install Playwright browsers (one-time)
npm run regression                   # Full pipeline: preflight + tests
```

### Git Workflow

```powershell
.\sync.bat "commit message"          # Git add, commit, push
```

## API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/data` | GET | Main player data (versioned contract `2026-03-10.v2`) |
| `/api/status` | GET | Server status + runtime info |
| `/api/health` | GET | Uptime health check |
| `/api/scrape` | POST | Trigger manual scrape |
| `/api/scaffold/status` | GET | Pipeline status |
| `/api/scaffold/raw` | GET | Raw source snapshots |
| `/api/scaffold/identity` | GET | Identity mappings |
| `/api/trade/suggestions` | POST | Roster-aware trade suggestions (reads live contract) |
| `/api/trade/finder` | POST | KTC arbitrage finder |
| `/api/leagues` | GET | Active league registry (stable `key` → `displayName` + roster settings; **no Sleeper IDs leaked**) |

### Rankings vs. league context — the core split

The single most important architectural rule for multi-league:

> **Scoring profile controls rankings.  League key controls context.**

* **`scoringProfile`** (from `config/leagues/registry.json`) is the
  identifier for "which set of rules produces a player's value".  Two
  leagues that use identical scoring share ONE ranking pipeline and
  ONE output.  A single scrape's blended rankings can be served to
  every league with the same profile — no per-league recompute.

* **`leagueKey`** is the identifier for "which league's rosters,
  teams, managers, draft, and signals".  Anything that depends on
  who-owns-what in Sleeper is league-scoped.

Fields that follow **scoring profile** (global across same-scoring leagues):
- `players`, `playersArray`, `sources`, `rankings`, `poolAudit`
- Rank history, source-value history, edge signals
- Player metadata (position, Sleeper ID, news)
- Tier boundaries, confidence buckets, value bands
- Injury-impact calculations (position-based, not league-based)

Fields that follow **leagueKey** (must be per-league):
- `sleeper.teams`, `sleeper.leagueId`, `sleeper.positions`,
  `sleeper.scoringSettings`
- Draft capital (per-team auction budgets, pick ownership)
- Public-league snapshots / standings / matchups
- Terminal aggregates (team portfolio, roster movers)
- Trade-finder, trade-suggestions, trade-simulate outputs
- Angle-finder / Angle-packages opponent filters
- Signal visibility (filtered by roster ownership)
- IDP display toggle (per-league `idpEnabled`)
- Roster-constraint derived UI (starter counts, flex rules)
- Per-user `selectedTeam`, `activeLeagueKey`, watchlist relevance

Contract annotations:
- `meta.leagueKey` — which specific league's `sleeper` block is
  stamped here
- `meta.scoringProfile` — which scoring rules produced these rankings
- `meta.sleeperDataReady` — true iff `sleeper` block is valid for the
  *requested* league; false when the server served the shared
  rankings but doesn't have the requested league's rosters loaded
- `meta.sleeperLoadedLeagueKey` — which league the `sleeper` block
  *would* be for, when `sleeperDataReady: false` (diagnostic only)

Error behavior on endpoints:
- `/api/data`, `/api/rankings/overrides` — 503 only when scoring
  profiles genuinely differ.  When they match but sleeper is for a
  different league, serve shared rankings with `sleeper: null` +
  `sleeperDataReady: false`.
- `/api/terminal`, `/api/trade/*`, `/api/angle/*`,
  `/api/draft-capital` — 503 whenever the loaded contract's
  `leagueKey` doesn't match the request.  These endpoints can't
  meaningfully work without the specific league's rosters.

Rule for new code:
- Need rankings / values / player data?  →  resolve the scoring
  profile via `league_registry.get_scoring_profile(key)`.  Share
  across leagues.  Never index per-league.
- Need rosters / teams / matchups?  →  resolve via `leagueKey`.  One
  pipeline per league.  Never collapse.

### League-aware routing

League-scoped endpoints accept an optional `leagueKey` parameter
(query string for GET, body field for POST).  The resolver lives in
`server.py::_resolve_league_for_request` and picks the target
league in this order:

1. explicit `leagueKey` in the request
2. the authenticated user's `activeLeagueKey` from `user_kv`
3. the registry's default league

**Validation rules** (returned as clean JSON errors):

| Condition | HTTP | Error code |
|---|---|---|
| unknown `leagueKey` | 400 | `unknown_league` |
| `leagueKey` is inactive | 400 | `inactive_league` |
| valid key but contract for it not loaded | 503 | `data_not_ready` |
| no leagues configured at all | 404 | `no_leagues_configured` |

Aliases (`"main"` → `"dynasty_main"`) are accepted and canonicalised
server-side.  Frontend callers should use the stable `key` from
`/api/leagues`, not raw Sleeper league IDs — no endpoint exposes
raw Sleeper IDs to the UI.

League-aware endpoints (all stamp `leagueKey` on their response):

- `GET /api/data` — full canonical contract
- `POST /api/rankings/overrides` — override-sensitive delta
- `GET /api/terminal` — team aggregates, movers, signals
- `POST /api/trade/simulate`
- `POST /api/trade/suggestions`
- `POST /api/trade/finder`
- `POST /api/angle/find`, `POST /api/angle/packages`
- `GET /api/draft-capital`
- `POST /api/scrape` (non-default leagueKey returns 501 today; multi-league scrape is future work)
- `GET /api/public/league/*` (routes through `_public_league_id()` which reads the registry)

Backend map the frontend relies on: `leagueKey` → `sleeperLeagueId`
+ `rosterSettings` + `idpEnabled`.  Lookups go through
`src/api/league_registry.py`; never read `os.getenv("SLEEPER_LEAGUE_ID")`
in new code.

## Architecture Concepts

### Frontend Runtime
Next.js is the sole production frontend. `FRONTEND_RUNTIME` is hardcoded to `next` in server.py — all page routes proxy to Next.js at port 3000. Returns 503 if Next is down; there is no Static fallback.

Production deployment requires both `dynasty.service` (backend) and `dynasty-frontend.service` (Next.js) running.

### Live Value Pipeline
The live ``/api/data`` contract is produced by
``src/api/data_contract.py::_compute_unified_rankings`` — the one and
only code path that determines live player values ("Final Framework").
Steps:

1. Common 0-9999 internal value scale
2. Percentile normalization against a FIXED 500-rank combined-pool
   reference (``_PERCENTILE_REFERENCE_N`` — ranks past 500 clamp to
   the curve tail; this is deliberate top-500-board behavior)
3. Hill-style percentile-to-value conversion via scope-level master
   curves in ``src/canonical/player_valuation.py``
4. Value-direct voting for ``_VALUE_BASED_SOURCES`` (today exactly
   ``ktcSfTep`` + ``idpTradeCalc``): ``raw / site_max × 9999``.
   Every other source — including DynastyDaddy, Yahoo/Boone,
   Fitzmaurice, FantasyCalc, OTCFFB after their rank-signal
   conversions — votes via rank → percentile → Hill.  (The refit
   workflow trains the scope masters on value-based observations.)
5. Scope-appropriate curve routing (cross-market → GLOBAL, overall
   IDP → IDP, everything else → OFFENSE; the ROOKIE master is refit
   tooling only — rookie sources ladder-translate first)
6. Hierarchical anchor + α-shrinkage (α=0.10) ONLY for IDP and
   picks; offense takes a flat count-aware mean-median across all
   sources.  Pick rows widen the anchor set to include ktcSfTep so
   the two real pick markets (KTC + IDPTC) average as peers.
7. Count-aware aggregation (n=1 passthrough, n=2 mean, n=3-4 untrimmed
   mean-median, n≥5 trimmed mean-median)
8. RETIRED: the λ·MAD volatility penalty is switched off
   (``_MAD_PENALTY_LAMBDA = 0.0`` since 2026-04-20); ``sourceSpread``
   is stamped as a pure diagnostic.  Likewise the soft fallback is
   diagnostics-only (``softFallbackCount`` never touches the math).
9. Single-source haircut: non-pick rows resting on one post-Hampel
   source keep 30% of their blended value
10. Market corridor clamp (``_apply_market_corridor_clamp``) — IDP
    rows only, P90 drift band per confidence bucket, hard band cap
    ``_MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS = {"idp": 0.15}``.
    Offense rows are not clamped at all.
    RETIRED: the IDP calibration post-pass this stage used to describe
    (``_apply_idp_calibration_post_pass`` reading
    ``config/idp_calibration.json``) no longer exists — see the
    "Phase 4c: removed" note in ``data_contract.py``.  Neither the
    function nor the config file is in the tree; ``rankDerivedValue``
    is the canonical-pipeline output with no post-blend IDP
    adjustment.  Note that the clamp's own comments still justify it
    as containing "the IDP calibration runaway", which is now a
    retired mechanism — the clamp still does real work against raw
    blend drift, but that stated rationale is stale.
11. Pick tethering — current-year slot picks inherit the merged
    rookie pool's values (offense + IDP rookies combined)
12. Multiplicative future-year pick discount
    (``config/weights/pick_year_discount.json``)

Master curve constants are refit weekly by
``.github/workflows/refit-hill-curves.yml`` (see
``scripts/auto_refit_hill_curves.py``), but the refit **no longer
ships them**.  It produces a *challenger*, scores it against dynasty
boards the fit never reads (``src/model_registry/holdout.py``), records
the verdict in ``config/model_registry/``, and stops.  Production
constants move only via ``scripts/model_registry.py promote`` +
``apply``, run by a human — see ADR-008 in
``docs/roster-trade-intelligence/DECISIONS.md`` for the three reasons
the previous auto-commit path had no working guard.

Blend weights live in the ``_RANKING_SOURCES`` registry (all 1.0 by
policy).  ``config/weights/default_weights.json`` is historical
documentation only — nothing loads it.

### Trade Engines
Two independent trade suggestion systems in `src/trade/`:
- **suggestions.py** — roster-aware trade suggestions (sell-high, buy-low, consolidation, upgrades)
- **finder.py** — KTC arbitrage finder (board value vs market value mismatches)

Both enforce a **top-150 quality filter**, but they gate on
**different boards**, and the difference is deliberate. Do not unify
them without reading why (WS-J F-3/F-4):

| Engine | Gate | Ranked against |
|---|---|---|
| `suggestions.py` | `BOARD_TOP_N_FILTER` (150) | **our blended board** — `display_value` order, covers every asset class |
| `finder.py` | `MARKET_TOP_N_FILTER` (150) | **the retail market, per market** — `ktcSfTep` for offense + picks, `idpTradeCalc` for IDP, each ranked within its own population |

`finder.py` must anchor on a real retail value because its whole
premise is arbitrage between our board and the market — the market
number is load-bearing in its arithmetic. `suggestions.py` only needs
an asset-quality gate ("don't propose trading roster clog"), which our
own board answers for IDP and picks that no single retail board
covers.

**Both engines now read the same internal value.** Until 2026-07-27
`finder.py` valued assets off `_finalAdjusted` — a verbatim deep copy
of the raw scraper composite — while `suggestions.py`, `angle.py`,
`waiver.py`, `monte_carlo.py` and the UI all read `rankDerivedValue`.
The finder was arbitraging a board no user could see (WS-J F-6 / audit
finding K). It now reads the canonical board via
`board_values_from_contract`, its absolute thresholds were re-derived
for the new scale rather than ported, and `metadata.valueSource` stamps
which scale produced a run. Assets the board declines to price leave
its universe and are counted in `metadata.assetsUnpricedByBoard` —
202 on a real payload — rather than vanishing silently.

What is still deliberately different is the **gate**, per the table
above: the quality filter, not the value.

Three traps this documentation previously set:

* **`finder.py` was offense-only.** It ranked every asset against KTC,
  and KTC publishes no IDP players — so every defender scored
  `ktc_value = None` and was dropped before scoring. In an IDP league
  the engine silently returned offense-only results. Fixed by the
  per-market gate above; it now emits `marketCoverage` per market and
  warns explicitly when an IDP league has no priced IDP assets.
* **`suggestions.py`'s gate never consulted KTC.** It was named
  `KTC_TOP_N_FILTER` and its helper `_assign_ktc_ranks`, but the rank
  was always the blended-board position. Renamed to
  `BOARD_TOP_N_FILTER` / `_assign_board_ranks`; `boardTopNFilter` is
  the honest metadata field. The `ktc*` names survive as deprecated
  aliases only.

Cross-market note: KTC and IDPTradeCalc are **directly comparable**,
not incommensurable. IDPTC is a full-roster calculator publishing
offense, IDP and picks on one native 0-9999 scale; of KTC's 500 rows,
475 also appear on the IDPTC board at a median value ratio of 1.000
(p10 0.888, p90 1.054, measured 2026-07-26). Both top out at 9999, so
there is no rescaling to apply between them.

### Canonical Data Mode
The offline canonical-build path (``scripts/canonical_build.py`` +
``src/canonical/transform.py`` + ``src/canonical/pipeline.py``) and its
``CANONICAL_DATA_MODE`` branches have been retired.  The live
``/api/data`` contract is the single source of truth; trade
suggestions read from it directly.

### BDVM — the fundamental valuation engine (feature-flagged, OFF)
``src/bdvm/`` is a SECOND, INDEPENDENT value concept: projection-driven
*fundamental* dynasty value per the Brisket Dynasty Valuation Model
(``docs/research/bdvm-v1/`` — research PDF, verified reference fixture,
and the living ``IMPLEMENTATION_REPORT.md``).  Core rules, all
test-pinned (``tests/bdvm/``):

- **It never touches ``rankDerivedValue``** or any existing route. The
  market board above stays the market-value concept; BDVM is the
  fundamental-value concept; they are compared, never merged in place.
- Reachable only behind the ``bdvm_engine`` feature flag (default OFF)
  at ``GET /api/bdvm/values`` (``surplusMode=option|truncated|plain``
  exposes the option-value ablation), ``GET /api/bdvm/roster``
  (strategy capitals + league-relative direction per roster) and
  ``GET /api/bdvm/trades`` (double-positive scan: each side must gain
  in its OWN strategy currency, gated by single-market fairness).
- Projections come from immutable snapshots under
  ``data/bdvm/projections/``: real sources via the manual-CSV adapter
  when they exist, else the §8.3 reconstructed baseline built by
  ``scripts/bdvm_build_baseline.py`` (realized nflverse PPG under the
  league's exact scoring + rookie draft-slot priors, all flagged
  ``is_proxy``).  Structured events (closed ontology,
  ``config/bdvm/event_types_v1.json``) adjust module inputs — never a
  final score — from ``data/bdvm/events/<season>.json``.
- Fundamentals compute with ZERO market inputs; the market layer
  (``src/bdvm/market.py``) runs strictly afterward and reads only
  value-signal sources (``ktcSfTep``/``ktc``/``idpTradeCalc`` — never
  the rank-signal synthetic encodings in ``canonicalSiteValues``).
- No positional multipliers anywhere: Superflex/TEP/IDP format effects
  flow from exact scoring + flex-aware dynamic replacement.
- Missing data is never imputed into a normal-looking value: players
  without a projection or age are returned as ``unpriced`` with a
  reason; with no projection snapshot the endpoint says so.
- Every payload is versioned: ``modelVersion`` + content-hashed
  ``paramSetId`` (``config/bdvm/params_v1.json`` — priors, not
  validated truth) + league ``configHash`` + ``asOf``.
- The frozen reference implementation under
  ``docs/research/bdvm-v1/reference/`` is an acceptance fixture — do
  not modify it and do not import it from ``src/``; the production
  engine must keep reproducing its Appendix-C numbers
  (``tests/bdvm/test_engine_parity.py``).

The platform currently has no forward-looking statistical projection
feed (everything live is market-rank derived), so BDVM ships with a
manual-CSV projection adapter + a reconstructed-baseline proxy builder
and stays dormant until snapshots exist under ``data/bdvm/projections/``.

### Single Source of Truth: Rankings Override Path
Custom source configurations (user-toggled sources or custom weights) flow through the **SAME** canonical pipeline as the default board. There is no frontend ranking engine, period — not even a fallback. `buildRows` is a pure materializer.

Flow:
1. User toggles a source or changes a weight on `/settings` (writes into `settings.siteWeights`).
2. `useDynastyData` observes the change, calls `fetchDynastyData({siteOverrides})`.
3. `fetchDynastyData` POSTs the override map to `POST /api/rankings/overrides?view=delta` and receives a compact delta payload (~70% smaller than the full contract — see Payload Size Optimization below).
4. `fetchDynastyData` merges the delta onto the cached base `/api/dynasty-data` contract via `mergeRankingsDelta` and returns a fully-populated contract object.
5. `server.py::post_rankings_overrides` invokes `build_rankings_delta_payload(raw_payload, source_overrides=...)` (or `build_api_data_contract` for legacy full-view consumers).
6. `src/api/data_contract.py::_compute_unified_rankings` filters disabled sources and applies overridden weights — same Hill curve, same coverage-aware blend, same robust-median step.
7. `buildRows` materializes the merged contract; it trusts backend stamps verbatim and never recomputes ranks.

Registry lockstep:
- Python registry: `src/api/data_contract.py::_RANKING_SOURCES`
- Frontend mirror: `frontend/lib/dynasty-data.js::RANKING_SOURCES`
- Runtime check: `GET /api/rankings/sources` returns the authoritative Python registry (proxied through `frontend/app/api/rankings/sources/route.js`)
- Parity test: `tests/api/test_source_registry_parity.py` parses the frontend JS and diffs against the Python registry.

**Fail-fast on missing stamps**: The prior `computeUnifiedRanks` fallback (~280 lines of coverage-aware blend code) has been **removed**. `buildRows` now fails fast when a non-empty payload has zero backend rank stamps: it logs an error and returns an empty rows array, letting the `useDynastyData` error state surface a "no players" banner. There is no silent recompute. If you see the fail-fast error in production logs, the scrape pipeline is not stamping — investigate upstream, do not add a client-side blend.

### Two overlays, and why neither one relaxes the no-frontend-ranker rule

There are **two** delta-shaped overlays on the contract. They differ in the
one way that matters most in this codebase — their scope:

| overlay | scope | driven by | endpoint |
|---|---|---|---|
| rankings override delta | **scoring profile** — shared across leagues | user source weights | `POST /api/rankings/overrides?view=delta` |
| league-adjusted valuation | **leagueKey** — roster-derived, never shared | positional scarcity from this league's 12 rosters | `GET /api/valuation/league-adjusted` |

The valuation overlay is league-scoped *by necessity, not convention*.
`lineupScarcity` is measured from one league's rosters, so two leagues sharing a
scoring profile get different adjusted values. Stamping it onto the contract
would let one league's roster shape silently reprice another's board — the exact
collapse the scoring-profile/leagueKey split exists to prevent. Hence an overlay
the client applies, never contract fields.

**Ranks are backend-computed in both cases.** The valuation overlay ships dense
`ranks` + `tiers` alongside sparse `factors`, produced by
`data_contract.py::compact_ranks_and_tiers` — the *same* function the pipeline
uses, called on shallow copies because `latest_contract_data` is a shared mutable
global. `buildRows` still consumes stamps verbatim. This feature **conformed to**
the "no frontend ranking engine, period" rule rather than being excepted from it:
the rule is what forced the composing design instead of a client-side re-sort.

Two consequences worth knowing before touching this:

- **`factors`, not absolute values.** The adjustment factor is a function of
  position alone and never reads the consensus value, so it composes exactly
  against any board — including one the user re-weighted. Absolute values would
  carry the default board's numbers into a board the server never computed.
- **The two overlays are NOT composed on the client.** With source overrides
  active the valuation overlay's ranks are the ranks of
  `default_consensus × factor`, but the correct answer is
  `overridden_consensus × factor`, which the server never computed. Composing
  them yields a board where neither values nor ranks correspond to anything, so
  `fetchDynastyData` serves the overridden market board and warns instead.
  Threading `valuation_mode` through the overrides pipeline server-side is the
  fix; until then the combination is deliberately blocked, not silently wrong.

Regression tests: `frontend/__tests__/valuation-overlay.test.js` (both
materializer key sets — the legacy dict uses `_canonicalConsensusRank` but
`rankDerivedValue`, and the legacy path is the default one), and
`tests/league_intel/test_publish.py` (caller-row isolation, dense contiguous
ranks, anchor-slot-pick exclusion).

### Rankings Override Payload Size Optimization
The `POST /api/rankings/overrides` endpoint supports two response views:

- `view=full` (default, backward-compat): returns the full canonical contract (~4 MB uncompressed, identical shape to `GET /api/data`).
- `view=delta` (default for frontend): returns only the override-sensitive fields per player, keyed by `displayName`, dropping the legacy `players` dict, `sleeper`, `methodology`, `poolAudit`, and other override-invariant blocks. Production payload drops from ~4 MB to ~1.25 MB uncompressed, and to ~100 KB over the wire with FastAPI's `GZipMiddleware`. The frontend merges the delta onto its cached base `/api/data?view=app` payload.

Regression test: `tests/api/test_source_overrides.py::TestBuildRankingsDeltaPayload` pins the delta shape, byte-size bounds, and the invariant that every field in `_DELTA_PLAYER_FIELDS` round-trips through a manual merge identically to the full-contract path.

See `tests/api/test_source_overrides.py` for the full contract spec.

### Adapter Pattern
Pluggable source adapters (`src/adapters/base.py` defines the frozen contract). All adapters emit `RawAssetRecord` dataclasses with normalized fields. Current adapters: DLF CSV, KTC stub, manual CSV, scraper bridge.

### Position Normalization
Single source of truth: `POSITION_ALIASES` in `src/utils/name_clean.py`. All modules import from there.

### Deployment
Production runs on a VPS (currently Contabo; the deploy target is the `DEPLOY_HOST` secret, not hardcoded anywhere) with nginx reverse proxy, systemd service, and Let's Encrypt SSL. See `deploy/` directory.

## Non-Negotiable Rules

1. **Do not assume features work** — trace the live execution path end-to-end before claiming anything is implemented
2. **Prefer modifying existing architecture** over introducing parallel systems
3. **Preserve working behavior** unless a verified flaw requires change
4. **Verify downstream effects** for any value/ranking change across UI rendering, sorting, filtering, exports, and league-specific transforms
5. **Verify the full pipeline** for any scraper/source change: ingestion -> normalization -> merge -> fallback -> frontend consumption
6. **Call out anything** mocked, bypassed, stale, duplicated, half-wired, dead, or missing
7. **Smallest correct change set** — read relevant files first, identify the real live path, make minimal changes, run validation, report what changed and what remains uncertain

## Performance Rules

- Prioritize page-load speed and perceived responsiveness
- Reduce blocking work on initial load
- Eliminate duplicated calculations, repeated fetches, oversized payloads
- Prefer memoization, batching, precomputation, caching, lazy loading where justified
- Do not sacrifice correctness for speed

## Coding Conventions

### Python
- Type hints with `from __future__ import annotations`
- Dataclasses for models, Pydantic for API contracts
- `pathlib.Path` for file operations
- ISO 8601 UTC timestamps (`datetime.now(timezone.utc).isoformat()`)
- `argparse` for script CLI arguments
- Exit codes for script success/failure

### JavaScript / React
- Next.js App Router (no pages directory)
- React hooks for state management
- Named exports from modules

### General
- Configuration via JSON templates in `config/`
- Environment variables via `.env` (see `.env.example`)
- Markdown for all documentation
- Versioned API contracts (e.g., `2026-03-10.v2`)

## Environment Variables

Key variables (see `.env.example` for full list):

| Variable | Purpose | Default |
|---|---|---|
| `FRONTEND_RUNTIME` | `next` (hardcoded) | `next` |
| `FRONTEND_URL` | Next.js dev server URL | `http://127.0.0.1:3000` |
| `SLEEPER_LEAGUE_ID` | Primary Sleeper league | -- |
| `BASELINE_LEAGUE_ID` | Baseline comparison league | -- |

## Safety

- Do not exfiltrate private data
- Do not run destructive commands without approval
- Prefer reversible operations
- Be explicit before any action affecting production, deployment, credentials, or public output
