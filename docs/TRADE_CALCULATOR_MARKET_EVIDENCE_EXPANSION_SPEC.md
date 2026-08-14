# Chase Upside — Trade Calculator, Real-Trade Database & Market-Evidence Expansion

**Status:** BINDING OWNER PRODUCT SPEC / C-SERIES SCOPE  
**Recorded:** 2026-08-13  
**Reference origin:** publicly observable KeepTradeCut trade-calculator workflows supplied by the owner as product inspiration  
**Design rule:** adopt useful workflows; do not copy branding or blindly reproduce weak design. Chase Upside uses its own canonical values, data contracts, methodology, and Premium Sports Intelligence presentation.

This specification is a permanent addition to the Chase Upside C-series scope. It must be reconciled into the post-B dependency plan and implemented when its prerequisites are stable.

---

# 1. PRODUCT OUTCOME

The mature Chase Upside Trade Calculator should answer more than “which total is larger?” It should help a dynasty manager:

- construct a trade quickly;
- understand raw asset equity;
- understand package/consolidation effects separately;
- see which side is favored and by how much;
- identify realistic players or picks that can even the deal;
- compare the proposal against accepted real dynasty trades;
- understand package composition, concentration, historical value movement, and recent market context;
- share/reopen the exact trade;
- use the same trusted calculations on mobile and desktop.

This is one product family built on the canonical trade/value/history infrastructure. It must not create another independent value or package engine.

---

# 2. CANONICAL RULES

1. `rankDerivedValue` / the current canonical asset-value contract remains the single canonical player/pick value owner unless a later owner-approved methodology explicitly supersedes it.
2. Every valid supported draft pick through **2029** must have a finite, non-missing canonical value by C completion.
3. Value Adjustment is a **trade/package lens**, not a mutation of canonical player or pick value.
4. Raw package totals must remain visible separately from any adjustment.
5. Historical charts use canonical historical values from the history owner; they do not reconstruct old values from today's board and call them historical.
6. Real accepted trades are evidence/context. One transaction never becomes canonical valuation truth by itself.
7. League-format context must be preserved so unlike trades are not presented as directly comparable without warning.
8. All trade URLs, exports, mobile views, desktop views, API responses, and downstream simulations resolve assets through stable canonical identity.
9. Missing evidence is unavailable/uncertain, not zero.
10. No competitor-derived feature justifies duplicating an engine Chase Upside already owns canonically.

---

# 3. REQUIRED FEATURE SET

## TC-01 — Two-sided asset trade builder with package composition summaries

Provide clear Team 1 / Team 2 package builders with:

- fast player and pick search;
- add/remove controls;
- player position, positional/overall rank, age, NFL team where applicable;
- canonical value;
- exact-slot picks and generic future picks where appropriate;
- total pieces;
- package composition summaries such as `1 QB, 1 WR, 1 RB`;
- selected fantasy-team context where applicable;
- roster-aware search/prioritization without hiding other legal assets.

Asset rows must preserve stable identity; same-name ambiguity and pick identity may not be resolved by display text alone.

## TC-02 — Explicit raw total versus package / Value Adjustment

For each side show:

- **Raw Canonical Asset Total** — direct sum of canonical asset values;
- **Value Adjustment / Package Adjustment** — separate non-asset trade-evaluation term;
- **Adjusted Trade Evaluation Total** where the active methodology calls for it.

Do not silently modify an individual player's or pick's displayed canonical value to make package math work.

The UI must explain what the adjustment means and which methodology/version produced it.

## TC-03 — Trade verdict and exact amount needed to even

After evaluation, clearly state:

- which team/side is favored;
- absolute adjusted gap;
- percentage/context where useful;
- approximate canonical value required on the weaker side to reach the active fairness target.

The amount-to-even calculation must use the **post-active-Value-Adjustment gap** and must not apply Value Adjustment twice.

For nonlinear package adjustment, use an actual solve/search rather than assuming one added point of raw asset value always moves adjusted equity by one point.

## TC-04 — Players and picks to even the trade

Automatically recommend nearby-value assets that could close the gap:

- players;
- exact-slot picks;
- generic future picks when those are the valid representation;
- combinations where a single asset cannot reasonably close the gap.

Rank suggestions by closeness after recomputing the full trade, not by a naive nearest raw-value lookup when package adjustment changes the answer.

Support one-action add controls and links to Rankings / Universal Player Profile / pick context.

Where league ownership is known, prioritize executable assets from the appropriate counterparty rather than impossible global suggestions.

## TC-05 — Shareable trade URLs

Allow a constructed trade to be encoded into a stable shareable URL.

Opening the URL must reconstruct:

- participating sides/teams where safe;
- all asset identities and quantities;
- multi-team destinations if applicable;
- relevant league context when authorized;
- supported calculator options/methodology version needed for faithful reconstruction.

Do not serialize secrets, private-only data, or fragile display-name-only identifiers.

Old shared links should degrade honestly if an asset is retired or a methodology version is no longer available.

## TC-06 — One-action calculator reset

Provide a prominent Clear Calculator action that removes:

- all assets;
- manual adjustments where supported;
- stale verdicts;
- stale equalizer suggestions;
- analysis tied to the old package.

Preserve durable global/league settings that are not part of the trade itself.

## TC-07 — Recent accepted dynasty trades inside the calculator

Show recent real accepted dynasty trades as reference evidence while a user evaluates a package.

Each result should include:

- date/time window;
- both/all sides;
- players and picks;
- relevant league format tags;
- source/provenance;
- enough identity to avoid confusing similarly named assets;
- links into the full trade database where allowed.

Prioritize relevant comparisons over unrelated recent transactions.

## TC-08 — Dedicated Dynasty Trade Database

Create a searchable/browsable database of real accepted dynasty trades.

Useful filters include:

- player;
- pick / pick class / round;
- date window;
- Superflex / 1QB;
- TE premium level;
- team count;
- starter count;
- PPR/scoring context;
- IDP / roster format where available;
- source;
- package size/topology;
- approximate package/value band.

The database should support player-profile and calculator deep links and preserve transaction provenance.

## TC-09 — Comparable / reference-trade matching

Given the current package or a selected asset, surface the most relevant historical real trades using a documented similarity model that may include:

- overlapping exact assets;
- same target player/pick;
- package value proximity;
- package topology;
- recency;
- league format/scoring similarity;
- team/starter count;
- pick horizon;
- asset tier/concentration.

Do not call a trade “comparable” solely because total values are similar.

Show why each comparison matched.

## TC-10 — League-format tags on real trades

Every reference trade should visibly show material context when known, such as:

- SF / 1QB;
- TE / TE+ / TE++ / other premium basis;
- team count;
- starter count;
- PPR/scoring family;
- IDP status;
- best-ball if material;
- date/season.

Unknown format fields remain unknown. Do not fabricate defaults to make the card look complete.

## TC-11 — Total absolute value exchanged visualization

Visualize each package with stacked bars showing how much each actual asset contributes to raw canonical value.

- each asset receives a consistent visual identity within the trade;
- Value Adjustment is visually distinct from actual assets;
- totals remain numerically visible, not chart-only;
- the visualization remains understandable without color alone.

## TC-12 — Consistent asset visual identity across analytics

Within one trade analysis, the same player/pick should use a consistent visual identifier/color/marker across:

- package value bars;
- trend charts;
- dispersion;
- value-span charts;
- legends/tooltips.

This is a presentation identity only; do not persist arbitrary chart colors as asset identity in the data model.

## TC-13 — Multi-asset historical value trend comparison

Provide a historical trend chart plotting every player/pick in the trade using Chase Upside canonical history.

Initial useful period: **6 months**, with selectable windows when coverage supports them:

- 7D;
- 30D;
- 3M;
- 6M;
- 1Y;
- full available history.

Requirements:

- exact timestamps/coverage;
- no fake pre-history;
- no current-value substitution for missing past values;
- picks included where canonical history exists;
- methodology changes detectable/explainable where material;
- sensible handling for assets with different history lengths.

## TC-14 — Quick Trade Facts comparison

Add a Team 1 versus Team 2 facts table including at minimum:

- Total Raw Canonical Value;
- Total Pieces;
- Average Asset Value;
- Average Age for applicable player assets;
- Average Rank for ranked assets.

Add Chase Upside-specific facts where methodologically valid, such as:

- confidence/coverage;
- starter impact;
- positional scarcity/need;
- contender/rebuilder fit;
- liquidity;
- pick/player composition.

Do not average inapplicable/null metrics as zero.

## TC-15 — Trade value-dispersion analysis

Show how concentrated or distributed each side's value is so a manager can distinguish:

- one elite asset;
- balanced core assets;
- many mid-tier pieces;
- depth-heavy packages.

Use an explainable concentration/dispersion metric and pair it with the underlying asset values. The visualization must not imply that higher or lower dispersion is automatically better without a validated decision rule.

## TC-16 — Historical value-span analysis

For each trade asset, show over the selected period:

- historical high;
- historical low;
- current value;
- current location within that span.

This should answer whether an asset is being acquired near a recent high, low, or midpoint while making clear that historical range is context, not a forecast.

## TC-17 — Biggest 30-day riser and faller insights

Add market-insight cards for the largest meaningful 30-day riser and faller from the relevant universe.

Include:

- player;
- position;
- NFL team;
- age;
- current canonical value;
- absolute/percentage change;
- sparkline;
- link to Universal Player Profile.

Extend to selectable horizons / positions later where useful. Require sufficient history and avoid ranking assets with missing baselines as movers.

## TC-18 — Inline analytical explainers / help

Provide concise tooltips/popovers/methodology links for non-obvious concepts, including:

- canonical value;
- Value Adjustment;
- amount-to-even;
- comparable trades;
- value dispersion;
- value span;
- confidence;
- pick valuation;
- historical methodology/version caveats.

The product should be understandable without requiring the user to know internal code names.

## TC-19 — Hard canonical pick-value completeness through 2029

**Non-negotiable C completion requirement.**

Every valid draft-pick asset through the 2029 rookie class must exist and have a finite, non-missing canonical Chase Upside value.

Coverage includes every league-supported round and, where applicable:

- exact slots;
- real owned picks;
- generic future round assets before slot is known;
- hypothetical generic picks used by the calculator.

Missing must never be silently represented as zero.

Automated completeness census and cross-surface parity tests are required.

## TC-20 — Exact-slot draft-pick trade assets

When the exact slot is known, support assets such as `2026 1.03` or `2026 4.07` directly in:

- Rankings;
- search/autocomplete;
- Trade Calculator;
- equalizer suggestions;
- Trade Finder/Suggestions;
- ownership/rosters;
- history;
- APIs;
- exports;
- downstream analysis.

Do not collapse a known 1.03 back into a generic “2026 1st.”

## TC-21 — Future generic-pick representation before slot is known

Before exact draft order is known, represent future assets such as:

- `2028 Round 1`;
- `2029 Round 3`;
- early/mid/late distributions where the canonical methodology supports them.

Use a documented valuation/distribution method with uncertainty. Transition later to the exact owned-pick identity without double counting, orphaning trade history, or creating a second lineage.

## TC-22 — Cross-surface pick-value parity

The same pick asset must resolve to the same canonical value in:

- Rankings;
- Trade Calculator;
- Analyze Trade;
- Trade Finder / Suggestions / Package Builder;
- roster/ownership views;
- Draft Capital / Pick Forecast;
- history;
- APIs;
- exports;
- mobile;
- desktop.

Package adjustment may affect **trade evaluation** but must never overwrite the pick's canonical value.

## TC-23 — Mobile-first Trade Calculator parity

The complete trade workflow must be fully usable on true mobile widths, including:

- asset search/add/remove;
- team context;
- two-team and supported multi-team flow;
- package totals;
- Value Adjustment;
- verdict and amount-to-even;
- equalizer suggestions;
- recent/comparable trades;
- trend/dispersion/value-span/Quick Facts analytics;
- sharing and clear/reset.

Mobile and desktop must consume the same canonical calculations. Responsive presentation may differ; truth may not.

## TC-24 — Dismissible product announcement / CTA banner

Support lightweight dismissible announcements for meaningful product events such as:

- rookie rankings release;
- draft-prep launch;
- major Chase Upside feature release.

Requirements:

- clear CTA;
- accessible dismiss control;
- does not obscure primary trade controls;
- sensible persistence/expiry;
- mobile-safe.

## TC-25 — Market/community update embeds

Support selective embeds or summarized trusted market/community updates where they add context to market movement.

They may inform explanations/intelligence but never become canonical valuation truth by themselves.

Respect source terms, attribution, privacy, and content safety.

## TC-26 — About, FAQ, Contact, methodology, and support surfaces

Maintain lightweight support/information destinations so users can understand:

- what Chase Upside is;
- methodology at an appropriate level;
- common questions;
- contact/help paths;
- optional support/donation paths if desired.

Do not let these surfaces clutter primary analytics workflows.

## TC-27 — Footer and mobile navigation support

Provide responsive access to key informational/support destinations while preserving maximum useful space on data-heavy mobile workflows.

This belongs within the Premium Sports Intelligence navigation system, not as a copied KTC footer.

## TC-28 — Optional non-intrusive monetization slots

If advertising/sponsorship is ever enabled, placements must be explicit and non-intrusive.

Never obscure or block:

- trade controls;
- player/pick values;
- verdicts;
- charts;
- mobile navigation;
- primary actions.

Monetization is lower priority than usability, trust, performance, and privacy.

This requirement defines safe capability; it does not require ads to be enabled.

## TC-29 — KTC-reference parity audit before mature calculator completion

Before declaring the mature Chase Upside calculator complete, compare the owner-captured KTC workflows against production Chase Upside and classify each observable concept as:

- implemented;
- intentionally improved/replaced;
- intentionally rejected with owner-approved reason;
- still pending.

Do not blindly copy KTC visual design. Preserve Premium Sports Intelligence.

The audit is a **product-workflow parity** check, not permission to scrape/copy proprietary code or data outside authorized sources.

## TC-30 — Mature Trade Calculator end-state acceptance gate

The mature calculator is complete only when:

- players and every supported pick through 2029 use canonical values;
- raw totals and Value Adjustment are explicit and separate;
- favored side and amount-to-even are clear;
- equalizer suggestions include players and picks and recompute the trade correctly;
- real accepted trades and comparable trades are available with format context;
- multi-asset trends work where history exists;
- Quick Facts work;
- dispersion works;
- historical value span works;
- riser/faller context works;
- shareable URL reconstruction works;
- calculator reset works;
- two-team and supported multi-team ownership/destination rules are correct;
- mobile and desktop calculations match;
- performance meets the global standard;
- accessibility/keyboard/touch behavior is verified;
- missing/stale/error states are honest;
- automated tests protect canonical-value, pick-completeness, serialization, package-adjustment, amount-to-even, and mobile/desktop parity contracts;
- the production browser matrix is verified.

---

# 4. DEPENDENCIES

This product family should not be implemented as one giant PR. Likely dependencies include:

1. canonical player/pick identity;
2. complete canonical pick values through 2029;
3. canonical history snapshots;
4. stable trade/package/Value Adjustment owner;
5. canonical before/after roster simulation;
6. real-trade transaction ledger + format metadata;
7. comparable-trade service;
8. shared chart/data primitives;
9. Premium Sports Intelligence Trade surface migration.

The post-B C-series replan must determine the final PR order from the actual repository state.

---

# 5. PERFORMANCE REQUIREMENTS

The mature Trade Calculator is a primary interactive product and must feel immediate.

- asset search/typeahead: local/cached where possible, near-instant;
- add/remove/recalculate: immediate for already loaded inputs;
- warm useful state: generally <=1s;
- normal production p95: target <=2s where architecture permits;
- <=5s absolute useful-state failure ceiling;
- real-trade/comparable data should be indexed/materialized off-request-path;
- historical charts should read prepared history, not rebuild it on click;
- no synchronous broad source scrape or market-ledger reconstruction on user Analyze.

Preserve the current useful result while background context refreshes when safe.

---

# 6. TEST / PRODUCTION PROOF MATRIX

At minimum protect:

- canonical value unchanged by package adjustment;
- same player/pick value on mobile and desktop;
- every valid pick through 2029 finite/non-missing;
- exact-slot identity survives URL serialization/deserialization;
- generic pick quantities can repeat while real owned picks cannot be duplicated illegally;
- multi-team asset has one source owner and one destination;
- raw package sum correctness;
- KTC Value Adjustment parity for its supported contract;
- no double application of adjustment in amount-to-even/equalizers;
- equalizer candidate actually reduces the recomputed gap;
- real-trade format metadata preserved;
- comparable-trade result explains match reason;
- historical chart never substitutes current value for absent history;
- null ages/ranks omitted from averages rather than treated as zero;
- accessibility of builder controls and charts/tables;
- share URL stable round trip;
- Clear Calculator removes trade state completely;
- full mobile workflow at true phone widths;
- desktop regression matrix;
- production authenticated browser proof after deploy.

---

# 7. NON-SCOPE / SAFETY

This specification does not authorize:

- changing canonical player values to mimic KTC;
- copying KTC branding/UI pixel-for-pixel;
- using unauthorized proprietary data;
- treating one real trade as truth;
- rewriting historical values from today's board;
- adding a second player/pick identity system;
- adding a second package generator;
- hiding uncertainty or missing data;
- implementing these features before their dependencies are stable merely because the screenshots exist.
