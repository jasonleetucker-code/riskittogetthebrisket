# The IDP Show: 2026 library audit (2026-11-01)

**Contract:** GitHub issue #2039, research and intake only.
**Status:** RESEARCH. This document changes no value, source vote, weight, flag, route or
deployment. It contains no proprietary tables and no full rankings. It records schemas,
column definitions, row counts, version counts, dates and methodology, all in our own words
and attributed to The IDP Show (theidpshow.com, Substack).
**Machine-readable inventory (schema only):**
[`evidence/idp_show_library_inventory_2026-11-01.json`](evidence/idp_show_library_inventory_2026-11-01.json).

## 0. How this was gathered

* We read the library on 2026-11-01 in the desktop app's built-in browser. The owner had
  signed that browser in to a **paid** (not Founding / S-Tier) subscription. No cookie,
  token or credential was read, copied, printed or stored.
* **Post metadata** comes from the publication's own archive listing (`/api/v1/archive`)
  and the per-post reader endpoint (`/api/v1/posts/<slug>`). That metadata covers date,
  `updated_at`, audience tier, byline, word count and embedded chart ids. Both endpoints
  served the signed-in session's normal subscriber view.
* **Embedded Datawrapper tables.** For each table we read only its header row, its row
  count, a content hash per published version, and the chart's own metadata (`createdAt`,
  `publishedAt`, `lastModifiedAt`, byline, intro line). Where a definition had to be
  verified, we computed ratios inside the browser and recorded the ratios, not the rows.
* **Scope.** We listed 161 posts dated in 2026: 96 free (`everyone`), 50 paid (`only_paid`)
  and 15 Founding / S-Tier (`founding`). Of these, 12 are podcast posts.
  * We read the full text of about 30 posts.
  * We read metadata for 54 charts from the 2025 weekly-projection series and about 25
    charts from 2026.
* **Founding-tier content was not readable** with this subscription. Every `founding`
  post returned only a preview of about 300 characters. That covers IDP Bets, S-Tier
  podcasts and the prospect-model database (see §9). It is recorded as **inaccessible**,
  not as empty.

## 1. Inputs for the opportunity challengers (Worker 5, `src/ros/idp_opportunity/`)

These are the short answers the shadow CB / LB-S / EDGE-DT challengers need. Details are in
§3 to §6.

1. **Opponent tackle opportunity by true position is reproducible from free data, and that
   is what we should build.** The IDP Show's "TKL EFF. Allowed" is **tackles credited to
   defenders of one true position (LB, S, CB, EDGE, DT) against an offense, divided by
   that offense's total offensive snaps**.
   * We verified this to within ±0.2% on every one of the 32 rows of the week-7 LB table.
   * The table also carries a per-game rate, a season total and a last-3-games average.
   * Their input is PFF position designations. We can build the same quantity from nflverse
     play-by-play tackler ids, nflverse rosters / depth charts for position, and team
     offensive snap counts. That version is point-in-time safe by construction and needs
     no licence.
   * Use their tables only as a **parity reference** if permission is granted. Never use
     them as an input.
2. **Their weekly tackles-allowed tables are point-in-time reconstructable by content.**
   * Each published Datawrapper version carries a `Week` field. A table labelled week *k*
     contains exactly *k − 1* games of data (bye teams one fewer). We checked this on every
     version of the LB, CB and DT tables.
   * So a "week *k*" version holds no week-*k* results, even though the versions themselves
     are undated.
   * This makes their table a usable **historical validation reference** for our own
     rebuilt feature. It is not an input.
3. **CB signals the CB column names:**
   * outside versus slot alignment;
   * snap share last week;
   * opponent 11-personnel rate (fewer three-WR sets means a slot corner leaves the field);
   * opponent WR targets per game;
   * opponent pass yards per game;
   * game total and spread;
   * injury / replacement.

   Alignment (slot / wide / box / deep) is PFF-charted in their tables. **We have no free,
   licensed per-player alignment source.** A CB challenger has to start from:
   * snap share (nflverse);
   * opponent personnel (nflverse participation, if available for 2026: verify);
   * targets (nflverse PBP);
   * lines (nflverse schedules).

   Alignment stays a named, missing input. It is never imputed.
4. **EDGE / DT signals the DL streaming model names, in its own stated priority:**
   * snap share (heaviest weight);
   * PFF pass-rush grade (second);
   * PFF run-defense grade (an indicator of snaps, weaker for fantasy);
   * opponent fantasy points allowed to DT / DE.

   The free proxies are:
   * nflverse snap share;
   * QB hits and sacks per pass-rush snap from PBP (`qb_hit_*_player_id`, `sack_player_id`);
   * our own opponent-allowed DL tackles / TFL / sacks.

   Grades, pressures and win rate are PFF data and are **not** licensed to us.
5. **LB / S signals:**
   * every-down versus rotational role;
   * the green-dot (defensive play-caller helmet) designation;
   * time spent on the edge, which suppresses LB tackles;
   * box rate for safeties;
   * team two-linebacker usage rate;
   * team zone versus man coverage rate (zone is associated with more efficient LB tackling
     in their framing);
   * injury replacement.

   Green dot is reported in prose only. It is not a field. It cannot be point-in-time
   reconstructed from their site.
6. **Sample-size and regression warnings their authors state:**
   * Week-1 calls run on prior-season data.
   * One-week box-score swings should not drive roster moves.
   * Sacks regress toward pressure-based expectation.
   * DB scoring is noisy week to week.

   Our challengers should carry the same shrinkage and be scored with uncertainty, not
   point MAE alone.
7. **Their scoring basis is "Big 3", not ours.** Do not reuse any of their point
   thresholds. See §2.

## 2. Scoring basis: Big 3 versus `dynasty_main`

The IDP Show states that all its player evaluations assume its **Big 3** scoring unless
noted. That covers dynasty ranks, season projections and DL-streaming point thresholds.
Weekly rank posts do not restate their basis, so the house default is assumed and is
**unverified per post**.

The `dynasty_main` values below come from the committed league snapshot
`config/league_intel/sleeper_league_snapshot_2026-07-26.json`. The live card is read at
runtime from the league registry.

| stat | Big 3 | `dynasty_main` | ratio (ours / Big 3) |
|---|---|---|---|
| solo tackle | 1.25 | 1.33 | 1.06 |
| assisted tackle | 0.75 | 0.80 | 1.07 |
| tackle for loss | 3 | 4.25 | **1.42** |
| sack | 5 | 2.92 | **0.58** |
| sack yards | 0.1 / yd | 0.111 / yd | 1.11 |
| QB hit | 2 | 2.13 | 1.07 |
| pass defended | 4 | 5.32 | **1.33** |
| forced fumble | 4 | 4.25 | 1.06 |
| fumble recovery | 3 | 3.19 | 1.06 |
| interception | 6 | 5.32 | 0.89 |
| safety / blocked kick | 5 / 5 | 5.32 / 5.32 | 1.06 |

**Consequences.**

* A typical sack scores about the same in both systems once its implied TFL and QB hit are
  added: 2.92 + 4.25 + 2.13 + yards ≈ 10 for ours, against 5 + 3 + 2 + yards ≈ 10.7 for
  Big 3. Sack-only crediting differs a lot, though.
* Our card pays **TFL +42% and PD +33%** relative to Big 3. So run-stopping DTs and LBs,
  and pass-breakup-heavy CBs, rank higher under our scoring than any Big 3 ordering
  implies.
* Lineup positions also differ. Their dynasty and DL work assumes **true positions** (DT,
  EDGE, LB, CB, S). `dynasty_main` starts **DL ×3, LB ×3, DB ×3** with Sleeper position
  eligibility, in a best-ball league.
* Their 4.31-point "average streamer" figure, their 9+ / 20+ hit rates and the "Yahoo /
  MFL projection" accuracy standard **do not transfer** to our league.

## 3. Product inventory

Abbreviations:

* Access: F = free, P = paid, S = Founding / S-Tier (not readable with our subscription).
* Horizon: W = weekly, ROS = rest of season, D = dynasty, S = season-long.
* Kind: raw = statistical data; judg = analyst judgement or rank; mix = both.

Datawrapper chart ids are listed so their schema can be re-verified. Row counts are for
the latest readable version.

| # | product | url slug (theidpshow.com/p/…) | latest post date / updated | cadence | access | horizon | kind | embedded data | basis | author |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Tackles Allowed (5 true positions) | `2026-tackles-allowed-data-nfl-idp` | 2026-10-27 / 10-27 | weekly (Tue) | F | W | raw (PFF-derived) | `CoZmA` LB, `dSJWY` S, `4P0Kf` CB, `2HxrV` EDGE, `aCfr1` DT; 32 rows each; 9–12 versions | true position | Jon Macri |
| 2 | Snap Shares | `2026-idp-snap-shares-nfl` | 2026-09-17 / chart 10-29 | weekly | F | W (history) | raw | `16i1M`, 841 rows, 8 versions; PFF-style 5-digit player id; positions CB/S/LB/ED/DI | true position | The IDP Show |
| 3 | Weekly IDP Rankings & Tiers (LB / DL / DB) | `week-N-idp-rankings-and-tiers-…` (weeks 1–8) | wk 8: 2026-10-28 / 10-31 | weekly (Tue), updated through Sat / Sun | P | W | judg | `paid-chart-redacted` LB 60 rows, `paid-chart-redacted` DL 84, `paid-chart-redacted` DB 84: **one persistent chart per position reused all season**, 26–29 versions; header column renamed `WEEK k` each week | house Big 3 (assumed); Sleeper-style groups | Jon Macri |
| 4 | Weekly IDP Fantasy Report + waiver targets | `week-N-idp-fantasy-report-…` (weeks 1–7) | wk 7: 2026-10-26 / 10-27 | weekly (Mon) | P | W / ROS | mix | `paid-chart-redacted` "full season IDP alignment data": 841 rows × 61 columns of PFF stats, grades and alignment snaps, 6 versions; team coverage rates in prose; green dot in prose | true position | Jon Macri |
| 5 | Johny the Greek's Cornerback Corner | `johny-the-greeks-cornerback-corner-…` (weeks 1–8) | wk 8: 2026-10-29 / 10-29 | weekly (Wed / Thu) | F | W | judg + accuracy ledger | none (prose); labels per player | Yahoo / MFL projections as the yardstick | Johny the Greek |
| 6 | DL Streaming 101 | `dl-streaming-101-week-N-idp` (weeks 1–8) | wk 8: 2026-10-29 / 10-29 | weekly (Wed) | F | W | mix | `uTq5b` streamer list, one chart reused all season, 11 versions, 20–31 rows; season scorecard is an **image** | Big 3; true position (MFL designation) | ProfessorIDP |
| 7 | Rest-of-Season IDP Rankings | `2026-rest-of-season-idp-rankings[-week-N]` (weeks 3–8) | wk 8: 2026-10-30 | weekly (Thu / Fri) | P | ROS | judg | `paid-chart-redacted` LB, `paid-chart-redacted` DL, `paid-chart-redacted` DB; 100 rows each; 6–8 versions; each row carries current rank, previous rank and difference | house Big 3 (assumed) | Jon Macri |
| 8 | IDP Dynasty Rankings (consensus) | `idp-dynasty-rankings` | 2026-10-08 | irregular (several per season) | P | D | judg (two-ranker consensus) | `paid-chart-redacted` 350 rows, 17 versions; columns: consensus overall, per-ranker ranks (2), position rank, age | **Big 3**; stated to **feed the IDP Trade Calculator** | Adamidp, Jon Macri |
| 9 | Dynasty Rankings & Tiers (single analyst) | `2026-idp-dynasty-rankings-and-tiers-fantasyfootball` | 2026-05-13 / 08-26 | irregular | P | D | judg | `paid-chart-redacted` 350 rows, v6 | **Big 3, true position** (DT / EDGE / LB / CB / S) | Jon Macri |
| 10 | Combined IDP + Offense Dynasty | `combined-idp-offense-dynasty-rankings-fantasy-football` | 2026-06-22 | stale (chart terminal at v4, 2026-08-19) | P | D | judg (vendor-declared aggregate of other boards + startup ADP) | `paid-chart-redacted` 665 rows; `paid-chart-redacted` excerpt 250 rows | not stated per board | ProfessorIDP |
| 11 | Season-long projections | `2026-idp-fantasy-football-projections-rankings` | 2026-06-08 / 07-15 | preseason, updated (17 versions) | P | S | raw-model (stat lines) | `paid-chart-redacted` 911 rows: points, snaps, total tackles (no solo / assisted split), sacks, QB hits, TFL, INT, FR, FF, PD; plus a customizable Google Sheet | Big 3 points; stat lines are basis-free | Jon Macri |
| 12 | Redraft position tiers / combined redraft ranks 1.0–3.0 | `2026-fantasy-football-rankings-idp-…`, `2026-combined-idp-rankings…` | 06-01 … 08-29 | preseason | P | S | judg | `paid-chart-redacted` 350 rows (combined 3.0) | Big 3 | Jon Macri |
| 13 | Projected IDP depth charts + scheme | `2026-projected-idp-depth-charts-defensive-schemes` | 2026-05-21 / 09-11 | offseason + preseason | F | S | mix | 32 team charts (`oqHQP`…): position / starter / backup 1 / backup 2; prose: expected zone %, man %, two-LB usage % per team | true position | The IDP Show |
| 14 | Weekly Injury Report tracker | `2026-weekly-injury-report-nfl-idp-fantasy-football` | 2026-10-14; chart daily | daily (Mon–Sat, 6–8 pm CT) | F | W | raw (official reports) | `0i4XK`, 26 versions, rows reset each week; columns: season, week, team, player, position, injury, day 1–3 practice status, game status, **last-checked timestamp**, still-listed flag | n/a | Jake Kohlhagen |
| 15 | Production vs Expected database | `idp-production-vs-expected-database` | 2026-05-22 / 06-29 | annual | P | S / D | raw-model | about 31 charts, 2021–2025: EDGE / DT expected sacks vs actual (126 EDGE rows for 2025); LB / S / CB / EDGE tackles vs expected (148 EDGE rows) | basis-free counts | Jon Macri |
| 16 | Big 3 IDP scoring leaders (2016–2026) | `big-3-idp-scoring-leaders` | 2026-05-20 / 09-15 | annual + in-season 2026 table | F | history | raw | 11 season tables, e.g. `dblCp` 990 rows: games, points, PPG, points / snap, full stat line, snaps, tackle % | Big 3 | The IDP Show |
| 17 | Green Dot / full-time LB tracker | (2025 series; final `2025-full-time-and-green-dot-linebackers-week-18-…`) | 2026-01-05 | weekly in 2025; **no 2026 series found** | F | W | mix | `LF7AH` 56 rows: snaps, snap rate, green-dot flag, tackle rate, weekly snaps / tackles | n/a | Mike Woellert |
| 18 | 2025 weekly stat-line projections | `2025-idp-projections-week-N-…` (weeks 1–18) | 2025-08-31 … 2026-01-02 | weekly (Wed) | P | W | raw-model (stat lines) | **54 charts**, LB / DL / DB per week; solo, assisted, TFL, QB hits, PD, FF, FR, INT, sack, snaps; points under Big 3, FantasyPros, Footballguys, D-UP, ESPN, Sleeper presets | stat lines basis-free | Mike Woellert |
| 19 | 2026 weekly stat-line projections | — | — | **none published in 2026** (confirms the 2026-10-29 census) | — | — | — | — | — | — |
| 20 | IDP Bets (weekly prop picks) | `idp-bets-week-N…` | wk 8: 2026-10-31 | weekly | **S (inaccessible)** | W | judg | preview only | n/a | Johny the Greek |
| 21 | S-Tier podcasts / prospect-model database | `s-tier-…`, `the-idp-show-prospect-models-…` | various | monthly | **S (inaccessible)** | D | — | preview only | — | Jon Macri |
| 22 | LB tackle efficiency study | `idp-linebacker-tackle-efficiency-fantasy-football` | 2026-06-16 | one-off | F | S / D | raw-model | prose; 2023–25 LBs with more than 1,500 snaps | basis-free | Mike Woellert |
| 23 | IDP Trade Calculator (idptradecalculator.com) | external site; described on `the-idp-show-pricing-and-tiers-breakdown-2026`, `idp-dynasty-rankings`, `the-idp-trade-show-february-2026-…` | — | follows the dynasty board | F | D | derived | — | Big 3 (inherited) | — |
| 24 | Podcasts with show notes | e.g. `idp-bets-season-long-idp-prop-bets-328`, `the-idp-trade-show-february-2026-…` | — | weekly | F | mixed | judg | timestamps only; no methodology beyond the calculator statement | — | various |

Not separately inventoried: offseason feature articles (breakouts, sleepers, darkhorse,
mock drafts, coaching-change pieces and similar). They are judgement prose, they carry no
reusable time series, and they matter here only as context.

## 4. Methodologies and definitions (paraphrased)

### 4.1 Tackles allowed (product 1)

* **Source.** PFF, chosen by the publisher so that true position designations are
  available.
* **Row meaning.** A row pairs an offense, named in parentheses, with the defense that
  faces it this week, named in capitals. The numbers describe tackles the **offense**
  conceded to defenders of the stated true position.
* **Columns:**
  * tackles allowed per game;
  * **TKL EFF. Allowed** = total tackles allowed to that position ÷ the offense's total
    offensive snaps, shown as a percentage (verified to within ±0.2% on all 32 week-7 LB
    rows);
  * season total;
  * last-3-games average, intended to catch recent offensive changes such as a QB change;
  * an offense-abbreviation sort key;
  * `TOTAL TEAM SNAPS`;
  * `Week`;
  * team keys.
* **Stated use.** A matchup **tie-breaker** for lineups and props. The page does not
  present it as a projection.
* **Limitations.**
  * It counts tackles, not tackle opportunities by alignment.
  * It uses no opponent-of-opponent adjustment.
  * Samples are small (4–7 games by week 8).
  * Each position's numbers depend on PFF's designations.
  * The per-game rate is confounded by pace. The snap-normalized rate removes pace, but
    tackles per snap still mix run / pass mix with how often the defense is on the field.

### 4.2 Snap shares (product 2)

* Each row is a defender's snap share per week and the season average.
* Data starts in week 1 and grows weekly (35 rows at v1, 841 at v8).
* The player id format and position codes match PFF's.
* The free nflverse `snap_counts` feed, already ingested by `src/playerctx/fetch.py`, gives
  the same concept from PFR. This product adds nothing we lack except PFF's true-position
  labels.

### 4.3 Weekly fantasy report (product 4)

**Structure.** Waiver targets in priority order by position, then a team-by-team section.
Each team section gives:

* zone and man coverage rates with league rank;
* LB, S, CB, EDGE and DT notes on role, snap share and green dot;
* injury-replacement reasoning.

**Data-key definitions in the article footer** (paraphrased):

* **tackle efficiency**: share of a defender's snaps on which he recorded a tackle;
* **win rate**: share of DL snaps that beat a blocker;
* **pressure rate**: pressures per pass-rush snap;
* **pass-rush grade**: PFF's;
* **zone rate**: Cover-2 / 3 / 4 / 6 snaps;
* **man rate**: Cover-0 / 1 / 2-Man snaps;
* **blitz rate**: plays with at least one extra rusher;
* **box, free-safety, slot, outside-corner and DL alignment**: snaps by alignment depth or
  width.

**Season reference averages** are quoted, for example an LB tackle-efficiency average of
about 12.8% (minimum 100 snaps) as of week 7, attributed to the article.

**Green dot.** The linebacker (occasionally a safety) wearing the radio helmet who relays
calls. The fantasy reasoning is that the dot correlates with every-down usage. It is
reported per team in prose, and it is not a structured field.

**Injury-replacement reasoning** is stated per case. Examples include "starter out for the
season, the backup wore the dot and played every down" and "returning starter eased back,
so expect his workload to grow".

These are dated **analyst assertions**. They are not observed facts until snap data
confirms them.

### 4.4 Cornerback Corner (product 5)

**Labels.** IDEAL, SOLID or SIT per corner, usually with a league-depth qualifier ("leagues
of all sizes", "medium to deeper", "deeper leagues only").

* The week-8 article had about 62 SOLID, 10 IDEAL and 14 SIT labels, by our count.
* The "calls" counted in the next week's ledger appear to be the **start** labels (SOLID
  plus IDEAL). SIT labels do not appear to be scored.

**Inputs named:**

* outside versus slot alignment and snap share last week;
* opponent 11-personnel rate (attributed to a third-party site): offenses that rarely use
  three-WR sets cut the opposing slot corner's snaps;
* opponent pass yards per game and WR targets per game;
* game total and spread (a high total with a small spread is preferred);
* injury and replacement.

**Accuracy rubric (the author's own).**

* A call is **correct** if the player matched, beat, or came within an undefined "slim
  margin" of his **Yahoo / MFL projection**.
* Players declared inactive or injured during play are **removed from the denominator**.
* A "massive hit" means double the projection or more.
* The weekly ledger for 2026 (calls / injured or inactive / adjusted / correct / stated
  accuracy) is:

  * Season to date (results weeks 1–7, read from the weekly articles): 569 calls, 64
    excluded as injured or inactive, 505 adjusted, 374 correct. The author's per-week
    ledger is not reproduced here.
* The season claim is 73%. Our recomputation from the season totals is 374 / 505 = 74.1%.

**Limitations.**

* The benchmark is a platform's projection, not our league score.
* "Slim margin" is undefined.
* Injured or inactive exclusion inflates accuracy relative to the user's realized outcome.
  The author partly acknowledges this by reporting an alternative figure (70% in week 8)
  that would credit players who had already cleared their projection before injury.
* SIT calls are not graded.
* There is no baseline. "Matches the projection" for an every-snap outside corner may be
  the base rate.
* Articles are edited after publication. `updated_at` falls after Thursday kickoff in
  several weeks, and "UPDATE" notes appear in the text. Substack exposes no revision
  history, so the pre-kickoff text is not recoverable.

### 4.5 DL Streaming 101 (product 6)

**Pool.** 20–40 DT / DE streamers, each rostered in fewer than 20% of IDP leagues (about
half under 10%), chosen after waivers run.

**Tiers.**

| tier | intended use |
|---|---|
| Ideal | any format |
| Solid | leagues with 16–24 starters at the position |
| Solid-deeper | best-ball, or 28+ starters |
| Dart throw | usage red flags, but boom potential |

**Model weights, as described in the author's methodology primer:**

1. snaps (heaviest);
2. PFF pass-rush grade;
3. PFF run-defense grade (mainly a proxy for snaps);
4. opponent fantasy points allowed to DT / DE;
5. small subjective adjustments.

**Chart columns.** Player, true position, Sleeper position, team, opponent, prior-season PFF
pass-rush grade, prior-season PFF run-defense grade, points allowed (from week 4), snap %
and rating.

**Self-scorecard.**

* Measures: average Big 3 points of all streamers, share of 0-point outings, share of 9+
  and 20+ games, and tier monotonicity.
* Week 7 is reported as the worst week of the season so far, with an average of 4.31
  points. Tier ordering held.
* The season table is an image, not data.

**Stated rules.**

* Do not cut on one box score.
* Pressures without sacks regress positively.
* Vacated snaps after a trade or release create opportunity, as in the week-8 example of a
  DT gaining a departed starter's snaps.
* DTs are more streamable than edges because managers hold edges.

**Limitations.**

* Big 3 thresholds.
* Grades come from PFF.
* "Points allowed" is the vendor's figure.
* Selection depends on the roster rates of other leagues.

### 4.6 Rankings (products 3, 7, 8, 9, 12)

**Weekly ranks:**

* one row per player: tier, position rank, team, week opponent and a short note;
* a "NEW" flag marks a player new to the list;
* the post says updates continue up to game day;
* charts are revised Saturday and even Sunday morning.

**ROS ranks:**

* top-100 per group (LB / DL / DB) with current rank, previous rank and difference;
* notable risers and fallers in prose.

**Dynasty consensus** (product 8):

* Two rankers (Adam Marcum, Jon Macri), 350 IDPs, Big 3, with per-ranker ranks and age.
* Adam's expanded spreadsheet is linked from the post. We did not open it.
* The post states that these rankings **feed The IDP Trade Calculator**.

**Single-analyst dynasty board** (product 9): Big 3, true position.

All five are **judgement ranks**. None carries a point value. Weekly and ROS ranks are
seasonal-lane evidence only.

### 4.7 Projections (products 11 and 18) and Production vs Expected (product 15)

**Season projections (2026).** The author says they model:

* expected sacks;
* past production with built-in regression;
* team scheme tackle rates;
* projected alignment from scheme;
* schedule-based run / pass game flow;
* rookie comparables from the house prospect model.

They are presented as less biased than the analyst's rankings. The published stat line
merges solo and assisted tackles, so rescoring under our card needs an explicit split
assumption. That assumption is labelled, never silent.

**2025 weekly projections:**

* full stat lines for LB, DL and DB, with a separate solo / assisted split;
* points under six preset scorings;
* **no 2026 continuation**.

**Expected sacks:**

* pass-rush snaps × three-year averages of PFF pass-rush grade, win rate and pressure rate;
* presented as the most stable and predictive DL metric, with year-to-year and in-season
  correlation charts shown as images;
* "tackles vs expected" is framed as context for tackler quality, not prediction.

### 4.8 Depth charts and scheme projections (product 13)

* Starter and backups by position.
* Expected zone and man coverage rates and projected two-LB usage per team, derived from
  the defensive play-caller's history.
* The page states that zone coverage tends to raise LB tackle efficiency.

## 5. Comparison with our models

| our owner | what it does today | what The IDP Show has that we lack | verdict |
|---|---|---|---|
| `src/ros/weekly_league_projections.py` | League-scored weekly points from Sleeper / RotoWire (plus the FPTrack filler, a RotoWire constituent); single family; no matchup or snap feature of its own | Opponent position-group tackle opportunity; snap / role change; green dot; CB alignment × personnel; DL pressure regression | **Missing signals.** All are candidate *residual* features over the RotoWire champion. RotoWire may already price some matchup, so test the increment, never add it naively. |
| `src/waivers/streaming.py`, `streaming_solver.py` | Optimizer over weekly projections with dynasty-cost guards | Candidate filters (roster rate below 20%, snap floor, vacated snaps), tier ordering, a "do not cut on one box score" prior | Their *filters* are testable as candidate-generation rules. Their *rank order* is judgement and not a value. |
| `src/waivers/drop_assessment.py` | Protection classes from canonical value, waiver ladder, playerctx snap share / trend / depth, draft capital | Pressure-without-sacks regression; green-dot / every-down role; injury-replacement temporariness | A role-security input (every-down share, sustained over N weeks) could reduce false "churn" labels. Pressure data is not licensed. |
| `src/api/data_contract.py` (`idpShowCombined` voter, `idpShow` unregistered) | `idpShowCombined` is the family's sole dynasty voter, withheld as stale (chart terminal 2026-08-19). The IDP-only board is fetched but does not vote. | The vendor states that the IDP-only consensus **feeds the IDP Trade Calculator**. IDPTC is already a voter. | **Double-count risk is now vendor-stated, not merely suspected** (§6). |
| `docs/sources/IDP_SOURCE_AUTHORITY_2026-10-28.md`, decision D-A | Owner decision pending on whether the IDP Show family should vote from the IDP-only board | Same as above | Any D-A "yes" must resolve the IDPTC lineage first. The vendor statement makes that blocker concrete. |
| `docs/projections/WEEKLY_IDP_SOURCE_CENSUS_2026-10-29.md` | Says no 2026 IDP Show weekly projection post exists, and paid 2025 weekly projections existed for weeks 5–18 | Confirmed: no 2026 weekly projection series. The 2025 series spans **weeks 1–18**, not 5–18. | Census correction: the 2025 series starts at week 1 (post dated 2025-08-31). |
| `docs/waivers/IDP_STREAMING_BACKTEST_RESULTS_2026-10-29.md` | +19.9 per decision week for the studied streamer; the strict solver is about +0.4; RotoWire under-projects IDP | Inputs that plausibly explain the human edge: role / green-dot changes, vacated snaps, snap-share trend | A role-change event feature is the most direct test of the "human edge" hypothesis (§7, item 3). |
| `src/league_intel/scorer.py` + league card | Exact `dynasty_main` scoring | Big 3 only | Every comparison must rescore stat lines under our card. Rank or point outputs on Big 3 are not comparable. |

## 6. Lineage and double-counting

**Vendor statements, all read on 2026-11-01:**

* The 2026-04-26 pricing post says the calculator is sourced from the publication's
  dynasty IDP rankings plus market-based offensive values.
* The 2026-10-08 consensus dynasty post says the rankings feed the IDP Trade Calculator.
* The 2026-02-27 podcast note says the calculator is powered by one ranker's dynasty
  rankings.

**What this means.**

* `config/sources/source_lineage.json` records `idptc-idpshow-suspected-ancestry` as
  *suspected*, on the grounds that "no vendor statement says so". **That premise is now
  false.**
* Under the owner's 2026-10-19 rule (`SOURCE_VOTING_CONSENSUS_2026-10-19.md`), a
  vendor-stated derivation is credible shared-data-lineage evidence.
* The "market-based offensive values" clause is also consistent with the measured
  `idptc-ktc-dependence` relation.

**Recommended governance follow-up.** This is not done here: it belongs to the sources lane
and its owner, and the record is a configuration file.

* Upgrade the relation from suspected to vendor-stated, citing these three posts.
* Re-evaluate whether the `idpShow` family and `idpTradeCalc` may both vote on IDP rows.
* Today `idpShowCombined` is withheld as stale, so the live overlap is dormant. It becomes
  live the moment decision D-A switches the family to the IDP-only board, or the combined
  board refreshes.

**Within the vendor**, the following are related, not independent:

* consensus dynasty board;
* single-analyst dynasty board (one of the two consensus rankers);
* combined offense + IDP board (a declared aggregate);
* ROS ranks, weekly ranks and the fantasy report (same primary author);
* season projections (same author, presented as model-based).

At most **one** IDP Show family vote may exist per lane. Weekly and ROS products never enter
the dynasty lane.

**External data inside the vendor's work.** PFF supplies grades, alignment, pressures and
the tackles-allowed counts. A third-party site supplies 11-personnel rates. Vegas lines are
also used. Any feature we derive from the vendor's tables inherits PFF lineage, and any
other PFF-based input we might add later would overlap with it.

## 7. Ranked improvement opportunities (shadow only; each needs preregistration)

Columns: hypothesis / required data / point-in-time feasibility / permission / owning module
/ test design / double-count risk.

1. **Opponent true-position tackle opportunity, rebuilt from nflverse.**
   * **Hypothesis.** Opponent tackles-allowed per offensive snap by true position (season
     plus last-3, shrunk toward the league mean) reduces weekly LB / S / CB residual error
     against the RotoWire champion under our card.
   * **Data.** nflverse PBP (tackler ids), rosters / depth-chart positions, team offensive
     snaps.
   * **Point-in-time.** Yes, by construction: use only games before week *k*.
   * **Permission.** Not needed (open data).
   * **Owner.** `src/ros/idp_opportunity/` (Worker 5) → challenger to
     `weekly_league_projections`.
   * **Test.** Expanding-window weekly MAE / RMSE / bias per position, rank correlation and
     top-starter hit rate, 2024–2026, pre-kickoff inputs only; champion versus champion
     plus feature.
   * **Double-count risk.** Medium. RotoWire may already include matchup, so test the
     residual only. The IDP Show tables are a parity reference only.
2. **Lineage record correction (IDP Show → IDPTC is vendor-stated).**
   * **Hypothesis.** The family-cap / independence rules currently treat IDPTC and IDP Show
     as independent. They are not.
   * **Data.** The three vendor statements (§6).
   * **Point-in-time.** n/a.
   * **Permission.** Reading published statements; no data ingestion.
   * **Owner.** Sources lane (`config/sources/source_lineage.json`, independence policy).
   * **Test.** A lineage-policy unit test that `idpShow*` and `idpTradeCalc` cannot both
     vote unless the owner explicitly decides it.
   * **Double-count risk.** This item *removes* a double count.
3. **Role-change events: vacated snaps, every-down share and green-dot proxy.**
   * **Hypothesis.** A defender whose snap share jumps after a teammate's IR, trade or
     release, or whose every-down share stays at or above about 90% for 2+ weeks, is
     under-projected by the champion. This explains part of the +19.9 human-streamer edge.
   * **Data.** nflverse weekly snap counts, Sleeper injury / transaction history (already
     ingested), depth-chart deltas.
   * **Point-in-time.** Yes. Snapshots are dated, and Sleeper statuses must be archived
     pre-kickoff.
   * **Permission.** Open data. Green dot itself is prose-only on the vendor site, so use a
     snap proxy instead.
   * **Owner.** `idp_opportunity` → `streaming_solver` candidate set.
   * **Test.** A counterfactual streaming backtest on the same candidate universe, with a
     no-move baseline, comparing the solver with and without the role-event feature.
   * **Double-count risk.** Low.
4. **DL sack regression from QB-hit and sack rates.**
   * **Hypothesis.** A DL's next-week sacks are better predicted by shrunk QB hits per
     pass-rush snap than by last week's sacks. Expect under-projection for high-hit /
     low-sack players.
   * **Data.** nflverse PBP `qb_hit_*` / `sack_player_id`; pass-rush snaps approximated by
     defensive snaps × opponent dropback rate. True pressures are PFF and unavailable.
   * **Point-in-time.** Yes.
   * **Permission.** Open.
   * **Owner.** `idp_opportunity` EDGE / DT challenger.
   * **Test.** Weekly DL residual MAE, and calibration of sack probability (Brier).
   * **Double-count risk.** Low to medium (RotoWire may already regress).
5. **CB personnel / slot exposure.**
   * **Hypothesis.** Slot-heavy CBs facing offenses with low 11-personnel rates lose snaps
     and tackle opportunities; outside CBs facing high WR-target offenses gain them.
   * **Data.** nflverse participation (`offense_personnel`; **2026 availability
     unverified**), PBP targets by receiver position, schedule lines. Slot / wide alignment
     is **unavailable** (PFF / FTN licence).
   * **Point-in-time.** Yes, if participation is published weekly.
   * **Permission.** Open for the personnel and target data. Alignment needs a licence.
   * **Owner.** `idp_opportunity` CB challenger.
   * **Test.** CB-eligible and S-eligible subsets separately; weekly residual; check whether
     snap share against low-11 offenses really falls.
   * **Double-count risk.** Low.
6. **Independent weekly stat-line family: evaluate the 2025 IDP Show weekly projections.**
   * **Hypothesis.** A second projection family, independent of RotoWire, reduces weekly
     IDP error when averaged (`equal_family_mean`).
   * **Data.** 54 charts for 2025 weeks 1–18 with solo / assisted / TFL / sack / QB hit /
     PD / INT / FF / FR stat lines.
   * **Point-in-time.** **Partial.**
     * 50 of 54 latest chart versions were last modified before that week's Sunday
       17:00 UTC kickoff.
     * **0 of 54** before the Thursday game.
     * Older versions are undated.
     * So the data is usable only for Sunday / Monday games, with 4 charts (2025 week 3 LB,
       week 6 DB, week 7 LB, week 18 LB) excluded as post-kickoff.
   * **Permission.** **Required.** Paid content; internal research use would need the
     publisher's permission for retained copies.
   * **Owner.** `projection_source_census` + `weekly_league_projections` (evaluation
     only).
   * **Test.** Rescore under our card; MAE / bias per DL / LB / DB against realized 2025
     stat lines; compare with RotoWire. There is no 2026 series, so this informs whether to
     seek a licence, not a live input.
   * **Double-count risk.** Unknown ancestry: the vendor discloses no use of RotoWire, so
     the census must test correlation first.
7. **Practice-participation availability prior.**
   * **Hypothesis.** The day-1 to day-3 practice status sequence (DNP / LP / FP) predicts
     inactives and snap reduction better than the final game status alone.
   * **Data.** Official injury reports via nflverse `injuries`, with free timestamps. The
     IDP Show tracker carries the same official facts with a last-checked timestamp.
   * **Point-in-time.** Yes, if our own captures are archived (the nflverse data is
     post-hoc but describes pre-game facts).
   * **Permission.** Open via nflverse. The vendor tracker needs permission.
   * **Owner.** `src/ros/availability.py` / `game_day_week`.
   * **Test.** Brier score for "inactive" and for "snap share below 50%".
   * **Double-count risk.** Low.
8. **Scheme context: team zone rate and two-LB usage.**
   * **Hypothesis.** LB2 snap share follows the team's two-LB usage, and zone-heavy teams
     raise LB tackle efficiency.
   * **Data.** Two-LB usage approximated from nflverse participation (`defense_personnel`).
     Coverage rates are charted data, licensed (PFF / FTN), so treat them as **missing**.
   * **Point-in-time.** Yes, for participation.
   * **Permission.** Open for personnel; licence for coverage.
   * **Owner.** `idp_opportunity` LB challenger.
   * **Test.** LB snap-share prediction error.
   * **Double-count risk.** Low.
9. **Season / ROS lane: IDP Show season projections as a seasonal-lane challenger.**
   * **Hypothesis.** A stat-line season projection improves ROS strength or Pick Forecast
     inputs over rank-derived proxies.
   * **Data.** `paid-chart-redacted` (911 rows, 17 undated versions; total tackles only).
   * **Point-in-time.** **No.** The versions are undated, so a pre-season snapshot cannot
     be certified.
   * **Permission.** Required.
   * **Owner.** Seasonal lane (`src/ros/*`), never dynasty.
   * **Test.** Prospective capture only.
   * **Double-count risk.** Medium, against the weekly RotoWire family on overlapping
     horizons.
10. **External benchmark: the CB and DL streaming call ledgers.**
    * **Hypothesis.** Our streaming recommendations match or beat a published expert's
      start calls under our scoring.
    * **Data.** Weekly CB / DL call lists (names plus labels).
    * **Point-in-time.** **Prospective only.** Article text is edited after kickoff and
      revisions are not retained. The DL chart has 11 undated versions.
    * **Permission.** Required to retain the lists.
    * **Owner.** `streaming_backtest` (evaluation).
    * **Test.** Same-week, same-pool comparison under our card, with SIT calls graded too
      and injured players kept in. That is the opposite of the author's rubric, which is
      the point.
    * **Double-count risk.** Benchmark only; never an input.

Not recommended:

* turning weekly or ROS ranks into points;
* adding any IDP Show board as an additional dynasty vote beside IDPTC;
* using their Big 3 thresholds;
* using PFF-derived columns from the alignment table without a PFF licence.

## 8. Point-in-time verdicts per product

| product | old versions retrievable? | dated? | verdict |
|---|---|---|---|
| Tackles allowed | yes, older published versions remain retrievable | no per-version timestamp; the `Week` field is present | **Point-in-time by content.** Week *k* holds *k − 1* games (verified). Historical reference only. |
| Snap shares | yes | no | **Point-in-time by masking.** Per-week columns let us drop week ≥ *k*. Redundant with nflverse. |
| Weekly ranks | yes (26–29 versions; the header shows `WEEK k`) | no; several versions per week, edited through Sat / Sun | **Not certifiable historically.** Which version was live at kickoff is unknown. Prospective capture only. |
| ROS ranks | yes | no | Not certifiable. Each row carries the previous rank, which only gives a lagged pair. |
| Fantasy report / alignment table | text: no revision history; alignment chart: 6 versions, undated, games-played column | no | Text not certifiable. The alignment table is partially content-checkable (games played), but it is PFF data. |
| CB Corner | text only; edited after publication | `updated_at` only | Prospective capture only. |
| DL Streaming | chart: 11 versions | no | Week-to-version mapping is inferential, so not certifiable. Prospective only. |
| Dynasty consensus | yes (17 versions) | no (the post is dated 10-08) | Not certifiable per version. Our own repo archive (`idpShow.csv` history) is the dated record. |
| Season projections | yes (17 versions) | no | Not certifiable. |
| 2025 weekly projections | latest version per chart | chart `lastModifiedAt` | **Partially certifiable.** Sunday / Monday games, 50 / 54 charts; no Thursday game. |
| Injury tracker | yes (26 versions) | **yes, per row (last-checked timestamp)** | Point-in-time feasible from row timestamps. The open nflverse equivalent is preferred. |
| Depth charts / scheme | yes | no | Not certifiable. Preseason context only. |
| Production vs expected | yes | no (annual) | Season-level, so the past seasons are inherently historical. PFF-derived. |

**Datawrapper caveat.** On the five tackles-allowed charts, the chart-level `publishedAt`
(2026-10-20) is *earlier* than the "Updated 10/27/26" intro line and the week-8 data. So
`publishedAt` cannot be trusted as the publication time of the current version. Treat
`lastModifiedAt` as an upper bound on when the latest content existed, and treat older
versions as undated.

## 9. Permission and ingestion blockers

* **No new automated ingestion was built, and none is proposed without a separate
  permission check.** For each product, automated use would need:
  1. written confirmation from The IDP Show that a paid subscriber may retain copies for
     internal model evaluation, separate from the existing owner attestation that covers
     the dynasty boards `fetch_idpshow.py` already reads;
  2. clarity on PFF-derived columns (tackles allowed, alignment, grades), since the
     publisher's licence from PFF may not extend to downstream retention;
  3. the existing session mechanism (box-local jar, never committed);
  4. dated capture by **our own clock** before kickoff (the vendor's versions are undated);
  5. identity mapping (PFF-style 5-digit ids → Sleeper via `src/identity`, exact rungs
     only).
* The Datawrapper dataset endpoints answer without authentication once a chart id is known.
  For paid products, the ids are learned only from paywalled posts, so we treat them as
  covered by the subscription terms. Reachability is not permission.
* **Founding / S-Tier content is inaccessible** with the current subscription: IDP Bets
  weekly picks, S-Tier podcasts and the historical prospect-model database. Nothing about
  those products is claimed here beyond their titles, dates and preview text.

## 10. UNRESOLVED

These are named gaps, not zeroes:

* Founding-tier products (§9) were not examined.
* Image-only content was not read as data: the DL streaming season scorecard and the
  expected-sacks correlation charts.
* Adam's linked dynasty spreadsheet, the customizable projection Google Sheet and the IDP
  Trade Calculator site itself were not opened.
* Whether `publishedAt` or `lastModifiedAt` reflects republishes was not resolved (§8
  caveat). The Wayback Machine might date old versions; not attempted.
* The latest version's dataset (`/11/`, `/12/`) of the LB and S tackles-allowed charts did
  not load from the browser (fetch failure). Their schema was confirmed from version 10 / 11
  and the chart metadata.
* nflverse participation availability for 2026 (needed for items 5 and 8) is unverified.
* The DL streaming week-to-version mapping (11 versions for 8 weeks) is unverified.
* The weekly-rank scoring basis is assumed to be Big 3 (house default) and is not stated per
  post.
* The `dynasty_main` card values are cited from the 2026-07-26 committed snapshot. The
  census quotes `idp_def_td` as 6.36 against 6.38 in that snapshot. The live card was not
  re-read.

## 11. #2039 traceability

| issue section | where it is answered here |
|---|---|
| §A Source inventory / legality / freshness | §0, §3 (per-product access, horizon, kind, schema, cadence, author), §8 (versioning and timestamps), §9 (permission and ingestion), JSON inventory |
| §B Weekly opportunity features (CB, LB / S, EDGE / DT, all positions) | §1 (challenger inputs), §4.1–4.5, §4.8, §7 items 1, 3, 4, 5, 7, 8 |
| §C Dynasty / ROS separation | §2 (scoring), §4.6–4.7, §5 (dynasty rows), §6 (lineage: vendor-stated IDPTC feed; one family per lane), §7 items 2 and 9 |
| §D Accuracy and counterfactual tests | §4.4 (CB rubric and denominators, recomputed), §4.5 (DL scorecard), §7 test designs, §8 (pre-kickoff feasibility), §7 item 3 (the +19.9 versus +0.4 gap) |
| §E UI deliverables | Out of scope for this audit. The UI must label weekly / ROS / dynasty as separate concepts and never show the vendor's self-reported accuracy as ours (§4.4). |
| §F Tests / gates / governance | §0 (no production change), §6 (lineage follow-up routed to the sources lane), §9 (no ingestion without permission). No planning documents were edited. |
