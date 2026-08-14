# Historical Trade Replay / As-Of Team Fit — Owner Specification

**Status:** OWNER-APPROVED / C-REPLAN DEPENDENCY-GATED  
**Recorded:** 2026-08-14  
**Canonical product family:** Trade History → Trade Calculator / Trade Desk / Team Strength & Weakness  
**Purpose:** make a completed trade answer what it meant for the user's roster **when the trade was made**, rather than incorrectly evaluating the old package against today's already-changed roster.

This is a future product requirement. It does **not** authorize implementation during the B-series. The post-B C-series replan must place it after the historical-data, canonical-value-history, roster-state, Team Strength/Weakness, and trade-analysis dependencies needed to make the result trustworthy.

---

## 1. Product job

When a user opens a completed league trade from Trade History, Chase Upside should be able to answer three distinct questions:

1. **Original Decision / At the Time** — How did this trade fit the user's team immediately before it happened, using only information that was available as of the trade timestamp?
2. **Outcome Since** — What actually happened after the trade?
3. **Today's View** — How would the same original package be evaluated with current information now?

These are different analyses and must never be silently blended.

The core owner requirement is that **Open in Trade Calculator from Trade History must not naively evaluate a completed trade against the user's current roster**. The acquired players may already be on the roster, outgoing players may be elsewhere, and later trades/waivers/drops/injuries/draft results may have changed the team substantially.

---

## 2. Historical Replay / As-Of mode

Opening a completed trade from Trade History should launch a clearly identified historical mode, conceptually:

> **HISTORICAL REPLAY — AS OF 2026-08-03 14:22**

The calculator/review surface must reconstruct the relevant league/team state immediately **before** the transaction, apply only the selected historical trade, and compare the resulting immediate-after state.

The historical trade itself remains immutable evidence. Replay is an analysis over that evidence, not a rewrite of trade history.

A user may explicitly switch to **Today's View**, but current-state analysis must never masquerade as the original decision context.

---

## 3. Roster reconstruction contract

For the selected historical trade:

1. identify the canonical league, teams/managers, transaction ID, and transaction timestamp;
2. reconstruct each participating roster immediately before the trade by replaying authoritative roster-changing events through `T-1`;
3. apply the historical trade exactly once to produce the immediate-after state;
4. preserve player and pick identity, including original-franchise pick ownership and exact-slot identity where already known at that date;
5. include FAAB or other league assets when the canonical trade model supports them;
6. use the league's actual scoring/roster configuration applicable to that historical season/date when available;
7. never infer current ownership backward merely from today's roster.

Potential event sources include drafts, trades, waiver claims, free-agent adds/drops, commissioner transactions, pick transfers, and other roster-changing records exposed by the canonical league-history owner.

If the available transaction history cannot reconstruct a roster defensibly, return a degraded/partial state rather than inventing the missing ownership.

---

## 4. Original Decision / At-the-Time analysis

The historical replay should use the same canonical future Team Fit / Analyze Trade primitives as live trades, but with **as-of inputs**.

Where historical evidence exists, the analysis may include:

- canonical asset equity before/after;
- Team Strength change;
- Team Weakness change;
- starting-group / best-ball lineup displacement;
- positional league rank and depth changes;
- roster construction and concentration;
- age/window effects;
- draft-capital changes;
- roster marginal impact;
- contender/rebuilder/window context only where the canonical methodology is validated;
- independent market corroboration that actually existed at the time;
- uncertainty/confidence appropriate to the historical evidence.

The output should explain both improvements and costs. A single trade grade must not erase meaningful tradeoffs.

Example dimensions are illustrative; implementation must consume the canonical owners that exist when C reaches this feature rather than duplicating them.

---

## 5. Strict no-future-information rule

**Original Decision mode is an as-of-time analysis.**

It may not silently use information that became known after the trade, including:

- today's canonical value;
- a later ranking snapshot;
- later injuries or recoveries;
- later depth-chart changes;
- later player performance;
- the identity of a rookie selected with a pick when that selection had not happened yet;
- current roster composition;
- later analyst opinions;
- later trade-market evidence;
- any hindsight-only model input.

If the exact historical observation is unavailable, use only an explicitly allowed nearest-prior/LKG rule with provenance. Do not use a future snapshot merely because it is closer in wall-clock time.

---

## 6. Historical evidence fidelity / provenance

Every historical replay should carry a compact reconstruction-quality record. Relevant inputs should be classified using states such as:

- **EXACT** — authoritative state/snapshot at the required time;
- **NEAREST PRIOR** — latest defensible observation before the trade;
- **RECONSTRUCTED** — deterministically derived from authoritative event history;
- **PARTIAL** — some required evidence exists but coverage is incomplete;
- **UNAVAILABLE** — cannot be recreated honestly.

The UI should make material limitations understandable without overwhelming the user.

Examples:

- roster reconstruction: EXACT/RECONSTRUCTED;
- canonical values: 18/20 exact same-day, 2 nearest-prior;
- historical ROS projections: UNAVAILABLE;
- historical injury context: PARTIAL.

Missing evidence must not silently become zero, neutral, or today's value.

---

## 7. Outcome Since lens

Outcome analysis is deliberately separate from decision quality.

Where evidence exists, **Outcome Since** may show:

- canonical value movement from trade date to later checkpoints/current day;
- realized fantasy production after the trade;
- games/weeks materially contributing to the acquiring team where the league model supports it;
- realized Player Impact / WAR / WAB evidence when canonical;
- injuries/availability that materially changed the outcome;
- what traded draft picks eventually became;
- subsequent asset lineage/trade-tree movement;
- whether acquired/outgoing assets were later moved;
- playoff/championship effects where deterministic attribution is defensible;
- current value of the original packages and/or their descendant assets, clearly distinguished.

Do not label an unforeseeable later outcome as proof that the original decision process was good or bad.

A trade can be a sound decision at the time and have a poor realized outcome, or vice versa. Chase Upside should preserve that distinction explicitly.

---

## 8. Today's View lens

**Today's View** asks a counterfactual current-information question:

> If these original trade packages were offered today, how would Chase Upside evaluate them now?

It may use current canonical values, current team/market context, and current intelligence, but must be clearly labeled as a present-day re-evaluation rather than historical truth.

When a pick has converted to a player, the product must decide explicitly whether Today's View compares the original pick asset at its historical identity or follows descendant asset lineage. If both are useful, show them as separate concepts rather than silently substituting one for the other.

---

## 9. Trade History → Trade Calculator workflow

The existing **Open in Calculator** / equivalent action from Trade History should become context-aware:

- new/current hypothetical trade → **LIVE MODE**;
- completed historical league trade → **HISTORICAL REPLAY / AS-OF MODE** by default;
- explicit user action → **TODAY'S VIEW**.

Historical mode should display the transaction date/time and reconstruction quality prominently enough to prevent confusion.

The calculator must not use today's selected-team roster simply because that roster is already loaded in the application.

---

## 10. Retroactive support for older trades

Trades made before this feature existed are eligible for replay.

The trade did not need to have been analyzed by Chase Upside when accepted. If the application can reconstruct the historical roster and retrieve defensible historical observations, it can run the later canonical analysis over that historical state.

Coverage will vary by date. The system must degrade honestly:

- roster-only replay may be possible even if historical projections are not;
- nearest-prior canonical value may be available when same-minute value is not;
- some older trades may support only a partial analysis;
- a trade with insufficient evidence should say so rather than generate a false precise grade.

---

## 11. Architecture / ownership

Do not create a second historical trade-analysis engine.

Historical Replay should orchestrate existing/future canonical owners:

- league transaction / roster-history reconstruction;
- canonical asset identity;
- canonical historical value snapshots;
- pick ownership / pick identity / pick valuation;
- Team Strength;
- Team Weakness;
- exact lineup/best-ball solver;
- roster marginal-impact engine;
- canonical Analyze Trade / Trade Desk decision contract;
- Player Impact / Awards history where relevant;
- Trade Trees / Asset Lineage;
- market/Second Opinions history where available.

The key architectural difference between Live and Historical modes is **time-scoped input selection**, not duplicated business logic.

---

## 12. Historical snapshot retention requirement

C planning must evaluate whether the data needed for future exact replay is currently retained. If not, introduce bounded snapshot/event retention **before** depending on it.

At minimum, preserve or be able to reconstruct the inputs that cannot be recreated later from authoritative event logs.

Snapshot policy must include:

- timestamp / effective-as-of time;
- league/scoring fingerprint where materially relevant;
- methodology/version provenance;
- canonical asset identity;
- enough information to distinguish what was known then from what became known later.

Do not backfill fake historical observations by applying today's model to data that did not exist at the time and calling the result historical.

---

## 13. Required tests

Before this feature is production-complete, automated coverage must prove at minimum:

1. deterministic roster reconstruction for a known transaction sequence;
2. the roster immediately before the selected trade is correct;
3. applying the trade produces the correct immediate-after ownership;
4. later transactions do not leak into the historical pre/post state;
5. current roster changes do not change a fixed historical replay result;
6. Original Decision mode never consumes a post-trade value/projection snapshot;
7. nearest-prior fallback never chooses a future observation;
8. missing historical evidence remains unavailable/partial rather than zero;
9. picks preserve canonical identity through ownership transfer and later slot resolution;
10. a completed trade opened from Trade History defaults to Historical Replay rather than Live/current-roster analysis;
11. Today's View is explicitly separate and may change as current data changes;
12. desktop and mobile show the same reconstructed state and analytical result.

Where multi-team trades are supported, include historical replay coverage for them as well.

---

## 14. Production acceptance gate

This feature is not complete because a historical trade can merely be loaded into the calculator.

Completion requires production proof that:

- a real completed trade reopens in historical/as-of mode;
- the pre-trade roster is correctly reconstructed;
- the immediate-after roster is correctly produced;
- the future canonical team-fit analysis consumes those reconstructed states;
- historical evidence has explicit provenance/fidelity;
- no future-information leakage occurs in Original Decision mode;
- Outcome Since remains separate from original decision quality;
- Today's View remains separate from both;
- older trades degrade honestly when evidence is incomplete;
- current-roster state cannot contaminate the historical result;
- the workflow is usable on authenticated desktop and mobile;
- relevant automated regression tests are green;
- the deployed result is production-verified.

---

## 15. C-series placement rule

The C-series dependency DAG should place this feature **after** the foundations it needs, especially historical snapshots/event reconstruction, canonical asset/pick history, Team Strength/Weakness, roster marginal impact, and the canonical Trade Decision / Trade Desk contract.

However, any historical-event/snapshot retention needed to make later replay possible should be introduced as early as the dependency graph justifies, so C does not discover at the end that the required evidence was never preserved.

The feature must appear in the C Scope Manifest and cannot be silently deferred if its approved dependencies are available.

**Owner end state:** Trade History becomes a decision-review and learning system, not merely a list of old transactions.