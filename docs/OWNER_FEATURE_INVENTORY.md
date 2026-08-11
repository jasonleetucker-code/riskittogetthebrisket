# Owner Feature Inventory

**Every user-facing feature, decision product, intelligence surface and materially new capability
the master specification / execution plan proposes to build, complete, repair, consolidate,
surface or materially change — deduplicated, classified, and reconciled against the actual
repository at HEAD.**

Built 2026-08-11 at the owner's request, as a scope-control checkpoint before any Phase B
implementation. Reconciled against BOTH the master specification and the tree — the phase-plan
bullets are **not** treated as exhaustive; several items below appear in the repo or the
specification but in no plan bullet.

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
| 1.5 | **Untouchable / excluded-player control** | Mark players that trade, waiver and draft optimizers must never propose moving or dropping | New | Does not exist (W09-F011) | D8 | D2 | **M** | KEEP — NEW BUILD |

---

## 2. Trade products

| # | Feature | Purpose | New/Existing | Current status at HEAD | Phase | Deps | Scope | Classification |
|---|---|---|---|---|---|---|---|---|
| 2.1 | **Trade calculator** | Value a proposed trade on the canonical board | Existing | Live at `/trade`. **W08-F004 repaired this session** — the search box could not find the current rookie class | — | — | S (done) | ALREADY COMPLETE — VERIFY ONLY |
| 2.2 | **Package adjustment** | One engine for consolidation premium / multi-asset discount | Existing, duplicated | KTC's published algorithm is ported in `src/trade/ktc_va.py`; a second port lives in `trade_grading.py`; `src/trade/__init__.py` monkeypatches. **OWNER DECISION 2026-08-11 (W08-F003):** KTC's non-monotonicity — where adding a positive-value asset can LOWER an adjusted side total — is **preserved exactly** when displaying the KTC-parity metric, and is never silently "fixed" or clamped. But it is **not** the canonical definition of trade value: our roster-aware, package-aware model is separate and uses our own methodology. The UI must label which is which, and KTC parity must not contaminate canonical package value, roster-aware marginal value, Team Strength/Weakness impact, Golden Upgrades, Perfect Waivers or any other decision model | C5 | — | **M** | KEEP — EXISTING, CONSOLIDATE (two clearly-separated concepts, not one merged engine) |
| 2.3 | **Trade Finder (arbitrage)** | Find trades where our board and the retail market disagree | Existing, defective | Live at `/arbitrage`. Open: no dominance pruning (W09-F012), gain not normalized by package size (W09-F002), lopsidedness ranked over mutual benefit (W09-F009) | D2 | — | **M** | KEEP — EXISTING, REPAIR/COMPLETE |
| 2.4 | **Trade Suggestions** | Roster-aware sell-high / buy-low / consolidation proposals | Existing, defective | Returns zero suggestions for 8 of 12 teams with no diagnosis (W09-F001); no DB can ever be proposed (W27-F002) | D2 | — | **M** | KEEP — EXISTING, REPAIR/COMPLETE |
| 2.5 | **Golden Upgrades** | Surface owned-player → target pairs where our model prefers the target while the market prefers what you already own, so the swap can improve the model score *and* potentially extract market value | Existing semantics, new surface | The arbitrage finder already computes market inversion. **OWNER DECISION 2026-08-11: KEEP as a distinct user-facing surface, but it must NOT become a second trade/arbitrage/value engine** — it is a specialized *consumer* of canonical infrastructure (values, ownership, package generation, package adjustment, roster-impact simulation, Team Strength/Weakness, market data, confidence). Distinct presentation, not distinct methodology. Criteria: owned by selected team; genuinely substitutable target; model prefers target; market prefers owned; obtainable; inversion meaningful enough to act on | D3 | D2, C1, C5 | **S–M on top of D2** | KEEP — EXISTING, REPAIR/COMPLETE |
| 2.6 | **Package Builder** | Build trade packages with return-position constraints applied **during** generation, not as a post-filter | New | No Package Builder component exists in the tree. **OWNER DECISION 2026-08-11: BUILD it as a real user-facing feature.** It must use the SAME canonical package-generation engine as Trade Finder / Trade Suggestions — no second package algorithm. Constraints: QB, RB, WR, TE, DL/EDGE, LB, DB, PICKS, honoured intentionally when several are selected. Must respect selected team, ownership, excluded/untouchable players (1.5), package adjustment (2.2), roster impact (1.3), Team Strength/Weakness (1.1/1.2), pick identity (2.7), missing/unpriced state, and league settings | D8 | 2.2, 2.3, 2.7, 1.5 | **L** | KEEP — NEW BUILD |
| 2.7 | **Stable draft-pick identity** | A pick keeps season + round + original owner + current owner through the whole pipeline | Existing, lossy | 53 of 216 league picks collapse; original-owner identity discarded before the trade calculator (W08-F005) | C6 | — | **L** | KEEP — EXISTING, REPAIR/COMPLETE |
| 2.8 | **2028/2029 future-pick valuation** | Price far-future picks instead of dropping them | Existing, partial | `config/weights/pick_year_discount.json` covers near years; unpriced picks are honestly excluded and flagged `isUnpriced` rather than zeroed — the correct posture, but they carry no value | D-tier | 2.7 | **M** | KEEP — EXISTING, REPAIR/COMPLETE |

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
| 4.3 | **Homepage Buy/Sell ticker** | Surface the canonical verdicts on the landing page | Existing, wrong source | `frontend/components/terminal/MarketTicker.jsx` exists and is live; must consume 4.2 rather than its own algorithm. Accessibility (touch/keyboard/screen-reader/reduced-motion) required | E2 | 4.2 | **S** | KEEP — EXISTING, REPAIR/COMPLETE |
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
| 6.6 | **Universal Player Profile** | One canonical page per player: identity, value, history, intelligence, performance, roster context, news | New (as canon) | **No universal profile route exists.** Only `/league/player/[playerId]` (public-league scoped) and `/players/compare`. Player clicks do not route to one canonical profile | F | 7.1, 7.2 | **L** | KEEP — NEW BUILD |
| 6.7 | **Blended source rank** | The cross-source rank shown on comparison surfaces | Existing, blank | Renders empty on the compare page; either restore or remove honestly | F4 | — | **S** | KEEP — EXISTING, REPAIR/COMPLETE |
| 6.8 | **Freshness indicators** | Show how old each computed intelligence actually is | Existing, partial | Some surfaces stamp freshness; not systematic (W08-F011) | F4 | — | **S** | KEEP — EXISTING, REPAIR/COMPLETE |
| 6.9 | **Human review / admin controls** | Approve / suppress / annotate / roll back model and extracted intelligence | Existing, narrow | `/admin` + `/admin/sharp-identities` and `src/sharp/curated_service.py` exist — a real review layer, but scoped to sharp identities only. Spec wants it general (W23-F017) | F | 4.2, 5.3 | **XL** | KEEP — EXISTING, REPAIR/COMPLETE |

---

## 7. Value model and identity (foundations)

Not product surfaces, but every product above reads them, so a defect here is a defect everywhere.

| # | Feature | Purpose | New/Existing | Current status at HEAD | Phase | Deps | Scope | Classification |
|---|---|---|---|---|---|---|---|---|
| 7.1 | **Canonical player identity** | One internal id joining Sleeper / KTC / IDP / news / stats, with UNRESOLVED as a real state | Existing, defective | W06 batch open: overrides lose to exact-id, `SleeperId` column unseen, near-name detector structurally unable to fire, ghost rows on the live board | B5 | — | **M** | KEEP — INFRASTRUCTURE/FOUNDATION |
| 7.2 | **Hill curve / percentile→value** | Convert rank to value | Existing, defective | **B1 investigated this session, not implemented.** Fit and serve use different denominators; error is per-scope: OFFENSE +8→25%, GLOBAL +6→14%, **IDP +14→34%**. Non-uniform scope-dependent distortion of the ladder | B1 | — | **L** | KEEP — INFRASTRUCTURE/FOUNDATION |
| 7.3 | **IDP valuation** | Value defenders correctly from dedicated sources | Existing, defective | W02-F001 (percentile/master mismatch — same root cause family as 7.2), W02-F002 (Hampel ejects the IDP anchor 29.4% of the time) | B2, B3 | 7.2 | **L** | KEEP — INFRASTRUCTURE/FOUNDATION |
| 7.4 | **Confidence buckets** | Say how trustworthy a value is | Existing, inverted | Bucket *rises* when sources disappear (W03-F004) | B11 | — | **M** | KEEP — INFRASTRUCTURE/FOUNDATION |
| 7.5 | **Canonical value scale (1–9999)** | Define what the product scale means and where it applies | Existing, undefined | Overlay has no clamp; live league-adjusted values exceed 9,999 (e.g. 10234). **OWNER DECISION 2026-08-11, resolved:** final canonical **individual player and draft-pick** values are a **1–9999 product scale**. Raw provider values keep their native units (0–100, ranks, dollars, 0–9999) and must NOT be mutated to force the range. Internal/intermediate maths may exceed 9999 where useful. **Aggregates are NOT capped** — Team Strength, package totals, roster/portfolio totals and other multi-asset sums may exceed 9999 and must not be clamped merely because individual assets are bounded. B9 must determine WHY league-adjusted individual values currently exceed the range and establish defensible normalization; a bare `min(value, 9999)` is explicitly forbidden where it would compress elite assets into ties, destroy ordering, mask a double application, or hide a scaling defect. Preserve monotonic ordering and elite-end separation | B9 | — | **M** | KEEP — INFRASTRUCTURE/FOUNDATION (decision resolved) |
| 7.6 | **Source independence / anti-double-counting / leave-one-out** | Stop comparing KTC against a consensus that contains KTC | Existing, circular | W12-F008: KTC sits on both sides of its own comparison; a leave-one-out diagnostic exists but is not used in production | B10 | — | **M** | KEEP — INFRASTRUCTURE/FOUNDATION |
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
| 9.1 | **Rankings pagination / windowing** | Stop rendering ~1,100 rows and 34k DOM nodes | Existing, absent | 200-row default; filters bypass the cap entirely; **no windowing implementation exists** — PR #760 proved windowing takes the board 22→59.5 FPS but its implementation was reverted uncommitted | G3 | — | **M–L** | KEEP — EXISTING, REPAIR/COMPLETE |
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
| 2.2 | **W08-F003 / KTC value adjustment** | PRESERVE exact KTC parity as a secondary/advisory metric — do not silently fix or clamp its non-monotonicity. Our canonical roster-aware model stays separate and uses our own methodology. Label the distinction in the UI; parity must not contaminate canonical package value, marginal value, Team Strength/Weakness, Golden Upgrades or Perfect Waivers | KEEP — EXISTING, CONSOLIDATE (two separated concepts) |
| §5 | **Podcast Intelligence** | KEEP the complete vision, STAGED after core foundations, in the 10-stage order recorded in §5. Not started during Phase B | KEEP — NEW BUILD (staged) |
| 0.1 | **Schedule Generator** | REMOVED permanently from this engagement. Must not be reintroduced as generator, optimizer, API, page, export or backlog item, and must not be resurrected by later plan regeneration because an old master prompt contained it | REMOVE — OWNER DOES NOT WANT / NOT APPLICABLE |

---

## Not in this inventory, by design

Audit tooling and registry work, test harnesses and regression tests, CI gates, lint/format,
migrations, dependency bumps, documentation drift, and the pure-infrastructure repairs already
tracked in `docs/master-site-audit/`. Also excluded: the six pre-squash performance PRs
(#758–763), which are dispositioned in `docs/BRANCH_DISPOSITION_2026-08-11.md`.
