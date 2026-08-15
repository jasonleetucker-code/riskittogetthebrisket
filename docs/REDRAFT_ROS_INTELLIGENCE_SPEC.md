# Redraft / Rest-of-Season Intelligence — Seasonal Competitive Layer

> **RECONCILIATION AMENDMENT — 2026-08-14.** Promoted to `main` verbatim from its planning branch by the
> post-B master reconciliation (`docs/POST_B_RECONCILIATION_2026-08-14.md`). No content was changed.
> Its C-Series phase placement and completion evidence live in
> `docs/C_SERIES_SCOPE_MANIFEST.md`.


**Status:** CANONICAL DETAILED PRODUCT/METHODOLOGY SPEC  
**Owner direction captured:** 2026-08-12  
**Execution posture:** APPROVED FUTURE DATA/INTELLIGENCE LAYER; EARLY COLLECTION MAY BEGIN IN THE SAME LOW-RISK SOURCE-ARCHIVE PHASE WHEN EXPLICITLY AUTHORIZED  
**Public/private posture:** MIXED — private decision intelligence plus public-safe broadcast outputs where separately approved

## 1. Governing distinction

Risk It To Get The Brisket is a dynasty product, but some questions are intentionally **current-season / rest-of-season** rather than long-horizon asset-value questions.

Therefore maintain two strictly separated evidence domains:

1. **DYNASTY VALUE DOMAIN** — only verified dynasty rankings/values may influence canonical dynasty player/pick value, dynasty source consensus, dynasty format-response curves, dynasty Buy/Sell value signals, and other long-horizon asset-value systems.
2. **REDRAFT / ROS COMPETITIVE DOMAIN** — verified redraft/rest-of-season/current-season rankings, projections, tiers, and related seasonal evidence may inform current-season competitive-strength models and features, but must never leak into canonical dynasty value.

A provider may contribute to both domains through different products/endpoints, but every observation must carry an explicit `gameType` / `horizon` classification and lineage.

**Redraft is useful evidence for seasonal competition. It is not dynasty value evidence.**

## 2. Approved uses for redraft / ROS evidence

Redraft/ROS sources may be used, after methodology validation, for current-season questions such as:

- rest-of-season player strength / ROS rankings;
- current-season team competitive strength;
- Power Rankings where a current-season production component is appropriate;
- playoff qualification probability;
- championship probability;
- weekly matchup projection inputs where source horizon matches the task;
- contender / fringe contender / rebuilder classification, as one seasonal component alongside dynasty roster/value context;
- future-pick forecasting where the original owner's expected current-season finish affects pick-slot distribution;
- Game Day / remaining-season projections;
- lineup intelligence;
- injury/role-adjusted seasonal outlook;
- projected points / positional production for the remainder of the current season;
- public-safe broadcast probabilities where the public/private product policy separately permits them.

Do not automatically use every redraft signal in every feature. Each downstream system must define the quantity it is predicting and whether ROS/redraft evidence belongs in that quantity.

## 3. Explicitly prohibited uses

Redraft, weekly, ROS, best-ball, DFS, or other seasonal rankings/values must **not** directly influence:

- canonical dynasty player value;
- canonical dynasty pick market value;
- dynasty source weights;
- dynasty source-consensus counts;
- dynasty format-normalization curves;
- long-horizon dynasty Buy/Sell solely because a player is strong/weak for this season;
- KTC/Dynasty Nerds/IDP dynasty calibration by mixing their seasonal products with their dynasty products;
- acquisition historical dynasty value;
- any feature presented as dynasty market value.

If a feature combines long-horizon dynasty value and current-season competitive outlook, keep those components separately named and separately sourced before synthesis.

## 4. Source universe

The ROS/redraft source universe does **not** have to be limited to providers already used for dynasty valuation.

Research and select a strong, diverse core of reputable current-season fantasy sources based on:

- explicit ROS/redraft product semantics;
- update frequency;
- projection/ranking depth;
- position coverage;
- IDP coverage where needed;
- methodology transparency where available;
- historical reliability/calibration where measurable;
- stable/authorized technical access;
- source independence;
- availability of exact scoring/format variants;
- freshness and provenance.

A dynasty provider's redraft product is not automatically privileged merely because its dynasty product is already integrated. Conversely, a high-quality redraft-only source may be valuable for ROS systems even though it can never enter the dynasty valuation pool.

Do not multiply one publisher/network into pseudo-consensus if several feeds are descendants of the same underlying rankings/projections.

## 5. Observation taxonomy / metadata

Every seasonal observation must preserve at least:

- source family;
- endpoint/page/mode;
- retrieval timestamp;
- source as-of timestamp when available;
- `gameType` / horizon, e.g. `REDRAFT_PRESEASON`, `REST_OF_SEASON`, `WEEKLY`, `PROJECTION`, `BEST_BALL`, etc.;
- season;
- week/as-of-week when applicable;
- canonical player identity plus native source identity;
- native rank/value/projection/tier;
- position;
- QB format;
- PPR/scoring preset;
- TE premium / start-TE settings where exposed;
- IDP format/preset where exposed;
- team-count/roster assumptions where exposed;
- source hash/snapshot hash;
- parser version;
- coverage/freshness state;
- common scrape-run ID where multiple variants are captured together.

Never strip the horizon label from an observation.

## 6. Horizon matching

Use evidence whose time horizon matches the downstream question.

Examples:

- **ROS playoff odds in Week 8:** ROS rankings/projections are appropriate; preseason redraft ranks should be heavily stale or excluded unless explicitly modeled.
- **Week 10 Game Day:** weekly projections may be appropriate; full-season redraft ADP is not a direct substitute.
- **Pick Forecast:** current-season ROS team strength may inform expected finish, but dynasty asset value still comes from the dynasty domain.
- **Contender/Rebuilder:** current-season ROS strength may identify contention probability, while long-term dynasty value/age/picks characterize roster window. Do not collapse those into one unlabelled score.

Freshness is part of the signal, not another independent vote.

## 7. Pick Forecast integration

CE-02 Pick Forecast should eventually model the specific future pick as a probability distribution over finish/slot outcomes.

For a pick whose slot depends on the original owner's current-season result, ROS evidence may inform:

- expected remaining player production;
- team ROS strength;
- schedule-adjusted win/outcome probabilities;
- playoff qualification odds;
- playoff advancement/championship paths where draft order depends on those outcomes.

Keep separate:

- **specific slot probability** driven partly by seasonal competitive evidence;
- **generic/specific dynasty pick value** driven by canonical dynasty valuation methodology.

A strong ROS team can imply a later expected pick without making the underlying generic future first intrinsically worth less than the value assigned to that expected slot.

## 8. Playoff / championship probability integration

Playoff/championship models should combine defensible independent inputs rather than use a redraft ranking as the probability itself.

Potential inputs include:

- current record/standings;
- points / realized team performance;
- remaining schedule;
- ROS player/team projection distributions;
- injuries/availability where modeled;
- best-ball or managed-lineup rules;
- league-specific scoring;
- playoff structure/tiebreakers.

Redraft/ROS ranks are evidence about remaining-season player strength. They are not a substitute for Monte Carlo/outcome simulation or exact league rules.

Archive predictions and evaluate calibration: teams assigned 30% playoff probability should qualify at roughly that rate over adequate samples.

## 9. Contender vs rebuilder

Do not define contender/rebuilder solely from dynasty value or solely from ROS rank.

A future canonical classification should distinguish at least:

- **current-season contention strength** — ROS/current-season evidence;
- **long-horizon dynasty asset strength** — canonical dynasty values/picks/age/window;
- **uncertainty/confidence**.

This allows meaningful states such as:

- strong contender + strong dynasty core;
- strong contender + aging/thin future;
- weak current-season team + strong rebuilding asset base;
- weak current-season team + weak long-term assets.

Do not publicly expose private strategic Buyer/Seller/Strong Seller recommendations merely because this classification exists. Public `/league` may use sanitized sports-broadcast framing only under Public League Experience v3 rules.

## 10. Format adaptation

Seasonal sources also require target-league adaptation where source-native scoring differs from the league.

Use the same architectural discipline as dynasty multi-format normalization:

**source-native seasonal observation** + **verified source format/horizon** + **target-league scoring/lineup structure** + **canonical projections/replacement/scarcity where appropriate** → **seasonal normalized evidence with confidence/provenance**.

Do not assume one generic redraft ranking can serve 1QB, SF, 2TE, deep-start, IDP, or unusual-scoring leagues without adjustment.

Where a seasonal source offers multiple native formats, capture them as calibration anchors. Multiple variants from one provider remain one source family.

## 11. Source independence / anti-double-counting

Keep lineage explicit among:

- source rankings;
- source projections;
- consensus rankings built from those sources;
- our ROS team-strength model;
- playoff simulations using that ROS strength;
- Pick Forecast using playoff/team-strength outputs.

Do not later count all descendants as independent evidence in the same final decision.

Example: if playoff odds already consume the canonical ROS strength model, Pick Forecast must not naively count both ROS Strength and those playoff odds as two unrelated votes without modeling their dependency.

## 12. Missing / stale behavior

- missing ROS rank ≠ zero current-season strength;
- no current projection ≠ zero points;
- stale preseason rank ≠ fresh ROS opinion;
- an injured player's missing projection ≠ automatic zero unless the source/model explicitly establishes zero expected availability;
- unsupported format ≠ exact-format ranking.

Represent `UNAVAILABLE`, `STALE`, `UNSUPPORTED`, `PARTIAL`, and confidence/coverage honestly.

## 13. Historical archive / evaluation

Archive seasonal observations rather than keeping only the latest board.

Historical data should support:

- source accuracy versus realized rest-of-season production;
- projection calibration;
- source reliability by position/format/time of year;
- playoff/championship probability calibration;
- Pick Forecast slot calibration;
- contender classification evaluation;
- whether combining sources improves on simple baselines.

Do not activate adaptive reliability weights until adequate leakage-safe historical evidence exists and the weighted challenger beats a static/diverse baseline out of sample.

## 14. Early collection recommendation

When the Multi-Format Source Archive bootstrap is separately authorized after urgent B6/B7 work, include a **capability/discovery pass for seasonal data** at the same time where low-risk.

That pass may:

1. enumerate current-season/redraft/ROS products exposed by existing providers;
2. research additional reputable ROS/redraft sources worth adding;
3. classify horizon and format explicitly;
4. begin archival capture of high-value ROS/redraft boards/projections;
5. keep the seasonal archive physically/logically separated from dynasty valuation inputs;
6. prove production dynasty values are unchanged;
7. measure runtime/network/storage costs;
8. add guards proving seasonal observations cannot enter the dynasty source pool.

This does **not** authorize immediate redesign of playoff odds, Pick Forecast, ROS Strength, contender/rebuilder, or Game Day. Collecting data early and activating downstream methodology are separate decisions.

## 15. Validation gates before downstream production use

For each downstream application, define the target first and compare against baselines.

Examples:

- ROS player-strength model: future realized points/value over the rest of that season;
- playoff odds: probability calibration / Brier or log-loss style evaluation;
- championship odds: calibration and discrimination with playoff-bracket rules;
- Pick Forecast: expected-slot error and bucket calibration;
- contender classification: relationship to realized playoff/championship outcomes, while preserving long-horizon dynasty distinction.

Pin inputs and evaluate out of sample through time.

## 16. Relationship to dynasty source-normalization spec

`docs/MULTI_FORMAT_SOURCE_NORMALIZATION_SPEC.md` remains the canonical specification for **dynasty source-native format capture and future dynasty league normalization**.

This document extends the architecture with an intentionally separate **seasonal competitive evidence domain**.

The two domains may share infrastructure such as:

- player identity;
- source capability metadata;
- scraping scheduler;
- provenance/snapshot infrastructure;
- scoring/league-config parsing;
- historical storage;
- confidence/coverage primitives.

They must not share an untyped observation pool where redraft can accidentally become dynasty evidence.

## 17. Method status

**Redraft/ROS data collection for seasonal intelligence:** OWNER-APPROVED DIRECTION; suitable for early archival bootstrap after urgent foundation work when explicitly authorized.

**Use in playoff/championship probability, Pick Forecast, contender/rebuilder, Game Day, ROS Strength, and other seasonal models:** PRODUCT APPROVED IN PRINCIPLE; EXACT METHODOLOGY REQUIRES VALIDATION PER FEATURE.

**Use in canonical dynasty value:** PROHIBITED.