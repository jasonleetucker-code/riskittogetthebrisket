# OWNER DIRECTIVE (verbatim) — 2026-10-19 — BUILD CHASE UPSIDE'S OWN REAL-TRADE PLAYER VALUATION SOURCE

OWNER DIRECTIVE — BUILD CHASE UPSIDE'S OWN REAL-TRADE PLAYER VALUATION SOURCE

Repository: jasonleetucker-code/riskittogetthebrisket
Website: chaseupside.com
Priority: High — New proprietary dynasty valuation source
Working name: Chase Upside Trade Market
Proposed source key: chaseTradeMarket

THE OBJECTIVE

I want Chase Upside to develop its own original player valuation source using real, completed dynasty fantasy football trades.

We currently collect trade information from other leagues, especially through Sleeper and our Sharp/market discovery systems.

I want to use that information to determine how actual dynasty managers value players.

This would be our own trade-derived valuation source, conceptually similar in purpose to KeepTradeCut's trade-derived values, but using our own data, independently developed methodology, and validation.

I am authorizing you to build the complete system—not simply prepare another research report.

The end goal is for Chase Upside Trade Market to become another legitimate voting source in our canonical dynasty player valuations.

It should eventually contribute alongside KeepTradeCut Crowd, KeepTradeCut Trades, FantasyCalc, DLF, IDP Trade Calculator, and our other approved sources.

However, its initial implementation must operate in shadow mode until it demonstrates that its estimates are reliable and contribute information beyond the sources we already use.

Do not activate unvalidated values in production.

Do not allow this work to unnecessarily delay the existing Chase Upside completion campaign.

⸻

1. AUDIT AND REUSE WHAT ALREADY EXISTS

Before building anything, inspect our existing trade-data infrastructure.

Start with:

* src/trade/market_trade_archive.py
* src/trade/market_trade_normalize.py
* src/trade/market_trade_groups.py
* src/trade/market_trade_format.py
* src/trade/market_trade_eval.py
* src/trade/market_trade_report.py
* src/trade/market_trade_database.py
* src/trade/market_trade_ledger.py
* scripts/market_trade_ledger.py
* docs/MARKET_TRADE_LEDGER_ACTIONABILITY_SPEC.md
* docs/market_trades/TARGET_FORMAT_CENSUS.md
* docs/research/ADAPTIVE_LEARNING_2026-09-26.md
* src/model_registry/
* Our existing Sleeper/Sharp discovery and historical league-data systems.

The adaptive-learning roadmap already identifies AL-2c, a shadow latent transaction-price model.

Implement this project by extending the existing AL-2 infrastructure.

Do not create a second trade database, second model registry, competing player identity system, or disconnected valuation engine.

Determine exactly what our currently collected trades are used for, where the observations are stored, how many unique underlying trades we have, and which necessary components are still missing.

Then implement the missing components.

Do not redo completed work.

⸻

2. LEAGUE AGE REQUIREMENT — MY MOST IMPORTANT FILTER

I do not want our player values determined primarily by inexperienced managers in brand-new startup leagues.

My preferred dataset consists of established dynasty leagues with at least three completed fantasy football seasons.

A league with valid history across three completed seasons qualifies as mature, provided its other data-quality requirements are satisfied.

Use Sleeper's previous-league relationships and historical league identifiers to establish continuity between seasons.

Do not mistakenly treat every new annual Sleeper league ID as a newly created league.

Verify continuity using actual historical evidence rather than assuming that a league's name proves its age.

Preferred group: Established leagues

Requirements:

* At least three completed fantasy seasons of verifiable dynasty league history.
* Genuine dynasty format.
* Verifiable completed trades.
* Sufficient league-format information.
* No demonstrated severe data-quality issues.

These leagues should form our primary training population.

Secondary group: Two-year leagues

I don't want overly restrictive rules to eliminate most of the available data.

Therefore, also evaluate established leagues with two completed seasons.

Keep them as a separately reported secondary population.

If three-year leagues provide enough qualified evidence, prioritize that sample.

If the three-year population is too small or leaves significant valuation gaps, evaluate whether including two-year leagues improves estimates.

Do not automatically give two-year leagues full authority.

Compare three-year-only results against a controlled inclusion of two-year leagues.

Only promote the secondary population into an authoritative model when the additional evidence is demonstrably helpful and its inclusion has been reviewed.

New leagues

Leagues with fewer than two completed seasons should not contribute to the initial authoritative trade-derived valuation source.

They may remain available in the general trade database and separate research population.

I do not want startup trades dominating our new rankings.

Avoid unnecessary exclusions

Do not require every qualifying league to have dozens of trades annually.

A long-running, legitimate dynasty league with modest trading activity can still provide useful evidence.

The model should recognize that one trade carries limited information without necessarily excluding the entire league.

Do not introduce arbitrary strictness that substantially reduces our dataset without measurable benefit.

⸻

3. OTHER LEAGUE-QUALITY CRITERIA

Research which additional criteria genuinely improve the reliability of trade-derived values.

Consider:

* Number of completed seasons.
* Dynasty league continuity.
* Actual transaction history.
* Manager continuity, where observable.
* League size.
* Scoring settings.
* Starting lineup requirements.
* Superflex versus one-quarterback formats.
* TE premium.
* IDP scoring and starting requirements.
* Roster depth.
* Rebuilding versus competing trade patterns.
* Whether the same managers repeatedly trade with one another.
* Whether transactions appear suspicious or manipulated.

I do not want a complicated checklist that unnecessarily eliminates valid leagues.

Use quality weighting and robust statistical methods where appropriate instead of rejecting leagues for minor differences.

A league should not be excluded simply because its managers make trades our existing rankings consider unusual.

Unusual trades may contain useful market information.

However, detect and control genuinely problematic activity, including:

* Duplicate transactions.
* Reversed or canceled trades.
* Orphaned or unresolved player identities.
* Suspicious reciprocal trade patterns.
* Artificial trades between related accounts where credible evidence exists.
* Transactions with non-player compensation that cannot be represented correctly.
* Non-dynasty transactions.
* Missing material league-format information.

Document the reasons for exclusions.

⸻

4. USE THE ACTUAL COMPLETED TRADE DATA

This source must be based on real transactions, not generated examples.

Use qualifying completed trades already collected through our Sleeper discovery system.

Expand historical retrieval where supported and permitted, particularly for mature leagues whose older transaction history is accessible.

Reuse existing collection mechanisms and persistence.

Preserve:

* Original trade timestamp.
* League and season lineage.
* Canonical player identifiers.
* Draft pick identifiers.
* Assets sent by every participating team.
* Relevant league settings at the time of the trade.
* Acquisition source.
* Trade identity and deduplication status.
* Collection timestamp.
* Original format metadata.
* Provenance and data-quality flags.

Use only data we are permitted to collect and process.

Do not assume Sleeper provides a global trade-history feed.

Do not collect private information through unauthorized access or bypass controls.

Do not expose identifiable outside-league manager or league information in the public valuation source.

⸻

5. AVOID DOUBLE-COUNTING KEEPTRADECUT DATA

This is extremely important.

KeepTradeCut Trades already contributes to our consensus.

If our new source is trained heavily on the exact same KTC trade observations, it could effectively give KTC's data another vote.

I want Chase Upside Trade Market to be a genuinely differentiated source.

For the initial authoritative candidate, prioritize independent Sleeper/Sharp trade observations whose underlying trades are not already included in a known KTC-derived training population.

Use the existing cross-source deduplication system to identify overlapping transactions.

Keep KTC trade-database observations available for independent research and benchmarking, subject to actual dataset-lineage limitations.

Report how many unique trades come from each acquisition channel.

If the same underlying Sleeper transaction appears in multiple places, count it once.

Do not assume that two different trades are duplicates merely because they involve identical players and occurred on the same day.

Also investigate potential circularity between the new source and our existing consensus.

A new model that simply reproduces current Chase Upside values through strong regularization is not automatically new independent market evidence.

Measure how much information comes from actual trades versus inherited valuation priors.

Do not let our existing consensus effectively vote for itself under a new name.

⸻

6. DEVELOP OUR OWN PLAYER VALUATION MODEL

Build a statistical model that learns implied player values from completed trades.

The model should learn the relative market worth of assets from the combinations managers actually exchange.

For example:

Manager A trades Player X.

Manager B trades Players Y and Z.

The transaction provides information about how those assets were valued in that market.

But it does not mean:

Value(X) = Value(Y) + Value(Z)

That would ignore our established Value Adjustment research.

Model requirements

Evaluate suitable methods, including:

* Regularized latent-price estimation.
* Trade-network or graph-based valuation.
* Robust optimization using observed trade packages.
* Hierarchical market models.
* Comparable-trade-based price estimation.
* Appropriate statistical uncertainty estimation.

Choose the approach that is most defensible and works with our available evidence.

You may combine approaches when doing so improves reliability.

Do not select a sophisticated machine-learning method simply because it sounds more advanced.

Compare candidates against reasonable simple baselines.

Package Value Adjustment

Account for trades involving different numbers of assets.

A one-for-three transaction does not necessarily mean the single player's value equals the unadjusted sum of the three players.

Use the existing approved geometric package model, geom_q078_v1, as the initial package-adjustment reference where appropriate.

However, avoid circular training or treating that formula as unquestionable ground truth.

Run sensitivity comparisons against other mathematically valid package models.

The trade-derived valuation model must remain distinct from the formula used to adjust packages in the Trade Calculator.

We are building a new player-value source, not replacing our Value Adjustment formula.

⸻

7. ACCOUNT FOR THE FACT THAT TRADES ARE NOT ALWAYS EVEN

A completed trade does not prove that both sides received exactly equal value.

Managers sometimes accept unequal trades because they are rebuilding, competing, managing roster limits, acquiring a specific position, or responding to other circumstances.

Treat observed trades as imperfect evidence of market valuations.

Use robust loss functions, reasonable transaction uncertainty, and appropriate safeguards against outliers.

Do not force every completed transaction to balance exactly.

Do not assume that the agreed trade price is equivalent to a player's objective football value.

We are measuring observed dynasty market behavior.

Where possible, distinguish genuine market-wide valuation patterns from individual managers' unusual preferences.

⸻

8. ACCOUNT FOR DIFFERENT LEAGUE FORMATS

Our league is a superflex, heavily TE-premium, IDP dynasty league.

We need player values relevant to that environment.

A quarterback's market value in a one-quarterback league cannot simply be mixed with his value in a superflex league.

Likewise, IDP values can differ dramatically based on scoring and starter requirements.

Use the existing format-census and comparability systems.

Prioritize:

1. Verified comparable dynasty formats.
2. Validated format-adjusted transactions.
3. Broader dynasty-market transactions when they can provide legitimate general information.

Do not invent compatibility where the league's format is unknown.

Develop and evaluate format-specific estimates or hierarchical relationships when the data supports them.

Preserve the distinction between:

* General dynasty transaction-market value.
* Value estimated for our target league format.

Do not label generic market values as exact equivalents of our league's scoring.

If certain conversions cannot be validated, leave those observations outside the target-format training population until their treatment is justified.

⸻

9. SUPPORT OFFENSE, IDP AND DRAFT PICKS

I want this to be a comprehensive dynasty valuation source.

Support:

* Quarterbacks.
* Running backs.
* Wide receivers.
* Tight ends.
* Defensive linemen.
* Linebackers.
* Defensive backs.
* Rookie draft picks.
* Future draft picks.

Do not force unsupported player groups into the model.

If IDP market observations are too sparse, report that limitation and continue building the necessary sample.

Handle specific draft picks separately from generic future picks when their actual identities and values differ.

Do not mistake a future first-round pick for an established slot such as 1.01 unless that slot was already known at the time.

If cross-position trading evidence is insufficient to place offense, IDP and picks on a shared scale, do not invent shared-market relationships.

Use existing validated cross-position mechanisms only where justified, and clearly identify any inherited anchor rather than calling it independently observed trade evidence.

⸻

10. USE RECENT TRADES WITHOUT IGNORING LONGER HISTORY

The leagues themselves should be established, but individual trades also need reasonable recency weighting.

A transaction from last week generally tells us more about today's market than one from two years ago.

However, older valid trades may help estimate less frequently traded players.

Research and implement an appropriate recency model.

Start by measuring available qualified trade counts across:

* Last 30 days.
* Last 90 days.
* Last 180 days.
* Last 365 days.
* Last 730 days.

Evaluate trade recency, player/team changes, market-regime differences, and sample sizes.

Do not assume that all historical trades should receive equal weight.

Do not retroactively value an old trade with today's information and pretend those values were known when it happened.

Preserve point-in-time correctness.

A model must be trained only on transactions available before its declared training cutoff.

⸻

11. DON'T LET ONE LEAGUE DOMINATE THE SOURCE

A league that completes 150 trades shouldn't automatically have 15 times the authority of a league that completes 10.

Likewise, several highly active managers should not determine the market by themselves.

Evaluate reasonable league-level contribution controls.

Consider:

* Per-league influence caps.
* Effective independent league counts.
* Per-manager concentration diagnostics when identifiers are authorized and available.
* Diversity of qualifying leagues.
* Robust transaction weighting.
* Hierarchical league effects.

Use measurements to choose the actual limits.

Do not automatically discard legitimate activity.

The objective is broad market representation, not simply maximum transaction volume.

⸻

12. HANDLE PLAYERS WITH LIMITED TRADE ACTIVITY

Many dynasty players will not appear in enough trades to establish a reliable independent price.

This is particularly likely for:

* Deep IDP players.
* Backup quarterbacks.
* Developmental rookies.
* Lesser-known prospects.
* Bench players.
* Low-liquidity draft assets.

Use appropriate statistical regularization and uncertainty estimates.

Where direct transaction evidence is insufficient, the source must disclose that.

Do not assign a player a confident value simply because an optimization routine generated one.

Do not silently substitute the canonical Chase Upside value and call it a new independent market observation.

If necessary, report:

* Insufficient evidence.
* Prior-dominated estimate.
* Supported trade-derived estimate.

Only genuinely supported estimates should become eligible to contribute independent votes.

Set minimum evidence requirements using research and validation, including the number of distinct qualifying leagues and independent transactions.

⸻

13. PRODUCE AN ACTUAL PLAYER-VALUE BOARD

I want a complete new source dataset, not just a trade analytics report.

The model should generate its own player-value estimates.

Proposed name:

Chase Upside Trade Market

Proposed key:

chaseTradeMarket

For each supported asset, produce:

* Canonical player or pick identity.
* Estimated trade-market value.
* Estimated market rank.
* Position.
* Relevant format.
* Confidence or uncertainty.
* Number of usable direct trade observations.
* Effective independent trade sample size.
* Number of distinct contributing leagues.
* Latest supporting transaction date.
* Training window.
* Dataset version.
* Model version.
* Training cutoff.
* Source lineage and provenance.
* Status indicating whether the value is sufficiently supported for voting.

Normalize valid estimates to our canonical shared valuation scale using an independently evaluated mapping.

Preserve the raw fitted estimates separately.

Do not make arbitrary maximum-value scaling decisions that distort offense versus IDP relationships.

⸻

14. INTEGRATE WITH THE EXISTING SOURCE-VOTING SYSTEM

The ultimate goal is for this source to vote.

Use the existing canonical source registry, voting mechanisms, source-health system, freshness policy, and provider-family safeguards.

Do not create a separate voting engine.

This should be one underlying source family, regardless of whether the model produces multiple format-specific or position-specific outputs.

Prevent duplicate contributions from the same trained model.

Treat this source as trade-derived and document any overlap with existing inputs.

Freshness

Follow the newly approved source freshness policy:

Days 0–7: 100%
Days 8–14: 75%
Days 15–21: 50%
Days 22–30: 25%
Older than 30 days: 0%

For this model, freshness must be based on a genuine update to its qualifying trade evidence and a successfully rebuilt, valid model snapshot.

Merely rerunning training on identical trades must not reset the freshness clock.

Measure when the model last incorporated genuinely new qualifying transaction information.

Use the existing source-freshness owner rather than constructing a second clock.

Initial activation

Register the new model as a shadow source first.

It should be visible for diagnostics and comparison without affecting canonical player values.

Complete the validation requirements before recommending activation.

Once ready, prepare a reversible production promotion that uses the normal source-weighting pipeline.

Do not silently activate it or change established player values without reporting the measured impact and obtaining my approval.

⸻

15. PERFORM REAL VALIDATION

Do not judge the model solely by how well it balances the trades it was trained on.

That would be circular.

Use held-out completed trades and time-ordered testing.

Include:

* Chronological train/test splits.
* Entire leagues held out from training.
* Independent manager/league concentration checks.
* Unseen player-package combinations.
* Separate offense and IDP evaluations.
* Superflex versus one-quarterback evaluations.
* TE-premium evaluations.
* Rookie pick evaluations.
* Small-sample and thin-market evaluations.
* Sensitivity to mature-league eligibility.
* Sensitivity to recency weighting.
* Sensitivity to package-adjustment assumptions.

Compare against:

* Chase Upside's existing consensus.
* KeepTradeCut Crowd.
* KeepTradeCut Trades.
* FantasyCalc.
* Other existing trade-derived sources where relevant.
* Simple historical-trade baselines.
* A prior-only baseline.
* Our new model with and without each major data population.

Determine whether the model adds real independent information.

If it simply reproduces existing sources, quantify that.

If it provides useful new market information, demonstrate how.

Completed trades are selected observations, and rejected offers are generally unavailable. Do not call better balance on accepted trades proof of objectively correct prices.

Use confidence intervals or other defensible uncertainty measures.

Report sample limitations accurately.

⸻

16. AUDIT THE THREE-YEAR REQUIREMENT EMPIRICALLY

I want specific answers about how the age requirement changes the usable population.

Produce a comparison containing:

Population A: Three or more completed seasons.

Population B: Two or more completed seasons.

Population C: All verified dynasty leagues, for research comparison only.

For each population, report:

* Number of qualifying leagues.
* Number of unique completed trades.
* Number of usable player assets.
* Offensive transaction coverage.
* IDP transaction coverage.
* Pick transaction coverage.
* Format compatibility.
* Effective independent league count.
* Model stability.
* Held-out performance.

Then recommend whether my default three-year requirement provides enough evidence.

I strongly prefer established leagues, but I am willing to consider two-year leagues if the evidence demonstrates that the additional population improves our coverage and accuracy.

Do not weaken the requirement silently.

⸻

17. ADD A USEFUL OWNER-FACING VIEW

Build a clear, responsive view for monitoring the new source.

It can be located within Source Health or an appropriate existing intelligence page.

Display:

Chase Upside Trade Market

With information such as:

* Current model status.
* Last genuine transaction-data update.
* Last successful model training.
* Eligible mature leagues.
* Unique qualifying trades.
* Three-year versus two-year league coverage.
* Total assets receiving estimates.
* Number of assets eligible to vote.
* Estimated freshness multiplier.
* Effective source weight.
* Confidence distribution.
* Recent changes in player valuations.
* Important unsupported positions.
* Model validation status.

Allow me to compare the new trade-derived values with the existing Chase Upside consensus.

For individual players, show the trade-derived valuation and its evidence confidence, when supported.

Do not expose outside-league manager identities or private transactions.

Use the site's established Premium Sports Intelligence design language.

Preserve desktop and mobile usability.

⸻

18. BUILD A REPEATABLE UPDATE PIPELINE

This must not be a one-time statistical experiment.

Implement a maintainable pipeline that can:

1. Collect newly available qualifying completed trades.
2. Connect annual Sleeper league histories.
3. Confirm league maturity.
4. Deduplicate transactions.
5. Validate asset identities and league formats.
6. Update the eligible trade population.
7. Rebuild the model at an appropriate cadence.
8. Produce versioned player-value snapshots.
9. Detect model instability or data-quality failures.
10. Run required validation.
11. Publish updated shadow or approved active source data.
12. Expose source-health and provenance information.

Make updates deterministic and reproducible from recorded inputs.

Use existing deployment, automation, model registry, and storage infrastructure.

Do not create unnecessary background services or excessive database duplication.

Keep the model stable when no meaningful new trade information has arrived.

Preserve historical model versions for backtesting and attribution.

⸻

19. RESPECT THE EXISTING COMPLETION CAMPAIGN

This work is authorized now.

Implement it alongside the existing Chase Upside development campaign without unnecessarily delaying other features.

Do not interfere with:

* The source-voting corrections in PR #1817.
* The universal freshness schedule.
* DLF IDP voting restoration.
* The IDP outlier-filter repair.
* The approved geometric Value Adjustment.
* Trade Calculator release work.
* Manager Intelligence.
* Trade Finder.
* Trade History.
* Production verification.

Coordinate changes to shared valuation and source-registry files.

Avoid unnecessary merge conflicts.

Do not create duplicate or competing implementations.

DFS and League Tycoon implementation remain shelved.

⸻

20. EXECUTION AND DELIVERY REQUIREMENTS

I want this developed to completion, not left indefinitely in a research phase.

Proceed through these milestones:

Milestone 1 — Existing Data Audit

Measure what we already have, identify genuinely missing components, and determine how much qualified three-year Sleeper trade history is available.

Milestone 2 — Mature League Qualification

Implement verified league-age checks, historical league-linking, quality rules and the separate two-year comparison cohort.

Milestone 3 — Trade-Derived Valuation Model

Implement the actual latent player-value model using eligible completed trades.

Milestone 4 — Shadow Source

Generate versioned player valuations and integrate the new source into our existing infrastructure without affecting production values.

Milestone 5 — Validation

Perform independent, chronological and league-held-out evaluations. Test stability, confidence, position coverage, source independence and susceptibility to duplicated trade evidence.

Milestone 6 — Site Integration

Implement the owner-facing source-health view and player-value comparisons. Prepare the voting integration and rollback controls.

Milestone 7 — Production Readiness

Provide a concise activation report showing the new model's actual value, limitations, eligible coverage, proposed weight, and impact on existing player rankings.

If validation succeeds, prepare the production-ready promotion for my approval.

If the current dataset is genuinely insufficient, still complete the infrastructure and shadow model. Identify the exact evidence shortage and the specific additional collection necessary rather than claiming unsupported accuracy.

Do not invent data to satisfy a release requirement.

⸻

FINAL OWNER INSTRUCTION

I want Chase Upside to have its own proprietary dynasty football trade-market valuation source.

I want it built using real completed trades from established dynasty leagues, especially the Sleeper leagues we already discover and monitor.

My preference is for leagues with at least three completed seasons.

I'm open to including leagues with two completed seasons when that demonstrably improves our estimates, but I don't want startup-league trade behavior dominating our values.

The model should independently estimate what players and draft picks are worth based on what experienced dynasty managers actually exchange.

It must account for different league formats, consolidation, IDP, draft picks, trade recency, sample quality and statistical uncertainty.

It must not simply copy KTC's trade-derived values or recycle Chase Upside's own consensus as artificial independent evidence.

It should eventually become a legitimate voting source in our canonical consensus.

I authorize the complete implementation, including the data pipeline, model, evaluation, source integration, status reporting and production-readiness work.

Start with shadow operation. Do not change live valuations until validated and approved.

Reuse the existing AL-2 and Market Trade Ledger architecture.

Do not stop after another feasibility report.

Build the source, test it, show me what it produces, and tell me when it's genuinely ready to vote.

Continue finishing Chase Upside in parallel.
