# Legacy rank-form Hill curve — backtest and decision

**Date:** 2026-07-29
**Script:** `scripts/backtest_legacy_rank_curve.py`
**Results:** `docs/measurements/legacy-rank-curve-backtest-2026-07-29.json`
**Reproduce:** `python scripts/backtest_legacy_rank_curve.py --out docs/measurements/<name>.json`

## Why this was measured

The platform carries **two independently-maintained families of Hill
constants**:

| family | constants | refit by | in the model registry? |
|---|---|---|---|
| percentile-form scope masters | `HILL_*_PERCENTILE_C/S` | `scripts/fit_hill_curve_percentile.py` + weekly `refit-hill-curves.yml` | yes (`CONSTANT_NAMES`) |
| legacy rank-form | `HILL_MIDPOINT/SLOPE`, `IDP_HILL_MIDPOINT/SLOPE` | `scripts/fit_hill_curve_from_market.py` | **no** |

The live board blends with the percentile family. The legacy family
survives on two *reconstruction* paths that answer "what would the
board have said for this rank?" when a real value is missing:

- `src/api/rank_history.py::_value_from_rank` — historical log entries
  that persisted a rank but not a value (per-source values only began
  persisting 2026-04-29). **Actively exercised in production.**
- `src/api/terminal.py::_row_value` — a ranked row carrying neither
  `rankDerivedValue` nor `values.full`. **Dormant**: 0 of 740 ranked
  rows on the 2026-07-29 payload hit it.

Because the two families drift independently, a reconstruction can
disagree with the board it is standing in for. This is a *consistency*
question, not a predictive-accuracy one — the board is the authority on
value, so the metric is simply how closely each candidate curve
reproduces `rankDerivedValue` from `canonicalConsensusRank` alone.

## Results

740 ranked rows (428 offense, 281 IDP, 31 picks). Error on the 1–9999
display scale; negative mean-signed error = the candidate **understates**
the board.

| candidate | overall RMSE | MAE | median abs | mean signed | IDP | offense | pick |
|---|---|---|---|---|---|---|---|
| best-fit rank-form (reference) | **96.3** | 65.7 | 47.0 | −15.2 | 65.6 | 113.5 | 68.7 |
| `percentile_global` | 238.4 | 177.8 | 122.0 | −112.7 | 164.9 | 278.8 | 193.4 |
| `percentile_scope` | 563.4 | 524.7 | 546.5 | −522.8 | 525.6 | 581.3 | 638.9 |
| `percentile_offense` | 589.4 | 559.0 | 604.5 | −557.3 | 595.8 | 581.3 | 638.9 |
| `legacy_scope` (rank_history today) | 670.3 | 539.3 | 698.5 | −529.2 | **78.7** | 845.9 | 887.8 |
| `legacy_offense` (terminal *before* this audit) | 840.4 | 823.1 | 828.5 | −823.1 | 826.5 | 845.9 | 887.8 |

A rank-form curve refit to the current board lands at
**midpoint 68.8 / slope 0.929** — very close to the existing *IDP*
constants (69.50 / 0.945), which is why `legacy_scope` scores so well on
IDP rows and so badly everywhere else.

### The error profiles are inverted

RMSE by rank band — this is the reason the family choice is not obvious:

| band | `legacy_offense` | `legacy_scope` | `percentile_global` | best-fit |
|---|---|---|---|---|
| 1–24 | 396 | 396 | **703** | 342 |
| 25–60 | 724 | 680 | 524 | 110 |
| 61–120 | 1017 | 944 | 352 | 91 |
| 121–250 | 1040 | 815 | 202 | 107 |
| 251–500 | 852 | 692 | 112 | 54 |
| 501+ | 695 | 468 | 136 | 62 |

`percentile_global` is dramatically better past rank ~60 but roughly
**twice as bad in the top 24**, where board values are driven by
value-direct KTC/IDPTC votes rather than any smooth rank curve.

## What was changed

Only the part the evidence makes unambiguous: **the two callers now
share one implementation and route by scope.**

`src/canonical/player_valuation.py::rank_to_value_for_scope` is now the
single implementation. `rank_history.py` delegates to it (behaviour
unchanged — it already routed by scope); `terminal.py` now uses it in
both of its fallback sites, where it previously applied the *offense*
curve to every row including IDP and picks.

Effect: IDP reconstruction RMSE **826 → 79**. Offense and pick
reconstruction are unchanged. This costs nothing — it uses constants
that already existed — and removes a case of two modules answering one
question two ways.

Terminal's second call site (`_roster_value_on_date`, historical roster
sums) resolves scope via the `row_index` it already receives. A roster
in this league starts nine IDP players, so the previous offense-curve
treatment understated a historical roster sum by roughly 800 points per
defender. Players no longer on the board fall back to the offense curve,
unchanged from before.

Pinned by `tests/canonical/test_rank_to_value_scope.py`.

## Open modeling decision — NOT taken here

**Should the legacy rank-form family be retired in favour of the
registry-managed percentile masters (or a refit)?**

Arguments to migrate:
- It would eliminate a constant family that sits outside the model
  registry, is refit by a different script on a different cadence, and
  has no out-of-sample gate — exactly the drift surface this audit
  exists to find.
- `percentile_global` beats the legacy family overall (238 vs 670).

Arguments against migrating as-is:
- It is ~2x worse in the top 24, the most visible part of any chart.
- It changes user-visible historical values on `/terminal` and the
  value-history chart. That is a product call, not a cleanup.
- A refit (68.8 / 0.929) fits far better than either live option, but
  adopting it would *re-create* the unmanaged second family rather than
  remove it — unless the refit is simultaneously brought under the model
  registry.

**Recommendation:** treat this as a scoped follow-up — bring the
rank-form reconstruction under the model registry and refit it there,
OR migrate the reconstruction paths to the percentile masters and accept
the top-24 degradation on a path that is already a fallback. Re-run the
script above after any curve change; it is the regression check.

Deliberately not decided inside an audit fix, per the guardrail that
questionable formulas be flagged rather than silently rewritten.

---

# Addendum — 2026-07-30: the family was re-tuned, not retired

**Script:** `scripts/backtest_legacy_rank_curve.py` (now fits per scope)
**Drift check:** `scripts/check_rank_form_drift.py`
**Results:** `docs/measurements/legacy-rank-curve-2026-07-30.json`

## The decision

Re-tune the rank-form constants against **our board**, keep the family,
and put a drift alarm on it. Both migration options above are off the
table for a reason that only became visible on re-measurement.

| constant | was | now |
|---|---|---|
| `HILL_MIDPOINT` | 48.44 | **65.4** |
| `HILL_SLOPE` | 1.149 | **0.910** |
| `IDP_HILL_MIDPOINT` | 69.50 | **64.6** |
| `IDP_HILL_SLOPE` | 0.945 | **0.900** |

Measured on the 2026-07-30 board (740 ranked rows: 420 offense, 292 IDP,
28 picks):

| candidate | overall RMSE | IDP | offense | pick |
|---|---|---|---|---|
| `legacy_scope` — **re-tuned** | **83.8** | 76.2 | 89.8 | 64.7 |
| best-fit per scope (floor) | 83.4 | 76.2 | 89.8 | 47.6 |
| best-fit single curve | 84.0 | 76.4 | 90.1 | 61.9 |
| `legacy_scope` — old constants | 644.9 | 89.5 | 821.8 | 882.9 |
| `percentile_global` | 410.1 | 459.0 | 380.6 | 276.5 |
| `percentile_scope` | 691.8 | 835.0 | 575.5 | 639.0 |

Offense reconstruction error drops **821.8 → 89.8**, a ~9× improvement on
every reconstructed offense value. IDP improves 89.5 → 76.2.

## Three things the first pass got wrong

**1. The old constants were fit to the wrong target.**
`scripts/fit_hill_curve_from_market.py` fits retail *source* boards —
"what shape does KTC publish". These constants have to answer "what does
*our* board pay at rank r", which is the output of the entire pipeline
after blending, TE basis conversion, α-shrinkage, the single-source
haircut, the corridor clamp and pick tethering. Those are different
questions, and the 821.8 RMSE is the size of the difference. Fitting
against `rankDerivedValue` is the correct target and that is what the
backtest script does.

**2. "The error profiles are inverted" no longer holds.**
The 2026-07-29 table showed `percentile_global` beating the legacy family
overall (238 vs 670) while being ~2× worse in the top 24, which is what
made the migration question genuinely hard. On the current board the
percentile candidates are 5–8× worse *everywhere* (410 and 692 against
83.8). The reason is structural, not a data shift: **the percentile
masters are an INPUT stage to the blend, not a model of its output.**
Translating them into rank space cannot answer this question, so
migrating the reconstruction paths onto them is not a live option.

**3. The offense/IDP split is much weaker than its comment claimed.**
The old rationale — dynasty IDP markets price differently from offense —
is a true statement about retail IDP boards and an irrelevant one here.
`canonicalConsensusRank` is a single **global** ordinal over the whole
board, so offense, IDP and pick rows all lie on one rank→value relation
by construction. Fitting per scope buys 84.0 → 83.4 RMSE (0.7%), and the
two fitted pairs are nearly identical (65.4/0.910 vs 64.6/0.900). The old
IDP pair scored well on IDP rows largely by coincidence: it happened to
sit near the global optimum while the offense pair did not.

The split is kept because `rank_history.py` already routes by scope and
the numbers are marginally better, but it should not be read as evidence
of two economies. If ranks ever become scope-local, re-fit and revisit.

## The re-tune is at the floor

83.8 against an achievable 83.4 means **there is no headroom left in this
curve family.** The residual ~84 RMSE is irreducible scatter: the board
is not a pure function of rank, because post-blend stages (pick
tethering, the two-way boost, the corridor clamp) move individual rows
off any smooth curve. A further refit cannot help; only a
reconstruction that uses more than the rank could.

## Stability: what moves these constants

Fit against 16 archived snapshots spanning **2026-07-16 → 07-30**
(`exports/archive/`, every 8th export):

| scope | midpoint range | slope range |
|---|---|---|
| offense | 65.4 (65.6 once) | 0.910 throughout |
| idp | 64.4 – 64.6 | 0.900 throughout |
| pick | 61.8 – 62.8 | 0.869 – 0.880 |

Market churn does **not** move them, and the reason matters: the board's
rank→value relation *is* a Hill curve, so churn only permutes which
player sits at which rank.

What does move them is a **percentile-master promotion**. The masters are
step 3 of the live pipeline, so a new pair reshapes the board and the
rank-form approximation goes stale. Measured directly: the 2026-07-29
pre-promotion board refit to **68.8 / 0.929**, the post-promotion board
to **65.2 / 0.905**.

That is a useful finding on its own — it means the right cadence for this
check is "after a promotion", not "daily".

## The drift alarm

`scripts/check_rank_form_drift.py`, run weekly by
`.github/workflows/audit-rank-form-drift.yml` (Tue 07:41 UTC, after
`refit-hill-curves.yml` at 06:17).

The metric is **excess RMSE** = RMSE(committed constants) −
RMSE(refit optimum), per scope, budget 25.0 on the display scale. Not
parameter delta: parameters are partially redundant, so a curve can move
its numbers and still reproduce the board, while a small move near a
steep optimum can matter more than a large one on a plateau. Excess RMSE
measures the thing that actually matters — whether the committed curve
still reproduces the board.

Calibration of the 25.0 budget, on real data:

| constants | excess RMSE | verdict |
|---|---|---|
| the new pair (offense) | +0.0 | ok |
| the new pair (IDP) | +0.0 | ok |
| old IDP pair (69.50/0.945) | +13.3 | ok — near the optimum by luck |
| old offense pair (48.44/1.149) | **+731.9** | drift |
| a promotion-sized move (68.8/0.929) | over budget | drift |

**It opens an issue, not a pull request, and that is deliberate.**
ADR-008 (`docs/roster-trade-intelligence/DECISIONS.md`) prohibits a model
autonomously rewriting production constants; its sharpest finding is that
the old auto-refit path was green *by construction* because it rewrote
the very test that guarded it. An automated patch that fixed
`player_valuation.py` and also re-baselined
`test_rank_form_constants_tripwire.py` would rebuild exactly that
circularity. So the automation computes the fix and prints the constants
plus the three files to write them in; a human applies them, the tripwire
fails, and updating the pins is the deliberate recorded act.

The alarm is itself tested — `tests/canonical/test_rank_form_drift_check.py`
proves it fires on the pre-re-tune pair and on a promotion-sized move,
because an alarm that cannot fire reads identically to a healthy system.

## The third copy of these constants

`frontend/lib/value-history.js` mirrors the offense pair for the terminal
team-value chart and the derived rank-history line. On 2026-07-30 it
still read `K = 45, EXP = 1.1, CEIL = 9999` — three values wrong at once
(the backend pair was 48.44 / 1.149, and `1 + 9999/(…)` puts rank 1 at
**10000** rather than 9999). Its own comment flagged the drift risk and
deferred the fix to a follow-up that never happened.

Now `RANK_FORM_CURVE` in that file is the single place the numbers appear,
and `tests/api/test_rank_form_frontend_parity.py` parses it and fails if
it disagrees with Python — including a formula check across twelve ranks,
so a divergence in the arithmetic (not just the constants) also fails.

## Pre-existing failure found while doing this

`tests/canonical/test_ktc_reconciliation.py` has **9 failing cases on
`main`**, unrelated to this change and confirmed by running it at a clean
HEAD. Its `PINNED_DELTAS` were baselined against percentile constants
that have since been promoted, so `_ours(rank)` no longer matches. It is
auto-marked `livedata` by `tests/conftest.py`, so CI runs it
`continue-on-error` and the staleness is invisible.

This is ADR-008's circularity showing up from the other side: the guard
whose pins the old refit used to rewrite is now simply stale, because
promotion re-baselines nothing. Not fixed here — re-baselining it is a
percentile-master decision, not a rank-form one — and registered as debt.
