# Scoring parity census — repo scorers vs the league host (CW-08)

**Status:** measurement only. No production code, scoring, BDVM/ROS value, flag or
public output is changed by this document or by the PR that carries it.
**Evidence:** `docs/scoring/evidence/scoring_parity_census_2026-11-06.json`
(aggregates, per-key tables, every mismatched player-week by public name).
**Reproduce:** `python scripts/scoring_parity_census.py` (live; caches under the
gitignored `data/scoring_parity/`), `--offline` to reuse the cache,
`--alt-realized-points <file>` to score with another `realized_points.py`
(used here for PR #1938), `--variant-json <census.json>` to embed that run.
Unit test (fixtures, no network): `tests/nfl_data/test_scoring_parity_census.py`.

## Verdict in one paragraph

**The host-native path is exact; the nflverse path (the one BDVM's in-season blend
reads) is 91.8% exact, and every disagreement is attributed.** Of 5,563 rostered
`dynasty_main` player-weeks in finalized 2026 weeks 1-8, the canonical scorer
`score_stat_line` over Sleeper's own stat line matches the host's `players_points`
on **4,833 / 4,833** scored player-weeks (max |Δ| 0.0044; the other 730 have no
stat line and were all awarded 0.0). The nflverse path matches on **3,743 / 4,077
(91.8%)**. The 334 misses split into **121 category-mapping defects**
(`sleeper_stat_line_from_row` drops events the row carries) and **213
raw-stat-feed disagreements** (nflverse charts the event differently from Sleeper,
mostly special-teams tackles inside the defensive tackle columns). Zero rows are
unexplained, zero are host-scoring differences, zero are configuration or
projection confusion. **PR #1938 is the fix for the mapping defects and it works:
re-running the identical census with its `realized_points.py` gives 3,931 / 4,077
(96.4%).** Nothing here duplicates it.

## Method and data timestamps

| item | value |
|---|---|
| league | `dynasty_main` (registry `defaultLeagueKey`; id resolved via `league_registry.get_sleeper_league_id`, not written to the evidence) |
| scoring card | Sleeper `/league/<id>` `scoring_settings`, fingerprint **`sf1:9e51824690d091f9`** (`scoring_fingerprint`) — identical to the fingerprint Lane A pinned on 2026-10-25 (`docs/valuation/idp_accuracy/MANIFEST.json`): **no configuration mismatch** |
| finality | `/state/nfl` season 2026, week 9, `display_week` 9; `host_lineups_open_from_week` → 9 (`host_week_not_final`); `last_scored_leg` 8. **Finalized weeks censused: 1-8.** Week 9 excluded (its games are not final; nflverse already carries partial week-9 rows) |
| fetch times (UTC) | Sleeper league, state, directory, 8 matchups, 8 stat dumps: all 2026-11-06T13:12:12Z (sha256 per response in the evidence `inputs`); nflverse `stats_player_week_2026` fetched live the same minute (canonical-row sha256 `b048a0ce…`); play-by-play supplement built the same hour via `persist_pbp_weekly(..., complete_through_week=8)`; census run 2026-11-06T13:14:23Z |
| population | every rostered player-week in `/matchups/<week>` `players_points` (starters and bench; best ball) = **5,563** (1,980 of the 4,077 scored nflverse rows are starters, reported separately) |
| host | Sleeper `players_points` |
| (b) | `score_stat_line(sleeper_stat_line, card)` (canonical dot product) and, separately, the production wrapper `compute_weekly_points(source="sleeper")`; both equal |
| (c) | `compute_weekly_points` over the nflverse weekly row **exactly as `bdvm.actuals.weekly_points_from_rows` feeds it**: `normalize_weekly_row` → play-by-play supplement (`attach_supplement`) → `TRUE_POSITION_MAP` position |
| identity | nflverse row → Sleeper id through `resolve_canonical_v2` (the identity owner): GSIS rung first, then the owner's **exact-name** rungs (name + position + team); guarded-fuzzy / initial rungs and ambiguities refused and counted |
| tolerance | 0.011 (Sleeper publishes 2 dp) |

Identity coverage is itself a finding: Sleeper's `/players/nfl` carries `gsis_id`
for only **3,893 of 12,229** entries (and none for most current rookies), so a
GSIS-only join reaches 1,934 of 8,428 nflverse REG rows. The owner's exact-name
rungs add 6,418 (`exact_clean` 6,348, `exact_canonical` 43, `exact_lookup` 27);
**76 nflverse rows stay unjoined** (72 unresolved/ambiguous, 4 refused as
fuzzy). On the host side **24 player-weeks (+292.72 host points; Quinnen
Williams ×8, Byron Young ×8, Matt Hibner ×3, Josh Uche ×3, Zonovan Knight ×2)
have no joined nflverse row** — the same name-collision / name-form families
Lane A found. They are reported as an identity class and are in neither the
numerator nor the denominator of the 91.8%. 1,462 more host rows have no nflverse
row and were awarded 0 (byes/inactives).

## (b) host-native scorer vs host — exact

| position | player-weeks | within 0.011 | max \|Δ\| |
|---|---|---|---|
| QB | 403 | 403 | 0.0000 |
| RB | 639 | 639 | 0.0033 |
| WR | 1,000 | 1,000 | 0.0033 |
| TE | 439 | 439 | 0.0000 |
| K | 160 | 160 | 0.0000 |
| FB | 5 | 5 | 0.0000 |
| DL | 651 | 651 | 0.0044 |
| LB | 737 | 737 | 0.0044 |
| DB | 799 | 799 | 0.0044 |
| **all** | **4,833** | **4,833 (100%)** | **0.0044** |

Every week 1-8 is 100%. Exceptions: none. This reproduces Lane A's weeks 1-6
result (3,710 / 3,710) on two more weeks.

## (c) nflverse path vs host

| position | n | within 0.011 | agreement | net Δ (nflverse − host) | **with #1938** agreement | net Δ with #1938 |
|---|---|---|---|---|---|---|
| QB | 261 | 251 | 96.2% | −12.77 | 99.6% | −0.80 |
| RB | 519 | 503 | 96.9% | −18.40 | 99.6% | +0.22 |
| WR | 805 | 744 | 92.4% | −86.76 | 99.5% | −1.39 |
| TE | 359 | 338 | 94.2% | −34.55 | 99.7% | −0.80 |
| K | 160 | 149 | 93.1% | +23.17 | 99.4% | −1.33 |
| FB | 4 | 1 | 25.0% | +3.00 | 25.0% | +3.00 |
| DL | 563 | 534 | 94.8% | −1.54 | 96.1% | −7.15 |
| LB | 662 | 566 | 85.5% | +78.90 | 90.8% | +22.75 |
| DB | 744 | 657 | 88.3% | +95.61 | 93.2% | +27.49 |
| **all** | **4,077** | **3,743** | **91.8%** | +46.66 | **96.4% (3,931)** | +41.99 |

Started-only: 1,829 / 1,980 (92.4%). By week: 90.5%-92.6% (no drift).

### Disagreement classes (334 mismatched rows)

| class | rows | net Δ pts | what |
|---|---|---|---|
| category mapping defect | 121 | −147.1 | the nflverse row carries the event and `sleeper_stat_line_from_row` emits nothing for that key |
| missing / different raw stat event in the feed | 213 | +193.8 | normalization emitted a nonzero count that differs from Sleeper's |
| host-scoring difference (host line ≠ host award) | 0 | — | (b) is exact, so none |
| identity mismatch | 24 host-nonzero player-weeks, outside the 4,077 | (+292.7 host pts unmatched) | see above |
| configuration mismatch | 0 | — | fingerprint equals the pinned card |
| projection-vs-actual confusion | 0 | — | both scorer inputs are realized stat lines; no projection field is read (directive §6.2) |
| unexplained | 0 | — | per-key deltas sum to every row's delta |

298 of 334 mismatched rows are explained by a single scoring key.

### Per-key decomposition (keys with any disagreement; nflverse − host)

| key (rate) | rows differ | net pts | class |
|---|---|---|---|
| `idp_tkl_solo` (1.33) | 216 | +22.6 | 100 mapping (non-IDP-listed player's tackle dropped); **96 special-teams tackle counted inside nflverse's defensive solo column — `nfl − host` equals the play-by-play `st_tkl_solo` count on all 96 (exact)**, so main pays it twice (column + `st_tkl_solo` supplement); 20 provider charting |
| `idp_tkl_ast` (0.80) | 117 | +61.6 | 91 nflverse over-counts (special-teams assists inside `def_tackle_assists`; the supplement has no `st_tkl_ast` key), 20 under-counts, 6 mapping (non-IDP) |
| `idp_qb_hit` | 10 | −19.1 | provider charting (9 under, 1 over) |
| `idp_pass_def` | 4 | −10.6 | provider charting |
| `idp_def_td` (6.36) | 3 | −19.1 | mapping: defensive fumble-return TD (`fumble_recovery_tds`) never mapped — Knight Jr. wk1, Bates III, Kancey |
| `idp_ff` (4.24) | 4 | −17.0 | 3 mapping (non-IDP-listed), 1 charting |
| `fgmiss_*` / `xpmiss` | 10 | +24.5 | mapping: blocked FG/PAT not scored as a miss (`fg_blocked`, `pat_blocked`) |
| `bonus_fd_rb` / `bonus_fd_wr` | 5 | +5.0 | 3 position vocabulary (host FB, nflverse RB), 2 charting |
| `st_tkl_solo` | 1 | −1.3 | provider charting (the play-by-play count) |

**Zero disagreement, with real activity on both sides:** `rec` (1,409
player-weeks), all six reception-distance bands (`rec_0_4` 615, `rec_5_9` 933,
`rec_10_19` 812, `rec_20_29` 311, `rec_30_39` 116, `rec_40p` 117), `rec_yd`,
`rec_td`, `bonus_rec_wr`, `bonus_fd_te/qb`, `pass_cmp/inc/yd/td/int/sack`,
`rush_*`, `fum_lost` (107), `xpm`, `fgm_yds`, `idp_sack` (323), `idp_sack_yd`,
`idp_tkl_loss` (536), `idp_int` (99), `idp_int_ret_yd`, `idp_fum_rec` (66),
`idp_fum_ret_yd`, `idp_blk_kick` (8), `idp_safe` (1), and the special-teams
return/play keys `kr_yd` (196), `pr_yd` (104), `st_ff` (5), `st_fum_rec` (1).
The full per-key table, including keys with no activity this season (team-DST
keys, `fgmiss_0_19`, `st_td`, `sack_yd` …) is in the JSON (`perKey`,
`pricedKeysWithNoActivity`). `idp_qb_hit` / `idp_pass_def` are the host's alias
spellings of the canonical `idp_hit` / `idp_pd` keys the scorer pays.

## Verdict per historical finding

| finding | verdict | evidence |
|---|---|---|
| **W18-F003** — `realized_points` disagrees with the host on 36% of player-weeks; no reception-distance bands; renamed nflverse columns for pass_int / pass_sack / fum_lost; no kicker scoring | **FIXED** (residual disagreement is 8.2%, not 36%, and none of it is the original causes) | all six bands, `pass_int` (127 rows), `pass_sack` (209), `fum_lost` (107), `xpm` (147), `fgm_yds` (134) show **0 differing player-weeks**. The scorer is the canonical `score_stat_line`; the host-native path is 100%. What remains on the nflverse path is a different set: non-IDP defensive events, blocked kicks, ST tackles, def fumble TDs (below) |
| **W13-F001** — BDVM drops the six reception-yardage bands (WR −19.7%, TE −22.0%) | **FIXED** on the shared realized-points scorer | BDVM's scoring (`src/bdvm/scoring.py`) and in-season actuals both call `compute_weekly_points`; bands agree on every joined row above. **Not measured:** BDVM's *projection-side* stat lines (no `data/bdvm/projections/` snapshot in this checkout); that path uses the same scorer but its inputs are Clay/IDP-Show lines, outside this census |
| **#802** — player-level special-teams scoring (`kr_yd`, `pr_yd`, `st_*`), distinguish from team DST | **PARTIAL** | on 2026 wk 1-8: `kr_yd` 196, `pr_yd` 104, `st_ff` 5, `st_fum_rec` 1, `idp_blk_kick` 8 player-weeks, **0 disagreement**; `st_tkl_solo` 145 / 146 (1 provider charting). Not shown here: `st_td` / return-TD keys had **no events** among rostered players (UNTESTED, not VERIFIED); the 2025 historical re-run #802 asks for is out of scope; the ST/defensive tackle split is still wrong in the *defensive* column (defect below) |
| **#1938 defect 01** — `def_*` dropped for non-IDP-listed players | **STILL_PRESENT on main** | 109 key-instances (WR 60 rows, TE 21, RB 15, QB 10 …), net −154.5 pts; 100 of them `idp_tkl_solo`. With #1938: 6 key-instances remain (−4.8), the unpaid non-IDP assists #1938 documents as its deliberate residual |
| **#1938 defect 02** — blocked FG/PAT not a miss | **STILL_PRESENT on main** | 9 K key-instances, +23.45 pts (K 93.1%). With #1938: 0 (K 99.4%) |
| **#1938 defect 03** — defensive fumble-return TD | **STILL_PRESENT on main** | 3 player-weeks, −19.08 pts. With #1938: 0 |
| **#1938 ST-tackle double pay** (the part #1938 flags for owner review) | **STILL_PRESENT on main; confirmed** | 96 key-instances, +148.96 pts, `nfl − host` equals the pbp `st_tkl_solo` count exactly on all 96. With #1938: 0. Residual (not fixed by #1938, agrees with its description): 91 `idp_tkl_ast` over-counts, +82.4 pts, special-teams assists |
| **#1938 defect 04** — Sleeper-FB / nflverse-RB first downs | **STILL_PRESENT, on main and with #1938** | 3 player-weeks, +3.0 pts; #1938 deliberately leaves it |

## Relationship to PR #1938 (draft, stacked on #1931)

#1938 targets exactly this path (`sleeper_stat_line_from_row`). Its defects 01-03,
the ST-tackle double-pay and the 04 residual all **reproduce on current main
(`53fb2e4d`) on two additional finalized weeks and a fresh `/state/nfl`**, and its
claimed effect reproduces too: this census with #1938's `realized_points.py`
(`d70bdd83`, loaded via `--alt-realized-points`, nothing else changed) moves the
nflverse path from **91.8% → 96.4%** (QB/RB/WR/TE/K all ≥ 99.4%; DL 96.1%, LB 90.8%,
DB 93.2%), mapping-defect rows 121 → 9, no position's agreement worse. The remaining LB/DB gap
is the special-teams-assist over-count plus provider charting of QB hits / PDs /
solo-vs-assist splits — #1938's documented residual. **This PR adds no scorer
change and does not touch `realized_points.py`**; it is the independent
re-measurement #1938 can cite (it differs from Lane A's by being a dated census
over finalized weeks 1-8, joined through the identity owner instead of by
normalized name, and by decomposing per scoring key).

## What this census does not claim

* It measures **rostered** player-weeks; players on no roster are not host-scored.
* It does not measure BDVM's projection side, ROS, or any 2025 history.
* The "mapping defect" rule is deliberately narrow (the row carries the event and
  the normalized key is zero). Nonzero-but-different counts are classed as feed
  disagreement even where one provider is plainly right.
* Special-teams assists are labelled feed over-count on the evidence of #1938's
  analysis; the census itself only shows the over-count, since the play-by-play
  supplement has no `st_tkl_ast` key.
* Fixing any of the above changes BDVM in-season posteriors; that needs its own
  blast-radius measurement and is #1938's (owner-gated) decision, not this PR's.
