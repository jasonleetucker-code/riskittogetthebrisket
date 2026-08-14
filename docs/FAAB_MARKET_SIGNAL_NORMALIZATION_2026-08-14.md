# FAAB Market Signals, Budget Normalization & Sharp-League Evidence

**Owner decision date:** 2026-08-14  
**Tracking issue:** #830  
**Status:** APPROVED EXTENSION / AUDIT OF EXISTING CANONICAL FAAB SYSTEM  
**Applies to:** FAAB Recommendations, Waivers, Perfect Waivers, CE-19 Waiver Market / FAAB Market Ledger, Sleeper market heat, external-league and Sharp-league waiver evidence.

---

## 1. Owner intent

Improve FAAB recommendations using real market-demand and clearing-price evidence without letting popularity overpower player value or creating a second FAAB formula.

The canonical split remains:

1. **Objective FAAB Ceiling** — what the player is worth in this league/format.
2. **Recommended Bid** — what this specific team should bid given its balance, roster, timing and likely competition.

Market-demand evidence belongs only in #2.

---

## 2. Existing implementation that must be preserved

This is an extension/audit, not a greenfield rebuild.

The current code already does two important things correctly:

- `src/trade/faab_history.py` normalizes historical bids to **percent of that season's original FAAB budget**, explicitly accounting for the Brisket league having used $1,000 in 2024, $200 in 2025 and $100 in 2026.
- `src/trade/faab_recommender.py` already treats Sleeper trending / crowd evidence as **demand evidence in the market layer**, not as a reason to raise objective player worth.

Do not regress either invariant.

---

## 3. Canonical FAAB normalization

Every historical or external FAAB observation must first be converted to a budget-neutral percentage:

```text
normalizedBidShare = observedBid / originalStartingBudget
normalizedBidPct   = 100 * observedBid / originalStartingBudget
```

When the product wants to display the observation on the current Brisket $100 scale:

```text
equivalentOnCurrent100 = normalizedBidShare * 100
```

Examples:

- $40 on a $200 starting budget = 20% = **$20 equivalent** on the current $100 scale.
- $100 on a $1,000 starting budget = 10% = **$10 equivalent** on the current $100 scale.
- $0 on any valid starting budget = 0% and remains a real market observation.

### Binding rules

- Use the **original season starting budget**, never the manager's remaining balance, as the normalization denominator.
- Preserve raw bid and raw starting budget alongside normalized values for auditability.
- Missing/unknown original budget = **UNAVAILABLE / NOT COMPARABLE**, not an assumed $100 denominator.
- Zero-dollar bids are real observations and must not be filtered out merely because they are zero.
- The current site's recommendation can still be capped by the user's actual remaining balance after normalized market evidence is translated into the current league context.

---

## 4. Sleeper Most Added / Most Dropped → Market Heat

Sleeper platform trending should answer:

> **How much acquisition pressure appears to be building around this player right now?**

It does **not** answer:

> How good is the player?  
> What is the player's canonical dynasty value?  
> What is the player's objective FAAB ceiling?

### Most Added

Most Added is the useful side of the signal because it can indicate that many managers noticed the same role, injury, news or opportunity change and competition may rise.

Prefer a velocity/acceleration view when enough snapshots exist, such as 6h / 12h / 24h / 48h changes, over a single raw rank.

A user-facing presentation may summarize this as:

- COLD
- NORMAL
- WARM
- HOT
- SURGING

The explanation should expose why the label exists, e.g. `Sleeper adds accelerated sharply over the last 12 hours`.

### Most Dropped

Most Dropped is materially noisier because broad Sleeper activity includes redraft, shallow benches, bye-week churn, injury reactions and league formats unlike ours.

Therefore:

- treat drop activity as weaker contextual evidence;
- use less negative power than the positive power granted to add acceleration;
- prefer flagging a potential concern for supporting context over automatically slashing a bid;
- never let broad drop activity override strong league-specific or player-value evidence by itself.

### Weight / cap

Sleeper heat must remain a **bounded market-layer modifier**. Initial design target: absent backtest evidence supporting more, the net upward effect attributable to Sleeper heat alone should be modest, roughly capped around **10% of the pre-heat recommended bid**, with weaker downside power from drops.

The exact production transform is **evidence-gated**. Backtest/calibration may justify a different monotonic bounded mapping, but no unbounded multiplier stack may return.

---

## 5. External-league FAAB evidence

Where Sleeper transaction access and league metadata provide a completed waiver/free-agent bid and a trustworthy original FAAB budget, the site may ingest outside-league observations.

This includes eligible leagues already used by the site's Sharp systems.

### Keep four evidence populations distinct

1. **Own-league FAAB history**  
   Highest relevance for forecasting how this exact league clears waivers.

2. **Sharp-league FAAB behavior**  
   Curated high-skill manager/league observations. Useful as an expert-market lens, but still subject to format comparability.

3. **Broad external Waiver Market / FAAB Market Ledger**  
   Larger external sample from eligible leagues/authorized data sources.

4. **Sleeper platform trending**  
   Real-time attention/acquisition-pressure evidence; not an observed clearing-price dataset.

Do not silently pool these into one sample or one provenance class.

---

## 6. Sharp-league data

Sharp-league waiver bids are useful when:

- the source league is known and legitimately accessible;
- the transaction includes a completed winning bid;
- the season's original starting FAAB budget is known;
- player identity resolves canonically;
- the league format/settings are known well enough to assess comparability.

Sharp status may make the cohort especially valuable for understanding how strong managers react to opportunities, but **Sharp does not erase format differences**.

A 12-team dynasty Superflex/TEP/IDP deep-roster league is more comparable to Brisket than a shallow redraft 1QB league even if both contain strong managers.

Store at least:

- source league ID/key;
- season;
- week/timestamp;
- player ID;
- raw winning bid;
- original starting budget;
- normalized bid percentage;
- $100-equivalent display value;
- team count;
- dynasty/redraft status where known;
- SF/1QB;
- TE/TEP settings where known;
- IDP status where known;
- roster depth / waiver rules where available;
- Sharp cohort / source classification;
- provenance and freshness.

---

## 7. Format comparability

Budget normalization solves the **currency scale** problem. It does not make every league economically identical.

External market evidence should be filtered or weighted using relevant context such as:

- dynasty vs redraft;
- Superflex vs 1QB;
- TE premium / two-TE demand;
- IDP vs offense-only;
- number of teams;
- roster and starting-lineup depth;
- waiver processing rules;
- free-agent pool depth;
- season phase/week;
- available roster spots / transaction environment where measurable.

Unknown settings reduce confidence. Materially incompatible leagues can be excluded from the closest-comps layer while remaining available as broad-market context.

Do not invent precise format weights without validation.

---

## 8. FAAB evidence hierarchy

For predicting the actual clearing price in this league, use the conceptual priority:

1. **This league's own normalized historical behavior**
2. **Comparable Sharp-league normalized winning bids**
3. **Comparable broad-market normalized winning bids**
4. **Existing crowd-market observations**
5. **Sleeper Market Heat / add acceleration**
6. **Sleeper drop activity as weaker context**

This is not permission to add six independent numbers together. Inputs with overlapping lineage or the same underlying event must be deduped/correlation-aware.

The objective ceiling remains outside this hierarchy and continues to bound rational spending.

---

## 9. Relationship to CE-19 and Perfect Waivers

This work extends **CE-19 Waiver Market / FAAB Market Ledger** rather than creating another market database.

CE-19 should become the canonical external waiver-market observation layer that can serve:

- FAAB recommended-bid clearing-price estimates;
- waiver-market history/player context;
- Perfect Waivers;
- future research/backtesting;
- user-facing Market Heat / market-context displays where appropriate.

Perfect Waivers may use Market Heat to understand urgency/availability risk, but popularity must not substitute for the optimizer's canonical player/roster value logic.

---

## 10. Double-counting protections

A single news event can generate several descendants:

`starter injury -> Sleeper add spike -> many waiver bids -> analyst/news discussion`

Those are not automatically four independent reasons to raise a recommendation.

Before combining market evidence, preserve lineage and ask what each observation adds:

- Sleeper add velocity: current attention / likelihood competitors noticed.
- Completed external bids: observed willingness to pay.
- Own-league history: local manager bidding culture.
- Sharp cohort: behavior of curated high-skill managers.

When two inputs are substantially the same population or event descendant, prevent duplicate amplification.

---

## 11. Validation requirements

Before promoting any new market weighting:

1. Reconcile historical Brisket seasons across $1,000 / $200 / $100 budgets and prove percentage invariance.
2. Unit-test external normalization across multiple starting budgets.
3. Prove missing starting budgets fail closed rather than defaulting silently.
4. Keep $0 bids in historical distributions.
5. Backtest recommendations against actual Brisket winning/clearing bids.
6. Compare models with and without Sharp-league evidence.
7. Compare models with and without Sleeper Market Heat.
8. Test that Sleeper trends never modify objective ceiling/canonical value.
9. Test format mismatch and low-sample confidence behavior.
10. Test source/cohort deduplication and overlap with broad-market observations.
11. Prefer calibration improvement, error reduction and decision usefulness over hand-picked examples that merely look better.

---

## 12. Implementation sequencing

Pick this up at the natural **FAAB / Waiver Market / CE-19 / Perfect Waivers** checkpoint.

First audit what the current FAAB engine already does with Sleeper trending and existing crowd data. Preserve correct behavior. Then extend the canonical market ledger and market layer rather than adding page-local multipliers or a second recommender.

**Method status:**

- percent-of-original-budget normalization: **FINAL / OWNER-DECIDED and already implemented for own-league history**;
- objective ceiling vs recommended-bid separation: **FINAL / OWNER-DECIDED**;
- Sleeper trending as bounded market-demand evidence only: **FINAL PRODUCT PLACEMENT; exact production transform requires validation**;
- Sharp/external FAAB ingestion: **APPROVED PRODUCT EXTENSION; comparability weights require empirical validation**;
- CE-19 as canonical external waiver-market owner: **APPROVED**.
