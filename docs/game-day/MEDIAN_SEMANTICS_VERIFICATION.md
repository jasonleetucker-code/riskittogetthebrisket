# Sleeper median-game semantics — verification attempt, 2026-09-04

**Status:** UNRESOLVED. Recorded so the attempt is not repeated blind, and
so no later reader mistakes the simulator's default for a verified fact.

`docs/GAME_DAY_PROBABILITY_SPEC.md` §3 requires the league-median
threshold to be host-faithful and says explicitly: *"Verify Sleeper/host
behavior for ties at the median and odd/even league sizes rather than
guessing."* Contract row `W1-23` depends on it. This is that attempt.

## What IS established

`league_average_match = 1` on the owner's league for **2026, 2025 and
2024** (walked via `previous_league_id`). The 2025 league ran
`best_ball=1`, 10 teams, `playoff_week_start=14`.

The median game is unambiguously **real and live**:

- head-to-head results alone reproduce Sleeper's reported 2025 records
  for **0 of 10** teams;
- every team's reported record totals exactly **26** decisions over a
  13-week regular season — two per week, not one.

So each week awards an H2H result **and** a threshold result. That much
is settled and the simulator relies on it.

## What could NOT be established

Whether the threshold is the league **median** or the league **average**
— the Sleeper setting is literally named `league_average_match` — and
what an exact tie does.

Six variants were tested against 2025, adding each team's threshold-leg
record to its computed H2H record and comparing with Sleeper's own
reported `settings.wins/losses`:

| variant | teams reproduced |
|---|---|
| mean of all 10 | 3 / 10 |
| median of all 10 | 2 / 10 |
| mean excluding self | 3 / 10 |
| median excluding self | 2 / 10 |
| median as the lower middle value | 1 / 10 |
| median as the upper middle value | 0 / 10 |

A season-total check does not discriminate either: across the 13 weeks,
**both** mean and median award exactly 65 wins, which is also the number
implied by the reported records.

## Why it could not be established — the load-bearing finding

**Sleeper's stored historical matchup points no longer reproduce
Sleeper's own season totals.** Summing the `points` field over the 2025
regular season and comparing with each roster's `settings.fpts`:

```
rid  sum wk1-13    sleeper fpts     delta
  1     4325.90        4828.64   -502.74
  4     4711.89        5280.65   -568.76
  9     5581.01        6088.63   -507.62
```

Every team is short by 500-630 points, and **no week range closes it** —
1-13, 1-14, 1-15, 1-16 and 1-17 all miss (closest, 1-14, still averages
188 points per team off).

The mechanism is specific to this format: in a **best-ball** league
Sleeper recomputes the optimal lineup from current player stats, so any
stat correction changes both the chosen lineup and the total. Those
revisions accumulate across a season. The consequence is that
back-computing *what the host decided at the time* from *what the host
reports now* is not a sound method here, whatever threshold statistic is
assumed.

This is the same perishability argument that motivated the Game Day
prediction archive (`src/ros/game_day_archive.py`), arriving from the
other direction: historical host data is not a faithful record of what
was true when a decision was made.

## What the simulator does in the meantime

`src/ros/game_day_sim.py` defaults to `THRESHOLD_SEMANTICS = "median"`
— the statistic the product spec names — and:

- carries `threshold_semantics` on every result, so the assumption is
  visible rather than implicit;
- hard-codes `threshold_semantics_verified = False`, which no caller can
  set true;
- accepts `threshold_semantics="mean"` as a parameter, so switching is a
  one-argument change;
- keeps `median_enabled=None` (`STANDINGS_RULE_UNVERIFIED`) distinct
  from `False` (`NOT_APPLICABLE`), per spec §9.

An exact tie is counted as **neither** a win nor a loss and is not
folded into either — no tie-breaking rule has been invented.

## How to resolve it

A human with the Sleeper app can settle both questions in under a
minute, which no amount of API archaeology replaces. Open any completed
2025 week; each team shows two results. Read off:

1. whether the extra result is scored against the league **median** or
   the league **average**;
2. what an exact tie with that threshold is recorded as.

Then set `THRESHOLD_SEMANTICS`, add the tie rule if one exists, and flip
`threshold_semantics_verified` — with the observation recorded here as
its evidence.
