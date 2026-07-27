# Competitor Gap Analysis — Fantasy Navigator + Play For Keeps

```yaml
audit_version: 1
repository: jasonleetucker-code/riskittogetthebrisket
main_sha: ae304293582b6b95e61e7ea3b55f8b46f2b912d6
timestamp: 2026-07-27T00:35:00Z
reviewed_branches:
  - main@ae304293582b6b95e61e7ea3b55f8b46f2b912d6
  - claude/redesign-r5-polish@bd0e3c9a0   # 17 ahead / 14 behind, unmerged
  - claude/league-intel-projections       # 17 ahead / 46 behind, unmerged
  - claude/league-intel-sim               # 9 ahead / 46 behind, unmerged
  - claude/e2e-r1-reconcile               # 6 ahead / 36 behind, unmerged
competitor_probe_date: 2026-07-27
competitor_probe_method: robots.txt + sitemap.xml + server-rendered HTML + published JS route table
supersedes: docs/ROADMAP-competitor-parity.md §"Phase 1 — Audits" (deliverables 1-4)
```

This document is a **snapshot of `main` at the SHA above**, not a
statement of present-tense fact. Every claim about what the product
does was re-derived from the tree tonight. Where an earlier document
(`ROADMAP-competitor-parity.md`, `CLAUDE_SESSION_AUDIT_HANDOFF.md`,
`ORCHESTRATION.md`) says something different, **this document does not
assume the earlier document was right** — two of the roadmap's three
named self-audit seeds turned out to be already fixed, and one of its
status claims was stale in the opposite direction.

---

## 0. How to read this — the four columns

The roadmap's Phase 1 was never produced, and every build phase went
ahead without it. The specific failure that creates is counting merged
code as shipped capability. This document therefore grades every
capability on four independent axes, because in this codebase they
genuinely come apart:

| Column | Question | How it was determined here |
|---|---|---|
| **Built** | Does the code exist and have tests? | File presence + `tests/` coverage |
| **Reachable** | Can a user action in the shipped UI cause it to execute? | Unbroken path: page → fetch → endpoint → module. Traced per item |
| **Used** | Is it actually being exercised? | **Largely unverifiable — see below** |
| **Correct** | Do the numbers it produces hold up? | Only where something was measured. Default is `unverified` |

**On "Used": the honest position is that we cannot measure it.** There
is no per-route analytics anywhere in the repo — no PostHog, Plausible,
GA, or equivalent (verified by grep across `frontend/`, `src/`,
`server.py`). `/api/metrics` exposes a single aggregate
`request_count`, not per-endpoint counters, and
`_request_context_middleware` (`server.py:2602`) assigns request IDs
for log correlation without persisting a route histogram. The only
usage-shaped state that exists is `user_kv` (watchlist, dismissed
signals, `activeLeagueKey`) and it lives on the production box, not in
the repo. So this document reports **`used: unverifiable`** for nearly
everything and does not launder reachability into usage. Adding a
route counter is itself a backlog item (B-14) precisely because its
absence made this column unwritable.

**On "Correct": absence of evidence is recorded as `unverified`, not
as `correct`.** Only two capabilities in the inventory have a
measurement behind them.

---

## 1. Our capability inventory

Grounded in code paths as of `ae3042935`. Organised by user-facing
surface, then by the engines behind them, then by what exists only as
Python.

### 1.1 Navigation — what the IA actually exposes

`frontend/lib/nav-model.js` is the single source of truth for the
desktop bar, mobile tabs, `/more` site map, and command palette. Two
top-level destinations (Rankings, News) plus four groups (Trade,
Roster, Intel, League) plus a System cluster. 36 page routes exist
under `frontend/app/`; 24 of them are `/league` sub-sections
(`frontend/app/league/sections/`).

### 1.2 Reachable user-facing capabilities

| Capability | Path | Built | Reachable | Used | Correct |
|---|---|---|---|---|---|
| Blended rankings board (21 sources) | `/rankings` → `GET /api/data` → `_compute_unified_rankings` | yes | **yes** | unverifiable | see §1.6 |
| Per-source override / custom weights | `/settings` → `POST /api/rankings/overrides?view=delta` | yes | **yes** | unverifiable | unverified |
| Player search + structured filters | `/rankings`, `frontend/lib/player-filters.js` (`EXPERIENCE_BUCKETS`, `FREE_AGENT_OWNER`) | yes | **yes** | unverifiable | n/a |
| Trade calculator + grading | `/trade` → `POST /api/trade/simulate` | yes | **yes** | unverifiable | unverified |
| Monte Carlo trade sim | `MonteCarloButton.jsx` → `POST /api/trade/simulate-mc` | yes | **yes** | unverifiable | unverified |
| Roster-aware trade suggestions | `/trade` → `POST /api/trade/suggestions` → `src/trade/suggestions.py` | yes | **yes** | unverifiable | unverified |
| Counter-pitch / angle packages | `/angle` → `POST /api/angle/packages` → `src/trade/angle.py` | yes | **yes** | unverifiable | **see §4.1 — known defect** |
| Trade history + retro grading | `/trades`, `frontend/lib/league-analysis.js` | yes | **yes** | unverifiable | unverified |
| Waiver add/drop analysis | `/waivers` → `useWaiverAnalysis` (client-side) | yes | **yes** | unverifiable | unverified |
| FAAB recommendation v2 (contention model) | `FaabRecommendation.jsx` → `POST /api/waiver/faab-recommend` → `faab_recommender` + `faab_contention` | yes | **yes** | unverifiable | unverified |
| News feed + News tab | `/news` → `GET /api/news` → `src/news/service.py`, 13 providers | yes | **yes** | unverifiable | n/a |
| Sharp Tracker (cross-league intel) | `/intel` → `GET /api/intel/summary` → `src/intel/` | yes | **yes** | **no snapshot verified** | unverified |
| Terminal / home dashboard | `/` → `GET /api/terminal` | yes | **yes** | unverifiable | unverified |
| Draft board + auction prep | `/draft` → `GET /api/draft-capital`, `useSleeperDraftSync` | yes | **yes** | unverifiable | unverified |
| Team strength / roster dashboard | `/rosters`, `buildLeagueEdgeMap` | yes | **yes** | unverifiable | unverified |
| Win-now vs rebuild phases | `/league/phases`, `frontend/lib/team-phase.js` | yes | **yes** | unverifiable | unverified |
| Public league hub (24 sections) | `/league` → `GET /api/public/league/*` | yes | **yes** | unverifiable | n/a |
| Per-player journey pages | `/league/player/[playerId]` | yes | **yes** | unverifiable | n/a |
| Weekly narrative articles | `/league/articles/...` → `weekly-narratives.yml` | yes | **yes** | unverifiable | n/a |
| League scoring comparison | `/league-comparison` → `GET /api/league-comparison` | yes | **yes** | unverifiable | unverified |
| Trending / movers | `/trending` → `GET /api/movers` | yes | **yes** | unverifiable | unverified |
| Source-disagreement edge board | `/edge` | yes | **yes** | unverifiable | unverified |
| "Arbitrage blotter" | `/finder` — **client-side filter over `useDynastyData()`**, see §1.4 | yes | **yes** | unverifiable | n/a |
| Rookie lab | `/idptc-rookies` | yes | **yes** | unverifiable | unverified |
| ROS projections / playoff sim | `/api/ros/*` router (`src/ros/api.py`), surfaced in `/league` ROS sections | yes | **yes** | unverifiable | unverified |
| Push notifications + custom alerts | `/api/push/*`, `/api/custom-alerts` | yes | **yes** | unverifiable | n/a |
| Multi-league switching | `LeagueSwitcher.jsx`, `config/leagues/registry.json` (**2 leagues**) | yes | **yes** | unverifiable | n/a |

### 1.3 Ingestion — measured

21 sources in `_RANKING_SOURCES` (`src/api/data_contract.py:1004`),
enumerated from the tree: `ktcSfTep`, `idpTradeCalc`, `dlfSf`,
`dlfRookieSf`, `dlfIdp`, `dlfRookieIdp`, `idpShow`, `dynastyNerdsSfTep`,
`fantasyCalc`, `otcffbSf`, `fantasyNavigatorSf`, `pfkDynasty`,
`dynastyDaddySf`, `fantasyProsSf`, `fantasyProsIdp`,
`fantasyProsFitzmaurice`, `flockFantasySf`, `flockFantasySfRookies`,
`yahooBoone`, `draftSharks`, `draftSharksIdp`.

**Both competitors are already ingested as sources** —
`fantasyNavigatorSf` and `pfkDynasty`. This audit therefore concerns
their *feature sets*, not their data.

### 1.4 Built and API-reachable, but with no UI caller

These have working endpoints. Nothing in `frontend/` calls them.
Verified by grepping the endpoint path across `frontend/` excluding
`node_modules`.

| Endpoint | Engine | Note |
|---|---|---|
| `POST /api/trade/finder` | `src/trade/finder.py` (892 lines) | **The KTC arbitrage finder has no UI.** `/finder` is a different thing — a client-side filter over `useDynastyData()` rows, self-described in its header as "the arbitrage blotter". This materially reframes F-6; see §5 |
| `POST /api/waiver/suggestions` | `src/trade/waiver.py` | `/waivers` uses the client-side `useWaiverAnalysis` hook instead |
| `GET /api/player/{sleeper_id}/realized` | `src/nfl_data/realized_points.py` | Realized fantasy points, no consumer — this is most of a "stats tab" already built |
| `GET /api/intel/member/{owner_id}` | `src/intel/` | Member drill-down; `/intel` calls `summary` and `player` only |
| `POST /api/intel/refresh`, `/refresh/status` | `src/intel/service.py` | Cron-driven (`intel-refresh.yml`) — legitimately not a UI surface |
| `GET /api/scaffold/*` (6 routes) | pipeline introspection | Ops/diagnostic — legitimately not a UI surface |
| `GET /api/metrics`, `/api/uptime`, `POST /api/test-alert`, `/api/signal-alerts/run`, `/api/custom-alerts/run`, `/api/league/articles/generate`, `/api/test/create-session` | various | Ops/cron/test — legitimately not UI |

The first three rows are the real finding. The rest are correctly
non-UI.

### 1.5 Built, NOT reachable — Python with no live path

Measured with an AST import-graph reachability pass (BFS from
`server.py`, `scripts/*`, and root-level modules, resolving relative
imports; dynamic `importlib` targets checked by hand). Script kept at
`scratchpad/reach.py`, not committed.

**208 modules under `src/`. 165 reachable. 43 unreachable, totalling
~12,571 lines.**

Two corrections applied to the raw output after manual review, so the
number is defensible:

* `src/ros/sources/*.py` (5 modules, 663 lines) were flagged
  unreachable but are **dynamically imported** via
  `importlib.import_module(src_meta["scraper"])`
  (`src/ros/scrape.py:449`) from the `ROS_SOURCES` registry. They are
  reachable. Excluded from the count above.
* `src/nfl_data/freshness.py` and `src/ros/tags.py` appeared in
  name-based greps because "freshness" and "tags" are common words.
  The AST pass is the authority; both are genuinely unreachable by
  import.

The consequential clusters:

| Cluster | Lines | Status |
|---|---|---|
| **`src/roster_intel/`** — all of WS-J | **4,673** | **Zero callers.** `git grep -l roster_intel` excluding `src/roster_intel/`, `tests/`, `docs/` returns nothing at `ae3042935`. Its only consumer is its own test suite (86 + 56 passing tests). Marginal contribution, position profiles, competitive window, partner fit, target engine, package generator |
| **`src/league_intel/`** (7 of 10 modules) | **3,244** | `twin.py` (LI-8 League Twin, 254 lines) has **zero importers at all**. `adjustment.py`, `cross_market.py`, `replacement.py`, `values.py` are imported **only by `roster_intel`** — transitively dead. `calibration.py` and `config.py` have no importers. Only `scorer.py`, `sim.py`, `sim_calibration.py` are live (via `src/ros/`) |
| `src/api/chat.py` | 351 | **Half-wired.** Claude-over-your-board SSE endpoint. `frontend/app/api/chat/route.js` proxies `POST /api/chat` to the backend — but **`server.py` never registers that route** (the string "chat" appears once in `server.py`, in an unrelated comment) and never imports the module. No chat UI component exists either |
| `src/news/unified_signal_engine.py` + `usage_signals.py` | 518 | Self-described "single entry point for every BUY/SELL/HOLD decision emitted to users". Nothing calls it. The live signal path is `frontend/lib/signal-engine.js` + `src/api/signal_alerts.py` |
| `src/nfl_data/{injury_feed,opportunity_stats,usage_windows}.py` | 818 | ESPN injuries, snap/target/carry opportunity metrics, rolling usage windows. Built, gated by flags that are ON, never invoked |
| `src/canonical/confidence_intervals.py` | 252 | See §4.3 |
| `src/api/auction_power.py` | 170 | See §4.4 |
| `src/api/espn_schema_drift.py`, `src/canonical/rank_history_band.py`, `src/trade/correlation_matrix.py`, `src/utils/http_fetch.py`, `src/backtesting/harness.py` | 973 | No callers |

**This is the single most important number in the document.** Roughly
12.5k lines of tested Python — including the entirety of the WS-J
workstream and most of League Intelligence — is not reachable by any
user. A feature-parity table that counted this as shipped capability
would tell the owner he has things he does not have.

### 1.6 What has actually been measured

Two things, and only two:

1. **Trade-engine value divergence (F-6 input).** 803 assets valued by
   both engines; median board/finder ratio **0.880**; Spearman ρ 0.9626
   overall; 194 assets the finder prices that the board cannot price
   at all (91 IDP, 71 offense, 32 picks), of which 162 are players and
   not the deliberate synthetic-pick case. Source:
   `docs/CLAUDE_SESSION_AUDIT_HANDOFF.md` §17, reproducible via
   `scripts/measure_engine_value_divergence.py`. Re-verified tonight
   that the mechanism still stands: `src/trade/finder.py:303` reads
   `_finalAdjusted`; `src/trade/suggestions.py:461` reads
   `rankDerivedValue`.
2. **KTC ↔ IDPTradeCalc comparability.** 475 of KTC's 500 rows appear
   on the IDPTC board; median value ratio 1.000, p10 0.888, p90 1.054
   (CLAUDE.md, measured 2026-07-26). Relevant to §4.1.

Everything else in the valuation pipeline is `unverified` in the
`correct` column. That is not a claim it is wrong; it is a refusal to
claim it is right.

---

## 2. Competitor inventories

### 2.1 Method and its limits

Probed 2026-07-27. Polite cadence: ~13 requests total across both
sites, no crawling, nothing authenticated, no paywalled content.

| Source of evidence | What it can establish |
|---|---|
| `robots.txt`, `sitemap.xml` | The **route list** the site publishes for indexing. Strong evidence a surface exists |
| Server-rendered HTML / `<meta name="description">` | The **vendor's own description** of a feature. Strong evidence of intent, weak evidence of quality |
| Published JS route table (Vite bundle) | The **client router's** path list. Strong evidence a surface exists |

**What none of this can establish:** how well anything works, what the
UI actually shows, or anything behind a login. Where a feature's
behaviour could not be observed without an account, it is marked
`unknown` below and is **not** ranked as a build target on the
strength of marketing copy.

### 2.2 Play For Keeps Dynasty (playforkeepsdynasty.com)

PFK's `robots.txt` explicitly welcomes AI agents ("GPTBot, ClaudeBot,
PerplexityBot, etc. are explicitly welcome to read and index"). Its
`sitemap.xml` lists **22 tool/content routes** plus article pages. Its
homepage is server-rendered with a complete self-authored feature list,
which is the strongest available evidence short of an account.

| Feature | Route | Evidence | Gated? |
|---|---|---|---|
| **Sleeper Snapshot** — look up any Sleeper user: account age, dynasty leagues, trade activity, championship history, roster value rank | `/lookup` | sitemap + homepage SSR copy | Free (stated) |
| **Dynasty Rankings** — PFK master board, every position + tier | `/rankings`, `/2026-rankings` | sitemap + SSR copy | Free |
| **Custom rookie rankings** — build your own order | `/2026-rankings/custom` | sitemap | Free |
| **2027 / 2028 rookie boards** | `/2027`, `/2028` | sitemap + SSR copy | Free |
| **Sharp Tracker** — trade activity from a *curated group of successful managers*, "real Sleeper trades scanned nightly" | `/sharp-tracker` | sitemap (`changefreq: daily`) + route meta | Free |
| **Pick Projector** — project where 2027 rookie picks land using team projections for *your* Sleeper league; early/mid/late | `/pick-projector` | route meta description | Free |
| **Sleeper Control Center** — scan **all** your leagues for pending trade offers, valuable waiver targets, meaningful completed trades | `/sleeper-control-center` | route meta description | Free |
| **Dynasty Power Rankings** — rank teams by PFK value or projected regular-season scoring | `/power-rankings` | sitemap + SSR copy | Free |
| **Dispersal Draft** — pool teams from a league, run a live mobile snake draft for orphans | `/dispersal` | sitemap + SSR copy | Free |
| **Trade Finder** — type a pick or player, see every equivalent-value asset grouped by position | `/trade-finder` | sitemap + SSR copy | Free |
| **Best Ball ADP** | `/best-ball-adp` | sitemap (`changefreq: daily`) | Free |
| **Projections** — full-season player projections | `/projections` | sitemap + SSR copy | Free |
| **Players / Stats** — profiles, scoring history, game logs, sortable leaderboards | `/players`, `/stats` | sitemap + SSR copy | Free |
| **Articles / Creators** — original analysis + published creator rankings | `/articles`, `/creators` | sitemap + SSR copy | Free |
| **Data sources** page | `/data-sources` | sitemap | Free |

PFK's own summary line: *"Free, no signup required for most tools."*
**Which minority of tools requires signup is `unknown`** — the copy
says "most", and I did not create an account to find out.

Backend shape (established by prior work, re-confirmed by our live
fetcher `scripts/fetch_pfk.py`): Supabase PostgREST, read anonymously
with the site's own embedded publishable key. Tables include
`pfk_dynasty_rankings` (their hand-maintained board — the independent
signal we ingest), `pfk_ktc_values` (a KTC mirror, skipped), and per
prior probes `sleeper_trades` / `sleeper_leagues_pool` / `scraper_runs`
feeding a `sharp_asset_summary` materialized view.

### 2.3 Fantasy Navigator (fantasynavigator.com → fantasynavigator.app)

A Vite SPA with **no server-rendered content at all** — every route
returns the same 3,799-byte `index.html`. The homepage is therefore
uninformative, which is why the initial fetch attempts returned only a
title. Feature enumeration came from two public artifacts: the
`sitemap.xml` (12 URLs) and the client router's path table extracted
from the published bundle `/assets/index-Sn076l6z.js`.

Full route table, verbatim from the bundle:

| Route | Component | Inferred feature | Confidence |
|---|---|---|---|
| `/` | `LandingPage` | Marketing | high |
| `/tradecalculator` | `trade-calculator` | Trade calculator | high (sitemap + route + meta) |
| `/ranks` | — | Composite dynasty/redraft rankings | high (we ingest this board) |
| `/ratemyteam` | `RateMyTeam` | Roster grade | high (route name) |
| `/rankyourteam` | — | User-built team ranking. **Not in sitemap** | medium |
| `/username` | `UsernameView` | Sleeper username entry point | high |
| `/leagues/:leagueYear/:userName/:guid` | `LeaguesApp` | **All of a user's leagues for a season** | high |
| `/leaguesummary/:userName/:userId/:leagueId/:leagueName/:leagueYear/:leagueStarters/:leagueSize/:leagueType/:guid/:rosterType/:avatar/:rankType` | — | Per-league summary, parameterized by roster size, starters, league type, roster type (SF/1QB) and rank type (dynasty/redraft) | high |
| `/about`, `/blog`, `/contact`, `/faq`, `/how-to-guide`, `/privacy-policy`, `/terms-of-service` | — | Content/legal | high |

Two structural observations that are evidence, not inference:

* **There is no auth route in the bundle's router.** All user state
  travels in the URL (`:userName`, `:guid`, `:rosterType`). FN appears
  to be entirely account-free.
* The site's own `<meta name="description">` claims "expert composite
  rankings, **power rankings**, and sophisticated trade analysis". A
  power-rankings *route* does not exist — it is presumably a view
  inside `/leaguesummary`. **Marked `unknown`; not ranked on this
  basis.**

`robots.txt` disallows `/api/`, which was respected — the public
`/ranks` JSON on the Render host is a different origin and is already
an integrated source (`scripts/fetch_fantasynavigator.py`).

**What is `unknown` for FN:** what `/ratemyteam` actually scores,
whether `/rankyourteam` is a live tool or dead code shipped in the
bundle, and what the league summary displays. FN is ad-supported
(Google AdSense tag present in `<head>`), which weakly suggests no
paywall.

---

## 3. Gap matrix

Every competitor feature × {Have / Have-but-improve / Add / Overlaps /
Build-better}, cross-referenced to §1.

### 3.1 Play For Keeps

| PFK feature | Verdict | Our equivalent | Reasoning |
|---|---|---|---|
| Dynasty rankings board | **Build-better (done)** | `/rankings`, 21-source blend incl. PFK's own board as one vote | We consume their board as a single input among 21, with Hill-curve percentile normalization and Hampel outlier rejection. Strictly more information than their hand-maintained board |
| Custom rookie ordering | **Have** | `/settings` source weights + `/idptc-rookies` | Ours re-runs the full canonical pipeline server-side rather than reordering a static list |
| 2027 / 2028 rookie boards | **Have** | Far-future pick rows + `pick_year_discount.json` | |
| Trade Finder ("equivalent-value assets by position") | **Have-but-improve** | `/trade` + `POST /api/trade/suggestions` | We have the engine; the *interaction* — type one asset, get every equivalent grouped by position — is a genuinely better UI idea than our current flow. Cheap to add over existing data |
| **Sharp Tracker** | **Overlaps — theirs is broader, ours is more relevant** | `/intel` + `src/intel/` | Both track cross-league buy/sell from Sleeper trades. **PFK's pool is thousands of leagues filtered to a curated "sharp" list; ours is our own league-mates' leagues.** Theirs answers "what does the market's smart money do"; ours answers "what do *the twelve people I trade with* do". For league edge ours is the better question — but **PFK's curated-sharp pool is not practically replicable** (it needs a large scraped league corpus plus a maintained roster of proven managers) and should not be ranked as buildable |
| **Sleeper Snapshot** (look up any user: account age, leagues, trade activity, titles, roster value rank) | **Add** | none | We have no arbitrary-user lookup. All of the underlying Sleeper calls are already implemented in `src/intel/crawler.py` and `src/public_league/sleeper_client.py`. Genuine league edge: scouting a trade partner's cross-league behaviour before opening a negotiation |
| **Pick Projector** (project future pick slots from team projections) | **Add — and we should be better at it** | partial: `/league` draft capital + `src/ros/playoff_sim.py` | We have strictly better inputs than PFK: a real playoff simulator and ROS team strength, versus their "team projections". The missing piece is only the mapping future-pick → projected slot → value. This is the highest-value *net-new* item in the matrix |
| **Sleeper Control Center** (scan all your leagues for pending offers / waiver targets) | **Add** | partial: 2-league registry with active-league switching | Our multi-league support is one-active-league switching, not a cross-league inbox. The `sleeper.teams` overlay and pending-transaction plumbing exist |
| Dynasty Power Rankings | **Have-but-improve** | `/league` power sections, `src/ros/power_v2.py`, `src/ros/championship.py` | Ours already does championship odds; theirs offers a value-vs-projected-scoring toggle we lack |
| Projections (full season) | **Have** | `src/ros/` ROS projections, `/api/ros/player-values` | |
| Players / Stats / game logs | **Add (mostly built)** | `GET /api/player/{id}/realized` exists **with no UI caller** (§1.4); `src/nfl_data/opportunity_stats.py` + `usage_windows.py` built and unreachable (§1.5) | This is a UI-only gap over ~1,100 lines of already-written, tested Python |
| Best Ball ADP | **Drop — see §6** | none | |
| Dispersal Draft | **Drop — see §6** | none | |
| Articles / Creators | **Overlaps, no action** | `/news` already ingests PFK's article feed via `src/news/providers/pfk.py`; `/league/articles` generates our own weekly narratives | We consume their content; publishing content has no league edge |
| Data-sources transparency page | **Have** | `/tools/source-health`, `/api/rankings/sources` | |

### 3.2 Fantasy Navigator

| FN feature | Verdict | Our equivalent | Reasoning |
|---|---|---|---|
| Trade calculator | **Build-better (done)** | `/trade` + Monte Carlo (`/api/trade/simulate-mc`) + roster-aware suggestions | A 21-source blend with a distributional simulator against a single KTC-derived board is not a close comparison |
| Composite `/ranks` board | **Build-better (done)** | We ingest it as `fantasyNavigatorSf` — one of 21 votes | Note the correlation caveat already documented on the registry entry: FN rows carry `ktc_player_id` and are KTC-derived, so this vote is partially redundant with `ktcSfTep` |
| `/ratemyteam` | **Have-but-improve** | `/rosters` team strength, terminal portfolio insights, `/league/phases` | Ours is deeper. What FN has that we do not is a *single shareable grade* — a low-effort, low-edge nicety |
| `/rankyourteam` | **Unknown — no action** | — | Cannot determine what this is without running the SPA. Not ranked |
| `/leagues/:year/:user/:guid` — all your leagues | **Add (overlaps PFK Control Center)** | 2-league registry | Same gap as PFK's Control Center; ranked once, not twice |
| `/leaguesummary/...` parameterized by roster type + rank type | **Have** | League registry carries `rosterSettings`, `idpEnabled`, `scoringProfile` | Our model is richer: scoring profile drives rankings, league key drives context |
| Account-free, URL-state architecture | **Deliberately not a goal** | Owner-only auth | Private personal tool. Non-goal per roadmap |
| Power rankings (claimed in meta, no route) | **Unknown — no action** | `/league` power sections | Not ranked; could not verify the feature exists |
| Blog / FAQ / how-to | **No action** | — | No league edge |

### 3.3 Where we are ahead, and it is not close

Neither competitor has any equivalent of: IDP-native valuation with a
calibration post-pass and market-corridor clamp; a 21-source
count-aware blend with Hampel outlier rejection; per-source weight
overrides that re-run the real pipeline; retro trade grading; a
per-manager trade-tendency table; league-mate-scoped cross-league
intelligence; FAAB contention modelling against rivals' actual
remaining budgets; a Monte Carlo trade simulator; automated weekly
narrative articles; or a 24-section public league history hub. **The
gap analysis should not be read as "we are behind."** It is a list of
four or five specific interaction ideas worth stealing, on top of a
platform that is already deeper than both.

---

## 4. Self-audit fix list

Roadmap seeds re-verified first, then what this pass found.

### 4.0 Roadmap seeds — two of three are already fixed

| Seed | Status at `ae3042935` | Evidence |
|---|---|---|
| Mock-news fallback masking backend failures | **FIXED — close it** | `frontend/lib/news-service.js:11-17` now documents backend-only fetch with an explicit `{unavailable:true, reason}` state. `mock-news.json` **no longer exists** anywhere in the repo |
| Dead `team` field (0/1077 populated) | **FIXED — close it** | `src/api/data_contract.py:7761` stamps `team` from the scraper's Sleeper metadata pass, commented 2026-07-26. `yearsExp` is stamped too. Both feed the shipped `/rankings` filters |
| `/draft-capital` legacy redirect | **NOT A DEFECT — close it** | `frontend/app/draft-capital/page.jsx` is an 11-line intentional `redirect()` to `/league?tab=draft-capital` preserving old bookmarks. It is correctly absent from `nav-model.js`. Cost: one file. Leave it |

That is a 2-of-3 false-positive rate on assumed-still-true findings,
which is the reason the brief asked for re-verification and the reason
this document's own claims are dated to a SHA.

### 4.1 `src/trade/angle.py` sums two different market boards — reachable, used, and not pinned

**This is the most consequential correctness item found, because
unlike everything else in §1.5 it is on a live path.**

`_value_pair` (`src/trade/angle.py:104-133`) returns a `market_value`
read from `canonicalSiteValues["idpTradeCalc"]` for IDP rows and
`canonicalSiteValues["ktcSfTep"]` for offense rows. Package totals then
**sum those across a mixed package** (`counter_market_values` at
`:509`, `offer_market_values` at `:471-475`), and gains are computed as
percentages of the summed total (`:526`).

So the offer side of the comparison is a **two-board splice** while the
`my_value` side (`rankDerivedValue`) is a **single unified scale**. The
asymmetry is the problem.

**Being precise about how bad this is,** because the honest answer is
between the two available narratives:

* It is **not unfounded**. CLAUDE.md records a measurement — 475 of
  KTC's 500 rows also on the IDPTC board, median value ratio **1.000**,
  both boards topping out at 9999. At the median, adding them is fine.
* It is **not pinned either**. The measured decile spread is p10 0.888
  / p90 1.054 — roughly ±9% per asset. Summing four assets does not
  cancel that error, the VA adjustment does not model it, and **no test
  covers a mixed offense+IDP package's total**. In an IDP league, mixed
  packages are the common case, not the edge case.

Correct framing: `correct: unverified, with a known unmodelled error
term`. The fix is to propagate the per-asset ratio dispersion into the
package total, or to route the market side through one scale, and
then to add the missing mixed-package test. It should not be described
as a silent wrong-answer bug, and it should not be left as "measured,
therefore fine".

### 4.2 Five feature flags are ON and gate code nothing reaches

`src/api/feature_flags.py` sets these `True` with comments asserting
live behaviour. All five gate modules that §1.5 proves unreachable:

| Flag | Comment claims | Reality |
|---|---|---|
| `value_confidence_intervals` | "additive `valueBand` field on rankings contract… Frontend ValueBandBadge renders when field is present" | `stamp_bands_on_players` is **never called**. `ValueBandBadge` is **never mounted on any page** (exported from `ui/index.js`, imported by nothing). See §4.3 |
| `usage_signals` | "fires via unified_signal_engine when nfl_data_ingest supplies stats" | `unified_signal_engine` is unreachable |
| `espn_injury_feed` | "external endpoint, protected by circuit breaker… Safe to activate" | `src/nfl_data/injury_feed.py` is unreachable |
| `depth_chart_validation` | "Requires injury feed ON to cross-check" | Depends on a flag whose module never runs; `depth_charts.py` itself is reachable only from `scripts/` |
| `positional_tiers` | "Frontend TierDivider renders when tierId set" | `TierDivider` is mounted **only** on `/draft` (`page.jsx:1117`); `/rankings` uses its own inline tier logic. Half-true |

A flag registry that reports `True` for capability that cannot execute
is precisely the "check that could not fail" family this project spent
a day cataloguing. It is cheap to fix and high-trust.

### 4.3 `valueBand` means two unrelated things

`src/canonical/confidence_intervals.py` computes a statistical
confidence band from source-rank dispersion and stamps it as
`valueBand`. `frontend/lib/rankings-helpers.js` computes a **letter
grade** (S+/S/D+/D/F from raw value thresholds) also called
`valueBand`, and that is what ships. The Python one has 252 lines and a
full test file; it has never run in production. Same name, different
semantics, one of them dead.

### 4.4 `src/api/auction_power.py` is a dead "source of truth"

The Python module's docstring positions it as the authority and the
home of the unit tests. The **live** implementation is
`frontend/lib/auction-power.js`, whose own header says "JS mirror of
`src/api/auction_power.py` — the Python module is the source of truth".
The Python is unreachable from `server.py`; only `draft-capital.jsx`
and the JS mirror run. Two implementations, one exercised, drift
unguarded by any parity test — a direct violation of "prefer modifying
existing architecture over introducing parallel systems".

### 4.5 `/api/chat` is a three-quarters-built feature

`frontend/app/api/chat/route.js` is a complete SSE-preserving proxy.
`src/api/chat.py` is 351 lines of working prompt-cache-aware streaming.
`requirements.txt` carries the dependency. **`server.py` registers no
`/api/chat` route and imports no chat module**, and no chat UI
component exists. Either mount it or delete both halves; leaving it is
the worst of the three options.

### 4.6 Documentation that outruns the code

* CLAUDE.md calls `_compute_unified_rankings` "the one and only code
  path that determines live player values". `src/trade/finder.py:303`
  reads `_finalAdjusted`. Still true tonight (F-6).
* CLAUDE.md documents the `suggestions.py` / `finder.py` gate split at
  length — accurate, but it does not say that `finder.py` **has no UI
  caller**, which is the fact that determines whether any of it
  matters.
* `ORCHESTRATION.md:24` describes WS-J as "blocked on cross-market
  normalization". The merged reality is different: it is not blocked,
  it is unreachable.
* The brief this document was written against stated "Redesign R5 —
  not started". `claude/redesign-r5-polish` is **17 commits / 33 files
  / +2,419 lines** ahead of main and 14 behind, last pushed 2026-07-26
  21:37 UTC.

### 4.7 Smaller items

* `src/news/providers/` registers 13 providers; the roadmap's Phase 6
  item "add a PFK provider" is **done** (`pfk.py`, `PfkArticlesProvider`).
* `/api/waiver/suggestions` and `POST /api/trade/finder` are
  maintained, tested endpoints with no consumer (§1.4).
* No per-route request telemetry exists, which is why the `used`
  column of this document is empty.
* `/league` sections carry **48 raw `className="card"` sites** (130
  repo-wide) still awaiting the R5 phase-A Card→Panel migration. This
  count uses a different measure than the "63 of 105" figure in
  circulation; treat mine as the one that is reproducible from the
  command in this sentence, not as a correction of theirs.

---

## 5. The ranked backlog

Ranked by **league-edge value ÷ effort**, with the reasoning stated per
item rather than a fabricated score. Effort is a **band**, grounded in
what the code actually looks like:

* **S** — a focused change, hours not days; the pieces exist
* **M** — a real feature; new module or new surface, days
* **L** — multi-PR, spans backend and frontend, or needs new ingestion

No decimals, no story points. Where an item's value depends on
something unverified, that is said.

---

**B-1 · Give WS-J a user surface** — value: **highest** · effort: **M–L**

4,673 lines of tested roster and trade intelligence — marginal
contribution, competitive window, partner fit, target selection,
package generation — currently reachable by nothing but its own tests.
No other item converts so much finished, reviewed work into user-facing
edge per unit of remaining effort. An `/api/gameplan` endpoint is being
built as its first caller; the surface is the open half. Effort is M–L
only because the UI is genuinely new, not because the logic is.
*Ranked first on the ratio, not on novelty.*

**B-2 · Feature-flag and dead-code honesty pass** — value: medium ·
effort: **S**

Flip the five flags in §4.2 to match reality, or delete what they gate.
Delete or mark the ~12.5k unreachable lines in §1.5 so future audits
stop rediscovering them. Low raw value, but the effort is hours and the
failure mode it removes — a registry that reports capability the system
does not have — is the exact one that produced this document's
existence. *Highest ratio in the list.*

**B-3 · Resolve `/api/chat`** — value: medium-high if mounted ·
effort: **S**

Registering the router is a handful of lines; the proxy, the module,
and the dependency already exist. An LLM that can answer questions
against your own live board is a capability **neither competitor has**
— it is a differentiator, not parity. If it is not wanted, deleting
both halves is equally cheap. The current state costs maintenance and
delivers nothing.

**B-4 · Pick Projector — future pick → projected slot → value** —
value: **high** · effort: **M**

The highest-value net-new item in the gap matrix. Pick trading is where
dynasty edge concentrates, and future picks are the assets most often
mispriced by league-mates. We already have better inputs than PFK:
`src/ros/playoff_sim.py`, `power_v2.py`, and the draft-capital
pipeline, versus their generic "team projections". The missing work is
the mapping layer plus a surface. *This is a build-better, not a
copy.*

**B-5 · Surface opportunity metrics + a player stats tab** — value:
high · effort: **S–M**

`src/nfl_data/opportunity_stats.py` (313 lines), `usage_windows.py`
(198), and `GET /api/player/{id}/realized` are all built and tested;
the first two are unreachable and the third has no caller. Snap share,
target share, and rolling usage are the leading indicators of dynasty
value moves — this is real edge, and it is mostly a wiring job over
existing code. Covers PFK's `/players` + `/stats` and the roadmap's
"stats tab" candidate in one pass.

**B-6 · Land Redesign R5** — value: medium-high · effort: **M**

Perf, accessibility, and mobile are the quality floor for every surface
above. The branch is 17 commits deep and **14 behind main**; the cost
here is rebase-and-review, not authoring, and that cost grows daily.
Note the stated hazard: tonight's merges were squashes and rebasing
onto a merged branch has twice produced silent reverts — this needs a
`git diff --stat origin/main HEAD` check before it lands. Subsumes the
`/league` card migration (§4.7), which should not be ranked separately.

**B-7 · Sleeper Snapshot — arbitrary-user lookup** — value: medium-high
· effort: **M**

Scouting a trade partner's cross-league behaviour before opening a
negotiation is direct league edge, and it is the PFK feature with the
clearest transfer to a private tool. Every Sleeper call it needs is
already implemented in `src/intel/crawler.py` and
`src/public_league/sleeper_client.py`; the work is aggregation plus a
page. Ranked below B-5 because the data is about people, not players,
and the edge is softer.

**B-8 · Fix and pin the mixed-package market splice in `angle.py`** —
value: medium · effort: **S–M**

The only correctness item in this backlog that is on a **live, reachable
path**. Propagate the per-asset KTC↔IDPTC ratio dispersion into package
totals or route the market side through one scale, and add the
mixed-offense+IDP package test that does not currently exist. Value is
"medium" rather than "high" honestly: the measured median ratio is
1.000, so the expected error is small — but it is unbounded per package
and untested, and in an IDP league mixed packages are the normal case.

**B-9 · Cross-league Control Center** — value: medium · effort: **M**

A single inbox across all your leagues for pending offers, waiver
targets, and completed trades worth reviewing. Covers both PFK's
Control Center and FN's `/leagues` view. The registry currently holds
two leagues, which caps the near-term payoff — this earns its rank on
the day the league count grows, and should be re-ranked then.

**B-10 · Trade Finder interaction — "one asset in, equivalents out"** —
value: medium · effort: **S**

PFK's best *interaction* idea: type any player or pick, get every
equivalent-value asset grouped by position. We have all the data and
all the valuation; this is a query and a view over
`useDynastyData()`. Cheap, and it makes the board answer the question
people actually ask during a negotiation.

---

Below the top ten, in order: **B-11** decide the fate of
`src/trade/finder.py` (§5 note below) · **B-12** wire or delete
`unified_signal_engine` · **B-13** add a parity test between
`auction_power.py` and its JS mirror, or delete the Python · **B-14**
add per-route request counters so a future audit can fill the `used`
column · **B-15** a single shareable team grade (FN `/ratemyteam`
parity, low edge, low effort) · **B-16** power-rankings value-vs-scoring
toggle.

### F-6 — a recommendation the brief did not anticipate

The brief lists F-6 as a known-open item to place in the ranking. **It
should be demoted below everything above, and the migration should
probably not be done at all in its current form**, for a reason the
measurement did not surface: **`src/trade/finder.py` has no UI
caller** (§1.4). `/finder` is a client-side filter over
`useDynastyData()`; nothing in `frontend/` references
`POST /api/trade/finder`.

The 0.880 median ratio and the 194-asset coverage gap are real and
correctly measured. But they describe a divergence between an engine
users reach and an engine users do not. Migrating `finder.py` onto
`rankDerivedValue` means re-deriving `MIN_ASSET_VALUE`,
`MAX_BOARD_LOSS`, `JUNK_THRESHOLD`, `ELITE_THRESHOLD`,
`MULTI_FOR_ONE_MIN_RATIO` and deleting `SINGLE_SOURCE_DISCOUNT` — a
substantial, risky change — and it would delete 162 players from the
universe of an engine no surface calls.

**The decision that should be made first is whether the arbitrage
finder gets a UI at all.** If yes, F-6 becomes a prerequisite and
ranks near B-4. If no, delete `finder.py` and `POST /api/trade/finder`;
F-6 dissolves, CLAUDE.md's "one and only code path" claim becomes true
for the first time, and ~892 lines stop being maintained. Ranking F-6
as a valuation task before that decision is made would be spending the
effort on the wrong question.

---

## 6. Roadmap items recommended for retirement

Retiring work is a valid output. Each of these is a Phase-7 candidate
or competitor feature that should be dropped rather than ranked.

| Item | Recommendation | Reasoning |
|---|---|---|
| **Best-ball ADP ingestion (Underdog)** | **Drop** | Best-ball ADP is a redraft/draft-season signal. This is a dynasty superflex IDP league with an auction rookie draft. The ADP would not inform a single trade, waiver, or FAAB decision. It also adds a new ingestion dependency on a commercial platform whose terms were not verified — and the roadmap's own framing of "polite personal-use ingestion" is weaker ground for a betting-adjacent operator than for a hobbyist rankings site. Low edge, non-zero risk, ongoing cost |
| **Dispersal draft tool** | **Drop** | Requires an orphan-team event in a stable 12-team league. Already listed as de-prioritized in the roadmap; make it a deletion, not a backlog item |
| **Creators / polls / content publishing** | **Drop** | No league edge. We already ingest PFK's articles as a news provider, which captures the only value in it |
| **PFK-style curated "sharp" pool** | **Drop as infeasible; keep our version** | Explicitly out of scope in the roadmap, and correctly so — it needs a large scraped league corpus plus a maintained roster of proven managers. Our league-mate-scoped `/intel` answers the more useful question anyway. Recording it here so it is not re-proposed |
| **Player contracts data** | **Demote, do not drop** | nflverse carries OTC contract data so it is obtainable, but contract value is a weak dynasty signal relative to snap share and target share, which B-5 already delivers from modules that are written. Revisit after B-5 |
| **`config/weights/default_weights.json`** | **Delete the file** | Already documented as dead in CLAUDE.md ("historical documentation only — nothing loads it"). A dead config that looks live is the §4.2 failure mode in another costume |
| **F-6 as a valuation migration** | **Suspend pending a product decision** | See §5 |
| **`/draft-capital` legacy redirect** | **Keep** | Listed as a self-audit seed; it is an intentional 11-line bookmark-preserving redirect. Not a defect |

---

## 7. What this document does not establish

Stated plainly so it is not over-read later:

* **No usage data.** The `used` column is empty by necessity (§0).
  Every "reachable" claim is about code paths, not about anyone
  clicking anything.
* **No competitor quality assessment.** Route lists and vendor
  self-descriptions establish that a feature *exists*. They say nothing
  about whether it is good. Nothing here was ranked on the strength of
  a competitor's marketing copy.
* **Nothing behind a login was examined**, on either site. PFK states
  "no signup required for **most** tools"; the minority that requires
  one is `unknown`.
* **The valuation pipeline was not re-audited.** §1.6 lists the only
  two measured facts in this document. Every other `correct: unverified`
  means exactly that — not verified, not "probably fine".
* **The reachability pass is static.** It resolves imports by AST and
  was hand-corrected for the one dynamic-import registry found
  (`ROS_SOURCES`). If another dynamic dispatch exists that I did not
  find, a module listed in §1.5 could be live. The specific claims
  about `roster_intel`, `league_intel/twin.py`, and `/api/chat` were
  each additionally confirmed by direct grep.
