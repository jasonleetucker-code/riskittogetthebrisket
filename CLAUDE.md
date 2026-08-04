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
├── server.py                  # FastAPI backend entry point (~100 routes)
├── Dynasty Scraper.py         # THE PRODUCTION SCRAPER (Selenium/requests).
│                              #   Not legacy despite its age: server.py
│                              #   imports it via importlib for /api/scrape,
│                              #   the scheduled loop and startup, and
│                              #   scheduled-refresh.yml runs it every 2h.
├── .github/workflows/         # GitHub Actions CI/CD pipelines
│
├── frontend/                  # Next.js app (App Router) — 38 pages
│   ├── app/                   # rankings/, trade/, draft/, bdvm/, waivers/,
│   │   │                      #   terminal/, news/, settings/, login/, …
│   │   └── api/               # 28 backend bridge routes
│   ├── components/            # React components + hooks
│   └── lib/                   # Data utilities (pure materializers)
│
├── src/                       # Modular canonical engine (~250 modules)
│   ├── adapters/              # base.py (frozen contract), scraper bridge,
│   │                          #   sleeper_trending, ktc_crowd_faab
│   ├── api/                   # API data contract (versioned) + endpoints
│   ├── bdvm/                  # Brisket Dynasty Valuation Model (fundamentals)
│   ├── canonical/             # Hill curves + tiering (player_valuation.py)
│   ├── identity/              # Player/pick master identity mapping
│   ├── league_intel/          # League-adjusted overlay, TE premium, scarcity
│   ├── model_registry/        # Hill-curve challenger/promotion (script-only)
│   ├── scoring/               # Scoring adjustments, archetypes, backtesting
│   ├── league/                # EMPTY placeholder — see src/league/README.md
│   ├── trade/                 # Trade engines: suggestions + arbitrage finder
│   ├── data_models/           # Dataclass contracts
│   └── utils/                 # Config loading, name/position normalization
│
├── config/
│   ├── bdvm/                  # BDVM params, event ontology, pick outcomes
│   ├── leagues/               # League registry + profile templates
│   ├── model_registry/        # Hill scope-master versions
│   ├── sources/               # Source ingestion templates
│   ├── tiers/, trade/, identity/, league_intel/
│   └── weights/               # Pick-year discount, TE curve, coverage floors
│
├── scripts/                   # Pipeline helper scripts (source fetches, fit, etc.)
├── deploy/                    # Deployment configs (nginx, systemd, deploy scripts)
├── tests/                     # pytest unit/integration + Playwright E2E
├── data/                      # Pipeline outputs. MOSTLY gitignored, but ~7,900
│                              #   files ARE tracked (data/ros/ is re-included by
│                              #   .gitignore, and refresh workflows `git add -f`)
├── exports/                   # Release artifacts (latest/ + archive/) — 141 tracked
└── docs/                      # Architecture blueprints, status docs, ADRs, audits
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
| `/api/sharp/roster-percentage` | GET | Sharp Roster Percentage board (global cohort — takes no `leagueKey`) |
| `/api/sharp/roster-percentage/audit` | GET | Every roster behind one player's count, for manual verification |

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
- `/api/terminal`, `/api/trade/*`, `/api/angle/*` — 503 whenever the
  loaded contract's `leagueKey` doesn't match the request.  These
  endpoints can't meaningfully work without the specific league's
  rosters.
- `/api/draft-capital` — 503 `data_not_ready` only when NO contract is
  loaded, and only on the non-default path.  It deliberately does NOT
  503 on a league *mismatch*.
  - The default league is served from `CSVs/Draft Data.xlsx` and never
    consults the contract, so contract readiness is irrelevant to it.
  - A non-default league takes the Sleeper-derived fallback
    (`src/api/draft_capital_fallback.py`), which fetches **that
    league's own** rosters and traded picks.  It needs the contract
    only for pick VALUES, so a foreign-league contract still produces
    a correct board for the requested league — refusing it would
    remove working multi-league functionality to satisfy a table.
  - This resolves Defect D-2 (`docs/python-coverage-audit.md`), which
    was open between "503 per this table" and "keep the fallback and
    fix the doc".  Fixing the doc is the answer, and this is it.
  - The 503 covers the no-contract case only.  This section used to
    claim that was also the only way to reach the hardcoded
    7000/4000/2000/1200-by-round table in `_pick_value_from_contract`
    — i.e. that the invented values sat behind the guard.  **That was
    false**, and it hid a live defect (audit finding C1): the fallback
    generates picks for `current_season` AND `current_season + 1`,
    while the live contract carries current-year slot picks only (72
    rows: 12 slots × 6 rounds).  Every next-year pick therefore missed
    the lookup and took a constant **with a fully valid contract
    loaded** — half the emitted board — and those constants were
    normalized into the same $1200 pool as the real values, diluting
    every genuine pick's dollars and shifting every team's
    `auctionDollars`.  A 503 gated none of it.
  - Fixed by removing the table outright.  `_pick_value_from_contract`
    returns `None` on a miss; `build_sleeper_derived` excludes unpriced
    picks from the dollar normalization (so they cannot dilute) and
    emits them with `dollarValue: null` +
    `isUnpriced: true` — ownership from Sleeper is still real, only the
    value is unknown.  `coveredPickYears` is now derived from what was
    actually priced instead of the loop bounds, and
    `pricedPickCount` / `unpricedPickCount` / `unpricedPickYears` make
    the omission visible (same posture as
    `metadata.assetsUnpricedByBoard` in `src/trade/finder.py`).
    Consequence worth knowing: the $1200 pool now lands entirely on the
    current class, so a real pick's dollar value is roughly double what
    this path used to report.
  - Pinned by `tests/api/test_draft_capital_data_not_ready.py` (which
    fails if a future change re-resolves D-2 by accident in either
    direction) and `tests/api/test_draft_capital_fallback.py` (which
    pins the unpriced-exclusion arithmetic).

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
Next.js is the sole production frontend, and since 2026-07-31 (#555) it is
the **only** thing that serves a page. `server.py` registers no page routes
at all: `/`, `/rankings`, `/league`, `/_next/*`, `/favicon.ico` and the
catch-all `@app.get("/{full_path:path}")` are gone, along with `_proxy_next`,
`_serve_app_shell`, `_require_auth_or_redirect` and `_auth_redirect_response`.
A page path requested from `:8000` now returns a JSON **404**.

This matches what production already did — `deploy/nginx/chaseupside-proxy.conf`
routes `location /` to the Next upstream and only `location /api/` reaches the
backend, so FastAPI never saw a page request. What the proxy did serve was a
*divergent* copy: it took a path string rather than a `Request`, so it
structurally could not forward cookies or the query string, and after
`frontend/middleware.js` landed it returned **200 carrying the login page body**
for an authenticated session. Two definitions of the page auth gate that had to
be kept in sync is what produced the incident `middleware.js` was written for.
There is now one, in Next.

**`frontend/middleware.js` + `frontend/lib/public-routes.js` are the only page
auth gate.** Adding a private page means adding it there; there is no backend
half to update. Anonymous access to a private page is a Next **307** to
`/login?next=…`, not the old backend 302.

`FRONTEND_RUNTIME` and `FRONTEND_URL` no longer exist in `server.py` — both
described this process's relationship with Next, and it has none.

Production deployment still requires both `dynasty.service` (backend) and
`dynasty-frontend.service` (Next.js) running: nginx needs the Next upstream.

E2E note: page navigations go through `pageUrl()` (`E2E_PAGE_ORIGIN`, :3000)
while `baseURL` stays :8000 for the API. Do **not** move `baseURL` to :3000 —
session minting posts to `${baseURL}/api/test/create-session` and there is no
Next bridge route for `/api/test`.

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
5a. TE basis conversion (2026-07-27, ADR-015 in
   ``docs/league-intelligence/DECISIONS.md``).  TE rows from non-TEP
   sources are lifted onto the basis the board is anchored on via
   ``src/league_intel/te_premium.convert_te_value(from_basis="base",
   to_basis="tepp")`` — KTC's own measured uplift, 1.209 at the top of
   the board rising toward 2.05 down it.  Replaces a flat 1.15 that sat
   below the entire observed range.  ``ktc`` / ``ktcSfTep`` are exempt
   (the anchor IS the TE++ board) and the conversion is a no-op when
   ``from == to``, so the double-count guard is structural.  TEP-native
   sources keep the flat 1.10 — only base ↔ tepp is measured.
   **The target basis is a CONSTANT, not the league's measured TE
   demand**: demand is a leagueKey property and this board is
   scoring-profile scoped, and the two live leagues on
   ``superflex_tep15_ppr1`` want different bases.  That half is overlay
   work.  Rollback: ``RISKIT_FEATURE_TE_BASIS_CONVERSION=0``; an
   explicit operator slider value bypasses the curve regardless.
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
11. Two-way player boost (``_apply_two_way_player_boost``,
    ``_TWO_WAY_PLAYERS`` — today exactly ``{"Travis Hunter": "DB"}``).
    A genuine post-blend OVERRIDE: ``rankDerivedValue`` becomes
    ``max(offense value, alt-position-family value)``, written to both
    the row and the legacy dict.  Runs after the corridor clamp and
    before the Phase 5 pick passes.

The pick stages are NOT in the order this list used to give.  Actual
live order (corrected 2026-07-29 audit):

12. Multiplicative future-year pick discount
    (``config/weights/pick_year_discount.json``) — **Phase 3a, BEFORE
    the global sort**, applied to the blended value so 2027/2028 picks
    settle lower in the ladder.
13. Pick tethering — **Phase 5.2b, AFTER the sort**: current-year slot
    picks inherit the merged rookie pool's values (offense + IDP
    rookies combined), OVERWRITING ``rankDerivedValue`` outright.  A
    tethered current-year pick therefore never carries a discount
    anyway (its year offset is 0 → factor 1.0), but the causal order
    matters when reasoning about future-year picks.

Master curve constants are refit weekly by
``.github/workflows/refit-hill-curves.yml`` (see
``scripts/auto_refit_hill_curves.py``), but the refit **no longer
ships them**.  It produces a *challenger*, scores it against dynasty
boards the fit never reads (``src/model_registry/holdout.py``), records
the verdict in ``config/model_registry/``, and stops.  Production
constants move only via ``scripts/model_registry.py promote`` +
``apply``, run by a human — see ADR-008 in
``docs/roster-trade-intelligence/DECISIONS.md`` (NOTE: the ADR numbers
are per-file, not global — there is a DIFFERENT ADR-008 in
``docs/league-intelligence/DECISIONS.md`` about replacement levels.
Always cite ADRs with their file) for the three reasons
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

### BDVM — the fundamental valuation engine (feature-flagged, ON since 2026-07-28)
``src/bdvm/`` is a SECOND, INDEPENDENT value concept: projection-driven
*fundamental* dynasty value per the Brisket Dynasty Valuation Model
(``docs/research/bdvm-v1/`` — research PDF, verified reference fixture,
and the living ``IMPLEMENTATION_REPORT.md``).  Core rules, all
test-pinned (``tests/bdvm/``):

- **It never touches ``rankDerivedValue``** or any existing route. The
  market board above stays the market-value concept; BDVM is the
  fundamental-value concept; they are compared, never merged in place.
- Reachable behind the ``bdvm_engine`` feature flag, **default ON**
  since 2026-07-28 — the condition it was held off for is met:
  ``scripts/bdvm_build_baseline.py`` writes a real snapshot (2,815
  records for 2026) and the engine answers ``status: "ok"`` with
  726 players priced and 222 honestly unpriced. Additive by
  construction: it never writes ``rankDerivedValue`` or touches an
  existing route, the /rankings Fund-gap column gates on
  ``status == "ok"`` so it self-suppresses without a snapshot, and
  the alert leg seeds a silent per-(user, league) baseline so
  flag-on day cannot flood. Rollback:
  ``RISKIT_FEATURE_BDVM_ENGINE=0`` **and restart** — flag reads are
  cached per process and there is no runtime toggle. Endpoints:
  at ``GET /api/bdvm/values`` (``surplusMode=option|truncated|plain``
  exposes the option-value ablation), ``GET /api/bdvm/roster``
  (strategy capitals + league-relative direction per roster) and
  ``GET /api/bdvm/trades`` (double-positive scan: each side must gain
  in its OWN strategy currency, gated by single-market fairness).
- Projections come from immutable snapshots under
  ``data/bdvm/projections/``: real sources first — **Mike Clay's ESPN
  guide** via ``scripts/fetch_clay_projections.py`` (public CDN PDF,
  ``pdftotext -layout``, team pages only: raw season stat lines for
  offense — the real OFFENSE source — plus a second IDP feed; combined
  tackles split with the shared 0.62 solo share; a two-way player gets
  ONE record combining both sides under the DEFENSIVE position so the
  scoring gate counts everything; same-side name collisions dropped,
  never guessed), **The IDP Show** projections via
  ``scripts/fetch_idpshow_projections.py`` (authenticated
  Datawrapper/Sheet pattern shared with the idpShow rankings fetcher;
  ``--csv`` for a manually downloaded sheet) and the manual-CSV
  adapter — else the §8.3 reconstructed baseline built by
  ``scripts/bdvm_build_baseline.py`` (realized nflverse PPG under the
  league's exact scoring + rookie draft-slot priors, all flagged
  ``is_proxy``; carries real records forward on rebuild).  All real
  sources merge via the shared ``supersede_merge_into_snapshot``
  policy: each replaces its own prior run wholesale and supersedes
  proxies per player while other real sources carry through, so a
  defender covered by Clay AND IDP Show gets a two-source consensus.
  The consensus is **vocabulary-aware**: a stat-line record whose
  league-scored IDP categories are a strict subset of a peer's (Clay
  publishes no TFL/PD — categories this league pays 4.25/5.32 for) is
  down-weighted by the labelled prior
  ``projection_consensus.vocabulary_dominated_weight_mult`` instead of
  dragging the mean down or silently imputing the missing categories;
  affected sources are stamped in ``projection.vocabularyLimitedSources``.
  Structured events (closed ontology,
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

Operational surfaces (post-merge additions):

- **Frontend**: ``/bdvm`` ("Fundamentals", Intel nav group) renders the
  three endpoints — value board (strategy-currency selector, surplus-mode
  ablation, fundamental-vs-market gap + signals), roster strategy
  capitals with expandable assets, and the double-positive trade scan.
  Pure display layer: ``frontend/lib/bdvm.js`` only reshapes/formats
  backend numbers (same materializer rule as ``buildRows``); the flag-off
  503 renders an explicit "engine switched off" state, never a generic
  error (``classifyBdvmFailure`` distinguishes the three 503 variants).
  Dev bridge routes at ``frontend/app/api/bdvm/*``; tests in
  ``frontend/__tests__/bdvm-lib.test.js`` + ``components/bdvm-page.test.jsx``.
- **Snapshot cadence**: ``scripts/refresh_bdvm_projections.py`` (weekly
  ``dynasty-bdvm-refresh`` systemd timer, Tue 06:10 UTC) rebuilds the
  reconstructed baseline, then merges Mike Clay's guide (self-skips
  without poppler-utils or on a CDN 404), then The IDP Show real
  projections (session jar shared with the rankings fetch timer; stage
  self-skips without it). Exit codes 0/1/2 in the playerctx style; runs
  on prod because the endpoints read local gitignored ``data/``.
- **Rankings gap column**: /rankings grows a "Fund gap" column
  (fundamental balanced minus market, tinted by BDVM signal) joined
  onto board rows AT RENDER TIME from ``/api/bdvm/values`` —
  playerId-first, name fallback (``lib/bdvm.js::buildBdvmIndex`` /
  ``bdvmEntryForRow``). The column exists only while the endpoint
  serves an ok payload and vanishes silently on any 503 (flag off, no
  snapshot, wrong league). Ranks and the ``#`` column stay
  backend-stamped — this is display enrichment, never a re-rank; the
  page's ``presorted`` sort switch gained a ``case "gap"`` (nulls sink).
- **Signal alerts**: ``src/api/bdvm_signal_alerts.py`` piggybacks on the
  daily ``/api/signal-alerts/run`` sweep (no new timer). Separate
  detector from the terminal one by design: different label set
  (STRONG_BUY..STRONG_SELL actionable; HOLD/NO_MARKET never) and a
  separate user_kv namespace (``bdvmSignalAlertStateByLeague``, keys
  ``bdvm:{playerId}``). Roster-scoped via the BDVM roster analysis;
  whole-league board computed once per league per sweep. **Baseline
  seeding**: the first sweep for a (user, league) records current
  actionable signals silently (``notifiedAt: 0``) so flag-on day never
  floods inboxes — pinned in ``tests/api/test_bdvm_signal_alerts.py``.
  Flag off → the sweep stamps ``bdvmEnabled: false`` and skips
  entirely.
- **Trade calculator check**: ``POST /api/bdvm/trade-eval``
  (``src/api/bdvm_api.py::get_bdvm_trade_eval``) CES-evaluates ONE
  specific trade in every strategy currency — package math is
  ``package_value`` (§3.13), never a plain sum. Asset refs resolve
  playerId-first → normalized name → pick name (picks use the
  strategy's distribution EV); unresolvable refs are reported in
  ``unresolved`` per side, never silently priced at zero. The route
  parses its body BEFORE the shared gate so the body ``leagueKey``
  reaches the resolver (POST convention — pinned by
  ``tests/bdvm/test_endpoint.py``). Renders as the "Fundamentals
  check (BDVM)" panel on /trade
  (``frontend/components/BdvmTradePanel.jsx``, below RosTradeFitPanel):
  display-only, never touches sideTotals/TradeMeter, silent-vanish on
  any non-ok. Tests: ``tests/bdvm/test_trade_eval.py``.
- **In-season updating** (§8.4): ``run_valuation(actuals=...)`` blends
  realized weekly PPG — scored under the league's exact settings from
  nflverse weekly rows (``src/bdvm/actuals.py``, REG weeks only, its
  own 24h disk-cache key) — into the projection posterior via
  ``blend_ros_mu`` (``w = n_prior/(n_prior+weeks)``, n_prior 6 offense
  / 8 IDP); σ shrinks by ``√w_prior``; ROS drops already-played weeks
  via ``current_week`` (uncapped — after the week-18 slate it is 19 so
  ROS sums zero, never double-counting the banked final week), with a
  per-player boundary-week rule: the in-progress week counts as
  remaining for players who haven't played it yet (nflverse publishes
  game-by-game). The actuals season is the CALENDAR NFL season
  (``current_nfl_season``: Sept–Dec → year, Jan → year−1, else None)
  — NEVER ``currentDraftYear``, which points one season ahead for the
  whole Sept–Jan window and would make the posterior structurally
  unreachable. Distinct players colliding on a normalized name are
  dropped (chimera guard, projection-side policy). Preseason is an
  exact no-op (``meta.inSeason = {"active": false}``). ``bdvm_api``
  refreshes actuals once per UTC day; fetch FAILURES are returned but
  never memoized, so a transient blip can't pin the board to preseason
  values until midnight. Tests: ``tests/bdvm/test_inseason.py``.
- **News → events ingestion**: ``src/bdvm/news_events.py`` piggybacks
  on the same daily signal-alerts sweep (runs BEFORE the per-user
  loop). Aggregated headlines map via conservative ordered keyword
  rules onto 11 of the 18 §7 ontology types (no match → NOTHING;
  ambiguous player mention → NOTHING; advice/listicle language —
  "trade targets", "who makes the cut", rankings/waiver/mock-draft
  vocabulary — → NOTHING; items naming >3 players → NOTHING;
  ACTIVATED_RETURN deliberately unmapped because its impact narrows
  σ). Auto events land in the speculation lane structurally:
  ``confidence = 0.45 < 0.5`` means ``effective_impact`` suppresses
  every non-sigma channel AND clamps ``sigma_mult ≥ 1.0`` — a headline
  can widen uncertainty but can NEVER move a mean or narrow σ; raising
  confidence is a human edit to ``data/bdvm/events/<season>.json``.
  Merge is dedup-by-eventId (``news:<item-id>:<player-key>``) plus
  same-fact suppression (one ``(playerKey, eventType)`` per 14 days —
  N providers ≠ N sigma wideners) with existing-wins; the 90d prune
  touches only ``news:*`` events still at speculation confidence
  (human-raised confidence exempts an event); refuses on corrupt OR
  valid-JSON-wrong-shape files rather than discarding human entries,
  and preserves extra top-level keys (``_comment``) on rewrite. The
  events-file fingerprint (mtime_ns, size) sits in the bdvm_api cache
  key, so every write invalidates cached boards. Tests:
  ``tests/bdvm/test_news_events.py``.
- **Draft board join**: /draft grows a "Fund gap" column on the
  RookieBoard — name-based join only (draft rows are keyed by
  ``playerSlug`` and carry no playerId) — plus a collapsed-by-default
  "Fundamental pick values (BDVM)" panel (balanced-strategy pick
  EV / hit% / median / ceiling beside the market anchor, from
  ``buildBdvmPickRows``). Same silent-vanish posture as the rankings
  gap column; sorting by gap sinks unpriced rows; auction math and
  backend-stamped ranks untouched. Tests:
  ``frontend/__tests__/components/DraftBoardSort.test.jsx``.

### Single Source of Truth: Rankings Override Path
Custom source configurations (user-toggled sources or custom weights) flow through the **SAME** canonical pipeline as the default board. There is no frontend ranking engine, period — not even a fallback. `buildRows` is a pure materializer.

Flow:
1. User toggles a source or changes a weight on `/settings` (writes into `settings.siteWeights`).
2. `useDynastyData` observes the change, calls `fetchDynastyData({siteOverrides})`.
3. `fetchDynastyData` POSTs the override map to `POST /api/rankings/overrides?view=delta` and receives a compact delta payload (~70% smaller than the full contract — see Payload Size Optimization below).
4. `fetchDynastyData` merges the delta onto the cached base `/api/dynasty-data` contract via `mergeRankingsDelta` and returns a fully-populated contract object.
5. `server.py::post_rankings_overrides` invokes `build_rankings_delta_payload(raw_payload, source_overrides=...)` (or `build_api_data_contract` for legacy full-view consumers).
6. `src/api/data_contract.py::_compute_unified_rankings` filters disabled sources and applies overridden weights — same Hill curve, same coverage-aware blend, same robust-median step.
7. `buildRows` materializes the merged contract; it trusts backend stamps verbatim and never recomputes VALUES.

One precise nuance on ranks (documented 2026-07-29 audit — the line
above used to read "never recomputes ranks", which overstated it):
`buildRows` assigns a display ordinal `computedConsensusRank = i + 1`
after sorting (`dynasty-data.js:1366`) and uses it for `r.rank`
(`:1378`) **only** when the backend stamped no `canonicalConsensusRank`
on that row. In practice that is players past the backend's
`OVERALL_RANK_LIMIT` (800) — rows the backend deliberately left
unranked — and it is suppressed for picks and whenever a valuation
overlay is active. A backend-stamped rank always wins.

This is a display ordinal for otherwise-unnumbered rows, not a ranking
engine: no value is recomputed and the sort key is the backend's
`rankDerivedValue`. The no-frontend-ranker rule is intact.

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
- **The two overlays are composed SERVER-SIDE, never on the client.** With
  source overrides active the valuation overlay's ranks are the ranks of
  `default_consensus × factor`, but the correct answer is
  `overridden_consensus × factor` — a board the client cannot construct because
  it never had the overridden consensus in the first place. So
  `POST /api/rankings/overrides?view=delta` accepts `valuation_mode` and
  computes it, and asking for the lens is what narrows that response's scope
  from scoring-profile to leagueKey (it 503s on a league mismatch exactly like
  `/api/valuation/league-adjusted`). The full view refuses the field explicitly
  rather than ignoring it, which would return a market board labelled adjusted.

Regression tests: `frontend/__tests__/valuation-overlay.test.js` (both
materializer key sets — the legacy dict uses `_canonicalConsensusRank` but
`rankDerivedValue`, and the legacy path is the default one), and
`tests/league_intel/test_publish.py` (caller-row isolation, dense contiguous
ranks, anchor-slot-pick exclusion).

### The lens reaches the engines: `valuation_mode`

The overlay above is for the *client* to multiply onto a board it holds.
That covers `/rankings` and nothing else — every engine (trade suggestions,
the arbitrage finder, angles, waivers, the terminal, the simulator) runs
server-side off `latest_contract_data` and never saw it. Switching the board
changed the rankings page and left the trade advice market-priced, with no
field on any response saying which was which.

Every league-scoped engine endpoint now accepts `valuation_mode`
(`"market"` | `"leagueAdjusted"`; body field for POST, `valuationMode` query
param for GET) and answers from the corresponding board:

| endpoint | wired | note |
|---|---|---|
| `POST /api/trade/suggestions` | yes | |
| `POST /api/trade/finder` | yes | our side only — the market anchor stays retail, else the arbitrage gap closes itself |
| `POST /api/angle/find`, `/api/angle/packages` | yes | same asymmetry |
| `POST /api/trade/simulate` | yes | |
| `POST /api/waiver/suggestions` | yes | no UI caller — `/waivers` computes client-side from contract rows, which already carry the lens |
| `POST /api/waiver/faab-recommend` | yes | a bid is derived from a value |
| `GET /api/terminal` | yes | applies on top of the cross-league hybrid contract |
| `POST /api/trade/simulate-mc` | n/a | values arrive in the request body; the client already sends whichever board it holds |
| `GET /api/draft-capital` | n/a | `compute_scarcity` has no `PICK` key, so picks carry factor 1.0 and the lens is a no-op for the pick board itself. Its `rookieKtcValue` IS a player value and does move under the lens — `/draft` therefore stays market-priced and says so via `ValueBasisNote` rather than being threaded |

Mechanism, in one place: `server.py::_valuation_scoped_contract` fetches the
league's factors and hands the engine a contract whose `playersArray` rows are
already repriced (`src/league_intel/overlay.py`). No engine knows the feature
exists, because every engine reads exactly one value — `rankDerivedValue`.

Four rules that are load-bearing:

- **`overlay.adjusted_rows` returns EVERY row, not the ranked ones.**
  `compact_ranks_and_tiers` returns only rows it ranked, dropping unranked rows
  and clearing current-year slot picks. Serving that subset measured 740 of
  1093 rows on the live contract — every 2026 pick gone from the trade
  calculator under the adjusted lens. It ranks our copies in place instead.
- **Nothing mutates `latest_contract_data`.** It is a shared module global; one
  in-place multiply would reprice the market board for every other request.
- **Degrade, never fail.** No roster snapshot, an incoherent adjusted board, or
  a broken overlay all serve the *market* board with a `valuationNote` naming
  the reason. Refusing would take down working engines to protect an optional
  lens.
- **Every response stamps `valuationMode` — including `"market"`.** "This is
  the market board" and "this field is missing" must not read the same.
  `tests/api/test_valuation_mode_threading.py` statically requires every
  handler that applies the lens to also stamp it.

Client side: `frontend/lib/valuation-mode.js` is the single answer to "which
board did the user pick" for all six call sites. `useTerminal` keys its cache
on the mode — a cache without it serves the stale market payload for the full
TTL after a switch, which looks exactly like the toggle being broken.

**The adjusted board is a toggle, not the default, and that is a measured
decision** — see `docs/adjusted-board-backtest.md`. Ranked against realized
2025 scoring over 572 players, four framings all return "no difference
detected" and three of four lean negative. Re-run
`scripts/backtest_adjusted_board.py` after any axis change.

### Rankings Override Payload Size Optimization
The `POST /api/rankings/overrides` endpoint supports two response views:

- `view=full` (default, backward-compat): returns the full canonical contract (~4 MB uncompressed, identical shape to `GET /api/data`).
- `view=delta` (default for frontend): returns only the override-sensitive fields per player, keyed by `displayName`, dropping the legacy `players` dict, `sleeper`, `methodology`, `poolAudit`, and other override-invariant blocks. Production payload drops from ~4 MB to ~1.25 MB uncompressed, and to ~100 KB over the wire with FastAPI's `GZipMiddleware`. The frontend merges the delta onto its cached base `/api/data?view=app` payload.

Regression test: `tests/api/test_source_overrides.py::TestBuildRankingsDeltaPayload` pins the delta shape, byte-size bounds, and the invariant that every field in `_DELTA_PLAYER_FIELDS` round-trips through a manual merge identically to the full-contract path.

See `tests/api/test_source_overrides.py` for the full contract spec.

### The sharp cohort: one pool, many surfaces

`src/sharp/cohort.py::cohort_members` is THE definition of "who is a
sharp". Every sharp-powered surface resolves its manager pool through
it, and none of them may keep a second list or add a qualification rule:

| surface | module |
|---|---|
| Sharp Buy/Sell Tracker (`/market/sharp-tracker`) | `src/sharp/market.py` |
| Sharp Roster Percentage (`/market/sharp-roster-percentage`) | `src/sharp/roster_percentage.py` |
| roster collection pass | `src/sharp/roster_collect.py` |
| activity crawl | `scripts/crawl_sharp_activity.py` |

`market.py` re-exports `CohortMember`, `cohort_members`,
`curated_members`, `provisional_members` and `load_ffpc_config`, so
`sharp_market.cohort_members` still resolves and the monkeypatch seam
existing tests use is preserved. Note the re-export is a
`from ... import` binding taken at import time — a test that patches
the cohort module before importing `market` captures the stub.

Qualification is decided in `src/sharp/score.py` +
`config/sharp/scoring_v2.json` over evidence from
`src/sharp/platform_records.py`; league eligibility in
`src/intel/league_filter.py` (dynasty only, ≥ 2 seasons). `cohort.py`
only SELECTS and DEDUPLICATES.

**Three sharp crawl passes, in order** — each depends on the one before,
which is why the timers are staggered:

1. `scripts/discover_sharp_graph.py` (04:20 UTC) — finds MANAGERS
2. `scripts/crawl_sharp_records.py` (04:50) — finds their RESULTS, which
   is what makes them scoreable
3. `scripts/crawl_sharp_rosters.py` (05:50) — finds what they currently
   OWN, which is what the roster-percentage board is made of

Two things the roster pass depends on, both fixed rather than worked
around:

- `discovery.py` records a `league_memberships` row at USER-expansion
  time as well as league-expansion time. It used to record one only when
  a league was expanded, so leagues left on the frontier by the budget
  had none — invisible to anything asking "which leagues does this
  manager play in", which silently bounded the roster crawl to the
  expanded subgraph.
- The roster pass orders leagues through
  `record_queue.prioritize_league_ids` (never-collected first, then
  oldest), the same fair ordering the records crawl uses. Sorting by
  league id meant a budget-capped run re-collected the same prefix
  forever and never reached the tail.

`server.py` calls `_sharp_service.register_http_routes()` explicitly
after importing the module. The import-time side effect alone is not
enough: anything that imports `src.sharp.service` before the app exists
makes it a no-op, and the module cache means the later import re-runs
nothing — `/api/sharp/market` then 404s with no other symptom.

Roster observations live in `sharp_rosters` / `sharp_roster_assets` /
`sharp_roster_asset_spans` / `sharp_roster_observations`
(`src/sharp/roster_store.py`), created by a plain
`CREATE TABLE IF NOT EXISTS` that is deliberately NOT wired to
`platform_ledger.PLATFORM_SCHEMA_VERSION` — bumping that re-runs the
whole platform migration on every deployed ledger to add four additive
tables.

Counting rules are enforced by primary keys rather than by caller
discipline: one row per roster, one row per (roster, player). The
denominator is ROSTERS, not people — a sharp with five dynasty teams
contributes five observations — and it is computed PER PLAYER, because a
linebacker cannot be rostered in a league with no IDP slots. Full
methodology and the known limitations (no general-dynasty ownership feed
exists; FFPC contributes zero rosters until a roster-bearing URL is
configured) are in `docs/sharp-roster-percentage/METHODOLOGY.md`.

### Adapter Pattern
Pluggable source adapters (`src/adapters/base.py` defines the frozen contract). All adapters emit `RawAssetRecord` dataclasses with normalized fields.

Actual contents of `src/adapters/` (corrected 2026-07-29 audit — the
list here previously named DLF CSV / KTC stub / manual CSV adapters
that are not in the tree):

| module | status |
|---|---|
| `scraper_bridge_adapter.py` | live (`server.py`) |
| `sleeper_trending.py` | live (`server.py`) |
| `ktc_crowd_faab.py` | live (waiver/FAAB path) |
| `base.py` | the frozen contract — imported by tests only, kept as the interface definition |

Source ingestion itself lives in `Dynasty Scraper.py` + `scripts/` fetchers, not in an adapter per source.

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
| `SLEEPER_LEAGUE_ID` | Primary Sleeper league | -- |
| `BACKEND_API_URL` | Backend origin for the Next bridge routes | `http://127.0.0.1:8000` |

`FRONTEND_RUNTIME` and `FRONTEND_URL` were removed from `server.py` with the
page proxy (#555). The backend no longer talks to Next, so Next's location is
nginx's business; `BACKEND_API_URL` is the surviving direction of that link,
read by the Next bridge routes.

## Safety

- Do not exfiltrate private data
- Do not run destructive commands without approval
- Prefer reversible operations
- Be explicit before any action affecting production, deployment, credentials, or public output
