# Normalized Workstream Inventory

_Generated: 2026-03-14_

This document maps every major workstream identified from the blueprint, repo structure, and planning docs. Each entry records source docs, stated goals, and doc-level currency assessment.

**Status legend for doc currency:**
- **Current** — Doc reflects repo reality as of 2026-03-14
- **Stale** — Doc exists but does not reflect actual progress
- **Missing** — No dedicated planning doc exists for this workstream
- **Aspirational** — Doc describes target state without distinguishing from current state

---

## 1. Source Ingestion / Adapters

| Field | Value |
|-------|-------|
| **Blueprint Phase** | Phase 1 |
| **Source Docs** | `docs/BLUEPRINT_EXECUTION.md` §3.1, §10 Phase 1; `src/adapters/README.md`; `data/raw/README.md` |
| **Stated Goals** | Define adapter contract, implement DLF CSV / KTC scrape / manual CSV adapters, raw snapshot storage, unmatched-player report |
| **Implementation Evidence** | `src/adapters/dlf_csv_adapter.py` (148 lines), `ktc_stub_adapter.py` (112 lines, stub), `manual_csv_adapter.py` (26 lines, minimal), `base.py` exists; `scripts/source_pull.py` exists; adapter contract frozen in README |
| **Doc Currency** | **Stale** — Blueprint checkboxes all unchecked despite partial implementation. Adapter contract README is current. |
| **Key Gap** | KTC adapter is a stub. Manual CSV adapter is minimal. No unmatched-player report visible. DLF CSV adapter exists but live integration path unclear. |

---

## 2. Identity Resolution

| Field | Value |
|-------|-------|
| **Blueprint Phase** | Phase 2 |
| **Source Docs** | `docs/BLUEPRINT_EXECUTION.md` §3.2, §10 Phase 2; `src/identity/` |
| **Stated Goals** | Master `players` table + alias ingestion, reconciliation CLI, unit tests for suffix/punctuation/team changes |
| **Implementation Evidence** | `src/identity/matcher.py` (261 lines), `models.py` (75 lines), `schema.py` exists, SQL migration `0001_identity_schema.sql` exists; `scripts/identity_resolve.py` exists |
| **Doc Currency** | **Stale** — Blueprint checkboxes unchecked. No dedicated identity planning doc. |
| **Key Gap** | No unit tests visible for identity. No reconciliation CLI documented. Schema exists but unclear if any data populates it. |

---

## 3. Canonical Value Pipeline

| Field | Value |
|-------|-------|
| **Blueprint Phase** | Phase 3 |
| **Source Docs** | `docs/BLUEPRINT_EXECUTION.md` §3.3, §5, §10 Phase 3; `.agents/skills/value-pipeline-auditor/SKILL.md` |
| **Stated Goals** | Define universes + weight config, percentile + curve transforms, source blending, snapshot versioning, canonical asset values + history |
| **Implementation Evidence** | `src/canonical/pipeline.py` (45 lines), `transform.py` (210 lines); `config/weights/default_weights.json` exists; `scripts/canonical_build.py` exists |
| **Doc Currency** | **Stale** — Blueprint checkboxes unchecked. Pipeline exists but is thin (45 lines). |
| **Key Gap** | `pipeline.py` is very small — likely scaffold-level, not production-ready. No canonical snapshot storage visible in `data/`. Weight config exists but untested against live data. |

---

## 4. League Context Engine

| Field | Value |
|-------|-------|
| **Blueprint Phase** | Phase 4 |
| **Source Docs** | `docs/BLUEPRINT_EXECUTION.md` §3.4, §6, §10 Phase 4 |
| **Stated Goals** | League settings schema + import, starter demand + replacement math (offense + IDP), scarcity multipliers, rookie optimism dial, pick curve + time discount |
| **Implementation Evidence** | `src/league/` contains only `.gitkeep` — **empty module**. `config/leagues/default_superflex_idp.template.json` exists. `scripts/league_refresh.py` exists. |
| **Doc Currency** | **Current** (accurately shows this as not started in blueprint Phase 4, though checkboxes format makes this ambiguous) |
| **Key Gap** | **Entire module not implemented.** This is a critical dependency for trade calculator and rankings to use canonical values. Template config exists but no engine code. |

---

## 5. Scoring Adjustment System

| Field | Value |
|-------|-------|
| **Blueprint Phase** | Cross-cutting (supplements Phase 4 league context) |
| **Source Docs** | `docs/scoring_adjustment_audit_2026-03-09.md`; `docs/scoring_adjustment_migration_notes_2026-03-09.md`; `docs/scoring_config_schema.md`; `docs/scoring_refactor_task_checklist_2026-03-09.md` |
| **Stated Goals** | Modular scoring under `src/scoring/`, empirical LAM refactor, baseline vs custom config, feature engineering, archetype model, backtesting |
| **Implementation Evidence** | `src/scoring/` — 11 files, 1,016 total lines. `tests/scoring/test_scoring_modules.py` exists. All 15 checklist items marked Done. |
| **Doc Currency** | **Current** — Best-documented workstream. Audit, migration notes, schema, and checklist are all consistent and up to date. |
| **Key Gap** | Scoring module integrates with legacy `server.py` / `Dynasty Scraper.py` path. Not yet wired to new canonical engine. |

---

## 6. Trade Calculator

| Field | Value |
|-------|-------|
| **Blueprint Phase** | Phase 5 |
| **Source Docs** | `docs/BLUEPRINT_EXECUTION.md` §7, §8.1, §10 Phase 5 |
| **Stated Goals** | Package adjustment logic, lineup impact service, REST endpoint + CLI, frontend calculator view |
| **Implementation Evidence** | `frontend/app/trade/page.jsx` (314 lines) — Next.js trade page exists. Legacy calculator in `Static/index.html`. Backend trade logic lives in `server.py` (legacy). No `src/api/` trade endpoint. |
| **Doc Currency** | **Aspirational** — Blueprint describes a new trade API that doesn't exist. Legacy calculator works but is not the blueprint target. |
| **Key Gap** | New trade engine (package adjustment, lineup impact, fairness bands) not implemented. Frontend exists for both legacy static and Next but consumes legacy data path. |

---

## 7. Rankings

| Field | Value |
|-------|-------|
| **Blueprint Phase** | Phase 6 |
| **Source Docs** | `docs/BLUEPRINT_EXECUTION.md` §8.2, §10 Phase 6 |
| **Stated Goals** | Rankings endpoint + table component, sortable master board (overall/offense/IDP/rookies/picks/roster), trend + source contribution |
| **Implementation Evidence** | `frontend/app/rankings/page.jsx` (277 lines) — Next.js rankings page exists. Legacy rankings in `Static/index.html`. Backend rankings from `server.py` `/api/data`. |
| **Doc Currency** | **Aspirational** — Blueprint target (canonical-fed rankings with source contribution, trend) not implemented. Current rankings use legacy data path. |
| **Key Gap** | No new rankings API endpoint. No trend/source contribution data. Rankings page exists but displays legacy-pipeline data. |

---

## 8. Landing Page / Jason vs League Flow

| Field | Value |
|-------|-------|
| **Blueprint Phase** | Not explicitly phased |
| **Source Docs** | None dedicated. `frontend/app/page.jsx` (60 lines) exists. |
| **Stated Goals** | Implied by product definition — entry flow for personal vs league context |
| **Implementation Evidence** | `frontend/app/page.jsx` is a minimal landing page. `frontend/app/login/page.jsx` (122 lines) exists. No routing spec or user-flow doc. |
| **Doc Currency** | **Missing** — No planning doc for landing page design, user flow, or Jason vs League entry point. |
| **Key Gap** | No page-flow architecture. No spec for how a user enters personal board vs league context. Design taste director skill exists but no applied design spec. |

---

## 9. IDP Support

| Field | Value |
|-------|-------|
| **Blueprint Phase** | Cross-cutting (mentioned in Phases 1, 3, 4, 6) |
| **Source Docs** | `docs/BLUEPRINT_EXECUTION.md` §1, §2, §3.3, §6 |
| **Stated Goals** | IDP assets in same canonical economy as offense, IDP-specific scarcity/replacement, IDP rankings |
| **Implementation Evidence** | `dlf_idp.csv` and `dlf_rookie_idp.csv` seed data exist. `config/leagues/default_superflex_idp.template.json` includes IDP positions. Adapter contract includes `is_idp` flag. |
| **Doc Currency** | **Aspirational** — Blueprint describes IDP as first-class but no IDP-specific implementation exists beyond seed data and config template. |
| **Key Gap** | IDP data exists as CSV seeds only. No IDP adapter, no IDP-specific canonical processing, no IDP scarcity math, no IDP UI filtering. |

---

## 10. Mobile Parity

| Field | Value |
|-------|-------|
| **Blueprint Phase** | Not explicitly phased |
| **Source Docs** | `README.md` "Regression Harness" section; `tests/e2e/` Playwright specs |
| **Stated Goals** | Desktop + mobile parity for trade calculator and rankings |
| **Implementation Evidence** | Playwright config targets `390x844` and `430x932` mobile viewports. E2E specs exist for smoke-api, trade-calculator, rankings. Design taste director skill mentions mobile ergonomics. |
| **Doc Currency** | **Current** (for testing infrastructure). **Missing** (for mobile design/UX planning). |
| **Key Gap** | Testing infrastructure exists. No mobile-specific design spec or responsive behavior documentation. |

---

## 11. Routing / Runtime Authority

| Field | Value |
|-------|-------|
| **Blueprint Phase** | Phase 0 (infrastructure) |
| **Source Docs** | `docs/BLUEPRINT_EXECUTION.md` "Runtime Reality Check"; `docs/REPO_INVENTORY.md` "Runtime Authority"; `README.md` server linking section |
| **Stated Goals** | Explicit `FRONTEND_RUNTIME` control (`static`/`next`/`auto`), no silent fallbacks |
| **Implementation Evidence** | `server.py` implements `FRONTEND_RUNTIME` env var. Three runtime modes documented and implemented. |
| **Doc Currency** | **Current** — Three docs consistently describe the same runtime model. This is well-documented. |
| **Key Gap** | None for current state. Future gap: when Next becomes primary, runtime default must flip and docs must update. |

---

## 12. Auth / Public Boundary

| Field | Value |
|-------|-------|
| **Blueprint Phase** | Not phased (v1 is private, no public SaaS) |
| **Source Docs** | `docs/BLUEPRINT_EXECUTION.md` §2 ("What v1 is not"); `frontend/app/login/page.jsx` |
| **Stated Goals** | Private platform, no anonymous users |
| **Implementation Evidence** | Login page exists (122 lines). No auth middleware, session management, or user model visible in `src/` or `server.py` (based on file sizes — full audit would require reading server.py). |
| **Doc Currency** | **Missing** — No auth architecture doc. Blueprint says private but doesn't spec how access is controlled. |
| **Key Gap** | Login page exists but auth implementation unclear. No documented auth strategy (API keys, sessions, OAuth, etc.). |

---

## 13. Scraper / Data Pipeline (Legacy)

| Field | Value |
|-------|-------|
| **Blueprint Phase** | Pre-existing (legacy, to be superseded by adapters) |
| **Source Docs** | `docs/REPO_INVENTORY.md`; `.agents/skills/scraper-ops/SKILL.md`; `defs_scraper.txt` |
| **Stated Goals** | Legacy scraper (`Dynasty Scraper.py`) continues operating while new adapters spin up |
| **Implementation Evidence** | `Dynasty Scraper.py` (501,202 bytes — very large). `server.py` (69,252 bytes). Both are the live production backbone per "Migration Honesty" section. |
| **Doc Currency** | **Current** — `REPO_INVENTORY.md` correctly labels these as legacy. Migration Honesty section is accurate. |
| **Key Gap** | Legacy scraper is monolithic. No timeline for adapter replacement. Dual-system period has no documented exit criteria. |

---

## 14. Performance / Cleanup

| Field | Value |
|-------|-------|
| **Blueprint Phase** | Not phased (ongoing) |
| **Source Docs** | `AGENTS.md` "Performance Rules"; `.agents/skills/performance-optimizer/SKILL.md`; `scripts/perf_startup_probe.js` |
| **Stated Goals** | Page-load speed, reduce blocking work, eliminate duplication |
| **Implementation Evidence** | Performance optimizer agent skill defined. Startup probe script exists. AGENTS.md mandates performance-first rules. |
| **Doc Currency** | **Current** (for governance). **Missing** (no performance baseline, no target metrics, no perf audit results). |
| **Key Gap** | No performance baseline documented. No target metrics. Governance exists but no measured status. |

---

## 15. Deployment / Runtime Hardening

| Field | Value |
|-------|-------|
| **Blueprint Phase** | Phase 0 (infrastructure) |
| **Source Docs** | `deploy/PRODUCTION_BOOTSTRAP.md`; `LOCKSTEP_SETUP.md`; `.github/workflows/deploy.yml`; `Jenkinsfile` |
| **Stated Goals** | Automated deploy to Hetzner, Jenkins CI pipeline, GitHub Actions deploy, lockstep sync |
| **Implementation Evidence** | Full deploy workflow in GitHub Actions (335 lines). Jenkinsfile with 6+ stages. Bootstrap script. Systemd service. Domain `riskittogetthebrisket.org`. |
| **Doc Currency** | **Current** — Best-operationalized workstream. Deploy pipeline, bootstrap, lockstep are all documented and implemented. |
| **Key Gap** | Jenkins stages reference scaffold scripts that may be scaffold-level (not production-grade). No rollback testing documented. |

---

## 16. API Data Contract

| Field | Value |
|-------|-------|
| **Blueprint Phase** | Cross-cutting |
| **Source Docs** | `docs/BLUEPRINT_EXECUTION.md` "Current Official /api/data Contract"; `docs/REPO_INVENTORY.md` "Backend Data Contract"; `README.md` "/api/data contract" |
| **Stated Goals** | Versioned contract (`2026-03-09.v1`), legacy compatibility + normalized additions, runtime + CI validation |
| **Implementation Evidence** | `src/api/data_contract.py` exists. `scripts/validate_api_contract.py` exists. Contract version documented in 3 places consistently. |
| **Doc Currency** | **Current** — Well-documented across three docs. Validation exists in both runtime and CI. |
| **Key Gap** | Contract validator exists but `src/api/` has no actual API service code. Contract covers legacy `/api/data` shape, not future canonical endpoints. |

---

## Summary Table

| # | Workstream | Blueprint Phase | Doc Currency | Implementation Depth |
|---|-----------|----------------|-------------|---------------------|
| 1 | Source Ingestion / Adapters | Phase 1 | Stale | Scaffold + partial |
| 2 | Identity Resolution | Phase 2 | Stale | Scaffold + partial |
| 3 | Canonical Value Pipeline | Phase 3 | Stale | Scaffold (thin) |
| 4 | League Context Engine | Phase 4 | Ambiguous | **Empty** |
| 5 | Scoring Adjustment | Cross-cutting | Current | **Implemented** |
| 6 | Trade Calculator | Phase 5 | Aspirational | Legacy only |
| 7 | Rankings | Phase 6 | Aspirational | Legacy only |
| 8 | Landing Page / User Flow | Unphased | Missing | Minimal |
| 9 | IDP Support | Cross-cutting | Aspirational | Seed data only |
| 10 | Mobile Parity | Unphased | Missing (design) | Test infra only |
| 11 | Routing / Runtime | Phase 0 | Current | **Implemented** |
| 12 | Auth / Public Boundary | Unphased | Missing | Login page only |
| 13 | Scraper / Data Pipeline | Legacy | Current | **Live production** |
| 14 | Performance / Cleanup | Ongoing | Missing (metrics) | Governance only |
| 15 | Deployment / Hardening | Phase 0 | Current | **Implemented** |
| 16 | API Data Contract | Cross-cutting | Current | **Implemented** (validation) |

---

## Interpretation Guide

- **Implemented**: Code is written, wired, and documented consistently.
- **Scaffold + partial**: Module structure exists with some real code, but not production-complete or end-to-end wired.
- **Scaffold (thin)**: Module exists but has minimal logic — likely placeholder-level.
- **Legacy only**: Feature exists via legacy path (`server.py` / `Dynasty Scraper.py` / `Static/`), not via new engine.
- **Empty**: Module placeholder exists but contains no implementation code.
- **Seed data only**: Input data exists but no processing pipeline.
- **Test infra only**: Testing exists but no feature implementation to test.
- **Governance only**: Rules/policies defined but no measured outcomes.
