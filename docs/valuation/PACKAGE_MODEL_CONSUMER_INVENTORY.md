# Package-model consumer inventory (owner VA package 2026-10-17)

Every place the codebase publishes or decides on package equity, and how each relates to the one
versioned package model (`src/valuation_math/package_model.py` / `frontend/lib/trade-logic.js` →
`packageAdjustPair`; active model in `config/trade/package_model.json`).

**Active model (owner decision 2026-10-17):** `geom_q078_v1` (geometric, q = 0.78); `ktc_2026_04`
is retained as the explicit rollback model. Tests that pin KTC's own formula (keeptradecut.com
captures, the 139-case port fixture, V12/V13 gates, KNOWN_DEFECT pins) select it explicitly; consumer
tests assert against the dispatch's active answer. Record:
`docs/valuation/PACKAGE_MODEL_OWNER_ACTIVATION_2026-10-17.md`.

**Rule:** a consumer that states "who wins this package comparison" under our model must go through
the dispatch, so changing the active model (an owner decision) changes every such surface at once and
no surface changes without it. The bypass guards in `tests/valuation_math/test_package_model.py` fail
if a Python or JS consumer calls the KTC primitives directly outside the allowlisted owners below.

Dispositions:

| code | meaning |
|---|---|
| MUST_MIGRATE | publishes our package verdict; routed through the dispatch (done in PR 1/2/3 as marked) |
| ADVISORY_REEVALUATE | deliberately models a specific market's own rule; re-decide if the active model changes |
| KEEP_RAW | deliberately raw sums; labelled as such |
| SEPARATE_ROSTER_LENS | roster-fit / simulator lens, never folded into the calculator verdict |
| LEGACY_RECEIPT_ONLY | compatibility shim, parity fixture or receipt stamp; decides nothing |
| NOT_APPLICABLE | displays a number computed elsewhere |

## Backend (Python)

| # | site | what it decides | disposition | covered by |
|---|---|---|---|---|
| 1 | `src/trade/analyze_trade.py` | Analyze Trade headline verdict, adjusted totals, `packageModel` receipt | MUST_MIGRATE — done (PR 1) | `tests/trade/test_analyze_trade*.py`, bypass guard |
| 2 | `src/trade/suggestions.py` (`_va_gap`, `_find_balancers`) | suggestion equalizer, adjusted gap | MUST_MIGRATE — done (PR 1) | `tests/trade/test_suggestions*.py`, `test_ktc_va_python_port.py` |
| 3 | `src/trade/angle.py` | Angle packages adjusted totals / acceptance gate | MUST_MIGRATE — done (PR 1) | `tests/test_trade_angle.py` |
| 4 | `src/trade/finder_value_adjustment.py` → `finder.py` | finder score premium + published `valueAdjustment` | MUST_MIGRATE — done (PR 1) | `tests/trade/test_finder_va_is_not_bypassable.py` |
| 5 | `src/trade/monte_carlo.py` | simulate-mc adjusted totals | MUST_MIGRATE — done (PR 1) | `tests/trade/test_monte_carlo*.py` |
| 6 | `src/trade/market_trade_eval.py` | residual of completed trades vs a source; now takes `model_id` | MUST_MIGRATE — done (PR 1); shadow evaluation hook (PR 4) | `tests/trade/test_market_trade_eval.py` |
| 7 | `src/public_league/trade_grading.py::trade_va_net` | public `/league` trade grades (at-the-time and current band) | MUST_MIGRATE — done (PR 1; current band PR 3) | `tests/public_league/test_trade_grade_parity.py`; `tests/api/test_trade_history_asof.py` (lands with PR 3) |
| 8 | `src/api/trade_history_asof.py` | private /trades At-the-Time grades | MUST_MIGRATE — built on #7 (PR 3) | `tests/api/test_trade_history_asof.py` (lands with PR 3) |
| 9 | `src/public_league/trade_grading.py::ktc_adjust_package` | KTC-port parity entry for the shared fixture | LEGACY_RECEIPT_ONLY | `trade_grade_parity_cases.json` |
| 10 | `src/trade/market_value_adjustment.py` | legacy re-export of `ktc_va` | LEGACY_RECEIPT_ONLY | `tests/valuation_math/test_package_model.py`, `tests/test_trade_finder.py` |
| 11 | `src/trade/ktc_va.py`, `src/valuation_math/ktc_va_core.py` | the KTC rollback model's implementation (active until 2026-10-17) | owner of model `ktc_2026_04` (not a consumer) | 139-case KTC fixture |
| 12 | `src/league_intel/cross_market.py` (`value_package` / `compare_packages`, via `/api/gameplan` packages and Angle) | each market's package value under **that market's own published rule** (KTC's rule for the KTC market) | ADVISORY_REEVALUATE — it states what KTC's market would say, not our verdict; keep KTC's rule for the KTC lens even after a promotion, but re-label if the lens is ever read as ours | `tests/league_intel/test_cross_market*.py` |
| 13 | `src/roster_intel/packages.py` | gameplan package generator (single-market comparison through #12) | ADVISORY_REEVALUATE (inherits #12) | `tests/roster_intel/test_packages.py` |
| 14 | `src/intel/manager_scout.py` | manager tendencies; `VALUE_BASIS = todays_canonical_board_raw_sum_not_value_adjusted` | KEEP_RAW (labelled) | `tests/intel/test_manager_scout*.py` |
| 15 | `src/trade/trade_simulator.py`, `team_impact.py`, `roster_capacity.py` | roster consequence, starters, forced drops | SEPARATE_ROSTER_LENS | `tests/api/test_trade_simulator.py` |
| 16 | `server.py` (contract `meta.packageModel`, `_stamp_valuation_mode`, simulate-mc) | receipts naming the active model | LEGACY_RECEIPT_ONLY (receipt) | `tests/valuation_math/test_package_model.py` |

## Frontend (JS)

| # | site | what it decides | disposition | covered by |
|---|---|---|---|---|
| 17 | `frontend/lib/trade-logic.js` — `computeValueAdjustment`, `computeMultiSideAdjustments`, `valueAdjustmentFromSideArrays` → `adjustedSideTotals`, `multiAdjustedSideTotals`, `computeSideFlows`, `tradeImbalance`, `tradeGapAdjusted`, `findBalancers` | the /trade calculator headline, meter, gap, equalizer | MUST_MIGRATE — done (PR 1) | `frontend/__tests__/package-model.test.js`, trade-logic tests |
| 18 | `frontend/lib/league-analysis.js::computeTradeVANet` | /trades Current Grade, Winners & Losers | MUST_MIGRATE — done (PR 1; W&L Σ adjusted nets PR 3) | `league-analysis.test.js`; `trade-history-grades.test.js` (lands with PR 3) |
| 19 | `frontend/components/trade/TradeSourceBreakdown.jsx` + `lib/second-opinions.js` | Second Opinions rows | MUST_MIGRATE — PR 2 (was hard-coded `adjustments = 0`) | `__tests__/components/second-opinions-hybrid.test.jsx` (lands with PR 2) |
| 20 | `frontend/components/trade/TradeFairnessExplanation.jsx` | prose summary; per-source figures are RAW, labelled | KEEP_RAW (labelled; full-coverage sources only, PR 2) | `__tests__/components/explanation-copy.test.jsx` |
| 21 | `frontend/components/waivers/ManualAddDrop.jsx` | add/drop comparison via `adjustedSideTotals` | MUST_MIGRATE — inherited from #17 | `__tests__/manual-add-drop.test.js` |
| 22 | `frontend/lib/trade-war-room.js`, `lib/manager-scout.js` | display of backend `vaNet` / raw-sum fields | NOT_APPLICABLE | war-room fixtures |
| 23 | `frontend/components/help/TradeHelp.jsx`, `TradeVerdictHelpBody.jsx`, `trade/TradeWarRoom.jsx`, `app/trade/trade-sections.jsx` | prose describing the active Value Adjustment | NOT_APPLICABLE (copy; updated for the geometric model 2026-10-17) | `__tests__/components/explanation-copy.test.jsx`, `trade-war-room.test.jsx` |

## When the active model changes

1. Edit `config/trade/package_model.json` (`active`) — owner decision only.
2. Every MUST_MIGRATE row follows automatically; receipts (`packageModel`) say which model produced a
   number, and /trades aging refuses to compare across models (`package_model_mismatch`).
3. Re-check: the ±200 aging PRIOR, the 3% fairness band, the finder thresholds tuned on KTC-adjusted
   numbers, and the copy in rows 22–23.
4. Rows 12–13 keep KTC's rule for the KTC market lens unless separately decided.
