# V1-52 follow-up — power_v2 streak/luck-regression season scoping

2026-08-22. Claude 3 — Season/Scoring/BDVM. Single code file + one test
file, no other unit touched. V1-52 itself is already
`IMPLEMENTED_UNVERIFIED` (gated on a production-only 12-owner
measurement); this closes a named residual from an earlier merged unit
in the same lane, not a reopen of the row's own gate.

## The residual, verbatim

PR #1032 (this session, merged, `src/ros/power_v2.py`'s `ppg`/`wl_record`
cross-season contamination fix) left its own follow-up comment at the
time:

> "KNOWN RESIDUAL (V1-52 investigation, not fixed here): `season_outcomes`
> and `expected_share_total` accumulate across every season the same way
> `career_state`'s points/games did before this fix, feeding the streak
> and luck-regression components respectively. Out of this unit's
> bounded scope (PPG/wl_record only) — tracked as a follow-up finding."

## What was verified before writing any code

Directly reading `build_section` (`src/ros/power_v2.py`) confirmed the
residual is real and unchanged since #1032 merged:

- `season_state` (the #1032 fix) resets at the top of every season's
  loop iteration — correct, already proven by that unit's own tests.
- `season_outcomes` and `expected_share_total` are declared once,
  OUTSIDE the loop, and never reset — accumulating across every season
  in `seasons_sorted`, exactly the pre-#1032 bug pattern for the other
  two fields.
- Both feed `_score_state` via `state["outcomes"]`/`state["expected"]`
  in BOTH the headline `final_state` and every per-week trend snapshot
  — so `streak` and `luck_regression` were contaminated on the current
  row AND on every trend point, the identical shape #1032 already fixed
  for `ppg`/`wl_record`.

**A sharper wrinkle #1032 introduced, found while verifying**:
`_score_state` reads `wins`/`games` from `state["career"]` (==
`season_state`, correctly season-scoped post-#1032) but
`expected_share_running = state["expected"]` (== `expected_share_total`,
still career-cumulative), then computes `luck_delta = (wins -
expected_share_running) / games`. This mixed a season-scoped
numerator/denominator with a career-cumulative subtrahend —
**internally inconsistent**, and arguably a worse defect than
pre-#1032's uniformly-wrong-but-consistent scoping. This confirmed the
gap is not cosmetic.

**No dual-use concern**, unlike `career_state` (whose `.keys()` also
backs `_enumerate_owner_ids`'s historical-presence fallback, which is
why #1032 needed a *parallel* accumulator rather than resetting
`career_state` in place). Grepping the whole file confirmed
`season_outcomes` and `expected_share_total` have exactly two consumers
each — the trend snapshot and `final_state` — both of which should be
season-scoped. So this fix is simpler than #1032's own: reset the two
existing dicts in place, alongside `season_state`'s existing reset.

## Fix

`src/ros/power_v2.py`, `build_section`: `season_outcomes` and
`expected_share_total` now reset to empty at the same point
`season_state` already resets (top of each season's loop iteration,
guarded the same way). Removed the now-stale "KNOWN RESIDUAL" comment
since the residual is closed. No other line changed — both consumers
were already correctly wired to these two names.

## Tests

Extended `tests/ros/test_power_v2_season_scoping.py`:

- **`test_luck_regression_uses_season_2_only_expected_share`** — reuses
  the file's existing `_two_season_snapshot()` fixture directly (no new
  fixture needed): alpha went undefeated on all-play expectation in
  season 2025 and 0-for-3 on it in season 2026. Season-2-only
  `expected_share_running` = 0.0 → `luck_score` = 0.5 (neutral,
  correct). Career-contaminated would sum in season 2025's 3.0,
  clamping the score to 1.0 (maximally "unlucky" — false, since season
  2025 has nothing to do with season-2 luck).
- **`test_streak_resets_at_the_season_boundary`** — the existing
  alpha/bravo fixture does NOT discriminate this defect (each owner's
  season-2026 outcomes are already uniform and the OPPOSITE sign from
  season-2025's uniform outcome, so the trailing-run search stops at
  the season boundary regardless of the bug). Added a new
  purpose-built 2-owner fixture (`charlie` losing every game of BOTH
  seasons — same sign on both sides of the boundary) so a
  career-contaminated run keeps counting straight through the
  boundary. Season-2-only: 3-game losing streak → score 0.2.
  Career-contaminated: 6-game streak → score floors at 0.0.
- **`test_both_lenses_agree_on_the_season_2_only_streak_and_luck`** —
  both lenses share one build, matching the file's existing pattern.

## Mutation proof (RED-before / GREEN-after)

Removed the two new reset lines, reran the three new tests:

```
FAILED test_streak_resets_at_the_season_boundary
  assert 0.0 == 0.2 ± 2.0e-07   (career-contaminated streak floored at 0.0)
FAILED test_luck_regression_uses_season_2_only_expected_share
  assert 1.0 == 0.5 ± 5.0e-07   (career-contaminated luck clamped to 1.0)
FAILED test_both_lenses_agree_on_the_season_2_only_streak_and_luck
3 failed, 8 passed
```

Every failing value matched the hand-computed contaminated value exactly
before the mutation was even applied — confirming the test design, not
just the fix. Restored → full `tests/ros/test_power_v2_season_scoping.py`
(11 tests) and full `tests/ros/` suite (244 passed, 2 skipped) both
GREEN, 0 regressions. Direct consumers outside `tests/ros/`
(`test_public_power_leaks_no_private_quantity.py`, `test_server_routes.py`,
`test_metric_separation.py`) also green, 38 passed.

## Scope

Single file (`src/ros/power_v2.py`) plus its season-scoping test file
touched. `career_state`, `season_state`'s own reset/logic,
`last_season_recent`/`last_season_allplay_share`, and every sibling file
are unmodified. Does not reopen V1-52's own gated status (production-scale
12-owner measurement, unchanged) — this closes a named code-level
follow-up from an already-merged unit in the same lane.
