# League-scored projections: model card

**Status:** batch 1 of the league-intelligence scoring workstream (`claude/li-scoring`).
Library and labelling only. No served value, Game Day number, BDVM output or
recommendation changes. Nothing on `server.py` or `src/api/**` imports the new
modules (pinned by `tests/league_intel/test_league_format.py`).

**Owner directive:** League Intelligence & Trade Decision Engine, 2026-10-19,
§4 ("Build a complete exact-league projection system") and §5.

## 1. What a league-scored projection is

A league-scored projection is a provider's projected **stat line**, scored
under the league's **actual Sleeper scoring card** by the one canonical exact
scorer (`src/league_intel/scorer.py::score_stat_line`). It is not the
provider's native fantasy-point total. Native totals are kept only as a
diagnostic (`native_fpg`, `native_points_ppr`) and are never blended.

There are two scoring paths, and both end in that same scorer:

| path | stat vocabulary | entry point | used by |
|---|---|---|---|
| season / ROS (BDVM snapshots) | nflverse column names (`receptions`, `receiving_yards`) | `ProjectionRecord.resolve_fpg_breakdown` -> `bdvm.scoring.score_stat_line_per_game_breakdown` -> `realized_points.compute_weekly_points` -> `score_stat_line` | `ros.projection_observations`, `ros.projection_ensemble`, `model_registry.projection_scorecard`, BDVM |
| weekly (Sleeper / keyed providers) | Sleeper stat keys (`rec`, `rec_yd`, `rec_0_4`) | `score_stat_line` directly | `ros.sleeper_weekly_projections`, `ros.keyed_weekly_projections`, Game Day |

## 2. What batch 1 adds

| addition | where | what it answers |
|---|---|---|
| `ProjectionObservation.scoring_components` | `src/ros/projection_observations.py` | the per-key `(key, raw, rate, points)` behind `league_scored_fpg`, from the **same** scoring call (no second pass). For a stat-line record the components sum, in order, to `league_scored_fpg` exactly. |
| `ProjectionObservation.uncovered_paid_keys` + `coverage_status` | same | the paid card rules the projection does not cover. Their contribution is **unknown, not zero**. For BDVM records this comes from the canonical coverage owner (`bdvm.source_vocabulary.record_coverage`), fed the engine's own unscored keys from the same call. A rate the card states but that cannot be read is added (the engine would coerce it to 0). `coverage_status = "unverifiable"` for source-scored points, so an empty list never reads as complete. |
| `ProjectionObservation.synthetic_components` | same | card keys whose projected value is an imputed split, not provider evidence. Today that means the reception bands (§4). This is a label only: the points stay in `league_scored_fpg`. |
| `scoring_coverage.uncovered_paid_keys(line, card, *, position=None)` | `src/nfl_data/scoring_coverage.py` | the same question for a **Sleeper-keyed** line. It returns nonzero-rate keys absent from the line that are not linear identities of keys it does carry. |
| `synthetic_splits` | `src/nfl_data/synthetic_splits.py` (new) | detects the provider's fixed reception-band split |
| `league_format.resolve_league_format(league_key, ...)` | `src/league_intel/league_format.py` (new) | which axes of a league's format are proven, combining sf1 + evidence state (`league_registry`) with the market format and `tmf1` (`trade.market_trade_format`) |

Plumbing, all additive with no value change:

- `realized_points.RealizedPoints.components` was added. It is excluded from
  equality, `repr` and `to_dict`.
- `bdvm.scoring.score_stat_line_per_game_breakdown` was added, and
  `..._detailed` now delegates to it.
- `ProjectionRecord.resolve_fpg_breakdown` was added, and `resolve_fpg_detailed`
  now delegates to it.

## 3. Inputs and categories covered, per source

Independence families come from `config/projections/source_capability_census.json`.

| source | family | horizon | status | stat vocabulary / categories |
|---|---|---|---|---|
| Sleeper weekly projections | **RotoWire** (`company: "rotowire"` on every row) | WEEKLY | LIVE (flagged) | Sleeper keys for offense, K and IDP. Reception bands are present but synthetic (§4). Threshold bonuses are not projected. Special-teams events are not projected. |
| Mike Clay / ESPN guide | `espnClay` | PRESEASON_FULL_SEASON | LIVE | Season stat lines for offense plus a second IDP feed. No TFL, no PD, no fumbles column. |
| The IDP Show | `theIdpShow` | PRESEASON_FULL_SEASON | LIVE | IDP stat lines (authenticated sheet). |
| Fantasy Nerds weekly | `fantasyNerds` | WEEKLY | flag OFF | **Not independent.** It is a published consensus whose declared constituents include RotoWire and ESPN/Clay (`constituentFamilies`). It must never vote alongside them. |
| SportsDataIO weekly | `sportsDataIo` | WEEKLY | flag OFF | Its own family. Linear derivations (`pass_inc`, `idp_tkl`, `fgmiss`, `xpmiss`, TE `bonus_rec_te`) are declared in `DERIVATIONS`, which `uncovered_paid_keys` imports rather than copies. |

That leaves three live independent families: RotoWire (weekly), Clay and The
IDP Show (both preseason, full season).

## 4. The synthetic reception-band split

dynasty_main pays six reception-distance bands. In the 2026-10-19 capture
those were `rec_0_4` 0.25, `rec_5_9` 0.5, `rec_10_19` 0.75, `rec_20_29` 1.0,
`rec_30_39` 1.25 and `rec_40p` 2.0, against `rec` 0.1.

The weekly provider does not project the distance distribution. Every band is
a fixed share of projected receptions, the same for every player:

```
rec_0_4 .2   rec_5_9 .2   rec_10_19 .3   rec_20_29 .2   rec_30_39 .1   rec_40p .1   (sum = 1.1)
```

**Measured.** Every banded row matched in each capture checked:

- 2026 week 7: 349 of 349 rows.
- 2026 week 8: 356 of 356 rows.
- Both weeks were fetched at 2026-10-19T22:28Z and are committed as
  `tests/fixtures/li_scoring/sleeper_projection_band_lines_2026_w7_w8.json`.
- The earlier week-3 work found 174/174 and 177/177.

The shares sum to 1.1, so the split over-allocates receptions by 10%. The
provider rounds `rec` and each band separately, so detection allows
`(1 + share) x 0.005` of publication slack. That is precision, not tuning. A
realized line can never match: real bands partition the receptions.
`tests/nfl_data/test_synthetic_splits.py` checks this against every band line
derived from four real 2025 play-by-play weeks.

**Why it matters.** On the week-7 capture under dynasty_main's card, the
synthetic band component is a large share of projected weekly points for
players projected at 8 or more points:

| position | median share of projected weekly points |
|---|---|
| WR | 30.9% (4.21 pts) |
| TE | 34.7% (3.76 pts) |
| RB | 15.1% (2.04 pts) |

A deep threat and a checkdown target get the same distance profile. Batch 1
**labels** this component and leaves the points alone. A measured per-player
reception-shape replacement is a later value-moving unit
(`nfl_data/reception_shape_projection.py`), evidenced separately.

## 5. Uncovered keys

The rule: a paid rule a source does not project is reported, never
zero-filled.

- Linear identities of expectations may be derived: `pass_inc = att − cmp`,
  `idp_tkl = solo + ast`, `fgmiss = fga − fgm`, `xpmiss = xpa − xpm`, and
  `bonus_rec_te = rec` for a TE only.
- **Threshold bonuses are never derived from a mean.** The indicator of a mean
  is not the mean of an indicator.
- Team-level rules (`classify == NOT_APPLICABLE`) are not player gaps.
- Position applicability beyond the gated derivations is deliberately not
  filtered in `uncovered_paid_keys`, so the function over-reports by design.
  The weekly source's own grammar (`sleeper_weekly_projections._uncovered_for`)
  remains the per-provider filter.

## 6. Card freshness and league format

- A scoring card proves when it was taken, not that it is still true. Only
  `fresh` evidence (at most 6 h old, with the season verified) yields an sf1
  fingerprint, a verified season or a `tmf1` format fingerprint.
- The card changes. The committed 2026-07-28 card and the 2026-10-19 capture
  differ in value on 21 keys (absent-vs-zero ignored). For example, `rec` went
  from 0.08 to 0.1, `rec_0_4` from 0.17 to 0.25, `pass_inc` from −0.22 to −0.67
  and `bonus_fd_qb` from 0.67 to 0.4. Any projection scored under a stale card is scored under the wrong
  rules. Scores therefore carry the card fingerprint (`scoring_fingerprint`
  on weekly observations; per-season cards in PR-3).
- `resolve_league_format` requires an explicit `league_key`. There is no
  default league. An unknown axis stays `None` and is listed in
  `unknown_axes`, never coerced to 0 or False. Any unknown axis withholds
  `tmf1`.
- In CI there is no gitignored `data/leagues` snapshot, so `dynasty_main`
  resolves as `unverified` with the reason `scoring_evidence_missing`.
- The captured live lineup (`roster_positions`) and the registry starters give
  the same `tmf1` (pinned).

## 7. Limitations

- **One weekly family.** RotoWire, through Sleeper, is the only live weekly
  projection. A weekly "ensemble" is a single-family passthrough and is
  labelled as such.
- **Full-season sources are preseason only.** Clay and The IDP Show publish
  once, before the season. They are not rest-of-season updates.
- **No predictive distributions yet.** Batch 1 has means only. Dispersion
  (`PredictiveSummary`, labelled `proxy_dispersion`) is PR-3. A
  provider-calibrated error model is PR-5 and needs the kickoff-locked
  pregame archive. Nothing here is a calibrated probability.
- **Event correlations.** A sack also produces a TFL, a QB hit and a tackle.
  Within one stat line, the exact scorer adds every key the line carries, so
  stacking is honoured when the source projects each category. Joint
  simulation of IDP events is PR-2 (`idp_event_model`), where most shares will
  start as PRIOR on the tracked fixtures.
- **Special-teams double count** (ST tackle / ST forced fumble on the realized
  path) is a known, separately evidenced fix. It is not batch 1.

## 8. Source independence

Each body of evidence votes once. RotoWire's Sleeper feed and a separately
ingested RotoWire product are one family. Fantasy Nerds is a consensus
containing RotoWire and Clay, so it is never an independent vote next to
either. Combining families is the job of `ros.projection_ensemble`, through
census ancestry; this card adds no weighting.
