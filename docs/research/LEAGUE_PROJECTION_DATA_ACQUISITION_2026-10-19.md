# Projection and advanced-data acquisition research — 2026-10-19

**Status:** first verified research census; NOT a claim that all 14 sources have production authorization or that they improve holdout accuracy. The existing registry is `config/projections/source_capability_census.json`; changes to ingestion authorization belong there only after verification. **Rankings and fantasy-point totals must not be misclassified as raw-stat projections.**

## A. Source inventory and decision

| Provider / source | Verified potential data | Repo posture observed | Acquisition / licensing verification | Decision |
|---|---|---|---|---|
| Sleeper | Weekly player projections and league host scoring context | `sleeperWeeklyProjections` = LIVE, feeds Game Day, not fixed preseason ensemble | Existing repo implementation; host endpoint must be available at runtime | **Evaluate actual score-category coverage/freshness first** |
| Fantasy Nerds | Weekly **stat-category** projections, IDP weekly projections, ROS skill+IDP stat categories, injuries/depth | Weekly adapter = `IMPLEMENTED_FLAG_OFF` | Official API: https://api.fantasynerds.com/docs/nfl ; keyed access; FAQ recommends caching and supports TEST examples | **P1: test pre-existing adapter, credential and field coverage** |
| SportsDataIO | Weekly and season-long player projections; **weekly IDP player projections**; extensive box score and depth | Weekly adapter = `IMPLEMENTED_FLAG_OFF` | Official: https://sportsdata.io/developers/api-documentation/nfl and https://sportsdata.io/developers/coverages/nfl ; keyed subscription and commercial rights require account review | **P1: verify activation and actual raw fields** |
| ESPN / Mike Clay | Preseason full-season projections from repository's Clay records | `clayProjections` = LIVE / preseason | Repo census labels LIVE; **do not assume weekly or ROS coverage** or blanket redistribution rights | **Reuse; add as-of/independence/coverage evaluation** |
| The IDP Show | Existing preseason full-season IDP projection records | `idpShowProjections` = LIVE / preseason | Repo census also marks subscription scope unrecorded: production automation/redistribution rights unresolved | **Reuse locally as permitted; document permission boundary** |
| FantasyPros | NFL weekly/ROS full-stat projections, player metadata | Projection source = GREENFIELD, ROS ranks currently separate RANKINGS_ONLY | Official API https://www.fantasypros.com/api-data/ ; https://support.fantasypros.com/hc/en-us/articles/49749297704475-How-do-I-request-access-to-the-FantasyPros-API ; free prototype, premium personal/noncommercial, commercial separate; no competing products under standard API terms | **High-priority conditional; licensing gate before public site** |
| DraftSharks | ROS IDP ranks; website has explicit Rankings / Projections modes | Current offense and IDP ROS entries marked LIVE_BUT_RANKINGS_ONLY | https://www.draftsharks.com/ros-rankings/idp/ppr ; source session already wired for rankings; confirm raw stat export and automation rights | **Investigate raw projections, don't recast rank as stats** |
| CBS Sports Fantasy | Candidate seasonal/weekly projections | GREENFIELD | No validated authorized API/export path in this audit | **Research only** |
| NFL Fantasy | Candidate weekly / preseason player projections | GREENFIELD | No verified API/field/redistribution rights in this audit | **Research only** |
| PFF | Premium charting/advanced data, possible pass-rush/coverage/usage features | Not demonstrated live as a raw-stat projection provider | https://www.pff.com/subscribe (Pro lists API) and https://www.pff.com/terms (personal-only standard API, public distribution/competing product prohibited) | **High-value feature challenger; legal gate, not production ready** |
| RotoWire | Candidate projected stats and injury/lineup context | Not demonstrated as licensed integration | Contract/API/fields unknown | **Research only** |
| FTN Fantasy | Candidate charting and projections | Not demonstrated as licensed integration | Verify available contract, stat fields and independence | **Research only** |
| Footballguys | Candidate seasonal/weekly projections | Not demonstrated as licensed integration | Verify export/API and rights | **Research only** |
| nflverse / nflfastR / nflreadr / nflreadpy | Historical PBP, roster, snap counts, some advanced/offensive/defensive inputs; useful for outcomes and model training, not *vendor projections* | Existing internal `src/nfl_data/` ingestion; first inspect before new fetch | https://github.com/nflverse/nflverse-data ; code licenses and upstream NFL data rights are distinct; check each dataset's provenance before distribution | **P1 historical evaluation + model inputs, provenance gate** |

### Coverage caveats

- The repository's `src/ros/projection_ensemble.py` records two fixed preseason/full-season LIVE families (`clayProjections`, `idpShowProjections`), while `sleeperWeeklyProjections` became separately LIVE for Game Day. This describes the **source census**, not a guarantee that today's files are present.
- Fantasy Nerds and SportsDataIO have *existing* keyed weekly adapters. Investigate why their flags are off and whether licenses and credentials allow activation before writing duplicate scrapers.
- ESPN, Clay, CBS, NFL, DraftSharks, IDP Show, RotoWire, FTN, Footballguys raw stat-field capabilities require product- and time-horizon-specific confirmation. A visible webpage widget is not a verified automated license.
- IDP full-stat projection coverage is a major bottleneck. Do not fabricate `QBHit`, `TFL`, PD, solo/assist splits, return yards or reception-distance bins when a provider supplies only fantasy points or aggregate stats.

## B. Missing raw features prioritized for direct scoring

| Feature family | Exact-league reason | Testable source candidates | Caveat |
|---|---|---|---|
| QB attempts, completions, incompletions, sacks, pass/first downs | league awards completions and penalizes incompletions; rushing/passing FDs have positional keys | Sleeper, Fantasy Nerds, SportsDataIO, actuals via nflverse | Derived `bonus_fd_qb` semantics must mirror host; don't add FD twice |
| Per-catch reception gain bins / first downs | custom `rec_0_4` through `rec_40p` rule is not equivalent to full PPR | PBP historical catches; probabilistic route/aDOT/YAC model | Expected bin counts need distributions, not average receiving yards divided by catches |
| RB carries, goal line, receiving roles | `rush_att` adds points; catches have band scoring | Fantasy Nerds/SportsDataIO plus nflverse historical usage | Opportunistic features can be highly correlated; avoid fake independent projections |
| DL QB hits, sacks, sack yards, TFL; LB solo/assisted; DB PD/INT | disruption and coverage awards differ significantly from standard IDP | SportsDataIO IDP; Fantasy Nerds IDP; IDP Show historical/full season; nflverse actuals | Sack/TFL/hit can co-occur; join play events once then score each allowed key |
| K made-FG distance, XP, misses | `fgm_yds` and distance-specific miss penalties | game-by-game actuals; provider raw kick projection if documented | Generic kicker projected points cannot be transplanted |
| Special teams return yards | player `kr_yd`/`pr_yd` are paid to eligible offensive/IDP players | nflverse actuals; source-specific field audits | Must not confuse player `st_` with Team DEF `def_` |
| Snap shares, route participation, alignment, pressure and pass rush | improve IDP and usage distributions | nflverse, licensed premium providers | Check completeness/latency/upstream data rights |
| Injuries, expected return, bye and opportunity | essential for sampled best-ball weeks | host reports, providers, roster/depth | missing is **unknown**, not probability 1 or stat 0 |

## C. Research/evaluation sequence

1. **Reuse inventory:** compare `config/projections/source_capability_census.json` and existing `src/ros/`, `src/nfl_data/` adapters with current source docs; log missing credentials *names* and access rights, never request raw secrets in PR comments.
2. **Coverage matrix:** provider × season/week × offense/IDP/K × stat key; preserve source timestamps, native schema, provider family, model ancestry and snapshot hash.
3. **Calibration:** rescore each raw-stat observation through **the matching historical league score card**. Missing field = unavailable/partial, never silently zero.
4. **Leakage-safe scoring:** compare holdout MAE/RMSE, proper interval scores and calibration by position and coverage. Evaluate source *incremental residual accuracy*, not number of sites.
5. **Ensemble:** equal-family median/mean baselines before learned weights; cap related provider ancestry, record confidence and missing-state semantics.
6. **Access:** consumer subscription ≠ public redistribution rights. Do not promote any source until authorized acquisition/use is documented and reviewed.

## D. New providers should only be purchased if they solve a demonstrated gap

Preferred immediate order: (1) live scoring validation, (2) activate/test already implemented Fantasy Nerds/SportsDataIO adapters **when authorized**, (3) improve use of existing Sleeper/Clay/IDP Show data, (4) test FantasyPros API in licensed capacity, (5) examine premium IDP charting as a challenger. No performance uplift is claimed without historical backtests.

## E. Citations, review dates and open questions

Official/provider evidence checked **2026-10-19**:

- Fantasy Nerds services and weekly/IDP/ROS projections: https://api.fantasynerds.com/docs/nfl
- SportsDataIO IDP and weekly/seasonal projections: https://sportsdata.io/developers/coverages/nfl
- FantasyPros API projections and access terms: https://www.fantasypros.com/api-data/ and https://support.fantasypros.com/hc/en-us/articles/49749297704475-How-do-I-request-access-to-the-FantasyPros-API
- DraftSharks public ROS IDP page: https://www.draftsharks.com/ros-rankings/idp/ppr
- PFF API offering and usage terms: https://www.pff.com/subscribe and https://www.pff.com/terms
- nflverse releases: https://github.com/nflverse/nflverse-data

**Unknown until independently verified:** exact current prices of Fantasy Nerds/SportsDataIO professional access; current source-specific API quota; provider player/IDP stat column lists for our scoring card; signed redistribution permissions; historical as-of projection archive depth; holdout accuracy; true cross-provider error correlation. Preserve these as unknowns rather than asserting they are absent or available.
