# Competitor-Parity Roadmap (Fantasy Navigator + Play for Keeps Dynasty)

> Living roadmap for the 37-item competitor-parity effort, approved
> 2026-07-25.  Progress state: Phase 0 complete (PR #530 merged,
> DraftSharks validated live in run 30178412079, soft-flag removed);
> Phase 2+2b in PR #532; Phase 6 in PR #533; Phase 5 building.
> Remaining main-track order: Phase 3 -> Phase 4 -> Phase 7.


## Context

The user wants the site to give them every possible edge in their league (trades, waivers/FAAB, player evaluation, league-mate tendencies). Two competitor sites — FantasyNavigator.com and PlayForKeepsDynasty.com (PFK) — are the inspiration benchmark. The request is a 37-item roadmap spanning: a player search/filter system, full competitor audits + feature-gap inventory, self-audit, two new ranking/value sources (FN + PFK), TEP normalization verification, FAAB formula optimization with league-wide budget awareness, PFK-style Sleeper intelligence (cross-league exposure, buy/sell tendencies, Sharp Tracker), and a real player-news system with a News tab.

This is a multi-week roadmap, not a single change. The plan below sequences it into phases with the audit deliverables gating the big implementation waves.

## Already known from this session (no re-investigation needed)

- **Item 10 (DLF RK / Flock RK "expected but did not match") — ROOT CAUSE FOUND AND FIX DRAFTED.** `_expected_sources_for_position` in `src/api/data_contract.py` never pruned rookie-class-only sources (`needs_rookie_translation`) for veteran players, so every vet inside their depth window showed the two rookie boards as "expected but did not match" on the Source Audit panel (screenshot: Colston Loveland). Fix (already in the working tree, uncommitted): rookie-translation sources are expected only for `is_rookie` non-pick rows. Needs: unit test + inclusion in PR #530 or follow-up.
- **Items 11-18 (TEP correctness) are substantially DONE as of today's calculation audit**, which verified: single application (backend blend only, frontend renders stamps), per-source `is_tep_premium` flags, KTC exemption, native (1.10) vs non-native (1.15, slider-clamped [1.0,1.5]) multipliers, league auto-derivation from `bonus_rec_te`. Remaining for this plan: stamp the TEP decision for the two NEW sources (FN, PFK — both declared by the user as NOT TEP-aware → `is_tep_premium: False`, non-native multiplier applies) and add a registry-completeness test that every source declares the flag explicitly.
- **New-source integration pattern (exact touchpoints, proven twice today with fantasyCalc/otcffbSf):** fetcher script in `scripts/fetch_<x>.py` (competition ranks for ties), `_SOURCE_CSV_PATHS` (signal: rank vs value), `_RANKING_SOURCES` registry entry (+ derived `is_rank_signal`), `frontend/lib/dynasty-data.js` RANKING_SOURCES mirror, `config/source_staleness.json`, `_SOURCE_MAX_AGE_HOURS`, row floors, `scheduled-refresh.yml` run_fetcher step, parity/completeness tests. **Item 7's "rank and value as separate data points" maps directly onto existing architecture:** value loads into `canonicalSiteValues` (display/trade-finder) while `signal: "rank"` drives the blend vote — same as dynastyDaddySf today.
- **In-flight: PR #530** (13 commits: rank-signal conversions, DraftSharks activation chain, caution de-saturation, calculation-audit fixes F-1..F-5+cleanup). Two Codex round-11 findings are still unaddressed (already-active DS path needs a worker-settle wait; tooltip trim-note count must subtract Hampel-dropped keys on legacy payloads). Pending sequence once merged: dispatch scheduled refresh → validate DraftSharks live → remove soft-flag → dispatch Hampel audit.

## Phase 0 — Land the in-flight work (prerequisite)
1. Implement the two Codex round-11 fixes + the item-10 rookie-expectation fix (+ unit test).
2. Merge PR #530 once CI is green (user already directed the DS-fix/Hampel-audit sequence).
3. Dispatch scheduled refresh → verify DraftSharks live → remove `draftSharks` soft-flag → dispatch Hampel audit → confirm green.

## Phase 1 — Audits (deliverables: 3 reports)  [items 2,3,4,5,36]

### Self-audit inputs (exploration complete — key facts)
Our site is already deep: 20+ authed pages + a 24-sub-tab public league hub. Highlights relevant to the gap analysis:
- **Already have** (maps to several "add" items): per-manager trade tendencies table (`frontend/lib/league-analysis.js::analyzeTradeTendencies`, rendered on `/trades`), retro trade grading ("aged well/poorly" via rank history), exploitable-team edge map (`buildLeagueEdgeMap` on `/rosters`), win-now/rebuild team phases + partner matching (`/league/phases`), counter-pitch package builder (`/angle`), KTC arbitrage finder (`/finder`), Monte Carlo trade sim, buy/sell/hold signal engine (`frontend/lib/signal-engine.js`), portfolio insights with volatility exposure, public per-player journey pages (`/league/player/[id]`).
- **News backend already real**: `server.py::/api/news` + `src/news/service.py` with providers (sleeper, espn, cbs, fantasypros, rotowire, dynasty RSS). Frontend `news-service.js` falls back to `mock-news.json` on failure. News surfaces in 3 places (activity feed, terminal TeamNewsFeed, 📰 chip on rankings rows) but **no top-level News tab** and no news section on the player popup beyond the chip.
- **Confirmed data gaps** (block item 1 filters): `row.team` (NFL team) is stamped but **0/1077 populated** (scraper never writes it; needs Sleeper-metadata enrichment in the contract build); `years_exp` exists in the legacy dict (`_yearsExp`, 770/1077) but is **never mapped onto rows** (only its `rookie` derivative); fantasy-team owner exists only via client-side join from `sleeper.teams` (pattern already in `PlayerPopup.jsx:358` via `buildTeamByPlayer` from `frontend/lib/waiver-logic.js`); `age` present (87%).
- **Search today**: `GlobalSearch.jsx` (name substring only, `/` hotkey) + rankings filters (position pills incl. rookie-splits, confidence, 5 lenses, sortable columns). No age/team/owner/experience/rank-range filters anywhere.
- **Missing entirely**: cross-league exposure (multi-league support is one-active-league registry switching only), sharp-money/league-member-accuracy tracking (zero hits repo-wide).

### Deliverables
1. Competitor feature inventories (FN + PFK) — from agent C probe + follow-up fetches during implementation.
2. Gap matrix: every FN/PFK feature × {Have / Have-but-improve / Add / Overlaps / Build-better}, cross-referenced against the self-audit inventory above.
3. Self-audit fix list: broken/stale/low-value features (seed: mock-news fallback masking backend failures; `team` field dead; `/draft-capital` legacy redirect; `_tier_id_from_rank` fallback duplication is fine).
4. Ranked backlog (league-edge value ÷ effort).

## Phase 2 — Two new sources: Fantasy Navigator + PFK  [items 7,8,9,13-18]

**Data acquisition (probe-verified, both public/unauthenticated):**
- **Fantasy Navigator**: single JSON GET `https://fantasy-navigator-latest.onrender.com/ranks?platform=sf` → rows `{player_full_name, player_rank, player_value, roster_type: sf_value|one_qb_value, rank_type: dynasty|redraft, age, team, ktc_player_id, is_rookie}`. Use `roster_type=sf_value` + `rank_type=dynasty` rows. **Caveat to document**: FN values carry `ktc_player_id` and are KTC-derived — partially correlated with our ktcSfTep vote; the count-aware blend + Hampel tolerate this, but note it in the registry comment. Freshness: dynasty rows update ~monthly (`_insert_date`) → `_SOURCE_MAX_AGE_HOURS: 720`.
- **PFK**: item 8's per-profile assumption is obsolete — the profile's dynasty value comes from one Supabase PostgREST table readable anonymously with the site's own embedded publishable key: `pfk_dynasty_rankings` → `{sleeper_player_id, rank, tier, value, player_name, position, team, kind, pick_year/round}` (players AND picks in one table; PFK's own hand-maintained board, distinct signal from KTC). One request per refresh cycle — polite, same 2h cadence as other fetchers. (Their `pfk_ktc_values` table is just a KTC SF-TEP mirror — skip it; we already have KTC.)
- **Player matching**: PFK rows carry `sleeper_player_id` → match via the existing Sleeper-ID identity map (`src/identity/`), stronger than name matching. FN rows carry `ktc_player_id` + names → name-normalize like other fetchers.

**Integration (proven pattern, per source):** `scripts/fetch_fantasynavigator.py` + `scripts/fetch_pfk.py` (competition ranks for ties) → CSVs `name,value,rank` (+ sleeper_id column for PFK) → `_SOURCE_CSV_PATHS` (start `signal: "rank"` — decide value-direct only after a distribution check like FC/OTC; both are KTC-adjacent decay shapes, so rank-signal is the safe default) → `_RANKING_SOURCES` entries (`is_tep_premium: False` for BOTH — user-confirmed neither is TEP-aware, so the non-native 1.15 TE multiplier applies) → frontend registry mirror + `isRankSignal` → staleness config, max-age, row floors (~75% of observed rows) → `scheduled-refresh.yml` run_fetcher steps → parity/completeness tests. Values land in `canonicalSiteValues` (separate data point: display, trade-finder, per-source winner) while rank drives the blend — exactly item 7's rank/value separation.
- Item 9 (values flow everywhere) is then automatic: consensus, trade eval, compare, waivers, FAAB all read the blended contract.
- **Registry TEP flag test** (items 13-17): add a test asserting every `_RANKING_SOURCES` entry declares `is_tep_premium` explicitly, and a documented per-source scoring-format table (standard/TEP/configurable/unknown) in the registry comments.

## Phase 3 — Player search & filtering system  [item 1]

**Prerequisite data work (backend):**
- Populate `team` (NFL team) in the contract: enrich rows from Sleeper player metadata during the contract build (the field + `REQUIRED_PLAYER_KEYS` slot already exist in `src/api/data_contract.py:7468`; only the write is missing). Sleeper's players blob (already ingested for age/positions) carries `team`.
- Stamp `yearsExp` on playersArray rows + legacy mirror (source: `_yearsExp` already in legacy dict) and map it in both materializers in `frontend/lib/dynasty-data.js`. Derive experience bucket: rookie (0), sophomore (1), vet (2+).
- Add `ownerTeam`/`ownerId` join availability: reuse `buildTeamByPlayer` (`frontend/lib/waiver-logic.js`) at `buildRows` call sites rather than stamping owner into the contract (owner is league-scoped; contract rows are scoring-profile-scoped — CLAUDE.md split).

**Frontend:** extend `/rankings` filter rail + `GlobalSearch`:
- Structured filters: position (exists), confidence (exists), lens (exists) + NEW: age range, experience bucket (Rookie/2nd-year/3+ years), NFL team dropdown, fantasy-team owner dropdown (incl. "Free agent"), consensus-rank range, value-band, tier, market-edge direction, rookie flag, watchlist-only.
- Search upgrades: token matching over name + NFL team + position + owner ("WR CHI", "owner:Jason").
- Keep `buildRows` pure — all filtering stays client-side over materialized rows (fast: ~1.1k rows).
- Reuse: `POS_FILTERS`/`CONFIDENCE_FILTERS` pattern (`app/rankings/page.jsx:55,74`), `applyLens` (`frontend/lib/edge-helpers.js`), FilterBar wrapper component.

## Phase 4 — FAAB optimization  [items 19-23]

**Current state (explored):** `recommend_faab` (`src/trade/faab_recommender.py:144`) = baseline pct-of-budget (`waiver.py:80`) × value-gain modifier × trending kicker × league position-bid calibration × KTC crowd blend × floors × own-team cap. Confirmed gaps vs the user's requirements:
- Other teams' balances/spent: available per team in `sleeper.teams[].faabRemaining/faabUsed` (`sleeper_overlay.py:392`) but never read by the recommender.
- `teamAggression[ownerId] = {totalSpent, avgBid, winningCount, maxBid}` computed in `faab_analytics.py:246` but **has no consumer** — ready-made input.
- Trending kicker input `latest_contract_data["sleeperTrending"]` is **never written** anywhere — dead input; must wire `/v1/players/nfl/trending/add` (endpoint confirmed reachable; already used by `src/news/providers/sleeper.py`).
- **Sleeper has NO public "suggested FAAB" field** (docs grep confirmed; only historical `waiver_bid` on transactions). Item 23 re-framed: our "market anchor" = league bid history (already wired) + trending velocity + optional cross-league observed bids later. Tell the user this explicitly.
- Failed bids invisible (Sleeper API limitation, documented in code) — contention model must infer from winning bids + trending.

**Design (v2, validated by design review — sealed first-price auction policy: bid the minimum that clears the expected top rival, never above value):**
1. **New module `src/trade/faab_contention.py`** — `estimate_rival_bids(...)`: per opponent, `exp_bid = min(base_bid × agg × need_f × intel_f, base_bid × 2.5) × 1.15 safety`, capped by their `faabRemaining`. `need_f` ∈ {need 1.0, neutral 0.55, surplus 0.25} via `analyze_roster`; `agg = clamp(their avgBid / league median winning bid, 0.5, 2.0)` requiring `winningCount ≥ 3` else 1.0 + lowSample flag (winning-bid selection bias is irreducible — present as estimate, not prediction); `intel_f` from Phase-5 snapshot (1.25 player-level / 1.10 position-level / 1.0). `clearing = topRival + 1`.
2. **Replaceability gate** (fixes systematic overpay): `dropoff = (add_value − next_best_same_pos_FA) / add_value`; chase clearing only when `dropoff ≥ 0.15`, else pure value bid + "replaceable" factor. Ceiling = `aggressive × (1 + 0.5×clamp(dropoff,0,0.5))`; if clearing > ceiling → stop at ceiling + "likely outbid" warning.
3. **Budget-environment scaling**: `env_scale = clamp((league median winning bid / budget) / 0.08, 0.6, 1.6)`, requires ≥10 analyzed bids, applied ONLY when `positionBids[pos].count < 3` (else it double-counts the existing position calibration — review-caught bug).
4. **Wire the dead trending input**: new `src/adapters/sleeper_trending.py` TTL-cached adapter (mirror `_PlayerMapCache` in `src/news/providers/sleeper.py`), warmed in `_warm_overlays_in_background`; primary over the never-written `sleeperTrending` key.
5. **Endpoint threading** (`server.py::post_waiver_faab_recommend`): opponents from `sleeper_teams` (all have `faabRemaining`); `teamAggression` filtered to CURRENT ownerIds (departed-owner drift); next-best-FA tracked in the existing pool loop; no `teamOwnerId` in body → skip contention with explicit missing factor (never guess which team is the user's). Response adds `contention{clearing, topRival, perOpponent}`, `inputsAsOf{rosters, leagueAnalytics, trending, intel}`, `staleInputs[]`, pacing warning when standard > 40% of remaining — additive keys only (backward compatible).
6. Freshness (item 21): recompute per request; overlay cycle picks up FAAB spends ≤ ~15 min; staleness stamps make the as-of visible.
7. Tests: `tests/trade/test_faab_contention.py` + extensions — 14 enumerated cases (clearing raise/cap, ceiling stop, dropoff gate, low-sample default, agg clamp, no-owner skip, all-broke rivals, env-scale on/off + double-count regression, intel precedence, 2.5× stack cap, pacing, endpoint compat, adapter TTL).

## Phase 5 — Sleeper intelligence (PFK-style) + Sharp Tracker  [items 24-29]

**How PFK actually does it (probe-verified):** hybrid — live client-side calls to Sleeper's public API for current state, plus their own scheduled server-side scrape of a large league pool into Supabase (`sleeper_trades`, `sleeper_leagues_pool`, `scraper_runs`), pre-aggregated into materialized views (`sharp_asset_summary`: buy/sell/net/volume over 48h/7d/14d/30d windows + league_count; keyed by Sleeper player_id). Their "sharp" = curated set of successful managers' accounts. All reads are public/unauthenticated.

**Our equivalent (design-review validated; all Sleeper endpoints public/reachable):**
1. **New module `src/intel/`** — `crawler.py` (`crawl(member_ids, season, prev_state, budget=900, sleep_s=0.12)`), `aggregate.py` (`build_asset_summary` — windows 48h/7d/14d/30d computed at read time; `trend_score = 3×net48h + 2×net7d + 1×net30d`), `store.py` (atomic write `data/intel/snapshot.json`, pattern `snapshot_store._atomic_write_json`; prune events to 45d), `service.py` (`refresh_intel` with process lock).
2. **Bounded crawl (review-corrected math)**: dedupe leagues across members (per-member cap 25, `truncated` flag) → league metadata comes free with the leagues-list call; incremental transactions via `fetchState[leagueId] = {maxCreatedSeen, boundaryTxIds}` fetching only the current week (+prev within 48h of rollover), dedup by txId — handles the offseason all-tx-in-week-1 degeneracy. First-run backfill: walk back ≤6 weeks or 30 days. Steady state ≈ **310 calls/run**; hard budget 900, single-threaded, 0.12s sleep, resumable round-robin. Identity: key on `owner_id` (global user_id, stable — authority comment in `sleeper_overlay._league_rid_lookup`); match co_owners; skip orphaned rosters.
3. **Endpoints** (`server.py`): `GET /api/intel/summary`, `/api/intel/player`, `/api/intel/member/{ownerId}`, `POST /api/intel/refresh` → **202 + daemon thread** (multi-minute crawl can't run inline), `GET /api/intel/refresh/status`.
4. **Cron**: NEW `.github/workflows/intel-refresh.yml` (daily + workflow_dispatch), warmup-style: POST the refresh endpoint, poll status ~6 min, idempotent failure issue (label `intel-stale`) — deliberately NOT bolted onto scheduled-refresh.yml (failure isolation; no fat snapshot commits to git). Accepted tradeoff: prod-disk snapshot lost on box rebuild → next run backfills (same as data/public_league/).
5. **Sharp Tracker v1 surfaces** (items 28-29): `frontend/app/intel/page.jsx` (asset table by trendScore, member exposure drill-down, staleness banner); PlayerPopup intel section ("4 league-mates hold him in 11 leagues; net +5 adds this week"); suggestions opponent-fit boost when that owner is net-buying the position cross-league (seam at `_opponent_fit_label`); FAAB `intel_f` (plain dict lookup — FAAB has zero crawler import dependency). Keep intel inside this private app (courtesy: it reads other users' public data).
6. Tests: `tests/intel/` — crawler (dedupe, cap, budget-exhaustion resumability, sleep, co-owner, isolation), incremental (boundary ties, offseason dedup), aggregate (window edges, trade add+drop pairing, trendScore), store (atomic, corrupt-load, pruning, failed-member data preservation), endpoints (202/alreadyRunning/staleHours).

## Phase 6 — News system + News tab  [items 31-35]

The backend already aggregates real news (`src/news/service.py`, providers: sleeper, espn, cbs, fantasypros, rotowire, dynasty-focused RSS; 180s cache, dedupe). Work is therefore mostly surface + linking + sources, not a new system:
1. **News tab**: add `/news` page + PRIMARY_NAV entry (`frontend/app/AppShellWrapper.jsx:36`), rendering the existing `useNews()` stream with filters (scope: My roster/League/All — reuse `TeamNewsFeed` logic; player/team/position filters; source filter).
2. **Player linking hardening**: today `useNews().byPlayer` maps name→latest item. Extend to all items per player + fuzzy name matching via `_canonical_match_key` equivalents; attach a News section to `PlayerPopup.jsx` (full list, not just the chip) and to `/league/player/[playerId]`.
3. **New providers**: PFK articles (https://playforkeepsdynasty.com/articles — likely RSS or HTML list; add `src/news/providers/pfk.py` following `_rss.py` pattern); optionally team beat-reporter RSS bundles per NFL team (config-driven list).
4. **Mock fallback fix** (self-audit item): `news-service.js` masks backend failures with the 2026-04 mock fixture — change to explicit "news unavailable" state so failures are visible (fail-fast convention like buildRows).

## Phase 2b — Rank+value separation fix (prereq for item 7, also audit follow-up)
Agent-verified: the registry comments claiming rank-signal sources keep their vendor value in `canonicalSiteValues` are **wrong** — `_parse_source_csv_cached`'s rank branch (`data_contract.py:3140-3155`) never reads `_VALUE_ALIASES`; the vendor value column is dropped. To honor "keep ranking and value as separate data points" (item 7) for PFK/FN (and retroactively FC/OTC/DD/Boone):
- Extend the rank branch to also read the value column when present and stamp it into a NEW parallel per-player map `sourceNativeValues[source_key]` (pattern: `sourceOriginalRanks`, stamped at `data_contract.py:3481`). `canonicalSiteValues` keeps the synthetic encoding (ordering machinery untouched — no blend change).
- Surface native values in the source-breakdown UI + trade-finder display where the synthetic guard currently blanks them; correct the wrong registry comments.

## Phase 7 — Implementation wave from ranked gap list  [item 37]
Execute the Phase-1 ranked backlog top-down. Already-identified strong candidates beyond Phases 2-6 (from the PFK feature list vs our inventory): Pick Projector equivalent (we have draft-capital + pick values; gap is future-pick → projected-slot mapping from team strength — `src/ros/` playoff sim gives us better inputs than PFK has), best-ball ADP ingestion (Underdog), player contracts/snap-share data (PFK's `pfk_player_contracts`, `pfk_player_season_snap_share` — nflverse has equivalents), stats tab on player popup. De-prioritized: dispersal draft tool, creators/polls (not league-edge).

### Phase 7 candidate dispositions — recorded 2026-07-27

The candidate list above is the ORIGINAL 2026-07-25 wording and is kept
verbatim so the history reads straight.  Three of its four items have
since been decided elsewhere, and re-reading the paragraph without this
table is how they got picked up again as open work:

| Candidate | Disposition | Where it was decided |
|---|---|---|
| Pick Projector equivalent | **Still open.** The one genuine net-new item here | `competitor-gap-analysis.md` §3.1 ranks it the highest-value net-new item |
| best-ball ADP ingestion (Underdog) | **Dropped** — a redraft/draft-season signal that informs no trade, waiver or FAAB decision in a dynasty superflex IDP league with an auction rookie draft, plus a new commercial-platform dependency on unverified terms | `competitor-gap-analysis.md` §6 |
| player contracts | **Demoted, not dropped** — obtainable from nflverse, but a weak dynasty signal next to snap/target share | `competitor-gap-analysis.md` §6 |
| snap-share data | **Already shipped** — `src/playerctx/` ingests the same nflverse `snap_counts` release, picks the dominant unit, joins to Sleeper ids, serves `GET /api/playerctx/player` and renders in the popup | PR #539 |
| stats tab on player popup | **Shipped** — `RealizedPointsSection` calls `GET /api/player/{id}/realized`, which existed with no caller and returned zero weeks for every player until the id-key fix | commits `22f9426d`, `4c552a8d` |

**Promoted in their place: the other half of B-5.**
`src/nfl_data/opportunity_stats.py` (313 lines), `src/nfl_data/usage_windows.py`
(198), `src/news/usage_signals.py` and `src/news/unified_signal_engine.py` are
built and tested with **zero production callers**, while
`src/api/feature_flags.py` reports `usage_signals: True` with a comment
asserting it "fires via unified_signal_engine".  Rolling snap / target /
carry share is the leading indicator of dynasty value moves — strictly
more league edge than any of the three dropped items, and it is a wiring
job over code that is already written.  See
`competitor-gap-analysis.md` §4.2 and B-5.

## Explicitly out of scope / non-goals
- Replicating PFK's thousands-league sharp pool in v1 (our pool = league members' leagues).
- Editing weights via `default_weights.json` (dead config — registry is authority).
- Public/commercial polish (site is private personal use — item 30 also means competitor-data ingestion for personal use is acceptable; keep fetch cadence polite: 1 request/source/refresh-cycle).

## User decisions (confirmed)
1. **Phase order**: sources-first — Phase 0 → 2+2b (FN/PFK sources) → 3 (search/filters) → 4 (FAAB) → 5 (intel/sharp) → 6 (news) → 1-reports alongside → 7 (ranked wave). Audit reports (Phase 1) are produced incrementally alongside, not as a blocking gate.
1b. **Execution mode (2026-07-25)**: HYBRID PARALLEL — after Phase 0 lands, the main session drives Phases 2→3→4 sequentially on the designated branch (they share `src/api/data_contract.py` + `frontend/lib/dynasty-data.js`), while two background agents build Phase 5 (`src/intel/`) and Phase 6 (news tab/providers) concurrently in isolated worktrees; their work lands as separate follow-up PRs after the main track's merges. Phases 2/3 must NOT be parallelized (hot-file conflicts); Phase 4's `intel_f` degrades gracefully if Phase 5 hasn't landed yet.
2. **Sharp Tracker v1 pool**: my league's members + all their other Sleeper leagues (schema kept extensible for a wider pool later).
3. **FAAB anchor**: derived market anchor (league bid history + trending velocity + rival budget/aggression) replaces the nonexistent Sleeper suggestion — no fragile app-scraping.
4. **Fetch cadence for FN + PFK**: every 2h with the other fetchers (simplest wiring; one request per source per cycle).

## Verification
- **Per source added**: fetcher dry-run row counts vs floors; rebuild contract locally (`build_api_data_contract`) → source appears in sourceRanks with sane drop rate (audit_dropped_sources.py < 10%); parity + completeness + trust tests green; TEP: TE rows show `tepBoostApplied` for the new sources.
- **Search/filters**: vitest for filter predicates; manual: each filter on /rankings narrows correctly; `team`/`yearsExp` coverage ≥ 85% of rows after enrichment (pin with a test like `test_data_contract_age.py`).
- **FAAB v2**: unit tests per factor (pattern: existing `tests/` faab tests); golden-case test: rival with high budget+need raises bid, exhausted-league lowers it; endpoint returns factor breakdown.
- **Intel/Sharp**: snapshot builder unit tests on fixture transactions; cron dry-run against real league (my ownerId) verifying league discovery + aggregation counts; UI renders per-player intel.
- **News**: /news renders live items with backend up; explicit unavailable-state with backend down (no silent mock); PFK provider returns items; player-linking test maps known article → player.
- **Full suite** (`pytest -m "not livedata"` + vitest) green at every merge; each phase lands as its own PR on the designated branch flow.
