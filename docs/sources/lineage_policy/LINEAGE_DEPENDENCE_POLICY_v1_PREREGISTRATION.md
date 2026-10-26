# Lineage dependence-classification policy v1: preregistration

**Policy id:** `lineage-policy/v1`.
**Content hash:** sha256 of the normative block below. The value is recorded in
[`LINEAGE_DEPENDENCE_POLICY_v1.sha256`](LINEAGE_DEPENDENCE_POLICY_v1.sha256), and the
rule for computing it is §1.2.
**Owner authority:** owner methodology decision 3 and required follow-through item 6
(2026-10-01). Intake: `docs/OWNER_REQUESTED_TODO.md`, the "Owner methodology decisions"
entry dated 2026-10-01.

This file is committed **on its own, before any dependence result set is computed or
examined under it**. No new dependence statistic was computed or looked at while it was
written. After this commit the file is frozen. A later change of method is a **new
policy version** in a new file (`lineage-policy/v2`). It is never an edit here.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

## What this file is not

- **Not a result.** It classifies nothing today. The first application is the next
  prospective dependence-classification experiment, which needs its own short run
  preregistration (§4).
- **Not authority to change anything served.** No value, weight, B10 family, source
  role, Hill constant, model-registry entry, flag or manifest moves because of this file
  or because of a result produced under it (§15.3).
- **Not a rewrite of #1599.** `docs/sources/integrity/OTC_LINEAGE_REMEASURE_2026-10-01.md`
  and `OTC_PAIR_SNAPSHOTS_2026-10-01.json` are immutable. Their thresholds and labels stay
  as they are, as descriptive historical output (§16).
- **Not code.** Implementing the instrument changes and the category vocabulary in
  `src/sources/` / `scripts/audit/` is a separate reviewed unit. That unit must implement
  this text. It may not reinterpret it.

## Disclosed exposure (not blind)

When this policy was written, its author had read:

1. **#1599's full results:** the OTC rows (for example base KTC: rank `cpx_lfo` +0.45,
   21/21 positive; detrended value +0.44, 21/21), the Fitzmaurice and Dynasty Nerds rows
   (about +0.15 medians on 6 and 5 distinct comparator versions), the four control
   pairs, and #1599's post-hoc rule (≥ +0.30 and ≥ 90% positive; +0.10 to +0.30 and
   ≥ 75% positive).
2. **#1599's instrument findings:** the depth artifact of per-board percentiles, the TE
   basis artifact, and the leave-pair-out floor of about 1/(k+1).
3. **The 2026-10-01 integrity sweep (#1592)** and its recorded pair verdicts.

How this policy limits the effect of that exposure:

- Every decisive cutoff is a declared **PRIOR**, with a rationale that does not depend on
  #1599's numbers (§17). None was chosen to reproduce or reverse a #1599 label.
- Any data window that overlaps #1599's history is labelled `retrospective`.
  **Independence can never be established from retrospective data alone** (§14).
- #1599's control pairs are reported for continuity. They are never used to tune
  anything (§12.4).

<!-- lineage-policy/v1:BEGIN-NORMATIVE -->

## 1. Identity, immutability, deviations

1.1 **Version.** Every result produced under this policy carries `policyVersion:
"lineage-policy/v1"` and `policyHash: "<sha256 of this normative block>"`. A result
without both stamps is not a v1 result.

1.2 **Hash rule.** Take the UTF-8 text strictly between the line
`<!-- lineage-policy/v1:BEGIN-NORMATIVE -->` and the line
`<!-- lineage-policy/v1:END-NORMATIVE -->`, excluding both marker lines: it begins after
the BEGIN line's line break and ends with the line break that precedes the END line.
Normalize line endings to LF. The policy hash is the lowercase hex SHA-256 of that
text. The sidecar file `LINEAGE_DEPENDENCE_POLICY_v1.sha256` records it, and a
repository test recomputes it.

1.3 **Immutability.** The normative block never changes. If the method must change,
create `lineage-policy/v2` in a new file with its own preregistration commit, made
before the v2 result set is examined. v1 results keep their v1 stamps and are never
relabelled as v2.

1.4 **Deviations.** If an experiment cannot follow a rule here, its report states the
rule, what was done instead and why, next to the original. A deviation that could
change a category makes every affected pair `INSUFFICIENT_EVIDENCE`, with reason
`policy_deviation`, for the safety use (§15.1).

## 2. The question

For an ordered pair (C, T), where C is a candidate board (for example a proposed
holdout or validation target) and T is a board in a training family, the policy asks:

- **Dependence:** is there evidence that C and T share player-specific opinion
  **beyond the positive floor** that any two boards share when each is measured against
  the same correlated consensus?
- **Independence:** is it established, with stated uncertainty and enough distinct
  evidence, that any such shared opinion is negligible?

These are two different questions. "No evidence of dependence" is **not** independence.

## 3. Provenance first; statistics never prove ancestry

3.1 A relation classified `proven` in `config/sources/source_lineage.json`
(`PROVEN_COMMON_ANCESTRY`, including a proven identity hop) **excludes** C from being
independent of T's family, whatever any statistic says.

3.2 A statistic measures **dependence**, never ancestry. No v1 result creates or
upgrades a `proven` relation.

3.3 A recorded `measured` or `suspected` relation is not outvoted by a v1 statistic.
Removing a recorded relation is a separate, reviewed lineage change, and for a
conclusion the owner has recorded it is an owner decision (§16.2).

## 4. Run preregistration (every application)

Each experiment run under v1 commits a short run preregistration **before computing
anything**. It names:

- the window (first and last snapshot instants);
- the pair list and the training-family set;
- the pinned inputs (§13);
- the population or populations (offense, IDP).

A run preregistration may choose only those items. It may not change a cutoff, a
statistic, a floor, an aggregation rule or a category rule. Extending the window or
adding pairs after any result is seen is a deviation (§1.4).

## 5. Observation units

5.1 **Snapshots.** Snapshots are weekly instants at 23:59:59Z. At each instant, every
board is read at its **last committed version at or before the instant**. Nothing later
than the instant is read.

5.2 **Distinct version.** A distinct version is a distinct content hash of the board's
parsed rows (player identity, rank and value). A re-commit with identical rows is the
same version.

5.3 **Limiting member.** The limiting member is the member of (C, T) with fewer
distinct versions inside the window. On a tie it is C.

5.4 **Version-block.** A version-block is a maximal run of consecutive usable snapshots
during which the limiting member's version does not change. **V** is the number of
version-blocks. The evidence unit of this policy is the version-block. Snapshots never
count as independent observations.

5.5 **Unusable snapshot.** A snapshot is unusable when either member is absent, the
common population is below 50 players, the consensus has fewer than 5 boards (§6.3),
or the simulated floor cannot be computed (§7.2). Unusable snapshots are dropped and
counted. They are never imputed.

## 6. Instrument

6.1 **Population.** Offense players only, picks excluded. IDP is a separate population
under identical rules, in its own run. Offense and IDP are never pooled.

6.2 **Common population.** The common population is the players both members rank,
with TE rows removed (the `cpx` construction). A consensus board joins the snapshot
only if it covers at least 60% of the common population. Every participating board is
re-ranked inside that one population, so depth cannot manufacture a shared residual.

6.3 **Consensus (leave-family-out).** The consensus is the voting registry at the
instant, minus both members, minus every board in either member's B10 correlation group
or from either member's provider (the `lfo` rule). Before a voter had its own CSV, its
committed carrier stands in, as in #1599. A carrier is never a measured member. **k** is
the number of consensus boards. If k < 5 the snapshot is unusable.

6.4 **Rank space.** Percentile ranks inside the common population. Each member's
residual is its percentile minus the consensus mean percentile. That residual is then
**detrended**: replaced by its residual from an ordinary-least-squares cubic polynomial
in the consensus mean percentile. This removes the attenuation-toward-the-middle bias
that #1599 left in its rank column.

6.5 **Value space (spacing).** Use only boards that publish native values. The value is
ln(value / that board's maximum value in the common population). The residual is
measured against the consensus mean over value-publishing consensus boards, and is then
detrended by the same cubic. If fewer than 5 value-publishing consensus boards
participate, or either member publishes no values, the value space is
`NOT_MEASURABLE` for that snapshot.

6.6 **Statistic.** In each space, at each usable snapshot s, the statistic r_s is the
Pearson correlation of the two members' detrended residuals.

## 7. The estimator's positive floor

7.1 **Analytic floor.** F_a = 1 / (k_eff + 1), with
k_eff = k / (1 + (k − 1) · ρ̄_C). Here ρ̄_C is the mean pairwise Pearson correlation of
the consensus boards' detrended leave-one-out residuals (each consensus board measured
against the mean of the others), clipped to [0, 1]. This is the floor that two
independent boards share through one consensus built from k correlated boards.

7.2 **Simulated floor.** At each snapshot:

1. Estimate Σ, the covariance of the detrended residuals of every participating board
   (both members and the consensus boards) around the full-pool mean, in the common
   population.
2. Set the C–T cross-covariance to zero. Keep every other entry.
3. Project to the nearest positive semi-definite matrix.
4. Draw R = 500 synthetic worlds. Each world adds multivariate-normal residuals with
   covariance Σ to the observed full-pool mean order.
5. Run the identical instrument on each world (§6.2–§6.6: re-ranking, consensus,
   detrend, correlation).

F_s is the median of the R statistics. The seed is fixed (§10.3). If the projection or
the simulation fails, the snapshot is unusable.

7.3 **Which floor decides what (asymmetric, fail-closed).**

- For **dependence** claims: F_dep = max(F_a, F_s). The higher floor makes it harder to
  over-claim dependence.
- For **independence** claims: F_ind = min(F_a, F_s). The lower floor makes it harder
  to over-claim independence.

The floor is **subtracted**: the excess is e_s = r_s − F, computed per snapshot and
separately for each use.

## 8. Aggregation over distinct versions

8.1 **Block excess.** A block's excess is the median of its snapshots' excess, for each
space and each floor.

8.2 **Point estimate.** Ê is the median of the block excesses.

8.3 **Consistency across distinct versions.** P⁺ is the share of version-blocks with
excess > 0. P_δ is the share with excess ≥ δ (§11). Both count version-blocks, never
snapshots.

## 9. Effective sample size (temporal autocorrelation)

9.1 ρ̂ is the lag-1 autocorrelation of the block-excess series in time order (F_ind
excess, rank space; the same ρ applies to both spaces).

9.2 ρ_used = max(clip(ρ̂, 0, 0.9), 0.2). The 0.2 floor is a PRIOR (§17): a member's own
week-to-week persistence means consecutive distinct versions are never fully
independent. Negative ρ̂ never inflates the sample.

9.3 n_eff = V · (1 − ρ_used) / (1 + ρ_used). This is the AR(1) (Kish-style)
adjustment. It applies to version-blocks, never to snapshots.

## 10. Uncertainty interval

10.1 **Bootstrap.** Circular moving-block bootstrap over the time-ordered block-excess
series, with block length ℓ = max(2, ⌈V^(1/3)⌉) and B = 10,000 resamples. The
resampled statistic is the median.

10.2 **Bounds.** L_dep is the 5th percentile of the resampled F_dep excess medians (a
one-sided 95% lower bound). U_ind is the 95th percentile of the resampled F_ind excess
medians (a one-sided 95% upper bound). Both are computed separately in each space.

10.3 **Seeds.** The base seed is 20261001. Each pair's seed is the base seed plus the
pair's zero-based index in the run preregistration's pair list, plus 1,000,000 × the
space index (rank = 0, value = 1). The simulated floor (§7.2) uses its own seed, the
pair seed + 500,000. Every seed is reported.

## 11. Category rules (primary cutoffs)

Primary cutoffs, all PRIORS (§17):

- **δ = 0.10**, the dependence magnitude;
- **ε = 0.05**, the independence equivalence margin;
- **p = 0.75**, the consistency share.

11.1 **Minimum evidence.** Below any of the following, the space is
`INSUFFICIENT_EVIDENCE`, with each failing reason stamped (`versions`, `n_eff`,
`players`, `coverage`, `instrument_invalid`, `policy_deviation`):

- V ≥ 8 distinct versions of the limiting member;
- n_eff ≥ 6;
- a median common population of at least 100 players;
- at least 80% of the window's snapshots usable;
- instrument validation passed (§12).

A thin result is never read as independence.

11.2 **Per space,** in this order:

1. `MEASURED_DEPENDENCE` when L_dep > 0 **and** Ê_dep ≥ δ **and** P⁺_dep ≥ p.
2. `INDEPENDENCE_SUPPORTED` when U_ind < ε **and** P_δ(F_ind) ≤ 0.25 **and** the
   half-window check (11.3) passes.
3. `SUSPECTED_DEPENDENCE` when neither of the above holds and Ê_ind > 0.
4. `INCONCLUSIVE` otherwise: there is enough evidence, but independence is not
   established.

11.3 **Half-window check.** Split the block series into its first ⌊V/2⌋ blocks and the
remainder. Compute Ê_ind, Ê_dep, L_dep and P⁺_dep on each half, without the minimum
evidence rule.

- If either half meets the MEASURED_DEPENDENCE condition while the full window does
  not, the full-window category is at least `SUSPECTED_DEPENDENCE`.
- `INDEPENDENCE_SUPPORTED` additionally requires Ê_ind < δ in both halves.

A regime change cannot be averaged away into independence.

11.4 **Pair label.** Rank and value categories are always **reported separately**. They
are never combined into one number. The pair label is:

- `INDEPENDENCE_SUPPORTED` only if **both** spaces are `INDEPENDENCE_SUPPORTED`;
- otherwise `MEASURED_DEPENDENCE` if either space is, naming the space or spaces
  (`rank`, `spacing`, `both`);
- otherwise `SUSPECTED_DEPENDENCE` if either space is, naming the space;
- otherwise `INSUFFICIENT_EVIDENCE` if either space is;
- otherwise `INCONCLUSIVE`.

If the value space is `NOT_MEASURABLE` (a rank-only board), the pair label follows
the rank space, except that a rank-space `INDEPENDENCE_SUPPORTED` becomes
`INDEPENDENCE_SUPPORTED_RANK_ONLY`. That label is **not** independence for any use
that compares spacing, which includes every Hill use.

11.5 **Family label.** A family is labelled by its most dependent member pair, in this
order: MEASURED > SUSPECTED > INSUFFICIENT > INCONCLUSIVE > RANK_ONLY >
RETROSPECTIVE_ONLY > SUPPORTED. A
family is `INDEPENDENCE_SUPPORTED` only if **every** member pair is. Requiring every
pair (an intersection-union rule) keeps the overall error rate for an independence
claim at the stated level without a multiplicity correction.

11.6 **Multi-cutoff report.** Every run also reports, for every pair and space, the
category under each δ ∈ {0.05, 0.10, 0.20, 0.30}. Only δ = 0.10 is decisive.

## 12. Instrument validation (gate before any classification)

Run on synthetic worlds built from each run's own consensus structure (§7.2 machinery),
with V = 12 version-blocks and ρ = 0.3 between blocks. The instrument fails validation
if any of the following does not hold:

12.1 **Independent pairs.** 200 synthetic pairs with C–T cross-covariance 0: the
MEASURED_DEPENDENCE rate is ≤ 5%, and the mean F_ind excess is within ±0.03.

12.2 **Injected dependence.** 200 synthetic pairs whose true residual correlation is
0.20: the MEASURED_DEPENDENCE rate is ≥ 80%.

12.3 **Depth confound.** 200 independent synthetic pairs whose members cover different
depths (one at the full common population, one truncated at 80% of it): the
MEASURED_DEPENDENCE rate is ≤ 5%.

If validation fails, every pair in the run is `INSUFFICIENT_EVIDENCE` with reason
`instrument_invalid`.

12.4 **Empirical controls.** The run reports the four #1599 control pairs (DLF vs base
KTC, FantasyCalc vs Dynasty Daddy, Fitzmaurice vs Dynasty Nerds, PFK vs base KTC) for
continuity. They are **never decisive and never used to tune** a parameter.

## 13. Pinned inputs and output schema

13.1 **Pins.** Every run records:

- the code SHA and whether the tree was clean;
- the `CSVs/site_raw` tree commit;
- the sha256 of `config/sources/source_lineage.json`;
- the voting-registry snapshot (the source list with B10 families);
- the policy version and hash;
- the window, the pair list and every seed.

Results are never compared across refreshed inputs with the difference attributed to
the method.

13.2 **Per pair and per space, the run outputs:**

- V, n_eff, ρ̂, ρ_used;
- the usable and unusable snapshot counts, with the reasons for unusable ones;
- the median players, k range, F_a and F_s ranges;
- Ê_dep, Ê_ind, L_dep, U_ind, P⁺_dep, P_δ;
- the half-window values;
- the category and the failing reasons;
- the multi-cutoff categories;
- the sensitivity grid (§17.2);
- the exposure label (§14).

## 14. Exposure and prospective confirmation

14.1 A version-block is `retrospective` if its limiting-member version first appeared
before this policy's preregistration commit timestamp. Otherwise it is `prospective`.
Every result reports both block counts.

14.2 Dependence findings (MEASURED or SUSPECTED) from retrospective blocks are valid
for the **safety use** (§15.1), because exclusion is the fail-closed direction. They
carry `exposure: retrospective`.

14.3 **Independence is never established retrospectively.** A pair can count as
`INDEPENDENCE_SUPPORTED` for any use only if the prospective-only subset itself meets
the minimum evidence rule (§11.1) and is `INDEPENDENCE_SUPPORTED` under §11.2–§11.4.
Otherwise the label is `INDEPENDENCE_SUPPORTED_RETROSPECTIVE_ONLY`, which is not
independence.

## 15. Uses

15.1 **Safety use: Hill exclusion, validation-target eligibility and promotion
safety.** A board counts as independent of a training family only when all of these
hold:

- (a) the family label is `INDEPENDENCE_SUPPORTED`, prospectively confirmed (§14.3);
- (b) no recorded `proven`, `measured` or `suspected` relation links it to the family
  (§3);
- (c) the result is not expired. A v1 result expires for this use 90 days after its
  window's last snapshot.

**Every other outcome is not independent.** That includes INSUFFICIENT_EVIDENCE,
INCONCLUSIVE, RANK_ONLY, RETROSPECTIVE_ONLY, a missing run and an expired run.
Unknown is never independent. Independence is established, never assumed.

Satisfying 15.1 makes a board **eligible** as an independent target. It does not make
it one. Under owner decision 1, an independent validation target for automatic Hill
promotion must also be preregistered as a target, and it must not derive materially
from the same training families.

15.2 **Durable lineage recording.** A v1 result may add a `measured` relation to the
lineage owner only when the pair label is `MEASURED_DEPENDENCE` **and** the space's
L_dep stays > 0 under a Holm step-down adjustment across the m pairs in the run (the
pair's one-sided level α/(m − i + 1) at its Holm rank i, with α = 0.05).
`SUSPECTED_DEPENDENCE` may be recorded only as a pair category stamped with the policy
version and hash, never as a relation. `INDEPENDENCE_SUPPORTED` is recorded as itself
and is never written as `INDEPENDENT_NO_EVIDENCE`, which means absence of evidence.
Adding the v1 vocabulary to the lineage owner is a separate reviewed code unit.

15.3 **Never.** A v1 result never changes a served value, weight, B10 family, source
role, Hill constant, model-registry entry, flag or training manifest. Those move only
through their own owners and gates.

## 16. Standing statements (owner decision 3, 2026-10-01)

16.1 **#1599's thresholds are not this policy.** The rule in
`docs/sources/integrity/OTC_LINEAGE_REMEASURE_2026-10-01.md` was declared after #1599's
data had been seen:

- `MEASURED_DEPENDENCE`: a median ≥ +0.30 and ≥ 90% of snapshots positive;
- `SUSPECTED_DEPENDENCE`: +0.10 to +0.30 and ≥ 75% positive;
- `INDEPENDENT_NO_EVIDENCE`: otherwise.

That rule and its labels are **descriptive historical output**. They are preserved
unmodified and they are not prospective methodology. No part of v1 inherits them.

16.2 **OTC stands excluded.** OTC's dependence on KTC is about +0.45 (rank `cpx_lfo`),
with positive evidence in 21 of 21 measured snapshots. That is **sufficient** evidence
that OTC must not be treated as an independent KTC-family holdout or validation target.
This policy does not need to re-measure OTC to keep it excluded. A v1 result does not,
by itself, reverse that conclusion: reversing a conclusion the owner has recorded is an
owner decision.

16.3 **Fitzmaurice and Dynasty Nerds stay descriptive.** #1599's SUSPECTED labels for
OTC–Fitzmaurice and OTC–Dynasty Nerds remain descriptive. They do not become permanent
production lineage truth because they crossed the provisional bands. Under §15.1, OTC
still does not count as independent of the Fitzmaurice or Dynasty Nerds families until
a prospectively confirmed v1 result says `INDEPENDENCE_SUPPORTED`. Fail-closed
exclusion does not require a dependence label.

## 17. Priors and the sensitivity grid

17.1 **Priors (declared before data, not tuned):**

| parameter | value | rationale |
|---|---|---|
| δ (dependence magnitude) | 0.10 excess correlation | Cohen's conventional "small" correlation. It is about 1% of shared residual variance beyond the floor, the smallest size worth recording as durable dependence. |
| ε (independence margin) | 0.05 | Half of δ, about 0.25% of shared variance. Strict on purpose, because independence is the claim that must be earned. |
| p (consistency share) | 0.75 | Three of four distinct versions agree in sign. A majority alone could be a single regime. |
| interval level | one-sided 95% | Conventional. The asymmetric floors (§7.3) already make each claim conservative in its own direction. |
| V minimum | 8 distinct versions | With fewer blocks, a moving-block bootstrap's 5% tail is set by about one block. |
| n_eff minimum | 6 | Keeps the bootstrap meaningful after the AR(1) discount at ρ_used ≈ 0.2–0.3. |
| ρ floor | 0.2 | A member's own persistence links consecutive versions even when each is distinct. |
| coverage | 60% of the common population | Inherited from the `cp` instrument as a construction choice, not a result threshold. |
| players minimum | 100 median | Below this, one correlation per snapshot is too noisy for the floor subtraction to mean much. |
| detrend degree | cubic | Inherited from #1599's value instrument. Now also applied to rank (§6.4). |
| R (simulated floor) | 500 | Monte Carlo error on a median correlation at this R is far below ε. |
| B (bootstrap) | 10,000 | Standard. |
| expiry | 90 days | Roughly a third of a season. Board methodology and depth change faster than that. |

17.2 **Sensitivity grid (always reported, never decisive).** Each axis is varied one at
a time from the primary, and the category reported:

- δ ∈ {0.05, 0.10, 0.20, 0.30};
- ε ∈ {0.03, 0.05, 0.10};
- p ∈ {0.67, 0.75, 0.90};
- interval ∈ {90%, 95%, 99%} one-sided;
- floor ∈ {F_a only, F_s only, the primary asymmetric pair};
- V minimum ∈ {6, 8, 12};
- n_eff minimum ∈ {4, 6, 10};
- ρ floor ∈ {0, 0.2, 0.4};
- coverage ∈ {50%, 60%, 75%};
- detrend ∈ {none, linear, cubic};
- TE rows ∈ {removed, kept when both members share a TE basis};
- consensus ∈ {`lfo`, `lpo`};
- percentiles ∈ {common population, per board (the depth-confounded instrument,
  reported only for continuity with #1599)};
- bootstrap ∈ {moving-block, stationary with mean block ℓ};
- a Kish-adjusted t-interval (mean ± t(n_eff − 1) · sd / √n_eff) beside the bootstrap.

A pair whose category changes across the grid is reported as **cutoff-sensitive**,
naming the axes. The primary category still decides.

<!-- lineage-policy/v1:END-NORMATIVE -->

## Notes (non-normative)

- **What this policy expects.** Few boards will reach `INDEPENDENCE_SUPPORTED`, and
  that is intentional. Board-to-board independence is hard to establish when every
  board reads the same players, the same news and often the same trades. This is why
  owner decision 1 makes an independent **non-board** target (the completed-trade
  ledger, with its stated KTC and mixed-provenance caveats) the leading candidate for
  Hill validation, and blocks automatic promotion until one exists
  (`AUTO_PROMOTION_BLOCKED: no_independent_validation_target`).
- **Relation to decision 1.** This policy decides only the statistical half for board
  targets. A transaction target's independence is decided by its provenance
  (deduplicated, format-qualified, KTC-platform trades reported per family) under that
  target's own preregistration. Mixing dependent and independent provenance must be
  treated explicitly.
- **Implementation.** The next prospective experiment needs:
  - the detrended rank residual (§6.4);
  - version-blocking (§5.4);
  - the simulated floor (§7.2);
  - the asymmetric floors and bootstrap (§7.3, §10);
  - the validation suite (§12);
  - the v1 category vocabulary.

  `scripts/audit/lineage_pair_snapshots.py` already provides the `cpx_lfo`
  construction, the cubic value detrend and point-in-time reads. Those pieces are to be
  extended there, not duplicated.
