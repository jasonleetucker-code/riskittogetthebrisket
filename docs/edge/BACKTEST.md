# Consensus Edge — backtest report

**Verdict: ready for shadow mode only. Not production ready.**

Not because the code is unfinished — because the evidence does not support promoting it, and this
document is the record of exactly why.

---

## 1. The historical panel exists, and finding it was the whole game

The starting assumption was that this repository had no as-of history and therefore nothing could
be validated. That was wrong, and it was wrong for a mechanical reason worth writing down:

```
git rev-parse --is-shallow-repository   ->  true      (563 commits)
```

The working clone was **shallow**. Every source appeared to have ~8 days of history. After
`git fetch --unshallow` (4,387 commits) the real picture appeared: the 2-hourly
`scheduled-refresh` workflow commits `CSVs/site_raw/*.csv`, so **every commit of those files is a
timestamped market observation**. There was no snapshot store to build — only a time series to read.

| source | days | range |
|---|---|---|
| `ktc`, `dynastyDaddySf` | 110 | 2026-04-16 → 2026-08-03 |
| `flockFantasySf` | 105 | |
| **`ktcSfTep`** — offense anchor | **99** | 2026-04-27 → 2026-08-03 |
| `fantasyCalc` | 83 | |
| `draftSharksSf`, `otcffbSf` | 75 | |
| **`idpTradeCalc`** — IDP anchor | **14** | |

Panel built by `src/edge/panel.py`: **45,935 as-of rows across 99 dates**, 42,291 carrying an
independent fair value, **31,243 carrying a 30-day outcome**.

### The look-ahead guard

`history.snapshot_at(source, as_of)` resolves the last commit **at or before** `as_of 23:59:59Z`.
Not the nearest commit; not the next one. Pinned by
`tests/edge/test_invariants.py::test_an_as_of_snapshot_never_reads_a_later_commit`.

Trailing price change (a legal backward-looking feature) and forward outcomes (labels) are attached
by two separate functions — `attach_trailing_change` and `attach_outcomes` — so the direction of
every read is visible at the call site and no code path does both.

---

## 2. Results

Rolling temporal folds, train → **purge gap = horizon** → test. No random splits: two rows for the
same player on consecutive days are nearly the same observation, and a random split reports a score
that cannot be earned in production.

### 14-day horizon (3 scored folds)

| predictor | mean OOS Spearman | median | worst fold | folds positive | mean decile spread |
|---|---|---|---|---|---|
| `trailing_30d` (momentum) | **+0.376** | +0.383 | +0.345 | 3/3 | +0.063 |
| `trailing_7d` | +0.252 | +0.265 | +0.220 | 3/3 | +0.051 |
| `gap + momentum` (naive 1:1) | +0.172 / +0.200 | | | 3/3 | +0.023 |
| **`log_gap`** — strict | **+0.090** | +0.082 | +0.078 | **3/3** | +0.014 |
| **`log_gap`** — family | **+0.121** | +0.135 | +0.090 | **3/3** | +0.013 |
| `market_value` | +0.019 | +0.006 | −0.040 | 2/3 | −0.010 |

### 30-day horizon — **1 scored fold, therefore not a validation**

`log_gap` +0.119 strict / +0.150 family; `trailing_30d` +0.413. One fold is an observation. It is
reported for completeness and must not be quoted as evidence.

### Full-sample (in-sample, for shape only)

| horizon | Spearman(gap, return) | top decile | bottom decile | spread |
|---|---|---|---|---|
| 7d | +0.084 | +1.7% | +0.1% | +1.6% |
| 14d | +0.105 | +2.8% | −0.1% | +2.9% |
| 30d | +0.140 | +6.0% | −0.6% | +6.6% |

The signal strengthening with horizon is the right shape for a mispricing that corrects slowly.

---

## 3. Four findings that changed the design

**1. Mispricing is real but weak.** `log_gap` was positive in *every* out-of-sample fold — that is
the finding that justifies shipping it at all — but rho ≈ 0.1 earns a modest weight, not a
confident one.

**2. Momentum is ~4× stronger, and it is deliberately excluded.** Trailing 30-day price change
predicts future price change at +0.38 against mispricing's +0.09. Admitting it to the directional
score would improve every number in this table **and turn the product into "buy whatever just went
up, at the top of its move"**. It ships as `directional=False`, enforced in `score.py::combine` and
pinned by `test_momentum_is_non_directional_and_excluded_from_the_score`. This is a deliberate
choice to score worse on the market target in exchange for answering the actual question.

**3. The gap is NOT a mean-reversion proxy.** `spearman(log_gap, trailing_30d) = −0.014`. The two
are essentially uncorrelated, so mispricing carries information momentum does not. This is what
makes it worth keeping despite being the weaker signal.

**4. A naive 1:1 blend is WORSE than its best part** (+0.17 vs +0.38). Unstandardized components on
different scales let the weaker drown the stronger. Every component is squashed to [-1, 1] before
combination — and this is the empirical case for visible sub-scores over one opaque average.

---

## 4. What CANNOT be validated

| | why |
|---|---|
| **IDP** | The IDP anchor has **14 non-adjacent days**. Rows can be built; no horizon can be scored. Offense results must never be quoted as covering defenders. |
| **Sharp Flow** | The movement ledger stores **no as-of history** and is empty in a fresh checkout. Nothing to fit or test against. Ships computed, displayed, and labelled `unvalidated_component`. |
| **30-day horizon** | One fold. |
| **Production outcomes** | The target is future MARKET movement. "Will the price move" is not "is this a good buy at this price". A production target needs league-scored future points, which this panel does not carry. |

### Residual circularity — disclosed, not solved

The leave-one-out consensus excludes the anchor, its vendor siblings (`ktc`,
`fantasyNavigatorSf` — confirmed KTC-derived in `scripts/fetch_fantasynavigator.py`) and, under
the `strict` policy, every crowd-trade source. But the audit established that **excluding
`ktcSfTep` does not fully remove KTC**: the OFFENSE Hill master curve is itself fitted on KTC's CSV.

This is a large improvement over comparing `rankDerivedValue` against KTC — which is
straightforwardly circular — but it is not a clean room, and the `family` policy scoring *better*
than `strict` (+0.121 vs +0.090) is consistent with some of the measured signal being
market-vs-market disagreement rather than pure mispricing.

---

## 5. Promotion gates — none of which are met

1. ≥5 scored out-of-sample folds at the primary horizon. *(currently 3 at 14d, 1 at 30d)*
2. Fitted weights beating the equal-weight and best-single-component benchmarks out of sample.
   *(no fit performed — see below)*
3. Sharp Flow validated against real history. *(no history exists)*
4. IDP either validated or explicitly scoped out of the product. *(14 days)*
5. Confidence calibrated — higher confidence buckets must show monotonically better accuracy.
6. A production-outcome target, not only a market-outcome one.

**No weights were fitted.** With one validated component there is nothing to fit a vector over, and
inventing one is the exact failure this exercise exists to prevent. `PROVISIONAL_WEIGHTS` is
labelled provisional in code, `weightsValidated: false` is stamped on every payload, and
`test_every_result_carries_a_model_version_and_shadow_status` fails if that ever silently flips.

---

## 6. Reproducing

```bash
git fetch --unshallow                      # REQUIRED — a shallow clone reports ~8 days
python -c "
from datetime import date
from src.edge import panel
for pol in ('strict','family'):
    rows = panel.build_panel(start=date(2026,4,27), end=date(2026,8,3), policy=pol)
    panel.write_panel(rows, panel.PANEL_DIR / f'offense_{pol}.jsonl')
    print(pol, panel.coverage_report(rows))
"
python -c "
from pathlib import Path
from src.edge import backtest
rows = backtest.load_panel(Path('data/edge/panel/offense_strict.jsonl'))
print(backtest.run_backtest(rows, target='log_return_14d', horizon_days=14).summary())
"
python -m pytest tests/edge -q
```

Panel files live in gitignored `data/edge/panel/` and are reproducible from git history, so they
are regenerated rather than committed.
