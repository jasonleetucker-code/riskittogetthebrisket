# Analyze Trade v3 — decision methodology and lineage map (#792, Batch 4)

**Owner:** `src/trade/analyze_trade.py` (the one canonical Analyze Trade decision owner).
**Contract:** `analyze_trade_v3`, served by `POST /api/trade/analyze` as `analysis`.
**Parameters:** `config/trade/analyze_trade.json`. Every threshold is a **PRIOR**: a declared judgement, not a calibrated fit. There is no outcome data yet to fit a trade-recommendation threshold against. Changing one is an owner-visible methodology change.
**Preregistered:** this document and the `decision` block of the config were written before any threshold was tuned against outcomes. Nothing here was fitted to make examples come out a particular way.

## 1. The three questions stay separate

| Question | Where it is answered | May it vote? |
|---|---|---|
| **A. Market / exchange price**: what comparable managers pay | `marketCorroboration`: the KTC Market benchmark plus completed-trade comparables | **No.** It corroborates or disputes the canonical direction and can cap confidence. |
| **B. Fundamental dynasty value**: what the assets are worth | `canonicalEquity`: canonical `rankDerivedValue`, with the exact KTC Value Adjustment shown separately | **Yes.** |
| **C. Roster-specific utility**: what the trade does for *this* team | `rosterImpact`: #1173 best-ball utility on the **final legal roster** | **Yes.** |

A trade can be slightly expensive by market price, fundamentally attractive and excellent for this roster all at once. The packet can say exactly that, because each answer keeps its own section and label.

## 2. Roles

* **VOTE** sets the direction: `canonicalEquity`, `rosterImpact`. Only these two enter the rule table.
* **MODIFIER** never sets a direction. It can do two things only:
  * cap confidence;
  * move the decision by **at most one step**, and only on evidence the votes do not already carry.

  The modifiers are `feasibility`, `marketCorroboration`, `valueUncertainty` and `competitivePosture` (through the strategic-fit rule).
* **CONTEXT** explains and never moves the decision: `ageWindow`, `currentSeasonEquity`, `draftCapital`.

Every section returns the same fields: `available`, `role`, `lineage`, `direction`, `magnitude`, `coverage`, `freshness`, `provenance`, `detail`, plus `unavailableReason` when unavailable. This keeps "not computed", "computed and neutral" and "context only" from ever looking alike.

## 3. Lineage map: one body of evidence, one vote

| Lineage | Upstream evidence | Sections that read it | Votes |
|---|---|---|---|
| `canonical_value` | blended source consensus → `rankDerivedValue` (includes KTC Crowd, KTC Trades and every voting source) | `canonicalEquity` (vote), `valueUncertainty` (modifier), Team Strength (context inside `rosterImpact`) | **1** |
| `league_scored_projection` | league-scored ROS projection ensemble | `rosterImpact` (vote), `currentSeasonEquity` (context) | **1** |
| `ktc_market_benchmark` | KTC's own published Crowd+Trades, the same two families already inside canonical value | `marketCorroboration` (modifier) | **0** |
| `completed_trade_ledger` | deduplicated completed trades (one per `underlyingTradeId`) | `marketCorroboration.comparables` (modifier) | **0** |
| `league_roster_rules` | roster limit, taxi, forced drops (#843) | `feasibility` (modifier) | **0** |
| `team_strategy_context` | Competitive Posture: an interpretation of strength, odds and age | `competitivePosture` (modifier, through strategic fit only) | **0** |
| `canonical_age` | board ages and the age-value portfolio | `ageWindow` (context); one input to strategic fit | **0** |
| `league_pick_ownership` | canonical pick ownership (Wave A) | `draftCapital` (context) | **0** |

Explicitly rejected: weighted panel averages such as "30% value + 20% Monte Carlo + 20% second opinions + 30% roster". Monte Carlo bands are centred on the same canonical p50, and second opinions are sources already inside canonical value. Averaging them would count one lineage two or three times. Monte Carlo is **not read** by the decision.

## 4. Decision rules

1. **Rule table over the two votes.** This is unchanged from v2, so existing outcomes do not move.
   * both favour → MAKE/HIGH;
   * favour + neutral → LEAN_MAKE/MEDIUM;
   * favour vs oppose → **TOO_CLOSE** (the votes conflict, and "depends" is the honest answer);
   * the opposing cases mirror these.
   * When only one vote is available, the result is MAKE/PASS only when its own magnitude is large: VA "stretch", or roster "large" (3× its neutral band). Otherwise it is LEAN.
2. **Feasibility (modifier).**
   * A cut that releases priced value, or a worsened overage, moves the decision one step toward PASS.
   * Resolving an overage moves it one step toward MAKE.
   * When no legal cleanup exists, the decision is capped at TOO_CLOSE.
3. **Strategic fit (modifier, preregistered).** The posture **label alone never moves the decision**. A step needs the label *and* independent evidence for that label's concern, and is at most one:
   * **PUSH**, giving up canonical value, season evidence present, no material title gain (< `titleDeltaMaterialPp`, or not significant under paired seeds): one step toward PASS.
   * **PUSH**, giving up at most a "lean" of canonical value for a material, significant title gain: one step toward MAKE.
   * **REBUILD**, incoming aging value share ≥ `agingShareMin` (age ≥ `agingAge`, the start of the canonical 28_30 band), with no canonical-value edge: one step toward PASS.
4. **Confidence (modifiers; never flip direction).**
   * Any named uncertainty brings HIGH down to MEDIUM.
   * KTC Market disagreement, where the benchmark covers ≥ `benchmarkCoverageMin` of the traded value, caps confidence at MEDIUM.
   * A low-confidence share of the traded value ≥ `lowConfidenceShareMedium` caps at MEDIUM; ≥ `lowConfidenceShareLow` caps at LOW.
   * An unstamped share ≥ 50% caps at MEDIUM. Unknown confidence is not high.
   * `confidenceDetail.reasons` states which rule fired.

A confident MAKE or PASS needs both votes to agree with no modifier firing. When the dimensions conflict, TOO_CLOSE is a valid result; no decisiveness is manufactured.

## 5. Final legal roster

`rosterImpact` and `finalRoster` read the one shared sequence: before roster → apply trade → roster capacity → required legal cleanup (forced drops from #843) → re-solve → compare. That sequence is `roster_capacity.final_legal_roster` / `simulate_final_legal_roster`.

For analysis, the simulator now also passes the board's positional ranks, the league size, ages and the youth curve (`trade_simulator.roster_profile_inputs`). That makes **Team Weakness before/after** real (`needsFixed` / `needsCreated` / urgent positions) and adds the **age-value portfolio** before/after on the same meaningful cores. Plain `/api/trade/simulate` keeps its earlier shape.

## 6. Missing is never zero

* An asset KTC does not price (IDP, deep rows, picks without a benchmark) is **excluded** from the benchmark and listed in `assetsWithoutBenchmark`. Coverage is reported as a share of traded canonical value.
* An asset with no confidence stamp counts as unknown confidence.
* Missing ages leave `ageWindow` unavailable (`no_age_evidence`).
* `currentSeasonEquity` is `counterfactual_not_wired` until the playoff simulator's paired-seed counterfactual is fed per request. That is a named follow-up, and no estimate is substituted.
* Draft capital never counts a pick the sender does not hold (`notOwnedBySender`). Slot projections stay `unvalidated` until the canonical Pick Projector (#1652) is consumed.

## 7. Not done here (named follow-ups)

* **Season counterfactual:** `seasonImpact` (playoffs, bye, title) from `playoff_sim.simulate_trade_impact` + `twin.strength_deltas_from_rosters`, materialized per league so only the delta runs per request.
* **Completed-trade comparables:** `marketComparables` from the comparables query layer. The section already reads it when present; until then it reports `comparables_not_wired`.
* **Pick Projector:** slot and tier probabilities for owned picks, after #1652.
* **Retire the second verdicts:** `team_impact.verdict` is a weighted composite the analyzer never reads; the TradeMeter's client-side fairness label is to be relabelled as value balance, not a recommendation.
* **Historical validation:** a point-in-time replay that keeps separate targets (market fairness, later market movement, football outcome, roster utility, seasonal effect), with no hindsight winner label.

## 8. Promotion boundaries

v3 promotes no value model, source weight, Signals IDP vote, comparable-price model, best-ball model or uncertainty model. The best-ball roster utility keeps the voting role it already had (PR #1459). This document neither promotes nor demotes it.
