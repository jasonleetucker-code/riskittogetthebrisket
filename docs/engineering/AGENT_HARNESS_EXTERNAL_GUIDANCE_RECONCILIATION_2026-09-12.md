# Agent-Harness External-Guidance Reconciliation — 2026-09-12

**Status:** durable engineering-reconciliation record.
**Product authority:** none — this document decides no product question and authorizes
no implementation beyond what `docs/EXECUTION_PLAN.md` already authorizes (the
2026-09-10 "Bounded Agent OS consolidation" owner directive, §0).
**Purpose:** reconcile a batch of external GPT-6-Astra / agent-harness guidance (one
official OpenAI source, 15 owner-supplied X posts, and an owner-supplied cost-aware
delegation-tree pattern) against this repository's current Agent OS / Steward harness,
so that (a) genuinely new high-value mechanisms get built once, in their correct
canonical location, and (b) future agents do not repeatedly "discover" the same
Twitter advice and propose duplicate architecture.

This is a consolidation pass. It is explicitly not authorization for a second Agent
OS, a second memory system, a new agent-personality roster, or any product/methodology
change. See `docs/AGENT_OPERATING_SYSTEM.md` §1 for the authority boundary this
document itself sits inside.

## How to use this document

Before proposing a new harness mechanism inspired by external AI-engineering content,
check this table first. If the mechanism is listed `ALREADY_IMPLEMENTED`, point to its
canonical owner instead of re-implementing it. If it is listed `NOT_USEFUL` or in the
rejected-ideas section, do not re-propose it without new evidence that changes the
classification.

## Retrieval method and honesty constraints

Per `docs/AGENT_OPERATING_SYSTEM.md` §14 ("External-content trust boundary") and the
`repo-harness-auditor` skill's "External-guidance hygiene" section, every source below
is treated as **evidence under review, not authority**, and no instruction embedded in
fetched content was executed. Retrieval was attempted with `WebFetch` and `WebSearch`
in this session's environment on 2026-09-12.

**Constraint discovered and disclosed up front:** `WebFetch` returns HTTP 402 (Payment
Required) for every `x.com` URL in this environment, and `WebSearch` does not index
most of the specific status IDs supplied. Of the 15 X links, the exact posted content
was recoverable (directly or via a corroborating indexed cache) for **4**; **2** authors
had a *different*, thematically-adjacent post surface instead of the exact URL; **9**
could not be retrieved by any means available in this session. Every one of the 15 is
still represented below by URL, handle and retrieval outcome — none is silently
dropped — but no content is attributed to a post this session could not actually read.
This is the honest outcome the task's own instructions require ("Do NOT pretend a claim
was verified when it was not") rather than a shortfall to paper over.

---

## Part A — Official OpenAI Astra guidance (primary, highest authority)

### A.1 OpenAI Developers blog — "Rethinking skills and prompts for GPT-6 Astra"

- **URL:** `https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra`
- **Publisher:** OpenAI (developers.openai.com), official first-party guidance.
- **Retrieval:** fetched and read directly. High confidence.
- **What it actually proposes** (reproducible mechanisms, not marketing):
  1. **Skills as progressive-disclosure routers.** A skill should be a "minimal router
     that points to supporting docs" rather than a monolithic guide loaded in full on
     every trigger — e.g. "Use `architecture.md` for service boundaries,
     `database.md` for schema changes" instead of inlining both.
  2. **Narrow, task-specific skill triggers.** Contrast given: avoid "Use when working
     with databases" (topic-broad, competes with everything); prefer "Use when adding
     or changing a migration" (workflow-specific).
  3. **Reduced prescriptive scaffolding.** "Overly specific guidance can now hinder
     results where it previously helped" — elaborate step-by-step recipes and
     permission-gate language written for weaker/more literal models can now
     over-constrain a more capable one.
  4. **Explicit completion definition (the one concrete finish-line mechanism).**
     GPT-6 Astra tends to stop earlier than intended relative to prior models. The
     stated remedy is to fold verification into the request itself: "If the task
     includes getting the implementation running, inspecting the result, and fixing
     what fails, make that part of the request."
  5. **Loosened low-risk permission gates.** Where a previous, more literal model
     needed "ask first" language for routine actions (running/fixing tests), that
     language can now cause unwanted under-triggering; grant standing permission for
     genuinely low-risk, reversible loops (run, fix, rerun affected tests) instead.
- **Explicitly not discussed in this source:** subagent delegation, model-routing /
  cost-efficiency policy, or multi-agent graphs. Those come from the X-post batch,
  the owner's own agent-tree pattern, and this repo's pre-existing Agent OS design —
  not from OpenAI's Astra post itself.
- **Repo analogue:** `.agents/skills/*/SKILL.md` (skill triggers), `docs/AGENT_OPERATING_SYSTEM.md`
  §3 ("Completion result contract", `UNRESOLVED` mandatory field), `AI_INSTRUCTIONS.md`
  (universal front door).
- **Classification:** `PARTIAL` → now largely covered.
  - Progressive-disclosure skill routing: **actively being implemented right now** by
    open PR #1344 (`codex/harness-progressive-disclosure`) — narrowed skill triggers,
    26%-smaller Agent OS core, 57%-smaller `repo-harness-auditor` skill. This
    reconciliation defers to that PR rather than duplicating it.
  - Explicit completion definition: **already implemented** — `docs/AGENT_OPERATING_SYSTEM.md`
    §3's "Completion result contract" (`STATUS/ACCEPTANCE/EVIDENCE/UNRESOLVED/BLOCKERS/NEXT_ACTION`,
    with `UNRESOLVED` mandatory even when `NONE`) already encodes "define what done
    looks like" as a structural requirement rather than a per-prompt reminder — this
    predates the Astra post and is a stronger mechanism (machine-checkable completion
    state vs. a written reminder in the prompt).
  - Reduced prescriptive scaffolding / loosened low-risk gates: **`DEFERRED_BY_AUTHORITY`
    to PR #1344's "model-migration hygiene" pass** (`repo-harness-auditor` SKILL.md
    already has a full "Model-migration hygiene" section for exactly this — auditing
    old anti-undertrigger instructions, "MUST/CRITICAL/always verify" wording, and
    over-verification caused by prompts written for a weaker model). Not re-audited
    here to avoid a second migration pass in flight at the same time as PR #1344.
- **Canonical destination:** `.agents/skills/*/SKILL.md` (already exists — PR #1344's
  concern), `docs/AGENT_OPERATING_SYSTEM.md` §3 (already exists), this document
  (record only).

### A.2 OpenAIDevs — X status 2098480213244117065

- **URL:** `https://x.com/openaidevs/status/2098480213244117065?s=46`
- **Publisher:** OpenAI Developers (official account).
- **Retrieval:** direct `WebFetch` returned HTTP 402; the exact text was recovered via
  an indexed search-engine cache. High confidence — this is OpenAI's own one-line
  restatement of A.1: *"Get more out of GPT-6 Astra by revisiting your skills,
  AGENTS.md, and task prompts. Make skill triggers specific, load guidance when it's
  relevant, and define what done looks like."*
- **Mechanism:** identical to A.1, condensed. No new information.
- **Classification:** `ALREADY_IMPLEMENTED` / duplicate of A.1. No separate action.

---

## Part B — The 15 owner-supplied X posts

Ordered as supplied. Each row states exactly what was recoverable, at what confidence,
and what — if anything — is adopted.

| # | Handle / URL (status id) | Retrieval outcome | Central mechanism (as far as verifiable) | Confidence | Repo analogue | Classification | Adopted / rejected |
|---|---|---|---|---|---|---|---|
| 1 | `av1dlive` / `2097362674078331148` | **UNVERIFIED — RETRIEVAL BLOCKED.** WebFetch 402; WebSearch did not index this exact status ID. The same author has other, differently-numbered posts on file with a recognizable thesis ("harness engineering is the next $100B opportunity... the model is almost irrelevant, the harness is everything, every failure is a signal about what the environment needs") — noted as **same-author-thematic-adjacent, not verified content of this URL**. | "Harness > model" thesis (adjacent post only) | Low (adjacent-post inference only) | `docs/AGENT_OPERATING_SYSTEM.md` §7 (correction/learning edges — "the harness should record why," not just what) already embodies "the harness is what matters, not the model" | `ALREADY_IMPLEMENTED` (as a general principle, from repo's own pre-existing design, not from this post) | Rejected as a *new* input — cannot adopt unverified content; the general principle it appears to state is already structural here |
| 2 | `lucaspatiri_` / `2097357340215279710` | **UNVERIFIED — RETRIEVAL BLOCKED.** Neither WebFetch nor WebSearch surfaced this post or any close match; account's indexed content is unrelated (growth/marketing case studies). | Unknown | None | — | `NOT_USEFUL` (no retrievable mechanism) | Rejected — no content to evaluate |
| 3 | `kocer_eth` / `2098333699641086183` | **UNVERIFIED — RETRIEVAL BLOCKED.** Account's indexed content (Cursor student-plan referral post) is unrelated to agent-harness engineering; this specific ID not found. | Unknown | None | — | `NOT_USEFUL` | Rejected — no content to evaluate |
| 4 | `rubenhassid` / `2098365950940569639` | **UNVERIFIED — RETRIEVAL BLOCKED.** Account posts general "AI tool tips" content (Claude Cowork setup, model comparisons); this exact ID not indexed. | Unknown | None | — | `NOT_USEFUL` | Rejected — no content to evaluate |
| 5 | `virgilxbt` / `2098412843775172931` | **UNVERIFIED — RETRIEVAL BLOCKED** for this exact ID. A different, indexed post from the same account (status `2092703095453040928`) reposts Steve Yegge (ex-Google/Amazon): *"Delete your IDE, you don't need it anymore. At Google, 85% of engineers are running agentic loops and graphs, and that is what the engineering setup will look like."* — noted as **same-author-thematic-adjacent, not verified content of this URL**. | "Loops and graphs are the new IDE" (adjacent post) | Low (adjacent-post inference; also a secondhand claim about Google's internal engineering, itself unverified/anecdotal) | `docs/AGENT_OPERATING_SYSTEM.md` §5 ("Work is a graph; each unit is a loop") is the repo's own loops-and-graphs model, already built independently and in more structural detail (fan-out/fake-edge test, quorum-aware fan-in, transition guards, graph specification contract) than a one-line claim about Google's headcount mix can establish | `ALREADY_IMPLEMENTED` | Rejected as a *new* input; the "85% of engineers" statistic is an unverified adoption claim per the repo's own external-guidance-hygiene rule and is not treated as evidence of anything |
| 6 | `openaidevs` / `2098480213244117065` | See Part A.2 above (verified, high confidence). | Astra skill/AGENTS.md/finish-line guidance | High | — | `ALREADY_IMPLEMENTED` | Adopted via A.1/A.2 already; no separate action |
| 7 | `txbrraa` / `2098521751898529815` | **UNVERIFIED — RETRIEVAL BLOCKED.** No indexed content found for this handle/ID at all. | Unknown | None | — | `NOT_USEFUL` | Rejected — no content to evaluate |
| 8 | `akshay_pachaar` / `2064051835636498924` | **PARTIALLY VERIFIED.** Indexed as an X long-form "article" titled *"Your Agent Harness Should Repair Itself."* Recoverable summary: when an agent fails in production, observability tools show *what* the agent did but little about *how to fix it*; references Cursor's public engineering writeups describing an agent harness as "layers of prompts, tools, and checks wrapped around the raw model." Full article text not recoverable — mechanism-level paraphrase only. | Self-repairing harness / failure-as-signal for harness improvement | Medium (title + one indexed paraphrase, not full text) | `docs/AGENT_OPERATING_SYSTEM.md` §7 (correction vs. learning edges) and §14's "Engineering reliability program" flywheel (`Agent-OS receipt -> repo task eval -> deterministic grading -> model/harness comparison -> targeted harness change`); Steward's `diagnose_failures()` ("records specific rule references when repeated independent failures suggest an instruction/specification problem") | `ALREADY_IMPLEMENTED` (design) / `PARTIAL` (missing the deterministic eval anchor) | **Adopted the one concretely missing piece**: this reconciliation builds `agent-evals/` (§D below), which is exactly the "deterministic grading" stage the existing flywheel design named but did not yet have a corpus for. Rejected: any notion of the harness *automatically* rewriting itself — `docs/AGENT_OPERATING_SYSTEM.md` §6/§14 already require eval-gated, human/integration-approved promotion, never self-promotion |
| 9 | `0xricker` / `2097328121556979988` | **UNVERIFIED — RETRIEVAL BLOCKED.** Account's indexed content is prediction-market trading strategy, unrelated to agent harnesses; this ID not found. | Unknown | None | — | `NOT_USEFUL` | Rejected — no content to evaluate |
| 10 | `gippp69` / `2097696163424014406` | **UNVERIFIED — RETRIEVAL BLOCKED.** Different, indexed post from the same account concerns "building a company inside a Grok bot" — unrelated theme; this exact ID not found. | Unknown | None | — | `NOT_USEFUL` | Rejected — no content to evaluate |
| 11 | `mikenevermiss` / `2098270564016091458` | **UNVERIFIED — RETRIEVAL BLOCKED.** Only third-party replies to a differently-numbered article by this account were indexed ("nice article," no content recoverable); this exact ID not found. | Unknown | None | — | `NOT_USEFUL` | Rejected — no content to evaluate |
| 12 | `pvncher` / `2095991462416490862` | **VERIFIED — corroborating, not independent.** The same numeric ID is indexed both as `x.com/pvncher/status/2095991462416490862` and `x.com/pvncher/article/2095991462416490862` (X's long-form "article" post type), titled *"Rethinking skills and prompts for GPT-6 Astra"* by Eric Provencher — i.e. this is a long-form X repost/commentary of the same OpenAI content in Part A.1, not an independent source. Recoverable content matches A.1 (defining completion before starting; GPT-6 Astra "feels more tentative about when to stop" than 5.6 Sol; "instructions can take many forms — Skills, AGENTS.md, and task prompts"). | Identical to A.1 | High (matches primary source) | Same as A.1 | `ALREADY_IMPLEMENTED` (duplicate of A.1) | No separate action — already covered by A.1's disposition |
| 13 | `maestrooth` / `2096882831138165160` | **UNVERIFIED — RETRIEVAL BLOCKED.** No content indexed for this exact account/ID (a differently-spelled account, `@MaestroHR`, is unrelated). | Unknown | None | — | `NOT_USEFUL` | Rejected — no content to evaluate |
| 14 | `sairahul1` / `2096902575035683147` | **PARTIALLY VERIFIED.** Indexed summary describes a "GPT-6 Astra Prompting Masterclass" thread: defining what completion looks like before a task starts, production-ready system prompts, and workflow-specific sections. Full thread text not recoverable. | Same finish-line mechanism as A.1, mechanism-level only | Medium (paraphrase only) | Same as A.1 | `ALREADY_IMPLEMENTED` (duplicate mechanism, already covered) | No separate action |
| 15 | `n01ennn` / `2096962591125905888` | **UNVERIFIED — RETRIEVAL BLOCKED.** A different, indexed post from the same account (a Postiz/solo-founder growth case study) is unrelated; this exact ID not found. | Unknown | None | — | `NOT_USEFUL` | Rejected — no content to evaluate |

**Summary of Part B:** of 15 supplied links, 2 (#6, #12) independently corroborate the
primary OpenAI source with no new mechanism; 2 (#8, #14) contribute partial,
mechanism-level content (one already covered — #14 — one contributing the concrete
`agent-evals/` gap — #8); 2 (#1, #5) have only unverifiable adjacent-post evidence
whose apparent thesis already matches pre-existing repo architecture; 9 could not be
retrieved by any means available and contribute nothing beyond being recorded as
attempted-and-blocked. No unsupported adoption/statistic claim from any of the 15 was
converted into a repository fact, per `docs/AGENT_OPERATING_SYSTEM.md` §14.

---

## Part C — Owner-supplied cost-aware agent-tree pattern

```
GPT-6 Astra — medium          (root / orchestrator)
  delegate on demand:
    explorer:   Luna — max     (bounded investigation)
    worker:     Sol — high     (implementation + tests)
    researcher: Luna — max     (focused lookup)
GPT-6 Astra — medium          (integrate + verify)
  only if needed:
    GPT-6 Astra — xhigh        (independent review)
```

- **Durable principle stated by the owner:** *"Split useful work. Don't spawn every
  role."*
- **Repo analogue:**
  - `docs/AGENT_OPERATING_SYSTEM.md` §5, "Fake-edge test" — *"For every proposed
    dependency, ask: does the downstream node actually consume the upstream result...
    If neither is true, the edge is fake and the jobs should usually run in
    parallel"* and "When not to graph" — *"If the fake-edge test finds no independent
    jobs, there is no useful graph to build."* This is the same principle, already
    written down and already load-bearing (it is what stops a lead from mechanically
    spawning explorer/worker/researcher/reviewer on every task).
  - `config/steward/routing.json` — capability-based ROUTINE/STANDARD/COMPLEX/CRITICAL
    profiles with owner pins, prohibitions, minimum-profile and escalation/downgrade
    rules already implement "least expensive sufficient available profile, escalate
    on evidence" (§0/AI_INSTRUCTIONS.md's own wording), which is the routing half of
    the screenshot's intent.
  - This session's own tool surface (the `Agent` tool's guidance: *"Do not spawn
    agents unless the user asks... A task with multiple angles... is not a request to
    spawn"*) already encodes the identical discipline at the harness level this
    session runs under.
- **Classification:** `ALREADY_IMPLEMENTED` (the durable principle) /
  `NOT_USEFUL` (the specific model roster — Astra-medium/Luna-max/Sol-high/Astra-xhigh
  — as a fixed routing table; this is a snapshot of one interactive harness's
  available models on one day, not a portable policy).
- **Adopted:** the principle only, and only because it was already the repo's
  principle before this reconciliation — no new code needed.
- **Explicitly rejected:** hardcoding this or any other named model/effort roster
  into `config/steward/routing.json` or `docs/AGENT_OPERATING_SYSTEM.md`. The
  directive's own "Things you must not implement" #9–#10 name this exactly ("A fixed
  model mapping based on one screenshot," "'Medium reasoning is always best'"), and
  `docs/agent-operating-system/STEWARD_RUNTIME.md` already states the correct
  standard: *"Claude, Gemini and Grok adapters can supply their own verified
  metadata; they remain unconfigured rather than pretending availability."*

---

## Part D — Repository-state findings: what is already implemented vs. genuinely open

This reconciliation inspected current `main` (`fc01c4177e72d3162676c2ce9e99644897df173`
at session start, 2026-09-12) plus every open and recently-closed PR touching Agent
OS / Steward / harness territory, per `ASSISTANT_COORDINATION.md`'s "check who else is
in there" rule. Two other sessions are working directly adjacent territory right now;
this reconciliation is written to complement, not duplicate, them.

| Directive deliverable | Disposition | Evidence / current owner |
|---|---|---|
| **D1 — this reconciliation document** | `NEW_HIGH_VALUE` | Nothing like it existed before this document. |
| **D2 — durable owner-intake pointer** | `ALREADY_IMPLEMENTED` (mechanism); this document adds the one expected pointer row | PR #1339 (**merged** 2026-09-11, `chatgpt/owner-todo-zero-loss-2026-09-10`) built the durable chat-to-intake capture rule now in `AI_INSTRUCTIONS.md` and the live ledger structure in `docs/OWNER_REQUESTED_TODO.md`. This reconciliation reuses that exact mechanism (see the new row added to `docs/OWNER_REQUESTED_TODO.md`) rather than inventing a second one. |
| **D3 — repo-specific agent/harness eval foundation (`agent-evals/`)** | genuinely `PARTIAL` → now `NEW_HIGH_VALUE`, built in this pass | Confirmed **absent from `main`'s filesystem** at session start. PR #1318 (`codex/agent-os-steward-telemetry`, **closed, not merged**, 2026-09-09) attempted a Steward evaluation/telemetry foundation (`evaluation.py` declaring a 7-stage pipeline, 3 `IMPLEMENTED_STAGES` / 4 `DEFERRED_BY_AUTHORITY`) but never reached `main`. `docs/engineering/ENGINEERING_RELIABILITY_PRIORITIES_2026-09-06.md` Priority 8 explicitly names `agent-evals/` as the open item. Built in this PR — see Part E below. |
| **D4 — instruction-economy / progressive-disclosure audit of CLAUDE.md, AGENT_OPERATING_SYSTEM.md, skills** | **IN PROGRESS ELSEWHERE — do not duplicate** | Open PR #1344 (`codex/harness-progressive-disclosure`, opened 2026-09-12T07:27Z, ~2 hours before this reconciliation began) is doing exactly this: conditional specialist-guidance loading, narrowed skill triggers, Agent OS core reported 26% smaller by word count, `repo-harness-auditor` reported 57% smaller, evidence in `docs/agent-operating-system/HARNESS_DISCLOSURE_AUDIT_2026-09-11.md`, status `READY_FOR_INTEGRATION` at time of writing. This reconciliation makes **zero edits** to `CLAUDE.md`, `docs/AGENT_OPERATING_SYSTEM.md` structure, or `.agents/skills/*` content to avoid a collision on the repo's own high-conflict-file custodianship rules (`ASSISTANT_COORDINATION.md`). Any instruction-economy finding from Part A/B above that duplicates #1344's scope is marked `DEFERRED_BY_AUTHORITY` to that PR. |
| **D5 — bounded subagent / write-scope policy (lead / investigator / implementation-owner / reviewer roles, disjoint-scope parallel writers)** | `ALREADY_IMPLEMENTED` | `docs/AGENT_OPERATING_SYSTEM.md` §4 ("Roles: responsibility, not personality" — product owner / implementation owner / integration role / independent reviewer / deterministic judge / production verifier, each with explicit responsibilities and non-responsibilities) and §5 ("Hidden edges," "Verifier independence," hidden-edge fake-edge test) already state this explicitly and are already tested indirectly via `tests/docs/test_agent_operating_system.py`. No gap found that this pass should fix. |
| **D6 — eval-gated harness-improvement flywheel** | `ALREADY_IMPLEMENTED` (design) + this pass supplies the missing anchor | `docs/engineering/ENGINEERING_RELIABILITY_PRIORITIES_2026-09-06.md`'s own "Agent improvement flywheel" (`Agent-OS receipt -> repo task eval -> deterministic grading -> model/harness comparison -> targeted harness change`) and Steward's `retrospective()`/`diagnose_failures()` (`docs/agent-operating-system/STEWARD_RUNTIME.md` §"Routing and Learning" — "proposes challengers without promoting them") already state the design correctly. What was missing was the "repo task eval / deterministic grading" stage itself, which had no corpus on `main` — this is exactly `agent-evals/` (Part E). No change was made to Steward's promotion boundary; evaluation still cannot self-promote. |
| **D7 — Steward memory hardening (provenance, freshness class, conflict representation, stale-retrieval detection, cross-model continuity)** | mostly `ALREADY_IMPLEMENTED`; one real `PARTIAL` found, deliberately not fixed in this pass | `src/steward/store.py` already requires `{source, at, repo_head, content, complete}` on every raw evidence record, enforces authority tiers (`observation < verified < repository < owner`, lower cannot supersede higher — see the `AUTHORITY` check), and keeps immutable superseded history. `docs/agent-operating-system/STEWARD_RUNTIME.md` already states the freshness-class distinction ("current PR state = volatile... owner product decision = durable until superseded") and cross-model continuity is already tested (`tests/steward/test_continuity.py` per that doc's "Verification and Continuity" section — "A different model retrieves durable evidence; hidden model state is never transferred"). **The one genuine gap:** the `source` field on a raw evidence record is free text, not a structured session/model/provider attribution field, so "which session/model produced this evidence" is recoverable only if the free-text value happens to encode it. This is real but small, and `src/steward/store.py` is a transactional schema that was itself only merged 2026-09-10 (PR #1333) with its own compare-and-swap revision tests — changing its schema in the same pass as this reconciliation would raise exactly the kind of regression risk `docs/AGENT_OPERATING_SYSTEM.md` warns against for "smallest correct change set." **Deferred explicitly** — see Part F. |
| **D8 — finish-line / task-contract review (objective, acceptance criteria, authority, human-decision boundaries, source-role disambiguation, verification, stop condition, unresolved requirements, budget/delegation bounds)** | `ALREADY_IMPLEMENTED` | `config/steward/contracts.schema.json` already defines `verifier`, `unresolved`, `budget` (wall-clock/actions/tool-calls/retries/parallel/USD), `halt_sentinel`, `autonomy_class` (`A_REPORT_ONLY`..`D_CONSEQUENTIAL`), `run_status` enum (`QUEUED`..`INCOMPLETE`), and `allowed_actions`/`denied_actions`. `docs/AGENT_OPERATING_SYSTEM.md` §3's "Completion result contract" independently covers the same ground for ordinary (non-Steward) session handoffs. No missing semantic found. |

---

## Part E — What this reconciliation actually builds

Per Part D, the only concretely missing mechanism from the directive's full list is
**D3 / Priority 8: `agent-evals/`.** This PR adds a bounded foundation:

- `agent-evals/README.md` — purpose, no-paid-inference-in-CI rule, how to add a case,
  how a harness change gets compared against a baseline.
- `agent-evals/schema/case.schema.json` — the JSON Schema one eval case must satisfy:
  `id`, `category` (drawn from the behaviors this directive and Priority 8 both name:
  `skill_selection`, `finish_line_persistence`, `owner_question_autonomy`,
  `proportional_verification`, `delegation_discipline`, `write_ownership`,
  `reviewer_independence`, `graph_failure_containment`, `stale_evidence_rejection`,
  `external_guidance_hygiene`, `cross_session_continuity`, `missing_never_zero`),
  `objective`, `setup`, `acceptance_criteria`, `forbidden_actions`, and a `grading`
  block naming which deterministic checks apply.
- `agent-evals/schema/run_artifact.schema.json` — the shape a captured agent
  run/transcript must have to be graded, deliberately reusing
  `config/steward/contracts.schema.json`'s `runReceipt` vocabulary (`status`,
  `actions[]`, repo-head SHAs) rather than inventing a second receipt shape.
- `agent-evals/cases/*.json` — an initial corpus built from **real, already-documented
  repository incidents** (not invented busywork), each naming its source record.
- `agent-evals/graders/deterministic.py` — a small, dependency-free grader that scores
  a submitted run artifact against a case's acceptance criteria using only static
  signals (changed-file scope, forbidden-path touches, required-string presence,
  declared-vs-actual `UNRESOLVED`/`STATUS`). It never calls a model and never makes a
  network request.
- `agent-evals/run_eval.py` — a CLI (`--list`, `--case <id> --artifact <path>`) that
  runs the deterministic grader. No model dispatch; capturing a real interactive run
  against a case is documented as a manual step, never invoked from CI.
- `tests/agent_evals/test_case_schema.py` and `test_deterministic_grader.py` — pytest
  coverage that runs in ordinary CI with zero API cost, proving the schema validates
  the shipped corpus and the grader actually discriminates pass from fail on
  synthetic fixtures.

This satisfies Priority 8's own definition of done ("create `agent-evals/` from
historical real repository tasks... grade with deterministic evidence where
possible... material Agent OS/skill/model-routing changes should eventually be
evaluated against this suite before becoming canonical") without fabricating live
paid-model execution in CI, and without creating a second harness/orchestration
system — it is a grading corpus that *consumes* the existing Agent OS/Steward
contracts, not a new one.

---

## Part F — Explicitly deferred work (named, not silently dropped)

| Item | Canonical owner | Why deferred | Dependency / authority | Smallest next action |
|---|---|---|---|---|
| Structured session/model/provider attribution on `src/steward/store.py` raw evidence records (D7's one real gap) | `src/steward/` (Steward store schema) | Small in isolation, but touches a just-merged (2026-09-10) transactional schema with its own compare-and-swap revision tests; bundling it into an unrelated external-guidance reconciliation raises regression risk for no urgent benefit | None blocking — genuinely dependency-ready | Add an optional structured `producer: {session_id, model, provider}` object to the evidence payload schema in a follow-up bounded PR, with a migration note for existing free-text `source` values; extend `tests/steward/test_store.py` accordingly |
| Reduced prescriptive scaffolding / loosened low-risk permission gates for GPT-6 Astra specifically (A.1 mechanism 3/5) | `.agents/skills/*/SKILL.md`, provider adapters | `repo-harness-auditor`'s existing "Model-migration hygiene" section already owns this exact audit, and PR #1344 is mid-flight on the same files | PR #1344 merging first | Re-run the model-migration hygiene checklist after #1344 merges, scoped to Astra-specific over-constraining language, if any remains |
| Wiring a real interactive/paid-model execution layer into `agent-evals/` (capturing live Claude/Codex runs against cases automatically) | `agent-evals/` | The directive explicitly forbids "automatic paid inference" and "unattended execution"; this pass only builds the deterministic-grading half | Owner authorization for any recurring paid-inference budget | When/if authorized, add an explicit, budgeted, manually-triggered capture script under `agent-evals/` that never runs from ordinary CI |
| Growing the `agent-evals/` corpus beyond its initial set | `agent-evals/` | Bounded-foundation sizing for this pass; a large corpus is better built incrementally against real incidents as they occur | None blocking | Add a case each time a genuinely novel harness-behavior failure is diagnosed and fixed (mirrors `docs/AGENT_OPERATING_SYSTEM.md` §7's learning-edge rule) |

---

## Part G — Explicitly rejected ideas (do not re-propose without new evidence)

Mapped directly to the directive's own "Things you must not implement" list, plus
specifics found in the source batch:

| Rejected idea | Where it appeared | Why rejected |
|---|---|---|
| A second Agent OS / competing orchestration document | general theme across the X batch's "harness engineering" framing | `docs/AGENT_OPERATING_SYSTEM.md` already exists, is mature, and is under active refinement (PR #1344); a second document would fragment authority |
| A second project-memory database / vector DB "for agent memory" | general theme; not concretely proposed by any of the 15 links but explicitly forbidden by the directive | `src/steward/` (SQLite, transactional, provenance-tracked) is the canonical local memory owner; a vector DB solves a retrieval-similarity problem this repo does not currently have |
| GitHub Spec Kit or any competing product-planning hierarchy | not found in any retrievable source content; directive names it defensively | `docs/MASTER_PRODUCT_PLAN.md` / `PRODUCT_PLAN.md` already own this |
| Persistent named "explorer/worker/researcher" agent personalities | owner's agent-tree screenshot (Part C) | `docs/AGENT_OPERATING_SYSTEM.md` §4 already states "Agent names do not create authority. A role exists only when the current execution plan/owner directive assigns it" |
| Hardcoding the screenshot's specific model roster (`gpt-6-astra-medium`, `luna-max`, `sol-high`, `astra-xhigh`) into `config/steward/routing.json` | owner's agent-tree screenshot (Part C) | Routing must stay capability/risk/cost-based and provider-agnostic (`docs/agent-operating-system/STEWARD_RUNTIME.md` — "remain unconfigured rather than pretending availability"); a screenshot is a snapshot of one day's available models, not a durable policy |
| Treating "85% of Google engineers run agentic loops and graphs" (virgilxbt's adjacent post, unverified even as to being the supplied URL's content) as engineering fact | Part B row 5 | Unsupported, unverifiable adoption statistic from a secondhand repost; `docs/AGENT_OPERATING_SYSTEM.md` §14 requires independent verification before treating such claims as evidence |
| An unattended, self-modifying harness that promotes its own changes | akshay_pachaar's "self-repairing harness" thesis (Part B row 8) taken to its logical extreme | `docs/AGENT_OPERATING_SYSTEM.md` §6's Activation Gate and §14's flywheel both require eval-gated, human/integration-approved promotion; "evaluation is not activation" is stated explicitly and is not relaxed here |
| Automatic paid inference in CI for `agent-evals/` | Priority 8 / this reconciliation's own D3 build | Explicitly forbidden by the directive and by `docs/AGENT_OPERATING_SYSTEM.md` §6 ("Do not fabricate live paid-model execution in CI"); the grader is deterministic-only |
| A whole-repo rewrite of `CLAUDE.md` for stylistic cleanliness | directive's own "must not implement" #20, and a real temptation given the file's size (145 KB / 2,485 lines) | `CLAUDE.md`'s own pruning constraint (its "CLAUDE.md pruning constraint" section) and `docs/AGENT_OPERATING_SYSTEM.md` §12 both require reference-aware, evidence-based pruning by `repo-harness-auditor` — which is exactly what PR #1344 is doing; a second, uncoordinated rewrite here would collide with it |

---

## Cross-references

- Owner intake pointer: `docs/OWNER_REQUESTED_TODO.md` (row added under "Recovered
  durable owner requirements," 2026-09-12).
- Engineering-reliability roadmap: `docs/engineering/ENGINEERING_RELIABILITY_PRIORITIES_2026-09-06.md`
  Priority 8 (updated with a pointer to `agent-evals/`, not rewritten).
- In-flight, complementary work not duplicated here: PR #1344 (progressive
  disclosure), PR #1339 (merged — owner-intake mechanism), PR #1333 (merged —
  Steward foundation).
- Eval foundation built by this reconciliation: `agent-evals/README.md`.
