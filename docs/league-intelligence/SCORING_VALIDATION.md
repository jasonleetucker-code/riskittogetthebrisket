# Scoring Validation — empirical golden results (LI-2)

Generated 2026-07-26.  Validates `src/league_intel/scorer.py` against
Sleeper's own awarded scores.

## Ground truth used

The 2026 season had **no scored weeks** at validation time
(`/v1/state/nfl`: week 0, season_type `off`), so the host-awarded
ground truth is the league's completed **2025 season**
(`previous_league_id` 1180092661344120832, status `complete`, 10
teams).  Sources, all fetched live 2026-07-26 at ≤1 req/s:

- `GET /v1/stats/nfl/regular/2025/{week}` — raw per-player stat lines
- `GET /v1/league/1180092661344120832/matchups/{week}` — host-awarded
  `players_points`, `starters_points`, `points`
- `GET /v1/league/1180092661344120832` — the 2025 scoring settings

The 2025 league uses the **same scoring-key vocabulary** as 2026 but
different rates (e.g. `rec` base was 0, `idp_tkl_solo` 1.38 vs 1.33,
`bonus_rec_te` 0.35 vs 0).  Rates are inputs to the scorer, so golden
tests validate the *mechanics* at the host's own numbers; the 2026
rates are applied by the same validated mechanism.

## Headline result — Sleeper scoring is a pure dot product

For **1,415 of 1,415** rostered player-weeks across weeks 1, 8 and 17
of 2025:

    host players_points  ==  Σ stat_line[k] × scoring_settings[k]
                            k ∈ stat_line ∩ scoring_settings

within |Δ| ≤ 0.011 (host rounds per-player scores to 2 decimals).
Zero failures, zero special cases.  There is **no exclusion, banding
precedence, or de-duplication logic** in Sleeper's engine: every stat
key present in the payload that has a scoring rate is awarded,
independently.  Team totals: `points == Σ starters_points` exactly on
every audited matchup entry, and re-scoring both frozen team fixtures
from raw stat lines reproduces the matchup `points`.

## Empirical stacking verdicts (all frozen as golden fixtures)

| Question (SETTINGS_AUDIT open item) | Verdict | Evidence |
|---|---|---|
| Pick-six: `pass_int` + `pass_int_td` stack? | **YES — stacks.** The stat payload carries both keys on a pick-six (`pass_int` counts the INT, `pass_int_td` the return TD). 2026 rates: −4 + −2 = **−6 total**. | 2025 w1 J.J. McCarthy (`pass_int 1`, `pass_int_td 1`) reconciles only when both are charged; also w17 pid 421 (`pass_int 3`, `pass_int_td 1`). Fixture: `pick-six QB`. |
| `bonus_fd_*` semantics — which stat drives it? | **The stat payload itself carries `bonus_fd_qb/rb/wr/te` as precomputed keys** equal to first downs *gained* by that player: `bonus_fd_rb == rush_fd + rec_fd` (5/5 samples), `bonus_fd_qb == pass_fd + rush_fd + rec_fd` (5/5). Generic `pass_fd`/`rush_fd`/`rec_fd` rates are 0 in this league, so the position bonuses are the only first-down scoring, exactly as audited. | Week-1 2025 stat payload probes; all golden QB/RB/WR/TE fixtures include the keys. |
| `rec` base + distance band stack? | **YES — mechanically confirmed** (co-present keys always both award; bands `rec_0_4 … rec_40p` are per-reception counts keyed on the catch's yardage, and do NOT necessarily sum to `rec` — e.g. a negative-yardage catch falls outside all bands). Caveat: the 2025 rate for base `rec` was 0.0, so the base term contributed 0 in every golden week; the stacking of `rec` specifically is inferred from the proven zero-exception dot-product mechanics, not from a nonzero-rate observation. Flagged for direct re-confirmation after 2026 week 1. | 1,415/1,415 dot-product reconciliation incl. every base+derivative pair (`pass_int`/`pass_int_td`, `fgm`/`fgm_yds`, `idp_sack`/`idp_sack_yd`, `fgmiss`/`fgmiss_50_59`). |
| IDP multi-event plays stack? | **YES — all events on one play award.** A sack play emits `idp_sack` + `idp_sack_yd` + `idp_qb_hit` + `idp_tkl_loss` + `idp_tkl_solo` (+`idp_tkl`) simultaneously and each nonzero rate scores. | 2025 w1 pid 10970 (sack + TFL + QB hit + 7 sack yards + 2 solo) reconciles exactly; Myles Garrett w8 (64.5 pts) golden fixture. |
| `idp_blk_kick` vs `blk_kick` | **No double-counting.** Individual defenders only ever carry `idp_blk_kick`; the plain `blk_kick` stat appears exclusively on TEAM/DEF pseudo-rows (`SEA`, `TEAM_SEA`, …), which this league cannot roster (no DEF slot). The 2026 `blk_kick 1.0` rate is inert for rostered players. | All block events in weeks 1/8/17 2025 partitioned cleanly by entity type. |
| Kicker scoring | Pure per-yard confirmed end-to-end: `fgm` rate 0 (zero-point component), `fgm_yds` per-yard, miss bands stack with base `fgmiss`. | Boswell w8 (17.01) and McLaughlin w1 (2.38, includes a miss) fixtures. |

## Golden fixture set (committed, `tests/league_intel/fixtures/`)

16 archetype player-weeks picked from **actual 2025 league rosters**
(`golden_player_weeks.json`, host-awarded expected points):

pocket QB (Jordan Love w8), rushing QB (Lamar Jackson w1), sack-prone
QB (Max Brosmer w17, negative total), pick-six QB (J.J. McCarthy w1),
pass-catching RB (Jahmyr Gibbs w1), early-down RB (Derrick Henry w17),
possession WR (Ja'Marr Chase w8), deep threat (Romeo Doubs w1),
receiving TE (Trey McBride w17), kicker (Chris Boswell w8), kicker
with miss (Chase McLaughlin w1), tackle LB (Blake Cashman w17), edge
(Myles Garrett w8), interior DL (Cameron Heyward w8), box safety
(Xavier McKinney w17), ballhawk corner (Xavier Watts w17).

Plus 2 full team weeks (`golden_team_weeks.json`): roster 1 week 1
(361.05, 22 starters — the 2025 lineup had 22 slots early season) and
roster 3 week 17 (283.78, 17 starters), validated by summing the
scorer's per-starter outputs from raw stat lines.

`scoring_settings_2025.json` freezes the 2025 rates the fixtures were
awarded under.

## What could NOT be validated (do not treat as confirmed)

- **Base `rec` stacking at a nonzero rate** — see caveat above;
  mechanically implied, directly unconfirmed until a 2026 week scores.
- **2026 rates end-to-end** — no 2026 host-awarded scores exist yet.
  First scored 2026 week should be reconciled the same way (the
  fixture-builder methodology in this doc reapplies directly).
- **Rounding at display boundaries** — host per-player scores are
  2-decimal; we pin |Δ| ≤ 0.011 per player and Σ(0.006 × starters) for
  team sums.  Sleeper's exact internal rounding step (per-stat vs
  per-total) is indistinguishable at this tolerance and does not
  affect any downstream use.
- **Mid-season 2025 lineup change** — matchup week 1 shows 22
  starters, week 17 shows 17; both team fixtures validate under their
  own starter lists, but 2025 lineup *structure* is otherwise not a
  model for 2026 (which is the canonical 21-slot snapshot).
