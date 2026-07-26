# League Settings Audit — dynasty_main (Sleeper 1312006700437352448)

Generated 2026-07-26. Sources compared:
- **hostApi** — live `GET /v1/league/1312006700437352448` (snapshot:
  `config/league_intel/sleeper_league_snapshot_2026-07-26.json`)
- **screenshot** — user-supplied screenshot evidence (spec §3)
- **repository** — `config/leagues/registry.json` rosterSettings

Verdict: **hostApi and screenshots agree on every visible setting.**
The repository registry is STALE on roster structure (P1 finding below).

## Roster structure

| Setting | hostApi | screenshot | repository | status |
|---|---|---|---|---|
| teams | 12 | 12 | 12 | match |
| QB / RB / WR | 1 / 2 / 3 | 1 / 2 / 3 | 1 / 2 / 3 | match |
| TE | **2** | 2 | **1** | **CONFLICT — repo stale** |
| FLEX (W/R/T) | 2 | 2 | 2 | match |
| SUPER_FLEX | 1 | 1 | 1 | match |
| K | **1** | 1 | **absent** | **CONFLICT — repo stale** |
| DL / LB / DB | **3 / 3 / 3** | 3 / 3 / 3 | **2 / 2 / 2** | **CONFLICT — repo stale** |
| IDP_FLEX | **0** | 0 | **2** | **CONFLICT — repo stale** |
| Starters total | 21 | 21 | 15 | **CONFLICT** |
| Bench | 37 | 37 | — (rosterSize 30) | **CONFLICT — repo stale** |
| Roster size | 58 | 58 | 30 | **CONFLICT — repo stale** |
| taxi_slots | **0** | unknown (§3.11) | 5 | **CONFLICT — repo stale**; resolves §3.11: NO taxi |
| reserve_slots | **0** | unknown (§3.11) | — | resolved: NO IR; pool = 58×12 = 696 exactly |
| best_ball | 1 | best ball | true | match |
| playoff_teams | 7 | unknown | — | resolved |
| playoff_week_start | 15 | unknown | — | resolved |
| draft_rounds | 6 | unknown | — | resolved (matches draft-capital assumption) |
| waiver_type / budget | 2 (FAAB) / $100 | unknown | FAAB $100 assumed | match |

**P1 impact:** any consumer reading `registry.json` rosterSettings models
the WRONG lineup (missing K, 1 TE instead of 2, 6 IDP+2flex instead of 9
fixed IDP, roster 30 vs 58). Consumers to verify before fixing: ros
lineup/team-strength starter slots, FAAB `analyze_roster`, angle/trade
roster math, frontend roster-constraint UI. Fix + consumer tests = task LI-1.

## Scoring — hostApi vs screenshot (all match)

Key confirmations and §3 question resolutions:

| Area | hostApi keys | Resolution |
|---|---|---|
| Pass yds | `pass_yd: 0.0333…` (=1/30) | matches 1pt/30yd |
| Completions / incompletions | `pass_cmp 0.15` / `pass_inc -0.22` | match |
| INT / pick-six | `pass_int -4` AND `pass_int_td -2` | **separate keys → a pick-six = −6 total (stacks). Verify empirically in golden tests (LI-2)** |
| First downs | generic `pass_fd`/`rush_fd`/`rec_fd` all **0**; `bonus_fd_qb 0.67`, `bonus_fd_rb/wr/te 1.0` | position-based bonuses are the ONLY first-down scoring. Sleeper semantics: `bonus_fd_<pos>` awards per first down GAINED by that player (rush or reception; QB also passing) — verify stacking empirically in LI-2 |
| Reception distance | `rec 0.08` + `rec_0_4 0.17`, `rec_5_9 0.42`, `rec_10_19 0.67`, `rec_20_29 0.92`, `rec_30_39 1.17`, `rec_40p 1.92` | Sleeper bands key on RECEPTION YARDAGE GAINED on the play. Hypothesis: base `rec` stacks with band (0.25/0.50/0.75/1.00/1.25/2.00 effective) — golden tests must confirm |
| Rushing | `rush_att 0.08`, `rush_yd 0.1`, `rush_td 6` | match |
| Fumbles | `fum 0`, `fum_lost -4`, `fum_rec_td 6` | match |
| Kickers | `fgm 0` + `fgm_yds 0.07` (pure per-yard, NO base make points — resolves §3.9), `xpm 2.31`, `xpmiss -3.15`, miss bands −4.55…−1.05 | match; `fgmiss_50p` 0 with `fgmiss_50_59 −1.75` + `fgmiss_60p −1.05` populated |
| IDP | `idp_sack 2.92`, `idp_sack_yd 1/9`, `idp_qb_hit 2.13`, `idp_tkl_solo 1.33`, `idp_tkl_ast 0.8`, `idp_tkl_loss 4.25`, `idp_int 5.32`, `idp_int_ret_yd 1/9`, `idp_pass_def 5.32`, `idp_ff 4.25`, `idp_fum_rec 3.19`, `idp_fum_ret_yd 1/9`, `idp_safe 5.32`, `idp_blk_kick 5.32`, `idp_def_td 6.38` | all match screenshots; stacking (sack+TFL+solo+yds on one play) to be confirmed in golden tests |
| ST player | `st_td 6`, `st_ff 4.25`, `st_fum_rec 3.19`, `st_tkl_solo 1.33`, `kr_yd`/`pr_yd 1/30` | match |
| Bonuses (10+ tkl, 2+ sack, 3+ PD, 40/50yd TDs, yardage milestones) | all **0** | resolved: none active |
| Team DEF keys | `pts_allow*`, `yds_allow*`, `def_*` populated | **irrelevant — no DEF roster slot**; note only |

## Open questions — RESOLVED 2026-07-26 (LI-2 golden validation)

All empirical stacking questions are answered in
`SCORING_VALIDATION.md` (1,415/1,415 player-weeks reconcile as a pure
dot product over shared stat keys; verdicts frozen as golden tests in
`tests/league_intel/`):

- Pick-six: **stacks** — `pass_int` + `pass_int_td` both charge (−6
  total under 2026 rates).
- First-down bonuses: **`bonus_fd_<pos>` is itself a precomputed stat
  key** (= first downs gained; QB variant includes passing FDs).
- Reception base+band: **stacks mechanically** (zero-exception dot
  product); direct nonzero-rate confirmation pends first scored 2026
  week because the 2025 `rec` base rate was 0.
- IDP multi-event: **all events on a play stack** (sack + sack yds +
  QB hit + TFL + solo).
- `idp_blk_kick` vs `blk_kick`: **no double-count** — individual
  defenders only ever carry `idp_blk_kick`; `blk_kick` is a TEAM/DEF
  stat this league can't roster.
- Rounding: host per-player scores are 2-decimal; scorer comparisons
  use 0.01 tolerance.

Still open (not scoring): tie handling among equivalent legal
best-ball lineups (affects LI-3 optimizer validation only, not
totals).

**Registry fix landed** (LI-1, same PR as this update): dynasty_main
rosterSettings now match the live truth (TE 2, K 1, DL/LB/DB 3,
IDP_FLEX 0, rosterSize 58, taxiSize 0, 21 starters); every consumer
verified in `tests/league_intel/test_registry_consumers.py`.
