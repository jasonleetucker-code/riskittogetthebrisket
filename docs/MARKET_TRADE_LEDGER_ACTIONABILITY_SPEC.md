# Market Trade Ledger — Format-Aware Recent Trades & Actionable Market Evidence

**Status:** CANONICAL DETAILED PRODUCT/METHODOLOGY SPEC SUPPLEMENT  
**Owner direction captured:** 2026-08-12  
**Canonical family:** CE-01 Market Trade Ledger / Trade Database / Trade Intelligence  
**Execution posture:** APPROVED FUTURE PRODUCT REQUIREMENT; DATA ACQUISITION + MODEL ACTIVATION REMAIN SOURCE/LEGAL/EVIDENCE GATED  
**Public/private posture:** recent anonymized market trades may be public-safe where source rights permit; personalized actionability is private.

## 1. Owner intent

Build a recent real-dynasty-trades system analogous in usefulness to current trade databases, but make it league-format aware and deeply integrated with Brisket's decision systems.

For a connected league, users should be able to see recent trades from meaningfully comparable dynasty formats rather than an undifferentiated pool. The system should eventually use those trades as evidence for market comps, liquidity, package construction, negotiation and potentially an independent market-implied valuation challenger.

Raw real trades must **not** directly overwrite canonical dynasty values merely because they occurred.

## 2. Existing product precedent / external capability

Current public trade-database products demonstrate that real dynasty trades can be filtered by important format dimensions such as QB format, PPR, team count, TE premium, starter count and package size, and can expose recent/30-day trade activity.

Brisket should adopt the concept, not another site's architecture, branding or proprietary data access.

The ingestion layer must use sources we are permitted and technically able to access. Do not assume Sleeper provides a global transaction firehose. A source-specific discovery/licensing/access audit is required before implementation.

## 3. Canonical Market Trade Ledger

Each completed market trade should be normalized into one append-only ledger with at least:

- transaction ID / source-native ID where available;
- source family;
- timestamp;
- league/format fingerprint or structured format metadata;
- dynasty verification state;
- team count;
- QB format (1QB/SF/2QB etc.);
- PPR/scoring basis;
- TE premium / TE starter-demand representation;
- starter count / lineup depth;
- IDP state and scoring/position structure when applicable;
- best-ball/managed setting where relevant;
- assets sent to each side with stable player/pick identity;
- number of teams in the transaction;
- package size;
- historical canonical values at the transaction timestamp where available;
- source provenance, freshness and coverage;
- deduplication key so the same Sleeper trade ingested through multiple sources is not counted twice.

The broad Market Trade Ledger remains separate from the curated Sharp Ledger and from the user's own Insider/league transaction history.

## 4. Format matching hierarchy

Do not use a binary "same league / not same league" filter only. Exact matches may be too sparse, while unrestricted matching can be misleading.

Every comp should carry a format-match state such as:

1. **EXACT / NATIVE COMPARABLE** — same material format dimensions for the target question.
2. **NEAR COMPARABLE** — small, explicitly quantified format differences unlikely to dominate the asset relationship.
3. **NORMALIZED COMPARABLE** — converted through validated league-format normalization with lower confidence.
4. **BROAD MARKET CONTEXT** — useful as context but not represented as same-format evidence.
5. **UNSUPPORTED / UNVERIFIED** — exclude from actionable calculations.

Important dimensions include Superflex/1QB, TE premium and TE starter demand, team count, starter depth, PPR/scoring environment and IDP structure.

Do not call a trade "from a league just like yours" unless the material similarity is actually demonstrated.

## 5. Recency

Recent transactions should dominate tactical market evidence, but do not hard-code 30 days as final methodology merely because it is intuitive.

Support windows such as 7/14/30/60/90 days and/or continuous recency weighting. The primary display may use a practical recent window such as 30 days after validation, while the model can expand backward when sample size is insufficient.

Trade evidence should preserve:

- age in days;
- sample size;
- market regime/date range;
- source coverage;
- recency weight where modeled.

A trade from yesterday and a trade from nine months ago should not silently count equally for today's clearing price.

## 6. Recent Trades UI

A player and general Trade Database surface should support:

- recent comparable trades;
- exact-format toggle/filter;
- date window;
- Superflex/1QB;
- TEP level / TE demand;
- team count;
- starter depth;
- IDP format where applicable;
- number of assets;
- player/pick search;
- value-at-time and current-value context when our historical snapshots exist;
- format-match badge and confidence;
- source/provenance.

A selected connected league should preconfigure the filter from its canonical settings, with user-visible overrides available for research.

## 7. Actionable use #1 — historical/comparable trade ranges

For a player or package, show what the real market has recently paid in comparable formats.

Useful outputs may include:

- median/trimmed range of comparable package value;
- central 50% / 80% trade range;
- most common asset archetypes received;
- examples closest to the proposed package;
- sample size and recency;
- exact vs normalized comp count.

Do not average multi-asset sides naively and call that player value. Trade packages contain consolidation economics and correlated assets.

## 8. Actionable use #2 — Trade Analyzer / Second Opinions

The canonical Analyze Trade result may use market comps as an independent evidence family:

- "8 close comps in the last 30 days";
- whether the proposed price is inside/outside recent market range;
- whether comparable managers typically paid a premium for consolidation;
- whether this exact player/pick package shape is unusual.

Market comps supplement canonical value; they do not replace it.

If our canonical value already consumes a future Real Trade Market Value signal, downstream analysis must not count raw ledger-derived comps as an independent second vote without dependency accounting.

## 9. Actionable use #3 — Trade Liquidity & Market Depth

The ledger is the primary broad-market input for the approved Liquidity/Market Depth feature.

Potential metrics:

- trades per 7/30/90 days;
- unique comparable leagues/trades;
- time since last comparable trade;
- dispersion in clearing prices/packages;
- number of distinct package archetypes;
- exact-format sample depth;
- player/pick market breadth.

Liquidity is not value. High trade frequency does not automatically mean "buy" or "sell".

## 10. Actionable use #4 — Trade Finder / Package Builder / Golden Upgrades

Real completed trades can constrain and improve package generation:

- favor package shapes the market demonstrably completes;
- identify common 2-for-1 / pick-plus-player structures;
- estimate consolidation premiums by value tier;
- avoid mathematically fair but historically implausible packages;
- surface "similar deals have actually cleared" evidence.

All package features must still use the one canonical package-generation engine.

## 11. Actionable use #5 — Negotiation Coach

Use comparable market trades to support opening offers, fair targets, concession ranges and walk-away points.

The coach can say, for example, that recent comparable SF/TEP trades cluster around a certain package range, while preserving uncertainty and explaining whether the comps are exact-format or normalized.

Market behavior is one input; counterparty-specific Manager Scout/Insider behavior remains a separate population.

## 12. Actionable use #6 — Market Pulse / Consensus Edge

The ledger may generate descriptive market signals such as:

- most traded players;
- rising/falling acquisition price;
- increasing transaction volume;
- widening/narrowing trade range;
- positional demand shifts;
- pick-year demand changes.

These signals may enter Consensus Edge only after lineage and independence are explicit. "Most traded" alone is not bullish or bearish.

## 13. Actionable use #7 — independent Real Trade Market Value

Once sample size and history are sufficient, the Market Trade Ledger may support a distinct **Real Trade Market Value** challenger.

Do NOT calculate this as a simplistic average of what came back in trades.

Candidate approaches include:

- robust latent-value / graph models;
- pairwise preference models;
- robust regression over package equations;
- Bayesian estimation;
- package-adjusted inference;
- recency weighting;
- format normalization;
- confidence intervals and minimum-sample gates.

The model must be backtested out of sample and compared with simpler baselines before any production influence.

Even if approved, Real Trade Market Value remains a named market signal. Whether/how it affects the canonical dynasty blend is a separate model-governance decision.

## 14. Avoid circularity

Required lineage examples:

- raw market trades → Real Trade Market Value;
- raw market trades → Liquidity;
- raw market trades → recent comps;
- Real Trade Market Value may later influence canonical value.

If canonical value already includes Real Trade Market Value, Analyze Trade cannot then treat canonical value + Real Trade Market Value + the same raw comps as three independent confirmations.

The same underlying transaction population affects a conclusion once unless a statistically justified decomposition exists.

## 15. Missing/sample-size behavior

- no exact-format trades ≠ zero market value;
- no recent trades ≠ illiquid with certainty;
- one trade ≠ reliable clearing price;
- unsupported format ≠ exact comp;
- missing source metadata ≠ conventional 12-team SF;
- no market evidence ≠ market disagreement.

Every derived metric needs sample count, coverage, format-match confidence, freshness and provenance.

## 16. Acquisition/data-source posture

Before implementing broad ingestion, perform a source audit:

- what public/authorized transaction data can be collected;
- exact format metadata available;
- global coverage versus known/opted-in leagues;
- rate limits;
- data rights/terms;
- stable transaction IDs for deduplication;
- whether historical transactions can be backfilled.

Do not bypass access controls or assume another site's public UI grants permission to reproduce its proprietary dataset wholesale.

If only connected/known Sleeper leagues are available initially, build the canonical ledger schema anyway so broader authorized sources can be added later without redesign.

## 17. Integration with existing roadmap

This specification deepens, rather than duplicates:

- CE-01 Market Trade Ledger / Trade Database;
- CE-14 Market Pulse;
- Trade Analyzer;
- Player Profile trade comps;
- Acquisition History;
- Trade Liquidity & Market Depth;
- Package Builder / Trade Finder / Golden Upgrades;
- Negotiation Coach;
- future Real Trade Market Value.

## 18. Method status

**Recent format-aware trade database:** OWNER-APPROVED PRODUCT DIRECTION.  
**Exact/near/normalized comp hierarchy:** OWNER-APPROVED DIRECTION; exact similarity metrics require implementation evidence.  
**30-day default window:** PLAUSIBLE UX DEFAULT / NOT FINAL METHODOLOGY until sample/recency analysis.  
**Use for comps, liquidity, package realism, negotiation and Market Pulse:** APPROVED IN PRINCIPLE.  
**Direct raw-trade modification of canonical player value:** NOT APPROVED.  
**Real Trade Market Value model:** FUTURE / EVIDENCE-GATED / OWNER PROMOTION REQUIRED.
