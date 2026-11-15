# BDVM correctness (Batch 3 Unit J1) — 2026-10-01 (LOCAL)

Two objective-correctness repairs to the BDVM projection/realized scoring lane,
following the [2026-10-01 scoring census](../scoring-census-2026-10-01/README.md):

1. **IDP fumble recovery** — `idp_fum_rec` / `idp_fum_ret_yd` read the wrong
   nflverse column. Host-golden proven, fixed. **This changes values** (see the
   board diff below).
2. **Source vocabulary → per-player coverage** — every projection source now has an
   explicit capability declaration (`src/bdvm/source_vocabulary.py`), and each
   player's `unscoredKeys` / `projection.scoringCoverage` reports what that player's
   sources cannot publish. Reporting only: no projected point changes.

Scope is LOCAL: no owner/production session. Sleeper data is the PUBLIC API,
read-only (`GET /v1/league/<id>`, `/v1/league/<id>/matchups/<wk>`,
`/v1/stats/nfl/regular/2025/<wk>`, `/v1/players/nfl`).

## 1. Host-golden: which nflverse column is `idp_fum_rec`?

`host_golden.py` → `host_golden.json`. dynasty_main's 2025 league
(`1180092661344120832`, card `idp_fum_rec` 3.3 / `idp_fum_ret_yd` 1/9 /
`st_fum_rec` 3.3), REG weeks 1-18 (stats) and 1-17 (matchups), nflverse
`stats_player_week_2025` rows and the 2025 play-by-play supplement. Joins:
gsis id, else a unique (week, normalized name) in the same position family (any
IDP family counts as one; offense/defense-crossing names are dropped — a WR
"DJ Turner" joined by name alone to the CB "DJ Turner" is the measured trap).

| claim | result |
|---|---|
| host `idp_fum_rec` == nflverse `fumble_recovery_own` | 21 / 244 IDP player-weeks |
| host `idp_fum_rec` == `fumble_recovery_opp` | 223 / 244 |
| host `idp_fum_rec` == `opp − st_fum_rec` (host's ST stat) | **244 / 244** |
| … with the play-by-play-derived `st_fum_rec` | **244 / 244** (PBP ST == host ST on 244/244) |
| host `idp_fum_ret_yd` == `fumble_recovery_yards_opp` | 63 / 65 (2 mismatches, −15 vs 0 and 13 vs 11; cause NOT traced — charting difference, special-teams return, or a host floor at 0 are unverified hypotheses) |
| host `idp_fum_ret_yd` == `fumble_recovery_yards_own` | 0 / 65 |
| host pays both rules on its own line (players_points − rescoring without them == line scored with only them) | 7,140 / 7,140 rostered player-weeks |
| **engine** vs host-awarded FR points, rostered IDP with any recovery activity — BEFORE | **1 / 92** |
| engine — AFTER, PBP supplement attached | **92 / 92** (max abs delta 0.0044) |
| engine — AFTER, weekly feed only | 91 / 92 (the one special-teams recovery, paid at the IDP rate) |

Four host recoveries were unjoinable (no gsis id, no unique same-family name) and
are dropped, not guessed. Season totals over the joined IDP rows: host 210, own 16,
opp 231, host ST 21.

**Why `opp − ST`.** nflverse's `fumble_recovery_opp` counts every recovery of an
opponent's fumble, defensive and special-teams (a gunner recovering a muffed
punt). Sleeper pays the latter under `st_fum_rec`, not `idp_fum_rec`.
`fumble_recovery_own` is a defender recovering his own team's fumble (a
teammate's botched return), which the host does not pay at all.

**The fix** (`src/nfl_data/realized_points.py::_idp_fumble_recovery_view`):

* a row already carrying the host's own `idp_fum_rec` (the league-comparison
  translation keeps Sleeper's keys) is taken as-is — ST-exclusive by the host's
  definition, never reduced a second time;
* else `fumble_recovery_opp − pbp.st_fum_rec` when the play-by-play supplement is
  attached (exact);
* else `fumble_recovery_opp` whole. The weekly feed cannot split ST from defense,
  so a defender's ST recovery is paid at the IDP rate while `st_fum_rec` stays
  reported `unscored` (21 of 231 IDP opponent recoveries in 2025). Pinned, not
  hidden, by the fixture test. On both dynasty_main cards the two rates are equal
  (3.3/3.3 in 2025, 3.19/3.19 in 2026), so the total is unaffected there.

Consistent everywhere the column is named: IDP Show `FR` → `fumble_recovery_opp`
(`src/bdvm/idpshow_projections.py`; it used to land on `_own`, so every projected
IDP Show recovery would have scored zero after the fix), the league-comparison
Sleeper→nflverse map, the coverage probe's maximal row, and the census finding
(marked resolved).

Fixture: `tests/nfl_data/fixtures/idp_fumble_recovery_host_golden_2025.json` —
numbers only (nflverse columns, PBP ST count, host stats, host-awarded FR points)
for the 92 rostered player-weeks; no names or ids. Test:
`tests/nfl_data/test_idp_fumble_recovery_host_golden.py` (RED 4 of 7 before the fix).

## 1b. Value change (disclosed) — `board_diff.json`

Same harness as #1574 (`../scoring-census-2026-10-01/board_diff.py`), pinned:
code `07c9b635e` (clean) vs base `0f9ed7072`'s `realized_points.py`, each in its
own process; dynasty_main; reconstructed baseline from nflverse 2023-2025 under the
contract's card, PBP supplement for 2025 only (2023/2024 take the weekly-only
`opp` path); contract built from `exports/latest/dynasty_data_2026-09-30.json`;
in-season = 2026 weeks 1-3 actuals.

| board | priced | players changed | rank changes | max abs delta (balanced) | max rank move | top-200 membership |
|---|---|---|---|---|---|---|
| preseason | 739 / 739 | 667 | 603 | +277.9 (James Pearce EDGE 5275 → 5553, rank 17 → 17) | 39 | none |
| in-season | 739 / 739 | 623 | 552 | +235.2 (Will Anderson EDGE 5566 → 5801) | 69 | Andrew Van Ginkel / Deebo Samuel swap across 200 |

1,651 baseline records' fpg move (max 0.418/game). IDP positional means rise
(CB 8.33 → 8.38, LB 8.81 → 8.89, EDGE 7.71 → 7.78, S 8.02 → 8.12, DT 5.82 → 5.89);
offense means are unchanged. Every value move of note is a defender; QB/TE/WR
balanced values move 0.0 (their ranks change as defenders pass them); RB moves by
at most 6.9 (preseason) / 2.3 (in-season) with fpg unchanged — **cause not
verified**, the same unexplained RB-specific secondary effect #1574 recorded
(likely flex-aware replacement); treat any explanation as a hypothesis. In-season,
some defenders fall (Kamari Lassiter CB −0.28 fpg, −219) — consistent with
own-team recoveries the old mapping paid (not traced per player). **Not measured:** Clay / IDP Show real projections (no local
snapshot — IDP Show FR projections move by the adapter fix), rookie priors, context
feed, events, production. The production delta needs an owner/production session.

## 2. Source vocabulary → coverage

`src/bdvm/source_vocabulary.py` is the one owner (the census's vocabulary
derivations moved here; `scoring_census` re-exports them). Declared sources:
`clayProjections` (stat line; offense pass/rush/receiving, IDP solo/assist/sack/INT;
first downs imputed), `idpShowProjections` (stat line; whatever columns the capture
publishes), `reconstructedBaseline` and `rookieDraftSlotPrior` (fpg-only
realized proxies). Anything else (a manual CSV) is `undeclared` and is read off the
columns its records carry.

Per record: a stat-line record lists every nonzero card rule for its position
family that the realized engine can score and no column on the line can move; a
proxy carries the realized engine's own unscored rules (`declared_unscored`,
persisted in the snapshot as `declaredUnscored`); a proxy written before this
(no declaration) or a source-scored points record is **`unverifiable`** — never
shown fully scoreable. `ConsensusProjection` gains `source_coverage` and
`coverage_status`; the payload gains `projection.scoringCoverage` per player and
`meta.scoringCoverage.playersByStatus` / `unscoredKeysBySource` /
`sourceCapabilities`. `weightSign` and the sign-aware "may be positive or negative"
wording are kept. Play-by-play-only rules are now scoped by rule family (a
reception band is no longer listed for a cornerback unless his record carries
offense columns).

### Coverage before → after, by measured 2025 impact (`coverage_report.json`)

"Before" = what `unscoredKeys` reported (play-by-play rules only, position-blind;
proxies reported nothing). Points = the census's realized 2025 points for that
family, SIGNED.

**dynasty_main (IDP)** — the largest newly-visible omissions are Clay-only defenders:

| lane | before | after | largest unscored contributors |
|---|---|---|---|
| Clay CB | 10 keys (+1,038) | 17 (+13,557) | `idp_pass_def` +8,326, `idp_tkl_loss` +2,154, `st_tkl_solo` +936, `idp_qb_hit` +481, `idp_ff` +475 |
| Clay LB | 10 (+1,023) | 17 (+12,034) | `idp_tkl_loss` +4,227, `idp_pass_def` +2,624, `idp_qb_hit` +2,601, `st_tkl_solo` +928 |
| Clay EDGE | 10 (+110) | 17 (+10,857) | `idp_tkl_loss` +4,596, `idp_qb_hit` +3,356, `idp_pass_def` +1,537, `idp_sack_yd` +463 |
| IDP Show (full capture) CB/LB/EDGE | 10 | 10 (+764…+1,702) | `st_tkl_solo`, `idp_sack_yd`, `idp_int_ret_yd`, `idp_blk_kick` — PD/TFL/QB hits are covered |
| Clay WR | 10 (+4,151) | 17 (+5,346) | rec bands, `kr_yd` +992 (newly visible), `fum_lost` |
| Clay QB | 10 (−52) | 17 (−394) | **`fum_lost` −436** (a penalty — the partial total is overstated), `pass_2pt` +82, `pass_int_td` −56 |
| baseline, no PBP artifact (WR / LB) | 0 | 10 (+4,151) / 3 (+1,023) | rec bands / ST rules |
| baseline, legacy snapshot | 0 | `unverifiable` | — |

**dynasty_new (offense-only — the census and its card have no IDP rules; the
brief called it an IDP league, which the data does not support)**:
Clay QB 2 → 7 keys, net −124 (`fum_lost` −218 outweighs `pass_2pt` +82); RB −69;
WR +48 (`st_td` +90, `rec_2pt` +56, `fum_lost` −100); TE −12.

Local reconstructed baseline (nflverse 2023-2025, PBP 2025 only), both cards:
before 2,815 / 2,815 proxies looked fully scoreable; after 1,953 `partial`
(seasons without the PBP artifact: `st_*` on all of them, rec bands +
`pass_int_td` on 735 offense records) and 862 `complete`.

**PD / TFL / QB hits (requirement 3).** These matter for **dynasty_main** (the IDP
league): +12,487 / +10,977 / +6,438 realized 2025 points. A real projection field
exists for all three — **The IDP Show** publishes PD, TFL and QB hits (and FF, FR,
def TD, safety) — and BDVM already scores them from it and down-weights a Clay
record that lacks them (`vocabulary_dominated_weight_mult`). No neutral estimate
was added. Clay's guide publishes none of them. Whether a given IDP Show capture
carries them is now visible per player (`unscoredKeysBySource`); the live sheet's
actual columns could not be checked locally (no snapshot).

## Data available for J2 (NOT built here)

* **Reception-distance bands (`rec_0_4…rec_40p`)** — no projection source publishes
  a per-target depth distribution. Historical inputs exist: the play-by-play
  supplement (`src/nfl_data/pbp_weekly.py`, exact against the host on seven 2025
  weeks) and per-player depth histograms in Sleeper's exact bands
  (`src/nfl_data/reception_depth.py`). nflverse's `receiving_10/_16/_20/_40` are
  cumulative thresholds, not bands, and must not be used. A J2 component would be a
  trained forecast, not a projection field.
* **First downs** — no projection source publishes them; `bonus_fd_*` is imputed
  today by `src/nfl_data/first_down_rate.py` (measured one-per-~20-yards fit) and
  the realized engine reads nflverse `*_first_downs` minus TDs exactly. Play-type
  first downs (`pass_fd`/`rush_fd`/`rec_fd`) are 0.0 on both live cards and must
  never be derived from aggregates.

## Reproduce

```bash
python docs/research/bdvm-v1/fumble-recovery-host-golden-2026-10-01/host_golden.py \
  --sleeper-dir <dir with league.json, stats_wk1..18.json, matchups_wk1..17.json> \
  --players <players.json> --weekly weekly_2025.json.gz --pbp pbp_weekly_2025.jsonl \
  --out host_golden.json [--fixture tests/nfl_data/fixtures/idp_fumble_recovery_host_golden_2025.json]
python docs/research/bdvm-v1/scoring-census-2026-10-01/board_diff.py \
  --weekly-json weekly_2023_2025.json.gz --pbp-dir <pbp dir> \
  --contract exports/latest/dynasty_data_2026-09-30.json \
  --actuals-json weekly_2026_wk1_3.json.gz --base-ref 0f9ed7072 --out board_diff.json
python docs/research/bdvm-v1/fumble-recovery-host-golden-2026-10-01/coverage_report.py \
  --out coverage_report.json
```

Input hashes are in `host_golden.json` (`inputs`) and `board_diff.json` (`pins`).
