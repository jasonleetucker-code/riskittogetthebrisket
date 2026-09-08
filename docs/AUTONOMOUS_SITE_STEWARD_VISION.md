# Autonomous Site Steward Vision

**Status:** owner-approved long-term direction, recorded 2026-09-08.

**Current implementation authority:** design/governance only. This document does **not** activate an unattended runner, change source weights, promote a model, add a production source, scrape a new site, change product methodology, or bypass any active completion contract / `docs/EXECUTION_PLAN.md`.

## 1. Goal

The long-term goal is to make Risk It To Get The Brisket behave like a continuously improving personal dynasty-football intelligence system with a website as its durable interface.

The desired system should require very little routine owner attention while continuously:

- keeping existing public data sources healthy and fresh;
- discovering potential new public sources;
- detecting stale, broken, degraded, duplicated, or low-value sources;
- researching fantasy-football products and public user-visible features for useful ideas;
- independently designing and prototyping comparable concepts that fit this site's own architecture and league;
- ingesting permitted public articles, transcripts, podcasts/video-derived text, and other evidence into provenance-aware intelligence lanes;
- detecting defects, drift, performance regressions, dead paths, stale documentation, and broken assumptions;
- repairing bounded defects and improving dependency-ready code;
- running challenger experiments for ranking/model/math improvements;
- verifying its own work through independent evidence and reviewers;
- leaving durable receipts so any run can be audited, resumed, or rolled back.

The target is **near-full automation with narrow, explicit human gates**, not an unconstrained self-modifying agent.

## 2. The model is the brain, not the scheduler

Astra or any future model is one component of the system.

The recurrent system must be:

`scheduler/event -> preflight -> state/authority load -> agent graph -> tools -> independent verification -> guarded action -> receipt/checkpoint -> next wake`

The scheduler/runtime decides **when** work starts. The model decides **how** to execute the currently authorized bounded contract.

As of 2026-09-08, OpenAI documents GPT-6 Astra as supporting web search, computer use, hosted shell, apply-patch, skills, MCP/tool search, async tool calling, multi-agent orchestration, and long-running/background Responses. Background Responses can report completion/failure via webhooks. Those capabilities make this architecture feasible, but they do not replace the repo-owned scheduler, persistent state, budgets, permissions, or kill switch.

Reference:
- https://developers.openai.com/api/docs/models/gpt-6-astra
- https://developers.openai.com/api/docs/guides/latest-model
- https://developers.openai.com/api/reference/resources/responses
- https://developers.openai.com/api/reference/resources/webhooks

Keep vendor-specific API syntax out of the canonical operating rules; the architecture must survive future model/provider changes.

## 3. “One lifetime prompt” means a versioned contract, not a giant prompt

Do not attempt to encode the entire future system in one enormous static prompt.

The durable equivalent is:

- a small model-neutral front door (`AI_INSTRUCTIONS.md`);
- the Agent OS;
- canonical product/architecture/methodology records;
- narrowly loaded skills;
- a machine-readable autonomous-run contract;
- persistent state/checkpoints;
- deterministic guards/tests;
- external scheduler/runtime policy;
- append-only receipts;
- owner-adjustable gates and budgets.

The owner should eventually be able to issue a simple instruction such as “run the site steward” because the durable details live in the repository and runtime, not because the instruction repeats a lifetime of process text.

## 4. Stewardship lanes

A recurrent steward should use separate lanes with separate authority and evidence.

### 4.1 Existing-source health

Continuously monitor existing sources for:

- acquisition success/failure;
- schema drift;
- row-count anomalies;
- freshness / source-as-of;
- game-type correctness;
- data-domain correctness;
- unexpected null/missing coverage;
- duplicate/correlated evidence;
- downstream reachability;
- parser breakage;
- terms/access changes that materially affect permitted acquisition.

Existing deterministic health policy may automatically mark a source degraded/unavailable when the evidence proves that state.

**Do not substitute stale data silently. Missing is never zero; stale is never current.**

### 4.2 New-source discovery

The steward may autonomously discover and research candidate public sources.

Candidate lifecycle:

`DISCOVERED -> QUARANTINED -> CLASSIFIED -> REPLAYABLE -> EVALUATED -> CHALLENGER -> APPROVED -> ACTIVE`

Retirement path:

`ACTIVE -> DEGRADED -> QUARANTINED -> REPAIRED or RETIRED`

A candidate must not influence canonical values merely because the agent found it.

Evaluate at minimum:

- public accessibility / permitted acquisition;
- source identity and provenance;
- exact game type and scoring/format;
- dynasty vs redraft/DFS/best-ball/weekly boundary;
- update cadence/freshness;
- coverage and missing behavior;
- stable schema or replayable acquisition contract;
- ordinal vs cardinal meaning;
- population and correlation with existing sources;
- whether it adds independent information rather than another copy of the same signal;
- source reliability history where measurable;
- whether the site can fail closed when it becomes unavailable.

**Source discovery and source activation are separate transitions.**

Under current repository governance, a new source or changed weighting that affects canonical production math requires the existing promotion/owner gate. A future owner decision may authorize a narrowly defined deterministic auto-promotion policy, but an agent may not invent that permission itself.

### 4.3 Feature / competitor intelligence

The steward may recurrently inspect publicly accessible fantasy-football sites, release notes, public screenshots/pages, documentation, discussions, and product announcements to discover useful **concepts**.

Examples include:

- league activity visualizations;
- market/roster concentration ideas;
- trade-history views;
- power-ranking explanations;
- contender/rebuilder views;
- waiver/FAAB tools;
- manager tendencies;
- draft tools;
- matchup/game-day ideas;
- historical/franchise storytelling;
- new ways to expose provenance, uncertainty, disagreement, or freshness.

Feature-discovery lifecycle:

`OBSERVED -> CONCEPT_NOTE -> FIT_ASSESSMENT -> INTERNAL_SPEC -> PROTOTYPE_BRANCH -> REVIEW -> OWNER/PRODUCT_GATE -> MERGED -> VERIFIED`

The system should compare the observed concept against the live repository first. If an equivalent owner already exists, extend it instead of creating a competitor clone.

#### Independent implementation rule

Public ideas may inspire functionality. Do **not** copy proprietary source code, copyrighted text, private/paywalled material, branding, visual assets, or a site's protected implementation.

Personal/noncommercial use does not erase copyright, access controls, robots/terms restrictions, or other legal/contractual boundaries.

Capture the **problem solved, user outcome, interaction pattern, and evidence model**, then design an implementation from this repository's own primitives, data, architecture, and visual system.

### 4.4 Public media / analyst evidence

The long-term system may ingest permitted public information from:

- articles;
- newsletters where access permits;
- public YouTube transcripts/captions;
- podcast transcripts or feeds when lawfully/technically available;
- press conferences/interviews;
- public rankings/projections;
- other public football analysis.

Every observation must preserve provenance such as:

- creator/publisher;
- URL or stable source identifier;
- title/episode/video;
- publication/recording date;
- retrieval date;
- exact timestamp/range when derived from audio/video;
- claim type;
- player/team/entity identity;
- game type / horizon;
- freshness/expiry;
- confidence/coverage;
- correlation/source-family information.

Commentary is evidence, not canonical fact. The system must distinguish reports, opinions, rankings, projections, rumors, and retrospective observations.

When a canonical analyst/evidence ledger exists, extend it rather than creating a parallel media-opinion owner.

### 4.5 Quality / reliability steward

This is the safest high-autonomy lane.

The agent may continually look for:

- failing CI;
- flaky tests;
- type/contract drift;
- broken links/routes;
- stale docs/work claims;
- unreachable/dead code;
- duplicated canonical owners;
- security/dependency warnings;
- browser/console errors;
- accessibility regressions;
- source-health failures;
- bad missing/stale handling;
- observability gaps;
- performance regressions.

Bounded reversible repairs with settled semantics are candidates for autonomous branch/PR execution under an owner-approved runner contract.

### 4.6 Performance / UX steward

Continuously measure high-value surfaces against the existing performance standard.

The system may:

- detect regressions;
- isolate likely causes;
- create bounded optimization branches;
- measure before/after using the same harness;
- verify real desktop/mobile browser flows;
- reuse the existing design system and architecture.

It may not declare success from code inspection or a clean build when the acceptance claim is user-visible behavior.

### 4.7 Math / model / rankings steward

The system may continuously:

- refresh approved inputs;
- detect drift;
- fit challenger models;
- backtest;
- run sensitivity/ablation analysis;
- test invariants;
- compare champions/challengers;
- produce promotion recommendations;
- monitor an already approved champion.

It may **not** silently self-promote new constants, source weights, scoring methodology, ranking formulas, or model versions.

The established sequence remains:

`fit -> backtest -> validate -> compare -> approval -> promote -> monitor -> rollback`

Automation should make everything before the approval gate dramatically easier, not delete the gate.

### 4.8 Agent/harness self-improvement

The steward may audit its own harness for:

- stale instructions;
- old-model compensations;
- duplicate skills;
- contradictory routing;
- unnecessary always-loaded context;
- over-testing;
- under-triggering/over-triggering;
- obsolete tool syntax;
- context-cost growth;
- repeated human corrections that should become a test/hook/rule.

Harness changes follow the same review/evidence rules as code. The agent may not weaken its own safety/approval boundaries simply because they make a run harder.

## 5. Autonomy classes

Use explicit classes rather than one global “autonomous” switch.

### Class A — observe/report

May research, measure, classify, and produce receipts. No mutation.

Examples:
- new-source discovery;
- competitor feature watch;
- source freshness reports;
- performance monitoring.

### Class B — reversible workspace/branch work

May create bounded local changes, fixtures, challenger experiments, prototypes, tests, or PRs.

Examples:
- scraper repair;
- test strengthening;
- UI prototype;
- performance optimization branch;
- source acquisition prototype that is not production wired.

### Class C — routine integration under pre-approved policy

May merge/deploy only when a committed owner-approved contract explicitly permits that exact class of change and deterministic gates prove all conditions.

This class should initially be narrow.

### Class D — consequential methodology/product/authority change

Requires a guarded owner decision unless a future owner record explicitly changes the boundary.

Examples:
- promoting a ranking/model challenger;
- changing source weights;
- activating a new canonical source;
- changing scoring/math semantics;
- introducing a new product concept into the official roadmap;
- changing privacy/auth boundaries;
- weakening safety/budget/deploy gates.

## 6. Discovery is broad; production authority is narrow

A mature steward should be extremely proactive **before** consequential boundaries.

It should be able to discover ten possible sources, reject seven, replay/evaluate three, and present one strong challenger without asking the owner to micromanage each research step.

It should be able to inspect many public fantasy products, deduplicate ideas against the repo, and prototype the best-fitting concept without requiring repeated prompts.

It should be able to find and repair obvious bounded breakage automatically.

The owner gate should happen near the consequential transition, not at every intermediate reasoning step.

## 7. Persistent state the system needs

A recurrent runner needs machine-readable durable state, not only chat history.

At minimum:

- last successful run per lane;
- last processed source/item identifiers;
- pending async/tool work;
- current candidate-source registry and lifecycle states;
- source-health history;
- candidate feature/concept registry;
- challenger experiment registry;
- open branch/PR/work-claim ownership;
- budgets/spend;
- retry state;
- receipts/evidence;
- unresolved decisions;
- cooldowns / next eligible checks;
- halt state.

Every run must refresh live GitHub/CI/source state before resuming a checkpoint.

## 8. Required runtime protections

Any unattended implementation must inherit the Agent OS autonomous-loop envelope:

- external scheduler;
- hard wall-clock/action/retry/parallel/spend budgets;
- allow/deny boundaries;
- one auditable execution gateway;
- append-only trace/receipt;
- resumable checkpoints;
- independent verification;
- external halt sentinel / kill switch;
- explicit report-only / assisted / autonomous mode;
- dry-run mode;
- rollback path;
- current-state preflight before consequential action.

The model cannot grant itself broader permissions.

## 9. Evidence-based source retirement

Do not remove a source simply because one fetch fails.

Retirement/quarantine policy should distinguish:

- transient fetch failure;
- authentication/access change;
- schema change;
- temporary site outage;
- stale publication;
- discontinued product;
- wrong game-type discovery;
- systematic low coverage;
- duplicated/correlated information;
- provenance failure;
- terms/access boundary change.

A source may be automatically excluded from current output when existing deterministic freshness/health rules prove it unusable. Permanent retirement or replacement should preserve the reason and historical provenance.

## 10. Research cadence should match change rate

“Constantly” does not mean every lane runs every minute.

Examples:

- current source acquisition: existing source-specific cadence;
- source-health alarms: event/failure driven;
- new-source discovery: weekly or monthly;
- competitor/product discovery: weekly;
- release-note/model/harness audit: on relevant model/runtime releases plus periodic review;
- podcast/video/article discovery: daily/weekly during season depending on value/cost;
- performance/browser regression: CI/deploy + periodic production sampling;
- deep model challenger work: scheduled when enough new evidence exists, not continuously.

Cadence is an operational policy and should be optimized for signal value, cost, rate limits, and source terms.

## 11. What “full automation” should mean here

A successful mature system should let the owner spend attention primarily on:

- genuinely subjective product choices;
- methodology changes with meaningful league consequences;
- new consequential data/source promotion;
- unusual failures;
- occasional review of what the steward has built/discovered.

It should **not** require the owner to repeatedly tell an agent to:

- refresh known sources;
- notice obvious source breakage;
- rerun routine tests;
- find stale work claims;
- measure regressions;
- research whether a public source has changed;
- scan for product ideas;
- produce bounded prototypes;
- investigate routine failures;
- preserve recurring lessons.

That is the automation target.

## 12. Phased implementation path

### Phase 0 — current foundation

Already present in the repository:

- model-neutral Agent OS;
- provider adapters;
- work claims / PR coordination;
- independent review;
- completion contracts;
- source-health concepts;
- tests/CI;
- bounded graph/loop rules;
- receipts;
- autonomous-runner safety design;
- halt/budget policy;
- model-migration/instruction-debt auditing.

### Phase 1 — report-only steward

Build the scheduler/state store and run recurrent read-only lanes:

- source health;
- new-source discovery;
- competitor-feature watch;
- current OpenAI/model/harness watch;
- performance/quality observations.

No production mutation.

### Phase 2 — autonomous branch/prototype steward

Permit bounded Class-B actions:

- repair obvious source parser breakage;
- strengthen tests;
- create challenger source adapters;
- create feature prototypes;
- fix routine defects;
- prepare PRs and evidence.

### Phase 3 — narrow auto-integration

After a representative evaluation period, authorize only carefully selected low-risk change classes for automatic integration when all deterministic gates are green.

### Phase 4 — mature near-full stewardship

Expand autonomy only where run history proves quality, rollback works, false-positive rates are acceptable, and owner review burden falls rather than rises.

Do not jump directly from design policy to unrestricted production mutation.

## 13. Success metrics for the steward itself

Measure whether autonomy is actually helping:

- percentage of scheduled runs completing without human rescue;
- false-completion / reviewer rejection rate;
- regressions introduced per autonomous merge;
- rollback rate;
- mean time to detect and repair source failures;
- stale-source exposure time;
- useful new-source candidates discovered vs noise;
- useful feature concepts/prototypes accepted vs noise;
- owner interventions per week;
- repeated correction rate;
- cost per accepted improvement;
- time-to-useful-state/performance regressions caught;
- percentage of actions with complete provenance/receipt;
- unresolved items aging without routing.

Autonomy is successful only when it improves site quality **and** reduces owner monitoring burden.
