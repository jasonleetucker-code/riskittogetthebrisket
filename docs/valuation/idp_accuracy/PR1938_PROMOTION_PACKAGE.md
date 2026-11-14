# PR #1938 promotion package (IDP scorer defects 01/02/03 + special-teams tackle de-duplication)

**Status:** promotion PREPARATION only, per the owner's 2026-11-07 instruction.
Nothing here merges, activates, or changes a flag, BDVM params or league scoring.
The PR stays a draft. Its valuation effects need a separate owner approval once the
production (box) impact evidence exists.

Agent-OS-Receipt: 741230def70b1c94b9924192ee784bb7241b91a6

## 1. Summary

* The scorer change is correct against the host on every corrected case, and the
  out-of-sample checks agree. Oracle: Sleeper's own published stat line, scored by
  the host-native scorer that matches the host exactly. Seasons: 2026 weeks 1-8
  (weeks 7-8 are new), plus 2025 and 2024 in full.
* The nflverse path reproduces the host's points on more player-weeks in every
  sample. Across 44,558 player-weeks in the three samples, exactly **one** becomes
  newly wrong. Details are in §4.
* The `/api/data` market board is unchanged. Under both scorers the contract built
  from `exports/latest/dynasty_data_2026-11-07.json` has 1,103 rows with identical
  `rankDerivedValue`, rank and confidence (`evidence/pr1938_market_board_parity.json`,
  command in §11). The permanent guard is
  `tests/idp_accuracy/test_market_board_does_not_read_realized_points.py` (§5).
* The change moves BDVM, and only BDVM-family surfaces, plus three secondary
  consumers listed in §5.
* **The production BDVM before/after was NOT measured.** The snapshot lives only on
  the box, and this session has no box access. §6 gives the exact read-only
  operator command. The script was smoke-tested in that mode against a local
  emulation, not the box (`evidence/pr1938_box_mode_smoke.json`).
* §6 also gives a **proxy** measurement on a reconstructed-baseline snapshot built
  from public data with the production builder. Its numbers are clearly labelled
  and are not production's.
* Two small defects in the new code were found. Neither was fixed here, because
  each needs a decision (§7, F1/F2):
  * the `max(def_tds, fumble TDs)` hedge is contradicted by host evidence;
  * a non-IDP fumble-recovery TD is paid under the wrong key.

## 2. Merge-update notes

* **Before:** head `d70bdd8337` on base `6662e1cf` (564 commits behind).
* **Merge:** `git merge origin/main` (main `d7db52a43b`) produced a merge commit,
  `3f9d0e76e6`. No rebase and no force-push.
* **Textual conflicts:** none.
  * `src/nfl_data/realized_points.py` is byte-identical to the PR head after the
    merge: main never touched it after `6662e1cf`.
  * `tests/idp_accuracy/test_scoring_events.py` auto-merged. Main's #2016 added
    `encoding="utf-8"` to its existing reads, and the PR's new tests are kept.
* **Semantic conflict, repaired:** main's #2016 guard,
  `tests/test_explicit_text_encoding.py`, failed on three PR-introduced `read_text()`
  calls:
  * `tests/idp_accuracy/test_scoring_events.py:58`
  * `scripts/idp_accuracy/scorer_fix_measure.py:135`
  * `scripts/idp_accuracy/scorer_fix_measure.py:213`

  The fix adds `encoding="utf-8"`, a no-op on Linux. The guard is now 5/5 green.
* **Main changes that touch the same area, all compatible:**
  * #2069 (CW-08 census), which is the independent re-measurement this package cites.
  * #2068 / #2093 (archetype / feature-engineering missing-is-unknown).
  * #1964 (backtest freeze check).
* The PR's committed "before" evidence (Lane A `scorer_reconciliation.json`,
  `MANIFEST.json`) and its `scorer_fix_measure.json` are untouched.

## 3. Per-case verification

Method: `scripts/idp_accuracy/pr1938_case_oracle.py` (new; reads none of the PR's
evidence or census code).

* **Join:** through the identity owner (`resolve_canonical_v2`: the GSIS rung, else
  its exact-name rungs, with fuzzy rungs refused).
* **Oracle:** Sleeper's published stat line for the same player-week.
* **Comparison:** done in **count space, key by key**. It compares the stat line
  `sleeper_stat_line_from_row` emits for the nflverse row (with the play-by-play
  supplement attached, exactly as `weekly_points_from_rows` does) against the
  host's count for that key.
* **Arms:** the scorer at `origin/main` ("before") and the working tree ("after").
* **Seasons:** 2024 and 2025 are scored with the current card. This is a
  scorer-parity test, so host awards are not read.
* **Evidence files:** `evidence/pr1938_case_oracle_2026_w1_8.json`, `…_2025_w1_18.json`,
  `…_2024_w1_18.json`.

Cells read `before → after / n` (player-weeks where the emitted count equals the host's).

| case | claim | 2026 wk 1-8 | 2025 wk 1-18 | 2024 wk 1-18 | verdict / residual |
|---|---|---|---|---|---|
| **Special-teams solo tackles, IDP-listed** (`_defensive_tackle_view` subtraction) | nflverse `def_tackles_solo` includes ST tackles; Sleeper pays them as `st_tkl_solo`. The old path paid them twice | `idp_tkl_solo`: **0 → 564 / 565** | **0 → 1,243 / 1,243** | **0 → 863 / 864** | **Confirmed.** Before, the IDP figure matched the host on *zero* IDP-listed player-weeks with an ST tackle. Residual 1/565: David Walker 2026 wk 6, where nflverse charts one more defensive solo than the host (provider charting, wrong before too) |
| Play-by-play ST count vs host `st_tkl_solo` (the subtraction's input) | "equals Sleeper's on 2,719 / 2,721" | IDP 562/565, non-IDP 207/209 | 1,242/1,243, 420/420 | 863/864, 344/345 | **Confirmed** (see §4 for the 2,719/2,721 reproduction) |
| Special-teams solo tackles, non-IDP-listed | subtraction lets a non-defender's defensive tackles be paid without paying his ST tackles | 209 → 208 / 209 | 415 → 420 / 420 | 343 → 344 / 345 | **Confirmed.** The one count-level regression (Luke Farrell 2026 wk 4) is a play-by-play under-count: pbp saw 1 ST tackle, the host 2. Points still match because both rules pay 1.33 |
| **Non-IDP-listed defensive stats** (defect 01) | the old gate dropped `idp_*` for QB/RB/WR/TE | `idp_tkl_solo` **1 → 143 / 144**; `idp_ff` **0 → 7 / 8**; `idp_blk_kick` **0 → 2 / 2** | solo 4 → 311/315; FF 0 → 11/11; blk 0 → 3/3; sack / QB hit / PD 0 → 1/1 each | solo 5 → 327/332; FF 0 → 10/10; blk 0 → 5/5 | **Confirmed.** Counter-examples: OL / punter solo tackles nflverse charts and the host does not (Zeitler, McKivitz, Fox 2025; 4 in 2024). Colson Yankoff 2026 wk 5 FF: host 1, nflverse 0 (feed gap) |
| **Tackle assists** (stated residual) | ST assists stay inside `def_tackle_assists`; non-IDP assists are withheld | IDP with ST snaps 1,850 → 1,850 / 2,403; without 952 → 952 / 987; non-IDP genuine assists **0 → 0 / 18** | 3,940/5,041; 2,269/2,339; non-IDP 0/63 | 4,235/4,833; 1,950/1,959; non-IDP 0/50 | **Residual confirmed, unchanged by the PR (never newly wrong).** Over-pay to IDP-listed players with ST snaps: 553 of 2,403 player-weeks (2026), 1,101 of 5,041 (2025). Under-pay of genuine non-IDP defensive assists: 18 (2026), 63 (2025). Needs `st_tkl_ast` in the pbp supplement |
| **Blocked FG / PAT** (defect 02) | blocked kick = miss, in the attempt's band (`fg_blocked_list`) | `fgmiss` **4 → 14 / 14**, `xpmiss` **10 → 14 / 14**, every band key 14/14 after | 12 → 33/33, 21 → 33/33, every band 33/33 | 12 → 30/30, 18 → 30/30, every band 30/30 | **Confirmed out of sample.** The unplaceable-distance branch was never needed on any observed row |
| **Defensive fumble-return TD** (defect 03) | `fumble_recovery_tds` capped at defensive recoveries, `max` with `def_tds` | IDP **7 → 13 / 13**; non-IDP 1 → 1 / 1 | IDP 27 → 42 / 43; non-IDP **2 → 1 / 2** | IDP 28 → 44/44; non-IDP 3 → 3/4 | **Confirmed for IDP, with two findings.** **F1:** Isaiah Rodgers 2025 wk 3 had an INT-return TD *and* a fumble-return TD (`def_tds` 1, `fumble_recovery_tds` 1) and the host paid `idp_def_td` **2**, while `max` pays 1 (−6.36). It is the only both-set row in 2024-2026, so the hedge is contradicted by the only evidence there is. **F2:** Tyler Lockett 2025 wk 5 (WR) recovered an opponent fumble for a TD. The host paid `fum_rec_td` 1 (6.00) plus `idp_fum_rec`, not `idp_def_td`. The PR now pays `idp_def_td` (6.36): net +0.36 vs −6.00 before, but under the wrong key. The cap correctly blocks own-team recovery TDs (Woody Marks 2025, James Mitchell 2026) |
| **FB vs RB position** (defect 04) | not the scorer's defect; not changed | `bonus_fd_rb` 4 → 4 / 15 | 3 → 3 / 37 (+ `bonus_fd_te` 0/7) | 0 → 0 / 25 | **Confirmed unchanged, and wider than described.** The PR named Hunter Luepke (nflverse RB / Sleeper FB). The same miss hits every nflverse-**FB** player (Juszczyk, Ingold, Prentice), because `TRUE_POSITION_MAP` maps FB → RB and the host pays an FB no first-down bonus: 11 of 15 FB player-weeks in 2026 wk 1-8. Pre-existing; a separate decision |

## 4. Parity reconciliation, before → after

**Lane A reconciliation, re-run.** This is `scorer_fix_measure.py --base-ref origin/main`
on inputs re-fetched 2026-11-07. Evidence: `evidence/pr1938_scorer_fix_measure_rerun_2026-11-07.json`.

* **Reproduced byte-for-byte:** the Sleeper stats and matchups for weeks 1-6. The
  sha256 values equal Lane A's pins (`0e2453cc…`, `9f4d2663…`, … `3fec893d…`).
* **Changed since the pin:**
  * The nflverse weekly file changed (stat corrections). It still has 6,488 rows,
    but the canonical hash is now `d5a30afd…`, not the pinned `6e4d9de3…`.
  * The pbp artifact was rebuilt through week 8, so its hash is `1746c6a7…`, not
    `46044a82…`.

| measure | PR's committed table | re-run 2026-11-07 |
|---|---|---|
| rostered before | 2,832 / 3,095 (91.5%) | **2,832 / 3,095 (identical, every position)** |
| rostered stage 1 (01/02/03 only) | 2,916 | 2,918 (DL +1, LB +1) |
| rostered after | 2,976 (96.2%) | 2,978 (96.2%); DL 403, LB 463, other positions identical |
| census after: stat-provider / scorer-attributed | 111 / 8 | 109 / 8 |
| wide sample base → after | 5,416 → 5,865 / 6,387, 0 newly wrong | 5,418 → 5,867 / 6,386, **0 newly wrong**, 449 fixed (identical) |
| tackle census, IDP-listed: equal / equal-after-ST-removal / pbp ST = host ST | 2,253 / 440 / **2,719 of 2,721** | 2,253 / 440 / **2,718 of 2,720** |
| tackle census, other | 107 / 162 / 268 of 270 | identical |
| assist census IDP with ST snaps: nflverse > host | 411 / 1,823 | 411 / 1,823 |
| served impact (Δmu_post, wk 1-6) | 373 of 1,642 change; 116 from 01/02/03; 117 ranked | **identical** |

The "2,719 / 2,721" claim reproduces as 2,718 / 2,720. One IDP-listed player-week
left the denominator after an nflverse correction. The two small movements (+2
within tolerance) trace to the same corrections. **Nothing reproduced worse.**

**CW-08 census (main #2069, independent).** It covers 2026 weeks 1-8, rostered
only, with the identity-owner join. Its result: 91.8% → **96.4%** with this PR's
`realized_points.py`. Mapping-defect rows fall 121 → 9, and no position gets worse.

**Independent oracle, points level (new, every player with a stat line).** Within
0.011 of the host-native scorer:

| sample | before | after | newly wrong | fixed |
|---|---|---|---|---|
| 2026 wk 1-6 | 5,457 / 6,428 | 5,910 | 0 | 453 |
| **2026 wk 7-8 (out of sample)** | 1,631 / 1,914 (85.2%) | **1,765 (92.2%)** | **0** | 134 |
| **2025 wk 1-18 (out of sample)** | 15,722 / 18,305 (85.9%) | **17,004 (92.9%)** | **1** | 1,283 |
| **2024 wk 1-18 (out of sample)** | 16,080 / 17,911 (89.8%) | **17,206 (96.1%)** | **0** | 1,126 |

The single newly wrong player-week is Kevin Zeitler (OG) in 2025 week 1. nflverse
charts a solo tackle the host does not, so the PR pays 1.33 for it. By position
the gains concentrate where expected:

| position | 2026 wk 1-8 | 2025 |
|---|---|---|
| LB | 754 → 918 of 1,169 | 1,751 → 2,119 of 2,677 |
| DB | 1,357 → 1,563 of 1,827 | 3,080 → 3,544 of 4,058 |
| K | 468 → 482 of 483 | 1,033 → 1,067 of 1,067 |
| WR | 1,057 → 1,122 of 1,128 | 2,347 → 2,489 of 2,504 |

The baseline rebuild scores the 2023-2025 seasons through this path. 2024 and 2025
use the same unified nflverse schema (`def_tackles_solo`), and the ST subtraction
is 863/864 and 1,243/1,243 there. So a rebuild applies it consistently. **2023 was
not checked.**

## 5. Consumer impact

| consumer | how it reaches the changed function | output changes? | evidence |
|---|---|---|---|
| `/api/data` (`rankDerivedValue`, ranks, confidence) and everything on the market board: trade calculator, finder, suggestions, angle, waivers, FAAB, terminal | no module-level import; one lazy import of a season helper only (see below) | **No** | `scripts/idp_accuracy/pr1938_market_board_parity.py` builds the contract from `exports/latest/dynasty_data_2026-11-07.json` (sha `7d35c88d…`) under each scorer, each in a fresh interpreter: 1,103 rows, 0 differing, table sha `3043fb05…` both (`evidence/pr1938_market_board_parity.json`). Permanent guard: `tests/idp_accuracy/test_market_board_does_not_read_realized_points.py` (below) |
| BDVM in-season posterior: `/api/bdvm/values`, `/roster`, `/trades`, `/trade-eval`; the /rankings Fund-gap column; the /draft BDVM panel | `bdvm.actuals.weekly_points_from_rows` | **Yes** | §6 (proxy measured; production blocked). On today's feed (2026 wk 1-8 plus partial wk 9), 438 of 1,725 players' weekly points change |
| Daily BDVM signal-alert sweep (`bdvm_signal_alerts`) | reads BDVM values | **Yes**, can fire transitions | proxy: 2 rostered transitions immediately, 6 after the baseline rebuild (§6) |
| BDVM reconstructed baseline (`dynasty-bdvm-refresh`, Tue 06:10 UTC) | `bdvm.baseline` scores 2023-2025 | **Yes**, at the next rebuild | proxy arm "after rebuild" (§6) |
| BDVM projection rescoring (Clay / IDP-Show records) | `bdvm.scoring` | **Expected no** for live records. Only a non-IDP-listed record carrying defensive / blocked-kick / fumble-TD columns could move. Two-way records are combined under the DEF position. IDP records get no pbp supplement, so nothing is subtracted, and their assists are unchanged | not measured on the box snapshot. The box run (§6) re-scores projections with each arm's own scorer, so it covers this |
| BDVM record scoring-coverage labels (`source_vocabulary`) | rate probes | **No** for served coverage: `_missing_for_vocabulary` filters by rule family before `engine_fires`, so offense records never list IDP keys | traced |
| `GET /api/player/{id}/realized` (LIVE, `realized_points_api`) | `compute_cumulative_points` with `SeasonPbpIndex` attached | **Yes**, toward the host | traced in `server.py` |
| `/api/league-comparison` (`host_native_scoring` defaults False) | `league_comparison.scoring_engine` over `_translate_stats` rows | **Yes, partly.** Non-IDP solo tackles, sacks and FFs now score. Kicker and fumble-TD keys do not traverse `_FIELD_MAP` (no change). No pbp, so no ST subtraction | traced |
| IDP positional scoring-fit axis (`gameplan._resolve_scoring_fit`, `consensus_edge/scoring_fit`) | `league_intel.scoring_fit` → `league_comparison.scoring_engine` plus pbp | **Yes, small.** The ST subtraction changes tackle volume under both cards; the ratio largely cancels | not measured |
| `model_registry/projection_scorecard` SEASON arm | `weekly_points_from_rows` | **Yes** (evaluation numbers only) | not measured |
| Diagnostics: `nfl_data/scoring_coverage.py`, `bdvm/scoring_census.py` | rate probes | **Yes** (coverage labels for non-IDP IDP keys and blocked kicks) | targeted tests green |
| ROS keyed weekly projections (`src/ros/keyed_weekly_projections.py`) | does not call it; keeps its own IDP-for-offense gate | **No**. Its comment "same scoping as realized_points" is now stale (follow-up) | traced |

**The market-board guard** (`tests/idp_accuracy/test_market_board_does_not_read_realized_points.py`,
3 tests). It asserts what can honestly be asserted:

1. **Module level.** The module-level import closure of `src.api.data_contract`
   excludes `src.nfl_data.realized_points` and `src.bdvm.actuals`. The closure
   counts top-level `try` / `if` imports and package `__init__`s.
2. **Lazy imports.** "Never imported" would be false. Walking the full graph,
   lazy imports included, there is exactly one entry into those modules:
   `league_registry` lazily imports `nfl_projection_season` from
   `src.bdvm.actuals`. That entry is pinned, so a new way in fails the test.
3. **Behaviour, the real guarantee.** The contract built from the newest complete
   archived scrape succeeds with `_score_stat_line`, `sleeper_stat_line_from_row`,
   `host_stat_line` and `weekly_points_from_rows` replaced by functions that raise.
   A mutation that calls `compute_weekly_points` from `_compute_unified_rankings`
   is caught (checked by hand).

## 6. BDVM value impact

### 6a. Production snapshot: BLOCKED (not measured)

* **What is missing:**
  * the box-local projection snapshot `data/bdvm/projections/2026/projections_<date>_*.json`
    (`latest_snapshot_path(2026)`);
  * the box's player context (`data/bdvm/context/`);
  * the events file (`data/bdvm/events/2026.json`);
  * the materialised nflverse weekly cache;
  * the pbp artifact (`data/nfl_data/actuals/pbp_weekly_2026.jsonl`).

  None of these are tracked in git: no snapshot exists in `exports/archive/`,
  `tests/fixtures/` or anywhere in the repo. This session has no box access.
* **Operator steps (read-only).** `scripts/idp_accuracy/pr1938_bdvm_value_impact.py`
  runs inside the deployed app, with nothing written to the app directory:
  1. From a repo checkout, copy the PR head's two files to `/tmp/pr1938/` on the box:
     ```
     git show <PR head>:scripts/idp_accuracy/pr1938_bdvm_value_impact.py > pr1938_bdvm_value_impact.py
     git show <PR head>:src/nfl_data/realized_points.py > realized_points.py
     ```
  2. On the box, as the app user:
     ```
     PYTHONDONTWRITEBYTECODE=1 /home/dynasty/trade-calculator/venv/bin/python \
       /tmp/pr1938/pr1938_bdvm_value_impact.py --app-dir /home/dynasty/trade-calculator \
       --corrected-scorer-file /tmp/pr1938/realized_points.py \
       --cache-only --out /tmp/pr1938/bdvm_impact_box.json
     ```
     The two arms share everything except the scorer:
     * `current` is the deployed `realized_points.py`; `corrected` is the PR's.
     * Both arms read the same snapshot, contract (`exports/latest`), weekly cache,
       pbp, context, events and params.
     * The scorer applies to the in-season actuals and to projection rescoring.

     The script never writes a snapshot, user_kv or anything under `data/`. It
     exits 2 with `BLOCKED:` when there is no snapshot or no materialised weekly rows.
  3. Paste back `/tmp/pr1938/bdvm_impact_box.json`. It names players and roster ids,
     never managers. At minimum, paste back:
     * `receipts`
     * `current_vs_corrected.values` → `valueChanged`, `rankChanged`,
       `absDeltaPctAmongChanged`, `rankMove`, `byPosition`, `replacementCurrent` /
       `replacementCorrected`, `topMoversRosteredByAbsDelta`, `signalFlips`,
       `alertTransitionsRostered`
     * `current_vs_corrected.tradeScan`
     * `current_vs_corrected.rosters`
* **Smoke test (local emulation, not the box).** Evidence:
  `evidence/pr1938_box_mode_smoke.json`, which has both runs' receipts and a hash of
  each run's `current_vs_corrected` block. The setup:
  * a detached `origin/main` worktree as `--app-dir`;
  * the PR file as the corrected scorer;
  * a scratch snapshot holding the reconstructed baseline;
  * `--cache-only`.

  Its `current_vs_corrected` block hashes identically to dev mode's on the same
  snapshot (`cab61c0b…` both). Afterwards the emulated app dir showed only the
  copied inputs and `__pycache__`; `find data -newer …` listed nothing. This does
  not prove behaviour on the real box, whose snapshot, context and events differ.
* **Not covered by the script:** the baseline-rebuild stage on the box. Use a dry
  run of the builder if wanted; it is not needed for the approval decision.

### 6b. Proxy measurement (dev mode, NOT production values)

Evidence: `evidence/pr1938_bdvm_value_impact_proxy.json`, from
`pr1938_bdvm_value_impact.py --proxy-baseline --proxy-rebuilt-arm`.

* **Snapshot:** 3,012 reconstructed-baseline records, built in memory with the
  production builder (`fetch_and_build_baseline`, 2023-2025, pbp joined) and scored
  with the **current** scorer.
* **Contract:** `exports/latest/dynasty_data_2026-11-07.json`.
* **Actuals:** today's 2026 feed, 8,500 rows, weeks 1-8 plus a partial week 9.
* **What is missing vs production:** no Clay / IDP-Show real records and no player
  context (neutral priors). So the values are not production's; the mechanism,
  direction and rough size are.

| | current → corrected (deploy only) | current → corrected **after next baseline rebuild** |
|---|---|---|
| priced players | 861 / 861 | 861 / 861 |
| balanced value changed (>0.5) | 325 | 754 |
| \|Δ%\| among changed: median / p90 / max | 2.2% / 19.2% / 131% (max is a near-replacement player) | 3.2% / 19.2% / 388% |
| changed ≥5% / ≥10% | 107 / 69 | 284 / 155 |
| BDVM rank move: median / p90 / max; top-100 in/out | 2 / 10 / 64; 1 in, 1 out | 4 / 19 / 80; 1 in, 1 out |
| replacement fpg changes | K 9.336 → 9.186; RB 10.195 → 10.243; worst-starter LB 12.477 → 12.402, QB 17.458 → 17.480; DB/DL/WR/TE unchanged | every group moves: DB 11.132 → 11.089, DL 8.883 → 8.847, K → 9.106, LB 11.748 → 11.703, QB 16.963 → 17.004, RB 10.195 → 10.340 (slots 38 → 37), TE 7.114 → 7.186, WR 10.011 → 9.920 (slots 46 → 47) |
| BUY/HOLD/SELL flips | 2 (BUY → STRONG_BUY Gracen Halton DT; SELL → STRONG_SELL Quentin Lake S) | 6 |
| alert transitions on rostered players (upper bound for one sweep) | **2** (2 rosters) | **6** (4 rosters) |
| double-positive trade scan (top 40) | 35 unchanged, 5 replaced | 34 unchanged, 6 replaced |
| roster strategy capital (balanced) | about ±1% per roster (e.g. +471 on 46,333); no direction flips | similar; no direction flips |

By position, deploy only (changed, up/down, mean |Δ| in value points):

| position | changed | up / down | mean \|Δ\| |
|---|---|---|---|
| WR | 62 | 51 / 11 | 37.0 |
| TE | 34 | 19 / 15 | 20.8 |
| RB | 104 | 14 / 90 | 6.0 (replacement rose) |
| QB | 8 | 7 / 1 | 25.7 |
| LB | 57 | 15 / 42 | 18.0 |
| S | 38 | 12 / 26 | 34.1 |
| CB | 21 | 11 / 10 | 20.1 |
| EDGE | 4 | 0 / 4 | 28.4 |
| DT | 2 | 2 / 0 | 161.6 |

Largest rostered movers:

| player | position | value change | rank |
|---|---|---|---|
| Gracen Halton | DT | +18.6% | 103 → 83 (fumble-return TD) |
| Ja'Marr Chase | WR | +6.5% | 25 → 22 |
| Drake London | WR | +7.6% | 42 → 36 |
| Jonas Sanker | S | +13.4% | — |
| Elijah Ponder | LB | +15.8% | — |
| Caleb Downs | S | −11.3% | — |
| Malaki Starks | S | −10.6% | — |
| Emmanuel McNeil-Warren | S | −12.3% | — |

## 7. Risks and findings

* **F1 (low).** The defect-03 `max(def_tds, fumble TDs)` hedge under-pays a week
  with both TD types. The only such row in 2024-2026 is Rodgers 2025 wk 3, where the
  host paid 2, and nflverse `def_tds` excludes fumble-return TDs in every observed
  row. **Recommended fix:** `def_tds + min(fumble_recovery_tds, recoveries)`, a
  one-line change with a test. Not changed here; it is an implementation-owner /
  owner call.
* **F2 (low).** A non-IDP-listed player's fumble-recovery TD is paid as
  `idp_def_td` (6.36). The host paid Lockett 2025 wk 5 as `fum_rec_td` (6.00). It
  occurred once in 2024-2026. Net error after the PR: +0.36 (before: −6.00).
* **F3 (low).** Provider / pbp charting gaps now surface as counts on non-IDP rows:
  * OL / punter solo tackles nflverse charts and the host does not (1 newly wrong
    point-week in 2025, 0 in 2024 and 2026);
  * pbp missing a special-teams recovery (Damien Lewis 2025 wk 10) or tackle
    (Farrell 2026 wk 4).
* **F4 (low, robustness).** `int(_num(fg_blocked))` raises on a NaN cell, where
  `main` silently propagated NaN.
  * NaN can only arrive through the `nfl_data_py` ingest rung (pandas). Production
    uses `nflverse_direct`: CSV strings, with `'NA'` mapped to 0
    (`docs/ops/P1_BDVM_INGEST_PRODUCTION_CLOSURE_2026-08-20.md`).
  * If the provider ever switched, the actuals fetch would raise. `bdvm_api` would
    then serve preseason values with a warning instead of NaN points.
  * Re-confirm `/api/status → nflDataProvider.active_provider == nflverse_direct` at
    release. A NaN-safe `_num` is a cheap follow-up.
* **Alert wave.** At most a handful of BDVM transitions on deploy, and again after
  the Tuesday rebuild (proxy: 2, then 6). Alerts that have been sent cannot be recalled.
* **No flag.** Rollback is revert + deploy (§9).
* **Residuals are unchanged, never made worse:**
  * the ST-assist over-pay (IDP-listed) and the unpaid genuine non-IDP assists;
  * the FB first-down bonus miss.
* **Unchecked:** 2023, the oldest baseline season; projection rescoring on the box
  snapshot (covered by the §6a run).

## 8. Recommendation for the owner to consider

**This is not an approval.** Merging #1938 and activating its valuation effects both
need the owner's **separate, explicit approval**, given after the §6a box evidence
exists. Nothing in this package authorizes either step.

> Recommendation for the owner to consider: once the §6a box run is attached and CI
> is green on the updated head, approve #1938 with the special-teams tackle
> de-duplication (01/02/03 + ST rule together). Deploy on a Monday (UTC) so the
> Tuesday 06:10 baseline rebuild lands the second stage within a day, and decide F1
> first.

Why ship them together: the ST rule is required for 01 to be correct on non-IDP
rows. On IDP-listed rows the old path matched the host on **zero** player-weeks
with an ST tackle, and the corrected path matches on 99.9% across three seasons.

## 9. Rollback

* **Path:** revert the PR's merge commit on `main` (`git revert -m 1 <merge sha>`,
  or `git revert <squash sha>`) through a normal PR. The Deploy Production pipeline
  restarts both services.
* **Reverts automatically on restart:**
  * BDVM in-season actuals (the actuals and values caches are process-memory, keyed
    per day / inputs);
  * `/api/player/{id}/realized`;
  * league comparison;
  * the scoring-fit memo.
* **Does NOT revert automatically:**
  1. **A baseline snapshot built while the PR was live.** It is an immutable, dated
     file under `data/bdvm/projections/2026/` and stays latest until a later
     rebuild. Run `scripts/refresh_bdvm_projections.py` on a later UTC day (a
     same-day rerun is a no-op) or wait for the next Tuesday timer.
  2. **Alerts already sent.** The sweep's last-seen state holds the corrected
     signals, so the revert can fire a second transition back. The 12 h minimum
     interval (`_MIN_NOTIFY_INTERVAL_HOURS`) limits repeats.
* **Emergency stop without a revert:** `RISKIT_FEATURE_BDVM_ENGINE=0` + restart.
  This turns off all of BDVM (the `/api/bdvm/*` endpoints 503) and does not affect
  `/api/player/realized`.

## 10. Owner decisions still needed

1. **Approve activation** after the §6a box evidence: the PR's valuation effect.
2. **Ship the special-teams tackle rule with 01/02/03?** Recommended **yes** (§8).
   The alternative is `stage1` (subtract only for non-IDP), which keeps the measured
   double-pay on IDP-listed players.
3. **F1:** fold the `def_tds + fumble TDs` sum into this PR before merge, or as a
   follow-up.
4. **`st_tkl_ast` follow-up:** a pbp supplement schema bump plus an artifact rebuild,
   to close the assist residual (2026 wk 1-8: 553 over-paid IDP player-weeks,
   18 unpaid non-IDP).
5. **Defect 04 / FB:** whether to join Sleeper's position into
   `weekly_points_from_rows` or map nflverse FB to a no-bonus position (11 of 15 FB
   player-weeks wrong, 2026 wk 1-8).
6. **Optional narrow flag** around the ST rule (the earlier review's suggestion).
   Not needed on the evidence, but it would make rollback deploy-free.

## 11. Reproduce

| step | command |
|---|---|
| tests | `python -m pytest tests/idp_accuracy tests/bdvm tests/nfl_data tests/scoring -q` → **1,631 passed, 3 skipped, 1 xfailed** (W13-F003, pre-existing) |
| wider consumer suites | `tests/league_comparison tests/model_registry tests/league_intel tests/ros tests/roster_intel tests/public_league tests/league_valuation tests/waivers` → 6,002 passed, 0 failed |
| encoding guard | `tests/test_explicit_text_encoding.py` → 5 passed |
| formatter | `bash scripts/format_python_changes.sh` → GREEN. Ruff **0.6.9**, the version pinned in `requirements-dev.txt` and enforced by that script; the global `ruff` on this machine is 0.16.9 and was not used |
| new tests | `python -m pytest tests/idp_accuracy/test_market_board_does_not_read_realized_points.py tests/idp_accuracy/test_pr1938_bdvm_value_impact.py -q` → 8 passed |
| market-board parity | `python scripts/idp_accuracy/pr1938_market_board_parity.py --export exports/latest/dynasty_data_2026-11-07.json --out docs/valuation/idp_accuracy/evidence/pr1938_market_board_parity.json` → 1,103 rows, 0 differing (exit 1 if any row differs) |
| Lane A re-run | `python scripts/build_pbp_weekly.py --seasons 2026 --complete-through-week 8 --out-dir data/idp_accuracy/pbp_weekly`, prime `data/idp_accuracy/cache` with the public Sleeper GETs, then `python scripts/idp_accuracy/scorer_fix_measure.py --base-ref origin/main --out <file>` |
| case oracle | `python scripts/idp_accuracy/pr1938_case_oracle.py --out <file>` (add `--season 2025 --weeks 1 … 18`; needs `build_pbp_weekly.py --seasons <season>`) |
| proxy BDVM | `python scripts/idp_accuracy/pr1938_bdvm_value_impact.py --proxy-baseline --proxy-rebuilt-arm --out <file>` |

**Test coverage of the new scripts:**
* `pr1938_bdvm_value_impact.py`: its pure diff logic (`diff_payloads`,
  `_trade_keys`, `_rostered`) is unit-tested in
  `tests/idp_accuracy/test_pr1938_bdvm_value_impact.py`. Its `main` (snapshot /
  network) is exercised only by the runs above.
* `pr1938_case_oracle.py` and `pr1938_market_board_parity.py` are **untested
  research scripts** (network / subprocess). Their outputs are the committed
  evidence JSONs.

## Result contract

* **STATUS:** PARTIAL. Every offline validation is done. The production BDVM
  before/after is blocked on box access.
* **UNRESOLVED:**
  1. the §6a box run;
  2. owner decisions 1-6 (§10);
  3. CI on the updated head;
  4. 2023 not checked.
* **NEXT_ACTION:**
  1. Run the §6a command on the box and attach the JSON.
  2. The owner decides §10.
