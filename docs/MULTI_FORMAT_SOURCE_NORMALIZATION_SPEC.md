# Multi-Format Source Archive & League Format Normalization

> **RECONCILIATION AMENDMENT — 2026-08-14.** Promoted to `main` verbatim from its planning branch by the
> post-B master reconciliation (`docs/POST_B_RECONCILIATION_2026-08-14.md`). No content was changed.
> Its C-Series phase placement and completion evidence live in
> `docs/C_SERIES_SCOPE_MANIFEST.md`.


**Status:** CANONICAL DETAILED PRODUCT/METHODOLOGY SPEC  
**Owner direction captured:** 2026-08-12  
**Execution posture:** START DATA COLLECTION EARLY; DO NOT CHANGE PRODUCTION VALUES YET  
**Public/private posture:** PRIVATE MODEL/DATA INFRASTRUCTURE

## 1. Goal

Build the data foundation for the eventual product promise that a user can connect/upload an arbitrary fantasy league and the site's rankings, values, roster intelligence, trades, waivers, drafts, replacement levels, and other decision systems conform to that league's actual format rather than assuming the owner's current Superflex/TE-premium configuration.

The immediate opportunity is to collect **multiple native format variants from each ranking/value source whenever that source actually publishes them**, so future format-normalization methodology can be learned from real paired observations instead of invented later from blanket multipliers.

This specification separates two activities:

1. **EARLY DATA COLLECTION — approved to begin relatively soon.** Archive source-native alternate-format observations now so historical paired data accumulates.
2. **PRODUCTION LEAGUE NORMALIZATION — future/evidence-gated.** Do not let alternate-format feeds alter canonical production rankings until the normalization model, league-demand model, confidence rules, and validation are ready and separately approved.

### 1.1 Hard invariant — dynasty data only

**Every external ranking/value observation used by this site must be explicitly verified as DYNASTY.** This is a dynasty product. Redraft, rest-of-season, weekly, DFS, best-ball-only, keeper, seasonal, tournament, or other non-dynasty ranking/value feeds must never enter the canonical dynasty source pool merely because they come from a provider we otherwise trust.

This requirement applies to **every provider and every format variant**, including KTC, Dynasty Nerds, IDP Trade Calculator, and any future source.

A source/provider is not globally "dynasty" just because it publishes some dynasty content. If the same site exposes dynasty and redraft products, each endpoint/page/mode must carry an explicit content-type/game-type classification and provenance. The ingestion system must prove that the specific observation is dynasty before accepting it into the dynasty archive.

Required source metadata should therefore include a canonical field such as:

- `gameType = DYNASTY` for eligible observations;
- explicit non-dynasty classifications such as `REDRAFT`, `REST_OF_SEASON`, `WEEKLY`, `BEST_BALL`, etc. where encountered for diagnostics/quarantine;
- `UNKNOWN/UNVERIFIED` when the page/feed cannot be proven to be dynasty.

**Only `DYNASTY` observations are eligible for the dynasty ranking/value archive and any downstream canonical valuation use.** `UNKNOWN/UNVERIFIED` fails closed and must not be silently accepted.

Do not infer dynasty status solely from player ages, the presence of rookies/picks, a URL fragment, a familiar provider name, or ranking shape. Prefer explicit provider labeling, documented endpoint semantics, page controls, source metadata, or another reproducible proof.

The early multi-format audit must specifically inspect each source for the risk of accidentally crossing into redraft/non-dynasty modes when toggling 1QB/Superflex, TEP, IDP presets, PPR modes, or other controls.

If a provider offers both dynasty and non-dynasty versions of the same format, archive only the dynasty variant for this system. Non-dynasty data may be ignored or quarantined for diagnostics, but it must not influence dynasty values, source-consensus counts, format-response curves, calibration, confidence, or Consensus Edge.

**Missing is never zero, and unverified is never dynasty.**

## 2. Timing / sequencing decision

Historical paired format observations have option value that cannot reliably be recreated later. Sources can change rankings, methodology, controls, endpoints, or historical availability. Waiting until universal-league support is being built risks having little historical evidence for how each source responds to format changes.

Therefore the project should begin the **archive/capture portion earlier than the full universal-league feature**.

However, do **not** interrupt B6 league-config correctness or B7 realized-points correctness. B7 retains NFL Week 1 urgency. The earliest sensible implementation slot is **after B6/B7, or another explicit owner-authorized low-risk data-capture slot**.

Early collection is not authorization to serve alternate-format values, change production source weights, alter the champion model, or build universal league normalization immediately.

## 3. Source-native format capability registry

For every rankings/value source, maintain a capability registry describing the format variants that source actually exposes.

Potential dimensions, only when genuinely available, include:

- 1QB vs Superflex / 2QB;
- TE premium vs non-TE-premium;
- multiple TE-premium levels;
- start-1-TE vs start-2-TE or equivalent source-native modes;
- offense-only vs IDP-inclusive boards;
- IDP scoring presets / position groupings;
- rookie vs veteran/startup/dynasty board type;
- PPR / half-PPR / standard or other source-native scoring modes;
- league-size or roster-format variants where published.

Every capability entry must also declare and verify the source observation's **game type/content type**. Dynasty eligibility is a separate dimension from scoring/lineup format. `SF + TE++` is not enough metadata; it must also be demonstrably a **dynasty** board/value mode.

Do not fabricate variants that a provider does not publish, and do not assume every source exposes the same dimensions.

Capability state must distinguish at least:

- **DIRECT NATIVE VARIANT** — explicitly published by the source;
- **DERIVED/INTERPOLATED** — future model output, never raw source data;
- **UNAVAILABLE** — confirmed not exposed;
- **UNKNOWN/UNVERIFIED** — not yet confirmed.

Missing is never zero.

## 4. KeepTradeCut is a priority calibration source

KTC is especially valuable because it exposes multiple format controls over the same underlying source family.

All KTC capture described in this section refers **only to KTC's dynasty products/data**. Do not substitute or mix any KTC non-dynasty/seasonal product if one exists now or in the future.

### 4.1 KTC TE-premium ladder — preserve all four states

Archive all four KTC TE-premium states whenever technically and legally feasible:

1. **Off** — KTC describes this as one starting TE with no TE scoring bonus.
2. **TE+** — one starting TE with a mild/moderate TE scoring bonus; KTC gives examples around +0.5/+0.75 PPR or roughly 1.5–2x the PPR received by WRs.
3. **TE++** — two starting TEs **OR** a significant/extreme TE scoring premium; KTC gives examples above +1 PPR / above 2x WR PPR or similarly large boosts.
4. **TE+++** — two starting TEs **AND** additional TE-specific scoring bonus(es) relative to WRs.

Preserve KTC's published description/version/as-of alongside the observations. Do not reduce these four modes to anonymous integers without retaining what KTC says each mode means.

### 4.2 Critical KTC interpretation

KTC states that its TE-premium values are **algorithmically applied from its base 12-team, .5-PPR, no-TEP crowd values**. Users answering K/T/C prompts are instructed to answer from that base no-TEP framework.

Therefore:

- Off/TE+/TE++/TE+++ are not four independent crowds;
- they are four same-source algorithmic transformations/calibration anchors;
- all four remain **one KTC source family** for consensus/source-independence purposes;
- the four states are nevertheless highly useful paired data for measuring KTC's own published TE adjustment curve.

Do not count KTC four times in Consensus Edge because four TEP modes were collected.

### 4.3 KTC QB modes

Where KTC exposes both 1QB and Superflex, archive both in the same scrape cycle where feasible, crossed with each available KTC TEP state.

Conceptually, the KTC capture matrix may therefore include:

- 1QB × Off
- 1QB × TE+
- 1QB × TE++
- 1QB × TE+++
- Superflex × Off
- Superflex × TE+
- Superflex × TE++
- Superflex × TE+++

Only capture combinations the source actually serves **as dynasty rankings/values**. Preserve the source's own base-format assumptions such as team count and PPR basis.

### 4.4 Why the KTC ladder is valuable

The four KTC TEP states give multiple points along a single source's TE-premium response curve. That can help answer empirically:

- how much TE1 changes from Off → TE+ → TE++ → TE+++;
- whether TE6/TE12/TE24 respond differently;
- whether the effect is monotonic but nonlinear;
- whether Superflex interacts with TE premium indirectly through the overall value ladder;
- whether the same KTC mode produces stable relationships over time.

Do **not** assume the labels map to a single numeric PPR premium. KTC itself describes the modes using both lineup demand (1TE vs 2TE) and scoring premium. Our future target-league adapter must therefore use the actual user's starting-TE demand and scoring configuration, not merely match a label string.

## 5. Raw observation schema / provenance

Every collected observation must preserve enough information to reconstruct exactly what the source said and under which format.

At minimum preserve:

- source family;
- source endpoint/page/mode identifier;
- retrieval timestamp;
- source-reported as-of timestamp if available;
- **game type/content type, with dynasty explicitly verified for every eligible observation**;
- evidence/provenance used to establish dynasty status;
- canonical asset identity plus original source identifier/name;
- native rank;
- native value if published;
- board/list type;
- QB mode;
- TE-premium mode/amount/label when explicit;
- lineup/TE-start mode when explicit;
- scoring preset when explicit;
- IDP mode/preset when explicit;
- league-size assumption when explicit;
- other source-native format metadata;
- raw snapshot hash/source hash;
- scraper/parser version;
- retrieval success/coverage state;
- source-provided tier/position rank where useful;
- common scrape-run/snapshot identifier tying simultaneous format variants together.

Keep raw source-native units intact. Never overwrite a native observation with the site's normalized value.

## 6. Same source, multiple variants = one source family

Multiple variants from one provider are calibration anchors, not independent consensus votes.

Example: a provider's SF/TEP, SF/non-TEP, 1QB/TEP, and 1QB/non-TEP outputs are four observations of how that provider responds to format, but one source family for source-independence.

Never turn format multiplicity into pseudo-consensus.

## 7. Learn empirical format-response curves, not proprietary formulas

The project may estimate how a source's **published dynasty outputs** change across dynasty formats. It should not claim to reverse-engineer or reproduce the provider's undisclosed internal formula, and it must never learn a dynasty-format response curve from a dynasty-vs-redraft comparison.

Legitimate questions include:

- How does a source's QB curve move from 1QB to SF?
- Is QB uplift concentrated among QB1–QB12 or does it persist to QB36?
- How does its TE curve move across TEP states?
- Do TE1, TE6, TE12, TE24, and TE36 receive different relative uplift?
- Does the relationship change over time?

Expected transformations should be rank/value-curve-sensitive where evidence supports that. Do not assume blanket positional multipliers such as `TE × 1.15` or `QB × constant`.

## 8. Paired-observation requirement

The highest-value calibration examples are same-source, same-run **dynasty** observations under different native dynasty formats.

Where possible, scrape all available variants in the same cycle and stamp a common run identifier so paired comparisons are not contaminated by market movement between scrape dates.

Every learned curve should preserve paired sample count, date range, source family, compared formats, overlapping coverage, position/rank region, uncertainty/confidence, and input hashes.

## 9. Future target-league adapter architecture

Keep four concepts separate:

**A. Source-native market opinion** — what the provider actually published.

**B. Source-specific empirical format response** — how that provider's published outputs move across its native format controls.

**C. Canonical target-league demand/scarcity model** — what the uploaded league's actual lineup and scoring settings imply structurally.

**D. Target-league normalized source observation** — the best-supported translation of the native source observation into the user's league, with provenance/confidence.

Do not conflate B and C. One measures provider/market behavior; the other is our independent league structure model.

All A/B observations in this dynasty system must originate from verified dynasty source data.

## 10. Canonical target-league dimensions

Universal-league support should model structural/continuous dimensions rather than only binary labels.

Relevant dimensions may include:

- teams;
- required QB starts;
- Superflex/OP eligibility and effective QB demand;
- required RB/WR/TE starts;
- FLEX composition and actual positional utilization;
- number of required TEs;
- TE reception premium;
- TE first-down/target premium;
- QB passing TD/interception/yardage/completion scoring;
- RB/WR reception/first-down/distance rules;
- roster depth and replacement pool;
- IDP required starters by DL/EDGE/LB/DB;
- IDP flex structure and scoring;
- kicker/DST settings where relevant;
- best-ball vs managed-lineup behavior where relevant downstream.

League configuration is factual input. A free-text profile label is not a substitute.

## 11. Replacement/PAR integration

Use the one canonical replacement/PAR owner. Do not create a second scarcity engine inside source normalization.

A 12-team start-1-TE league and a 12-team start-2-TE league must not receive the same TE treatment merely because both have a +0.5 reception premium. Likewise 10-team 1QB, 14-team 1QB, 12-team SF, and 14-team SF create different QB demand.

Use actual lineup configuration and, where defensible, measured positional utilization to estimate replacement scarcity.

## 12. Format confidence / provenance

A normalized source observation should preserve a state such as:

- **NATIVE EXACT** — direct source-native match;
- **NATIVE NEAR / INTERPOLATED** — target lies between supported native anchors;
- **CROSS-FORMAT MODELED** — learned source-specific transformation;
- **CROSS-SOURCE / STRUCTURAL EXTRAPOLATION** — source lacks adequate native variants and broader evidence/league structure is needed;
- **UNSUPPORTED** — insufficient evidence for a defensible translation.

Exact production labels can change. The requirement is that modeled/extrapolated observations not masquerade as direct native observations.

A separate dynasty-eligibility gate precedes these format-confidence states. An observation cannot be `NATIVE EXACT` for this system unless its game type is verified dynasty.

## 13. Do not force every weird scoring rule into every market source

Some unusual scoring rules can be modeled by our projection/fundamental/replacement systems without enough evidence to claim how a particular ranking provider would react.

When evidence is insufficient:

- preserve the source's market opinion honestly;
- model league-specific production/scarcity independently;
- expose disagreement where useful;
- do not invent fake source-specific precision.

Market-vs-fundamental divergence may itself be useful edge information.

## 14. IDP-specific requirements

Apply the same approach to IDP sources where multiple native modes/presets genuinely exist.

Preserve DL vs EDGE semantics, LB/DB groupings, IDP scoring preset, required IDP starters, flex structure, native rank/value units, format confidence, and explicit dynasty game-type provenance.

IDP Trade Calculator or another IDP provider remains one source family even if several scoring/format modes are archived.

Do not assume offense and IDP share one format-adjustment curve.

Do not ingest a provider's seasonal/weekly/redraft IDP rankings into the dynasty IDP value pool merely because the provider also publishes dynasty IDP material.

## 15. Historical archive policy

Alternate-format dynasty observations should be append-only/versioned like other historical value snapshots. Do not keep only the latest variant board.

Preserve enough history to evaluate stability, time variation, player/rank/position-specific effects, direct-vs-modeled translation error, and future out-of-sample backtests.

## 16. Early implementation phase — DATA COLLECTION ONLY

When separately authorized, the early capture phase should be deliberately narrow:

1. audit every current ranking/value source;
2. enumerate verified native **dynasty** format variants and explicitly identify/reject non-dynasty modes exposed by the same provider;
3. establish a game-type/content-type guard so only verified dynasty observations enter the dynasty archive;
4. extend scraper/source metadata to capture those dynasty variants;
5. preserve them in a versioned historical archive with common run IDs;
6. add coverage/freshness/provenance diagnostics, including dynasty-verification status;
7. prove current production outputs are byte/value-equivalent to the pre-change champion path;
8. add regression fixtures showing that a redraft/ROS/weekly/best-ball board cannot be accepted merely because it comes from an approved provider;
9. do not route alternate variants into canonical production ranking/value calculations;
10. do not change production weights;
11. do not activate any learned format transformation;
12. measure added runtime/network/storage cost and avoid unnecessary duplicate fetching.

For sites where access, terms, anti-bot controls, or paid entitlements make alternate scraping inappropriate, record the capability as unavailable/blocked rather than bypassing controls.

## 17. Future model-validation requirements

Before any normalized alternate-format observation affects production:

- prove every training/calibration observation is verified dynasty;
- define the target quantity;
- pin inputs;
- create train/validation/OOS splits over time;
- compare direct native target-format observations against predictions generated from other dynasty formats;
- measure error by source, position, rank/value region, and target format;
- test stability across market periods;
- validate interpolation separately from extrapolation;
- compare against simple baselines;
- establish minimum sample thresholds;
- maintain confidence/coverage states;
- require explicit owner approval before production activation.

A model that looks plausible is not enough.

## 18. Relationship to current/future work

This work depends on or interacts with:

- B6 scoring-profile / league-config truth;
- B7 realized scoring correctness;
- canonical league settings;
- canonical player/pick identity;
- historical value snapshots;
- source independence;
- confidence/coverage;
- CE-09 Replacement/PAR;
- TEP methodology review;
- future universal league onboarding/configuration;
- Consensus Edge and source lineage.

B6 establishes that league compatibility cannot be a hand-entered label. This specification defines the longer-term data/model direction that eventually replaces coarse format assumptions with factual league configuration plus evidence-backed normalization.

## 19. Non-scope for early capture

Do not during the early collection phase:

- ingest redraft, ROS, weekly, DFS, best-ball-only, keeper, seasonal, or other non-dynasty ranking/value data into the dynasty archive or model;
- assume an ambiguous provider endpoint is dynasty;
- change the champion board;
- promote/apply a format-normalization model;
- invent a universal SF/1QB multiplier;
- invent a universal TEP multiplier;
- collapse KTC Off/TE+/TE++/TE+++ into four independent votes;
- duplicate the canonical replacement engine;
- rebuild every scraper merely for symmetry;
- scrape modes that do not actually exist;
- bypass provider access controls;
- start universal-league UI simply because the archive exists.

## 20. Method status

**Dynasty-only source eligibility:** OWNER-DECIDED HARD INVARIANT. NON-DYNASTY OR UNVERIFIED OBSERVATIONS MUST FAIL CLOSED.

**Alternate-format historical collection:** OWNER-APPROVED DIRECTION; IMPLEMENT EARLY AFTER CURRENT URGENT FOUNDATION WORK WHEN EXPLICITLY AUTHORIZED.

**Source-specific format curves:** INVESTIGATION REQUIRED / EVIDENCE-GATED.

**Target-league normalization model:** FUTURE / EVIDENCE-GATED.

**Production activation:** OWNER APPROVAL REQUIRED AFTER OUT-OF-SAMPLE VALIDATION.
