# Package Value Adjustment — Phase 2 preregistration (2026-10-19)

**Committed before any Phase 2 result was computed.** Phase 1 (PR #1833,
`docs/valuation/PACKAGE_MODEL_HYBRID_RESEARCH_2026-10-19.md`) is preserved unchanged.
Production stays `geom_q078_v1`, q = 0.78. This document cannot promote anything.

Disclosure: while designing the new candidate (§2) I hand-computed about five illustrative package values to
check the formula was sensible. No archive, Trade Finder or matrix result for it had been computed when this
file was committed.

## 1. Why Phase 1's real-trade metric is replaced

Phase 1 scored models by mean **|residual|** on accepted trades. That target has no interior optimum: it
keeps improving as packages collapse toward "best player only" (q → 0.2), so it cannot identify a package
model (Phase 1 §6). Phase 2 uses a **calibration** target instead:

* Orient each two-team trade so side A is the side holding the single most valuable asset (the "stud
  side"). Signed residual `r = (adjA − adjB) / mean(adjA, adjB)`.
* A model that prices package **structure** correctly leaves accepted trades with mean signed residual ≈ 0
  **within every structure bin**: 1v1, ordinary (1v2–2v3), mid (2v4–3v4), deep (fewer side ≤ 3, more side
  ≥ 5), and by deep-side concentration (effective-count share, §2).
* Over-discounting depth pushes deep bins positive. Under-discounting pushes them negative. So the target
  has an interior optimum, and noise (about 21% per trade, Phase 1) averages out with n.
* **This measures where the market clears, not fairness.** Accepted trades are selected (rejections are
  unseen) and can be lopsided. The report must say so.
* The 1v1 bin is the **value-curve control**. No package model touches it, so a non-zero 1v1 mean is a
  board-versus-market offset that the package model must not absorb (that would double-count).
  Structural bins are read **relative to the 1v1 bin**.

## 2. Candidates (frozen)

| id | formula | role |
|---|---|---|
| `GEOM_78` | `U = Σ 0.78^(i−1) v_(i)` via the production dispatch | incumbent |
| `KTC` | `ktc_2026_04` via the production dispatch, on canonical values | baseline |
| `BLEND_G75_K25`, `BLEND_G50_K50`, `BLEND_G25_K75` | Phase 1 blended signed gap | baseline (already fails §3 C1) |
| `FGEOM_70_20` | weights `0.2 + 0.8·0.70^(i−1)` | Phase 1 depth floor |
| `HYBRID_50` | `0.5·Σv + 0.5·‖v‖_1.5` | Phase 1 challenger |
| `GEOM_85`, `LP_150` | as Phase 1 | sensitivity baselines |
| **`EFD_78`** | **`U = (Σ v_i^p)^(1/p)`, p = 1 / log2(1.78) = 1.20210** | **new challenger** |

`EFD_78` = "effective package depth, incumbent-anchored". Rationale (not fitted to any trade):

* **Identity.** `(Σ v^p)^(1/p) = T · N_p^(1/p − 1)`, where T is the raw total and
  `N_p = (Σ (v_i/T)^p)^(−1/(p−1))` is the Rényi/Hill **effective number of pieces** of order p. So the
  package is discounted by how many pieces *effectively* carry its value, not by how many it lists.
  Six equal starters count as 6; a star plus five near-zero pieces counts as about 1.
* **Marginal influence** of a piece is `(v_i / U)^(p−1)`. It is near 1 for a piece comparable to the
  package and near 0 for a negligible one: a smooth, value-relative diminishing return with no threshold.
* **Anchor.** p is chosen so two equal pieces get exactly the incumbent's two-piece premium
  (`2^(1/p) = 1 + 0.78`). Ordinary two-piece trades therefore start from the owner-approved prior, and only
  the treatment of depth and filler differs.
* **Properties by construction.** It is a p-norm, so it is monotone in adding or raising, symmetric,
  permutation-invariant, positively homogeneous and 1-for-1 = raw. Minkowski bounds the gain from adding
  an asset of value x by x, so a 1-point asset adds at most 1 point.

Sensitivity members `EFD_p` for p ∈ {1.15, 1.30} are reported, never selected. Nothing is tuned after
this commit.

## 3. Criteria and what counts as a meaningful improvement

| # | criterion | measured by | pass / improvement bar |
|---|---|---|---|
| C1 | mathematical correctness | Phase 1 property suite + a 1-point-gain bound + splitting/threshold scans | **hard gate**: zero failures |
| C2 | ordinary trades | archive calibration in ordinary bins; band agreement with the incumbent | challenger's ordinary-bin \|mean\| (relative to 1v1) not worse than the incumbent's by more than 2 pts |
| C3 | large packages | archive calibration in the deep bin; controlled matrix | **a demonstrated weakness** = the incumbent's deep-bin mean (relative to 1v1) has a 95% CI excluding 0 on the held-out period; a fix = the challenger's CI includes 0 there |
| C4 | depth vs filler | controlled constant-total matrix | report; filler guard: ≤ 10 pieces each ≤ 10% of a star never reach the star's value (both models) |
| C5 | market evidence | §1 calibration, chronological holdout (earlier 60% describes, later 40% confirms), by format/source where n ≥ 30 | C3 + C2 must hold on the **held-out** period |
| C6 | Trade Finder | replay (§4) | the challenger may not increase "star for a pile" recommendations rated fair, nor remove sensible multi-starter trades the incumbent keeps |
| C7 | stability | the constant-total matrix across concentration profiles | no discontinuity; smooth in concentration |
| C8 | explainability | formula + rationale | one sentence a manager can follow |
| C9 | operational risk | consumer census | report |

**Decision rule.** CHALLENGE only if C1 passes and the incumbent shows a demonstrated weakness (C3) that the
challenger fixes on held-out evidence without failing C2 or C6. KEEP if the incumbent shows no demonstrated
weakness. INSUFFICIENT EVIDENCE if the archive needed for C3/C5 cannot be evaluated or is too small
(n < 30 in the deep bin). q = 0.78 is never re-estimated from accepted trades.

## 4. Trade Finder defensibility definitions (fixed before the replay)

Per recommended trade, on canonical values:

* **star-for-pile**: the side that gives the trade's single best asset receives ≥ 3 pieces, none of them
  ≥ 50% of that asset's value, and the trade is rated `fair` or `slight` under the model.
* **sensible depth**: one side receives ≥ 2 pieces, each ≥ 40% of the best asset it gives, with raw total
  ≥ 1.15 × what it gives.
* Changes are reported as **appear / disappear / reorder / reclassify**, separated by cause: model scoring
  versus candidate generation (identical candidate pools are replayed, then scored per model).

## Amendment 1 (2026-10-19, after the first own-league computation; before any market-ledger or Trade Finder result)

**What was found.** Orienting each trade by "the side holding the single most valuable asset" (§1) makes
the signed residual of every 1-for-1 trade **non-negative by construction**: the stud side *is* the
higher-valued side, so the 1v1 "control" measured |gap|, not a market offset (own-league: +0.206, n = 9).
The same selection on a noisy value biases every other bin upward (a winner's-curse effect). This is a
mathematical defect of the design, not a reaction to which model looked better.

**Change.** Orientation is by **piece count**, which carries no value noise: side A = the side receiving
**fewer** pieces (the consolidating side). Signed residual `r = (adjA − adjB) / mean(adjA, adjB)`.

* Too weak a consolidation premium makes `r` negative; too strong makes it positive. The calibration point
  is `mean r = 0`.
* Equal-count trades (including 1v1) cannot be oriented without values and carry no count signal. They are
  reported for coverage only.
* Bins (by fewer / more pieces):
  * `1vN_small`: 1v2, 1v3;
  * `ordinary`: any other unequal shape with more side ≤ 4;
  * `deep`: more side ≥ 5;
  * plus the deep side's effective-count share (low = filler-heavy, high = genuine depth) where n allows.
* The value-curve confound remains: if the canonical curve is flatter than the market's, stars look
  under-priced and the package model appears too weak. Accepted trades cannot separate the two. This is
  reported as a limitation, never corrected for inside the package model.
* The decision rule (§3) applies unchanged to these bins: a demonstrated weakness = the incumbent's
  `deep` mean has a 95% CI excluding 0 on the held-out later 40%.
