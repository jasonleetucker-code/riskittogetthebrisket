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
