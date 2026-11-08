# 02. Data source and licensing matrix

**Status:** research only, 2026-11-08. All terms below were read from the linked page on 2026-11-08 unless a row says otherwise. **This is an engineering summary, not legal advice.** Counsel should review anything that reaches production. One organization's datasets do not share one license; rows are split wherever upstreams differ.

**Rating key for machine-learning use:** GREEN = page permits it or states open data. AMBER = allowed only with a condition, or the page is silent. AMBER+ = open license stated, but the rights of the upstream provider are not addressed. RED = page prohibits it. Code licenses are separate from data licenses: `nflreadr` and `nflreadpy` are MIT, and that says nothing about the data they fetch.

**Owner fact needed:** I found no monetization record in `docs/MASTER_PRODUCT_PLAN.md`. Several AMBER rows depend on whether Chase Upside counts as commercial use. The owner must state this.

## A. Rights

| id | dataset | upstream | stated terms | commercial | attribution | redistribution | ML training | cost | rating |
|---|---|---|---|---|---|---|---|---|---|
| D01 | nflverse play-by-play | NFL game feeds, via nflverse | Repo CC-BY-4.0; nflverse says most data is CC-BY 4.0 except FTN | Allowed by CC-BY | Required | Allowed with attribution | Not addressed; CC-BY has no field-of-use limit | $0 | AMBER+: NFL's own rights not addressed by nflverse |
| D02 | nflverse weekly player stats (`stats_player_week`) | NFL box scores | As D01 | As D01 | Required | As D01 | As D01 | $0 | AMBER+ |
| D03 | nflverse schedules / `games.csv` (spread, total, moneylines, weather, roof) | Odds and weather source unstated | As D01 | As D01 | Required | As D01 | As D01 | $0 | AMBER: **odds source not stated** |
| D04 | nflverse snap counts | **Pro Football Reference** | CC-BY claim on repo; PFR terms below still govern the upstream | Unclear | Required | Unclear | **PFR bars ML use** | $0 | **RED for training** `[I]` |
| D05 | nflverse PFR advanced stats | **PFR** | As D04 | Unclear | Required | Unclear | PFR bars ML use | $0 | **RED for training** `[I]` |
| D06 | nflverse NGS weekly | NFL Next Gen Stats | As D01; NFL terms below | Unclear | Required | Unclear | NFL silent; bars systematic retrieval without consent | $0 | AMBER |
| D07 | nflverse participation | NGS to 2022; **FTN 2023+** | **CC-BY-SA 4.0** | Allowed with share-alike | "FTN Data via nflverse" or "NFL NextGenStats via nflverse" | Share-alike | Not addressed; share-alike may reach published derivatives | $0 | AMBER |
| D08 | nflverse FTN charting | FTN | **CC-BY-SA 4.0** | As D07 | "FTN Data via nflverse" | Share-alike | As D07 | $0 | AMBER |
| D09 | nflverse injuries | "an API"; source unstated | As D01 | Unclear | Required | Unclear | Unclear | $0 | AMBER |
| D10 | nflverse depth charts | Unstated | As D01 | Unclear | Required | Unclear | Unclear | $0 | AMBER |
| D11 | nflverse players, rosters, contracts, draft picks, combine | Mixed; **draft and combine from PFR**, contracts from OverTheCap | As D01, upstream differs per file | Varies | Required | Varies | PFR files RED, others AMBER | $0 | Split per file |
| D12 | ffopportunity expected points | Built on nflverse | Code GPL-3; **models and data CC-BY-SA 4.0** | Share-alike | Required | Share-alike | Not addressed | $0 | AMBER |
| D13 | DynastyProcess data | FantasyPros ECR (`db_fpecr`), others | Repo GPL-3.0 per GitHub sidebar; license file not fetched | Unclear for data | Not stated | Unclear; FantasyPros upstream | Unclear | $0 | AMBER |
| D14 | Pro Football Reference direct | Sports Reference | Terms and data-use page bar automated access without permission and bar AI training, including models that predict, classify or score. Competing database barred. Facts may be reused. | Credited sharing welcomed, not database building | Credit | Limited | **Prohibited** | Custom data from $5,000 | **RED** |
| D15 | NFL.com, NGS site, official injury report | NFL | Personal non-commercial use; systematic retrieval needs written consent; automated collection for commercial purposes barred | Needs permission | n/a | Barred | Silent; retrieval limits apply | n/a | **RED for scraping** |
| D16 | CollegeFootballData API | CFBD | Terms effective 2026-08-12: commercial use permitted; **model training, feature engineering and backtesting permitted**; raw bulk republication barred; models and weights may be commercialized | **Yes** | Recommended, not required | Raw data barred | **Permitted** | Free 1,000 calls/mo; Tier 1 $1, up to Tier 6 $30 | **GREEN** |
| D17 | Sports Reference CFB direct | Sports Reference | Same as D14 | As D14 | As D14 | As D14 | Prohibited | n/a | **RED** |
| D18 | Sleeper documented API | Sleeper | Docs: read-only, no auth, keep under 1,000 calls/min; commercial use needs a licensing conversation. App terms limit license to personal non-commercial use | **Contact Sleeper** | Required for trending data | Barred in app terms | Not addressed in the part read | $0 | AMBER |
| D19 | Sleeper weekly projections (undocumented) | RotoWire via Sleeper | Not in public docs. Census: `OWNER_ATTESTED_AUTHORIZED` | Per owner attestation | n/a | Unknown | Unknown | $0 | AMBER: owner attestation, no public terms |
| D20 | ESPN scoreboard, injuries, depth charts; Clay PDF | Disney | Personal non-commercial; automated extraction barred except search indexing; **AI training barred** | Barred without license | n/a | Barred | **Prohibited** | n/a | **RED** |
| D21 | SportsDataIO | Vendor | Website terms bar copying and scrapers. Licensing help: feeds go under client agreements; **ML and statistical use allowed subject to use case and feeds**; no resale as a data product; personal projects use a separate lab | Under license | Per agreement | No resale | Allowed under license | Quote only | AMBER: needs contract |
| D22 | FTN Data direct | FTN | Terms page returned HTTP 403 | Unverified | Unverified | Unverified | Unverified | $599 / $5,000, undated | UNVERIFIED |
| D23 | PFF | PFF | Paid API tier for personal use only; commercial use, public redistribution, competing products, scraping and AI training or evaluation barred, with a narrow allowance for personal local models | **Barred** | n/a | Barred | **Prohibited** | Paid | **RED** |
| D24 | FantasyPros API | FantasyPros | Free non-production; $8.99/mo personal and non-commercial; commercial plan custom with redistribution rights. Terms PDF could not be parsed this session | Commercial plan | Unverified | Commercial plan | Unverified | $0 / $8.99 / custom | AMBER |
| D25 | Fantasy Nerds API | Vendor | API data allowed in commercial apps under API terms; reselling or sublicensing needs approval; caching recommended; site scraping restricted | Yes, via API terms | Unverified | Needs approval | Not addressed | Not shown; third-party listing $74.95/yr (unverified) | AMBER |
| D26 | The Odds API (game odds, props, historical) | Sportsbooks | Commercial display allowed if data is not the main product; no resale, feeds or files; **training statistical and ML models listed as permitted** | Yes | Not required | Barred as product | **Permitted** | Free 500 credits; $30, $59, $119, $249/mo | **GREEN** |
| D27 | National Weather Service API | US government | Described as open data, free for any purpose; no named license; User-Agent required | Yes | Not required | Yes | Yes | $0 | **GREEN** |
| D28 | Open-Meteo | Vendor | Data CC-BY 4.0; free tier non-commercial only, 10,000 calls/day; commercial needs paid plan | Paid plan | Required | CC-BY | Allowed under CC-BY | Free / paid | GREEN if the plan matches |

## B. Content, freshness and value

| id | fields | years | NFL / college / IDP | cadence and PIT notes | access | reliability | expected incremental value `[I]` |
|---|---|---|---|---|---|---|---|
| D01 | Play-level EPA, air yards, YAC, tacklers, first downs | 1999+ | NFL, IDP via play events | Nightly; Thursday pull cleanest after stat corrections. **Revises** (repo measured week 1-6 rows change: `docs/league-intelligence/SCORING_PARITY_TAXONOMY_2026-11-08.md` §1) | GitHub release CSV | High | **High.** Backbone for shares and expected stats |
| D02 | Offense and defense box scores | Long (per pbp era) | NFL, IDP | Nightly; revises | GitHub | High; repo found four scorer defects on this path | **High** |
| D03 | `spread_line`, `total_line`, moneylines, `temp`, `wind`, `roof`, `surface` | Long | NFL | Pre-game; whether the line is opening or closing not stated | GitHub | Medium: provenance unknown | **High** if lines are PIT-valid; check before use |
| D04 | Offense, defense, ST snap share | 2012+ | NFL, IDP | Every 6 h; needs PFR post | GitHub | High | **High** value but rights-blocked for training |
| D05 | Pressures, targets allowed, broken tackles | 2018+ | NFL, IDP | Weekly or season | GitHub | Medium | Medium; rights-blocked for training |
| D06 | CPOE, separation, RYOE | 2016+ | NFL offense | Nightly | GitHub | Medium; PIT-safe after game | Medium |
| D07 | `route`, coverage, `was_pressure`, `defense_players` | 2016+ | NFL, IDP | **2023+ only after the postseason**, so unusable in-season | GitHub | Medium | Medium for training, zero for live |
| D08 | Motion, play action, blitzers, box count, created receptions | 2022+ | NFL | 6-hourly; repo measured lag from 47.5 days early to about 2 days later (`IDP_OPPORTUNITY_CHALLENGERS_RESULTS`) | GitHub | Medium | Low to medium |
| D09 | Report status, practice status | 2009+ | NFL, IDP | Daily; file **not timestamped**, so PIT unverified `[R]` | GitHub | Medium | Medium for training with a label caveat |
| D10 | Weekly depth slot | 2001+ | NFL, IDP | Weekly; freshness of a row needs per-season check | GitHub | Medium | Medium |
| D11 | Identity, draft slot, age, contracts, combine | 2000+ combine | NFL, IDP | Slow | GitHub | High | **High** for rookies and survival |
| D12 | Expected yards, TDs, fantasy points per play | About 2006+ | NFL offense | Automated | GitHub | Medium; generic scoring | Medium as a baseline |
| D13 | Player IDs; FantasyPros ECR history; values | Archive depth unverified | NFL, IDP (ID only) | Weekly | GitHub | Medium | **High** as the only cheap PIT consensus rank archive, if rights clear |
| D14 | Everything PFR | Long | NFL | Daily | Barred | High | Not usable |
| D15 | Official reports, NGS pages | Current | NFL | Live | Barred | High | Not usable by scraping |
| D16 | College games, drives, plays, players, usage, returning production, ratings | Multi-decade (exact depth not verified) | College, no IDP focus | Live tiers | API key | Community-run; high usage | **High** for rookies; the licensing is unusually clean |
| D17 | CFB box scores | Long | College | Daily | Barred | High | Not usable |
| D18 | Rosters, matchups, weekly stats, players | Multi-season | NFL, IDP | Hours after games | Public HTTP | High; host truth for scoring | **High**, already the scoring truth |
| D19 | Weekly stat-line projections | Archive starts 2026 week 8 `[R]` | NFL, IDP (partial) | Multiple per week; `lock_baseline_at_kickoff` | Undocumented endpoint | Medium; one model family | **High** as current consensus proxy |
| D20 | Injuries, depth, scoreboard; Clay preseason | Live only for injuries | NFL, IDP via Clay | Live | Public endpoint | High | Medium; rights problem |
| D21 | Projections, IDP, depth, injuries, odds, props | Not stated in the part read | NFL, IDP | Minutes | Keyed | High claimed; no backtests found | Medium to high as a second independent family |
| D22 | Charting | 2019+ per page | NFL | Unknown | Paid | Unknown | Low: free route exists |
| D23 | Grades, charting | Long | NFL, IDP, college | Paid | Barred for our use | High | Not usable |
| D24 | Projections, ECR, ADP, injuries | Historical on commercial tier | NFL, IDP | Frequent | Keyed | Medium to high | **High** as a consensus family, license gate |
| D25 | Weekly stat projections, IDP | Unknown | NFL, IDP | Weekly | Keyed | Unknown | Medium: adapter exists, flag OFF |
| D26 | Game odds, props | Game odds from 2020-06-06 (10-min, 5-min after Sep 2022); **props from 2023-05-03** | NFL | 5-minute snapshots | Keyed | High for prices | **High** for team totals and PIT market baselines; props sample is short |
| D27 | Forecast, station obs | Observations keep only 7 days | US | Hourly | Public | High | Low to medium; no archive, so capture forward or use NCEI |
| D28 | Hourly history and forecast | Multi-decade (not verified here) | Global | Hourly | Public API | Medium | Low to medium |

## C. Findings

| # | finding | evidence | required action |
|---|---|---|---|
| 1 | **PFR rights flow into nflverse snap counts, advanced stats, draft picks and combine.** The CC-BY label on the nflverse repo cannot grant rights nflverse does not hold `[I]` | Snap counts source: `load_snap_counts` doc. PFR terms bar AI use including predictive scoring | Do not train on D04, D05, or PFR-derived D11 without permission or counsel. Consumers exist today: `src/nfl_data/nflverse_direct.py`, `src/playerctx/fetch.py`, `src/bdvm/context.py`. Owner decision |
| 2 | **ESPN inputs are live while Disney terms bar automated extraction and AI training** | `src/nfl_data/injury_feed.py`, `live_game_state.py`, `depth_charts.py`; `src/bdvm/clay_projections.py`. Census posture `PUBLIC_NO_AUTH`, `licensingStatus` null | Public availability is not a license. Record an owner decision. Do not use Clay rows as training labels until resolved |
| 3 | **Sleeper's documented API asks commercial users to contact it**; the projections endpoint is undocumented | https://docs.sleeper.com/ ; `config/projections/source_capability_census.json` | Record the owner attestation's basis; contact Sleeper if the site is commercial |
| 4 | **CC-BY requires attribution on every surface that uses the data** | Six frontend files mention nflverse (`DataInfoBody.jsx`, `GameDayHelp.jsx`, `PlayerPopup.jsx`, `game-day-view.js`, two in `league-comparison`) | Audit whether the BDVM, rankings and waiver surfaces carry it |
| 5 | **FTN and ffopportunity are share-alike** | `load_participation`, `load_ftn_charting`, ffopportunity pages | Research use only. Before publishing outputs built on them, get counsel on whether an adaptation exists |
| 6 | **PFF is not a usable input** under standard terms | PFF terms | Remove from candidates unless an enterprise contract exists |
| 7 | **The clean path exists and is cheap**: D01-D03 for NFL, D16 for college, D26 for prices, D27/D28 for weather | Rows above | Prefer these. A paid feed is justified only by demonstrated gap (`docs/PROJECTION_ENSEMBLE_PLAN_2026-08-15.md`) |
| 8 | **A partial fallback for defensive snap share exists** | Sleeper stat lines carry `def_snp` and `tm_def_snp` (`docs/projections/IDP_OPPORTUNITY_CHALLENGERS_RESULTS_2026-11-01.md`), subject to finding 3. Offensive equivalents were not verified. D07 covers offseason training only | Evaluate before any model depends on D04 |

## D. Primary pages read on 2026-11-08

| source | URL |
|---|---|
| nflverse data repo | https://github.com/nflverse/nflverse-data |
| nflreadpy license note | https://github.com/nflverse/nflreadpy |
| nflreadr MIT | https://nflreadr.nflverse.com/LICENSE.html |
| Update schedule | https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html |
| Snap counts | https://nflreadr.nflverse.com/reference/load_snap_counts.html |
| NGS | https://nflreadr.nflverse.com/reference/load_nextgen_stats.html |
| Participation | https://nflreadr.nflverse.com/reference/load_participation.html |
| Participation fields | https://nflreadr.nflverse.com/articles/dictionary_participation.html |
| FTN charting fields | https://nflreadr.nflverse.com/articles/dictionary_ftn_charting.html |
| FTN charting license | https://search.r-project.org/CRAN/refmans/nflreadr/html/load_ftn_charting.html |
| Injuries | https://nflreadr.nflverse.com/reference/load_injuries.html |
| Depth charts | https://nflreadr.nflverse.com/reference/load_depth_charts.html |
| PBP | https://nflreadr.nflverse.com/reference/load_pbp.html |
| Player stats | https://nflreadr.nflverse.com/reference/load_player_stats.html |
| Combine | https://nflreadr.nflverse.com/reference/load_combine.html |
| PFR advanced | https://nflreadr.nflverse.com/reference/load_pfr_advstats.html |
| FF opportunity | https://nflreadr.nflverse.com/reference/load_ff_opportunity.html |
| FF rankings | https://nflreadr.nflverse.com/reference/load_ff_rankings.html |
| Schedule fields | https://raw.githubusercontent.com/nflverse/nflreadr/main/data-raw/dictionary_schedules.csv |
| nfldata games notes | https://github.com/nflverse/nfldata/blob/master/DATASETS.md |
| ffopportunity | https://ffopportunity.ffverse.com/ |
| DynastyProcess | https://github.com/dynastyprocess/data |
| Sports Reference data use | https://www.sports-reference.com/data_use.html |
| Sports Reference terms | https://www.sports-reference.com/termsofuse.html |
| NFL terms | https://www.nfl.com/legal/terms/ |
| CFBD terms | https://collegefootballdata.com/terms |
| CFBD tiers | https://collegefootballdata.com/api-tiers |
| Sleeper API | https://docs.sleeper.com/ |
| Sleeper terms (first 100k chars read) | https://support.sleeper.com/en/articles/5486620-terms-of-use |
| Disney terms | https://disneytermsofuse.com/english/ |
| SportsDataIO terms | https://sportsdata.io/terms-of-service |
| SportsDataIO licensing | https://sportsdata.io/help/data-rights-and-licensing-questions |
| FTN data | https://ftnfantasy.com/data |
| PFF terms | https://www.pff.com/terms |
| FantasyPros API | https://www.fantasypros.com/api-data/ |
| Fantasy Nerds terms | https://www.fantasynerds.com/terms |
| Fantasy Nerds FAQ | https://api.fantasynerds.com/getting-started/faq |
| Odds API terms | https://the-odds-api.com/terms-and-conditions.html |
| Odds API history | https://the-odds-api.com/historical-odds-data/ |
| Odds API tiers | https://the-odds-api.com/#get-access |
| Open-Meteo terms | https://open-meteo.com/en/terms |
| NWS API | https://www.weather.gov/documentation/services-web-api |

**Could not verify:** FTN terms (HTTP 403); FantasyPros API terms PDF (returned, not parseable); FantasyPros support article (HTTP 403); Sleeper terms past 100,000 characters; CFBD history depth; Open-Meteo history depth; DynastyProcess ECR archive depth; whether nflverse lines are opening or closing.
