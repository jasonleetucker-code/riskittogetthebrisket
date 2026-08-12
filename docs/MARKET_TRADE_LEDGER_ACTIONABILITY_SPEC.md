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

## 19. Approved multi-source acquisition strategy and cross-source deduplication

The owner explicitly approves pursuing more than one acquisition path instead of waiting for a hypothetical global Sleeper firehose.

### 19.1 Source lane A — known Sleeper-league discovery

Brisket may expand the market sample using the same general discovery pattern already used for the Sharp transaction system: begin with known Sleeper users/accounts for which public identity/league discovery is technically and permissibly available, enumerate the public dynasty leagues that can be proven to belong to those accounts, and ingest completed transactions from those known leagues through Sleeper's league-specific APIs.

This can begin with the existing Sharp population and other already-known/approved Sleeper league IDs, but the resulting transactions belong to the **broad Market Trade Ledger** only if the sampling design says they are broad-market evidence. Sharp-derived transactions must retain provenance identifying the Sharp discovery path so they are not silently counted once as Sharp evidence and again as an independent broad-market vote.

Every discovered league must have its own league/format metadata captured from the host wherever possible. Do not infer SF, TEP, team count, starter depth or scoring from the identity of the user who led us to the league.

### 19.2 Source lane B — KeepTradeCut recent-trade database

Brisket should also investigate ingesting the public KeepTradeCut Trade Database because it exposes a much broader recent-trade population together with useful format dimensions such as QB setting, PPR, team count, TE premium, starter count and package size.

Implementation remains source/permission gated. Before automated acquisition, audit the current Terms/robots/access pattern, rate limits and whether an authorized API, export, partnership or licensing path exists. Do not bypass access controls. If automated collection from the public UI is permitted, keep the collector polite, cached and rate-limited; if it is not permitted, pursue an authorized alternative rather than evasion.

KTC-sourced observations must be labeled as KTC provenance. Do not assume that every KTC trade originated on Sleeper unless the source itself proves the platform.

### 19.3 Source lane C — future authorized sources

The same ledger must support additional authorized sources later, including opted-in Brisket leagues, partner data, other host APIs or licensed datasets, without changing downstream consumer contracts.

### 19.4 One raw archive, one canonical analytical ledger

Preserve every source-native observation append-only in the raw acquisition archive with its own source ID, timestamp, source payload hash and provenance. Then map those observations into canonical **underlying-trade groups** for analytics.

The raw archive may contain two or more observations of the same real-world trade. The analytical ledger must not treat those observations as independent transactions.

### 19.5 Deduplication identity hierarchy

Deduplication must use the strongest available evidence, in descending order:

1. **CONFIRMED SAME HOST TRANSACTION** — same host/platform + league ID + source-native transaction ID. Collapse to one underlying trade.
2. **CONFIRMED CROSS-SOURCE MATCH** — one source exposes enough identifiers to prove that another source row represents that exact host transaction. Collapse to one underlying trade while preserving both provenance records.
3. **HIGH-CONFIDENCE CANDIDATE MATCH** — same normalized asset multisets on each side, same transaction date/time within a defensible tolerance, same team count and materially matching format metadata, plus any additional source evidence. Mark as a candidate duplicate, not automatically proven.
4. **AMBIGUOUS SIMILAR TRADE** — same package/date or similar metadata but no league/transaction identity. Do **not** automatically collapse it; the exact same package can legitimately occur in two different leagues.
5. **DISTINCT** — sufficient evidence shows separate underlying transactions.

Side orientation must be canonicalized before comparison so A-for-B and B-for-A representations match. Player aliases and draft-pick representations must be resolved through canonical identity before fingerprinting.

### 19.6 Never solve double counting by creating false undercounting

A naïve hash such as `date + Player A + Player B` is prohibited as a final dedupe key because identical trades can occur independently in many leagues on the same day.

If cross-source identity is unresolved, preserve an explicit dedupe state such as:

- `CONFIRMED_UNIQUE`
- `CONFIRMED_DUPLICATE`
- `PROBABLE_DUPLICATE`
- `POSSIBLE_OVERLAP`
- `UNRESOLVED`

For model/trend calculations that are sensitive to volume, either exclude unresolved overlap from claims that require unique-trade counts, use conservative bounds/sensitivity analysis, or apply an evidence-validated overlap model. Never silently count an uncertain duplicate twice and never silently delete it as though uniqueness were proven.

UI sample counts should distinguish raw observations from estimated/confirmed unique underlying trades when those numbers differ materially.

### 19.7 Sharp overlap and source independence

If a trade is discovered through a Sharp manager's Sleeper league and also appears in KTC or another broad source, it remains **one underlying trade**. Its provenance can say both `SHARP_DISCOVERY` and `KTC_MARKET`, but its transaction volume contribution is one.

Likewise, a trade involving a Sharp manager may legitimately inform both:

- broad-market transaction behavior; and
- the separate Sharp-behavior feature.

But downstream consensus must know those are two analyses of the same event, not two independent observations. Signal-lineage rules apply.

### 19.8 Coverage reporting

Market Trade Ledger outputs should eventually expose source coverage such as:

- confirmed unique trades;
- raw source observations;
- source mix;
- exact-format count;
- probable-overlap count;
- unresolved-overlap count;
- date coverage;
- known sampling biases.

A large KTC sample and a smaller Sharp-seeded Sleeper sample should not be presented as a statistically representative sample of all dynasty leagues without evidence that the sampling process supports that claim.

### 19.9 Owner-approved acquisition priority

Preferred practical sequence:

1. preserve/build the canonical ledger + dedupe schema first;
2. ingest already-known Sleeper leagues, including the existing Sharp-discovery graph, where permitted;
3. investigate and, if permitted/authorized, add KTC Trade Database acquisition;
4. run cross-source overlap/dedupe validation before combining source-level volume metrics;
5. add future authorized sources without changing the canonical ledger contract;
6. only then promote market-derived models after out-of-sample validation and source-lineage review.

Using both Sleeper-derived and KTC-derived data is preferred when technically and permissibly available because the sources can improve coverage and cross-check each other, **provided the same underlying trade never becomes two independent market observations.**
