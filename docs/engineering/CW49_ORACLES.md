# CW-49 independent oracles (FAAB anchors / market layer, BDVM ROS blend)

Owner directive 2026-11-07 §5 / §7. Tests only; no change to `src/`, `config/` or any served behavior.
Result: no defect found, so there are no xfails.

## Files
- `tests/trade/test_faab_independent_oracles.py` (113 tests)
- `tests/bdvm/test_ros_blend_oracle.py` (63 tests)

## Genuinely independent (expected value computed by separate code or by hand)
| Test group | Oracle |
|---|---|
| Anchors (`resolve_anchors`) | Literal rank lookup on a synthetic strictly-descending board (`LINEAR[teams*starters-1]`), hand-built 12th-best/2x-line blend, tail-decay and min-band widening re-derived in the test; per-league difference, row-order and translation invariance. |
| Objective at budget scale | `_o_curve`: smootherstep written in expanded form `10x^3-15x^4+6x^5` (engine uses Horner), compared via `recommend()` objective dollars at three budgets and five points. |
| Season option factor | `_o_option` restated from the doc formula; compared for every week 1-17, three statuses, two playoff starts. |
| Drop cost / team ceiling | Net-surplus composition recomputed by the oracle; free drop at or below replacement. |
| Bid argmax | Brute-force grid over every integer bid with an oracle zero-inflated lognormal win model (`statistics.NormalDist`, not `math.erf`); expected `recommended` = cheapest bid within minEdge of the true optimum, for two rival fields, six values, two balances. Also checks win probability, `<=` true argmax, and zero surplus at the ceiling. |
| Clearing p25/p50/p75 | Independent CDF scan over 0..budget. |
| Rival CDF | Engine `rival_bid_cdf` equals the oracle over 24 (bid, demand) points to 1e-12. |
| Crowd conversion applied once | Bid placed at the oracle's per-rival median must give P(beat) = 1/2, i.e. win = 1 - p/2; the median is the documented `(1-w)*modelled + w*pct*0.53` blend. A double or missing order-statistic correction breaks it. |
| BDVM ROS blend | Hand-computed posteriors (15.2, 7.0, 12.0), oracle weight and mu over a grid; `ros_value` per-game surplus by Simpson integration of the density, not the closed form. |

## Metamorphic / invariant (independent of exact numbers)
Crowd and trending never change objective, team ceiling or maxRational but do raise clearing; unknown-balance rival changes nothing; recommended <= balance and rungs ordered; option factor monotone; more weeks moves the posterior monotonically toward recent form within the convex hull; identical prior/recent is a fixed point; preseason is an exact no-op; IDP trusts its prior longer than offense; `ros_value` linear in weeks, zero for no weeks, monotone in mu and replacement, convex in sigma near replacement; missing bid history gives neutral flagged priors and a nonzero bid for a valuable player.

## Reproduces the implementation (regression value only, not independent)
- `test_shipped_config_equals_the_documented_spec`: pins config to literals copied from the docs, so it detects recalibration, not correctness of the calibration.
- The oracle's engagement and median-share formulas are a transcription of `docs/faab-model.md` / config; they prove the code matches the documented model, not that the model is right (fit evidence is `scripts/faab_backtest.py`).
- `test_expected_surplus_at_the_ceiling_is_exactly_zero` is an algebraic identity.

## Not covered (gaps)
`_rival_engagement` trending lift numerics, carry-over damping, positional need multipliers on the bid, and the `service.py` sigma shrink (`sqrt(w_prior)`) end to end; only the shrink factor's oracle values are pinned.
