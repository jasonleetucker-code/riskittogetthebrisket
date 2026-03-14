# Master Implementation Audit

_Generated: 2026-03-14_

---

## 1. Executive Summary

The Risk It to Get the Brisket dynasty platform is a **dual-track system**: a mature legacy runtime (`Dynasty Scraper.py` + `server.py` + `Static/index.html`) and a partially-built new canonical engine (`src/`). The legacy track is production-live and feature-rich. The new engine has real implementations in adapters, identity, canonical transforms, and scoring — but is **not yet wired into the production data path**.

**What works today**: Scraping, data serving, trade calculator, rankings, auth gate, deploy pipeline, E2E regression, Jenkins CI.

**What the blueprint promises but doesn't exist yet**: Canonical-engine-fed rankings, new trade API with lineup impact, league context engine (scarcity/replacement), IDP-specific pipeline, multi-source blending in production.

The biggest risk is not code quality — it's the **disconnect between the new engine pipeline and the live runtime**. The new engine scripts run and produce output, but `server.py` and the frontend consume only the legacy scraper's output.

---

## 2. Blueprint vs Current State — Full Comparison

### Phase 0: Repo Spine

| Blueprint Item | Status | Evidence |
|---------------|--------|----------|
| Document current legacy stack | **Complete** | `docs/REPO_INVENTORY.md`, Migration Honesty section |
| Carve out `/src` structure | **Complete** | `src/adapters/`, `src/identity/`, `src/canonical/`, `src/league/`, `src/api/`, `src/data_models/`, `src/utils/`, `src/scoring/` all exist |
| Add `.env.example` + config loaders | **Complete** | `.env.example` at root; `src/utils/config_loader.py` is functional (repo_root, load_json, save_json, canonical_data_dir with env override) |

### Phase 1: Source Adapters & Raw Store

| Blueprint Item | Status | Evidence |
|---------------|--------|----------|
| Define adapter contract | **Complete** | `src/adapters/base.py` defines `SourceAdapter` protocol + `AdapterResult` dataclass; `src/adapters/README.md` has frozen contract |
| DLF CSV adapter | **Complete** | `src/adapters/dlf_csv_adapter.py` (148 lines) — dual-fallback CSV parser, field normalization, robust error handling |
| KTC scrape stub | **Scaffolded** | `src/adapters/ktc_stub_adapter.py` (112 lines) — reads seed CSVs only, no live scraping |
| Manual CSV loader | **Placeholder** | `src/adapters/manual_csv_adapter.py` (26 lines) — returns empty records with warning |
| Raw snapshot storage | **Complete** | `data/raw/README.md` specifies layout; `scripts/source_pull.py` writes versioned snapshots to `data/raw/{source}/{season}/{snapshot_id}/` with manifest + parse log + JSONL |
| CLI/cron entrypoint | **Complete** | `scripts/source_pull.py` is the CLI entrypoint; Jenkinsfile stage 3 ("Ingest") runs it |
| Unmatched-player report | **Partial** | Identity resolution reports unresolved/low-confidence/duplicates, but no dedicated "unmatched from ingest" report |

### Phase 2: Identity Mapping

| Blueprint Item | Status | Evidence |
|---------------|--------|----------|
| Master `players` table + alias ingestion | **Complete** | `src/identity/models.py` defines PlayerRow, PlayerAliasRow, PickRow, PickAliasRow; `migrations/0001_identity_schema.sql` creates tables with FKs and indexes |
| CLI to reconcile new names | **Complete** | `scripts/identity_resolve.py` — loads raw snapshot, calls `build_identity_resolution()`, writes report |
| Unit tests for suffix/punctuation/team changes | **Missing** | No identity-specific tests. `src/utils/name_clean.py` handles suffix stripping, ASCII folding, but has no test coverage |
| Identity matching logic | **Complete** | `src/identity/matcher.py` (261 lines) — 4-tier confidence ladder (1.00→0.98→0.93→0.85), quarantine threshold, duplicate alias detection, single/multi-source tracking |

### Phase 3: Canonical Pipeline

| Blueprint Item | Status | Evidence |
|---------------|--------|----------|
| Define universes + weight config | **Complete** | `src/canonical/transform.py` defines KNOWN_UNIVERSES = {offense_vet, offense_rookie, idp_vet, idp_rookie, picks}; `config/weights/default_weights.json` has per-source weights |
| Percentile + curve transforms | **Complete** | `transform.py`: `percentile_from_rank()`, `percentile_to_canonical()`, power curve with configurable exponent (default 0.65), CANONICAL_SCALE=9999 |
| Source blending + snapshot versioning | **Complete** | `blend_source_values()` uses weighted averages; `write_canonical_snapshot()` versions output with run_id + timestamp |
| Store canonical assets + value history | **Partial** | Canonical snapshots written to `data/canonical/`. No value history table or trend tracking yet. |

### Phase 4: League Context

| Blueprint Item | Status | Evidence |
|---------------|--------|----------|
| League settings schema + import | **Scaffolded** | `config/leagues/default_superflex_idp.template.json` exists with teams/starters/pick_model. No engine code to consume it. |
| Starter demand + replacement math | **Not started** | `src/league/` contains only `.gitkeep` |
| Scarcity multipliers + rookie optimism dial | **Not started** | No implementation |
| Pick curve + time discount module | **Scaffolded** | Config template has `future_year_discount` values. No engine code. |

### Phase 5: Trade API + Calculator

| Blueprint Item | Status | Evidence |
|---------------|--------|----------|
| Package adjustment logic | **Not started** | No new trade engine code anywhere in `src/` |
| Lineup impact service | **Not started** | No implementation |
| REST endpoint + CLI | **Not started** | `src/api/` has only `data_contract.py` (validator, not API services) |
| Frontend calculator view | **Complete (legacy path)** | `frontend/app/trade/page.jsx` (314 lines) — fully functional two-sided trade builder with 4 value modes, persistent workspace, live verdict. Consumes legacy `/api/data` payload. |
| Static calculator | **Complete (legacy)** | `Static/index.html` has full calculator |

### Phase 6: Rankings + Roster Dashboards

| Blueprint Item | Status | Evidence |
|---------------|--------|----------|
| Rankings endpoint + table component | **Complete (legacy path)** | `frontend/app/rankings/page.jsx` (277 lines) — sortable, filterable, auto-tiered rankings with CSV export. Consumes legacy `/api/data`. |
| Roster/team view | **Not started** | No roster/team view page or API |
| Player detail page with trend | **Not started** | No player detail page. No trend/history data. |

### Phase 7: Advanced Tooling

| Blueprint Item | Status | Evidence |
|---------------|--------|----------|
| Trade finder / target list | **Not started** | |
| Contender vs rebuilder toggle | **Not started** | |
| Historical value charts + regression alerts | **Not started** | |

---

## 3. Verified Complete

These items are **fully wired, reachable, and used in production**:

1. **`server.py` FastAPI backend** (1,793 lines) — serves `/api/data`, `/api/status`, `/api/health`, `/api/scrape`, auth endpoints, scaffold endpoints, frontend routing. Live on Hetzner at `riskittogetthebrisket.org`.

2. **FRONTEND_RUNTIME system** — `static`/`next`/`auto` modes implemented, documented in 3 docs, tested in E2E.

3. **Auth gate** — Single-user auth with session cookies, HttpOnly, redirect-to-login pattern. Username/password env-configurable (default hardcoded — security note). Protected routes: `/app`, `/rankings`, `/trade`, `/login`, `/index.html`.

4. **`/api/data` contract** (v2026-03-10.v2) — Versioned, validated at runtime and CI. Serves full/runtime/startup payload modes with ETag caching and gzip.

5. **Scraper lifecycle** — `Dynasty Scraper.py` invoked via importlib, progress-tracked, timeout-guarded (7200s), stall-detected (900s), auto-scheduled (every 2h).

6. **Deploy pipeline** — GitHub Actions workflow (335 lines) → SSH to Hetzner → `deploy.sh` with force checkout, venv rebuild, systemd restart, health verification, auto-rollback.

7. **Jenkins CI** — 12-stage pipeline: ingest → validate → identity → canonical → league → report → smoke → contract → frontend build → regression.

8. **E2E regression** — Playwright suite targeting 3 viewports (desktop + 2 mobile). 5 test cases covering API contract, rankings, trade calculator.

9. **Scoring module** — `src/scoring/` (11 files, 1,016 lines) fully implemented: Sleeper ingest, baseline config, feature engineering, archetype model, player adjustment, backtest, delta scoring. Integrated into legacy `compute_empirical_lam()` flow.

10. **Landing page routing** — `server.py` serves `landing.html` at `/`, `/league` as public entry, auth-gated `/app`, `/rankings`, `/trade`.

---

## 4. Partial / Incomplete

| Item | What Exists | What's Missing |
|------|------------|----------------|
| **Source adapters** | DLF CSV adapter works. KTC reads seed CSVs. | KTC live scraping. Manual CSV adapter unimplemented. No Dynasty Nerds, Yahoo, or IDPTradeCalc adapters. |
| **Identity resolution** | Matcher with confidence ladder, schema, SQL migration, CLI script. | No unit tests. No persistent DB — runs in-memory from JSON snapshots. Reconciliation is automated, no manual review queue. |
| **Canonical pipeline** | Transform logic (11 functions), pipeline orchestrator, weight config, validation with jump detection. | No value history/trend tracking. Not wired to production data path — `server.py` doesn't consume canonical output. |
| **Trade calculator** | Full frontend (Next.js + Static). 4 value modes. Persistent workspace. | Uses legacy values only. No package adjustment, lineup impact, fairness bands, or balancing suggestions per blueprint. |
| **Rankings** | Full frontend with sorting, filtering, tiers, CSV export. | No source contribution breakdown. No trend data. No canonical-engine-sourced values. |
| **Mobile parity** | E2E tests target mobile viewports. CSS breakpoint at 800px. Trade page has mobile sheet picker. | No mobile navigation drawer. Rankings relies on horizontal scroll. No touch gestures. Basic responsive only. |
| **API data contract validation** | `src/api/data_contract.py` builds and validates contract. CI and runtime checks. | `src/api/` has no API service code — only the contract validator. The actual API lives in `server.py`. |

---

## 5. Planned but Not Started

| Item | Blueprint Reference | Notes |
|------|-------------------|-------|
| League context engine (scarcity, replacement, pick curves) | Phase 4 | `src/league/` is empty. Critical dependency for canonical-fed trade calc and rankings. |
| New trade API (package adjustment, lineup impact, fairness) | Phase 5 §7 | No code in `src/api/` beyond contract validator. |
| Roster/team view | Phase 6 | No page, no API, no data model. |
| Player detail page with trend history | Phase 6 | No page, no trend data. |
| Trade finder / target list | Phase 7 | |
| Contender vs rebuilder toggle | Phase 7 | |
| Historical value charts / regression alerts | Phase 7 | |
| Yahoo values source | Implied by multi-source | No adapter, no config. |
| DynastyNerds values source | Blueprint §1 mentions | No adapter, no config. |
| IDPTradeCalc source | Implied by IDP emphasis | No adapter, no config. |

---

## 6. Blocked or Unclear

| Item | Status | Why |
|------|--------|-----|
| **Source weights** | Blocked | Blueprint §11 lists as "founder input required." Current config uses equal 1.0 weights for all DLF sources. |
| **Package tax multiplier** | Blocked | Founder decision needed (§11). |
| **Rookie optimism setting** | Blocked | Founder decision needed (§11). |
| **Contender vs rebuilder heuristics** | Blocked | Founder decision needed (§11). |
| **Market mirror vs My board mode** | Blocked | Founder decision needed (§11). |
| **Pick discount schedule** | Partially unblocked | Config template has 2026/2027/2028 discounts. No engine code to apply them. |
| **Scoring module wiring to new engine** | Unclear | Scoring integrates with legacy `compute_empirical_lam()`. Unclear if it should also feed canonical pipeline or remain legacy-only. |
| **New engine → production cutover** | Unclear | No documented exit criteria for when `server.py` should consume canonical pipeline output instead of scraper output. |

---

## 7. False Sense of Completion

These items **appear complete** from doc/file presence but are **not actually wired or functioning as implied**:

1. **Blueprint Section 10 checkboxes** — All `[ ]` unchecked, making it look like zero progress. Actually Phase 0 is complete and Phase 1-3 are partially done. Misleading in the opposite direction (understates progress).

2. **`src/api/` described as "FastAPI services for calculator, rankings, roster endpoints"** in `src/README.md` — Actually contains only a contract validator (`data_contract.py`). No API services. The real API is `server.py`.

3. **`frontend/app/login/page.jsx`** — Looks like a real login page but is a **demo/placeholder**. It accepts any credentials, stores session in localStorage only, has no backend integration. The **real auth** is in `server.py` (session cookies via `/api/auth/login`).

4. **Next.js frontend auth** — Next.js pages have no auth protection. All pages accessible without login. The auth gate is only on `server.py`'s HTML routes (`/app`, `/rankings`, `/trade`). If someone accesses the Next dev server directly (port 3000), there's no auth.

5. **Scaffold pipeline output** — `scripts/source_pull.py` → `canonical_build.py` → `league_refresh.py` produce JSON artifacts in `data/`, but `server.py` **never reads these files**. It reads `dynasty_data_*.json` from the legacy scraper only. The scaffold pipeline runs in Jenkins but its output is not consumed by anything in production.

6. **`scripts/league_refresh.py`** — Runs in Jenkins pipeline but outputs a stub: "Scaffold output only. Full league adjustment math remains in legacy pipeline for now."

7. **KTC adapter** — Has code to read seed CSVs and produce records. But `config/sources/dlf_sources.template.json` has KTC_STUB **disabled** (`"enabled": false`). No KTC data flows through the pipeline.

8. **IDP support** — Config templates include IDP positions. Adapter contract includes `is_idp` flag. DLF IDP CSV seeds exist. But no IDP-specific processing, scarcity math, or UI filtering exists beyond passing the flag through.

---

## 8. Security Notes

1. **Hardcoded default credentials** in `server.py` line 93: `JASON_LOGIN_PASSWORD = "Elliott21!"`. Env-overridable but default is in source code.

2. **In-memory session store** — Sessions lost on restart. No persistence, no session expiry beyond manual cleanup.

3. **Next.js frontend has no auth** — Direct access to `localhost:3000` bypasses all auth. Acceptable for dev, risky if Next is ever exposed publicly.

4. **Cookie not secure by default** — `JASON_AUTH_COOKIE_SECURE = False`. Must be set to True for HTTPS production.

---

## 9. Test Coverage Assessment

| Area | Tests | Coverage Level |
|------|-------|---------------|
| Scoring modules | 5 unit tests | Moderate — covers normalization, delta, multiplier bounds, output shape, persistence |
| API contract | Validated at runtime + CI | Good — structural validation of all required fields |
| E2E smoke | 1 test (API + tabs) | Smoke only |
| E2E rankings | 1 test (search, filter, sort, source cols) | Functional |
| E2E trade calculator | 2 tests (CRUD + save/load + 3-team) | Good — covers core workflows |
| Adapters | **None** | Missing |
| Identity | **None** | Missing |
| Canonical transforms | **None** | Missing |
| League context | **N/A** | Module empty |
| Name cleaning | **None** | Missing |
| Auth flow | **None** (E2E tests bypass auth) | Missing |
| Deploy/rollback | **None** (manual verification only) | Missing |

---

## 10. Source/Value Coverage

| Source | Config Status | Adapter Status | Production Status |
|--------|-------------|----------------|-------------------|
| DLF Superflex | Enabled | Working DLF adapter | **Seed CSV only** — adapter not wired to production |
| DLF IDP | Enabled | Working DLF adapter | **Seed CSV only** |
| DLF Rookie SF | Enabled | Working DLF adapter | **Seed CSV only** |
| DLF Rookie IDP | Enabled | Working DLF adapter | **Seed CSV only** |
| KTC | Disabled in config | Stub adapter (seed CSV) | **Not active** |
| Dynasty Nerds | Not configured | No adapter | **Not started** |
| Yahoo | Not configured | No adapter | **Not started** |
| IDPTradeCalc | Not configured | No adapter | **Not started** |
| Legacy multi-source (via scraper) | N/A | `Dynasty Scraper.py` | **LIVE** — this is what actually powers production |

---

## 11. Runtime Authority Map

| Route | Authority | Auth | Data Source |
|-------|-----------|------|-------------|
| `/` | `server.py` → `landing.html` | Public | Static HTML |
| `/league` | `server.py` → inline HTML | Public | Static HTML |
| `/app` | `server.py` → Static/Next | Auth required | N/A (frontend shell) |
| `/rankings` | `server.py` → Static/Next | Auth required | `/api/data` → legacy scraper |
| `/trade` | `server.py` → Static/Next | Auth required | `/api/data` → legacy scraper |
| `/login` | `server.py` → Static/Next | Auth required | N/A |
| `/api/data` | `server.py` | Public | `dynasty_data_*.json` from scraper |
| `/api/status` | `server.py` | Public | In-memory state |
| `/api/health` | `server.py` | Public | In-memory state |
| `/api/scrape` | `server.py` | Public (POST) | Triggers scraper |
| `/api/auth/*` | `server.py` | Public | In-memory sessions |
| `/api/scaffold/*` | `server.py` | Public | `data/` JSON artifacts |
| Next dev (`:3000`) | Next.js | **No auth** | `/api/dynasty-data` → backend fallback |
