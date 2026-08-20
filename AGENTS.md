# Repo Instructions (Dynasty Trade Calculator)

## Scope
This repository powers dynasty fantasy football valuation, rankings, trade calculation, source ingestion, and scraper-backed data publishing.

## Working Copy Coordination
- Active working copy: `C:\Users\jason\code\riskittogetthebrisket`.
- GitHub `main` is the shared source of truth for Claude, ChatGPT/Codex, and local work.
- Before starting work, run `git pull --ff-only origin main` from the active working copy.
- Use a task branch for meaningful changes (`codex/...` for Codex, `claude/...` for Claude).
- Do not edit OneDrive repo copies unless the user explicitly asks; treat them as backups/archive only.
- Do not let multiple assistants edit the same branch at the same time.
- See `ASSISTANT_COORDINATION.md` for the shared start-of-session checklist and handoff rules.
- Main movement alone does **not** invalidate completed feature evidence. After a PR reaches `READY_FOR_INTEGRATION`, freeze implementation; Integration owns the planned freshness reconciliation, final shipping gate, and dependency-ordered merge. Do not make finished branches continually chase `main`. See `ASSISTANT_COORDINATION.md` → **Main-Movement and Integration Queue Policy**.

## Non-Negotiables
- Do not assume a feature works because a helper, component, or file exists.
- Trace the live execution path end to end before claiming anything is implemented.
- Prefer modifying existing architecture over introducing parallel systems.
- Preserve working behavior unless a verified flaw requires change.
- Verify downstream effects for any value/ranking change in UI rendering, sorting, filtering, exports, and league-specific transforms.
- Verify ingestion, normalization, merge logic, fallback behavior, and frontend consumption for any scraper/source change.
- Call out anything mocked, bypassed, stale, duplicated, half-wired, dead, or missing.

## Safety
- Do not exfiltrate private data.
- Do not run destructive commands without approval.
- Prefer reversible operations where possible.
- Be explicit before any action affecting production, deployment, credentials, or public output.

## Required Workflow
1. Read relevant files first.
2. Identify the real live path, not just helpers.
3. Make the smallest correct change set.
4. Run available validation commands/tests.
5. Report exactly what changed, what was verified, and what remains uncertain.

## Performance Rules
- Prioritize page-load speed and perceived responsiveness.
- Reduce blocking work on initial load.
- Eliminate duplicated calculations, repeated fetches, and oversized payloads.
- Prefer memoization, batching, precomputation, caching, and lazy loading where justified.
- Do not sacrifice correctness for speed.

## Output Rules
- Be direct.
- Name exact files touched.
- Name exact code paths affected.
- Distinguish verified facts from inferences.
- When auditing, label items as complete, partial, mocked, bypassed, stale, dead, or missing.
