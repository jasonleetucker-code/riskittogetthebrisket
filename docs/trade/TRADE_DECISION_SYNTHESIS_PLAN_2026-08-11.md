# Trade Decision Synthesis Plan — 2026-08-11

**Owner status:** approved product/methodology scope.  
**Implementation status:** planning/audit only; do not interrupt the currently isolated B2 work.

## Why this exists

The Trade Calculator now exposes several useful but overlapping lenses: canonical side values, KTC-style package/value adjustment, a Monte Carlo value-distribution simulation, per-vendor "Second Opinions", and roster/team impact. The owner wants two things:

1. confidence that the Monte Carlo math still reflects the current value architecture rather than assumptions from an older version of the site; and
2. one deliberate **Analyze** action that can synthesize the available evidence into an actionable recommendation from the selected team's perspective.

The central architectural rule is that these panels are **not independent votes**. A good decision layer must reason about lineage and unique information rather than add every displayed number together.

---

## A. Current Monte Carlo semantics to audit

At current HEAD, the Monte Carlo trade simulator is fundamentally an **asset-value uncertainty simulation**, not a full roster/trade-outcome simulation.

The live frontend centers each player's simulated band on `effectiveValue(row, valueMode, settings)`, which is the same trade-workspace value used by the trade builder and honors a temporary per-player custom value. League/value adjustments already baked into `row.values.full` therefore flow into Monte Carlo indirectly.

The frontend also requests `applyConsolidationAdjustment: true`, so the backend Monte Carlo path can apply the KTC-style consolidation/value-adjustment lens to the sampled side values.

However, the simulator does **not** inherently consume independent roster-impact, Team Strength/Weakness, second-opinion tallies, future strategic fit, or other trade-analysis panels. Those belong outside the Monte Carlo distribution unless a defensible probabilistic model specifically represents them.

### Known/current concerns that require a fresh HEAD audit

- The current frontend synthesizes a flat ±15% value band when the row has no stamped `valueBand`; historical/current docs state that live rows have not had real source-derived value bands stamped. This makes the simulation stable but the uncertainty width largely an assumption.
- The simulator currently uses uniform positive same-team / same-position-group correlation knobs (`same_team_rho=0.25`, `same_pos_group_rho=0.10`). A richer `src/trade/correlation_matrix.py` exists, but repository search shows no live production consumer. Its hard-coded pairwise rhos are themselves assumptions and require evidence before use.
- The current Monte Carlo is expected to favor the side with the larger adjusted p50 total most of the time. That is not itself a bug: if both sides receive similarly-shaped uncertainty distributions, a center-value lead should usually win more draws. What must be audited is whether the center, distribution width/shape, package adjustment and correlation structure are defensible.
- Current product governance distinguishes exact KTC value-adjustment parity as a **secondary/advisory** KTC lens from the future canonical roster-aware package methodology. The Monte Carlo audit must determine whether applying KTC VA inside its default output is correctly labeled or improperly contaminates a canonical recommendation.
- Current trade-simulation/team-impact code has separate heuristics and weights; Monte Carlo must not silently absorb those as if they were independent probabilistic evidence.

### Required Monte Carlo revalidation

1. Trace current UI asset → `effectiveValue` → request payload → backend `TradePlayer` → band → package adjustment → correlations → simulation → symmetrization/enrichment → rendered result.
2. Verify manual trade-value overrides, TE-premium-adjusted values, future-pick discounts, IDP values and any other canonical upstream value changes all reach the MC center exactly once.
3. Reproduce same-side/swap symmetry, tie handling, mean preservation, seed reproducibility and convergence.
4. Verify the result is not biased by the 1–9999 product scale or endpoint handling.
5. Replace or calibrate the flat ±15% band only if defensible evidence exists; otherwise label the MC explicitly as a sensitivity analysis rather than pretending to know true probability.
6. Investigate a real source-derived uncertainty model using normalized per-source contributions / historical value movement / confidence, with source correlation and missingness handled correctly. Do not treat 14 correlated sources as 14 independent observations.
7. Validate or replace the correlation model. Same-NFL-team correlation can differ by relationship (QB-WR, competing RBs, starter-backup, etc.) and is not universally +0.25; position-group-wide correlation across all offense is especially broad.
8. Separate **KTC-parity MC** from any future **canonical site decision uncertainty** if their package methodologies differ.
9. Backtest/retrospect where a falsifiable target exists. If there is no defensible outcome target for "which side won the dynasty trade", do not manufacture one. Monte Carlo should quantify uncertainty in value, not claim real-world probability of future trade success.
10. Return honest provenance/coverage for every simulated asset and a useful convergence/error diagnostic.

---

## B. Quick Second Opinions verdict

The existing `TradeSourceBreakdown` already computes a winner and margin per independent vendor (sub-boards are rolled up by vendor). Add a very fast summary above the detailed table, e.g.:

> **Second opinions: Side A 5 · Side B 3 · Even 1 · 2 incomplete**

### Critical methodology rule

The summary should distinguish a vendor's **native opinion** from rows that are completed using our own canonical value. The existing component defaults to filling uncovered pieces with our value for comparability. That is useful for the detailed table, but an imputed row is not a fully independent external vote.

Preferred aggregate semantics:

- count once per independent vendor/network, not once per sub-board;
- native-covered vote when enough of the proposed trade is actually covered to make a defensible side comparison;
- otherwise classify as PARTIAL/INCOMPLETE rather than quietly turning our own value into the vendor's vote;
- optionally show a separate "with imputation" tally for diagnostics, never confuse it with independent consensus;
- report coverage and margin strength, not only raw vote count.

---

## C. Canonical Analyze / Trade Decision Synthesis

### Product job

After assets are entered, one **Analyze Trade** action should answer from the selected fantasy team's perspective:

- **MAKE THE TRADE**
- **LEAN MAKE**
- **TOO CLOSE / DEPENDS**
- **LEAN PASS**
- **PASS**

The owner ultimately wants a simple actionable answer, but the product must not force false certainty when strong independent dimensions disagree.

### Do not implement as a naive weighted average of visible panels

Many panels reuse the same underlying values/sources:

- canonical site value is already blended from ranking/value sources;
- Second Opinions are many of those same sources viewed individually;
- Monte Carlo is centered on the same canonical trade values;
- KTC Value Adjustment is also included in some trade/MC views;
- roster impact uses canonical player values to measure before/after fit.

Therefore a formula like `30% value + 20% MC + 20% second opinions + 30% team impact` would **double/triple count the same evidence** and create false confidence.

### Recommended decision architecture: unique-information dimensions

The canonical decision engine should synthesize dimensions by what *new information* they add:

1. **Canonical asset/equity value** — one source of truth for the site's player/pick value and package methodology.
2. **Market corroboration / disagreement** — external vendor opinions summarized with independence/coverage; primarily confidence/explainability unless a leave-one-out design proves additional value.
3. **Uncertainty / risk** — Monte Carlo or another calibrated uncertainty model around the value conclusion; a confidence modifier, not a second vote for the same p50 values.
4. **Roster marginal impact** — before→apply→rerank→after Team Strength / starting-group displacement / Team Weakness / roster construction; this is genuinely incremental information beyond raw asset equity.
5. **Future-asset / window context** — picks, age/window, liquidity or contention context only where canonical methodology is validated; avoid duplicate "contender" heuristics.
6. **Optional intelligence context** — later Consensus Edge / market comps / Sharp / manager fit / news only where each brings independent evidence and is fresh enough to act on.
7. **Constraints/owner policies** — untouchable/excluded assets and future explicit owner policy can veto or qualify a recommendation, but hidden preferences must not be inferred.

### Suggested synthesis behavior

Rather than scoring every raw metric directly, normalize each independent dimension into:

- direction: favors selected team / neutral / opposes;
- magnitude;
- confidence/coverage;
- provenance/freshness;
- dependencies/lineage.

Then produce:

- final recommendation;
- confidence (LOW/MEDIUM/HIGH or calibrated probability only if evidence supports one);
- top 3 reasons **for**;
- top 3 reasons **against**;
- disagreements/uncertainties;
- "what would change the answer" where useful.

### Example

> **LEAN MAKE THE TRADE** — medium confidence
>
> **Why:** +620 canonical marginal value; improves WR top-5 group and fills a major weakness; 5 of 7 independently-covered market vendors favor your side.
>
> **Risk:** gives up the most liquid asset; value-uncertainty simulation is only 57/43 and still uses synthetic bands.
>
> **Roster effect:** Team Strength +1,340; WR weakness MAJOR → MINOR; RB depth declines.

The exact numbers are illustrative only; implementation must consume current canonical services.

### Backtesting / governance

A final recommendation engine is high-impact and must be testable. Do not tune weights simply until recommendations "look right".

Where historical completed trades and contemporaneous values exist, test whether the engine's **stated components** reproduce what was knowable at trade time. Outcome labels require a clearly defined target (e.g. subsequent canonical value change, realized scoring contribution, roster strength change) and must not use present/future information in historical inputs.

If no single objective ground truth exists for "good dynasty trade", preserve a transparent multi-objective recommendation rather than pretending a supervised model has an objective label.

---

## D. Relationship to existing canonical plans

This work should extend/reconcile existing Trade Calculator, roster-aware trade simulation, package adjustment, Team Strength/Weakness, CE-05 Trade Desk and future CE-01 market comps. It must **not** create parallel value, package, roster-impact or source-consensus engines.

The eventual CE-05 Trade Desk should become the natural home for the full synthesis, while the existing `/trade` calculator can expose the Analyze action earlier once dependencies are trustworthy.

## Coordination

Do not interrupt isolated B2. First audit the current Monte Carlo after the current foundational checkpoint. Build the unified decision synthesis only after canonical value/package/Team Strength/Weakness/roster-impact dependencies are reliable enough that the synthesis is not merely combining broken inputs.