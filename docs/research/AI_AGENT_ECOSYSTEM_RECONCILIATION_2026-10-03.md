# AI Agent Ecosystem Reconciliation — 2026-10-03

**Owner request:** issue #1628\
**External stimulus:** https://x.com/thegreatest_sv/status/2080634616860320073?s=46\
**Repository base inspected:** main at acb1da9c4c084fc1eaa26139ac73cec7307b825a after #1626 merged\
**Agent-OS-Receipt:** cdca1dca8385f70c0989302dece8d1bd4ce4843c\
**Status:** RESEARCH / PLANNING ONLY. This record does not authorize production behavior, source activation, model promotion, spending, merge or deploy.

## 1. Executive Summary

The X post is not a description of one architecture. Its recoverable text is a pointer to a large AI-agent ecosystem catalog: “I FOUND 300+ AI AGENTS SO YOU DON'T HAVE TO.” The remainder describes a free GitHub list mapping 300+ AI-agent tools in one place.

Direct retrieval of the X status is blocked in this environment. The post text is recoverable from indexed search. The X Snowflake resolves to 2026-07-24T12:42:03.638Z. Attached media, author replies and the exact outbound redirect are therefore UNVERIFIED.

The high-confidence catalog match is ARUNAGIRINATHAN-K/awesome-ai-agents-2026. Its repository snapshot immediately before the post already described 470+ tools, so the social headline is a rounded/outdated marketing count rather than a precise inventory fact. Treat the catalog as a discovery index, not an authority.

The main conclusion for Calculator is: **do not adopt another generic agent framework.** Calculator already has a more repo-specific control plane than most of the catalog: Agent OS, Steward, deterministic routing, work claims, autonomy classes, a provenance-aware transactional store, explicit budgets, review/verification gates, model registry, learning receipts and repo-specific agent evals.

The best additive ideas are lower in the stack:

1. exact dependency + build-once/deploy-tested artifact identity;
2. a typed API-contract spine, starting with one low-risk endpoint;
3. vendor-neutral end-to-end application and agent execution telemetry;
4. a future Class-B branch executor with real isolation/capability enforcement;
5. a tighter Steward-receipt -> agent-evals feedback loop.

Browser-agent tooling is useful as a verifier, not as a replacement for deterministic Playwright. Vector-memory products, a second orchestrator, generic multi-agent frameworks, “MCP everywhere,” self-promoting agents and reinforcement-learning control of product behavior are rejected.

## 2. Current Calculator Architecture

### Runtime

Browser -> Nginx -> Next.js -> FastAPI -> SQLite / files / external sources

Current live code establishes:

- Next.js 16.3.6 + React 19.3.0; README still says Next 15 and is stale on this point.
- Python 3.12 + FastAPI + Uvicorn.
- FastAPI owns the canonical private API; Next owns pages.
- Private API middleware gates all /api routes except an explicit public allowlist and self-authenticated endpoints.
- Sessions use an in-memory hot cache plus data/session_store.sqlite persistence with sliding inactivity TTL.
- The rankings contract is built on the backend. frontend/lib/dynasty-data.js explicitly refuses to re-implement ranking math.
- Primary scrape builds the canonical default-league contract; non-default league overlays replace only league context.
- Large contract representations are precomputed and cached as raw/gzip bytes for runtime, startup, array and compact views.
- Production deploy validates a target SHA, then checks out/builds on the VPS; frontend and Python runtime dependencies are still materialized on the production host.

### Product/data modules

Important canonical homes include:

- source intelligence: src/sources, src/source_archive, src/source_quality;
- identity: src/identity;
- canonical valuation: src/api/data_contract.py + src/canonical + src/valuation_math;
- history: src/history;
- model lifecycle: src/model_registry;
- projections/Game Day: src/ros;
- trades/FAAB/waivers: src/trade;
- public league intelligence: src/public_league;
- analyst evidence: src/analyst;
- DFS: src/dfs;
- autonomous engineering/research: src/steward + agent-evals.

### Canonical intelligence flow

The common pattern is:

acquisition -> raw observation -> identity -> normalization -> provenance -> health/freshness/coverage/lineage -> domain-specific calculation -> API contract -> frontend -> user decision

It is intentionally **not** one universal pipeline:

- dynasty values run through source-family/freshness/Hill logic;
- projections use exact scoring and family-level ensembles;
- Game Day uses point-in-time live/pregame archives and simulations;
- completed trades preserve format/timing disposition before use;
- DFS has its own slate/contest/projection/field/portfolio store and is prohibited from feeding dynasty values;
- Steward state/evidence is a private engineering control plane, not product truth.

## 3. Exact X Post Reconstruction

### CONFIRMED

Recoverable indexed text:

> I FOUND 300+ AI AGENTS SO YOU DON'T HAVE TO.

The remainder describes a free GitHub list that maps 300+ AI-agent tools in one place.

Account: thegreatest_sv.\
Status ID: 2080634616860320073.

### INFERRED WITH HIGH CONFIDENCE

The X Snowflake timestamp resolves to 2026-07-24T12:42:03.638Z.

The likely referenced catalog is:
https://github.com/ARUNAGIRINATHAN-K/awesome-ai-agents-2026

Why:
- the wording and scope match;
- the catalog brands itself as an AI-agent ecosystem map;
- it contains the categories implied by the post;
- a pre/post timestamp snapshot exists around the post.

Snapshot immediately before the post:
e92770786caf6612ae2cd5b7b4b841fb3344995c

At that snapshot the README already advertised 470+ tools, which means “300+” is not a precise count.

### UNVERIFIED

Because direct X access is blocked:

- attached image/video contents;
- exact outbound t.co redirect;
- quoted-post contents;
- author thread replies;
- comments;
- any claim that the inferred GitHub repository was definitely the clicked target.

No recommendation below depends on an unverified attachment.

## 4. Technical Decomposition of the X System

The post itself has almost no architecture. The value comes from the referenced ecosystem and its own design guidance.

The catalog’s architecture is straightforward and useful as a pattern: a canonical curated README/data source is parsed at build time into typed normalized data, then served through a static Next application with in-memory search/filter. Calculator already uses stronger variants of this “canonical source -> generated materialization -> read-only UI” pattern in multiple registries and contracts.

The catalog’s design-pattern guide emphasizes:

- controlled workflows before autonomy;
- routing to specialized agents/tools;
- parallel work only when dependencies permit;
- reflection/review;
- human-in-the-loop gates;
- per-step observability;
- single-agent simplicity unless multi-agent coordination earns its complexity.

Those principles align strongly with Calculator’s existing Agent OS.

The external tool families most relevant to Calculator are:

- tracing/agent observability;
- evaluation and benchmark harnesses;
- secure code execution/sandboxes;
- browser verification;
- durable execution;
- typed structured agent/tool contracts;
- tamper-evident action receipts.

## 5. Calculator Overlap Matrix

| External concept | Class | Current Calculator owner | Gap / decision |
|---|---|---|---|
| Controlled flow + human gates | A — ALREADY STRONGER | docs/AGENT_OPERATING_SYSTEM.md; config/steward/contracts.schema.json | Keep current authority model. |
| Specialist agents/handoffs | A/B | Agent OS graph; Steward planner/routing; work claims | No new agent framework. |
| Durable task state/checkpoints | A | src/steward/store.py + controller.py | SQLite/CAS is sufficient until measured failures prove otherwise. |
| Agent memory | A | src/steward/store.py | Reject vector DB/second memory store. |
| Cost/model routing | C — PARTIAL | src/steward/routing.py | Recommendation logic exists; execution telemetry is not yet rich enough to optimize cost-per-success. |
| Agent evals | C | agent-evals | Exact-diff and CI evidence are strong; Steward receipt/run evidence is not yet a first-class eval input. |
| Agent tracing | C | Steward receipts + server metrics/logging | Missing one end-to-end span/event vocabulary across app + autonomous work. |
| Tool/command guardrails | C | contracts schema allowed/denied actions/paths/domains | Strong policy contract; future Class-B execution still needs real OS/network/credential enforcement. |
| Secure sandbox | C/G | future Steward Class B | Pattern valuable; paid cloud sandbox not authorized. Prefer local/container/worktree enforcement first. |
| Browser agent | C/G | Playwright E2E + performance baselines | Useful for adversarial UX discovery; deterministic Playwright remains canonical verification. |
| Durable workflow platform such as Temporal | E/F | systemd/GitHub Actions/SQLite/Steward | No measured need for a second orchestration substrate. |
| LangGraph/CrewAI/AutoGen-style orchestrator | F | Agent OS/Steward | Duplicates a more repo-specific owner. |
| OpenAI Agents SDK wholesale | E/F | Agent OS/Steward | Useful reference patterns; do not replace the control plane. |
| Structured tool schemas | B/C | JSON Schema contracts, dataclasses | Agent contracts strong; HTTP API response typing remains weak. |
| Typed HTTP API spine | D — MISSING + HIGH VALUE | FastAPI/server.py + frontend clients | No response_model usage on server.py; add incrementally. |
| OpenTelemetry-style traces | D/C | server JSON logs + route-specific diagnostics | High-value missing cross-layer correlation. |
| Exact dependency/artifact identity | D | build_identity.py + deploy workflows | SHA is strong; dependency tree/artifact identity is not. |
| Build once, deploy tested artifact | D | CI/deploy | Current deploy rebuilds/installs on VPS. |
| Cryptographic action receipts | E/G | immutable Steward/model receipts | Interesting if threat model expands; signature does not prove truth. |
| MCP everywhere | F | existing CLI/scripts/tools | Adds schema/context/attack surface without a requirement. |
| Vector/RAG project memory | F | Steward SQLite/provenance store | Wrong problem; semantic-vector retrieval gap has not been demonstrated. |
| Local open model routing | G | Steward model routing | Only after a zero-incremental-cost runtime and eval evidence exist. |
| Prompt optimization/self-repair | G | agent-evals + retrospective | Challenger-only, never self-promoting. |
| Reinforcement learning for agent/product decisions | F/G | Adaptive Learning governance | Not justified; production decision rules remain gated. |

## 6. What We Already Do Better

Calculator is already stronger than the generic ecosystem pattern in several areas:

1. **Authority is data, not vibes.** Autonomy class, allowed/denied actions, path/domain constraints, budgets and halt sentinel are explicit contracts.
2. **Memory has provenance and authority.** Steward evidence records source/time/repo-head/completeness and keeps superseded history instead of treating “memory” as an opaque vector retrieval result.
3. **Learning is separated from activation.** Model registry, challengers, learning receipts and owner/P6 gates make evaluation non-equivalent to promotion.
4. **Missing/stale semantics are structural.** Source acquisition/freshness and projection ensembles refuse common missing->zero and stale->current coercions.
5. **Repo evals are artifact-grounded.** agent-evals distinguishes declared claims from exact-artifact verification and can bind CI evidence to the pinned revision.
6. **Work coordination is explicit.** Work claims, canonical owners and integration gates address the biggest practical multi-agent failure mode: simultaneous edits and false completion.
7. **Product-domain isolation is unusually strong.** DFS, seasonal projections, dynasty valuation and league context have explicit non-contamination boundaries.

Replacing these with a general agent product would be a regression.

## 7. Gaps Exposed by the Post

### Gap 1 — artifact reproducibility is behind commit reproducibility

src/api/build_identity.py proves the running Git SHA well. The deploy path still installs Python dependencies and builds Next on the VPS. requirements.txt is compatible-release based, not an exact lock. That allows the tested source revision and deployed dependency/build graph to diverge.

The nfl_data_py comment is an especially useful warning: the repo can describe a capability as enabled while a runtime dependency is intentionally not installed by the canonical manifest.

### Gap 2 — HTTP contracts are not typed end-to-end

server.py has no response_model occurrence. src/data_models/contracts.py uses dataclasses for ingestion/canonical records, but important HTTP responses remain dictionary/JSONResponse shaped and frontend types are hand-maintained JavaScript.

The safest pilot is GET /api/leagues because it is public, small and has an explicit redaction/privacy contract.

### Gap 3 — tracing is fragmented

Calculator has:
- structured JSON logging;
- request IDs/error envelopes;
- scrape/source diagnostics;
- route baselines;
- build SHA identity;
- Steward receipts;
- learning receipts.

What it does not have is one vendor-neutral trace/span vocabulary joining:
browser/Next -> backend route -> cache/pipeline stage -> source generation -> persistence
and, separately:
Steward task -> agent/turn -> tool/action -> guard/verifier -> handoff -> result/cost.

### Gap 4 — future write-capable autonomous execution needs enforcement, not only a schema

The Steward contract already describes path/action/domain restrictions. Phase 1 is report-only. Before Class B becomes real, branch-only autonomous work needs a concrete execution boundary:
- isolated worktree/container;
- non-root runtime identity;
- no production credentials;
- egress allowlist/default deny where feasible;
- file/path allowlist;
- command/tool allowlist;
- bounded resource limits;
- immutable run evidence.

### Gap 5 — agent eval feedback can be more automatic without becoming self-promoting

The pieces exist but are not fully connected:
Steward receipts/run state -> normalized eval artifact -> deterministic agent-evals grading -> retrospective challenger recommendation.

That is a high-leverage safe loop because the final step remains recommendation only.

## 8. Architecture Improvements

### A. Artifact identity chain

Current:
Git SHA -> CI validation -> SSH deploy -> production resolves dependencies/builds frontend -> process reports Git SHA

Target:
Git SHA -> exact dependency locks -> CI-built backend/frontend artifacts -> artifact manifest/digests -> deploy exact tested artifact -> process reports Git + dependency + artifact identity

Owner:
engineering reliability/deploy, extending src/api/build_identity.py and existing deploy workflows.

No new service is required.

### B. Typed API contract ratchet

Current:
FastAPI handler -> dict/JSONResponse -> manual frontend consumer/tests

Target:
Pydantic response model -> OpenAPI -> generated/checked frontend type -> consumer -> contract/adversarial test

Start with GET /api/leagues only. Do not convert the whole API in one migration.

### C. Unified trace correlation

Current:
independent logs/metrics/receipts

Target:
trace_id/request_id/deploy_sha/artifact_id/source_generation/run_id propagated through existing boundaries, with span-style events for important work.

Do not send private league payloads or source-native private values to telemetry.

### D. Class-B executor

Current:
Steward planner/contracts -> report-only controller

Target:
planner/contracts -> capability gate -> isolated branch workspace -> bounded tools/network -> verifier -> PR/handoff receipt

No merge/deploy privilege.

### E. Eval bridge

Current:
Steward receipt + agent-evals are separate stores/workflows

Target:
Steward receipt/run evidence -> deterministic adapter -> agent-evals run artifact -> grade -> retrospective recommendation

No model/harness auto-promotion.

## 9. Product Improvements

The X ecosystem itself does not reveal a compelling new dynasty/DFS user feature. Most applicable value is engineering substrate.

Indirect product gains:

- faster/safer deploys reduce stale/outage risk;
- typed contracts reduce UI/API drift;
- traces shorten diagnosis of slow Rankings/Trade/Game Day/DFS paths;
- browser adversarial verification can catch mobile/useful-state failures missed by unit tests;
- better agent evals improve the development system that ships product features.

Do not add an “AI agents” page or user-facing agent gimmick merely because the catalog exists.

## 10. Adaptive Learning Opportunities

Useful:
- reuse agent-eval thinking for model evaluation: exact version, point-in-time inputs, outcomes and evidence class;
- treat harness/model-routing changes as challengers evaluated against a fixed corpus;
- learn routing/cost only from completed run evidence with task class and success/reviewer outcomes.

Not useful:
- online self-modifying production valuation;
- reinforcement learning that changes trade/ranking methodology;
- “agent trust score” as a substitute for model-specific validation;
- automatic promotion because an agent’s historical success rate is high.

Adaptive Learning’s existing observation -> feature -> prediction -> outcome -> evaluation -> challenger -> governed promotion model remains superior.

## 11. Agent OS / Site Steward Opportunities

### P0 candidate: execution-span vocabulary

Add a small model-neutral local event contract:
- run_id;
- task_id/work_unit;
- agent/provider/model when applicable;
- phase: plan / turn / tool / guard / handoff / verifier / write;
- tool/action;
- start/end/duration;
- input/output token counts when exposed;
- cached tokens when exposed;
- cost when exposed;
- success/failure/refusal;
- retry;
- evidence refs;
- exact repo heads;
- authority decision.

This should extend receipts, not create a second telemetry database.

### P0/P1 candidate: Steward -> agent-evals adapter

Build an adapter only after the active claims ledger is writable. It should create an eval artifact from a completed Steward run while preserving VERIFIED/DECLARED/NOT_CHECKED distinctions.

### P1 candidate: Class-B isolation design

Use the contract’s existing allowed_paths/denied_actions/allowed_domains as the policy source. Enforcement must live outside model reasoning.

### P2 candidate: model-operated browser reviewer

Use existing Playwright CLI/skills patterns for token-efficient coding-agent browser work. MCP is justified only for a long-lived exploratory loop where persistent browser state outweighs its context/tool-schema cost.

## 12. Performance / Cost Opportunities

### Cheap deterministic filter -> expensive reasoning

Calculator already applies this principle in several forms. Extend it to agent routing:

1. deterministic preflight/policy/static checks;
2. deterministic retrieval/context pruning;
3. cheap/no-model task classification where the task is obvious;
4. one capable model only for ambiguous/high-value reasoning;
5. independent reviewer only when risk/acceptance profile warrants it.

Expected effect is primarily **agent token/tool reduction**, not user-page latency.

### Browser tooling

For coding agents, Playwright’s own guidance favors CLI + skills over MCP because the CLI avoids loading large tool schemas/accessibility trees into context. That fits Calculator’s existing Playwright investment.

### CI

The catalog does not change the repo’s existing conclusion: improve parallelization/caching and exact artifact reuse; do not drop tests to get faster.

### Operational cost

Default new recurring external-service cost remains $0. Hosted sandbox/observability products are not required to realize the design improvements.

## 13. Reliability / Testing / Observability Opportunities

1. Finish exact dependency/artifact identity.
2. Add typed response models incrementally.
3. Add OpenAPI-driven/adversarial tests after enough endpoint schemas become authoritative.
4. Add trace correlation to high-value routes and source pipelines.
5. Extend property/mutation tests around authority/policy decisions.
6. Feed actual agent run artifacts into agent-evals.
7. Preserve browser useful-state tests as final truth for user-visible behavior.
8. Add a small SLO set: availability, authenticated core-flow success, data freshness, API latency and frontend Core Web Vitals.

## 14. Security / Permission Architecture

### Read-only

Agents may inspect:
- repository code/docs;
- public external research;
- non-secret test artifacts;
- current Git/PR/work-claim state;
- sanitized source fixtures.

### Sandboxed

Agents may:
- execute tests;
- run replay/backtests;
- use synthetic fixtures;
- run browser verification against approved targets;
- build challenger artifacts;
- modify a disposable worktree.

No production credentials.

### Write-to-branch

Only under a valid claim:
- bounded code/docs changes;
- tests/evidence;
- PR creation;
- no merge unless existing integration policy authorizes it.

### Production-sensitive

Explicit authorization:
- deployment;
- source activation;
- credentials;
- paid services;
- methodology/model promotion;
- production data mutation.

### Hard deny

- bypassing access controls;
- secret exfiltration;
- disabling safety/acceptance gates to pass;
- autonomous paid spend;
- self-granting additional authority;
- model-generated production actions that deterministic policy has not permitted.

## 15. Proposed Target Architecture Delta

### Delta 1 — build identity

Current:
main SHA -> validate -> rebuild on VPS -> Git SHA status

Proposed:
main SHA -> exact locks -> CI artifact -> digest/manifest -> deploy exact artifact -> Git+artifact status

Failure:
artifact identity mismatch refuses deploy or marks verification failed.

Rollback:
redeploy prior known-good artifact or existing flag/revert mechanism.

### Delta 2 — API contract

Current:
GET /api/leagues -> dynamic dict -> JSONResponse -> JS consumer

Proposed:
GET /api/leagues -> LeagueListResponse model -> OpenAPI -> generated/checked frontend type -> same UI

Failure:
schema mismatch fails CI before deploy.

Rollback:
remove response_model/type generation without changing endpoint semantics.

### Delta 3 — telemetry

Current:
logs + counters + domain receipts

Proposed:
existing owners emit correlated span-like events to one local/OTel-compatible vocabulary.

Failure:
telemetry must degrade without breaking product paths.

Rollback:
feature/config disable exporter; retain normal logs.

### Delta 4 — Steward Class B

Current:
planner -> report-only controller

Proposed:
planner -> deterministic capability gate -> isolated workspace -> bounded action -> verifier -> receipt/PR

Failure:
fail closed, preserve workspace/evidence, no production side effect.

Rollback:
disable Class B; report-only remains.

## 16. Prioritized Roadmap

Scores are ordinal 1–10. They are decision aids, not fake ROI mathematics.

| Candidate | User value | Reliability | Eng leverage | Difficulty | Ops complexity | Ongoing cost | Risk | Confidence | Overall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Exact dependency + artifact identity | 6 | 10 | 10 | 7 | 6 | 2 | 4 | 10 | P0/P1 |
| Typed API pilot + ratchet | 6 | 9 | 9 | 5 | 3 | 1 | 3 | 10 | P1 |
| Unified app + agent trace vocabulary | 5 | 9 | 10 | 6 | 5 | 1 | 3 | 9 | P0/P1 |
| Steward -> agent-evals bridge | 3 | 9 | 9 | 4 | 3 | 1 | 2 | 9 | P0 |
| Class-B isolation/capability executor | 4 | 10 | 9 | 8 | 7 | 2 | 6 | 9 | P1 |
| Browser-agent adversarial verifier | 5 | 7 | 7 | 5 | 4 | 2 | 4 | 8 | P2 |
| Tamper-evident/hash-chained action receipts | 2 | 5 | 4 | 5 | 4 | 1 | 3 | 7 | P2 |
| Local model routing | 2 | 5 | 5 | 7 | 7 | 3 | 5 | 5 | P2 |
| New generic agent orchestrator | 1 | 2 | 1 | 8 | 9 | 4 | 8 | 10 | REJECT |
| Vector DB for Steward memory | 1 | 1 | 1 | 6 | 6 | 3 | 6 | 10 | REJECT |
| MCP for every tool | 1 | 2 | 2 | 6 | 7 | 2 | 6 | 9 | REJECT |
| RL/self-promoting agent behavior | 1 | 1 | 2 | 10 | 10 | 8 | 10 | 10 | REJECT |

Interpretation:
- P0 means prepare/execute the bounded unit as soon as coordination/authorization permits.
- P1 means high-value engineering after current conflicting work and prerequisites.
- P2 means shadow/research first.
- REJECT means no roadmap item should be created absent materially new evidence.

## 17. Five Biggest Wins

### #1 — exact lock + tested artifact identity

Why it matters:
production truth currently proves source commit better than dependency/build truth.

What exists:
SHA pinning, build_identity.py, deploy smoke, npm lock.

Change:
add exact Python resolution and artifact manifest/digests; stop independently rebuilding the tested application on production as the end state.

Likely owners:
requirements/lock, .github/workflows, deploy, src/api/build_identity.py, deploy verification tests.

Risk:
medium migration risk; coordinate with Dependabot.

Authorization:
PLANNING ONLY unless an execution-plan engineering unit is opened.

### #2 — typed API spine, one endpoint first

Why:
reduces backend/frontend/redaction drift.

Start:
GET /api/leagues, because it has a small public/private view contract and no current response_model.

Likely files:
new src/api/schemas/leagues.py; server.py route; generated frontend type artifact/tooling; contract tests.

Authorization:
PLANNING ONLY.

### #3 — unified trace/event vocabulary

Why:
the product and agent harness both have excellent local evidence but weak cross-boundary correlation.

Change:
vendor-neutral trace IDs/spans tied to deploy/artifact/source/run identity.

Authorization:
bounded report-only Steward telemetry may be AUTHORIZED NOW under the Agent OS consolidation; product-wide instrumentation is PLANNING ONLY.

### #4 — Class-B isolated branch executor

Why:
policy contracts already exist; the next autonomy step needs enforcement outside the model.

Change:
isolated workspace + non-root identity + no prod credentials + network/path/tool policy + verifier.

Authorization:
BLOCKED BY ACTIVATION/PHASE AUTHORITY for real autonomous branch execution.

### #5 — Steward receipt -> agent-evals loop

Why:
creates a safe continuous-improvement loop for the engineering harness without self-modification.

Change:
deterministic adapter + exact-artifact grading + retrospective recommendation.

Authorization:
conceptually within existing bounded Agent OS/eval work, but implementation is currently BLOCKED BY COORDINATION because the shared work-claim ledger is actively claimed.

## 18. Exact Repository Changes for P0/P1

### Artifact identity

Likely:
- an exact Python lock artifact chosen by the repository (uv.lock or an equivalent hashed lock);
- requirements.txt remains the human/runtime intent manifest if desired;
- .github/workflows/pr-validation.yml / deploy.yml / release-candidate.yml consume exact resolution;
- deploy/deploy.sh deploys the tested artifact rather than re-resolving/rebuilding as the end state;
- src/api/build_identity.py grows dependency/artifact fields;
- scripts/verify_lockstep.ps1 and deploy tests verify identity;
- artifact manifest includes git SHA, lock digest, frontend build ID/digest and backend dependency digest.

No feature flag is required for a build-system migration; rollout should support one reversible old/new deploy path until production proof is complete.

### Typed API pilot

Likely:
- src/api/schemas/leagues.py (new);
- server.py GET /api/leagues response model only;
- generated or checked frontend type under frontend/lib or a generated-types directory;
- tests/api test asserting private fields cannot enter the public model;
- frontend consumer compile/check test;
- scripts/validate_api_contract.py extended only as needed.

No endpoint semantic change.

### Trace/event vocabulary

Likely:
- src/observability or an existing diagnostics owner after canonical-owner review;
- middleware propagation in server.py only after active server claims clear;
- src/steward receipts/routing adapter for agent-run spans;
- local JSON/SQLite or OTel-compatible exporter;
- tests that prove telemetry failure cannot fail a product request.

Private payloads must not be recorded.

### Steward eval bridge

Likely:
- agent-evals adapter for Steward receipt/run artifacts;
- src/steward read-only export helper if needed;
- tests in tests/agent_evals and tests/steward;
- no model calls in CI;
- no self-promotion.

### Class-B executor

Likely later:
- config/steward contract enforcement extension;
- isolated worktree/container runner;
- capability gate module;
- secret/network policy;
- resource limits;
- verifier/handoff receipt;
- adversarial tests proving denied paths/domains/commands cannot be reached.

No production credentials; no merge/deploy action.

## 19. Existing Work / PR Collision Check

At this research checkpoint:

- #1627 Signals Fantasy is open and touches docs/OWNER_REQUESTED_TODO.md, docs/WORK_CLAIMS.md, docs/ARCHITECTURE.md, data_contract.py, feature flags, source/model files and rankings UI.
- #1618 pick ownership is open and touches trade/draft/league identity paths.
- #1533 Rookie Auction is open and touches auction + work-claims infrastructure.
- #1513 awards is open and touches planning/owner-intake records.
- #1508/#1506 are Python dependency updates; #1507 is a frontend test dependency update.

#1626 merged during this research and advanced main to acb1da9c4c084fc1eaa26139ac73cec7307b825a.

Therefore:
- do not edit OWNER_REQUESTED_TODO.md or WORK_CLAIMS.md from this branch;
- do not start the lock/dependency migration while dependency PRs are unresolved without a fresh claim/reconciliation;
- do not touch server.py/data_contract.py from this research branch;
- the new research document path is intentionally isolated.

## 20. Authorization Status

| Recommendation | Status |
|---|---|
| Research document + issue capture | AUTHORIZED NOW — executed |
| Steward report-only run telemetry design | AUTHORIZED NOW in principle under bounded Agent OS consolidation; implementation needs a fresh work claim |
| Steward -> agent-evals deterministic adapter | AUTHORIZED NOW in principle; BLOCKED BY COORDINATION until claim ledger clears |
| Exact dependency/artifact migration | PLANNING ONLY |
| Typed API response-model pilot | PLANNING ONLY |
| Product-wide OTel-style instrumentation | PLANNING ONLY |
| Class-B autonomous branch executor | BLOCKED BY DEPENDENCY / ACTIVATION AUTHORITY |
| Browser-agent reviewer | P2; NEEDS OWNER/AUTHORITY for unattended paid/computer-use execution |
| Paid hosted sandbox/observability | NEEDS OWNER APPROVAL / spend approval |
| Model/source/methodology promotion | existing domain policy only; this research grants none |
| New agent framework / vector memory / RL autonomy | REJECT |

## 21. Durable Records Updated

Executed:

- GitHub issue #1628 — durable owner research request.
- docs/research/AI_AGENT_ECOSYSTEM_RECONCILIATION_2026-10-03.md — this detailed research record on branch chatgpt/ai-agent-ecosystem-reconciliation-2026-10-03.

Intentionally NOT edited:

- docs/OWNER_REQUESTED_TODO.md;
- docs/WORK_CLAIMS.md;
- docs/EXECUTION_PLAN.md.

Reason:
active claims/open PRs currently touch the shared planning/intake ledgers. Per repository coordination rules, avoiding an overlapping edit is safer than manufacturing a merge conflict.

Required follow-up:
after conflicting claims clear, add one compact OWNER_REQUESTED_TODO pointer to issue #1628 / this research record. That pointer is intake capture, not implementation authorization.

## 22. Unresolved Questions / Evidence Gaps

1. X direct page/media/thread/outbound-link access remains blocked. The exact post text is recovered, but media/replies are UNVERIFIED.
2. The Awesome AI Agents repository is a high-confidence match, not a cryptographically proven outbound redirect from the post.
3. The catalog’s marketing counts, market stats, project “tier” badges and vendor claims are not accepted as evidence without primary-source verification.
4. No measured production trace study has yet quantified how much unified tracing would reduce diagnosis time.
5. No Class-B autonomous executor exists on main, so sandbox requirements remain a design target, not a measured implementation comparison.
6. Exact Python locking technology should be selected by a bounded implementation unit after resolving current dependency PRs; the requirement is exact reproducibility, not allegiance to uv/pip-tools/etc.
7. Browser-agent verification needs an explicit target/use case and authority boundary; existing deterministic Playwright is already the default.
8. The final owner-intake pointer remains blocked by active shared-ledger claims and must be reconciled later.

## Source notes

Primary external references inspected:
- X status URL above; indexed search for exact text; direct X fetch blocked.
- ARUNAGIRINATHAN-K/awesome-ai-agents-2026, including README, ARCHITECTURE.md, DATA_SCHEMA.md and Design Patterns.md; pre-post snapshot e92770786caf6612ae2cd5b7b4b841fb3344995c.
- OpenAI Agents SDK official documentation for agents, tracing, guardrails and sandbox concepts.
- Microsoft Playwright / Playwright MCP official repository and CLI guidance.
- E2B primary repository for isolated hosted sandboxes.
- Galley primary repository for executor/supervisor/worktree/evidence patterns.
- Nobulex primary repository for cryptographic receipt concepts, including its own warning that signatures authenticate content rather than establish truth.
- OpenTelemetry and OWASP agent-security primary guidance.

The external ecosystem was used as a stimulus and comparison set. Repository-native architecture and live code remain authoritative.
