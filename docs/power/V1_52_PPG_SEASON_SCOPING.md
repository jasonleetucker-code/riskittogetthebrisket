# V1-52 — power_v2 PPG cross-season contamination (#1020 reproduction + fix)

2026-08-21. Claude 3 — Season/Scoring/BDVM, V1 numerator sprint. This
unit does NOT touch, rebase, or integrate `#996`/`#1009` (frozen for a
separate session/"Claude 5" to own). No V1-52 feature implementation
beyond this bounded reproduction and repair.

## Reproduction

Adversarial audit `#1020` claimed `src/ros/power_v2.py`'s PPG
accumulator carries prior-season scoring into the current season's
number. Independently reproduced against `origin/main`
(`54a70883e71e1c68c12099226aca6e4baeef8db6`) by static reading before
any test was written:

`career_state` (`build_section`, declared once, accumulated across
`for season in seasons_sorted:` with no per-season reset) fed `ppg`
(`points/games`) and `wl_record` (`wins/games`) directly in
`_score_state`. Its own code comment already admitted the scope:
*"Career totals across all seasons (matches power.py's accumulator
semantics)"* — a CAREER average presented as a current-season number.
`recentAvg` and `all_play` were already correctly season-scoped (gated
by `if season is seasons_sorted[-1]:` and unconditional per-week
overwrite respectively), which is what proves the defect was in the
accumulator specifically, not in "season" as a concept the module
lacked.

> **CORRECTION (2026-08-24, V1-52 follow-up 2).** The sentence above is
> **wrong about `recentAvg`**, and wrong in the direction that matters:
> it cites as *proof of correctness* the very gate that was the defect.
> `if season is seasons_sorted[-1]:` is not a season scope — the
> accumulation loop `continue`s past a scoreless season *before* that
> line, so whenever the newest season in the snapshot has no scores yet
> (every preseason, including the state production is in now) the guard
> never fires for any season, `last_season_recent` stays empty for every
> owner, and `recent` resolves to a shared 0.5 percentile carrying a
> 0.12 weight. Repaired by binding all six accumulators to the last
> **scored** season; full record in
> `docs/power/V1_52_RECENT_SEASON_BINDING.md`. The original sentence is
> left standing rather than rewritten, because a
> documented-as-verified falsehood is itself part of the record.

**REPRODUCED: YES**, confirmed by a two-season fixture
(`tests/ros/test_power_v2_season_scoping.py`) before any fix — see the
mutation transcript below for the exact RED state.

## Design correction found during this investigation

`career_state.keys()` is ALSO consumed after the accumulation loop, as
the third-priority fallback in `_enumerate_owner_ids` — a genuinely
cross-season *presence* check: a manager who mid-rejoined and is
missing from both live sources this season still needs to appear via
history (the function's own docstring names this exact scenario).
**A blanket reset of `career_state` would fix PPG and silently drop
that owner from the table.**

Fix: `career_state` and its use in `_enumerate_owner_ids` are left
completely untouched. A new, parallel accumulator, `season_state` (same
shape), is declared once and reset to empty at the top of each
season's processing in the accumulation loop — so by loop-end it holds
only the final season's totals, the same "last write wins across the
season boundary" contract `last_season_recent`/`last_season_allplay_share`
already use. `ppg`/`wl_record` (via `_score_state`'s `state["career"]`
read) and the per-week trend snapshot's `"career"` key now read from
`season_state` instead of `career_state`. `wl_record` shares the exact
same bug as `ppg` and is fixed by the same change (not separately
requested, but the same accumulator, same fix).

## Known residual, out of this unit's bounded scope

`season_outcomes` (streak input) and `expected_share_total`
(luck-regression input) share the identical unscoped-across-seasons
accumulation pattern. Flagged in a code comment at their declarations.
Not fixed here — the task's scope is PPG (and its `wl_record` sibling
via the shared accumulator), not every historical-results component.

## Verification

- `tests/ros/test_power_v2_season_scoping.py` — 8 new tests, all
  passing: season-2-only `ppg` percentile ranking (discriminating
  assertion — bravo's real season-2 PPG of 200 must outrank alpha's 10,
  which flips under contamination since alpha's career average would
  be inflated by an extreme season-1), exact `wl_record` values (0.0 /
  1.0 — under contamination both read a tied 0.5, hiding the real
  season-2 gap entirely), both lenses agree, `recentAvg`/`all_play`
  unaffected with exact expected values, trend-series week-1-of-season-2
  uncontaminated, mid-rejoin fallback preserved, unrankable refusal
  unaffected.
- Full `tests/ros/` suite: 229 passed, 1 skipped — 0 regressions.
- Direct consumers outside `tests/ros/`
  (`tests/api/test_public_power_leaks_no_private_quantity.py`,
  `tests/public_league/test_server_routes.py`,
  `tests/roster_intel/test_metric_separation.py`): 31 passed.

## Mutation proof (RED-before / GREEN-after, transcript)

**Mutation 1 — remove the per-season `season_state` reset line:**

```
FAILED test_ppg_percentile_ranks_season_2_only_not_career
  assert 0.25 > 0.75   (bravo's ppg percentile now BELOW alpha's — inverted)
FAILED test_wl_record_is_season_2_only
  assert 0.5 == 0.0    (both owners tied at the career-contaminated 0.5)
FAILED test_both_lenses_agree_on_season_2_only_ppg
  assert 0.25 > 0.75
3 failed, 5 passed
```
Restored → 229 passed, 1 skipped (full `tests/ros/`).

**Mutation 2 — reroute `_enumerate_owner_ids`'s historical-fallback
argument from `career_state.keys()` to `season_state.keys()`** (proves
the "don't blanket-reset `career_state`" design decision is
load-bearing, not cosmetic — without this second mutation a future
"simplification" back to a single accumulator would pass every other
test silently):

```
FAILED test_a_historical_only_owner_still_appears_with_a_real_zero_ppg
  AssertionError: mid-rejoin/departed owner dropped from the table
  assert 'charlie' in {'alpha', 'bravo'}
1 failed, 7 passed
```
Restored → 229 passed, 1 skipped.

## L2 measurements

**(a) Production magnitude — UNMEASURABLE in this environment, stated
honestly rather than skipped.** `data/` is gitignored per this repo's
own convention; the one committed dev fixture,
`data/public_league/snapshot.json`, has 2 seasons but **zero**
matchup data (`matchups_by_week` is empty for both), so no real
multi-season PPG contamination is observable from it — `build_section`
against it finds no scored weeks and cannot demonstrate the bug's
production magnitude either way. This measurement requires an
authenticated production session against
`data/ros/team_strength/latest.json` + the real Sleeper history, the
same "production-only" gate several other V1-52 sub-claims in
`docs/VERSION_1_COMPLETION_CONTRACT.md` already carry (e.g. "the
outstanding L2 measurement is production-scale 12-owner lens-agreement,
which needs the gitignored `data/ros/team_strength/latest.json`").
**Not claimed here.**

**(b) Synthetic fixture delta — exact, from the mutation transcript
above.** Correct (fixed): alpha's season-2 `ppg` percentile 0.25,
bravo's 0.75 (bravo, the real season-2 leader, ranks ahead). Buggy
(mutation 1 applied): alpha 0.75, bravo 0.25 — a complete inversion.
`wl_record`: correct 0.0/1.0 exact; buggy 0.5/0.5 tied.

## Preserved, verified unaffected

- Both canonical lenses (`forward_looking`/`results_only`) read the
  fixed engine identically — asserted directly, not inferred from
  shared code.
- `recentAvg` and `all_play` were already correct and remain correct,
  with exact expected values asserted in the new fixture (not merely
  "test still passes").
  > **CORRECTED 2026-08-24** — see the correction at the top of this
  > document. `recentAvg` was **not** correct: it was measured only when
  > the newest season in the snapshot happened to carry scores, which no
  > preseason satisfies. This fixture asserted exact values and still
  > missed it, because the fixture gives its current season real scores
  > and so never reaches the failing state. Fixed in
  > `docs/power/V1_52_RECENT_SEASON_BINDING.md`; `all_play` was
  > genuinely correct and stays so.
- Unrankable stays a refusal (`powerScore`/`rank` stay `None`, never
  `0.0`) — unaffected, confirmed via the existing proven
  `test_power_unrankable.py` fixture shape.
- `weekRankDelta` does not exist as a field in `power_v2.py` at all —
  it is exclusive to the legacy `src/public_league/power.py`, which
  this unit does not touch (its own separate, pre-existing "resets to
  0 in week 1" issue is out of scope here).

## Freeze

`FEATURE_GREEN` / `READY_FOR_INTEGRATION`. Does not authorize further
V1-52 feature work. `#996`/`#1009` remain frozen and untouched. Claude
5 owns: this PPG fix landing → `#996` → `#1009` → shipping-tree CI →
the real 12-owner L2 measurement, using the verification recipe already
prepared at `docs/power/V1_52_L2_VERIFICATION_RECIPE.md` (prior
session, PR #1028).
