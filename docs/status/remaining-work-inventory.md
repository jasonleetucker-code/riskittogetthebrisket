# Remaining Work Inventory

_Generated: 2026-03-14_

---

## Critical Blockers

These items block the transition from legacy-only to canonical-engine-fed production.

### CB-1: Wire canonical pipeline output into `server.py`
- **What**: `server.py` reads only `dynasty_data_*.json` from the legacy scraper. The canonical pipeline (`scripts/canonical_build.py`) writes `data/canonical/canonical_snapshot_*.json` but nothing in production reads it.
- **Why critical**: Until this is wired, the entire `src/` engine is a parallel system with no production impact.
- **Depends on**: CB-2 (league refresh must produce real adjustments for canonical values to be competitive with legacy).
- **Files**: `server.py` (data loading path), `src/api/data_contract.py` (may need canonical-aware contract building).

### CB-2: Implement league context engine (`src/league/`)
- **What**: `src/league/` is empty. Needs: replacement baselines, scarcity multipliers, position-demand math, pick curve application.
- **Why critical**: Without league context, canonical values are raw blended rankings — not league-adjusted. The trade calculator and rankings need scarcity/replacement to be useful.
- **Depends on**: Founder decisions on replacement math parameters.
- **Files**: `src/league/` (new), `config/leagues/default_superflex_idp.template.json` (input), `scripts/league_refresh.py` (currently scaffold).

### CB-3: Resolve founder decisions (blueprint §11)
- **What**: Source weights, package tax multiplier, rookie optimism setting, contender vs rebuilder heuristics, Market mirror vs My board default.
- **Why critical**: These parameterize the league and trade engines. Can't finalize league context or trade API without them.
- **Action**: Schedule decision session with Jason. Document decisions in `config/` or `docs/`.

---

## High-Priority Unfinished Work

### H-1: Add KTC live adapter (or stable seed pipeline)
- **What**: KTC adapter is stub-only and disabled in config. Multi-source blending needs ≥2 real sources.
- **Files**: `src/adapters/ktc_stub_adapter.py`, `config/sources/dlf_sources.template.json`.
- **Option A**: Implement live KTC scraping.
- **Option B**: Establish reliable KTC seed CSV pipeline (manual export → adapter).

### H-2: Build new trade API with blueprint features
- **What**: Package adjustment, lineup impact, fairness band + balancing suggestions, per blueprint §7.
- **Files**: New files in `src/api/` or integrated into `server.py`.
- **Depends on**: CB-2 (league context for lineup impact), CB-3 (package tax decision).

### H-3: Build roster/team view
- **What**: Team values, strengths/weaknesses, roster profiles per blueprint §8.
- **Files**: New `frontend/app/roster/` or `frontend/app/team/` page. New API endpoint.
- **Depends on**: CB-1 (canonical values in production), Sleeper roster import.

### H-4: Build player detail page with trend
- **What**: Current value, trend history, tier, source breakdown per blueprint §8.
- **Files**: New `frontend/app/player/[id]/` page. Requires value history data.
- **Depends on**: Value history tracking (not yet implemented).

### H-5: Unit tests for core pipeline modules
- **What**: Adapters, identity matcher, canonical transforms, name cleaning have zero test coverage.
- **Files**: New `tests/adapters/`, `tests/identity/`, `tests/canonical/`, `tests/utils/`.
- **Why high**: These modules are the foundation. Any regression in matching or transforms silently corrupts values.

### H-6: Wire Next.js frontend auth to `server.py` auth
- **What**: Next.js login page (`frontend/app/login/page.jsx`) is a demo placeholder. Real auth is in `server.py`. Next.js pages have no route protection.
- **Risk**: If Next.js is ever exposed publicly (runtime=next or auto), there's no auth barrier.
- **Files**: `frontend/app/login/page.jsx`, potentially Next.js middleware.

---

## Medium-Priority Follow-Up Work

### M-1: Dynasty Nerds adapter
- Source mentioned in blueprint §1. No adapter or config exists.

### M-2: Yahoo values adapter
- Implied by multi-source strategy. No adapter or config exists.

### M-3: IDPTradeCalc adapter (offensive + IDP coverage)
- Implied by IDP emphasis. Would strengthen IDP value coverage.

### M-4: IDP-specific pipeline differentiation
- **What**: IDP assets pass through the pipeline with `is_idp=true` flag but receive no IDP-specific processing (no IDP scarcity, no IDP replacement baselines, no IDP-only UI filtering in Next.js).
- **Depends on**: CB-2 (league engine with IDP positions).

### M-5: Value history / trend tracking
- **What**: Blueprint promises trend charts. Currently canonical snapshots are written but not compared across time.
- **Files**: Need `value_history` storage (DB or JSON series), delta computation, API endpoint.

### M-6: Settings page in Next.js
- **What**: Blueprint §8 lists Settings surface. Static app has settings/site matrix. Next.js has no settings page.
- **Files**: New `frontend/app/settings/` page.

### M-7: Improve mobile experience
- **What**: Trade page has mobile sheet pattern. Rankings uses horizontal scroll. No mobile nav drawer. No touch gestures.
- **Files**: `frontend/app/layout.jsx` (mobile nav), `frontend/app/rankings/page.jsx` (mobile layout).

### M-8: Documentation of canonical → production cutover criteria
- **What**: No documented exit criteria for when `server.py` should switch from legacy scraper to canonical pipeline as primary data source.
- **Action**: Define criteria (e.g., ≥2 sources, identity resolution >95%, league engine complete, E2E tests pass on canonical data).

---

## Low-Priority Polish / Future Enhancements

### L-1: Trade finder / target list (Phase 7)
### L-2: Contender vs rebuilder toggle (Phase 7)
### L-3: Historical value charts + regression alerts (Phase 7)
### L-4: Logistic curve option for canonical transforms
### L-5: Persistent identity DB (SQLite from existing schema)
### L-6: Session persistence across server restarts (DB or Redis)
### L-7: Cross-league trade database

---

## Technical Debt / Cleanup

### TD-1: Hardcoded default credentials
- `server.py` line 93: `JASON_LOGIN_PASSWORD = "Elliott21!"` in source. Move to env-only with no default.

### TD-2: Cookie security flag
- `JASON_AUTH_COOKIE_SECURE = False` by default. Should be True in production.

### TD-3: Blueprint backlog checkboxes
- Section 10 of `BLUEPRINT_EXECUTION.md` has all `[ ]` unchecked. Update to reflect actual progress.

### TD-4: `src/README.md` accuracy
- Describes `src/api/` as "FastAPI services for calculator, rankings, roster endpoints." Actually contains only a contract validator. Update description.

### TD-5: `scripts/league_refresh.py` honesty
- Runs in Jenkins but outputs stub data. Either implement or remove from Jenkins pipeline until ready.

### TD-6: Legacy scraper size
- `Dynasty Scraper.py` is 501KB. Monolithic. As adapters mature, break down or sunset.

---

## Verification / Testing Gaps

### VG-1: No adapter unit tests
### VG-2: No identity matcher unit tests
### VG-3: No canonical transform unit tests
### VG-4: No name_clean unit tests
### VG-5: No auth flow E2E test (all E2E tests bypass auth via static runtime)
### VG-6: No deploy/rollback integration test
### VG-7: No performance baseline or target metrics documented
### VG-8: No load testing for `/api/data` endpoint
