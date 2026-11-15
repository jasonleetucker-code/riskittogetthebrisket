# IDP accuracy, Lane B: replacement methodology, in shadow (2026-10-25)

**Status: SHADOW RESEARCH — FEATURE_GREEN locally (L0 format/lint, L1 `tests/league_valuation`); L2 CI not run, nothing merged, nothing deployed.**
Nothing here changes a served value, anchor, flag, scoring rule, source vote or consumer. The new module is not imported by any production code
(`tests/league_valuation/test_isolation.py` passes unchanged).

**Authority:** `docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md` §7 (replacement value that makes sense) under the §13 safety rules.
**Extends, does not redo:** Investigation B (`docs/valuation/IDP_REPLACEMENT_AND_SCORING_2026-10-20.md`), Lane A's scoring manifest, Lane C's cross-position market baseline.

**Evidence:** `docs/valuation/idp_accuracy/evidence/b_replacement_2026-10-25.json` (aggregates and public NFL player names only).
**Code:** `src/league_valuation/replacement_shadow.py`, `config/league_valuation/replacement_shadow_v1.json`, `scripts/idp_accuracy/replacement_report.py`.
**Tests:** `tests/league_valuation/test_replacement_shadow.py`.

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## 0. Summary

Replacement is six questions, not one number. They are implemented separately and never merged:

| | definition | answers |
|---|---|---|
| D1 | league-wide starter threshold from the exact solver over the 12 real rosters (FLEX and SUPER_FLEX compete) | what the weakest starter produces |
| D2 | best viable free agent (unrostered, explicit healthy, an established role, positive production) | what the single best wire player produces |
| D3 | production-qualified free-agent pool | what a typical qualified wire player produces |
| D4 | 3rd-best, and median of the top-5, qualified free agents | a level robust to one player |
| D5 | dynamic league-wide allocation: each free agent goes to ONE team | what is left after the other teams have claimed |
| D6 | team-specific replacement after a hypothetical transaction | what THIS roster would use |

Findings (all on the pinned 2026-10-25 inputs; n and the conditional interval are in §3 and the evidence JSON):

1. **The wire is close to the starter line at DB, and further at LB and RB/WR/TE.** Median production starter minus the best viable free agent, in points per game: DB 1.0, DL 2.6, LB 4.4, WR 7.6, TE 7.0, RB 11.4. The third-best viable free agent produces 0.82 of the median starter at DB, 0.74 at DL, 0.64 at LB. There is no viable free-agent QB (0 of 21 unrostered).
2. **Every free-agent level is inflated by selection, and we measured by how much.** Ranked on weeks before *w* and scored on week *w*, the top five viable free agents scored **51% of their history ppg for IDP (95% CI 36%–65%, 42 player-weeks, 23 players)**; DB 40% (22%–60%), DL 48% (29%–71%), LB 69% (39%–102%, 14 player-weeks), offense 37% (20%–52%). An empirical-Bayes expectation predicts better than the raw mean (squared error 27.8 vs 30.6, n=1,133 player-weeks). The raw D2 DB level of 13.7 ppg is one player (Christian Izien, 6 games, interval 1.7–25.7); the shrunk expectation is 9.7.
3. **The board prices a minority of the productive wire.** 135 of the 157 viable DBs, 135 of 167 DLs and 64 of 81 LBs are unpriced (counted, never given a value of 0). Value-unit D3/D4 levels therefore rest on 3 priced players at DB and DL and are undefined at LB; they land at 229–1,139 against a starter floor of 1,369–1,686. They are not usable as served anchors.
4. **Best-ball depth is invisible to an average-week lineup.** The same allocation on one pseudo-week of expected ppg finds exactly one claim league-wide (a kicker); on the real weekly lineups it finds 36 (3 rounds × 12 teams). But history overstates them: decided on weeks before *w* and scored on week *w*, the allocation realised **24% of the points it predicted** (23, 66 and 17 against 162, 145 and 142 per week).
5. **Competition for the same players is real but modest.** In round 1 two free agents were the best claim for more than one team; the one-owner-per-player matching gives up 9.9 of 73.9 points per week (13%) against letting every team take its favourite.
6. **A package is not a sum.** Whole-roster before/after versus the naive sum of per-player deltas differs on 7–12 of 12 teams per recipe (e.g. 1-for-2 LB expansion: +1.1 points per week, interval 0.5–1.8; 1-for-2 RB: +1.2).
7. **Reproduction of Investigation B: its code reproduces exactly; one headline number does not, because the data moved.** On the pinned inputs B's own script and the shadow module in legacy-B mode agree on **63 of 63** anchors, and the D1 value levels equal LI-5 exactly on the same rosters (7 of 7). B's DB anchor of 2,156 set by an Out player does not reproduce: no unrostered DB is valued above 1,917 now (§9).

## 1. Definitions and rules that hold for all of them

* **Two units that never mix.** `ppg` = league-scored points per game played (host-native scorer; 3,299 of 3,299 player-weeks equal Sleeper's own). `board value` = `rankDerivedValue`.
* **Missing is never zero.** A player the board does not price has no value (counted as `unpricedViable`). A player with no games has no ppg and is not a weekly replacement. An undefined level carries a reason (`pool_smaller_than_rank_3`, `empty_pool`, …) and the evidence test refuses any level that is exactly 0.
* **Health** is the strict rule: an NFL team, an explicit `status = Active`, no unavailable injury designation. A missing or unrecognised status is UNKNOWN and excluded (none occurred in this snapshot; a test pins it). Questionable is kept and counted (6 DBs, 3 DLs); dropping them is a published sensitivity.
* **Unrostered prospects with zero production are not weekly replacements.** `no_games` (e.g. 12 RBs, 10 WRs) and `below_min_games` (fewer than 3 games) are excluded and counted; a priced prospect with no games cannot set a level whatever his price.
* **Eligibility** is Sleeper's `fantasy_positions` (a DL/LB hybrid is legal at either slot), the basis on which the exact solver matches Sleeper's awarded best-ball lineups.
* **Production qualification** (D3/D4): the free agent's ppg is at or above the P10 of the ppg of the league's production-optimal starters at the position (Investigation B's A4 bar). P25, P50 and the best-ball starter floor are published sensitivities; the bar is unstable by construction (DB: 11 qualified at P10, 1 at P25, 0 at P50).
* **The host's lineup rule.** In realised weeks a rostered player with no stat line scores 0.0 and is startable. Sleeper's own awarded lineup does this (one team-week started two non-players instead of a −2.9 fumbler); it is modelled for realised weeks only and never for a projection. With it the engine reproduces **72 of 72** awarded team-week totals within Sleeper's 2-decimal rounding (max difference 0.012).

## 2. Inputs

| | |
|---|---|
| Board | `exports/archive/dynasty_export_20261025_120337.zip`, sha256 checked, rebuilt with today's `build_api_data_contract` |
| Production | Sleeper 2026 regular season weeks 1–6 (week 7 in progress), scored by `compute_weekly_points(source="sleeper")` |
| Rosters, players DB, league | the Lane A cache snapshot (2026-10-25 20:15Z), 12 rosters of 58, 21 starter slots, no IDP flex, no IR, no taxi |
| Lineup owner | `src.ros.lineup.solve_optimal_assignment`, injected through a port (the module imports nothing from `src`) |
| Config | `replacement_shadow_v1.json`, every constant classified CONVENTION / PRIOR / STRUCTURAL with a reason; the content id is pinned by a test |

Roster agreement: the contract's roster snapshot and the live one are identical (696 ids, 0 differences), so the consumer diagnostics and the definitions describe the same rosters.

## 3. Results by position

Points per game, season to date (weeks 1–6). Intervals are 95% and **conditional on the players who set each number** (§4). `n` is the pool size.

| | median starter | D1 median marginal starter | D1 best-ball floor | D2 best viable | D3 qualified pool mean | D4 3rd-best qualified | viable / qualified (P10) / unpriced viable |
|---|---|---|---|---|---|---|---|
| QB | 24.0 [16.4, 27.5] | 20.4 [11.7, 25.7] | 8.8 [5.6, 11.8] | none (0 viable) | none | none | 0 / 0 / 0 |
| RB | 15.7 [9.8, 20.0] | 11.6 [6.9, 17.5] | 5.5 [3.1, 7.6] | 4.3 [3.2, 6.0] Sione Vaki | none | none | 28 / 0 / 18 |
| WR | 14.2 [11.1, 17.3] | 11.6 [7.7, 14.9] | 6.3 [3.2, 10.2] | 6.6 [1.6, 10.3] Chris Moore | none | none | 40 / 0 / 20 |
| TE | 10.8 [7.1, 13.9] | 10.0 [5.3, 12.9] | 2.3 [1.1, 3.6] | 3.8 [0.2, 8.2] Nate Adkins | 3.8 (n=1) | none | 42 / 1 / 30 |
| DL | 13.4 [9.8, 17.0] | 12.1 [7.5, 16.6] | 6.6 [3.9, 9.3] | 10.8 [3.1, 19.2] David Walker | 9.6 [7.3, 11.8] n=7 | 9.9 [5.0, 14.1] Que Robinson | 167 / 7 / 135 |
| LB | 15.7 [13.5, 17.3] | 13.9 [10.8, 16.6] | 11.0 [5.9, 16.9] | 11.3 [2.4, 20.9] Jake Hansen | none (0 qualified) | none | 81 / 0 / 64 |
| DB | 14.7 [11.7, 16.8] | 13.9 [9.1, 16.3] | 9.7 [7.0, 12.6] | 13.7 [1.7, 25.7] Christian Izien | 11.7 [9.6, 14.0] n=11 | 12.0 [6.1, 19.4] Rasul Douglas | 157 / 11 / 135 |

Kickers are reported separately in the evidence (`levels.raw.byPosition.K`): the board prices no kicker, so every K value level is undefined.

**Starter-to-replacement gap** (median production starter minus the level, ppg, with the paired conditional interval):

| | vs D1 median marginal | vs D2 best | vs D3 pool mean | vs D4 3rd-best |
|---|---|---|---|---|
| RB | 4.1 [0.0, 8.0] | 11.4 [5.2, 15.9] | none | none |
| WR | 2.5 [0.0, 6.5] | 7.6 [2.3, 13.3] | none | none |
| TE | 0.8 [−0.9, 4.3] | 7.0 [1.5, 11.7] | 7.0 [1.5, 11.7] | none |
| DL | 1.3 [−1.2, 5.9] | 2.6 [−6.7, 10.7] | 3.8 [−0.5, 8.1] | 3.5 [−1.9, 9.8] |
| LB | 1.8 [−0.5, 4.5] | 4.4 [−6.3, 13.4] | none | none |
| DB | 0.8 [−1.8, 5.0] | 1.0 [−12.5, 12.6] | 3.0 [−0.8, 6.4] | 2.7 [−5.6, 9.2] |

Reading, in plain terms:

* The pool-based gaps (D3) are the stable ones; the single-player gaps (D2) have intervals wider than the gap itself at DL, LB and DB. A replacement level read off one free agent with six games is noise-dominated.
* DB has the flattest wire (gap to the best viable DB about 1 ppg, third-best at 0.82 of the median starter), LB the steepest of the three IDP positions (4.4; 0.64), DL in between. That matches Investigation B's qualitative finding.
* **Board value units.** D1 median marginal / best-ball floor: DB 1,739 / 1,369, DL 2,048 / 1,686, LB 2,346 / 1,610. D2 best (priced only): DB 1,917 (22 priced of 157), DL 1,773 (32 of 167), LB 2,160 (17 of 81). D2 3rd-best: 1,436 / 1,697 / 1,727. D3/D4 are undefined or rest on three priced players (§0 item 3).

## 4. How the numbers were estimated, and what is not claimed

* **The interval to quote** (`ci95Conditional`): resample the played weeks of exactly the players behind each number (and teams as clusters for the league-wide thresholds), recompute the level from those fixed players, 500 replicates, seed in the config. The point always lies inside its interval (a test enforces it). It **excludes selection**.
* **What a full-procedure bootstrap says instead.** Resampling games and re-selecting everything is biased upward for maxima: the replicate mean sits 4.3 ppg above the observed best-viable DL level, 6.3 above DB, 4.0 above LB. It is published as `reselection` (an inflation diagnostic) and `identityStability`, never as an interval. The same player sets the D2 level again in only 25% of resamples at DB, 27% at LB, 20% at DL; the third-best identity is stable in 8–14%.
* **Winner's curse, measured out of sample** (`selectionRegression`): see §0 item 2. The conditional interval plus this ratio is the honest statement: the observed free-agent level is an upper-biased description of what the wire will produce, by roughly half at IDP.
* **Empirical-Bayes expectation.** One normal random-effects model per (position, rostered or free agent): `y ~ N(mu_i, sigma²)`, `mu_i ~ N(mu, tau²)`, moment estimates, nothing tuned. D2 best viable shrinks DB 13.7→9.7, DL 10.8→7.1, LB 11.3→7.4, WR 6.6→4.1. It is validated for free agents only (lower squared error than raw out of sample) and is deliberately **not published for rostered starters**, where shrinking toward a rostered mean that includes bench players would pull stars down. It over-shrinks real risers (free-agent populations are skewed mixtures), so read it as a lower bracket.
* **Walk-forward discipline** (directive §13 rule 13): every claim about a replacement's contribution has an out-of-sample twin that selects on weeks before the scored week. The in-sample versions are hindsight and are labelled.

## 5. Depth, eligibility, sensitivities

**Healthy waiver depth** (`healthyWaiverDepth`): viable free agents per position and every exclusion counted. Examples: DB 264 unrostered candidates → 157 viable (59 injured/out, 40 below three games, 6 zero production, 2 no games); LB 146 → 81; QB 21 → 0.

**Role and eligibility uncertainty.** Recomputing D1–D4 with hybrids allowed at their Sleeper positions versus listed position only moves DL levels by +0.5 to +0.8 ppg (52 of 118 rostered DL-eligible players are DL/LB hybrids), LB by up to +0.4 (D1 median marginal; the free-agent levels do not move), DB by at most 0.2 (4 hybrids of 117). The hybrid free agents (15 viable at DL, 21 at LB) change which player sets the LB level at most marginally.

**Sensitivities** (`sensitivities`): the P25 bar leaves 1 qualified DB and 0 DL (the primary P10 leaves 11 and 7); dropping Questionable players moves the DB pool from 157 to 151 and leaves the D2 best unchanged; nominal-only eligibility lowers the best viable DL from 10.8 to 10.2; the median of the top 3 / 5 / 10 qualified DBs is 12.0 / 12.0 / 11.9 ppg and is undefined for DL at the top 10 (7 qualified) and for LB entirely.

## 6. D5 and D6

**D5 allocation** (serial maximum-gain matching, 3 rounds, each team one claim per round, each free agent at most one team; the cheapest legal drop is a rostered player who never starts, which is exact and free because adding a player can never promote a non-starter). It is a planner allocation, **not a model of FAAB bidding** and does not say who wins a contested player.

Round 1 (12 claims): DL 5 (mean ppg 9.1 [8.1, 10.1], 4 priced), DB 4 (12.2 [11.5, 13.1], 1 priced), LB 2, K 1. Best viable free agent left after all rounds: DB 11.8 (Christian Benford), DL 9.2, LB 10.1, RB 4.3, WR 6.6, TE 3.4. Hindsight gain per claim is 3–8 points per week; the walk-forward realised 24% of it (§0 item 4). The contrast run (one pseudo-week of expected ppg) leaves a single claim.

**D6 team-specific.** Each team loses its highest-ppg player at the position; what is its best single claim, with every viable free agent open versus after the other teams' D5 claims are removed?

| | lost by the team (pts/wk) | share recovered, open | share recovered, after competition | best claim ppg, open → after competition |
|---|---|---|---|---|
| DB | 5.9 | 0.93 | 0.82 | 11.9 → 10.4 |
| LB | 7.1 | 0.85 | 0.50 | 11.2 → 7.4 |
| DL | 8.1 | 0.74 | 0.64 | 10.8 → 7.9 |
| TE | 7.2 | 0.43 | 0.41 | 3.4 → 3.0 |
| RB | 10.4 | 0.21 | 0.21 | 3.4 → 3.4 |
| WR | 11.0 | 0.17 | 0.17 | 5.2 → 5.1 |
| QB | 12.5 | none (no viable QB) | none | — |

Competition costs the IDP positions most where the pool is thinnest (LB: from 0.85 to 0.50). All of this is in-sample lineup arithmetic on realised weeks; the allocation's out-of-sample ratio (24%) applies equally.

## 7. Marginal best-ball contribution and packages

**Contribution** (`marginalBestBallContribution`): for every rostered player, lineup points per week with him minus without him, by a whole-roster solve each week; "over replacement" lets the roster backfill with the position's D2/D3/D4 free agent. A bench player worse than the backfill has a *negative* value over it.

| DB (pts/wk, 95% cluster interval) | in-sample (backfill picked on the same weeks) | walk-forward (backfill picked before the scored week) |
|---|---|---|
| without him, no backfill, all 117 rostered | 2.4 [2.1, 2.9] | 2.7 [2.1, 3.4] |
| without him, no backfill, 75–101 who started | 2.8 | 4.2 [3.5, 5.1] |
| over the D2 best backfill, starters | −1.6 [−2.1, −1.1] | 4.2 (the backfill never entered a lineup) |
| over the D4 3rd-best backfill, starters | −0.8 [−1.3, −0.3] | 3.6 [2.8, 4.4] |

In hindsight the best wire DB, DL or LB beats the average started IDP player (negative over replacement); chosen before the week he adds nothing. The same table exists for every position.

**Packages** (`wholeRosterPackages`): the evaluator takes any package and returns the whole before/after roster, forced drops, the naive sum of per-player deltas, and their difference. Five recipes × three shapes were run for all 12 teams on realised weeks. Whole-roster versus naive sum differs on 7–12 of 12 teams in every recipe; the difference is up to 1.2 points per week (R3 1-for-2 RB) on deltas of 5–25, and is what the engine's "never sum per-player deltas" rule exists to prevent. R3 shapes force one release per team; it is the free never-starter, so it costs no lineup points.

## 8. Consumer impact (offline, read-only)

Anchor dicts in **board value units** were swapped into the consumers' own pure functions (`CapacityContext`, `assess_roster_capacity`, `forced_drop_cost`, the Trade Finder factor `−(cost/give)×50`, `faab_engine.resolve_anchors`, Perfect Draft rookie surplus), exactly as Investigation B did. No flag was changed and `displacement.py`, `context.py`, `roster_capacity.py`, `droppability.py`, `feature_flags.py` and `trade_simulator.py` were only read.

Served anchors today: QB 1,379, RB 1,652, WR 1,754, TE 2,082, DL 1,874, LB 2,160, DB 1,917 (four of seven set by an injured or inactive player: DL, RB, WR, TE).

| anchor set | net +1 trade: teams whose forced drop changes (of 12) | mean Δ forced-drop cost | mean abs Δ Finder factor | net +2: teams changed | notes |
|---|---|---|---|---|---|
| D1 median marginal | 6 | +450 | 7.5 | 10 | raises every position's anchor to a starter's value |
| D1 best-ball floor (LI-5 `bestBallStarter`) | 6 | −172 | 4.4 | 9 | |
| D2 best viable | 1 | −151 | 2.1 | 2 | QB falls back to served |
| D2 3rd-best viable | 5 | −240 | 3.5 | 8 | |
| D2 banded top-3 (LI-5 waiver tier over the viable pool) | 3 | −188 | 2.6 | 5 | matches the LI-5 flag-ON lens-A level at DL and LB; DB 1,622 vs 1,629 (lens A does not require an established role) |
| D3 pool mean | 5 | −188 | 2.7 | 8 | 5 positions undefined → served |
| D4 3rd-best qualified | 6 | −99 | 4.0 | 10 | 5 positions undefined → served |
| D5 mean of round-1 claims | 7 | −310 | 7.1 | 11 | |
| D6 team-specific after the trade | 3 | −201 | 3.1 | 4 | per team/scenario; DB falls back to served in 22 of 24 |

* **Forced-drop counts do not change under any anchor** (0.83 per team at net +1, as in B): the anchor moves only the *cost* (through which tied sub-anchor player is chosen and the release cost of unpriced cuts), exactly Investigation B's mechanism. Investigation A's forced-drop work and this are still a sequencing question, not a stacking one.
* **Perfect Draft**: rookies with positive surplus over the anchor, DB/DL/LB: served 2/4/5; D2 best 2/5/5; D2 3rd-best 8/7/8; D1 floor 10/7/9; D3/D4 anchors (a few hundred) make 13–23 rookies "positive" at DB/DL, which is an artifact of three priced players, not a finding.
* **FAAB `V_repl`**: served pool 1,655 (guardrail-widened); viable priced pool 1,636; qualified priced pool 902 (6 players, not viable); pool left after the D5 allocation 1,601. A 2,200-value player sits at 64.1% / 65.8% / 92.6% / 68.7% of the budget ceiling. FAAB is barely affected unless the pool collapses to the few priced qualified players.
* **LI-5 consolidation (flag `replacement_level_li5_consolidation`, OFF, owner-held)**: its lens-A level computed offline is QB 1,291, RB 1,522, WR 1,438, TE 1,871, DL 1,729, LB 1,920, DB 1,629, identical to Investigation B's A3hs (healthy, strict, banded top-3) at every position on the pinned inputs.
* **Scarcity multiplier**: still inert at 1.0; nothing here changes that.

## 9. Reproduction of Investigation B

Method: B's own script, unmodified, was run on the pinned inputs (`PYTHONUTF8=1 python scripts/idp_replacement_research.py --out <path> --cache-dir data/idp_accuracy/cache --no-bdvm --roster-max-age-s 1000000000`; the default Windows code page crashes its final source-location step, UTF-8 mode avoids it). The shadow module in legacy-B mode (listed-position pools, B's health rules, no games/production floor, value ordering, B's production bar) was compared field by field.

* **63 of 63** anchor values equal (9 definitions × 7 positions). D1 value levels equal `compute_replacement_levels` exactly on the same rosters (7 of 7 positions, both tiers).
* **Discrepancies against B's published (2026-10-20) numbers are data, not method:**

| B finding | published 2026-10-20 | same code, pinned 2026-10-25 |
|---|---|---|
| DB anchor set by an Out player | 2,156 (Out) | **1,917**, Keionte Scott, healthy and Active; no unrostered DB is valued higher. **Not reproduced.** |
| healthy banded top-3 level DB / DL / LB | 1,754 / 1,812 / 1,946 | 1,629 / 1,729 / 1,920 (lower at all three; the wire's top names changed between the snapshots) |
| anchors set by an injured player or a non-producing rookie | 6 of 7 | 4 of 7 set by an injured or inactive player (DL, RB, WR, TE); the LB anchor is a healthy rookie as before |
| third-best wire / median starter, DB / DL / LB | 0.95 / 0.79 / 0.63 | 0.83 / 0.71 / 0.65 (DB still the flattest) |
| DB wire value-vs-ppg rank correlation | 0.21 [−0.21, 0.60] | 0.26 [−0.20, 0.61] (unchanged: value does not order the wire) |
| LB gap steepest of the three IDP positions | yes | yes (4.4 vs DL 2.6 vs DB 1.0 against the best viable free agent) |

The mechanism B identified (a served anchor set by a non-producing or injured player) persists at four positions; the specific DB headline was a snapshot of the 2026-10-20 wire.

## 10. Which definition answers which consumer's question

This is analysis, not an activation request. No single definition is valid for every consumer (directive §7).

| consumer | the question | definition that answers it | caution from the evidence |
|---|---|---|---|
| forced-drop cost / roster capacity | what is a released player's opportunity cost this season? | D2/D4 level over the viable pool, health-filtered | mostly changes *which tied cut* is chosen and the charge for unpriced cuts; sequence with Investigation A |
| Perfect Draft rookie surplus | does a rookie beat the wire? | a level in value units, D2 banded | value-unit D3/D4 are unusable (few priced players) |
| Trade Finder Team Context | forced-release cost of a package | D6 for the actual roster after the package | D6 is in-sample; undefined or unpriced claims must fall back visibly |
| FAAB `V_repl` | position-agnostic price floor | unchanged | pool changes barely move it |
| league-wide waiver reading | what is left after everyone claims | D5 leftover | planner allocation, not bids |
| a lineup / package decision | does this move help the lineup? | the whole-roster evaluator, never a sum | in-sample gains are ~4× optimistic (§0 item 4) |

## 11. Limits and unresolved

* Six weeks; single-player levels are noise-dominated; intervals are conditional on selection (§4).
* In-sample lineup gains are hindsight; the walk-forward ratio (24%) rests on three evaluation weeks.
* The board does not price most productive IDP free agents; any value-unit replacement level for IDP is therefore built from a small priced minority until pricing coverage improves.
* Health is one snapshot; byes are inferred for weeks 1–6 only (no forward schedule), so a future bye is not modelled.
* The cross-position question (is a DB point worth a WR point?) is **not** answered here: Lane C owns it (IDPTC + Draft Sharks). The position tables above are within-position replacement levels; K is separate.
* **UNRESOLVED:** (a) owner decision on whether any of D2/D4 should replace the served anchor, after Investigation A and the LI-5 consolidation sequencing; (b) the EB prior for free agents is a normal approximation, a skew-aware prior would raise the lower bracket; (c) a forward schedule and a projection source would turn D5/D6 from history-based into forecast-based; (d) `tests/league_valuation/test_isolation.py` scans `scripts/` for `import src.league_valuation`, so the report script loads the module by file path (the way sibling research scripts load each other); a coordinator may prefer an explicit allow-list entry instead.

## 12. Regenerate and test

```
python scripts/idp_accuracy/replacement_report.py --b-pinned-run <B run JSON on the pinned inputs> --offline
python -m pytest tests/league_valuation -q
bash scripts/format_python_changes.sh
```

The Sleeper cache (`data/idp_accuracy/cache`) is gitignored; the report reuses Lane A's cached bodies byte for byte (`--offline` refuses a fetch). Tests: about 40 synthetic and adversarial cases (an injured high-value free agent, a multi-eligible player, an unpriced free agent, a zero-production prospect, two teams wanting the same free agent against a brute-force optimum, the host's zero-fill rule, the winner's curse), invariants on the committed evidence, and real-roster checks that run when the cache is present.
