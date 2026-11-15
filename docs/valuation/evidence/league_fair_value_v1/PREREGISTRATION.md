# Preregistration — Brisket League Fair Value (`league_fair_value_v1_shadow`)

**Status: DRAFT — thresholds are TO-FREEZE. Nothing in this document is frozen.**
Until a commit freezes the TO-FREEZE fields below and the evaluator verifies that
commit, every evaluation receipt this family produces carries the verdict
`insufficient_sample`, whatever the results look like.

Machine-readable twin: `src/league_valuation/preregistration.py`
(`GateThresholds`, `PRIMARY_METRIC`, `TO_FREEZE_FIELDS`, `OWNER_PRECONDITIONS`,
`DISPOSITION_TO_VERDICT`). `tests/league_valuation/test_preregistration.py`
fails if this file stops naming every machine field.

Owner directive: League Intelligence & Trade Decision Engine, 2026-10-19
(Stage D, "Valuation Intelligence"). Rejected predecessor:
`docs/valuation/LEAGUE_AWARE_METHODOLOGY_REJECTION.md` — not restored.

## 1. What is evaluated

The challenger shrinks the canonical market value (`rankDerivedValue`, the
champion) toward the league-utility order measured by BDVM's own fundamental
output, by quantile matching inside each scope population and log-space
interpolation with `k_i = kMax · q_i`. Method: `MODEL_CARD.md`. Parameter set:
`config/league_valuation/fair_value_v1.json` (every constant PRIOR, never fitted
on the board it shrinks; `paramSetId` is its content hash).

## 2. Primary metric (one, dynasty horizon)

`within_position_spearman_delta_vs_canonical_realized_por_2plus_seasons`

* **Target:** realized league-scored points over replacement summed over at
  least 2 forward seasons (`forward_seasons >= 2`), each season scored with its
  OWN scoring card (`league_comparison.season_scoring`), replacement measured
  the same way for both boards; or an owner-approved independent target
  registered through `model_registry.independent_validation`.
* **Statistic:** within-position Spearman of each board against that target;
  the metric is challenger minus champion, pooled across positions with a paired
  bootstrap over players (`model_registry.board_holdout.paired_bootstrap`, math
  only — never the withdrawn lens).
* **Cohorts:** QB, RB, WR, TE, DL, LB, DB.

## 3. Secondary metrics (descriptive only, never a gate)

* `forward_ros_realized_points_spearman_delta` — favours the projection-built
  challenger by construction.
* `future_market_movement_spearman_delta` — circular with the market champion.

Both travel in the receipt's `extra.secondaryDescriptive`, with
`secondaryMetricsGate: false`. If a secondary metric is ever tested across the
seven position cohorts it uses a Holm correction and is still descriptive.

## 4. Holdout (chronological, examined once)

* Origin: the challenger board and BDVM snapshot dated strictly before the first
  forward season's kickoff; outcomes from the following seasons only.
* `holdout_window`: **TO-FREEZE** (expected: the 2026 and 2027 NFL seasons).
* Point-in-time guards: kickoff lock by `observed_at`; `src.history.asof`
  reads with `knowledge_cutoff` and `max_age_days`; board date strictly before
  the target window; rebuilds only from pinned inputs.
* The window is examined ONCE under this preregistration. Re-examining it needs
  a new preregistration and a new forward window (anti-adaptive rule).

## 5. Pins every receipt carries

`codeSha` (`api.build_identity.resolve_build_identity`), `sourceHashes`,
`snapshotHash`, `scoringFingerprint` (sf1, per season), and the extended pins
`formatFingerprint` (tmf1), `bdvmParamSetId`, `hillMasterParamSet`,
`challengerParamSetId`. A missing pin is refused; an absence is stated as
`unobserved` / `not_applicable` with a reason.

## 6. Gate (TO-FREEZE fields)

| field | meaning | value |
|---|---|---|
| `min_ci_lower_bound` | the primary metric's CI lower bound must exceed this | **TO-FREEZE** (expected `0.0`) |
| `ci_level` | bootstrap interval level | **TO-FREEZE** |
| `bootstrap_iterations` | paired bootstrap resamples | **TO-FREEZE** |
| `min_n_per_cohort` | players with a realized target per position cohort | **TO-FREEZE** |
| `max_cohort_regression` | largest tolerated per-cohort point regression | **TO-FREEZE** |
| `holdout_window` | the forward seasons examined | **TO-FREEZE** |
| `preregistration_commit` | full 40-hex SHA of the commit that freezes this file | **TO-FREEZE** |
| `preregistration_committed_at` | that commit's instant (must precede the evaluated cutoff) | **TO-FREEZE** |

The evaluator verifies the commit with
`model_registry.independent_validation.git_preregistration_committed` (strict
ancestor of HEAD, blob unchanged since).

Additional hard requirements (not tunable): zero out-of-range values, zero
lineage violations (`src.evidence_lineage`), byte-reproducible from pins.

## 7. Owner preconditions (required before ANY promotion path)

| field | question | state |
|---|---|---|
| `projectionUtilityInDynastyRuling` | may projection-derived utility enter a dynasty value at all (source-domain boundary)? | **unrecorded** |
| `canonicalIdentityArchitecture` | league-scoped canonical value, or a redefined canonical identity? | **unrecorded** |

While either is unrecorded a passing primary gate is reported `INCONCLUSIVE`,
never `ELIGIBLE`.

## 8. Dispositions → `EvaluationReceipt` verdicts

| disposition | verdict |
|---|---|
| ELIGIBLE | challenger_better_pending_policy |
| NOT_ELIGIBLE | champion_retained |
| INSUFFICIENT | insufficient_sample |
| INCONCLUSIVE | inconclusive |

* INSUFFICIENT — thresholds unfrozen; no primary result; any cohort below
  `min_n_per_cohort`; no interval.
* NOT_ELIGIBLE — any hard requirement failed; a cohort regressed beyond
  `max_cohort_regression`; or the primary interval lies wholly below zero.
* ELIGIBLE — CI lower bound above `min_ci_lower_bound`, no cohort regression,
  hard requirements met, both owner preconditions recorded.
* INCONCLUSIVE — everything else (including a passing gate with unrecorded
  preconditions).

Receipts are `model_registry.evaluation_receipt.EvaluationReceipt`;
`promotes` is the constant `False`. `challenger_better_pending_policy` is a
statement about evidence; promotion needs a registered, passing, owner-approved
gate in `model_registry.family_gates` (PR-2) and a separate single-writer
serving PR behind a default-OFF flag with a rollback env var.

## 9. Expected outcome

`insufficient_sample` for at least two seasons: no board history predating an
observable multi-season outcome exists, and board history does not yet record
`league_key` / scoring and format fingerprints (the rejection record's reopen
condition — `src/snapshots/board_store.py` columns are a later PR).
