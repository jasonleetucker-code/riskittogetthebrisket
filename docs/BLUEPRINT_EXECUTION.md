# Risk It to Get the Brisket — Operating Blueprint

_Last updated: 2026-03-12_

This is the working master blueprint for what the product is becoming, plus a
repo-grounded execution checkpoint. It is not a claim that every module is
already complete.

## 1) Product Vision
Risk It to Get the Brisket is evolving from a single trade calculator into a
full dynasty platform with first-class IDP support, league-native valuation,
and a public league identity layer.

North-star outcomes:
- Measure value correctly across players, picks, scoring formats, and league settings.
- Turn values into action with calculator and realistic trade suggestions.
- Represent league identity/history publicly without leaking private edge.
- Deliver full-power mobile and desktop experiences with fast load and stable interactions.

## 2) Non-Negotiable Product Rules
- No fake completeness: feature existence in code is not proof of live wiring.
- Mobile is not reduced mode: no desktop-only critical workflows.
- Custom league reality matters: scoring, roster structure, IDP, pick economy.
- Public pages must not expose private valuation or optimization internals.
- Data quality and source completeness are more important than visual polish.
- Rankings, calculator, and suggestions must share the same valuation backbone.

## 3) Major Product Pillars

### 3.1 Unified Valuation Engine
Target behavior:
- Aggregate intended sources when available.
- Preserve per-source columns.
- Resolve all assets to canonical entities.
- Normalize to canonical 0-9999 economics.
- Produce one backend-authoritative value bundle consumed everywhere.

Target source family includes:
- KeepTradeCut
- Dynasty IDP Trade Calculator
- Draft Sharks
- DLF CSV sources
- Dynasty Nerds
- Yahoo
- FantasyPros
- Dynasty Daddy
- FantasyCalc
- FantasyNavigator (or equivalent future source when integrated)

### 3.2 Custom League Scoring Translation
Target behavior:
- Ingest Sleeper scoring settings for target league.
- Compare against explicit baseline/test scoring config.
- Use historical stat profiles to derive position/player effects.
- Feed scoring effects into value resolution and trade evaluation.

### 3.3 Trade Decision System
Target behavior:
- Stable calculator with full desktop/mobile parity.
- Package/consolidation logic that is explainable and realistic.
- Upgrade from passive grading to proactive sendable trade generation.

### 3.4 Public League Pages
Target behavior:
- Public-safe league hub with history, franchises, awards, records, draft,
  trades, constitution, money, and media modules.
- Strong boundary between public content and private strategy edge.

### 3.5 Mobile, Performance, and Reliability
Target behavior:
- Fast first paint, low interaction latency, no broken mobile controls.
- Clear freshness/source health visibility.
- Reliable deploy/update/sync flow with rollback safety.

## 4) Authoritative Runtime Architecture (Truth)

Live authoritative value path today:
- `Dynasty Scraper.py` builds runtime player/pick payload.
- `src/api/data_contract.py` builds and validates `/api/data` contract.
- `server.py` publishes `/api/data`, `/api/status`, startup/runtime/full views.

Explicitly non-authoritative scaffold path today:
- `src/adapters`, `src/identity`, `src/canonical`, `src/league`
- `scripts/source_pull.py`, `scripts/identity_resolve.py`,
  `scripts/canonical_build.py`, `scripts/league_refresh.py`
- `/api/scaffold/*` endpoints

Frontend runtime truth:
- `FRONTEND_RUNTIME=static` is default live runtime mode in `server.py`.
- Next runtime is available in `next` or `auto`, but static remains default.

## 5) Canonical Value Bundle Contract
For each known player/pick, resolver output must include:
- `rawValue`
- `scoringAdjustedValue`
- `scarcityAdjustedValue`
- `bestBallAdjustedValue`
- `fullValue`
- `confidence`
- `sourceCoverage`
- `adjustmentTags`
- layer diagnostics/metadata used by rankings/calculator/player detail

Current live contract source:
- `src/api/data_contract.py` (`CONTRACT_VERSION` in code; currently `2026-03-19.v5`)

## 6) Module Architecture Map
- Module A: Canonical entity layer (players, picks, aliases, identity map)
- Module B: Source ingestion layer (scrape/API/CSV pulls + provenance)
- Module C: Normalization layer (rank/value transforms + blending)
- Module D: League context layer (Sleeper scoring + scarcity/replacement)
- Module E: Valuation engine (authoritative value bundles and diagnostics)
- Module F: Trade engine (package math, fairness, side deltas)
- Module G: Trade suggestions engine (sendable offers + realism strategy)
- Module H: Public league pages engine (history/records/awards/money/media)
- Module I: Frontend experience layer (mobile + desktop parity)
- Module J: Ops/observability layer (deploy, health, freshness, rollback)

## 7) Phased Roadmap
- Phase 1: Foundation stabilization (mobile parity, broken interactions, speed, deploy truth)
- Phase 2: Value engine completion (source breadth, mapping, normalization, shared backbone)
- Phase 3: League scoring intelligence (Sleeper-aware translation in live valuation)
- Phase 4: Calculator decision-tool upgrade (deeper explainability and package realism)
- Phase 5: Trade Suggestions v1 (realism/strategy modes, exclusions, counters, sendability)
- Phase 6: Public League Pages expansion (history ecosystem without private-edge leakage)
- Phase 7: Intelligence/content layer (interpretation signals, not valuation truth source)

## 8) Current Execution Checkpoint (Repo-Grounded)

### 8.1 Status by Module
- Valuation engine: `mostly working` (live in scraper + contract resolver).
- Source ingestion (live runtime path): `mostly working` (multi-source scrape + diagnostics).
- Source ingestion (`src/` scaffold path): `partial` (artifact pipeline, not live authority).
- Canonical mapping: `partial` (live heuristics in scraper; scaffold identity exists but non-live).
- 0-9999 normalization: `mostly working` (live composite + contract clamping).
- Scoring translation: `partially built` (live scoring modules wired; still evolving).
- Trade calculator (static runtime): `mostly working`.
- Trade calculator (Next runtime): `partially built`.
- Trade suggestions: `partially built` (static-only implementation; not migrated to Next).
- Rankings (static runtime): `mostly working`.
- Rankings (Next runtime): `mostly working`.
- Public League Pages (Next): `scaffolded only` (no live `frontend/app/league/page.*`; runtime authority remains FastAPI static League shell).
- Public/private boundary: `partial` (implemented in Next sanitization; backend public contract still needed).
- Mobile parity overall: `wired but brittle` (strong static coverage, partial Next parity).
- Performance/reliability: `partial` (recent wins, but shared JS and dual-runtime complexity remain).
- Deployment/ops: `mostly working` (GitHub Actions + Jenkins + health checks + runtime switching).

### 8.2 Phase Assessment
Actual position:
- Between `Phase 1` and early `Phase 2`.

Why:
- Foundation hardening and runtime-truth work is real.
- Authoritative value bundles are live.
- But architecture is still split (static default + partial Next migration), and
  `src` canonical pipeline is not runtime authority yet.

## 9) Next Implementation Priorities (Ordered)

### Priority 1 (highest leverage): Runtime authority cutover plan for migrated Next routes
Objective:
- Move from "Next exists" to controlled runtime authority for migrated routes.

Work:
- Add explicit backend route handling for `/calculator` parity path in `server.py`
  (right now backend routes include `/trade` but not `/calculator`).
- Define route-by-route cutover toggles and rollback checks.
- Keep static fallback safe until parity gates pass.

Acceptance criteria:
- `/`, `/rankings`, `/league`, `/calculator` reachable intentionally under chosen runtime mode.
- Clear rollback path documented and tested.

### Priority 2: Finish authoritative contract consumption in all active UIs
Objective:
- Remove remaining value-path ambiguity between legacy and migrated surfaces.

Work:
- Continue reducing frontend fallback chains in `frontend/lib/dynasty-data.js`.
- Keep `valueBundle` as primary and legacy aliases strictly compatibility-only.
- Add explicit mismatch diagnostics where any UI recomputes known-asset values.

Acceptance criteria:
- Rankings/calculator/player detail parity holds for all selected value bases.
- Confidence/sourceCoverage remain visible in active user surfaces.

### Priority 3: Trade suggestions migration into shared service layer
Objective:
- Prevent static-only "advanced" suggestions from becoming dead-path logic.

Work:
- Extract suggestion logic from `Static/js/runtime/30-more-surfaces.js` into
  shared backend or shared library service with explicit contracts.
- Reuse authoritative value bundles and package logic.
- Expose realism/strategy/exclusions/counter outputs through one interface.

Acceptance criteria:
- Same suggestion model reachable from the active calculator runtime.
- No duplicate suggestion engines with different behavior.

### Priority 4: Public League data contract and admin-backed manual datasets
Objective:
- Make League Pages truthful and extensible without leaking private internals.

Work:
- Add a dedicated public-safe backend contract endpoint (allowlist-first).
- Add commissioner-managed stores for missing manual-first domains
  (`rules_versions`, payouts ledger, media posts).
- Keep missing-history modules explicitly blocked or provisional.

Acceptance criteria:
- League pages no longer rely on broad private payload sanitization alone.
- Constitution/money/media can be maintained without code edits.

### Priority 5: Historical data backbone for Phase 2+ league modules
Objective:
- Unlock records/awards/history with real attribution integrity.

Work:
- Build ingestion/backfill for seasons, standings, matchups, weekly team scores,
  weekly player scores, and roster ownership by week.
- Add quality gates before enabling records/awards outputs.

Acceptance criteria:
- Historical attribution is reproducible and auditable.
- Awards/records modules avoid fabricated outputs.

## 10) What Should Wait
- Do not prioritize intelligence/content ingestion as valuation input before
  valuation/scoring/public-contract foundations are stable.
- Do not claim `src/adapters|identity|canonical|league` as runtime authority
  until wired into live `/api/data`.
- Do not force full Next cutover before calculator + mobile parity gates pass.

## 11) Core Evidence Paths
- Runtime authority and frontend mode:
  - `server.py`
- Live value bundle resolver + diagnostics:
  - `src/api/data_contract.py`
- Live source ingestion, normalization, scoring, and diagnostics:
  - `Dynasty Scraper.py`
- Scoring translation modules:
  - `src/scoring/*`
- Next migrated routes and loaders:
  - `frontend/app/*`
  - `frontend/lib/dynasty-data-server.js`
  - `frontend/lib/dynasty-source.js`
  - `frontend/lib/dynasty-data.js`
- Trade/Rankings migration shell pages in Next:
  - `frontend/app/trade/page.jsx`
  - `frontend/app/rankings/page.jsx`
- Public league route implementation:
  - `server.py` (`/league`, `/league/{league_path:path}`)
  - `Static/league/index.html`
  - `Static/league/league.js`
  - authority reference: `docs/RUNTIME_ROUTE_AUTHORITY.md`
- Scaffold (non-authoritative) pipeline:
  - `scripts/source_pull.py`
  - `scripts/identity_resolve.py`
  - `scripts/canonical_build.py`
  - `scripts/league_refresh.py`
- Regression and contract checks:
  - `tests/api/test_value_pipeline_golden.py`
  - `tests/api/test_status_compact.py`
  - `tests/e2e/*`
  - `scripts/validate_api_contract.py`

