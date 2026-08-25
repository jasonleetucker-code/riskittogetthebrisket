# V1-52 follow-up 2 — `recent` / `all_play` bind to the last SCORED season

2026-08-24. Claude 3 — Season/Scoring/Projections. One code file, one test
file, two doc corrections. V1-52 is `IMPLEMENTED_UNVERIFIED`; this closes an
**independent implementation defect** found while re-confirming whether the row
is purely state-blocked. It does not promote the row.

## Why this was looked for at all

The dispatch asked me to confirm — not assume — that V1-52's remaining gap is
pure state blockage (Section 3 of `docs/power/V1_52_L2_VERIFICATION_RECIPE.md`
needs real scored weeks) with **no independent implementation defect hiding
behind the missing observation**.

There is one. The confirmation failed, and this is it.

## The defect

`src/ros/power_v2.py::build_section`:

```python
for season in seasons_sorted:
    week_scores = luck._season_weekly_scores(season, registry)
    if not week_scores:
        continue                      # <-- scoreless season skipped HERE
    ...
    if season is seasons_sorted[-1]:  # <-- ...but the gate is on the LIST
        recent_buffer = defaultdict(list)
```

`seasons_sorted[-1]` is the newest season **in the snapshot**, not the newest
season **with scores**. Those diverge in exactly one situation — and it is the
situation production is in right now:

> a scoreless current season sitting after prior scored seasons, i.e. every
> preseason.

2026 is `seasons_sorted[-1]`, and 2026 `continue`s at the top. So the guard
never fires for 2024 or 2025 either, and `last_season_recent` stays **empty for
every owner, permanently**.

`_score_state` then reads:

```python
rb = state["recent"].get(oid, [])
recent = sum(rb) / len(rb) if rb else 0.0
```

→ `0.0` for everyone → `_percentile` over an all-equal list → **0.5 for
everyone**.

### Why it matters

`WEIGHTS["recent"] = 0.12`. On the results-only lens the active weights sum to
0.55, so **0.12 / 0.55 ≈ 21.8% of every published results-only `powerScore` is
a constant nobody measured.** Rank *order* is not disturbed (a shared constant
shifts all owners equally), which is precisely why it survived — but every
score is inflated by an unmeasured term, and the UI renders `recentAvg` as a
literal `0.0` in the "Recent avg" column, presenting an absent observation as a
measurement. That is the "missing is never zero" rule inverted on a public
surface.

It also sits directly on V1-52's own critical path: Section 3(b) of the L2
recipe eyeballs `rank / displayName / powerScore / record`. Re-running Section 3
against this engine would have measured a corrupted `powerScore` column.

## L2 — measured on the live production board, not asserted

`GET https://chaseupside.com/api/public/league/rosPower?lens=results_only`,
2026-08-24, the real 12-owner league:

```
preseason: True    unrankable: None    rows: 12
effectiveWeights: {ppg 0.18, recent 0.12, wl_record 0.10,
                   all_play 0.08, streak 0.05, luck_regression 0.02}

 1. Brent     82.41   recent=0.5  recentAvg=0.0  ppg=443.36
 2. Joey      73.74   recent=0.5  recentAvg=0.0  ppg=385.17
 3. Ed        66.59   recent=0.5  recentAvg=0.0  ppg=393.44
 ...
11. jstuedle  20.00   recent=0.5  recentAvg=0.0  ppg=0.00
12. Blaine    20.00   recent=0.5  recentAvg=0.0  ppg=0.00

distinct recent percentiles across all rows: [0.5]
distinct recentAvg across all rows:          [0.0]
```

- **12 of 12** headline rows carry `recent = 0.5` and `recentAvg = 0.0`.
- **108 of 108** trend rows (9 weeks × 12 owners) carry the same.
- Active weights sum to **0.5500**; `recent` is **21.82%** of the published
  score.
- Every `powerScore` on the board therefore contains
  `0.5 × 0.12 / 0.55 × 100 = **10.91 points** of unmeasured constant.

Two facts this measurement also settles, both relevant to V1-52's remaining bar
and both recorded in the handoff rather than acted on here:

1. **The results-only lens is NOT refusing.** `unrankable: None`, twelve real
   ranks, real scores 82.41 → 20.00. The premise that "both lenses correctly
   refuse so there are no numeric ranks to compare" does not describe
   production.
2. **Two owners with no games played receive real numeric ranks** (`ppg 0.0`,
   `powerScore 20.00`, ranks 11-12) assembled entirely from component defaults
   — indistinguishable from a measured last place. That is an owner call, not a
   defect I may decide; it is listed as `OWNER_DECISION_REQUIRED`.

### Same family as the two fixes already merged this session

| PR | accumulator | fed |
|---|---|---|
| #1032 | `season_state` | `ppg`, `wl_record` |
| #1059 | `season_outcomes`, `expected_share_total` | `streak`, `luck_regression` |
| **this** | `last_season_recent`, `last_season_allplay_share` | `recent`, `all_play` |

Those two PRs reset their accumulators *after* the `continue`, so they
correctly hold the last **scored** season. The recent-form buffer was the one
that never got the same treatment — it kept a gate that only coincidentally
agreed with them, and only while the newest season had scores.

### It was documented as verified

`docs/power/V1_52_PPG_SEASON_SCOPING.md` (#1032's own record) asserts:

> "`recentAvg` and `all_play` were already correctly season-scoped (gated by
> `if season is seasons_sorted[-1]:` …), which is what proves the defect was in
> the accumulator specifically"

and

> "`recentAvg` and `all_play` were already correct and remain correct."

It cites the defective gate as proof of correctness. Both passages are
corrected in place (append-only; the originals are left standing, because a
documented-as-verified falsehood is itself part of the record).

## Fix

All six accumulators now reset at the same point, on each **scored** season:

```python
season_state = defaultdict(...)
season_outcomes = defaultdict(list)
expected_share_total = defaultdict(float)
last_season_recent = defaultdict(list)      # new
last_season_allplay_share = {}              # new
recent_buffer = defaultdict(list)           # no longer gated
```

and the per-week write drops its `if season is seasons_sorted[-1]:` guard.

"The last **scored** season wins" is now structural for every accumulator
rather than a property of which season happens to sit last in the list. The two
can no longer diverge.

`last_season_allplay_share` is included deliberately, not opportunistically.
Its unconditional overwrite was correct for owners who played the last scored
season, but an owner in the table who did **not** play it kept a stale
prior-season share — while their `season_state` correctly went empty. Resetting
it alongside makes the three agree about which season they describe. That path
was live-reachable and unpinned by any test.

## Why no test caught it

No fixture had the production shape. Every two-season fixture in
`tests/ros/test_power_v2_season_scoping.py` gives the current season real
scores, so the gate fires and the bug is invisible.
`tests/ros/test_power_unrankable.py`'s fixtures are single-season, so the last
scored season *is* `seasons_sorted[-1]`. `#1032`'s own
`test_recent_avg_is_exact_and_unaffected_by_the_fix` asserts only
`bravo > alpha`, which holds under the defect.

## Tests

New `TestRecentFormSurvivesAScorelessCurrentSeason` in
`tests/ros/test_power_v2_season_scoping.py`, on a new
`_preseason_shape_snapshot()`: 2025 complete with four scored weeks, 2026
present and **scoreless**.

Four weeks against `_RECENT_WINDOW = 3` is deliberate — the trailing window must
drop week 1, so a buffer that never slid would give alpha 265.0 instead of 20.0
and be caught.

- `test_the_fixture_really_is_the_preseason_shape` — non-vacuity: asserts 2026
  is the newest season *and* carries no matchups, so the fixture cannot quietly
  stop discriminating the way the older ones do.
- `test_recent_avg_is_the_last_scored_seasons_trailing_window` — exact values
  (alpha 20.0, bravo 200.0).
- `test_recent_percentiles_are_measured_not_a_shared_default` — asserts the two
  percentiles are not both 0.5.
- `test_all_play_also_survives_the_scoreless_season`.
- `test_recent_still_carries_its_declared_weight` — guards the opposite failure:
  a "fix" that silently dropped the component would also stop it being constant.

## Mutation proof (RED-before / GREEN-after)

Restored the retired `seasons_sorted[-1]` binding at both sites:

```
FAILED test_recent_avg_is_the_last_scored_seasons_trailing_window
FAILED test_recent_percentiles_are_measured_not_a_shared_default
  AssertionError: every owner sharing the 0.5 midpoint is the signature of an
  unmeasured component, not a real tie
  assert {0.5} != {0.5}
2 failed, 3 passed
```

The failure reproduced the predicted signature exactly — a single shared 0.5
across all owners. Restored → 16/16 green.

Stated honestly: `test_all_play_also_survives_the_scoreless_season` **passes
under the mutation**. `all_play`'s unconditional overwrite already worked in the
preseason shape, so that test is a regression guard for the reset added here,
not part of the RED proof.

### `all_play` — the contradiction this document used to carry, resolved

**Corrected 2026-08-25 (owner traffic-control on #1081).** The heading and the
change table above both say this unit binds `all_play` to the last scored
season, while the paragraph directly above said its defect "needs a third-season
fixture to exhibit and is not claimed as reproduced." Those cannot both be the
whole story, and the gap between them is exactly where a reader would form a
wrong belief. Split into the two separate claims it was conflating:

* **`all_play`'s season RESET is fixed here, and is now pinned.** The
  third-season fixture that was called for exists —
  `TestEverySeasonResetHoldsAcrossThreeSeasons` — and asserts that `all_play`,
  like `ppg`/`wl_record`/`streak`/`luck_regression`/`recent`, describes the last
  **scored** season and not a prior one. No claim rests on an unwritten fixture
  any more.
* **`all_play`'s MISSING-value semantics are NOT fixed here.** An owner absent
  from the last scored season still resolves through
  `state["allplay"].get(oid, 0.0)` — a coercion of the same family as the one
  removed from `recent`. That is deliberate and scoped: the owner direction on
  this PR names *recent-form* as the component that must stay unknown, and
  widening a published-value semantic beyond the direction would be inventing
  scope, not following it. Recorded here as a known, named residual rather than
  quietly fixed or quietly ignored.

## Missing is never zero — the second repair

The first repair bound recent form to the last **scored** season. That fixed
*which* season it describes and left the unmeasured case coerced:
`recent = sum(rb) / len(rb) if rb else 0.0`. Because every owner shared that
`0.0`, `_percentile` returned a confident **0.5 for all of them** — an
unmeasured component published as a midpoint, which is the original defect
wearing a different mask.

Per the owner invariant (missing/unknown != zero) both missing cases now stay
unknown, and they resolve through two different mechanisms because the
missingness lives at two different granularities:

| case | who lacks it | mechanism |
|---|---|---|
| (a) no scored weeks anywhere | everyone | `"recent"` joins `missing_inputs`, so the weight renormalises away league-wide — the **same** path `team_ros_strength` and `schedule_adjusted` already use |
| (b) an owner absent from the last scored season | one owner | the component stays in the section budget; that **row's** `weightsApplied` drops it and its score renormalises over the weights it actually has |

Neither invents a rule. (a) is the existing league-wide renormalisation; (b) is
that identical rule applied at the granularity the missingness has. The two
alternatives were both explicitly ruled out: multiplying the weight by a
stand-in is the coercion being removed, and leaving the weight in the divisor
against a zero numerator deflates the score by exactly that weight — the silent
deflation the league-wide renormalisation exists to prevent.

`_percentile` needed no change: it already excludes `None` from its comparison
population (`eligible = [v for v in values if v is not None]`), so an unmeasured
owner cannot drag the scale others are ranked against.

**The frontend needed no change either**, and that was verified rather than
assumed: `ros-power.jsx`'s `fmtRaw` already renders `null` as `—`, and
`ComponentBar` returns `null` for a weight it cannot find — so an unmeasured
component's bar vanishes instead of rendering a fabricated 0%. Publishing
per-row `weightsApplied` is what makes that work, and the field name already
said "Applied".

An owner with **nothing** measurable refuses outright (`powerScore: None`,
`rank: None`) and sorts last without consuming a rank — the same rule as the
section-level refusal, at the same granularity as the rest of this change.

### Mutation proof for the missing-is-never-zero repair

Three mutations, each restoring one of the coercions the owner named, all RED
then restored GREEN:

```
A  recent = ... if rb else 0.0            (coerce to zero)     -> 4 failed
B  "recent": 0.5 if i["recent"] is None   (coerce to neutral)  -> 3 failed
C  owner_weights = active_weights          (keep the weight)    -> 5 failed
```

C fails loudest because a `None` component reaching the weighted sum is a
`TypeError`, not a wrong number — the coercion cannot be reintroduced quietly.

## Regression

`tests/ros/` + `tests/public_league/`: **671 passed, 2 skipped, 0 failed.**
`ruff format --check` / `ruff check` clean.

## Scope

`src/ros/power_v2.py` (one reset block, one write site), its season-scoping test
file, this document, and two corrections in
`docs/power/V1_52_PPG_SEASON_SCOPING.md`. `career_state` is untouched (it is
career-scoped on purpose and backs `_enumerate_owner_ids`'s historical-presence
fallback). No weight, lens, refusal contract, or methodology changed. Does not
promote V1-52 — see the handoff for what that still needs.
