# Assistant Coordination

**This file is the authority for day-to-day branch and merge practice.**
`docs/ORCHESTRATION.md` is the detail reference for file custodians, high-conflict
files and git mechanics — but its §2 integration policy **expired on 2026-08-01**
and is marked as historical there. If the two ever disagree about branching or
merging again, this file wins and the other one is stale.

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

**Then check whether someone else is already on it:**

```bash
python scripts/check_work_claims.py --files <paths you expect to change> --defect <ids>
```

This is not ceremony. On 2026-08-05 two sessions independently fixed the
SAME six defects in one window — the TEP default, the rank-space market gap,
the open redirect, FAAB budget mixing, ROS absence odds and the compact-view
weights — and nobody noticed until one branch had already merged. Roughly a
third of a session's output was discarded, and which version survived came
down to which branch was mergeable first rather than which was better.

The two rules above did not prevent it and could not have: they govern WHERE
your work goes, not what someone else is already doing. See
`docs/WORK_CLAIMS.md` for the full record and the claim format. Add your row
in your first commit; set it `done` in your last.

## Which lane am I, and what may I build?

`docs/EXECUTION_PLAN.md` §0 is the **only** record that answers that, and it is the only place
the lane map lives. As of 2026-08-20 it authorizes the POST-V1 C-Series mass-build campaign —
Claude 9-13 on isolated branches, **execution timing only**, with Claude 5 the sole integration
and merge authority. Do not infer authorization from this file, from a scope manifest, or from a
capability being approved in the long-term plan.

## Branch Rules

- Codex work goes on `codex/<task-name>`.
- Claude work goes on `claude/<task-name>`.
- Do not let multiple assistants edit the same branch at the same time.
- Push branches early so the other assistant can inspect or build on the work.
- Merge one task at a time back to `main`. Open the PR when the work is ready;
  do not hold it for a batch. (`docs/ORCHESTRATION.md` §2 says the opposite —
  that policy expired 2026-08-01. Measured: 37 merges landed on 2026-08-04
  alone, against the "~13 merges/day" it claimed to have retired.)

## Main-Movement and Integration Queue Policy

**Main movement alone does not invalidate completed feature evidence.** Once a
PR has proved its implementation and is ready for integration, the implementation
agent must stop chasing `main`. Freshness is an Integration responsibility.

Use these states explicitly:

- `FEATURE_GREEN`: the PR's implementation is complete and its feature-scoped
  validation is green on its own head.
- `READY_FOR_INTEGRATION`: feature evidence is complete; freeze implementation
  unless a real defect is found.
- `INTEGRATION_GREEN`: the PR has been reconciled with the current shipping tree
  and the required final shipping gate is green on that exact tree.

Rules:

1. **Do not refresh a completed PR merely because `main` moved.** A new base SHA
   is not, by itself, a reason to rebase, merge `main`, rerun all feature tests,
   or return work to the implementation agent.
2. **Integration owns freshness.** The integration owner selects the next PR in
   dependency/risk order and performs one planned current-`main` reconciliation
   when that PR reaches the front of the merge queue.
3. **Preserve feature evidence.** Green feature tests remain valid evidence about
   the implementation. Final integration validation answers the separate question
   of compatibility with the current shipping tree.
4. **Invalidate only for a reason.** Additional reconciliation or retesting after
   the planned freshness pass requires at least one of: a demonstrated conflict,
   a dependency changed, a failed integration gate, or material overlap between
   intervening commits and the PR's dependency/risk surface.
5. **Merge immediately after final green.** Once the exact integration tree is
   green and all normal merge gates are satisfied, merge that PR before starting
   another unrelated `main`-changing merge whenever practical.
6. **Respect dependency order.** Stacked/dependent PRs must be integrated in their
   dependency order; never merge a child first merely because GitHub currently
   labels it mergeable.
7. **Use a temporary integration branch only when useful.** For bursts of parallel
   work, Integration may maintain a short-lived rolling integration branch to
   prove the combined future state. It is staging only, must be refreshed from
   `main`, must stay small, and must never become a second long-lived source of
   truth.
8. **Implementation agents freeze at handoff.** After `READY_FOR_INTEGRATION`, they
   should not add unrelated cleanup, opportunistic refactors, or freshness-only
   commits unless Integration sends the PR back for a concrete reason.

The intended flow is:

```text
implementation -> FEATURE_GREEN -> READY_FOR_INTEGRATION
               -> Integration freshness pass -> INTEGRATION_GREEN -> merge
```

This policy supersedes any instruction that treats every movement of `main` as
automatic invalidation of all open PR evidence.

## Before You Start: Check Who Else Is In There

The branch rule above is necessary and **not sufficient**. Several sessions run
concurrently, each on its own branch, and a branch lock does not stop two of them
independently fixing the same defect in the same file. That is not hypothetical —
on 2026-08-05 two sessions wrote the same `src/trade/monte_carlo.py` fix, arriving
at the same design and even the same string literal, with one constant differing.
Both were correct; one was wasted, and the differing constant made it a semantic
conflict rather than a clean textual one.

So, before writing code:

1. **List the open PRs and read their file lists**, not just their titles. Two
   PRs can describe different work and touch the same lines.
2. **Search the finding registries before "discovering" anything.**
   `docs/audits/decision-intelligence-audit-2026-08-04.registry.json` holds 531
   findings; `scripts/audit_status.py` carries the curated status for the
   Criticals. Four of nine findings in one 2026-08-05 sweep were already recorded
   there. Re-finding a known defect is cheap; re-fixing one is not.
3. **Trust a PR's diff over its description.** A PR body describes the work at the
   moment it was written. On 2026-08-05 one PR still opened "Audit only — no
   production file is modified" while its head carried 69 production source files.
4. **Say what you are taking.** Name the files in the PR description, and if you
   are claiming a subsystem for a while, say so where the next session will look.

## When Your Work Overlaps Someone Else's

- **Never rebase onto another PR's branch** — rebase onto `origin/main` directly.
  Then verify with three dots: `git diff --stat origin/main...HEAD` should show
  only your own files. (Two dots hides the problem; this correction was paid for
  twice — see `docs/ORCHESTRATION.md` §2a.)
- If the same lines are already changed on another open PR, **re-derive your fix
  on top of theirs, or drop yours** — do not blind-rebase and do not assume the
  merge resolved it correctly.
- High-conflict files have custodians and append-only conventions: see
  `docs/ORCHESTRATION.md` §3 before editing `server.py`, `package.json`,
  `globals.css`, or `src/api/data_contract.py`.
- No cross-agent file edits without a registry entry (`docs/ORCHESTRATION.md`
  §2 rule 6 — that rule did not expire).

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
