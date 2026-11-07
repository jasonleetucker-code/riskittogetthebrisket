# Owner directive — IDP market pricing, acquisition intelligence, historical trade research and draft strategy (2026-10-26)

**Status:** RECORDED VERBATIM. The owner gave this directive to the coordinator session in chat on 2026-10-26.

Scope and authorization:
- **Authorization.** Granted as research, read-only collection, additive diagnostics and shadow-only development in
  `docs/EXECUTION_PLAN.md`, in the section of the same date.
- **Owner-reserved.** Everything in §15 below is owner-reserved and NOT authorized.

Owner answers recorded with the directive, 2026-10-26:
1. **Census data source.** The Phase 1 census pulls from Sleeper's public read-only API across the full
   `previous_league_id` chain, priced from the tracked `exports/archive/` through `src/history`. No box run.
2. **Trades before 2026-07-14.** Point-in-time prices begin at `HISTORY_FLOOR` (2026-07-14), so these trades have none.
   Survey licensed or public historical archives of IDPTC, KTC or other dynasty trade values for those trades, honoring
   their terms of use. No paid data. Nothing is ingested until the owner approves a specific source; until then those
   trades are labelled `before_history_boundary`.

---

MASTER CLAUDE CODE IMPLEMENTATION DIRECTIVE
Chase Upside — IDP Market Pricing, Acquisition Intelligence, Historical Trade Research, and Draft Strategy

Repository: `jasonleetucker-code/riskittogetthebrisket`
Primary league: `dynasty_main`
Sleeper League ID: `1312006700437352448`

## Objective

Build an evidence-based framework that helps dynasty managers decide when to buy, sell, draft, or avoid IDP players
when the prevailing league trade market differs from Chase Upside's independent player valuations.

Do not simply raise IDP values until the numbers agree with IDP Trade Calculator.

The ultimate objective is to make stronger dynasty decisions while preserving the independence, accuracy,
interpretability, and safety of our existing system.

This directive authorizes investigation, read-only data collection, additive diagnostics, and independently tested
shadow development consistent with existing owner directives. It does not authorize changes to production canonical
valuations, source voting, scoring cards, trade fairness, or owner-held methodology without the required separate
approval.

## SECTION 1 — REQUIRED FIRST ACTIONS

Before beginning implementation:

1. Inspect the latest `main` branch.
2. Read `CLAUDE.md`, `AGENTS.md` if present, and `docs/agent-operating-system/SESSION_HANDOFF.md`.
3. Review existing owner directives and the execution plan.
4. Identify active agents, open work claims, pending PRs, and branch dependencies.
5. Identify the actual production deployment SHA.
6. Identify all existing trade-market, IDP, replacement, projection, draft, and auction projects.
7. Compare this directive with any newer owner decisions.
8. Do not duplicate completed work or overwrite newer code.
9. Establish an ownership matrix for each authoritative component.
10. Produce a compact research and implementation plan.

Use current repository evidence rather than assuming this document reflects the latest development state.

### Important existing research

Read the following before proposing new algorithms:

- `docs/valuation/idp_accuracy/README.md`
- `docs/valuation/idp_accuracy/C_MARKET_CROSS_POSITION.md`
- `docs/valuation/idp_accuracy/B_REPLACEMENT.md`
- `docs/valuation/idp_accuracy/D_BESTBALL.md`
- `docs/valuation/idp_accuracy/E_SCORING_SENSITIVITY.md`
- `docs/valuation/idp_accuracy/F_CANDIDATES.md`
- `docs/valuation/idp_accuracy/G_ACCURACY.md`
- `docs/valuation/idp_accuracy/H_RECOMMENDATIONS.md`
- `docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md`
- `docs/market_trades/CHASE_TRADE_MARKET_POWER_STUDY.md`
- `docs/market_trades/CHASE_TRADE_MARKET_PREREGISTRATION.md`
- `docs/market_trades/TARGET_FORMAT_CENSUS.md`
- `docs/owner/CHASE_TRADE_MARKET_SOURCE_V2_2026-10-19.md`
- `docs/trade/HISTORICAL_TRADE_REPLAY_AS_OF_ANALYSIS_SPEC.md`
- `docs/trade/NTEAM_TRADE_ENGINE_SPEC.md`

Also find and read the latest scoring, source-accuracy, league-valuation, and trade-decision reports. Do not assume
files or versions are unchanged.

## SECTION 2 — VERIFIED PROBLEM STATEMENT

Prior research found that Chase Upside's canonical value for the 10th-ranked defender was approximately 80% of the
corresponding IDP Trade Calculator value. The discount was not universal. Some defensive ranks were nearly equal.

An October 25–26 study found:

- 397 priced IDPs, all classified as low-confidence.
- Approximately three active IDP source votes per player, versus 12–14 for offense.
- Significant disagreement between IDPTC and Draft Sharks about which defenders are elite.
- Compression of the upper IDP rankings caused partly by that disagreement.
- Inconclusive evidence about whether our overall defensive valuation level is correct.
- No alternative cross-position model that passed every promotion gate.
- Fragile replacement assumptions in some positions.
- Stronger starter-to-replacement production gaps for LB than DB in the measured sample.

The research also identified that short-term realized lineup contribution and long-term dynasty market value are
different targets. Do not reinterpret those six-week studies as proof that the canonical IDP values should change.

Our league has 12 teams, 58 roster spots, and nine IDP starters per team: three DL, three LB, and three DB. The
historical league format differs from the current configuration. In particular, the 2025 season had 10 teams. Use
historically correct scoring and lineup requirements.

### The practical problem

If another manager values a linebacker at 7,000 and Chase Upside values him at 5,000, the calculator may discourage an
acquisition even when paying the prevailing market price improves the user's overall competitive outlook. But paying
that price is not automatically justified.

We need to distinguish:

1. Independent dynasty market valuation.
2. External IDPTC reference value.
3. Estimated actual league acquisition or sale price.
4. Whole-roster team-specific utility.
5. Opportunity cost and availability of alternatives.
6. Final recommendation confidence.

The objective is a more useful decision, not artificial agreement among valuation sources.

## SECTION 3 — HISTORICAL LEAGUE TRADE AUDIT: HIGHEST PRIORITY

This is the mandatory first empirical workstream.

### Reuse the existing owners

Inspect and reuse:

- `src/trade/market_trade_ledger.py`
- `src/trade/market_trade_archive.py`
- `src/trade/market_trade_normalize.py`
- `src/trade/market_trade_groups.py`
- `src/trade/market_trade_format.py`
- `src/trade/market_trade_report.py`
- `src/trade/market_trade_eval.py`
- `src/trade/market_trade_reference.py`
- `src/trade/market_trade_database.py`
- `src/trade/comparable_trades.py`
- `src/trade/own_league_format_capture.py`
- Existing Sleeper clients, identity resolution, historical scoring, pick identity, and temporal-data owners.

Do not create another underlying trade ledger. Do not duplicate Sleeper acquisition or player identity logic.

### Historical retrieval

Walk the primary league's verified Sleeper `previous_league_id` chain. For each season, retrieve through approved
existing clients and archives:

- League metadata
- Historical scoring rules
- Historical roster settings
- League members and roster identifiers
- Completed trades
- Trade timestamps
- Player transfers
- Draft-pick transfers
- Relevant FAAB transfers, when recorded
- Rookie drafts
- Startup drafts
- Auction drafts, if applicable
- Draft order and completed picks

Include offseason transactions and any documented draft-period transactions that the current acquisition pipeline could
otherwise omit.

Preserve original league-season identity. Do not silently treat transaction fields or weeks as interchangeable across
years.

Validate pagination, deduplication, missing windows, transaction completion status, pick ownership, and player IDs.

Respect provider terms, access controls, rate limits, and applicable commercial-use restrictions.

### Historical pricing integrity

Use point-in-time prices from:

- Archived Chase Upside contracts
- Archived IDPTC observations where available
- Other archived authorized market sources
- Existing temporal or historical value stores

Never use a later observation as though it were known at the time of the trade. If historical values are missing,
record a structured missing-data reason. Keep nearest-prior values separate from exact observations. Do not backfill
unknown historical prices with today's numbers and label them historical.

### Deliverable A — Verified trade census

Report:

- Seasons recovered
- Historical league IDs
- Completed trade counts by season
- IDP trades by DL/LB/DB
- Offense-for-IDP trades
- IDP-for-IDP trades
- Trades involving picks
- Multi-team trades
- Trades containing unpriced assets
- One-for-one identifiable swaps
- Multiple-player packages
- Historical-value coverage
- Number of distinct trading managers
- Number of distinct players and picks
- Number of trades suitable for each proposed analysis
- Observations excluded and exact reasons
- Coverage changes after league-format validation

Produce transaction-level private audit evidence and appropriately anonymized aggregate reports. Do not expose private
manager identifiers or outside-league transaction contents through public routes.

If production data cannot be accessed, deliver the read-only on-box execution plan and explicit blockers rather than
claiming this census is complete.

## SECTION 4 — TEST WHETHER IDPTC REPRESENTS OUR LEAGUE MARKET

Do not equate the statement "most managers use IDPTC" with a measured market-price model. Study whether actual
completed trades show IDPTC-aligned valuations.

### Competing hypotheses

- H1: IDPTC approximates the league's actual market prices.
- H2: Chase Upside's canonical values approximate actual transaction behavior more closely.
- H3: The league has position-specific premiums.
- H4: The league has tier-specific premiums, especially for elite IDPs.
- H5: Some managers have different pricing preferences.
- H6: The apparent discrepancy is explained by package effects, draft picks, source staleness, or player selection.
- H7: The sample is insufficient to distinguish these explanations.

Preserve the possibility that H7 is the correct result.

### Statistical requirements

Completed trades provide constraints and revealed preferences, not exact individual asset values. For one-for-one
transactions, evaluate source-relative price gaps. For multi-asset transactions, use the authorized package valuation
logic as a benchmark and independently investigate whether it describes accepted transactions.

Do not assume every completed trade is fair. Do not assume geometric package discount parameter q = 0.78 is the true
market-clearing mechanism merely because it is the active calculator model.

Investigate:

- Robust latent market values
- Hierarchical partial pooling
- Format-matched reference populations
- Historical price drift
- Bid-ask spread and market liquidity
- Transaction-level uncertainty
- Manager heterogeneity
- Selection effects
- Owner-by-position interactions only where data supports them

Prevent correlated observations from creating false confidence. Separate KTC-derived trades from other sources where
market-data lineage overlaps. Perform temporal and independent-league validation. Do not publish precise owner-specific
pricing coefficients if the effective sample size is inadequate.

### Deliverable B — Market hypothesis verdict

For each hypothesis report:

- Sample
- Measurement
- Uncertainty
- Whether results are statistically distinguishable
- Practical materiality
- Model comparison
- Evidence limitations
- Status: supported, rejected, inconclusive, or unavailable

## SECTION 5 — DEVELOP A NON-VOTING LEAGUE MARKET PRICE LAYER

The existing `chaseTradeMarket` source is a separate experimental project and remains non-voting. Do not turn this
project into a second source-voting mechanism. Reuse existing pricing, archive, format, and player identity owners.

Research a league-specific market layer which, only if supported, can estimate:

- Expected acquisition-price range
- Expected sale-price range
- Reference IDPTC value
- Difference from canonical Chase Upside value
- Position- and tier-specific differences
- Evidence quantity
- Effective independent sample size
- Data freshness
- Market-confidence classification
- Reasons for unavailable estimates

The acquisition and sale ranges may differ. The market model must abstain if sample quality or coverage is
insufficient.

Fallback behavior:

1. Display the actual authorized IDPTC reference as IDPTC.
2. Display independent Chase Upside values.
3. Mark estimated league price unavailable when empirical evidence is inadequate.
4. Explain the disagreement without issuing an unsupported market-price claim.
5. Never treat missing data as zero.

Any learned model must be developed and backtested in shadow before affecting a recommendation.

## SECTION 6 — TEAM-SPECIFIC ACQUISITION INTELLIGENCE

The trade decision architecture already has separate lenses. Reuse:

- `src/trade/analyze_trade.py`
- `src/trade/trade_decision.py`
- Existing team-context simulation
- Roster-capacity owners
- Best-ball roster utility
- Competitive posture
- Replacement logic
- Draft-pick ownership and valuation
- Existing package math
- Evidence and confidence systems

Preserve the single canonical top-line decision owner. Do not create a second yes/no formula.

### Research objective

For a proposed acquisition, determine whether the expected benefit is greater than its complete opportunity cost.
Evaluate whole-roster before/after states. Account for:

- Players given away
- Players received
- Draft picks
- Forced drops
- Lineup slot eligibility
- Bench and positional depth
- League-specific scoring
- Current championship window
- Future dynasty horizon
- Injury uncertainty
- Other obtainable players
- Transaction feasibility

Avoid double-counting roster utility, team strength, competitive posture, or source-derived valuation evidence.

### Maximum advisable acquisition price

Research a candidate method that estimates the highest legal outgoing package which still produces a sufficiently
beneficial expected result relative to the next-best feasible strategy. Do not simply convert fantasy PPG to dynasty
market-value points with an arbitrary coefficient.

Where the team-utility-to-market-cost relationship is not validated, express the result as:

- Affordable under the tested candidate model
- Borderline or uncertain
- Excessive relative to tested alternatives
- Not estimable

No falsely precise maximum prices.

### Alternative defender recommendations

Research the identification of:

- Similar production at lower expected cost
- Different positional archetypes that fit the actual scoring card
- Short-term veteran alternatives
- Developmental alternatives
- Existing roster solutions
- Waiver or draft alternatives

A substitute must be evaluated in the same team context as the original target. Do not merely rank defenders by value
divided by raw PPG.

### Deliverable C — Acquisition shadow model

Build reproducible scenario evaluations and tests. No production recommendation changes until predictive, calibration,
and regression evidence supports them.

## SECTION 7 — SELLING AND NEGOTIATION INTELLIGENCE

Research how to identify defensible IDP sales. Evaluate:

- Market return versus independent value
- Team utility surrendered
- Replacement acquisition cost
- Contender/rebuilder timing
- Positional surplus
- Age and injury risk
- Pick packages
- Multi-team trade possibilities
- Market liquidity
- Unrealized gains from apparently favorable trades

Do not assume managers will pay their reference calculator's full listed values. Do not label a sale profitable simply
because the IDPTC number is greater than our consensus number. The completed legal roster and realistic acquisition
alternatives must remain central.

Deliver private, evidence-backed selling recommendations in shadow.

## SECTION 8 — ROOKIE DRAFT, STARTUP, AND AUCTION RESEARCH

### Rookie drafts

Analyze the actual league's historical rookie draft selections. Measure:

- Actual IDP selection order
- IDP selection distribution by round
- Elite-IDP position premiums
- Offensive versus defensive selection patterns
- Changes after league expansion and scoring changes
- Availability probability at subsequent picks
- Owner positional preferences, if sufficiently sampled
- Historical player outcomes, using proper cutoffs

Supplement with compatible external IDP-specific draft samples where licensed and available. Investigate The IDP Show's
combined offense-IDP rookie ADP as a candidate reference. Do not use offense-only ADP as if it describes mixed IDP
drafts.

Develop and test a draft decision that compares selecting the target now versus taking another player and risking the
target being unavailable later.

### Startup drafts

Model the entire draft state:

- Current roster composition
- Remaining starters
- Replacement scarcity
- League format
- Other teams' needs
- Available player pool
- Future pick positions
- Expected player availability

Use actual draft evidence where available and abstain when no comparable population exists.

### Auction drafts

Reuse the existing auction authoritative components. Research a bid model using actual auction dollars and:

- Remaining team budgets
- Required roster spots
- Competition
- Expected future nomination prices
- Replacement alternatives
- Player utility
- Budget opportunity cost

Do not use uncalibrated dynasty trade points as auction dollars.

### Deliverable D — Draft and auction research

Produce empirical ADP coverage, draft-selection models, auction calibration evidence, and shadow recommendation
prototypes. No automatic activation.

## SECTION 9 — CONTINUE IDP VALUATION ACCURACY RESEARCH

Do not close the existing IDP program merely because the market-price layer is being built. Investigate the remaining
unresolved questions from Lanes A–H. Particularly:

- Whether elite-defender consensus compression improves or harms predictive accuracy
- Whether the league-specific cross-position level is justified
- Whether source freshness explains part of the disagreement
- Whether replacement anchors are structurally biased
- Whether a full 17-game outcome window changes earlier conclusions
- Whether DL, LB, and DB need different correction methods
- Whether best-ball marginal utility has predictive value beyond the existing consensus
- Whether IDPTC and other vendors genuinely share independent market information

Do not invent a flat IDP multiplier. Do not use circular market matching as proof of predictive improvement. Keep all
candidates isolated and shadow-only.

Any suggested canonical value adjustment must go through its existing owner and independent promotion process. A
candidate must demonstrate forward or properly held-out improvement on an appropriate target.

## SECTION 10 — CALIBRATION AND MODEL RELIABILITY

Current best-ball simulation calibration remains a separate blocker. Before using precise changes in championship
probability to justify an acquisition premium:

1. Inspect the latest simulation calibration research and production model.
2. Determine whether the estimated playoff or championship changes are adequately calibrated.
3. Quantify uncertainty.
4. Avoid false precision.
5. Abstain or provide explicitly caveated scenario analysis where calibration is inadequate.

Do not let an unreliable championship probability override a sound market or roster decision. No model may gain
authority merely because it produces a confident-looking number.

## SECTION 11 — HISTORICAL BACKTEST DESIGN

Create reproducible comparisons among:

- Current canonical values
- IDPTC
- Existing independent source consensus
- Proposed league-market pricing
- Proposed team-utility acquisition methods
- Proposed draft availability methods
- Proposed combined decision rules

Evaluate each against an appropriate target.

### Market predictions

Use future completed trades and draft decisions, while acknowledging that accepted exchanges are not exact
reservation-price observations.

### Utility predictions

Use held-out, league-scored lineup contribution, marginal roster effects, and adequately calibrated multi-year outcomes
where available.

### Acquisition recommendation performance

Evaluate opportunity cost, substitution quality, and counterfactual roster improvement. Avoid evaluating a proposed
decision with a target that it directly optimizes in-sample.

### Mandatory safeguards

- Historical timestamp integrity
- Same-season scoring identity
- No future-data leakage
- Source-lineage deduplication
- Player and pick identity correctness
- Point-in-time roster reconstruction
- Correct package mathematics
- Independent-league and chronological holdouts
- Pre-registered hypotheses and gates
- Confidence intervals
- Sensitivity to sample restrictions
- Sensitivity to sparse IDP trade populations
- Explicit insufficient-data outcomes

Use the existing test conventions. Do not claim a model improved predictive performance unless the acceptance gates
support it.

## SECTION 12 — PRODUCT AND UI DESIGN

Design a private, league-aware acquisition view within existing trade surfaces. Potential displays:

**Independent Value**

- Chase Upside canonical value
- Source confidence
- Reason for source disagreements

**League Market**

- IDPTC reference
- Estimated acquisition price, if supported
- Estimated sale price, if supported
- Comparable completed trades
- Market coverage and freshness

**Team Impact**

- Net roster effect
- Positional replacement
- Legal roster consequences
- Current-season utility
- Long-term utility where supportable
- Uncertainty
- Alternative acquisitions

**Recommendation**

- Keep one authoritative top-line decision
- Explain when market price and independent value disagree
- Explain what can or cannot be inferred
- Identify missing information
- Identify alternatives
- Identify whether paying a premium has demonstrated team benefit

Proposed categories such as "strategically justified premium" are exploratory. Do not independently invent another
verdict owner. Keep the public neutral calculator's fairness semantics unchanged. All league-private information must
remain private.

Use source labels to avoid confusing:

- IDPTC published price
- Chase Upside market consensus
- Estimated league price
- Predicted utility

## SECTION 13 — WORKSTREAMS AND PARALLEL EXECUTION

Use a coordinated, resource-efficient approach. Suggested independent workstreams:

- **Lane A — Historical Trade Recovery.** Own-league transaction history, season-chain validation, completeness audit.
- **Lane B — Market Model Research.** Comparable trades, price constraints, partial-pooling models, uncertainty.
- **Lane C — Canonical IDP Accuracy.** Ongoing source compression and cross-position validation.
- **Lane D — Team Acquisition Utility.** Opportunity-cost and alternative-defender research.
- **Lane E — Draft and Auction Markets.** IDP selection timing, ADP, auction bidding.
- **Lane F — Integration and Acceptance.** Authoritative owner mapping, shadow UI contracts, review, regression,
  rollout.

Do not assume these lanes are completely independent. Publish a dependency matrix before assigning agents. Use
isolated branches or worktrees. No two agents should own the same mutable files simultaneously. Reuse existing
authoritative owners rather than building parallel versions. Respect the current worker concurrency limit in the
repository guidance. Do not start expensive redundant research agents for work that a deterministic read or script can
accomplish.

Do focused validation continuously and broader integration testing at the appropriate merge gates. Preserve essential
checks and independent reviews. Maintain compact durable handoffs. Report actual results, not simply counts of tasks or
PRs.

## SECTION 14 — IMPLEMENTATION PHASES

### Phase 0 — Current-state reconciliation

Deliver:

- Current deployment state
- Authoritative files and components
- Open PR and owner-claim map
- Confirmed research gaps
- Dependency graph
- Research plan

### Phase 1 — Historical trade and draft census

Deliver:

- Verified league-season history
- Completed transaction census
- IDP trade classification
- Historical valuation coverage
- Draft selection census
- Format changes and missing-data limitations

This phase is mandatory before any league market-price claims.

### Phase 2 — Shadow market-price research

Deliver:

- Hypothesis tests
- Candidate market model
- Confidence/abstention design
- Temporal validation
- Comparison with IDPTC and canonical values

No production voting.

### Phase 3 — Shadow acquisition and selling intelligence

Deliver:

- Whole-roster opportunity-cost calculations
- Alternative acquisition comparisons
- Buying and selling test scenarios
- Sensitivity analyses
- Validation results

### Phase 4 — Draft and auction prototypes

Deliver:

- Availability estimates
- Draft opportunity-cost framework
- Auction-budget opportunity cost
- Backtests and limitations

### Phase 5 — Additive, non-authoritative integration

Only where the evidence and existing authorization permit:

- Show direct source comparison
- Explain the confidence state
- Show validated comparable market evidence
- Expose experimental estimates privately and clearly labeled

Do not alter the canonical ranking or verdict just to expose information.

### Phase 6 — Owner decision package

Present all candidate changes requiring approval. Include predicted benefits, evidence, downside risk, affected
consumers, tests, flags, and rollback mechanisms. Nothing owner-held activates without explicit approval.

## SECTION 15 — OWNER RESERVED CHANGES

These require a separate owner decision:

- Canonical IDP value changes
- IDP source voting or weight changes
- Shared market-anchor changes
- Replacement-level promotion
- League-specific fair-value promotion
- Public fairness changes
- Package mathematics changes
- Recommendation rule-table changes
- Production feature-flag activation
- Scoring-card changes
- Any new model affecting live trade verdicts

Do not infer approval from the presence of this research directive. Existing project-wide approvals for routine
development and merging do not override owner-reserved methodology decisions.

## SECTION 16 — VALIDATION AND RELEASE CONDITIONS

Every additive implementation must have:

- Defined authoritative owner
- Tests for missing and stale data
- Tests for unpriced players and picks
- Historical cutoff tests
- Multi-team trade invariants
- Privacy and cross-league isolation tests
- No double-counting of value-derived evidence
- No regression of public market fairness
- Correct league selection and scoring propagation
- Deterministic replay fixtures
- Source and model provenance
- Review from an independent agent or reviewer
- Passing required exact-head CI checks
- Clear rollback procedure

Do not promote a predictive model from synthetic power-study results alone. Do not promote a player-valuation candidate
based on in-sample alignment with existing market sources. Do not activate a market-price model that cannot reliably
distinguish acquisition price from independent value. Do not silently replace missing numbers with zero. Do not report a
successful deployment without verification of the actual production SHA and affected functionality.

## SECTION 17 — FINAL REQUIRED OUTPUT

At the conclusion of the investigation and approved development, provide a consolidated report containing:

1. Current repository and production state.
2. Every season of own-league history recovered.
3. Actual verified trade and draft population sizes.
4. Evidence for or against IDPTC as the prevailing league market.
5. Position- and tier-specific market differences.
6. Whether our canonical IDP valuations appear systematically inaccurate.
7. Evidence-supported defender acquisition strategy.
8. Evidence-supported defender selling strategy.
9. Rookie draft strategy.
10. Startup and auction strategy.
11. Recommended production architecture.
12. Existing modules reused.
13. New components implemented.
14. Models tested and rejected.
15. Models retained in shadow.
16. Outstanding data-quality or sample-size blockers.
17. Pull requests and their review/merge state.
18. Exact production deployment and verification state.
19. Owner decisions still required.
20. Next highest-value actionable research or implementation items.

Distinguish these statuses throughout: VERIFIED, IMPLEMENTED, MERGED, DEPLOYED, VERIFIED IN PRODUCTION, RESEARCHED,
SHADOW ONLY, INCONCLUSIVE, BLOCKED, REQUIRES OWNER APPROVAL. Never treat those states as interchangeable.

## Ultimate success criterion

Chase Upside must help a dynasty manager answer: "Even if my league charges more for this defensive player than our
calculator says he's worth, is acquiring him at that price the best decision for my team—or is there a better way to
build a championship roster?"

The system should also answer the reverse when selling defenders and provide evidence-based draft and auction
acquisition guidance.

We are not attempting to make every valuation source agree. We are attempting to make the best possible dynasty
decisions using independent value, actual league market behavior, roster-specific utility, and honest uncertainty.

Begin with the current-state audit and the historical league trade/draft census. Execute approved independent
workstreams in parallel where safe, and preserve all owner-reserved approval gates.
