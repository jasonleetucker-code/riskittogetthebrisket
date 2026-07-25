# Assistant Coordination

## Active Working Copy

Use this folder for all Claude, ChatGPT/Codex, and local development:

```text
C:\Users\jason\code\riskittogetthebrisket
```

Do not edit OneDrive repo copies unless Jason explicitly asks. Treat them as backups or archives only.

## Start Every Session

```powershell
git pull --ff-only origin main
git status --short --branch
```

If the branch is not clean, inspect the existing changes before doing new work.

## Branch Rules

- Codex work goes on `codex/<task-name>`.
- Claude work goes on `claude/<task-name>`.
- Do not let multiple assistants edit the same branch at the same time.
- Push branches early so the other assistant can inspect or build on the work.
- Merge one task at a time back to `main`.

## Required Handoff

Every assistant should report:

- Exact files touched.
- Exact live code path affected.
- Tests or validation commands run.
- Anything mocked, partial, stale, bypassed, dead, duplicated, or still uncertain.

## Repo-Specific Caution

For rankings, values, scraper, ingestion, or frontend data changes, trace the full path before claiming completion:

```text
ingestion -> normalization -> merge/fallback -> API contract -> frontend consumption
```
