# OWNER DIRECTIVE (verbatim) — 2026-10-19 (evening) — MASTER IMPLEMENTATION DIRECTIVE: BRISKET LEAGUE INTELLIGENCE & ULTIMATE TRADE DECISION ENGINE

Coordinator note (not owner text): received in chat 2026-10-19 ~20:54 UTC. Saved verbatim below. Precedence: newest owner directive on league-aware valuation and the trade decision engine; earlier directives stay in force where not in conflict.

MASTER IMPLEMENTATION DIRECTIVE

BRISKET LEAGUE INTELLIGENCE & ULTIMATE TRADE DECISION ENGINE

Repository: "jasonleetucker-code/riskittogetthebrisket"

Primary League: Risk It To Get The Brisket

Sleeper League ID: "1312006700437352448"

Priority: CRITICAL — CORE PRODUCT INTELLIGENCE

Operating Mode: Maximum Velocity Parallel Development

Authorization: Implement approved improvements immediately, validate objectively, and integrate using our established autonomous merge procedures.

---

1. THE ULTIMATE OBJECTIVE

I want Risk It To Get The Brisket to become an exceptionally sophisticated, league-aware dynasty fantasy football intelligence platform.

Every improvement we're developing—including projections, advanced statistics, league scoring, roster construction, Best Ball optimization, positional scarcity, player valuation, aging curves, injury risk, and predictive modeling—must ultimately contribute to making better fantasy football decisions.

The Trade Calculator is the most important destination for this intelligence.

Its fundamental purpose is to answer one question:

SHOULD I MAKE THIS TRADE?

Not simply:

"Are both sides approximately equal in market value?"

Not simply:

"Which side has more projected points?"

Not simply:

"Which team receives the more valuable players?"

I want the system to evaluate everything relevant and ultimately tell me:

YES — I recommend making this trade.

or

NO — I recommend declining this trade.

I want the most accurate recommendation our available information and defensible mathematics can support.

The recommendation should be personalized to the actual roster, league, and competitive situation.

I recognize that no model can predict the future perfectly.

However, I want the system to use as much credible evidence as possible, understand uncertainty, and consistently make decisions supported by that evidence.

Do not confuse using more inputs with creating a better model. Every input must provide defensible information.

---

2. THIS IS AUTHORIZATION TO IMPROVE CANONICAL PLAYER VALUES

This is an important owner decision.

I believe our league's scoring system and roster construction affect what players are worth.

Our league is not a generic dynasty league.

It has unusual scoring rules, mandatory tight-end starters, Superflex, deep rosters, significant IDP requirements, and Best Ball.

Those differences can substantially change the value of individual players.

Therefore, I do not want league-specific intelligence permanently isolated from player valuation.

I authorize the development, testing, and evidence-based adoption of league-aware player values throughout the site.

However, that authorization is conditional on mathematical validity.

Distinguish two concepts

Observed Market Value

The actual value published by an external source or inferred from observed dynasty transactions.

Brisket League Fair Value

Our independently calculated estimate of what a player should be worth under our actual league rules.

The second can differ from the first.

Do not falsify or overwrite external sources' published market values.

Instead, preserve their actual observations and use them as inputs or independent benchmarks.

Our canonical Brisket player values may incorporate league-specific effects once those effects are validated.

Critical existing research

Read:

"docs/valuation/LEAGUE_AWARE_METHODOLOGY_REJECTION.md"

The previous league-adjusted model was rejected for legitimate mathematical reasons.

Do not simply restore it.

Develop a superior methodology that addresses those findings.

I do not want arbitrary positional multipliers.

I want adjustments supported by measurable differences in expected production, replacement value, scarcity, and multi-year usefulness.

A player should not become 12% more valuable just because someone assigns his position a 1.12 multiplier.

If his value increases, the system must have a credible explanation grounded in the expected contribution of that player under our particular league rules.

Canonical value requirement

Once a challenger model passes the established validation gates, the league-aware Brisket value should become eligible for adoption as the authoritative player value.

That value must be:

- Deterministic for a particular model and evidence snapshot.
- Consistent across devices.
- Consistent across pages.
- Reproducible.
- Versioned.
- Mathematically bounded.
- Properly calibrated.
- Resistant to noisy data.
- Protected against double-counting.
- Reversible if later evidence shows regression.

Do not activate a new model merely because its code passes CI.

Establish objective promotion thresholds before examining final holdout results.

If those thresholds are met, follow the existing model-governance process and use this directive as the owner's conditional authorization for the validated methodology, to the extent permitted by repository policy.

If the established governance requires a separate explicit owner approval, preserve that requirement and present the evidence and promotion decision together rather than bypassing it.

If the evidence is insufficient, keep the model experimental and continue collecting data.

---

3. FIRST: RECONCILE EXISTING WORK

Before implementing anything, inspect the latest repository state.

Specifically examine:

- PR #1843 — League intelligence audit and research.
- Issue #1842 — Complete league-intelligence implementation.
- PR #1836 — Trade Calculator integration train.
- Existing Best Ball trade utility work.
- Existing Value Adjustment implementation.
- Existing Second Opinions implementation.
- Existing projection-source integrations.
- Existing source voting and freshness work.
- Existing player-value normalization.
- Existing mathematical modeling and calibration policies.

Also inspect the implementation and status of:

- "src/api/data_contract.py"
- "src/league_intel/"
- "src/scoring/"
- "src/ros/"
- "src/bdvm/"
- "src/trade/"
- "src/roster_intel/"
- "src/valuation_math/"
- "src/model_registry/"
- "src/nfl_data/"

Treat these as starting points, not a complete inventory.

Reuse working systems.

Do not create competing implementations.

Respect the latest owner-approved scoring, source-voting, and Value Adjustment directives.

Do not overwrite active development from another agent.

---

4. BUILD A COMPLETE EXACT-LEAGUE PROJECTION SYSTEM

Our first major requirement is accurate player projections under our actual scoring rules.

Retrieve and validate the current Sleeper configuration.

Then build upon our existing scoring and projection infrastructure.

Required projections

We need statistical projections for:

- Weekly production.
- Rest-of-season production.
- Full-season production.
- Future seasons where defensible.

Include:

- Quarterbacks.
- Running backs.
- Wide receivers.
- Tight ends.
- Kickers.
- All relevant IDP positions.
- Rookies and prospects where supportable.

Use the exact league scoring engine.

Do not substitute generic projected fantasy points when raw statistical categories are available.

Offensive scoring

Account for:

- Passing attempts.
- Completions and incompletions.
- Passing yards.
- Passing touchdowns.
- Interceptions.
- Passing and rushing first downs.
- Rushing attempts.
- Rushing yards.
- Rushing touchdowns.
- Targets.
- Receptions.
- Reception-distance scoring bands.
- Receiving yards.
- Receiving touchdowns.
- Fumbles.
- Return production.
- Other applicable bonuses.

Defensive scoring

Account for:

- Defensive snaps.
- Solo tackles.
- Assisted tackles.
- Tackles for loss.
- Quarterback hits.
- Sacks.
- Sack yardage.
- Interceptions.
- Passes defended.
- Forced fumbles.
- Recoveries.
- Return yardage.
- Defensive touchdowns.
- Other relevant scoring categories.

Preserve correlations between events.

For example, a sack may also produce a tackle for loss, quarterback hit, and tackle.

Our scoring system can award points for multiple events occurring on the same play.

The projection model must understand these relationships.

Statistical distributions

Do not limit projections to one expected number.

Where evidence supports it, estimate distributions containing:

- Expected outcome.
- Median.
- Variance.
- Useful percentiles.
- Ceiling outcomes.
- Downside outcomes.
- Availability uncertainty.

Use calibrated probabilities and predictive distributions.

Do not manufacture precision when a data source lacks sufficient statistical information.

---

5. EXPAND OUR PROJECTION AND STATISTICAL DATA SOURCES

Use the research from PR #1843 and Issue #1842 as the starting point.

Investigate all relevant providers identified in that research.

Prioritize getting existing integrations working before building duplicate acquisition systems.

Particular candidates include:

- Sleeper.
- Fantasy Nerds.
- SportsDataIO.
- ESPN / Mike Clay.
- The IDP Show.
- FantasyPros.
- DraftSharks.
- nflverse.
- Other credible statistical and projection providers.

Source integration requirements

For every source, verify:

1. Actual available statistical categories.
2. Player and positional coverage.
3. Forecast horizon.
4. Historical coverage.
5. Forecast accuracy.
6. Data freshness.
7. Source independence.
8. Acquisition permissions.
9. Redistribution restrictions.
10. Incremental predictive value.

A source that only publishes rankings is not automatically a statistical projection provider.

A source that republishes another model is not independent evidence.

A source that cannot be acquired or used under an authorized arrangement must remain unavailable for production ingestion.

Do not fabricate missing statistics.

Projection ensemble

Develop and validate a multi-source ensemble.

Compare:

- Individual providers.
- Equal-family averages.
- Median ensembles.
- Robust consensus methods.
- Reliability-weighted ensembles.
- Internal statistical models.

Learn reliability weights from historical performance when sufficient evidence exists.

Do not assign weights merely because a source is popular.

Account for provider correlation so multiple versions of the same underlying forecast do not create artificial confidence.

Use different models or weights where appropriate for:

- QB.
- RB.
- WR.
- TE.
- DL.
- LB.
- DB.
- K.

A projection provider may be strong at offensive forecasting and weak at IDP.

Our weighting should be capable of recognizing that.

---

6. BUILD A BETTER LEAGUE-SPECIFIC PLAYER VALUATION MODEL

This is one of the most important implementation requirements.

I want the model to understand what players are genuinely worth under our league rules.

Evaluate the combined influence of:

A. Exact scoring

How much fantasy production does this player's particular statistical profile generate under our rules?

B. Positional scarcity

How difficult is it to replace that production?

C. Roster requirements

How many players at that position must start?

D. League size

How many teams are competing for those players?

E. Roster depth

How do our deep rosters affect replacement quality and the availability of usable players?

F. Best Ball

How much does the player's weekly scoring distribution contribute to optimal lineups?

G. Player longevity

How much useful production can we reasonably expect over future seasons?

H. Player development

How likely is the player's role and production to improve or decline?

I. Availability

What is the probability that the player remains available and productive?

J. Market evidence

How does our calculated league-specific utility compare with actual dynasty market valuations?

Each of these factors must be considered.

However, this does not mean assigning arbitrary positive weight to every category.

If a factor has little evidence, high uncertainty, or duplicates another factor, its effective contribution may legitimately be very small or zero until it can be supported.

The objective is to use all credible information, not to force all information into the final formula.

Proposed mathematical direction

Investigate using market value as a prior.

Then calculate the incremental contribution of reliable league-specific information.

For each player, estimate:

1. Baseline market valuation.
2. Expected production under our scoring.
3. Expected replacement-adjusted production.
4. Expected Best Ball contribution.
5. Multi-year expected contribution.
6. League-specific scarcity effects.
7. Confidence in those estimates.

Calibrate the relationship between these quantities and actual dynasty market values.

Use historical observations and out-of-sample testing to determine how strongly the model should rely on each estimate.

Consider regularization, Bayesian shrinkage, constrained calibration, and other appropriate techniques.

A strong market prior should protect against an unproven model dramatically repricing players.

Stronger independent evidence should permit more meaningful adjustments.

Do not multiply the existing 0–9999 ranking-derived value directly by an arbitrary adjustment factor.

Use a mathematically appropriate transformation and recalibration that preserves the established value scale.

Superflex and tight ends

Be especially careful with double-counting.

Many existing dynasty market sources already assume Superflex.

Our current board also uses TE++ source alignment.

Do not apply another generic Superflex or tight-end multiplier simply because our league uses those formats.

Measure what is already represented in the baseline, then calculate only the incremental league-specific effect not already included.

IDP

Investigate whether our unusual defensive scoring meaningfully changes the relative value of individual defenders.

I particularly want us to identify players whose statistical profiles are especially advantageous under our scoring system.

Do not limit this to generic DL, LB, and DB multipliers if player-specific evidence supports a better approach.

But do not promote noisy individual-player adjustments that fail historical validation.

---

7. IMPLEMENT TRUE BEST BALL PLAYER UTILITY

Our league uses Best Ball.

Our player valuation and trade recommendations must understand this.

A player who occasionally produces 25 points may have a different contribution than a player who consistently produces 12 points.

That difference depends on the rest of the roster.

Build upon our existing Best Ball utility engine.

For every simulated week:

1. Determine player availability.
2. Project individual performance distributions.
3. Sample coherent statistical outcomes.
4. Apply exact league scoring.
5. Optimize the complete legal starting lineup.
6. Calculate the resulting team score.
7. Repeat across a sufficient number of simulations.

Account for all 21 starting positions and applicable eligibility rules.

Include:

- Offensive starters.
- Superflex.
- Mandatory tight ends.
- Offensive Flex.
- Kicker.
- DL.
- LB.
- DB.

Include bye weeks, injuries, uncertain availability, and projected role changes when defensible.

Preserve realistic dependencies within games and among related player outcomes.

Marginal player value

For roster-specific calculations, simulate the team with and without a player.

Estimate:

Marginal Best Ball Utility = Expected Optimal Team Production With Player − Expected Optimal Team Production Without Player

Use an appropriate replacement scenario when the player is removed.

Do not assume an empty roster spot is always the correct alternative.

This allows us to measure the player's actual incremental contribution rather than merely summing projected individual points.

Use this as an important input to roster analysis and trade recommendations.

---

8. IMPLEMENT DYNASTY-HORIZON INTELLIGENCE

The site must understand that dynasty players have value beyond the current season.

Develop defensible forecasts incorporating:

- Current production.
- Future production.
- Player age.
- Position-specific aging curves.
- Player development.
- Role security.
- Injury and availability uncertainty.
- Expected career duration.
- Rookie uncertainty.
- Future team situation.
- Multi-season upside and downside.

Use appropriate forecast horizons.

Do not treat year-three projections as equally reliable as next week's projections.

Model uncertainty explicitly.

Where available, use historical player trajectories and position-specific development patterns.

Competitive window

Different teams have different strategic objectives.

A contender may rationally prefer a productive veteran.

A rebuilding team may rationally prefer a younger player or future draft capital.

Use the existing roster and championship intelligence to estimate the manager's competitive window.

Avoid reducing the entire decision to a single arbitrary win-now multiplier.

The value of competitive timing should arise from projected team outcomes over relevant seasons.

---

9. BUILD THE ULTIMATE TRADE DECISION ENGINE

THIS IS THE PRIMARY PRODUCT GOAL

All this intelligence must feed the Trade Calculator.

The existing Trade Calculator should evolve into a comprehensive decision engine.

Do not create a separate calculator that competes with our current one.

Enhance its authoritative backend evaluation system and existing frontend experience.

Every completed trade evaluation should consider the following dimensions.

DIMENSION 1 — Canonical player value

Evaluate the market and Brisket league-aware values of all assets.

Include the existing Value Adjustment methodology.

Preserve distinctions between:

- Player valuation.
- Package-size adjustment.
- Trade fairness.
- Roster-specific utility.

Do not apply the same effect multiple times.

DIMENSION 2 — Exact-league projected production

Calculate how the trade changes projected production under our scoring system.

Account for every relevant scoring category.

DIMENSION 3 — Best Ball impact

Calculate how the trade affects expected optimal weekly lineup performance.

This must account for the actual roster receiving or losing each player.

DIMENSION 4 — Championship probability

Estimate how the trade changes the team's probability of winning the championship.

Use the existing simulation infrastructure where possible.

Avoid claiming more precision than the data supports.

DIMENSION 5 — Future competitiveness

Determine how the trade affects the team's expected performance beyond the current season.

Include multi-year forecasts and championship windows.

DIMENSION 6 — Positional scarcity

Consider the availability of replacement players and the depth of the position.

DIMENSION 7 — Roster construction

Consider:

- Starting lineup requirements.
- Roster depth.
- Roster capacity.
- Bench composition.
- Positional needs.
- Available replacements.
- Bye-week coverage.
- Redundant assets.
- Potential waiver replacements.

A player can have substantial market value while providing relatively little incremental benefit to a particular roster.

DIMENSION 8 — Age and development

Consider player trajectories and future value.

DIMENSION 9 — Injury and availability

Consider availability, expected recovery, and downside uncertainty using defensible forecasts.

DIMENSION 10 — Draft capital

Include:

- Current rookie-pick values.
- Future rookie-pick values.
- Pick-year uncertainty.
- Draft-class strength.
- Expected pick position.
- Opportunity cost.
- Multi-year team strategy.

Do not treat an unknown future pick position as guaranteed.

DIMENSION 11 — Trade package mathematics

Continue using our approved Value Adjustment approach.

Keep package concentration, roster-slot effects, and raw player valuation mathematically distinct.

Do not let a package adjustment double-count an effect already captured by the marginal roster simulation.

DIMENSION 12 — Risk and uncertainty

Evaluate:

- Projected upside.
- Projected downside.
- Volatility.
- Player uncertainty.
- Injury uncertainty.
- Model disagreement.
- Forecast horizon.
- Data freshness.

Use calibrated uncertainty rather than simply labeling players risky.

DIMENSION 13 — Market evidence and alternative opportunities

Consider:

- External valuations.
- Comparable trades.
- Historical trade information.
- Our trade-derived valuation model when validated.
- Alternative obtainable players.
- Opportunity cost.

Historical transactions should be evaluated under their actual past information, not today's future-informed estimates.

DIMENSION 14 — Manager-specific context

Where appropriate, consider:

- Competitive window.
- Trading tendencies.
- Positional preferences.
- Roster needs.
- Existing assets.
- Trade history.

Manager tendencies can inform whether another manager might accept a trade.

They should not masquerade as evidence that the trade improves our roster.

DIMENSION 15 — League-specific strategic rules

Evaluate any additional relevant features of our league, including settings that influence:

- Starting lineups.
- Rosters.
- Playoff qualification.
- Best Ball scoring.
- Waivers.
- Pick ownership.
- Transaction eligibility.

Do not invent salary-cap or contract restrictions that our current Sleeper league does not have.

---

10. THE MATHEMATICS OF YES OR NO

This is the most important modeling decision.

Do not determine the recommendation by arbitrarily adding fifteen percentages together.

Many of those inputs are correlated.

For example:

- Projected fantasy points influence Best Ball performance.
- Best Ball performance influences championship probability.
- Championship probability influences competitive-window strategy.

If we independently add all three as separate bonuses, we could count the same improvement repeatedly.

Instead, develop a hierarchical decision model.

Recommended architecture

Layer A — Asset evaluation

Estimate the market and league-aware value of each asset.

Layer B — Forecasting

Estimate player outcomes and uncertainty.

Layer C — Roster simulation

Determine the expected incremental value of the assets to the receiving roster.

Layer D — Competitive outcomes

Calculate how the revised roster affects expected season results and future competitiveness.

Layer E — Trade decision

Compare the expected strategic utility of accepting the trade against declining it.

Use an explicit, validated decision objective.

For example:

"Decision Advantage = Expected Team Utility After Trade − Expected Team Utility Before Trade"

This is the central idea, not a requirement to use a simplistic one-number formula.

Expected Team Utility should incorporate current and future team outcomes, their uncertainty, the team's competitive window, and the opportunity cost of the exchanged assets.

Where factors overlap, use conditional modeling or residual information rather than rewarding the same signal twice.

Confidence weighting

I want the math to determine how heavily each type of information should influence the decision.

Investigate:

- Empirical reliability weighting.
- Bayesian shrinkage.
- Regularized models.
- Calibrated predictive distributions.
- Model averaging.
- Out-of-sample validation.
- Sensitivity analysis.

Confidence must reflect demonstrated reliability and data coverage.

Do not simply set:

- Market value = 30%.
- Projections = 25%.
- Best Ball = 20%.
- Age = 15%.
- Injuries = 10%.

Unless actual validation supports those allocations.

The weights should be based on evidence, not convenience.

Small differences

Avoid overreacting to marginal projected improvements.

For example, a trade producing an estimated 0.1% championship improvement may be indistinguishable from no improvement given uncertainty.

Evaluate the distribution of possible outcomes.

Determine whether the apparent advantage is meaningful.

When the model has enough evidence to make a decision, provide YES or NO.

For genuinely borderline trades, provide the binary recommendation with an appropriately low-confidence explanation. An optional NEUTRAL/WAIT label may supplement the recommendation but must not replace the actual answer.

If essential data is missing and the system cannot responsibly evaluate the trade, explicitly report INSUFFICIENT EVIDENCE rather than inventing a confident recommendation.

Default decision posture

When expected advantages are effectively indistinguishable, prefer retaining the existing roster rather than manufacturing a trade advantage.

This is a conservative decision policy, not an excuse to reject trades that show defensible improvements.

---

11. TRADE CALCULATOR OUTPUT REQUIREMENTS

The user-facing experience must remain simple.

I don't want a wall of mathematical diagnostics when I evaluate a trade.

The default result should provide:

THE RECOMMENDATION

A clear:

YES — MAKE THIS TRADE

or

NO — DECLINE THIS TRADE

CONFIDENCE

Display a calibrated confidence assessment.

Do not produce a numerical percentage unless it has a defined, tested meaning.

THE THREE BIGGEST REASONS

Explain why the system recommends accepting or declining.

For example:

1. The trade improves our expected Best Ball lineup production.
2. We sacrifice too much long-term dynasty value.
3. Our replacement options at linebacker are weak.

These are examples, not predetermined conclusions.

THE KEY NUMBERS

Where credible, display before-and-after estimates for:

- Brisket player value.
- Market-value difference.
- Weekly Best Ball scoring.
- Championship probability.
- Multi-year outlook.
- Roster depth.
- Risk.

WHAT COULD CHANGE THE RECOMMENDATION?

Identify meaningful uncertainty.

Examples:

- A player's recovery.
- A projected role change.
- A missing projection source.
- A change in competitive outlook.

EXPANDED ANALYSIS

Allow interested users to inspect:

- Model inputs.
- Projection sources.
- Mathematical contributions.
- Confidence.
- League scoring effects.
- Roster-construction effects.
- Simulation results.
- Data freshness.

The advanced analysis must be available without overwhelming the primary recommendation.

Two-sided evaluations

The decision must be evaluated separately for each team.

A trade can be:

- Good for both teams.
- Good for one team and bad for the other.
- Bad for both teams.

Do not infer that one side's gain equals the other side's loss.

A trade may improve both teams because their rosters and competitive situations differ.

---

12. APPLY THE INTELLIGENCE THROUGHOUT THE SITE

Do not implement this only inside the Trade Calculator.

The same validated systems should benefit:

- Player Rankings.
- Player Profiles.
- Second Opinions.
- Trade Finder.
- Golden Trades.
- Package Scanner.
- Trade Simulator.
- Trade History.
- Public League Hub Trade Advisor.
- Roster Intelligence.
- Power Rankings.
- Team Strength.
- Draft Capital.
- Rookie Evaluation.
- Perfect Draft.
- Waiver Recommendations.
- FAAB Recommendations.
- Game Day.
- Matchup Predictions.
- Playoff Simulations.
- Championship Probability.
- Manager Intelligence.

However, each feature should consume the appropriate information.

For example:

Historical Trade Analysis should use historically available information and the appropriate historical scoring configuration.

A current trade recommendation should use the latest legitimate evidence.

A public trade advisor should not expose private manager information or confidential calculations.

The canonical Brisket player value should have one authoritative calculation.

Roster-specific strategy should be applied after the canonical value is established.

Do not give the same player contradictory canonical values across different pages.

---

13. HISTORICAL VALIDATION AND PROTECTION AGAINST DATA LEAKAGE

This is mandatory.

Develop a rigorous historical testing framework.

Use chronological training and testing.

A historical prediction must only use information that was available when the prediction would have been made.

Prevent:

- Future statistics leaking into historical projections.
- Later injury reports leaking into earlier predictions.
- Revised forecasts being used as original forecasts.
- Future roster information leaking backward.
- Current player values replacing historical prices.
- Future trades influencing past trade recommendations.
- Model tuning against supposedly independent holdouts.
- Survivorship bias.
- Scoring changes being applied to seasons with different rules.

Compare models

Evaluate:

1. Existing production model.
2. Exact-league projection model.
3. Improved positional scarcity model.
4. Best Ball utility model.
5. Multi-source projection ensemble.
6. Dynasty-horizon model.
7. Combined league-aware valuation model.
8. Complete trade decision model.

Do not assume combining models automatically improves performance.

What we need to measure

Depending on the model, evaluate:

- Projection accuracy.
- Calibration.
- Player ranking quality.
- Fantasy scoring accuracy.
- Positional replacement accuracy.
- Weekly lineup accuracy.
- Championship prediction calibration.
- Multi-year forecasting.
- Trade decision outcomes.
- Model stability.
- Reliability across player types.

Recognize that accepted historical trades are a selected sample, not a complete dataset of accepted and declined opportunities.

Do not train a supposedly optimal YES/NO decision policy solely by labeling completed trades as good decisions.

Production promotion

Define acceptance thresholds before final testing.

Require:

- Meaningful improvement on relevant held-out metrics.
- Sufficient sample size.
- No unacceptable regression in important positional cohorts.
- No scoring errors.
- No significant calibration deterioration.
- No unexplained out-of-range values.
- No source-lineage violations.
- Reproducible results.
- Stable runtime performance.

If the model does not satisfy the requirements, keep the current model.

---

14. PERFORMANCE IS A PRODUCT REQUIREMENT

All this sophistication must not make the Trade Calculator unbearably slow.

Investigate an architecture where expensive work happens before the user requests a trade.

Precompute and cache where appropriate:

- Statistical projections.
- Player outcome distributions.
- League scoring translations.
- Multi-year player forecasts.
- Replacement-level estimates.
- League-wide scarcity measurements.
- Calibration parameters.
- Player valuation components.

When a user evaluates a trade, reuse these prepared calculations.

The trade request should primarily perform the roster-conditional work necessary to evaluate that specific transaction.

Consider:

- Efficient Monte Carlo simulation.
- Deterministic random seeds.
- Adaptive simulation budgets.
- Cached scenario results.
- Incremental updates.
- Vectorization.
- Async execution where appropriate.
- Bounded computational cost.

Do not silently substitute a weaker model merely to meet a performance target.

If a faster approximation is introduced, validate it against the full model and report its limitations.

Measure actual latency.

Preserve the speed improvements already being developed for the Trade Calculator.

---

15. PRODUCTION ROLLOUT STRATEGY

Implement in stages.

STAGE A — Foundation

- Complete the league configuration audit.
- Verify exact scoring.
- Correct known defects.
- Establish consistent model inputs.
- Add missing provenance and regression coverage.

STAGE B — Projection Intelligence

- Improve source coverage.
- Reuse existing adapters.
- Build missing authorized integrations.
- Implement exact-league statistical forecasting.
- Validate projection ensembles.

STAGE C — Player Utility

- Improve positional replacement.
- Improve Best Ball simulations.
- Implement marginal roster contribution.
- Improve dynasty-horizon forecasting.

STAGE D — Valuation Intelligence

- Develop league-aware fair values.
- Compare against current canonical values.
- Measure calibration and double-counting.
- Run historical and forward-looking shadow comparisons.
- Establish objective model promotion criteria.

STAGE E — Trade Decision Engine

- Combine validated models.
- Implement the explicit YES/NO decision framework.
- Account for roster and competitive context.
- Calibrate confidence.
- Improve explanations.
- Integrate with the current Trade Calculator and related tools.

STAGE F — Site-Wide Integration

Propagate the validated intelligence to applicable features.

Implement automated consistency checks.

Important sequencing rule

These stages describe dependencies, not a requirement that every stage finish before another begins.

Use parallel implementation for independent components.

An agent can develop the Trade Decision interface while another develops projection infrastructure.

Use stubs or documented interfaces where necessary.

However, do not expose unvalidated placeholder calculations as real production intelligence.

---

16. MAXIMUM VELOCITY ENGINEERING DIRECTIVE

Follow our permanent parallel-development policy.

Use isolated worktrees and specialized agents.

Assign independent workstreams such as:

Agent 1 — Exact Scoring and Data Sources

Scoring correctness, raw category coverage, projections, and provider integration.

Agent 2 — League Valuation Mathematics

Market priors, scarcity, calibration, and league-aware dynasty values.

Agent 3 — Best Ball and Roster Intelligence

Weekly simulations, replacement levels, marginal roster value, and competitive-window forecasts.

Agent 4 — Trade Decision Engine

YES/NO logic, risk integration, decision calibration, and trade recommendation outputs.

Agent 5 — Site-Wide Integration and Validation

Frontend integration, cross-feature consistency, historical tests, and performance.

Coordinate ownership to prevent conflicting changes.

Have agents establish compatible interfaces early.

Begin writing code immediately.

Do not serialize independent implementation work.

Perform focused testing during development and comprehensive integration validation at appropriate milestones.

Autonomous merges

I do not want to manually approve routine merges.

The designated Integration Authority should merge completed changes automatically when all established requirements are satisfied.

Do not bypass required CI checks, review requirements, or branch protection.

Keep experimental models separate from live production behavior until they meet promotion requirements.

Do not allow CI on one independent feature to prevent coding on another.

---

17. MAINTAIN TRANSPARENCY ABOUT THE MODEL

I am trusting the engineering and mathematical research to determine appropriate weighting.

That does not mean the model should become an unexplained black box.

For every significant model, document:

- Inputs.
- Output.
- Mathematical assumptions.
- Training data.
- Validation data.
- Reliability.
- Limitations.
- Known biases.
- Source independence.
- Calibration.
- Confidence methodology.
- Model version.
- Promotion criteria.

Create reproducible model evaluation receipts.

When a model changes, quantify what changed and why.

When possible, show examples of players whose values increased or decreased due to our league-specific rules.

Distinguish genuine player-specific effects from broad positional adjustments.

Do not invent numbers to demonstrate an improvement.

---

18. REQUIRED IMPLEMENTATION DELIVERABLES

I expect actual working code, not merely documentation.

Deliver:

1. Verified league configuration and scoring integration.
2. Expanded authorized statistical projection coverage.
3. League-scored player projection distributions.
4. Improved positional replacement calculations.
5. Improved Best Ball player utility.
6. Multi-year dynasty forecasting infrastructure.
7. A validated league-aware valuation challenger.
8. Canonical valuation integration when promotion gates are satisfied.
9. A unified, roster-aware Trade Decision Engine.
10. Clear YES/NO trade recommendations with calibrated confidence.
11. Site-wide integration of appropriate intelligence.
12. Historical evaluation and regression coverage.
13. Performance optimizations.
14. Model versioning and provenance.
15. Production verification and rollback capability.

Update the existing project plans and developer guidance.

Record dependencies, implementation status, PR numbers, validation results, and unresolved blockers.

Do not mark a feature complete merely because code was written.

Differentiate:

- Implemented.
- Tested.
- Validated.
- Merged.
- Deployed.
- Production verified.

---

19. ACCEPTANCE TEST: THE TRADE CALCULATOR

Ultimately, the entire initiative should be judged by whether it improves our ability to evaluate actual trades.

Use representative trades involving:

- A quarterback in our Superflex format.
- A tight end in our two-TE lineup.
- An elite defensive lineman.
- A high-volume linebacker.
- A defensive back specializing in coverage production.
- A high-upside, volatile Best Ball player.
- A consistent but lower-ceiling veteran.
- A rookie.
- Future draft capital.
- Multi-player packages.
- A contender acquiring a veteran.
- A rebuilder trading away an aging star.
- A team with poor positional depth.
- A team with substantial positional surplus.

For each scenario, demonstrate that the Trade Calculator considers the relevant evidence.

The engine should identify the actual marginal benefit of the transaction.

It must not simply produce a recommendation from total market value.

Compare the new recommendations against the current calculator.

Explain where the recommendation changes.

Explain why.

Evaluate whether those changes are more defensible under historical and simulated outcomes.

A changed recommendation is not automatically an improvement.

---

20. FINAL OWNER DIRECTIVE

I want every useful piece of intelligence we are developing to contribute to the quality of our fantasy football decisions.

I want our unique league scoring to matter.

I want our roster requirements to matter.

I want positional scarcity to matter.

I want Best Ball to matter.

I want player age and future development to matter.

I want injury risk to matter.

I want championship probability to matter.

I want projected performance to matter.

I want actual dynasty market values to matter.

I want trade history and market evidence to matter.

I want our current roster and competitive window to matter.

But I do not want fifteen arbitrary multipliers stacked on top of one another.

I want an integrated mathematical system that understands how these factors interact and how reliable each source of information actually is.

Our external market sources should remain independent observations.

Our Brisket valuation should become more league-aware when evidence justifies it.

Our Trade Calculator should use those valuations alongside roster-specific simulations and competitive context.

And the ultimate product should give me a clear recommendation:

YES, MAKE THIS TRADE.

or

NO, DON'T MAKE THIS TRADE.

With an explanation I can understand and mathematical evidence supporting the recommendation.

Do not automatically assume our existing methods are optimal.

Do not automatically assume more complicated methods are better.

Demonstrate improvements.

Preserve working systems.

Correct measurable deficiencies.

Implement the strongest defensible approaches.

Keep unreliable models experimental.

Use maximum safe parallel-development throughput.

Automatically merge routine production-ready changes under our established policies.

Begin implementation immediately. Do not stop after producing another plan.

The ultimate goal is simple:

BUILD A TRADE CALCULATOR THAT MAKES THE BEST POSSIBLE DYNASTY FANTASY FOOTBALL DECISIONS FOR OUR SPECIFIC LEAGUE USING ALL THE RELIABLE INTELLIGENCE AVAILABLE TO IT.
