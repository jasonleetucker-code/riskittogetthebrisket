# CLAUDE.md — Chase Upside Technical Operating Constitution

## What this document is — and is not

**CLAUDE.md is the technical operating constitution / runbook for this repository.** It defines durable implementation discipline, canonical-boundary rules, repo workflow, validation expectations, and the minimum technical context a Claude Code session must carry.

**It is NOT the product roadmap, NOT the owner-feature backlog, and NOT an authorization record. Nothing in this file authorizes starting a feature or phase.**

> **Mandatory startup rule for every material product, architecture, model, feature, or implementation-planning task:** start at [`PRODUCT_PLAN.md`](PRODUCT_PLAN.md), then follow the hierarchy in [`docs/MASTER_PRODUCT_PLAN.md`](docs/MASTER_PRODUCT_PLAN.md), and check [`docs/EXECUTION_PLAN.md`](docs/EXECUTION_PLAN.md) before writing production code.

| Question | Canonical record |
|---|---|
| Where do I start? | `PRODUCT_PLAN.md` |
| What is Chase Upside building / which product rule wins? | `docs/MASTER_PRODUCT_PLAN.md` |
| **What am I authorized to implement right now?** | **`docs/EXECUTION_PLAN.md`** |
| Which planning/spec/evidence records are active vs historical? | `docs/PLANNING_DOCUMENT_STATUS.md` |
| How is the whole direction layer synchronized? | `docs/PRODUCT_DIRECTION_SYNC_MANIFEST.md` |
| What is the exhaustive discussion-derived feature coverage? | `docs/OWNER_MASTER_FEATURE_BACKLOG_2026-08-13.md` |
| What does newer owner feature intent require? | `docs/OWNER_FEATURE_SPEC_RECONCILIATION_2026-08-13.md` + Appendix + feature-specific binding specs |
| What older detailed owner intent still applies where not superseded? | `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` |
| What compact owner requests remain durable? | `docs/OWNER_REQUESTED_TODO.md` + `docs/OWNER_REQUESTED_TODO_SPEC_INDEX.md` |
| How must post-B C be replanned/executed/deployed/closed? | `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` |
| What are current implementation owners / details? | live code + current ADRs + scoped architecture docs |
| What defect was measured at what pinned state? | `docs/master-site-audit/` and other evidence artifacts |
| Who is editing what? | `docs/WORK_CLAIMS.md` |

**If this file conflicts with that hierarchy, the hierarchy wins for product intent and sequencing.** Live code/executable evidence can prove a status sentence stale; current implementation behavior does not silently override a newer owner product decision merely because it ships today.

This file intentionally avoids duplicating fast-changing feature roadmaps and methodology prose. Put detailed feature logic beside its canonical code/ADR/spec rather than turning CLAUDE.md into a second product plan.

---

# Current program status — orientation only

`docs/EXECUTION_PLAN.md` is authoritative; this summary is here only to prevent a new coding session from starting from obsolete B6-era assumptions.

As of the 2026-08-14 synchronization:

- B4 complete/accepted (#805).
- B5 complete/accepted (#806).
- B6 scoring/league identity merged/verified (#810; operational verification #819).
- B7 realized scoring merged (#820).
- B8 privacy/public-distribution boundary merged (#821).
- #822 merged: the previous league-aware valuation implementation was **rejected as canonical** and the product returned to **one canonical player-value methodology** across devices/surfaces.
- Active Fast Lane order: **B9a → B9b → B10 → B11**.
- After B11: **STOP**. No automatic C1. Enter Plan Mode, build the exhaustive C Scope Manifest + dependency DAG, obtain owner approval, then execute the approved C plan.

Do not copy this status into another roadmap. Update `EXECUTION_PLAN.md` when it changes.

---

# Project overview

Chase Upside is a dynasty fantasy-football valuation, league intelligence, trade/waiver/draft decision, market/analyst intelligence, historical, public-league, and current-season decision platform.

The current repository retains the historical name `riskittogetthebrisket`; do not blanket-rename repository/league/infrastructure/history identifiers whose old name is part of their identity.

## Tech stack

- **Backend:** Python 3, FastAPI, Uvicorn (port 8000)
- **Frontend:** Next.js 15 + React 19 (port 3000)
- **Scraping / acquisition:** Playwright plus sanctioned requests/Selenium paths including `Dynasty Scraper.py`
- **CI/CD:** GitHub Actions
- **Testing:** pytest, Vitest, Playwright E2E, contract/audit gates
- **Primary dev:** Windows; production/CI: Linux

## Working-copy coordination

- Active working copy: `C:\Users\jason\code\riskittogetthebrisket`.
- GitHub `main` is the shared source of truth for Claude, ChatGPT/Codex, and local work.
- Before starting meaningful work: `git pull --ff-only origin main`.
- Use task branches (`claude/...`, `codex/...`) for meaningful changes.
- Do not let multiple assistants edit the same branch concurrently.
- Treat OneDrive copies as backup/archive unless explicitly instructed otherwise.
- Read `ASSISTANT_COORDINATION.md` and `docs/WORK_CLAIMS.md` before overlapping work.
- A branch/PR description is not authority for product scope; compare against current `main` + `EXECUTION_PLAN.md`.

---

# Governance invariants every implementation session must hold

## 1. One concept, one canonical owner

Pages/features consume canonical systems; they do not independently reimplement them.

This applies especially to:

- player identity;
- pick identity/ownership/value;
- league/scoring identity;
- canonical player value/rank/tier;
- historical value/acquisition/transaction truth;
- realized scoring;
- lineup/best-ball assignment;
- replacement/PAR/VORP/Player Impact;
- Team Strength / Team Weakness;
- package generation / trade simulation;
- projections/probabilities;
- Sharp cohort/evidence;
- Analyst Intelligence and Buy/Sell synthesis;
- public/private classification;
- confidence/provenance/freshness.

If the owner is defective, repair it. A page-local workaround becomes a second owner and is normally the wrong fix.

## 2. Missing is never zero

No projection ≠ 0 points. No FAAB history ≠ $0. No trade comp ≠ $0 market value. No analyst take ≠ neutral. No assignment snapshot ≠ a legitimate empty assignment. No historical value ≠ today's value. Unknown scoring compatibility ≠ compatible. Unresolved identity ≠ best fuzzy guess.

Preserve explicit unavailable / unsupported / stale / partial / insufficient / unpriced / unproven states through APIs and UI.

## 3. Signal independence / no double counting

A body of evidence affects a conclusion once. A provider, its derivative, its mirrored board, a consensus containing it, and a simulator centered on that consensus do not become independent votes merely because they appear in separate components.

Before adding a signal identify population, source/family, overlap, freshness, coverage, sample size, missing behavior, and provenance.

## 4. Champion is not challenger

Model evaluation never equals activation.

**collect → provenance/history → train challenger → backtest → out-of-sample validate → compare → review/calibrate → explicit owner/human approval → promote → monitor → rollback**.

Nothing silently self-promotes.

## 5. Pinned inputs for methodological comparisons

Record code SHA, source/input hashes, board/snapshot hash, scoring/config identity, model/parameter version, and timestamp. Do not compare two runs across refreshed data and call the difference a code effect.

## 6. Recommendation is not execution

A model/AI recommendation never silently mutates a league. Mutations need canonical auth/authorization, explicit league/team, appropriate preview/confirmation, idempotency, failure handling, and auditability.

## 7. Facts, opinions, market behavior, and models remain distinguishable

News is not an analyst vote. Market transactions are not projections. Roster concentration is not automatically a trade penalty. A derived panel is not a new independent evidence source.

---

# Canonical value contract

## One canonical methodology today

PR #822 is the current binding implementation decision: the previous league-aware valuation lens was evaluated and **rejected as canonical** under the evidence bar.

Therefore:

- canonical player value/rank/tier has **one** production methodology across mobile/desktop and downstream engines;
- a persisted local setting must not silently select another canonical methodology;
- experimental league-adjusted values may exist for research/diagnostics but must not overwrite canonical `rankDerivedValue`, canonical rank, or canonical tier;
- do not reintroduce a “Market / My League” canonical toggle without a newly validated methodology and explicit promotion;
- the rejection is of the current implementation/evidence, not of league-aware valuation as a future product goal.

The exact live value pipeline is owned by `src/api/data_contract.py` and the canonical valuation modules it calls. **Read the current code and current valuation ADR/evidence before changing it; do not trust an old copied formula in a roadmap or handoff.**

## Source domains

Only observations explicitly verified as **DYNASTY** may influence canonical dynasty player/pick value. Redraft/ROS/weekly/DFS/best-ball-only sources belong in seasonal intelligence, not the dynasty valuation pool.

Unverified game type fails closed; a trusted provider name is not evidence that every feed it publishes is dynasty.

Source-native 1QB/SF/TEP/IDP variants may be archived without becoming multiple independent votes. Same-provider variants/derived boards require explicit family/provenance treatment.

## Picks through 2029

By C completion every valid supported pick through the 2029 class must have a finite non-missing canonical Chase Upside value. Unknown exact slot is an uncertainty/distribution problem, not permission to drop the asset or price it at zero.

Stable real-pick identity must survive season + round + original owner + current owner and transition safely from uncertain/generic to exact-slot value.

---

# Multi-league architecture

The durable split is:

> **Scoring identity controls which scoring-dependent valuation artifacts may be shared. `leagueKey` controls league ownership/context.**

## Scoring compatibility is factual

B6 is merged. `scoringProfile` is a configuration/model label; it is **not** proof that two leagues may share a scoring-dependent ranking contract.

Compatibility must derive/validate from actual scoring settings. Missing/unverifiable evidence fails closed. Do not key a cross-league value cache on `scoringProfile` alone.

## League context is league-scoped

Rosters, managers, teams, pick ownership, matchups, transaction context, selected team, league-specific UI, and other who-owns-what data follow `leagueKey`.

Never combine the requested league's rosters/teams with another league's `scoringSettings`, `rosterPositions`, or `leagueSettings` and stamp the result ready.

Use the canonical resolver/registry already in the code; do not invent raw Sleeper-ID routing in a feature.

---

# Realized scoring

B7 is merged. Historical points, Game Day, Player Impact, Awards, Power, Playoff simulation, and any other realized-performance consumer must use the canonical realized-scoring owner.

Rules:

- every nonzero league scoring rule is either scored correctly or explicitly classified unsupported/unscorable;
- renamed provider/feed fields must not silently become zero;
- player special teams and DST/team-defense scoring remain distinct;
- host/live vocabulary must be validated against the actual source data, not only fixtures written in the engine's own vocabulary.

Do not write page-local scoring calculators.

---

# Public / private distribution boundary

B8 is merged.

Public `/league` and other public distribution channels may expose factual/retrospective/public-safe league products. Proprietary per-manager decomposition, targets, weaknesses, strategy recommendations, detailed roster/FAAB intelligence, private forecasts, and other competitive decision intelligence remain private.

The boundary is semantic, not a brittle field-name denylist. Git/tracked artifacts and alternate representations are distribution channels too; do not fix HTTP privacy while republishing the same private payload elsewhere.

Do not over-close public-safe standings, records, scores, public odds, history, and entertainment simply because a payload contains an owner/team identifier.

---

# Trade architecture

Keep three concepts distinct:

1. **canonical raw asset equity/value**;
2. **exact KTC Value Adjustment** as an advisory market/consolidation lens;
3. **canonical before → apply transaction → rerank/reassign → after roster marginal impact**.

Do not hide them inside one unexplained scalar. Do not invent a proprietary “Our VA” without a defined target and evidence that it adds information.

Trade Calculator, Finder, Suggestions, Package Builder, Golden Upgrades, 3-team trades, equalizers, Trade Desk, and future real-trade comparables should consume common canonical package/ownership/value/roster infrastructure rather than each growing its own rules.

Detailed mature product requirements: `docs/TRADE_CALCULATOR_MARKET_EVIDENCE_EXPANSION_SPEC.md`.

---

# Roster / waiver / draft architecture

Team Strength, Team Weakness, lineup assignment, replacement, roster displacement, and Dropability must converge on shared roster math. FLEX/SUPER_FLEX/best-ball legality makes many questions set-dependent; naïve per-position counts are insufficient.

FAAB must preserve the distinction between:

- objective value/ceiling; and
- this team's recommended bid given budget/need/market context.

Perfect Waivers optimizes adds **with corresponding drops** as roster changes. Perfect Draft is a combination/budget optimizer, not a second rookie ranking engine.

Protected/untouchable assets and intentional roster policies such as QB handcuffs affect action eligibility/personalization, not global canonical player value.

Read current dedicated feature docs/code before altering any of these systems.

---

# Analyst / Sharp / market intelligence

Keep populations distinct:

- broad retail/crowd market;
- real accepted-trade market;
- Sharp cohort behavior/ownership;
- specific league-manager behavior;
- Analyst Intelligence opinions;
- factual news;
- projections/fundamentals;
- Chase Upside canonical conclusions.

Repeated same-analyst theses across podcast/YouTube or syndication do not create false consensus. Stance type, price/context trigger, freshness/event horizon, provenance, and confidence must survive extraction.

`STASH / SPECULATIVE BUY` is not equivalent to a conviction BUY. Inactive historical takes may remain visible after they stop voting.

---

# Historical truth / backtesting

Trade-time values, prediction snapshots, weekly reports, awards, acquisition history, model versions, and similar historical records must remain reconstructable.

For trade history keep distinct:

- **Current Grade** — evaluate with today's canonical methodology/values;
- **At-the-Time Grade** — use closest valid snapshot at or before the transaction;
- **How It Aged** — compare consistent methodology across the two timestamps.

Never substitute today's value for a missing historical value and call it contemporaneous truth.

---

# Frontend contract rule

The frontend is a consumer/materializer of authoritative backend contracts. It must not silently rebuild canonical player values/ranks, source normalization, scoring, or other canonical business truths merely because a payload is incomplete.

Backend-stamped values/ranks win. Missing authoritative stamps should fail/degrade explicitly rather than trigger a hidden client-side replacement engine.

Mobile and desktop must consume the same canonical methodology and value contract.

---

# Performance / serving rule

Correctness comes first, but slow correctness is still a product defect.

Prefer:

**acquire → normalize → background expensive work → materialize/index/cache → serve fast → refresh asynchronously**.

Use bounded request-time work, memoization, batching, precomputation, caching, lazy loading, and LKG/SWR where defensible. Do not hide >5-second operations behind indefinite spinners.

Global product targets are in `MASTER_PRODUCT_PLAN.md`; feature-specific budgets may be stricter.

---

# Testing / validation rules

## Before implementation

- read the active spec and current code;
- identify the canonical owner;
- reproduce the defect/current behavior when fixing correctness;
- pin inputs for any value/model comparison;
- establish RED/falsifiable evidence before GREEN where applicable;
- check for duplicate engines / stale branches / active work claims.

## Before merge

Run the focused tests plus all broad gates required by the change class. For repository-wide PR validation this normally includes:

```bash
python -m pytest tests/ -q
python -m ruff format --check .
python -m ruff check .

cd frontend
npx vitest run
npm run build
```

Also run applicable contract, audit-drift, coercion, bundle-budget, livedata/advisory, backtest, and E2E gates defined by the repo/workflow.

**Exact-head rule:** CI must validate the final candidate SHA. A green result on an earlier head is not evidence for later commits.

## After merge/deploy

For production-impacting work, verify the deployed revision through risk-proportional live checks. A feature is not “done” because unit tests passed if the real product never serves or reaches it.

---

# Git / deployment discipline

- Prefer the smallest correct change at the canonical owner.
- Do not mix unrelated product work into a tightly scoped correctness/model/security pass.
- Rebase/merge against current `main` deliberately; squash-merged branch ancestry can be misleading, so inspect the actual diff against `main`.
- Preserve working behavior unless a verified defect/approved requirement requires change.
- Do not mutate shared globals in request paths unless the architecture explicitly owns that mutation.
- Production is deployed through the checked-in deploy/GitHub Actions path; do not invent a second deployment mechanism inside feature work.
- Rollback must be explicit for material model, schema, migration, or deployment changes.

---

# Key commands

### Start the local stack

```powershell
.\start_dynasty.bat
.\start_frontend.bat
.\start_stack.bat
```

### Common tests

```bash
python -m pytest tests/ -q
npm install
npm run regression:install
npm run regression
```

### Git helper

```powershell
.\sync.bat "commit message"
```

---

# Coding conventions

## Python

- type hints with `from __future__ import annotations` where appropriate;
- dataclasses for internal models, Pydantic for API contracts where used;
- `pathlib.Path` for file operations;
- ISO-8601 UTC timestamps;
- `argparse` for script CLIs;
- explicit exit codes for operational scripts.

## JavaScript / React

- Next.js App Router;
- React hooks for state;
- named exports where consistent with the module;
- presentation/materialization stays separate from canonical backend business logic.

## General

- configuration in canonical config owners rather than duplicated literals;
- environment variables via `.env` / deployment environment;
- Markdown for documentation;
- versioned API/data contracts when semantics change materially;
- comments explain *why/invariant*, not a stale copy of obvious implementation.

---

# Safety

- Do not exfiltrate private data.
- Do not run destructive commands without explicit authorization.
- Prefer reversible operations.
- Be explicit before actions affecting production, deployment, credentials, auth, privacy, or public output.
- Do not publish private manager/roster intelligence merely as “audit evidence.”
- Do not manufacture certainty to keep a page populated.

---

# Final rule for future Claude sessions

Before claiming a material task is ready to implement, answer all of these:

1. Did I start at `PRODUCT_PLAN.md`?
2. Did I read current `MASTER_PRODUCT_PLAN.md`?
3. Does `EXECUTION_PLAN.md` authorize this exact work now?
4. Did I read the detailed owner spec that owns the behavior?
5. Did I inspect current code/runtime evidence rather than trusting a dated status row?
6. Am I modifying the canonical owner rather than creating a parallel engine?
7. Are missing/degraded/provenance/freshness/confidence semantics explicit?
8. Do my tests fail for the defect/mechanism before the fix when applicable?
9. Will exact-head CI + deployment + production verification prove the real outcome?
10. If this is C-series work, has the B→C hard gate passed and has the owner approved the post-B C plan?

If any required answer is no, reconcile the state before implementing.
