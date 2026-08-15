# Mathematical / Decision-Model Calibration Policy — 2026-08-15

**Status:** BINDING OWNER METHODOLOGY REFINEMENT — PLANNING ONLY  
**Owner instruction date:** 2026-08-15  
**Implementation authorization:** NONE. This document refines the required end-state of already-approved C-Series capabilities. `docs/EXECUTION_PLAN.md` remains the only record that may authorize implementation.  
**Primary C-Series destinations:** `C1-PICK-01`, `C1-PICK-03`, `C2-REPL-01`, `C2-STR-01`, `C2-CORE-01`, `C2-AGE-02`, `C3-PKG-01`, `C3-VA-02`, `C3-CAP-01`, `C3-CALC-01`, `C3-MC-01`, `F-VAL-01`, `C1-SRC-01`, `C10-CLOSE-*`.

---

## 1. Owner decision

The owner approved a targeted mathematical refinement pass after reviewing the current formula inventory and C-Series architecture.

The decision is **not** to replace the canonical player-value engine wholesale. The canonical consensus value spine remains the production baseline unless a challenger proves materially better under the existing P6 model-promotion standard.

The main opportunity is the **decision layer around canonical value**: roster strength, replacement/scarcity, pick uncertainty, trade fairness, consolidation/roster impact, Monte Carlo uncertainty, TE-demand calibration, and roster-age construction metrics.

This policy therefore adds the requirements below to the relevant existing C-Series rows and to the future detailed C execution decomposition.

---

## 2. Global numerical-governance rule

Every material constant, threshold, multiplier, discount, weighting, cutoff, prior distribution or nonlinear transform used in a published decision output must be classified as exactly one of:

1. **MEASURED / VALIDATED** — estimated or selected from appropriate evidence and supported by a reproducible validation record;
2. **MECHANICALLY REQUIRED** — follows from a declared scoring/rules/identity/math contract and has no empirical tuning claim; or
3. **PRIOR / HEURISTIC** — a provisional assumption used because the required empirical evidence does not yet exist.

A prior may ship in a bounded V1 only when:

- it is explicitly labelled as a prior in code/config/docs;
- its sensitivity is measured;
- missing evidence is not disguised as certainty;
- it does not self-promote;
- a named challenger/calibration task exists before C10 closure.

Anything that changes a published number remains subject to the existing P6 standard: pinned inputs, backtest/calibration where possible, champion/challenger comparison, human promotion, monitoring, rollback, and no temporal leakage.

### C10 closure requirement

C10 must include a **prior census**. Every surviving numerical prior must be one of:

- validated and promoted;
- retained deliberately with a documented reason, sensitivity bounds and uncertainty treatment; or
- removed/replaced.

No consequential "magic number" may survive C10 merely because it has been in production for a long time.

---

## 3. C1 — Pick valuation and uncertainty

### 3.1 Future-pick discount must be calibrated, not inherited as a sacred multiplier

**Destinations:** `C1-PICK-01`, `C1-PICK-03`.

Current synthetic future-year treatments are allowed only as temporary provenance-rich fallbacks. The final pick model must test the year-discount / time-preference curve against real dynasty market evidence and the site's historical pick ledger as that evidence becomes available.

Required challenger work:

- compare plausible discount families rather than assuming one fixed annual multiplier;
- preserve season/round identity and uncertainty;
- test monotonicity and pathological cases;
- separate generic market value from the forecast of one owned pick;
- never use `0` for an unknown future pick;
- do not let current roster deterioration improve a manager's outlook when that manager no longer owns the relevant pick.

### 3.2 Owned picks become distributions, not only point estimates

`C1-PICK-03` must ultimately model an owned pick as an outcome distribution under the league's actual draft-order rules, for example probabilities over early / mid / late or over exact slots when the state supports it.

The distribution should consume canonical team-strength/season evidence only when available and should expose:

- expected value;
- distribution / credible range;
- uncertainty/confidence;
- owner/current-owner identity;
- the rule set that determines order;
- the fact that an exact slot is unknown when it is unknown.

A single point forecast may be displayed for convenience, but it cannot be the only retained state.

---

## 4. C2 — Roster strength, replacement, meaningful core and age-value

### 4.1 Team Strength must be lineup- and replacement-aware

**Destinations:** `C2-LINE-01`, `C2-REPL-01`, `C2-STR-01`, `C2-SIM-01`.

The final Team Strength methodology must not be a raw sum of roster values or an arbitrary fixed top-N sum.

It should begin from the canonical exact lineup/slot solver and a single replacement/PAR owner, then distinguish:

- starter contribution;
- flex/superflex eligibility and displacement;
- replacement scarcity in this exact league;
- meaningful depth;
- bench assets whose marginal roster effect is small;
- position-specific injury/availability importance where evidence supports it.

Depth must have **diminishing marginal importance**. A WR6 cannot count like a WR1 merely because both have positive canonical value. In Superflex, a reserve QB may have substantially more roster-impact value than the same raw-value depth asset at a readily replaceable position.

Canonical dynasty player value remains unchanged. This is roster-impact / construction math, not a second player valuation.

### 4.2 Replacement level must be empirical and shared

`C2-REPL-01` must consolidate the existing replacement implementations and define replacement from the actual league environment rather than page-local cutoffs.

At minimum, validate replacement against:

- league size;
- required starters;
- flex/superflex eligibility;
- roster depth;
- positional player pool;
- realistic free-agent / bench availability;
- IDP positional structure.

Where multiple replacement definitions are defensible for different questions, the difference must be named as a different view rather than silently using different formulas under one label.

### 4.3 The `ceil(1.5 × starter demand)` Meaningful Roster Core rule is a champion candidate, not a permanent axiom

**Destination:** `C2-CORE-01`.

Keep `ceil(1.5 × real starter demand)` as the approved V1 champion because it is materially better than scattered page-local QB3/RB3/WR5/etc. rules and correctly counts Superflex as QB demand.

Before it is frozen as canonical long-term methodology, run challenger tests including at least:

- 1.25× starter demand;
- 1.50× starter demand;
- 1.75× starter demand;
- a data-derived marginal-value / replacement-impact cutoff.

Evaluate stability across league formats and whether the selected core matches the assets that meaningfully drive roster strength. Do not tune merely until a few hand-picked rosters "look right."

### 4.4 Young Core Index — continuous position-relative age, not crude universal age buckets

**Destination:** `C2-AGE-02`.

Preserve the approved principles:

- canonical player value is not age-adjusted again;
- only meaningful roster value drives the primary index;
- picks are excluded from age math;
- low-value young bench players cannot make a roster look artificially young;
- age expectations differ by position.

The production challenger should prefer and test **continuous position-normalized age curves** over universal hard buckets such as "under 25 = young." A 26-year-old RB and a 26-year-old QB must not receive the same youth interpretation merely because the calendar age matches.

The final 0–100 score remains league-relative and must be validated against real league examples before being treated as canonical.

---

## 5. C3 — Trade fairness, consolidation, roster impact and Monte Carlo

### 5.1 Internal trade-fairness language must be scale-aware

**Destinations:** `C3-CALC-01`, `C7-DESK-01` when it consumes the calculator result.

Fixed raw-point thresholds on the nonlinear 0–9999 board are provisional. A 500-point gap near the elite tier is not economically equivalent to a 500-point gap deep on the board.

The site's own fairness / amount-to-even / recommendation language should challenger-test a scale-aware contract using some combination of:

- relative / percentage gap;
- package size;
- asset tier / local curve slope;
- uncertainty/confidence;
- topology.

The final rule must preserve symmetry and explainability.

**Do not alter KTC's own Value Adjustment to accomplish this.** KTC VA remains an exact, separately labelled external market-consolidation lens.

### 5.2 Exact KTC VA stays preserved as a market lens

**Destination:** `C3-VA-02`.

Do not "improve" KTC parity by changing its behavior. Consolidate the multiple implementations and make parity exact, but keep KTC VA methodologically separate from canonical roster impact and any future proprietary package methodology.

### 5.3 Consolidation / package quality should ultimately be judged by true roster impact

**Destinations:** `C3-PKG-01`, `C3-CAP-01`, `C2-SIM-01`.

Current constants such as minimum-upgrade ratios and stretch tolerances are priors. They may bound search in V1, but they are not the final explanation of why a 2-for-1 or 3-for-1 helps.

Once canonical roster simulation exists, package evaluation should answer:

`before roster -> apply trade -> enforce final legal capacity -> choose optimal required cleanup -> re-solve lineup -> recompute strength/weakness/core -> compare final state`

This naturally captures:

- starter promotion;
- displaced depth;
- scarce backup value;
- forced-drop cost;
- roster-slot value;
- positional need fixed/created;
- whether consolidation actually improves the meaningful roster.

Never approximate forced-drop cost as package delta minus the lowest raw-value player.

### 5.4 Monte Carlo needs empirical uncertainty and correlation calibration

**Destination:** `C3-MC-01`.

Synthetic ±15% bands are not a final uncertainty model. Before Monte Carlo percentages are promoted as meaningful decision evidence, challenger work must estimate uncertainty from retained history where feasible and test stratification by factors such as:

- position;
- value tier;
- age / career stage;
- forecast horizon;
- injury/status class where supported;
- market-liquidity / source-coverage state.

Correlation assumptions must also be measured or bounded rather than treated as permanent universal same-team / same-position coefficients.

Until validation supports a literal probability interpretation, label the result as a **scenario win rate / modeled outcome share**, not "the probability this trade wins in real life."

The Monte Carlo layer remains an uncertainty lens, not the final trade oracle.

---

## 6. Canonical valuation / TE premium — targeted calibration, not a board rewrite

### 6.1 Do not overhaul the canonical consensus board without a proven challenger

**Destination:** `F-VAL-01`.

The canonical consensus value engine remains the champion. Equal weighting of independent source families remains the default unless historical evidence demonstrates that another weighting scheme improves the declared target without overfitting.

Do not learn source weights from a small/noisy history merely because optimization is possible.

### 6.2 TE premium: preserve measured source conversion; validate the league-demand mapping

**Destinations:** existing #785 requirement, `F-VAL-01`, `C1-SRC-01`.

Preserve the measured source-to-TE-premium / TE++ conversion evidence and the structural no-double-count safeguards.

The unresolved prior is the mapping from league structure/scoring into the target TE basis. Rules such as "1 mandatory TE -> base, 2 -> TE++, 3 -> TE+++" are operator assumptions until validated.

The final calibration should test the combined effect of:

- mandatory TE starter count;
- TE FLEX/SFLEX eligibility;
- TE-specific scoring edges;
- league size;
- replacement scarcity / depth of startable TEs;
- observable market behavior in comparable formats.

A one-TE league with a very large TE receiving premium may create more TE demand than a lightly scored two-TE league; the model must be able to represent that possibility rather than assuming starter count alone fully determines the basis.

Keep source-basis alignment and league-demand adjustment as separate axes so TE premium cannot be applied twice.

---

## 7. Confidence — preserve the bottleneck architecture

The current five-axis confidence owner is **not** targeted for a methodology rewrite by this decision.

Keep the bottleneck structure across:

- independence;
- coverage;
- freshness;
- applicability;
- agreement.

Do not replace it with a weighted-average score where strong source count can compensate for stale, inapplicable or incomplete evidence.

The existing C1 confidence work remains a naming/consumer migration unless later evidence specifically justifies a methodology challenger.

---

## 8. C-Series placement / sequencing

This policy must be folded into the detailed C-Series execution decomposition before implementation proceeds beyond the currently authorized retention work.

| C destination | Required mathematical refinement |
|---|---|
| **C1 — picks / valuation foundations** | Calibrate future-pick discount; owned-pick outcome distributions; preserve canonical board as champion; TE-demand mapping calibration under existing #785 |
| **C2 — roster math** | Exact lineup + one replacement owner; marginal/diminishing depth; Team Strength; 1.5× core challenger; continuous position-relative Young Core age function |
| **C3 — trade substrate** | Scale-aware internal fairness; exact KTC VA parity preserved separately; roster-impact consolidation; final-legal-roster capacity math; empirical Monte Carlo uncertainty/correlation |
| **C7 — decision consumers** | Best Trade / Trade Desk / Golden Upgrades / Package Builder consume the C2/C3 canonical outputs; they do not recreate these formulas |
| **C10 — closure** | Prior census; every consequential heuristic validated, explicitly retained with bounds, or removed |

### Dependency principle

Do the math at its canonical owner **before** high-order products consume it. In particular:

- do not tune Best Trade around a temporary Team Strength formula;
- do not invent package premiums before exact roster simulation exists;
- do not let Monte Carlo percentages become final-decision votes before uncertainty calibration;
- do not freeze the Meaningful Roster Core multiplier before the C2 challenger pass;
- do not tune Young Core on full-roster age noise.

---

## 9. Required evidence before promotion

For each changed methodology, the implementation unit must state:

- declared target / question the formula answers;
- units and scale;
- canonical inputs and lineage;
- whether each tunable is MEASURED, MECHANICAL or PRIOR;
- candidate/challenger formulas;
- pinned comparison dataset / snapshot;
- out-of-sample or temporal validation where feasible;
- sensitivity analysis;
- calibration / reliability where the output is probabilistic;
- pathological/boundary cases;
- cross-format behavior;
- missing-data behavior;
- production observability and rollback.

Parity tests prove two implementations agree. They do **not** prove the shared formula is correct. Accuracy/effectiveness claims require separate evidence.

---

## 10. Non-goals / anti-drift

This owner decision does **not** authorize:

- replacing the canonical player board with BDVM;
- changing canonical values to make individual trade examples look better;
- creating an age-adjusted second player valuation;
- deleting KTC Value Adjustment;
- treating market consensus as objective future truth;
- presenting Monte Carlo scenario share as a literal real-world trade-success probability before validation;
- adding a new page-local Team Strength, replacement, fairness, package or confidence formula;
- beginning any C-Series implementation unit that is not authorized by `docs/EXECUTION_PLAN.md`.

The intended outcome is a site whose numerical recommendations are **consistent, explainable, league-aware, calibrated where evidence permits, and explicit about uncertainty where it does not**.
