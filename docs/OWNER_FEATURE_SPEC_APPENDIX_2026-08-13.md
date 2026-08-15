# Chase Upside — Owner Feature Specification Appendix

**Status:** BINDING COMPANION TO `OWNER_FEATURE_SPEC_RECONCILIATION_2026-08-13.md`  
**Date:** 2026-08-13

This appendix closes the smaller-feature / competitive-backlog specification gaps that are easy to lose when only the major product systems are described. It does not authorize implementation out of `EXECUTION_PLAN.md` sequence.

Global rules from the main reconciliation apply to every item here: one canonical owner, missing ≠ zero, explicit provenance/freshness/confidence, no duplicate engines, background expensive work, and production verification before “done.”

---

# A. ROSTER / TEAM SECONDARY FEATURES

## A1. Untouchables / protected assets

**Question:** Which assets should Chase Upside treat as unavailable for automated trade-away/drop recommendations?

This is a user/team policy layer, not a global player-value statement. It may include explicit user-protected players/picks and durable roster policies. Protected status must flow into Trade Finder, Trade Suggestions, Golden Upgrades, waiver/drop recommendations, package generation, and automated decision surfaces.

Do not lower canonical value or rank because an asset is untouchable. The restriction is **action eligibility**, not valuation.

UI must make protection understandable without forcing the user to re-enter it on every page. Changes should be explicit/auditable and should not silently alter historical recommendations.

## A2. QB handcuff / intentional roster-pair policy

Where the selected-team policy intentionally pairs a starting QB with that NFL team’s primary backup, roster-construction logic should recognize the pair as intentional depth rather than automatically recommending the backup as dead weight solely because standalone rank/value is low.

This belongs in roster-action policy (Dropability / Team Weakness / recommendations), not global canonical rankings.

## A3. Starter relevance filter (CE-22)

*Identifier reconciled 2026-08-14: this entry was tagged `CE-13` on PR #816, which conflicted with the canonical registry. See `docs/CE_REGISTRY.md`.*

**Question:** Which players/assets are actually relevant to this league’s starting and competitive environment?

Use canonical league roster/scoring configuration, projected/realized lineup demand, replacement levels, and roster context to distinguish likely starters/flex/meaningful depth from low-relevance inventory.

The filter may simplify recommendation and comparison surfaces, but must never delete or zero low-relevance assets. It is a view/relevance classification, not a value rewrite.

## A4. Roster-age windows (CE-23)

*Identifier reconciled 2026-08-14: this entry was tagged `CE-01` on PR #816, which conflicted with the canonical registry. See `docs/CE_REGISTRY.md`.*

Show age/durability distribution by position and competitive window rather than one misleading average age. Weighting should distinguish cornerstone/high-value/starter assets from low-value bench filler where appropriate and expose the method.

Use age curves as context for team-window analysis and future-strength forecasts; do not directly apply arbitrary age penalties to canonical value outside the valuation model.

## A5. League longevity / history (CE-24)

*Identifier reconciled 2026-08-14: this entry was tagged `CE-02` on PR #816, which conflicted with the canonical registry. See `docs/CE_REGISTRY.md`.*

Surface seasons played, franchise continuity, records, championships/playoffs, transaction history, notable eras, and long-term performance from canonical historical league data.

Historical franchise identity must survive owner/name changes where the league’s own continuity says the franchise is the same. Do not rewrite old seasons using current team names without preserving historical context.

## A6. Comparable-user strategy signals (CE-03)

*Identifier reconciled 2026-08-14: this entry was tagged `CE-12` on PR #816, which conflicted with the canonical registry. See `docs/CE_REGISTRY.md`.*

Future feature for comparing strategy patterns among sufficiently similar leagues/users/managers. Similarity must be explicit (format, scoring, roster size, market context, timeframe) and sample-size/confidence visible.

Never present behavior from dissimilar public leagues as personalized evidence merely because it increases sample size. Privacy boundaries apply.

---

# B. TRADE / PACKAGE SECONDARY FEATURES

## B1. Package Adjustment methodology

There are two distinct concepts that must remain distinct:

1. **Exact KTC-style Value Adjustment** — a market-parity consolidation lens Chase Upside intentionally preserves.
2. **Future canonical site package methodology** — must be defined/validated before claiming it is superior or even necessary as a second scalar.

Do not silently modify KTC-parity behavior for monotonicity or aesthetics. If a proprietary package scalar is proposed, it must define its target, validate across 1-for-1 / 2-for-1 / 3-for-1 / elite consolidation / picks / IDP / TEP topologies, benchmark against contemporaneous market/trade evidence, test pathological behavior, and show that it adds information beyond raw equity + KTC VA + roster marginal impact.

## B2. Trade-tax / friction constraints (CE-05)

*Identifier reconciled 2026-08-14: this entry was tagged `CE-05 lineage` on PR #816, which conflicted with the canonical registry. See `docs/CE_REGISTRY.md`.*

Trade recommendations should recognize that equal calculator value does not imply executable trade. Model relevant friction explicitly where evidence exists: consolidation premium, roster-space pressure, positional scarcity/need, pick liquidity, timing, counterparty incentives, and league-specific transaction constraints.

Do not hide these in an unexplained “tax” multiplier. Prefer explainable dimensions and observed market evidence.

## B3. Teammate / portfolio comparison (CE-06)

Compare concentration by NFL team, position, age/window, asset type, and possibly correlated outcomes. Canonical-value-weighted exposure is primary where valuation is relevant; counts are secondary.

This is primarily descriptive risk/context. Do not penalize a roster/trade simply for concentration without an owner-approved validated recommendation rule.

## B4. Compare multi-select (CE-25)

*Identifier reconciled 2026-08-14: this entry was tagged `CE-07` on PR #816, which conflicted with the canonical registry. See `docs/CE_REGISTRY.md`.*

Extend Player Compare beyond pairwise comparison to a bounded multi-select that uses the same canonical player contracts. Comparison columns should be aligned and source-aware, with responsive horizontal/stacked behavior on mobile.

No copied local values or separate comparison-only ranking math.

## B5. Trade counterpart / manager buy-sell frequency (CE-03)

Use canonical transaction history to show how often a manager buys/sells positions/assets, deal size, consolidation tendency, picks vs players, recurring counterparties, and time-window changes.

Descriptive evidence only unless a future validated Manager Scout model consumes it. Always show sample size/time window.

## B6. Future picks as trade assets (CE-02)

*Identifier reconciled 2026-08-14: this entry was tagged `CE-04` on PR #816, which conflicted with the canonical registry. See `docs/CE_REGISTRY.md`.*

This feature is now subordinate to the **Canonical Owned Future Pick Projection & Valuation Engine**. Actual league picks must have stable identity/ownership and executable availability. Generic hypothetical pick archetypes remain separate.

Do not build an independent CE-02 pick-value model.

## B7. Cross-league trade / portfolio view (CE-26)

*Identifier reconciled 2026-08-14: this entry was tagged `CE-10` on PR #816, which conflicted with the canonical registry. See `docs/CE_REGISTRY.md`.*

Allow a user with multiple supported leagues to compare roster/value/exposure or move between league contexts without data leakage. Every result must be stamped to the selected league configuration and roster ownership.

Do not combine values/needs from two leagues as if they share scoring/roster rules unless canonical configuration equivalence is proven.

## B8. League keeper / privacy mechanics (CE-27)

*Identifier reconciled 2026-08-14: this entry was tagged `CE-11` on PR #816, which conflicted with the canonical registry. See `docs/CE_REGISTRY.md`.*

Respect league-specific private/public boundaries, keeper/taxi/IR/draft constraints, and any owner-level visibility rules. Public/share outputs must exclude private intelligence and private league details by contract rather than relying on UI hiding.

Security/public-boundary foundation (B8) owns the underlying enforcement model.

---

# C. WAIVER / DRAFT SECONDARY FEATURES

## C1. Pre-auction / pre-draft immutable snapshot

Before a live draft/auction begins, preserve a versioned snapshot of rankings/values, available roster/picks/budget, league settings, recommendations, and model/source versions needed for later evaluation.

This allows post-draft analysis without rewriting what Chase Upside “knew” using later values.

## C2. Auction bid remaining-budget constraint

Every recommended/automated bid must respect remaining budget and any minimum-dollar-per-open-roster-slot rules. The recommendation contract should distinguish suggested target value from executable maximum bid.

No UI should recommend an amount the user cannot legally place.

## C3. Lineup IQ (CE-12)

*Identifier reconciled 2026-08-14: this entry was tagged `CE-15` on PR #816, which conflicted with the canonical registry. See `docs/CE_REGISTRY.md`.*

**Question:** How efficiently is a team converting available roster output into counted lineup output under this league’s actual lineup semantics?

For best-ball leagues, use exact best-ball optimization and evaluate missed/realized opportunity according to rules, not manual-start assumptions. For managed-lineup leagues, compare actual starts with defensible optimal/expected alternatives.

Metrics should distinguish decision quality from bad luck and preserve uncertainty where projections are involved.

## C4. Draft Room (CE-13)

*Identifier reconciled 2026-08-14: this entry was tagged `CE-16` on PR #816, which conflicted with the canonical registry. See `docs/CE_REGISTRY.md`.*

Live draft decision surface that composes Perfect Draft, canonical rankings/value, league config, remaining board, roster needs, pick/auction context, and future-pick/capital intelligence.

The Draft Room orchestrates canonical services; it does not own a separate board/value system.

---

# D. MARKET / INTELLIGENCE SECONDARY FEATURES

## D1. Market Pulse (CE-14)

*Identifier reconciled 2026-08-14: this entry was tagged `CE-17 lineage` on PR #816, which conflicted with the canonical registry. See `docs/CE_REGISTRY.md`.*

**Question:** What is moving in the dynasty market right now, and why?

Compose canonical value/rank changes, source movement, real trade/waiver market evidence, sharp behavior, factual news, and analyst signals. Preserve lineage so a KTC move and canonical value derived partly from KTC are not presented as two independent confirmations.

Show timeframe and distinguish price movement from news/opinion causes.

## D2. Sharp-manager concentration

Sharp Roster % should show not only aggregate ownership but whether that ownership is broad or concentrated in one/few managers. A player rostered by 8/10 independent sharps means something different from repeated exposure attributable to one manager or linked leagues.

Use canonical manager identity and de-duplicate linked/repeated evidence where possible.

## D3. Source freshness / provenance display

Every source-derived value, projection, news event, analyst take, or sharp observation should carry enough metadata to answer “from where?” and “as of when?” without overwhelming primary UX.

Freshness state (`fresh/stale/missing/unavailable` or domain equivalent) must be machine-readable; UI can progressively disclose it.

## D4. Human review / admin exception workflow

When player identity, source parsing, analyst identity, content classification, or model promotion needs manual correction, preserve an auditable override/decision record with who/when/why and avoid silently editing raw source evidence.

Manual correction should modify the canonical resolution layer rather than patch one consumer.

## D5. Adaptive source weighting

Future model should learn whether source reliability varies by position, horizon, season period, or target while preserving independence and avoiding circular self-validation against a target built from the same sources.

Candidate weights must be trained/evaluated on temporally valid outcomes/market targets, regularized/shrunk for sparse segments, compared with simple baselines/production, and promoted only with owner approval.

No automatic live self-reweighting without a governed challenger lifecycle.

## D6. Analyst/source independence

Two websites repeating the same underlying ranking, syndicated article, analyst take, or provider feed are one lineage, not multiple independent votes. Independence metadata should be explicit enough for Consensus Edge, confidence, and canonical value aggregation to avoid false corroboration.

This is central B10 foundation work.

---

# E. PLAYER / RANKING SECONDARY FEATURES

## E1. Blended source rank / source-board comparison

Display where each provider ranks/values a player and how the canonical board relates to them. Preserve source-native scale/format before normalization. Missing coverage is not a zero/worst rank.

UI should make disagreement useful without implying all sources are equally independent or equally relevant to the league format.

## E2. Confidence semantics

Confidence must answer a defined question—e.g., confidence in canonical value/rank, forecast distribution, recommendation, or data readiness. It cannot be one universal decorative percentage.

Inputs may include source coverage, independence, dispersion, freshness, model calibration, identity quality, and horizon, but each feature must expose the meaning. B11 owns foundation semantics.

## E3. Model provenance

Material model-derived outputs should be traceable to model version, input/as-of state, and relevant configuration. Historical artifacts preserve the model/input version used at creation.

Provenance is primarily for correctness/audit/explainability; UI can expose it on demand.

## E4. Personal Rankings (CE-14A)

*Identifier reconciled 2026-08-14: this entry was tagged `CE-19` on PR #816, which conflicted with the canonical registry. See `docs/CE_REGISTRY.md`.*

Allow a user to maintain personal preference/rank overlays without corrupting global canonical truth. Personal ranks can power compare/watchlist/decision context, but canonical value/rank remains independently visible.

If personal feedback is later used to train personalization, that is a separate governed model decision.

## E5. Individualized rankings / tuning (CE-14A)

*Identifier reconciled 2026-08-14: this entry was tagged `CE-14` on PR #816, which conflicted with the canonical registry. See `docs/CE_REGISTRY.md`.*

Personalized ranking should arise from explicit league/team/user context with explainable deltas from canonical global rank/value. Avoid opaque wholesale reorderings that make it impossible to tell whether the market or personalization moved.

Treat personalization as a layer over canonical truth unless a validated model explicitly defines otherwise.

## E6. User feedback / polling (CE-28)

*Identifier reconciled 2026-08-14: this entry was tagged `CE-14A` on PR #816, which conflicted with the canonical registry. See `docs/CE_REGISTRY.md`.*

Collect structured feedback on recommendations, trade outcomes, preferences, or UI usefulness with clear target semantics. Do not treat clicks/approval as ground-truth player value without bias analysis.

Feedback can inform product evaluation and future challengers, but model use requires provenance, privacy, and temporal validation.

---

# F. PUBLIC / SOCIAL / NOTIFICATION SECONDARY FEATURES

## F1. Push notifications (CE-29)

*Identifier reconciled 2026-08-14: this entry was tagged `CE-08` on PR #816, which conflicted with the canonical registry. See `docs/CE_REGISTRY.md`.*

Notify only on meaningful selected-team/watchlist/league events or decision changes. Canonical event/signal dedupe prevents multiple source copies from generating multiple notifications.

Users need category/frequency controls; critical auth/security notifications remain separate from fantasy-content preferences.

## F2. Share Renderer (CE-10)

*Identifier reconciled 2026-08-14: this entry was tagged `CE-21` on PR #816, which conflicted with the canonical registry. See `docs/CE_REGISTRY.md`.*

See main reconciliation §6.9. Additional requirement: all public share outputs must consume a privacy-safe public contract. A private Consensus Edge rationale or hidden owner preference must not leak simply because a public card reuses a component.

## F3. Personalized campaign/feed (CE-15)

*Identifier reconciled 2026-08-14: this entry was tagged `CE-20 lineage` on PR #816, which conflicted with the canonical registry. See `docs/CE_REGISTRY.md`.*

A personalized feed should rank genuinely actionable changes for the selected team: injuries/status, market moves, waivers, trade opportunities, opponent/matchup leverage, analyst consensus changes, and deadlines.

It is an orchestration/ranking layer over canonical signals and should explain why an item is relevant now. Avoid engagement-maximizing filler.

## F4. Security / public-boundary correctness

Public and unauthenticated routes must have explicit contracts about which league/user/model data may be exposed. Redaction occurs in backend/public contracts, not merely by hiding frontend controls.

Private selected-team recommendations, admin data, credentials, internal provenance that creates security risk, and private league data must not leak through public endpoints/share artifacts/cache keys.

B8 is the foundation phase for this family.

## F5. Draft-capital/public redaction

When draft capital/picks are public, expose only fields authorized by the public league contract. Internal valuation diagnostics, private recommendation context, or hidden user preferences remain private. Stable pick identity may be public while current owner-private analysis remains private.

---

# G. PERFORMANCE / RELIABILITY PRODUCT REQUIREMENTS

## G1. Rankings pagination

Serve a bounded initial slice (current target 50) with stable filtering/sorting/paging semantics. Do not make the browser download/re-render the entire board to simulate pagination.

## G2. Compact payloads

API responses should provide the fields needed by the requesting surface; avoid repeatedly shipping full giant contracts when a section/subcontract is enough. Preserve canonical IDs/version/freshness so compact responses remain attributable.

## G3. Mobile scaling

Premium Sports Intelligence should retain information density on mobile through hierarchy, horizontal affordances, progressive disclosure, sticky controls, and responsive tables—not by converting every row into an oversized rounded card.

## G4. E2E diagnostics / root-cause evidence

Production E2E failures should preserve enough endpoint/status/payload/screenshot/log evidence to distinguish app defect, missing data, authentication, timeout, and test-harness failure. A green workflow is not production truth if the meaningful assertion was skipped/advisory.

## G5. LKG / stale-while-revalidate behavior

Slow/failed refresh should serve last-known-good when that is semantically safe and clearly stamped. Never let LKG silently claim current freshness. For correctness-sensitive state where stale evidence is unsafe (e.g., proven league-config compatibility past its authority window), fail/degrade explicitly rather than using LKG as truth.

---

# H. REMOVED / SUPERSEDED / DO-NOT-DUPLICATE RULES

- Removed public money/constitution concepts stay removed unless reauthorized.
- Current simplistic Pick Projector is a transitional implementation to be superseded by the canonical owned-pick engine, not preserved as a competing answer.
- Multiple power-ranking engines should be consolidated into one canonical Power system.
- YouTube intelligence extends Podcast/Analyst Intelligence; it is not a second signal engine.
- Game Day, Command Center, Trade Desk, Portfolio, Draft Room, and UPP are orchestration surfaces; canonical truth remains in the underlying services.
- KTC Value Adjustment and any future site-specific package methodology remain distinct concepts.
- Personal/user rankings do not overwrite global canonical rankings.
- Public League and authenticated navigation must point to one canonical `/league` experience rather than forked copies.

---

# I. DONE MEANS MORE THAN “PAGE EXISTS”

For every feature in this appendix, the exit standard remains:

1. current bad/missing contract understood;
2. canonical owner identified;
3. dependencies satisfied;
4. RED→GREEN or equivalent evidence for correctness work;
5. no duplicate truth engine introduced;
6. missing/stale/degraded semantics explicit;
7. performance budget met;
8. mobile/public/privacy behavior checked where relevant;
9. production behavior verified on real data;
10. owner-facing explanation matches the intended user question.

A route, component, endpoint, or test file existing in the repository is **not** sufficient evidence that the feature is complete.
