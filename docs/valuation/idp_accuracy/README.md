# IDP valuation accuracy research: index of every lane

**Program:** `docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md` (research and shadow work only; it authorizes no change to live
canonical rankings, values, scoring, source voting, the IDP ceiling, public fairness rules, trade verdicts, deployment or Sleeper writes).
**Start with `H_RECOMMENDATIONS.md`**: it answers the directive's ten questions, classifies every candidate change as ADVANCE, KEEP EXPERIMENTAL
or REJECT, and lists the owner decisions.

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## Lanes

Status is as of 2026-10-26. "Validate PR" is the L2 CI job; PRs marked `pending` had not finished when this index was written. All PRs are
research or shadow work, and none is deployed.

| lane | what it did | PR | branch | head | state | docs on that branch |
|---|---|---|---|---|---|---|
| **A** | scoring accuracy, shared manifest, scorer reconciliation | [#1931](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/1931) | `claude/idp-a-scoring-manifest` | `c563b979a` | open, ready; L0 and Validate PR pass | `docs/valuation/idp_accuracy/A_SCORING_ACCURACY.md`, `MANIFEST.json`, `evidence/scorer_reconciliation.json` |
| **A fixes** | repair nflverse-path scorer defects 01, 02, 03 (**changes BDVM in-season values**) | [#1938](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/1938) | `claude/idpa-scorer-defect-fixes` | `1edc29d45` | draft, stacked on #1931; L0 and Validate PR pass | same `A_SCORING_ACCURACY.md` (fix section), `evidence/scorer_fix_measure.json` |
| **C** | cross-position market baseline, shared-market anchor verdict | [#1936](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/1936) | `claude/idp-c-market-baseline` | `4484f5f7a` | open, ready; Validate PR passes | `docs/valuation/idp_accuracy/C_MARKET_CROSS_POSITION.md`, `evidence/c_market_baseline_2026-10-25.json` |
| **B** | replacement methodology in shadow (D1 to D6, whole-roster evaluator) | [#1940](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/1940) | `claude/idp-b-replacement-shadow-v2` | `0987b5bfd` | draft; L0 and Validate PR pass | `docs/valuation/idp_accuracy/B_REPLACEMENT.md`, `evidence/b_replacement_2026-10-25.json` |
| **D** | best-ball volatility by archetype | [#1941](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/1941) | `claude/idp-d-bestball-archetypes-v2` | `0f7eb4a2a` | draft; L0 passes, Validate PR pending | `docs/valuation/idp_accuracy/D_BESTBALL.md`, `evidence/bestball_archetypes.json` |
| **E** | scoring sensitivity (TFL, PD, LB, best ball) | [#1943](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/1943) | `claude/idp-e-scoring-sensitivity-v2` | `f31323b36` | draft; L0 passes, Validate PR pending | `docs/valuation/idp_accuracy/E_SCORING_SENSITIVITY.md`, `evidence/scoring_sensitivity.json` |
| **F and G** | candidate set, candidate D, the fair-value structural finding, the preregistered near-term backtest | [#1942](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/1942) | `claude/idp-g-backtest` | `0378868df` | draft, stacked on #1940; L0 passes, Validate PR pending | `docs/valuation/idp_accuracy/F_CANDIDATES.md`, `G_PREREGISTRATION.md`, `G_ACCURACY.md`, `evidence/g_*.json`, `evidence/f_structural_level_invariance.json` |
| **H** | recommendations, owner decisions, shadow trade comparison | [#1945](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/1945) | `claude/idp-h-recommendations` | the PR's head | draft; based on `main` | `H_RECOMMENDATIONS.md`, `README.md`, `evidence/h_trade_shadow_comparison.json` |

Read any lane's document from its branch before it merges: `git show origin/<branch>:docs/valuation/idp_accuracy/<file>`.

## Verdicts in one line each

| lane | result |
|---|---|
| A | host-native scorer exact (3,710 of 3,710 within 0.01); nflverse path 91.5% exact with four enumerated defects (96.2% after #1938) |
| C | shared-market anchor `NOT_JUSTIFIED` (level unresolved, not shown wrong); all 397 priced IDP rows low confidence |
| B | replacement is fragile: free-agent levels realize about half out of sample, four of seven served anchors set by an injured or inactive player |
| D | best-ball volatility premium IDP 11.9% against offense 7.0% of ppg; follows slot economy; not predictable per player |
| E | TFL does not favour DT as a class; PD deepens the CB pool; LB stable but its elite separation not detectable at six games |
| F and G | no candidate advances; A significantly worse, B not evaluable and structurally unable to fix a level, C no difference, D blocked by its guards |
| H | no served value change warranted; two mechanical repairs ready for owner decisions; five owner decisions listed |

## Related PRs (not lanes of this program)

| PR | why it matters here |
|---|---|
| [#1937](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/1937) | Lane E trade defect fixes; pins the cut-ladder name tie-break (`LANE-E-DEFECT-I9-TIEBREAK`) as an owner decision |
| [#1939](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/1939) and [#1932](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/1932) | IDP source staleness reports; the IDP Show board-swap question comes from #1939 |

## Merge notes

* Two stacks: **#1938 on #1931** and **#1942 on #1940**; the rest are independent of each other. Each lane writes distinct file names under
  `docs/valuation/idp_accuracy/`, so the documents do not collide. The empty `scripts/idp_accuracy/__init__.py` and `tests/idp_accuracy/__init__.py`
  are byte-identical wherever they appear.
* The shadow trade comparison (`scripts/idp_accuracy/trade_shadow_comparison.py`) reads candidate C and D scores from Lane G's
  `evidence/g_stage1_scores.json`: from this checkout once #1942 is merged, and from `git show origin/claude/idp-g-backtest:...` until then.
* Nothing under `src/` imports any research script, and no lane changes a served path except #1938, which changes BDVM's in-season
  posterior (not `/api/data`) and awaits owner approval.

## Reproduce this lane

```bash
python scripts/idp_accuracy/trade_shadow_comparison.py --offline   # after one online run has filled data/idp_accuracy/cache
python -m pytest tests/idp_accuracy/test_trade_shadow_comparison.py -q
```
