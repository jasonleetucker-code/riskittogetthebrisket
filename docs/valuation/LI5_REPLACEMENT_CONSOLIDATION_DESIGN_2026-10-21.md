# LI-5 replacement-level consolidation: design (2026-10-21)

**Status: DESIGN ONLY. Every decision in §11 is PENDING.** Nothing here is authorized, approved or
implemented. This document adds no code, no configuration, no feature flag and no test. It changes no
value, source, weight, vote, curve, scoring rule, replacement anchor or served behaviour.

**Row:** `C2-REPL-01` (CE-09), `docs/C_SERIES_SCOPE_MANIFEST.md:234` ("One replacement level / PAR",
status DUPLICATED, target "one service; domain views are consumers"); `C2-DROP-01` (`:239`) says dropability
"consumes the shared replacement owner". Execution-map unit `C2-U2`.

**Authority and inputs.** Owner decision 2026-10-20 §3
(`docs/owner/LOW_VALUE_ASSET_OWNER_DECISIONS_2026-10-20.md`) authorized the *investigation*, not an
implementation. Inputs:

- the research record `docs/valuation/IDP_REPLACEMENT_AND_SCORING_2026-10-20.md` and its evidence JSON
  `docs/valuation/evidence/idp_replacement_2026-10-20/idp_replacement.json` (PR #1888, head `ac07c3e16`, incl.
  the independent-review corrections). Its line numbers were traced on a different base; **every file:line in
  this document was re-verified on `main@7dd8cb048`** and several differ from #1888's;
- the forced-drop record `docs/trade/FORCED_DROP_FIX_2026-10-20.md` (PR #1890, branch
  `ccr-04f5ba3d-forced-drop-fix`). That PR owns `src/trade/roster_capacity.py`,
  `src/trade/forced_drop_selection.py` and `src/draft/displacement.py`; this design routes around them and
  edits none of them.

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## 0. Summary

1. **What is wrong.** `src/draft/displacement.py::waiver_values_by_position` (`:276`) sets each position's
   waiver anchor to the single highest-valued unrostered player. #1888 measured that this counts injured
   players and non-producing rookies (six of seven anchors on 2026-10-20), and that value does not order the IDP
   wire. The anchor feeds roster capacity, the Trade Calculator Team Context, War Room, Finder, Angle,
   suggestions, the Perfect Draft server and client, droppability and auction advice.
2. **What the repo already says.** The manifest records replacement level as five implementations to be
   consolidated. **But** the V1-29 census (`scripts/replacement_census.py`, row `G`) and the C2 chain
   (`docs/roster-intelligence/C2_CANONICAL_ROSTER_CHAIN.md` §3) currently classify displacement's waiver anchor
   as **DISTINCT** ("different question and unit, must NOT be merged") and LI-5 as canonical **only for the
   `rosValue` unit**, enforced by `tests/roster_intel/test_replacement_owner.py`. This design reconciles the two
   rather than ignoring either (§2.5, §4.8).
3. **Proposed shape.** One *level* owner, LI-5 (`src/league_intel/replacement.py`), gains a unit-agnostic
   `waiver_levels` entry point whose algorithm is, by construction, the code `compute_replacement_levels` runs
   for its waiver tier (mean of free-agent ranks 1-3, `DEFAULT_BAND = 2`). A separate *population* builder
   (who counts as a free agent) composes the **existing** owners: league-wide rostered set, auction-rookie
   exclusion (consumer-specific), `src/trade/waiver.py::waiver_candidate_exclusion`, and
   `src/ros/availability.py`. `displacement.waiver_values_by_position` becomes a thin consumer. No new health
   definition, no new banding implementation.
4. **Currency.** `rankDerivedValue` (0-9999) for every displacement consumer. LI-5's gameplan call stays in
   `rosValue` (0-100) and is not touched. There is no validated conversion between the two, so mixing is
   refused (§4.3).
5. **Two things are deliberately separate.** *Consolidation* (this document) is gated by one new default-OFF
   flag. *Scarcity activation* (the 0.85-1.15 multiplier, inert at 1.0 today) is **not** part of this change and
   is pinned inert by test (§12).
6. **Sequencing.** Pure LI-5 refactor and population builder can be built without touching #1890's files.
   Wiring consumers collides with #1890 in four files and starts only after #1890 merges; activation is
   sequenced after #1890's flag decision, never stacked with it (§6).
7. **Owner calls.** Eight decisions, all PENDING, with a recommended choice, a default and answer text (§11).
   The central one is *which question the ladder answers* (§5).

## 1. Purpose and non-goals

**Purpose.** Prepare an implementation-ready design for replacing the best-single-unrostered-player anchor with
the canonical LI-5 waiver-tier rule plus a health filter built from existing owners, as the `C2-REPL-01`
consolidation, and for measuring its effect before any owner approval.

**Non-goals (each is a hard line, not a deferral):**

- No change to any IDP or offense value, `rankDerivedValue`, source weight, vote, family, Hill curve or scoring
  card. No automatic lowering of IDP values. The league-specific DB scoring hypothesis stays evidence-collection
  only (#1888 §9 recommendation 3).
- No activation of the scarcity multiplier (§12). `gameplan.py:517` keeps calling LI-5 without free agents.
- No change to FAAB's `V_repl` (`src/trade/faab_engine.py`, position-agnostic, its own anchor) or to BDVM's
  replacement engine (frozen Appendix-C parity fixture).
- No change to trade values, Value Adjustment, package math, fairness bands, or the forced-drop selection rule
  (#1890's).
- No public surface change. Replacement anchors are private; the owner's 2026-10-20 §1 forbids revealing them on
  the public calculator, and public paths run `market_fairness` with capacity OFF.
- No production-qualified (A4) anchor (#1888 §9: unstable in its bar, undefined at four positions, circular
  evaluation).
- No new replacement-level *implementation*. A health-filtered banded rule written inside `displacement.py`
  would be the sixth; it is out.

## 2. Current state (verified on `main@7dd8cb048`)

### 2.1 The two anchors

| | displacement anchor | LI-5 waiver tier |
|---|---|---|
| definition | best unrostered `rankDerivedValue` per position: `waiver_values_by_position` `src/draft/displacement.py:276-293`, over `_available_players` `:226-273` | `compute_replacement_levels(..., free_agents=...)` `src/league_intel/replacement.py:341-465`; waiver tier at `:439-452`: `_banded_value(fa_pool, 1, band)` (`:443`) with `DEFAULT_BAND = 2` (`:84`) = mean of ranks 1-3 |
| currency | `rankDerivedValue`, 0-9999 | `rosValue`, 0-100 ROS index (`:386`: `float(p.get("rosValue") or 0.0)`; docstring `:22`) |
| health / eligibility | none: any unrostered priced non-pick row with `rankDerivedValue > 0` | none: any unrostered row with `rosValue > 0` |
| position key | raw board `position`, upper-cased | `normalize_base_position` (DE/DT/EDGE/NT to DL, OLB/ILB/MLB to LB, CB/S/SS/FS to DB) |
| positions emitted | every position with an eligible free agent, including K/DEF | only positions with a priced **rostered** pool (`for pos, pool in rostered.items()`, `:393`) |
| production caller | all consumers in §2.2 | `gameplan.py:517` **without free agents**, so no waiver tier is ever produced |

### 2.2 Consumer map of the displacement anchor

"Population" is the unavailable-keys argument each caller passes today. It differs by consumer and the
consolidation must preserve each (§4.4, decision D6).

| consumer | where | anchor use | population today |
|---|---|---|---|
| capacity context (builds `waiver_values`) | `src/trade/roster_capacity.py:516-533` (`build_capacity_context` def `:466`); note an inline rostered-set loop `:516-528` that duplicates `src/draft/context.py::league_rostered_keys` `:107` | `waiver_values_by_position(contract, rostered_keys)` | league-wide rostered only; **no auction-rookie exclusion**, by comment (`:530-532`: "a trade in August is not bidding against them") |
| cut ladder inside capacity | `roster_capacity.py:1343` passes `context.waiver_values` to `build_cut_ladder`; `release_cost = base_value x scarcity_multiplier` at `:1360`; sort `:1387`; `forced_drop_cost` `:707` | ECC `max(0, base - waiver) x mult`; an unpriced player's base is the waiver value (`displacement.py:359-384`, `assumedWaiver`) | as above |
| Trade Calculator Team Context / `/api/trade/simulate` | `src/api/trade_simulator.py:1040,1048` | `rosterCapacity` block | as above |
| War Room (Analyze Trade, Analyze Multi) | `src/trade/analyze_trade.py:456,478` read `forcedDropReleaseCost`; `src/trade/trade_decision.py:471` (`forced_drop_unpriced` gate); `src/trade/analyze_service.py:456` (one `league_scarcity` read per request) | objective component | as above, through the simulator |
| Trade Finder | `src/trade/finder.py:1145-1163` (`_forced_drop_factor`), `:1963-1972`, `:2006`, `:2022` | ranking factor, reorders, filters nothing | as above |
| Best Offers / package builder | `server.py:10122-10142` (`capacity_for`), `:10322`, `:10621`; context via `server.py:11863-11870` | forced-drop cost per offer | as above |
| Angle | `src/trade/angle.py:381-386`; contexts `server.py:11185,11354` | capacity block, annotation | as above |
| Suggestions | `src/trade/suggestions.py:2181-2186` | capacity block, annotation | as above |
| Perfect Waivers | `src/trade/perfect_waivers.py:1014,1022,1092` | `effective_cut_cost(asset, {}, None)`: **no anchor in its cost basis**; but `team_droppability` and the capacity assessment feed `requiredStartersToday` through the ECC-ordered `undroppable` list | droppability: auction rookies excluded; capacity: none |
| Perfect Draft, server | `src/draft/context.py:310-354`: `auction_keys` `:316`, `waiver_values_by_position(..., auction_keys)` `:324`, `free_agent_ladder(..., auction_keys, limit=90)` `:332`, ladder built `:354`, payload `waiverValues` `:399` / `waiverLadder` `:404`; route `src/api/draft_optimizer_api.py:84` | per-position anchor, plus the position-agnostic ladder `W(k)` | league-wide rostered **and auction rookies** (`rookie_pool.auction_rookie_keys` = top-72 rookie rows with a `playerId`, **regardless of date**) |
| Perfect Draft, client | `frontend/lib/perfect-draft.js:156-176` (`waiverValueFor`, `surplusOverReplacement`), `:250-262` (`releaseCost` = base x mult), `:521`, `:833`, `:1186`, `:1386`; `frontend/components/draft/PerfectDraftPanel.jsx:198-222` | surplus over replacement; cut side | server's payload; the client computes no value |
| Auction advice | `frontend/lib/auction-advice.js:97,111` (reads `ctx.waiverValues`, `ctx.waiverLadder`) | passthrough into the same engine | server's payload |
| Droppability / roster intelligence | `src/roster_intel/droppability.py:228-249`, `:282`, `:289`; callers `src/api/roster_intelligence.py:328,468` | cut ladder, `waiverValues`, `waiverPopulation` | league-wide rostered and auction rookies (`None` asks the contract; `()` asserts nobody) |

**Not consumers of the displacement anchor:** FAAB (`faab_engine.resolve_anchors`, `V_repl`), BDVM, rankings,
the trade value / Value Adjustment stack, public `/league`, trade history.

### 2.3 The scarcity chain (inert)

- `src/api/gameplan.py:517-518`: `compute_replacement_levels(rep_teams, slots, endogenous=endogenous)` then
  `compute_scarcity(replacement, rep_teams)`. No free agents are passed, so no waiver tier exists.
- `compute_scarcity` (`replacement.py:603`): `waiver_scarcity = _safe_drop(best_ball, waiver)` =
  `1 - waiver / bestBallStarter`, `None` when either is missing.
- `displacement.scarcity_multiplier` (`:209-223`): `0.85 + 0.30 x clamp(waiver_scarcity, 0, 1)`, **1.0 when
  `waiver_scarcity` is `None`**. `src/roster_intel/targets.py:458-471` carries the same formula and `:805`
  uses the signal as a threshold.
- Read by: `src/draft/context.py:152-173` (`_league_scarcity`, through `get_league_bundle`), shared by
  `roster_capacity.league_scarcity` (`:451-463`) and `droppability`. #1888 confirmed
  `servedMultiplierByPosition` is 1.0 at every position.

### 2.4 What else says "replacement" (V1-29 census)

`scripts/replacement_census.py` (guard: `tests/roster_intel/test_replacement_owner.py`):

| row | module | unit | disposition today |
|---|---|---|---|
| A | `src/league_intel/replacement.py` | `rosValue` | OWNER |
| B / C | `src/scoring/replacement_level.py`, awards shim | fantasy points | OWNER / ADAPTER |
| D | `src/bdvm/replacement.py` | projected PPG | DISTINCT (frozen parity fixture) |
| E | `src/trade/faab_engine.py` (`V_repl`) | `rankDerivedValue` | DISTINCT (format line, not "what can I sign") |
| **G** | **`src/draft/displacement.py` (`waiver_values_by_position`, `free_agent_ladder`)** | **`rankDerivedValue`** | **DISTINCT** |
| I | `src/league_comparison/metrics.py` | points | DISTINCT |

The guard asserts (a) every OWNER row is consumed, (b) no two OWNER rows share a **unit**, (c) every OWNER
symbol is defined at exactly its declared path.

### 2.5 The tension this design must resolve

Two repository records point opposite ways. The manifest says consolidate to one service with domain views as
consumers. The V1-29 census and C2 chain §3 say displacement's anchor answers "what can I sign instead" in a
different unit and "merging across units would be the defect". Both are consistent with a narrower reading:
**what must not be merged is the *unit*; what can and should be shared is the *algorithm* (banded tier over a
free-agent pool) and the *population* (who is a free agent).** The C2-U2 execution-map entry says the same:
"different defensible definitions must be **named as different views**, never the same label over different
formulas." §4 builds on that reading, and §4.8 lists the governance edits (census row A's unit becomes
"caller-selected value field", row G becomes ADAPTER) that the implementation PR must make **together with**
its code so the guard stays green. That is a change to a prior owner-adopted boundary and is therefore
decision D3, not an implementation detail.

## 3. Findings that shape the design

**F1. Two populations already exist and the shadow research used one of them.** Capacity builds the anchor
without auction-rookie exclusion (`roster_capacity.py:533`); Perfect Draft and droppability exclude it
(`context.py:316,324,332`; `droppability.py:228-235`). `auction_rookie_keys` is top-72 rookie rows by value,
with no date check, so in October it still removes any *unrostered* top-72 rookie. The anchor setters #1888
named at DL and LB (Derrick Moore, Kaleb Elarms-Orr; both unrostered rookies) are quite possibly in that set,
which would mean Perfect Draft's served `waiverValues` already differ from the capacity anchor #1888 measured.
This is the review caveat that the Perfect Draft shadow skipped the auction-rookie exclusion. It is
**unverified here** (no board build was run); §4.4 turns it into a parity requirement and §9 into a
measurement.

**F2. The add-pool predicate does not remove the DL and LB rookie anchor setters in October.**
`waiver_candidate_exclusion` (`src/trade/waiver.py:263-299`) refuses a row for: position not offered, `unpriced`,
`below_min_value` (`MIN_WAIVER_VALUE = 500`, `:48`), `single_source` (`sourceCount < 2`), and `rookie_gate`.
The rookie gate is **date-only** (`_rookies_eligible_today`, `src/trade/suggestions.py:1874-1897`: closed
Feb 1 to May 11, open otherwise), so it does not fire on 2026-10-21. `single_source` is the only gate that can
bite, and it could not be established by static reading:

| anchor setter (as of #1888) | role | rookie_gate (Oct) | `sourceCount` |
|---|---|---|---|
| Derrick Moore (DL 1,918, healthy rookie) | sets DL A0 | does not apply | **unverified**. Indicative only: on the current-main `CSVs/site_raw` (dynasty boards, ROS boards excluded) his name appears on `idpTradeCalc`, `idpShow` and `idpShowCombined`, i.e. two providers. The archived scraper payload shows one canonical site value (`_sites` 1), which is not the pipeline's `sourceCount` (rank-signal sources join later) |
| Kaleb Elarms-Orr (LB 2,149, healthy rookie) | sets LB A0 | does not apply | **unverified**; indicative: six boards (`dlfIdp`, `dlfRookieIdp`, `draftSharksIdp`, `idpShow`, `idpShowCombined`, `idpTradeCalc`) |
| Keionte Scott (DB 1,917, rookie) | sets DB A1 | does not apply | **unverified**; indicative: `idpTradeCalc`, `idpShow`, `idpShowCombined` |

Consequence: **at DL and LB the health filter is a no-op** (#1888: A1 = A0 at DL and LB because the setters are
healthy); the whole DL/LB improvement comes from banding (DL 1,918 to 1,812, LB 2,149 to 1,946). Health matters
at DB (setter listed Out) and at offense positions. If a setter *is* single-source, the add-pool filter would
remove him and the anchor would move further. The existing `waiver_pool_exclusion_census` function
(`waiver.py:302`) already reports exclusions by reason; the replay (§9) must call it and report each setter's
`sourceCount` and reasons.

**F3. The existing owners do not cover everything the research health rule covered.**
`availability.player_week_states` (`src/ros/availability.py:258`) answers per-week states from Sleeper host
metadata. It does not check "has an NFL team", and Sleeper's `status` field (`Active` / `Inactive`) is not read.
#1888's strict rule required both, and its LB census found three priced "Active" linebackers with no team.
`waiver_candidate_exclusion` checks neither. So a player with no NFL team is reported `available` by the owner.
Whether any such player reaches a top-3 slot is measurable (§9). If one does, the fix belongs in the existing
add-pool owner (a new reason code there, which changes waiver recommendations and therefore needs its own
decision), not in a private rule inside the consolidated owner.

**F4. The availability owner is week-relative and silent in the off-season.** With `current_week` unknown (the
August rookie auction, the pre-draft window) `player_week_states` returns `weekly_designation_<x>_current_week_only`
as AVAILABLE for an "Out" player, because "current week only" has no current week. So a health filter consuming
it is **not applicable** when the league's own week is unknown (`fantasy_week_horizon` /
`availability.load_context`; "no calendar fallback on this path" is the existing stance). The consolidated
owner must stamp `health: not_applicable` and apply banding alone in that case. Perfect Draft in August is
therefore served at the banded level **without** health (the §5 rule for question B, dynasty-asset opportunity cost), not the health-filtered level of question A. D1 option A therefore does not hold for Perfect Draft in the pre-season: its stamp must say so (`health: not_applicable`, served level named as banded-without-health), and the two must not share one label.

**F4b. What "week unknown" means.** The off-season trigger is `ctx.current_week is None` or a date outside the NFL season; whether Sleeper reports `leg` as 0, 1 or missing in the off-season is unverified, and `leg=1` before week 1 (or the last week after the season) would run the health filter against a stale or irrelevant week. The build adds a test for `leg=1` before the season starts.

**F4c. Bye and owner-override states.** In `src/ros/availability.py` the `unavailable` state includes `bye` and `owner_override`. The design evaluates health at the current week only; counting a bye as unavailable would drop a position's top free agents on their bye week and move the anchor week to week on schedule alone. The rule is therefore an injury-type reason-code allowlist (state the exact codes in the build); `bye` and `owner_override` do not exclude. If the owner prefers to accept bye exclusion, a bye-week test and a replay row are required.

**F5. Health data is daily and request-path network access is forbidden.** `matchup_intel._players_meta`
(`src/api/matchup_intel.py:185-199`) falls back to a multi-MB network fetch when the persisted DB is stale or
missing a requested id. CLAUDE.md's stance for scoring evidence is "never fetched inside a request". The
disk-only accessor `game_day_live.persisted_players_meta` (`src/ros/game_day_live.py:851-876`) is age-bounded
(`PLAYERS_DB_MAX_AGE_SECONDS = 24 h`) and returns `fetchedAt`, but returns `None` unless it holds *every* id
asked for. The health layer must use the disk-only path, stamp the as-of time, and degrade (§4.4) when it
returns `None`.

**F6. "Documented ceiling" stops being true once the anchor is a banded mean.** #1890 charges an unpriced
roster player at the position's waiver value and labels the basis `assumed` with `bound: "upper"`
(`forced_drop_selection.py`, "the repository's one documented ceiling"). That is correct only while the anchor
is the *best* unrostered player. A mean of ranks 1-3 of healthy players is below the best free agent's value,
so it is an estimate, not a ceiling. The implementation PR must relabel the basis when the flag is ON. This is
a second coupling with #1890 beyond file collisions.

**F7. Residuals remain even after the change.** Under A3h, 12 of 35 value-optimal DB starters still sit below
the anchor and the DB anchor (1,754) is above the lowest starter (1,335) (#1888 §9). The consolidation is an
improvement, not a fix of the DB question; the owner should not be told otherwise.

## 4. Target architecture

### 4.1 Single owner API (LI-5)

In `src/league_intel/replacement.py`:

```
waiver_levels(
    free_agents: Iterable[Mapping],      # already population-filtered by the caller
    *,
    value_key: str,                      # "rosValue" (LI-5's own call) or "rankDerivedValue"
    position_of: Callable[[Mapping], str] = <normalize_base_position of row["position"]>,
    band: int = DEFAULT_BAND,
) -> dict[str, ReplacementLevel]         # tier "waiver"; value, thresholdRank, bandLow/High, sampleSize
```

Rules (all inherited, none new):

- Pool per position is every row with `value > 0`, sorted descending; a missing value is *excluded*, never
  coerced (the existing `float(... or 0.0)` then `> 0` filter is the same outcome).
- Level = `_banded_value(sorted_pool, 1, band)`: the mean of ranks `max(1, 1-band) .. min(n, 1+band)`, i.e.
  ranks 1-3 at `band = 2`; a pool of one or two uses what exists; an empty pool yields **no level** (the key is
  absent). `sample_size`, `band_low`, `band_high` come back for free and are the provenance.
- `compute_replacement_levels` is refactored so its waiver block calls the same helper. Parity with the
  reference is then structural, and a test pins it anyway (§8).

**Why not feed `compute_replacement_levels` directly.** It requires a `teams` roster argument, runs the optimizer
for the other three tiers (the expensive part), emits only positions that have a priced rostered pool, and is
hard-wired to `rosValue`. Displacement needs only the waiver tier, for every position with a free agent. The new
entry point is the extracted waiver-tier code, not a second algorithm.

### 4.2 Displacement becomes a thin consumer

With the flag OFF, `waiver_values_by_position`, `free_agent_ladder` and `count_free_agents` run today's code
verbatim. With it ON:

```
waiver_values_by_position(contract, rostered, unavailable) =
    { pos: lvl.value for pos, lvl in waiver_levels(population(...), value_key="rankDerivedValue",
                                                   position_of=<raw upper-cased board position>) }
```

- `free_agent_ladder` and `count_free_agents` read the **same population** but stay unbanded and
  position-agnostic. The ladder is a different *view* (an ordered list for `W(k)`), not a level; it shares the
  population so health and auction parity cannot diverge between the level and the ladder. It stays in
  displacement and is named so.
- Keys stay the board's own position strings (no DE/CB collapse), so every existing consumer lookup
  (`_waiver_value_for`, `waiverValueFor`) resolves unchanged. A replay census of distinct board positions
  confirms the board is already family-normalized; if it is not, that is a finding, not a silent remap.
- The `_waiver_value_for` fallbacks (cheapest positional level when a position has none; `0.0` when there are
  no levels at all) are untouched. They are the named pre-existing follow-up in #1890 §11 and outside this
  change. The design adds no new path to them except through thin or empty positions, which is why the thin- and
  empty-wire cases are adversarial tests (§8).

### 4.3 Currency decision: `rankDerivedValue`

**Choice: the consolidated owner is currency-parametric; displacement consumers use `rankDerivedValue`; LI-5's
gameplan call keeps `rosValue`.**

Why not run the displacement consumers in `rosValue`:

- Every consumer compares the anchor with a `rankDerivedValue` quantity: ECC `max(0, base - waiver)` with
  `base = rankDerivedValue`; release cost `base x mult`; Perfect Draft rookie `boardValue` minus `waiverValue`;
  trade package values. A `rosValue` anchor against a `rankDerivedValue` base is exactly the "feeding the target
  engines the contract's 0-9999 numbers" dead-signal failure `gameplan.py:36-47` documents, in reverse.
- `rosValue` is an ordinal log-rank index with a ROS horizon (this-season production). The board is a dynasty
  market value. The repo records "no validated conversion between them", and the C2 chain §3 correction exists
  because exactly this unit confusion was once made in a documentation table.
- #1888's evidence (A3h) is in `rankDerivedValue`, so an owner-approved rule is the one measured.

Consequences to accept:

- LI-5 stays unit-honest by *argument*, not by a baked-in constant: the same function is called with different
  `value_key`s by callers that own their unit. Census row A's unit becomes "caller-selected value field" (§4.8).
- `waiver_scarcity = 1 - waiver / bestBallStarter` is a ratio and is only meaningful when both terms share a
  currency. A market-currency waiver tier **cannot** be divided by a `rosValue` best-ball floor. This is the
  structural reason the consolidation cannot activate scarcity even by accident: the scarcity input would have to
  be a *separate* `rosValue`-currency free-agent tier (§12).

### 4.4 Population: existing owners only

One builder in a new draft-layer module (sibling of `src/draft/rookie_pool.py`, e.g.
`src/draft/waiver_population.py`; the name is not binding). It defines **who is a free agent**; LI-5 defines
what the level of that pool is. It uses lazy function-level imports for `src.trade.waiver` and `src.ros.availability`
(precedent: `src/draft/context.py:_roster_size_for` imports `src.trade.roster_capacity` lazily), because
`src/trade/waiver.py` imports `src/trade/suggestions.py` and a top-level import from the draft layer risks a
cycle. An import-boundary test (§8) pins this.

| step | rule | existing owner |
|---|---|---|
| 1. rostered | league-wide rostered key set (ids and names) | `src/draft/context.py::league_rostered_keys` (`:107`). Capacity's inline copy (`roster_capacity.py:516-528`) is behaviour-identical and folds into this call; a byte-parity test covers the fold |
| 2. unavailable keys | **per consumer, preserved**: capacity `()`; Perfect Draft `auction_rookie_keys`; droppability `None`-asks-contract / caller-supplied | `src/draft/rookie_pool.py`; the existing arguments (decision D6) |
| 3. add-pool eligibility | `waiver_candidate_exclusion(row, positions=waiver_positions(include_kicker_def=True), min_value=MIN_WAIVER_VALUE, rookies_eligible=<injected>) is None` | `src/trade/waiver.py`. `include_kicker_def=True` so K/DEF roster players keep a positional level; `rookies_eligible` is resolved **once at the request boundary** (not read from the clock inside the builder) so results are deterministic and testable |
| 4. health | evaluation week = the league's own current week; state per `player_week_states(pid, meta, ctx)`: `available` and `uncertain` stay, `unavailable` and `unknown` are excluded; counts per state are stamped | `src/ros/availability.py`, with `load_context`; meta from the disk-only `persisted_players_meta` |

Health mapping rationale. The availability owner's contract is "UNKNOWN IS NEVER AVAILABLE" and it keeps
`uncertain` in for lineup solves while *reporting* it. A replacement candidate that is Questionable this week is
a usable replacement more often than not; one with no host metadata is not demonstrably usable. This matches the
research strict rule on `unknown` and on Out/IR/PUP, and differs on Doubtful (research excluded it; the owner
reports it as `uncertain`, so it stays in and is counted). The replay reports the sensitivity of excluding
`uncertain` as well (decision D5).

Degradation, stated so no path produces a silent zero:

| condition | behaviour | stamp (`replacementPopulation.health`) |
|---|---|---|
| league week unknown (off-season, pre-draft) | steps 1-3 only; banding applies | `not_applicable: no_current_week` |
| persisted players DB missing, stale (> 24 h) or lacking ids | **legacy population**; banding still applies | `evidence_unavailable: <reason>`, `asOf` if known |
| DB read but a given player has no metadata | that player is `unknown`, excluded | counted in `unknown` |
| a position ends up with 1-2 eligible players | LI-5's existing thin-pool behaviour (mean of what exists) | `sampleSize` per position |
| a position ends up with none | no level for that position; existing `_waiver_value_for` fallback applies | position listed in `positionsWithoutLevel` |

Falling back to the legacy population when health evidence is lost is deliberate: excluding every "unknown"
player when the whole feed is down would empty the pool and send the anchor to the `0.0` fallback, which is
worse than the status quo and is a MISSING-IS-NEVER-ZERO violation. It is labelled, never silent.

`waiver_candidate_exclusion` is applied as-is, including `min_value = 500` and `single_source`. Anchors sit at
1,400-2,100 so the floor does not move a level, but it does truncate the **ladder** tail at 500 (the ladder
holds up to 90 values); the replay reports the ladder-length change. Treating "replacement candidate" as
"add-pool-eligible" is itself a definition choice and is part of D5.

### 4.5 Banding

LI-5's `DEFAULT_BAND = 2` (the mean of ranks 1-3), unchanged, is the rule #1888 called A3 / A3h / A3hs and
measured. It is a smoothing rule, not a calibrated constant (its source docstring says rank-indexed levels
average a window "hostage to one player's projection"). Banded-only (A3, no health) is also measurable from the
same code path with the health step disabled, which is how §9's stepwise attribution is produced. The band is
read from the LI-5 constant; the implementation adds no second knob.

### 4.6 Provenance and payload

Additive only, present only with the flag ON (so flag-OFF payloads stay byte-identical):

- `replacementPopulation`: `{rule: "li5_waiver_tier_v1", valueKey, band, populationBasis, unavailableKeysCount,
  eligibleFreeAgents, excludedByReason (the waiver owner's census), health: {state, asOf, available, uncertain,
  unavailable, unknown}, positionsWithoutLevel}`.
- Per position, optionally `waiverLevelDetail`: `{sampleSize, thresholdRank, bandLow, bandHigh}` taken straight
  from `ReplacementLevel`.
- `waiverValues` / `waiverLadder` keep their shapes and field names (the Perfect Draft client and
  `auction-advice.js` read them unchanged). The frontend computes nothing new; it needs no change for the
  numbers. A label ("banded healthy replacement") is optional presentation work for a UI lane.
- `CONTEXT_VERSION` (`src/draft/context.py:59`) bumps only if a field *changes meaning*; the meaning of
  `waiverValues` does change (best player to banded mean) when ON, so the implementation should bump it behind
  the flag, with a contract test.

### 4.7 What stays distinct (named, not merged)

| stays | why |
|---|---|
| FAAB `V_repl` | position-agnostic format line blended with the 12th-best live player; answers "what does the format make replacement", has its own anchor (`faab_engine.py`). Whether its live pool should also exclude injured players is a separate small question (#1888 §8.2: 1,706 raw to 1,655) and is **not** part of this change |
| the free-agent ladder `W(k)` | a different view (ordered list), shares the population, not the level |
| `roster`, `starter`, `bestBallStarter` tiers | LI-5's other three tiers, unchanged, still `rosValue` |
| BDVM replacement | frozen Appendix-C fixture; do not touch |
| `rosValue` LI-5 call in the gameplan bundle | scarcity inputs; unchanged (§12) |

### 4.8 Governance edits the implementation PR must carry with its code

1. `scripts/replacement_census.py`: row A `unit` becomes "caller-selected value field: rosValue (gameplan) or
   rankDerivedValue (displacement consumers)"; row G becomes ADAPTER ("population + thin view over the LI-5 waiver
   tier"); notes updated. The three guard properties still hold (E keeps `rankDerivedValue` but is DISTINCT, not
   OWNER, so there is no two-OWNER-one-unit conflict).
2. `docs/roster-intelligence/C2_CANONICAL_ROSTER_CHAIN.md` §3: table row for `src/draft/` waiver value and the
   paragraph that says "no merge" are corrected to describe the shared algorithm and the retained unit split.
3. `docs/C_SERIES_SCOPE_MANIFEST.md` `C2-REPL-01` status update, only on evidence (not before activation).
4. `CLAUDE.md` gets a short pointer in the roster-capacity section when the flag is activated, not before.

## 5. Which question does the ladder answer? (owner call, D1)

The anchor prices the opportunity cost of a roster spot. There are two defensible questions, and they give
different answers for exactly the players #1888 flagged.

| | **A. This-season lineup replacement** | **B. Dynasty-asset opportunity cost** | C. Status quo (best single unrostered) |
|---|---|---|---|
| asks | "If I release X, what usable player can I put in that spot?" | "What claimable asset do I forgo by keeping X?" | what ships today |
| injured / not-yet-playing free agent | excluded (he scores 0 and occupies a spot; this league has **0 IR and 0 taxi slots**, 58 spots, 11 of 12 rosters at or over the cap) | included at full dynasty value (a claimable stash) | included |
| rule | banded mean of ranks 1-3 of the health-filtered population (A3h/A3hs) | banded mean of ranks 1-3, **no** health filter (A3) | rank 1 |
| DB anchor / DB starters below it (#1888 §2.2) | 1,754 / 12 of 35 | 1,994 / 23 of 35 | 2,156 / 26 of 35 |
| DL, LB anchor | 1,812 and 1,946 | no health effect at DL/LB (setters are healthy), same as A | 1,918 and 2,149 |
| offense QB / RB / WR / TE | 1,410 / 1,502 / 1,583 / 1,769 | not published in #1888 for banded-all; replay must produce | 1,923 / 1,626 / 1,802 / 2,061 |
| fits best ball, no IR | yes: it is the question the format asks | only if the owner values stashing injured assets over roster spots | no |
| risk | year-round dynasty value of an injured star on the wire is understated as a "cost of keeping X" | keeps charging cuts against assets that cannot help this season | the measured defect |
| status of its evidence | #1888 A3h/A3hs; wire-order evidence is an absence of evidence (small n, CIs about +/-0.34 to 0.41) | #1888 A3 | n/a |

**Recommendation: A for every displacement consumer, with B retained as a named, non-served shadow lens** in the
replay so the owner can see the gap. Reason: the format is best ball with no IR, and the consumers (forced-drop
charge, cut ladder, droppability, Perfect Draft cut side) all ask what you give up *to hold a roster spot now*.
The two questions must not share one label (C2-U2's "named as different views"): if the owner chooses B for any
consumer, it is a separately named level, not the same field with a different formula. A and B are two outputs
that differ only by the health step (which lives in the population builder, §4.4, not in LI-5), not two owners. **Default if unanswered:** no change (the
flag stays OFF, the status quo C stands).

## 6. Phased plan and dependency on #1890

**State of #1890 (verified).** Branch `ccr-04f5ba3d-forced-drop-fix`, flag `forced_drop_cheapest_legal`
(default OFF, gate LIVE), selection mode V5 vs V5-R pending an owner call, activation checklist §10 all open.
Its diff touches: `src/draft/displacement.py` (`build_cut_ladder` seams `order_key` / `candidate_ids`, +23),
`src/trade/roster_capacity.py` (about +506 at the head current when this was reviewed, regions `assess_roster_capacity`, `forced_drop_cost`, `ForcedDrop`,
`RosterCapacity`; **not** `build_capacity_context`), `src/roster_intel/droppability.py` (`pool_cut_ladder`
signature, +8), `src/api/feature_flags.py` (+20), `src/api/trade_simulator.py`, `src/trade/{analyze_trade,finder,trade_decision}.py`,
`server.py` (5 lines), the new `src/trade/forced_drop_selection.py`, and tests/fixtures including
`tests/fixtures/forced_drop_flag_off_reference.json`. It reads `context.waiver_values` and
`waiver_values_available` (`waiver_values` semantics are therefore a shared interface).

| phase | content | files | #1890 collision | gate to start | gate to finish |
|---|---|---|---|---|---|
| **P0** | this design | `docs/valuation/` doc, `docs/WORK_CLAIMS.md` row | none | n/a | owner reads §11 |
| **P1** | LI-5 `waiver_levels` extraction + parity; census row A edit; no consumer wired, no flag | `src/league_intel/replacement.py`, `scripts/replacement_census.py`, `tests/league_intel/test_replacement.py`, `tests/roster_intel/test_replacement_owner.py`, C2 chain §3 | **none** | D2 and D3 answered | L1 green; parity and byte-identity of `compute_replacement_levels` |
| **P2** | population builder, unwired | new `src/draft/waiver_population.py`, new tests | **none** | P1 | import-boundary, adversarial health tests green |
| **P3** | wire consumers behind the flag; additive payload; replay harness (new script) | `src/draft/displacement.py` (`waiver_values_by_position`, `free_agent_ladder`, `count_free_agents` only), `src/draft/context.py` (`:310-335`), `src/trade/roster_capacity.py` (`:516-533` and a new `CapacityContext` field), `src/roster_intel/droppability.py` (`:228-249`), `src/api/feature_flags.py` | **4 files collide** (`displacement.py`, `roster_capacity.py`, `droppability.py`, `feature_flags.py`), same files, different regions; also relabel #1890's `bound: "upper"` basis (F6) | **#1890 merged to `main`** (flag OFF is enough); rebase onto it, never fork | flag-off byte identity; per-consumer parity; replay stepwise table |
| **P4** | evidence package + owner approval of the §10 impact | docs/evidence | none | P3; #1890's flag decision recorded | owner approval, separate from D1-D8 |
| **P5** | activation (owner), soak | flag flip + restart | none | #1890 either activated and soaked, or explicitly held with the baseline for the replay fixed | verify on the box (§9) |
| **P6** | delete the legacy branch | displacement, context, capacity, droppability | none | soak complete | census, flag-off identity tests retired with the flag |

**Why the anchor change must follow, not stack on, #1890.** #1888 §8.2 measured that every forced drop has an
effective cut cost of 0 under every anchor, so the anchor moves a charge only through (a) which tied sub-anchor
player is chosen and (b) the release cost of **unpriced** cuts, which is charged at the waiver value. Both are
exactly what #1890 corrects (alphabetical ties; unpriced charged a whole waiver level). Activating both at once
would make their effects unattributable. With #1890's flag ON, the anchor enters the *charge* only through
unpriced players' base and through published fields; with it OFF it also decides ECC order. The replay (§9)
therefore fixes #1890's flag state as the baseline and reports both.

**Collision handling.** Same-file, different-region edits merge textually, but `feature_flags.py` entries are
adjacent and `tests/fixtures/forced_drop_flag_off_reference.json` hashes capacity blocks: this change adds
fields only when ON, so the fixture must remain byte-identical (a test asserts it). If #1890 is still unmerged
when P3 is ready, P3 waits (`BLOCKED_BY_ACTIVE_CLAIM` per `docs/WORK_CLAIMS.md`); it does not fork the files.

## 7. Feature flag and rollback

- **Proposed name:** `replacement_level_li5_consolidation`, registered in `src/api/feature_flags.py`,
  **default `False`**, gate status per the registry convention (`LIVE` once the read sites exist). Env override
  `RISKIT_FEATURE_REPLACEMENT_LEVEL_LI5_CONSOLIDATION`.
- **One flag, one effect.** It switches the displacement consumers from the legacy anchor to the LI-5
  waiver tier over the composed population. Banding and health are *not* two flags (that would invite
  unmeasured combinations); their separate effects are decomposed in the replay instead. The question (D1) and
  the `uncertain` handling (D5) are reviewed constants in one config/constant location, not environment reads,
  because changing them changes served verdicts (same pattern as #1890's `SELECTION_MODE`).
- **Reserved, not created:** a scarcity flag (suggested name `replacement_scarcity_activation`) is named in §12
  so nobody overloads this one. It is not added by this work.
- **Flag OFF** = today's code path, byte-identical, no new fields, no new reads (no players-DB access).
- **Rollback:** set `RISKIT_FEATURE_REPLACEMENT_LEVEL_LI5_CONSOLIDATION=0` (or unset) **and restart** (flag reads
  are cached per process; there is no runtime toggle). The legacy branch is kept until P6 so rollback is a flip,
  not a deploy. Cached Perfect Draft contexts (`draft_optimizer_api.py` caches by league and team) must be
  cleared by the restart; the implementation adds the flag state to the cache key so a flip cannot serve a stale
  context.

## 8. Test plan (describe only; nothing is run here)

1. **Parity against the LI-5 reference.** For synthetic pools and for a pinned contract: for every position,
   `waiver_levels(pool, value_key=K)[pos].value` equals
   `compute_replacement_levels(teams, slots, free_agents=[{"position": p, "rosValue": v}, ...], band=2)[pos].levels["waiver"].value`
   (the reference reads only `rosValue`, so the test re-keys values into it; the unit is irrelevant to the
   arithmetic). Positions present in only one side are asserted explicitly (reference emits none without a
   rostered pool). Property loops over seeded random pools (the repo has no Hypothesis dependency; #1890's
   brute-force loops are the precedent): monotone in the pool (adding a higher value never lowers the level),
   permutation-invariant, level <= max, level >= min of the band, ties.
2. **`compute_replacement_levels` unchanged.** Golden outputs for the existing LI-5 tests
   (`tests/league_intel/test_replacement.py`) byte-identical after the helper extraction.
3. **Flag-OFF byte identity.** A reference corpus recorded on pre-change `main` (same method as
   `tests/fixtures/forced_drop_flag_off_reference.json`): Perfect Draft `build_roster_context` payload,
   `team_droppability` for every team, capacity blocks, and digests of simulate / War Room / Finder payloads on
   the pinned board; flag OFF (default and explicit `0`) must match exactly and flag ON must change all of them.
   Also asserts #1890's reference fixture still matches.
4. **Population parity per consumer.** For each consumer (capacity, Perfect Draft, droppability) the
   population *before* the health and add-pool steps equals the legacy free-agent set exactly (ids), including
   the auction-rookie exclusion where it applies and its absence in capacity. A test constructs a contract where
   an unrostered top-72 rookie is the best DL and asserts capacity includes him and Perfect Draft excludes him.
   This is the parity requirement from review caveat 5: any shadow or replay must build each consumer's
   population through that consumer's real builder, never a harness-local one.
5. **Health adversarial cases.** An injury flip (Active to Out between two evaluations changes the level
   deterministically given a pinned meta snapshot); `unknown` (no metadata) excluded; `uncertain` kept and
   counted; thin wire (1-2 eligible); empty wire (no level, fallback documented); stale or missing players DB
   (legacy population, `evidence_unavailable` stamped, no network call: the test patches the network client to
   raise); off-season (`not_applicable`); a no-NFL-team player (current behaviour: reported `available`, test
   documents F3 rather than hiding it); `rookies_eligible` injected both ways (the Feb-May window excludes all
   rookies deterministically).
6. **Scarcity pinned inert.** With the flag ON, `servedMultiplierByPosition` is 1.0 at every position; an AST /
   call-site test asserts `gameplan.py` still calls `compute_replacement_levels` without `free_agents`, and that
   no market-currency waiver tier is ever passed to `compute_scarcity`.
7. **No second implementation.** `scripts/replacement_census.py` stays green with the edited rows; an AST guard
   fails if `displacement.py` or the population module defines a banded/sorted-top-N level (`_banded_value`,
   `statistics.fmean` over a sorted pool) or a second health predicate (health logic may only call
   `availability.player_week_states` and `waiver_candidate_exclusion`). Import-boundary test: importing
   `src.draft.displacement` does not import `src.trade.waiver`/`suggestions`.
8. **Governance guard.** `tests/roster_intel/test_replacement_owner.py` edits are part of P1 and must show the
   guard can still go red (its non-vacuity probes remain).
9. **Per-consumer before/after on a pinned board** (the replay; §9 for method): capacity and forced-drop charge,
   War Room verdict categories, Finder top-20 overlap, Best Offers, Angle, Perfect Draft `waiverValues`,
   `waiverLadder`, MaxBid / plan, auction advice, droppability, Perfect Waivers (asserted unchanged except the
   `undroppable` list order), FAAB (asserted identical), and **`scripts/board_diff.py --expect-no-value-change`**
   proving no `rankDerivedValue`, rank or tier moved.
10. **Performance.** `build_capacity_context` p50/p95 before and after; N-team per-team contexts (the N-team
    engine builds one per team) must share one population computation per request snapshot. Cache key:
    contract stamp, evaluation week, health-evidence `fetchedAt`, hash of the unavailable-key set, flag state.
11. **Frontend.** No change needed; the existing vitest suites for `perfect-draft.js`, `auction-advice.js` and
    `PerfectDraftPanel` run against golden payloads with and without the additive block.
12. **Public-safety.** A test that no replacement anchor, population block or level appears in any public
    payload (the existing public-payload value-free assertions already cover `market_fairness`; extend the
    fixture list).

## 9. Evidence required before activation

**From #1888 (re-measured on the then-current board, not reused):**

- anchors A0 vs A3 vs A3hs per position and "value-optimal starters below the anchor" (DB 26/35 to 23/35 to
  12/35; DL 7/37 to 3/37; LB 6/35 to 3/35; offense A0 to A3h QB 1,923 to 1,410, RB 1,626 to 1,502, WR 1,802 to
  1,583, TE 2,061 to 1,769);
- the strict-vs-loose rule check (`healthyLooseButNotStrict`, 0 everywhere in the snapshot) *re-expressed
  for the availability owner*, plus the new count of players each existing owner passes that the research rule
  rejected, and vice versa (no NFL team; Doubtful);
- the wire-order Spearman figures (DL 0.09, LB -0.21, DB 0.21; n 36 / 21 / 27) as the justification that value
  does not order the IDP wire, with the caveat that small samples are an absence of evidence, not proof;
- the residuals (12 of 35 DB starters still below the anchor; DB anchor above the lowest starter) shown to the
  owner as what the change does **not** fix;
- the consumer shadow results (capacity scenarios: A3h changed the forced drop on 4 of 12 teams at net +1, mean
  change -246, max 1,872; Perfect Draft positive-surplus rookies DB 2 to 6 of 21, DL 3 to 5 of 24, LB 5 to 6 of
  18; `W(k)` top five 2,156 to 2,149 at the top, 1,923 to 1,895 at the fifth). Those were measured against the
  **pre-#1890** charge and with the capacity-style population, so they are reference points, not the approval
  numbers.

**New measurements (these decide approval):**

1. **Stepwise attribution per position:** legacy A0 -> population parity (auction exclusion per consumer) ->
   add-pool eligibility -> health -> banding, so each effect is attributable, plus the banded-only (B) and
   health-excluding-`uncertain` variants as sensitivity.
2. **Anchor-setter audit:** for every position, the legacy setter and the three banded members: rookie flag,
   `sourceCount`, `waiver_candidate_exclusion` reason, availability state and reason, whether the setter is in
   `auction_rookie_keys`. This closes review caveat 4 (F2).
3. **Population sizes and ladder length** (eligible free agents per position, excluded by reason, ladder
   truncation at the 500 floor).
4. **Both consumer populations:** capacity-style and Perfect Draft-style anchors side by side on the same
   board (F1), for every position.
5. **Stability over time:** the anchor's week-over-week and day-over-day drift under real status churn, legacy vs
   new. #1888 states banding "damps but does not remove" sensitivity to statuses. Historical Sleeper statuses
   are not retained in the repo, so this needs a snapshot series on the box (one snapshot per day, aggregate
   counts only).
6. **Consumer effect on the pinned board with #1890's flag state fixed** (OFF and ON, V5-R if chosen): forced-drop
   cut-set changes, charge distribution, War Room category transitions, Finder top-20 overlap and
   non-zero-charge candidates, Perfect Draft MaxBid and plan, droppability ladder membership, and the
   `undroppable` list order in Perfect Waivers.
7. **Latency and cache behaviour** of the new reads.

**Method (the repo's pinned-archive approach; described, not run).** Build the board from a committed archive
through `scripts/low_value_asset_shadow_replay.py::build_context`, and pin **the whole input tree, not just the
archive**: the contract build also reads `CSVs/`, `data/scrape_state` and `config/weights` from the working
tree, which the two-hourly refreshes move (#1890 §0: an unpinned rebuild moved 844 of 1,003 values). #1890's
replay (`scripts/forced_drop_fix_replay.py`) does this with `--csv-rev <sha>` and a `csv_tree` helper that stamps
the revision and a hash of the built board; the new replay should import or lift that helper once #1890 is on
`main` rather than re-implement it. Health inputs are a pinned, aggregate-only snapshot of Sleeper player
statuses (no ids committed). The evaluation week and `rookies_eligible` are passed explicitly. Report the board
hash and rebuild identity with every table.

**Production-box replay (required before approval).** The box has the real persisted players DB, the real league
week, real scarcity (still inert) and Component B for the War Room. It measures what the local run cannot: the
persisted-DB coverage of free-agent ids (does `persisted_players_meta` return `None` because some free agent is
absent, F5), the actual `uncertain` / `unknown` rates, real latency, and the stability series above. The result
is recorded as aggregate counts only.

## 10. Exact production impact surface (if activated; owner approval required)

All private. The flag changes **no value on any board**; it changes the replacement level the following
*recommendations and diagnostics* are computed against.

| surface | what changes | how |
|---|---|---|
| Trade Calculator Team Context (`/api/trade/simulate`) | `rosterCapacity.forcedDrops[].effectiveCutCost`, `waiverValue`, and the charge for an unpriced forced drop; under the legacy selection rule also **which** player is cut (ECC order) | lower anchors make players valued between the new and old anchor have positive ECC |
| War Room (`/api/trade/analyze`, `/api/trade/analyze-multi`) | `objectiveValue.forcedReleaseCost`, the `forced_drop_unpriced` evidence gap outcome, and therefore private-decision categories on trades whose forced cut is unpriced or ECC-ordered | through the simulator |
| Trade Finder (Team Context ON), Best Offers, package builder | `rankingFactors.forcedDropCost` and therefore ranking order and top-20 overlap; filters nothing | `forced_drop_cost` |
| Angle (`/api/angle/*`), Suggestions | capacity annotations (`rosterCapacity` blocks); no filtering | annotation only |
| Perfect Draft (`/api/draft/roster-context`, client, auction advice) | `waiverValues` (every position), `waiverLadder` (`W(k)`), cut-ladder rung order and **which rungs ship**, `assumedWaiverRungs`, rookie surplus, MaxBid and plan, `ladderExhausted`; PD in August is banding-only (F4) | server payload the client reads unchanged |
| Droppability / roster intelligence | cut ladder, `waiverValues`, `waiverPopulation`, `undroppable` order | same builder |
| Perfect Waivers | cut **prices** unchanged (no anchor); `requiredStartersToday` / `undroppable` list contents can shift (capacity counts do not) | via the ECC-ordered ladder |
| **Unchanged** | all `rankDerivedValue`, ranks, tiers, confidence, trade values, Value Adjustment, package math, fairness bands, FAAB, BDVM, rankings, public `/league`, public advisor, trade history, scarcity multiplier (1.0) | asserted by test |

**Direction and size, from the research (reference only, pre-#1890 and capacity-style population):** anchors fall
at every position (DB -402, DL -106, LB -203, QB -513, RB -124, WR -219, TE -292); forced-drop charges move on
a minority of trades (4 of 12 teams in the neutral scenario); Perfect Draft recommends more rookies with positive
surplus at every IDP position. No number in this section is an approval figure; §9 replaces them.

## 11. Owner decisions (all PENDING)

Format: **Recommended**, **Default if unanswered**, **Answer text** (ready to paste). Implementation of any
phase beyond P0 is not authorized until the owner answers D2.

**D1. Which question does the replacement level answer?** PENDING.
- Options: (A) this-season lineup replacement, health-filtered; (B) dynasty-asset opportunity cost, no health
  filter; (C) leave as is. Consequences in §5.
- **Recommended:** A, with B kept as a named, non-served shadow lens for comparison.
- **Default:** C (flag stays OFF).
- **Answer text:** "D1: Option A. The replacement level answers this-season lineup replacement for every
  roster-capacity, droppability and Perfect Draft consumer. Keep Option B only as a named shadow lens in the
  replay; it is not served."

**D2. Authorize implementation of the consolidation behind a default-OFF flag?** PENDING.
- Authorizes P1-P3 only (owner API, population builder, wiring behind
  `replacement_level_li5_consolidation`), not activation. P3 starts only after #1890 merges.
- **Recommended:** yes.
- **Default:** no implementation.
- **Answer text:** "D2: Authorized. Implement P1-P3 as designed in
  docs/valuation/LI5_REPLACEMENT_CONSOLIDATION_DESIGN_2026-10-21.md behind a default-OFF flag. Do not activate."

**D3. Reconcile the V1-29 boundary: share the algorithm, keep the units apart?** PENDING.
- LI-5 stays the single level owner, called with a caller-selected value field; displacement becomes an
  ADAPTER; census row A's unit and C2 chain §3 are edited in the same PR.
- **Recommended:** yes (the alternative is leaving the manifest's `C2-REPL-01` open indefinitely).
- **Default:** no consolidation; D2 cannot proceed past P0.
- **Answer text:** "D3: Approved. Replacement level has one algorithm owner (LI-5) used in two currencies;
  displacement consumers use rankDerivedValue, the gameplan call keeps rosValue, and the V1-29 census and C2
  chain are updated to say so."

**D4. Band width.** PENDING.
- Keep LI-5's `DEFAULT_BAND = 2` (mean of ranks 1-3), the rule #1888 tested; alternatives are the 3rd-best
  healthy player (A2: DB 1,436; 3/35 starters below) and the best-ball-starter floor (A5: DB 1,384; 2/35), both
  much lower and more disruptive, and neither is a waiver concept.
- **Recommended:** keep the LI-5 constant, no new knob.
- **Default:** same.
- **Answer text:** "D4: Keep LI-5's existing band (mean of free-agent ranks 1-3). No new constant."

**D5. Population and health semantics.** PENDING.
- (i) Replacement candidates are the waiver add pool (`waiver_candidate_exclusion`, as-is) intersected with
  availability: `available` and `uncertain` stay, `unavailable` and `unknown` are excluded, health not applied
  when the league week is unknown; (ii) the alternative is health only, ignoring the add-pool gates
  (`single_source`, 500 floor, rookie gate); (iii) a no-NFL-team player is reported `available` by the existing
  owners (F3) and is handled only if the replay shows one reaching a top-3 slot, by a new reason code in the
  add-pool owner (a separate decision).
- **Recommended:** (i); sensitivity of excluding `uncertain` reported in the replay.
- **Default:** (i).
- **Answer text:** "D5: Approved as (i). Candidates are add-pool-eligible players whom the availability owner
  reports available or uncertain. Report the sensitivity of excluding uncertain. Do not add a no-team rule
  unless the replay shows it affects an anchor, and bring that to me separately."

**D6. Keep each consumer's existing population?** PENDING.
- Capacity: no auction-rookie exclusion; Perfect Draft and droppability: auction rookies excluded. The
  alternative is unifying (which would silently change one of them).
- **Recommended:** preserve the rostered and auction-rookie unavailable-key populations of each consumer. The
  add-pool gates (`waiver_candidate_exclusion`: value floor, `single_source`, `rookie_gate`, position set) and the
  health filter (D5) are the intentional new population rules and are part of this change's effect; they truncate
  the ladder tail (§4.4 step 3) and the replay reports an "add-pool only" step separately from the health step.
- **Default:** preserve.
- **Answer text:** "D6: Preserve each consumer's current rostered and auction-rookie unavailable-key populations; prove it by
  test. The add-pool gates and the D5 health filter are the intended population changes. Any other change to who
  counts as a free agent is a separate decision."

**D7. Sequencing relative to the forced-drop correction (#1890).** PENDING.
- P1-P2 may proceed now (no shared files). P3 starts after #1890 merges. Activation is evaluated against a
  recorded #1890 baseline and is **not** stacked in the same release; #1890's `bound: "upper"` unpriced-charge
  label is corrected when this flag is ON (F6).
- **Recommended:** as stated.
- **Default:** as stated.
- **Answer text:** "D7: Approved sequencing. P3 waits for the forced-drop correction to merge; the two
  activations are separate releases with the first recorded as the baseline."

**D8. Scarcity stays out of this change.** PENDING.
- The consolidation must leave the scarcity multiplier at 1.0 and must not supply free agents to the gameplan
  LI-5 call. Activation is a separate decision (§12).
- **Recommended:** yes.
- **Default:** scarcity inert.
- **Answer text:** "D8: Confirmed. This change must keep the scarcity multiplier inert at 1.0. Scarcity
  activation is a separate future decision."

Not asked here: approval of the production impact (that is P4, on the replay's numbers); any IDP value or
weight change (prohibited); the DB league-scoring hypothesis (evidence collection only); FAAB's pool.

## 12. Scarcity activation (not part of this change)

Today the multiplier is inert because `gameplan.py:517` calls LI-5 without free agents, so there is no waiver
tier, `waiver_scarcity` is `None` and `scarcity_multiplier` returns 1.0 (§2.3). The consolidation above feeds
free agents to a *market-currency* level used by displacement and **never** to the gameplan call, and §4.3
shows a market-currency waiver tier cannot be combined with the `rosValue` best-ball floor. So nothing here
turns scarcity on, and a test pins that (§8 item 6).

Activating it is an independent owner decision. It would need:

1. a `rosValue`-currency free-agent tier for the gameplan bundle's LI-5 call, with the **same population and
   health rules**, and ROS coverage of unrostered players (unverified: `rosValue` for free agents comes from the
   ROS board, and a free agent with no ROS read must be excluded, never zero);
2. the measured distribution of `waiver_scarcity` per position, so the owner sees the range of the 0.85-1.15
   multiplier it would apply to every cut cost (#1888 says wire depth is high at DB, so it would sit near 0.85
   there and near 1.15 where the wire is thin);
3. #1890's box replay **with real scarcity** (its own activation checklist item 3), because the multiplier is
   one-sided under its V5 charge and enters V5-R selection on both sides;
4. its own default-OFF flag (reserved name `replacement_scarcity_activation`), its own byte-identity test and
   its own §10-style impact statement;
5. an explicit owner decision on whether the multiplier is wanted at all: `src/roster_intel/targets.py`
   carries the same formula for the add side, so the choice affects both sides of the roster.

It must not switch on as a side effect of the consolidation. #1888 §9 recommendation 2 ("either record
`scarcity multiplier intentionally inert`, or let LI-5's free-agent tier feed it") remains open; this document
recommends recording it as intentionally inert in the displacement and gameplan owners as part of P3 (a comment
and the pinned test), and leaves the other option to the owner.

## 13. Engineering-reliability applicability check

Against `docs/engineering/ENGINEERING_RELIABILITY_PRIORITIES_2026-09-06.md`; only mechanisms plausibly relevant.

| # | mechanism | disposition | note |
|---|---|---|---|
| 1 | external-source deterministic replay | **APPLY_NOW** | pinned board plus pinned aggregate players-status snapshot; no network in the request path or the replay |
| 2 | typed API contract spine | **APPLY_NOW** (minimal) | additive `replacementPopulation` block with a contract test and a `CONTEXT_VERSION` decision; no wider typing work |
| 3 | reproducible dependency / artifact identity | NOT_RELEVANT | no dependency or build change |
| 4 | property and mutation testing | **APPLY_NOW** | seeded property loops for the owner API (no Hypothesis dependency in the repo); a targeted mutation of the band index must fail the parity test |
| 5 | progressive typing | ALREADY_COVERED | new modules carry annotations under the existing ratchet |
| 6 | observability and SLOs | **APPLY_NOW** (bounded) | stamp population, health evidence age, positions without a level; measure latency in the replay. New SLO infrastructure is DEFERRED_BY_AUTHORITY |
| 7 | frontend performance | NOT_RELEVANT | no frontend change |
| 8 | agent evals | NOT_RELEVANT | |
| 9 | faster CI | NOT_RELEVANT | path-aware L2 already covers it |
| 10 | architecture boundaries | **APPLY_NOW** | import-boundary test (draft layer must not import `src.trade.waiver` at module level) and the AST single-owner guard |
| 11 | supply-chain security | NOT_RELEVANT | |
| 12 | SQLite migration ownership | NOT_RELEVANT | no persistence |

## 14. Limits and UNRESOLVED

**Limits of this document.** No board was built and no code was run; all behavioural claims are from reading
`main@7dd8cb048`, #1888 and #1890. The `sourceCount` of the DL/LB anchor setters (review caveat 4) is
**unverified** (F2); static reading settles only that `rookie_gate` is irrelevant in-season and that
`single_source` is the gate that could matter. Whether the capacity and Perfect Draft anchors differ today (F1)
is likewise unmeasured. The #1888 figures cited are on a pre-#1890, capacity-style, 2026-10-20 snapshot and move
with statuses.

STATUS: PARTIAL (design complete; no decision made, nothing implemented)

ACCEPTANCE: an implementation-ready design covering the single-owner API, the thin displacement consumer, the
currency choice, health via existing owners, banding, a phased plan with explicit #1890 dependency and file
collisions, a flag and rollback, a test plan, activation evidence, the exact production impact surface, an owner
decision list with answer text, a separate scarcity section, and the reliability applicability check.

EVIDENCE: read of `src/draft/displacement.py`, `src/draft/context.py`, `src/draft/rookie_pool.py`,
`src/league_intel/replacement.py`, `src/api/gameplan.py`, `src/trade/roster_capacity.py`,
`src/roster_intel/droppability.py`, `src/trade/waiver.py`, `src/ros/availability.py`,
`src/ros/game_day_live.py`, `src/api/matchup_intel.py`, `scripts/replacement_census.py`,
`tests/roster_intel/test_replacement_owner.py`, the Perfect Draft and auction-advice frontend modules, the
#1888 record and evidence JSON, and the #1890 record and diff, all on `main@7dd8cb048` / the cited branches.

UNRESOLVED:
- owner answers D1-D8 (all PENDING);
- `sourceCount` / exclusion reasons of the DL, LB and DB anchor setters (caveat 4), and the capacity-vs-Perfect
  Draft anchor difference (caveat 5): both are replay measurements, not design questions;
- persisted-players-DB coverage of free-agent ids on the box (F5);
- whether any no-NFL-team player reaches a top-3 slot (F3);
- #1890 merge, selection-mode decision (V5 vs V5-R) and activation state, which gate P3 and P5;
- the reconciliation of V1-29 with `C2-REPL-01` (D3) changes a prior owner-adopted boundary and needs the owner
  to say so.

BLOCKERS: P3 onward is blocked by D2 and by #1890 merging. P1-P2 are blocked only by D2 and D3.

NEXT_ACTION: owner answers §11; if D2 and D3 are approved, open P1 (LI-5 `waiver_levels` extraction and parity,
census row edit) as an isolated branch with no #1890 file in its claim.
