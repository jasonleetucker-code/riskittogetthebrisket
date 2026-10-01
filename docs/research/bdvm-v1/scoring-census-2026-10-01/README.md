# BDVM scoring census — 2026-10-01 (LOCAL)

**Scope: LOCAL.** No owner/production session was available, so this is a
pinned local census over the real league cards (read-only from the main
checkout's gitignored `data/leagues/scoring_<id>.json`, fetched 2026-09-26)
and public nflverse 2025 history. Production coverage is still the
`/api/bdvm/values` `meta.scoringCoverage` block; this census covers what that
block cannot see.

Reporting only: nothing here changes a projected point, value or weight.

## Reproduce

```bash
python scripts/bdvm_scoring_census.py --out-dir docs/research/bdvm-v1/scoring-census-2026-10-01   --leagues-dir <checkout>/data/leagues --weekly-json weekly_2025.json.gz --pbp-dir <pbp dir> --season 2025
```

Pins (in `census.json`): code `b57bab6f9` (clean), card sha256 + fingerprint
(`sf1:9e51824690d091f9` / `sf1:82a5f8ef2bfdb098`), weekly rows sha256
`e4161184…327c` (19,422 rows from `stats_player/stats_player_week_2025.csv`),
PBP supplement sha256 `f8dc2ce3…c2d7` (built by `pbp_weekly.persist_pbp_weekly`,
986 players). Files: `census.json` (every rule, both leagues), `census.md`
(full table incl. SUPPORTED and NOT_APPLICABLE).

## Method

* **Engine layer** — `scoring_coverage.classify` (behavioural probe) decides
  whether `realized_points` reads a rule at all.
* **Source layer** — each adapter's own parser is run on a synthetic input to
  derive its column vocabulary (Clay offense: att/cmp/yds/td/int/sk, carries,
  targets/rec/yds/td; Clay IDP: solo/ast split, sacks, INT; IDP Show: solo/ast,
  TFL, sacks, QB hits, INT, PD, FF, FR, def TD, safety; manual CSV: any weekly
  column, never the PBP supplement; reconstructed baseline: weekly feed + PBP).
  A rule is "supplied" when BDVM's projection scorer (first-down imputation on)
  moves on a line built from exactly that vocabulary.
* **Classes** — SUPPORTED (every covering real source supplies it; `imputed`
  noted) / ABSENT_FIELD (one covering source has it, another does not) /
  UNSUPPORTED_VOCABULARY (no real source can emit it) / MAPPING_ERROR (engine
  ignores a rule whose stat exists) / NOT_APPLICABLE (DST, kicker, or IDP in an
  offense-only league).
* **Impact** — realized 2025 REG points under the card, SIGNED, the number of
  players who recorded the stat over the eligible family population, and the
  share of the affected families' realized points. Priority = |points at risk|.
  For ABSENT_FIELD that is an UPPER bound (only players covered solely by Clay
  omit it; per-player source coverage needs the prod snapshot, unavailable
  locally). A count of missing keys is never used as a share of points.

## Headline

* **dynasty_main** (offense 53,065 / IDP 80,156 realized pts): 86 nonzero
  rules → 21 SUPPORTED, 7 ABSENT_FIELD, 21 UNSUPPORTED_VOCABULARY, 37 N/A,
  0 MAPPING_ERROR after this unit's fix.
  * Offense, reported in `unscoredKeys`: reception-distance bands + ST tackles +
    pick-six ≈ **+7,250 net (13.7% of offense points)** — the six `rec_*` bands
    alone are 6,764, six times the flat `rec` (1,113).
  * Offense, **silent** (not in `unscoredKeys`): `fum_lost` **−964**, plus
    kr/pr yards, ST TD, 2-pt conversions → net ≈ +1,330. A Clay-scored QB/RB/WR
    therefore omits a PENALTY: the partial total is overstated for fumblers.
  * IDP, ABSENT_FIELD (Clay-only defenders): PD, TFL, QB hits, FF, FR, def TD,
    safety ≈ **+32,383 upper bound (40% of IDP points)** — silent per player;
    mitigated only where IDP Show also covers the player (vocabulary down-weight).
  * IDP, UNSUPPORTED and silent: sack yards, INT/FR return yards, blocked kicks.
* **dynasty_new** (offense 46,536): 41 rules → 9 SUPPORTED, 7 UNSUPPORTED, 25 N/A.
  Silent net **−166**: `fum_lost` (−482) outweighs ST TD + 2-pt (+316), i.e.
  the projected totals are on net **overstated**, not understated.

## Priority (non-SUPPORTED, non-N/A rules, by |2025 points at risk|)

### dynasty_main (Sleeper 1312006700437352448, IDP)
| # | rule | weight | class | missing from | 2025 pts (signed) | affected / eligible | share | in unscoredKeys? | capable feed needed |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `idp_pass_def` | 5.3 | ABSENT_FIELD | clayIdp | +12486.8 | 577 / 1034 | 15.58% | NO (silent) | an IDP feed with passes defended (IDP Show has it; Clay's guide does not) |
| 2 | `idp_tkl_loss` | 4.24 | ABSENT_FIELD | clayIdp | +10977.4 | 642 / 1034 | 13.69% | NO (silent) | an IDP feed with TFL (IDP Show has it; Clay's guide does not) |
| 3 | `idp_qb_hit` | 2.12 | ABSENT_FIELD | clayIdp | +6438.44 | 531 / 1034 | 8.03% | NO (silent) | an IDP feed with QB hits (IDP Show has it; Clay's guide does not) |
| 4 | `rec_10_19` | 0.75 | UNSUPPORTED_VOCABULARY | clayOffense | +2478 | 391 / 610 | 4.67% | yes | per-target depth distribution (a reception-distance forecast) |
| 5 | `st_tkl_solo` | 1.33 | UNSUPPORTED_VOCABULARY | clayOffense, clayIdp, idpShow | +2475.13 | 543 / 1644 | 1.86% | yes | a special-teams snap/tackle projection |
| 6 | `rec_5_9` | 0.5 | UNSUPPORTED_VOCABULARY | clayOffense | +1898 | 403 / 610 | 3.58% | yes | per-target depth distribution (a reception-distance forecast) |
| 7 | `kr_yd` | 0.0333 | UNSUPPORTED_VOCABULARY | clayOffense, clayIdp, idpShow | +1795.63 | 166 / 1644 | 1.35% | NO (silent) | a return-role / return-yards projection |
| 8 | `idp_ff` | 4.24 | ABSENT_FIELD | clayIdp | +1505.2 | 258 / 1034 | 1.88% | NO (silent) | an IDP feed with forced fumbles (Clay's FF column does not survive text extraction) |
| 9 | `rec_20_29` | 1 | UNSUPPORTED_VOCABULARY | clayOffense | +980 | 273 / 610 | 1.85% | yes | per-target depth distribution (a reception-distance forecast) |
| 10 | `fum_lost` | -4 | UNSUPPORTED_VOCABULARY | clayOffense | -964 | 155 / 610 | -1.82% | NO (silent) | a projection feed publishing fumbles lost (Clay's guide has no fumbles column); manual CSV 'fumbles_lost' column is accepted |
| 11 | `idp_sack_yd` | 0.111111 | UNSUPPORTED_VOCABULARY | clayIdp, idpShow | +918.34 | 417 / 1034 | 1.15% | NO (silent) | an IDP feed with sack yards (none publishes it) |
| 12 | `idp_fum_rec` | 3.19 | ABSENT_FIELD (+baseline map error) | clayIdp | +749.65 | 199 / 1034 | 0.94% | NO (silent) | an IDP feed with fumble recoveries |
| 13 | `rec_0_4` | 0.25 | UNSUPPORTED_VOCABULARY | clayOffense | +536.75 | 379 / 610 | 1.01% | yes | per-target depth distribution (a reception-distance forecast); historical PBP can train it but is not a projection |
| 14 | `idp_int_ret_yd` | 0.111111 | UNSUPPORTED_VOCABULARY | clayIdp, idpShow | +536.12 | 151 / 1034 | 0.67% | NO (silent) | an IDP feed with interception return yards (none publishes it) |
| 15 | `rec_40p` | 2 | UNSUPPORTED_VOCABULARY | clayOffense | +452 | 130 / 610 | 0.85% | yes | per-target depth distribution (a reception-distance forecast) |
| 16 | `rec_30_39` | 1.25 | UNSUPPORTED_VOCABULARY | clayOffense | +418.75 | 175 / 610 | 0.79% | yes | per-target depth distribution (a reception-distance forecast) |
| 17 | `pr_yd` | 0.0333 | UNSUPPORTED_VOCABULARY | clayOffense, clayIdp, idpShow | +281.77 | 68 / 1644 | 0.21% | NO (silent) | a return-role / return-yards projection |
| 18 | `idp_blk_kick` | 5.3 | UNSUPPORTED_VOCABULARY | clayIdp, idpShow | +217.3 | 36 / 1034 | 0.27% | NO (silent) | an IDP feed with blocked kicks (none publishes it) |
| 19 | `idp_def_td` | 6.36 | ABSENT_FIELD | clayIdp | +178.08 | 27 / 1034 | 0.22% | NO (silent) | an IDP feed with defensive TDs |
| 20 | `st_td` | 6 | UNSUPPORTED_VOCABULARY | clayOffense, clayIdp, idpShow | +162 | 21 / 1644 | 0.12% | NO (silent) | a return-TD projection |
| 21 | `st_ff` | 4.25 | UNSUPPORTED_VOCABULARY | clayOffense, clayIdp, idpShow | +136 | 32 / 1644 | 0.10% | yes | a special-teams forced-fumble projection |
| 22 | `idp_fum_ret_yd` | 0.111111 | UNSUPPORTED_VOCABULARY (+baseline map error) | clayIdp, idpShow | +93.88 | 59 / 1034 | 0.12% | NO (silent) | an IDP feed with fumble return yards (none publishes it) |
| 23 | `pass_2pt` | 2 | UNSUPPORTED_VOCABULARY | clayOffense | +84 | 30 / 610 | 0.16% | NO (silent) | a projection feed publishing 2-pt conversions |
| 24 | `rec_2pt` | 2 | UNSUPPORTED_VOCABULARY | clayOffense | +84 | 39 / 610 | 0.16% | NO (silent) | a projection feed publishing 2-pt conversions |
| 25 | `st_fum_rec` | 3.19 | UNSUPPORTED_VOCABULARY | clayOffense, clayIdp, idpShow | +82.94 | 26 / 1644 | 0.06% | yes | a special-teams fumble-recovery projection |
| 26 | `pass_int_td` | -2 | UNSUPPORTED_VOCABULARY | clayOffense | -56 | 24 / 610 | -0.11% | yes | a pick-six-thrown rate component (no projection feed publishes it) |
| 27 | `idp_safe` | 5.3 | ABSENT_FIELD | clayIdp | +47.7 | 9 / 1034 | 0.06% | NO (silent) | an IDP feed with safeties |
| 28 | `rush_2pt` | 2 | UNSUPPORTED_VOCABULARY | clayOffense | +34 | 15 / 610 | 0.06% | NO (silent) | a projection feed publishing 2-pt conversions |
### dynasty_new (Sleeper 1320092771247222784, offense-only)
| # | rule | weight | class | missing from | 2025 pts (signed) | affected / eligible | share | in unscoredKeys? | capable feed needed |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `fum_lost` | -2 | UNSUPPORTED_VOCABULARY | clayOffense | -482 | 155 / 610 | -1.04% | NO (silent) | a projection feed publishing fumbles lost (Clay's guide has no fumbles column); manual CSV 'fumbles_lost' column is accepted |
| 2 | `st_td` | 6 | UNSUPPORTED_VOCABULARY | clayOffense | +114 | 14 / 610 | 0.24% | NO (silent) | a return-TD projection |
| 3 | `pass_2pt` | 2 | UNSUPPORTED_VOCABULARY | clayOffense | +84 | 30 / 610 | 0.18% | NO (silent) | a projection feed publishing 2-pt conversions |
| 4 | `rec_2pt` | 2 | UNSUPPORTED_VOCABULARY | clayOffense | +84 | 39 / 610 | 0.18% | NO (silent) | a projection feed publishing 2-pt conversions |
| 5 | `rush_2pt` | 2 | UNSUPPORTED_VOCABULARY | clayOffense | +34 | 15 / 610 | 0.07% | NO (silent) | a projection feed publishing 2-pt conversions |
| 6 | `st_fum_rec` | 1 | UNSUPPORTED_VOCABULARY | clayOffense | +5 | 5 / 610 | 0.01% | yes | a special-teams fumble-recovery projection |
| 7 | `st_ff` | 1 | UNSUPPORTED_VOCABULARY | clayOffense | +4 | 4 / 610 | 0.01% | yes | a special-teams forced-fumble projection |


## Mapping findings

1. **FIXED here — `bonus_rec_wr` (dynasty_main 0.02/rec): MAPPING_ERROR.** The
   probe classified it `GAP`: the normalizer emitted only `bonus_rec_te`, so
   every WR scored a silent zero (and it was not in `unscoredKeys`). All
   sources publish `receptions`; `realized_points` now emits the
   `bonus_rec_rb/_wr/_te` family by position (119.5 realized 2025 pts, 217 WRs).
   RED-first: `tests/bdvm/test_position_reception_bonus.py`.
2. **NOT fixed — `idp_fum_rec` / `idp_fum_ret_yd` read the wrong column on the
   realized path** (affects the reconstructed-baseline proxy and every realized
   consumer, not the projection sources). The engine reads
   `fumble_recovery_own`; a defender recovering the offense's fumble is `_opp`.
   2025 REG IDP: own 16 vs opp 235; Sleeper host `idp_fum_rec` totals for wk
   5/9/14 are 20/13/10 vs opp 19/16/9 and own 0/0/3
   (`docs/master-site-audit/evidence/W18/`). Out of this unit's scope (not a
   projection field; changes host-validated realized scoring and is coupled to
   the IDP Show adapter mapping `FR` → `fumble_recovery_own`). Needs its own
   unit with host-golden validation. ~750 + 94 pts/season on dynasty_main.

## Gaps / capable feeds needed (no derivation attempted)

* Reception-distance bands `rec_0_4…rec_40p`: need a per-target depth
  distribution forecast. Never derived from aggregate yards. Historical PBP
  (already built by `pbp_weekly`) can TRAIN such a component; it is not a
  projection.
* `fum_lost`, 2-pt conversions: a projection feed publishing them (manual CSV
  accepts `fumbles_lost` / `*_2pt_conversions` columns today; none is loaded).
* Return yards / ST TDs / ST tackles: a return-role / special-teams projection.
* `pass_int_td`: a pick-six-thrown rate component.
* IDP sack yards, INT/FR return yards, blocked kicks: no feed publishes them.
* Clay IDP lacks PD/TFL/QB hits/FF/FR (FF does not survive pdftotext); IDP Show
  has them — the IDP Show live sheet's actual columns were not verifiable
  locally (no snapshot in this checkout).
* `unscoredKeys` reports only the PBP-only rules; source-vocabulary gaps
  (`fum_lost` etc.) are silent per player. Stamping per-source vocabulary gaps
  into `unscoredKeys` would need a declared vocabulary on `ProjectionRecord`.
* Reconstructed-baseline records are fpg-only, so `RealizedSeason.unscored`
  (PBP rules missing for a season) does not reach the consensus `unscoredKeys`.
* Same "lower bound" wording remains in `src/nfl_data/realized_points.py`
  (`RealizedPoints.unscored`) and `src/bdvm/baseline.py`; `pass_int_td` makes it
  equally wrong there (outside this unit's edit list).
