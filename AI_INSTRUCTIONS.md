# Universal AI Instructions — Risk It To Get The Brisket

**This is the model-neutral entrypoint for every LLM/agent working in this repository.**

Astra, Claude, Codex, Gemini, Grok, ChatGPT, Copilot, and any future coding agent must use the same repository-owned operating rules. Provider-specific files are adapters only and may not contain unique product, engineering, safety, or verification rules.

## Read what the task needs

For material work, read the core `docs/AGENT_OPERATING_SYSTEM.md` and current authorization in `docs/EXECUTION_PLAN.md`. Before editing, check `docs/WORK_CLAIMS.md`, overlapping open PRs and the relevant branch rules in `ASSISTANT_COORDINATION.md`.

- Use the active owner-authorized completion contract when selecting campaign work or changing its covered scope.
- Use relevant sections of `CLAUDE.md`, the legacy-named universal technical runbook for every model, and trace the affected live code. Do not preload the full runbook for every edit.
- For engineering-system improvements or a material new-feature applicability pass, use relevant sections of `docs/engineering/ENGINEERING_RELIABILITY_PRIORITIES_2026-09-06.md`.
- **Only for unattended/recurrent site-steward design or operation**, read `docs/AUTONOMOUS_SITE_STEWARD_VISION.md`. Do not preload that long-term vision into ordinary feature sessions.
- Load graph, runtime-control and runner references only when their Agent OS router applies. A typo or narrow documentation correction needs the applicable instructions and affected references, not every planning document.

## Durable owner-intake capture rule

Record definite durable owner work in `docs/OWNER_REQUESTED_TODO.md`, directly or through a pointer to its detailed contract. Preserve ambiguous ideas for review and later supersession without turning them into binding scope. Claim “saved” only after verifying that repository record; chat, memory or an unlinked issue is insufficient. Capture is not implementation authorization: `docs/EXECUTION_PLAN.md` owns current scope. Background: `docs/OWNER_TODO_RECOVERY_AUDIT_2026-09-10.md` and issue #1336.

## Material new-feature engineering applicability check

For material new features or major behavior changes, use the Agent OS section of this name. It owns the `APPLY_NOW`, `ALREADY_COVERED`, `NOT_RELEVANT` and `DEFERRED_BY_AUTHORITY` dispositions; this relevance pass does not expand scope.

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


Carry `Agent-OS-Receipt: <AGENT_OS_LOADED_BLOB_SHA>` into material checkpoints, work-claim/PR handoffs and the final handoff as specified in the Agent OS.

Startup is read-only routing, receipt and Git state. Use `bash scripts/agent_session_start.sh --diagnostics` when investigating the Python environment or source freshness; it runs the optional test collection, freshness and syntax probes. Required task/CI checks remain separate.

## Python formatting contract

After Python changes and before committing or pushing, run `bash scripts/format_python_changes.sh`. It uses the Ruff version pinned in `requirements-dev.txt` and rules in `pyproject.toml`, then the repo-wide CI format/lint gates. Keep formatter output; do not imitate Ruff manually. If shell execution is unavailable, use those files and CI results as authority.

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