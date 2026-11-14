# IDP accuracy — Deliverable A: scoring accuracy and the shared research manifest

**Lane:** A (scoring and data correctness). **Directive:**
`docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md` §6A / §6B.
**Status:** research only. No production code, scoring, value, rank, source, flag or
public output is changed by this lane.

## Verdict

**`SCORER_DISCREPANCIES`** — split by scorer path, because two production paths score
this league and they do not agree with Sleeper equally well:

| path | used by | result vs Sleeper `players_points` (2026 wk 1–6) |
|---|---|---|
| **host-native** `compute_weekly_points(..., source="sleeper")` over Sleeper's own stat line | Investigation B; the scorer the 2026 research reads | **VERIFIED**: 3,710 / 3,710 scored player-weeks within 0.01 (max \|Δ\| 0.0044, Sleeper's own 2-dp rounding). 461 more had no stat line and were awarded 0. Zero exceptions. |
| **nflverse** `src.bdvm.actuals.weekly_points_from_rows` (the BDVM in-season blend via `bdvm_api`), default `source="nflverse"` + play-by-play supplement | BDVM in-season posterior; BDVM realized-PPG baseline; scoring census | **DISCREPANCIES**: 2,832 / 3,095 joined, scored player-weeks within 0.01 (91.5%). Four genuine scorer defects (92 player-weeks), 171 stat-provider disagreements, 53 identity-join failures. Every mismatch is attributed; none is unexplained. |

Consequence for the other lanes: **performance claims built on Sleeper-native scoring
(Investigation B's method) rest on a verified scorer.** Anything built on the nflverse
path — in particular BDVM in-season fundamentals — inherits the defects and the
provider differences below, and IDP is where they concentrate (LB 84.5%, DB 87.6%,
DL 93.8% exact vs RB 97.3%, QB 95.5%).

## Pinned inputs (all in `MANIFEST.json`)

| input | value |
|---|---|
| repo | pinned `bdbc83a1f` (2026-10-25); built at `af616f531`, which differs only in 10 `data/scrape_state/*_last_success` stamps — `CSVs/`, `config/`, `src/` git tree ids identical |
| league | `dynasty_main` = Sleeper `1312006700437352448` (registry resolves to the same id); season 2026, `in_season` |
| scoring fingerprint | **`sf1:9e51824690d091f9`** (`scoring_fingerprint()`, `src/league_comparison/sleeper_scoring.py`); identical to the archive's own `sleeper.scoringSettings` |
| roster-format fingerprint | **`rf1:10f897578eea2fe4`** (roster_positions, num_teams, taxi/reserve slots, best_ball, type) |
| served archive | `exports/archive/dynasty_export_20261025_120337.zip`, sha256 `50fb251a…c8dc8f6`, scrape 2026-10-25T12:03:37Z; enabled scrapers KTC + IDPTradeCalc complete, DraftSharks files preserved (not refetched) |
| served board | rebuilt by `build_api_data_contract`: 1,107 rows (540 offense / 429 IDP / 138 picks), 1,008 priced, 740 ranked, 47 quarantined; `servedBoardSha256` `4e6ba1f5…7d8712` — **identical when rebuilt in a clean worktree at the pinned SHA** |
| statistics cutoff | 2026 REG weeks 1–6 (Sleeper `last_scored_leg` 6); week 7 in progress and excluded |
| projections | **UNAVAILABLE** — `data/bdvm/projections/` is box-local and absent here |
| model versions | BDVM `params_v1:01af672b2aff`; fair value `league_fair_value_v1:1ba0dfff046b`; best-ball `bestball_marginal_v1` / `48a3a5cdd4fa884b`; `bridges_v1`; package model `geom_q078_v1` (each with file sha256) |
| datasets | sha256 of every Sleeper response used (league, rosters, 6 matchups, 6 weekly stat dumps, player directory), the canonical-JSON sha256 of the 6,488 nflverse rows scored, and the play-by-play artifact |

## Owner checklist — verified from the snapshot

All 14 items pass; **no discrepancy**. 12 teams; 58 roster spots (21 starters + 37 BN);
best ball on; slots exactly QB, RB×2, WR×3, TE×2, FLEX×2, SUPER_FLEX, K, DL×3, LB×3,
DB×3; 9 IDP starters (108 league-wide); no IDP_FLEX; `taxi_slots` 0; `reserve_slots`
0; `pass_td` 6; tiered reception present; TFL (4.24) and PD (5.30) priced above a
solo tackle (1.33).

**Reception tiers are by catch LENGTH, not volume**: every catch pays `rec` 0.10 plus
one of `rec_0_4` 0.25 / `rec_5_9` 0.50 / `rec_10_19` 0.75 / `rec_20_29` 1.00 /
`rec_30_39` 1.25 / `rec_40p` 2.00, plus `rec_yd` 0.10. Only the nflverse path needs
play-by-play to know the length; Sleeper's line carries the tier keys directly.

**TE premium: none.** `bonus_rec_te` 0.0; `bonus_fd_te` = `bonus_fd_wr` =
`bonus_fd_rb` = 1.0; the only position reception bonus is `bonus_rec_wr` 0.02 (a tiny
WR premium). TE scarcity here is the two TE starting slots, not scoring. The served
board, however, is anchored on KTC **TE++** boards and lifts non-TEP sources' TEs onto
that basis (ADR-015, `te_premium.convert_te_value`) — so served TE values embed a
TE-premium-scoring market price this card does not pay. Whether two required TE slots
earn a comparable premium is a lineup-utility question for Lanes C/D; it is not a
scoring fact, and no lane should assume the uplift is earned by scoring.

IDP price ratios (per solo tackle): sack 2.20, TFL 3.19, PD 3.98, QB hit 1.59, assist
0.60. A 1-sack / 1-TFL / 1-QB-hit play pays 9.28 + sack yards (1/9 per yard).

## B — scorer verification (host-native path)

Truth: Sleeper's `players_points` from `/league/<id>/matchups/<week>`, which lists every
rostered player (starters and bench).

* **Coverage:** 4,171 rostered player-weeks over 72 team-weeks; 0 roster entries lacked
  an award.
* **Investigation B reproduced exactly:** its filter (stat line present, `gp > 0`)
  gives **3,299 / 3,299 within 0.01, max 0.0044** — the same numbers it reported.
* **Extended:** dropping the `gp > 0` filter adds 411 lines (all within tolerance);
  the remaining 461 player-weeks have no Sleeper stat line and were all awarded 0.0
  (byes rise from week 5: 59, 48, 61, 57, 105, 131 by week).
* **By position** (n, all within 0.01): QB 309, RB 499, WR 773, TE 340, K 122, FB 5,
  DL 486, LB 572, DB 604.
* **Independent oracle:** a from-scratch Σ rate × stat agrees with the production
  scorer on every row, so agreement is not an artifact of one implementation.
* **Exception census:** empty.

### Stat stacking — derived, not assumed

Of 251 player-weeks with a sack plus a TFL or QB hit, the awarded points match the
**stacked** prediction (every key paid) on **251 / 251** and the un-stacked alternative
(TFL / hit not paid on the sack play) on **0 / 251**. Stacking lives in the STAT feed:
of 330 sack player-weeks, 295 carry TFL ≥ sacks and 319 carry QB hits ≥ sacks.
Combined `idp_tkl` is priced 0, so it never double-pays solo + assist.

### Lineups and multi-position eligibility

* The exact solver (`src/ros/lineup.py`) over Sleeper's own per-player points
  reproduces **72 / 72** Sleeper best-ball team totals exactly (max \|Δ\| 0.000).
  Over our computed points: 72 / 72 within 0.015 (max 0.0122 = 21 starters' 2-dp
  rounding accumulating; 67 / 72 within 0.01).
* All **1,510** Sleeper-chosen starter slots are legal under
  `player_eligible_for_slot`; 0 violations.
* Sleeper really does use the second `fantasy_positions` entry: it started LB-listed
  players at DL 38 times, DL-listed at LB 14 times, DB-listed at LB twice.
* Rostered multi-position players today: 52 DL/LB, 3 DB/LB, 1 DB/WR. No rostered
  player's listed position falls outside his `fantasy_positions` family.
* Caveat: `fantasy_positions` comes from today's `/players/nfl`; Sleeper publishes no
  dated eligibility history, so a mid-season change is invisible.

## nflverse path — exception census (3,095 joined, scored player-weeks)

| category | n | attribution |
|---|---|---|
| match (≤ 0.01) | 2,832 | — |
| **IDPA-DEFECT-01** | 80 | **scorer defect**: `sleeper_stat_line_from_row` drops `def_*` stats when the listed position is not IDP; the nflverse row has them and Sleeper pays `idp_*` to any player (a WR's tackle / forced fumble after a turnover). Net −117.8 pts, offense only |
| **IDPA-DEFECT-02** | 7 | **scorer defect**: a blocked FG (`fg_blocked`) / PAT (`pat_blocked`) is not scored as a miss; Sleeper scores `fgmiss_<band>` / `xpmiss`. Net +16.45 pts, kickers |
| **IDPA-DEFECT-03** | 2 | **scorer defect**: a defensive fumble-return TD (`fumble_recovery_tds`) is not mapped to `idp_def_td`. −12.72 pts (Demetrius Knight Jr. wk1, Jessie Bates III wk5) |
| **IDPA-DEFECT-04** | 3 | **scorer defect (position vocabulary)**: a player Sleeper lists FB but nflverse lists RB has first downs paid as `bonus_fd_rb`; Sleeper prices no FB first down. +3.0 pts (one player) |
| stat-provider disagreement | 171 | **not scorer**: the providers chart events differently — solo tackles (95 rows), assists (87), QB hits (9), PDs (4), one ST tackle (play-by-play derived), one WR first down. 169 are IDP (LB 78, DB 65, DL 26); net **+154.3 pts nflverse over Sleeper** (Σ\|Δ\| 251.9) |
| identity: name collision dropped | 25 | by design in `weekly_points_from_rows` (two players, one normalized name): Byron Murphy II / Byron Murphy Jr., Byron Young, Justin Jefferson, Marcus Harris |
| identity: join miss | 28 | name forms differ (Cam Bynum, Dax Hill, Dru Phillips, Josh Uche, Joshua Metellus, Joshua Palmer, Matt Hibner, Zonovan Knight); 20 of 28 are DB/LB |
| no nflverse points, awarded 0 | 1,023 | consistent (no event either side) |

Exact-match rate by position on the nflverse path: QB 95.5%, RB 97.3%, WR 93.2%,
TE 93.2%, K 93.4%, **DL 93.8%, LB 84.5%, DB 87.6%**.

The four defects are pinned as `xfail(strict=True)` in
`tests/idp_accuracy/test_scoring_events.py` (01, 02 ×2, 03); 04 is a caller
position-vocabulary choice with no clean synthetic unit test and is recorded here only.
**Not fixed in this lane** (owner-reserved: scoring-path changes move BDVM numbers).

## Event-level tests

`tests/idp_accuracy/test_scoring_events.py` — 32 pass, 4 strict xfail. Every
expectation is derived from the pinned card in `MANIFEST.json`: solo/assist/combined
tackles, TFL, sack + sack yards, QB hit and alias collapse, PD and alias collapse and the
zero-priced 3-PD bonus, INT / FF / FR with return yards, pick-six, safety, blocked kick,
special-teams plays and return TD, sack stacking (cited to the awarded-data evidence),
IDP stats paid to an offensive player, 6-pt passing TD, all six reception-length tiers,
the WR-only reception bonus, negative fumble, precomputed totals never scored, team-DST
entries refused rather than zeroed, the nflverse IDP path, and Sleeper eligibility
(DL/LB hybrid, single-position LB, DB/WR two-way, solver placement, plus the
1,510-slot and 72 / 72 evidence pins).

## Reproduce

```bash
python scripts/idp_accuracy/scorer_reconcile.py --nflverse   # writes evidence/scorer_reconciliation.json
python scripts/idp_accuracy/build_manifest.py                # writes MANIFEST.json (needs the evidence)
python -m pytest tests/idp_accuracy -q
```

Public Sleeper GETs are cached once under the gitignored `data/idp_accuracy/cache/`
(throttled < 5 req/s); `--offline` reuses them. The nflverse weekly file is fetched live
(`nflverse_direct` does not cache it) — the manifest's canonical row hash says whether a
re-run scored the same rows. **Sleeper stat corrections or a re-published nflverse file
can change a re-run**; the pinned checksums are the reference.

## Fix lane — IDPA-DEFECT-01/02/03 repaired in `realized_points.py` (stacked PR)

**Status:** the nflverse path now fixes the three scorer defects above; this section
supersedes the "pinned as `xfail`" wording for them. It CHANGES BDVM in-season
values and needs owner / integration review. Evidence:
`evidence/scorer_fix_measure.json`, produced by
`python scripts/idp_accuracy/scorer_fix_measure.py` (same pinned rows, cache and pbp
artifact; the "before" is this document's committed reconciliation, reproduced
exactly). Everything here is the nflverse path only; the host-native path is untouched.

| defect | verdict | what changed |
|---|---|---|
| 01 `def_*` dropped for non-IDP-listed | **fixed**, with one deliberate residual | defensive stats are read for every row. Solo tackles are nflverse's solo count **less the play-by-play special-teams count** (nflverse charts special-teams tackles too; Sleeper pays them as `st_tkl_solo`). `idp_blk_kick` is also un-gated (both 2026 blocked punts by non-IDP players were paid by the host). **Residual:** tackle *assists* stay IDP-only, because special-teams assists cannot be separated (5 rostered player-weeks still unpaid) |
| 02 blocked FG / PAT | **fixed** | a blocked kick is a miss: `xpmiss`, `fgmiss` and the distance band from `fg_blocked_list` (23 yd -> 20-29 ... 62 yd -> 60+, plus `fgmiss_50p`) |
| 03 defensive fumble-return TD | **fixed** | `fumble_recovery_tds`, capped at defensive recoveries and `max`-ed with `def_tds`, pays `idp_def_td` |
| 04 Sleeper-FB / nflverse-RB first downs | **not a scorer defect; not changed** | the scorer is faithful to the position it is handed (`"FB"` pays no `bonus_fd_*`, `"RB"` pays the RB rate). nflverse lists Hunter Luepke RB, Sleeper lists him FB, and Sleeper's listing is not an input on the in-season path. Repair means joining Sleeper's position into `weekly_points_from_rows`: a new cross-provider input, not a scorer repair. Related, pre-existing and separate: `TRUE_POSITION_MAP` maps an nflverse-listed FB to RB (documented in `realized_points.py`, 6 more player-weeks in the wide sample) |

### Found while fixing: special-teams tackles were double-paid to IDP-listed players

Un-gating 01 exposed that nflverse's tackle columns include special-teams tackles. Over
the 6,387 player-weeks that join to a Sleeper stat line (rostered or not), the
play-by-play special-teams count equals Sleeper's `st_tkl_solo` on 2,719 / 2,721
IDP-listed player-weeks, and nflverse's solo count equals Sleeper's `idp_tkl_solo`
**only after** removing it on 440 more. The base scorer paid those tackles twice
(`idp_tkl_solo` from the weekly column, `st_tkl_solo` from the supplement). The
rostered reconciliation above filed ~60 of them under "stat-provider disagreement";
they were ours. The same one-line rule that makes 01 correct (subtract the
special-teams count) is therefore applied to every position, not only to non-IDP
players. This is the part of the change most worth reviewing: it moves IDP-listed
players, not just receivers (see impact below). Withholding it from IDP-listed
players restores the 01/02/03-only behaviour (`stage1` in the evidence).

**Remaining residual (unfixed, measured):** nflverse's `def_tackle_assists` also lumps
in special-teams assists that Sleeper pays nothing for. nflverse exceeds Sleeper's
`idp_tkl_ast` on 411 of 1,823 IDP-listed player-weeks with special-teams snaps (16 of
732 without) and on 161 of 169 non-IDP player-weeks with them. The supplement carries
only `st_tkl_solo`; closing this needs a `st_tkl_ast` key (schema bump + artifact
rebuild), so it is left as a follow-up rather than guessed at.

### Before -> after, rostered reconciliation (3,095 joined player-weeks within 0.01)

| position | before | stage 1 (01/02/03, IDP tackles untouched) | after |
|---|---|---|---|
| QB | 190 / 199 | 198 | 198 |
| RB | 396 / 407 | 406 | 406 |
| WR | 577 / 619 | 616 | 616 |
| TE | 260 / 279 | 278 | 278 |
| K | 114 / 122 | 121 | 121 |
| DL | 396 / 422 | 396 | 402 |
| LB | 431 / 510 | 432 | 462 |
| DB | 467 / 533 | 468 | 492 |
| FB | 1 / 4 | 1 | 1 |
| **all** | **2,832 (91.5%)** | **2,916 (94.2%)** | **2,976 (96.2%)** |

Census after: 111 stat-provider disagreements (was 171), 8 scorer-attributed (5 = the
deliberate non-IDP assists, 3 = defect 04), 25 + 28 identity. The wide sample
(6,387 player-weeks, host-native scorer as truth): 5,416 -> 5,865 within 0.01 (84.8% ->
91.8%), **0 player-weeks newly wrong**.

### Served impact

BDVM blends realized PPG into its posterior as
`mu_post = w * mu_prior + (1 - w) * mu_recent` (`src/bdvm/ros.py`), so a change in a
player's weekly points moves `mu_post` by `(1 - w) * dPPG` whatever his projection is.
`/api/data` and `rankDerivedValue` do not read this path and do not change. The
projection snapshot is box-local, so BDVM `run_valuation` outputs on a pinned snapshot
are **UNAVAILABLE** here; the evidence reports the part that does not need it. On the
pinned week 1-6 rows, 373 of 1,642 players with samples change (116 from 01/02/03 alone):
LB 115, S 86, CB 45, EDGE 12, DT 4 (almost all **down**, mean |d mu_post| about 0.2-0.25
points/game: removed special-teams double-count) and WR 42, TE 21, RB 13, QB 7 (all
**up**, about 0.13-0.21: defensive events now paid) and K 9 (down 0.24: blocked kicks now
charged). 117 of the changed players are ranked on the served board. Value-level movement (replacement levels, z-stats, Fund gap, signal
alerts) follows from these `mu` shifts and needs the box snapshot to quantify.

## Limitations

* In-sample by construction: this verifies scoring arithmetic on realized weeks; it
  says nothing about predictive accuracy.
* One season (2026), six weeks. Earlier seasons were scored under different cards
  (Investigation B: 2025 card differs), so this is not a multi-season scorer audit.
* Eligibility is today's directory, not a dated history.
* The nflverse "stat-provider disagreement" class is attributed by comparing the two
  normalized stat lines; which provider is correct per play is not adjudicated.
  Sleeper's numbers are what this league is scored on.
