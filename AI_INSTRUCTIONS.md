# Universal AI Instructions — Risk It To Get The Brisket

**This is the model-neutral entrypoint for every LLM/agent working in this repository.**

Astra, Claude, Codex, Gemini, Grok, ChatGPT, Copilot, and any future coding agent must use the same repository-owned operating rules. Provider-specific files are adapters only and may not contain unique product, engineering, safety, or verification rules.

**Permanent cross-model process (owner 2026-10-19):** follow
`docs/AGENT_OPERATING_SYSTEM.md` §3 and `ASSISTANT_COORDINATION.md`
for parallel isolated authorized feature implementation, mandatory L0/L1
during coding, required L2/L3 at integration/release, and Integration-led
merges of qualifying green reviewed routine PRs without repeated owner
approval. Owner-only consequential gates are unchanged.

## Read order for material work

1. `docs/AGENT_OPERATING_SYSTEM.md` — model-neutral agent workflow, evidence, graph, review, handoff, and autonomy rules.
2. `docs/EXECUTION_PLAN.md` — current implementation authorization and lane ownership.
3. Any active owner-authorized completion contract.
4. `docs/WORK_CLAIMS.md` plus live open PRs/branches before overlapping edits.
5. `ASSISTANT_COORDINATION.md` — branch/integration mechanics.
6. `CLAUDE.md` — **legacy filename, universal technical runbook for every model**. Its filename is historical; its technical invariants and architecture guidance are not Claude-only.
7. Relevant architecture/ADR/domain docs and live code.
8. For engineering-system improvements, read `docs/engineering/ENGINEERING_RELIABILITY_PRIORITIES_2026-09-06.md`.
9. **Only for unattended/recurrent site-steward design or operation**, read `docs/AUTONOMOUS_SITE_STEWARD_VISION.md`. Do not preload that long-term vision into ordinary feature sessions.

## Three-month owner conversation-detail audit — 2026-10-30

**Mandatory pre-implementation lookup when an idea may derive from July 30–October 30 discussions:** `docs/MASTER_PRODUCT_PLAN.md` §13 → `docs/owner/CHASE_UPSIDE_90_DAY_CONVERSATION_AUDIT_2026-10-30.md` → original historical records: `docs/OWNER_TODO_RECOVERY_AUDIT_2026-09-10.md` R-01…72, `docs/owner/RIT_14DAY_AUDIT_RECONCILIATION_2026-10-25.md` RIT-001…088, dated owner directives and `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` §23. **Never assume a chat-derived promise or an unmerged PR has been integrated into main**. Specifically, the unmerged #1755's 100-mechanism/44-candidate League Tycoon research was rescued to `docs/owner/LEAGUE_TYCOON_DEFERRED_IDEAS_PRESERVED_2026-10-16.md`; it remains PARKED and old #1755 heading collisions must be reconciled before merge. The three-month search has **no exhaustive raw-chat export**; all unobserved original messages remain `RAW_CHAT_NOT_RETRIEVED`, not “nothing else existed.” Owner intake = 3MA-1…6; `docs/EXECUTION_PLAN.md` controls what may actually be built.

## Owner product specificity / multi-agent coordination — 2026-10-30

When the owner gives one or many product ideas, **do not mistake a one-line umbrella name for a complete specification**. Alongside the existing owner-intake ledger, follow `docs/BRISKET_IDEAS.md` §§15–16 (mandatory `SPEC_READY` fields, zero-loss source gaps, and coordinated parallel lanes), `docs/MASTER_PRODUCT_PLAN.md` §12 (shared dependency graph and dated initiative routing), and `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` §§21–22 (exact user-facing input/output/test contracts and Oct 9–30 reconciliation). Reuse the RIT-001…088 audit and subsequent dated directive IDs instead of creating redundant features. Keep uncertain ideas labeled uncertain and active claims respected. This documentation rule is NOT permission to implement ideas outside `docs/EXECUTION_PLAN.md`.

## Durable owner-intake capture rule

When the owner says anything that a reasonable product/engineering lead would interpret as **durable future work**, do not leave that intent only in chat. This includes informal wording such as “add this,” “we need to fix/change this,” “make this better,” “remember/revisit this,” “do this later,” “put this on the list,” and equivalent statements that create, refine, pause, reject, or supersede product/process work.

1. Determine whether the statement is a **definite/high-confidence durable owner instruction** or only ambiguous brainstorming.
2. For definite/high-confidence durable work, ensure it is represented in the live owner-intake ledger, `docs/OWNER_REQUESTED_TODO.md`, either directly or through an explicit compact incorporation pointer to the detailed issue/spec/addendum that carries the long-form contract.
3. If the statement is genuinely ambiguous, preserve it for owner review without silently promoting it into binding scope.
4. Do **not** say “added,” “saved,” “on the TODO,” or equivalent unless the durable repository intake was actually updated or an existing canonical intake entry was verified.
5. A GitHub issue, planning document, assistant memory, or chat response by itself is **not** a substitute when the live owner-intake ledger does not point to the durable requirement.
6. Preserve supersession: later explicit owner instructions win; older formulations remain traceable but must not survive as conflicting active requirements.
7. **Capture is not implementation authorization.** `docs/EXECUTION_PLAN.md` remains the sole current implementation-authorization record; an intake update must not interrupt active engineering merely because a new request was captured.
8. Astra/Steward campaign planning must be able to consume the live owner intake plus current GitHub/planning/execution evidence without needing access to the owner's chat history. The intended path is: `owner statement -> owner intake -> detailed issue/spec if needed -> canonical mapping -> execution plan when authorized -> Astra reconciliation`.

The historical recovery and rationale for this rule are tracked in `docs/OWNER_TODO_RECOVERY_AUDIT_2026-09-10.md` and issue #1336.

## Material new-feature engineering applicability check

Before implementing any **material new feature or major behavior change**, perform the shared engineering-priorities applicability check in `docs/AGENT_OPERATING_SYSTEM.md` against `docs/engineering/ENGINEERING_RELIABILITY_PRIORITIES_2026-09-06.md`.

This is a lightweight relevance pass, not permission to expand scope or implement all twelve priorities. Classify only the mechanisms that could materially affect the feature as `APPLY_NOW`, `ALREADY_COVERED`, `NOT_RELEVANT`, or `DEFERRED_BY_AUTHORITY`. Relevant `APPLY_NOW` items belong in the bounded feature design/tests; deferred items must stay visible rather than being silently forgotten.

## Main-movement / CI restart rule

A new `main` SHA is not itself a CI failure. When `main` advances while a PR is
validating, every model must use the canonical triage in
`ASSISTANT_COORDINATION.md` → **Benign automated `main` movement: classify before
restarting CI**. Reuse an existing implementation-head result when the intervening
change is proven `BENIGN_AUTOMATION_MOVE`; reconcile/revalidate when it is
`RELEVANT_BASE_MOVE`. Do not infer benignity merely from a bot/automation author,
and do not restart the whole feature-development cycle merely because scheduled
repository automation changed an unrelated file.

## Universal startup

For a material local agent session, run:

`bash scripts/agent_session_start.sh`

Claude Code runs this through its existing SessionStart adapter. Other agents should run the same shared script when their runtime permits shell execution. If not, reproduce its read-only checks directly and run `python scripts/agent_os_receipt.py` for the Agent OS receipt.


## Python formatting contract

Do not hand-format Python to imitate Ruff from memory.

The repository owns one deterministic formatter contract:

`bash scripts/format_python_changes.sh`

Run it after changing Python and before committing or pushing. The script:

- requires the exact Ruff version pinned in `requirements-dev.txt`;
- reads `pyproject.toml` for the canonical formatting rules;
- formats the changed Python files;
- then runs the same repo-wide `ruff format --check .` and `ruff check .` gates CI uses.

If the script changes a file, keep the formatter output. Do not manually re-wrap it based on aesthetics, guessed line length, or another formatter's conventions.

If the runtime cannot execute shell commands, inspect `pyproject.toml` and `requirements-dev.txt`, and treat CI/Ruff output as authoritative rather than guessing formatting.

Carry:

`Agent-OS-Receipt: <AGENT_OS_LOADED_BLOB_SHA>`

into the first material checkpoint, material work-claim/PR handoff, and final handoff.

## Provider adapters

- `CLAUDE.md` / `.claude/` — Claude compatibility/autostart surface.
- `AGENTS.md` — Codex and other AGENTS-aware tools.
- `GEMINI.md` — Gemini adapter.
- `.github/copilot-instructions.md` — GitHub Copilot adapter.

**Adapters may add only provider-mechanical instructions** needed to load or invoke the shared system. If a rule affects correctness, architecture, safety, evidence, product behavior, or engineering process, put it in a model-neutral canonical document instead.

## No private instruction forks

If a provider-specific file contains a useful rule that another model would not receive:

1. move/copy the rule into the correct shared canonical document;
2. replace the provider-specific wording with a pointer or provider-only invocation detail;
3. add/adjust a parity test if the rule is important enough to regress.

Do not make the human owner remember which model knows which rule.

## Product authority

This file and the Agent OS govern **how agents work**. They do not authorize product scope or methodology. Product/implementation authority remains with the existing owner/product hierarchy and current execution plan/contracts.