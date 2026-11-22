# Top 10 dynasty improvements, Chase Trade Market completion and implementation — owner directive, 2026-11-21

**Structured record** of the owner's chat directive "CHASE UPSIDE — TOP 10 DYNASTY IMPROVEMENTS, TRADE MARKET
INTELLIGENCE & IMPLEMENTATION". It names the repository `jasonleetucker-code/riskittogetthebrisket` and production
https://chaseupside.com. Every requirement, limit and deliverable is kept; the prose is condensed.

- **Intake rows:** DYN10-1 … DYN10-14 in `docs/OWNER_REQUESTED_TODO.md`.
- **Authorization:** `docs/EXECUTION_PLAN.md`, dated section of 2026-11-21.
- **Scope:** it runs inside the existing planning hierarchy and the existing Chase Trade Market owners. It is not a
  second roadmap, ledger or model architecture.

**Nature:** an audit **and** implementation directive.
1. Audit the dynasty platform.
2. Finish and validate Chase Trade Market (CTM), the existing project that learns independent player and pick prices
   from real completed dynasty trades.
3. Rank exactly ten improvements, then start implementing them in priority order.
4. Do not stop at a roadmap.

**Goal:** an evidence-based dynasty decision-intelligence platform that combines six inputs:
- independent fundamentals;
- established dynasty market providers;
- prices observed in completed trades;
- league-specific scoring and roster construction;
- roster-aware trade recommendations;
- historical learning with predictive validation.

The intelligence must be proprietary and backed by evidence, not attractive arbitrary numbers.

## Part 1 — Scope

- **Dynasty only.** No DFS (lineups, DraftKings / FanDuel, salary projections), no betting, no unrelated fantasy
  products, and no League Tycoon (paused).
- **No site-wide redesign.** Another developer owns the frontend redesign. Use existing components. Targeted
  functional UI is allowed.
- Shared infrastructure is allowed where dynasty functionality needs it.
- Preserve working features and calculations unless evidence justifies a change.
- Before touching code, check worktrees, open PRs, claims and incomplete hardening work (#2287–#2290). Never
  interfere with another developer's unmerged changes.

## Part 2 — Chase Trade Market: intent and history

- **Intent.** Learn how managers actually value players and picks from completed trades across real dynasty leagues:
  relative prices, uncertainty, trends, and a comparison with our valuations.
- **A completed trade is not an equal-value exchange.** Objectives, positional needs, risk and information differ.
- **End state.** Verified transaction-derived prices become an *additional, appropriately controlled* signal in
  dynasty valuation. **Immediate activation of an unvalidated model is NOT authorized.**
- **Reuse; never restart or fork.** The PRs to recheck for current state:
  - #1586 completed-trade ledger;
  - #1610 comparability dispositions;
  - #1721 recent trades in the calculator;
  - #1742 comparable-trade matching and database;
  - #1752 comparable trades as a non-voting lens;
  - #1851 evidence fields and provenance;
  - #1852 league maturity, lineage, census and reserve;
  - #1858 registry promotion gates;
  - #1865 synthetic market simulation, estimator comparison and power study;
  - #1876 release-train integration;
  - #1907 manager-lineage concentration and validation holdout;
  - #1985 historical trade and draft census;
  - #1987 IDP market-hypothesis preregistration;
  - #1989 historical canonical-value coverage;
  - #2202 out-of-sample package-model validation.

  Verify the canonical paths (`src/trade/market_trade_*`, `comparable_trades.py`,
  `src/model_registry/promotion_gates.py`, `docs/market_trades/*`) and keep their ownership boundaries.
- **The 2026-10-20 research figures are historical, not current.** They were roughly:
  - 29,638 canonical groups;
  - 18,690 graded;
  - 11,565 leagues;
  - 19,652 KTC groups;
  - 9,957 Sharp/Sleeper groups.

  Recompute them from authoritative production data. Graded ≠ model-eligible. Possible problems include duplicates,
  incomparable formats, missing metadata or point-in-time prices, correlated populations, maturity rules, and
  task-inappropriate records.
- **KTC trades are not necessarily independent of the KTC prices already voting.** Never count the same evidence
  twice under different names.

## Part 3 — Completing CTM (phases)

| Phase | Requirement (condensed) |
|---|---|
| CTM-1 Current-state audit | Trace the pipeline: acquisition → identity → dedup → comparability → historical timing → eligibility → training data → estimation → evaluation → registry → shadow → canonical integration. Classify each stage as one of: working+deployed / implemented-inactive / research-only / partial / blocked by data / blocked by owner / broken / superseded / not implemented. State exactly why CTM does not influence canonical values, and whether any production consumer reads trade-derived prices (examine the serving path). |
| CTM-2 Data coverage | Measure today's dataset. Cover: totals; independent trades after dedup; verified dynasty and verified mature leagues; offense; IDP DL/LB/DB; rookie vs veteran; picks; SF vs 1QB; TEP; best ball vs lineup; exact-format vs broad-context; exclusions with reasons; managers and lineages where safely measurable; observation age; missing metadata and point-in-time evidence. Separate KTC from independently collected Sleeper trades. Assess Sharp-discovery selection bias and the need for more discovery, history capture or format classification. Reuse existing collectors; no duplicated acquisition. |
| CTM-3 Unfinished infrastructure | Inspect #1852 and later work. Resolve genuine gaps: maturity, cross-season identity, manager lineage, dedup, train/validation independence, leakage, point-in-time format, missing historical prices, eligibility and sample size. Never silently merge stale branches. Use read-only production diagnostics where authorized, and never mutate production data during exploration. |
| CTM-4 Estimator | Evaluate the existing approaches before inventing new ones. Treat each of: identity, positive scales, packages and consolidation, multi-team trades, scoring, lineup scarcity, roster size, SF, TEP, IDP, recency, availability, pick horizon, manager/league dependence, sparsity, outliers and drift. Respect identifiability limits and never fabricate values without identifying evidence. Compare simple baselines to complex methods. |
| CTM-5 Validation | Use chronological, league-holdout and manager-lineage leakage analysis, future unseen trades, uncertainty intervals, position-specific error, coverage, and comparisons against existing methods. Where authorized, compare with KTC, IDPTC, DLF, FantasyCalc, canonical values and fundamentals, using compatible formats and point-in-time data. Market-price prediction ≠ player-quality prediction. Respect preregistration and owner approval. **Do not touch reserved holdouts of draft preregistrations.** |
| CTM-6 IDP focus | Cover edge, DT, LB, S, CB, elite and young IDP, IDP-for-offense and IDP-for-pick trades, and premiums in 3/3/3 leagues. Our own league is not a sufficient market. Measure cross-league evidence separately, and report insufficiency instead of inventing a premium. |
| CTM-7 Shadow values | Internal output, where data supports it: player, asset id, format, implied value, date, evidence count, independent leagues, effective sample size, interval, coverage, trend, canonical value and difference, provenance, model version. It stays separate from canonical values. An optional internal comparison view uses existing UI conventions. It is never promoted because tests pass. |
| CTM-8 Controlled integration | Before any activation: incremental predictive value; comparison with canonical; correlation with existing markets; evaluation by offense / IDP / picks; value movement and ranking disruption; sparse behavior; shadow runs; promotion gates; rollback; owner approval. Never silently change weights, formulas, canonical values or flags. If prerequisites pass but approval is outstanding, prepare the exact change and evidence for the owner. A validated non-voting shadow model is a valid success. |

## Part 4 — Ten candidate areas (evidence decides the final order)

1. CTM (above).
2. Canonical valuation engine. Cover: weights and contributions; correlated and stale sources; native vs rank-derived
   values; offense/IDP calibration; replacement; age; scoring scarcity; confidence and missing data; BDVM; historical
   accuracy; CTM compatibility. Keep *fundamental utility* separate from *market price*; they inform each other only
   through a validated method.
3. Trade Finder / Analyzer: Best Offers, Package Builder, Golden Upgrades, Angle, War Room, multi-team, counteroffers,
   post-trade simulation, forced drops, contender/rebuilder, comparable trades, market disagreement, partners.
   Historical trades are never automatically fair.
4. Automated team advisor: buy, sell-high, rebuild, contend, weaknesses, picks, aging, concentration, sustainability.
   Every recommendation carries evidence, impact and uncertainty, and reuses canonical systems.
5. Sleeper and multi-league: sync, roster and pick ownership, scoring, transactions, history chains, selection,
   navigation, freshness, identity. The correct league context reaches every tool.
6. Championship probability and posture: best ball, scoring projections, IDP starters, depth, injury uncertainty,
   playoffs, sustainability, contend / retool / rebuild. No unsupported precision.
7. Waiver / FAAB: availability, add/drop, IDP streaming, dynasty upside, lineup impact, budget, priorities, protected
   players. Realistic moves, not generic lists.
8. Rookie draft and draft capital: offense and IDP rookies, pick value and identity, future classes, acquisition,
   auctions and budget strategy, team-specific recommendations, uncertainty when rookie sources are stale.
9. League market intelligence and Manager Scout: tendencies, partners, preferences, positions, pick trading, league
   patterns. History is evidence of acceptance, never proof.
10. Unified command center: connect existing features through the League Hub and dashboard without a redesign.

## Parts 5–6 — Better opportunities and ranking

- Repairs can outrank features. Hunt for:
  - wrong values;
  - double counting;
  - scarcity errors;
  - IDP mapping bugs;
  - stale data;
  - broken recommendations;
  - scoring propagation errors;
  - hidden capabilities;
  - misleading probabilities;
  - missing validation;
  - disconnected workflows;
  - duplicate engines;
  - pick-identity errors;
  - broken cross-league comparisons.
- Rank **exactly ten** on a 100-point rubric. Assess complexity and risk separately.

  | Criterion | Points |
  |---|---|
  | Decision quality | 30 |
  | Accuracy and reliability | 20 |
  | Usefulness and frequency | 15 |
  | Improvement over existing | 15 |
  | Feasibility and reuse | 10 |
  | Differentiation | 10 |

- Do not inflate CTM's score, but credit the completed investment.
- For each improvement, give: current state, owners, shortcomings, proposal, benefit, dependencies, complexity,
  sequence, tests, acceptance and security/privacy. State CTM's rank and what holds it back.

## Parts 7–9 — Execution, standards and scenarios

- **Workstreams:**
  - A: CTM — eligibility, validation, trustworthy shadow; no duplicate model.
  - B: valuation quality and BDVM, without disturbing CTM evaluation.
  - C: trade decision intelligence.
  - D: the remaining ranked items.

  Parallelize independent work; serialize shared models, source registries and canonical trade engines.
- **Standards:**
  1. Verify before changing.
  2. Reproduce defects.
  3. Add regression tests.
  4. Preserve provenance.
  5. Prevent leakage.
  6. Protect private league data.
  7. Use only authorized sources.
  8. Keep canonical asset and pick identity.
  9. Keep scoring consistent.
  10. Keep freshness and missingness explicit.
  11. Add no fabricated precision.
  12. Use model governance.
  13. Record model and data versions.
  14. Compare against the incumbent.
  15. Provide rollback.
  16. Follow PR and release policy.

  No weight, constant, promotion or restricted activation without evidence and authorization. Owner decisions get a
  recommendation with alternatives, and a pending decision never stops independent work.
- **Scenarios:**
  - 12-team SF, 2 TE, heavy TEP, 9 IDP starters, non-IDP, deep rosters, best ball;
  - package trades; 2-, 3- and 4-team trades;
  - rookie and future picks, auctions;
  - contending and rebuilding teams, forced releases;
  - missing or stale rankings, incomplete trade coverage;
  - for CTM: duplicates, format incompatibility, collection-time and future leakage, correlated sources, repeated
    managers and leagues, sparse players, unidentifiable graphs, package distortion, outliers, holdout performance,
    reproducibility, and promotion refusal on a failed gate.

  Synthetic success without real-data evidence stays experimental.

## Parts 10–11 — Deliverables and success

| Deliverable | Content |
|---|---|
| A — CTM status report | Collection, coverage, eligibility, offense, IDP, picks, model, validation, production state, blockers, next steps. Current audit, not historical counts. |
| B — Top 10 | Rank, improvement, existing state, score /100, complexity, benefit. Exactly ten, with departures explained. |
| C — Implementation | Changes, files, tests, commits, PRs, and integration / deployment / verification kept separate. |
| D — CTM advancement | Tangible progress toward a validated model. No readiness claim without evidence. |
| E — Updated roadmap | Update the existing canonical planning docs. Each item is one of: verified complete / built inactive / research only / in progress / waiting on owner / blocked by data / deferred. No competing backlog. |

**Success** means the platform answers five questions better:
- What is this player worth?
- What are managers paying?
- What does our system see that the market misses?
- Would this trade help my roster?
- What should I do next?

Proving that the incumbent beats a challenger is a valid outcome. Accuracy, independent validation and useful decisions
matter more than feature count.
