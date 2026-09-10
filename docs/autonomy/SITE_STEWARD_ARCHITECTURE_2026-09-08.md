# Autonomous Site Steward — Research-Backed Target Architecture

**Date:** 2026-09-08  
**Status:** implementation architecture / research reconciliation. **Not runtime activation.**  
**Owner direction:** near-full autonomous stewardship with narrow consequential gates.  
**Authority constraint:** Read the live Week 1 contract for its literal count; the 25/30 observation at this document's creation is historical. This document does not authorize broad post-launch implementation, production mutation, new canonical source activation, or methodology promotion while that contract remains active.

Companion:
- `docs/AUTONOMOUS_SITE_STEWARD_VISION.md`
- `config/steward/contracts.schema.json`
- `docs/AGENT_OPERATING_SYSTEM.md`

## 1. Executive verdict

Implementation update, 2026-09-10: the owner-authorized local report-only
foundation now lives in `src/steward/`; see
`docs/agent-operating-system/STEWARD_RUNTIME.md` for executable commands,
schema/version behavior, planning and routing. The launch count and model
pricing/ranking examples below are historical observations from this document's
date, not current state or routing policy. Read the live Week 1 contract and
`config/steward/routing.json`. No unattended activation is implied.

The owner's destination is technically achievable in stages. The durable architecture is **not one lifetime model invocation**. It is a recurrent execution system that wakes bounded model runs, persists operational state outside model context, verifies outputs, and applies only pre-authorized transitions.

| Desired capability | Verdict | Required mechanism |
|---|---|---|
| Keep existing sources refreshed/healthy | POSSIBLE NOW | Existing refresh/source-health machinery + Steward coordination |
| Detect stale/broken/degraded sources | POSSIBLE NOW | Existing health/freshness checks + deterministic lifecycle transitions |
| Discover new public dynasty sources | POSSIBLE NOW | Scheduled web research + quarantined candidate registry |
| Automatically make a discovered source canonical | POSSIBLE BUT INADVISABLE by default | Guarded source-promotion policy; discovery never implies activation |
| Research public competitor features | POSSIBLE NOW | Read-only web/product-intelligence lane + concept registry |
| Independently prototype comparable repo-native features | POSSIBLE NOW | Isolated branch/prototype agent after authority allows |
| Copy proprietary implementations/assets because site is personal | REJECT | Personal/noncommercial status does not erase copyright/access/terms boundaries |
| Ingest public articles | POSSIBLE NOW | Permitted fetch + claim-level provenance + short excerpts/summaries |
| Ingest podcast RSS metadata/publisher-linked transcripts | POSSIBLE NOW | RSS/Podcast Namespace discovery; publisher-linked transcript lane |
| Automatically scrape arbitrary YouTube transcripts | POSSIBLE BUT INADVISABLE | Current YouTube policies prohibit scraping; official caption download is not a generic public-transcript API |
| Use permitted YouTube metadata/pages as research evidence | POSSIBLE NOW | Official API/public permitted access, no scraping circumvention |
| Transcribe audio the system is permitted to download/process | POSSIBLE NOW | Speech-to-text service + rights/access guard |
| Continuously find CI/source/site defects | POSSIBLE NOW | Event/schedule triggers + deterministic monitors + read-only investigator |
| Prepare autonomous fixes/PRs | POSSIBLE NOW | Class-B isolated branch work with deterministic gates |
| Auto-merge every AI fix | POSSIBLE BUT INADVISABLE | Only narrowly pre-authorized low-risk classes after measured reliability |
| Continually fit/backtest model challengers | POSSIBLE NOW | Existing champion/challenger registry + recurrent evaluation |
| Let the model self-promote consequential math | POSSIBLE BUT INADVISABLE | Keep methodology/promotion transition guarded |
| Let the Agent OS improve itself | PARTIALLY POSSIBLE | Eval-driven proposed harness changes; safety/authority boundaries immutable to the runner |
| Run forever from one Astra prompt | NOT CURRENTLY POSSIBLE | External scheduler/event loop + persistent state required |
| Near-full low-touch stewardship | POSSIBLE WITH EXTERNAL INFRASTRUCTURE | Small repo-owned controller/state store + existing schedules/events + bounded model runs |

## 2. What the repository already owns

Do not replace these systems with an “agent platform.”

Current live repository evidence on 2026-09-08 includes:

- `.github/workflows/scheduled-refresh.yml`: primary source refresh every 2 hours (`42 */2 * * *`).
- `public-league-warmup.yml`: 20-minute public snapshot warm-up.
- `prod-e2e-smoke.yml`: production browser smoke every 4 hours.
- `health-check.yml`: production health every 6 hours.
- `smoke-test.yml`: daily repository validation.
- `audit-dropped-sources.yml`: weekly source-drop surveillance.
- `audit-rank-form-drift.yml`: weekly rank-form drift surveillance.
- `refit-hill-curves.yml`: weekly Hill challenger/refit evaluation. Production promotion remains human/guarded.
- `intel-refresh.yml`: daily intelligence refresh.
- `retention-health.yml`: daily retention health.
- `weekly-narratives.yml`: season narrative schedule.
- `deploy.yml`: push-to-main deployment path.
- a source registry/CSV ingestion contract with parity/health tests and 21-source board evidence in current audits;
- `source_health_alerts` wired into the running signal sweep;
- a real `src/model_registry/` champion/challenger/rollback/promotion system;
- a model-neutral Agent OS with work claims, independent review, receipts, graph semantics, budgets, checkpoint requirements, explicit autonomy modes, and a fail-closed halt sentinel design.

The residual is orchestration across these capabilities: durable cross-run state, discovery registries, model routing, bounded agent execution, a unified run receipt, and transition guards.

## 3. Recommended architecture

### 3.1 Choice: hybrid existing infrastructure + repo-owned Steward controller

Build one small `src/steward/` control plane rather than importing a general workflow framework first.

```text
GitHub schedule/event ─┐
systemd timer/event ───┼──> steward preflight/router
webhook callback ──────┘          |
                                  v
                         durable Steward state
                         (private SQLite + JSONL receipts)
                                  |
                    +-------------+-------------+
                    |                           |
            deterministic jobs             model jobs
          (existing scripts/tests)    (Luna/Terra/Sol/Astra)
                    |                           |
                    +-------------+-------------+
                                  |
                         independent verifier
                                  |
                         transition-policy guard
                                  |
              +-------------------+-------------------+
              |                   |                   |
          report only       branch/PR output    guarded executor
                                                (future, narrow)
```

The scheduler decides **when** a run exists. The state machine decides **what bounded unit is eligible**. The model decides **how to reason inside that unit**. A deterministic guard decides **whether a requested transition is allowed**.

### 3.2 Why this beats a new framework today

This repository already has GitHub Actions, systemd timers, SQLite state patterns, CI, deploy gates, source jobs, and a graph-shaped Agent OS. Replacing those with another orchestrator would create a second execution owner.

Use a durable workflow framework only when measured failures show the local controller is no longer sufficient—for example, many multi-day workflows with complex compensation, hundreds of concurrent pending jobs, or frequent crash/retry ambiguity.

## 4. Credible alternatives

### Alternative A — GitHub Agentic Workflows

GitHub Agentic Workflows are a strong **narrow pilot** for repository-only report/review tasks. They run in Actions, support schedules/events and multiple coding engines, are read-only by default, and separate agent reasoning from validated safe outputs. Staged mode can preview writes.

Why not the canonical core yet:
- public preview / subject to change;
- duplicates part of the repository's existing Agent OS and Actions abstraction;
- natural fit for GitHub issues/PRs, weaker fit for private production state/source/media lifecycle;
- persistent cross-run domain state still belongs elsewhere.

Best use: a future read-only CI-investigator/status-report experiment, not the source/model/site control plane.

### Alternative B — LangGraph

LangGraph supplies checkpoint persistence, durable stateful graphs and human interrupts.

Why not now:
- the Agent OS already specifies the graph/role/transition semantics;
- adds a framework/runtime and new persistence conventions;
- interrupt resumption can re-execute node logic, so side effects still need idempotency discipline.

Adopt only if the local state machine becomes difficult to maintain.

### Alternative C — Temporal

Temporal offers the strongest durability guarantee of the compared options: workflows resume across crashes/network/infrastructure failures, including very long-lived workflows.

Why not now:
- substantial operational/platform overhead for a solo personal site;
- current jobs are mostly minutes-to-hours, not business-critical days-to-years transactions;
- existing Actions/systemd + explicit checkpoints can cover Phase 1/2 cheaply.

Reconsider if the Steward becomes a large always-on service with many long-running compensating workflows.

## 5. OpenAI runtime design

Current OpenAI capability is sufficient for the reasoning side:

- GPT-6 Astra: complex end-to-end reasoning/coding/research/computer-use jobs.
- Responses API: background responses, conversations, built-in tools, bounded `max_tool_calls`.
- async tool calling: lets Astra continue while the application executes a pending tool; the **application still owns execution/pending state**.
- webhooks: completion/failure/incomplete/cancelled lifecycle events for background responses.
- prompt caching / compaction: reduce repeated context cost but are not operational memory.
- model snapshots: pin behavior during an evaluation window.

The Steward therefore stores response IDs/conversation IDs as **references**, never as the sole state of a run.

## 5.1 Owner cost policy — zero incremental spend by default

**Owner decision, 2026-09-08:** get everything useful that can be achieved without new metered spend before enabling paid autonomous intelligence.

Until a later explicit owner decision changes this boundary:

- Phase 1 and all pre-Phase-1 Steward preparation use a **$0 incremental usage budget** (`max_usd: 0`);
- do not invoke usage-billed OpenAI API models, API web search, transcription, computer-use, or other metered AI/tool services;
- do not add paid data subscriptions, paid hosted workflow products, or larger paid runners for Steward work;
- prefer the repository's existing standard GitHub Actions on this public repository, existing VPS/systemd capacity already being paid for, deterministic Python/tests, SQLite, HTTP/RSS endpoints that are legitimately free to access, and append-only local receipts;
- an inability to perform semantic discovery/coding without a paid model is a truthful deferred capability, not a reason to silently spend money;
- the model/runtime cannot raise `max_usd` above zero. Paid escalation requires a separate explicit owner authorization recorded durably.

GitHub currently documents standard GitHub-hosted Actions runners as free for public repositories; that makes them the default recurring compute surface where they fit. Existing VPS costs are pre-existing infrastructure, not evidence that a new Steward service is free in an accounting sense.

Reference:
- https://docs.github.com/en/billing/concepts/product-billing/github-actions
- https://docs.github.com/actions/reference/runners/github-hosted-runners

## 6. Model routing

Do not use Astra for every unit.

| Work | Default | Escalate when |
|---|---|---|
| deterministic freshness/schema/count checks | no model | never unless diagnosis is needed |
| high-volume classification/dedup/entity tagging | GPT-5.6 Luna | ambiguity exceeds confidence threshold |
| routine web research/synthesis/source classification | GPT-5.6 Terra | conflicting evidence or consequential recommendation |
| normal coding/review with substantial context | GPT-5.6 Sol | complex architecture/high-risk reasoning |
| hardest architecture, novel debugging, consequential cross-domain review | GPT-6 Astra | default top tier |
| independent verification | equal or stronger than risk warrants; separate context | author evidence is insufficient |

Keep the stable Agent OS/policy prefix cache-friendly; inject current repo/source/run state later. Avoid crossing the 272K-token Astra long-context pricing threshold unless the task truly needs it.

### Illustrative monthly AI budget

These are planning scenarios, not promises. They use current model token rates, $10/1K web-search runs, and GPT-Transcribe at $0.0045/minute. They exclude search-result content tokens, GitHub Actions/VPS costs, computer-use-specific charges, and any >272K Astra surcharge.

| Activity | Approx. monthly variable AI spend |
|---|---:|
| Low — daily classification, ~20 research runs, ~4 Astra escalations, 300 searches, 20 audio hours | **~$20** |
| Medium — several daily lanes, ~60 research runs, ~12 Astra escalations, 1,200 searches, 60 audio hours | **~$80** |
| High — broad seasonal monitoring/prototyping, ~180 research runs, ~40 Astra escalations, 4,000 searches, 150 audio hours | **~$300** |

Set a hard monthly and per-run budget in the runtime. Cost growth should cause graceful deferral, not silent model downgrades on consequential work.

## 7. Persistent state

Use a private SQLite store on the production/steward host for mutable operational state. Do **not** use Git commits as a queue.

Minimum tables/entities correspond to `config/steward/contracts.schema.json`:

- autonomous run contract;
- checkpoint;
- run receipt;
- source candidate;
- feature concept;
- media evidence record.

Also keep append-only JSONL receipts suitable for backup/audit. Every resume begins with a fresh repo/CI/source preflight even when a checkpoint exists.

## 8. Source Steward

### 8.1 Candidate lifecycle

```text
DISCOVERED
  -> QUARANTINED
  -> CLASSIFIED
  -> REPLAYABLE
  -> EVALUATED
  -> CHALLENGER
  -> APPROVED
  -> ACTIVE
  -> DEGRADED
  -> REPAIRED | QUARANTINED | RETIRED
```

No discovered source may vote in canonical production before the approved transition.

### 8.2 Required measurements

For every candidate/active source retain:
- source identity and canonical URL;
- access method and access/terms review timestamp;
- domain/game type/horizon;
- dynasty vs redraft/DFS/best-ball semantics;
- ordinal vs cardinal semantics;
- scoring/TEP/SF/IDP applicability;
- publication/update cadence;
- fetch freshness and content freshness separately;
- schema fingerprint and drift history;
- expected/observed row count and coverage;
- missing/null behavior;
- provenance quality;
- fetch/reliability history;
- correlation/source-family relationship;
- incremental information contribution;
- replay fixture/evidence;
- quarantine/retirement reason.

### 8.3 Automatic decisions

Safe deterministic automatic transitions:
- ACTIVE -> DEGRADED when predeclared health/freshness/schema gates fail;
- DEGRADED -> ACTIVE/REPAIRED when the same objective gates recover;
- any candidate -> QUARANTINED for access-policy failure, unknown semantics, parser/schema uncertainty, or provenance failure;
- suppress an unusable source from current output when canonical missing/stale policy already authorizes that behavior.

Guarded transitions:
- CHALLENGER -> APPROVED/ACTIVE;
- changed source weighting;
- changing ordinal/cardinal interpretation;
- cross-market translation changes;
- permanent retirement when evidence is ambiguous rather than discontinued/prohibited.

## 9. Fantasy-product intelligence

The Steward may inspect publicly accessible feature surfaces to answer five questions:

1. What user problem is being solved?
2. What interaction/evidence pattern solves it?
3. Why is that useful to this league?
4. Does the repository already own an equivalent?
5. What independent implementation would fit our architecture/data/design system?

Current examples show recurring high-value patterns:
- league landscape/positional-strength/free-agent views;
- contender vs dynasty lenses;
- trade-partner discovery;
- mock post-trade power rankings;
- multi-market disagreement;
- real-trade browsers;
- draft assistants/mock drafts;
- historical/portfolio/manager-level views.

These are **concept inputs**, never licenses to copy code, prose, branding or assets.

Feature lifecycle:

```text
OBSERVED -> CONCEPT_NOTE -> FIT_ASSESSED -> INTERNAL_SPEC
         -> PROTOTYPE -> REVIEW -> APPROVED|REJECTED
         -> MERGED -> VERIFIED
```

## 10. Media intelligence

### Articles/public pages

Fetch only access-permitted pages. Store claim-level provenance and compact evidence, not wholesale copyrighted article mirrors. Prefer links + structured claims + short necessary quotations.

### Podcasts

RSS is the preferred automation surface:
- `guid`/publication date identify new items;
- `enclosure` identifies publisher-syndicated media;
- Podcasting 2.0 `<podcast:transcript>` can explicitly link publisher-provided transcript/caption files, including timed formats.

Prefer publisher-linked transcripts. Transcribe audio only when acquisition/processing is permitted, and store structured claims/summaries rather than redistributing full transcripts by default.

### YouTube

Do not build a generic YouTube transcript scraper.

Current YouTube API policy prohibits scraping YouTube applications. The official captions API can list caption tracks with authorization, but downloading captions requires authorization associated with edit permission, so it is not a general public-video transcript feed.

Safe initial lane:
- discover videos through permitted metadata/search;
- record URL/channel/title/date;
- use creator-provided external transcripts/articles/podcast feeds when available;
- process content only through a specifically reviewed permitted mechanism;
- keep YouTube-derived claim state `UNAVAILABLE` rather than bypassing access limits.

## 11. Media evidence semantics

Classify each observation as one of:
- FACT;
- REPORT;
- ANALYST_OPINION;
- PROJECTION;
- RANKING;
- RUMOR;
- RETROSPECTIVE.

A claim needs creator/publisher, source URL/id, publication/retrieval time, episode/article identity, player/team/entity, horizon/game type, timestamp/range when applicable, confidence, freshness/expiry, and source-family/correlation metadata.

Commentary may inform an intelligence feature but is never silently converted into canonical player value or factual news.

## 12. Reliability / performance Steward

Highest-autonomy candidates are settled-semantics repairs:

Eligible early Class-B automation:
- investigate CI failures;
- parser/schema repair behind unchanged contracts;
- stale documentation/status repair backed by executable evidence;
- deterministic dependency/format/lint fixes;
- broken-link/route tests;
- accessibility regressions with deterministic reproduction;
- performance regressions with before/after measurement;
- missing observability/tests for an already-settled invariant.

Remain PR-only / guarded:
- auth/privacy changes;
- source semantics;
- scoring/value/ranking math;
- new feature product decisions;
- schema migrations with destructive behavior;
- dependency upgrades with broad runtime behavior;
- production infrastructure/secret changes.

UI completion requires a real browser flow. Performance completion requires comparable before/after measurement with the same harness and useful-state marker.

## 13. Model/math Steward

Reuse the existing model registry.

Automate:
`refresh -> fit -> leakage checks -> backtest/holdout -> sensitivity -> ablation -> compare -> record -> monitor`.

Do not automate the consequential promotion edge merely because a challenger wins one metric. Promotion remains:
`evaluate -> promotable -> guarded approval/policy -> promote -> apply -> production monitor -> rollback`.

A future deterministic auto-promotion policy would itself be an owner-approved methodology contract with sample-size, freshness, holdout, scope, regression, rollback and cool-down conditions.

## 14. Self-improvement

The Steward may propose Agent OS/skill/tool changes only through an eval-gated harness lane.

Maintain a small representative eval set covering:
- task routing;
- source classification;
- stop/approval behavior;
- false completion;
- exact-head/current-state discipline;
- skill triggering;
- external prompt-injection resistance;
- bounded verification;
- handoff completeness.

Track before/after completion rate, reviewer rejection, context footprint, cost, latency, unnecessary approvals and repeated corrections.

The runner cannot change its own denylist, halt semantics, budget ceiling, approval guards or authority hierarchy.

## 15. Security / threat model

| Threat | Primary control |
|---|---|
| indirect prompt injection in web/page/issue/README | external content is data; read-only untrusted-content worker; structured evidence boundary |
| malicious source asks agent to run commands/change repo | no tool authority derived from content; transition guard rejects |
| exfiltration through browser/tool | least-privilege credentials, domain/network restrictions, no secrets in research worker |
| model invents permission | permission checked by deterministic executor against committed run contract |
| malicious/accidental write | report-only default; branch-only Class B; separate guarded executor |
| retry duplicates side effects | idempotency keys + transition ledger + checkpointed pending actions |
| poisoned memory | provenance on state writes; no raw web text becomes authority/memory |
| compromised model output | schema validation + independent verifier + deterministic gates |
| runaway spend/loop | wall-clock/tool/token/search/action/monthly budgets + retry cap |
| unsafe continuation after operator concern | external fail-closed HALT sentinel checked before run/unit/consequential transition |
| stale checkpoint acts on new repo reality | mandatory fresh preflight before resume/action |

For high-risk web-reading workflows, prefer a **privilege split**: a read-only research worker sees raw untrusted content and emits validated structured evidence; a privileged coding/execution worker receives the evidence record plus trusted repo state, not arbitrary external instructions.

## 16. Scheduler / event policy

“Constant” means event/cadence appropriate to change rate.

| Lane | Initial cadence |
|---|---|
| existing source acquisition | keep existing 2-hour refresh / source-specific cadence |
| source-health evaluation | each refresh + event/failure driven |
| new-source discovery | weekly in-season; biweekly/monthly offseason |
| competitor/product discovery | weekly |
| article/news evidence | daily in-season, lower offseason |
| podcast feed discovery | daily in-season |
| YouTube metadata discovery | daily/weekly; transcript acquisition only if permitted |
| CI failure investigation | event-driven |
| prod health/performance | retain current 4h/6h + deploy checks |
| deep browser/performance sweep | deploy + weekly |
| Hill/model challenger | existing weekly + event when meaningful new evidence warrants |
| harness/model-migration audit | model/runtime release event + monthly |
| Steward self-metrics review | weekly, monthly trend |

GitHub scheduled workflows can be delayed under load, so deadlines requiring precise timing should stay on the existing production/systemd side or verify actual execution time rather than trusting cron intent.

## 17. Autonomy transition guards

- **Class A / observe-report:** automatic after valid run contract + budget + HALT/preflight.
- **Class B / reversible branch-prototype:** requires owner-approved lane, clean work claim, non-overlap, branch-only token, deterministic validation and no production/source/methodology transition.
- **Class C / pre-authorized integration:** initially empty. Add only named change classes after representative run history proves low rejection/regression/rollback rates.
- **Class D / consequential:** explicit guarded owner/methodology/source/security decision unless a later committed contract defines deterministic promotion conditions.

No model output can move an item to a more permissive class.

### Mode × autonomy-class composition

`mode` and `autonomy_class` are intentionally separate axes:

- `autonomy_class` is the **maximum side-effect authority** the run may exercise;
- `mode` is how independently the agent may operate **inside that ceiling**;
- `autonomous` mode never upgrades the authority class.

The initial machine contract enforces:
- Class A => `report_only`;
- Class C/D => a non-empty `owner_authorization_ref`;
- Class D => `assisted` only (no unattended consequential execution).

Future policy may narrow these combinations further. Broadening them is an owner/governance change, not a model decision.

## 18. Success metrics

Track at minimum:
- scheduled-run completion without human rescue;
- false-completion rate;
- independent-review rejection rate;
- autonomous regression rate;
- rollback rate;
- source-failure detection and repair latency;
- stale-source exposure duration;
- useful source candidates / candidates researched;
- accepted feature concepts/prototypes / concepts proposed;
- owner interventions per week;
- repeated-correction rate;
- AI/tool cost per accepted improvement;
- performance regressions caught pre-owner;
- provenance completeness;
- unresolved-item age and routing;
- percentage of runs halted safely when guard/budget conditions fail.

The program succeeds only when site quality improves **and owner monitoring burden falls**.

## 19. Phased implementation

### Phase 1 — report-only Steward

**Authority:** next runtime implementation, but DEFERRED_BY_AUTHORITY while the active Week 1 fixed-denominator launch campaign remains incomplete.

Build:
- `src/steward/` deterministic controller;
- private SQLite state + append-only receipts;
- run-contract validation against `config/steward/contracts.schema.json`, with `max_usd: 0` for the owner-authorized free mode;
- HALT/budget/idempotency/preflight logic;
- read-only lanes for source health, new-source discovery, product concepts, repo/CI health and Steward metrics;
- one existing scheduler trigger plus manual dry run;
- no repository/product mutation.

Acceptance:
- 30 representative scheduled/manual runs;
- resume after forced interruption without duplicate work;
- HALT/budget/retry tests;
- no write-capable token in model research process;
- complete receipt/provenance;
- useful report generated from fresh state;
- zero production mutation.

Exit/rollback: remove/disable trigger; state is observational only.

### Phase 2 — autonomous branches/prototypes/repairs

Permit named Class-B work:
- isolated branches;
- work claims;
- source-adapter challengers;
- routine settled-semantics repairs;
- feature prototypes;
- tests and PR preparation.

Acceptance before expansion:
- independent-review rejection rate and regressions below an owner-set threshold over a representative sample;
- reliable rollback/branch disposal;
- no unauthorized canonical transition.

### Phase 3 — narrow auto-integration

Start with an explicit empty allowlist. Admit only individual low-risk change classes whose deterministic gates and run history justify it.

Every class needs:
- exact allowed paths/action type;
- required tests;
- max blast radius;
- rollback;
- post-merge verification;
- auto-disable on regression/reviewer rejection.

### Phase 4 — mature near-full stewardship

Expand autonomous integration only from measured evidence. Keep Class-D methodology/source/security/product transitions guarded unless the owner explicitly codifies a deterministic policy.

## 20. Research reconciliation

| Finding | Disposition |
|---|---|
| external scheduler, budgets, checkpoints, halt, autonomy modes | ALREADY_COVERED in Agent OS |
| external content is untrusted evidence | ALREADY_COVERED via #1285 |
| mandatory unresolved completion / change-class evidence / progressive skill loading / stop causality | ADD_TO_AGENT_OS via superseded #1287 content carried into this change set |
| long-term source/feature/media/self-improvement destination | ADD_TO_AUTONOMOUS_STEWARD_VISION |
| concrete scheduler/state/model/source/media/security design | ADD_TO_ENGINEERING_BACKLOG / this architecture record |
| six durable state contracts | DETERMINISTIC_TEST_OR_HOOK / machine-readable schema now |
| report-only controller/state store | RUNTIME_IMPLEMENTATION — next, deferred while Week 1 active |
| a new always-loaded Site Steward skill | REJECT FOR NOW — no repeated runtime workflow exists yet |
| Temporal/LangGraph as immediate dependency | REJECT FOR NOW — existing infrastructure is sufficient for Phase 1 |
| GitHub Agentic Workflows as canonical runtime | REJECT FOR NOW; valid narrow pilot after preview/steward evaluation |
| arbitrary YouTube transcript scraping | REJECT |
| copying competitor code/assets/prose | REJECT |
| duplicating shared semantics into CLAUDE.md/AGENTS.md | REJECT |

## 21. Primary research sources

Platform/capability:
- https://developers.openai.com/api/docs/models/gpt-6-astra
- https://developers.openai.com/api/docs/guides/latest-model
- https://developers.openai.com/api/reference/cli/resources/responses/methods/create
- https://developers.openai.com/api/reference/java/resources/webhooks
- https://github.blog/changelog/2026-06-11-github-agentic-workflows-is-now-in-public-preview/
- https://docs.github.com/en/copilot/concepts/agents/about-github-agentic-workflows
- https://docs.temporal.io/
- https://reference.langchain.com/python/langgraph

Media/access/copyright:
- https://developers.google.com/youtube/terms/developer-policies
- https://developers.google.com/youtube/terms/api-services-terms-of-service
- https://developers.google.com/youtube/v3/docs/captions/list
- https://developers.google.com/youtube/v3/docs/captions/download
- https://podcasting2.org/docs/podcast-namespace/tags/transcript
- https://www.rssboard.org/rss-specification
- https://www.copyright.gov/fair-use/more-info.html
- https://www.copyright.gov/title37/202/37cfr202-1.html

Product-pattern research:
- https://www.dynasty-daddy.com/help/trade-calculator
- https://dynasty-daddy.com/help/contender-mode
- https://keeptradecut.com/dynasty/power-rankings
- https://www.dynastynerds.com/dynasty-tools/
- https://www.dynastynerds.com/dynasty-tools/league-analyzer/
- https://dynastyleaguefootball.com/2026/09/03/dlfs-2026-nfl-season-coverage/

These links are evidence sources, not authority over repository/product rules.
