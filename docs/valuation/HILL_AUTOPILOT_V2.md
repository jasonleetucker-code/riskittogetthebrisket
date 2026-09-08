# Hill Autopilot v2 — canonical calibration contract

Status: implementation contract for the live percentile-form Hill masters.

## Objective

The Hill curve must stay current without depending on the owner remembering to
review or promote a challenger. Refitting is therefore automatic whenever
material market data changes, and canonical promotion is automatic only when a
candidate has accumulated enough reproducible evidence to make the state change
safer than keeping the incumbent.

The raw fitter is **not** allowed to write production constants. It only creates
challengers. The automatic state-change path is:

```
2-hour data refresh
  -> material CSV commit?
  -> dispatch refit-hill-curves.yml on that exact SHA
  -> raw refit (forced)
  -> current-snapshot tournament of all standing challengers
  -> parameter-stability gate
  -> forward-in-time persistence gate using git-retained holdout boards
  -> compose OFFENSE-only safe candidate
  -> downstream board-impact capture + guard
  -> fresh paired validate inside promote()
  -> per-scope registry gate
  -> apply
  -> hard tests
  -> commit canonical constants + registry
  -> deploy
```

Every ordinary run records evidence in
`config/model_registry/hill_autopilot_runs.jsonl`. A missing run is therefore
observable; a low-drift run no longer disappears from the audit trail.

## Cadence

`.github/workflows/scheduled-refresh.yml` already refreshes market data every
two hours. A refit is dispatched only when that run creates a material
`chore: automated data refresh ...` commit. Freshness-stamp-only commits do not
refit because no Hill training input changed.

The former independent Tuesday cron is removed. The data producer owns model
cadence.

## What can become canonical automatically

### OFFENSE

OFFENSE currently has a cross-market scorer. Autopilot may change only:

- `HILL_PERCENTILE_C`
- `HILL_PERCENTILE_S`

### GLOBAL / IDP

These scopes still lack promotable evidence of their own. A raw refit may
propose new GLOBAL/IDP constants and the registry keeps them as evidence, but
autopilot never carries those values into production on an OFFENSE win.

The automatic promotion payload is composed from:

- winning OFFENSE c/s;
- incumbent GLOBAL c/s;
- incumbent IDP c/s;
- incumbent ROOKIE c/s.

That means `ModelRegistry.promote()` independently sees GLOBAL/IDP as
`UNCHANGED_FROM_CHAMPION`; no override is used.

### ROOKIE

ROOKIE remains unrouted. It can be fit and monitored but is not an automatic
production decision.

## Readiness criteria

Policy lives in
`config/model_registry/hill_autopilot_policy.json`, not in prose.

A standing candidate must clear all of these before board-impact evaluation:

1. **Current paired improvement**
   - champion and every challenger are re-scored on the same current files;
   - minimum improvement is the greater of 25 RMSE points or 5% of the
     incumbent criterion.

2. **Cross-market breadth**
   - at least 3 holdout boards must improve;
   - no holdout board may worsen by more than 10%.

3. **Row health**
   - every scored holdout board must have at least 300 usable rows;
   - after enough run history exists, a board may not collapse more than 15%
     below its recent row-count median.

4. **Candidate tournament**
   - the best current candidate wins regardless of whether it is newest;
   - newest-fit-wins is explicitly not a rule.

5. **Parameter persistence**
   - at least three independently fitted challengers must converge within the
     configured c/s tolerances;
   - their fit times must span at least five days;
   - with two-hour refits, evidence is sampled across that span rather than
     simply taking the newest three runs.

6. **Forward persistence**
   - git history supplies daily holdout boards strictly after the winning
     candidate's fit date;
   - at least five future daily snapshots are required;
   - the candidate must clear the dynamic paired margin on at least 80% of
     those days;
   - median forward improvement must be at least 25 points.

This is deliberately stronger than repeatedly re-scoring one current snapshot.

## Downstream board-impact gate

Once statistical readiness clears, the proposed scope-safe version is priced
through the real canonical contract twice on identical inputs using
`scripts/measure_hill_version_board.py`.

`scripts/hill_board_guard.py` refuses automatic promotion if the change:

- unprices more than the configured fraction of previously priced assets;
- creates excessive median / p90 / maximum value moves;
- destroys too much top-25 or top-100 membership;
- creates excessive median / p90 rank displacement;
- or if the two captures do not have identical input, source-CSV and freshness
  hashes.

The limits are catastrophe rails, not an objective function. A legitimate
calibration can move many values; it cannot silently destroy the board.

## Promotion is self-proving

`scripts/model_registry.py promote` now re-runs the paired
champion/challenger evaluation itself immediately before state mutation.
A stale advisory `validate` result cannot be used as a receipt.

Only a version whose status is exactly `challenger` can be promoted. A
`rejected` version cannot later bypass its recorded verdict.

`apply` records `appliedAt` when it actually writes the champion's
constants.

## Canonical tripwire

The hard test no longer pins July's literal constants. The invariant is now:

```
committed player_valuation.py constants
    == imported runtime constants
    == model-registry champion params
```

This lets a legitimate automatic promotion remain green while making a hand
edit or registry/source mismatch fail immediately.

KTC reconciliation remains a livedata advisory sanity check and carries no
champion-specific values that require manual re-baselining.

## Stale-evidence protection

Before committing an automatic promotion, the workflow fetches `origin/main`
and verifies that main is still the exact SHA on which all evidence was
measured. If main advanced during evaluation, the write is refused and the next
data refresh re-runs the process.

There is no "rebase the model decision onto newer data" path.

## Rollback

After `apply`, the hard model-registry/canonical tests run again. A failure
automatically invokes registry rollback and re-applies the former champion
before the workflow exits red.

The normal registry rollback remains the explicit emergency undo for a
post-deployment issue.

## Remaining work before GLOBAL/IDP auto-promotion

Autopilot intentionally does **not** manufacture evidence. GLOBAL and IDP need
their own scope-valid evaluation layer before they can become independently
automatic. When those scorers exist, the same tournament/persistence/impact
framework can promote those scopes without an owner override.
