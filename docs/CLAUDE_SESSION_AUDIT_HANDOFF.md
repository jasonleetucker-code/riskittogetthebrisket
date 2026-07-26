# Claude Session Audit Handoff — Risk It To Get The Brisket

**Prepared:** 2026-07-26
**Repository:** `jasonleetucker-code/riskittogetthebrisket`
**Branch this document was written on:** `claude/session-audit-handoff-tvxfc1`
**Repo HEAD at time of writing:** `c534280d` (identical to `origin/main`)
**Intended audience:** an independent AI or senior engineer performing a technical + strategic audit.

---

## 0. Provenance warning — READ THIS FIRST

This document must not be read as a verbatim transcript reconstruction, because it cannot be one.

**The Claude Code session in which this document was produced began with the handoff request itself.** There is no prior visible conversation in this session's context: no earlier user messages, no earlier assistant turns, no earlier tool calls. The container was started fresh, the repository was cloned fresh, and the first user message was the request to write this file.

Therefore:

| Section | Provenance | Confidence |
|---|---|---|
| 1 (objective) | Inferred from `CLAUDE.md`, `docs/ROADMAP-competitor-parity.md`, `docs/league-intelligence/MASTER_PLAN.md`, PR bodies | Medium-high — these documents state user intent explicitly and quote user decisions |
| 2 (chronology) | **Reconstructed from repository artifacts only** — git log, merged PR titles/bodies, open PR bodies, ADRs, roadmap "User decisions (confirmed)" blocks | Medium — sequence and content are real; the *conversational* framing (what was asked vs. what was proposed) is inferred |
| 3, 4, 5, 6 (architecture, formulas, roster, trade) | **Read directly from source code at `c534280d`** with file:line references | High — verifiable by inspection |
| 7 (external inspiration) | `docs/ROADMAP-competitor-parity.md` + registry comments | High |
| 8 (agents/workflows) | `.github/workflows/`, `.agents/skills/`, `docs/ORCHESTRATION.md`, open PRs | High for files; medium for "is it working" |
| 9 (work completed) | Git diff of this branch vs `origin/main` | High — and the answer is uncomfortable; see §9 |
| 10–14 | Analysis by me over the above | Explicitly labelled as judgement |

**Where I do not know something, this document says so.** I have not invented dialogue, commit history, test results, or deployment outcomes. Every claim about repository state below was verified by reading the repository during the production of this document; every claim about *intent* is sourced to a document that records it.

An auditor should treat §2 as "how the system got here, as evidenced by what it left behind" — not "what Jason said and when."

---

## 1. Original Objective

### 1.1 The product

**Risk It To Get The Brisket** is a private dynasty fantasy football valuation and decision-support platform, built for a specific 12-team Superflex + TE-Premium + IDP dynasty league on Sleeper. It ingests ~20 external ranking/valuation sources, normalizes them onto one canonical 0–9999 value scale, and serves a web application for rankings, trade analysis, waiver/FAAB bidding, draft preparation, league intelligence, and news.

### 1.2 The problem it solves

Dynasty managers evaluating a trade today have to consult several disagreeing markets (KeepTradeCut, DynastyDaddy, FantasyCalc, DLF, IDP Trade Calculator, …), each with its own scale, scoring assumptions, and blind spots — and none of which know anything about *their* league's scoring, roster construction, or league-mates. The stated ambition is to close both gaps at once:

1. **Consensus instead of one market.** Blend many sources into a single defensible value with explicit confidence, disagreement, and provenance stamps — so a value is auditable, not a black box.
2. **League-specific instead of generic.** Reprice assets against this league's exact 141 scoring keys, 21-slot best-ball lineup, superflex + 2-TE demand, and IDP requirements — where the generic market is systematically wrong.
3. **Edge instead of information.** Turn the value board into action: trades that look fair to the counterparty on KTC but win on our board, FAAB bids that clear the actual expected top rival, waiver claims priced against replacement level, and intelligence on how league-mates behave across all their other Sleeper leagues.

`docs/ROADMAP-competitor-parity.md` states the driving requirement plainly:

> "The user wants the site to give them every possible edge in their league (trades, waivers/FAAB, player evaluation, league-mate tendencies)."

### 1.3 Target users

Primarily a **single power user (the owner) and his league-mates by invitation.** Evidence:

- Auth is an allowlist of usernames (`PRIVATE_APP_ALLOWED_USERNAMES`, default `jasonleetucker`) plus a guest-pass system (`src/api/guest_passes.py`).
- The roadmap explicitly declares "Public/commercial polish (site is private personal use)" as a **non-goal**.
- A separate public, unauthenticated surface exists at `/league` (`src/public_league/`, 24+ sub-sections) that is league-facing content — standings, matchup recaps, awards, rivalries, player journeys — i.e. a league "hub" for the other 11 managers.

So there are effectively **two products in one repo**: a private analytics terminal, and a public league-history/engagement site.

### 1.4 Expected final experience

From `docs/ORCHESTRATION.md`:

> "Target: **comprehensively functional, integrated, polished product in ~1 week** (by ~2026-08-02). Optimize for the final integrated system, not constant main-branch stability."

The intended end state is a single coherent app where every surface (rankings, player profile, trade, draft, waivers, news, intel, league hub) reads from one canonical contract, renders on one design system, and can explain every number it shows. Notably, the user explicitly **de-prioritized continuous production stability in favour of end-state quality** — a decision that is echoed in the instruction for this very document ("Do not prioritize keeping the production site continuously functional unless it is necessary to avoid data loss or blocked development").

---

## 2. Chronological Session History (reconstructed from artifacts)

**Reminder: reconstructed. See §0.** What follows is the sequence of work as evidenced by the repository, with the *decisions* quoted from documents that record them. Where I infer the conversational shape, I say "inferred".

### Stage A — Pre-existing baseline (before the reconstructable window)

The repository already contained, before any of the work below: the canonical valuation pipeline (`_compute_unified_rankings`), Hill curves, Hampel filtering, ~18 ranking sources, Sleeper overlay, trade suggestions + arbitrage finder, ROS engine, public league hub, news backend, and a large automation fleet. This is important context: **almost nothing in this project was built from scratch in the reconstructable window.** The dominant activity has been *extension and correction of an already-large system.*

Evidence: `docs/` contains dated status reports going back to 2026-03 (`scoring_adjustment_audit_2026-03-09.md`, `deploy-failure-20260323-analysis.md`, `rankings_identity_fix_2026-04-14.md`), and the contract version is pinned at `2026-03-10.v2`.

### Stage B — 2026-07-25: the competitor-parity mandate

**What was requested (as recorded):** a 37-item roadmap benchmarking the site against two competitors — **FantasyNavigator.com** and **PlayForKeepsDynasty.com (PFK)** — spanning player search/filtering, competitor audits, self-audit, two new ranking sources, TEP verification, FAAB optimization, PFK-style Sleeper intelligence, and a real news system.

**How it was interpreted:** not as a single change but as a phased multi-week program, with audit deliverables produced *alongside* implementation rather than gating it.

**Approach proposed:** `docs/ROADMAP-competitor-parity.md`, "approved 2026-07-25", sequencing Phase 0 → 2+2b → 3 → 4 → 5 → 6 → 7.

**Alternatives considered and rejected (recorded in that document):**

| Alternative | Verdict | Recorded reason |
|---|---|---|
| Audits (Phase 1) as a blocking gate before implementation | **Rejected** | User decision: "Audit reports (Phase 1) are produced incrementally alongside, not as a blocking gate." |
| Scraping PFK per-player profiles | **Rejected — obsolete** | Probe found one anonymously-readable Supabase PostgREST table `pfk_dynasty_rankings`; one request per cycle instead of thousands |
| Ingesting PFK's `pfk_ktc_values` table | **Rejected** | It is a KTC SF-TEP mirror; we already have KTC — would double-count |
| Scraping Sleeper's app for a "suggested FAAB" number | **Rejected** | Probe confirmed no such public field exists; replaced by a derived market anchor |
| Adding FN/PFK as value-direct sources immediately | **Deferred** | Both are KTC-adjacent decay shapes; rank-signal is the safe default until a distribution check |
| Replicating PFK's thousands-league sharp pool | **Rejected for v1** | Pool scoped to league members' own leagues |
| Editing weights via `config/weights/default_weights.json` | **Rejected** | Dead config; the `_RANKING_SOURCES` registry is the authority |

**User preferences captured in that document** (these are recorded as confirmed decisions, and several *override* earlier defaults):

1. Phase order is **sources-first**, not audit-first.
2. Sharp Tracker v1 pool = my league's members + all their other Sleeper leagues.
3. FAAB anchor = derived (league bid history + trending velocity + rival budget/aggression), because the "real" anchor doesn't exist.
4. FN + PFK fetch cadence = every 2h with the other fetchers.
5. Neither FN nor PFK is TEP-aware → `is_tep_premium: False` for both.
6. **Execution mode revised to HYBRID PARALLEL** (2026-07-25): the main session drives Phases 2→3→4 sequentially (shared hot files), while background agents build Phase 5 and Phase 6 concurrently in isolated worktrees. Phases 2/3 explicitly must **not** be parallelized.

That last item is the first recorded pivot toward multi-agent execution, and it is justified by *file-conflict risk*, not by throughput alone.

### Stage C — 2026-07-26: the implementation wave lands

Sixteen PRs merged to `main` on a single day. In merge order (from `git log`):

| # | Title | What it delivered |
|---|---|---|
| 533 | Phase 6: News tab, player linking, PFK provider, fail-fast fallback | `/news`, `src/news/providers/pfk.py`, removal of silent mock-news fallback |
| 535 | Phase 3: player search & filter system | `team`/`yearsExp` enrichment + filter engine (`frontend/lib/player-filters.js`) |
| 537 | Production hardening (**prepared, not applied**) | nginx/systemd/backup/monitoring configs under `deploy/` |
| 536 | Redesign R0: design tokens, component library | `frontend/app/tokens.css`, `ds.css`, `docs/DESIGN-SYSTEM.md` |
| 539 | Player context data layer | `src/playerctx/` — nflverse contracts, snap share, depth charts |
| 540 | Phase 6b: per-player ESPN news, 7-day cutoff, digests | `src/news/providers/espn_player.py`, `src/news/digest.py` |
| 538 | Phase 4: FAAB v2 — contention-aware waiver recommender | `src/trade/faab_contention.py` |
| 534 | Phase 5: Sleeper intelligence + Sharp Tracker v1 | `src/intel/`, `/api/intel/*`, `intel-refresh.yml` |
| 541 | Pick Projector | `src/ros/pick_projection.py` |
| 542 | Redesign R1: app shell, navigation IA, universal search | `AppShellWrapper.jsx`, `frontend/lib/nav-model.js` |
| 543 | E2E safety net: critical-journey Playwright suite | `tests/e2e/`, `.github/workflows/e2e.yml` |
| 544 | fix(intel): refresh workflow repo context + auth diagnostics | intel cron repair attempt |
| 546 | LI-0: coordination docs + settings audit vs live Sleeper | `docs/league-intelligence/*`, live config snapshot |
| 548 | docs: canonical orchestration plan | `docs/ORCHESTRATION.md` |
| 547 | Identity sweep: recover votes lost to name drift | identity matching audit tooling |
| 549 | Redesign R2: rankings board + player profiles | rebuilt `/rankings` + PlayerPopup on the design system |

Plus two non-PR commits worth flagging: `5536f4b9 Add GitHub Action to grant SSH access` followed ~26 minutes later by `c534280d Delete .github/workflows/grant-ssh-access.yml`. That is an SSH-access workflow that was added and then removed the same day. **I do not know the reason** — it may have been a debugging aid for the VPS, or a security reconsideration. An auditor should ask.

### Stage D — 2026-07-26: the League Intelligence mandate

**What was requested (as recorded in `docs/league-intelligence/MASTER_PLAN.md`):** a "League Intelligence Engine" spec — league-exact scoring, best-ball optimization, replacement/scarcity, league-adjusted values, simulation.

**How it was interpreted — and the first major pushback:** the plan's opening line is a correction of the spec:

> "This plan maps that spec onto the EXISTING repository — a large fraction is already built and must be audited/extended, not duplicated."

Five ADRs were recorded, each of which is a *rejection of a literal reading of the spec* in favour of extending existing architecture:

| ADR | Spec said | Decision | Why |
|---|---|---|---|
| 001 | Build a full parallel valuation system | Compute `leagueAdjustedDynastyValue` **from** `consensusValue`; leave consensus untouched | Duplicating `_compute_unified_rankings` would violate the repo's one-live-path rule |
| 002 | New canonical config, leave registry alone | **Fix the stale registry in the same PR**, with tests on every consumer | Registry contradicted live Sleeper on 8 fields — leaving it stale means two configs, one wrong |
| 003 | Implement the UI valuation toggle now | **Defer** until Redesign R2 merges | R2 agent owns the two biggest value consumers; concurrent edits guarantee conflicts |
| 004 | Write a new exact best-ball optimizer | **Audit and replace the core of `src/ros/lineup.py`** behind the same interface | CLAUDE.md rule 2: prefer modifying existing architecture |
| 005 | Define a custom stat-line schema | Use **Sleeper's own stat keys** as the event vocabulary | Sleeper's per-player weekly stats share the namespace with `scoring_settings`, making every historical player-week directly scorable |

ADR-005 was later **superseded by ADR-006** when golden validation proved there are no stacking rules to encode — Sleeper scoring is a pure dot product (1,415/1,415 player-weeks reconcile within 0.011).

**LI-0 finding that mattered most:** `config/leagues/registry.json` `rosterSettings` were **stale on 8 fields** vs. the live Sleeper API — TE 1→2, K missing, DL/LB/DB 2→3, IDP_FLEX 2→0, rosterSize 30→58, taxiSize 5→0. Consumers (ROS lineup slots, FAAB roster analysis, trade `DEFAULT_STARTER_NEEDS`) were modelling **the wrong lineup in production**. This is the single most consequential correctness finding in the reconstructable window.

### Stage E — 2026-07-26: orchestration policy is rewritten mid-flight

`docs/ORCHESTRATION.md` §2 records an explicit reversal:

> "Old mode (per-task PR, merge-on-green, ~13 merges/day) is retired."

New policy: **one branch per workstream**, PR only at integration checkpoints, two scheduled integration windows (~2026-07-29 and ~2026-08-01), reviewer runs at checkpoints rather than per push. Eleven workstreams (A–I, R) were assigned one owner each with exclusive file scope.

**Why the direction changed (inferred from the artifact):** the merge rate on 2026-07-26 was ~16 PRs in one day across overlapping surfaces. Batching reduces CI cost, review load, and — critically — cross-agent conflicts on hot files (`server.py`, `globals.css`, `package.json`).

### Stage F — 2026-07-26: the evidentiary crisis

This is the most important stage for an auditor, and it is recorded in PR #553's body. Over the course of the workstream execution, **the same class of failure appeared six times across three workstreams**, and a standing rule was promoted to `docs/ORCHESTRATION.md` §2b in response. The three shapes:

1. **A check that passes when it shouldn't.** A TE-premium figure of 1.316 landed 0.004 away from KTC's measured 1.320 and read as independent corroboration. It was not: the 1.316 paired a *measured* league endpoint against an *assumed* 1.0-TE reference. The agreement was the assumption reflected back. Three separate instances of this pattern occurred.
2. **A condition that can never fire.** LI-7 computed `projection_corroborated` from `applied` axes, while the corroboration axis carries factor 1.0 by design — making corroboration structurally invisible.
3. **A fix that reads correctly but cannot take effect.** R3's mobile-order restoration was inert because a media query adds no specificity and the base rule sat after it. The diff reviewed as correct while rendering identically to the regression.

Plus the strongest form: **without `E2E_TEST_MODE`, every signed-in E2E spec skipped and the suite reported green while asserting nothing.**

Standing rules recorded as a result:

- State which side of any comparison is measured and which is assumed.
- Write the test that fails when the mechanism is disconnected.
- **A test never observed failing is not yet evidence** — run new regression assertions against the pre-fix state and require them to fail there.

**Retractions issued in the same PR** (this is genuinely good practice and should be credited): the `FLEX: TE 0` / "TE demand overstated 46%" findings were retracted as artifacts of optimizing on season-long means; the `3.79` depth figure was retracted as never having been `starters_per_team`; and the headline TE premium was revised **downward** from ~1.32 to **≈1.12** once both endpoints were measured symmetrically.

### Stage G — Current state (this session)

Five PRs open, none merged: #550 (League Intelligence LI-1..LI-7), #551 (Redesign R3), #552 (Redesign R4), #553 (orchestration docs), #554 (E2E runnable suite). `main` is at `c534280d`. The branch this document sits on has **no code changes** relative to `main`.

---

## 3. Current Product Architecture

### 3.1 Component map

| Component | Technology | Primary paths |
|---|---|---|
| Frontend | Next.js 15 + React 19 (App Router), port 3000 | `frontend/app/`, `frontend/components/`, `frontend/lib/` |
| Backend | Python 3.11, FastAPI + Uvicorn, port 8000 | `server.py` (10,707 lines), `src/` |
| Persistence | SQLite (3 small DBs) + JSON/CSV snapshots on disk + git-committed CSVs | `data/`, `CSVs/`, `exports/` |
| Data ingestion | Playwright scraper + ~12 Python fetcher scripts | `Dynasty Scraper.py` (307 KB), `scripts/fetch_*.py` |
| Valuation engine | Canonical blend | `src/api/data_contract.py` (9,009 lines), `src/canonical/player_valuation.py` |
| Trade engines | Two independent systems + simulator | `src/trade/` |
| Roster/ROS analysis | ROS values, lineups, sims | `src/ros/` |
| League intelligence | Cross-league Sleeper crawl | `src/intel/` |
| News | 9 providers + digest | `src/news/` |
| Public league hub | 27 modules | `src/public_league/` |
| Automation | 14 GitHub Actions workflows | `.github/workflows/` |
| Deployment | Hetzner VPS, nginx, systemd, Let's Encrypt | `deploy/` |
| Testing | pytest (205 files) + Playwright E2E + vitest (12 files) | `tests/` |

### 3.2 Frontend

Next.js is the **sole** production frontend. `FRONTEND_RUNTIME` is hardcoded to `next` in `server.py`; all page routes proxy to port 3000 and return **503 if Next is down** — there is deliberately no static fallback.

Routes (`frontend/app/`): `rankings`, `trade`, `trades`, `angle`, `finder`, `edge`, `draft`, `draft-capital`, `waivers`, `news`, `intel`, `rosters`, `players`, `trending`, `settings`, `login`, `admin`, `more`, `league` (public hub), `league-comparison`, `idptc-rookies`, `tools`, `design`.

Design system (PR #536, R0): `frontend/app/tokens.css`, `ds.css`, `docs/DESIGN-SYSTEM.md`. Navigation IA is centralized in `frontend/lib/nav-model.js` (single source; other workstreams register routes only).

**Critical frontend rule:** `buildRows` in `frontend/lib/dynasty-data.js` is a *pure materializer*. It trusts backend stamps verbatim and never recomputes ranks. The prior ~280-line `computeUnifiedRanks` client-side fallback was **removed**; `buildRows` now fails fast (logs error, returns empty rows) when a non-empty payload has zero backend rank stamps.

### 3.3 Backend and APIs

100 route decorators in `server.py`. Grouped:

| Group | Endpoints |
|---|---|
| Core data | `/api/data`, `/api/dynasty-data`, `/api/rankings/overrides`, `/api/rankings/sources`, `/api/data/rank-history`, `/api/data/player-source-history` |
| Trade | `/api/trade/{suggestions,finder,simulate,simulate-mc,import-ktc,export-ktc}`, `/api/angle/{find,packages}` |
| Waivers | `/api/waiver/{suggestions,faab-recommend}` |
| League | `/api/leagues`, `/api/terminal`, `/api/draft-capital`, `/api/league-comparison`, `/api/sleeper/draft/picks` |
| Intel | `/api/intel/{summary,player,member/{ownerId},refresh,refresh/status}` |
| News | `/api/news`, `/api/custom-alerts`, `/api/custom-alerts/run`, `/api/signal-alerts/run` |
| Player context | `/api/playerctx/player`, `/api/player/{sleeper_id}/realized`, `/api/movers` |
| Public league | `/api/public/league`, `/api/public/league/{section}`, `+.csv`, `/matchups`, `/players`, `/metrics`, `/player/{id}`, `/matchup/...` |
| Auth | `/api/auth/{login,logout,status}`, `/api/user/state`, `/api/user/signals/{dismiss,restore}` |
| Admin | `/api/admin/{guest-pass,guest-passes,sessions/force-logout-all,signal-state/migrate,nfl-data/flush}` |
| Ops | `/api/status`, `/api/health`, `/api/uptime`, `/api/metrics`, `/api/scrape`, `/api/scaffold/*` |
| Push | `/api/push/{public-key,subscribe,unsubscribe}` |

**League-aware routing:** `server.py::_resolve_league_for_request` resolves `leagueKey` → explicit request param → user's `activeLeagueKey` → registry default. Errors: `unknown_league` (400), `inactive_league` (400), `data_not_ready` (503), `no_leagues_configured` (404). No endpoint exposes raw Sleeper league IDs to the UI.

**The architectural split that governs everything** (from `CLAUDE.md`): *scoring profile controls rankings; league key controls context.* Rankings/values/player metadata are shared across leagues with identical scoring; rosters/teams/matchups/draft capital/trade outputs are per-league.

### 3.4 Database

There is **no relational database server.** Persistence is:

| Store | Type | Path | Contents |
|---|---|---|---|
| User KV | SQLite (WAL) | `data/user_kv.sqlite` | Per-user `selectedTeam`, `watchlist`, `dismissedSignals`, `dismissalAliases` |
| Sessions | SQLite | (via `src/api/session_store.py`) | Auth sessions surviving restart; TTL `SESSION_TTL_DAYS` default 30; rows carry `allowlist_version` hash so an allowlist change invalidates sessions |
| Guest passes | SQLite | (via `src/api/guest_passes.py`) | Invitation passes, revocation |
| Source CSVs | Flat files, git-committed | `CSVs/`, `data/` | Per-source `name,value,rank` |
| Contract snapshots | JSON | `data/` | Daily snapshots used for backtests |
| Intel snapshot | JSON, league-partitioned | `data/intel/snapshot_<leagueKey>.json` | Cross-league transaction events, pruned to 45 days |
| Public league | JSON | `data/public_league/` | Snapshots, archives |
| ROS aggregate | JSON | `data/ros/aggregate/latest.json` | Blended rest-of-season values |

**Consequence:** the VPS disk is a stateful dependency. `data/intel/` and `data/public_league/` are explicitly accepted as lost-on-rebuild (next run backfills). `user_kv.sqlite` has a dedicated backup script (`deploy/backup_user_kv.sh`) — it is the only genuinely irreplaceable state.

### 3.5 Data ingestion

Two mechanisms:

1. **`Dynasty Scraper.py`** (307 KB, legacy Selenium/requests + Playwright) — the primary scrape, run by `scheduled-refresh.yml` every 2 hours (`cron: 42 */2 * * *`).
2. **Per-source fetcher scripts** (`scripts/fetch_*.py`), invoked by a `run_fetcher` shell function in the same workflow with per-source failure isolation and freshness stamps: `fetch_dynasty_daddy.py`, `fetch_fantasycalc.py`, `fetch_otcffb.py`, `fetch_fantasynavigator.py`, `fetch_pfk.py`, `fetch_flock_fantasy.py`, `fetch_flock_fantasy_rookies.py`, `fetch_draftsharks.py`, `fetch_draftsharks_ros.py`, `fetch_fantasypros_fitzmaurice.py`, `fetch_yahoo_boone.py`.

Post-fetch the workflow runs: `validate_scrape_sanity.py` (pre-commit gate), retention pruning, commit, deploy trigger, DLF freshness assertion, `watchdog_freshness.py`, `watchdog_contract_coverage.py`, and a failure alert step.

Separate cadences exist for DLF and IDPShow (`deploy/dlf_fetch_and_push.sh`, `deploy/idpshow_fetch_and_push.sh`) — visible in git log as hourly-ish `chore(dlf)` / `chore(idpshow)` commits.

### 3.6 Ranking sources (the registry)

21 registered sources in `src/api/data_contract.py::_RANKING_SOURCES` (line ~1020 onward):

`ktcSfTep`, `idpTradeCalc`, `dlfSf`, `dlfRookieSf`, `dlfIdp`, `dlfRookieIdp`, `idpShow`, `dynastyNerdsSfTep`, `fantasyCalc`, `otcffbSf`, `fantasyNavigatorSf`, `pfkDynasty`, `dynastyDaddySf`, `fantasyProsSf`, `fantasyProsIdp`, `fantasyProsFitzmaurice`, `flockFantasySf`, `flockFantasySfRookies`, `yahooBoone`, `draftSharks`, `draftSharksIdp`.

All blend weights are **1.0 by policy**. `config/weights/default_weights.json` is documentation only — nothing loads it.

### 3.7 Autonomous agents, scheduled workflows, news, Sleeper, IDP, caching, auth, deployment, testing, monitoring

Covered in dedicated sections: agents/workflows §8, news below, Sleeper below, IDP §4.9, caching/auth/deploy/test/monitoring below.

**News** (`src/news/`): 9 providers — `sleeper`, `espn`, `espn_player`, `cbs`, `fantasypros`, `rotowire`, `dynasty_focused`, `pfk`, plus a shared `_rss.py` base. Service layer `src/news/service.py` (180s cache, dedupe), digest builder `src/news/digest.py` (emits a digest once a player has 2+ stories inside a hard 7-day window), unified signal engine `src/news/unified_signal_engine.py`, usage signals `src/news/usage_signals.py`, custom alerts `src/news/custom_alerts.py`. The silent mock-news fallback was removed in PR #533 in favour of an explicit "news unavailable" state.

**Sleeper integration**: `src/api/sleeper_overlay.py` (rosters, users, matchups, transactions, traded picks, drafts — refreshes ~15 min), `src/public_league/sleeper_client.py`, `src/league_comparison/sleeper_scoring.py` and `sleeper_stats.py`, `src/scoring/sleeper_ingest.py`, `src/adapters/sleeper_trending.py` (TTL-cached trending adds), `src/news/providers/sleeper.py`. Owner identity keys on `owner_id` (Sleeper's global stable user_id), with co-owner matching.

**Caching**: FastAPI `GZipMiddleware(minimum_size=1024)`; an overlay response cache (`_OVERLAY_RESPONSE_CACHE`, pre-encoded, bounded, single-key retention); a contract-id-keyed by-name index (`_LIVE_BY_NAME_CACHE`); `Cache-Control: private, max-age=30, stale-while-revalidate=300` on the heavy data route and `max-age=60` variants elsewhere; per-league context and roster caches at 3600s TTL (`_LEAGUE_CONTEXT_CACHE_TTL_SECONDS`); a 15-min trending adapter TTL; a 6-hour championship-sim cache (`_SIM_CACHE_TTL_SEC`); `functools.lru_cache` on CSV parsing.

**Auth**: allowlist usernames + password (`JASON_LOGIN_USERNAME` / `JASON_LOGIN_PASSWORD`), cookie-based sessions with a `max_age` that deliberately outlives iOS Safari tab eviction, SQLite-backed session persistence, allowlist-version invalidation, in-memory session dict capped at 5000 with LRU eviction, and a guest-pass system with revocation and admin force-logout.

**Deployment**: Hetzner VPS. `deploy/` contains nginx configs, systemd units (`dynasty.service` + `dynasty-frontend.service` — both required), `deploy.sh`, `rollback.sh`, `verify-deploy.sh`, `bootstrap-production.sh`, `apply_hardening.sh`, logrotate, grafana and monitoring configs, and `PRODUCTION_BOOTSTRAP.md`. **PR #537's hardening is explicitly "prepared, not applied".**

**Testing**: 205 pytest files under `tests/` (subdirs: adapters, api, backtesting, canonical, identity, integration, intel, league_comparison, maintenance, news, nfl_data, playerctx, pool, public_league, ros, scoring, scripts, trade, utils, e2e), 12 JS test/spec files, plus a Playwright E2E suite (`tests/e2e/` with `playwright.config.js`, `preflight.py`, `specs/`, `helpers/`).

**Monitoring**: `/api/health`, `/api/uptime`, `/api/metrics`; `health-check.yml` every 6h; `smoke-test.yml` daily; `prod-e2e-smoke.yml` every 4h against the public `/league`; `public-league-warmup.yml` every 20 min; watchdog scripts for freshness and contract coverage; `src/api/ops_alerts.py`, `source_health_alerts.py`, `espn_schema_drift.py`; push notifications via `src/api/push_delivery.py`.

---

## 4. Every Formula and Scoring Model

All formulas below were read from source at `c534280d`. File:line references are given. Where a formula is **proposed but not implemented**, it is labelled.

### 4.0 The value scale

| Property | Value |
|---|---|
| Internal/display scale | 0–9999 integer (`_DISPLAY_SCALE_MAX = 9999`, `src/api/data_contract.py:4841`; `DISPLAY_SCALE_MIN = 1`, `player_valuation.py:126`) |
| Units | Dimensionless "value points". Not dollars, not projected fantasy points. |
| Anchor semantics | The top asset on any source normalizes to 9999 |

### 4.1 Rank → percentile

**Implementing file:** `src/api/data_contract.py:4797`, `:4849`

```
p = (rank − 1) / (N_ref − 1),  clamped to [0, 1]
N_ref = _PERCENTILE_REFERENCE_N = 500
```

| Variable | Definition | Source |
|---|---|---|
| `rank` | Player's effective rank within a source, post-ladder-translation | Per-source CSV |
| `N_ref` | Fixed reference pool size — **not** the source's own pool size | Constant |

**Why fixed:** every source's contribution lands in the same combined-pool coordinate system. 500 aligns with KTC's native pool.

**Known weakness (stated in code):** ranks past 500 clamp to the curve tail. This is described as "deliberate top-500-board behavior", but it means rank 520 and rank 900 are *indistinguishable* in value terms. For a 12×58 = 696-roster-spot league, a meaningful part of the rosterable universe sits in the flat region.

### 4.2 Percentile → value (Hill curve)

**Implementing file:** `src/canonical/player_valuation.py::percentile_to_value` (line 366)

```
V(p) = 9999 / (1 + (p / c)^s)
```

Rank-form equivalent stamped for the frontend: `V(r) = 9999 / (1 + ((r − 1)/midpoint)^s)` where `midpoint = c × (N_ref − 1)`.

Four scope-level master curves (`player_valuation.py:88–114`):

| Curve | `c` | `s` | Implied midpoint (rank) | Routed live? |
|---|---|---|---|---|
| GLOBAL | 0.1130 | 0.870 | 56.4 | ✅ cross-market sources |
| OFFENSE | 0.1180 | 1.170 | 58.9 | ✅ default |
| IDP | 0.0930 | 0.970 | 46.4 | ✅ overall IDP |
| ROOKIE | 0.1280 | 0.865 | 63.9 | ❌ **fit-only, not routed** |

Legacy rank-form constants also exist and are separately maintained: `HILL_MIDPOINT = 48.44`, `HILL_SLOPE = 1.149`, `IDP_HILL_MIDPOINT = 69.50`, `IDP_HILL_SLOPE = 0.945` (`player_valuation.py:55–73`).

**Refit:** `.github/workflows/refit-hill-curves.yml`, weekly Tuesdays 06:17 UTC, via `scripts/auto_refit_hill_curves.py`, trained on value-based observations.

**Worked example (OFFENSE curve, c=0.1180, s=1.170):**

| Rank | p | (p/c)^s | V |
|---|---|---|---|
| 1 | 0.0000 | 0 | **9999** |
| 12 | 0.0220 | 0.148 | **8709** |
| 25 | 0.0481 | 0.361 | **7346** |
| 59 | 0.1162 | 0.980 | **5050** |
| 120 | 0.2385 | 2.243 | **3083** |
| 250 | 0.4990 | 5.412 | **1559** |
| 500 | 1.0000 | 12.20 | **757** |

**Known weaknesses:**
- The curve is fit globally, not per position. A QB and an RB at the same consensus rank receive the same value, with positional demand entering only via the source consensus itself.
- Two parallel parameterizations (percentile-form and rank-form) are maintained in the same module. Nothing in the code enforces that they agree.
- The ROOKIE curve is refit weekly but never routed — dead compute.

### 4.3 Value-direct voting

**Implementing file:** `src/api/data_contract.py:5026` (`_VALUE_BASED_SOURCES`)

```
contribution = raw_source_value / site_max × 9999
```

Membership today is **exactly two sources**: `ktcSfTep`, `idpTradeCalc`.

Sources **removed** from this path and their recorded reasons (all in registry comments):

| Source | Removed | Hampel drop rate that triggered it | Recorded cause |
|---|---|---|---|
| `dynastyDaddySf` | 2026-04-22 | 61% | 10,200 cap with top 3 tied |
| `yahooBoone` | 2026-04-22 | 47% | 141 top with seven players ≥110 |
| `fantasyProsFitzmaurice` | 2026-04-22 | 19% | 0–101 scale, top dozen bunched 80–101 |
| `fantasyCalc` | 2026-07-25 | 55–58% every week live | Crowd curve decays faster than KTC-anchored consensus |
| `otcffbSf` | 2026-07-25 | 56% → 86% | Same |
| `ktc` (standard) | 2026-04-28 | — | Retired from blend; values retained for the arbitrage finder only |

An import-time invariant (`_validate_value_based_sources_invariant`) fails module load if a `signal: value` source is neither in `_VALUE_BASED_SOURCES` nor declares `ds_combined_rank_partner`.

**DraftSharks carve-out:** DS publishes offense and IDP on one cross-market `3D Value +` scale that goes **negative** past ~rank 200 (211 SF rows, 252 IDP rows). Per-CSV normalization would erase DS's native offense/IDP ratio and mishandle negatives, so the two CSVs are merged into one cross-market rank list routed through the GLOBAL Hill master.

### 4.4 Per-player Hampel outlier rejection

**Implementing file:** `src/api/data_contract.py:231–233`, `_hampel_filter_per_player`

```
drop source i if |v_i − median(v)| > max(K × MAD(v), floor)
K = 2.75,  floor = 1000.0 (Hill points),  min_n = 4
```

Guards: no filtering below 4 values; no filtering when MAD = 0; no filtering if it would leave fewer than 2 survivors; **pick rows skip Hampel entirely**.

**Why the floor is 1000 and not 500** (recorded 2026-04-27): with KTC + ktcSfTep + IDPTC + dynastyDaddySf all riding a shared market, their values cluster within 50–150 points (MAD ≪ 200), so K·MAD collapses to the floor; rank-Hill sources (which span ~2000 points between adjacent rank decades at the steep top) then fell outside a 500-point floor on routine disagreement and got dropped at 18–25% rates.

**Unvalidated assumption:** K = 2.75 is described as "tuned for our typical n=4–8 coverage" but no backtest is cited for K specifically — unlike α and λ, which have named report files.

### 4.5 Count-aware mean-median blend

**Implementing file:** `src/api/data_contract.py::count_aware_mean_median_blend` (line 5855), aliased `_trimmed_mean_median` at line 6578

| n | Center | MAD |
|---|---|---|
| 1 | the value | `None` |
| 2 | mean | half-range |
| 3–4 | (mean + median)/2, **untrimmed** | over full set |
| ≥5 | (trimmed_mean + trimmed_median)/2, drop one max + one min | over trimmed set |

Prior implementation trimmed at n≥3, which collapsed n=3 to a single surviving source. Corrected 2026-04-20.

### 4.6 Hierarchical anchor + α-shrinkage

**Implementing file:** `src/api/data_contract.py:6800–6835`, constant at `:4941`

```
Final_center = Anchor + α × (SubgroupBlend − Anchor),   α = 0.10
```

**Gating (this is the important part):**

| Row type | Path |
|---|---|
| IDP (DL/LB/DB) | Hierarchical: anchor + α·subgroup |
| Picks | Hierarchical (anchor set widened to include `ktcSfTep` so KTC + IDPTC average as peers) |
| Offense (QB/RB/WR/TE) | **Flat** count-aware mean-median over all values; `alphaShrinkage` stamped as 0.0 |

`Anchor` = count-aware mean-median across covered cross-market sources (IDPTC value-direct; DS + FG combined cross-market rank → GLOBAL Hill).

**Recorded tuning history:** α was 0.30 in the PR-3 standalone sweep. A 2D α×λ joint backtest (`reports/alpha_lambda_joint_backtest_full.md`) found the true stability optimum at **α = 0** — the degenerate "use IDPTC alone" solution. That was rejected as *product-bad* because it violates the declared consensus-fit objective in `docs/architecture/optimization-target.md`. α = 0.10 was chosen as the cheapest non-degenerate joint point (VW 0.299), explicitly accepting **~2× worse stability than the degenerate optimum**.

**This is a documented, deliberate accuracy-for-principle trade and an auditor should scrutinize it.** The metric said "ignore the other 15 sources"; the product said "no". Both positions are defensible; the decision is not empirically settled.

**Offense flat-blend rationale (2026-04-20):** IDPTC as a hard anchor at α=0.10 over-weighted it vs. other sources and caused ordering glitches — the cited example is Drake Maye ranking below Jaxon Smith-Njigba where the offense consensus had Maye higher.

### 4.7 MAD volatility penalty — RETIRED

**Implementing file:** `src/api/data_contract.py:4975`

```
final = center − λ × MAD,   λ = _MAD_PENALTY_LAMBDA = 0.0
```

λ was 0.5 in PR 2, then 0.10 after the joint backtest, then **set to 0.0 on 2026-04-20**. Recorded reason: the count-aware blend already damps disagreement on offense, and α-shrinkage already damps it on IDP/picks — λ·MAD stacked a third penalty on the same signal and hid real board movement.

`sourceSpread` is still stamped as a pure diagnostic. `madPenaltyApplied` is stamped as `None` purely because frontend builds still read the key. **This is dead-field debt.**

### 4.8 Single-source haircut

**Implementing file:** `src/api/data_contract.py:4989`, applied at `:6916`

```
if not is_pick and len(post_Hampel_values) <= 1:
    blended_value ×= 0.30
```

Picks are exempt (a single KTC per-slot synthetic value is structurally normal for them). The haircut is applied to the **pre-sort** value so board rank and displayed value stay consistent, and is re-stamped onto `_blendedValueUncapped` so an unranked single-source rookie can't price picks on an unpenalized value.

**Unvalidated assumption:** 0.30 is a strong claim (a 70% markdown) with no cited backtest. Note the trade finder uses a *different* single-source discount — `SINGLE_SOURCE_DISCOUNT = 0.88` (`src/trade/finder.py:29`), a 12% haircut, commented "Match frontend". **These two numbers describe the same underlying phenomenon and differ by 58 percentage points.** See §11.

### 4.9 IDP calibration + market corridor clamp

**IDP calibration post-pass:** `_apply_idp_calibration_post_pass`, reading `config/idp_calibration.json`.

**Corridor clamp:** `src/api/data_contract.py:4278–4340`, `_apply_market_corridor_clamp` (line 4468), invoked at `:7232`.

```
band = min( P90( |final − market| / market ) within the row's confidence bucket,
            max_band[asset_class] )
if |final − market| / market > band:  clamp final to the band edge
```

| Parameter | Value |
|---|---|
| Percentile | `_MARKET_CORRIDOR_PERCENTILE = 0.90` |
| Min bucket sample | `_MARKET_CORRIDOR_MIN_BUCKET_N = 30` (else fall back to overall board P90) |
| Max band, IDP | 0.15 (±15% of IDPTC) |
| Max band, offense | **none — offense is not clamped at all** |
| Primary anchors | offense → `ktcSfTep`; IDP → `idpTradeCalc` |
| Offense fallback chain | ktcSfTep → idpTradeCalc → dynastyDaddySf → fantasyProsFitzmaurice → yahooBoone → median of scope-eligible contributions |
| IDP fallback chain | idpTradeCalc → dlfIdp → idpShow → fantasyProsIdp |

Worked example from the code comments: a Vikings LB priced at 1,900 internal vs. 3,600 IDPTC (47% drift) clamps to 3,060 (the ±15% band edge).

**Known weakness:** the clamp exists solely to contain IDP calibration runaway. It means an IDP value can never disagree with IDPTC by more than 15% — **so on IDP, the "consensus of 21 sources" is bounded to a ±15% corridor around one source.** That is a significant limitation on the product's core claim, and it is not surfaced to users.

### 4.10 TE-premium (TEP) adjustment

**Implementing file:** `src/api/data_contract.py:5382–5384`, applied around `:6024–6037`

| Constant | Value | Applies when |
|---|---|---|
| `_TE_BLANKET_NON_NATIVE_MULTIPLIER` | **1.15** | Source is not TEP-aware (`is_tep_premium: False`) |
| `_TE_BLANKET_NATIVE_MULTIPLIER` | **1.10** | Source is TEP-aware |
| `_TE_BLANKET_KTC_EXEMPT_KEYS` | `{ktc, ktcSfTep}` | Exempt — KTC's TE+ sub-board already prices it |

Operator slider clamps the non-native multiplier to [1.0, 1.5]. League auto-derivation from Sleeper's `bonus_rec_te` via `_derive_tep_multiplier_from_league`, with `_TEP_DERIVATION_SLOPE = 0.30` and derived value clamped to [1.0, 2.0] (`:5319–5321`).

**Contested by measurement (PR #550/553):** symmetric measurement of the 1-TE vs 2-TE endpoints on 2025 weekly actuals gives an **operative structural premium of ≈1.12**, below the 1.15 currently applied and far below every prior figure. This is recorded as "a finding, not a published value" — i.e. the constant has *not* been changed. **This is an open, live contradiction between measurement and implementation.**

### 4.11 Pick tethering and future-year discount

**Tethering:** current-year slot picks inherit values from the merged rookie pool (offense + IDP rookies combined). Constants: `_ROOKIE_ANCHOR_LEAGUE_SIZE_DEFAULT = 12`, `_ROOKIE_ANCHOR_ROUNDS = 6` (`:5295–5296`). Pick-name grammar: `_PICK_SLOT_RE` matches `YYYY Pick R.SS`; `_PICK_TIER_RE` matches `YYYY Early|Mid|Late Nth`.

**Year discount:** `config/weights/pick_year_discount.json`, applied in `_apply_pick_year_discount_to_blend` before the global sort.

```
value ×= offsetDiscounts[ pick_year − current_rookie_draft_year() ]
```

| Offset | Multiplier |
|---|---|
| 0 (upcoming draft) | 1.00 |
| 1 | 0.82 |
| 2 | 0.66 |
| 3 | 0.53 |
| >3 | `0.80 ^ offset` (`fallbackBase`) |

`current_rookie_draft_year()` resolution: (1) manual `currentDraftYear` override if set (currently `null`); (2) **derived from the scrape** — the lowest year still carrying slot-specific rows is the active class; (3) date fallback rolling on May 15.

The offset schema is a genuinely good design choice: it never goes stale.

**Note:** 0.82/0.66/0.53 is roughly `0.82^n` (0.82, 0.672, 0.551), so the explicit table barely differs from a geometric decay at 0.82 — while `fallbackBase` is 0.80. No source or backtest is cited for 0.82.

### 4.12 Confidence buckets and disagreement flags

**Implementing file:** `src/api/data_contract.py:111–190`

Confidence (first match wins):

| Bucket | Rule |
|---|---|
| high | ≥2 sources AND percentileSpread ≤ 0.08 |
| medium | ≥2 sources AND percentileSpread ≤ 0.20 |
| low | single source, OR spread > 0.20, OR no percentile signal and absolute ordinal spread > 80 |
| none | no unified rank |

Legacy absolute fallbacks: `_CONFIDENCE_SPREAD_HIGH = 30`, `_CONFIDENCE_SPREAD_MEDIUM = 80`.

**Trimmed percentile spread** (`_PERCENTILE_SPREAD_TRIM_MIN_N = 5`): at n≥5, drop the single most extreme percentile on **each** side before max−min. Recorded rationale (2026-07-25 "caution-saturation audit"): raw max−min grows mechanically with source count; after the May–July source additions top players carry ~12 sources and **72% of the top-200 board carried a "wide disagreement" flag — flags rose *with* coverage, so more data read as less confidence.** Post-fix measured on the live board: top-200 disagreement 143 → ~40 rows; `suspicious_disagreement` 82 → ~15.

**Depth-aware allowance** (`_disagreement_depth_allowance`):

```
threshold_effective = base_threshold + min(consensus_percentile, 0.25)
base: hasSourceDisagreement 0.10;  suspicious_disagreement 0.20
```

Justification recorded: median trimmed spread is 0.068 inside the top 100 but 0.30 at ranks 201–400, for two structural reasons — sources genuinely order deep players near-randomly, and pool-size normalization makes identical ordinal placements read as different percentiles (rank 66 of 280 = 0.24 vs rank 44 of 500 = 0.09).

**Confidence buckets deliberately do NOT get the allowance** — a design decision the code argues for explicitly.

Anomaly flag catalogue: `offense_as_idp`, `idp_as_offense`, `missing_position`, `retired_or_invalid_name`, `ol_contamination`, `suspicious_disagreement` (>150 ordinal ranks), `missing_source_distortion`, `impossible_value`, plus identity quarantine flags `duplicate_canonical_identity`, `name_collision_cross_universe`, `position_source_contradiction`, `unsupported_position`, `no_valid_source_values`.

### 4.13 Injury adjustment

**Implementing file:** `src/api/injury_impact.py:80–152`

```
discount_pct = BASE[severity] × pos_mult × age_mult × time_decay
final = min(discount_pct, 5.0)
value ×= (1 − discount_pct/100)
if offseason(now): discount → 0
```

| Component | Values |
|---|---|
| `BASE` | alert 4.0, watch 2.0, info 0.5 (percent) |
| Position multiplier | RB 1.20, WR 1.00, TE 0.90, QB 0.70, IDP 0.80, other 1.00 |
| Age multiplier | rookie 0.80; ≤25 0.80; ≤28 1.00; ≤31 1.20; >31 1.40 |
| Decay | linear to zero over 30 days |
| Hard cap | 5.0% |
| Offseason months | Feb–Aug inclusive → discount forced to zero |

**Design intent stated in code:** "A torn ACL in Week 8 is a redraft disaster (−30% RoS) but a dynasty hiccup (−3 to −5% multi-year)."

**Known weaknesses (mine):** the 5% cap is unconditional, so a career-ending injury and a hamstring tweak are within 4.5 points of each other. Severity is a 3-level enum derived from news classification, not from injury type or reported timeline. The month-based offseason switch means a torn Achilles on 1 September gets a full discount while the same injury on 31 August gets zero — the code acknowledges the coarseness but the discontinuity is real.

### 4.14 Tiering

**Implementing file:** `src/canonical/player_valuation.py:41–43`, `src/scoring/tiering.py`, `config/tiers/thresholds.json`

Two mechanisms coexist:

1. Rolling-median gap detection: `TIER_GAP_WINDOW = 7`, `TIER_GAP_THRESHOLD = 2.0`, `TIER_MIN_SIZE = 3`.
2. Per-position Cohen's-d thresholds: QB 0.35, RB 0.22, WR 0.22, TE 0.35, DL/LB/DB 0.30, PICK 2.0.

The config file states these are **priors**, to be replaced by `scripts/fit_tier_thresholds.py` "once we have a month of canonical-contract history". Policy: changes >15% open a PR, smaller drifts update silently.

**I could not verify that the fitter has ever run.** An auditor should check whether these are still hand-set priors.

### 4.15 Other value-curve machinery (present, routing unverified)

`player_valuation.py` also defines: `W_MEDIAN = 0.70` / `W_MEAN = 0.30` (consensus rank weighting), `CLIFF_BASE_POINTS = 120.0` / `CLIFF_RANK_DECAY = 0.006` (tier cliffs), `VOL_COMPRESSION_STRENGTH = 0.03` / `VOL_FLOOR = 0.92` (volatility compression, max 8% markdown). **I did not trace whether `run_valuation` (line 541) — which uses these — is on the live `/api/data` path or is legacy from the retired canonical-build mode.** Given that `CLAUDE.md` says the offline canonical path is retired and `_compute_unified_rankings` is "the one and only code path", these constants are probably dead. **Flagged for verification.**

### 4.16 Two-way player boost

**Implementing file:** `src/api/data_contract.py:~4770–4838`

A player appearing in both offense and IDP families gets an alt-family value computed (value-direct if native, else rank→percentile→Hill on the appropriate master), averaged, and **if it exceeds the primary-family value, it replaces it.** An audit block `twoWayPlayerBoost` is stamped either way.

**Weakness:** this is a max() operator, not a blend. It is one-directional — the boost can only raise a value, never lower it. For a genuinely two-way player, taking the higher of two market opinions is an optimistic estimator.

### 4.17 FAAB v2 — contention model

**Implementing files:** `src/trade/faab_contention.py`, `src/trade/faab_recommender.py`

Per-opponent expected bid:

```
exp_bid = min( base_bid × agg × need_f × intel_f,  base_bid × 2.5 ) × 1.15
exp_bid = min(exp_bid, their_faabRemaining)
clearing = topRival + 1
```

| Variable | Definition | Default / bounds |
|---|---|---|
| `base_bid` | Our value-derived bid | from `recommend_faab` |
| `agg` | `clamp(their avgBid / league median winning bid, 0.5, 2.0)` | 1.0 if `winningCount < 3`, flagged `lowSample` |
| `need_f` | need 1.0 / neutral 0.55 / surplus 0.25, via `analyze_roster` | neutral |
| `intel_f` | 1.25 player-level, 1.10 position-level, else 1.0 | 1.0 when snapshot missing |
| `STACK_CAP_MULT` | 2.5 | hard |
| `SAFETY_MARGIN` | 1.15 | always applied |
| `INTEL_WINDOW_MS` | 14 days | |

**Missing-data behavior (well-handled):** rivals with a missing/non-integer `faabRemaining` are flagged `balanceUnknown` and **excluded from `topRival`/`clearing`** — an unverifiable rival must never raise the user's bid. The endpoint skips contention entirely when fewer than half of rivals carry a usable balance. If no `teamOwnerId` is in the body, contention is skipped with an explicit missing factor — the code never guesses which team is the user's.

Recommender-side factors (`faab_recommender.py`):

| Constant | Value | Meaning |
|---|---|---|
| `_VALUE_MOD_FLOOR` / `_CEILING` | 0.5 / 1.8 | value-gain modifier clamp |
| `_LEAGUE_CALIBRATION_BLEND` | 0.5 | blend weight vs league bid history |
| `_DROPOFF_GATE` | 0.15 | chase clearing only if `(add − next_best_FA)/add ≥ 0.15` |
| `_CEILING_DROPOFF_CLAMP` / `_SCALE` | 0.5 / 0.5 | ceiling = aggressive × (1 + 0.5·clamp(dropoff,0,0.5)) |
| `_ENV_SCALE_TARGET_SHARE` | 0.08 | env_scale = clamp((median winning bid / budget)/0.08, 0.6, 1.6) |
| `_ENV_SCALE_CLAMP` | (0.6, 1.6) | |
| `_ENV_MIN_BIDS_ANALYZED` | 10 | env scaling requires ≥10 analyzed bids |
| `_POSITION_CALIBRATION_MIN_COUNT` | 3 | env scale applied **only** when position bids < 3, to avoid double-counting |
| `_PACING_WARN_SHARE` | 0.40 | warn when a bid exceeds 40% of remaining budget |

Staleness ceilings: rosters 24h, leagueAnalytics 7d, trending 3h, intel 48h.

**Acknowledged irreducible limitation, stated in the returned `notes`:** "Sleeper never exposes losing bids, so selection bias is irreducible." The model is presented as an estimate, never a prediction. This is exemplary.

**Worked example (hypothetical).** Target: WR, our value bid $18. Rival A: avgBid $9 vs league median $6 → agg 1.5; roster thin at WR → need 1.0; intel shows they added 2 WRs cross-league in 10 days → 1.25. Raw = 18 × 1.5 × 1.0 × 1.25 = $33.75; stack cap = 18 × 2.5 = $45 (not binding); × 1.15 safety = $38.8; their FAAB remaining $22 → capped to **$22**. If A is the top rival, clearing = **$23**. Dropoff gate: if the next-best FA WR is worth 90% of the target, dropoff = 0.10 < 0.15 → **do not chase $23**; bid value only and label "replaceable".

### 4.18 Sharp Tracker trend score

**Implementing file:** `src/intel/aggregate.py:41`

```
trend_score = 3 × net_48h + 2 × net_7d + 1 × net_30d
```

where `net_X` = adds − drops for that asset across the crawled league pool inside window X. Windows: 48h / 7d / 14d / 30d (`WINDOWS_MS`), computed at read time; events pruned to 45 days.

**Weakness:** the windows are nested, not disjoint, so a transaction 30 hours old is counted in all three terms and receives an effective weight of 6, while one 20 days old receives 1. That may be intended, but it is not stated, and the weights (3/2/1) are unsourced.

Crawl budget: per-member league cap 25, steady state ≈310 API calls/run, hard budget 900, single-threaded, 0.12s sleep, resumable round-robin, incremental via `fetchState[leagueId] = {maxCreatedSeen, boundaryTxIds}`.

### 4.19 Power rating v2

**Implementing file:** `src/ros/power_v2.py:65`

```
power = Σ_i WEIGHTS[i] × percentile_i
```

| Component | Weight |
|---|---|
| `team_ros_strength` | 0.38 |
| `ppg` | 0.18 |
| `recent` (3-game window) | 0.12 |
| `wl_record` | 0.10 |
| `all_play` | 0.08 |
| `streak` | 0.05 |
| `schedule_adjusted` | 0.04 |
| `roster_health` | 0.03 |
| `luck_regression` | 0.02 |
| **Total** | **1.00** |

Six of the nine components (`ppg`, `recent`, `wl_record`, `all_play`, `streak`, `luck_regression` = 0.55 combined weight) are routed through `missing_inputs` when no scored games exist in the current season. **In the offseason — i.e. right now, late July — 55% of this formula has no input.** How the remainder renormalizes was not traced; an auditor should check whether `team_ros_strength` at 0.38 effectively becomes 0.69 of the live weight, or whether the score is simply depressed.

Weights are labelled "(spec)" — i.e. handed down, not fit.

### 4.20 Team direction classifier (contender / retooler / rebuilder)

**Implementing file:** `src/ros/direction.py:53`

Evaluated top-to-bottom, first match wins:

| Label | Condition |
|---|---|
| Strong Buyer | playoff ≥ 0.75 AND championship ≥ 0.10 |
| Buyer | playoff ≥ 0.60 AND championship ≥ 0.05 |
| Selective Buyer | 0.45 ≤ playoff < 0.60 |
| Strong Seller / Rebuilder | playoff < 0.10 AND championship < 0.01 AND `age_heavy` |
| Seller | playoff < 0.25 AND championship < 0.02 |
| Selective Seller | 0.20 ≤ playoff < 0.40 |
| Hold / Evaluate | everything else |

`age_heavy` = `vetCount ≥ 4`. Veteran age thresholds (`_VETERAN_AGE`, described as "spec values verbatim"): QB 32, RB 26, WR 29, TE 30, DL/DE/DT/EDGE 30, LB 29, DB/S/CB 29.

**Bug-shaped observation:** the ordering means a team at playoff 0.30, championship 0.015 hits **Seller** (`< 0.25`? no — 0.30 is not < 0.25, so it falls to Selective Seller). But a team at playoff 0.22, championship 0.01 matches **Seller** at the `< 0.25` clause before ever reaching the `0.20 ≤ playoff < 0.40` Selective Seller clause. So the entire band 0.20–0.25 is unreachable as "Selective Seller". The code comments acknowledge the spec's bands "overlap intentionally" and are resolved strongest-first — but the *effect* is that one documented category is partially shadowed. Low severity; worth a test.

**`team_ros_strength_percentile` is accepted as a parameter and used only in the human-readable `summary` string — it never affects the label.** That is a silently inert input.

### 4.21 Lineup optimization and depth

**Implementing file:** `src/ros/lineup.py`

Live on `main`: **greedy** slot-ordered fill, claiming optimality "because per-slot decisions are independent given fixed values."

**PR #550's audit verdict: that claim is false in general.** Greedy is optimal only while slot eligibility sets form a **laminar family**. It happens to hold for the current slot vector, so the code was "correct by an unstated, unenforced precondition." PR #550 replaces the core with an exact maximum-weight assignment (matroid greedy + augmenting paths, dependency-free) behind the same interface.

Health penalty (`_value_with_health_penalty`): injured → ×0.4; bye → ×0.0.

Depth scoring: `DEPTH_BENCH_LIMIT = 8`; per-position geometric decay QB 0.55, RB 0.65, WR 0.65, TE 0.55, DL/LB/DB 0.55, default 0.50. So bench WR1 counts 100%, WR2 65%, WR3 42%, WR4 27%.

**The larger bug found in PR #550:** *Sleeper evaluates slot eligibility against `fantasy_positions`, not `position`.* `_hydrate_overlay_players` kept only `position`, so **every hybrid IDP was locked out of half its legal slots in production.** Found empirically: reconstruction scored *below* the host on 5/10 weeks and the diff was hybrids the host had started. Fixed on branch; **not on `main`.**

Validation on branch: brute-force equivalence; an explicit non-laminar counterexample; and 10/10 real Sleeper best-ball team-weeks reproducing the host's awarded total (8/10 identical starter sets; the 2 that differ score identically).

### 4.22 Positional coverage — was a constant

`_positional_coverage` returned **exactly 100.00 for all 12 teams** — a constant contributing a flat 5 points to every composite. PR #550 makes it slot-derived, demand-weighted, and eligibility-aware; measured range becomes 90.87–100.00.

**Honest limitation recorded in the PR itself:** at 5% weight the fix moves composites by ≤0.46, and **rank order is unchanged across all 12 teams**. It is "now correct rather than a lie, but still a weak signal."

### 4.23 Replacement level and scarcity (PR #550, branch only)

Four replacement tiers computed off the real 12×58 pool (666 rostered players), with smoothed ±2-rank bands: **starter / bestBallStarter / roster / waiver**.

Six separate scarcity components rather than one score. Headline measurement: **QB `waiverScarcity` 0.75 vs RB 0.21** — described as "the defining fact of a superflex league."

Two deliberate deviations (ADR-008): unpriced players excluded from level pools; `waiverScarcity` measured against the best-ball starter floor rather than the noisy roster tail.

**Status: not merged. Not surfaced in any UI.**

### 4.24 League-adjusted value (PR #550, branch only, NO-OP by construction)

`src/league_intel/values.py` defines `marketValue` / `consensusValue` / `leagueAdjustedDynastyValue` with schema + model + config + `dataThrough` stamps, and a single selector `get_active_value(player, mode, context)`.

**The no-op guarantee is enforced in construction:** `build_player_values` raises if anyone flips `LEAGUE_ADJUSTED_IS_NOOP` without supplying a validated model. Consensus is *read* from `rankDerivedValue`; `data_contract.py` is untouched.

LI-7 adjustment engine (`src/league_intel/adjustment.py`) uses **evidence tiers, not a scalar confidence**: an axis with no admissible evidence contributes **exactly zero** and is arithmetically inert regardless of the factor supplied. Three guardrails: evidence gate (ABSENT axes contribute 0), magnitude cap (**±25%**), and monotonicity (`check_position_monotonicity` over a batch — order preservation is a set property, so a per-row version could never fire).

Current honest state: with no permitted raw-category source (LI-6 not built), *every* league-adjusted value would rest on roster structure alone, so `STRUCTURAL_ONLY` is the labelled default and `projection_corroborated` is `False`. The TE axis is deliberately `ABSENT` so it cannot stack on the blend's existing ×1.15 multiplier.

### 4.25 Exact league scorer (PR #550, branch only)

`src/league_intel/scorer.py` — pure `score_stat_line(stat_line, config)` over all 141 scoring keys.

**Key empirical finding (ADR-006, supersedes ADR-005's phrasing): Sleeper scoring is a pure dot product over shared stat keys. There are no stacking rules to encode.** 1,415/1,415 rostered 2025 player-weeks reconcile within **0.011**, plus two full team totals.

Resolved open questions:

| Question | Verdict |
|---|---|
| Pick-six | **Stacks** — `pass_int` + `pass_int_td` both charge (−6 at 2026 rates) |
| `bonus_fd_*` | Is itself a precomputed stat key = first downs gained |
| `rec` base + band | Stacks mechanically; nonzero-rate confirmation pends 2026 wk 1 |
| IDP multi-event | All events stack (sack + sack-yd + QB hit + TFL + solo) |
| `idp_blk_kick` vs `blk_kick` | No double-count — `blk_kick` is TEAM/DEF-only |
| Kicker | Pure per-yard (`fgm` rate 0) |

### 4.26 Trade formulas

See §6 for full treatment. Summary of constants:

**`src/trade/suggestions.py`:** `MIN_RELEVANT_VALUE 500`, `FAIRNESS_TOLERANCE 769`, `MAX_SUGGESTIONS_PER_TYPE 8`, `CONSOLIDATION_MIN_UPGRADE_RATIO 0.70`, `CONSOLIDATION_MAX_OVERPAY_RATIO 0.30`, `UPGRADE_SWEETENER_SURPLUS_MULTIPLIER 2.0`, `MAX_GIVE_PLAYER_APPEARANCES 2`, `MAX_RECEIVE_TARGET_PER_CATEGORY 2`, `MAX_LOW_CONFIDENCE_PER_CATEGORY 2`, `MIN_ACTIONABLE_VALUE 2000`, `MAX_GAP_FOR_1FOR1 400`, `HIGH_DISPERSION_CV 0.12`, `LOW_DISPERSION_CV 0.04`, `KTC_TOP_N_FILTER 150`, `MAX_BALANCERS 2`.

**`src/trade/finder.py`:** `MIN_ASSET_VALUE 800`, `MIN_KTC_VALUE 500`, `MAX_BOARD_LOSS −200`, `MAX_PACKAGE_SIZE 3`, `MAX_RESULTS 40`, `JUNK_THRESHOLD 400`, `SINGLE_SOURCE_DISCOUNT 0.88`, `MULTI_FOR_ONE_MIN_RATIO 0.55`, `PARTIAL_KTC_MAX_RANK 15`, `PARTIAL_KTC_ARBITRAGE_CAP 8.0`, `ELITE_THRESHOLD 7500`, `ELITE_MULTI_MIN_RATIO 0.65`, `PACKAGE_ANCHOR_MIN_PCT 0.35`, `CONFIDENCE_SOURCE_BASELINE 5`, `ROSTER_SURPLUS_THRESHOLD 4`, `ROSTER_WEAK_THRESHOLD 1`.

**`config/trade/team_impact.json`:** weights `fillStarter 1.0`, `depth 0.25`, `overflow 0.6`, `fitNormalization 4000`, `equityNormalization 2500`, `compositeFitWeight 0.55`, `compositeEquityWeight 0.45`; verdict thresholds accept 20 / leanAccept 8 / leanDecline −8 / decline −20; window fit `contendIndexThreshold 0.15`, `youngStarterMaxAge 23`, `primeStarterMinAge 24`, `primeStarterMaxAge 29`.

### 4.27 Formulas that are proposed but NOT implemented

| Formula | Status | Where described |
|---|---|---|
| League-adjusted delta vs consensus, published | Enforced no-op | ADR-001, `values.py` |
| LI-6 projection re-scoring through the exact scorer | **Not built** | MASTER_PLAN item 6 |
| Rookie priors / archetype role states | Not built | MASTER_PLAN LI-9+ |
| Champion–challenger MLOps for model swaps | Not built | MASTER_PLAN LI-9+ |
| Contextual values (contender/rebuilder/roster-specific) | Not built | MASTER_PLAN LI-9+ |
| Waiver score v2 | Not built | MASTER_PLAN LI-9+ |
| Best-ball ADP ingestion (Underdog) | Not built | ROADMAP Phase 7 |
| Cross-league observed FAAB bids as market anchor | Not built | ROADMAP Phase 4 note |

---

## 5. Roster Analysis System

### 5.1 What exists and where

| Capability | Implementation | Status |
|---|---|---|
| Overall roster value | Sum of `rankDerivedValue` over roster; `analyze_roster` (`src/trade/suggestions.py:540`) | Live |
| Starting-lineup strength | `optimize_lineup` (`src/ros/lineup.py:123`) → `starting_lineup_score` | Live (greedy on main; exact on PR #550) |
| Depth | `bench_depth_score`, top-8 bench with per-position geometric decay | Live |
| Positional strength / weakness | `need_positions` / `surplus_positions` vs `DEFAULT_STARTER_NEEDS` | Live |
| Short-term competitiveness | `src/ros/playoff_sim.py`, `power_v2.py` | Live |
| Rest-of-season outlook | `src/ros/` ingestion of 5 ROS sources → `aggregate.py` → `data/ros/aggregate/latest.json` | Live |
| Long-term dynasty outlook | Dynasty consensus values + age profile | Live |
| Age curve | `build_roster_age_profile` (`direction.py:131`), `src/utils/age.py` | Live |
| Injury risk | `src/api/injury_impact.py` (value discount) + `injured` flag in lineup | Live |
| Replacement value | `src/scoring/replacement_level.py` (legacy) + LI-5 four-tier engine | **LI-5 branch-only** |
| Positional scarcity | Six components in LI-5 | **Branch-only** |
| League-specific scarcity | LI-5, measured off the real 12×58 pool | **Branch-only** |
| Draft capital | `/api/draft-capital`, `src/api/draft_capital_fallback.py`, `src/ros/pick_projection.py` | Live |
| Taxi squads | Registry field; **live league has taxi = 0** | Config-only |
| Best ball | League is best-ball; `optimize_lineup` + `DEPTH_BENCH_LIMIT` model it | Live (approximately) |
| IDP | Full first-class support — see §4 | Live |
| Contender/retooler/rebuilder | `classify_team` (`direction.py:53`) | Live |
| Championship probability | `simulate_championship_odds` (`championship.py:163`), 6h cache | Live |
| Future flexibility | Draft capital + pick projector + age profile; **no single composite metric** | Partial |

### 5.2 How target positions are generated

`analyze_roster` (`src/trade/suggestions.py:540`) builds a `RosterAnalysis` carrying `starter_counts`, `need_positions`, `surplus_positions`, and total value. Needs and surpluses are derived by comparing the count of players above `MIN_RELEVANT_VALUE` at each position against `DEFAULT_STARTER_NEEDS`:

```python
DEFAULT_STARTER_NEEDS = {"QB": 2, "RB": 3, "WR": 4, "TE": 1, "DL": 3, "LB": 3, "DB": 2}
```

**These numbers are wrong on `main`.** PR #550 identifies `DEFAULT_STARTER_NEEDS` as "a hardcoded mirror of the stale lineup" and corrects TE 1→2 and DB 2→3 against the live 21-slot vector (QB1 RB2 WR3 TE2 FLEX2 SFLEX1 K1 DL3 LB3 DB3). **Until #550 merges, every trade suggestion, every need/surplus label, and every FAAB need factor on production is computed against a lineup the league does not use.** This is the highest-impact live defect I found.

### 5.3 How recommended moves are generated

Four generator functions in `src/trade/suggestions.py`, each capped at `MAX_SUGGESTIONS_PER_TYPE = 8`:

| Generator | Line | Logic |
|---|---|---|
| `_generate_sell_high` | 849 | Players whose board value exceeds market, or on surplus positions |
| `_generate_buy_low` | 913 | Players whose market lags our board |
| `_generate_consolidation` | 980 | 2+ depth pieces → 1 better starter; target ≥ 0.70 of combined; overpay ≤ 0.30 of give total |
| `_generate_positional_upgrades` | 1068 | Fill `need_positions` using surplus assets; sweetener tolerance ×2.0 |

Balancers (`_find_balancers`, line 1162) attach up to `MAX_BALANCERS = 2` throw-ins from roster (`_roster_balancer_candidates`) or pool (`_pool_balancer_candidates`) to close the gap.

Quality filtering (`_apply_quality_filters`, line 1257) enforces the dedup caps: max 2 appearances per give-player across all categories (lowered 3→2 after an audit found **52.5% of suggestions were repetitive**), max 2 suggestions per receive-target per category, max 2 low-confidence per category, both sides ≥ `MIN_ACTIONABLE_VALUE` 2000, and suppression of 1-for-1s whose gap exceeds 400 while carrying balancers ("a package deal masquerading as a 1-for-1").

`_rookies_eligible_today` (line 1386) gates rookie inclusion by draft timing.

### 5.4 Weaknesses in the roster system

1. **`DEFAULT_STARTER_NEEDS` is a hardcoded duplicate of config.** Three places model the lineup: `config/leagues/registry.json`, `src/ros/lineup.py` slot flattening, and this dict. Two were wrong.
2. **No composite "future flexibility" metric** despite it being a listed goal.
3. **Taxi and IR are modelled as config fields but the live league has 0 of each**, so that code path is untested against reality.
4. **Replacement level is not used by the trade engines.** `MIN_RELEVANT_VALUE = 500` is a flat constant standing in for replacement level, when a four-tier per-position replacement engine exists on a branch. Nothing connects them.
5. **`analyze_roster` counts players above a value threshold, not lineup-legal starters.** A team with 4 elite TEs and no WRs shows "surplus TE, need WR" correctly, but a team with 3 WRs who are all WR40-ish shows no need.

---

## 6. Trade Recommendation System

### 6.1 Two independent engines

| | `src/trade/suggestions.py` | `src/trade/finder.py` |
|---|---|---|
| Purpose | Roster-aware suggestions | KTC arbitrage |
| Endpoint | `POST /api/trade/suggestions` | `POST /api/trade/finder` |
| Question | "What should I do with my roster?" | "Where does the market misprice against my board?" |
| Quality gate | KTC top-150 | KTC top-150 |
| Ranking | `rank_score` (additive bonuses) | `arbitrage` (multiplicative) |

There is also `src/api/trade_simulator.py` (+ `/api/trade/simulate`, `/api/trade/simulate-mc` with `src/trade/monte_carlo.py`), `src/trade/angle.py` (`/api/angle/find`, `/api/angle/packages` — counter-pitch package builder), `src/trade/team_impact.py`, `src/trade/symmetrize.py`, `src/trade/correlation_matrix.py`, and `src/trade/ktc_import.py` / `ktc_va.py`.

### 6.2 Package shapes supported

| Shape | Where | Notes |
|---|---|---|
| 1-for-1 | `_generate_1for1` (`finder.py:523`); all suggestion categories | Suppressed in suggestions if gap > 400 with balancers attached |
| 2-for-1 | `_generate_2for1` (`finder.py:541`) | Guarded by `MULTI_FOR_ONE_MIN_RATIO 0.55`, `ELITE_MULTI_MIN_RATIO 0.65`, `PACKAGE_ANCHOR_MIN_PCT 0.35` |
| 1-for-2 | `_generate_1for2` (`finder.py:561`) | |
| 2-for-2 | **Not generated by the finder.** `MAX_PACKAGE_SIZE = 3` permits it structurally but no generator emits it | Gap |
| Player-for-pick / pick-for-player | Supported — picks are first-class assets in the pool with their own values | |
| Positional swaps | `_generate_positional_upgrades` | |
| Contender / rebuilding trades | Via `classify_team` labels + `_opponent_fit_label` | Advisory, not a hard filter |
| Buy-low / sell-high | `_generate_buy_low` / `_generate_sell_high` | |

### 6.3 Modelling the other manager's needs

`_analyze_opponent_rosters` (`suggestions.py:794`) runs the same `analyze_roster` over every league roster from the Sleeper overlay. `_opponent_fit_label` (line 816) then labels whether a receive-target sits at a position where the opponent has surplus and a give-piece fills their need. A match contributes `+1.5` to `rank_score`.

In the finder, roster fit is lighter: `ROSTER_SURPLUS_THRESHOLD 4` / `ROSTER_WEAK_THRESHOLD 1` produce a "light fit bonus" only.

**Planned but unbuilt:** the roadmap describes boosting opponent fit when Sharp-Tracker intel shows that owner is net-buying the position cross-league. The seam exists at `_opponent_fit_label`; **I found no evidence it is wired.**

### 6.4 Trade realism and acceptance probability

**There is no calibrated acceptance-probability model.** Nothing in the repo estimates P(accept). What exists instead is a *plausibility gate* and a *scalar appeal*:

In the finder (`_score_trade`, `finder.py:323`), all of the following must hold or the trade is discarded:

1. No overlap between give and receive names.
2. **Every** outgoing asset has a KTC value ≥ 500.
3. At least one receive asset has KTC.
4. IDP assets without KTC must not be ≥ half of either side (they distort KTC appeal).
5. `board_delta = recv_model − give_model ≥ −200`.
6. If giving more pieces than receiving: `give_model ≥ 0.55 × recv_model` (0.65 if the target is ≥ 7500), and `max_give ≥ 0.35 × max_recv`.
7. **`opp_appeal > 0` strictly** — the opponent must win on KTC. No break-even, no loss.
8. Not all assets on a side below `JUNK_THRESHOLD 400`.

```
opp_appeal = (give_ktc − recv_ktc) / max(recv_ktc, 1)
```

In the suggestions engine, realism is instead `_fairness_label(gap)`:

| Label | Gap (display scale) |
|---|---|
| even | < 256 |
| lean | < 769 |
| stretch | ≥ 769 |

**The `FAIRNESS_TOLERANCE = 769` constant carries an explicit code comment admitting its origin is "undocumented legacy tuning"** and that it is *independent* of the trade page's own verdict bands (350 / 900 / 1800 in `frontend/lib/trade-logic.js`). A 2026-07-25 audit (F-7) found the previously-documented relationship between the two scales was simply wrong. **Two different fairness vocabularies are live simultaneously on two surfaces.**

### 6.5 The arbitrage score

```
board_gain_norm = board_delta / max(give_model, 1)
arbitrage = board_gain_norm × 50            # f_board_edge
          + opp_appeal × 30                  # f_ktc_appeal
          + (10 if board_delta > 0 else 0)   # f_positive_bonus

if coverage == "partial":
    arbitrage × = 0.3
    arbitrage = min(arbitrage, 8.0)

source_confidence = min(1.0, avg_source_count / 5)
ktc_confidence    = 1.0 if full coverage else 0.7
arbitrage ×= 0.7 + 0.3 × (source_confidence × ktc_confidence)

arbitrage += min(1.0, min(give_model, recv_model) / 5000) × 5   # f_value_scale
```

**Worked example.** Give: player valued 6,000 on our board, KTC 5,200. Receive: player valued 7,000 on our board, KTC 4,800. Both full-KTC, both 6-source.
- `board_delta = 1000`; `board_gain_norm = 0.1667` → `f_board_edge = 8.33`
- `opp_appeal = (5200 − 4800)/4800 = 0.0833` → `f_ktc_appeal = 2.50`
- `f_positive_bonus = 10`
- Subtotal 20.83; confidence = min(1, 6/5)=1.0 × 1.0 → multiplier 1.0 → 20.83
- `f_value_scale = min(1, 6000/5000) × 5 = 5` → **arbitrage ≈ 25.8**

Note the shape: `f_positive_bonus` is a flat +10 for any positive board delta, which is larger than either graded term in this example. **A trade that gains 1 point on our board scores nearly the same as one gaining 1,000.** That is a real ranking distortion.

### 6.6 The suggestions rank score

```
rank_score = min(give_total, receive_total)/1000        # base magnitude
           + fairness_bonus                              # even 3.0 / lean 1.0 / stretch 0.0
           + confidence_bonus                            # high 2.0 / medium 1.0 / low 0.0
           + need_severity                               # 2.0 if starter_count==0, 1.0 if < needed
           + edge_bonus                                  # market_discount 1.5 / market_premium 1.0 / high_dispersion 0.5
           + opponent_fit                                # 1.5 if fit
           − overflow_penalty                            # 1.0 per receive-asset at a surplus position
```

`rank_score_breakdown` returns the same components for debugging, and the endpoint exposes it — good transparency.

**Weakness:** `base` is unbounded while every bonus is ≤ 3. A 9,000-value trade contributes 9.0 to base, dwarfing the entire qualitative stack (max ~8.5 including fit). **The ranking is dominated by trade size.**

**Structural smell:** `edge` and `opponent_fit` are read via `s.__dict__.get(...)` — they are annotations set post-construction rather than dataclass fields. Any refactor to `__slots__` or a frozen dataclass silently zeroes both bonuses, with no test failing.

### 6.7 External market vs internal model

| Aspect | Treatment |
|---|---|
| External market | `ktcSfTep` (offense) and `idpTradeCalc` (IDP) values, loaded into `canonicalSiteValues`. Standard `ktc` is loaded but **does not vote** since 2026-04-28. |
| Internal model | The blended consensus (`rankDerivedValue`) over 21 sources |
| How they differ | Internally: percentile-normalized, Hill-transformed, Hampel-filtered, count-aware-blended, TEP-multiplied, injury-discounted, single-source-haircut, IDP-calibrated, corridor-clamped |
| How the difference is exploited | Exactly the finder's premise: rank by `board_delta > 0` while `opp_appeal > 0` |

**How "fair externally, good for us internally" trades are identified:** that is the finder's entire definition. Both conditions are hard gates (7 and 5 in §6.4) and both feed the score. `_edge_label(board_gain_pct)` labels the magnitude; `_opp_appeal_phrase(appeal)` renders the counterparty framing.

**The circularity risk an auditor must weigh:** KTC and IDPTC are simultaneously (a) the two value-direct voters in the blend, (b) the market anchors for the corridor clamp, and (c) the "opponent's view" in the arbitrage calculation. On IDP the clamp binds the blend to within ±15% of IDPTC. So the finder is, on IDP, searching for arbitrage between IDPTC and a quantity constrained to lie within 15% of IDPTC. The available edge is bounded by construction. Additionally, `fantasyNavigatorSf` values carry `ktc_player_id` and are KTC-derived — a correlation the roadmap flags but does not correct for.

### 6.8 Roster legality and lineup consequences

**Roster legality is not enforced.** No trade generator checks roster size limits (58), position minimums, or taxi/IR eligibility. Lineup consequences are handled *soft*, via:
- `overflow_penalty` in `rank_score` (−1.0 per receive at a surplus position)
- `config/trade/team_impact.json` weights `fillStarter 1.0` / `depth 0.25` / `overflow 0.6`, composited `0.55 × fit + 0.45 × equity`, with verdict thresholds at ±20 / ±8

`src/trade/team_impact.py` is the module that computes lineup impact for the **simulator**; the suggestion generators use only the coarse penalty.

### 6.9 Duplicate and absurd trade filtering

| Mechanism | Where |
|---|---|
| Exact-package dedup | `_deduplicate` (`finder.py:580`) |
| Give-player appearance cap (2 across all categories) | `_apply_quality_filters` |
| Receive-target cap (2 per category) | same |
| Low-confidence cap (2 per category) | same |
| Both sides ≥ 2000 | same |
| Fire-sale guard (2 fillers for an elite) | `MULTI_FOR_ONE_MIN_RATIO`, `ELITE_MULTI_MIN_RATIO` |
| Package-anchor guard (2 bench stashes summing high) | `PACKAGE_ANCHOR_MIN_PCT 0.35` |
| Junk guard | `JUNK_THRESHOLD 400` |
| Self-trade guard | name-set intersection |
| Partial-KTC demotion | ×0.3, capped at 8.0, cannot rank above position 15 |

### 6.10 Multi-player package value, consolidation premium, liquidity discount

**Package value is a plain sum.** `give_model = sum(_mv(a) for a in give)`. There is **no** superadditivity for consolidation and **no** subadditivity for fragmentation in the finder's arithmetic.

The consolidation *premium* is expressed only as a **relaxed constraint**, not a value adjustment: `CONSOLIDATION_MIN_UPGRADE_RATIO = 0.70` permits the acquired star to be worth only 70% of the summed depth pieces, and `CONSOLIDATION_MAX_OVERPAY_RATIO = 0.30` allows overpaying by up to 30% of what you send. In effect the engine tolerates a ~30% consolidation tax rather than pricing the star higher.

**There is no liquidity discount model.** Nothing marks down hard-to-move assets or marks up single-asset trades for transactability. `MAX_BALANCERS = 2` and `MAX_PACKAGE_SIZE = 3` cap complexity structurally instead.

**Positional-scarcity adjustment inside trades: absent.** The LI-5 finding that QB waiver scarcity is 0.75 vs RB 0.21 in a superflex league has no path into any trade valuation.

---

## 7. External Inspiration and Feature Parity

| Source | Feature / idea | Status | Evidence |
|---|---|---|---|
| **Fantasy Navigator** | `fantasyNavigatorSf` ranking source (single JSON GET, `roster_type=sf_value`, `rank_type=dynasty`) | **Implemented** | Registry key at `data_contract.py:1361`; `scripts/fetch_fantasynavigator.py`; wired in `scheduled-refresh.yml:254` |
| Fantasy Navigator | Benchmark for overall feature inventory / gap matrix | **Partially implemented** | ROADMAP Phase 1 deliverables described; I found **no gap-matrix report file** in `docs/` |
| **PlayForKeeps (PFK)** | `pfkDynasty` ranking source via anonymous Supabase PostgREST `pfk_dynasty_rankings` (players AND picks, matched by `sleeper_player_id`) | **Implemented** | Registry key at `:1388`; `scripts/fetch_pfk.py`; workflow line 259 |
| PFK | `pfk_ktc_values` table | **Investigated and rejected** | It mirrors KTC SF-TEP; would double-count |
| PFK | Per-profile scraping | **Investigated and rejected** | Obsoleted by the single-table discovery |
| PFK | Sharp Tracker / sharp-money aggregation over a crawled league pool | **Implemented (our own bounded version)** | `src/intel/`, `/api/intel/*`, `frontend/app/intel/` |
| PFK | Thousands-league sharp pool | **Rejected for v1** | Scoped to league members' own leagues |
| PFK | News articles as a provider | **Implemented** | `src/news/providers/pfk.py` |
| PFK | Pick Projector (future pick → projected slot) | **Implemented** | `src/ros/pick_projection.py` (PR #541) — and the roadmap argues our playoff sim gives better inputs than PFK has |
| PFK | Player contracts / snap share | **Implemented via nflverse equivalents** | `src/playerctx/`, `src/nfl_data/` (PR #539) |
| PFK | Dispersal draft tool, creators/polls | **Rejected** | "not league-edge" |
| **KeepTradeCut** | `ktcSfTep` value-direct anchor; market anchor for the corridor clamp; opponent-appeal basis in the finder; top-150 quality gate | **Implemented** | Throughout |
| KeepTradeCut | Standard `ktc` as a voting source | **Retired 2026-04-28** | Still loaded for the arbitrage finder + per-source winner display |
| KeepTradeCut | Trade import/export interop | **Implemented** | `/api/trade/import-ktc`, `/api/trade/export-ktc`, `src/trade/ktc_import.py` |
| KeepTradeCut | Crowd FAAB signal | **Implemented** | `src/adapters/ktc_crowd_faab.py`, `_ktc_crowd_blend` |
| **IDP Trade Calculator** | `idpTradeCalc` value-direct source; the **only** source pricing offense and IDP on one combined scale; hierarchical anchor for IDP + picks; IDP market anchor for the clamp | **Implemented** | `:1039`, blend at `:6800+` |
| **Sleeper** | Rosters, users, matchups, transactions, traded picks, drafts, trending adds, player metadata, exact scoring keys, weekly stats | **Implemented** | `sleeper_overlay.py`, `sleeper_client.py`, `sleeper_trending.py`, LI-2 scorer |
| Sleeper | "Suggested FAAB" field | **Investigated — does not exist** | Docs grep confirmed; only historical `waiver_bid` on transactions |
| Sleeper | Losing bids | **Confirmed unavailable** | Documented as an irreducible selection bias in the FAAB notes |
| **ESPN** | News provider (general + per-player) | **Implemented** | `src/news/providers/espn.py`, `espn_player.py` |
| ESPN | Schema drift detection | **Implemented** | `src/api/espn_schema_drift.py`, `config/espn_schema_baseline.json` |
| **Stock-market platforms** | Value-history charts, movers, volatility exposure, portfolio insights, "buy/sell/hold" signals, arbitrage blotter, tiers/bands | **Implemented** | `frontend/lib/{value-history,movers,market-movers,portfolio-insights,signal-engine}.js`, `/edge`, `/finder`, `/trending` |
| Stock-market platforms | Confidence intervals on values | **Partially** | `src/canonical/confidence_intervals.py`, `rank_history_band.py` exist; UI surfacing unverified |
| **NFL scouting / draft systems** | Depth charts, snap share, opportunity stats, usage windows, realized points, contracts, archetypes | **Implemented (data layer)** | `src/nfl_data/*`, `src/playerctx/*`, `src/scoring/archetype_model.py` |
| **Other: DLF, DynastyDaddy, DynastyNerds, FantasyPros (SF/IDP/Fitzmaurice), FlockFantasy, Yahoo/Boone, DraftSharks, OTCFFB, FantasyCalc, IDPShow** | Ranking sources | **Implemented** | Registry lines 1086–1681 |
| **Underdog** | Best-ball ADP ingestion | **Planned only** | ROADMAP Phase 7 |

### 7.1 Legal / terms-of-service posture

This is worth stating plainly for the auditor, because the repository's own position is explicit and narrow:

- The roadmap declares the site **private personal use**, and on that basis treats "competitor-data ingestion for personal use" as acceptable, with a politeness commitment: **1 request per source per refresh cycle** (2h).
- PFK's data is read via **PFK's own embedded publishable Supabase key**. It is anonymously readable by design. Whether "readable" implies "licensed for ingestion into a competing analytics product" is a question the repo does not address and I cannot resolve.
- The Sharp Tracker reads other Sleeper users' **public** data. The repo commits to keeping intel "inside this private app" as a courtesy.
- `Dynasty Scraper.py` is browser automation against ranking sites. Terms-of-service exposure there is unassessed in-repo.

**Assessment: this is a genuine risk area with no legal review recorded anywhere in the repository.** It is low-probability while the site stays private and single-user; it becomes material the moment the site is shared beyond the league or monetized.

---

## 8. Autonomous Agent System

### 8.1 Scheduled workflows (GitHub Actions)

| Workflow | Schedule (UTC) | Purpose | Writes to repo? | Failure behavior |
|---|---|---|---|---|
| `scheduled-refresh.yml` | `42 */2 * * *` (every 2h) | Scrape + all fetchers + sanity gate + commit + deploy trigger + watchdogs | ✅ commits data | Per-source isolation via `run_fetcher`; sanity gate blocks commit; alert step on failure |
| `refit-hill-curves.yml` | `17 6 * * 2` (weekly Tue) | Refit the 4 Hill masters | ✅ constants | Unknown; not traced |
| `audit-dropped-sources.yml` | `23 7 * * 1` (weekly Mon) | Report Hampel drop rates per source | Report only | — |
| `audit-identity-matches.yml` | `17 8 * * *` (daily) | Identity match audit | Report only | — |
| `intel-refresh.yml` | `10 9 * * *` (daily) | POST intel refresh, poll ~6 min | ❌ (prod disk) | Idempotent failure issue, label `intel-stale` |
| `e2e.yml` | `23 6 * * *` (nightly) | Critical-journey Playwright suite | ❌ | — |
| `prod-e2e-smoke.yml` | `17 */4 * * *` | Public `/league` smoke | ❌ | — |
| `public-league-warmup.yml` | `*/20 * * * *` | Keep public league cache warm | ❌ | — |
| `health-check.yml` | `17 */6 * * *` | Site health | ❌ | — |
| `smoke-test.yml` | `15 6 * * *` | Daily smoke | ❌ | — |
| `weekly-narratives.yml` | `0 13 * * 3` + `0 14 * * 2` | Matchup narratives | ✅ likely | — |
| `deploy.yml` | dispatch + trigger | Deploy to VPS | — | `rollback.sh` exists |
| `pr-validation.yml` | on PR | CI | — | — |
| `claude.yml` | on mention | Claude Code GitHub app | — | — |

Plus two out-of-band shell loops on the VPS: `deploy/dlf_fetch_and_push.sh` and `deploy/idpshow_fetch_and_push.sh`, visible in git log as `chore(dlf)` / `chore(idpshow)` commits roughly hourly.

**Commit-noise observation:** on 2026-07-26 the automation produced ~20 commits to `main` (4 distinct chore types, some pairs like `chore: freshness stamps` immediately followed by `chore: automated data refresh` 2 seconds apart). That pairing looks like two commits where one would do.

### 8.2 Repo-local skills (`.agents/skills/`)

| Skill | Purpose |
|---|---|
| `performance-optimizer` | Page-load / payload work |
| `scraper-ops` | Scraper + source operations |
| `design-taste-director` | Design system custodianship |
| `blueprint-auditor` | Blueprint conformance |
| `reality-check-review` | Adversarial "is this actually wired" review |
| `value-pipeline-auditor` | Valuation pipeline audit |

I did not read their contents in depth. **They are prompts, not running processes** — they only act when invoked.

### 8.3 The orchestrated agent fleet (`docs/ORCHESTRATION.md`)

| WS | Workstream | Owner | Branch | Status as recorded | Actual PR state |
|---|---|---|---|---|---|
| A | Redesign R2 — rankings + profiles | design custodian | `claude/redesign-r2-rankings` | "Testing (PR imminent)" | **Merged** (#549) |
| B | Redesign R3 — dashboard/news/market | news-domain agent | `claude/redesign-r3-surfaces` | "Ready (awaiting R2)" | **Open** (#551, CI ✅) |
| C | Redesign R4 — war room + trade | trade-domain agent | `claude/redesign-r4-warroom` | "Ready (awaiting R2)" | **Open** (#552, CI ✅) |
| D | Redesign R5 — perf/a11y/mobile + dead-CSS purge | design custodian | `claude/redesign-r5-polish` | "Blocked by B+C" | **Not opened** |
| E | League Intelligence LI-1..LI-8 | league-intel agent | `claude/league-intel-foundation` | "In progress" | **Open** (#550, CI ✅) |
| F | LI-9 UI valuation-mode toggle | design custodian | TBD | "Blocked by E(LI-4)+A" | **Not opened** |
| G | E2E safety net upkeep | e2e agent | `claude/e2e-r1-reconcile` | "In progress" | **Open** (#554, red on a one-file lint gate) |
| H | Identity sweep | identity agent | `claude/identity-sweep` | "Converging" | **Merged** (#547); defect handed to #550 |
| I | Ops: cron/deploy/VPS | orchestrator | `main` dispatch | "intel 401 user-blocked (issue #545)" | Open blocker |
| R | Fresh-eyes review | reviewer agent | read-only | "At integration checkpoints only" | — |

Idle agents with retained context, to be resumed rather than cold-spawned: intel, FAAB, playerctx, news, prod-hardening.

### 8.4 Per-agent detail

Inputs/outputs/dependencies are as recorded in `ORCHESTRATION.md` §3–4:

- **Shared frozen contracts:** `ds/` component APIs + tokens (design custodian owns; others may ADD primitives but not mutate); `nav-model.js` (single IA source); `/api/data` + `buildRows` purity (orchestrator; frozen, no client-side value math ever); `league_registry.rosterSettings` (league-intel agent, frozen after LI-1); Sleeper stat-key vocabulary (ADR-005); `getActiveValue()` selector (LI-4).
- **High-conflict files with rules:** `server.py` (append-only sections per workstream), `package.json`/lockfile (single-owner edits), `globals.css` (R5 owns the purge; others additive only).
- **Dependency graph:** `R2 → (R3 ∥ R4) → R5 → final integration`; `LI-1/2 → LI-3 → LI-5 → LI-7`; LI-4 independent after LI-1 and unlocks F; LI-6 after LI-2, feeds LI-7; LI-8 after LI-3.

**Failure/retry/observability posture:** the orchestration doc's only stated failure mitigation is "credit outages (mitigated: liveness tick auto-resumes agents)". There is **no** documented retry policy, no per-agent timeout, no dead-man's-switch, and no dashboard beyond the hand-maintained table in the doc itself. **PR #553's own headline is that this table was "describing a state two merges old"** — which is direct evidence that the observability mechanism (a human/agent-updated markdown table) failed at its one job.

### 8.5 Duplicated responsibilities, races, and consolidation opportunities

**Duplicated responsibility:**

1. **`intel-refresh.yml` vs `scheduled-refresh.yml`.** Deliberately separated for failure isolation (recorded), which is correct. Not a defect.
2. **`e2e.yml` (nightly full) vs `prod-e2e-smoke.yml` (4-hourly public) vs `smoke-test.yml` (daily) vs `health-check.yml` (6-hourly).** Four overlapping health signals with four alert paths. **Consolidation candidate.**
3. **DLF/IDPShow VPS shell loops vs `scheduled-refresh.yml` fetchers.** Two ingestion mechanisms writing to the same repo on different cadences from different machines. This is the clearest **race-condition candidate** in the system: both push commits to `main`.
4. **`docs/ORCHESTRATION.md` (dashboard) vs GitHub PR state (truth).** Documented divergence; PR #553 exists specifically to fix it. The dashboard should be *generated*, not maintained.
5. **`docs/ROADMAP-competitor-parity.md` vs `docs/league-intelligence/MASTER_PLAN.md`** — two live plans with overlapping scope (both touch values, FAAB, trades) and no cross-reference of precedence.

**Race conditions:**

- Multiple agents + two VPS cron loops + `scheduled-refresh.yml` all commit to `main`. `AGENTS.md` states "Do not let multiple assistants edit the same branch at the same time" but nothing enforces it.
- `data/intel/snapshot_<key>.json` is written by `src/intel/store.py` and *read by a path-mirroring derivation* in `src/trade/faab_contention.py` that deliberately does **not import** `src.intel`. The drift risk is real; it is pinned only by a parity test. The comment even records that a legacy single-file `data/intel/snapshot.json` "never shipped; reading it would pin `intel_f` at 1.0 forever" — i.e. this seam has already failed once in design.

**Unnecessary PR workflow:** the doc itself retired the ~13-merges/day mode. **But #553 is a docs-only PR that stays open to accumulate coordination-doc changes** — a PR used as a working document. That is a reasonable adaptation but it means orchestration state lives in an unmerged branch, invisible to anyone reading `main`.

**Safe parallelization opportunities:** R5 (global CSS purge) genuinely must wait. But LI-6 (projection re-scoring) has no dependency on the redesign track at all and is currently unstarted while D and F wait on frontend merges.

### 8.6 Is any of it actually working?

| Claim | Verified? |
|---|---|
| Data refresh runs | **Yes** — git log shows `chore: automated data refresh` at 2026-07-26 17:46, and `ktc.csv` (501 lines) + `idpTradeCalc.csv` (901 lines) were 0h old at session start |
| DLF/IDPShow loops run | **Yes** — `chore(dlf)` 18:27, `chore(idpshow)` 18:32 |
| Intel refresh runs | **No — recorded as failing.** `ORCHESTRATION.md`: "intel 401 user-blocked (issue #545)"; "intel cron stays red until user runs the journalctl step" |
| E2E suite runs | **Was not runnable.** PR #554: "Two agents in a row could not get a real run." The backend died at import without `JASON_LOGIN_PASSWORD`; without `E2E_TEST_MODE` every signed-in spec skipped and the suite **reported green while asserting nothing** |
| Hill refit runs | **Not verified** |
| Tier fitter runs | **Not verified; likely never** |
| Deploy runs | **Not verified in this session** |

---

## 9. Work Actually Completed

### 9.1 In this session — the honest answer

**Zero code changes.** Verified:

```
git rev-parse HEAD          → c534280d
git rev-parse origin/main   → c534280d
```

The branch `claude/session-audit-handoff-tvxfc1` is identical to `origin/main`. There is no merge base with a divergent `main` because the branch *is* `main`.

| Artifact | This session |
|---|---|
| Files created | 1 — `docs/CLAUDE_SESSION_AUDIT_HANDOFF.md` (this document) |
| Files modified | 0 |
| Commits | 1 (this document, when committed) |
| PRs opened | 1 (for this document) |
| Database migrations | 0 |
| Environment variables added | 0 |
| External services touched | GitHub API (read-only: `list_pull_requests`) |
| Tests run | **0 — pytest is not installed in this container.** `python -c "import pytest"` → `ModuleNotFoundError`. The SessionStart hook reported the same. |
| Builds run | 0 |
| Deployments | 0 |

I have **not** verified any test result, build result, or deployment result in this session. Every test figure quoted elsewhere in this document (e.g. "249 passed", "3234 passed") is **quoted from a PR body written by another agent** and is unverified by me.

### 9.2 Work completed in the reconstructable window (merged to `main`)

File-by-file inventory is not possible for 16 merged PRs without reading 16 diffs; what follows is per-PR, with the caveat that "production-ready" reflects the PR's own claim plus my inspection of the landed code, not an independent verification.

| PR | Key paths | Why | Production-ready? | Tested? | Known issues |
|---|---|---|---|---|---|
| #533 | `frontend/app/news/`, `src/news/providers/pfk.py`, `frontend/lib/news-service.js` | News tab; kill silent mock fallback | Yes | `tests/news/` exists | — |
| #535 | `frontend/lib/player-filters.js`, contract `team`/`yearsExp` enrichment | Search/filter system | Yes | vitest | `team` was 0/1077 populated before this |
| #536 | `frontend/app/tokens.css`, `ds.css`, `docs/DESIGN-SYSTEM.md` | Design system R0 | Yes | — | — |
| #537 | `deploy/*` | Prod hardening | **Prepared, NOT applied** | — | Nothing is live |
| #538 | `src/trade/faab_contention.py`, `src/adapters/sleeper_trending.py` | FAAB v2 | Backend yes | `tests/trade/test_faab_contention.py` (14 enumerated cases) | **Had no UI until #552** |
| #539 | `src/playerctx/`, `src/nfl_data/` | Contracts/snaps/depth | Yes | `tests/playerctx/`, `tests/nfl_data/` | — |
| #540 | `src/news/providers/espn_player.py`, `src/news/digest.py` | Per-player news, 7-day cutoff | Yes | — | — |
| #534 | `src/intel/`, `/api/intel/*`, `intel-refresh.yml`, `frontend/app/intel/` | Sharp Tracker v1 | Backend yes | `tests/intel/` | **Cron 401-blocked (issue #545) — the feature has no data in prod** |
| #541 | `src/ros/pick_projection.py` | Pick Projector | Yes | `tests/ros/test_pick_projection.py` | Test injects synthetic values, pins no live ordering |
| #542 | `AppShellWrapper.jsx`, `frontend/lib/nav-model.js` | Shell + IA + universal search | Yes | — | `/waivers` and `/news` reported **absent from the IA** by #554 |
| #543 | `tests/e2e/`, `e2e.yml` | E2E safety net | **No** | — | Suite was not actually runnable; see #554 |
| #544 | `intel-refresh.yml` | Intel auth diagnostics | Attempted fix | — | Did not resolve the 401 |
| #546 | `docs/league-intelligence/*`, `config/league_intel/sleeper_league_snapshot_2026-07-26.json` | LI-0 audit | Docs | — | Surfaced the 8-field registry staleness |
| #548 | `docs/ORCHESTRATION.md` | Orchestration plan | Docs | — | Went stale within hours |
| #547 | identity matching + audit tooling | Recover votes lost to name drift | Yes | `tests/identity/` | Left an aggregate-join defect, handed to #550 |
| #549 | `frontend/app/rankings/`, PlayerPopup | Redesign R2 | Yes | — | — |

### 9.3 Work in flight (open PRs, NOT on `main`)

| PR | Branch | CI | What it contains | Risk if not merged |
|---|---|---|---|---|
| #550 | `claude/league-intel-foundation` | ✅ | LI-1..LI-7: canonical config, **registry fix (8 fields)**, exact scorer (1,415/1,415 reconcile), exact best-ball optimizer, **`fantasy_positions` eligibility fix**, `_positional_coverage` fix, replacement levels, value schema, adjustment guardrails | **Highest.** Production is running a wrong lineup model and locking hybrid IDPs out of legal slots |
| #551 | `claude/redesign-r3-surfaces` | ✅ | `/news`, `/edge`, `/finder` rebuilt | Medium |
| #552 | `claude/redesign-r4-warroom` | ✅ | `/draft`, `/trade`, `/trades`, `/angle`, `/waivers` rebuilt + **FAAB contention's first UI (~130 new lines, `components/waivers/FaabRecommendation.jsx:98-230`)** | Medium; the FAAB UI is genuinely new code the PR itself asks to be reviewed as such |
| #553 | `claude/this-keeps-happening-ly8avw` | — | Orchestration docs, retractions, §2b evidentiary rule | Low |
| #554 | `claude/e2e-r1-reconcile` | ❌ red on a one-file lint gate | One-command runnable E2E suite; verified 149 passed / 0 failed / 29 skipped / 9.3 min against the stacked redesign | High — without it there is no honest test signal |

### 9.4 Environment variables

From `.env.example`: `FRONTEND_URL`, `SLEEPER_LEAGUE_ID`, `BASELINE_LEAGUE_ID`, `SLEEPER_TRADE_HISTORY_DAYS`, `JASON_LOGIN_USERNAME`, `JASON_LOGIN_PASSWORD`, `JASON_AUTH_COOKIE_SECURE`, `DISK_SPACE_MIN_MB`, `LOG_FORMAT`.

Referenced in code but **not** in `.env.example`: `PRIVATE_APP_ALLOWED_USERNAMES`, `SESSION_TTL_DAYS`, `FRONTEND_RUNTIME`, `ALLOW_DEFAULT_LOGIN_DEV`, `E2E_TEST_MODE`, `UPTIME_CHECK_ENABLED`, `CANONICAL_DATA_MODE` (retired). **`.env.example` is incomplete** — and PR #554's root-cause was precisely that the E2E harness didn't know `JASON_LOGIN_PASSWORD` was required at import.

---

## 10. Unfinished Work and Technical Debt

### CRITICAL

| # | Item | Detail |
|---|---|---|
| C1 | **`config/leagues/registry.json` rosterSettings are stale on 8 fields in production** | TE 1→2, K missing, DL/LB/DB 2→3, IDP_FLEX 2→0, rosterSize 30→58, taxi 5→0. Every consumer — ROS lineups, FAAB `analyze_roster`, `DEFAULT_STARTER_NEEDS`, playoff sim, draft capital — models the wrong league. Fix exists on #550, unmerged. |
| C2 | **Hybrid IDPs locked out of legal slots in production** | `_hydrate_overlay_players` keeps `position`, but Sleeper evaluates against `fantasy_positions`. Empirically confirmed: reconstruction scored below the host on 5/10 weeks. Fix on #550, unmerged. |
| C3 | **`src/trade/suggestions.py::DEFAULT_STARTER_NEEDS` is a hardcoded mirror of the stale lineup** | Directly corrupts every trade suggestion's need/surplus logic today. |
| C4 | **The E2E suite reported green while asserting nothing** | Without `E2E_TEST_MODE`, every signed-in spec skipped. Any "CI is green" claim made before #554 is worthless for authenticated surfaces. |
| C5 | **pytest is not installed in the standard session container** | The SessionStart health hook fails at "Test Collection". Agents cannot self-verify. Every test claim in this repo currently comes from an agent asserting it ran tests somewhere else. |

### HIGH

| # | Item | Detail |
|---|---|---|
| H1 | **TEP multiplier 1.15 contradicts the measured ≈1.12** | Measurement is on an unmerged branch and explicitly labelled "a finding, not a published value". Live values carry an over-application. |
| H2 | **Intel cron 401-blocked (issue #545)** | Sharp Tracker has a UI, endpoints, tests, and an empty snapshot. `intel_f` in FAAB is permanently 1.0. |
| H3 | **Two contradictory single-source penalties** | Blend applies ×0.30; finder applies ×0.88. Same phenomenon, 58 points apart. |
| H4 | **Two contradictory fairness vocabularies** | `FAIRNESS_TOLERANCE 769` (suggestions) vs 350/900/1800 (`trade-logic.js`). Code comment admits 769's origin is undocumented legacy tuning. |
| H5 | **IDP consensus is bounded to ±15% of one source** | The corridor clamp makes "21-source consensus" partly illusory on IDP, and this is not disclosed in the UI. |
| H6 | **Page proxy serves the anonymous shell to signed-in sessions** | Reported by #554's first real run; owned by nobody, filed as "product defects surfaced, owned elsewhere". |
| H7 | **`/waivers` and `/news` absent from the navigation IA** | Same source. |
| H8 | **6 duplicate player rows in `data/ros/aggregate/latest.json`** | `nate landman`, `cam skattebo`, `cam ward`, `tank dell`, `cam bynum`, `mitch tinsley` each present as both lowercase and Title Case with ROS value split across two rows. Plus 16 rows with non-lowercase `canonicalName` → **40 of 666 rostered players fail to join.** |
| H9 | **`docs/ORCHESTRATION.md` dashboard is hand-maintained and was two merges stale** | The coordination mechanism's own failure mode. |
| H10 | **Prod hardening prepared but not applied** | #537 landed configs; nothing is live. |
| H11 | **VPS cron loops and CI both push to `main`** | Unguarded concurrent writers. |

### MEDIUM

| # | Item |
|---|---|
| M1 | `_MAD_PENALTY_LAMBDA = 0.0` and `madPenaltyApplied = None` are dead fields kept only because frontend builds still read the key |
| M2 | The ROOKIE Hill curve is refit weekly and never routed |
| M3 | `player_valuation.py` maintains two parallel curve parameterizations (percentile-form + rank-form) with nothing enforcing agreement; `run_valuation` and its constants (`W_MEDIAN`, `CLIFF_*`, `VOL_*`) may be entirely dead |
| M4 | `config/tiers/thresholds.json` values are self-described priors; unclear whether `fit_tier_thresholds.py` has ever run |
| M5 | `config/weights/default_weights.json` is dead config still present in the tree |
| M6 | `power_v2` loses 55% of its weight in the offseason with unverified renormalization |
| M7 | `classify_team` accepts `team_ros_strength_percentile` and uses it only in a display string |
| M8 | `classify_team`'s 0.20–0.25 playoff band shadows "Selective Seller" |
| M9 | `rank_score` is dominated by trade size (unbounded base vs ≤3 bonuses) |
| M10 | `f_positive_bonus = 10` in the finder is a flat step function larger than the graded terms in typical cases |
| M11 | `edge`/`opponent_fit` read via `__dict__.get` would silently zero under a dataclass refactor |
| M12 | No 2-for-2 generator despite `MAX_PACKAGE_SIZE = 3` |
| M13 | No roster-legality checking in any trade generator |
| M14 | Package values are plain sums — no consolidation premium or fragmentation discount in the arithmetic |
| M15 | LI-5 scarcity (QB 0.75 vs RB 0.21) has no path into trade or waiver valuation |
| M16 | `.env.example` is missing at least 6 variables the code reads |
| M17 | Two overlapping live plans (`ROADMAP-competitor-parity.md`, `league-intelligence/MASTER_PLAN.md`) with no precedence |
| M18 | Four overlapping health/smoke workflows |
| M19 | `_positional_coverage` fix moves composites by ≤0.46 and changes no rank order — correct but near-useless at 5% weight |
| M20 | Fantasy Navigator values are KTC-derived (`ktc_player_id`); the correlation is documented but not corrected for |
| M21 | Injury discount cap of 5% makes catastrophic and trivial injuries nearly indistinguishable; the Aug 31/Sep 1 offseason boundary is a discontinuity |
| M22 | `trend_score` weights (3/2/1) over nested windows are unsourced and effectively weight a 30-hour-old transaction 6× |
| M23 | `_ALPHA_SHRINKAGE = 0.10` accepts ~2× worse stability than the backtest optimum for principled reasons — defensible but unsettled |
| M24 | `_HAMPEL_K = 2.75` has no cited backtest, unlike α and λ |
| M25 | Pick discounts 0.82/0.66/0.53 unsourced |
| M26 | No gap-matrix / competitor-audit report file found in `docs/` despite being a Phase 1 deliverable |
| M27 | Two-way player boost is a max() not a blend — optimistic by construction |

### LOW

| # | Item |
|---|---|
| L1 | Automation commits ~20/day to `main` with paired commits 2 seconds apart |
| L2 | `Dynasty Scraper.py` is 307 KB in one file |
| L3 | `server.py` is 10,707 lines with "append-only sections per workstream" as the coordination strategy |
| L4 | `src/api/data_contract.py` is 9,009 lines |
| L5 | A 3.4 MB `Dynasty Trade Calculator.pdf` is committed at repo root |
| L6 | `docs/status/` holds 22 dated one-off reports with no index or retention policy |
| L7 | `Jenkinsfile` present alongside GitHub Actions — likely dead |
| L8 | `codex_loop.py` (28 KB) + `codex_loop_config.example.json` at root — provenance/relevance unclear |
| L9 | An SSH-grant workflow was added and deleted the same day with no recorded reason |
| L10 | Mobile: no evidence of a mobile audit beyond R5's planned sweep; #551's mobile-order regression was inert-fixed once already |

### Security / privacy specifics

| Severity | Item |
|---|---|
| **High** | The added-then-deleted `grant-ssh-access.yml` needs explanation. If it ever ran, credentials may have been exposed. |
| Medium | `PRIVATE_APP_ALLOWED_USERNAMES` defaults to `jasonleetucker` if unset — fail-open on the *name*, though the password still gates. |
| Medium | The Sharp Tracker aggregates other real users' Sleeper activity. Legally public; ethically it is surveillance of league-mates. The repo's mitigation is "keep it inside this private app" — a policy, not a control. |
| Medium | No legal/ToS review recorded for scraping DLF, KTC, DynastyDaddy, FantasyNavigator, PFK. |
| Low | Guest passes mint sessions; revocation exists and sessions carry `guest_pass_id`, which is good. |

---

## 11. Contradictions and Unresolved Decisions

| # | Contradiction | Which side currently controls the implementation |
|---|---|---|
| 1 | **Stability vs. velocity.** `CLAUDE.md` rule 3: "Preserve working behavior unless a verified flaw requires change." `ORCHESTRATION.md`: "Optimize for the final integrated system, not constant main-branch stability." | **ORCHESTRATION wins.** 16 PRs merged in one day; the redesign track rewrote nine surfaces. |
| 2 | **"One live path" vs. two trade engines, two fairness scales, two single-source penalties, three lineup configs.** | **The duplicates win in practice.** The rule is stated but not enforced by any test. |
| 3 | **Consensus-of-many vs. anchored-to-one.** Product claim: 21-source consensus. Implementation: IDP is clamped to ±15% of IDPTC; IDP + picks use α=0.10 against a single anchor; the backtest optimum was α=0 (use IDPTC alone). | **Anchoring wins on IDP and picks; consensus wins on offense.** This split is deliberate and documented, but it means the product's headline claim is only true for QB/RB/WR/TE. |
| 4 | **Accuracy vs. stability (α).** Backtest said α=0; product principle said α>0. | **Principle wins at α=0.10**, with a recorded ~2× stability cost. |
| 5 | **Measured TEP ≈1.12 vs. applied 1.15.** | **1.15 wins** — the measurement sits on an unmerged branch and was deliberately not published. |
| 6 | **Current-season vs. dynasty horizon.** Injury discount caps at 5% and zeroes Feb–Aug (dynasty framing), while ROS values, FAAB, and playoff sims are explicitly current-season. | **Both run, on different surfaces, with no reconciliation.** A player can be −0% on the board and unstartable in the sim. |
| 7 | **Offense vs. IDP treatment.** Offense: flat blend, no clamp, no calibration post-pass. IDP: hierarchical anchor, calibration pass, ±15% clamp. | **Asymmetry wins, deliberately.** The IDP machinery exists because IDP source quality is worse. But it means IDP values are structurally less able to disagree with the market than offense values. |
| 8 | **UI ambition vs. architecture.** LI-5 produces six scarcity components and four replacement tiers; LI-4 produces a three-field value schema and a selector. The UI toggle (WS-F) is unstarted and blocked. | **Architecture is ahead of UI.** Multiple engines have no surface: FAAB contention had none until #552; LI-4/5/7 have none at all. |
| 9 | **Autonomous development vs. branch safety.** `AGENTS.md`/`CLAUDE.md`: "Do not let multiple assistants edit the same branch at the same time" and use task branches. `ORCHESTRATION.md`: one branch per *workstream*, batched, push often, PR rarely. | **ORCHESTRATION wins.** The older per-task rule is superseded but still printed in two files, which will mislead the next agent that reads `CLAUDE.md` first. |
| 10 | **"Completed" vs. actually completed.** #553 documents that the dashboard was two merges stale; #550 retracts three earlier published findings; #543 shipped an E2E suite that could not run; #534 shipped Sharp Tracker whose data pipeline is 401-blocked. | **Reality wins, but only after adversarial review caught it.** The system's self-reports have been unreliable at a measurable rate: six evidentiary failures across three workstreams. |
| 11 | **`docs/ROADMAP-competitor-parity.md` vs `docs/league-intelligence/MASTER_PLAN.md`.** Both are live plans; both claim ownership of value/FAAB/trade evolution. | **Unresolved.** No precedence is stated anywhere. |
| 12 | **Speed vs. correctness in the payload path.** `CLAUDE.md` Performance Rules demand smaller payloads; the delta view drops ~70%. But `buildRows` must fail fast rather than recompute, so a partial payload yields an empty board rather than a degraded one. | **Correctness wins**, correctly. Worth noting only because it is a *good* resolution of a real tension. |

---

## 12. Claude's Self-Audit

The instruction was to be adversarial and not defend the implementation. Three of these concern *this* session; the rest concern the work visible in the repository, which I am also willing to criticize despite not having authored it in view.

### 12.1 About this session specifically

1. **I was asked to reconstruct a session I cannot see, and the honest answer is that I cannot.** The single most useful thing I can tell the reviewer is that §2 is archaeology, not recall. If this document is read as a transcript, it will mislead. I have flagged it three times; it is still the document's largest weakness.

2. **I could not run a single test.** pytest is absent from the container. Every quantitative validation claim in this document — 1,415/1,415 reconciliations, 249 league_intel tests, 3,234 suite passes, 149 E2E passes — is **quoted from PR bodies written by other agents**, and those same agents' claims have been caught wrong six times in this repository in the last day. I have not independently verified any of it, and the reviewer should treat all of it as unverified.

3. **I read roughly 3,000 of the ~27,000 lines in the four largest modules.** `server.py` (10,707), `data_contract.py` (9,009), `Dynasty Scraper.py` (307 KB) and the frontend were sampled by targeted grep, not read. Statements like "there is no acceptance-probability model" are grep-negative results across `src/`, which is strong but not conclusive. `run_valuation` being dead is an inference from `CLAUDE.md`, **not verified by tracing the call graph** — I flagged it rather than resolving it, and I should have resolved it.

### 12.2 Formula problems I would escalate

4. **The single-source penalty is incoherent across the system.** ×0.30 in the blend, ×0.88 in the finder. Both are labelled as the same concept. At least one is wrong, and neither cites evidence.

5. **`f_positive_bonus = 10` is a step function in a graded score.** In my worked example it exceeded both graded terms combined. It makes the finder's ranking substantially a binary "is board_delta positive" sort with tie-breaking, which is not what the surrounding code implies.

6. **`rank_score`'s base term is unbounded.** `min(give,receive)/1000` reaches 9.0 while the entire qualitative stack maxes near 8.5. The suggestion feed is primarily a "biggest trades" feed wearing a quality score.

7. **The IDP corridor clamp undermines the product thesis and nobody says so in the UI.** If IDP values cannot deviate more than 15% from IDPTC, then the IDP arbitrage finder is searching a space bounded by construction, and "our consensus disagrees with IDPTC" is a claim the system is not permitted to make loudly.

8. **`trend_score`'s nested windows double- and triple-count recent events** with no stated intent. If intended, it should be documented as an effective decay; if not, it's a bug.

9. **The 5% injury cap plus a month-based offseason switch is too coarse for a product whose thesis is precision.** A season-ending Achilles on August 31 is priced at zero.

### 12.3 Architectural weaknesses

10. **`server.py` at 10,707 lines with "append-only sections per workstream" as the concurrency strategy is not an architecture, it's a queue discipline.** It works only while agents cooperate. Nothing enforces it.

11. **Three independent representations of the league's lineup** (registry JSON, ROS slot flattening, `DEFAULT_STARTER_NEEDS`) is the direct cause of C1/C3. The fix in #550 corrects the values but does not eliminate the duplication — `DEFAULT_STARTER_NEEDS` remains a hardcoded dict. **It will go stale again.**

12. **`faab_contention.py` deliberately does not import `src.intel` and instead re-derives the snapshot path by string convention**, pinned only by a parity test. The comment itself records that a prior version of this seam would have "pinned `intel_f` at 1.0 forever". This is a known-fragile coupling that was solved with a test instead of an interface.

13. **The orchestration dashboard is a markdown table maintained by hand.** It failed. State that is derived from PR/CI reality should be generated from PR/CI reality.

### 12.4 Overengineering

14. **Four scope-level Hill masters refit weekly, one of which is never routed.** The ROOKIE curve is compute and complexity with no consumer.

15. **Six scarcity components, four replacement tiers, a three-field value schema, an evidence-tier adjustment engine with three guardrails — and zero user-visible output.** LI-4/5/7 is a large, careful, well-tested subsystem that currently changes nothing, by design. The design is right (no-op until validated); the *sequencing* means substantial effort sits unmerged and unused while `DEFAULT_STARTER_NEEDS` is wrong in production.

16. **Two full trade engines plus a simulator plus a Monte Carlo plus an angle/package builder plus correlation matrices**, when neither engine models acceptance probability, roster legality, or scarcity. Breadth was bought before depth.

### 12.5 Underengineering

17. **No acceptance-probability model at all**, in a product whose central promise is finding trades a counterparty will take. `opp_appeal > 0` is a gate, not a probability.

18. **No liquidity or package-complexity discount.** Real dynasty trades fail on complexity; the model prices a 3-for-1 identically to a 1-for-1 of the same sum.

19. **No positional adjustment anywhere in the value curve.** In a superflex league where measured QB waiver scarcity is 3.5× RB's, the Hill curve treats QB12 and RB12 identically and relies entirely on the sources to have priced it.

20. **`.env.example` incompleteness directly caused a multi-agent failure** (#554's root cause). A trivial file, two agents lost.

### 12.6 Claims of progress that exceeded reality

I am reporting these because the reviewer needs the pattern, not because I authored them:

21. `docs/ORCHESTRATION.md` described WS-A as "Testing (PR imminent)" when it had merged.
22. Three separate "external corroboration" claims were later shown to be assumptions reflected back.
23. `FLEX: TE 0`, "TE demand overstated 46%", and the `3.79` depth figure were all published as findings and later retracted.
24. `_positional_coverage` returned a constant 100.00 for all 12 teams while contributing to a composite presented as measured.
25. `projection_corroborated` was computed from a condition that could never fire.
26. A CSS fix was merged that could not take effect.
27. An E2E suite reported green while skipping every authenticated spec.

**To the repo's credit, every one of these was caught and documented by its own adversarial review process, and §2b of `ORCHESTRATION.md` now encodes the lesson.** That is the healthiest thing in this project. It is also evidence that the base rate of unverified claims is high enough to require it.

### 12.7 What should be rewritten or removed

| Action | Target |
|---|---|
| **Rewrite** | `DEFAULT_STARTER_NEEDS` → derive from the canonical config, not a dict |
| **Rewrite** | Unify the two single-source penalties and the two fairness scales into one shared module |
| **Rewrite** | `rank_score` and `arbitrage` to bound the dominant terms |
| **Rewrite** | The orchestration dashboard as generated output |
| **Remove** | `config/weights/default_weights.json`, `Jenkinsfile` (if dead), the committed 3.4 MB PDF, `madPenaltyApplied`, the unrouted ROOKIE curve refit |
| **Remove or route** | `run_valuation` + `W_MEDIAN`/`CLIFF_*`/`VOL_*` if confirmed dead |
| **Resolve** | The added-then-deleted SSH workflow |

### 12.8 Decisions a senior engineer should independently verify

1. α = 0.10 over the backtest's α = 0 — is the consensus principle worth 2× stability?
2. The ±15% IDP corridor clamp — does it invalidate IDP arbitrage?
3. `_SINGLE_SOURCE_VALUE_RETENTION = 0.30` — where does 0.30 come from?
4. `_HAMPEL_K = 2.75` and `_HAMPEL_MIN_THRESHOLD = 1000` — is the floor now too permissive?
5. `_PERCENTILE_REFERENCE_N = 500` truncation vs. a 696-spot rostered universe.
6. Whether the offense flat-blend / IDP-hierarchical asymmetry is principled or path-dependent.
7. Whether the TEP multiplier should drop to the measured 1.12.
8. Whether `power_v2` renormalizes correctly when 55% of its weight is missing.

---

## 13. Recommended Next Steps — 7-day execution order

Priority order per the stated ranking: data/formula correctness → agent coordination → core functionality → testing → performance → UI → deployment. Production continuity is explicitly *not* prioritized.

### Day 1 — Correctness of what is already true but not live

1. **Merge #550.** It is CI-green and it fixes C1, C2, C3, and the coverage constant. Everything else in this list is less valuable than getting production onto the correct lineup model. Do this before any redesign merge so the frontend work integrates on top of correct data.
2. **Fix the container so agents can run tests** (add pytest + deps to the SessionStart environment, or a `requirements-dev` install step). Until this is done, every agent claim is unfalsifiable. This is the meta-fix that makes the rest of the week trustworthy.
3. **Complete `.env.example`** with the six-plus missing variables, and add a startup assertion listing what is required. This is 20 minutes and it already cost two agents a day.

### Day 2 — Formula reconciliation

4. **Resolve the two single-source penalties** (0.30 vs 0.88) into one constant in one module, with a recorded rationale.
5. **Resolve the two fairness scales** (769 vs 350/900/1800) — pick one vocabulary, or name them distinctly so nobody assumes they relate.
6. **Decide the TEP multiplier.** Either adopt the measured ≈1.12, or record explicitly why 1.15 stands. Do not leave a measured contradiction unaddressed in the tree.
7. **Trace and delete or route `run_valuation`** and its constants. Answer the dead-code question definitively.
8. **Fix the `data/ros/aggregate/latest.json` duplicate rows and case drift** (H8) — 40 of 666 rostered players currently fail to join.

### Day 3 — Agent coordination

9. **Merge #553** and make the dashboard generated: a script that reads PR/CI state and rewrites the table, run by the existing health workflow. Remove the hand-maintained table.
10. **Reconcile `CLAUDE.md` / `AGENTS.md` / `ASSISTANT_COORDINATION.md` with `ORCHESTRATION.md`.** The per-task-branch rule is superseded but still printed first in the file every agent reads. Fix the ordering conflict.
11. **Establish precedence between the two live plans** (competitor-parity roadmap vs LI master plan), or merge them.
12. **Serialize the writers to `main`**: the VPS DLF/IDPShow loops and `scheduled-refresh.yml` both push. Give them non-overlapping windows or a lock.
13. **Resolve the intel 401 (issue #545).** Sharp Tracker is fully built and has never had data.

### Day 4 — Core functionality: close the engine-to-surface gaps

14. **Merge #551 and #552** in dependency order. Review #552's `FaabRecommendation.jsx:98-230` as new code, not a migration — it renders bid guidance a manager spends real money against.
15. **Wire LI-5 scarcity into FAAB and trade valuation.** Six measured scarcity components with no consumer is the largest built-but-unused asset in the repo, and QB-vs-RB scarcity in superflex is exactly the edge the product exists to find.
16. **Add the missing 2-for-2 generator** or document why it's excluded.

### Day 5 — Testing and validation

17. **Merge #554** (fix the one-file lint gate first). Then run the suite and record the result *in the repo*, not in a PR body.
18. **Apply the §2b rule retroactively to the highest-value assertions**: for each of the three retracted findings and each guardrail in LI-7, write the test that fails when the mechanism is disconnected, and **observe it fail** against the pre-fix state.
19. **Add a lineup-config parity test** asserting that the registry, the ROS slot flattener, and `DEFAULT_STARTER_NEEDS` agree. This is the test that would have caught C1 and C3.
20. **Add a registry-completeness test** for `is_tep_premium` (already scoped in the roadmap, not confirmed done).

### Day 6 — Performance, then UI

21. Verify the delta-payload path end to end under real load (`view=delta` ~1.25 MB → ~100 KB gzipped); confirm the fail-fast path doesn't fire in production logs.
22. **R5 sweep** (WS-D): perf/a11y/mobile + the dead-CSS purge. It has been blocked all week and is the last redesign dependency.
23. Fix H6 (anonymous shell served to signed-in sessions) and H7 (`/waivers`, `/news` missing from IA) — both are user-visible and currently owned by nobody.

### Day 7 — Deployment stability

24. **Apply the #537 hardening** that has been sitting prepared.
25. Verify `deploy/backup_user_kv.sh` actually runs and produces a restorable artifact — it protects the only irreplaceable state in the system.
26. Consolidate the four overlapping health/smoke workflows into one with clear ownership.
27. **Answer the SSH-workflow question** and, if it ever executed, rotate anything it could have exposed.

**Explicitly deferred beyond this week:** LI-6 projection re-scoring, LI-8 simulation extension, LI-9 archetypes/rookie priors, Underdog ADP, the competitor gap-matrix report, and any publication of `leagueAdjustedDynastyValue`.

---

## 14. Questions for the Independent Reviewer

### Mathematics

1. Is α = 0.10 defensible when the joint backtest's optimum was α = 0, given the ~2× stability cost? Is there a formulation (e.g. per-position α, or shrinking toward the subgroup rather than the anchor) that preserves multi-source voice without the variance?
2. Does the ±15% IDP corridor clamp make IDP arbitrage findings structurally impossible? Compute the maximum achievable `board_delta` on an IDP-only trade under the clamp.
3. Is a fixed `_PERCENTILE_REFERENCE_N = 500` correct for a league whose rostered universe is 696 players? Quantify the value compression between rank 500 and rank 696.
4. Is the Hill curve's lack of any positional term defensible in superflex, given LI-5's measured QB waiver scarcity of 0.75 vs RB 0.21?
5. Reproduce the TEP premium derivation independently. The repo's own number moved from ~1.32 to ≈1.12 once both endpoints were measured. Is ≈1.12 right, and what is the confidence interval on 158–170 team-weeks?
6. Is `trend_score = 3·net48h + 2·net7d + 1·net30d` over *nested* windows intended? What effective decay does it imply?
7. Is `_HAMPEL_MIN_THRESHOLD = 1000` (10% of the full scale) now too permissive — i.e. does it disable Hampel on most rows?
8. Where should the single-source retention factor sit: 0.30, 0.88, or somewhere else? Design the experiment that answers it.

### Code

9. Is `run_valuation` in `src/canonical/player_valuation.py` reachable from `/api/data`? If not, are `W_MEDIAN`, `CLIFF_*`, `VOL_*` dead?
10. In `power_v2.build_section`, how are weights renormalized when the six results-driven components (0.55 total) route to `missing_inputs`? Is the offseason score depressed or rescaled?
11. Does `classify_team`'s ordering make the 0.20–0.25 playoff band unreachable for "Selective Seller"? Should `team_ros_strength_percentile` influence the label rather than only the summary string?
12. Are `edge` / `opponent_fit` (set via `__dict__` post-construction) at risk under any planned dataclass change?
13. Verify that the `faab_contention` ↔ `intel.store` path convention cannot drift, or replace the convention with a shared constant.
14. Audit `_hydrate_overlay_players` after #550: is `fantasy_positions` threaded to *every* eligibility consumer, or only the optimizer?

### Design and product

15. Should the product disclose, in the UI, that IDP values are corridor-clamped to one source? Users are being shown "consensus" that is partly a constrained restatement of IDPTC.
16. Is a KTC-anchored blend that also uses KTC as the counterparty's view a coherent arbitrage premise, or is the measurable edge mostly noise? Note that `fantasyNavigatorSf` is additionally KTC-derived.
17. Should trade suggestions model acceptance probability at all, or is `opp_appeal > 0` an adequate proxy for a single-league private tool?
18. Is the two-way-player max() the right operator, or should it be a coverage-weighted blend?

### Process

19. Six evidentiary failures in three workstreams in one week. Is §2b sufficient, or does the review process need a structural change (e.g. mandatory pre-fix failing-test evidence in every PR template)?
20. Is one-branch-per-workstream with two integration windows the right model at this agent count, or does it just relocate merge pain to two large events?
21. Should `server.py` (10,707 lines) be split before the next parallel wave, given "append-only sections" is the only thing preventing conflicts?

### Legal / ethical

22. Assess the ToS and licensing exposure of ingesting DLF, KTC, DynastyDaddy, FantasyNavigator, and PFK data — particularly PFK via their embedded publishable Supabase key.
23. Assess the Sharp Tracker: it aggregates named league-mates' transaction behavior across all their leagues. Public data, but is "keep it inside this private app" an adequate control?

---

## 15. Source Appendix

### 15.1 Primary file paths

**Valuation core**
- `src/api/data_contract.py` (9,009 L) — `_compute_unified_rankings`, `_RANKING_SOURCES` (:1020–1681), `_VALUE_BASED_SOURCES` (:5026), `count_aware_mean_median_blend` (:5855), `_hampel_filter_per_player`, `_apply_market_corridor_clamp` (:4468), `_apply_idp_calibration_post_pass`, `_apply_pick_year_discount_to_blend`, `_build_hill_curves_block` (:4851), `current_rookie_draft_year`, `build_api_data_contract`, `build_rankings_delta_payload`, `_validate_and_quarantine_rows`, `_disagreement_depth_allowance` (:165)
- `src/canonical/player_valuation.py` (887 L) — `percentile_to_value` (:366), `rank_to_value` (:333), `detect_tiers` (:248), `compute_tier_adjustments` (:413), `compute_volatility_adjustments` (:463), `run_valuation` (:541)
- `src/canonical/{calibration,confidence_intervals,idp_backbone,normalization_validator,rank_history_band}.py`

**Trade**
- `src/trade/suggestions.py` (1,625 L) — `analyze_roster` (:540), `rank_score` (:693), `rank_score_breakdown` (:741), `_generate_sell_high` (:849), `_generate_buy_low` (:913), `_generate_consolidation` (:980), `_generate_positional_upgrades` (:1068), `_find_balancers` (:1162), `_apply_quality_filters` (:1257), `generate_suggestions_from_pool` (:1412)
- `src/trade/finder.py` (735 L) — `_score_trade` (:323), `_generate_1for1` (:523), `_generate_2for1` (:541), `_generate_1for2` (:561), `_deduplicate` (:580), `find_trades` (:596)
- `src/trade/{angle,faab_contention,faab_recommender,monte_carlo,team_impact,symmetrize,correlation_matrix,ktc_import,ktc_va,waiver}.py`

**Roster / ROS**
- `src/ros/{lineup,power_v2,championship,direction,playoff_sim,pick_projection,team_strength,aggregate,api,scrape,tags,trade_deadline,mapping,parse}.py`
- `src/ros/sources/{draftsharks_ros,fantasy_football_calculator,fantasypros_ros_idp,fantasypros_ros_overall,fantasypros_ros_sf}.py`

**League intelligence (branch #550)**
- `src/league_intel/{config,scorer,values,adjustment}.py`, `tests/league_intel/`, `config/league_intel/`

**Other backend**
- `src/api/` — `league_registry.py`, `sleeper_overlay.py`, `injury_impact.py`, `terminal.py`, `trade_simulator.py`, `session_store.py`, `user_kv.py`, `guest_passes.py`, `rate_limit.py`, `feature_flags.py`, `startup_validation.py`, `ops_alerts.py`, `source_health_alerts.py`, `espn_schema_drift.py`, `rank_history.py`, `source_history.py`, `auction_power.py`, `faab_analytics.py`, `draft_capital_fallback.py`, `compact_view.py`, `chat.py`, `push_delivery.py`, `signal_alerts.py`, `signal_state_migration.py`, `team_assignment.py`, `public_activity_valuation.py`, `error_responses.py`
- `src/intel/{crawler,aggregate,store,service}.py`
- `src/news/` (service, digest, base, custom_alerts, unified_signal_engine, usage_signals, providers/×9)
- `src/public_league/` (27 modules)
- `src/nfl_data/`, `src/playerctx/`, `src/scoring/`, `src/identity/`, `src/adapters/`, `src/league_comparison/`, `src/backtesting/`, `src/pool/`, `src/utils/`, `src/maintenance/`

**Frontend**
- `frontend/lib/dynasty-data.js` (`RANKING_SOURCES` mirror, `buildRows`, `fetchDynastyData`, `mergeRankingsDelta`), `nav-model.js`, `trade-logic.js`, `waiver-logic.js`, `league-analysis.js`, `signal-engine.js`, `edge-helpers.js`, `player-filters.js`, `portfolio-insights.js`, `trade-retro-value.js`, `value-history.js`, `movers.js`, `market-movers.js`
- `frontend/app/` — 20+ authed routes + `league/` public hub
- `frontend/components/waivers/FaabRecommendation.jsx` (branch #552)
- `frontend/app/tokens.css`, `ds.css`, `globals.css`, `shell.css`

**Config**
- `config/leagues/registry.json`, `owner_names.json`, `default_superflex_idp.template.json`
- `config/weights/{pick_year_discount,default_weights,source_row_floors,top50_coverage_floors}.json`
- `config/tiers/thresholds.json`, `config/trade/team_impact.json`, `config/source_staleness.json`, `config/espn_schema_baseline.json`, `config/league_comparison.json`, `config/team_assignment.json`, `config/identity/id_overrides.json`, `config/league_intel/sleeper_league_snapshot_2026-07-26.json`, `config/idp_calibration.json`

### 15.2 Persistence

| Store | Path |
|---|---|
| `user_kv` (SQLite) | `data/user_kv.sqlite` — one row/user, `state_json` + `updated_at` |
| sessions (SQLite) | via `src/api/session_store.py` — `allowlist_version` per row |
| guest passes (SQLite) | via `src/api/guest_passes.py` |
| intel snapshot | `data/intel/snapshot_<leagueKey>.json` |
| ROS aggregate | `data/ros/aggregate/latest.json` |
| public league | `data/public_league/` |
| source CSVs | `CSVs/`, `data/` |
| exports | `exports/latest/`, `exports/archive/` |

**There are no SQL tables beyond the three SQLite stores above.**

### 15.3 API endpoints

See §3.3 for the full enumeration (100 route decorators in `server.py`).

### 15.4 Environment variables

Declared: `FRONTEND_URL`, `SLEEPER_LEAGUE_ID`, `BASELINE_LEAGUE_ID`, `SLEEPER_TRADE_HISTORY_DAYS`, `JASON_LOGIN_USERNAME`, `JASON_LOGIN_PASSWORD`, `JASON_AUTH_COOKIE_SECURE`, `DISK_SPACE_MIN_MB`, `LOG_FORMAT`.
Used but undeclared: `PRIVATE_APP_ALLOWED_USERNAMES`, `SESSION_TTL_DAYS`, `FRONTEND_RUNTIME`, `ALLOW_DEFAULT_LOGIN_DEV`, `E2E_TEST_MODE`, `UPTIME_CHECK_ENABLED`.

### 15.5 External services and URLs discussed

| Service | Endpoint / note |
|---|---|
| Fantasy Navigator | `https://fantasy-navigator-latest.onrender.com/ranks?platform=sf` — JSON; use `roster_type=sf_value` + `rank_type=dynasty`; `_SOURCE_MAX_AGE_HOURS: 720` (dynasty rows update ~monthly) |
| PlayForKeeps | Supabase PostgREST table `pfk_dynasty_rankings` (anonymous, site's own publishable key); `pfk_ktc_values` rejected as a KTC mirror; `https://playforkeepsdynasty.com/articles` for the news provider |
| Sleeper | Public API — leagues, rosters, users, matchups, transactions, traded picks, drafts, `/v1/players/nfl/trending/add`, weekly stats |
| KeepTradeCut | SF-TEP board; crowd FAAB |
| IDP Trade Calculator | Combined offense+IDP scale |
| nflverse | Contracts, snap share, depth charts, opportunity stats |
| ESPN / CBS / FantasyPros / RotoWire | News RSS/APIs |
| Hetzner VPS | Production host; nginx + systemd + Let's Encrypt |

### 15.6 Reports and analyses referenced by the code

- `reports/alpha_lambda_joint_backtest_full.md` — the α × λ 2D sweep
- `reports/mad_lambda_backtest_full.md` — the λ sweep
- `docs/architecture/optimization-target.md` — the declared "market consensus fit" objective that vetoed α = 0
- `docs/architecture/final-framework-transition.md`, `live-value-pipeline-trace.md`
- `docs/league-intelligence/{MASTER_PLAN,DECISIONS,STATUS,SETTINGS_AUDIT,TASK_REGISTRY}.md`
- `docs/ROADMAP-competitor-parity.md`, `docs/ORCHESTRATION.md`, `docs/DESIGN-SYSTEM.md`, `docs/PROD-HARDENING.md`, `docs/idp-ranking-model.md`, `docs/ros-engine.md`, `docs/playerctx.md`, `docs/performance-optimization.md`, `docs/identity-audit-2026-07.md`, `docs/automation-audit.md`, `docs/backtest_methodology.md`, `docs/ux-audit.md`, `docs/trust-edge-handoff.md`
- `docs/ops/{automation-runbook,current-automation-state,failure-handling-and-fallbacks,recommended-automation-model,schedules-and-cadence}.md`
- `docs/runbooks/{production-activation-runbook,ktc-production-validation,public-primary-activation,git-history-shrink}.md`
- `docs/status/` — 22 dated reports

### 15.7 Exact user requirements that materially shaped the design

Quoted verbatim from repository documents that record them:

1. > "The user wants the site to give them every possible edge in their league (trades, waivers/FAAB, player evaluation, league-mate tendencies)." — `ROADMAP-competitor-parity.md`
2. > "**Phase order**: sources-first — Phase 0 → 2+2b (FN/PFK sources) → 3 (search/filters) → 4 (FAAB) → 5 (intel/sharp) → 6 (news) → 1-reports alongside → 7 (ranked wave). Audit reports (Phase 1) are produced incrementally alongside, not as a blocking gate."
3. > "**Sharp Tracker v1 pool**: my league's members + all their other Sleeper leagues (schema kept extensible for a wider pool later)."
4. > "**FAAB anchor**: derived market anchor (league bid history + trending velocity + rival budget/aggression) replaces the nonexistent Sleeper suggestion — no fragile app-scraping."
5. > "**Fetch cadence for FN + PFK**: every 2h with the other fetchers."
6. > "**Execution mode (2026-07-25)**: HYBRID PARALLEL … Phases 2/3 must NOT be parallelized (hot-file conflicts)."
7. > "Target: **comprehensively functional, integrated, polished product in ~1 week** (by ~2026-08-02). Optimize for the final integrated system, not constant main-branch stability." — `ORCHESTRATION.md`
8. > "The user's Final Framework override (2026-04-20) is: value-based sites feed their real dollar-equivalent values straight into the aggregation; rank-only sites continue through rank → percentile → Hill." — `data_contract.py:5026` comment
9. > "user-confirmed neither is TEP-aware" (FN and PFK) — registry comments at `:1353`, `:1384`
10. > "League value starts as consensus no-op; never fabricate adjustments." — `MASTER_PLAN.md` non-negotiables
11. `CLAUDE.md` Non-Negotiable Rules 1–7, particularly rule 1 ("Do not assume features work — trace the live execution path end-to-end") and rule 2 ("Prefer modifying existing architecture over introducing parallel systems"), which directly produced ADRs 001, 002, and 004.
12. The instruction that produced this document, including: *"Do not claim something is completed unless it actually exists in the repository"* and *"Do not prioritize keeping the production site continuously functional unless it is necessary to avoid data loss or blocked development."*

---

## Completion statement

All 15 requested sections are present. Two carry material limitations that are stated in-line and repeated here:

- **§2 (Chronological Session History)** is reconstructed from repository artifacts, not from a conversation transcript, because this session contains no prior conversation. Sequence and content are evidence-based; conversational framing is inferred and labelled.
- **§9 (Work Actually Completed)** reports that this session produced **no code changes** — only this document. All test/build/deploy figures quoted anywhere in this document come from PR bodies authored by other agents and were **not** independently verified, because pytest is not installed in this container.

Everything in §3–§6 was read from source at `c534280d` and is verifiable by inspection at the file:line references given.
