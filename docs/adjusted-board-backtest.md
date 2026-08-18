# Should the league-adjusted board be the default?

**Answer, measured 2026-07-28: no. Keep it a toggle.**

Not because it is bad — because nothing measured says it is better, and
three of the four framings lean slightly against it. Flipping a default
is a claim of improvement, and there is no evidence for that claim.

Reproduce with:

```bash
python3 scripts/backtest_adjusted_board.py --json docs/measurements/adjusted-board-backtest-<date>.json
```

Raw result: `docs/measurements/adjusted-board-backtest-2026-07-28.json`.
Engine: `src/model_registry/board_holdout.py`.

## What was compared

Both boards ranked against what players **actually scored in 2025 under
this league's exact rules**, with `compare_boards` reporting whether the
difference in Spearman correlation survives a paired bootstrap (2000
resamples, seeded).

* market arm — `rankDerivedValue` straight off the live contract
* adjusted arm — the same value times this league's overlay factor from
  `GET /api/valuation/league-adjusted`
* target — season totals from `compute_player_season_scores` **with the
  play-by-play supplement joined**, which carries the six reception
  bands, the three player special-teams rules and the pick-six penalty
  that weekly box scores cannot produce

Population: 572 players. From 1093 board rows, 144 picks (no realized
points, and the adjustment never moves them), 240 rows the pipeline
declined to price, 137 that did not join to an nflverse season line.

## Result

| framing | n | market ρ | adjusted ρ | Δ | 95% CI on Δ | win rate |
|---|---|---|---|---|---|---|
| full board | 572 | +0.5620 | +0.5541 | **−0.0078** | [−0.0166, +0.0007] | 0.043 |
| board top 300 | 245 | +0.5311 | +0.5319 | +0.0008 | [−0.0115, +0.0154] | 0.524 |
| points per game | 572 | +0.5846 | +0.5787 | −0.0059 | [−0.0147, +0.0030] | 0.104 |
| over replacement | 572 | +0.4535 | +0.4459 | −0.0076 | [−0.0165, +0.0011] | 0.043 |

Every interval spans zero, so the honest verdict in all four is **no
difference detected**. But the point estimate is negative in three of
four, and on the full board the adjusted arm loses 95.7% of resamples.
That is not enough to call the adjustment harmful. It is comfortably
enough to decline to make it the default.

## The finding that matters more than the verdict

Only three positions get a per-player adjustment at all:

| position | n | distinct factors | range |
|---|---|---|---|
| DB | 139 | **1** | 1.0065 |
| DL | 145 | **1** | 1.0831 |
| LB | 114 | **1** | 0.9932 |
| QB | 72 | **1** | 1.0120 |
| K | 19 | **1** | 0.9525 |
| RB | 142 | 45 | 0.7986 – 1.0664 |
| TE | 85 | 49 | 0.8873 – 1.0591 |
| WR | 213 | 96 | 0.9099 – 1.1273 |

`structuralScarcity` and `scoringFit` are **per-position scalars**.
A constant multiplier cannot reorder a position against itself, so the
per-position deltas for DB / DL / LB / QB are exactly `0.0000` — by
construction, not because the harness is blind. `factor_shape` is
printed alongside the verdict for exactly this reason.

This splits the feature into two claims that need separate evidence:

1. **Within position** — only reception fit is live, on RB/TE/WR. TE is
   consistently positive (+0.0255 in the top 300, +0.0115 per game), RB
   consistently slightly negative, WR flat. Directionally what the
   reception-banding measurement predicted, nowhere near significant at
   n=40–128.
2. **Across positions** — the scalars. Tested twice, once against raw
   points and once against points over replacement, because raw points
   are not comparable across positions and would penalise positional
   re-pricing for the wrong reason. Neither framing supports the
   scalars; both lean marginally against.

## Why the over-replacement target exists

A QB outscores every DB in this league by construction, and the board
correctly does not rank him above all of them. Scoring a cross-position
ordering against raw points therefore grades the board on a question it
is not trying to answer — and penalises exactly what the positional
scalars do.

Over-replacement fixes that, using **realized** points and the league's
roster settings. It deliberately never calls
`src.league_intel.replacement`: that module is part of the thing under
test, and deriving the target from it would let the adjustment grade its
own paper. Pinned by
`tests/scripts/test_backtest_adjusted_board.py::test_the_baseline_never_consults_the_module_under_test`.

Flex and superflex slots are not allocated — that allocation is an
optimisation whose answer depends on the values under test. Dedicated
slots only means every flex-eligible baseline sits somewhat too shallow,
identically in both arms.

## Why banded receptions had to be in the target

This league pays by catch distance (`rec_0_4` 0.17 through `rec_40p`
1.92). Those keys are unscorable from weekly box scores — only
play-by-play carries them, which `src/nfl_data/scoring_coverage.py`
reports directly (`audit_scoring_settings(..., pbp_supplement=False)`).
A target built from weekly stats alone is missing the
reception-distance component entirely, and reception fit is one of the
two live axes in the adjustment.

Scoring the adjustment against a target that omits the thing it corrects
for would have guaranteed a loss for a reason unrelated to whether it is
right.

**Changed 2026-08-18 (#802).** The bands used to be bolted on here from
the SEASON histogram in `reception_depth_<season>.jsonl`, which made this
script a second owner of what a band is worth — and it carried none of
the player special-teams rules (`st_tkl_solo` 1.33, `st_ff` 4.25,
`st_fum_rec` 3.19) or the pick-six penalty at all, so the target was
still incomplete in a way the prose did not say. The target now comes
from the canonical per-week supplement,
`data/nfl_data/actuals/pbp_weekly_<season>.jsonl`
(`src/nfl_data/pbp_weekly.py`), which carries all ten and is reconciled
to the league host's own weekly line.

The no-double-count rule is unchanged and is now **structural** rather
than a caller remembering it: the supplement is an allow-list of the ten
keys the weekly feed cannot supply, so it cannot write `rec` — which
the weekly engine already paid — even if handed one.

Two consequences for reading a run:

* the target moved, so verdicts from before this date are not comparable
  with verdicts after it;
* `pbpPlayers` in the run header replaces `bandedPlayers`. **A zero there
  means the artifact is missing and the ten rules scored nothing**, which
  makes the run a measurement of a different quantity than it claims.
  Build it with `scripts/build_pbp_weekly.py`.

## What this does not establish

The board is current; the season is finished. **This is not a forecast
test.** It cannot say whether either board predicts 2026.

The comparison is still sound because any lookahead in the board is a
*common-mode* error — it inflates both arms identically and cancels in
the difference. What survives is the question actually asked: does
applying the tilt move the ordering toward or away from this league's
scoring reality?

Supported: "the adjusted board does not align better with our scoring
than the market board does."
Not supported: "the adjusted board predicts next season worse." That
would need board snapshots taken *before* a season.

**The mechanism to keep those snapshots exists, but it cannot reach
2025.** `src/api/rank_history.py` appends one entry per UTC date on
every fresh scrape (`server.py:1710`), carrying both ranks and
`rankDerivedValue`, retained for three years. What it does *not* have is
depth: the append path is recent, so the log does not go back to the
2025 season, and it cannot be backfilled there either —
`scripts/backfill_rank_history.py` replays `exports/archive/*.zip` and
that directory was capped at 14 days. Every other dated artifact in the
repo starts 2026-03-22 or later.

So a genuine forward test needs a board snapshot taken before a season
whose outcomes we then observe, and the earliest such pair is **a board
from before the 2026 season scored against 2026 results — available
around December 2026**, not now.

Two changes landed 2026-07-28 to make sure that date is actually
reachable rather than discovered-too-late:

* `rank_history.coverage()`, surfaced on `/api/status` as
  `rankHistoryCoverage`. The append is best-effort inside a `try` and
  fires only on a fresh scrape, so a stall costs one warning line and
  then silence. `staleDays` is the field that catches it: a log that
  stopped growing yesterday looks perfect by span, count and gap count.
* Export archives now keep every zip for 14 days and then **one per day
  out to a year** (`EXPORTS_ARCHIVE_DAILY_MAX_AGE_DAYS`). At a flat 14
  days any stall longer than a fortnight was permanently unrepairable;
  a year of dailies costs ~80 MB and makes the backfill actually useful.

Power: the CI half-width is about 0.009 ρ, so this design detects a
difference of roughly ±0.015 and cannot rule out a genuine improvement
of +0.005. A null here is a real null at the effect sizes the current
axes produce, not a null at any effect size.

## What would change the answer

* **Run the forward test once the 2026 season has outcomes** (~Dec
  2026). Point this script's board source at a dated entry in
  `data/rank_history.jsonl` from before the season instead of
  `exports/latest/`, and the common-mode caveat disappears entirely —
  it becomes "did this board predict the season", which is the question
  actually worth answering. `compare_boards` and the realized-points
  join are unchanged; the one thing to build is a position lookup,
  since snapshots key on `name::assetClass` and carry no position.
  Check `rankHistoryCoverage` on `/api/status` before then — if the log
  has stalled, the window closes silently.
* **More per-player axes.** Four of eight positions currently receive a
  single scalar. Reception fit is the only per-player signal live, and
  it reaches RB/TE/WR only. An IDP per-player axis was refused for good
  reason (`src/league_intel/scoring_fit.py`); a projection-corroborated
  axis is blocked on LI-6.
* **Re-run after any axis change.** The script takes about 90 seconds
  and needs no arguments.
