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

For external league-level FAAB evidence, **dynasty is a hard eligibility requirement**. The model must not ingest redraft or other non-dynasty league transaction histories as clearing-price comps.

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

### Important population distinction

Sleeper platform-wide trending is not a league-level FAAB transaction sample. It may contain activity from formats unlike ours, including redraft. Therefore it must remain a **separate weak/bounded attention signal** and must never be mixed into the dynasty-only external clearing-price ledger as though it were comparable FAAB history.

The owner's **dynasty-only rule applies to external league-level FAAB/waiver transaction data**. We are not authorized to ingest non-dynasty league histories merely to enlarge the sample.

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

## 5. External-league FAAB evidence — dynasty-only hard gate

Where Sleeper transaction access and league metadata provide a completed waiver/free-agent bid and a trustworthy original FAAB budget, the site may ingest outside-league observations **only when the source league is verified dynasty**.

This includes eligible leagues already used by the site's Sharp systems.

### Hard eligibility rule

The external FAAB ledger must reject:

- redraft leagues;
- keeper leagues that materially reset rather than operate as dynasty;
- guillotine or other fundamentally different seasonal formats;
- any league whose dynasty status cannot be established confidently.

Unknown dynasty status is **not** permission to assume dynasty. Fail closed for the comparable FAAB dataset.

### Keep four evidence populations distinct

1. **Own-league FAAB history**  
   Highest relevance for forecasting how this exact league clears waivers.

2. **Sharp-league FAAB behavior**  
   Curated high-skill **dynasty** manager/league observations. Useful as an expert-market lens, but still subject to format comparability.

3. **Broad external Dynasty Waiver Market / FAAB Market Ledger**  
   Larger external sample from eligible dynasty leagues / authorized data sources.

4. **Sleeper platform trending**  
   Real-time attention/acquisition-pressure evidence; not an observed clearing-price dataset.

Do not silently pool these into one sample or one provenance class.

---

## 6. Sharp-league data

Sharp-league waiver bids are useful when:

- the source league is **verified dynasty**;
- the source league is known and legitimately accessible;
- the transaction includes a completed winning bid;
- the season's original starting FAAB budget is known;
- player identity resolves canonically;
- the league format/settings are known well enough to assess comparability.

Sharp status may make the cohort especially valuable for understanding how strong managers react to opportunities, but **Sharp does not erase format differences**.

For the Brisket league, a 12-team dynasty Superflex/TEP/two-TE/IDP deep-roster league is far more comparable than a dynasty 1QB, non-TEP, offense-only shallow league, even if both contain strong managers.

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
- **verified dynasty status / verification provenance**;
- SF/1QB;
- TE starter count / TEP settings where known;
- IDP status and defensive starter depth where known;
- total roster depth / starting-lineup depth;
- waiver/FAAB rules where available;
- Sharp cohort / source classification;
- provenance and freshness.

---

## 7. Target-league format comparability

Budget normalization solves the **currency scale** problem. It does not make every dynasty league economically identical.

The comparison system should derive a **target-league similarity profile** from canonical league settings and use that to rank/filter external dynasty observations. This avoids hard-coding one universal weighting scheme while still optimizing properly for Brisket.

### Brisket priority profile

For our league, give highest priority to dynasty leagues that resemble Brisket across the settings most likely to change waiver demand and budget allocation:

1. **Superflex / 2QB structure**
2. **TE premium and two mandatory TE starters / comparable TE demand**
3. **IDP with comparable defensive roster/start requirements**
4. **12 teams or similar team count**
5. **Deep rosters and similar starting-lineup/bench depth**
6. **Comparable waiver/FAAB processing rules**
7. **Comparable season week / phase**
8. **Comparable scoring-driven positional scarcity where measurable**

The closest-comps layer should therefore favor leagues matching **SF + TEP/two-TE + IDP** before less similar dynasty formats.

### Position-specific comparability

Format differences matter differently by player position. Use stricter matching when the setting directly drives positional demand:

- **QB:** Superflex/2QB dynasty evidence is primary. 1QB dynasty observations are materially less comparable and should be strongly downweighted or excluded from closest-comps calculations.
- **TE:** TEP and especially two-TE dynasty observations are primary for TE claims. Non-TEP/single-TE dynasty data may remain broad context but should not lead the estimate.
- **IDP (DL/EDGE/LB/DB):** external clearing-price evidence must come from dynasty leagues that actually use IDP. Offense-only leagues are invalid player-level FAAB comps for IDP assets.
- **RB/WR:** overall format similarity still matters because SF, TEP, IDP, roster depth and team count alter how a finite FAAB budget is allocated. Individual mismatches can be weighted rather than automatically excluded if the data remains useful.

### Similarity tiers

A useful implementation may expose internal tiers such as:

- **Tier A — Closest comps:** dynasty + strong SF/TEP/two-TE/IDP/depth/team-count/waiver similarity.
- **Tier B — Comparable dynasty:** dynasty and most key structural settings match, with limited mismatches.
- **Tier C — Broad dynasty context:** dynasty but meaningful format differences reduce transferability.
- **Excluded:** non-dynasty, unknown dynasty status, missing required budget provenance, or player-position incompatibility such as offense-only league data for an IDP claim.

Do not invent final numeric weights merely from these labels. Validate them empirically against Brisket historical clearing prices.

### Future target leagues

If the product later analyzes another user's dynasty league with different settings, comparator relevance should be derived from **that target league's canonical settings**, not Brisket's hard-coded configuration.

The hard external eligibility gate remains **dynasty-only** unless a later explicit owner decision changes it.

---

## 8. FAAB evidence hierarchy

For predicting the actual clearing price in Brisket, use the conceptual priority:

1. **This league's own normalized historical behavior**
2. **Closest-format dynasty Sharp-league normalized winning bids**
3. **Closest-format broad dynasty normalized winning bids**
4. **Less-similar dynasty market observations with reduced confidence/weight**
5. **Existing crowd-market observations where methodologically compatible**
6. **Sleeper Market Heat / add acceleration**
7. **Sleeper drop activity as weaker context**

This is not permission to add seven independent numbers together. Inputs with overlapping lineage or the same underlying event must be deduped/correlation-aware.

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

The league-level CE-19 external FAAB dataset is **dynasty-only**. Preserve source settings and similarity metadata so consumers can request closest-format comps rather than a generic pooled average.

Perfect Waivers may use Market Heat to understand urgency/availability risk, but popularity must not substitute for the optimizer's canonical player/roster value logic.

---

## 10. Double-counting protections

A single news event can generate several descendants:

`starter injury -> Sleeper add spike -> many waiver bids -> analyst/news discussion`

Those are not automatically four independent reasons to raise a recommendation.

Before combining market evidence, preserve lineage and ask what each observation adds:

- Sleeper add velocity: current attention / likelihood competitors noticed.
- Completed external dynasty bids: observed willingness to pay.
- Own-league history: local manager bidding culture.
- Sharp dynasty cohort: behavior of curated high-skill managers.

When two inputs are substantially the same population or event descendant, prevent duplicate amplification.

---

## 11. Validation requirements

Before promoting any new market weighting:

1. Reconcile historical Brisket seasons across $1,000 / $200 / $100 budgets and prove percentage invariance.
2. Unit-test external normalization across multiple starting budgets.
3. Prove missing starting budgets fail closed rather than defaulting silently.
4. Keep $0 bids in historical distributions.
5. Prove **no non-dynasty or unknown-dynasty league transaction history enters the external FAAB dataset**.
6. Prove Brisket closest-comps ranking prioritizes SF + TEP/two-TE + IDP + similar team/depth/waiver settings.
7. Test QB comparisons so SF/2QB materially outranks 1QB dynasty evidence.
8. Test TE comparisons so TEP/two-TE materially outranks non-TEP dynasty evidence.
9. Test IDP comparisons so offense-only leagues cannot supply IDP player clearing-price comps.
10. Backtest recommendations against actual Brisket winning/clearing bids.
11. Compare models with and without Sharp-league evidence.
12. Compare models with and without Sleeper Market Heat.
13. Test that Sleeper trends never modify objective ceiling/canonical value.
14. Test format mismatch and low-sample confidence behavior.
15. Test source/cohort deduplication and overlap with broad-market observations.
16. Prefer calibration improvement, error reduction and decision usefulness over hand-picked examples that merely look better.

---

## 12. Implementation sequencing

Pick this up at the natural **FAAB / Waiver Market / CE-19 / Perfect Waivers** checkpoint.

First audit what the current FAAB engine already does with Sleeper trending and existing crowd data. Preserve correct behavior. Then extend the canonical dynasty-only market ledger and market layer rather than adding page-local multipliers or a second recommender.

**Method status:**

- percent-of-original-budget normalization: **FINAL / OWNER-DECIDED and already implemented for own-league history**;
- objective ceiling vs recommended-bid separation: **FINAL / OWNER-DECIDED**;
- external league-level FAAB source eligibility = **DYNASTY ONLY / FINAL OWNER DECISION**;
- Brisket external-comps priority = **favor SF + TEP/two-TE + IDP + similar league depth/settings / FINAL PRODUCT DIRECTION; exact weights evidence-gated**;
- position-specific QB/TE/IDP comparability rules: **APPROVED / REQUIRED**;
- Sleeper trending as bounded market-demand evidence only: **FINAL PRODUCT PLACEMENT; exact production transform requires validation**;
- Sharp/external FAAB ingestion: **APPROVED PRODUCT EXTENSION; comparability weights require empirical validation**;
- CE-19 as canonical external waiver-market owner: **APPROVED**.
