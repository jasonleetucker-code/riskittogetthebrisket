# Scoring parity taxonomy: nflverse path vs host-native scoring (2026-11-08)

**Status:** research / evidence only. No served scoring, value, rank, flag or public output is
changed. **Authority:** owner master directive 2026-11-08 section 7 Priority 2 (exact league
scoring parity). **Does not authorize** merging or activating PR #1938 (owner-reserved; it
changes BDVM in-season values). PR #1938 was evaluated read-only in a throwaway worktree.

Reproduce (both trees, identical pinned inputs):

```
python scripts/idp_accuracy/scoring_parity_taxonomy.py --out <main.json> --label main
# in a throwaway detached worktree of origin/claude/idpa-scorer-defect-fixes (never merged):
python scripts/idp_accuracy/scoring_parity_taxonomy.py --out <pr1938.json> --label pr1938
```

Committed evidence: `docs/valuation/idp_accuracy/evidence/scoring_parity_taxonomy_{main,pr1938}.json`.
The script reuses `scorer_reconcile.reconcile_host` / `reconcile_nflverse` (the census behind the
"91.5%" figure) and adds one deterministic classifier, `classify_exception`.

## 1. What was compared

| item | value |
|---|---|
| truth | Sleeper `players_points` (`/league/<id>/matchups/<week>`), every rostered player-week, starters and bench |
| league / card | `dynasty_main` = `1312006700437352448`; fingerprint `sf1:9e51824690d091f9` (asserted by the script) |
| sample | 2026 REG weeks 1-6, 4,171 rostered player-weeks; 3,710 have a Sleeper stat line; 3,095 join to an nflverse row and are scored |
| host-native scorer | `compute_weekly_points(source="sleeper")`: **3,710 / 3,710 within 0.01**, max abs 0.0044. This is the oracle for everything below |
| nflverse path | `weekly_points_from_rows` as `bdvm_api` runs it: normalize + play-by-play supplement + canonical scorer |
| nflverse rows | 6,488 REG rows; canonical sha256 `d5a30afd...c577a`; file sha256 in the evidence JSON |
| pbp artifact | sha256 `abde7c89...adb36c`, weeks 1-6 |
| Sleeper responses | league, players, rosters, 6 matchups, 6 stat dumps: sha256 of each recorded; identical between the two trees (test-pinned) |
| trees | main `3602f31f6` realized_points sha `1a6e8b4f...`; #1938 head `678ffa663` sha `080540a1...` |

Input drift, stated plainly: the nflverse rows' canonical hash is **not** the `6e4d9de3` Lane A recorded
on 2026-10-25. nflverse revised week 1-6 rows since (the feed is live and unpinned), moving the
"before" figure from 2,832 to **2,834** of 3,095 (91.57%). The taxonomy run pins its rows in a gitignored
cache and hashes them, so both trees saw the same rows.

## 2. Taxonomy: every mismatching player-week, one class each

Points are `nflverse path - host` for a scored mismatch; for identity rows (no nflverse points exist) they are
minus the host award. `abs` is the sum of absolute points. 3,095 scored + 53 unjoined identity rows; 1,023
further rows are awarded 0 by the host and absent from nflverse (agree, not mismatches).

| class | main: n | main: net / abs pts | #1938: n | #1938: net / abs pts |
|---|---:|---:|---:|---:|
| implementation_error | 137 | -8.4 / 216.5 | 0 | 0 / 0 |
| source_data_disagreement | 91 | +16.3 / 110.8 | 91 | +16.3 / 110.8 |
| missing_stat_category | 9 | +3.7 / 29.2 | 0 | 0 / 0 |
| incorrect_player_identity | 53 | -561.3 / 561.3 | 53 | -561.3 / 561.3 |
| incorrect_position_classification | 3 | +3.0 / 3.0 | 3 | +3.0 / 3.0 |
| irreconcilable_provider_semantics | 21 | +31.1 / 41.8 | 23 | +12.8 / 20.8 |
| unavailable_evidence | 0 | 0 | 0 | 0 |
| rounding | 0 | 0 | 0 | 0 |
| unexplained | 0 | 0 | 0 | 0 |
| **total mismatching** | **314** | | **170** | |
| **within 0.01 (of 3,095 scored)** | **2,834 (91.6%)** | | **2,978 (96.2%)** | |

By side (counts; offense = QB/RB/WR/TE/K/FB):

| class | main IDP | main offense | #1938 IDP | #1938 offense |
|---|---:|---:|---:|---:|
| implementation_error | 62 (+104.0) | 75 (-112.5) | 0 | 0 |
| source_data_disagreement | 89 (+16.7) | 2 (-0.3) | 89 | 2 |
| missing_stat_category | 2 (-12.7) | 7 (+16.5) | 0 | 0 |
| incorrect_player_identity | 41 (-425.7) | 12 (-135.7) | 41 | 12 |
| incorrect_position_classification | 0 | 3 (+3.0) | 0 | 3 |
| irreconcilable_provider_semantics | 16 (+36.5) | 5 (-5.3) | 18 (+16.8) | 5 (-4.0) |

Exact-match rate by position (joined, scored):

| pos | main | #1938 | | pos | main | #1938 |
|---|---:|---:|---|---|---:|---:|
| QB | 95.5% | 99.5% | | DL | 94.1% | 95.5% |
| RB | 97.3% | 99.8% | | LB | 84.7% | 90.8% |
| WR | 93.2% | 99.5% | | DB | 87.6% | 92.3% |
| TE | 93.2% | 99.6% | | K | 93.4% | 99.2% |

### Subclasses and the code line behind each

| class : subclass | main n | cause / location (main) | #1938 |
|---|---:|---|---|
| implementation_error : idp_gate_non_idp_listed_player | 80 | `src/nfl_data/realized_points.py:696` `if _is_idp_position(pos):` emits `def_*` stats only for IDP-listed positions; Sleeper pays `idp_*` to anyone (-117.8 pts) | fixed |
| implementation_error : special_teams_tackle_paid_twice | 62 -> +104.0 | `:708` `_tackle_view` takes nflverse solo tackles, which include special-teams tackles, then the `st_tkl_solo` supplement pays them again | fixed (subtracts the supplement count) |
| missing_stat_category : blocked_kick_not_a_miss | 7 | no mapping of `fg_blocked` / `pat_blocked` to `fgmiss_*` / `xpmiss` (+16.5 pts, all kickers) | fixed |
| missing_stat_category : defensive_fumble_return_td | 2 | `fumble_recovery_tds` not mapped to `idp_def_td` (-12.7) | fixed |
| incorrect_position_classification : FB_vs_nflverse_RB | 3 | nflverse lists Hunter Luepke RB, Sleeper FB; the first-down bonus is position-keyed and the card prices no FB first down (+3.0) | open (needs Sleeper's position as an input; `TRUE_POSITION_MAP` also maps nflverse FB to RB) |
| incorrect_player_identity : identity_join_miss / name_collision_dropped | 28 / 25 | name key does not resolve to exactly one nflverse player; production drops colliding names by design (-561.3 host pts unmatched, mostly DBs) | open, by design |
| irreconcilable_provider_semantics : special_teams_assists_lumped | 16 -> 18 | nflverse `def_tackle_assists` includes special-teams assists the host does not pay; the supplement has no `st_tkl_ast` | open |
| irreconcilable_provider_semantics : non_idp_listed_assists_inseparable | 5 | same cause on non-IDP-listed players; with the gate repaired the assist can be neither paid nor withheld correctly | open (the deliberate residual in #1938) |
| source_data_disagreement : unattributed_solo_assist_split | 77 (68 assist + 9 solo) | a solo/assist count differs and no independent evidence says why: a provider gamebook split, **or the same special-teams-assist defect as F1** (+42.1 net pts). Not proven provider disagreement | open |
| source_data_disagreement : idp_hit / idp_pd | 8 / 4 | QB-hit and pass-defended charting differ (-14.8 / -10.6) | open |
| source_data_disagreement : bonus_fd_wr / st_tkl_solo | 1 / 1 | provider first-down / special-teams tackle charting | open |

**Two caveats on attribution (independent review).**

1. *The assist split is a proxy.* The `special_teams_assists_lumped` rows (16 / 18) are identified by a special-teams SOLO tackle count in the supplement, which is not assist evidence; the supplement has no assist data. The 77 `unattributed_solo_assist_split` rows (68 assist-dominant, 9 solo-dominant) are therefore an upper bound on how many more rows are really F1: up to 77 of the 91 `source_data_disagreement` rows may be the same defect, and the true split between provider disagreement and F1 is unknown until an `st_tkl_ast` key exists.
2. *Counts are by dominant key, not cause.* Class and subclass are assigned from the single key with the largest |host - nflverse| points. Rows where several keys differ (29 on main, 8 after #1938; `multiKey` in the evidence; 8 of them in the unattributed split) are counted once under that key. A solo-to-assist reclassification, for example, appears under whichever of the two moved more points.

No mismatch was `rounding`, `unavailable_evidence` or `unexplained`. The classifier is a function of the
row's own evidence (key differences, supplement counts, listings), never the player; its branches are
unit-tested in `tests/idp_accuracy/test_scoring_parity_taxonomy.py`. Two judgment calls are labelled:
a position split only counts when the key's rate is position-scoped (every IDP rate on this card is
position-agnostic); and a non-IDP-listed player's assist is "inseparable" rather than a code defect because
un-gating it would trade an under-pay for an over-pay.

## 3. Category coverage per scorer

Hand-computed tests: `tests/idp_accuracy/test_scoring_parity_categories.py` (127 passing, 2 strict xfail).
Every one of the 58 nonzero card keys a player can earn has a literal-expected case on **both** scorers
(offense incl. all six reception bands, position first-down bonuses, WR reception bonus, pass cmp/inc,
2-point conversions, return yardage, special-teams events, kicking, and every IDP rule); a completeness test
fails if a card key lacks a case. 28 team-defense keys (`pts_allow*`, `yds_allow`, `def_*`, `int`, `sack_yd`,
`safe`, `fum_rec*`, ...) are TEAM_ONLY: the host scorer refuses team entries, and none was ever paid to a
player in 2026 wk 1-6.

| scorer | does not score | how it fails |
|---|---|---|
| host-native | nothing on the card: it is a dot product over Sleeper's own keys (3,710 / 3,710) | a team entry returns `None`; a supplement is refused with `ValueError` |
| nflverse, weekly feed only | the 10 play-by-play keys: six `rec_*` bands, `st_tkl_solo`, `st_ff`, `st_fum_rec`, `pass_int_td` | **fails closed**: listed in `unscored`, total is a labelled partial (test-pinned) |
| nflverse + supplement (production) | `st_tkl_ast` (does not exist); defects 01-04 on main | **silent**: pays the lumped assist; the four defects score 0 (already strict-xfail in `test_scoring_events.py`) |

### Strict-xfail findings (served behaviour untouched)

* **F1** `test_special_teams_assists_are_not_paid_as_defensive_assists`: ST assists are paid as defensive
  assists (16 rows, +36.5 pts on main; 18 rows, +16.8 after #1938). Needs an `st_tkl_ast` supplement key
  (schema bump + artifact rebuild).
* **F2** `test_a_row_with_no_position_does_not_silently_score_defensive_stats_as_zero`: a row with no
  position scores every `def_*` stat 0 with nothing in `unscored` (missing is never zero). Latent: the 6 of
  6,488 position-less rows are nameless and skipped upstream. Plain bug outside #1938's stated scope, but #1938 un-gates `def_*` for every row and so resolves it
  incidentally (verified on #1938's tree), hence an xfail conditioned on main only, so it becomes a plain passing test automatically once #1938 lands.

## 4. Downstream impact on BDVM in-season values (descriptive)

BDVM blends realized PPG as `mu_post = w*mu_prior + (1-w)*mu_recent`, `w = n_prior/(n_prior+weeks)`
(`src/bdvm/ros.py`, `config/bdvm/params_v1.json`), so `d mu_post = (1-w) * d PPG` whatever the projection.
Measured on every player with an nflverse row and a Sleeper line (1,621 players, same weeks; GSIS id where
Sleeper has one, else unique normalized name; 111 rows unjoinable):

| | players moved by > 0.01 / 0.1 / 0.25 / 0.5 pts/game | mean abs | max |
|---|---|---:|---:|
| **today (main)**, IDP (844) | 377 / 299 / 172 / 48 | 0.118 | 0.86 |
| today, offense (777) | 128 / 118 / 21 / 7 | 0.031 | 0.87 |
| today, all (1,621) | 505 / 417 / 193 / 55 | 0.076 | 0.87 |
| **remaining gap after #1938**, IDP | 297 / 172 / 30 / 1 | 0.049 | 0.53 |
| remaining, offense | 24 / 10 / 4 / 1 | 0.005 | 0.71 |
| remaining, all | 321 / 182 / 34 / 2 | 0.028 | 0.71 |

So #1938 removes roughly 36% of players with a >0.01 gap and 82% of those above 0.25, but the residual
(provider assist/solo splits, charting) still moves ~20% of players by more than 0.01. Value-level movement
(Fund gap, strategy currencies, BUY/SELL signals) needs the box-local projection snapshot and is measured in
#1938's `pr1938_bdvm_value_impact.py`; this section is the scoring-input gap only. The largest residual moves
(Colson Yankoff 0.71, A.J. Terrell 0.53) were not traced and may be join artifacts.

## 5. Release decision brief: PR #1938 (owner-reserved, not merged here)

**What it fixes.** Four defects in `sleeper_stat_line_from_row`/`_tackle_view` on the nflverse path: `def_*`
stats dropped for non-IDP-listed players (80 player-weeks), blocked FG/PAT not charged as a miss (7),
defensive fumble-return TD unpaid (2), and special-teams tackles paid twice (62, the part that moves
IDP-listed players). On identical inputs the exact-match rate rises 2,834 -> 2,978 of 3,095 (91.6% -> 96.2%),
with all 146 implementation/missing-category rows cleared (the two assist residual classes grow by 2 rows,
which is the five non-IDP-listed assists the repair surfaces). **What remains:** 170 mismatches: 91 provider
solo/assist/charting disagreements, 53 identity rows, 23 inseparable special-teams assists, 3 FB/RB. IDP is
still the weak side (LB 90.8%, DB 92.3%). **Blast radius.** `/api/data`, `rankDerivedValue` and ranks are
unchanged (the market board does not read this path). It changes BDVM's realized-PPG input: the `mu_post` gap to host scoring falls from 505 to 321
players above 0.01 and from 417 to 182 above 0.1, mostly IDP downward (special-teams double count removed)
and offense slightly up; it flows to Fund gap, `/api/bdvm/*`, the Draft BDVM panel, strategy currencies and the daily BDVM
signal-alert sweep, and the next baseline rebuild rescoring prior seasons. Four older tests asserting the old
gate as policy were rewritten. **Rollback.** Revert the PR (`realized_points.py`, `clay_projections.py` and tests) and restart; no
data migration, schema or flag. The nflverse rows and pbp artifact are untouched. **Recommendation for the
owner:** approve as a unit but decide the special-teams tackle rule (62 rows, the only part changing
IDP-listed values) knowingly; treat the st-assist residual, FB/RB and identity classes as follow-ups. Before
activation, run `pr1938_bdvm_value_impact.py` on the box snapshot to size value-level movement.

## 6. Verification state

TESTED_IN_PR. Offline, deterministic tests only (`tests/idp_accuracy`); the live Sleeper/nflverse run is a
research script whose inputs are pinned by hash. Not verified here: value-level BDVM movement (box snapshot),
the two identity classes' root cause per player, and predictive skill (this is scoring correctness, not
forecasting accuracy).
