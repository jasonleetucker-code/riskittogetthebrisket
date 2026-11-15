# OWNER DIRECTIVE (verbatim) — 2026-10-19 (second, later version) — BUILD CHASE UPSIDE'S OWN TRADE-DERIVED VALUATION SOURCE

Precedence note (coordinator, not owner text): this later directive refines CHASE_TRADE_MARKET_SOURCE_2026-10-19.md for the same project. Where the two conflict, this later one wins; the earlier stays traceable.

OWNER DIRECTIVE — BUILD CHASE UPSIDE'S OWN TRADE-DERIVED VALUATION SOURCE

Repository: jasonleetucker-code/riskittogetthebrisket

Priority: New dynasty valuation capability. Continue existing release trains and authorized completion work without unnecessary interruption.

Objective

Build a proprietary, trade-derived dynasty player valuation model using actual completed trades from established dynasty leagues, particularly Sleeper leagues we already discover and collect.

The eventual goal is to create another eligible source in our consensus system:

Chase Upside Trade Market

This should measure what real dynasty managers reveal through their completed trades, independently of what ranking websites say players are worth.

I want a working source pipeline, fitted model, generated player rankings, confidence information, testing, and integration with our existing source architecture.

Do not stop at a research report or a proposed design.

However, the new source must remain non-voting until it passes the required independent validation and I approve production voting.

1. Reuse the infrastructure we already have

Inspect and reuse the existing Market Trade Ledger and Adaptive Learning work:

* src/trade/market_trade_archive.py
* src/trade/market_trade_normalize.py
* src/trade/market_trade_groups.py
* src/trade/market_trade_format.py
* src/trade/market_trade_eval.py
* src/trade/market_trade_report.py
* docs/market_trades/TARGET_FORMAT_CENSUS.md
* docs/MARKET_TRADE_LEDGER_ACTIONABILITY_SPEC.md
* docs/research/ADAPTIVE_LEARNING_2026-09-26.md

Specifically review the planned AL-2b format translators and AL-2c latent transaction-price model.

Do not create a competing trade database, duplicate acquisition pipeline, or second identity system.

Explain which existing features already consume these trades and identify precisely what is missing to derive player values.

2. Require established dynasty leagues

For the initial model, prioritize leagues with at least THREE VERIFIED COMPLETED SEASONS of dynasty operation.

On Sleeper, follow the actual league-history chain, including previous_league_id, to establish continuity across seasons.

A league created three calendar years ago is not automatically eligible.

Verify that it has actually operated across three completed seasons.

Do not mistake redraft leagues, recreated league IDs, or unverified league histories for established dynasty leagues.

I want an experienced dynasty-trading population, not a model dominated by startup leagues.

Measure how many leagues and completed trades survive this requirement.

Also evaluate two-season leagues as a separate research cohort to determine how much additional evidence they could provide, but do not silently relax the three-season requirement.

Recommend any additional league-quality protections based on measured evidence.

Avoid unnecessarily restrictive criteria that eliminate large amounts of legitimate data.

Focus on a few meaningful safeguards: verified dynasty format, actual completed-season history, identifiable transactions, adequate market activity, and reliable league settings.

Do not assume an established league necessarily contains expert managers. Measure whether league age actually improves the resulting signal.

3. Make league formats matter

Never treat all dynasty formats as interchangeable.

Account for:

* Superflex versus one-quarterback leagues
* Number of teams
* TE premium
* PPR and other scoring differences
* Starting lineup size
* IDP versus offense-only leagues
* IDP position requirements and scoring
* Draft pick formats
* Other materially different roster rules

Use the existing format fingerprints and comparability machinery.

Prefer exact or demonstrably comparable formats.

Develop and validate format translators only when the evidence supports them.

Unknown format information must remain unknown.

Do not represent a league as comparable merely because it is labeled dynasty.

Support both a broad dynasty trade-market estimate and a target-format estimate for our league when sufficient data exists.

4. Build a mathematical player-value model

Use completed trades as observations that reveal relative player and pick values.

For example, a trade exchanging one player for two other players provides information about how their market values compare.

However, do not assume every accepted trade is perfectly even.

Managers can intentionally overpay, rebuild, contend, consolidate, or prioritize roster needs.

Research and implement an appropriate robust model, evaluating approaches such as:

* Regularized latent player-value estimation
* Trade-equilibrium models with uncertainty
* Graph-based relative valuation
* Robust regression or Bayesian estimation
* Trade acceptance or revealed-preference constraints

These are candidates, not instructions to implement all of them.

Select a defensible mathematical method using evidence and appropriate testing.

Account for package consolidation effects, including unequal asset counts.

Do not treat raw summed package totals as necessarily equivalent.

Use the existing geometric Value Adjustment as a documented benchmark where applicable, but do not assume its q = 0.78 parameter is the true market price mechanism.

Avoid circularity: the new source must not simply reproduce our existing canonical player values through its initial assumptions.

If an external anchor is required to establish the 0–9,999 scale, disclose it and evaluate dependence on that anchor.

Produce independent relative rankings and well-defined scale calibration.

5. Prevent contaminated or misleading evidence

Use only actual completed transactions.

Deduplicate identical underlying trades collected through multiple feeds.

Do not count one trade twice because it appears on both Sleeper and KTC.

Separate direct Sleeper-observed transactions from KTC database observations.

KTC's own Trades signal may already reflect trades in the KTC database, so using those same transactions to create another consensus voter could create feedback and double-counting.

Measure and document this overlap.

Prefer independently observed Sleeper transactions for the first independently voting candidate.

KTC-derived transactions may be used for separate benchmarks or carefully controlled analyses, but not disguised as independent evidence.

Guard against suspect trades, unresolved player identity, incorrect draft pick identity, missing assets, invalid transaction states, league-format uncertainty and abusive manipulation.

Do not exclude a legitimate trade merely because its values disagree with our current rankings.

6. Weight the evidence appropriately

I want the market source to reflect what managers value NOW.

Older trades may remain useful for learning structural patterns, but recent completed trades should carry greater influence when estimating current player values.

Do not confuse the source's historical league eligibility with the freshness of individual trade observations.

Use a sensible recency model, tested against chronological holdout data.

Prevent a single highly active league or pair of managers from dominating the model.

Include effective sample counts, uncertainty estimates and evidence coverage per player.

Players with insufficient trade evidence should have low confidence or an unavailable independent estimate.

Do not invent independent trade-market values simply by copying our current rankings.

7. Generate a complete experimental source

Create a named, versioned source such as:

chaseTradeMarket

Display name:

Chase Upside Trade Market

Produce:

* Player identity
* Position
* Estimated trade-market value
* Estimated rank
* Model version
* Data as-of date
* Number of directly and indirectly informative trades
* Effective independent league coverage
* Format coverage
* Confidence or uncertainty
* Freshness
* Source provenance
* Reasons a player is unpriced

Support offense, IDP, rookies, and draft picks where evidence is adequate.

Do not force prices for categories that do not have sufficient evidence.

Show whether a player appears overvalued or undervalued relative to our current consensus, while recognizing that the disagreement is not proof either valuation is incorrect.

8. Validate the model independently

Backtest on genuinely future or held-out trade observations.

Prevent look-ahead bias.

Separate trades by time and underlying league to avoid training and testing on overlapping evidence.

Compare model predictions against real held-out transactions using appropriate loss functions and uncertainty calibration.

Benchmark against:

* Current Chase Upside values
* KTC Crowd
* KTC Trades
* Other relevant independent sources
* Simple baseline models

Test whether the model adds genuine information beyond our existing sources.

Evaluate separately by player position, market tier, trade structure, number of assets, scoring format, league experience and sample size.

Do not equate historical trade acceptance with proof that a trade was fair.

If the current dataset is too small to justify an independent valuation source, report the exact shortfall and continue collecting evidence.

9. Integrate with Chase Upside

Build the experimental source into the existing source registry and source-health architecture.

Initially label it:

Experimental — Not Voting

Expose its model-generated rankings and relevant confidence information in an appropriate research or source-comparison view.

Use existing design conventions and mobile-responsive layout requirements.

Prepare the source to become a regular consensus voter after successful validation and owner authorization.

Do not activate it in the official consensus prematurely.

When it becomes eligible to vote, apply the owner's approved freshness and source-family rules, and ensure its influence is transparent.

Do not double-count raw trade-market comps elsewhere as another independent valuation source if they are derived from the same underlying transactions.

Preserve the active geometric package Value Adjustment and all current canonical values during this development.

10. Report what the evidence actually supports

At completion, provide:

* Total discovered leagues
* Leagues with three verified completed seasons
* Eligible unique completed trades
* Data lost to each exclusion criterion
* League-format coverage
* Player coverage
* Accuracy and uncertainty of the experimental values
* Most significant disagreements with the current consensus
* Whether the model adds predictive information
* Areas where the evidence is insufficient
* Remaining requirements before I should authorize voting

Also show at least five real, properly anonymized examples explaining how completed trades contributed to model-generated player valuations.

Make the math understandable to someone without a statistics background.

Final instruction

I want Chase Upside to have its OWN trade-derived dynasty valuation source, not just consume the trade-derived source published by KeepTradeCut.

Build the end-to-end capability using our existing trade infrastructure.

Use established leagues, preferably at least three completed seasons.

Make the model statistically defensible, format-aware, duplicate-safe, recency-aware and independently validated.

Finish the functional implementation and experimental integration.

Do not alter the live consensus until the model has demonstrated value and I authorize it to vote.

Continue existing release trains and other approved Chase Upside work in parallel without unnecessary delays.
