#!/usr/bin/env python3
"""If you had followed this board, would you have done better?

`run_consensus_edge_backtest.py` answers "does the mispricing score rank
players usefully" — currently no: rho +0.031 over 6 non-overlapping
14-day folds. That is a statement about a number inside the engine. It is
not a statement about the thing a user sees, which is a **list of twenty
names** and a **label next to each player**, and this is what scores
those.

Its verdict is what turned the feature flag ON on 2026-08-04 and what
turned it back OFF the same day, once the board it had been measuring
was repaired (ADR-021/023). Treat its `decision` block as the gate, not
as commentary.

This does. It replays the FULL labelled board — `service.build_board`,
the same function the API calls, not a reimplementation of the composite
— for every fold origin on the committed panel, and asks seven
questions of it. The headline is the first; the rest exist to explain
it.

1. **Top-20 precision.** Take `service.top_movers(board, 20)` — the
   literal `/api/consensus-edge/top` payload — and measure what those
   players did over the horizon against their cohort. Benchmarked
   against twenty players drawn at random from the same priced universe,
   because "positive excess return" means nothing until you know what a
   coin flip returns on the same day.
2. **Label monotonicity.** Buy > Neutral > Sell?
3. **Confidence calibration.** Do better-evidenced rows predict better?
4. **Decile monotonicity.** Is the relationship monotone, or all tails?
5. **Asset-class robustness.** Offense, IDP and picks separately.
6. **Turnover.** How much does the top-20 churn between origins? A list
   that reshuffles constantly is unusable however well it correlates.
7. **Panel depth.** The panel is NOT homogeneous — `CSVs/site_raw/`
   holds 9 files on 2026-04-16 and 24 from 2026-06-01. That has never
   been controlled for in any measurement here. Reported per fold so a
   reader can see whether the edge lives only in the well-sourced era.

**Three things that would each silently invalidate this**, all handled
explicitly rather than by care:

* `csv_root` is threaded into every board build. Without it the pipeline
  enriches from TODAY's CSVs and the replay is contaminated — measured
  at **666 of 667 rows changing score** on a single panel day. This is
  why `build_board` gained the parameter.
* The scoring fit is passed **inert**. `scoring_fit.measure` reaches
  nflverse on a cache miss, and an active fit is exactly the divergence
  `validation_scope` flags — the published rho describes a board with
  the fit off, so a replay applying it measures something else.
* `hours_stale` is **pinned**, not inherited. `dataFreshness.ageHours`
  comes from file mtime, and the panel materialises CSVs into a fresh
  temp dir, so an inherited value would read as perfectly fresh and sit
  every row at its confidence ceiling.

**What this cannot show.** Coverage is 1/3 with one weighted component,
so confidence caps at 69.34 and Strong Buy / Strong Sell are
unreachable; `Conflicted` needs two opposing weighted components and
`Withheld` is never passed by the service. Those four buckets are empty
by construction and are reported as such rather than omitted. Every
would-be Strong Buy is demoted into `Buy` with a `labelReason`, so the
Buy bucket is split on that — pooling them measures a blend.

Exit codes: 0 success, 1 soft failure (no panel, no usable folds),
2 refusing to measure (shallow clone).
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.api.data_contract import build_api_data_contract  # noqa: E402
from src.consensus_edge import MODEL_VERSION  # noqa: E402
from src.consensus_edge import backtest as bt  # noqa: E402
from src.consensus_edge import outcomes as oc  # noqa: E402
from src.consensus_edge import panel  # noqa: E402
from src.consensus_edge import params as params_mod  # noqa: E402
from src.consensus_edge import scoring_fit, service, validation_scope  # noqa: E402

OUT_DIR = REPO / "docs" / "measurements"

# Staleness stamped on every replayed board. The live board reads ~8h
# (scrape runs every 2h; the oldest market anchor lags). Pinned rather
# than inherited — see the module docstring.
_PINNED_HOURS_STALE = 8.0

# Bootstrap draws for the random-20 benchmark. Seeded: a verdict that
# changes between runs is not a verdict.
_BOOTSTRAP_DRAWS = 2000
_BOOTSTRAP_SEED = 20260804

_TOP_N = 20

# Market value below which a "buy" is not a trade you can actually make.
# The log-ratio mispricing score is easiest to make large on a
# floor-priced asset — a 60-point move on a 152-value rookie is +40% —
# so the raw top-20 skews deep. Measured on one fold, four of the top
# twenty were priced under 310 and contributed every bit of the mean.
# A parallel "tradeable" list is scored above this floor so the report
# says whether the edge survives among assets worth trading for.
_TRADEABLE_VALUE_FLOOR = 2000.0


def log(msg: str) -> None:
    print(f"[ce-validate] {msg}", flush=True)


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


class _DayCache:
    """Boards and prices per as-of date, built at most once.

    A labelled board is four pipeline passes (the contract, plus
    `fair_value_index`'s default board and one anchor-free board per
    market), so adjacent folds sharing a boundary date matter.
    """

    def __init__(self, hours_stale: float, params: dict[str, Any]):
        self._cache: dict[date, dict] = {}
        self._hours_stale = hours_stale
        self._params = params
        self._inert = scoring_fit.inert_board(
            "historical replay: the fit is held inert so the board matches the "
            "configuration the published measurement was produced under"
        )
        self.builds = 0

    def day(self, when: date) -> dict:
        hit = self._cache.get(when)
        if hit is not None:
            return hit
        started = time.time()
        with panel.panel_day(when) as pd:
            contract = build_api_data_contract(pd.payload, csv_root=pd.csv_root)
            prices = oc.market_prices(contract)
            board = service.build_board(
                contract,
                params=self._params,
                hours_stale=self._hours_stale,
                # Both load-bearing. See the module docstring.
                csv_root=pd.csv_root,
                scoring_fit_board=self._inert,
            )
            sources = len(pd.csv_sources)
        entry = {"board": board, "prices": prices, "sourceCount": sources}
        self._cache[when] = entry
        self.builds += 1
        scored = sum(1 for r in board.get("players") or [] if r.get("score") is not None)
        log(f"  board {when} in {time.time() - started:.1f}s ({scored} scored, {sources} sources)")
        return entry


def _returns(cache: _DayCache, origin: date, horizon: date) -> dict[str, dict[str, Any]]:
    return oc.forward_returns(cache.day(origin)["prices"], cache.day(horizon)["prices"])


def _outcomes(returns: dict[str, dict[str, Any]]) -> dict[str, float]:
    return {k: v["excessReturn"] for k, v in returns.items() if v.get("excessReturn") is not None}


def _bucket_stats(
    rows: list[dict[str, Any]],
    outcomes: dict[str, float],
    returns: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Robust summary of one group of board rows.

    **The median is the headline and the mean is a diagnostic**, which is
    the opposite of the obvious choice and is forced by the data. These
    are percentage returns on assets whose denominators span 152 to 9999.
    Measured on one real fold: four players priced 152-306 returned
    +327%, +268%, +210% and +195%, dragging the top-20 mean to +59.44%
    while the median sat at +1.04%. A 60-point absolute move on a
    floor-priced rookie is noise wearing a huge percentage; reporting the
    mean as the result would have manufactured an edge out of four cheap
    assets.

    `topContributorShare` makes that dependence visible instead of
    implicit: it is the fraction of the summed excess coming from the
    single largest row. Anything near 1.0 means the mean is one player.

    `attrition` is the second thing this used to hide. `n` counts the
    rows that COULD be scored; the rest were silently absent from every
    statistic. Those rows are not a random sample — a player who leaves
    the anchor board between origin and horizon has usually been dropped
    by the market — so the rate belongs next to the headline. Pass
    `returns` (the full `forward_returns` map) to get it; without it the
    field is `None` rather than a reassuring zero.
    """
    values = [outcomes[r["playerKey"]] for r in rows if r["playerKey"] in outcomes]
    lost = oc.attrition([r["playerKey"] for r in rows], returns) if returns is not None else None
    if not values:
        return {
            "n": 0,
            "meanExcess": None,
            "medianExcess": None,
            "hitRate": None,
            "attrition": lost,
        }
    ordered = sorted(values)
    trim = len(ordered) // 10
    trimmed = ordered[trim : len(ordered) - trim] if len(ordered) >= 10 else ordered
    total = sum(abs(v) for v in values)
    return {
        "n": len(values),
        "medianExcess": statistics.median(values),
        "meanExcess": statistics.fmean(values),
        "trimmedMeanExcess": statistics.fmean(trimmed) if trimmed else None,
        "hitRate": sum(1 for v in values if v > 0) / len(values),
        "topContributorShare": (max(abs(v) for v in values) / total) if total > 0 else None,
        "attrition": lost,
    }


def _random_benchmark(universe: list[float], k: int, rng: random.Random) -> dict[str, Any]:
    """What does drawing ``k`` players at random return on this day?

    Deliberately NOT `board_holdout.paired_bootstrap`, which compares two
    rank correlations over the SAME players — a different shape. Here the
    question is whether one selected subset beats subsets of the same
    size chosen without skill, so the resample is over which players get
    picked.

    Returns the distribution's median and its 5th/95th percentiles, so a
    top-20 mean can be placed against what luck produces at this n. The
    mean of the distribution is the universe mean by construction; the
    SPREAD is the part that matters, and is the part a bare "positive
    excess return" claim hides.
    """
    if len(universe) < k:
        return {"draws": 0, "median": None, "p05": None, "p95": None}
    means = []
    for _ in range(_BOOTSTRAP_DRAWS):
        means.append(statistics.fmean(rng.sample(universe, k)))
    means.sort()
    return {
        "draws": _BOOTSTRAP_DRAWS,
        "median": means[len(means) // 2],
        "p05": means[int(0.05 * len(means))],
        "p95": means[int(0.95 * len(means))],
    }


def _percentile_of(value: float, sorted_sample: list[float]) -> float:
    below = sum(1 for v in sorted_sample if v < value)
    return below / len(sorted_sample) if sorted_sample else 0.0


def _equal_count_deciles(
    rows: list[dict[str, Any]], outcomes: dict[str, float], bins: int = 10
) -> list[dict[str, Any]]:
    """Equal-COUNT buckets over the score, not equal-width.

    Nothing in the repo does this. `bdvm.backtest.calibration` bins by
    fixed range on [0, 1], which is wrong for a score on [-76, +76] whose
    mass sits near zero — equal-width bins would put nearly every row in
    the middle bucket and leave the tails at n=2.
    """
    scored = [r for r in rows if r.get("score") is not None and r["playerKey"] in outcomes]
    if len(scored) < bins * 3:
        return []
    scored.sort(key=lambda r: r["score"])
    out = []
    size = len(scored) / bins
    for i in range(bins):
        chunk = scored[int(i * size) : int((i + 1) * size)]
        if not chunk:
            continue
        stats = _bucket_stats(chunk, outcomes)
        stats["decile"] = i + 1
        stats["meanScore"] = statistics.fmean(r["score"] for r in chunk)
        out.append(stats)
    return out


def _label_groups(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Board rows by label, with Buy/Sell split on demotion.

    Every would-be Strong Buy lands in `Buy` carrying a `labelReason`,
    because the confidence ceiling (69.34) sits under the Strong
    threshold (70). Pooling the two measures a blend of different score
    distributions, so the demoted rows get their own group — they are the
    highest-scoring rows on the board and the most interesting bucket.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        label = str(row.get("label") or "")
        if label in ("Buy", "Sell") and row.get("labelReason"):
            label = f"{label} (demoted from Strong)"
        groups.setdefault(label, []).append(row)
    return groups


def _confidence_buckets(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    edges = [(0, 35, "<35"), (35, 50, "35-50"), (50, 60, "50-60"), (60, 101, "60+")]
    out: dict[str, list[dict[str, Any]]] = {name: [] for _, _, name in edges}
    for row in rows:
        conf = row.get("confidence")
        if not isinstance(conf, (int, float)):
            continue
        for low, high, name in edges:
            if low <= conf < high:
                out[name].append(row)
                break
    return out


def _evaluate_fold(
    cache: _DayCache, origin: date, horizon: date, rng: random.Random
) -> dict[str, Any]:
    board = cache.day(origin)["board"]
    returns = _returns(cache, origin, horizon)
    outcomes = _outcomes(returns)
    players = board.get("players") or []
    scored = [r for r in players if r.get("score") is not None and r["playerKey"] in outcomes]
    if len(scored) < bt.MIN_PAIRS_PER_FOLD:
        return {
            "origin": origin.isoformat(),
            "horizon": horizon.isoformat(),
            "usable": False,
            "reason": f"only {len(scored)} rows had both a score and an outcome",
        }

    universe = [outcomes[r["playerKey"]] for r in scored]
    movers = service.top_movers(board, limit=_TOP_N)
    benchmark = _random_benchmark(universe, _TOP_N, rng)
    bench_sample = sorted(
        statistics.fmean(rng.sample(universe, _TOP_N)) for _ in range(_BOOTSTRAP_DRAWS)
    )

    top_buys = _bucket_stats(movers["buys"], outcomes, returns)
    top_sells = _bucket_stats(movers["sells"], outcomes, returns)

    # The same list restricted to assets worth trading for. `top_movers`
    # ranks on score alone, and score is easiest to maximise on a
    # floor-priced asset, so the published list skews deep — this says
    # whether the edge survives where a user could act on it.
    tradeable_pool = [
        r
        for r in board.get("players") or []
        if r.get("qualified")
        and (r.get("score") or 0) > 0
        and isinstance(r.get("marketValue"), (int, float))
        and r["marketValue"] >= _TRADEABLE_VALUE_FLOOR
    ][:_TOP_N]
    top_values = [
        r["marketValue"] for r in movers["buys"] if isinstance(r.get("marketValue"), (int, float))
    ]

    fold: dict[str, Any] = {
        "origin": origin.isoformat(),
        "horizon": horizon.isoformat(),
        "usable": True,
        "rowsScoredWithOutcome": len(scored),
        "panelSourceCount": cache.day(origin)["sourceCount"],
        "universeMeanExcess": _mean(universe),
        "topBuys": top_buys,
        "topSells": top_sells,
        # Actionability, not accuracy. A correct call on a 152-value
        # rookie is not a trade anyone can make.
        "topBuysTradeable": _bucket_stats(tradeable_pool, outcomes, returns),
        "topBuysValueProfile": {
            "medianMarketValue": statistics.median(top_values) if top_values else None,
            "belowTradeableFloor": sum(1 for v in top_values if v < _TRADEABLE_VALUE_FLOOR),
            "of": len(top_values),
            "floor": _TRADEABLE_VALUE_FLOOR,
        },
        "randomBenchmark": benchmark,
        # Where the top-20 mean falls in the luck distribution. 0.95 means
        # only 5% of random draws did as well.
        "topBuysPercentileVsRandom": (
            _percentile_of(top_buys["meanExcess"], bench_sample)
            if top_buys["meanExcess"] is not None
            else None
        ),
        "topBuysBeatRandomMedian": (
            top_buys["meanExcess"] > benchmark["median"]
            if top_buys["meanExcess"] is not None and benchmark["median"] is not None
            else None
        ),
        "byLabel": {
            name: _bucket_stats(rows, outcomes, returns)
            for name, rows in _label_groups(players).items()
        },
        "byConfidence": {
            name: _bucket_stats(rows, outcomes)
            for name, rows in _confidence_buckets(scored).items()
        },
        "byAssetClass": {},
        "deciles": _equal_count_deciles(scored, outcomes),
    }

    for asset in ("offense", "idp", "pick"):
        subset = [r for r in scored if r.get("assetClass") == asset]
        fold["byAssetClass"][asset] = _bucket_stats(subset, outcomes)

    return fold


def _turnover(cache: _DayCache, origins: list[date]) -> list[dict[str, Any]]:
    """Overlap of consecutive top-20 buy lists.

    A board that is right on average but reshuffles its recommendations
    every fold is not actionable — you cannot trade on a list that has
    changed by the time you act. Nothing else here measures this.
    """
    out = []
    previous: set[str] | None = None
    previous_date: date | None = None
    for when in origins:
        movers = service.top_movers(cache.day(when)["board"], limit=_TOP_N)
        current = {r["playerKey"] for r in movers["buys"]}
        if previous is not None and previous and current:
            out.append(
                {
                    "from": previous_date.isoformat(),
                    "to": when.isoformat(),
                    "overlap": len(previous & current),
                    "of": min(len(previous), len(current)),
                    "retentionRate": len(previous & current) / min(len(previous), len(current)),
                }
            )
        previous, previous_date = current, when
    return out


def _pool(folds: list[dict[str, Any]], path: list[str]) -> dict[str, Any]:
    """Fold-count-weighted summary of one bucket across usable folds.

    Reports the per-fold spread beside the mean deliberately. Rows within
    a fold are cross-sectionally correlated — they share a market — so
    the FOLD count is the honest sample size, not the row count. Same
    discipline as `backtest.summarise`.
    """
    medians: list[float] = []
    means: list[float] = []
    ns: list[int] = []
    offered: list[int] = []
    dropped: list[int] = []
    by_reason: dict[str, int] = {}
    for fold in folds:
        node: Any = fold
        for key in path:
            node = (node or {}).get(key) if isinstance(node, dict) else None
        if isinstance(node, dict) and isinstance(node.get("medianExcess"), (int, float)):
            medians.append(float(node["medianExcess"]))
            if isinstance(node.get("meanExcess"), (int, float)):
                means.append(float(node["meanExcess"]))
            ns.append(int(node.get("n") or 0))
            lost = node.get("attrition")
            if isinstance(lost, dict):
                offered.append(int(lost.get("of") or 0))
                dropped.append(int(lost.get("dropped") or 0))
                for reason, count in (lost.get("byReason") or {}).items():
                    by_reason[str(reason)] = by_reason.get(str(reason), 0) + int(count)
    if not medians:
        return {"folds": 0, "medianExcess": None, "foldsPositive": 0, "totalRows": 0}
    return {
        "folds": len(medians),
        # Mean OF the per-fold medians: robust within a fold, and the
        # fold count stays the sample size across them.
        "medianExcess": statistics.fmean(medians),
        "meanExcess": statistics.fmean(means) if means else None,
        "foldsPositive": sum(1 for v in medians if v > 0),
        "totalRows": sum(ns),
        # Rows this bucket CONTAINED, against rows it could score. The
        # gap is survivorship: those rows were dropped by every statistic
        # above and are disproportionately the worst outcomes, since a
        # player usually leaves the anchor board because the market let
        # him go. Quoting `medianExcess` without this quotes a number
        # computed on the survivors.
        "rowsOffered": sum(offered),
        "rowsDropped": sum(dropped),
        "attritionRate": (sum(dropped) / sum(offered)) if sum(offered) else None,
        "attritionByReason": dict(sorted(by_reason.items())),
        "perFoldMedian": medians,
        "perFoldMean": means,
    }


def _decide(summary: dict[str, Any]) -> dict[str, Any]:
    """The ship / don't-ship call, on a bar set before the numbers were.

    Headline is top-20 precision against the random benchmark. Label
    monotonicity and the decile check are diagnostics that explain the
    headline; they do not override it. The asset-class clause is a
    separate veto: an edge confined to one class must not be presented
    behind a board that looks uniform.
    """
    top = summary["pooled"]["topBuys"]
    usable = top.get("folds") or 0
    beat = summary["topBuysBeatRandomInFolds"]
    # The MEDIAN decides. See `_bucket_stats` — the mean of percentage
    # returns across assets priced 152 to 9999 is one cheap rookie away
    # from any conclusion you like.
    median = top.get("medianExcess")

    if usable < bt.MIN_FOLDS_FOR_A_VERDICT or median is None:
        return {
            "recommendation": "inconclusive — not enough usable folds to call it",
            "rationale": f"{usable} usable fold(s), floor is {bt.MIN_FOLDS_FOR_A_VERDICT}.",
        }

    classes = summary["pooled"]["byAssetClass"]
    positive_classes = [
        name
        for name, stats in classes.items()
        if (stats.get("folds") or 0) >= bt.MIN_FOLDS_FOR_A_VERDICT
        # Median here too, for the same reason the headline uses it: a
        # single floor-priced asset returning +327% would otherwise make
        # an asset class look positive on its own.
        and (stats.get("medianExcess") or 0) > 0
    ]
    measured_classes = [
        name
        for name, stats in classes.items()
        if (stats.get("folds") or 0) >= bt.MIN_FOLDS_FOR_A_VERDICT
    ]
    # At least one asset class must show a positive edge, and if two or
    # more were measurable at least two must. The earlier form — "or
    # len(measured_classes) <= 1" alone — shipped a board on which ZERO
    # measured classes were positive, because a single measurable class
    # satisfied it vacuously.
    broad = bool(positive_classes) and (len(positive_classes) >= 2 or len(measured_classes) <= 1)

    ships = median > 0 and beat > usable / 2 and broad
    return {
        "recommendation": "ship it (flag ON)" if ships else "do not ship yet",
        "rationale": (
            f"top-20 buys returned a median {median:+.2%} cohort-excess across "
            f"{usable} folds and beat a random-20 draw in {beat}/{usable}. "
            f"Asset classes with a positive measured edge: "
            f"{', '.join(positive_classes) or 'none'} (of {', '.join(measured_classes) or 'none'} measured)."
            + (
                ""
                if ships
                else " Bar was: positive mean AND beat random in a majority of folds"
                " AND the edge is not confined to a single asset class."
            )
        ),
        "medianExcessTop20": median,
        "meanExcessTop20": top.get("meanExcess"),
        "foldsBeatRandom": beat,
        "foldsUsable": usable,
        "positiveAssetClasses": positive_classes,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--horizon-days", type=int, default=14)
    ap.add_argument("--max-folds", type=int, default=None)
    ap.add_argument("--start", type=str, default=None, help="YYYY-MM-DD")
    ap.add_argument("--end", type=str, default=None, help="YYYY-MM-DD")
    ap.add_argument("--hours-stale", type=float, default=_PINNED_HOURS_STALE)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if panel.is_shallow():
        print(
            "[ce-validate] shallow clone: run `git fetch --unshallow` first.",
            file=sys.stderr,
        )
        return 2

    def _parse(value: str | None) -> date | None:
        return datetime.strptime(value, "%Y-%m-%d").date() if value else None

    try:
        available = panel.available_dates(start=_parse(args.start), end=_parse(args.end))
    except panel.PanelUnavailable as exc:
        print(f"[ce-validate] no panel: {exc}", file=sys.stderr)
        return 1
    if not available:
        print("[ce-validate] panel is empty for the requested window", file=sys.stderr)
        return 1

    folds = bt.folds(available, args.horizon_days)
    truncated = False
    if args.max_folds and len(folds) > args.max_folds:
        folds = folds[: args.max_folds]
        truncated = True
    if not folds:
        print("[ce-validate] no folds", file=sys.stderr)
        return 1

    log(f"panel {available[0]} -> {available[-1]} ({len(available)} dates)")
    log(f"horizon {args.horizon_days}d -> {len(folds)} non-overlapping folds")
    log(f"hoursStale pinned at {args.hours_stale}; scoring fit held inert")
    if truncated:
        log(f"TRUNCATED to {args.max_folds} folds — coverage is not complete")

    params = params_mod.load()
    cache = _DayCache(args.hours_stale, params)
    rng = random.Random(_BOOTSTRAP_SEED)

    started = time.time()
    results: list[dict[str, Any]] = []
    try:
        for fold in folds:
            entry = _evaluate_fold(cache, fold.origin, fold.horizon, rng)
            results.append(entry)
            if entry["usable"]:
                buys = entry["topBuys"]
                log(
                    f"  fold {fold.origin} -> {fold.horizon}: top-20 buys "
                    f"mean {buys['meanExcess']:+.2%} (hit {buys['hitRate']:.0%}), "
                    f"median {buys['medianExcess']:+.2%}, "
                    f"random median {entry['randomBenchmark']['median']:+.2%}, "
                    f"pct {entry['topBuysPercentileVsRandom']:.0%}"
                )
            else:
                log(f"  fold {fold.origin}: unusable ({entry['reason']})")
        turnover = _turnover(cache, [f.origin for f in folds])
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"[ce-validate] failed: {exc}", file=sys.stderr)
        return 1

    usable = [f for f in results if f["usable"]]
    label_names = sorted({name for f in usable for name in f["byLabel"]})
    conf_names = sorted({name for f in usable for name in f["byConfidence"]})

    summary: dict[str, Any] = {
        "modelVersion": MODEL_VERSION,
        "paramSetId": params.get("paramSetId"),
        "measuredAt": datetime.now(timezone.utc).isoformat(),
        "target": "cohort-excess market return of the anchor board",
        "horizonDays": args.horizon_days,
        "topN": _TOP_N,
        "hoursStalePinned": args.hours_stale,
        "panelStart": available[0].isoformat(),
        "panelEnd": available[-1].isoformat(),
        "foldsAttempted": len(results),
        "foldsUsable": len(usable),
        "foldsTruncated": truncated,
        "configuration": dict(validation_scope.MEASURED_CONFIGURATION),
        "folds": results,
        "turnover": turnover,
        "topBuysBeatRandomInFolds": sum(1 for f in usable if f.get("topBuysBeatRandomMedian")),
        "pooled": {
            "topBuys": _pool(usable, ["topBuys"]),
            "topBuysTradeable": _pool(usable, ["topBuysTradeable"]),
            "topSells": _pool(usable, ["topSells"]),
            "byLabel": {name: _pool(usable, ["byLabel", name]) for name in label_names},
            "byConfidence": {name: _pool(usable, ["byConfidence", name]) for name in conf_names},
            "byAssetClass": {
                name: _pool(usable, ["byAssetClass", name]) for name in ("offense", "idp", "pick")
            },
        },
        # Two remain impossible, for reasons coverage cannot fix. Strong
        # Buy / Strong Sell were here too until the coverage denominator
        # stopped counting zero-weight components; they are now reachable
        # and are measured above like any other label.
        "unreachableLabels": {
            "Conflicted": (
                "needs two opposing components with weight > 0; opportunity is weight 0 "
                "and sharpFlow is absent wherever the ledger is empty"
            ),
            "Withheld": "classify's quarantined kwarg is never passed by build_board",
        },
        "panelBuilds": cache.builds,
        "elapsedSeconds": round(time.time() - started, 1),
        "caveats": [
            "Scores the SHIPPED artifact — service.build_board and "
            "service.top_movers — not a reimplementation of the composite.",
            "Every board is built with csv_root threaded, the scoring fit held "
            "inert, and hoursStale pinned. Omitting any one silently invalidates "
            "the result rather than erroring.",
            "The panel is entirely OFFSEASON (2026-04-16 onward; the 2025 season "
            "ended January 2026 and the repo's first commit is 2026-03-09). "
            "Offseason price moves are driven by different forces than in-season "
            "ones; re-run once in-season dates accrue.",
            "The panel is not homogeneous: CSVs/site_raw holds 9 files at the "
            "start of the window and 24 from 2026-06-01. Per-fold source counts "
            "are reported so a reader can judge whether the edge is confined to "
            "the well-sourced era.",
            "Measures market movement, not fantasy production.",
            "Folds are non-overlapping; the fold count is the honest sample size, "
            "not the row count.",
        ],
    }
    summary["decision"] = _decide(summary)

    log("")
    top = summary["pooled"]["topBuys"]
    trade = summary["pooled"]["topBuysTradeable"]
    if top["medianExcess"] is not None:
        log(
            f"TOP-{_TOP_N} BUYS: median {top['medianExcess']:+.2%} cohort-excess over "
            f"{top['folds']} folds ({top['foldsPositive']}/{top['folds']} positive), "
            f"beat random in {summary['topBuysBeatRandomInFolds']}/{top['folds']}"
        )
        log(f"  (mean {top['meanExcess']:+.2%} — outlier-driven, see topContributorShare)")
    if trade.get("medianExcess") is not None:
        log(
            f"TRADEABLE (value >= {_TRADEABLE_VALUE_FLOOR:.0f}): median "
            f"{trade['medianExcess']:+.2%} over {trade['folds']} folds "
            f"({trade['foldsPositive']}/{trade['folds']} positive)"
        )
    for name in label_names:
        pooled = summary["pooled"]["byLabel"][name]
        if pooled["medianExcess"] is not None:
            log(
                f"  {name:32s} {pooled['medianExcess']:+.2%}  "
                f"({pooled['foldsPositive']}/{pooled['folds']} folds positive, "
                f"{pooled['totalRows']} rows)"
            )
    log("")
    log(f"DECISION: {summary['decision']['recommendation']}")
    log(f"  {summary['decision']['rationale']}")

    if args.dry_run:
        print(json.dumps(summary, indent=2, default=str))
        return 0
    if not usable:
        print("[ce-validate] no usable folds; refusing to write", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = args.out or (
        OUT_DIR
        / f"consensus-edge-board-validation-{date.today().isoformat()}-h{args.horizon_days}.json"
    )
    out.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    log(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
