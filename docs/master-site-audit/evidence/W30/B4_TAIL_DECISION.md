# B4 / W30-F023 — decision

## Recommendation

**BLOCKED BY A CANONICAL DEPENDENCY.**

The repair is identified, measured and one constant wide
(`tail_policy.TAIL_SATURATION_RANK = 903`). It is **not applied**,
because applying it drives the B3 market corridor onto rows B3's own
repair criteria state it must not touch, through the two residuals that
were deliberately left open — **#794** (corridor anchor/voter
circularity) and **#795** (systemic-drift self-widening).

B4's scope forbids reopening B3, and the standing instruction for this
case is explicit: *if a tail change exposes a new corridor defect, record
and stop*. This is that record.

**Is the chosen policy continuous, bounded, unchanged, or other?**
*Bounded at a justified boundary* — rank 903, the deepest rank any source
publishes. That is the policy the evidence selects. What ships today is
**unchanged**, pending the dependency.

## What shipped

| | |
|---|---|
| Production values | **unchanged** — all 1,092 rows hash identically |
| Tail policy owner | **one**, was four (`src/canonical/tail_policy.py`) |
| `valueContributionPath` | fixed — was re-derived, now recorded |
| W30-F023 assertions | `xfail(strict=True)`, still failing, still describing the defect |

The single-owner refactor is a W30-F008-class repair in its own right and
is behaviour-preserving, so it lands. Before it, serving, fitting and
holdout scoring each decided the tail separately; a repaired board would
have been scored by a saturated evaluator and any refit would have
re-learned the saturated shape. That is now structurally impossible.

## The defect, as measured on the pin

Board `dynasty_data_2026-08-11.json` sha256 `8fb6ede274171aee…`.

**421 of 5,146 rank-Hill observations sit past rank 500 (8.18%), touching
254 board rows — every one of them served.** That last clause was the
missing distinction: `254 / 1,092` mixes published rows with 352 rows the
board never serves, and understates the user-visible rate. Against the
740 served rows it is **34.3%**.

| bucket | all rows | served rows |
|---|---|---|
| DB | 62.6% | **79.8%** |
| DL/EDGE | 66.9% | **75.2%** |
| LB | 43.0% | **53.8%** |
| TE | 14.5% | 15.0% |
| QB / RB / WR | 5.7 / 1.4 / 1.4% | 7.1 / 2.0 / 2.1% |
| picks | 0.0% | 0.0% |

The unserved-but-touched population is **empty**, which is worth stating
because it changes what a membership effect at the board cut can be: rows
cross the cut by being displaced by the repricing of these 254, not by
being promoted out of a touched-but-unserved pool, because there is none.

## Candidates, against criteria declared first

Criteria are in `b4_candidate_measure.py` and were declared before any
candidate was scored. One needed a measurement clarification, recorded in
place rather than silently applied: "strictly decreasing per unit rank"
is unachievable by *every* candidate including the current one, because
contributions are integers and adjacent deep ranks tie on rounding.

| cand | head delta | separation | strict/evidence | invents evidence | V@50000 |
|---|---|---|---|---|---|
| A current | 0 | 0.125 | no | no | 1698 |
| B continuous | 0 | 1.000 | yes | **yes** | 72 |
| C877 | 0 | 1.000 | yes | no | 1197 |
| **C903** | 0 | 1.000 | yes | no | 1175 |
| D per-source | **1063** | 1.000 | yes | no | — |

* **A** is the defect: eight distinct live ranks, one value.
* **D** (per-source native-pool coordinate) is disqualified twice — it
  moves the fitted head by 1063 and prices rank 600 at six different
  values depending on which source supplied it, so the coordinate stops
  being a shared unit. That is W30-F008 re-created. Worth measuring
  because it is the strictest reading of "missing is never zero"; the
  measurement is what refuses it.
* **B and C are observationally identical on this board** — max |delta| 0
  across every rank 1..877. The choice is not decidable from the data and
  falls to criteria 4/5, about ranks nobody has published. B resolves rank
  50,000 to 72, a value no evidence supports; C stops resolving where
  evidence stops.
* **C903 over C877**: 877 is this pin's deepest rank-Hill rank and has no
  headroom, and it would re-saturate the 878..899 band `idpTradeCalc`
  publishes — reachable through the value-direct fallback branch. 903 is
  the deepest rank any source publishes, corroborated independently at
  `src/api/source_history.py:352-353`.

**A bounded tail is a change of units, not a refit** — asserted as
arithmetic, not prose. Re-expressing the curve in a universe `N' = R_MAX`
with `c' = c·(N−1)/(N'−1)` and keeping `(c, s, N)` while raising the
coordinate ceiling to `p_max = (R_MAX−1)/(N−1)` agree at **every** rank on
all three masters, max |delta| 0. The rank-space midpoint `M = c·(N−1)` is
the invariant (B1.2). This is also why "do not simply change
`PERCENTILE_REFERENCE_N`" is satisfied rather than dodged: changing N
alone moves `M` and genuinely reshapes the curve, while the ceiling
formulation touches no committed constant at all.

## Board impact of the repair (measured, not shipped)

Identical pinned input, tail at 500 vs 903.

* **252 of 1,092 rows change value**; 36 of them carry no saturated
  observation at all, i.e. second-order blend/corridor coupling.
* Rank movement over 707 rows ranked in both: median 0, p10 −30, p90 +33,
  range −74..+104.
* **Served count is unchanged at 740**, with 33 rows swapped across the
  cut in each direction. The promotions are offense depth (Nick Chubb,
  Kareem Hunt, Will Levis); the drops are deep IDP (Sauce Gardner, Pat
  Surtain, Jaycee Horn) — the direction the defect predicts.
* Top 50 and top 100 **identical**; top 200 one row in/out; top 400 twelve.
* Positional movement lands where the defect is: DL/EDGE 61.4%, DB 51.8%,
  LB 37.7%, against WR 1.4% and RB 1.4%.
* **Picks move despite 0.0% saturated observations** — 30 rows, all 5th/6th
  round, −47..−80. Explained, not dismissed: current-year slot picks are
  tethered to the merged rookie pool (Phase 5.2b), which includes IDP
  rookies whose values fell. The chain is evidence → rookie pool → tether,
  not a pick-side effect.
* **Two rows rose while no contribution of theirs rose** — Abdul Carter
  +372, Dallas Turner +77. B1.2 saw this class of movement and it must be
  explained: both are corridor clamps that newly fired *upward*. Not a
  blend anomaly; it is the dependency below.

## The blocking dependency

The corridor's band is a **P90 of the drift distribution of the board it
is clamping**, computed per confidence bucket. So values feed the band and
the band feeds values.

Removing the saturation lowers deep IDP blends, which changes that
distribution, which **narrows the band from ~0.63 to ~0.46**. A narrower
corridor overrides more aggressively — including rows that were never its
target.

| | before | after |
|---|---|---|
| clamps applied | 32 | 27 |
| newly clamped | — | 14 |
| direction | all `down` | 24 `down`, **3 `up`** |
| anchor source | `idpTradeCalc` ×32 | `idpTradeCalc` ×27 |
| bandPct min/med/max | 0.518 / 0.632 / 0.650 | 0.256 / 0.461 / 0.461 |

Two B3 characterization tests fail as a direct result, and they encode
B3's own repair criteria:

* `test_the_corridor_no_longer_overrides_well_covered_rows` — four rows
  with five or more contributing sources are clamped. B3's criterion was
  that after its repair, *no* such row is clamped at all.
* `test_the_corridor_is_a_tail_rail_not_a_majority_of_the_board` — three
  clamped rows land in the top third of the IDP board.

Abdul Carter is the clean example, and note what he is not: he has **no
rank past 500**. None of his five sources moved. He is clamped because the
*band* moved — from below his 32.5% drift to 25.6% — and then dragged
+372 toward `idpTradeCalc`, which is itself one of his five voters.

That is #794 and #795 exactly:

* **#794 anchor/voter circularity** — all 27 clamps anchor on
  `idpTradeCalc`, a source that also votes in the blend it is correcting.
  Under the repair its co-voters fall while it does not (it is
  value-direct), so it pulls the row back toward itself.
* **#795 systemic-drift self-widening** — the saturation was inflating
  deep IDP values, which inflated the board's own drift distribution,
  which widened the band. The band was partly a measurement of the
  defect. Fixing the defect tightens the corridor onto unrelated rows.

Neither is separable from the tail policy on this board, and both are
explicitly out of B4's scope.

## Not changed, and why

* **`PERCENTILE_REFERENCE_N`** — untouched. It is a coordinate unit; the
  boundary is a separate quantity.
* **Champion constants** — untouched. No promote, no apply, no refit.
  Registry stays v2.
* **`OVERALL_RANK_LIMIT` (800)** — untouched, and confirmed as the wrong
  domain for this: `idpShow` reaches effective rank 877 on rows the board
  publishes, so saturating at the board limit would still collapse
  genuine evidence. Board rank and source coordinate are different things.
* **B3 corridor methodology, TEP, confidence, source weights** — untouched.
* **`HillCurveExplorer.jsx`** — still extrapolates continuously past rank
  500 with no `p ≤ 1` clamp, so the drawn curve and its own scatter
  diverge past 500 on the live page today. Deliberately left: it currently
  draws the *repaired* curve, so "fixing" it now means making it draw the
  saturated one, which the repair would immediately undo. It is a
  user-visible symptom of W30-F023 and should be resolved with it.

## Gates

| gate | result |
|---|---|
| `tests/canonical/test_percentile_tail_policy.py` | 8 RED before the owner landed → **17 passed / 8 xfailed(strict)** |
| full `pytest tests/ -q -m "not livedata"` | **6,912 passed / 0 failed**, 8 xfailed, 18 skipped, 278 deselected, 294 subtests (525 s) |
| `pytest -m livedata` | **253 passed / 0 failed**, 25 skipped, 336 subtests |
| `vitest run` (frontend) | **2,010 passed / 0 failed**, 121 files — unchanged, the change is backend-only |
| `npm --prefix frontend run build` | compiled; **all 14 route bundle budgets under** |
| `ruff check .` | All checks passed |
| `ruff format --check .` | 1,014 files already formatted |
| `scripts/check_decision_coercions.py` | clean in the files this change touches |
| `scripts/audit_status.py` | no drift (21 closed / 19 open / 2 needs_review / 1 deferred) |
| CI `Validate PR` at exact HEAD | recorded on PR #798 — a doc cannot contain the result of the run that includes it, so the final conclusion is stated there rather than asserted here |

The Python count is **6,912 + 8 xfailed = 6,920** against B3's 6,913 — the
delta is the seven new non-xfail tests in this file and nothing else. No
pre-existing test changed state, which is the load-bearing claim: the four
tests that pin the collapse as intentional
(`test_coordinate_equivalence.py`, `test_percentile_coordinate_contract.py`,
`test_valuation_pipeline_stages.py`) and the two B3 corridor
characterizations all still pass, because production behaviour did not
move. They were observed to fail under the applied repair — that
measurement is §"The blocking dependency" — and pass again once it was
withdrawn.

The first exact-HEAD CI run failed on `ruff format --check` for two
evidence scripts (my formatting; tests green in the same run) and was
fixed in `fde9e31bc`. That fix also corrected a real defect it exposed:
the harness's tautology guard grepped for clamp source-text the
single-owner refactor had removed, so it would have reported "no clamps
found" on a tree whose saturation is unchanged. It is now behavioural.

## What would unblock this

A decision on #794/#795 — specifically whether the corridor may anchor on
a source that is also a voter, and whether its band may be derived from
the same board it is correcting. Until then, setting
`TAIL_SATURATION_RANK` to 903 trades a measured IDP-tail defect for a
measured corridor defect, which is not an improvement that can be
asserted from this evidence.

The re-run after that decision is cheap and already written:
`b4_board_impact.py --report` diffs the two boards on the same pin.
