# Agent Harness Design Rationale — 2026-09-05

This file records **why** `docs/AGENT_OPERATING_SYSTEM.md` exists and what was intentionally changed or deferred.

It is rationale/provenance, not an authority source. If this file conflicts with the operating system or product records, it loses.

## Inputs distilled

### Charlie Hills — Claude Code operating-system pattern

Useful principles adopted:

- Treat Claude Code as a persistent operating environment, not a disposable chat.
- Keep the always-loaded front door small; route detail to project-specific references and skills.
- Turn repeated successful workflows into skills rather than repeatedly prompting them.
- Make truly mandatory deterministic behavior a hook/script/test rather than trusting prose recall.
- Use planning/discovery before committing to a wrong implementation path.
- Persist useful session decisions/progress in files so new sessions do not rediscover them.
- Avoid skill bloat; one skill should do one recognizable job.
- Add explicit close/save-progress behavior so unfinished work and durable learnings are not lost.

Source post supplied by the owner:
`https://x.com/charliejhills/status/2091484130290888729`

### Hanako — loops inside graphs

Useful principles adopted:

- A bounded work unit should iterate until its acceptance criterion passes or reaches a genuine blocker.
- The larger program should be modeled as a graph of dependencies and parallelizable units.
- A failed unit should be routed backward for correction without discarding accepted sibling work.
- Distinguish:
  - **correction edge** — repair this run;
  - **learning edge** — persist the lesson so the next run does not repeat the same error.
- Deterministic combination/validation belongs in code, not model judgment.
- Human approval belongs near consequential/irreversible boundaries rather than every intermediate step.

### Codez — agent team rather than parallel tabs

Useful principles adopted:

- Parallel agents are not an organization if the human must manually shuttle all context between them.
- Give each agent a role/domain and explicit ownership boundary.
- Durable tasks/claims/PRs should carry state between agents.
- Handoffs should be structured.
- Review should be independent from authorship when the risk justifies it.
- Shared durable history is what lets one agent's learning benefit the next.

### Eric Provencher — audit old prompts for stronger models

Useful principles adopted:

- Instructions written to compensate for weaker models can become harmful when a newer model follows them more literally.
- Contradictory instructions become more expensive, not less.
- Skill descriptions themselves consume routing attention; overlapping or over-eager descriptions should be pruned.
- Do not automatically add more “MUST/CRITICAL/always verify again” wording when current models already perform the behavior.
- Preserve actual domain invariants while deleting model-babysitting workarounds.

The current Anthropic prompting guidance independently supports the same direction:
- explicit, direct instructions;
- proactive action only when that is actually desired;
- investigate relevant code before making claims;
- use parallel tool calls for independent reads/actions;
- preserve external state for long-horizon workflows;
- balance reversible autonomy with confirmation at consequential boundaries;
- remove older prompting patterns that cause over-triggering or over-verification on newer models.

### zodchiii — Fable 5.1 migration / harness guidance

Owner-supplied source:
`https://x.com/zodchiii/status/2095806517500932190`

The X body was not reliably retrievable through the automated client, so this pass does **not** quote or treat a mirror as authoritative. The useful migration themes were cross-checked against Anthropic's current model prompting guidance and its open-source `prompt-audit` skill before adoption.

New principles adopted:

- loops need bounded retry/action budgets and explicit exit conditions, not just acceptance criteria;
- debugging should reproduce first, trace the first broken invariant, separate evidence from root-cause conclusion, and fix the canonical cause rather than the downstream symptom;
- model/reasoning effort should be routed to the task instead of defaulting every unit to the most expensive tier;
- independent tool reads/actions should be batched or parallelized while genuine dependencies remain serialized;
- prefer targeted edits over gratuitous whole-file rewrites;
- model upgrades should trigger a migration audit of prompts/skills/tool settings, followed by representative-task revalidation and rollback capability;
- where a harness directly manages model conversation history and the model binds reasoning to prior prefixes, accepted history should be treated append-only rather than rewritten in place.

Deliberately **not** adopted into always-loaded rules:

- Fable-5.1-only API syntax, pricing, or fixed effort constants that will churn;
- blanket model-specific instructions when Claude Code/runtime already owns the behavior;
- forced use of `/claude-api prompt-audit` when that command is unavailable;
- any instruction to weaken existing repo verification or canonical-owner invariants in the name of prompt simplification.

### Anatoli Kopadze — graph engineering

Owner-supplied source:
`https://x.com/anatolikopadze/status/2080668775796314331`

Useful principles adopted:

- a graph node needs a real contract: bounded job, explicit input, structured output;
- remove "fake edges" when one step does not actually consume another's result;
- use the diamond for wide work: fan out, deterministic reduce, independent verify, synthesize;
- verifier context should be independent from worker context;
- audit hidden dependencies caused by shared files/workspaces/state, credentials, or rate-limited APIs;
- every fan-in should compare received results with expected results so silent node failures cannot masquerade as completeness;
- use layered fan-in when raw parallel output would overflow synthesis context;
- topology is not truth: ground the graph in immovable external anchors such as executed tests, production observations, authoritative data, or frozen owner rules;
- graphs are inappropriate for small, exploratory, or genuinely sequential work;
- start with bounded width/cost and expand only after a scoped run earns it.

These extend the existing "loops inside graphs" rule without adding a new overlapping skill.

### Mr. Buzzoni / PolyDAO — Loop Rat autonomous-runner pattern

Owner-supplied source:
`https://x.com/polydao/status/2096128417108287566`

The publicly mirrored post describes an autonomous repo loop with a committed contract, local overrides, spend caps/timeouts/denylist, schedule, independent rubrics/grading, append-only receipts and action trace, resumable checkpoint, budget ledger, and an external halt file. It also separates the scheduler/engine from the model call itself: the model does not decide when it wakes. citeturn305770search2turn305770search5

Useful principles adopted:

- unattended autonomy needs an execution contract, not just a prompt;
- separate committed policy from local operator overrides, and never allow local overrides to weaken the committed safety boundary;
- enforce spend/time/action/retry/parallelism limits outside model prose;
- centralize repo-owned model calls behind one auditable gateway;
- externalize resumable state with checkpoints plus append-only run receipts/traces;
- make verification executable and keep grading independent from authorship;
- require a simple external kill/halt sentinel for unattended schedulers;
- distinguish report-only, assisted, and autonomous modes;
- treat deployment of unattended loops as a separate owner-authorized activation decision.

Deliberately not adopted as automatic behavior:

- no new night-shift scheduler is activated by this documentation change;
- no fixed dollar budget or cadence from the example is copied into this repo;
- no new model/provider choice is hard-coded;
- no autonomous loop may bypass existing claims, exact-head CI, protected PR, deploy, auth, or completion-contract gates.

## What the repo already had

The audit found that this repository was **not** starting from zero.

Existing harness pieces on `main`:

- `CLAUDE.md` — detailed technical/runbook + invariants;
- `AGENTS.md` — compact repo instructions;
- `ASSISTANT_COORDINATION.md` — branch/integration coordination authority;
- `docs/WORK_CLAIMS.md` — durable collision avoidance;
- `.claude/settings.json` — SessionStart hook wiring;
- `.claude/health-check.sh` — session-start test/freshness/git health;
- `.agents/skills/`:
  - blueprint-auditor
  - design-taste-director
  - performance-optimizer
  - reality-check-review
  - scraper-ops
  - value-pipeline-auditor
- `docs/claude-dispatch/` — historical/derived dispatch records.

That means the correct repair was **reconciliation and routing**, not another parallel orchestration framework.

## Measured problems

### 1. The continuation prompt had become a second operating system

The owner repeatedly had to tell sessions to:

- use live GitHub;
- read the same completion contract;
- count only literal VERIFIED;
- distinguish implemented/merged/deployed/verified;
- preserve canonical-owner/missing/stale/privacy invariants;
- inspect exact-head CI;
- merge bounded eligible PRs;
- continue independent work around blockers;
- stop V1 from reopening.

Those are mostly process rules. Re-pasting them every hour is evidence they belong in the repo/harness.

### 2. CLAUDE.md is very large

At the time of this pass, `CLAUDE.md` was approximately **142 KB**.

The ideal front-door pattern would be a much smaller router. However, this repo has substantial historical coupling:

- code comments cite `CLAUDE.md` rules;
- tests describe invariants by reference to it;
- audit evidence cites named sections;
- architecture/product docs refer to its detailed pipeline claims.

A blind split during the Week 1 launch would create a large documentation/reference blast radius.

Decision:
- **do not** destructively shrink it in this pass;
- put a small operating layer in front of it;
- add a dedicated `repo-harness-auditor` skill for a later compatibility-safe pruning migration.

### 3. Skills existed but no launch-specific traffic-control skill existed

The six existing skills are reasonably domain-specific. None owns:

- a fixed-denominator completion contract;
- exact-head integration;
- deploy/prod evidence harvesting;
- literal VERIFIED counting;
- stop-on-completion behavior.

That repeated workflow warranted one new specialist skill.

### 4. The SessionStart hook checked health but did not route work

The repo already paid the startup-hook cost, but it did not tell Claude:

- which operating-system file to read;
- whether a fixed-denominator launch contract is active;
- its mechanical current tally;
- which rows are BLOCKED / IN PROGRESS;
- that V1 must stay closed.

The existing hook is therefore extended rather than adding a second hook pipeline.

## Architecture chosen

### Front door

`docs/AGENT_OPERATING_SYSTEM.md`

Small enough to read at session start, explicit that it has **zero product authority**.

### Technical detail

`CLAUDE.md`

Remains the detailed runbook until a dedicated pruning pass can preserve/update its semantic references safely.

### Branch/integration mechanics

`ASSISTANT_COORDINATION.md`

Remains authoritative. The new operating system points to it instead of copying it.

### Product authorization

Unchanged:
- `PRODUCT_PLAN.md`
- `docs/MASTER_PRODUCT_PLAN.md`
- `docs/EXECUTION_PLAN.md`
- active owner-authorized completion contract

### Work collision state

Unchanged:
- `docs/WORK_CLAIMS.md`

### Deterministic startup routing

Existing:
- `.claude/settings.json` -> SessionStart -> `.claude/health-check.sh`

Extended:
- the health check prints the agent router and active Week 1 contract state.

### Specialist workflows

Existing six skills retained.

Added:
- `season-launch-traffic-control`
- `repo-harness-auditor`

No generic “super agent” skill was added.

## What should disappear from future giant prompts

Once this PR is on `main`, ordinary continuation prompts should **not** need to restate:

- the authority hierarchy;
- ONE CONCEPT / ONE CANONICAL OWNER;
- missing != zero;
- stale != current;
- implementation/merge/deploy/verify distinctions;
- check work claims/open PRs;
- exact-head integration policy;
- fixed-denominator counting mechanics;
- continue dependency-ready work around a blocked node;
- reviewer independence;
- correction-edge/learning-edge policy;
- durable handoff fields;
- “do not reopen V1” while the launch router says it.

Prompts should primarily contain **new owner intent or a new methodology/product decision**.

If a prompt is becoming long because it re-explains process, that is a harness defect.

## What must NOT disappear

Do not prune genuine domain truth merely because a model is smarter:

- missing is not zero;
- stale is not current;
- factual scoring identity controls compatibility;
- best-ball uses the canonical optimal-lineup behavior;
- public/private is a semantic boundary;
- canonical values/lineups/identity have one owner;
- correlated evidence is not independent evidence;
- evaluation is not activation;
- recommendations are not execution;
- provenance matters;
- unknown/unverified states fail closed where the product requires them.

## Learning-edge rule going forward

When a session says some variant of “I keep having to tell Claude X”:

1. determine whether X is a domain truth, deterministic check, specialist workflow, or transient preference;
2. put it in **one** canonical place;
3. if deterministic, prefer a test/hook/script;
4. if a repeated reasoning workflow, prefer a small skill;
5. remove duplicate copies when safe.

The objective is a harness that gets **smaller and more reliable** as the repo matures.
