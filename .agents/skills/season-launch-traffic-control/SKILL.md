---
name: season-launch-traffic-control
description: Use only for active fixed-denominator season-launch completion work: mechanical contract recounts, exact-head PR integration, deploy/production evidence harvesting, blocker routing, and truthful VERIFIED promotion. Do not use for broad product implementation or as a second feature owner.
---

# Season Launch Traffic Control

## Objective

Advance an active season-launch completion contract through legitimate evidence while preserving repository ownership and methodology boundaries.

## Authority

This skill does not authorize product scope.

Before acting, read:

1. `docs/AGENT_OPERATING_SYSTEM.md`
2. `docs/EXECUTION_PLAN.md`
3. the active completion contract
4. `docs/season-launch/2026_SEASON_LAUNCH_STATUS.md` when Week 1 launch is active
5. `docs/WORK_CLAIMS.md`
6. current open PRs and live `main`

For Week 1, the canonical scoreboard is:

`docs/season-launch/WEEK_1_LAUNCH_CONTRACT.md`

Fixed denominator: **30**. Only literal row status `VERIFIED` counts.

## Traffic-control loop

1. Re-read live `main` and the contract.
2. Mechanically count contract rows by literal status.
3. Identify changes since the prior repository state.
4. Inspect relevant open PRs and exact-head CI.
5. Merge only bounded, eligible PRs through the normal protected path.
6. Harvest deploy/production evidence separately from merge evidence.
7. Promote a contract row only when its own acceptance condition is actually satisfied.
8. Route a failed unit back to the smallest responsible implementation step.
9. Continue other dependency-ready work when one row is blocked.
10. Stop the campaign when the contract's terminal condition is reached.

## Evidence states

Never collapse:

`IMPLEMENTED -> FEATURE_GREEN -> READY_FOR_INTEGRATION -> INTEGRATION_GREEN -> MERGED -> DEPLOYED -> VERIFIED`

If the contract uses fewer labels, preserve the same semantic distinction in the evidence note.

## Required invariants

Preserve:

- ONE CONCEPT / ONE CANONICAL OWNER
- missing != zero
- stale != current
- unknown != false
- exact requested-league scoring/settings
- canonical best-ball optimal-lineup behavior
- auth/provenance
- public/private semantic boundary
- no guessed methodology
- no synthetic production evidence

## Blockers

If a row requires a genuine owner/external decision:

- mark/report that specific row blocked;
- state the smallest exact decision/evidence needed;
- do not guess;
- continue independent dependency-ready work.

Examples include:
- unavailable credential/secret that the repository cannot set itself;
- host semantics that cannot be established from current evidence;
- irreversible capture-timing tradeoff reserved for the owner.

## Integration behavior

- Inspect the PR's exact current head.
- Do not merge a stale/unknown head merely because an earlier run was green.
- Preserve dependency order.
- Do not reopen a superseded implementation and create a second owner.
- Leave a durable disposition comment when closing/superseding work so the next session does not rediscover the reason.

## Output

Report compactly:

- current X/N and percentage;
- newly VERIFIED rows;
- PRs opened/merged;
- deployments/production verification;
- blockers;
- pace against the active deadline;
- one highest-value next action.

If the Week 1 contract reaches 30/30, report exactly:

`WEEK 1 LAUNCH TRANCHE COMPLETE — 30/30 VERIFIED`

Then make no further Week 1 completion-tranche changes.
