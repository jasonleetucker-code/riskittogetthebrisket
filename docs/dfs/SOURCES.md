# DFS — sources, independence and acquisition policy

## 1. Registry

`config/dfs/source_seeds.json` preserves every owner-supplied seed verbatim: 74 websites
(Appendix A), 6 sportsbooks (B), 29 podcasts (C) — 109 entries with stable `seedId`s
(`A-001`…, `B-001`…, `C-001`…). Seeds start `accessState: "unverified"` /
`sourceCategory: "unknown"`: **a seed is a name to investigate, not an integration.**
`tests/dfs/test_source_seeds.py` pins the counts and refuses any non-`unverified` state or live
connector without recorded evidence. All three kinds are resolved (§5–7).

Resolving a seed fills: canonical identity + aliases (`aliasOf`, never deletion), official domain,
owner, sports/platforms, category, independence group, access state, acquisition method, license
assessment (collection / retention / transformation / display / training / redistribution),
cost/quota, cadence, connector state. Known duplicate names across appendices ("One Week Season"
site + podcast; DraftKings/FanDuel as books and as DFS platforms) are separate seeds by kind.

## 2. Independence

A source count is not an accuracy score. Before any source contributes to an ensemble, record its
upstream lineage and correlation group. A model sold through two storefronts is one forecast
(e.g. THE BLITZ via FantasyLabs); a host repeating a beat reporter is one report. Unknown
independence is treated conservatively (grouped).

## 3. Acquisition rules

Preferred order: official/authorized API → licensed feed → publisher export/RSS/transcript →
owner-authorized file import → permitted page acquisition within terms. Never evade paywalls,
CAPTCHA, rate limits, geo restrictions or bot prohibitions; robots.txt is not a license. No
billable trial or purchase without owner approval. On 2026-09-30 the DraftKings and FanDuel rules
pages returned 403 to automated fetch and the in-app browser refused the DraftKings domain; that
is recorded as a blocker, not worked around.

## 4. Competitor research protocol (DFS-§3)

Per observation: product, capability, sport/platform coverage, evidence URL/location, date,
access level, evidence class (`observed_hands_on` / `vendor_docs` / `vendor_marketing` /
`unverified_claim`), confidence, adoption decision (`reuse` / `implement` / `adapt` /
`experiment` / `defer` / `reject`). Never record a paywalled feature as hands-on. Time-boxed
batches of ~10 products; findings land in `docs/dfs/COMPETITOR_MATRIX.md` (created by the first
batch — nothing has been observed yet, so no matrix is published with empty claims).

## 5. Podcast resolution (2026-09-30)

All 29 podcast seeds resolved to real public RSS feeds (Apple directory lookup + direct feed fetch;
two re-verified independently): **23 available_public, 6 inactive**, 0 paywalled, 0 unresolved,
no two seeds sharing one feed. **4 feeds carry `podcast:transcript` tags** — both RotoGrinders
shows on every episode (C-009, C-010); Run Pure Sports (C-004) and Ship Chasing (C-017) only on
older episodes. Stokastic's umbrella feed (C-006) reposts its NFL/NBA/NHL feeds, so the four share
one independence group. "Theory of DFS" (C-026) is now titled "Unexpected Value". Several seeds are
season-long or betting shows rather than DFS. **Rights are unassessed for every show**: a public
feed is not permission to download, transcribe, retain or train on audio; the first acquisition
step is a terms review per show, starting with the transcript-publishing feeds (which need no
transcription at all).


## 6. Website resolution (2026-09-30)

All 74 website seeds were researched (public pages + search; search-snippet-only claims are
labelled in each entry's notes). `accessState` records **our current authorised path, not how open
the site is**: 28 paid sites are `permission_required` (no subscription is held), 25 free/freemium
sites are `manual_import_only` until a terms review is recorded, 14 stay `unverified` (pricing not
determined), 6 are `unresolved_identity` (LineupIQ, Bet The Line, Sharp AI Proptimizer, NFL Data
Edge, SportsPredict, Prediktor — owner clarification needed) and Statz.ai is `out_of_scope`
(soccer/cricket only). Licences are unassessed for every site.

- **Aliases:** numberFire (A-031) redirects into FanDuel Research (A-030) — one source.
- **Shared data → one independence group:** FantasyData + DraftDashboard (SportsDataIO data);
  THE BLITZ + EV Analytics (the same Derek Carty projections — also resold on RotoGrinders and the
  FantasyLabs marketplace, recorded in notes).
- **Shared ownership is recorded as `corporateParent`, NOT merged into one group:** Better
  Collective (RotoGrinders, FantasyLabs, Action Network), Marzen Media (FantasyPros, BettingPros),
  Gambling.com Group (RotoWire, OddsJam), FanDuel. Two models under one parent are still two
  models unless evidence shows shared inputs.
- **Documented public APIs** (`acquisitionMethod: api_candidate`, terms and keys still required):
  DailyAmbush, Diamond DFS, PFF, Opta, Unabated, OddsJam. **12** sites document a CSV export
  (`owner_csv_export` — the owner exports from their own account and imports the file).

## 7. Sportsbook resolution (2026-09-30)

All 6 books are `permission_required` with `acquisitionMethod: licensed_aggregator_candidate`.
None publishes a public odds API. The terms we could read (FanDuel general terms; Caesars NV;
Hard Rock) bar automated access, scraping, or betting bots; DraftKings and bet365 terms returned
403 and are recorded from search snippets only; BetMGM's sportsbook terms URL 404'd and needs a
human to locate. Odds can reach ChaseUpside only through a licensed aggregator the owner approves.
Aggregators documented as carrying these books: The Odds API (all but US bet365), OpticOdds
(most), SportsDataIO (search-snippet-only). Each book is its own independence group: books price
independently even where they share a parent. DraftKings and FanDuel are the same companies as
the DFS platforms; that is recorded as `corporateParent`, not as a data dependency.

## 8. Classification by data type, access and point-in-time usefulness (DFS-MOD-12, 2026-09-30)

"Connected" means a working adapter with a recorded successful pull. Everything else is research.

| Data type | Connected today | Researched, not connected (why) | PIT usefulness |
|---|---|---|---|
| Salaries / roster eligibility | **Automatic (NFL, NBA, NHL × DK+FD):** Daily Fantasy Fuel pages via `src/dfs/auto` (DFS-AUTO-03/19); official DK/FD salary CSVs (owner upload, *Advanced*) | SportsDataIO DFS slates (paid; key not provisioned; flag OFF) — the only path to platform player ids | High — recorded with the page's own publish stamp |
| Projections | Owner CSV import; **Daily Fantasy Fuel** (`src/dfs/sources_dff.py`, NFL/NBA/NHL, DK/FD) | Free/freemium pages (CeeGeeDFS, Fantasy Team Advice CSV, DraftEdge, RotoBaller…), paid (RotoGrinders, FantasyLabs, Stokastic, SaberSim, ETR…) — not yet adapted | Only as fetched: recorded at fetch time |
| Ownership (projected) | Owner CSV import | CeeGeeDFS (free), Fantasy Team Advice (freemium CSV), paid ownership (RotoGrinders pOWN, FantasyLabs, Stokastic, SaberSim) | Critical input; realized ownership comes from standings |
| Betting lines / game environment | **Daily Fantasy Fuel** page context (spread, over/under, implied team total) | Licensed odds APIs (The Odds API, OpticOdds/OddsJam, SportsDataIO) — paid, owner approval; books' own sites barred by terms | High for ownership features; recorded at fetch time |
| Player props | — | Odds aggregators (paid), PropsCash/Outlier-type tools (paid) | Later (projection ensembles) |
| Injuries / news / starting status | DK file status + DFF injury flag | Team/league reports, SportsDataIO news (paid) | High but fast-moving: needs frequent timestamps |
| Contest results / realized ownership | Owner-uploaded DK standings; canonical results format (any platform) | No verified FanDuel standings export | The truth side — never an input before lock |
| Weather | — | Not researched yet (NFL only) | Medium (NFL kickers/passing) |
| Historical data | Accumulates from owner imports + pulls going forward | Paid historical DFS databases (not researched for price) | Needed for any real backtest |

**Paid data that would materially change what is possible** (nothing purchased; prices NOT verified):
- **A licensed odds feed** (e.g. The Odds API — public tiered pricing exists; OpticOdds — sales contact):
  closing/pre-lock lines, totals and player props for every sport. Unlocks: better ownership features,
  prop-derived projections, a second independent projection signal. Free alternative today: DFF's
  page context (spread / total / implied), NFL/NBA/NHL only.
- **A paid projection + ownership source with history** (e.g. RotoGrinders, FantasyLabs, Stokastic): the
  one thing a backtest cannot conjure — historical PRE-LOCK ownership forecasts to score against
  realized ownership. Free alternative: start recording DFF + owner imports now, so history accrues.
- **SportsDataIO DFS slates** (adapter built, flag OFF): automatic slate loading. Free alternative:
  official CSV upload (works today).

## 9. Provider matrix for the zero-upload workflow (DFS-AUTO-21, 2026-09-30)

States: **FREE** (no cost, permitted path in use or usable), **ALREADY AVAILABLE** (a Calculator owner
already collects it), **PAID** (needs a subscription — owner approval, nothing purchased), **UNKNOWN**
(terms or coverage unresolved → research-only), **NOT PERMITTED** (terms, robots, login or private
endpoints bar it).

| Data | Source | State | Used by `/dfs` today | Notes |
|---|---|---|---|---|
| NFL schedule, kickoff, lock | nflverse (`nfl_data.ingest`) | ALREADY AVAILABLE | yes | per-season file 404s, the combined `games.csv` rung answers (pre-existing `url_stale` warning) |
| NFL DK/FD pool, salary, position | Daily Fantasy Fuel (A-020) | FREE (owner-authorised) | yes | week pool; slate windows derived; no platform ids |
| NBA/NHL DK/FD pool, salary, position(s) | Daily Fantasy Fuel (A-020) | FREE (owner-authorised) | built (DFS-AUTO-19); waits on the schedule-source decision | the one dated slate each page lists; robots re-checked 2026-10-07 (`/lineup/*` only) |
| NBA/NHL schedule, start time, lock | ESPN public scoreboard (`src/dfs/auto/league_schedule.py`) | PENDING OWNER DECISION (possible expansion of the owner-attested ESPN integration; ADR-DFS-025, `config/dfs/auto_sources.json`) | built, gated off | no key; 30-min cache; preseason / postponed / invalid-time events dropped |
| NHL projected lines (EV / PP), goalie starter flag | Daily Fantasy Fuel (A-020) | FREE (owner-authorised) | evidence only | carried on the athlete; not yet a stack constraint or correlation input |
| NBA/NHL player directory (cross-provider identity) | — | UNKNOWN | no | athletes are provider-scoped (`athlete:<sport>:dailyfantasyfuel:<id>`, DFS-§9-03) |
| NBA/NHL second projection family | — | UNKNOWN / PAID | no | DFF is the only family; no ensemble |
| MMA pool, salary | — | UNKNOWN | no (DFS-AUTO-20) | no permitted source found |
| DK/FD platform player ids, official slate lists | SportsDataIO DFS slates | PAID | no (DFS-AUTO-18) | adapter built, flag OFF |
| DK/FD platform player ids, slate lists | DraftKings / FanDuel lobbies or private JSON | NOT PERMITTED | never | owner constraint |
| NFL projections (stat lines, rescored) | Sleeper weekly (RotoWire model) | ALREADY AVAILABLE | yes | flag `sleeper_weekly_projections` |
| NFL projections (fantasy points) | Daily Fantasy Fuel | FREE (owner-authorised) | yes | "hand-cut in-house" (site's claim) |
| Projections (keyed) | SportsDataIO / Fantasy Nerds weekly | PAID | no | Calculator lanes exist, flags off |
| Projections, starting lineups | RotoGrinders (A-001) | FREE for login-free pages (owner permission) / PAID for premium | no (DFS-AUTO-22) | projections render client-side; CSV premium; `/lineups/*` server-rendered |
| Injury status | Sleeper directory; DFF flag | ALREADY AVAILABLE / FREE | yes | Out/IR withheld |
| Game lines (spread / total) | DFF page context; nflverse | FREE / ALREADY AVAILABLE | context only | never a projection input |
| Player props, live odds | licensed aggregators (The Odds API, OpticOdds, SportsDataIO) | PAID | no (DFS-AUTO-12) | books' own sites barred by terms |
| Ownership projections | CeeGeeDFS, Fantasy Team Advice; paid (RotoGrinders pOWN, FantasyLabs, Stokastic) | UNKNOWN / PAID | no | structural baseline + field-implied challenger instead |
