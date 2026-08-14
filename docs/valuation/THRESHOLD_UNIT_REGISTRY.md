# Threshold semantic units — the B9b classification

**Status:** classification record + conversion log
**Owner of the numbers:** `config/thresholds.json` (loaded by `src/api/thresholds.py`,
mirrored in `frontend/lib/thresholds.js`, enforced by `tests/api/test_threshold_parity.py`)
**Companion:** `docs/master-site-audit/B_SERIES_EXECUTION_LEDGER.md` §B9b

---

## 1. The defect class

A threshold is a number *plus a scale*. Drop the scale and the number keeps working
while its meaning drifts, because the distribution underneath it moves — a refit Hill
curve, a source added or removed, a deeper pool, a different vendor index.

Two failures, both measured on live data, both invisible to review and to the test suite:

**Cross-scale comparison (W29-F005).** The "Seller cash-out" tag compared a 0–9999
dynasty board value against a 0–100 ROS strength index:

```
dynastyValue < rosValue * 0.7
```

The right-hand side maxes at **60.8**. The board's lowest priced value is **1,134**. The
ranges do not overlap: **0 of 1,093 rows** could ever satisfy it, and the tag had never
rendered in production. It existed in three files — two JS copies and one Python — and
survived review three times.

Its unit test passed. It passed because the fixture supplied `dynasty_value=40`, an input
the 1–9999 board cannot produce. *A test with no unit discipline validated a predicate with
an empty solution set.*

**Absolute constants on a non-uniform index.** The same classifier gated "strong" and
"elite" on `rosValue >= 60` and `>= 80`, written as if the 0–100 index were a percentile.
It is not. Measured over the live aggregate and **all 893 historical aggregates
(2026-04-28 → 2026-08-14)**:

| statistic | value |
|---|---|
| median `rosValue` | 9.15 |
| 90th percentile | 26.17 |
| 99th percentile | 59.41 |
| maximum | 86.79 |

So `>= 60` sat *above the 99th percentile* and selected 9 of 1,031 players (0.87%);
`>= 80` selected 2 (0.19%), never more than 3 in any historical aggregate. The complement
was the clearer damage: "Injury/bye cover" fires when **not** strong, so it labelled
**99.13%** of the pool — a tag carrying no information.

---

## 2. The classification rule

| class | means | correct unit |
|---|---|---|
| **BOARD-RELATIVE** | quality, tier, elite/depth status, relevance, scarcity position, "top X-ish" | rank, percentile, ratio |
| **VALUE-UNIT** | genuinely additive arithmetic in canonical value units — a gap between two values, a package delta | canonical value units, justified |
| **FOREIGN SCALE** | a vendor's own scale, never the canonical board | that vendor's unit, named |

A BOARD-RELATIVE concept expressed as an absolute value is the defect. A VALUE-UNIT
concept expressed as an absolute value is correct and may stay — with its unit declared.

---

## 3. Converted

| constant | was | now | evidence |
|---|---|---|---|
| ROS "elite" gate | `rosValue >= 80` | `ROS_ELITE_PERCENTILE = 95` | selected 0.19% of the pool |
| ROS "strong" gate | `rosValue >= 60` | `ROS_STRONG_PERCENTILE = 75` | selected 0.87%; complement labelled 99.13% |
| ROS depth band | `30 <= rosValue < 60` | `ROS_DEPTH_BAND_LOW_PERCENTILE = 40` … strong cut | band edges now adjacent by construction |
| "Seller cash-out" | `dynastyValue < rosValue * 0.7` | `rosPercentile - dynastyPercentile >= 25` | 0 of 1,093 rows could fire; now 19 of 1,031 |

**Measured effect on tag populations** (live pool, 1,031 players):

| tag | before | after |
|---|---|---|
| Seller cash-out | **0** (unreachable) | 19 (1.84%) |
| Injury/bye cover | 99.13% | 55.87% |
| Contender upgrade | 2 players | 47 (4.56%) |
| Win-now target | ≤9 possible | 52 (5.04%) |

All nine tags are now reachable and each has a test proving it fires
(`tests/ros/test_tag_parity.py`).

Two structural changes came with it, because the duplication is what let the defect
survive:

* **`rosPercentile` is stamped server-side**, over the whole pool.
  `/api/ros/player-values` truncates to `limit` (500 by default), so a client ranking what
  it received would be measuring a standing within the top half and calling it a
  percentile.
* **`canonicalPercentile` is stamped on contract rows**, for the same reason — a consumer
  holding one row cannot compute a standing. It is the scale-stable companion to
  `rankDerivedValue`.
* **One classifier**, in `frontend/lib/ros-index.js`, mirroring `src/ros/tags.py`, with the
  parity test that a JS comment had promised as "PR-future" and that was never written.

---

## 4. Classified, registered, not yet converted

These are BOARD-RELATIVE concepts still expressed in canonical value units. Converting each
changes which assets a recommendation surface offers — a product-visible change that needs
its own before/after measurement, so each is specified here rather than changed in bulk.

| constant | file | value | concept | conversion target |
|---|---|---|---|---|
| `MIN_RELEVANT_VALUE` | `src/trade/suggestions.py:173` | 500 | "worth proposing at all" | board rank / percentile |
| `MIN_ACTIONABLE_VALUE` | `src/trade/suggestions.py:222` | 2000 | "actionable" quality tier | percentile |
| `MIN_WAIVER_VALUE` | `src/trade/waiver.py:41` | 500 | wire relevance | percentile |
| contender gate | `src/trade/suggestions.py:1233` | `display_value >= 7000` | "elite target" | percentile |

## 5. Correctly VALUE-UNIT — retained, with justification

| constant | file | value | why it stays |
|---|---|---|---|
| `FAIRNESS_TOLERANCE` | `src/trade/suggestions.py:183` | 769 | a *gap between two canonical values*; subtraction in value units is the operation |
| near-even gate | `src/trade/suggestions.py:1503` | 500 | same — `abs(give − receive)` |
| `CONSOLIDATION_MIN_UPGRADE_RATIO` | `suggestions.py:190` | 0.70 | already a ratio, scale-stable |
| `CONSOLIDATION_MAX_OVERPAY_RATIO` | `suggestions.py:197` | 0.30 | already a ratio |

## 6. FOREIGN SCALE — correctly named, leave alone

| constant | file | scale |
|---|---|---|
| `BOARD_TO_COMPOSITE_K = 0.875` | `src/trade/finder.py:58` | the *conversion itself*, and the only place in the repo that names one |
| `KTC_MAX_PLAYER_VALUE` / `KTC_TOP_REFERENCE` | `src/trade/market_value_adjustment.py` | KTC native 0–10041 |
| `KTC_MAX_PLAYER_VAL` / `KTC_T_REFERENCE` | `src/trade/ktc_va.py` | KTC native — **duplicated** with the above; one concept, two owners |

## 7. Scales in play

Five, and outside `finder.py` the constants do not say which one they belong to:

1. canonical `rankDerivedValue` — 1–9999 (Hill asymptote)
2. legacy composite `_finalAdjusted` — ~1.131× the board
3. KTC native — 0–10041
4. BDVM trade value — its own 0–10000
5. ROS `rosValue` — 0–100 strength index, median 9.15

---

## 8. What is NOT closed

* The four BOARD-RELATIVE constants in §4 are registered and specified, not converted.
* The KTC-native constant pair in §6 is duplicated across two modules.
* **`inferValueBundle` coerces an unpriced row to `0`** (`frontend/lib/dynasty-data.js`).
  The rationale on the function is sound as far as it goes — it replaced a fallback that
  substituted a *composite-scale* number into board-scale sums — and `0` is arithmetically
  neutral **in a sum**. It is not neutral in a sort, a minimum, an average or a display,
  where it asserts "this asset is worth nothing". `MISSING IS NEVER ZERO` wants `null`
  with each consumer deciding. The change is wide (trade sums, portfolio, movers,
  team-phase, CSV export) and is recorded here rather than attempted unmeasured.
