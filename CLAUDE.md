# CLAUDE.md — Risk It To Get The Brisket

## What this document is — and is not

**CLAUDE.md is the technical operating / runbook document.** It describes how
the system is built, where the canonical owners live, which invariants the code
must hold, and how to run and validate it.

**It is NOT the authoritative product roadmap, and NOT the product-methodology
source of truth.** Nothing here authorizes a feature.

> **Mandatory startup rule for any material product, architecture, model, or
> feature-planning work: start at [`PRODUCT_PLAN.md`](PRODUCT_PLAN.md) and
> follow the canonical hierarchy defined in
> [`docs/MASTER_PRODUCT_PLAN.md`](docs/MASTER_PRODUCT_PLAN.md).**

| Question | Canonical record |
|---|---|
| Where do I start? | `PRODUCT_PLAN.md` |
| What are we building, and which record wins? | `docs/MASTER_PRODUCT_PLAN.md` |
| What does an approved feature actually mean? | `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` |
| Does a feature exist / is it defective / evidence-gated? | `docs/OWNER_FEATURE_INVENTORY.md` |
| **What am I authorized to implement right now?** | `docs/EXECUTION_PLAN.md` |
| What is the complete scope, who owns it, and what proves it done? | `docs/C_SERIES_SCOPE_MANIFEST.md` |
| Where did a given requirement go? | `docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md` |
| What does a CE identifier mean? | `docs/CE_REGISTRY.md` |
| What is the C-Series completion standard? | `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` |
| Canonical owners, boundaries, technical invariants | `docs/ARCHITECTURE_HANDOFF.md`, current ADRs, live code |
| What defect was measured, with what evidence? | `docs/master-site-audit/` |
| Which records are legacy vs canonical? | `docs/PLANNING_DOCUMENT_STATUS.md` |
| Who is editing what right now? | `docs/WORK_CLAIMS.md` |

**If this file conflicts with that hierarchy, the hierarchy wins**, per the
precedence rules in `MASTER_PRODUCT_PLAN.md` §2. One nuance from those rules is
worth repeating here because this document is the one most likely to describe
implementation: *existing implementation behavior does not override a newer
owner product decision merely because that is how the site currently behaves* —
and equally, live code or executable evidence can prove a status claim in any
document, including this one, stale.

This file deliberately **points to** the canonical records rather than
reproducing them. A second copy of the roadmap is a second roadmap, and it will
drift.

## Governance invariants every implementation session must hold

Stated here because they bind code, not just product decisions. The full
methodology lives in `MASTER_PRODUCT_PLAN.md` §3 — read it before designing
anything that touches these.

- **ONE CONCEPT, ONE CANONICAL OWNER.** Pages and features consume canonical
  systems; they never reimplement them. If the canonical owner is defective,
  repair it — a page-local workaround becomes a second owner. (§3.1 lists the
  ~25 concepts that require one.)
- **MISSING IS NEVER ZERO.** No projection ≠ 0 points. No FAAB history ≠ $0. No
  trade comps ≠ no market value. Missing historical value ≠ today's value.
  Unresolved identity ≠ best fuzzy guess. Unverified game type ≠ dynasty. Every
  decision surface preserves explicit missing / insufficient / stale /
  unavailable states. (§3.2)
- **Signal independence — no double counting.** A body of evidence affects a
  conclusion once. KTC, a consensus containing KTC, and a Monte Carlo centered
  on that consensus are correlated descendants, not independent votes. Declare
  population, overlap, correlation group, sample size, freshness, coverage,
  missing behavior and provenance before adding a signal. (§3.3)
- **Champion ≠ challenger.** Evaluation is not activation. Nothing self-promotes.
  (§3.4)
- **Model evaluation does not authorize production promotion.** The sequence is
  fit → backtest → validate → compare → human approval → promote → monitor →
  rollback. See also the Hill-curve registry rules below, which are this
  invariant made executable.
- **Pinned inputs and provenance for every model experiment.** Code SHA, source
  hashes, board/snapshot hash, model version, scoring config, timestamp. Never
  compare across refreshed inputs and attribute the difference to code. (§3.5)
- **Public `/league` vs private decision intelligence is a semantic boundary**,
  not a field-name denylist. Factual and retrospective content is public;
  proprietary values, edges, targets, weaknesses, forecasts and manager
  tendencies are private. (§5)
- **Recommendations and execution are separate.** A model recommendation never
  silently mutates a league. Mutations need auth, explicit league/team, preview
  or confirmation, idempotency, and an audit trail. (§3.6)

## Source-domain boundaries — which evidence may touch which answer

Two evidence domains, deliberately separated. Full methodology in
`docs/MULTI_FORMAT_SOURCE_NORMALIZATION_SPEC.md` and
`docs/REDRAFT_ROS_INTELLIGENCE_SPEC.md` (both on `main`; read them
before ingesting anything new).

**Dynasty valuation lane.** Every external ranking/value observation that
reaches canonical dynasty player/pick value must be **explicitly verified as
DYNASTY**. Redraft, rest-of-season, weekly, DFS and best-ball-only boards must
never enter the dynasty pool, consensus counts, source weights, format curves,
calibration or Consensus Edge — including when they come from a provider we
otherwise trust, and including when the same provider publishes both. Game type
is proven per endpoint/feed, never inferred from player ages, a URL fragment, or
a familiar provider name. **Unverified game type fails closed:** `UNKNOWN` is
not `DYNASTY`.

**Seasonal intelligence lane.** Verified redraft / ROS / current-season
rankings and projections are *allowed and encouraged* for current-season
questions — ROS strength, playoff and championship probability, Pick Forecast
inputs, contender/rebuilder classification, Game Day, lineup intelligence. That
evidence stays separate from canonical dynasty valuation. A feature combining
long-horizon value with current-season outlook keeps the components separately
named and separately sourced before synthesis.

**Multi-format dynasty archive.** Future ingestion preserves source-native
dynasty 1QB / Superflex / TEP / IDP variants rather than flattening them.
KTC's Off / TE+ / TE++ / TE+++ are **same-source calibration states of one
provider, not four independent votes** — KTC applies them algorithmically from
one base crowd value, so counting them four times in consensus would
manufacture agreement out of one opinion. Collecting or archiving alternate
boards does **not** authorize using them to alter production values; that is
separately evidence-gated and owner-approved.

## Trade History — three distinct questions

Full methodology in `docs/TRADE_HISTORY_AGING_SPEC.md`.
Not currently authorized for implementation. The guardrails that must survive
any future work:

- **Current Grade** — this trade evaluated with today's canonical values and
  today's canonical trade methodology.
- **At-the-Time Grade** — the closest valid snapshot **at or before** the trade
  timestamp. Never a future snapshot presented as contemporaneous truth.
- **How It Aged** — the difference between the two, measured with the **same
  trade methodology on both timestamps**. Comparing one quantity then against a
  different quantity now measures the methodology, not the aging.
- A missing historical value is **not** the player's current value, and picks
  need first-class historical values rather than a current-value substitute.
- Provenance and coverage are explicit; the current fixed ±200 aging threshold
  is evidence-gated, not finished methodology.

## Project Overview

Dynasty fantasy football valuation and trade calculator platform. Ingests external rankings sources (DLF, KTC, FantasyCalc, DynastyDaddy, etc.), normalizes them to a canonical scale, and serves a web UI for trade analysis and rankings.

## Working Copy Coordination

- Active working copy: `C:\Users\jason\code\riskittogetthebrisket`.
- GitHub `main` is the shared source of truth for Claude, ChatGPT/Codex, and local work.
- Before starting work, run `git pull --ff-only origin main` from the active working copy.
- Use a task branch for meaningful changes (`claude/...` for Claude, `codex/...` for Codex).
- Do not edit OneDrive repo copies unless the user explicitly asks; treat them as backups/archive only.
- Do not let multiple assistants edit the same branch at the same time.
- See `ASSISTANT_COORDINATION.md` for the shared start-of-session checklist and handoff rules.

## Tech Stack

- **Backend**: Python 3, FastAPI, Uvicorn (port 8000)
- **Frontend**: Next.js 15 + React 19 (port 3000)
- **Scraping**: Playwright (browser automation), legacy Selenium/requests (`Dynasty Scraper.py`)
- **CI/CD**: GitHub Actions (`.github/workflows/`)
- **Testing**: pytest (unit/integration), Playwright E2E regression
- **Platform**: Windows (primary dev via `.bat` files), Linux/Unix (production + CI)

## Directory Structure

```
├── server.py                  # FastAPI backend entry point (~100 routes)
├── Dynasty Scraper.py         # THE PRODUCTION SCRAPER (Selenium/requests).
│                              #   Not legacy despite its age: server.py
│                              #   imports it via importlib for /api/scrape,
│                              #   the scheduled loop and startup, and
│                              #   scheduled-refresh.yml runs it every 2h.
├── .github/workflows/         # GitHub Actions CI/CD pipelines
│
├── frontend/                  # Next.js app (App Router) — 38 pages
│   ├── app/                   # rankings/, trade/, draft/, bdvm/, waivers/,
│   │   │                      #   terminal/, news/, settings/, login/, …
│   │   └── api/               # 28 backend bridge routes
│   ├── components/            # React components + hooks
│   └── lib/                   # Data utilities (pure materializers)
│
├── src/                       # Modular canonical engine (~250 modules)
│   ├── adapters/              # base.py (frozen contract), scraper bridge,
│   │                          #   sleeper_trending, ktc_crowd_faab
│   ├── api/                   # API data contract (versioned) + endpoints
│   ├── bdvm/                  # Brisket Dynasty Valuation Model (fundamentals)
│   ├── canonical/             # Hill curves + tiering (player_valuation.py)
│   ├── identity/              # Player/pick master identity mapping
│   ├── league_intel/          # League-adjusted overlay, TE premium, scarcity
│   ├── model_registry/        # Hill-curve challenger/promotion (script-only)
│   ├── scoring/               # Scoring adjustments, archetypes, backtesting
│   ├── league/                # EMPTY placeholder — see src/league/README.md
│   ├── trade/                 # Trade engines: suggestions + arbitrage finder
│   ├── data_models/           # Dataclass contracts
│   └── utils/                 # Config loading, name/position normalization
│
├── config/
│   ├── bdvm/                  # BDVM params, event ontology, pick outcomes
│   ├── leagues/               # League registry + profile templates
│   ├── model_registry/        # Hill scope-master versions
│   ├── sources/               # Source ingestion templates
│   ├── tiers/, trade/, identity/, league_intel/
│   └── weights/               # Pick-year discount, TE curve, coverage floors
│
├── scripts/                   # Pipeline helper scripts (source fetches, fit, etc.)
├── deploy/                    # Deployment configs (nginx, systemd, deploy scripts)
├── tests/                     # pytest unit/integration + Playwright E2E
├── data/                      # Pipeline outputs. MOSTLY gitignored, but 8,825
│                              #   files ARE tracked (data/ros/ is re-included by
│                              #   .gitignore, and refresh workflows `git add -f`).
│                              #   The tracking is DELIBERATE, not an accident:
│                              #   scheduled-refresh.yml force-adds
│                              #   data/scrape_state/ every 2h even when the
│                              #   scrape fails, and deploy dispatch keys on
│                              #   those commit subjects — so `git rm --cached`
│                              #   freezes prod's source_health. See W31-F001 in
│                              #   docs/master-site-audit/REBASELINE_2026-08-11.md
├── exports/                   # Release artifacts (latest/ + archive/) — 168 tracked
└── docs/                      # Architecture blueprints, status docs, ADRs, audits
```

## Key Commands

### Starting the Stack

```powershell
.\start_dynasty.bat          # Start Python backend (port 8000)
.\start_frontend.bat         # Start Next.js dev server (port 3000)
.\start_stack.bat            # Start both in separate windows
```

### Testing & Validation

```bash
# Python tests (primary test suite)
python -m pytest tests/ -q

# E2E regression
npm install                          # Install root + frontend deps
npm run regression:install           # Install Playwright browsers (one-time)
npm run regression                   # Full pipeline: preflight + tests
```

### Git Workflow

```powershell
.\sync.bat "commit message"          # Git add, commit, push
```

## API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/data` | GET | Main player data (versioned contract `2026-03-10.v2`) |
| `/api/status` | GET | Server status + runtime info |
| `/api/health` | GET | Uptime health check |
| `/api/scrape` | POST | Trigger manual scrape |
| `/api/scaffold/status` | GET | Pipeline status |
| `/api/scaffold/raw` | GET | Raw source snapshots |
| `/api/scaffold/identity` | GET | Identity mappings |
| `/api/trade/suggestions` | POST | Roster-aware trade suggestions (reads live contract) |
| `/api/trade/finder` | POST | KTC arbitrage finder |
| `/api/leagues` | GET | Active league registry (stable `key` → `displayName` + roster settings; **no Sleeper IDs leaked**) |
| `/api/sharp/roster-percentage` | GET | Sharp Roster Percentage board (global cohort — takes no `leagueKey`) |
| `/api/sharp/roster-percentage/audit` | GET | Every roster behind one player's count, for manual verification |
| `/api/draft/roster-context` | GET | Perfect Draft roster context — rosters at board value, waiver levels, cut ladder (flag `perfect_draft`) |

### Rankings vs. league context — the core split

The single most important architectural rule for multi-league:

> **Scoring controls rankings.  League key controls context.**

* **Scoring** decides "which set of rules produces a player's value".
  Two leagues that use identical scoring share ONE ranking pipeline and
  ONE output; a single scrape's blended rankings can be served to every
  such league with no per-league recompute.

  **Which leagues those are is a FACT, not a label.** Three distinct
  identities, and conflating the first two is W18-F001:

  | concept | what it is | what it may decide |
  |---|---|---|
  | `scoringProfile` | a hand-authored config/model **label** in `config/leagues/registry.json` | model/config identity for its existing consumers (BDVM, the gameplan bundle, draft scarcity). **Never** cross-league ranking compatibility |
  | factual scoring identity | derived/validated from the league's **actual valuation-affecting scoring configuration** | whether two leagues may share scoring-dependent rankings |
  | `leagueKey` | ownership identity — rosters, teams, managers, draft, signals | everything that depends on who-owns-what |

  Matching profile labels alone are **insufficient**, and unverifiable
  compatibility **fails closed**. The canonical requirement is
  `docs/MASTER_PRODUCT_PLAN.md` §4.10 ("League scoring-profile
  identity"); this file does not restate it.

  Why it is not academic: both live leagues carry
  `superflex_tep15_ppr1` while their hosts differ on 35 of 48 shared
  scoring keys (`rec` 1.0 vs 0.08, `pass_td` 4 vs 6, `pass_yd` 0.04 vs
  1/30, `pass_int` -1 vs -4, `bonus_rec_te` 0.0 vs 0.5), so
  `/api/data?leagueKey=dynasty_new` served dynasty_main's board.

  **Status — B6/W18-F001 is MERGED AND LIVE on `main`** (PR #810, merge
  `5c699af`, 2026-08-13). `scoring_fingerprint`, `leagues_share_scoring`
  and `_scoring_identity_error` all resolve in `src/` and `server.py`.
  The invariant above and the field/API shape below are both canonical.
  `docs/EXECUTION_PLAN.md` remains authoritative for phase status.

  The identity is `scoring_fingerprint()`
  (`src/league_comparison/sleeper_scoring.py`), computed over the
  league's ACTUAL scoring card with key order, numeric form (`1` vs
  `1.0`) and absent-vs-explicit-zero normalized away and non-numeric
  metadata excluded.  It returns `None` — never a hash of `{}` — when
  there is no card, so unproven is distinguishable from proven and
  **fails closed**.  Deliberately not the pre-existing `_scoring_hash`,
  which gets all three normalizations wrong and would manufacture false
  *in*compatibility; that one keeps its league-comparison display
  consumers.

  Where it lives:
  - per league — a snapshot at `data/leagues/scoring_<sleeperLeagueId>.json`,
    refreshed by the post-scrape warm pass and by
    `scripts/fetch_league_scoring.py` (needed once on a cold deploy).
    **Never fetched inside a request** — an 8 s Sleeper round-trip in the
    `/api/data` gate would trade a correctness bug for a latency one.
  - per contract — `meta.scoringFingerprint`, derived from the
    contract's OWN `sleeper.scoringSettings` so it can be recomputed
    from the artifact it describes instead of copied from config.

  **A snapshot proves when it was taken, not that it is still true.**
  Evidence is `fresh` / `stale` / `missing` (`scoring_evidence_state`) and
  only `fresh` authorizes reuse.  The budget is
  `SCORING_SNAPSHOT_MAX_AGE_HOURS = 6`, which is the repo's existing
  scrape-cadence staleness rule (`SCRAPE_INTERVAL_HOURS * 3`, and the
  default in `data_contract._SOURCE_MAX_AGE_HOURS`) rather than a new
  number.  Season must be **verified**, not merely un-contradicted: a card
  from a different NFL season is stale however recently it was fetched
  (Sleeper leagues chain year to year under new ids), and so is one whose
  season is unrecorded or whose current-season resolver cannot answer —
  an unknown may not pass as a match.  Stale evidence is retained and
  readable; only its authority expires.

  **The stamp is a cache of the card, and must agree with it.**  Card +
  agreeing stamp → that fingerprint; card, no stamp → recompute; card and
  stamp *disagree*, or the stamp carries a different `sf*` version → fail
  closed; **stamp with no card → fail closed**, decided explicitly rather
  than emerging from lookup order.

  `league_registry.leagues_share_scoring()` is the single owner of the
  question and every gate routes through
  `server.py::_scoring_identity_error`.  Rule for new code: a cache may
  be keyed by `leagueKey` or by the fingerprint — **never** by
  `scoringProfile`.

* **`leagueKey`** is the identifier for "which league's rosters,
  teams, managers, draft, and signals".  Anything that depends on
  who-owns-what in Sleeper is league-scoped.

Fields that follow **scoring** — global across leagues *proven* to score
identically, never across leagues that merely share a profile label:
- `players`, `playersArray`, `sources`, `rankings`, `poolAudit`
- Rank history, source-value history, edge signals
- Player metadata (position, Sleeper ID, news)
- Tier boundaries, confidence buckets, value bands
- Injury-impact calculations (position-based, not league-based)

Fields that follow **leagueKey** (must be per-league):
- `sleeper.teams`, `sleeper.leagueId`, `sleeper.rosterPositions`,
  `sleeper.scoringSettings`, `sleeper.leagueSettings` — the exact tuple
  `sleeper_overlay.LEAGUE_SPECIFIC_SLEEPER_FIELDS` enforces (W18-F002).
  NOT `sleeper.positions`, which this list named until 2026-08-13: that
  field is the playerId → NFL-position map `buildRows` reads, and a
  player's position does not depend on which league is asking. It is
  NFL-wide, alongside `sleeper.playerIds` / `sleeper.idToPlayer`
- Draft capital (per-team auction budgets, pick ownership)
- Public-league snapshots / standings / matchups
- Terminal aggregates (team portfolio, roster movers)
- Trade-finder, trade-suggestions, trade-simulate outputs
- Angle-finder / Angle-packages opponent filters
- Signal visibility (filtered by roster ownership)
- IDP display toggle (per-league `idpEnabled`)
- Roster-constraint derived UI (starter counts, flex rules)
- Per-user `selectedTeam`, `activeLeagueKey`, watchlist relevance

Contract annotations:
- `meta.leagueKey` — which specific league's `sleeper` block is
  stamped here
- `meta.scoringProfile` — the config/model LABEL the build ran under.
  Descriptive; decides nothing about compatibility.
- `meta.scoringFingerprint` — the FACTUAL identity of the scoring that
  produced these rankings.  This is what compatibility is decided on.
- `meta.sleeperDataReady` — true iff EVERY league-specific field in the
  `sleeper` block is COMPLETE and belongs to the *requested* league.
  False when the server served shared rankings without that league's
  rosters, and false on a cross-league overlay whose own config could not
  be fetched *or came back partial* (W18-F002) — in that case the
  league-specific fields are ABSENT rather than inherited.  Complete is
  defined by what the consumers need, in
  `sleeper_overlay.league_config_is_complete`: non-empty scoring, a
  **non-empty** `rosterPositions` (an empty list makes
  `bdvm/league_config.py` fall through to the registry, and
  `starter-slots.js` ranks the live list above it, so `[]` means missing),
  and `leagueSettings` carrying `num_teams > 1` (below that the same
  builder raises).  No empty-but-present value counts as complete.  The
  one merge that can produce this state is
  `sleeper_overlay.merge_cross_league_sleeper_block`; do not re-inline it.
- `meta.sleeperLoadedLeagueKey` — which league the `sleeper` block
  *would* be for, when `sleeperDataReady: false` (diagnostic only).
  Deleting it would hide a chimera, not prevent one.

Error behavior on endpoints:
- `/api/data`, `/api/rankings/overrides` — 503 when scoring is not
  PROVEN identical (different fingerprints, or either side unverifiable).
  When it is proven and sleeper is for a different league, serve shared
  rankings with `sleeper: null` + `sleeperDataReady: false`.
- `/api/terminal`, `/api/trade/*`, `/api/angle/*` — 503 whenever the
  loaded contract's `leagueKey` doesn't match the request.  These
  endpoints can't meaningfully work without the specific league's
  rosters.
- `/api/draft-capital` — 503 `data_not_ready` only when NO contract is
  loaded, and only on the non-default path.  It deliberately does NOT
  503 on a league *mismatch*.
  - The default league is served from `CSVs/Draft Data.xlsx` and never
    consults the contract, so contract readiness is irrelevant to it.
  - A non-default league takes the Sleeper-derived fallback
    (`src/api/draft_capital_fallback.py`), which fetches **that
    league's own** rosters and traded picks.  It needs the contract
    only for pick VALUES, so a foreign-league contract still produces
    a correct board for the requested league — refusing it would
    remove working multi-league functionality to satisfy a table.
  - Its ROOKIE block is the one part that is scoring-dependent, and it
    is gated by the same `_scoring_identity_error` as everything else
    (W18-F001).  Measured on the live board: dynasty_new used to be
    served 40 rookies priced under dynasty_main's 0.08-PPR / 6-point-TD
    rules on a full-PPR / 4-point-TD board; it now gets
    `rookieSource: "none"` with all 80 of its real picks intact.
    Withholding a value we cannot justify, not refusing the board.
  - This resolves Defect D-2 (`docs/python-coverage-audit.md`), which
    was open between "503 per this table" and "keep the fallback and
    fix the doc".  Fixing the doc is the answer, and this is it.
  - The 503 covers the no-contract case only.  This section used to
    claim that was also the only way to reach the hardcoded
    7000/4000/2000/1200-by-round table in `_pick_value_from_contract`
    — i.e. that the invented values sat behind the guard.  **That was
    false**, and it hid a live defect (audit finding C1): the fallback
    generates picks for `current_season` AND `current_season + 1`,
    while the live contract carries current-year slot picks only (72
    rows: 12 slots × 6 rounds).  Every next-year pick therefore missed
    the lookup and took a constant **with a fully valid contract
    loaded** — half the emitted board — and those constants were
    normalized into the same $1200 pool as the real values, diluting
    every genuine pick's dollars and shifting every team's
    `auctionDollars`.  A 503 gated none of it.
  - Fixed by removing the table outright.  `_pick_value_from_contract`
    returns `None` on a miss; `build_sleeper_derived` excludes unpriced
    picks from the dollar normalization (so they cannot dilute) and
    emits them with `dollarValue: null` +
    `isUnpriced: true` — ownership from Sleeper is still real, only the
    value is unknown.  `coveredPickYears` is now derived from what was
    actually priced instead of the loop bounds, and
    `pricedPickCount` / `unpricedPickCount` / `unpricedPickYears` make
    the omission visible (same posture as
    `metadata.assetsUnpricedByBoard` in `src/trade/finder.py`).
    Consequence worth knowing: the $1200 pool now lands entirely on the
    current class, so a real pick's dollar value is roughly double what
    this path used to report.
  - Pinned by `tests/api/test_draft_capital_data_not_ready.py` (which
    fails if a future change re-resolves D-2 by accident in either
    direction) and `tests/api/test_draft_capital_fallback.py` (which
    pins the unpriced-exclusion arithmetic).

Rule for new code:
- Need rankings / values / player data?  →  resolve the scoring
  profile via `league_registry.get_scoring_profile(key)`.  Share
  across leagues.  Never index per-league.
- Need rosters / teams / matchups?  →  resolve via `leagueKey`.  One
  pipeline per league.  Never collapse.

### League-aware routing

League-scoped endpoints accept an optional `leagueKey` parameter
(query string for GET, body field for POST).  The resolver lives in
`server.py::_resolve_league_for_request` and picks the target
league in this order:

1. explicit `leagueKey` in the request
2. the authenticated user's `activeLeagueKey` from `user_kv`
3. the registry's default league

**Validation rules** (returned as clean JSON errors):

| Condition | HTTP | Error code |
|---|---|---|
| unknown `leagueKey` | 400 | `unknown_league` |
| `leagueKey` is inactive | 400 | `inactive_league` |
| valid key but contract for it not loaded | 503 | `data_not_ready` |
| no leagues configured at all | 404 | `no_leagues_configured` |

Aliases (`"main"` → `"dynasty_main"`) are accepted and canonicalised
server-side.  Frontend callers should use the stable `key` from
`/api/leagues`, not raw Sleeper league IDs — no endpoint exposes
raw Sleeper IDs to the UI.

League-aware endpoints (all stamp `leagueKey` on their response):

- `GET /api/data` — full canonical contract
- `POST /api/rankings/overrides` — override-sensitive delta
- `GET /api/terminal` — team aggregates, movers, signals
- `POST /api/trade/simulate`
- `POST /api/trade/suggestions`
- `POST /api/trade/finder`
- `POST /api/angle/find`, `POST /api/angle/packages`
- `GET /api/draft-capital`
- `POST /api/scrape` (non-default leagueKey returns 501 today; multi-league scrape is future work)
- `GET /api/public/league/*` (routes through `_public_league_id()` which reads the registry)

Backend map the frontend relies on: `leagueKey` → `sleeperLeagueId`
+ `rosterSettings` + `idpEnabled`.  Lookups go through
`src/api/league_registry.py`; never read `os.getenv("SLEEPER_LEAGUE_ID")`
in new code.

## Architecture Concepts

### Frontend Runtime
Next.js is the sole production frontend, and since 2026-07-31 (#555) it is
the **only** thing that serves a page. `server.py` registers no page routes
at all: `/`, `/rankings`, `/league`, `/_next/*`, `/favicon.ico` and the
catch-all `@app.get("/{full_path:path}")` are gone, along with `_proxy_next`,
`_serve_app_shell`, `_require_auth_or_redirect` and `_auth_redirect_response`.
A page path requested from `:8000` now returns a JSON **404**.

This matches what production already did — `deploy/nginx/chaseupside-proxy.conf`
routes `location /` to the Next upstream and only `location /api/` reaches the
backend, so FastAPI never saw a page request. What the proxy did serve was a
*divergent* copy: it took a path string rather than a `Request`, so it
structurally could not forward cookies or the query string, and after
`frontend/middleware.js` landed it returned **200 carrying the login page body**
for an authenticated session. Two definitions of the page auth gate that had to
be kept in sync is what produced the incident `middleware.js` was written for.
There is now one, in Next.

**`frontend/middleware.js` + `frontend/lib/public-routes.js` are the only page
auth gate.** Adding a private page means adding it there; there is no backend
half to update. Anonymous access to a private page is a Next **307** to
`/login?next=…`, not the old backend 302.

`FRONTEND_RUNTIME` and `FRONTEND_URL` no longer exist in `server.py` — both
described this process's relationship with Next, and it has none.

Production deployment still requires both `dynasty.service` (backend) and
`dynasty-frontend.service` (Next.js) running: nginx needs the Next upstream.

E2E note: page navigations go through `pageUrl()` (`E2E_PAGE_ORIGIN`, :3000)
while `baseURL` stays :8000 for the API. Do **not** move `baseURL` to :3000 —
session minting posts to `${baseURL}/api/test/create-session` and there is no
Next bridge route for `/api/test`.

### Live Value Pipeline
The live ``/api/data`` contract is produced by
``src/api/data_contract.py::_compute_unified_rankings`` — the one and
only code path that determines live player values ("Final Framework").
Steps:

1. Common 0-9999 internal value scale
2. Percentile normalization against a FIXED 500-rank combined-pool
   reference (``_PERCENTILE_REFERENCE_N`` — ranks past 500 clamp to
   the curve tail; this is deliberate top-500-board behavior)
3. Hill-style percentile-to-value conversion via scope-level master
   curves in ``src/canonical/player_valuation.py``
4. Value-direct voting for ``_VALUE_BASED_SOURCES`` (today exactly
   ``ktcSfTep`` + ``idpTradeCalc``): ``raw / site_max × 9999``.
   Every other source — including DynastyDaddy, Yahoo/Boone,
   Fitzmaurice, FantasyCalc, OTCFFB after their rank-signal
   conversions — votes via rank → percentile → Hill.  (The refit
   workflow trains the scope masters on value-based observations.)
5. Scope-appropriate curve routing (cross-market → GLOBAL, overall
   IDP → IDP, everything else → OFFENSE; the ROOKIE master is refit
   tooling only — rookie sources ladder-translate first)
5a. TE basis conversion (2026-07-27, ADR-015 in
   ``docs/league-intelligence/DECISIONS.md``).  TE rows from non-TEP
   sources are lifted onto the basis the board is anchored on via
   ``src/league_intel/te_premium.convert_te_value(from_basis="base",
   to_basis="tepp")`` — KTC's own measured uplift, 1.209 at the top of
   the board rising toward 2.05 down it.  Replaces a flat 1.15 that sat
   below the entire observed range.  ``ktc`` / ``ktcSfTep`` are exempt
   (the anchor IS the TE++ board) and the conversion is a no-op when
   ``from == to``, so the double-count guard is structural.  TEP-native
   sources keep the flat 1.10 — only base ↔ tepp is measured.
   **The target basis is a CONSTANT, not the league's measured TE
   demand**: demand is a leagueKey property and this board is
   scoring-profile scoped, and the two live leagues on
   ``superflex_tep15_ppr1`` want different bases.  That half is overlay
   work.  Rollback: ``RISKIT_FEATURE_TE_BASIS_CONVERSION=0``; an
   explicit operator slider value bypasses the curve regardless.
6. Hierarchical anchor + α-shrinkage (α=0.10) ONLY for IDP and
   picks; offense takes a flat count-aware mean-median across all
   sources.  Pick rows widen the anchor set to include ktcSfTep so
   the two real pick markets (KTC + IDPTC) average as peers.
7. Count-aware aggregation (n=1 passthrough, n=2 mean, n=3-4 untrimmed
   mean-median, n≥5 trimmed mean-median)
8. RETIRED: the λ·MAD volatility penalty is switched off
   (``_MAD_PENALTY_LAMBDA = 0.0`` since 2026-04-20); ``sourceSpread``
   is stamped as a pure diagnostic.  Likewise the soft fallback is
   diagnostics-only (``softFallbackCount`` never touches the math).
9. Single-source haircut: non-pick rows resting on one post-Hampel
   source keep 30% of their blended value
10. Blend-integrity detection (``_detect_blend_integrity_violations``)
    — flags rows whose blended value fell OUTSIDE the range of their own
    source contributions, which is structurally impossible under correct
    operation.  **It changes no value**: the row is stamped
    ``blendIntegrityViolation`` and left alone, because coercing an
    impossible number to a plausible one hides a pipeline fault.  No
    asset-class exemption, no confidence dependency, no tunable band —
    ``_BLEND_HULL_EPSILON`` (1e-9) is float slack, not policy.

    **Not clamping is only half of abstaining.**  The other half is that
    the value stops counting as an ordinary canonical number, and that is
    done with the two fail-closed mechanisms this codebase already has
    rather than a third invented for one detector:

    * **row level** — the detector appends ``blend_integrity_violation``
      to ``anomalyFlags``, and that flag is in ``_QUARANTINE_FLAGS``, so
      ``_validate_and_quarantine_rows`` sets ``quarantined = True`` and
      degrades ``confidenceBucket`` to ``low``.  Consensus Edge then
      returns ``WITHHELD`` (``score.classify`` puts quarantine ahead of
      every other branch), BDVM skips the row, and /edge drops it.  All
      pre-existing behaviour — nothing new consumes the flag.
    * **build level** — ``validate_api_data_contract`` raises a hard
      **error**, so ``scripts/validate_api_contract.py`` (the "API data
      contract check" CI step) exits non-zero and ``contractHealth.ok``
      is stamped ``False``.  An error rather than a warning or the soft
      ``degraded`` status because the gate keys on ``ok`` and ignores
      warnings.  This scan deliberately covers the WHOLE array, not the
      ``[:1000]`` prefix the per-row shape checks use — the board runs
      deeper than that cap and the retired corridor did its work at
      ranks 691-740.

    What it does NOT do: stop a running server publishing the generation.
    That path already publishes ``invalid`` contracts, and changing it
    would be a far larger blast radius than this finding.

    **Placement** is after the blend and count-aware aggregation and
    BEFORE the two-way boost and Phase 5 pick passes — chosen on what the
    invariant means (a *blend* cannot leave its contributions' range;
    those later stages are overrides computing from a different
    population), not on a measured difference.  Both placements flag zero
    rows on the live board.

    REPLACED the market corridor clamp (W02-F015/F016/F017 =
    #794/#795/#796), which is gone along with
    ``_apply_market_corridor_clamp``, ``_market_anchor_for_row``,
    ``_MARKET_ANCHOR_BY_ASSET_CLASS``, ``_MARKET_ANCHOR_FALLBACKS`` and
    every ``_MARKET_CORRIDOR_*`` constant.  Four measured reasons:

    * its **anchor was a voter** in the blend it corrected — on 539 of
      539 clamped rows across 17 independent historical days, always
      ``idpTradeCalc``, and the fallback chain never fired;
    * its **band was a P90 of the board it policed**, so it clamped a
      fixed ~9% whether the board was healthy or 10x broken — scaling
      every IDP value by 10x fired the identical rows at the identical
      rate;
    * its **confidence bands were ordered backwards** (HIGH permitted
      MORE disagreement than MEDIUM);
    * it **caught nothing upstream did not already handle**.  Injecting
      anomalies at the source CSVs and rebuilding the whole pipeline, it
      fired on 0 of 6 victims in every scenario: a single source at x5 or
      x20 is absorbed by the Hampel filter plus the count-aware blend
      (<=1.7% movement) and an anchor source at x5 is caught outright by
      the declared-range check (0.0%).

    Its stated purpose had also predeceased it: the docstring justified
    it as containing the IDP calibration post-pass, which was retired.

    Removing it changed 32 rows on the live board — all IDP, ranks
    691-740, 2-4 sources each, zero offense, zero picks, and **zero
    change to any published top-200 membership**.

    Known uncovered risk, named rather than papered over: correlated
    multi-source anomalies (measured up to 48% blend movement) are caught
    by neither the old corridor nor this detector, because sources
    agreeing on something wrong is indistinguishable from disagreement at
    the blend.  No independent IDP reference exists to arbitrate — every
    IDP-covering source votes.

    Evidence: ``docs/master-site-audit/evidence/W02/CD_*``.
11. Two-way player boost (``_apply_two_way_player_boost``,
    ``_TWO_WAY_PLAYERS`` — today exactly ``{"Travis Hunter": "DB"}``).
    A genuine post-blend OVERRIDE: ``rankDerivedValue`` becomes
    ``max(offense value, alt-position-family value)``, written to both
    the row and the legacy dict.  Runs after the corridor clamp and
    before the Phase 5 pick passes.

The pick stages are NOT in the order this list used to give.  Actual
live order (corrected 2026-07-29 audit):

12. Multiplicative future-year pick discount
    (``config/weights/pick_year_discount.json``) — **Phase 3a, BEFORE
    the global sort**, applied to the blended value so 2027/2028 picks
    settle lower in the ladder.
13. Pick tethering — **Phase 5.2b, AFTER the sort**: current-year slot
    picks inherit the merged rookie pool's values (offense + IDP
    rookies combined), OVERWRITING ``rankDerivedValue`` outright.  A
    tethered current-year pick therefore never carries a discount
    anyway (its year offset is 0 → factor 1.0), but the causal order
    matters when reasoning about future-year picks.

Master curve constants are refit weekly by
``.github/workflows/refit-hill-curves.yml`` (see
``scripts/auto_refit_hill_curves.py``), but the refit **no longer
ships them**.  It produces a *challenger*, scores it against dynasty
boards the fit never reads (``src/model_registry/holdout.py``), records
the verdict in ``config/model_registry/``, and stops.  Production
constants move only via ``scripts/model_registry.py promote`` +
``apply``, run by a human — see ADR-008 in
``docs/roster-trade-intelligence/DECISIONS.md`` (NOTE: the ADR numbers
are per-file, not global — there is a DIFFERENT ADR-008 in
``docs/league-intelligence/DECISIONS.md`` about replacement levels.
Always cite ADRs with their file) for the three reasons
the previous auto-commit path had no working guard.

Blend weights live in the ``_RANKING_SOURCES`` registry (all 1.0 by
policy).  ``config/weights/default_weights.json`` is historical
documentation only — nothing loads it.

### Perfect Draft — the rookie-auction budget optimizer

``src/draft/`` + ``frontend/lib/perfect-draft.js`` answer *which
COMBINATION of rookies a budget should buy* — not which rookies rank
highest.  Flag ``perfect_draft`` (LIVE, default on); rollback
``RISKIT_FEATURE_PERFECT_DRAFT=0`` **and restart**.  Full reference in
``docs/perfect-draft.md``; decisions in
``docs/roster-trade-intelligence/DECISIONS.md`` ADR-009/010/011.

**The rookie draft has NO per-team slot limit.**  Picks are valued into
``teamTotals[].auctionDollars``; the auction caps nobody's rookie count.
``DEFAULT_INITIAL_SLOTS``, ``phaseMultiplier``, ``slotPressure``, ``mdv``
and ``slotsByTeamFromPicks`` are **gone** from ``draft-logic.js``, and
their removal changed live MaxBid numbers (sheet parity was deliberately
given up — the spreadsheet encoded the same wrong assumption).
``effectiveBudgetFor(remaining)`` is now just remaining dollars;
``topCompetitorMax`` is the richest rival's actual remaining.  Roster
*capacity* (58 in ``dynasty_main``) is real and lives in the optimizer as
``openRosterSpots``.

**Both sides are measured over replacement, and that is load-bearing.**
Rookie board values and the $1200 dollar ladder come from the same convex
Hill curve, so value-per-dollar rises ~30x down the ladder; a raw
``max Σ value`` objective just reads the price curve back out and buys
$1 darts.  So:

```
waiverValue(pos) = best unrostered player at that position
surplus(rookie)  = max(0, boardValue − waiverValue(pos))
ECC(player)      = max(0, base − waiverValue(pos)) × (0.85 + 0.30·waiverScarcity)
   base          = boardValue, or waiverValue when unranked ("assumedWaiver")
NetValue(S)      = Σ surplus − D(|S|)
```

An empty roster spot is worth waiver level, not zero.  Unranked roster
players cost 0 and are stamped — the board's 375/497 floor is an artifact
(19 players at each, single-source, no position), and costing cuts at it
would turn an identity-join miss into a free-cut recommendation.

``D(k)`` depends only on ``k``, so one cardinality-constrained knapsack
solves every plan size at once; star- and depth-focused alternatives are
the ends of that frontier, not a second algorithm.  This is exact, not
heuristic: legal cut-sets are the independent sets of the dual of a
transversal matroid.  Droppability is therefore a **matching** —
``src/ros/lineup.py::solve_optimal_assignment`` re-run per rung — never a
per-position count, because FLEX/SUPER_FLEX make it set-dependent.

``planMaxBid`` is an **indifference price**
(``max{q : bestNetWith(i at q) ≥ bestNetWithout(i)}``), never
``price + (netWith − netWithout)`` — that adds value units to dollars.
It is named ``planMaxBid`` because the board already shows five other
max-bid fields.  ``bestNetWithout(i)`` doubles as the live pivot.

**Live updating.**  The solve is a ``useMemo`` over live workspace state, so it
re-runs on every recorded pick (hand-entered, ``Q`` quick-record, or the live
Sleeper feed), budget edit, PreDraft edit and inflation shift.  One subtlety is
load-bearing: the roster context is a **pre-draft snapshot**, so
``applyDraftProgress`` advances ``openRosterSpots`` and the cut ladder past this
team's purchases — each rookie fills an open spot first, then consumes the
cheapest remaining rung.  Without it roster room is double-counted and the ladder
re-offers cuts already consumed (recommending the same release twice).
``ladderExhausted`` is surfaced explicitly because "no room left to model" and
"nothing is worth buying" render identically and mean opposite things.
``draftPhase`` distinguishes pre/live/complete; ``realizedResults`` values what
was already bought with the SAME surplus/ECC primitives so it is comparable to
the plan.  The ~140 ms solve goes through ``useDeferredValue`` so a burst of
live picks cannot jank the board.  The context itself is fetched once per
(league, team) — deliberately not polled — with a manual refresh for mid-draft
trades.  Code-split with ``React.lazy`` + ``Suspense`` to keep it out of the initial
/draft chunk (124.7 KB vs a 128 KB budget; ``main`` is 125.8 KB without the
feature).  NOT ``next/dynamic`` — that pulled Next's loadable runtime into the
shared graph and moved ~8 KB from the common chunk into EVERY page's chunk,
breaking /waivers' budget as collateral.  Measured both ways.

**Split:** the server serves ``GET /api/draft/roster-context`` (rosters
joined to ``rankDerivedValue``, waiver levels, the cut ladder — all static
for a whole draft, all needing the 4 MB contract + lineup solver +
scarcity); the client runs the knapsack against live ``localStorage``
state.  Not a frontend ranking engine: it recomputes no value, exactly as
``draft-logic.js`` already consumes ``rookieKtcValue``.
``rookieBoardValue`` was added to ``/api/draft-capital`` because the
dollar ladder is not invertible — and it is redacted for public callers.

Cache key carries **team identity**; an unresolvable team is a 400, never
another team's numbers.  The league-match gate scopes the feature to the
league whose rosters are loaded, so the second league (served only by the
Sleeper-derived fallback, which emits no rookie fields) gets a silently
vanished panel rather than a plan built on placeholder rookies.

Confidence is a bootstrap ``P(this plan wins)`` over the frontier **plus**
the per-rookie pivots — without the pivots, two tied plans of the same
size are invisible.  Near-tie at ``P ≥ 0.25``.  Seeded PRNG so the number
does not flicker across re-renders.

Its two uncertainty inputs were documented before they were wired (fixed
2026-08-04, ADR-010 amendment), and both carry a trap worth knowing:

* **A zero ``marketDispersionCV`` means UNOBSERVED, not agreed.**  The
  scraper's dispersion is undefined below two comparable site values — 31
  of the top 72 rookies on the 2026-08-04 board, i.e. the thinnest-covered
  rows.  ``_our_rookie_pool`` nulls non-positive at the source and
  ``valueSigmas`` places those rows at the **p90 of the dispersion observed
  across the pool**; passing the literal ``0.0`` through would present the
  least trustworthy values on the board as the most certain.  The
  ``singleSource`` floor (0.35) is a much narrower term — it fires on 2 of
  72, because the pipeline's flag requires that matching COULD have
  produced more than one source.  Measured effect of wiring it: none on
  the live recommendation (39.5% either way — the 0.075 stand-in lands
  where the old flat 0.08 sat), but live rather than inert (5x the CVs →
  22.0% and a near-tie).
* **Price is a FEASIBILITY risk, not a value risk.**  Surplus is measured
  over replacement and does not depend on price, so a price draw cannot
  move net value — only whether the plan is buyable.  Sigma comes from
  ``sd(ln(paid / preDraftAtPick))`` per tier, shrunk toward the board-wide
  sample and then toward the declared ``PRICE_DISPERSION_PRIOR``;
  ``computeDraftStats`` publishes the raw ratios and ``perfect-draft.js``
  estimates, split that way so the estimator does not drag the solver out
  of its lazy chunk.  ``meta.budgetHeadroomAtP75`` is ``null`` — never 0 —
  when no sigma was supplied.

**Opponent awareness is a price CAP, not a bidding model.**  The
``Prices`` control switches between ``fair`` (the board's
inflation-adjusted price — the default) and ``contested``, which caps it
at one dollar past the richest rival who still wants that tier
(``bayesianTopCompetitor``, computed on every board render since it was
written and read by nothing until now).  The cap only ever LOWERS a
price, so it is never more optimistic about affordability — it stops
requiring you to outbid budgets that no longer exist.

**Positional balance is REPORTED, not optimized**, and that boundary is
deliberate.  ``planPositionBalance`` names which starting slots the
roster cannot fill (measured against the league's own ``starters``
block, never a constant — ``DEFAULT_POSITION_MINS`` is a generic shape
and this league's registry says exactly what it starts), which the plan
fills and which it leaves open.  Folding a positional minimum into the
objective would need per-position counts in the DP state — the explosion
the k-only decomposition exists to avoid — and would mean inventing a
rate at which a filled starting slot is worth giving up board value.

``evaluateBid`` answers the live question (*"bidding is at $X, do I
go?"*) from the same solve ``computeMaxBid`` already runs: win-at-this-
price versus the pivot.  Verdicts are coarse on purpose.

**Backtesting is BLOCKED and ``scripts/backtest_perfect_draft.py`` says
so** (exit 2, never 0 — "no data" must not read as "passed").  Realized
auction prices existed nowhere: ``_normalize_pick`` in
``src/public_league/draft.py`` was reading Sleeper's pick metadata and
discarding ``metadata.amount``, which is now carried through (``None``
for a snake draft — a different statement from ``0``).  What cannot be
fixed is the pre-draft BOARD snapshot: ``rank_history`` does not reach
past ``exports/archive/``'s 2026-07-14 start, and no code recovers an
observation nobody made.  ``--record-snapshot`` captures the board and
every roster context together before an auction; run it first.

Not sourced from BDVM: it returns ``no_projection`` for the 2026 rookie
class (upstream nflverse gap).  ``strategyMultiplier`` is the seam to
replace when that changes.

**Replacement level is a LADDER, and its rungs are the TAIL** (2026-08-04,
ADR-010 amendment).  The flat per-addition ``waiverValue(pos)`` charge
assumed you could sign the best free agent k times over.  ``R(k)`` charges
off ``context.waiverLadder`` instead — and off its *tail*, which is the
part that is easy to get backwards: the baseline is "buy nothing", and an
idle team fills its open spots off the wire, so a plan using k of them
forgoes the LAST k free agents it would have signed, not the best.  With
five open spots, buying one rookie costs the fifth-best.  The charge
saturates at ``W(open)``.

Two defects were found and fixed alongside it, both bigger than the
change that exposed them:

* **The auction's own rookies were counted as free agents.**  Five of the
  six best "free agents" on the 2026-08-04 board were lots in the very
  draft being optimized, so the model advised against paying for a rookie
  TE because that same rookie TE was notionally free.
  ``src/draft/rookie_pool.py`` is now the single definition of "in this
  auction", shared by ``_our_rookie_pool`` and the roster context.
* **Releasing 23 of 30 rostered players cost exactly zero.**
  ``ECC = max(0, base − waiver)`` is 0 for anyone at or below waiver
  level, which under the ladder is a double credit — so the client uses
  ``releaseCost = baseValue × scarcityMultiplier``.  ECC itself is
  unchanged for its other consumers.

**Measured, and it did NOT do what the old note predicted**: the
recommendation moved 35 → 34 rookies, not to a small plan.  The high-k
preference was never the replacement term — it is that **roster value is
an unweighted sum of market values**, so a 58-man roster that starts 21
still books bench player #40 at full market value.  Lineup-aware roster
value is the real fix and breaks the k-decomposition.  Documented in
``docs/perfect-draft.md`` §9.

### Trade Engines
Two independent trade suggestion systems in `src/trade/`:
- **suggestions.py** — roster-aware trade suggestions (sell-high, buy-low, consolidation, upgrades)
- **finder.py** — KTC arbitrage finder (board value vs market value mismatches)

Both enforce a **top-150 quality filter**, but they gate on
**different boards**, and the difference is deliberate. Do not unify
them without reading why (WS-J F-3/F-4):

| Engine | Gate | Ranked against |
|---|---|---|
| `suggestions.py` | `BOARD_TOP_N_FILTER` (150) | **our blended board** — `display_value` order, covers every asset class |
| `finder.py` | `MARKET_TOP_N_FILTER` (150) | **the retail market, per market** — `ktcSfTep` for offense + picks, `idpTradeCalc` for IDP, each ranked within its own population |

`finder.py` must anchor on a real retail value because its whole
premise is arbitrage between our board and the market — the market
number is load-bearing in its arithmetic. `suggestions.py` only needs
an asset-quality gate ("don't propose trading roster clog"), which our
own board answers for IDP and picks that no single retail board
covers.

**Both engines now read the same internal value.** Until 2026-07-27
`finder.py` valued assets off `_finalAdjusted` — a verbatim deep copy
of the raw scraper composite — while `suggestions.py`, `angle.py`,
`waiver.py`, `monte_carlo.py` and the UI all read `rankDerivedValue`.
The finder was arbitraging a board no user could see (WS-J F-6 / audit
finding K). It now reads the canonical board via
`board_values_from_contract`, its absolute thresholds were re-derived
for the new scale rather than ported, and `metadata.valueSource` stamps
which scale produced a run. Assets the board declines to price leave
its universe and are counted in `metadata.assetsUnpricedByBoard` —
202 on a real payload — rather than vanishing silently.

What is still deliberately different is the **gate**, per the table
above: the quality filter, not the value.

Three traps this documentation previously set:

* **`finder.py` was offense-only.** It ranked every asset against KTC,
  and KTC publishes no IDP players — so every defender scored
  `ktc_value = None` and was dropped before scoring. In an IDP league
  the engine silently returned offense-only results. Fixed by the
  per-market gate above; it now emits `marketCoverage` per market and
  warns explicitly when an IDP league has no priced IDP assets.
* **`suggestions.py`'s gate never consulted KTC.** It was named
  `KTC_TOP_N_FILTER` and its helper `_assign_ktc_ranks`, but the rank
  was always the blended-board position. Renamed to
  `BOARD_TOP_N_FILTER` / `_assign_board_ranks`; `boardTopNFilter` is
  the honest metadata field. The `ktc*` names survive as deprecated
  aliases only.

Cross-market note: KTC and IDPTradeCalc are **directly comparable**,
not incommensurable. IDPTC is a full-roster calculator publishing
offense, IDP and picks on one native 0-9999 scale; of KTC's 500 rows,
475 also appear on the IDPTC board at a median value ratio of 1.000
(p10 0.888, p90 1.054, measured 2026-07-26). Both top out at 9999, so
there is no rescaling to apply between them.

### FAAB recommendations — one engine, two separate answers
``src/trade/faab_engine.py`` is the ONLY place a FAAB dollar figure is
derived.  Full reference: ``docs/faab-model.md``.

The design turns on a separation the previous implementation did not
make at all:

* **objective ceiling** — what the player is WORTH, as a share of the
  league's **original** budget.  A function of the player and the
  league FORMAT.  It does not move when a manager spends, and it is
  identical for every team in the league.
* **recommended bid** — what THIS team should bid, given its balance,
  roster, drop side, the week, and the expected clearing price.
  Almost always far below the ceiling.

The old formula had neither.  It was ``0.05 + 0.25 x (value / best
value on the wire)`` of the team's REMAINING balance, so (a) the best
free agent always priced at 21% of budget whether he graded 9999 or
900, (b) a barren wire bid MORE because it lowered the denominator,
and (c) a player's "objective" worth shrank as the manager spent.  On
the real 2026-08-04 board every one of the 40 surfaced candidates
priced between $14 and $21 of $100.

Model, in five stages (all parameters in ``config/trade/faab.json`` —
the engine contains no numeric literal that affects a recommendation):

1. **Anchors** — ``V_allin`` is the board value at
   ``teamCount x starterSlotsPerTeam``, the league-wide STARTING pool;
   ``V_repl`` is the format line at 2x that, blended with the live
   pool's Nth-best unrostered player.  Both recompute per league per
   board refresh and hard-code no player.
2. **Surplus** — ``max(0, V - V_repl)``.  The drop side subtracts the
   same way, so dropping a below-replacement player is free.
3. **Ceiling curve** — smootherstep on ``s^2.2``: a long flat toe for
   replacement-level players, saturating at 100% of the original
   budget at ``V_allin``.  Zero slope at both ends, so nothing jumps
   at a threshold.  An uncapped ``rawCeiling`` keeps growing above the
   line so the market layer can still tell a 2400 player from a 9999.
4. **Team layer** — drop cost, startable-depth need, season option
   value (unspent FAAB expires, so the ceiling relaxes toward 100%
   late), competitive status, then a hard cap at the balance.
5. **Market** — rivals are a zero-inflated lognormal fitted to this
   league's real Sleeper history.  ``recommended = argmax_b P(win|b) x
   (rawCeiling - b)``: bidding the ceiling captures zero surplus by
   construction, which is what produces "worth the whole budget, bid a
   fraction of it".  Verified 2026-08-04: a ``dynasty_main`` player
   sitting exactly on the all-in line (2341) is worth $100 of $100 and
   the engine recommends $33 in week 8.

**The all-in region is derived, not hard-coded**, and it independently
reproduces two managers' stated judgments: ``dynasty_new``'s starter
line (10 x 10 = rank 100) lands exactly on Josh Jacobs (3901), the
value the site owner named; ``dynasty_main``'s (12 x 20 = rank 240 →
2341) sits just under the peer's cluster (Dobbins 2661 / Stribling
2680 / Warren 2938).  Pinned by ``tests/trade/test_faab_calibration.py``.

Rules for new code:

* Need a bid?  → call the engine.  There is no second formula, and
  ``frontend/lib/waiver-logic.js`` deliberately exports none (the old
  ``computeFaabHint`` JS port is deleted — same no-frontend-engine rule
  as ranking).
* Positional scarcity, age, dynasty outlook and the TE/superflex
  premiums are ALREADY inside the canonical 1-9999 value.  Do not
  re-apply them here.  Trending adds and the KTC crowd bid % are
  demand EVIDENCE reported as factor rows; they feed rival engagement
  in the market layer and never scale the objective value.
* Need "does this roster need the position?"  → the engine's
  ``classify_need`` (startable depth vs lineup slots), NOT
  ``suggestions.analyze_roster``.  That helper answers a trade-surplus
  question and, measured on real 58-man best-ball rosters, returns
  ``surplus`` for 68 of 84 team/position pairs and ``need`` once — it
  cannot discriminate here.

**Two independent market signals**, deliberately separate:

* ``data/faab/bid_history_<leagueKey>.json`` — what OUR league pays.
  Full Sleeper transaction history, but one league's culture.
* ``data/faab/crowd_history_<leagueKey>.json`` — what COMPARABLE
  leagues pay for the same player right now, from KTC's public waiver
  database (``scripts/fetch_crowd_faab.py``).  The feed is a ~5-day
  200-row rolling window across ~83 MyFantasyLeague leagues, so it is
  ACCUMULATED (deduped by KTC row id) rather than snapshotted, and
  filtered to leagues matching this league's format.  Measured
  2026-08-04: the wider superflex+TEP market's median claim is 0.30%
  of budget with a p90 of 8.5%, which brackets this league's own 0% /
  6% — the two markets agree.

  It is an anonymous crowd, NOT experts; no ranking source in the
  pipeline is attached to a league at all.  **It prices the MARKET,
  never the PLAYER**: crowd evidence raises rival engagement and the
  expected clearing price, and is structurally unable to move the
  objective ceiling (which is computed before any crowd data is read).
  A player our board grades below replacement stays a $0
  recommendation however hot he is elsewhere — the explanation names
  the disagreement instead of hiding it.  Pinned by
  ``tests/trade/test_faab_crowd.py``.  Note the crowd figure is a
  WINNING bid, already a max over its league's field, so
  ``crowdWinningBidToRivalMedian`` converts it back to the per-rival
  level before it is compared with the modelled share; without that
  the order statistic is counted twice.

Bid history lives in ``data/faab/bid_history_<leagueKey>.json``
(gitignored like the rest of ``data/``), written by
``scripts/fetch_faab_history.py``; run it on prod.  Without it the
engine falls back to configured priors plus the live analytics block
and says so in ``contention.notes``.  Note
``src/api/faab_analytics.py`` gates its median on ``bid > 0`` and so
reports 2.00% of budget where the true median is 0.00% — measured
2026-08-04, 41-77% of adds cost nothing per season (combined 56.6% in
``dynasty_main``, 50.3% in ``dynasty_new``).  ``src/trade/faab_history.py``
keeps zero bids for exactly that reason; prefer it for anything
market-facing.  ``faab_analytics.py`` is unchanged and still powers the
history panel, so anything reading ``leagueMedianWinningBid`` is reading
a nonzero-only median.

Did it work?  ``scripts/faab_backtest.py`` replays this league's real
claims through both models (384 of 695 join to a canonical value today).
Low-value overbids — below replacement, bid > 5% of budget — go from
**166 of 166 (OLD) to 0 of 166 (NEW)**, and that band is 43% of the
sample.  Total committed falls from 45.51 budget-units (OLD) to 23.18
(NEW) against 9.25 actually spent.  NEW's win rate is *lower* (59.4% vs
95.3%) **by design** — OLD buys its win rate by bidding roughly 5x the
market on everything.  Report this honestly rather than cherry-picking:
NEW's median overpayment is $0 vs OLD's $20 but its **mean is worse**
($44.77 vs $34.73, dragged by look-ahead artifacts above the all-in
line); the claims NEW declined cost 8.00 budget-units of forgone roster;
and "impactful players missed" is 0 for BOTH models, so it is evidence
NEW gave nothing up at the top, not evidence it improved there.  The
script states five structural caveats at the top of every run; read them
before quoting it.

### Canonical Data Mode
The offline canonical-build path (``scripts/canonical_build.py`` +
``src/canonical/transform.py`` + ``src/canonical/pipeline.py``) and its
``CANONICAL_DATA_MODE`` branches have been retired.  The live
``/api/data`` contract is the single source of truth; trade
suggestions read from it directly.

### BDVM — the fundamental valuation engine (feature-flagged, ON since 2026-07-28)
``src/bdvm/`` is a SECOND, INDEPENDENT value concept: projection-driven
*fundamental* dynasty value per the Brisket Dynasty Valuation Model
(``docs/research/bdvm-v1/`` — research PDF, verified reference fixture,
and the living ``IMPLEMENTATION_REPORT.md``).  Core rules, all
test-pinned (``tests/bdvm/``):

- **It never touches ``rankDerivedValue``** or any existing route. The
  market board above stays the market-value concept; BDVM is the
  fundamental-value concept; they are compared, never merged in place.
- Reachable behind the ``bdvm_engine`` feature flag, **default ON**
  since 2026-07-28 — the condition it was held off for is met:
  ``scripts/bdvm_build_baseline.py`` writes a real snapshot (2,815
  records for 2026) and the engine answers ``status: "ok"`` with
  726 players priced and 222 honestly unpriced. Additive by
  construction: it never writes ``rankDerivedValue`` or touches an
  existing route, the /rankings Fund-gap column gates on
  ``status == "ok"`` so it self-suppresses without a snapshot, and
  the alert leg seeds a silent per-(user, league) baseline so
  flag-on day cannot flood. Rollback:
  ``RISKIT_FEATURE_BDVM_ENGINE=0`` **and restart** — flag reads are
  cached per process and there is no runtime toggle. Endpoints:
  at ``GET /api/bdvm/values`` (``surplusMode=option|truncated|plain``
  exposes the option-value ablation), ``GET /api/bdvm/roster``
  (strategy capitals + league-relative direction per roster) and
  ``GET /api/bdvm/trades`` (double-positive scan: each side must gain
  in its OWN strategy currency, gated by single-market fairness).
- Projections come from immutable snapshots under
  ``data/bdvm/projections/``: real sources first — **Mike Clay's ESPN
  guide** via ``scripts/fetch_clay_projections.py`` (public CDN PDF,
  ``pdftotext -layout``, team pages only: raw season stat lines for
  offense — the real OFFENSE source — plus a second IDP feed; combined
  tackles split with the shared 0.62 solo share; a two-way player gets
  ONE record combining both sides under the DEFENSIVE position so the
  scoring gate counts everything; same-side name collisions dropped,
  never guessed), **The IDP Show** projections via
  ``scripts/fetch_idpshow_projections.py`` (authenticated
  Datawrapper/Sheet pattern shared with the idpShow rankings fetcher;
  ``--csv`` for a manually downloaded sheet) and the manual-CSV
  adapter — else the §8.3 reconstructed baseline built by
  ``scripts/bdvm_build_baseline.py`` (realized nflverse PPG under the
  league's exact scoring + rookie draft-slot priors, all flagged
  ``is_proxy``; carries real records forward on rebuild).  All real
  sources merge via the shared ``supersede_merge_into_snapshot``
  policy: each replaces its own prior run wholesale and supersedes
  proxies per player while other real sources carry through, so a
  defender covered by Clay AND IDP Show gets a two-source consensus.
  The consensus is **vocabulary-aware**: a stat-line record whose
  league-scored IDP categories are a strict subset of a peer's (Clay
  publishes no TFL/PD — categories this league pays 4.25/5.32 for) is
  down-weighted by the labelled prior
  ``projection_consensus.vocabulary_dominated_weight_mult`` instead of
  dragging the mean down or silently imputing the missing categories;
  affected sources are stamped in ``projection.vocabularyLimitedSources``.
  Structured events (closed ontology,
  ``config/bdvm/event_types_v1.json``) adjust module inputs — never a
  final score — from ``data/bdvm/events/<season>.json``.
- Fundamentals compute with ZERO market inputs; the market layer
  (``src/bdvm/market.py``) runs strictly afterward and reads only
  value-signal sources (``ktcSfTep``/``ktc``/``idpTradeCalc`` — never
  the rank-signal synthetic encodings in ``canonicalSiteValues``).
- No positional multipliers anywhere: Superflex/TEP/IDP format effects
  flow from exact scoring + flex-aware dynamic replacement.
- Missing data is never imputed into a normal-looking value: players
  without a projection or age are returned as ``unpriced`` with a
  reason; with no projection snapshot the endpoint says so.
- Every payload is versioned: ``modelVersion`` + content-hashed
  ``paramSetId`` (``config/bdvm/params_v1.json`` — priors, not
  validated truth) + league ``configHash`` + ``asOf``.
- The frozen reference implementation under
  ``docs/research/bdvm-v1/reference/`` is an acceptance fixture — do
  not modify it and do not import it from ``src/``; the production
  engine must keep reproducing its Appendix-C numbers
  (``tests/bdvm/test_engine_parity.py``).

The platform currently has no forward-looking statistical projection
feed (everything live is market-rank derived), so BDVM ships with a
manual-CSV projection adapter + a reconstructed-baseline proxy builder
and stays dormant until snapshots exist under ``data/bdvm/projections/``.

Operational surfaces (post-merge additions):

- **Frontend**: ``/bdvm`` ("Fundamentals", Intel nav group) renders the
  three endpoints — value board (strategy-currency selector, surplus-mode
  ablation, fundamental-vs-market gap + signals), roster strategy
  capitals with expandable assets, and the double-positive trade scan.
  Pure display layer: ``frontend/lib/bdvm.js`` only reshapes/formats
  backend numbers (same materializer rule as ``buildRows``); the flag-off
  503 renders an explicit "engine switched off" state, never a generic
  error (``classifyBdvmFailure`` distinguishes the three 503 variants).
  Dev bridge routes at ``frontend/app/api/bdvm/*``; tests in
  ``frontend/__tests__/bdvm-lib.test.js`` + ``components/bdvm-page.test.jsx``.
- **Snapshot cadence**: ``scripts/refresh_bdvm_projections.py`` (weekly
  ``dynasty-bdvm-refresh`` systemd timer, Tue 06:10 UTC) rebuilds the
  reconstructed baseline, then merges Mike Clay's guide (self-skips
  without poppler-utils or on a CDN 404), then The IDP Show real
  projections (session jar shared with the rankings fetch timer; stage
  self-skips without it). Exit codes 0/1/2 in the playerctx style; runs
  on prod because the endpoints read local gitignored ``data/``.
- **Rankings gap column**: /rankings grows a "Fund gap" column
  (fundamental balanced minus market, tinted by BDVM signal) joined
  onto board rows AT RENDER TIME from ``/api/bdvm/values`` —
  playerId-first, name fallback (``lib/bdvm.js::buildBdvmIndex`` /
  ``bdvmEntryForRow``). The column exists only while the endpoint
  serves an ok payload and vanishes silently on any 503 (flag off, no
  snapshot, wrong league). Ranks and the ``#`` column stay
  backend-stamped — this is display enrichment, never a re-rank; the
  page's ``presorted`` sort switch gained a ``case "gap"`` (nulls sink).
- **Signal alerts**: ``src/api/bdvm_signal_alerts.py`` piggybacks on the
  daily ``/api/signal-alerts/run`` sweep (no new timer). Separate
  detector from the terminal one by design: different label set
  (STRONG_BUY..STRONG_SELL actionable; HOLD/NO_MARKET never) and a
  separate user_kv namespace (``bdvmSignalAlertStateByLeague``, keys
  ``bdvm:{playerId}``). Roster-scoped via the BDVM roster analysis;
  whole-league board computed once per league per sweep. **Baseline
  seeding**: the first sweep for a (user, league) records current
  actionable signals silently (``notifiedAt: 0``) so flag-on day never
  floods inboxes — pinned in ``tests/api/test_bdvm_signal_alerts.py``.
  Flag off → the sweep stamps ``bdvmEnabled: false`` and skips
  entirely.
- **Trade calculator check**: ``POST /api/bdvm/trade-eval``
  (``src/api/bdvm_api.py::get_bdvm_trade_eval``) CES-evaluates ONE
  specific trade in every strategy currency — package math is
  ``package_value`` (§3.13), never a plain sum. Asset refs resolve
  playerId-first → normalized name → pick name (picks use the
  strategy's distribution EV); unresolvable refs are reported in
  ``unresolved`` per side, never silently priced at zero. The route
  parses its body BEFORE the shared gate so the body ``leagueKey``
  reaches the resolver (POST convention — pinned by
  ``tests/bdvm/test_endpoint.py``). Renders as the "Fundamentals
  check (BDVM)" panel on /trade
  (``frontend/components/BdvmTradePanel.jsx``, below RosTradeFitPanel):
  display-only, never touches sideTotals/TradeMeter, silent-vanish on
  any non-ok. Tests: ``tests/bdvm/test_trade_eval.py``.
- **In-season updating** (§8.4): ``run_valuation(actuals=...)`` blends
  realized weekly PPG — scored under the league's exact settings from
  nflverse weekly rows (``src/bdvm/actuals.py``, REG weeks only, its
  own 24h disk-cache key) — into the projection posterior via
  ``blend_ros_mu`` (``w = n_prior/(n_prior+weeks)``, n_prior 6 offense
  / 8 IDP); σ shrinks by ``√w_prior``; ROS drops already-played weeks
  via ``current_week`` (uncapped — after the week-18 slate it is 19 so
  ROS sums zero, never double-counting the banked final week), with a
  per-player boundary-week rule: the in-progress week counts as
  remaining for players who haven't played it yet (nflverse publishes
  game-by-game). The actuals season is the CALENDAR NFL season
  (``current_nfl_season``: Sept–Dec → year, Jan → year−1, else None)
  — NEVER ``currentDraftYear``, which points one season ahead for the
  whole Sept–Jan window and would make the posterior structurally
  unreachable. Distinct players colliding on a normalized name are
  dropped (chimera guard, projection-side policy). Preseason is an
  exact no-op (``meta.inSeason = {"active": false}``). ``bdvm_api``
  refreshes actuals once per UTC day; fetch FAILURES are returned but
  never memoized, so a transient blip can't pin the board to preseason
  values until midnight. Tests: ``tests/bdvm/test_inseason.py``.
- **News → events ingestion**: ``src/bdvm/news_events.py`` piggybacks
  on the same daily signal-alerts sweep (runs BEFORE the per-user
  loop). Aggregated headlines map via conservative ordered keyword
  rules onto 11 of the 18 §7 ontology types (no match → NOTHING;
  ambiguous player mention → NOTHING; advice/listicle language —
  "trade targets", "who makes the cut", rankings/waiver/mock-draft
  vocabulary — → NOTHING; items naming >3 players → NOTHING;
  ACTIVATED_RETURN deliberately unmapped because its impact narrows
  σ). Auto events land in the speculation lane structurally:
  ``confidence = 0.45 < 0.5`` means ``effective_impact`` suppresses
  every non-sigma channel AND clamps ``sigma_mult ≥ 1.0`` — a headline
  can widen uncertainty but can NEVER move a mean or narrow σ; raising
  confidence is a human edit to ``data/bdvm/events/<season>.json``.
  Merge is dedup-by-eventId (``news:<item-id>:<player-key>``) plus
  same-fact suppression (one ``(playerKey, eventType)`` per 14 days —
  N providers ≠ N sigma wideners) with existing-wins; the 90d prune
  touches only ``news:*`` events still at speculation confidence
  (human-raised confidence exempts an event); refuses on corrupt OR
  valid-JSON-wrong-shape files rather than discarding human entries,
  and preserves extra top-level keys (``_comment``) on rewrite. The
  events-file fingerprint (mtime_ns, size) sits in the bdvm_api cache
  key, so every write invalidates cached boards. Tests:
  ``tests/bdvm/test_news_events.py``.
- **Draft board join**: /draft grows a "Fund gap" column on the
  RookieBoard — name-based join only (draft rows are keyed by
  ``playerSlug`` and carry no playerId) — plus a collapsed-by-default
  "Fundamental pick values (BDVM)" panel (balanced-strategy pick
  EV / hit% / median / ceiling beside the market anchor, from
  ``buildBdvmPickRows``). Same silent-vanish posture as the rankings
  gap column; sorting by gap sinks unpriced rows; auction math and
  backend-stamped ranks untouched. Tests:
  ``frontend/__tests__/components/DraftBoardSort.test.jsx``.

### Confidence — one owner, five axes, a bottleneck (B11)

``src/api/confidence.py`` is the ONLY place a ``confidenceBucket`` is
decided. ``data_contract.py`` assembles the evidence and decides no
level; there is **no frontend confidence math**, which is why the gate's
parameters live in ``config/confidence/gate_v1.json`` and are
deliberately NOT mirrored into ``frontend/lib/thresholds.js`` — the
parity test would require the JS export, and that is exactly the
client-side constant #725 removed.

Confidence answers **"how good is the evidence behind this value"**, and
the unit of evidence is the **B10 provider family**, never the source
key.

| axis | question | HIGH needs |
|---|---|---|
| independence | how many correlation-group heads voted | ≥ 5 families |
| coverage | how many of the **eligible** families actually did | ≥ 75% |
| freshness | how many of those are inside their ``maxAgeHours`` budget | ≥ 75% |
| applicability | how many reached the row without approximation, on this board's TE++ basis | ≥ 75% |
| agreement | how many price within 15% relative of ``rankDerivedValue`` | ≥ 75% |

**Overall = the WEAKEST axis.** Nothing averages, so a large source count
cannot buy freshness, applicability, coverage or agreement.

Four things are load-bearing and easy to undo by accident:

* **5 / 3 families are the BLEND's own rungs**, not new numbers.
  ``_mean_median_blend`` trims one extreme per side at k ≥ 5, so five
  families is the smallest panel whose published value survives one
  outlying opinion in either direction; 3-4 is the untrimmed rung, 2 a
  plain mean, 1 a passthrough. Two families therefore cannot exceed LOW.
* **Coverage's DENOMINATOR is what COULD have been observed.** A family
  that stops covering a row stays eligible, so its silence is permanent
  missing evidence. This is what makes deleting evidence unable to
  promote a row — MISSING IS NEVER ZERO applied to confidence.
* **A duplicate family member is not an input to any axis.**
  ``assess_confidence`` RAISES on a repeated family rather than
  averaging or ignoring it. Collapsing a family is therefore an exact
  identity on confidence, which is invariants 1 and 2 discharged
  structurally rather than by calibration.
* **Agreement is measured in VALUE space**, against ``rankDerivedValue``,
  with the same symmetric mean normalisation ``marketGapValueRatio``
  uses. Consequence: any post-blend OVERRIDE that moves a value
  invalidates the stamp taken before it, which is why
  ``_restate_confidence_after_override`` re-runs the gate on rows whose
  value changed (found on Travis Hunter, whose two-way boost left all
  eleven families 24-56% below the published number while the row
  claimed high agreement).

RETIRED: ``max(percentile) − min(percentile)`` bucketed at 0.08 / 0.20.
A range can only narrow when an observation is removed, so deleting
evidence promoted rows — and re-basing the same statistic onto
independent evidence reproduced the failure (60 rows, wrong direction;
#833). ``sourceRankPercentileSpread`` is still computed, still published
and still drives ``hasSourceDisagreement``; it no longer decides
confidence. Do not reintroduce a range as the deciding statistic.

Picks keep their own coefficient-of-variation rule
(``assess_pick_confidence``) because rank spread on picks is dominated by
the flat-value regions in R3-R6 — but it is family-aware, and its
independence bar is 2 markets rather than 5 because the pick population
only HAS 2-4 families (KTC + IDPTC).

Per-row fields: ``confidenceBucket`` / ``confidenceLabel`` /
``confidenceAxes`` / ``confidenceReasons``. ``metrics`` stays on the
assessment object and off the payload (the reasons already carry its
numbers, and publishing both cost +15 KB gzip for a block nothing
renders). Full record: ``docs/master-site-audit/B_SERIES_EXECUTION_LEDGER.md``
§B11; distribution evidence in
``docs/master-site-audit/evidence/B11/``.

### Single Source of Truth: Rankings Override Path
Custom source configurations (user-toggled sources or custom weights) flow through the **SAME** canonical pipeline as the default board. There is no frontend ranking engine, period — not even a fallback. `buildRows` is a pure materializer.

Flow:
1. User toggles a source or changes a weight on `/settings` (writes into `settings.siteWeights`).
2. `useDynastyData` observes the change, calls `fetchDynastyData({siteOverrides})`.
3. `fetchDynastyData` POSTs the override map to `POST /api/rankings/overrides?view=delta` and receives a compact delta payload (~70% smaller than the full contract — see Payload Size Optimization below).
4. `fetchDynastyData` merges the delta onto the cached base `/api/dynasty-data` contract via `mergeRankingsDelta` and returns a fully-populated contract object.
5. `server.py::post_rankings_overrides` invokes `build_rankings_delta_payload(raw_payload, source_overrides=...)` (or `build_api_data_contract` for legacy full-view consumers).
6. `src/api/data_contract.py::_compute_unified_rankings` filters disabled sources and applies overridden weights — same Hill curve, same coverage-aware blend, same robust-median step.
7. `buildRows` materializes the merged contract; it trusts backend stamps verbatim and never recomputes VALUES.

One precise nuance on ranks (documented 2026-07-29 audit — the line
above used to read "never recomputes ranks", which overstated it):
`buildRows` assigns a display ordinal `computedConsensusRank = i + 1`
after sorting (`dynasty-data.js:1366`) and uses it for `r.rank`
(`:1378`) **only** when the backend stamped no `canonicalConsensusRank`
on that row. In practice that is players past the backend's
`OVERALL_RANK_LIMIT` (800) — rows the backend deliberately left
unranked — and it is suppressed for picks and whenever a valuation
overlay is active. A backend-stamped rank always wins.

This is a display ordinal for otherwise-unnumbered rows, not a ranking
engine: no value is recomputed and the sort key is the backend's
`rankDerivedValue`. The no-frontend-ranker rule is intact.

Registry lockstep:
- Python registry: `src/api/data_contract.py::_RANKING_SOURCES`
- Frontend mirror: `frontend/lib/dynasty-data.js::RANKING_SOURCES`
- Runtime check: `GET /api/rankings/sources` returns the authoritative Python registry (proxied through `frontend/app/api/rankings/sources/route.js`)
- Parity test: `tests/api/test_source_registry_parity.py` parses the frontend JS and diffs against the Python registry.

**Fail-fast on missing stamps**: The prior `computeUnifiedRanks` fallback (~280 lines of coverage-aware blend code) has been **removed**. `buildRows` now fails fast when a non-empty payload has zero backend rank stamps: it logs an error and returns an empty rows array, letting the `useDynastyData` error state surface a "no players" banner. There is no silent recompute. If you see the fail-fast error in production logs, the scrape pipeline is not stamping — investigate upstream, do not add a client-side blend.

### Two overlays, and why neither one relaxes the no-frontend-ranker rule

There are **two** delta-shaped overlays on the contract. They differ in the
one way that matters most in this codebase — their scope:

| overlay | scope | driven by | endpoint |
|---|---|---|---|
| rankings override delta | **scoring profile** — shared across leagues | user source weights | `POST /api/rankings/overrides?view=delta` |
| league-adjusted valuation | **leagueKey** — roster-derived, never shared | positional scarcity from this league's 12 rosters | `GET /api/valuation/league-adjusted` |

The valuation overlay is league-scoped *by necessity, not convention*.
`lineupScarcity` is measured from one league's rosters, so two leagues sharing a
scoring profile get different adjusted values. Stamping it onto the contract
would let one league's roster shape silently reprice another's board — the exact
collapse the scoring-profile/leagueKey split exists to prevent. Hence an overlay
the client applies, never contract fields.

**Ranks are backend-computed in both cases.** The valuation overlay ships dense
`ranks` + `tiers` alongside sparse `factors`, produced by
`data_contract.py::compact_ranks_and_tiers` — the *same* function the pipeline
uses, called on shallow copies because `latest_contract_data` is a shared mutable
global. `buildRows` still consumes stamps verbatim. This feature **conformed to**
the "no frontend ranking engine, period" rule rather than being excepted from it:
the rule is what forced the composing design instead of a client-side re-sort.

Two consequences worth knowing before touching this:

- **`factors`, not absolute values.** The adjustment factor is a function of
  position alone and never reads the consensus value, so it composes exactly
  against any board — including one the user re-weighted. Absolute values would
  carry the default board's numbers into a board the server never computed.
- **The server-side composition is GONE (B9a).** `POST /api/rankings/overrides`
  used to accept `valuation_mode` and multiply the league factors into
  `rankDerivedValue` after the override pipeline, so the endpoint could serve a
  board that was both re-weighted and league-adjusted. The arithmetic was right
  — `overridden_consensus × factor` is a board the client cannot construct — but
  #822 rejected that methodology for promotion to canonical and ruled it **may
  not own a canonical field**, and this path was the one place still writing it.

  It also breached the scale. The ±25% bound is applied to the **factor**
  (`league_intel/adjustment.py`), never to the **product**, so canonical values
  left their declared 1–9999 range: measured on the 2026-08-14 board, **10,160**
  under the real factor set and **12,471** at the cap, both published under
  `rankDerivedValue`. 9,999 is the Hill **asymptote**, so those are numbers the
  curve defining the scale cannot produce.

  The request is now **ignored, not refused** — the same convergence rule the
  engine gate uses, so a stored `leagueAdjusted` on someone's phone quietly
  returns to the canonical answer. `meta.valuationMode` is always `"market"`
  with `valuationNote: "league_adjusted_withdrawn: not_canonical"`.
  `apply_valuation_factors` and the `valuation_factors` parameter are **deleted**
  rather than left unreferenced, so there is no seam to re-thread by accident.

  Two consequences: asking for the lens **no longer narrows scope** (nothing
  league-scoped is computed, so no 503 on a league mismatch), and the response
  is **cacheable** again (the memo excluded it only because gameplan freshness
  was unseeable). The full and delta views now answer identically.

  Pinned by `tests/api/test_canonical_value_scale_contract.py` (the scale is a
  contract on every published path, plus the structural absence of the seam) and
  `tests/api/test_league_adjusted_endpoint.py` §4.

Regression tests: `frontend/__tests__/valuation-overlay.test.js` (both
materializer key sets — the legacy dict uses `_canonicalConsensusRank` but
`rankDerivedValue`, and the legacy path is the default one), and
`tests/league_intel/test_publish.py` (caller-row isolation, dense contiguous
ranks, anchor-slot-pick exclusion).

### `valuation_mode`: accepted, ignored, and stamped

**The lens is WITHDRAWN everywhere.** It was never deleted from the request
surface, and that is deliberate — read on.

The history matters because the shape is a scar from it. The overlay is for the
*client* to multiply onto a board it holds, which covered `/rankings` and
nothing else: every engine (trade suggestions, the arbitrage finder, angles,
waivers, the terminal, the simulator) runs server-side off
`latest_contract_data` and never saw it, so switching the board changed the
rankings page and left the trade advice market-priced with no field saying
which was which. The repair threaded `valuation_mode` through every
league-scoped engine endpoint, via one mechanism —
`server.py::_valuation_scoped_contract` handed the engine a repriced contract,
so no engine had to know the feature existed.

Then #822 evaluated that methodology for promotion to canonical and **rejected
it** on seven measured defects (current-roster-state input, an ordinal
log-rank driver, an underived `0.5` reference constant, position-wide scalars,
no scale renormalisation, no staleness detection, no double-count guard) and on
the absence of the outcome evidence a replacement would need. Full record:
`docs/valuation/LEAGUE_AWARE_METHODOLOGY_REJECTION.md`.

So today, at every one of those endpoints plus
`POST /api/rankings/overrides` (closed later, in B9a):

* the field is still **parsed** — `_requested_valuation_mode`;
* the request is **ignored, never refused**. A stored `leagueAdjusted` in
  someone's `localStorage` must converge to the canonical answer silently;
  refusing would turn an obsolete client-side value into a broken page for a
  user who never chose anything;
* the response is stamped `valuationMode: "market"` with
  `valuationNote: "league_adjusted_withdrawn: not_canonical"`, because
  "this is the market board" and "this field is missing" must not read the same.

`_valuation_scoped_contract` is the single seam where the lens ever reached an
engine, which is why it is the single place it is closed — pinned by
`tests/api/test_canonical_value_invariance.py`. `src/league_intel/overlay.py`
still computes the board, but writes only `experimentalLeagueAdjustedValue` /
`…Rank` / `…Tier` and is forbidden from touching `CANONICAL_VALUE_FIELDS`.

Rule for new code: **do not re-thread `valuation_mode` into anything.** A
future validated league-aware methodology re-opens one seam deliberately, and
renormalising onto the 1–9999 scale is part of what it has to earn.

**The governing invariant, stated carefully.** This section used to read "every
engine reads exactly one value — `rankDerivedValue`", full stop. That is too
absolute, and `docs/master-site-audit/VALUE_FLOW_MAP.md` §4 splits it:

| claim | verdict |
|---|---|
| One function computes the board | holds — `_compute_unified_rankings`, bit-reproducible |
| No frontend ranking engine | holds |
| Every engine *reads* `rankDerivedValue` | holds |
| Every engine *serves* `rankDerivedValue` | holds (B9a) |
| One number per player per session | holds (B9a) |

The invariant to design against is therefore:

> **Canonical player value has one owner, and every downstream engine and
> surface consumes that canonical value — unless it is deliberately showing an
> explicitly named alternate concept, in which case the name travels with the
> number.**

Serving a different quantity under the canonical field name is a defect, not an
alternate opinion. **Both measured violations are now fixed** (B9a — W29-F001,
W29-F002).

The mechanism was a SECOND CANONICAL BOARD. `build_api_data_contract` ran
`_compute_unified_rankings` a second time with every IDP-scoped source disabled
and stamped the result on each row as `offenseOnlyRankDerivedValue`; three
engines then substituted it whenever the trade in front of them happened to
contain no defender — `suggestions.py` into `displayValue`, `finder.py` into
`modelValue`, `trade_simulator.py` into the resolved asset value *and* the
manager's entire untraded roster. The switch was **per trade, not per league**,
so one player carried two unlabelled numbers in one league on one day.

Measured on the 2026-08-14 contract before removal: 605 rows carried it, 507
were comparable, and **491 of those disagreed** — up to 21.87%. The
disagreement was never confined to defenders; **picks moved most** (2026 Pick
2.06: 3,224 → 2,519), because `idpTradeCalc` is a full-roster calculator and
dropping it changes the count-aware blend, the Hampel filter, the single-source
haircut and the pick anchor set for every row.

Removed rather than deprecated — a ready-made second canonical board on every
row is what let three engines wire it in without anyone deciding to. The
canonical board is byte-identical after removal (0 values moved, 0 ranks
changed, `scripts/board_diff.py --expect-no-value-change`), and the contract
build lost a duplicate pipeline pass (0.62 s → 0.49 s median).

An IDP-free view **filters the asset universe or names its lens; it does not
reprice the assets.** `suggestions._trade_is_idp_free` survives as exactly that
— a universe predicate — and its docstring says so. Pinned by
`tests/api/test_one_canonical_value_per_asset.py`, which asserts the invariant
(same asset, same value, whatever else is in the trade) plus a structural guard
that neither engine's asset type can carry a second board again.

W29-F002's overlay half was closed separately by #822: `overlay.adjusted_rows`
now writes `experimentalLeagueAdjustedValue` and never a canonical field.

The rule this yields for new work: **existing implementation behavior does not
become canonical architecture merely because it ships.** When code and the
canonical product architecture disagree, the code is the defect.

Four rules that are load-bearing:

- **`overlay.adjusted_rows` returns EVERY row, not the ranked ones.**
  `compact_ranks_and_tiers` returns only rows it ranked, dropping unranked rows
  and clearing current-year slot picks. Serving that subset measured 740 of
  1093 rows on the live contract — every 2026 pick gone from the trade
  calculator under the adjusted lens. It ranks our copies in place instead.
- **Nothing mutates `latest_contract_data`.** It is a shared module global; one
  in-place multiply would reprice the market board for every other request.
- **Degrade, never fail.** No roster snapshot, an incoherent adjusted board, or
  a broken overlay all serve the *market* board with a `valuationNote` naming
  the reason. Refusing would take down working engines to protect an optional
  lens.
- **Every response stamps `valuationMode` — including `"market"`.** "This is
  the market board" and "this field is missing" must not read the same.
  `tests/api/test_valuation_mode_threading.py` statically requires every
  handler that applies the lens to also stamp it.

Client side: `frontend/lib/valuation-mode.js` is the single answer to "which
board did the user pick" for all six call sites. `useTerminal` keys its cache
on the mode — a cache without it serves the stale market payload for the full
TTL after a switch, which looks exactly like the toggle being broken.

**The adjusted board is a toggle, not the default, and that is a measured
decision** — see `docs/adjusted-board-backtest.md`. Ranked against realized
2025 scoring over 572 players, four framings all return "no difference
detected" and three of four lean negative. Re-run
`scripts/backtest_adjusted_board.py` after any axis change.

### Rankings Override Payload Size Optimization
The `POST /api/rankings/overrides` endpoint supports two response views:

- `view=full` (default, backward-compat): returns the full canonical contract (~4 MB uncompressed, identical shape to `GET /api/data`).
- `view=delta` (default for frontend): returns only the override-sensitive fields per player, keyed by `displayName`, dropping the legacy `players` dict, `sleeper`, `methodology`, `poolAudit`, and other override-invariant blocks. Production payload drops from ~4 MB to ~1.25 MB uncompressed, and to ~100 KB over the wire with FastAPI's `GZipMiddleware`. The frontend merges the delta onto its cached base `/api/data?view=app` payload.

Regression test: `tests/api/test_source_overrides.py::TestBuildRankingsDeltaPayload` pins the delta shape, byte-size bounds, and the invariant that every field in `_DELTA_PLAYER_FIELDS` round-trips through a manual merge identically to the full-contract path.

See `tests/api/test_source_overrides.py` for the full contract spec.

### The sharp cohort: one pool, many surfaces

`src/sharp/cohort.py::cohort_members` is THE definition of "who is a
sharp". Every sharp-powered surface resolves its manager pool through
it, and none of them may keep a second list or add a qualification rule:

| surface | module |
|---|---|
| Sharp Buy/Sell Tracker (`/market/sharp-tracker`) | `src/sharp/market.py` |
| Sharp Roster Percentage (`/market/sharp-roster-percentage`) | `src/sharp/roster_percentage.py` |
| roster collection pass | `src/sharp/roster_collect.py` |
| activity crawl | `scripts/crawl_sharp_activity.py` |

`market.py` re-exports `CohortMember`, `cohort_members`,
`curated_members`, `provisional_members` and `load_ffpc_config`, so
`sharp_market.cohort_members` still resolves and the monkeypatch seam
existing tests use is preserved. Note the re-export is a
`from ... import` binding taken at import time — a test that patches
the cohort module before importing `market` captures the stub.

Qualification is decided in `src/sharp/score.py` +
`config/sharp/scoring_v2.json` over evidence from
`src/sharp/platform_records.py`; league eligibility in
`src/intel/league_filter.py` (dynasty only, ≥ 2 seasons). `cohort.py`
only SELECTS and DEDUPLICATES.

**Three sharp crawl passes, in order** — each depends on the one before,
which is why the timers are staggered:

1. `scripts/discover_sharp_graph.py` (04:20 UTC) — finds MANAGERS
2. `scripts/crawl_sharp_records.py` (04:50) — finds their RESULTS, which
   is what makes them scoreable
3. `scripts/crawl_sharp_rosters.py` (05:50) — finds what they currently
   OWN, which is what the roster-percentage board is made of

Two things the roster pass depends on, both fixed rather than worked
around:

- `discovery.py` records a `league_memberships` row at USER-expansion
  time as well as league-expansion time. It used to record one only when
  a league was expanded, so leagues left on the frontier by the budget
  had none — invisible to anything asking "which leagues does this
  manager play in", which silently bounded the roster crawl to the
  expanded subgraph.
- The roster pass orders leagues through
  `record_queue.prioritize_league_ids` (never-collected first, then
  oldest), the same fair ordering the records crawl uses. Sorting by
  league id meant a budget-capped run re-collected the same prefix
  forever and never reached the tail.

`server.py` calls `_sharp_service.register_http_routes()` explicitly
after importing the module. The import-time side effect alone is not
enough: anything that imports `src.sharp.service` before the app exists
makes it a no-op, and the module cache means the later import re-runs
nothing — `/api/sharp/market` then 404s with no other symptom.

Roster observations live in `sharp_rosters` / `sharp_roster_assets` /
`sharp_roster_asset_spans` / `sharp_roster_observations`
(`src/sharp/roster_store.py`), created by a plain
`CREATE TABLE IF NOT EXISTS` that is deliberately NOT wired to
`platform_ledger.PLATFORM_SCHEMA_VERSION` — bumping that re-runs the
whole platform migration on every deployed ledger to add four additive
tables.

Counting rules are enforced by primary keys rather than by caller
discipline: one row per roster, one row per (roster, player). The
denominator is ROSTERS, not people — a sharp with five dynasty teams
contributes five observations — and it is computed PER PLAYER, because a
linebacker cannot be rostered in a league with no IDP slots. Full
methodology and the known limitations (no general-dynasty ownership feed
exists; FFPC contributes zero rosters until a roster-bearing URL is
configured) are in `docs/sharp-roster-percentage/METHODOLOGY.md`.

### Player identity — one owner, dual-read migration in flight (C1-ID-01)

`src/identity/` owns player-identity resolution. `resolution.py` is the canonical
engine: legacy-faithful V1 policies (`SCRAPER_SLEEPER_ATTACH_V1`,
`CONTRACT_CSV_JOIN_V1`) reproduce the two historical matchers exactly for the
dual-read migration, and `CANONICAL_V2` is the repaired destination semantics
(guarded fuzzy per W06-F006, explicit AMBIGUOUS/UNRESOLVED with reasons and
candidates, group-level position drift tolerance, deterministic under directory
order). `name_primitives.py` holds the scraper's name-matching primitives, moved
verbatim; `Dynasty Scraper.py` imports them back and is an ADAPTER, not an owner.

Migration state: **CUT OVER (2026-08-16).** Both sites resolve through the owner and
the legacy ladders are **deleted** — no flag, no fallback. Served policies are
`SCRAPER_SLEEPER_ATTACH_V1` and `CONTRACT_CSV_JOIN_V1` (the owner's exact
transcriptions of the retired ladders), proven identical on production before the
swap: scraper 2,016/2,016 over a full refresh cycle, contract 24,024/24,024, and a
before/after board rebuild moving 0 of 1,092 rows.

**`CANONICAL_V2` is implemented but NOT served, deliberately.** The same production
cycle measured that it is not yet a strict improvement: it would drop correct identity
for the first-name-variant class (Matt/Matthew Judon, Michael/Mike Hall, …) and refuse
rows whose call site passes no position. It needs a first-name-variant rung
(`name_clean.is_first_name_variant`) and a no-position tiebreak — canonical-identity
semantics, so a separate authorized unit. The gap is measured every cycle as
`v2WouldChange` in `data/scrape_state/identity_dual_read.json`; the contract stamps
`identityJoin` naming the deciding owner.

Rules for new code: need identity resolution → `src/identity/resolution.py` (use
`resolve_canonical_v2` only where an explicit refusal is acceptable — it is not the
served board policy); never add consumers to `unified_mapper.resolve_player`
(legacy-V1 compat only); never define matching/normalization logic outside
`src/identity/` + the `name_clean` family registry. Full record:
`docs/identity/C1_ID_01_IDENTITY_CONSOLIDATION.md`.

### Pick identity — one owner (C1-ID-02, cut over 2026-08-16)

`src/identity/picks.py` owns draft-pick identity end to end. Two canonical
concepts, deliberately distinct: a **league pick** (owned asset — identity is
`league_key + season + round + origin franchise`, canonical id
`pick:<leagueKey>:<season>:r<N>:o<rid>`; current owner and realized slot are
STATE, so a trade or the draft order landing never mints a new asset) and a
**market pick reference** (what sources price — `mpick:<year>:r<N>[:s<slot>|:t<tier>]`
at exactly one of slot/tier/generic grades; the board's pick-row names are its
display form). A league pick *resolves to* a market ref via
`market_resolution()` — a pure function of state that takes the clock as an
argument and answers `unknown_slot` with the GENERIC grade, never a fabricated
tier or slot (the legacy "unknown → Mid" display convention survives only inside
the owner's explicitly-named legacy formatters, byte-parity-pinned).

Consumers are adapters: the contract's pick regexes/parsers, the overlay's and
scraper's ownership fold + label grammars (pickDetails now also carry an
additive canonical `assetId`, stamped only when the Sleeper id resolves to a
registry key — fail closed), draft-capital's name formatting, and the intel
crawler's `pick:<season>:<round>` strings all delegate.  That intel grade is a
PERSISTED generic-grade key whose origin collapse is documented at the owner;
re-keying it is C1-U8's migration.  The frontend's label-lookup grammar is a
deferred migration held in lockstep by
`tests/identity/test_pick_grammar_frontend_parity.py`.  Rules for new code:
never parse, compare, or mint pick identity outside the owner; identity says
WHAT the asset is — valuation stays in the pipeline.  Full record:
`docs/identity/C1_ID_02_PICK_IDENTITY.md`.

### Temporal history — one owner (C1-U4, delivered 2026-08-16)

`src/history/` owns as-of asset-value history end to end: what a historical
observation IS (`store.py` — append-only `data/temporal_ledger.sqlite`; identical
re-ingest is a no-op, conflicting re-ingest is surfaced and never applied,
corrections are explicit rows), how assets are KEYED across time (`keys.py` —
`player:<sleeperId>` / `name:<canonical>::<group>` / `mpick:*` via the C1-U2/C1-U3
identity owners; the prefixes are disjoint so players and picks cannot collide),
and what "as of T" MEANS (`asof.py` — fidelity `exact` / `nearest-prior` /
`reconstructed` (defined, never produced — no approved reconstruction methodology
exists) / `partial` / `unavailable` with machine-readable missing reasons).
**A future observation is never selectable**, structurally.  The pre-2026-07-14
gap is PERMANENT: writes earlier than `HISTORY_FLOOR` are refused and queries
answer `before_history_boundary` — never interpolated, never today's value.
Lanes keep quantities honest: `canonical_board` (served values incl. rank-less
slot picks — pick history is first-class), `source_value` (vendor-published
numbers only), `scraper_blend` (the scraper's own composite, a different named
quantity).  `rankChange` is now DERIVED from the ledger's previous board date
(read-only on every build; no comparator → `None`, never 0; rollback
`RISKIT_FEATURE_LEDGER_RANK_CHANGE=0` stamps `None`, deliberately not the retired
cache).  `data/snapshots/ranks_last.json` and its self-referential diff are
deleted.  Ingest: live recording at the fresh-scrape site in `server.py`;
`scripts/build_temporal_ledger.py` (archive backfill + legacy-store migrations,
deterministic and idempotent); `scripts/temporal_ledger_status.py` (probe).
Rules for new code: any historical/as-of read goes through `src/history` — never
interpret `rank_history.jsonl` / `source_value_history.jsonl` /
`board_history.sqlite` / `exports/archive` directly in new consumers (they remain
raw evidence and keep recording for the retention rows); never re-derive an old
value with today's curve and present it as observed.  Full record:
`docs/history/C1_U4_TEMPORAL_LEDGER.md`.

### Adapter Pattern
Pluggable source adapters (`src/adapters/base.py` defines the frozen contract). All adapters emit `RawAssetRecord` dataclasses with normalized fields.

Actual contents of `src/adapters/` (corrected 2026-07-29 audit — the
list here previously named DLF CSV / KTC stub / manual CSV adapters
that are not in the tree):

| module | status |
|---|---|
| `scraper_bridge_adapter.py` | live (`server.py`) |
| `sleeper_trending.py` | live (`server.py`) |
| `ktc_crowd_faab.py` | live (waiver/FAAB path) |
| `base.py` | the frozen contract — imported by tests only, kept as the interface definition |

Source ingestion itself lives in `Dynasty Scraper.py` + `scripts/` fetchers, not in an adapter per source.

### Position Normalization
Single source of truth: `POSITION_ALIASES` in `src/utils/name_clean.py`. All modules import from there.

### Deployment
Production runs on a VPS (currently Contabo; the deploy target is the `DEPLOY_HOST` secret, not hardcoded anywhere) with nginx reverse proxy, systemd service, and Let's Encrypt SSL. See `deploy/` directory.

## Non-Negotiable Rules

1. **Do not assume features work** — trace the live execution path end-to-end before claiming anything is implemented
2. **Prefer modifying existing architecture** over introducing parallel systems
3. **Preserve working behavior** unless a verified flaw requires change
4. **Verify downstream effects** for any value/ranking change across UI rendering, sorting, filtering, exports, and league-specific transforms
5. **Verify the full pipeline** for any scraper/source change: ingestion -> normalization -> merge -> fallback -> frontend consumption
6. **Call out anything** mocked, bypassed, stale, duplicated, half-wired, dead, or missing
7. **Smallest correct change set** — read relevant files first, identify the real live path, make minimal changes, run validation, report what changed and what remains uncertain

## Performance Rules

- Prioritize page-load speed and perceived responsiveness
- Reduce blocking work on initial load
- Eliminate duplicated calculations, repeated fetches, oversized payloads
- Prefer memoization, batching, precomputation, caching, lazy loading where justified
- Do not sacrifice correctness for speed

## Coding Conventions

### Python
- Type hints with `from __future__ import annotations`
- Dataclasses for models, Pydantic for API contracts
- `pathlib.Path` for file operations
- ISO 8601 UTC timestamps (`datetime.now(timezone.utc).isoformat()`)
- `argparse` for script CLI arguments
- Exit codes for script success/failure

### JavaScript / React
- Next.js App Router (no pages directory)
- React hooks for state management
- Named exports from modules

### General
- Configuration via JSON templates in `config/`
- Environment variables via `.env` (see `.env.example`)
- Markdown for all documentation
- Versioned API contracts (e.g., `2026-03-10.v2`)

## Environment Variables

Key variables (see `.env.example` for full list):

| Variable | Purpose | Default |
|---|---|---|
| `SLEEPER_LEAGUE_ID` | Primary Sleeper league | -- |
| `BACKEND_API_URL` | Backend origin for the Next bridge routes | `http://127.0.0.1:8000` |

`FRONTEND_RUNTIME` and `FRONTEND_URL` were removed from `server.py` with the
page proxy (#555). The backend no longer talks to Next, so Next's location is
nginx's business; `BACKEND_API_URL` is the surviving direction of that link,
read by the Next bridge routes.

## Safety

- Do not exfiltrate private data
- Do not run destructive commands without approval
- Prefer reversible operations
- Be explicit before any action affecting production, deployment, credentials, or public output
