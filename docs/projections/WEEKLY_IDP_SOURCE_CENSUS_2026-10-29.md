# Weekly IDP projection source census — 2026-10-29

Owner directive: `docs/owner/IDP_STREAMING_DIRECTIVE_2026-10-29.md` (IST-1, scraping
attestation, decision 4). Question per source: are **weekly IDP stat-line projections**
(not just fantasy points or ranks) reachable without a paywall, or with a session the repo
already holds? Probes were read-only, 1–3 requests per source, at least 1 s apart (5 s for
FantasyPros per its `Crawl-delay`), with the repo's weekly-projection User-Agent. No paywall
was bypassed, no credential was used, nothing was purchased.

Machine-readable entries live in `config/projections/source_capability_census.json`; this file
is the narrative record of the probes.

## Verdict summary

| Source | Access path probed | Weekly IDP stat lines? | Verdict |
|---|---|---|---|
| **Sleeper (RotoWire model)** | `api.sleeper.app/projections/nfl/<season>/<week>` (existing, flag ON) | **Yes** — solo, ast, TFL, sack, sack yd, QB hit, PD, INT, INT ret yd, FF, FR, safety; current **and future** weeks | **LIVE** (existing `sleeperWeeklyProjections`) |
| **FPTrack** | public catalog JSON `fptrack.com/api/sports-v2/projections/football/week?v=5&week=N` | **Yes** — solo, ast, sack, PD, INT, FF, INT-TD + FR-TD; TFL is a 0 placeholder, FR / safeties null; current week only | **Adapter built**, flag `fptrack_weekly_projections` default OFF; **RotoWire constituent** → coverage filler, never a second vote |
| FantasyPros | `/nfl/projections/{dl,lb,db}.php?week=N` | Stat columns exist (TACKLE, ASSIST, SACK, PD, INT, FF, FR, TD) but only **10 rows** are server-rendered (LB wk 8); DB wk 9 had 0 rows; the rest load from `/api/`, which robots.txt disallows; the official API is a paid product | Not viable (truncated public page; full data only via disallowed/paid API). TACKLE semantics also ambiguous (7.3 vs RotoWire solo 4.46 / total 8.59) |
| FFToday | `/rankings/playerwkproj.php?PosID=50/60/70` | **No** — the projections menu lists QB/RB/WR/TE/K only; the LB page renders no rows; IDP exists only as rankings | Not viable |
| Fleaflicker | `/api/FetchPlayerListing` | Needs a `league_id`; robots.txt disallows `/api/` and league player pages | Not pursued |
| IDP Guru | weekly rankings article | Paywalled ($19.99 in-season); weekly content is **rankings**, projections are a preseason workbook | Not viable |
| MyFantasyLeague | `api.myfantasyleague.com/<yr>/export?TYPE=projectedScores` | Requires a league id; returns **points** under that league's scoring, no stat lines | Not viable (points-only) |
| IDP Start/Sit | page script → Google Apps Script JSON | 227 rows of **points** under six preset scorings (Big 3, FantasyPros, D-UP, Footballguys, ESPN, Sleeper); no stat line, no week field | Not viable (points-only; 6 linear equations cannot recover 9 stat categories) |
| RotoWire (direct) | `/football/projections.php?type=weekly&pos=LB` | Subscription required | Not viable; also the SAME family as the Sleeper source |
| Footballguys | `/projections?pos=lb&week=N` | Subscriber-only | Not viable |
| Razzball | `/pigskinonator-idp/` (Weekly IDP projections) | "Membership Required" | Not viable |
| FantasyData | `/nfl/fantasy-football-idp-projections` | 3 free rows then "SIGN UP TO SEE MORE"; season scope by default | Not viable (paywall); same company as SportsDataIO |
| SportsDataIO | keyed API (existing adapter) | Yes, but needs `SPORTSDATAIO_API_KEY` — none installed | Unavailable (no key) — existing `IMPLEMENTED_FLAG_OFF` |
| FantasyNerds | keyed API (existing adapter) | Points + some stats; needs `FANTASYNERDS_API_KEY` — none installed | Unavailable (no key); a consensus family that includes RotoWire |
| Draft Sharks | `/weekly-rankings/idp` (public) | Public page: 26 rows of **points** (floor / consensus / DS / ceiling / 3D); stat columns may appear with the owner's session ("research depth"), which lives only on the production box | Deferred — verify with the wired session on the box; not testable here |
| The IDP Show | Substack archive API | Paid weekly projection posts existed in **2025** (weeks 5–18); none found for 2026 on 2026-10-29; the session lives only on the production box | Deferred — no 2026 weekly post to parse |
| LineupExperts | `/fantasy-football/idp-rankings` | HTTP 403 (bot protection) | Not pursued — no evasion |
| DataForce | homepage | HTTP 403 | Not pursued — no evasion |
| NBC Sports / Rotoworld | `/fantasy/football/projections` | 404; no IDP projection product found | Not viable |
| Mike Woellert (Every-Down IDP) | candidate domains | No reachable publication found (proxy 502 / 404) | Not found |

## FPTrack — details

* **Endpoint**: `GET https://fptrack.com/api/sports-v2/projections/football/week?v=5&week=<N>`
  (the `catalogUrl` the public `/football/weekly-projection-rankings` page loads). No
  authentication. `robots.txt`: `User-agent: * / Allow: /`, `Content-Signal:
  search=yes,ai-train=no,use=reference` — no AI-training use is made.
* **Coverage (week 8, fetched 2026-10-29 ~09:08 UTC)**: 1,105 players — DL 231, LB 170, DB 248,
  WR 148, TE 101, RB 93, QB 57, K 29, DEF (team) 28. `week=9` the same morning returned an
  empty `players` list; `availableWeeks` was `[1..8]` — **no future weeks**.
* **IDP fields**: `tackles` (SOLO — see below), `assists`, `tacklesForLoss` (**0 on all 649 IDP
  rows → placeholder**, treated as unpublished/uncovered), `passesDefended`, `sacks`,
  `defInterceptions`, `forcedFumbles`, `fumbleRecoveries` (null), `interceptionTouchdowns` +
  `fumbleRecoveryTouchdowns` (summed to `idp_def_td`), `safeties` (null on IDP rows). No QB
  hits, sack yards, return yards or blocked kicks.
* **Freshness**: payload `asOf` was the epoch placeholder and `generatedAt` is render time;
  rows carry no provider update stamp, so none is claimed.
* **Ancestry / independence**: joined on name + team, 583 IDP players: `tackles` vs RotoWire
  `idp_tkl_solo` median difference 0.04, 41% identical after rounding to one decimal, 65%
  within 0.15; `assists` vs `idp_tkl_ast` likewise. That is shared data lineage, so the
  census declares `rotowire` a constituent family: FPTrack **never votes beside** the Sleeper
  source; it fills players RotoWire did not project (28 IDP players in week 8).
* **Identity**: FPTrack ids are its own. Rows resolve to Sleeper ids through
  `src/identity/resolution.resolve_canonical_v2` with **exact-rung** answers only, corroborated
  by team; a collision (two rows → one Sleeper id) refuses both. Week 8: 1,021 resolved, 56
  refused unresolved, 28 team-defense rows refused.

## Sleeper / RotoWire — IDP quality notes (existing live source)

* Week 8 (2026-10-29): 1,129 IDP rows carry a game id; 657 carry a real stat line, the rest
  are placeholders (only `adp_dd_ppr`) and are reported unprojected, never zero.
  Week 9 (published the same day): DL 346, LB 167, DB 308 projected.
* Published IDP keys: `idp_tkl`, `idp_tkl_solo`, `idp_tkl_ast`, `idp_tkl_loss`, `idp_sack`,
  `idp_sack_yd`, `idp_qb_hit`, `idp_pass_def`, `idp_int`, `idp_int_ret_yd`, `idp_ff`,
  `idp_fum_rec`, `idp_fum_ret_yd`, `idp_safe`, plus `def_pr_yd` / `def_pr_td` and defensive TDs
  under `pass_int_td` / `def_fum_td`.
* `dynasty_main` pays `idp_def_td` (6.36), `idp_blk_kick` and the special-teams keys
  (`st_tkl_solo`, `st_ff`, `st_fum_rec`, `st_td`, `kr_yd`); RotoWire publishes none of those
  keys for IDP players, so they are reported **uncovered** on every IDP projection. Whether
  RotoWire's `pass_int_td` / `def_fum_td` on defenders should be read as `idp_def_td` is a
  mapping decision for the Sleeper source owner (not made here).

## Not done here, and why

* No adapter for FantasyPros: the public page is truncated to ~10 rows and the full data is
  behind a robots-disallowed endpoint / paid API.
* No adapter for Draft Sharks or The IDP Show weekly projections: their sessions live only on
  the production box, and no 2026 IDP Show weekly projection post exists to fix a schema.
* No key-dependent source was activated (SportsDataIO, FantasyNerds: no keys).
