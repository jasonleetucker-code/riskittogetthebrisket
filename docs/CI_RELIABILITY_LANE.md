# CI Reliability Lane — Isolated Cloud Repair Scope

## Branch

`claude/ci-reliability-hardening`

This branch is an intentionally isolated CI/workflow reliability lane. It must be worked from a separate cloud Claude session or other isolated clone/sandbox. It must not share a working directory or active branch with the six V1 engineering lanes.

## Mission

Make GitHub Actions trustworthy and quiet for the right reasons:

- healthy repository/production states should produce green workflows;
- genuine defects should remain red and actionable;
- chronic false-red, flaky, stale-assumption, runner-environment, and duplicated-workflow failures should be eliminated at their root cause;
- no workflow may be made green by hiding, skipping, weakening, swallowing, fabricating, or misclassifying failure.

The target is not "make the emails stop." The target is a reliable signal system in which red means something is actually wrong.

## Initial Failure Families To Audit

At minimum inspect the currently reported failures for:

- Bootstrap Sharp Records
- Retention health (read-only)
- Audit Rank-Form Curve Drift
- PR Validation
- Scheduled Data Refresh
- Verify Sharp Production Population
- E2E Safety Net

Do not assume these are seven independent defects. First cluster failures by common root cause, shared setup, shared external dependency, shared generated artifact, auth/configuration, runner state, stale fixture/assumption, or product regression.

## Required Operating Rules

1. Read `AGENTS.md` and `ASSISTANT_COORDINATION.md` before changing anything. Their rules remain authoritative.
2. Follow the repository anti-thrashing policy: do not chase every `main` movement. Preserve feature/diagnostic evidence and let Integration own final freshness reconciliation.
3. Stay on `claude/ci-reliability-hardening` until handoff. Do not work directly on `main`.
4. Inspect open PRs and `docs/WORK_CLAIMS.md` before touching overlapping files. Add/update a work claim for this lane.
5. Reproduce and classify each failure before repairing it. Record the exact failing workflow, job, step, SHA, and causal evidence.
6. Prefer shared root-cause repairs over seven one-off patches.
7. CI/workflow/test-harness/setup/bootstrap/probe changes are in scope. Product-source changes are allowed only when a proven product defect is the actual root cause and the file is not actively owned by another lane; otherwise hand the defect to the owning lane.
8. Never use `continue-on-error`, blanket skips, weakened assertions, fake production data, swallowed exit codes, disabled checks, unconditional success paths, or equivalent false-green mechanisms to make a workflow pass.
9. Preserve repository semantics: missing/unknown != zero; stale != current; unavailable != healthy; degraded != valid empty.
10. Do not alter valuation/scoring/trade/BDVM methodology, owner product rules, authentication policy, or V1 scope merely to satisfy CI.
11. Do not merge incomplete umbrella #923.
12. If a workflow is intentionally red under a real degraded condition, make that behavior explicit, bounded, documented, and actionable rather than silently coercing it green.
13. Where practical, prove repaired guards have teeth with RED→GREEN/non-vacuity evidence or an equivalent controlled failure reproduction.
14. Re-run only the workflows necessary to validate the causal repair. Do not spam reruns of genuine reds.
15. Before handoff, audit for false greens as aggressively as false reds.

## Failure Classification

Every investigated failure must be placed in exactly one primary class:

- PRODUCT_DEFECT
- WORKFLOW_DEFECT
- TEST_OR_ASSERTION_DEFECT
- RUNNER_OR_ENVIRONMENT_DEFECT
- CONFIG_OR_SECRET_DEFECT
- EXTERNAL_DEPENDENCY_DEGRADED
- STALE_ASSUMPTION_OR_FIXTURE
- FLAKY_OR_RACE
- EXPECTED_ACTIONABLE_FAILURE
- DUPLICATE_OR_OBSOLETE_WORKFLOW

If evidence is insufficient, mark `UNRESOLVED` rather than guessing.

## Done Criteria

This lane is ready for Integration only when:

- the named failure families have been audited against live GitHub evidence;
- common root causes have been identified and repaired where authorized;
- affected exact-head workflows are green when the system is healthy;
- intentional failure states remain truthful and actionable;
- no false-green workaround was introduced;
- no unrelated product feature work was absorbed;
- the branch is documented with a concise failure matrix showing before state, root cause, repair, validation, and any remaining external blockers;
- a single bounded PR is opened from this branch to `main` and handed to Claude 5 / Integration as `READY_FOR_INTEGRATION`.

## Integration Owner

Claude 5 / Integration owns final current-shipping-tree reconciliation, dependency/order checks, final CI, and merge. The CI Reliability lane must not repeatedly rebase/chase `main` after feature evidence is complete.
