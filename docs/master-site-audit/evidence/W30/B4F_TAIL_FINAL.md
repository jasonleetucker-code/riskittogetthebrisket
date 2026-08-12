# B4-FINAL — W30-F023 percentile tail saturation, repaired

> **This supersedes `B4_TAIL_DECISION.md`, which is preserved unchanged.**
> That document recorded a *blocked* experiment whose conclusion was
> "903 is the right boundary but landing it drives the B3 market corridor
> onto rows its own criteria forbid". The corridor was removed by #799
> (merge `52d48b6e5`), so both halves of that conclusion have been
> re-examined here on fresh inputs. One of them did not survive.

## Recommendation

**B4 / W30-F023 VERIFIED FIXED.**

`tail_policy.TAIL_SATURATION_RANK = 904`.

## 1. The pin

| | |
|---|---|
| code | `63f6b59a9` (branch restarted from `origin/main` after #799 merged) |
| board | `exports/latest/dynasty_data_2026-08-12.json` |
| board sha256 | `87b3ec8abfe4f82ae2772e9fd5861490c64b1f16fecc732f39d89c9b145c1734` |
| board bytes | 835,679 |
| scraped | 2026-08-12T03:13:01 |
| source CSVs | 24, individually hashed in `b4f_pin.json` |
| sources | 21 registered; value-direct = `idpTradeCalc`, `ktcSfTep` |
| champion | registry v2 (`HILL_*` constants unchanged by this pass) |
| `PERCENTILE_REFERENCE_N` | 500 (unchanged) |
| `OVERALL_RANK_LIMIT` | 800 (unchanged) |
| rows / served | 1,094 / 740 |
| observations | 6,316 total, 5,143 rank-Hill |
| deepest effective rank | 898 |
| deepest rank-Hill rank | 876 |

Full pin: `b4f_pin.json`. Old B4 evidence untouched.

## 2. RED on current HEAD

Population is **path-gated**: `valueContributionPath == "rank_hill"` AND
`effectiveRank > 500`. A deep stamped rank on a value-direct source is not
saturation — those price from the raw site value and never reach
`percentile_to_value`.

| | |
|---|---|
| rank-Hill observations | 5,143 |
| past the boundary | **421** (8.19%) |
| distinct rows touched | **254** |
| ...served | **254** |
| ...unserved | **0** |
| value-direct observations | 1,173 (279 past 500 — **not** the defect) |

Positional concentration (all 254 touched rows are served):

| bucket | rows | % all rows | % served |
|---|---|---|---|
| QB | 4 | 0.37% | 0.54% |
| RB | 2 | 0.18% | 0.27% |
| WR | 4 | 0.37% | 0.54% |
| TE | 11 | 1.01% | 1.49% |
| DL/EDGE | 97 | 8.87% | 13.11% |
| LB | 49 | 4.48% | 6.62% |
| DB | 87 | 7.95% | 11.76% |
| **total** | **254** | **23.22%** | **34.32%** |

Sources contributing saturated observations: `draftSharksIdp` 193,
`idpShow` 170, `dlfIdp` 23, `draftSharks` 17, `dlfRookieIdp` 8,
`flockFantasySfRookies` 7, `fantasyProsIdp` 3. Every value-direct source
contributes **zero**.

These are freshly measured (`b4f_reproduce.json`). They land within a few
observations of the 2026-08-11 numbers, which is a property of a stable
deep tail rather than a reused figure — the rank-Hill total moved 5,146 →
5,143 and the board is a different file.

## 3. The boundary changed: 903 → 904

**This is the finding of the pass.**

The prior round selected 903 as "the deepest rank any source publishes,
corroborated independently at `src/api/source_history.py:352-353`". Two
things are wrong with that.

**It has no executable definition.** Every occurrence of 903 in the tree
is prose: a comment in `source_history.py`, a docstring sentence in
`tests/api/test_source_history_rank_encodings.py`. That test's actual
guard uses 2,000. Nothing computes 903 and nothing measured it.

**It is refuted by measurement.** Replaying the 17 compatible historical
days with current code (`b4f_historical.py`, the #799 leak-guarded
harness) gives the deepest observed effective rank per day:

```
784, 785, 898, 898, 898, 898, 898, 899, 900, 900, 900, 900, 900, 901, 901, 903, 904
```

Maximum **904**, from `idpTradeCalc` on **2026-07-28**. 903 would have
re-saturated a rank the evidence has actually seen — headroom −1.

The quantity moves with source coverage (784 to 904 across 17 days), so
**a single board cannot decide this boundary**, which is precisely how the
original number went unchallenged.

### Why the boundary must cover value-direct ranks

904 comes from `idpTradeCalc`, a value-direct source that does not
normally traverse the curve. Covering it is not slack. The value-direct
**fallback** is live code: `data_contract.py` routes a value-direct source
to `percentile_to_value` when the source is suppressed, its value is
outside the declared range, or the value is missing/non-positive. A
boundary set at the deepest *rank-Hill* rank (882) would re-saturate the
band above it the moment that branch takes traffic. This is the same
reasoning the prior round used to reject 877 — the reasoning was sound;
only its number was not.

### Why not more headroom

Any margin above 904 would resolve ranks nothing has published, which is
the same objection that rules out unbounded extrapolation. 904 is the
observed maximum exactly.

**Known residual, stated plainly:** because the boundary is the observed
maximum, a future board on which a source reaches 905 will saturate there.
That is a far smaller defect than W30-F023 (which collapsed everything
past 500) and it is the honest position. `b4f_historical.py --depths`
re-runs the measurement when it needs revisiting.

## 4. A tail policy, not a refit

`PERCENTILE_REFERENCE_N`, the champion midpoint/slope, the registry, the
source weights, the coordinate pools, TEP and league scoring are all
untouched. The rank-space invariant `M = c·(N−1)` holds.

Evaluating every integer rank 1..904 on all three routed masters under
both policies (`b4f_equivalence.json`):

| master | max head Δ (ranks 1–500) | distinct values in 501–904 before | after | M |
|---|---|---|---|---|
| shared_market | **0** | 1 | 395 | 55.89 |
| offense | **0** | 1 | 327 | 54.89 |
| idp | **0** | 1 | 271 | 41.42 |

The fitted head is preserved exactly. The tail gains the separation the
defect removed.

## 5. Board impact

Production (`None`) vs candidate (904) on identical pinned inputs
(`b4f_impact_904.json`):

| | |
|---|---|
| rows compared | 1,094 |
| values changed | **245** |
| mean / median abs change | 75.1 / 64 |
| P90 / max abs change | 162 / 196 |
| median / P90 / max relative | 3.91% / 11.35% / 14.42% |
| ranks changed | 402 |
| median / P10 / P90 / max rank movement | 16 / 2 / 60 / 103 |

Served membership:

| | |
|---|---|
| top 50 / 100 / 200 | **0 / 0 / 0** |
| top 400 | 24 |
| full served cut | 740 → 740, churn 66 |

**No change in the top 200.** Every value moves *down*, which is the
expected direction: saturated ranks were being priced as though they sat
at the reference population, so resolving them prices them lower.

| bucket | changed | median abs | max abs |
|---|---|---|---|
| QB | 2 | 3 | 15 |
| RB | 2 | 19 | 40 |
| WR | 3 | 72 | 81 |
| TE | 10 | 21 | 162 |
| DL/EDGE | 87 | 77 | 179 |
| LB | 42 | 54 | 196 |
| DB | 69 | 89 | 185 |
| picks | 30 | 27 | 82 |

Largest movers: Jimmy Rolder −196, Romello Height −189, Alohi Gilman −185,
Jakobe Thomas −184, Christian Rozeboom −183.

## 6. Attribution — nothing unexplained

| | |
|---|---|
| direct (own rank-Hill contribution moved) | 215 |
| second-order with a **demonstrated** mechanism | 30 |
| **unexplained** | **0** |

The 30 are all picks. The corridor can no longer be the explanation, so
the chain was checked rather than asserted:

* 36 rookies moved, **all 36 down** (26 IDP, 10 offense);
* 30 picks moved, **all 30 down**;
* every affected pick is **2026** — the current rookie year, which is
  exactly the set Phase 5.2b tethers to the merged rookie pool.

That is the legitimate `IDP rookie repricing → merged rookie ordering →
pick anchor` path: directionally consistent and confined to the tethered
year. No 2027/2028/2029 pick moved, which is what a spurious pick-side
coupling would have produced.

Per-pick detail (year, round, slot, before, after, Δ) is in
`b4f_impact_904.json` under `pickRows`. Largest: 2026 Pick 6.03
1765 → 1683 (−82); smallest: 2026 Pick 6.07 1644 → 1641 (−3).

## 7. The corridor is gone, and integrity holds

Executable references in `src/` + `server.py` to
`_apply_market_corridor_clamp`, `_market_anchor_for_row`,
`_market_anchor_value_for_row`, `_MARKET_ANCHOR_BY_ASSET_CLASS`,
`_MARKET_ANCHOR_FALLBACKS`, `_MARKET_CORRIDOR_*`: **0 each, 0 total**.
(Scanned over executable code only — the test suite names them on purpose,
to pin their absence.)

Blend-integrity detector:

| tail | violations | flags | quarantined | contract |
|---|---|---|---|---|
| `None` | 0 | 0 | 1 (pre-existing) | healthy |
| `904` | 0 | 0 | 1 (pre-existing) | healthy |

Across all 17 historical days at 904: **0 integrity violations**. The tail
repair does not produce structurally impossible blends.

## 8. Historical sensitivity

17 compatible days, current code + historical inputs, leak-guarded, league
context pinned (`b4f_historical_sensitivity.json`):

| | |
|---|---|
| values changed / day | 197–257 |
| median abs change / day | 47–72 |
| max abs change (worst day) | 629 on 2026-07-26 |
| served-cut churn / day | 0–66 |
| integrity violations | **0 on every day** |
| days exceeding the boundary | **none** |

Two days (2026-08-03, 2026-08-06) show a much shallower domain (785/784)
and correspondingly smaller impact — those are partial-coverage days, not
pathologies.

## 9. Frontend

The Hill Curve Explorer extrapolated continuously while serving saturated
— the two disagreed about the deep tail. Repaired by **exposing the
canonical boundary**, not by writing a second tail rule:
`_build_hill_curves_block` stamps `saturationRank` on every curve entry
and `hillValue` honours whatever it is handed. Change the constant and the
chart follows. A note appears only when the plotted domain actually
reaches the boundary, so it describes something visible.

Pinned by `frontend/__tests__/components/HillCurveTailPolicy.test.jsx` (6
tests), including that a missing boundary degrades to extrapolation rather
than rendering NaN — a real bug the test caught, since `Number(null)` is 0
and passes a bare finiteness check.

## 10. Tests

`tests/canonical/test_percentile_tail_policy.py`: the `xfail(strict=True)`
markers are removed and the classes are ordinary regressions — 27 pass.
`test_the_repair_is_what_makes_these_pass` asserts the pre-repair policy
still collapses the ranks in question, so the suite cannot pass with or
without the fix.

Four tests elsewhere pinned the saturated behaviour as correct and were
**re-decided with the reasoning recorded in each**, not silently flipped:

| test | was | now |
|---|---|---|
| `test_coordinate_equivalence.py::test_ranks_past_the_reference_population_share_one_coordinate` | collapse at the reference | collapse at the *boundary*; the 500→boundary span must NOT collapse |
| `test_coordinate_equivalence.py::test_equivalence_breaks_exactly_where_the_smaller_universe_clamps` | two universes diverge past 500 | both saturate together at the boundary — the transform is a unit change |
| `test_percentile_coordinate_contract.py::test_ranks_past_the_universe_clamp` | `p == 1.0` past the reference | `p > 1.0` inside the domain; saturation only past the owner's boundary |
| `test_valuation_pipeline_stages.py::test_pipeline_flattens_every_rank_past_the_reference` | the deep board flattens | resolves to the boundary **and** flattens past it |

## 11. Not in scope, and deliberately untouched

* **#804 / W02-F019** (correlated-source anomalies) — a different problem:
  several sources being wrong together, which does not touch the
  percentile coordinate. No source weights, families, caps, lineage
  changes or market references were introduced.
* **Hill registry** — no promote, no apply, no constant change.
* **#794/#795/#796** — resolved by #799; nothing reopened.
