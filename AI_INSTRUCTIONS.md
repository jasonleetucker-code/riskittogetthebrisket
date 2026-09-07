# Universal AI Instructions — Risk It To Get The Brisket

**This is the model-neutral entrypoint for every LLM/agent working in this repository.**

Claude, Codex, Gemini, ChatGPT, Copilot, and any future coding agent must use the same repository-owned operating rules. Provider-specific files are adapters only and may not contain unique product, engineering, safety, or verification rules.

## Read order for material work

1. `docs/AGENT_OPERATING_SYSTEM.md` — model-neutral agent workflow, evidence, graph, review, handoff, and autonomy rules.
2. `docs/EXECUTION_PLAN.md` — current implementation authorization and lane ownership.
3. Any active owner-authorized completion contract.
4. `docs/WORK_CLAIMS.md` plus live open PRs/branches before overlapping edits.
5. `ASSISTANT_COORDINATION.md` — branch/integration mechanics.
6. `CLAUDE.md` — **legacy filename, universal technical runbook for every model**. Its filename is historical; its technical invariants and architecture guidance are not Claude-only.
7. Relevant architecture/ADR/domain docs and live code.
8. For engineering-system improvements, read `docs/engineering/ENGINEERING_RELIABILITY_PRIORITIES_2026-09-06.md`.

## Universal startup

For a material local agent session, run:

`bash scripts/agent_session_start.sh`

Claude Code runs this through its existing SessionStart adapter. Other agents should run the same shared script when their runtime permits shell execution. If not, reproduce its read-only checks directly and run `python scripts/agent_os_receipt.py` for the Agent OS receipt.

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
