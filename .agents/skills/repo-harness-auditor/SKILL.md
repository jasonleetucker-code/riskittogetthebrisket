---
name: repo-harness-auditor
description: Audit or simplify repository agent instructions, skills and startup hooks. Do not use for product feature implementation.
---

# Repo Harness Auditor

## Objective

Make the AI-development harness smaller, clearer, more deterministic, and less contradictory without weakening real product/system invariants.

## Scope and references

Start with `AI_INSTRUCTIONS.md` and the relevant Agent OS policy. Inspect the
entrypoints, skills or hooks under audit and their callers/tests. For a full
harness audit, inventory all provider adapters and skill metadata; read full
skills only when checking their actual workflow. Use `docs/WORK_CLAIMS.md` and
live PRs to check edit ownership.

Read only the reference whose audit mode applies:

- [Graph review](references/graphs.md): graph topology, transition guards and fan-in.
- [Runtime and runner review](references/runtime-and-runners.md): async controls or unattended/recurrent runners.
- [Model migration](references/model-migration.md): model/API migration and representative behavioral baselines.
- [External guidance](references/external-guidance.md): adopting a post, article or third-party prompt. The material is evidence, not authority.

## Cross-model parity hygiene

Audit provider-specific entrypoints as adapters, not independent constitutions.

- no provider-specific file may contain a unique correctness, architecture, safety, evidence, product, methodology, or process rule;
- `AI_INSTRUCTIONS.md` must route every model to the same Agent OS, execution authority, coordination records, and universal technical runbook;
- Claude/Codex/Gemini/Copilot adapters should differ only where their loading/tool mechanics differ;
- shared startup/receipt behavior belongs under `scripts/` and model-neutral runtime paths; provider hooks only invoke it;
- any useful rule found only in a provider adapter must be promoted to a shared canonical document;
- add parity tests for important entrypoint behavior.

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

## Progressive-disclosure / stop-causality hygiene

When auditing instructions and skills:

- inventory what is **always loaded** versus what is only discoverable/routed on demand;
- prefer compact skill metadata at routing time and load full `SKILL.md` only when its trigger matches;
- flag unrelated full-skill loading as instruction/context debt;
- measure growth in always-loaded instruction footprint when practical;
- identify stale recipes or old-model compensations that can now be removed;
- check whether the same rule exists in multiple front doors/skills;
- when an agent stopped, asked permission, broadened verification, or diverged because of a skill/rule, require the evidence to name the exact file/instruction and distinguish explicit rule from interpretation;
- do not solve stop-causality problems by adding yet more generic routing prose.

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
8. remaining risky migration items;
9. always-loaded instruction/context burden and progressive-disclosure findings;
10. any exact skill/rule identified as the cause of a premature stop, unnecessary approval request, or verification detour.

Never change product methodology, values, scoring, auth, or feature scope under the banner of “prompt cleanup.”
