# C1-U6 — Pick Completeness Through 2029

**Status:** DELIVERED (this unit) — manifest rows `C1-PICK-01`, `C1-PICK-02`
**Authorized:** 2026-08-16 at the C1-U4 owner checkpoint (`docs/EXECUTION_PLAN.md` §0/§2);
`C1-U5` deliberately deferred by the same decision
**Canonical owner:** the `data_contract` pick pipeline (`src/api/data_contract.py`
injection → blend → tether → completeness pass) + `src/api/pick_value_resolution.py`
(reference-class lookup, computes nothing)
**Binding methodology:** `docs/MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md` §3.1 ·
`docs/TRADE_CALCULATOR_MARKET_EVIDENCE_EXPANSION_SPEC.md` TC-19..TC-22 ·
`docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` §10

This document is the design record the unit's checkpoint reviews: the census, the
measured REDs, the evidence, the challenger comparison, the promotion decision,
the sensitivity bounds, and what was deliberately not done.

---

## 1. The product contract

After C1-U6, every VALID canonical future pick through the horizon
(`current_rookie_draft_year() + 3` → 2029 while the active draft is 2026; the
horizon self-rolls) has exactly one of:

* **A.** a finite canonical market value backed by approved evidence
  (`direct_market_blend` / `rookie_pool_tether`), or
* **B.** a finite explicitly-PRIOR-derived fallback with provenance, prior
  classification, named uncertainty, and a reproducible derivation
  (`derived_year_step` / `derived_round_step` / `derived_uniform_tier_ev`).

It never has: 0-because-evidence-is-missing, NaN/∞, fabricated exact-slot
certainty, a silently borrowed current-year value, or a consumer-specific guess.
"Missing market evidence" and "worth zero" remain different states structurally:
an unresolvable reference answers `value: None` + a machine-readable reason.

## 2. Pre-change census — every future-pick value decision path

Measured on `main` @ `6309da82` (2026-08-16; eight-agent sweep + direct
measurement).  **Six independent decision paths** created/derived/discounted
future pick values:

| # | path | what it decided | constants (classification) | disposition |
|---|---|---|---|---|
| 1 | `Dynasty Scraper.py` pick-model rebuild (L6150-6554) | deletes and rebuilds all 126 raw pick rows; 2027/2028 tiers = 0.75/0.65-weighted outside-market blend × its OWN year discount; rounds 5-6 = base×disc only | seeds {2027: 0.84, 2028: 0.70} recalibrated per run, clamped [0.60,0.95]/[0.45,0.85] (PRIOR — and the 0.95 clamp ceiling CONTRADICTS the measured market: both vendors price 1-out ABOVE current, +26% at R1); blend weights 0.75/0.25, 0.65/0.35 (PRIOR); slot-spread 0.20/0.14/0.12 (PRIOR); pad decay 0.94, seed 2500 (PRIOR) | RETAIN as the raw-payload producer (its values only vote where the CSVs corroborate; its R5/R6 synthesis measured NON-MONOTONIC — R4→R5 step > 1.0 — and never votes). Rollover year-literal defect recorded §12 |
| 2 | `_inject_far_future_pick_sources` + Phase 3a discount (data_contract) | 2029 = verbatim clone of 2028 tiers, × `offsetDiscounts["3"]` = 0.53 at blend | 1.00/0.82/0.66/0.53 + fallbackBase 0.80 (PRIOR — audit V-12/C-11: uncalibrated, applied to a cloned price) | **REPLACED** — measured year-step at injection (§5); Phase 3a is stamp-only |
| 3 | `_anchor_current_year_picks_to_rookies` (tether) | current-year slot values = merged rookie pool | league size (MEASURED live, 12 fallback PRIOR); rounds 6 (PRIOR) | RETAIN unchanged |
| 4 | `src/canonical/calibration.py` pick pricer | round curve {6124/5251/4367/3425/3146/2600} × 0.70^years, tier ±15%, slot interpolation | all PRIOR/stale (contradicting every live constant) | **RETIRED** — deleted outright; the layer now refuses picks (`retired_second_owner_c1u6`); production-dormant, tests-only |
| 5 | `src/bdvm/picks.py` | fundamental pick EV with its own strategy discounts (0.72/0.85/0.93) | PRIOR in its own config | RETAIN — a deliberately SEPARATE named fundamental-value concept; never touches `rankDerivedValue` |
| 6 | `src/api/draft_capital_fallback.py` | slot-name lookup; every future-year pick missed BY DESIGN → unpriced | (7000/4000/2000/1200 table already deleted pre-unit) | ADAPT — future-year picks resolve at the GENERIC grade (§7) |

Consumers verified to read `rankDerivedValue` off the board with no constants of
their own: finder, suggestions, simulator, angle, terminal, public-activity
valuation, waivers (picks excluded by design), Perfect Draft (players only).
Frontend: no pick-value engine (auction-$ in `pick-stack.js` is the separately
named dollar concept, ratios read off the board).

## 3. The measured REDs (all reproduced on the live payload, production build path)

`tests/api/test_pick_completeness_red.py`; raw run: 5/5 failing on `main`.

* **RED-1 cap truncation** — 5 voted 2029 rows (Mid/Late 3rd, E/M/L 4th) carried
  the discount stamp yet published `rankDerivedValue: None` (sorted past
  `OVERALL_RANK_LIMIT`; value-stamping only covered `row_normalized[:800]`).
* **RED-2 no voting source for future rounds 5-6** — 18 valid rows (both leagues
  draft 6 rounds) with zero votes: KTC and IDPTC publish future tiers for rounds
  1-4 only; the raw `ktc` values on those rows are the scraper's model composite
  (retired from voting 2026-04-28).
* **RED-3 uncalibrated clone discount** — 2029 = clone(2028) × 0.53 where the
  market's own observable year-step is ~0.84 (§5); the incumbent sat ~37% below
  every observed cell.
* **RED-4 clone anchor asymmetry** — 2029 rows carried 2028's vendor numbers
  VERBATIM in `canonicalSiteValues`, handing market-anchor consumers (angle's
  `ktc` fallback) an undiscounted anchor against a discounted model value —
  manufactured "arbitrage" on far-future picks.
* **RED-5 no generic-grade value** — `market_resolution` answers an unknown slot
  with the GENERIC grade (C1-U3, frozen), but no generic board row and no
  resolver existed: the honest representation of every unrealized future league
  pick had no canonical value at all.

## 4. Evidence

**Vendor year-step (the only observable year-distance evidence).**
`site_raw/ktcSfTep.csv` + `site_raw/idpTradeCalc.csv` from all 34 archived
export dates (2026-07-14 → 2026-08-16): same-day, same-provider, cross-sectional
ratios `value(2-out)/value(1-out)` per (tier, round) cell, rounds 1-4.  816
cell-days.  Deliberately NOT the raw payload's `ktc` key (scraper composite —
contaminated by its own tier model and clamped discount recalibration) and NOT
the temporal ledger's `source_value` lane for pick tiers (the archive backfill
ingested the payload, so its `ktc` rows inherit the composite; clean
`ktcSfTep`/`idpTradeCalc` lane rows begin with live recording 2026-08-16).
No temporal leakage is possible by construction: both legs of every ratio are
observed simultaneously.  Findings:

* pooled median **0.8407** (mean 0.839, sd 0.051);
* cross-provider agreement within 2% (KTC 0.8546, IDPTC 0.8369);
* time-split drift 0.6% (first-half 0.8399 vs second-half 0.8453);
* real (tier × round) structure BOTH providers agree on independently — Early
  1st decays hardest (KTC 0.7248 / IDPTC 0.7138), the tail flattens;
* IDPTC's pick board is frozen across the window — counted as ONE independent
  observation, not 34.

**Round-step (rounds 5-6, no vendor evidence exists).**  The served canonical
board's own tethered rookie-market round ladder — real market values of actual
round-5/6 assets: R5/R4 ∈ [0.9007, 0.9323], R6/R5 ∈ [0.9128, 0.9182] across six
sampled archive rebuilds.  Rejected alternatives: future-tier trend
extrapolation (~0.75-0.80 — a fitted shape with zero observations of the target
quantity) and the scraper's R5/R6 synthesis (measured non-monotonic).

**Current term structure** (why vendor years stay undiscounted, T-3/C-2):
1-out/current = +26% at R1 falling to +9% at R4, in both providers.

## 5. Champion/challenger — the year-step family

`scripts/calibrate_pick_year_step.py` (pinned inputs: the archive CSVs;
reproducible; leakage-free splits).  Score = absolute percentage error
predicting one provider's observed 2-out tier values from its own 1-out values,
under families fitted WITHOUT that evidence:

| family | params | fit=KTC→eval=IDPTC | fit=IDPTC→eval=KTC | time-split (KTC) |
|---|---|---|---|---|
| incumbent 0.53-on-clone | 1 | 36.7% median | 38.0% | 38.3% |
| config incremental step 0.803 | 1 | 7.1% | 6.9% | 7.0% |
| pooled measured step 0.8407 | 1 | 3.6% | 3.4% | 3.3% |
| per-round measured step | 4 | 2.3% | 2.6% | 1.8% |
| **per-cell measured step** | **12** | **1.4%** | **1.7%** | **1.4%** |

**Promotion decision: the per-cell measured year-step family replaces the
incumbent** for synthetic-year derivation — it wins every leakage-free split
including max-error (9.0/14.4/7.6% vs pooled's 19.7/17.4/19.7%), its 12
parameters are each directly measured medians corroborated by two independent
provider families, and the incumbent is not merely worse but contradicts every
observed cell.  This is exactly the challenger work the unit was chartered to
perform (map §17: "future-pick year discount | PRIOR | validated in C1-U6");
the owner checkpoint reviews this record.  Rollback: revert
`config/weights/pick_year_discount.json` (the old `offsetDiscounts` schema is
gone; reverting the file + `data_contract.py` restores the prior behavior).

**Classification stays PRIOR (measured-anchored), never MEASURED/VALIDATED**,
because the family is fitted on the 1-out→2-out step and applied to the
2-out→3-out step — an extrapolation NO evidence in scope can test (no vendor
publishes 3-out; the archive spans 34 days of one season; a year-rollover
observation of the same class at two distances does not exist yet).  The
assumption is named in the config (`classificationNote`) and here.

## 6. The derivation architecture

* **Year-step at INJECTION** (`_inject_far_future_pick_sources`): cloned
  per-source values are stepped by `_year_step_for(tier, round)`^gap at
  creation, so the blend, the per-source display values, the confidence inputs
  and the published value carry ONE consistent derivation (closes RED-4
  structurally).  Phase 3a (`_apply_pick_year_discount_to_blend`) is stamp-only:
  `pickYearDiscount` = the net factor, consumed by the draft-day projections;
  vendor-priced years remain exempt and unstamped
  (`tests/api/test_pick_year_discount_gate.py`).
* **Off-cap pick value stamping** (Phase 4b'): a pick row that voted keeps its
  value past `OVERALL_RANK_LIMIT` (value only — rank/tier/percentile stay
  capped), the same posture the rookie tether already took.  Player rows past
  the cap are untouched (deliberate top-board behavior).
* **Completeness pass** (Phase 5.2b', `_complete_future_pick_values`): strict
  priority — direct evidence is never overwritten.
  1. round-step: unpriced future tier rows in configured rounds (5-6) derive
     from the same year+tier's nearest priced lower round;
  2. generic grade: a rank-less `"YYYY Round N"` row per future year × round at
     the unweighted mean of the three tier values (uniform-slot EV; C1-U7
     replaces the uniform assumption with real owned-pick distributions);
  3. `pickValueProvenance` stamped on EVERY pick row.
* **Resolver** (`src/api/pick_value_resolution.py`): one owner for
  MarketPickRef→value; slot/tier/generic grades; aliases followed; current-year
  generic = centre-slot convention (labelled); missing → `None` + reason.
* **Build census** (`validate_api_data_contract`): every future tier + generic
  row through the horizon finite + provenance-stamped, no pick 0/NaN — an
  ERROR (contractHealth gate), same posture as `_PICK_COUNT_FLOOR`.

**Provenance schema** (`pickValueProvenance`): `class` ∈ {`direct_market_blend`,
`rookie_pool_tether`, `derived_year_step`, `derived_round_step`,
`derived_uniform_tier_ev`, `alias_suppressed`, `unavailable`}; derivations carry
`family`, `classification: "PRIOR"`, `basis` (row name(s)), `factor`, and
`yearStepFactor` where a year derivation is in the chain; `unavailable` carries
`reason`.  Parameters, versions, evidence pointers and effective dates live in
`config/weights/pick_year_discount.json` (`derivedYearModel` /
`derivedRoundModel` / `genericGradeModel`).

## 7. Consumers

* **Migrated (authorized "stop returning missing/zero"):**
  `draft_capital_fallback._pick_value_from_contract` — future-season picks
  resolve at the GENERIC grade (their generated "slots" are reverse-standings
  stand-ins, not known slots; every pick of one future (season, round) prices
  identically — no fabricated slot certainty).  Consequence: the $1200 pool
  redistributes across BOTH generated seasons again — with real generic values
  this time, not the deleted constants.  `trade_simulator._resolve_asset` —
  roster/trade pick labels that miss the name index route through
  `parse_pick_label` → `market_resolution` → board row (the measured
  silent-drop of every roster pick from before/after aggregates); a
  suppressed-tier hit follows its alias instead of pricing at 0; unparseable
  labels still refuse.
* **Unchanged by design:** finder/suggestions/angle/terminal/public-activity
  (they read the board; completeness reaches them automatically — pinned by the
  census parity test), BDVM (separate named concept), waivers/Perfect Draft
  (picks excluded by design).  The EXPORT surface (`exports/latest/` +
  archive zips) serves the scraper's raw payload + site CSVs — the
  `scraper_blend`/`source_value` lanes in C1-U4's terms, deliberately
  different named quantities from the canonical board — so the acceptance
  chain's "export" leg is the raw-evidence archive, not a second canonical
  value surface; the export-parity test self-skips with that recorded.
* **Deferred with record:** the frontend label-lookup migration onto
  identity-routed lookup (the C1-U3 deferral; the generic-grade rows it needs
  now exist; grammar-parity test holds the lockstep), the intel-ledger re-key
  (C1-U8), `roster_intel`'s never-fed `pick_value=0.0` gameplan field,
  frontend `league-analysis.js:140` missing→0, `trade-retro-value.js`
  pick-history copy-forward (C3-U9 per the aging spec).

## 8. Board effects (measured, `scripts/board_diff.py` before→after)

* 1093 → 1111 rows (+18 generic-grade); picks 144 → 162; priced 812 → 849
  (the diff's own accounting: 23 pick rows newly priced in place + 18 added
  generic rows − 4 cap-margin players; the 23 = 18 round-step completions +
  5 previously cap-truncated voted rows); ranked 740 → 740.
* **Authorized pick movement:** the eleven synthetic 2029 tier rows rose
  +34.7%..+65.3% (the measured step replacing 0.53 on the same basis values);
  2027/2028 vendor rows byte-identical except two tail completions.
* **Player coupling, explained (the STOP-and-explain requirement):** IDP rank
  sources translate onto the IDPTC cross-market backbone, which BY DESIGN
  contains pick rows (IDPTC prices players and picks on one scale).  Repricing
  the synthetic rows re-indexes that backbone by 1-2 positions, so IDP players'
  translated votes shift — measured p50 +0.1%, max −1.3% (Jacob Rodriguez, a
  rookie LB whose α-shrunk subgroup sits in the pick-dense backbone region; the
  2026 Pick 2.01 tether follows him at −0.9%).  There is NO implementation of
  finite 2029 values that leaves players byte-identical: the retired verbatim
  clones already sat in the same backbone at WRONG positions, so keeping,
  moving, or removing them all perturb translations.  The coupling is a direct
  mechanical consequence of the authorized pick repricing through a designed
  shared structure, not an unrelated drift.  Follow-up recorded (§12): whether
  synthetic rows should be excluded from translation pools is its own measured
  decision — exclusion also moves player values.
* **Cap-margin churn:** four tail players (values ≈1140, the board's ranked
  floor) fell out of the top-800 value-stamping window as repriced 2029 rows
  entered it — the same boundary churn every 2-hour refresh produces when
  values fluctuate.
* Rank displacement: 627 rank labels shifted ≤ a dozen positions (mechanical
  consequence of eleven pick rows moving up; player VALUES at those ranks moved
  ≤0.1% except as above).

## 9. Sensitivity (bounded, recorded — not optimized)

* **Year-step**: observed cell range [0.7138, 0.8954]; cross-provider
  disagreement ≤3.4% per cell except late.4 at 8.6% (per-cell band recorded in
  the config's evidence block).
  2029 E1 spans ≈ 3593 × [0.85, 1.12] under ± the disagreement band; under the
  full observed range a 2029 first sits between ~3,600 and ~4,500 vs the
  incumbent's 2,668.  Board-order effect: 2029 firsts sit ranks ~117-136 under
  the champion; they would sit ~123-145 at the low band, ~100-125 at the high —
  never above any 2028 first equivalent (monotonicity holds across the range).
* **Round-step**: R5 = R4 × [0.90, 0.93] observed; the rejected trend
  alternative (0.75) would price 2027 R5 tiers ~1,310 vs 1,624-1,737 — a
  ±300-point band on assets at the board's tail (positions >740).  Nothing
  above round 4 changes under either choice.
* **Generic grade**: mean-of-tiers vs Mid-tier-only differ ≤2% (the tier curve
  is near-symmetric); C1-U7's distributions supersede both.
* **Pathological parameters rejected structurally**: steps clamped to
  (0.05, 1.0] (`test_year_step_rejects_pathological_parameters`) — a
  "future year worth more" parameter cannot ship.

## 10. Year/round behavior

Within every future year: E1 > M1 > L1 > … monotone by round after completion
(round-steps < 1).  Across years at fixed (tier, round): current-year TIER
equivalents < 1-out (the market's real +26%..+9% premium, untouched), 1-out >
2-out > 3-out (measured step < 1).  The one deliberate non-monotonicity — next
year's class priced ABOVE the imminent one — is the market's own measured term
structure, preserved per T-3/C-2, not smoothed away.

## 11. What C1-PICK-02 means here

`market_resolution` (C1-U3, untouched) is the transition; C1-U6 adds the value
half: one `LeaguePickIdentity` resolves finite at every basis along
unknown-slot → tier-from-slot → exact-slot, with the identity constant and no
second asset minted (`tests/api/test_pick_completeness.py::
TestGenericExactSlotTransition`).  Valuation never mutates identity: the
resolver echoes the caller's ref verbatim; the generic grade never becomes
"Mid" outside the legacy formatters that already carried the label.

## 12. Follow-ups recorded, NOT blocking this unit

1. **Scraper rollover year-literals** — `Dynasty Scraper.py` hard-codes "2026"
   slot labels and `(2027, 2028)` tier years; when the sources roll, the
   contract's self-rolling `current_rookie_draft_year()` will be pinned by the
   scraper's stale rebuild.  Manifests at the next class rollover (~May 2027).
2. **Synthetic rows in translation pools** — whether pipeline-invented pick
   rows should be excluded from the IDPTC backbone / source ordinal pools that
   translate OTHER rows (§8).  Its own measured decision; either way moves
   players.
3. **Scraper R5/R6 `ktc` display values** — still emitted (non-voting,
   display-only) and non-monotonic; retiring them touches the scraper's pick
   block.
4. **Frontend consumers** — `league-analysis.js:140` unresolvable-pick → 0 in
   trade-history aggregation; `portfolio-insights.js` stale "board publishes
   nothing for 2029" comment; the label-lookup migration (now unblocked).
5. **`check_product_plan_governance.py`** fails on `main` over four
   unclassified planning-like addendum docs (pre-existing; not CI-wired).
6. **`roster_intel` gameplan `pickValue: 0.0`** — a never-fed parameter
   published as a real $0 (undocumented missing-as-zero on a live field).
7. **IDPTC staleness** — its pick board did not move for 34 days; if it is
   abandoned upstream, the pick blend's second family goes stale silently.
   Worth a freshness note in a future source-health pass.

## 13. What was deliberately NOT done

No C1-U5 confidence work (no new confidence consumer was built — derived rows
stamp buckets through the existing pick vocabulary only).  No C1-U7 owned-pick
distributions, no team-strength/owner inputs anywhere (draft capital prices all
stand-in slots of a future round identically).  No C1-U8 lineage/re-key.  No
trade-engine methodology (engines consume the same board field they always
read).  No projections, no UI redesign, no scraper pick-model rebuild, no new
sources (IDP Guru remains out of scope).  `CANONICAL_V2`, C1-U3 and C1-U4
untouched.  No persisted backfill: the board is deterministic from source data
+ config, so regeneration replaces migration; historical observations remain
C1-U4's and are not rewritten (the ledger will simply record the new values
from the next scrape on — `pipeline_version` distinguishes methodology).
