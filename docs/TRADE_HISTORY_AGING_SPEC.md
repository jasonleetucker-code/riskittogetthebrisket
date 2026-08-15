# Trade History — Current Grade, At-the-Time Grade & Aging Methodology

> **RECONCILIATION AMENDMENT — 2026-08-14.** Promoted to `main` verbatim from its planning branch by the
> post-B master reconciliation (`docs/POST_B_RECONCILIATION_2026-08-14.md`). No content was changed.
> Its C-Series phase placement and completion evidence live in
> `docs/C_SERIES_SCOPE_MANIFEST.md`.


**Status:** CANONICAL DETAILED PRODUCT/METHODOLOGY SPEC SUPPLEMENT  
**Owner direction captured:** 2026-08-12  
**Canonical family:** Trade History / Acquisition History / Historical Value Snapshots  
**Public/private posture:** Public-safe retrospective presentation may exist; proprietary current decision-intelligence internals remain private according to the Master Product Plan.

> This specification refines the existing Trade History and Acquisition History requirements. It does not create a second valuation or trade-grading engine. The Trade History page must consume the same canonical value, pick identity, historical snapshot, package/trade methodology, and provenance owners used elsewhere.

---

## 1. Owner intent

Trade History should answer three different questions without conflating them:

1. **CURRENT GRADE — “How does this trade look today?”**
2. **AT-THE-TIME GRADE — “How did this trade look when it was actually made?”**
3. **HOW IT AGED — “How much better or worse has the trade become since it was made?”**

The current grade should continue to use the site's **current canonical asset values and current canonical trade-grading methodology**. Historical aging must not replace that current view.

The existing `Aged well` / `Aged poorly` concept is directionally correct, but its current implementation has known shortcuts that are not acceptable as the finished methodology:

- a trade that predates history can use the earliest later snapshot as a proxy;
- a player with no history can silently fall back to the player's current value;
- picks currently use current value because per-pick historical values are not available in the helper;
- the aging path can compare `side.netValue` while the displayed current result may prefer a different/adjusted trade-equity quantity;
- the fixed ±200 value-point threshold does not scale with trade size.

These behaviors must be repaired when this backlog item becomes active.

---

## 2. Canonical concepts

### 2.1 Current Grade

**Question:** If this exact historical trade were evaluated today, what would the site say?

Requirements:

- use today's canonical player values;
- use today's canonical pick values / resolved-pick treatment according to stable pick identity and asset-lineage rules;
- use the site's one canonical trade-equity/package methodology;
- support 2-team and 3+ team trades consistently;
- preserve current league/scoring context where relevant to the canonical trade grade;
- expose current value/edge separately from historical aging.

Do not freeze the trade's headline grade at the value it had when the trade was made. The owner explicitly wants Trade History's ordinary trade grade to reflect **current values**.

### 2.2 At-the-Time Grade

**Question:** Using information that existed at or before the transaction timestamp, how did the trade look then?

Requirements:

- use the closest valid canonical historical value snapshot **at or before** the actual trade timestamp for each asset;
- never use a future snapshot as though it were contemporaneous;
- include both players and draft picks;
- use stable player/pick identity rather than display-name matching as the final architecture;
- use the same canonical trade-equity/package methodology used for the Current Grade when measuring aging, so methodology changes do not masquerade as asset aging;
- preserve exact timestamp, snapshot/model version, scoring/config fingerprint where relevant, and provenance.

### 2.3 How It Aged

**Question:** How has the economics of the trade changed since it was made?

Conceptually:

`Aging Change = Current Canonical Trade Edge - At-the-Time Canonical Trade Edge`

The exact production edge representation may be a normalized percentage, package-equity measure, or another owner-approved canonical trade metric. The critical requirement is **methodological symmetry**: the historical and current sides must use the same canonical grading methodology, changing the asset values/time state rather than changing the formula.

Interpretation:

- a trade can be a current loss but still have **aged well** if it is materially less bad than it appeared at the time;
- a trade can be a current win but have **aged poorly** if its advantage has materially eroded;
- `Current winner/loser` and `Aged well/poorly` are intentionally different concepts.

---

## 3. Do not let model-version changes masquerade as aging

A trade's aging measure is intended to describe **what happened to the assets**, not merely that the site's formulas changed.

Therefore the canonical aging comparison should normally replay the same currently approved trade-grading methodology over:

- historical asset values at the trade timestamp; and
- current asset values today.

If the system actually recorded the trade grade produced by the site at the moment the transaction occurred, preserve that separately as something like:

**Original Site Grade — model/version X, as-of timestamp Y**

That is valuable historical provenance, but it is a different concept from canonical asset aging.

Never overwrite the recorded original grade when methodology later changes.

---

## 4. Historical provenance — no silent substitution

Every asset used in an at-the-time grade must carry a historical-value provenance state compatible with the project's canonical history semantics:

- **RECORDED** — explicitly stored contemporaneously by the system;
- **HISTORICAL SNAPSHOT** — canonical archived value known to be valid at/before the trade timestamp;
- **RECONSTRUCTED** — defensibly rebuilt from contemporaneous evidence while preserving methodology/source/version;
- **UNAVAILABLE** — no defensible historical value exists.

The following are forbidden:

- current value substituted for missing historical value;
- earliest future snapshot substituted for a trade that predates coverage while still presented as an exact at-trade value;
- today's pick value presented as historical pick value;
- a future model/snapshot backfilled into the past without an explicit reconstructed label;
- unresolved identity silently guessed.

**Missing historical value is unavailable, not zero and not current value.**

---

## 5. Coverage gate for Aged Well / Aged Poorly

Do not emit a confident `Aged well`, `Aged poorly`, or numerical aging delta unless historical coverage is sufficient for the trade.

The implementation must define a defensible trade-level coverage rule considering:

- number of assets with valid historical values;
- percentage of historical package value covered;
- whether a missing asset is material to either side;
- pick-history availability;
- identity confidence;
- timestamp precision;
- reconstruction status.

Possible presentation states should include concepts such as:

- **Exact / high-confidence historical comparison**;
- **Reconstructed / estimated historical comparison**;
- **Partial coverage — aging unavailable**;
- **Historical comparison unavailable**.

Do not turn low coverage into a normal-looking precise grade.

---

## 6. Historical player values

For players:

- prefer the canonical historical value stamped by the backend/model at or before the transaction time;
- do not re-derive an old value using today's Hill curve or today's model unless the result is explicitly classified as reconstruction and that reconstruction method is approved;
- preserve model version and source/input provenance where available;
- eventually use stable canonical player ID rather than display-name lookup.

Historical rank without a historical value may be useful evidence, but it must not automatically be converted with today's formula and labeled contemporaneous truth.

---

## 7. Historical draft-pick values

Draft picks require first-class historical valuation support; `current pick value` is not an acceptable finished substitute for `pick value when traded`.

For every historical pick, preserve stable identity:

- season;
- round;
- original owner;
- current owner at each historical point where reconstructable;
- stable canonical pick ID;
- generic market value at the timestamp;
- specific expected-pick value/distribution only where that forecast genuinely existed at the timestamp;
- provenance/model version.

Do not use a later-known final draft slot to make an earlier trade appear more predictable than it really was.

### Resolved picks

Once a pick is exercised, the system may show its direct drafted-player descendant when canonical asset lineage proves the relationship, but must distinguish:

- the **original pick asset**;
- the **player selected with that pick**;
- any later trades involving that pick or player.

Do not silently replace an old pick with a player based on fuzzy inference. Trade Trees / Asset Lineage should own downstream lineage beyond the direct historical asset identity.

---

## 8. Package methodology consistency

Current Grade and At-the-Time Grade must consume **one canonical trade grading/package owner**.

If package/consolidation economics are part of the canonical trade grade, apply them symmetrically to both timestamps.

Do not compare:

- raw historical net vs package-adjusted current net;
- one historical formula vs another current formula;
- KTC advisory Value Adjustment on one side of the comparison but not the other;
- different league/scoring contexts without explicitly stating why.

KTC Value Adjustment remains an advisory parity lens unless a later owner-approved canonical methodology says otherwise. Historical Trade Aging must not silently promote it into the site's canonical trade conclusion.

---

## 9. Replace the fixed ±200 aging threshold

The current fixed threshold of roughly ±200 canonical value points is not approved as the final classification rule because significance depends on trade size and the underlying canonical trade metric.

Before finalizing labels such as:

- Aged very well;
- Aged well;
- Stable;
- Aged poorly;
- Aged very poorly;

calibrate thresholds against a normalized trade-edge measure and historical distribution of real trades.

At minimum:

- account for package/trade size;
- avoid tiny absolute movements triggering strong labels on blockbuster trades;
- avoid meaningful percentage swings being ignored on smaller trades;
- preserve a neutral/stable band;
- test sensitivity on historical league trades;
- do not choose thresholds merely because the labels look balanced.

**Method status:** label thresholds require historical validation before final production activation.

---

## 10. User-facing presentation

A historical trade should eventually be able to show, with progressive disclosure:

**Today**
- current values by asset/side;
- current canonical trade grade/edge.

**When traded**
- historical values by asset/side where supported;
- at-the-time canonical grade/edge;
- historical provenance/coverage.

**How it aged**
- normalized change in trade edge;
- `Aged well / Stable / Aged poorly` style label only when coverage and calibrated thresholds support it;
- concise explanation of the largest asset-value changes driving the movement.

Optional historical provenance may also show the recorded **Original Site Grade** if one exists.

Do not overwhelm the default trade card. Use progressive disclosure for asset-level history and provenance.

---

## 11. Relationship to Acquisition History and Trade Trees

This feature must reuse rather than duplicate:

- canonical historical value snapshots;
- Acquisition History / holding periods;
- stable pick identity;
- canonical asset lineage / Trade Trees;
- canonical trade grading/package methodology;
- canonical player identity;
- canonical league/scoring context;
- provenance/confidence infrastructure.

Acquisition History answers what a manager paid and the return on a holding period. Trade History Aging answers how the economics of a completed trade changed from transaction time to now. Trade Trees answer what assets subsequently became. They are related but not interchangeable.

---

## 12. Validation requirements

When this item becomes active, do not simply alter the labels in `trade-retro-value.js`.

Required workflow:

1. reproduce and RED-test the current future-snapshot fallback for pre-coverage trades;
2. RED-test current-value fallback when historical player value is missing;
3. RED-test current-value substitution for historical picks;
4. RED-test mismatch between the current displayed trade-equity methodology and the quantity passed to the aging calculation;
5. create fixtures for exact historical coverage, reconstructed history, partial history, and unavailable history;
6. include player-only, pick-only, mixed player/pick, 2-team and 3+ team trades;
7. validate stable player/pick identity across historical snapshots;
8. replay a representative historical league-trade sample and inspect classification sensitivity;
9. prove missing/future data fails closed rather than silently producing a precise grade;
10. measure any performance/network effect of historical lookups;
11. run applicable frontend/backend/livedata gates and exact-head CI;
12. stop for owner review before changing any major canonical trade-grading policy.

---

## 13. Implementation timing

This is **approved required future work**, but it does not preempt the active B6/B7 foundation sequence.

Natural dependency window:

- canonical historical value snapshots;
- Acquisition History;
- stable pick identity;
- canonical trade/package methodology;
- Trade Trees / Asset Lineage where resolved picks need lineage.

The current UI may remain as an interim best-effort surface, but it must not be treated as final historical methodology.

---

## 14. Method status

**Current Grade uses current values:** OWNER-DECIDED / REQUIRED.  
**At-the-Time Grade based on contemporaneous historical values:** OWNER-DECIDED / REQUIRED.  
**No current/future fallback masquerading as historical truth:** OWNER-DECIDED / REQUIRED.  
**Player + pick historical provenance:** OWNER-DECIDED / REQUIRED.  
**Same-methodology current-vs-historical aging comparison:** OWNER-DECIDED / REQUIRED.  
**Exact aging-label thresholds:** INVESTIGATION REQUIRED / HISTORICAL VALIDATION.  
**Production repair:** FUTURE DEPENDENCY-GATED; MUST BE COMPLETED BEFORE FINAL MASTER AUDIT CAN CLOSE THIS FEATURE AS CORRECT.
