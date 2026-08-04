#!/usr/bin/env python3
"""Does the composite beat the one component we have already validated?

Market Mispricing has an out-of-sample result (rho +0.126 over 7
non-overlapping 14-day folds).  The composite adds Opportunity at a
DECLARED weight of 0.2 — a prior, never measured.  Until now that was
unavoidable: Opportunity was believed unbacktestable because
``data/rank_history.jsonl`` is untracked and always has been, so the
board history it reads cannot be recovered from git.

That reasoning was half wrong, and the wrong half is the useful one.
The history file is not the only route to past board values: the panel
already reconstructs each as-of date from committed payloads and source
CSVs, and ``build_api_data_contract`` on that payload yields exactly the
``rankDerivedValue`` series ``rank_history.jsonl`` records.  Board
history at any past date is therefore derivable from data already in the
repo, and the ``boardMomentumRisk`` axis can be measured out of sample
like any other signal.

**What this measures, precisely.**  Opportunity as it actually ships
today, which is the momentum axis alone.  Its other axis, ``snapTrend``,
reads ``data/playerctx/snapshot.json`` — a weekly artifact with no
history in the repo — so it is absent in every environment except
production and CANNOT be replayed.  That is stated in the output rather
than papered over: this validates the configuration the board serves
everywhere but production, and leaves the production-only axis
unvalidated.

**Production's window is 30 days, so this replays 30 days.**
``inputs.rank_history()`` calls ``load_history(days=30)`` and the axis
differences the first and last points of whatever series it receives.
Replaying a 3-day window would measure a different signal and report it
under the shipping signal's name — so the lookback here defaults to the
same 30 and is stamped on the result.

**Two runs, one fold set, one cache.**

1. candidate ``composite`` vs benchmark ``mispricing`` — the decision.
   ``evaluate_fold`` scores every series on the same intersection of
   players, so this is a like-for-like head-to-head, not two numbers
   from two studies.
2. candidate ``momentum`` alone — whether the axis carries any signal of
   its own, which is what tells you *why* answer 1 came out as it did.

Exit codes follow the repo's fetch-script convention: 0 success,
1 soft failure (no panel, no usable folds), 2 refusing to measure
(shallow clone, panel too short for the lookback).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.api.data_contract import build_api_data_contract  # noqa: E402
from src.consensus_edge import MODEL_VERSION  # noqa: E402
from src.consensus_edge import backtest as bt  # noqa: E402
from src.consensus_edge import opportunity  # noqa: E402
from src.consensus_edge import outcomes as oc  # noqa: E402
from src.consensus_edge import panel  # noqa: E402
from src.consensus_edge import params as params_mod  # noqa: E402
from src.consensus_edge import score as score_mod  # noqa: E402
from src.consensus_edge.fair_value import _row_key, fair_value_index  # noqa: E402
from src.consensus_edge.inputs import RANK_HISTORY_DAYS  # noqa: E402
from src.consensus_edge.mispricing import score_index  # noqa: E402

OUT_DIR = REPO / "docs" / "measurements"

# Points sampled across the lookback window. The axis differences the
# first and last, so a third exists only to satisfy its ``len >= 3``
# guard — which is itself a real part of the shipping signal (a player
# with under three snapshots gets no momentum score in production
# either). Sampling three rather than thirty is not an approximation of
# the measured quantity; it is the same quantity at a thirtieth of the
# pipeline cost.
_LOOKBACK_POINTS = 3


def log(msg: str) -> None:
    print(f"[ce-composite] {msg}", flush=True)


class _DayCache:
    """Panel days built at most once, in two tiers.

    The tiers matter for wall-clock. A board — values plus market prices
    — is ONE pipeline pass. A mispricing signal is three, because
    ``fair_value_index`` builds the default board plus one anchor-free
    board per market. Momentum needs only the cheap tier, and it needs
    several dates per origin, so collapsing the two would triple the
    cost of the majority of the work for nothing.
    """

    def __init__(self, limit: int = 12):
        self._boards: dict[date, dict] = {}
        self._signals: dict[date, dict[str, float]] = {}
        self._order: list[date] = []
        self._limit = limit
        self.builds = 0

    def values(self, when: date) -> dict[str, float]:
        return self._board(when)["values"]

    def prices(self, when: date) -> dict[str, dict]:
        return self._board(when)["prices"]

    def market_value_signal(self, when: date) -> dict[str, float]:
        """Benchmark: the market price itself.

        If "buy whatever is cheap" explains the returns, a candidate
        signal has to beat that or it is adding nothing.
        """
        return {k: float(v["price"]) for k, v in self.prices(when).items()}

    def _board(self, when: date) -> dict:
        hit = self._boards.get(when)
        if hit is not None:
            return hit
        started = time.time()
        with panel.panel_day(when) as day:
            contract = build_api_data_contract(day.payload, csv_root=day.csv_root)
        values: dict[str, float] = {}
        for row in contract.get("playersArray") or []:
            key = _row_key(row)
            raw = row.get("rankDerivedValue")
            if key and isinstance(raw, (int, float)) and raw > 0:
                values[key] = float(raw)
        entry = {"values": values, "prices": oc.market_prices(contract)}
        self._boards[when] = entry
        self.builds += 1
        self._evict(when)
        log(f"  board {when} in {time.time() - started:.1f}s ({len(values)} valued)")
        return entry

    def mispricing(self, when: date) -> dict[str, float]:
        hit = self._signals.get(when)
        if hit is not None:
            return hit
        started = time.time()
        with panel.panel_day(when) as day:
            # csv_root is load-bearing: without it the pipeline enriches
            # canonicalSiteValues from TODAY's CSVs on disk, which is
            # look-ahead leakage that still produces a valid-looking
            # board. It contaminated 682/692 rows the one time it was
            # omitted.
            index = fair_value_index(day.payload, csv_root=day.csv_root)
        scores = score_index(index)
        signal = {k: v["score"] for k, v in scores.items() if v.get("score") is not None}
        self._signals[when] = signal
        log(f"  mispricing {when} in {time.time() - started:.1f}s ({len(signal)} scored)")
        return signal

    def _evict(self, keep: date) -> None:
        self._order.append(keep)
        while len(self._order) > self._limit:
            stale = self._order.pop(0)
            if stale not in self._order:
                self._boards.pop(stale, None)


def lookback_dates(origin: date, available: list[date], lookback_days: int) -> list[date] | None:
    """Panel dates spanning ``[origin - lookback, origin]``, oldest first.

    Returns None when the panel does not reach far enough back, which
    makes the fold unusable rather than silently measuring a shorter
    window under the shipping window's name.

    Every returned date is at or before ``origin``. That is the entire
    leakage discipline for this signal, and it is enforced here rather
    than by review.
    """
    horizon_start = origin.toordinal() - lookback_days
    eligible = [d for d in available if horizon_start <= d.toordinal() <= origin.toordinal()]
    if len(eligible) < _LOOKBACK_POINTS:
        return None
    eligible.sort()
    if eligible[0].toordinal() > horizon_start + 2:
        # The oldest available date is materially newer than the window
        # start — the window would be short, and a short window measures
        # a smaller price move under the same name.
        return None
    step = (len(eligible) - 1) / (_LOOKBACK_POINTS - 1)
    picked = sorted({eligible[round(i * step)] for i in range(_LOOKBACK_POINTS)})
    return picked if len(picked) >= _LOOKBACK_POINTS else None


def momentum_signal(
    origin: date,
    cache: _DayCache,
    available: list[date],
    lookback_days: int,
) -> dict[str, float]:
    """``boardMomentumRisk`` per player, exactly as the board computes it.

    Calls the production axis rather than reimplementing it. A
    reimplementation would be free to disagree with the shipped code —
    and a backtest that validates a different function than the one that
    ships is worse than no backtest, because it carries the authority of
    one.
    """
    dates = lookback_dates(origin, available, lookback_days)
    if not dates:
        return {}
    series_by_date = [cache.values(d) for d in dates]

    out: dict[str, float] = {}
    for key in series_by_date[-1]:
        points = [{"val": s[key]} for s in series_by_date if key in s]
        axis = opportunity.board_momentum_risk_axis(points)
        if axis["score"] is not None:
            out[key] = float(axis["score"])
    return out


def composite_signal(
    origin: date,
    cache: _DayCache,
    available: list[date],
    lookback_days: int,
    params: dict,
) -> dict[str, float]:
    """The composite as ``service.build_board`` computes it.

    Uses ``score.composite`` itself, so the weights, the renormalisation
    over present components, the core-component requirement and the tanh
    compression are the shipped ones and not a second implementation
    that happens to agree today.

    Sharp Flow is None throughout: the ledger is empty in every
    reachable environment, so this is the composite as actually served.
    """
    mispricing = cache.mispricing(origin)
    momentum = momentum_signal(origin, cache, available, lookback_days)

    out: dict[str, float] = {}
    for key, mis in mispricing.items():
        blended = score_mod.composite(
            {"mispricing": mis, "sharpFlow": None, "opportunity": momentum.get(key)},
            params,
        )
        if blended.get("score") is not None:
            out[key] = float(blended["score"])
    return out


def _run(
    name: str,
    signal_fn,
    *,
    available: list[date],
    horizon_days: int,
    cache: _DayCache,
    benchmark_fns: dict,
    max_folds: int | None,
) -> dict:
    log("")
    log(f"── {name} ──")

    def outcome_fn(origin: date, horizon: date) -> dict[str, float]:
        returns = oc.forward_returns(cache.prices(origin), cache.prices(horizon))
        return {
            k: v["excessReturn"] for k, v in returns.items() if v.get("excessReturn") is not None
        }

    return bt.run_backtest(
        available,
        horizon_days,
        signal_fn=signal_fn,
        outcome_fn=outcome_fn,
        benchmark_fns=benchmark_fns,
        max_folds=max_folds,
        on_fold=lambda r: log(
            f"  fold {r.fold.origin} -> {r.fold.horizon}: "
            + (
                f"rho={r.spearman:+.3f} n={r.n_pairs}"
                if r.usable and r.spearman is not None
                else f"unusable ({r.reason or 'no correlation'})"
            )
        ),
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--horizon-days", type=int, default=14)
    ap.add_argument(
        "--lookback-days",
        type=int,
        default=RANK_HISTORY_DAYS,
        help="momentum window; defaults to production's rank-history window",
    )
    ap.add_argument("--max-folds", type=int, default=None)
    ap.add_argument("--start", type=str, default=None, help="YYYY-MM-DD")
    ap.add_argument("--end", type=str, default=None, help="YYYY-MM-DD")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if panel.is_shallow():
        print(
            "[ce-composite] shallow clone: run `git fetch --unshallow` first. "
            "A backtest over a shallow clone silently measures a few days.",
            file=sys.stderr,
        )
        return 2

    def _parse(value: str | None) -> date | None:
        return datetime.strptime(value, "%Y-%m-%d").date() if value else None

    try:
        available = panel.available_dates(start=_parse(args.start), end=_parse(args.end))
    except panel.PanelUnavailable as exc:
        print(f"[ce-composite] no panel: {exc}", file=sys.stderr)
        return 1
    if not available:
        print("[ce-composite] panel is empty for the requested window", file=sys.stderr)
        return 1

    span = (available[-1] - available[0]).days
    if span < args.lookback_days + args.horizon_days:
        print(
            f"[ce-composite] panel spans {span}d; needs at least "
            f"{args.lookback_days + args.horizon_days}d for a {args.lookback_days}d "
            f"lookback plus a {args.horizon_days}d horizon",
            file=sys.stderr,
        )
        return 2

    # Origins must have a full lookback behind them, so the first
    # `lookback_days` of the panel can only ever be history, never a
    # fold origin. Trimming here rather than letting early folds fail
    # keeps the fold count honest: a fold that could not be measured is
    # not the same as a fold that was never eligible.
    first_origin = available[0].toordinal() + args.lookback_days
    origins = [d for d in available if d.toordinal() >= first_origin]
    log(f"panel {available[0]} -> {available[-1]} ({len(available)} dates)")
    log(
        f"lookback {args.lookback_days}d reserves {len(available) - len(origins)} dates "
        f"as history; {len(origins)} eligible as fold origins"
    )
    planned = bt.folds(origins, args.horizon_days)
    log(f"horizon {args.horizon_days}d -> {len(planned)} non-overlapping folds")
    if not planned:
        print("[ce-composite] no folds after reserving the lookback", file=sys.stderr)
        return 1
    if args.max_folds:
        log(f"capped at {args.max_folds} folds")

    params = params_mod.load()
    cache = _DayCache()
    benchmarks = {
        # The incumbent. "Beats random" is not the bar; "beats the
        # component we already validated" is the entire question.
        "mispricing": cache.mispricing,
        "marketValue": cache.market_value_signal,
    }

    started = time.time()
    try:
        composite = _run(
            "composite (mispricing + momentum) vs mispricing alone",
            lambda o: composite_signal(o, cache, available, args.lookback_days, params),
            available=origins,
            horizon_days=args.horizon_days,
            cache=cache,
            benchmark_fns=benchmarks,
            max_folds=args.max_folds,
        )
        momentum = _run(
            "momentum axis alone",
            lambda o: momentum_signal(o, cache, available, args.lookback_days),
            available=origins,
            horizon_days=args.horizon_days,
            cache=cache,
            benchmark_fns=benchmarks,
            max_folds=args.max_folds,
        )
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"[ce-composite] failed: {exc}", file=sys.stderr)
        return 1

    verdict = _decide(composite)
    summary = {
        "modelVersion": MODEL_VERSION,
        "paramSetId": params.get("paramSetId"),
        "measuredAt": datetime.now(timezone.utc).isoformat(),
        "target": "cohort-excess market return of the anchor board",
        "lookbackDays": args.lookback_days,
        "lookbackPoints": _LOOKBACK_POINTS,
        "compositeWeights": (params.get("composite") or {}).get("weights"),
        "runs": {"composite": composite, "momentum": momentum},
        "decision": verdict,
        "panelBuilds": cache.builds,
        "elapsedSeconds": round(time.time() - started, 1),
        "caveats": [
            "Measures Opportunity as it ships OUTSIDE production: the momentum "
            "axis alone. The snapTrend axis reads data/playerctx/snapshot.json, "
            "which has no history in the repo and cannot be replayed, so it "
            "remains unvalidated.",
            "Sharp Flow is absent throughout — the ledger is empty in every "
            "reachable environment — so this is a two-component composite.",
            "Replays today's pipeline over past inputs: inputs cannot leak, but "
            "the model is current.",
            "Measures market movement, not fantasy production — the panel " "covers an offseason.",
            "Folds are non-overlapping; the fold count is the honest sample size.",
            "Fewer folds than the mispricing-only backtest, because the lookback "
            "window reserves the first "
            f"{args.lookback_days} days of the panel as history. The "
            "head-to-head is still like-for-like: every series in a run is "
            "scored on the same folds and the same player intersection.",
        ],
    }

    log("")
    log(f"composite: {composite['verdict']}")
    log(f"momentum:  {momentum['verdict']}")
    log("")
    log(f"DECISION: {verdict['recommendation']}")
    log(f"  {verdict['rationale']}")

    if args.dry_run:
        print(json.dumps(summary, indent=2, default=str))
        return 0

    if not composite.get("foldsUsable"):
        print("[ce-composite] no usable folds; refusing to write a measurement", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = args.out or (
        OUT_DIR / f"consensus-edge-composite-{date.today().isoformat()}-h{args.horizon_days}.json"
    )
    out.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    log(f"wrote {out.relative_to(REPO)}")
    return 0


def _decide(composite: dict) -> dict:
    """Turn the head-to-head into the weight decision, stated up front.

    The bar was set before the number was known: the composite must beat
    mispricing alone out of sample, or the momentum weight goes to zero
    and the board ships mispricing alone. Encoded here so the decision
    is read off the data rather than argued afterward.
    """
    usable = composite.get("foldsUsable") or 0
    mean = composite.get("meanSpearman")
    bench = (composite.get("benchmarks") or {}).get("mispricing") or {}
    incumbent = bench.get("meanSpearman")
    beaten = bench.get("beatenInFolds")

    if usable < bt.MIN_FOLDS_FOR_A_VERDICT or mean is None or incumbent is None:
        return {
            "recommendation": "inconclusive — keep the declared prior and say so",
            "rationale": (
                f"{usable} usable fold(s); below the {bt.MIN_FOLDS_FOR_A_VERDICT}-fold "
                "floor for calling a direction."
            ),
            "compositeMeanRho": mean,
            "mispricingMeanRho": incumbent,
            "foldsBeaten": beaten,
            "foldsUsable": usable,
        }

    delta = mean - incumbent
    majority = beaten is not None and beaten > usable / 2
    wins = delta > 0 and majority
    return {
        "recommendation": (
            "keep momentum in the composite" if wins else "set the momentum weight to zero"
        ),
        "rationale": (
            f"composite mean rho {mean:+.3f} vs mispricing {incumbent:+.3f} "
            f"(delta {delta:+.3f}); composite beat mispricing in {beaten}/{usable} folds. "
            + (
                "Adding the axis improves the ranking on a majority of folds."
                if wins
                else "The axis does not improve on the component already validated, so "
                "it must not move scores. Note this returns the board to ONE live "
                "component, which puts Strong labels out of reach again — that is "
                "the design working, not a regression."
            )
        ),
        "compositeMeanRho": mean,
        "mispricingMeanRho": incumbent,
        "deltaRho": delta,
        "foldsBeaten": beaten,
        "foldsUsable": usable,
    }


if __name__ == "__main__":
    raise SystemExit(main())
