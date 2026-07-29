# Metric definitions — Sharp Tracker and Insider Trading

Every number either product displays is defined here, exactly once. If a metric is not in
this file, it should not be on screen.

---

## The three units

These are different things and are never interchangeable. Most counting bugs in this
domain come from silently converting one into another.

| Unit | Definition | A 4-player trade is… |
|---|---|---|
| **transaction** | One Sleeper transaction, identified by its `transaction_id`. | **1** |
| **asset movement** | One asset changing hands inside a transaction. | **4** |
| **observation** | One `(manager, asset, direction)` pair. | **8** — each side observes each asset from its own perspective |

Enforced by `tests/intel/test_ledger.py::TestUnitSeparation`.

---

## Counts

| Metric | Definition |
|---|---|
| `tradeCount` | Distinct `tx_id` values. Counts **transactions**. |
| `assetMovementCount` | Distinct `movement_id` values. Counts **movements**. |
| `buyCount` | Observations where a tracked manager **received** the asset **in a trade**. |
| `sellCount` | Observations where a tracked manager **sent away** the asset **in a trade**. |
| `uniqueManagerCount` | Distinct `user_id` values (stable Sleeper id, never username). |
| `uniqueLeagueCount` | Distinct `league_id` values. |
| `net` | `buyCount − sellCount`. **Never displayed without `volume`.** |
| `volume` | `buyCount + sellCount`. The evidence behind the direction. |
| `buyRate` | `buyCount / volume`, or `null` when volume is 0. |

### Trades only

`buyCount` and `sellCount` count **trades and nothing else**. Waiver claims, free-agent
pickups, and drops are stored in the ledger and are queryable, but never inside a buy or
sell number.

| Sleeper `type` | Counted as a buy/sell? | Where it surfaces |
|---|---|---|
| `trade` | **Yes** | Sharp Tracker board, Insider Trading leads |
| `waiver` | No | "Waiver interest" — a separately labelled section |
| `free_agent` | No | "Waiver interest" |

A drop is not a sell. A waiver add is not a buy. Pinned by
`tests/intel/test_ledger.py::TestTradeVsWaiver`.

---

## Time windows

**Windows are overlapping views over the same rows. They are never additive buckets, and
totals are never produced by adding them.**

A movement 15 days old is inside the 30-day window *and* the 90-day window *and* all-time.
It is **one** movement seen through three lenses:

```
7d  count = 0
30d count = 1
90d count = 1
all count = 1        ← its own query, NOT 0 + 1 + 1 = 2
```

Every window is an independent SQL query against the raw movement rows
(`ledger.asset_signals(since_ms=…, until_ms=…)`). There is deliberately **no function
anywhere in `src/intel/` that accepts two window results and combines them.**

Edges are inclusive: an event exactly `window` old still counts.

| Product | Windows | Default |
|---|---|---|
| Sharp Tracker | 48h · 7d · 14d · 30d | 30d — velocity and trend change matter here |
| Insider Trading | 7d · 30d · 90d · all | **30d**, single uncluttered view; others are explicit filters |

Every count on screen is labelled with its active range, and a drill-down transaction list
lets any number be audited back to its movements.

**Retention** is 400 days (`ledger.MOVEMENT_RETENTION_DAYS`), so the 90-day window is
genuinely answerable. Its predecessor's 45 days made that structurally impossible.

---

## Derived signal metrics

### `signalStrength`

```
normalized_net × sample_confidence × breadth × manager_quality × 100
```

- `normalized_net = net / volume`, bounded to [-1, 1] — the directional *lean*.
- `sample_confidence = volume / (volume + 5)` — saturating, so 1 → 3 observations matters
  far more than 40 → 42.
- `breadth = unique_managers / (unique_managers + 3)` — one manager buying an asset in six
  of their own leagues is **one opinion repeated**, not six opinions.
- `manager_quality` — Sharp Tracker passes the cohort's Sharp Score weight; Insider
  Trading passes `1.0`, because its cohort is defined by league membership, not by skill.

**Why direction is normalized.** A 40-buy / 39-sell asset scores near zero. That is
correct and deliberate: it is real *disagreement*, not a strong signal. Its `volume` and
`confidence` remain high — we are confident that opinion is split. This is exactly why
volume is displayed beside strength and never replaced by it.

### `velocity`

```
(short_window_volume / short_span) ÷ (long_window_volume / long_span)
```

A ratio of **rates**, never a sum. `> 1` means the asset is moving faster recently than
its longer baseline. Returns `null` when the long window holds fewer than 3 observations,
rather than inventing a large number from a tiny denominator.

Because the short window is a strict subset of the long one, shared movements appear in
both numerator and denominator and **cancel** — which is precisely why this construction
cannot double-count. A steady rate yields exactly `1.0` regardless of overlap
(`test_velocity_of_a_steady_rate_is_one`).

### `confidence`

| Tier | Condition |
|---|---|
| `high` | volume ≥ 12 **and** ≥ 4 managers **and** ≥ 3 leagues |
| `medium` | volume ≥ 5 **and** ≥ 2 managers |
| `low` | any activity below that |
| `insufficient` | no activity in the window |

A single observation can never be labelled `high`.

---

## Retired metrics

**`trendScore` — removed.** It was `3·net48h + 2·net7d + 1·net30d`, the board's headline
column *and* sort key, with the formula printed to users. Because the windows are nested,
a 48-hour-old event carried an effective weight of **6**, not the disclosed 3. It ranked
one fresh buy above five sustained ones, and it was a sum of overlapping windows.

`tests/intel/test_signals.py::TestNoWindowSumming::test_trend_score_is_gone` fails if it
returns under any name.

---

## Coverage honesty

`ledger.coverage()` reports what we actually observe: earliest and latest observation,
movement/league/manager/transaction counts, movements by transaction type, the retention
horizon, and `complete: false`.

Statements about a manager's behaviour are scoped to observation, never asserted as
global fact:

> ✅ "We observed one purchase across the leagues and window available to us."
> ❌ "This manager has only bought the player once."
