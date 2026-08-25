# V1-51 residual — rosPlayoffOdds' silent zero-simulation state

2026-08-22. Claude 3 — Season/Scoring/BDVM. Docs + one code file, no
other unit touched. V1-51 itself is already `VERIFIED`; this closes
the row's own named residual rather than reopening the row.

## The residual, verbatim from the completion contract

`docs/VERSION_1_COMPLETION_CONTRACT.md`'s V1-51 row (§3.4) already
named this gap explicitly: *"`rosPlayoffOdds` reports `n_simulations: 0`
with `playoffOdds: []` but publishes no `unsimulable` block or
`simulated` flag, so it is truthful and non-contradictory yet does not
NAME the reason its two siblings now share. Pre-existing, unchanged by
#956, and outside this row's stated close condition... Whether that
warrants its own row is an owner call."*

## What was verified before writing any code

`src/ros/playoff_sim.py::simulate_playoff_odds` has three early-return
refusal branches. Two already carry an `unsimulable` block
(`playoff_seeds is None` → `playoff_bracket_unknown`; `not schedule and
games_played <= 0` → `no_games_played_and_none_scheduled`, both with
existing test coverage in `tests/ros/test_playoff_sim_unsimulable.py`).
The third, `if not distributions:`, returned bare
`{"playoffOdds": [], "n_simulations": 0, ...}` with no `unsimulable`
key — the exact gap the row names.

`distributions` comes from `_build_team_distributions`, which reads
`per_owner, pool = playoff_odds._season_weekly_scores(current_season,
snapshot.managers)` — the **identical function** the sibling
`src.public_league.playoff_odds` engine calls to decide
`no_scored_weeks_in_league`. `distributions` is empty precisely when
`per_owner` is empty: the same "zero scored weeks" state the two
sibling engines (`playoff_odds.py`, `src/ros/championship.py`) already
detect and both name `no_scored_weeks_in_league` — the reused string is
not a guess, it is the same underlying signal.

Existing test coverage in `tests/ros/test_playoff_sim_unsimulable.py`
deliberately bypasses this branch: its `_Harness._run` patches
`_build_team_distributions` to always return non-empty distributions,
so the `if not distributions:` path had zero test coverage before this
unit — confirmed by reading the harness, not assumed.

## Fix

`src/ros/playoff_sim.py`, `simulate_playoff_odds`'s `if not
distributions:` branch: added an `unsimulable: {reason:
"no_scored_weeks_in_league", detail: ...}` block, matching the exact
reason string and `detail` phrasing style already used by the two other
refusal branches in this same function and by both sibling engines.
Nothing else in the branch's shape changed.

## Tests

New `TestNoScoredWeeksInLeague` class in
`tests/ros/test_playoff_sim_unsimulable.py`, with its own harness that
patches `_build_team_distributions` to return `({}, {})` directly
(distinct from the existing harness, which cannot reach this branch by
construction):

- the shared reason and detail text are present;
- the state is never stamped `converged` (nothing was simulated);
- the reason is distinct from the OTHER refusal branch's
  `no_games_played_and_none_scheduled`, so the two don't collapse into
  one code path.

## Mutation proof (RED-before / GREEN-after)

Removed the new `unsimulable` block, reran the three new tests:

```
FAILED test_no_scored_weeks_yields_the_shared_unsimulable_reason
  KeyError: 'unsimulable'
FAILED test_no_scored_weeks_is_a_distinct_reason_from_nothing_scheduled
  KeyError: 'unsimulable'
2 failed, 9 passed
```

Restored → full `tests/ros/test_playoff_sim_unsimulable.py` (11 tests)
and full `tests/ros/` suite (241 passed, 2 skipped) both GREEN, 0
regressions on the two pre-existing sibling branches.

## Scope

Single file (`src/ros/playoff_sim.py`) plus its test file touched.
`playoff_odds.py`, `championship.py`, `simulate_trade_impact`,
`build_section`, and the two pre-existing refusal branches are
unmodified. Does not reopen the V1-51 row (already `VERIFIED`) — this
is the row's own named residual, closed at the code level.
