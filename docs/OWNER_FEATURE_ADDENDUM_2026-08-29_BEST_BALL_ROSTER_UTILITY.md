# Owner Feature Addendum — Dynasty Best-Ball Roster Utility

**Owner decision date:** 2026-08-29  
**Tracking issue:** #1173  
**Status:** OWNER-APPROVED SCOPE / PLANNED  
**Primary product owner:** canonical Trade Analyze / Trade Desk decision contract  
**Related foundations:** exact lineup assignment, Team Strength/Weakness, projections, injury/availability modeling, canonical values, KTC Value Adjustment

## 1. Purpose

Add a roster-conditional dynasty best-ball utility layer to trade analysis without changing canonical standalone player values.

Canonical player value continues to answer **what the asset is worth in the dynasty market/model**. This addendum creates a separate roster-context question: **what does this asset do for this exact roster under this league's best-ball lineup rules?**

The primary use is `/trade` Analyze Trade and the future Trade Desk. The same engine may later power a team-page Roster Efficiency / Redundancy Map.

## 2. Mathematical owner contract

For roster `R`, define expected best-ball lineup utility as:

`F(R) = E[optimal legal weekly lineup score | R, exact league rules]`.

For a proposed trade:

`Best-Ball Lineup Impact = F(R_after) - F(R_before)`.

The model must evaluate the entire legal lineup globally, including Superflex, offensive FLEX and IDP-FLEX eligibility. It must reuse canonical exact lineup/assignment machinery rather than independent per-position greedy approximations.

Player roster utility is conditional on the rest of the roster. A player's standalone canonical value must not be overwritten because his expected lineup utilization is low or high on a particular team.

## 3. Required decision outputs

The engine must provide, at minimum:

- **Best-Ball Lineup Impact:** expected optimal-lineup PPG and/or season delta before versus after the trade.
- **Lineup Entry Probability (LEP):** probability a relevant player appears in the optimal legal lineup under simulated/scenario weekly outcomes.
- **Usable Production / Redundancy:** distinguish raw projected scoring from projected scoring that actually survives competition for lineup slots.
- **Depth Insurance Value:** estimate lineup degradation under plausible starter injury/unavailability states before versus after the trade.
- **Roster Spot Shadow Value:** in unequal-player-count trades, value the gained/lost roster spot using the best realistic retained, replacement, stash or waiver asset rather than treating an empty slot as automatically worth zero.
- **Consolidation / Diversification classification:** identify whether the trade concentrates or spreads roster value and calculate roster-specific impact; there is no universal consolidation premium.
- **Position-specific depth effects:** diminishing returns must emerge from exact lineup demand and roster competition rather than arbitrary depth multipliers.
- **Explainable reasons:** output human-readable evidence for Analyze Trade, e.g. incoming player's lineup-entry probability, outgoing players' redundant utilization, healthy-lineup gain, injury-resilience loss, and roster-slot value.

## 4. Inputs and calibration

Use the best available canonical inputs, including:

- exact league scoring;
- exact league lineup requirements and eligibility;
- canonical player and pick identity;
- current / ROS / weekly projections when trustworthy;
- historical weekly scoring distributions;
- position/player availability and injury assumptions;
- bye weeks;
- empirical or bounded weekly variance and ceiling distributions;
- relevant player/team correlation where it adds independent information;
- realistic replacement/stash candidates for roster-slot valuation.

Missing or untrusted evidence remains explicit. Do not silently convert missing projection, injury or correlation information to zero.

Validate the model first on controlled synthetic cases where expected direction is mathematically known, then on historical weekly data with no-lookahead backtesting and calibration.

## 5. Trade-decision integration

This is a genuinely incremental **roster utility** dimension inside the one canonical Analyze Trade decision contract. It does not replace:

- canonical asset/package equity;
- KTC Value Adjustment as a named external-market consolidation lens;
- independent market corroboration;
- age/window/future-asset analysis;
- positional scarcity/need;
- uncertainty/risk analysis.

Respect lineage. Canonical player values, projections derived from common sources, Monte Carlo centered on those same values, and roster analyses that reuse those inputs must not be counted as independent votes merely because they render in different panels.

The decision engine should be able to distinguish a market-even trade that meaningfully improves usable weekly lineup scoring from one that only increases redundant bench value.

## 6. Product surface

Add a compact **Roster Construction Impact** section to Analyze Trade. At minimum it should expose:

- best-ball expected PPG before and after;
- net lineup-impact delta;
- relevant LEP changes;
- consolidation/redundancy effect;
- injury/depth-resilience delta;
- gained/lost roster-slot value;
- plain-English explanation of why the roster benefits or loses.

Example presentation:

> Strong consolidation opportunity. The incoming WR enters the simulated optimal lineup in 91% of eligible weeks; the two outgoing WRs enter in 28% and 7%. Expected optimal-lineup scoring rises 2.6 PPG. Injury resilience falls 0.4 PPG-equivalent, while the freed roster spot adds 0.3 PPG-equivalent. Net roster utility remains strongly positive.

Later, reuse this engine for a team-page **Roster Efficiency / Redundancy Map** identifying high-utilization core players, useful depth, redundant assets and fragile positional depth.

## 7. Guardrails

1. **Do not change canonical player values because of roster fit.**
2. **Do not invent a second proprietary Value Adjustment solely to encode roster utility.**
3. Preserve exact KTC VA as a separate market lens.
4. Best Ball Mania tournament advancement, finals and championship-equity statistics are **not** direct inputs to this dynasty best-ball model. Public best-ball research may inform methodology only where structurally transferable.
5. Tournament payout/upper-tail optimization is out of scope for this league's weekly dynasty-best-ball decision objective.
6. FLEX must be modeled globally; WR/RB/TE depth cannot be valued in isolation when they compete for shared lineup slots.
7. Unequal-package trades must account for the roster spot gained/lost.
8. Injury resilience and healthy-week efficiency must remain separately visible before synthesis.
9. Any roster-context recommendation must preserve market-value truth: a redundant player can still be highly valuable in trade even if his marginal scoring utility to the current roster is low.

## 8. Relationship to existing owner decisions

This addendum deepens the already-approved direction that **roster marginal impact is a major genuinely incremental trade dimension** and that Analyze Trade must synthesize unique-information dimensions without double counting. It specifies the previously missing dynasty-best-ball mechanics required to make that roster-impact dimension decision-grade.

It should be reconciled into `docs/OWNER_REQUESTED_TODO.md`, `docs/OWNER_FEATURE_INVENTORY.md`, the appropriate scope manifest/roadmap, and `docs/EXECUTION_PLAN.md` only when the normal planning/authorization workflow schedules implementation.