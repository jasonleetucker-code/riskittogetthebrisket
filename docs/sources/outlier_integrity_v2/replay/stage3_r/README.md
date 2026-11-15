# Outlier integrity v2: Stage 3 R constraints at the FROZEN thresholds

Preregistration §5.3 Stage 3, §11 criteria 2 and 11. R boards are must-pass constraints,
never evidence (§5.1). Re-run of the pre-freeze checks (`../../r_constraints/`, deviation T1)
on the Stage 2 thresholds (`../../FROZEN_THRESHOLDS.json`), code `d1ff711ae0`, NO-HISTORY
(no history lane exists for a pinned production payload).

Reproduce: throwaway sparse worktree at the code commit, inputs pinned with
`../../rootcause/pin_inputs.sh`, then `python scripts/oiv2_regression_boards.py PAYLOAD
pin2015|pin0527 OUT` and `python scripts/oiv2_perf.py PAYLOAD OUT` (pin2015 only).
Payload sha256 prefixes: pin2015 `3ef54acda8c1062f`, pin0527 `b639608f68176b9a`.

| check | pin2015 | pin0527 | criterion |
|---|---|---|---|
| 31 IDP votes dropped by the incumbent in B | 31 / 31 | 31 / 31 | — |
| retained in C (DLF IDP restored + V2) | **31 / 31** | **31 / 31** | 2: pass |
| retained in C″ (DLF IDP + D4 + V2) | **31 / 31** | **31 / 31** | 2: pass |
| D4 set by rule (B′ vs A′) | 20 votes / 14 rows | 20 votes / 13 rows | — |
| D4 set retained in C′ / C″ | **20 / 20, 20 / 20** | **20 / 20, 20 / 20** | 2: pass |
| C built twice: identical | yes | yes | determinism |
| D vs A: rows changed, median / p90 / max | 539, 0.25% / 0.84% / 34.6% | 581, 0.23% / 0.83% / 35.6% | — |
| rows ≥ 10% (D vs A) | LaJohntay Wester +34.6%, Pete Werner −12.4% | the same two | attributed in `r_pin*.json` |

Theo Johnson: as before the freeze, the rule does not produce him on these pins (Draft Sharks
3001 / 3009 is kept by the incumbent in B′); the owner-named case is pinned by the frozen
panel test `tests/fixtures/oiv2/panel_theo_johnson_pr1817_lane.json`.

**Criterion 11 (performance) FAILS**: V2-ON build 1.618 s vs incumbent 0.959 s median
(ratio **1.69**, limit 1.25); peak RSS 91.9 MB vs 69.6 MB (+22.3 MB, limit +50 MB: pass).
`perf_pin2015.json`.
