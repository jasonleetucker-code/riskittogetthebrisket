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

## Training substrate (Batch 3 Unit D, 2026-10-01)

Which evidence trains and holds out each scope is owned by ONE manifest,
`src/model_registry/training_manifest.py`. Its paths, signal types, live roles and
provider families are derived from the live source registry. The fitter's and
holdout's source tables are views of it. Its rules:

- every training and holdout population is players-only;
- only native values teach spacing;
- no provider family sits on both sides of a split;
- lineage (proven / measured / suspected / unknown) is read from the lineage owner, and measured dependence is reported, not confused with ancestry;
- one trainer per family per scope.

**Rank-voter native values train by default (lead decision, 2026-10-01).** Dynasty
Daddy, Dynasty Nerds, Yahoo/Boone, Fitzmaurice and DraftSharks vote by RANK at serve
time, but they also publish vendor-native VALUE columns, and those columns are real
vendor spacing evidence. The manifest trains on them by default
(`TrainingPolicy.allow_rank_voter_native_values=True`) and every input records its
`spacingEvidence` (`native_value`; a rank-only board or a synthetic rank encoding can
never train). The opposite policy — training on value-signal lineages only — is a
single switch (`allow_rank_voter_native_values=False`) and will be a **preregistered
arm in the clean D2 rerun**, not an ad-hoc comparison after the fact.

Every raw refit is a pinned, point-in-time training run
(`src/model_registry/training_run.py`). The run refuses any input observed after its
cutoff (HEAD's commit time). A `--cutoff` earlier than HEAD is never fitted from HEAD's
tree: `auto_refit_hill_curves.py` routes it to a git replay at or before the cutoff,
and a replay refuses a commit that holds no board snapshot rather than falling through
to `RISKIT_FIT_SNAPSHOT`. `scripts/hill_training_run.py verify` replays a recorded run
from git and must reproduce the same `challengerHash` **and the same parameters** (for
an Autopilot composite: the source run's hash and the OFFENSE pair; its other scopes
are the incumbent's and no run produced them). The workflow verifies the latest raw
refit and, before registering a composite, the **tournament winner** it is built from.

Storage and identity:

- The full run record is a committed artifact,
  `config/model_registry/training_runs/<challengerHash>.json`; the registry entry
  keeps a compact summary (hashes, the replay pins verify needs, per-scope
  promotability). `load_training_run` integrity-checks an artifact against its
  summary. Retention (`prune_training_runs`, run after every recorded refit and as
  `hill_training_run.py prune`) deletes unreferenced artifacts and those of rejected
  runs older than 30 days; a pruned run still replays from its summary.
- `challengerHash` is the run's IDENTITY (it includes the cutoff and cutoff-relative
  freshness ages, so it differs on every run). `evidenceHash` is what the run is
  evidence OF: the sorted set of content hashes of the values each trainer fed the
  fit, plus `modelHash`. Tournament de-duplication and the parameter-stability gate
  key on `evidenceHash`, so refits on unchanged trainer data count once.
- A composite (`composedFrom`) re-stamps `modelHash` / `challengerHash` /
  `evidenceHash` from its own parameters (the source's are kept as `source*`) and is
  never tournament-eligible.
- A declared trainer whose value column is absent raises `MissingColumnError` rather
  than reading as zeros; the fitter skips it with `missing_column:<col>`, the run
  records the input with `missingColumn` and `rowsRead: null`, and any skipped
  declared trainer makes that scope `promotable: false`. A non-promotable OFFENSE
  scope is rejected at refit time and excluded from the tournament. Missing inputs
  record `rowsRead` / `picksDropped` as `null`, never `0`.

Evidence and the remaining owner decisions (H1/H2/H3/H4):
[`evidence/hill-trainer-repair-2026-10-01/README.md`](evidence/hill-trainer-repair-2026-10-01/README.md).

## Readiness criteria

Policy lives in
`config/model_registry/hill_autopilot_policy.json`, not in prose.

0. **Reproducible current substrate.** Only a raw challenger whose `trainingRun` is on
   the current substrate version, is `reproducible: true` and has a promotable OFFENSE
   scope enters the tournament; composites never do. One whose `evidenceHash` repeats
   an earlier version's is the same evidence and is dropped. Pre-repair challengers (no pins, KTC pick rows in the OFFENSE fit,
   Fantasy Navigator held out) cannot compete. Promotion therefore waits for fresh
   substrate-v2 evidence to meet gates 5 and 6 below.

A standing candidate must clear all of these before board-impact evaluation:

1. **Current paired improvement**
   - champion and every challenger are re-scored on the same current files;
   - minimum improvement is the greater of 25 RMSE points or 5% of the
     incumbent criterion.

2. **Cross-market breadth**
   - at least 3 holdout boards must improve. Since 2026-10-01 the OFFENSE split has
     exactly 3 boards (FantasyCalc, OTC, PFK), so this gate now means **all three must
     improve**. Every holdout's relationship with every training family is read from the
     ONE lineage owner, `config/sources/source_lineage.json` (its `pairReconciliation`
     categories, validated by `src/sources/source_census.py`), by
     `training_manifest.holdout_lineage` — there is no private dependence table. A board
     counts as **independent** only when the owner reconciles it
     `INDEPENDENT_NO_EVIDENCE` with every training family, naming the family's actual
     trainer key, and no recorded proven / measured / suspected relation joins it to a
     member of that family — a relation is never outvoted by a pair verdict (the worse of
     the two wins, PROVEN > MEASURED > SUSPECTED > INDEPENDENT), and the owner's validator
     refuses an `INDEPENDENT_NO_EVIDENCE` pair beside a proven or measured relation joining
     its sources, cited or not. Both read one rule, `source_census.relation_dependence_category`:
     a measured relation counts only with a positive dependence statistic in its latest
     measurement (D2 §5; `dlf-ktc-independence`, residual −0.447, counts as nothing), and the
     validator follows exactly one *identity* hop per side (`IDENTITY_RELATION_KINDS`: one
     provider's calibration states, payload, page or boards — never scale borrowing or data
     use). `PROVEN_COMMON_ANCESTRY` excludes the board from the split;
     `MEASURED_DEPENDENCE` and `SUSPECTED_DEPENDENCE` (the D2 preregistration §5 rule
     counts suspected relations) keep it in the split, tagged and not independent; and
     anything the owner cannot answer — an unreadable or invalid lineage file, no
     reconciled pair, a null category — is `UNKNOWN` and fails closed (not independent).
     Each scored board's categories are published as `lineageDependence`, the MEASURED
     subset as `measuredDependence`, and the mean RMSE over independent boards as
     `independentCriterion`. **Today no OFFENSE holdout is independent**: OTC carries
     measured dependence on base KTC, Dynasty Daddy and Yahoo/Boone and suspected
     dependence on Fitzmaurice and Dynasty Nerds (#1599,
     `docs/sources/integrity/OTC_LINEAGE_REMEASURE_2026-10-01.md`); PFK and FantasyCalc
     are measured-dependent on `ktcCrowd` / `dynastyDaddySf` and have no reconciled pair
     for the other trainers. So `independentCriterion` is `null` with
     `independentCriterionReason: "no_independent_holdout"`, also recorded in every
     Autopilot run as `holdoutIndependence`. It is **reporting-only**: no readiness or
     promotion gate reads it, so its absence neither stops nor loosens automatic OFFENSE
     promotion. The threshold stays at 3 boards, and nothing re-weights or drops a
     dependent board to make it pass. `manifestHash` covers the holdout labels DERIVED
     from the lineage file (each board's per-family category), not the file's bytes: an
     edit that changes an OFFENSE holdout's category makes standing challengers
     `stale_code_or_manifest` until a refit replaces them, while an unrelated edit (an IDP
     or DLF pair, prose, a re-measurement that keeps the verdict) does not restart the
     persistence window. The file's normalized sha256 is still recorded as provenance in
     the manifest and in every run record (`lineage`, outside `pinsHash`);
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
