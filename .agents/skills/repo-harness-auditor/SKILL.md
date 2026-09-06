---
name: repo-harness-auditor
description: Use when auditing or refactoring this repository's AI harness: CLAUDE.md, AGENTS.md, assistant coordination, agent skills, Claude hooks, repeated continuation prompts, contradictory instructions, model-migration prompt debt, or duplicated agent workflow rules. Do not use for product feature implementation.
---

# Repo Harness Auditor

## Objective

Make the AI-development harness smaller, clearer, more deterministic, and less contradictory without weakening real product/system invariants.

## Read first

1. `docs/AGENT_OPERATING_SYSTEM.md`
2. `CLAUDE.md`
3. `AGENTS.md`
4. `ASSISTANT_COORDINATION.md`
5. `.claude/settings.json` and referenced hook scripts
6. `.agents/skills/*/SKILL.md`
7. `docs/WORK_CLAIMS.md`
8. tests/docs or code references that pin the files being changed

## Classification pass

Classify each instruction under review as:

- **domain truth** — keep;
- **authority/risk boundary** — keep once in the canonical place;
- **deterministic check** — prefer test/hook/script;
- **specialist workflow** — prefer one narrow skill;
- **historical model workaround** — remove if no longer justified;
- **duplicate** — replace with a pointer;
- **contradictory/stale** — repair;
- **session-specific state** — move out of always-loaded instructions.

## Skill hygiene

For every skill:

- verify one clear trigger domain;
- verify explicit non-goals;
- look for overlap with sibling skills;
- shorten descriptions that aggressively compete for unrelated tasks;
- remove dead skills that never own a real workflow;
- do not create a skill for a one-off task.

Prefer fewer sharper skills over a large overlapping catalog.

## Hook hygiene

Use hooks for deterministic work that truly must happen at the relevant lifecycle event.

A hook should:

- be fast;
- fail/degrade truthfully;
- avoid network dependence at session startup unless explicitly intended;
- not manufacture freshness from filesystem metadata;
- not duplicate a CI job merely for ritual;
- print actionable routing/state rather than long prose.

Before adding a hook, ask whether a test, skill, or ordinary code path is a better owner.

## Prompt-debt audit

Search for recurring owner/agent prompts that repeatedly restate the same process.

For each repeated instruction, determine whether it should become:

- operating-system rule;
- specialist skill;
- deterministic test/hook;
- canonical contract field;
- one durable owner decision;
- nothing (obsolete prompting debt).

The goal is to make future prompts mostly contain **new intent**, not the entire operating history.

## CLAUDE.md pruning procedure

`CLAUDE.md` is heavily cross-referenced. Do not shrink it by blind extraction.

Before moving a section:

1. search repo-wide references to the section/claim;
2. identify tests/docs/comments that depend on its location or semantics;
3. find whether a more canonical record already owns the content;
4. move only redundant detail;
5. leave a stable pointer/anchor when references reasonably depend on it, or update all references in the same bounded PR;
6. run coordination/docs/invariant tests;
7. confirm the resulting always-loaded front door is materially smaller.

Do not trade token savings for governance drift.

## Graph-orchestration hygiene

When the harness or a workflow uses parallel agents, audit the topology rather than assuming "parallel" means efficient or safe:

- every node has a bounded input/output contract;
- every edge passes a real dependency or protects a shared mutable/rate-limited resource;
- fake edges are removed;
- hidden edges (same file, worktree, state store, credential/session, API budget) are made explicit or isolated;
- verifier nodes use fresh context and can reject the worker;
- deterministic reduce steps use code rather than model judgment where practical;
- fan-in counts expected vs received inputs and reports partial coverage truthfully;
- large fan-in is layered to avoid context collapse while retaining provenance;
- the graph terminates in external anchors, not agent self-consistency;
- fan-out/agent/cost budgets and stop conditions are bounded;
- the task is actually wide enough to justify a graph.

## Autonomous-runner hygiene

When reviewing any unattended/recurrent agent runner, verify:

- committed contract and gitignored local overrides are separated;
- local overrides can tighten but cannot weaken committed safety boundaries;
- wall-clock, action/iteration, retry, parallel-width, and spend/token budgets are enforced outside prompt prose;
- destructive/out-of-scope actions have an explicit denylist or allowlist boundary;
- repo-owned model invocation has one auditable gateway rather than scattered hidden call sites;
- per-run receipts and traces are append-only;
- checkpoints contain enough state to resume but still force fresh preflight against current repo/PR/CI state;
- verification is executable where possible and independent grading is separate from authorship;
- a fail-closed external halt sentinel is checked before start and before consequential side effects;
- report-only, assisted, and autonomous modes are explicit rather than inferred;
- scheduled autonomy has an owner-approved activation decision and rollback path.

Do not deploy a new unattended runner merely because the harness audit describes how one should be governed.

## Model-migration hygiene

When Claude/Codex model behavior changes materially, treat the harness like code that is being migrated.

### Migration checklist

1. Freeze a small representative baseline task set and record current quality/cost/latency observations where measurable.
2. Audit prompts, skills, tool descriptions, hooks, and always-loaded instructions for old-model compensations.
3. When the current vendor supplies a prompt-migration audit (for example, Anthropic's `/claude-api prompt-audit` when available), run it as **evidence, not authority**; review every proposed deletion against repo domain invariants.
4. Re-sweep model/effort routing instead of assuming the previous "best" tier remains optimal.
5. Check model/API compatibility changes that can break the harness: unsupported forced-tool settings, prefill/format hacks, thinking/history behavior, and deprecated configuration.
6. If the harness directly manages conversation history for a model with prefix-bound thinking, treat accepted history as append-only; prefer a new turn or turn-scoped reminder over editing earlier accepted content.
7. Rerun the baseline and inspect quality, silent failure modes, cost, and latency before declaring the migration better.
8. Keep a rollback path until the new harness is proven.

Also:
- audit old anti-undertrigger instructions;
- audit repeated “MUST/CRITICAL/always verify again” wording;
- test whether those instructions now cause over-triggering/over-verification;
- preserve actual domain truths;
- prefer normal direct language where stronger models already comply;
- re-check skill routing overlap;
- audit verification rituals and reasoning scaffolds that duplicate capabilities the current model/runtime already provides.

Do not assume a prompt that helped the previous model is neutral on the new one.

## Learning-edge review

Review recent incidents/repeated corrections.

For each, ask:

- Was the current run corrected?
- Was the lesson persisted?
- Is the persistence in the correct canonical place?
- Could a deterministic test/hook prevent recurrence?

If the same issue was rediscovered twice, treat that as evidence the learning edge is missing.

## Deliverable

Report:

1. harness map;
2. duplicated/contradictory/stale instructions;
3. skill overlap/dead-weight findings;
4. hook opportunities and hooks that should not exist;
5. safe pruning changes;
6. tests/evidence;
7. estimated reduction in repeated prompt/context burden;
8. remaining risky migration items.

Never change product methodology, values, scoring, auth, or feature scope under the banner of “prompt cleanup.”
