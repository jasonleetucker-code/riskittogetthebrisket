# Owner Feature Inventory

**Every user-facing feature, decision product, intelligence surface and materially new capability
the master specification / execution plan proposes to build, complete, repair, consolidate,
surface or materially change — deduplicated, classified, and reconciled against the actual
repository at HEAD.**

Built 2026-08-11 at the owner's request, as a scope-control checkpoint before any Phase B
implementation. Reconciled against BOTH the master specification and the tree — the phase-plan
bullets are **not** treated as exhaustive; several items below appear in the repo or the
specification but in no plan bullet.

**2026-08-11 owner-scope reconciliation:** §13 incorporates the later owner-approved YouTube,
player-profile, ticker, TEP, trade-exposure, Dynasty Daddy, X-feed, Game Day, Monte Carlo,
Second Opinions and Analyze Trade requirements. Where older wording in this file conflicts with
§13's explicit owner clarification, the newer §13 decision controls.

> **POST-B RECONCILIATION — 2026-08-14.** B4–B11 are merged and the B-Series Completion Audit passed
> (#837, `79f47ff`). **Individual status cells in this file that describe a B-era defect as current are
> stale**; rows 7.4, 7.5 and 7.6 are annotated inline. Row 2.8's "honestly unpriced" posture is
> **superseded** — see the row. Scope, phase, canonical owner and completion evidence for every
> capability now live in `docs/C_SERIES_SCOPE_MANIFEST.md`; this file remains the exhaustive
> capability/status ledger. §12 and §13.5's CE table mirrors `docs/CE_REGISTRY.md`, which is canonical.

## How to read this

**Classification** is exactly one of:

| code | meaning |
|---|---|
| **KEEP — NEW BUILD** | Does not exist. Owner wants it. Must be built. |
| **KEEP — EXISTING, REPAIR/COMPLETE** | Exists but is defective, partial, or unwired. |
| **KEEP — EXISTING, CONSOLIDATE** | Exists two or more times, in disagreement. Pick one owner, retire the rest. |
| **KEEP — INFRASTRUCTURE/FOUNDATION** | Not a product feature. Everything above it depends on it. |
| **REMOVE — OWNER DOES NOT WANT** | Out of scope by owner decision. Not backlog. |
| **ALREADY COMPLETE — VERIFY ONLY** | Believed done. Needs current-HEAD proof, not code. |
| **KEEP — FUTURE / EVIDENCE-GATED** | Approved in principle, deliberately dormant until evidence justifies it. |
| **NEEDS OWNER DECISION** | Cannot be resolved from repo, spec, data or methodology. |

**All seven previously-open owner decisions were resolved on 2026-08-11** and are recorded
inline below plus summarised in §11. No item in this inventory now carries
NEEDS OWNER DECISION.

**Scope** is S / M / L / XL. **Status** is what the repository actually does at HEAD, not what a
document claims. Where the registry and the tree disagree, the tree wins and the disagreement is
stated.

A deliberate exclusion: this inventory covers **product**, not plumbing. Audit tooling, test
harnesses, migrations, CI gates, lint/format work, one-line bug fixes and pure refactors are out
of scope here — they appear in `docs/master-site-audit/` and `docs/ARCHITECTURE_HANDOFF.md`.
Foundations are included only where a product capability cannot exist without them.

---

## 0. Removed from scope

| # | Feature | Purpose | New/Existing | Current status | Phase | Deps | Scope | Classification |
|---|---|---|---|---|---|---|---|---|
| 0.1 | **Fantasy league schedule generator** | Generate the 12-team / 3-division / 14-week regular-season schedule with divisional constraints and a forced week-4 matchup | New | **No implementation anywhere** — a whole-tree grep over 10,409 files returns nothing; no route, script, config or doc | ~~D7~~ | — | ~~L~~ | **REMOVE — OWNER DOES NOT WANT / NOT APPLICABLE** |

Recorded 2026-08-11. `W28-F001` is marked `published: false` with
`ownerDisposition: "NOT APPLICABLE — OWNER REMOVED FROM SCOPE"`; the published-findings count
falls 432 → 431 and open P1s 48 → 47. Removed from `NEXT_STEPS.md`'s build table and from
`REPAIR_ROADMAP.md`'s P1-13 closure list (where it never belonged on mechanism anyway — it was
grouped by workstream adjacency). **There was no code to delete.** It must not reappear as a
build, blocker, backlog item or future feature.

---

## 1. Roster intelligence

| # | Feature | Purpose | New/Existing | Current status at HEAD | Phase | Deps | Scope | Classification |
|---|---|---|---|---|---|---|---|---|
| 1.1 | **Team Strength** | One canonical answer to "how strong is this roster" — the meaningful upper roster: QB3 / RB3 / WR5 / TE3 / DL5 / LB5 / DB5 by canonical league-adjusted value | New (as canon) | **Does not exist as a single owner.** Multiple partial notions exist and disagree: terminal roster strength is a raw sum of `rankDerivedValue` with no lineup solve (W20-F003), `src/ros/` carries an ROS 0-100 strength, `roster_intel` computes marginal values. No module implements the spec's Top-N table | C1 | B9 (value-scale semantics) | **L** | KEEP — NEW BUILD |
| 1.2 | **Team Weakness / Need Priority** | Which starting slots the roster cannot fill, against explicit thresholds (QB1 Top12, QB2 another Top24, WR3 another Top36, IDP = slot × league size, Flex from real league settings) | Existing, unverified | `src/roster_intel/` computes something in this shape but has **zero frontend consumers** (W20-F001) and known defects (W20-F011: urgentNeed contradicts the roster's own lineup solve). **Must be proved or repaired against the spec's thresholds before being made canonical** — owner directive, not merely wired up | C2 | C1 | **M** | KEEP — EXISTING, REPAIR/COMPLETE |
| 1.3 | **Roster-aware trade simulation** | Before/after Top-N group membership per position, modelling promotions and displacements, plus needs fixed and needs created | Existing, shallow | `/api/trade/simulate` sums values; no cascade, no before/after group comparison, no needs delta | D1 | C1, C2 | **L** | KEEP — EXISTING, REPAIR/COMPLETE |
| 1.4 | **Dropability / cut candidates** | Which rostered players are genuinely droppable, set-dependently (FLEX/SF make this a matching problem, not a per-position count) | Existing, partial | Real primitives exist in `src/draft/displacement.py` (ECC ladder) and `src/ros/lineup.py::solve_optimal_assignment`. Not exposed as a general product surface; waiver page pairs adds with a naive lowest-value drop | D5 | C1 | **M** | KEEP — EXISTING, REPAIR/COMPLETE |
| 1.5 | **Untouchable / excluded-player control** | Mark players that trade, waiver and draft optimizers must never propose moving or dropping — **extended 2026-08-14 by rows 2.10/2.11**: user + fantasy-league scoped, outgoing-only for NFL-team protection, plus temporary LOCK/EXCLUDE package refinement | New | Does not exist (W09-F011) | D8 | D2 | **M** | KEEP — NEW BUILD |

| 1.6 | **Roster age-value portfolio / Young Core Index** | Show how a roster's meaningful dynasty value is distributed across ages, which position groups are old relative to the league, and who owns the strongest concentration of meaningful young talent | New | **OWNER DECISION 2026-08-14 (#838): BUILD.** Absent. Value-weighted core age over the canonical meaningful Team Strength group; age-value distribution; per-position profiles for QB/RB/WR/TE/DL-EDGE/LB/DB with league rank and percentile; a 0–100 league-relative **roster-construction** index with youth normalized per position and weighted by canonical value; overall and positional "youngest valuable room" leaderboards; a compact Age & Value module on every team profile. **Does not create a second age-adjusted valuation — canonical value already embeds age.** Missing age stays missing; picks are excluded from age math, never age zero. Binding requirement: `docs/OWNER_FEATURE_ADDENDUM_2026-08-14_AGE_VALUE_PORTFOLIO.md`; manifest `C2-AGE-01`…`C2-AGE-03`, `C7-AGE-01` | C2 / C7 | 1.1, 1.2, 7.1 | **M–L** | KEEP — NEW BUILD |

| 1.7 | **Canonical Meaningful Roster Core (#839)** | One site-wide roster-core selector for every whole-team dynasty value or strength claim | New | **OWNER DECISION 2026-08-14: BUILD.** Replaces hard-coded QB3/RB3/WR5/TE3/DL5/LB5/DB5 selection and raw full-roster sums with one league-config-derived selector: **`ceil(1.5 × real starter demand)` per position**, **Superflex counted as real QB demand** (1QB + 1SF ⇒ 2 QB-demand starters ⇒ 3 meaningful QBs), and regular/IDP FLEX resolved as the highest-valued remaining eligible depth after dedicated position cores. No page-local top-N rules. **Ships as the V1 champion labelled PRIOR**, with the `MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md` §4.3 challenger pass (1.25× / 1.50× / 1.75× / data-derived) before it is frozen. Manifest `C2-CORE-01`. **Provenance corrected 2026-08-17:** this is addendum #839 (2026-08-14), promoted here and to `OWNER_REQUESTED_TODO_SPEC_INDEX.md` T-NEW-19 — it is **not** intake decisions 47–49, which are #829's Weekly Report Studio decisions, and `#839` has no row in the intake ledger. See `docs/C_SERIES_DIRECTIVE_RECONCILIATION_2026-08-17.md` §4.1 and §6.1. **AMENDED 2026-08-18 by owner addendum #899 (ordering):** FLEX is an ASSIGNMENT RULE, not a sortable Team Strength position. Actual starter assignment comes FIRST — dedicated slots, then each actual FLEX/SF/IDP-FLEX starter slot from the highest-valued remaining legally eligible players — and every actual starter is removed from the pools BEFORE reserve selection. Reserve demand is then `ceil(M × slots) − slots` per dedicated position, and `ceil(M × actual FLEX slots) − actual FLEX slots` for FLEX. `M` stays the 1.5× V1 champion/PRIOR with its §4.3 challenger pass — this changes WHEN a player leaves the pool, not the multiplier. Every player counts at most once; reuse the canonical exact assignment machinery (`src/ros/lineup.py`), never per-position greedy lists. No FLEX column required. See `docs/OWNER_FEATURE_ADDENDUM_2026-08-18_FLEX_STARTER_ASSIGNMENT.md` | C2 | 1.1 | **M** | KEEP — NEW BUILD |

---

## 2. Trade products

| # | Feature | Purpose | New/Existing | Current status at HEAD | Phase | Deps | Scope | Classification |
|---|---|---|---|---|---|---|---|---|
| 2.1 | **Trade calculator** | Value a proposed trade on the canonical board | Existing | Live at `/trade`. **W08-F004 repaired this session** — the search box could not find the current rookie class | — | — | S (done) | ALREADY COMPLETE — VERIFY ONLY |
| 2.2 | **Package adjustment / consolidation** | Preserve KTC market-parity Value Adjustment while establishing the site's canonical package/roster decision semantics | Existing, duplicated + future methodology | KTC's algorithm is ported in `src/trade/ktc_va.py`; duplicate/legacy implementations still require consolidation. **OWNER CLARIFICATION 2026-08-11:** exact KTC VA is the trusted market-parity/consolidation benchmark and must remain available, including genuine non-monotonic behavior in KTC-parity mode. The site has **not** yet proven a superior proprietary scalar "Our VA". Do not invent one merely to have one. The preferred canonical architecture may be canonical asset/package equity + exact KTC VA as the market lens + separate before→apply→rerank→after roster marginal impact. Only introduce a proprietary scalar package premium if a defined target and evidence show it adds information; benchmark any candidate against KTC and contemporaneous market evidence across common trade topologies. KTC parity must be visibly distinct from canonical roster impact and must not silently contaminate Team Strength/Weakness, Golden Upgrades, Perfect Waivers or the final Analyze Trade decision | C5 / D1 / future evidence gate | 1.1, 1.2, 1.3 | **M–L** | KEEP — EXISTING, CONSOLIDATE + EVIDENCE-GATED CANONICAL METHODOLOGY |
| 2.3 | **Trade Finder (arbitrage)** | Find trades where our board and the retail market disagree | Existing, defective | Live at `/arbitrage`. Open: no dominance pruning (W09-F012), gain not normalized by package size (W09-F002), lopsidedness ranked over mutual benefit (W09-F009) | D2 | — | **M** | KEEP — EXISTING, REPAIR/COMPLETE |
| 2.4 | **Trade Suggestions** | Roster-aware sell-high / buy-low / consolidation proposals | Existing, defective | Returns zero suggestions for 8 of 12 teams with no diagnosis (W09-F001); no DB can ever be proposed (W27-F002) | D2 | — | **M** | KEEP — EXISTING, REPAIR/COMPLETE |
| 2.5 | **Golden Upgrades** | Surface owned-player → target pairs where our model prefers the target while the market prefers what you already own, so the swap can improve the model score *and* potentially extract market value | Existing semantics, new surface | The arbitrage finder already computes market inversion. **OWNER DECISION 2026-08-11: KEEP as a distinct user-facing surface, but it must NOT become a second trade/arbitrage/value engine** — it is a specialized *consumer* of canonical infrastructure (values, ownership, package generation, package adjustment, roster-impact simulation, Team Strength/Weakness, market data, confidence). Distinct presentation, not distinct methodology. Criteria: owned by selected team; genuinely substitutable target; model prefers target; market prefers owned; obtainable; inversion meaningful enough to act on | D3 | D2, C1, C5 | **S–M on top of D2** | KEEP — EXISTING, REPAIR/COMPLETE |
| 2.6 | **Package Builder** | Build trade packages with return-position constraints applied **during** generation, not as a post-filter | New | No Package Builder component exists in the tree. **OWNER DECISION 2026-08-11: BUILD it as a real user-facing feature.** It must use the SAME canonical package-generation engine as Trade Finder / Trade Suggestions — no second package algorithm. Constraints: QB, RB, WR, TE, DL/EDGE, LB, DB, PICKS, honoured intentionally when several are selected. Must respect selected team, ownership, excluded/untouchable players (1.5), package adjustment (2.2), roster impact (1.3), Team Strength/Weakness (1.1/1.2), pick identity (2.7), missing/unpriced state, and league settings | D8 | 2.2, 2.3, 2.7, 1.5 | **L** | KEEP — NEW BUILD |
| 2.7 | **Stable draft-pick identity** | A pick keeps season + round + original owner + current owner through the whole pipeline | Existing, lossy | 53 of 216 league picks collapse; original-owner identity discarded before the trade calculator (W08-F005) | C6 | — | **L** | KEEP — EXISTING, REPAIR/COMPLETE |
| 2.8 | **2028/2029 future-pick valuation** | Price far-future picks instead of dropping them | Existing, partial | **SUPERSEDED 2026-08-14 — this row's posture is no longer the requirement.** Measured on the live board: 2026 carries 72 slot rows + 18 tier rows, 2027 and 2028 carry 18 tier rows each, and 2029 IS priced but **synthetically** — a verbatim value clone of the 2028 tier rows × 0.53, allowlisted past the single-source gate by name. 2030+ is absent entirely. The requirement is now that **every valid supported pick through 2029 carries a finite, non-missing canonical value** with provenance and uncertainty (`docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` §10, manifest `C1-PICK-01`). Missing still never becomes zero — the replacement is a documented generic/future valuation, not a zero and not a dropped asset | D-tier | 2.7 | **M** | KEEP — EXISTING, REPAIR/COMPLETE |

| 2.9 | **Best Trade to Send Each Team** | For every other team in the league, one best mutually defensible player-only offer | New | **OWNER DECISION 2026-08-14: BUILD.** No dedicated surface exists — zero hits repo-wide. Nearest machinery (the finder's per-opponent iteration, suggestions' fit labels) ranks a global list. Hard rules: canonical WIN for us, opponent EVEN-or-better on KTC or IDP TC with whole-package **native** coverage; missing/unsupported/imputed assets cannot create a fake opponent win; honest no-result; ranked for mutual defensibility, not maximum exploit; recommendation only, never a silent send. **Topology superseded 2026-08-14 (#841/#842): `no draft picks` and exact-equal-player-count are WITHDRAWN** — picks are valid when posture makes them mutually beneficial, and player counts may differ by at most one (`abs(players_A − players_B) <= 1`) with picks excluded from the count. Binding specs: `docs/trade/TRADE_GENERATION_PREFERENCES_AND_REFINEMENT_SPEC.md`, `docs/trade/TRADE_FINDER_POSTURE_AWARE_PICKS_ADDENDUM_2026-08-14.md`, `docs/trade/TRADE_CONTEXT_AND_TOPOLOGY_SUPERSESSION_2026-08-14.md`; backlog §2.3; manifest `C7-BEST-TRADE` | C7 | 2.2, 2.3, 2.4, 2.10, 2.11, 1.1, 1.2, 1.3, 1.5, 7.1 | **M–L** | KEEP — NEW BUILD |
| 2.10 | **Persistent personal trade protection** | One canonical user + fantasy-league scoped outgoing-protection layer that every generated trade recommendation consumes | New | **OWNER DECISION 2026-08-14: BUILD.** 0% implemented — verified by grep, no mechanism of any kind, and no request contract carries an exclusion parameter. Supports individual untouchables and NFL-team protection **without mutating canonical player data or values**. Jason's league preference: MIN players blocked **OUTGOING** while remaining valid **INCOMING** targets; team identity follows canonical current NFL team dynamically; other users unaffected; manual Trade Calculator what-if stays free-form. Extends row 1.5. Binding spec: `docs/trade/TRADE_GENERATION_PREFERENCES_AND_REFINEMENT_SPEC.md` §2–3; ledger row 103; manifest `C3-CON-02` | C3 | 1.5, 2.11 | **M** | KEEP — NEW BUILD |
| 2.11 | **Generated-package LOCK / EXCLUDE refinement** | Two per-player refinement controls on every generated package, applied during generation | New | **OWNER DECISION 2026-08-14: BUILD.** Absent. LOCK requires the player in the next regeneration; EXCLUDE forbids him. Mutually exclusive per player; multiple constraints allowed; **generation constraints, not post-filters**; state persists through regeneration and ordinary refresh until explicitly cleared; a temporary EXCLUDE never silently becomes a permanent untouchable; persistent protection outranks temporary refinement; parent hard rules never weaken — if constraints make a qualifying package impossible, show **No qualifying trade found under current constraints**. ONE constraint owner consumed by all eight generated-trade surfaces. Binding spec: `docs/trade/TRADE_GENERATION_PREFERENCES_AND_REFINEMENT_SPEC.md` §5–6; ledger row 104; manifest `C3-CON-03` | C3 | 2.10, 2.2, 2.3, 2.4 | **M** | KEEP — NEW BUILD |

| 2.12 | **Competitive Posture (#840)** | Classify each team as PUSH / RETOOL / REBUILD / HOLD from canonical evidence | New | **OWNER DECISION 2026-08-14: BUILD.** Absent. Derived from Team Strength, Meaningful Roster Core, age/value construction, playoff and championship probability, season timing and pick ownership. Consumed by Analyze Trade and the posture-aware generator; explained, never asserted. Binding spec: `docs/trade/ANALYZE_TRADE_COMPETITIVE_POSTURE_ADDENDUM_2026-08-14.md`; manifest `C7-POST-01` | C7 | 1.1, 1.2, 1.6 | **M** | KEEP — NEW BUILD |
| 2.13 | **Use Team Context toggle (#842)** | One shared control across Trade Finder and Analyze Trade, ON by default | New | **OWNER DECISION 2026-08-14: BUILD.** Absent. ON consumes the full team-aware stack; OFF is a clearly labelled **Asset-Only** analysis that must not consume team-specific evidence — while still using canonical league-format-aware asset value, package/VA math, external evidence, intrinsic age, pick value, uncertainty and liquidity. **OFF removes team context, not league-format valuation.** Never silently switch ON to OFF when context is missing; mark the affected dimensions unavailable. Binding spec: `docs/trade/TRADE_CONTEXT_AND_TOPOLOGY_SUPERSESSION_2026-08-14.md`; manifest `C3-CTX-01` | C3 | 2.12, 1.1, 1.2 | **M** | KEEP — NEW BUILD |
| 2.14 | **Roster capacity / forced-drop trade analysis (#843)** | Evaluate a trade against the final legal post-trade roster, not the intermediate over-limit state | New | **OWNER DECISION 2026-08-14: BUILD.** Absent. `before → apply → capacity/overage → required cleanup → apply optimal cleanup → rerun roster intelligence → evaluate`. Forced-drop cost uses canonical dropability and the true final roster marginal effect, **never `package delta − lowest raw player value`**. Picks do not consume an active spot. Preserve uncertainty when cleanup options are close. Binding spec: `docs/trade/ROSTER_CAPACITY_FORCED_DROP_TRADE_ANALYSIS_ADDENDUM_2026-08-14.md`; manifest `C3-CAP-01` | C3 | 1.3, 1.4, 2.13 | **M** | KEEP — NEW BUILD |

---

## 3. Waivers, FAAB and draft

| # | Feature | Purpose | New/Existing | Current status at HEAD | Phase | Deps | Scope | Classification |
|---|---|---|---|---|---|---|---|---|
| 3.1 | **FAAB recommendations** | Separate objective ceiling (what a player is worth) from recommended bid (what this team should bid) | Existing, rebuilt | `src/trade/faab_engine.py` is a full two-layer model with config, history and backtest. Registry's saturation/monotonicity findings (W11-F003/F004) **predate the rewrite and need re-measurement, not repair-by-assumption** | D4 | — | **M** | KEEP — EXISTING, REPAIR/COMPLETE |
| 3.2 | **FAAB league context panel** | Show league budget and typical winning bids beside the bid | Existing | **W11-F006 repaired this session** — it unwrapped a key the backend never sends, so real numbers rendered as em-dashes | — | — | S (done) | ALREADY COMPLETE — VERIFY ONLY |
| 3.3 | **Perfect Waivers** | Best *combination* of adds and drops for the whole roster, with a stop rule and soft positional constraints — not "who is the best free agent" | New | Does not exist. Primitives do: the draft optimizer's k-decomposition, ECC ladder and waiver ladder are directly reusable with FAAB as the budget | D5 | C1, 1.4 | **L** | KEEP — NEW BUILD |
| 3.4 | **Expanded waiver drop candidates** | Stop pairing every add with the same lowest-valued player | Existing, defective | Current pairing is naive; correct answer is the matching problem in 1.4 | D5 | 1.4 | **S within D5** | KEEP — EXISTING, REPAIR/COMPLETE |
| 3.5 | **Perfect Draft** | Which *combination* of rookies a budget should buy | Existing, live | Full budget-knapsack optimizer with displacement, cut ladder, confidence and live updating. **The registry calls this "Missing" (W10-F003) — that is stale**; documented at length in CLAUDE.md and present in `src/draft/` + `frontend/lib/perfect-draft.js` | — | — | S (verify) | ALREADY COMPLETE — VERIFY ONLY |
| 3.6 | **Perfect Draft pre-auction snapshot** | Capture the pre-draft board so the optimizer can ever be backtested | Existing, unrun | `scripts/backtest_perfect_draft.py --record-snapshot` exists and exits 2 without data. **One-shot and unrecoverable — must run on prod before the 2026 rookie auction** | D6 | prod access | **S (ops)** | KEEP — EXISTING, REPAIR/COMPLETE (time-critical) |
| 3.7 | **Draft bid respects remaining budget** | Stop telling a manager with $4 left to "win at $37" | Existing, defective | W10-F001 open | D-tier | — | **S** | KEEP — EXISTING, REPAIR/COMPLETE |

---

## 4. Market intelligence

| # | Feature | Purpose | New/Existing | Current status at HEAD | Phase | Deps | Scope | Classification |
|---|---|---|---|---|---|---|---|---|
| 4.1 | **Consensus Edge** | Where our model disagrees with the market, with component-level explainability | Existing, half-wired | `src/consensus_edge/` (~17 modules) + `/consensus-edge` page. Identity join fails (W14-F001); flag gated behind an ADR-023 quality gate. Spec requires: global component failure must not become zero for every player, weights renormalize, score/coverage/confidence stay distinct | E1 | — | **M** | KEEP — EXISTING, REPAIR/COMPLETE |
| 4.2 | **Central Buy/Sell Tracker** | One reconciled buy/sell verdict per player, replacing scattered emitters | New | **22 label emitters at HEAD** (registry recorded 16), ~14 reachable, 5 competing threshold sets, nothing reconciling them (W12-F003) | E2 | 4.1 | **XL** | KEEP — NEW BUILD |
| 4.3 | **Homepage Buy/Sell ticker** | Surface the canonical verdicts on the landing page | Existing, wrong source | `frontend/components/terminal/MarketTicker.jsx` exists and is live; must consume 4.2 rather than its own algorithm. Accessibility (touch/keyboard/screen-reader/reduced-motion) required. **Owner rule:** BUY items may be global; SELL items must be limited to players rostered by the selected fantasy team | E2 | 4.2 | **S** | KEEP — EXISTING, REPAIR/COMPLETE |
| 4.4 | **Sharp Tracker** | What proven-sharp managers are buying and selling | Existing, slow | Live at `/market/sharp-tracker`. Cohort recomputed per request; no memoization (W15-F017) | E3 | — | **M** | KEEP — EXISTING, REPAIR/COMPLETE |
| 4.5 | **Sharp Roster Percentage** | What share of sharp rosters own each player | Existing | Live at `/market/sharp-roster-percentage` with methodology doc and validation script | E3 | — | S (verify) | ALREADY COMPLETE — VERIFY ONLY |
| 4.6 | **Manager-level Sharp concentration** | Stop one manager's five teams reading as five independent opinions | Existing, missing field | No per-player manager concentration published (W15-F009, P1) | E3 | 4.5 | **M** | KEEP — EXISTING, REPAIR/COMPLETE |
| 4.7 | **Sharp event ledger** | One ledger for trades/waivers/adds/drops/drafts, deduped within 7/14/30-day windows | Existing, narrowed | `src/intel/platform_ledger.py` exists but `query_movements` defaults to `tx_type='trade'` only, so adds/drops never surface (W15-F013) | E3 | — | **M** | KEEP — EXISTING, REPAIR/COMPLETE |
| 4.8 | **Insider Trading / cross-league ownership** | What my league-mates own and do in *other* leagues | Existing | Live at `/league/insider-trading`, backed by `src/intel/`. Surfaces its own limits inconsistently (W29-F003) | F | 4.7 | **S** | KEEP — EXISTING, REPAIR/COMPLETE |

---

## 5. Podcast intelligence

Entirely greenfield: **no podcast, transcript, episode or analyst-take code or schema exists
anywhere in the tree.** The specification devotes ~28 sections to it. It is the single largest
build in the engagement and the most external-dependency-heavy (65 submitted feeds, transcript
providers, LLM extraction, cost control, legal/access constraints).

**OWNER DECISION 2026-08-11: KEEP the complete vision, STAGED after the core foundations.** Not
removed, not deferred indefinitely, and **not started during Phase B**. Build in this order when
its dependencies are ready — the numbering below maps to the owner's stages:

1. canonical source registry (shows, submitted entries, aliases, network relationships,
   duplicate feeds; the unresolved entry stays unresolved rather than guessed)
2. episode discovery (stable IDs/GUIDs, publication time, metadata, dedup, freshness window)
3. transcript acquisition (official → publisher → legitimate provider/API → official YouTube →
   permitted audio transcription → unavailable/retry; **never** bypassing paywalls or access
   controls)
4. canonical analyst/speaker identity (aliases, affiliations, repeat guests, one analyst across
   several shows, network dependence)
5. structured actionable dynasty-take extraction — transaction intent, not sentiment, with
   NO SIGNAL common ("I like him" → NO SIGNAL; "buying everywhere" → BUY; "great player, too
   expensive" → SELL; "a second not a first" → CONDITIONAL BUY; "contender hold, rebuilder sell"
   → CONTEXTUAL; "start him this week" → NO DYNASTY SIGNAL)
6. deduplication and independence (same analyst on several shows, syndicated duplicates, repeated
   clips, network correlation, aliases, reposts must not read as independent opinions)
7. seven-day consensus over unique analysts/shows, independence, diversity, conviction,
   confidence, price, conditionality and recency — never raw mention count
8. product surfaces (player profiles, selected-team intelligence, team pages, buy/sell,
   news/Analyst Pulse with factual news clearly separate)
9. one bounded ranking input for the whole ecosystem — not 65 source weights; missing podcast
   information is neutral
10. personalized team podcast from structured takes (rostered players, trade targets, weaknesses,
    waiver opportunities, market movement) — never raw transcript concatenation, with
    traceability back to source takes

All seven rows below are **KEEP — NEW BUILD, staged per the owner decision above**, and none
begins during Phase B.

| # | Feature | Purpose | New/Existing | Current status | Phase | Deps | Scope | Classification |
|---|---|---|---|---|---|---|---|---|
| 5.1 | **Podcast source registry** | Canonical show identity for the 65 submitted entries, incl. alias/duplicate resolution and one unresolved entry that must stay unresolved | New | Nothing | E6 | — | **M** | KEEP — NEW BUILD |
| 5.2 | **Episode discovery + transcript acquisition** | Find episodes, get transcripts through a provider fallback chain, without bypassing paywalls or access controls | New | Nothing | E6 | 5.1 | **L** | KEEP — NEW BUILD |
| 5.3 | **Take extraction** | Turn transcript into structured dynasty takes where NO SIGNAL is the common outcome; redraft/DFS/betting must not become dynasty signals | New | Nothing | E6 | 5.2 | **XL** | KEEP — NEW BUILD |
| 5.4 | **7-day podcast consensus** | One player-level signal weighted by independence — not raw mention counts, not one analyst repeating himself | New | Nothing | E6 | 5.3 | **L** | KEEP — NEW BUILD |
| 5.5 | **Personalized team podcast** | A generated audio/script brief for the selected roster | New | Nothing | E6 | 5.4 | **L** | KEEP — NEW BUILD |
| 5.6 | **Podcast on player / team / news surfaces** | "Analyst Pulse" beside factual news, kept visibly separate from fact | New | Nothing | E6 | 5.4 | **M** | KEEP — NEW BUILD |
| 5.7 | **Bounded podcast ranking input** | All podcast intelligence contributes ONE modest, confidence-aware signal — never 65 ranking sources | New | Nothing | E6 | 5.4 | **M** | KEEP — NEW BUILD |

The staging is what makes this safe: it is the only major area with zero existing foundation, and
every other product in this inventory is independent of it, so ordering it last costs nothing
elsewhere.

---

## 6. League surfaces and history

| # | Feature | Purpose | New/Existing | Current status at HEAD | Phase | Deps | Scope | Classification |
|---|---|---|---|---|---|---|---|---|
| 6.1 | **Playoff odds** | Chance each team makes/wins the playoffs | Existing, duplicated | **Two engines feeding the same `/league` tab, disagreeing on league structure** (7 vs 6 playoff spots) — W30-F001 | F1 | — | **M** | KEEP — EXISTING, CONSOLIDATE |
| 6.2 | **Power Rankings** | Rank the 12 teams — **a distinct product from Team Strength** (owner ruling: Team Strength may become one input, but they do not merge) | Existing, duplicated | Two engines ranking the same league differently, 10 teams vs 12 (W30-F003) | F1 | 1.1 optional | **M** | KEEP — EXISTING, CONSOLIDATE |
| 6.3 | **Franchise / ownership history** | All-time records that do not erase franchises | Existing, defective | A hardcoded retired-owner list erases 2 of 10 2024 franchises from every all-time aggregate; history payload self-contradicts (W19-F001/F002) | F2 | — | **M** | KEEP — EXISTING, REPAIR/COMPLETE |
| 6.4 | **Public league pages** | Standings, champions, records, rivalries, drafts, trades, recaps | Existing, broad | Extensive: `/league` plus franchise, rivalry, weekly, articles, activity routes | F | — | S–M | KEEP — EXISTING, REPAIR/COMPLETE |
| 6.5 | ~~**Money / Constitution / League Media**~~ | Public surfaces for dues, rules and league media | New | Do not exist (W19-F007). **OWNER DECISION 2026-08-11: REMOVED from this engagement's product scope.** No implementation time during this master pass; may be reconsidered as a future project. Must not remain an unresolved defect, blocker, backlog requirement or Phase F obligation. This is a scope decision only — no existing working code is to be deleted for it | ~~F~~ | — | ~~L~~ | **REMOVE — OWNER DEFERRED OUT OF THIS ENGAGEMENT** |
| 6.6 | **Universal Player Profile** | One canonical page per player: identity, value, history, intelligence, performance, roster context, news | New (as canon) | **No universal profile route exists.** Only `/league/player/[playerId]` (public-league scoped) and `/players/compare`. Player clicks do not route to one canonical profile. Owner-approved expansion: consume one canonical player intelligence/news feed spanning Podcast Intelligence, future YouTube Intelligence and all canonical fantasy-news pools, with fact/opinion separation, provenance, freshness and dedupe | F / E6 | 7.1, 7.2, 5.x, 13.2 | **L** | KEEP — NEW BUILD |
| 6.7 | **Blended source rank** | The cross-source rank shown on comparison surfaces | Existing, working | **Stale as of 2026-08-21 (V1-98).** Was already correct end-to-end (backend computation, materializer threading, honest "—" fallback) — the "renders empty" claim was untested, not observed; live board check found 800/1109 players carrying a real value. Regression-pinned by `frontend/__tests__/components/players-compare-blended-rank.test.jsx` | F4 | — | **S** | KEEP — EXISTING, VERIFIED |
| 6.8 | **Freshness indicators** | Show how old each computed intelligence actually is | Existing, working | **V1-92, 2026-08-21:** board-level freshness is site-wide (`StaleDataBanner`, every page). The one measured gap (W08-F011 — trade builder showed no per-asset source count or confidence) is closed: `/trade` asset rows now show `sourceCount` and a `confidenceBucket`/`confidenceLabel` badge, both real backend stamps, regression-pinned | F4 | — | **S** | KEEP — EXISTING, VERIFIED |
| 6.9 | **Human review / admin controls** | Approve / suppress / annotate / roll back model and extracted intelligence | Existing, narrow | `/admin` + `/admin/sharp-identities` and `src/sharp/curated_service.py` exist — a real review layer, but scoped to sharp identities only. Spec wants it general (W23-F017) | F | 4.2, 5.3 | **XL** | KEEP — EXISTING, REPAIR/COMPLETE |

---

## 7. Value model and identity (foundations)

Not product surfaces, but every product above reads them, so a defect here is a defect everywhere.

| # | Feature | Purpose | New/Existing | Current status at HEAD | Phase | Deps | Scope | Classification |
|---|---|---|---|---|---|---|---|---|
| 7.1 | **Canonical player identity** | One internal id joining Sleeper / KTC / IDP / news / stats, with UNRESOLVED as a real state | Existing, defective | W06 batch open: overrides lose to exact-id, `SleeperId` column unseen, near-name detector structurally unable to fire, ghost rows on the live board | B5 | — | **M** | KEEP — INFRASTRUCTURE/FOUNDATION |
| 7.2 | **Hill curve / percentile→value** | Convert rank to value | Existing, defective | **B1 investigated this session, not implemented.** Fit and serve use different denominators; error is per-scope: OFFENSE +8→25%, GLOBAL +6→14%, **IDP +14→34%**. Non-uniform scope-dependent distortion of the ladder | B1 | — | **L** | KEEP — INFRASTRUCTURE/FOUNDATION |
| 7.3 | **IDP valuation** | Value defenders correctly from dedicated sources | Existing, defective | W02-F001 (percentile/master mismatch — same root cause family as 7.2), W02-F002 (Hampel ejects the IDP anchor 29.4% of the time) | B2, B3 | 7.2 | **L** | KEEP — INFRASTRUCTURE/FOUNDATION |
| 7.4 | **Confidence buckets** | Say how trustworthy a value is | Existing, inverted | **FIXED — B11 (#832/#833/#834).** Confidence is now a five-axis evidence gate (independence, coverage, freshness, applicability, agreement) whose overall level is the WEAKEST axis, owned by `src/api/confidence.py`. The spread statistic that produced this defect is retired. *Residual: naming only — 24 priced pick rows still carry the label `"none" / "None — unranked"`; manifest `C1-CONF-01`.* Historical text: "Bucket rises when sources disappear (W03-F004)" | B11 | — | **M** | KEEP — INFRASTRUCTURE/FOUNDATION |
| 7.5 | **Canonical value scale (1–9999)** | Define what the product scale means and where it applies | Existing, undefined | **FIXED — B9a (#824) and #822.** `apply_valuation_factors` is deleted, the league-aware methodology was evaluated and rejected for canonical promotion, and the 1–9999 scale is enforced by `tests/api/test_canonical_value_scale_contract.py`. Historical text: "Overlay has no clamp; live league-adjusted values exceed 9,999 (e.g. 10234)." **OWNER DECISION 2026-08-11, resolved:** final canonical **individual player and draft-pick** values are a **1–9999 product scale**. Raw provider values keep their native units (0–100, ranks, dollars, 0–9999) and must NOT be mutated to force the range. Internal/intermediate maths may exceed 9999 where useful. **Aggregates are NOT capped** — Team Strength, package totals, roster/portfolio totals and other multi-asset sums may exceed 9999 and must not be clamped merely because individual assets are bounded. B9 must determine WHY league-adjusted individual values currently exceed the range and establish defensible normalization; a bare `min(value, 9999)` is explicitly forbidden where it would compress elite assets into ties, destroy ordering, mask a double application, or hide a scaling defect. Preserve monotonic ordering and elite-end separation | B9 | — | **M** | KEEP — INFRASTRUCTURE/FOUNDATION (decision resolved) |
| 7.6 | **Source independence / anti-double-counting / leave-one-out** | Stop comparing KTC against a consensus that contains KTC | Existing, circular | **FIXED — B10 (#825/#827/#831).** 21 source keys collapse to 13 provider families, one vote each; the market gap no longer measures retail against itself. Historical text: "W12-F008: KTC sits on both sides of its own comparison; a leave-one-out diagnostic exists but is not used in production" | B10 | — | **M** | KEEP — INFRASTRUCTURE/FOUNDATION |
| 7.7 | **Scoring-profile handling** | Two leagues share rankings only if they genuinely share scoring | Existing, hand-typed | `scoringProfile` is a typed label, not derived from scoring settings (W18-F001) | B6 | — | **M** | KEEP — INFRASTRUCTURE/FOUNDATION |
| 7.8 | **League-config consistency** | One canonical owner of league settings | Existing, mostly good | `league_registry` is canonical; residual drift in comparison config and per-league roster shapes (W18-F005/F011) | F3 | 7.7 | **S–M** | KEEP — INFRASTRUCTURE/FOUNDATION |
| 7.9 | **Realized scoring correctness** | Our points match the league host's | Existing, defective | Disagrees with the host on 36% of player-weeks — renamed nflverse columns and missing reception bands (W18-F003). **Deadline: NFL week 1** | B7 | — | **M** | KEEP — INFRASTRUCTURE/FOUNDATION |
| 7.10 | **Historical value snapshots** | A per-player value history that reconstruction can rely on | Existing, thin | `exports/archive/` starts 2026-07-14; `rank_history.jsonl` accrual is prod-only and unverified from here | C4 | — | **M** | KEEP — INFRASTRUCTURE/FOUNDATION |
| 7.11 | **Acquisition / holding-period history** | What each rostered player was worth when acquired, what was paid, how long held, across re-acquisitions | New | Does not exist. Sleeper transactions are fetched today only for FAAB history. **Provenance must distinguish RECORDED / HISTORICAL SNAPSHOT / RECONSTRUCTED / UNAVAILABLE, and never use a future snapshot as historical truth** | C3 | 7.10 | **L** | KEEP — NEW BUILD |
| 7.12 | **Model provenance stamps** | Every material number says which model, params and as-of produced it | Existing, partial | BDVM stamps well; the main board does not (W04-F011) | C | — | **M** | KEEP — INFRASTRUCTURE/FOUNDATION |

---

## 8. BDVM, news, notifications

| # | Feature | Purpose | New/Existing | Current status at HEAD | Phase | Deps | Scope | Classification |
|---|---|---|---|---|---|---|---|---|
| 8.1 | **BDVM fundamentals** | Projection-driven fundamental value, independent of market | Existing, live | `/bdvm` + endpoints, flag ON. Open: drops six reception yardage-band rules so WR fundamentals are understated 19.7% (W13-F001); signal layer saturates at 81.5% STRONG_SELL (W13-F003) | E | 7.9 | **M** | KEEP — EXISTING, REPAIR/COMPLETE |
| 8.2 | **BDVM performance** | Stop 30-45s responses | Existing, improved | 4-entry LRU cache and the discarded-nflverse-fetch fix are already at HEAD. Remaining: no stampede protection, no HTTP cache headers, cold recompute straddles the 30s bridge budget | G5 | — | **S** | KEEP — EXISTING, REPAIR/COMPLETE |
| 8.3 | **News → player intelligence** | Attach news to the right player and the right meaning | Existing, defective | A contract-extension headline multiplies value by 0.96 via the injury path (W21-F001); terminal news filters by fantasy-team name against player names (W21-F003) | E4 | — | **S each** | KEEP — EXISTING, REPAIR/COMPLETE |
| 8.4 | **Analyst opinion vs fact separation** | Never present analyst opinion as objective fact | New (partly) | BDVM's news→events lane already models this posture (speculation confidence can widen σ but never move a mean). Not generalized to display surfaces | E4, 5.6 | 5.3 | **M** | KEEP — EXISTING, REPAIR/COMPLETE |
| 8.5 | **Notification / signal hygiene** | One alert per fact per player | Existing, defective | Three independent email detectors can alert on the same player the same day (W12-F006); cooldown keyed on rule tag so it never engages (W12-F005) | E5 | — | **S–M** | KEEP — EXISTING, REPAIR/COMPLETE |

---

## 9. Performance, mobile, platform

| # | Feature | Purpose | New/Existing | Current status at HEAD | Phase | Deps | Scope | Classification |
|---|---|---|---|---|---|---|---|---|
| 9.1 | **Rankings pagination / windowing** | Stop rendering ~1,100 rows and 34k DOM nodes | Existing, **shipped** | **CORRECTED 2026-08-25 (Integration; the previous cell was stale in both claims):** windowing IS implemented and `VERIFIED` on `main` since `V1-106` (`a9136e13e`) — "no windowing implementation exists" was false at HEAD. The old "22→59.5 FPS" figure is also retired: #760's first harness paced its own scroll with `setTimeout(16)`, so 59.5 was a property of the measuring loop, retracted by the FPS harness's own header. Cite `V1-106`'s own evidence for current behavior, not this row's history | G3 | — | **M–L** | KEEP — EXISTING, SHIPPED (V1-106) |
| 9.2 | **Compact-view payload** | Phones should receive less, not more | Existing, inverted | The "compact" mobile view still ships the legacy players dict, so it is **larger** than the desktop array view (W26-F001) | G4 | — | **S–M** | KEEP — EXISTING, REPAIR/COMPLETE |
| 9.3 | **Mobile optimization** | Real 390px usability | Existing, partial | Genuine infrastructure (viewport export, ~20 breakpoints, 3 mobile Playwright projects). Open: `/trade` sticky bar clipped by the FAB, `/draft` panel refuses to stack, touch-target density (W26-F015/F017) | G6 | 9.2 | **M** | KEEP — EXISTING, REPAIR/COMPLETE |
| 9.4 | **E2E diagnostics** | Make the next failure self-describing (endpoint URL attribution, no refuted comments) | Existing, missing | Console capture stores message text but not `msg.location().url`. Low-risk, no production behavior change | G1a | #762 claim clearing | **S** | KEEP — EXISTING, REPAIR/COMPLETE |
| 9.5 | **E2E root cause / bridge stall repair** | Fix the actual backend stall behind the rotating flake | Existing, unproven | PR #762 has a convincing unmerged diagnosis. **Must be independently reproduced before any root-cause claim** (owner directive) | G1b | 9.4 | **M** | KEEP — EXISTING, REPAIR/COMPLETE |
| 9.6 | **Security repairs** | Redirect sanitization, trusted-proxy rate limiting, login throttle, admin-gated mutations | Existing, defective | Open: XFF trusted unvalidated (W22-F002), no login throttle (W22-F003), unguarded mutation routes (W22-F005/F007) | B8 | — | **S–M** | KEEP — INFRASTRUCTURE/FOUNDATION |
| 9.7 | **Unauthenticated draft-capital redaction** | Do not serve internal pick dollar values to anonymous callers | Existing, exposed | W00-F001. **Owner decided 2026-08-11: redact for unauthenticated**, reusing the existing `rookieBoardValue` redaction posture | B8 | 9.6 | **S** | KEEP — EXISTING, REPAIR/COMPLETE |

---

## 10. Adaptive / ML

| # | Feature | Purpose | New/Existing | Current status at HEAD | Phase | Deps | Scope | Classification |
|---|---|---|---|---|---|---|---|---|
| 10.1 | **Hill curve refit lifecycle** | Fit → backtest → validate → promote → monitor → rollback, human-gated | Existing | `src/model_registry/` produces challengers and scores them against holdout boards; **production constants move only via human-run `promote` + `apply` (ADR-008)** | B1 | 7.2 | — | KEEP — INFRASTRUCTURE/FOUNDATION |
| 10.2 | **Adaptive source weighting** | Learn which sources predict best | New | Does not exist. **OWNER DECISION 2026-08-11: KEEP in the long-term vision but DO NOT ACTIVATE NOW.** Foundational phases continue on static, explicit, defensible weights. Nothing may automatically change production weights off short samples — "five good weeks from Source X, therefore double its weight" is exactly the forbidden behavior. Before any adaptive weight touches production: accumulate history → define outcomes → leakage-safe splits → train → backtest → out-of-sample evaluation → stability measurement → minimum-sample thresholds → beat the static baseline → human approval → deploy behind a model version/flag → monitor → support rollback | G | 5.4, 7.10 | **L** | KEEP — FUTURE / EVIDENCE-GATED |

---

## 11. Owner decisions — all resolved 2026-08-11

Nothing in this inventory carries NEEDS OWNER DECISION. These are binding and should not be
re-asked unless new repository evidence makes the requested behavior impossible or materially
unsafe, in which case record the contradiction rather than inventing an answer.

| # | Item | Decision | Final classification |
|---|---|---|---|
| 2.5 | **Golden Upgrades** | KEEP as a distinct user-facing surface, but as a *consumer* of canonical infrastructure — never a second trade/arbitrage/value engine. Distinct presentation, not distinct methodology | KEEP — EXISTING, REPAIR/COMPLETE |
| 2.6 | **Package Builder** | BUILD it. Same canonical package-generation engine as Finder/Suggestions; return-position constraints applied during generation; respects exclusions, ownership, package adjustment, roster impact, Team Strength/Weakness, pick identity, unpriced state | KEEP — NEW BUILD |
| 6.5 | **Money / Constitution / League Media** | REMOVED from this engagement's scope. Not a defect, blocker, backlog item or Phase F obligation. May return as a future project. No existing working code is to be deleted for it | REMOVE — OWNER DEFERRED OUT OF THIS ENGAGEMENT |
| 7.5 | **Canonical value scale** | Individual player and pick values are a **1–9999 product scale**. Raw provider units stay native. Intermediate maths may exceed it. **Aggregates (Team Strength, package/roster/portfolio totals) are NOT capped.** B9 must find the true cause of >9999 league-adjusted values and normalize defensibly — a bare `min(v, 9999)` is forbidden where it would tie elite assets, destroy ordering, mask double application or hide a scaling defect | RESOLVED — B9 unblocked |
| 10.2 | **Adaptive source weighting** | KEEP in the vision, DO NOT ACTIVATE. Static explicit weights until the full evidence lifecycle (history → outcomes → leakage-safe splits → train → backtest → out-of-sample → stability → minimum samples → beat static baseline → human approval → flagged deploy → monitor → rollback) is satisfied | KEEP — FUTURE / EVIDENCE-GATED |
| 2.2 | **W08-F003 / KTC value adjustment** | KEEP exact KTC parity as a secondary/advisory market-consolidation metric. Do not silently fix or clamp its genuine behavior. **Do not claim we already have a superior proprietary replacement.** The canonical site trade architecture remains separate and should combine canonical asset/package equity with true roster marginal impact; determine through evidence whether a second proprietary scalar VA is needed at all | KEEP — EXISTING KTC PARITY + EVIDENCE-GATED CANONICAL METHODOLOGY |
| §5 | **Podcast Intelligence** | KEEP the complete vision, STAGED after core foundations, in the 10-stage order recorded in §5. Not started during Phase B | KEEP — NEW BUILD (staged) |
| 0.1 | **Schedule Generator** | REMOVED permanently from this engagement. Must not be reintroduced as generator, optimizer, API, page, export or backlog item, and must not be resurrected by later plan regeneration because an old master prompt contained it | REMOVE — OWNER DOES NOT WANT / NOT APPLICABLE |

---

## 12. Competitive expansion — OTC Fantasy + Play For Keeps

> **`docs/CE_REGISTRY.md` is canonical for CE identifiers as of 2026-08-14.** This table mirrors it. The
> registry now runs CE-01…CE-29; CE-22…CE-29 were minted to resolve a collision in which 18 of 22 identifiers
> named two different capabilities.

**OWNER DECISION 2026-08-11: KEEP the competitive expansion as authoritative future product
scope.** These capabilities were selected after a feature-by-feature review of OTC Fantasy and
Play For Keeps. They are **not permission to clone competitor implementation**, and they are not
permission to interrupt foundational correctness work. The product strategy is to combine the
strongest workflow/execution ideas from OTC, the strongest market/manager-intelligence ideas from
Play For Keeps, and this platform's deeper roster-aware decision intelligence.

**Implementation status at the time this section was added:** scope is approved and must not be
forgotten, but CE product-code implementation is not yet authorized. The later reconciliation pass
must map each CE item to actual repository owners and phase dependencies before implementation.
Existing canonical systems win over creating parallel engines.

| ID | Feature | Purpose | New/Existing | Current status | Dependency placement | Scope | Classification |
|---|---|---|---|---|---|---|---|
| CE-01 | **Market Trade Ledger / Trade Database** | Canonical broad-market ledger of real completed dynasty trades powering searchable trade comps, Most Traded, player/pick market history and eventual independent real-trade market value | New | Approved scope; no canonical broad-market trade ledger yet. Must remain distinct from the Sharp ledger | After canonical player + pick identity; ingestion/schema prep may begin after critical foundations | **XL** | **KEEP — NEW BUILD** |
| CE-02 | **Pick Forecast** | Project each specific future pick's landing distribution, expected slot/value, confidence and volatility instead of only generic early/mid/late value | New | Approved scope; no canonical specific-pick forecast exists | After stable pick identity + Team Strength/Weakness + leakage-safe historical backtest inputs | **L** | **KEEP — NEW BUILD** |
| CE-03 | **Manager Scout / Manager Intelligence** | Canonical fantasy-behavior profile for managers: trade/pick tendencies, roster construction, cross-league ownership and negotiation-relevance signals | New | Approved scope; extends Insider Trading rather than replacing it | After canonical manager/team identity and transaction history are trustworthy | **L** | **KEEP — NEW BUILD** |
| CE-04 | **Dynasty Command Center** | Action-oriented homepage ranking what needs attention now: incoming offers, waivers, lineup issues, market/Sharp/Insider signals, pick movement and later podcast intelligence | New | Approved scope; must aggregate canonical actionable events rather than create separate logic per card | After core roster/trade/waiver/market foundations | **L** | **KEEP — NEW BUILD** |
| CE-05 | **Trade Desk** | Unified Incoming / Outgoing / Past / Completed trade workflow with canonical value, KTC advisory metric, package adjustment, roster impact, weaknesses, comps, Sharp and manager context | New | Approved scope; must consume Trade Calculator/Simulator/Package infrastructure rather than duplicate it | After canonical trade/package architecture; execution waits for CE-11 | **L** | **KEEP — NEW BUILD** |
| CE-06 | **Dynasty Portfolio / Exposure** | Cross-league player, NFL-team, position, age, contender/rebuild and draft-pick exposure with value-weighted drilldowns | New | Approved scope; descriptive by default, not automatic diversification judgment | After multi-league identity/ownership foundations | **M** | **KEEP — NEW BUILD** |
| CE-07 | **Market ADP** | One canonical time-series service for rookie ADP, startup ADP and optional best-ball ADP, with provenance, samples and trends | New | Approved scope; do not build separate ingestion systems per draft type | After canonical identity; may feed Perfect Draft/Profile/Market Pulse later | **L** | **KEEP — NEW BUILD** |
| CE-08 | **Projections & Stats Hub** | Canonical sortable projections and realized-stat research surface feeding profiles, BDVM, matchup intelligence and replacement value | Existing foundations / new surface | Approved scope; must reuse canonical scoring/projection infrastructure rather than create another scoring system | After scoring/projection correctness foundations | **M** | **KEEP — EXISTING FOUNDATION / NEW SURFACE** |
| CE-09 | **League Replacement Value / PAR / WAR** | League-specific production scarcity: projected/realized points above replacement, defensible WAR-style outputs and Value/PAR | New | Approved scope; analytical lens only, never a replacement for canonical dynasty value or Team Strength | After canonical league settings + scoring + projections | **M** | **KEEP — NEW BUILD** |
| CE-10 | **Share Renderer / Team Cards** | Reusable export layer for Team, Anonymous Team, Trade, Player and Power Rankings cards in shareable layouts | New | Approved scope; one renderer, not bespoke screenshot code per page | After underlying surfaces stabilize | **M** | **KEEP — NEW BUILD** |
| CE-11 | **Sleeper Action Gateway** | One authenticated/authorized mutation boundary for sending/responding to trades, setting lineups, waivers and supported draft actions | New | Approved scope; recommendation and execution must remain separate; no page-specific raw Sleeper write logic | Only after core decision products are correct/stable and security/auth architecture is ready | **L** | **KEEP — NEW BUILD** |
| CE-12 | **Lineup Intelligence** | User-facing lineup optimization over existing assignment primitives, beginning with max projection and later adding defensible ceiling/floor/contingency modes | Existing foundations / new surface | Approved scope; must reuse lineup solver | After projection/lineup infrastructure; execution later through CE-11 | **M** | **KEEP — EXISTING FOUNDATION / NEW SURFACE** |
| CE-13 | **Draft Room** | Unified live draft workspace combining Perfect Draft, rookie rankings, ADP, profiles, Team Weakness, pick trades and real trade comps | Existing foundations / new surface | Approved scope; Perfect Draft remains the optimizer and is embedded, not rebuilt | After draft + ADP + trade/pick foundations | **M** | **KEEP — EXISTING FOUNDATION / NEW SURFACE** |
| CE-14 | **Market Pulse** | Market dashboard for Most Traded, Most Traded Picks, ADP/value risers/fallers and broad-market vs Sharp divergence | New surface over CE-01/07 | Approved scope; derives from canonical ledgers/history rather than a new transaction source | After CE-01 + CE-07 + Sharp ledger | **M** | **KEEP — NEW SURFACE OVER CE-01/07** |
| CE-14A | **Personal Rankings Overlay** | Private user ordering shown beside Site/KTC/Market/Sharp/Podcast/ADP ranks without mutating canonical values | New | Approved scope | After canonical rankings/profile foundations | **M** | **KEEP — NEW BUILD** |
| CE-15 | **Portfolio Trade Campaign** | Find plausible acquire/sell packages across multiple leagues with owner fit, cooldown/duplicate protection and required human review | New | Approved future scope; no automatic mass-spam default | Requires multi-league Portfolio + Manager Intelligence + Trade Finder/Package Builder + CE-11 | **L** | **KEEP — FUTURE** |
| CE-16 | **Trade Polls** | Optional community/league/shareable trade polls compared against KTC, canonical model, real comps and Sharp market | New | Optional future scope; votes are descriptive, never authoritative valuation | After Trade Desk/Share infrastructure if still desired | **S–M** | **KEEP — OPTIONAL / FUTURE** |

### 12.1 Canonical competitive-expansion owners

Do not implement the table above as 17 isolated engines. The intended reusable canonical layers are:

1. `market_trade_ledger` — broad market behavior; **separate from** the Sharp event ledger.
2. `market_adp` — rookie/startup/optional best-ball ADP observations and time series.
3. `manager_intelligence` — fantasy-behavior observations and tendencies; extends Insider Trading.
4. `projection_and_stats` — one stats/projection layer reused by profiles, BDVM, PAR and matchup tools.
5. `league_action_gateway` — all authenticated Sleeper mutations; decision plane stays separate.
6. `share_renderer` — one export/rendering layer reused across products.
7. `command_center` — one canonical actionable-event feed/ranking contract, not many homepage APIs.
8. `pick_forecast` — specific-pick probability/EV model with leakage-safe backtesting.

Existing owners remain authoritative for player identity, pick identity, league settings, canonical
value, package generation, package adjustment, trade simulation, Team Strength and Team Weakness.
Pages consume those owners; pages do not recalculate them.

### 12.2 Competitive-expansion priority after dependencies

**Tier 1:** CE-01 Market Trade Ledger / Trade Database; CE-02 Pick Forecast; CE-04 Dynasty Command
Center; CE-03 Manager Scout.

**Tier 2:** CE-06 Dynasty Portfolio; CE-07 Market ADP; CE-08 Projections & Stats Hub; CE-09
Replacement Value.

**Tier 3:** CE-05 Trade Desk; CE-11 Sleeper Action Gateway; CE-12 Lineup Intelligence; CE-13 Draft
Room.

**Tier 4:** CE-10 Share Renderer; CE-14 Market Pulse; CE-14A Personal Rankings Overlay.

**Tier 5:** CE-15 Portfolio Trade Campaign; CE-16 Trade Polls.

Tier does **not** override foundational dependency ordering. Identity/value/scoring/Team
Strength/Team Weakness/trade correctness still win over competitor parity or convenience.

### 12.3 Binding competitive-expansion methodology rules

- **Broad market != Sharps != Insider != Podcast != KTC != BDVM != canonical model.** Keep the
  observation populations distinct and document overlap/correlation before any signal enters a
  blended product.
- **Missing is never zero.** No trades, ADP, projection, manager observation or Sharp sample must
  publish as a numeric zero merely because evidence is absent.
- Real historical trade comps must use contemporaneous value provenance where available:
  RECORDED / HISTORICAL SNAPSHOT / RECONSTRUCTED / UNAVAILABLE. Never label today's value as a
  historical acquisition/trade value.
- Pick Forecast keeps **generic market value** (for example, `2027 Mid 1st`) distinct from a
  **specific-pick expected value** (for example, a named franchise's 2027 1st distribution).
- Manager Scout is fantasy-behavior analysis only; no real-world identity enrichment, financial
  profiling or psychological profiling.
- Recommendation and execution are separate planes. AI/model recommendations must never silently
  trigger Sleeper mutations.
- All new market/manager/predictive outputs require explicit freshness, sample/coverage and
  confidence semantics.
- Multi-league support must remain possible without prematurely rewriting the entire current app
  during foundational phases.

### 12.4 Competitor-parity features explicitly NOT added by this decision

The competitive review does **not** reintroduce or newly approve:

- Fantasy Schedule Generator — still permanently removed / NOT APPLICABLE.
- Full Dispersal Draft system — not approved now; future owner decision required if genuinely needed.
- Standalone competitor-copy Rookie WR model.
- Generic best-ball product suite (best-ball ADP may be an optional CE-07 data source only).
- Generic article CMS / media-company build.
- Generic podcast-hosting product; Podcast Intelligence remains the approved media strategy.
- Automatic bulk-trade spam.
- Generic community/social-network build.
- Subscription/billing platform merely for competitor parity.
- Competitor branding, copyrighted copy, proprietary code, private APIs or protected assets.

The later competitive reconciliation should create
`docs/competitive/OTC_PFK_FEATURE_AUDIT.md` and
`docs/competitive/COMPETITIVE_EXPANSION_ARCHITECTURE.md`, map every public/login-gated competitor
capability to COVERED / EXTEND / NEW / LATER / DO NOT BUILD, build the duplicate-risk and dependency
maps, and insert these CE items into the existing execution plan. **That reconciliation work must
not silently remove, rename away, or forget any CE item recorded here.**

---

## 13. Owner-approved scope reconciliation — later 2026-08-11 additions

This section is authoritative master scope. It incorporates the owner requests that were initially
recorded in `docs/OWNER_FEATURE_ADDENDUM_2026-08-11.md`, the Dynasty Daddy competitive audit,
`docs/OWNER_REQUESTED_TODO.md`, and `docs/trade/TRADE_DECISION_SYNTHESIS_PLAN_2026-08-11.md`.
These are not optional ideas merely because they arrived after the first inventory pass.

### 13.1 Additional approved features and repairs

| Ref | Feature | Binding requirement | Dependency/status | Classification |
|---|---|---|---|---|
| #782 | **YouTube Dynasty Intelligence** | Build a large dynasty-YouTube intelligence pipeline targeting roughly 50 reputable sources/channels/videos while excluding/deduping content already represented by Podcast Intelligence. Reuse canonical source/analyst identity, transcript acquisition, actionable-take extraction, NO SIGNAL, freshness, provenance and independence/correlation handling. Feed appropriate structured output into Consensus Edge/bounded intelligence, Buy/Sell, player profiles, selected-team intelligence and the personalized weekly team podcast/brief. A podcast episode uploaded to YouTube must not become another independent vote | Stage after Podcast/source-identity foundations; no Phase-B build | **KEEP — NEW BUILD (STAGED)** |
| #783 / 6.6 | **Unified Player Profile Intelligence** | Universal Player Profile must contain one useful player-specific intelligence/news feed spanning Podcast Intelligence, future YouTube Intelligence, Sleeper news, RotoWire, RotoBaller and every other canonical fantasy-news source. Use attributed excerpts, concise source cards, synthesis or a hybrid; separate fact from opinion; preserve source/as-of/provenance; dedupe syndicated/reposted content; do not republish full copyrighted articles/transcripts | Extends Universal Player Profile and canonical news/intelligence services | **KEEP — NEW BUILD / EXTEND 6.6** |
| #784 / 4.3 | **Consensus Edge / Buy-Sell homepage ticker** | Stock-market-style horizontal ticker. BUY may include relevant targets broadly. **SELL may only include players currently rostered by the selected fantasy team.** Ticker is presentation only and must read canonical persisted Buy/Sell/Consensus output; no frontend thresholds or second signal engine | After Central Buy/Sell Tracker; accessibility/reduced-motion required | **KEEP — EXISTING, REPAIR/COMPLETE** |
| #785 | **Two-TE / TE-premium valuation audit** | Deep-audit exact two-mandatory-TE scoring and value methodology. Derive league demand/FLEX/SF eligibility from canonical settings; measure TE scoring relative to WR/RB; inventory every source's base/TEP/TE++ basis; where standard+TEP boards exist measure actual rank/player-dependent uplift; remeasure KTC base→TEP/TE++ as a diagnostic; prevent native-TEP double adjustment; search whole tree for stale blanket `1.15` or duplicate premium paths; validate elite/mid/starter/TE2/fringe/deep ranges against cross-position scarcity and realized scoring. Success means evidence that values are right for this league, not merely closer to KTC | Appropriate Phase-B/league-value checkpoint after isolated B2 unless direct overlap | **KEEP — METHODOLOGY AUDIT / REPAIR** |
| #786 | **Trade Simulator NFL-team exposure** | Add value-weighted NFL-team exposure before→after a proposed trade, showing affected teams as before % → after % and percentage-point change; raw count secondary. Picks normally have no NFL-team exposure. Missing/unpriced stays explicit. This is informational only and must not influence grade, package adjustment, Team Strength or Analyze Trade unless separately authorized. Share one reusable exposure primitive with CE-06 Portfolio | After canonical roster/trade state is available | **KEEP — NEW BUILD / EXTEND TRADE SIMULATOR + CE-06** |
| #788 | **Dynasty Analyst X Feed** | Preserve long-term concept of roughly 500 reputation-curated dynasty analysts using official/authorized X integration, with cross-media analyst identity/dedupe and useful filtering. **Do not build while recurring API economics are disproportionate to the current small/private site. No scraping.** | Cost/policy gated; reconsider later | **KEEP — FUTURE / COST-GATED** |
| #789 / CE-20 | **Game Day Command Center** | Build a Sunday companion that is materially better for this league than generic Sleeper display: exact custom scoring, true entire-roster best-ball simulation, projected final-score distributions, calibrated live win probability, current score/state, likely eventual best-ball contributors, personalized owner/opponent event/news context, rooting/leverage guide, late-Sunday/Monday "what do I need?", mobile `For You | Matchup | Players | Games | News`, desktop/tablet TV mode and eventual custom-scoring play explanation where affordable event data supports it | Low-cost V1 first; dependencies: scoring correctness → canonical best-ball assignment → projection-source audit → custom-stat projection → snapshot/history → calibrated simulation → live refresh → UI. Paid second-by-second PBP optional later only if usage justifies cost | **KEEP — NEW BUILD / PLANNED PRODUCT** |
| #790 | **Monte Carlo current-HEAD methodology audit** | Revalidate complete path asset value → payload → `TradePlayer` → uncertainty band → KTC/package adjustment → correlation → simulation → symmetry/enrichment → UI. Verify TEP/IDP/pick/manual override propagation exactly once; mean preservation, side-swap symmetry, ties, seeded reproducibility, convergence and endpoint behavior. Remeasure synthetic ±15% fallback and investigate defensible player-specific uncertainty/source correlation. Monte Carlo is a value/consensus uncertainty lens, **not** literal probability the dynasty trade succeeds in real life | Next appropriate trade/model checkpoint; do not interrupt B2 | **KEEP — EXISTING, RE-AUDIT/REPAIR** |
| #791 | **Second Opinions one-glance winner tally** | Add immediate `Side A · Side B · Even · Incomplete` summary above detailed vendor rows. Count once per genuinely independent vendor/network; native coverage only for a true external vote. Rows completed with our canonical value are partial/incomplete rather than independent corroboration. Preserve coverage and margin for drilldown | Small UX addition after safe checkpoint; reuse existing per-vendor breakdown | **KEEP — EXISTING, REPAIR/COMPLETE** |
| #792 / CE-05 | **Analyze Trade canonical recommendation** | After assets are entered, one deliberate Analyze Trade action returns MAKE THE TRADE / LEAN MAKE / TOO CLOSE-DEPENDS / LEAN PASS / PASS from selected-team perspective, with confidence, strongest reasons for/against, material uncertainty/disagreement and optionally "what would change the answer." Must synthesize unique-information dimensions and lineage rather than averaging visible panels | Dependency-gated until canonical value/package/Team Strength/Weakness/roster-impact foundations and MC audit are trustworthy; `/trade` and CE-05 must consume the same decision contract | **KEEP — NEW BUILD / PLANNED DECISION PRODUCT** |

### 13.2 Game Day prediction methodology is part of the product, not an implementation detail

CE-20/#789 must model the actual league rather than inherit Sleeper's assumptions:

- every still-eligible rostered player remains in the weekly/live outcome distribution until the
  final best-ball assignment makes his contribution impossible;
- a provisionally filled lineup slot is not treated as permanently complete while bench players
  can still displace that score;
- weekly player projections must be translated through the league's complete scoring system;
- projection-provider gaps such as first downs, reception-distance/big-play bands and unusual IDP
  events must be modeled from defensible historical/conditional distributions where possible or
  remain explicitly uncertain — never silently zero;
- archive timestamped pregame and in-game predictions and measure final-score MAE/RMSE, best-ball
  assignment accuracy, Brier score/log loss where appropriate and reliability/calibration without
  temporal leakage;
- one canonical matchup-projection/win-probability owner feeds every Game Day surface;
- V1 must be useful without a commercial real-time play-by-play contract.

### 13.3 Analyze Trade unique-information architecture

Do **not** treat current trade panels as independent votes. Canonical value already contains many
external sources; Second Opinions exposes many of those same sources; Monte Carlo is centered on
canonical values; KTC VA can appear in several trade views; roster analysis also consumes canonical
values. A naïve formula such as `value + MC + second opinions + KTC VA + roster impact` can
triple-count the same evidence.

The canonical Analyze Trade contract should reason over unique-information dimensions:

1. **Canonical economic value** — one owner for player/pick/package equity.
2. **Market corroboration/disagreement** — independent external evidence, with native coverage,
   source/network lineage and imputation clearly separated; primarily confidence/explainability
   unless incremental value is proven.
3. **Uncertainty/risk** — revalidated Monte Carlo or successor around the value conclusion, usually
   a confidence/risk modifier rather than another vote for the same p50.
4. **Roster marginal impact** — true before → remove outgoing → add incoming → rerank → recompute
   meaningful Top-N groups → measure promotions/displacements → recompute Team Weaknesses and
   construction. Draft picks have zero current Team Strength contribution but retain future/asset
   value.
5. **Future/window context** — picks, age, liquidity and competitive window only where the
   canonical methodology is validated; do not stack duplicate contender classifiers.
6. **Later incremental intelligence** — real trade comps, Sharp, Insider, Consensus Edge,
   news/podcast/YouTube and Manager Scout only when freshness/independence justify inclusion.
7. **Explicit owner constraints** — untouchables/exclusions can veto or qualify a recommendation;
   do not infer hidden preferences.

Every dimension should expose direction, magnitude, confidence/coverage, provenance/freshness and
lineage/dependencies. The final result must remain explainable rather than collapse into a mystery
number.

### 13.4 KTC Value Adjustment — binding owner clarification

This supersedes any earlier wording that could be read as "we already have a better proprietary VA."

- **KEEP exact KTC VA.** The owner values it and much of the market understands it.
- KTC VA is the site's **market-parity/consolidation benchmark**, not an enemy to replace.
- Preserve exact KTC behavior when labeled KTC, including genuine non-monotonic cases; do not
  silently clamp/fix it while still calling it KTC.
- The site **has not yet proven a superior proprietary scalar Value Adjustment**.
- Do not create an "Our VA" merely because the product seems to need a second number.
- A preferred final architecture may be **canonical raw/package equity + exact KTC VA market lens
  + canonical roster marginal impact + uncertainty + independent corroboration → Analyze Trade**.
- If a proprietary scalar package premium is ever proposed, first define its target and validate
  it across 1-for-1, 2-for-1, 3-for-1, larger packages, elite consolidation/breakup, player+pick,
  pick-heavy, offense, IDP, mixed and pathological/non-monotonic cases. Benchmark against exact KTC
  VA and contemporaneous market/trade evidence. No temporal leakage and no tuning merely until
  hand-picked examples look good.
- When our eventual canonical recommendation differs from KTC, explain the reason — e.g. different
  player values, exact league scoring, Team Strength displacement, positional weakness, future
  assets or another independently justified factor.

### 13.5 Dynasty Daddy competitive additions — CE-17 through CE-21

The full evidence/implementation detail lives in
`docs/competitive/DYNASTY_DADDY_FEATURE_AUDIT.md` and
`docs/competitive/COMPETITIVE_EXPANSION_DYNASTY_DADDY_ADDENDUM.md`.
These additions are approved future scope and must be reconciled with §12, not left in a side file.

| ID | Feature | Canonical interpretation | Classification |
|---|---|---|---|
| CE-17 | **League Format / Utilization Lab** | League-specific research surface over canonical scoring/stats/replacement infrastructure: utilization, target/opportunity metrics, spike weeks and defensible WAR/WoRP/VoRP-style research without creating another scoring engine | **KEEP — NEW BUILD** |
| CE-18 | **Trade Trees / Asset Lineage** | Show how a player/pick/asset was acquired and what traded-away assets subsequently became. Must consume stable pick identity, transaction history and acquisition provenance rather than reconstructing with future data | **KEEP — NEW BUILD** |
| CE-19 | **Waiver Market / FAAB Market Ledger** | Broad-market real waiver-bid observations, claim counts/ranges and market context kept distinct from our FAAB recommendation and Sharp behavior. One market ledger, not another bidding model | **KEEP — NEW BUILD** |
| CE-20 | **Game Day Command Center** | Now elevated from a vague optional idea to the fully specified best-ball/custom-scoring Sunday intelligence console in #789/§13.2 | **KEEP — NEW BUILD / PLANNED PRODUCT** |
| CE-21 | **Dynasty Season Recap / Wrapped** | Analytical season recap: best/worst trades, waiver wins, draft hits/misses, value gains, championship run, roster evolution and shareable outputs; not gamification for its own sake | **KEEP — FUTURE / NEW BUILD** |

Dynasty Daddy also enriches existing approved features rather than creating duplicates: CE-03
manager tendencies in context; CE-04 watchlist/target alerts; CE-06 richer player/NFL-team/position/
age/stack/pick exposure and cross-league availability; CE-09 research into startability-adjusted
realized contribution; CE-11 supported waiver/lineup/draft mutations through one secure action
gateway; CE-12 schedule-aware FLEX placement, weather/status context, waiver alternatives and
projection accuracy; CE-13 live draft sync; CE-14A personal ranking import; CE-15 richer
multi-asset/FAAB campaign patterns; and Universal Player Profile historical value/ADP/stats/
started-rostered history/trade context. These are extensions of canonical owners, not new engines.

### 13.6 Immediate owner-requested live/product fixes remain binding

These are tracked in `docs/OWNER_REQUESTED_TODO.md` and are not erased simply because the feature
inventory normally excludes small defects:

- **#779** — repair the `/admin` `fmtPassExpiry` runtime crash with real-page regression evidence.
- **#780** — repair/verify configurable-hours temporary password/pass generation end to end,
  including actual authentication, expiry and revocation/fail-closed semantics.
- **#781** — Trade Calculator manual value edits must be visually silent; no yellow/badge/per-player
  override marker, one discreet top-level Reset Values control, removal clears the temporary
  override, re-adding returns to canonical value, and canonical truth is never mutated.

### 13.7 Execution ordering / scope safety

- Do not interrupt the isolated B2 IDP curve-routing work merely to implement any §13 item.
- At the next safe integration/planning checkpoint, reconcile §13 into the active dependency graph,
  canonical-owner map and phase plan.
- #790 should be the next appropriate Monte Carlo/trade-model audit; #791 is small but still waits
  for a safe checkpoint; #792 waits for canonical Team Strength/Weakness/roster-impact foundations.
- #785 belongs at the appropriate league-value/TEP checkpoint and must not be "fixed" by simply
  raising tight ends until they resemble KTC.
- #788 stays cost-gated/long-term.
- CE-17–CE-21 and all competitor enrichments remain future scope after dependencies.
- Missing is never zero. Signal lineage/independence remains mandatory. Recommendation and mutation
  planes stay separate.

---

## Not in this inventory, by design

Audit tooling and registry work, test harnesses and regression tests, CI gates, lint/format,
migrations, dependency bumps, documentation drift, and the pure-infrastructure repairs already
tracked in `docs/master-site-audit/`. Also excluded: the six pre-squash performance PRs
(#758–763), which are dispositioned in `docs/BRANCH_DISPOSITION_2026-08-11.md`.
