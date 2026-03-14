# Blueprint & Planning Source-of-Truth Assessment

_Generated: 2026-03-14_

---

## 1. Executive Summary

This repo has **one strong primary blueprint** (`docs/BLUEPRINT_EXECUTION.md`) supported by a consistent set of secondary docs. The planning picture is coherent but carries two systemic risks:

1. **The blueprint's execution backlog (Section 10) uses unchecked `[ ]` boxes for every phase**, making it impossible to distinguish planned from completed work without inspecting implementation files. The scoring refactor checklist marks everything "Done" but is a narrow sub-workstream, not a full progress tracker.
2. **Several docs mix current-state facts with aspirational architecture** in ways that could mislead a reader into thinking more of the new engine is live than actually is. The "Migration Honesty" footer in the blueprint partially addresses this, but it's easy to miss.

There are **no conflicting blueprints** — the docs are additive and internally consistent. The main gap is the absence of a single, honest, phase-level progress tracker.

---

## 2. Blueprint / Planning Docs Found

| # | Document | Type | Last Updated | Role |
|---|----------|------|-------------|------|
| 1 | `docs/BLUEPRINT_EXECUTION.md` | Primary blueprint + backlog | 2026-03-09 | **Primary source of truth** for architecture, product definition, execution phases |
| 2 | `docs/REPO_INVENTORY.md` | Repo layout + component status | 2026-03-09 | Secondary — maps legacy vs new components |
| 3 | `README.md` | Operator quick-start + contract reference | 2026-03-09 | Secondary — operational entry point |
| 4 | `AGENTS.md` | Agent behavior rules | Undated | Governance — constrains agent operations |
| 5 | `LOCKSTEP_SETUP.md` | Jenkins/GitHub/server sync checklist | Undated | Operational — deployment lockstep |
| 6 | `deploy/PRODUCTION_BOOTSTRAP.md` | Production server runbook | Undated | Operational — first-time server setup |
| 7 | `docs/scoring_adjustment_audit_2026-03-09.md` | Pre-refactor scoring audit | 2026-03-09 | Workstream-specific — scoring |
| 8 | `docs/scoring_adjustment_migration_notes_2026-03-09.md` | Scoring migration notes | 2026-03-09 | Workstream-specific — scoring |
| 9 | `docs/scoring_config_schema.md` | Scoring config schema | Undated | Workstream-specific — scoring |
| 10 | `docs/scoring_refactor_task_checklist_2026-03-09.md` | 15-part scoring checklist | 2026-03-09 | Workstream-specific — scoring (all marked Done) |
| 11 | `src/README.md` | New engine module overview | Undated | Secondary — describes intended `src/` layout |
| 12 | `src/adapters/README.md` | Adapter contract spec | Undated | Spec — frozen adapter contract |
| 13 | `data/raw/README.md` | Raw ingestion layout spec | Undated | Spec — ingestion folder conventions |
| 14 | `frontend/README.md` | Frontend quick-start | Undated | Secondary — Next.js dev instructions |
| 15 | `.agents/skills/blueprint-auditor/SKILL.md` | Agent skill definition | Undated | Tooling — blueprint audit behavior |
| 16 | `.agents/skills/reality-check-review/SKILL.md` | Agent skill definition | Undated | Tooling — reality check behavior |
| 17 | `.agents/skills/value-pipeline-auditor/SKILL.md` | Agent skill definition | Undated | Tooling — value pipeline audit behavior |
| 18 | `.agents/skills/scraper-ops/SKILL.md` | Agent skill definition | Undated | Tooling — scraper ops behavior |
| 19 | `.agents/skills/design-taste-director/SKILL.md` | Agent skill definition | Undated | Tooling — UI design direction |
| 20 | `.agents/skills/performance-optimizer/SKILL.md` | Agent skill definition | Undated | Tooling — performance optimization |

---

## 3. Source-of-Truth Assessment

### Primary Source of Truth
**`docs/BLUEPRINT_EXECUTION.md`**

This is the canonical plan. It defines:
- Mission statement and product scope (v1 is/is not)
- Five-system architecture (raw → identity → canonical → league → decision)
- Core data models and tables
- Normalization/blending rules
- League context and pick engine
- Trade engine contract
- UI surfaces (MVP)
- Jenkins responsibilities
- 8-phase execution backlog (Phase 0–7)
- Open founder decisions
- Immediate next actions

The "Migration Honesty" and "Runtime Reality Check" sections (appended 2026-03-09) are the most honest current-state markers in the repo.

### Secondary Supporting Docs (Consistent)
- `docs/REPO_INVENTORY.md` — Correctly describes legacy vs new layout. Consistent with blueprint.
- `README.md` — Operational quick-start. Documents scaffold pipeline commands and API contract. Consistent.
- `LOCKSTEP_SETUP.md` — Jenkins/GitHub sync. Operational, not aspirational.
- `deploy/PRODUCTION_BOOTSTRAP.md` — Server setup. Accurate to production infrastructure.
- `src/adapters/README.md` — Frozen adapter contract. Consistent with blueprint Phase 1 spec.
- `data/raw/README.md` — Ingestion layout. Consistent with blueprint raw source layer.

### Workstream-Specific Docs (Narrow Scope, Current)
The four `docs/scoring_*` files document a completed scoring refactor sub-workstream. All four are internally consistent and correctly scoped. The 15-part checklist marks all 15 items as Done, which appears accurate based on the `src/scoring/` module (1,016 lines across 11 files, plus tests).

### Agent Skill Definitions (Governance, Not Planning)
The six `.agents/skills/*/SKILL.md` files define agent behavior rules, not plans. They are well-structured and useful operational tools.

---

## 4. Outdated / Overlapping / Conflicting Docs

### Outdated
- **None clearly outdated.** All docs reference 2026-03-09 or are undated but consistent with current repo state.

### Overlapping (Acceptable)
- `docs/BLUEPRINT_EXECUTION.md` Section 12 ("Immediate Next Actions") partially overlaps with Phase 0/1 of Section 10. Minor — just different granularity views.
- `README.md` "Canonical Scaffold" section partially restates `docs/REPO_INVENTORY.md` "New structure" section. Minor.

### Misleading (Action Needed)
- **Blueprint Section 10 (Execution Backlog)**: All 30+ checkboxes are `[ ]` unchecked, yet multiple Phase 0 and Phase 1 items are observably complete in the repo (e.g., `/src` structure exists, adapter contract is defined, DLF CSV adapter exists, config loaders exist, `.env.example` exists). The backlog gives a false impression that zero work has been done on the new engine.
- **`src/README.md`**: Describes `src/api/` as "FastAPI/Starlette services for calculator, rankings, roster endpoints" — but `src/api/` contains only `data_contract.py` (a contract validator, not API services). The description oversells what exists.
- **`docs/REPO_INVENTORY.md`** describes `server.py` status as "Legacy (to be replaced)" — accurate but could mislead about timeline. `server.py` is the entire live backend and will remain so for a significant period.

### Conflicting
- **No direct contradictions found** between documents.

---

## 5. Docs Not Found (Gaps)

The following planning artifacts do not exist but would be expected for a project of this scope:

| Missing Doc | Why It Matters |
|-------------|---------------|
| Phase-level progress tracker | No way to see which blueprint phases/items are actually complete vs in-progress vs not-started |
| Landing page / Jason vs League flow spec | Blueprint mentions UI surfaces but no page-flow or routing spec exists |
| Mobile parity spec | No mobile-specific planning doc despite regression suite targeting mobile viewports |
| Auth/public boundary spec | `frontend/app/login/page.jsx` exists (122 lines) but no auth architecture doc |
| IDP-specific implementation plan | Blueprint covers IDP conceptually but no dedicated IDP implementation plan exists |
| Data source integration status | No tracker for which sources (KTC, DLF, Dynasty Nerds, etc.) are live vs stubbed vs planned |

---

## 6. Risks and Unknowns

1. **Progress invisibility**: The unchecked execution backlog is the biggest planning risk. Work has been done but isn't tracked, making it hard to prioritize next steps or communicate status.
2. **League module is empty**: `src/league/` contains only `.gitkeep`. This is Phase 4 of the blueprint — scarcity, replacement baselines, pick curves — and is a prerequisite for the trade calculator to use canonical values.
3. **`src/api/` is misrepresented**: Described as API services but contains only a contract validator. The actual API remains in `server.py`.
4. **Open founder decisions (Blueprint Section 11)** are unresolved — source weights, package tax, rookie optimism, contender heuristics, pick discounts. These block Phase 3-5 completion.
5. **No test coverage for new engine modules**: Only `tests/scoring/` exists. No tests for adapters, identity, canonical, or league modules.

---

## 7. Final Recommendation

1. **Update Blueprint Section 10** to reflect actual completion status of each phase item.
2. **Create a workstream inventory** (see companion doc `docs/status/workstream-inventory.md`) that normalizes all planned work into trackable streams with current status.
3. **Resolve "Migration Honesty" into a standing status section** that is maintained on every significant change, not buried as a footer.
4. **Do not create new competing blueprints.** The existing `BLUEPRINT_EXECUTION.md` is sound. It needs progress tracking, not replacement.
5. **Address the six doc gaps** identified in Section 5 as workstreams mature.
