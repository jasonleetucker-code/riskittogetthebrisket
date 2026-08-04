#!/usr/bin/env python3
"""Measure whether the Consensus Edge mispricing signal predicts anything.

This is the script that decides whether the feature ships as a
recommendation or as a labelled experiment.  It replays the board over
committed history, scores each player's mispricing at an origin date,
and correlates that against the cohort-excess market return over the
following horizon.

What it can and cannot establish, stated up front because the result
will be quoted later:

* It measures **market movement**, not fantasy production.  The panel
  covers the 2026 offseason, where no games were played, so a production
  target is unavailable — not merely unmeasured.
* It replays TODAY's pipeline over past inputs.  Inputs cannot leak (they
  come from commits at or before the origin), but the model is current,
  so this answers "would this signal have ranked players usefully?" and
  not "what did the site show that day?".
* Folds are non-overlapping, so the fold count is small by construction.
  A 14-day horizon over ~110 days yields ~7 independent observations.
  Single-digit folds cannot support a confident weight.

Every run writes a dated JSON measurement under ``docs/measurements/``
alongside the verdict, so a future reader can see the evidence rather
than the conclusion.

Exit codes (repo convention — see scripts/refresh_playerctx.py):
    0  - backtest ran and a measurement was written
    1  - soft failure (no panel, no usable folds, write error)
    2  - schema regression: shallow clone, so history is not measurable
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
from src.consensus_edge import outcomes as oc  # noqa: E402
from src.consensus_edge import panel  # noqa: E402
from src.consensus_edge import validation_scope  # noqa: E402
from src.consensus_edge.fair_value import fair_value_index  # noqa: E402
from src.consensus_edge.mispricing import score_index  # noqa: E402

OUT_DIR = REPO / "docs" / "measurements"


def log(msg: str) -> None:
    print(f"[ce-backtest] {msg}", flush=True)


class _DayCache:
    """Builds each as-of date at most once.

    A fold needs the origin board for the signal and the horizon board
    for the outcome, and adjacent folds share a boundary date, so naive
    recomputation would roughly double an already slow walk.
    """

    def __init__(self, limit: int = 8):
        self._cache: dict[date, dict] = {}
        self._order: list[date] = []
        self._limit = limit

    def prices(self, when: date) -> dict[str, dict]:
        return self._entry(when)["prices"]

    def signal(self, when: date) -> dict[str, float]:
        return self._entry(when)["signal"]

    def market_rank_signal(self, when: date) -> dict[str, float]:
        return self._entry(when)["marketValue"]

    def _entry(self, when: date) -> dict:
        hit = self._cache.get(when)
        if hit is not None:
            return hit
        started = time.time()
        with panel.panel_day(when) as day:
            contract = build_api_data_contract(day.payload, csv_root=day.csv_root)
            prices = oc.market_prices(contract)
            # No `scoring_fit_board`, deliberately, and asserted below
            # rather than left to a reader: the reception multipliers
            # are fitted on a whole season's data and the panel cannot
            # reconstruct them as-of, so applying them to a board from
            # three months ago would be look-ahead leakage. The service
            # DOES pass one, and `validation_scope` is what keeps that
            # divergence visible instead of silent.
            index = fair_value_index(day.payload, csv_root=day.csv_root)
        scores = score_index(index)
        signal = {k: v["score"] for k, v in scores.items() if v.get("score") is not None}
        # Benchmark: the market value itself.  If a "buy cheap players"
        # rule explains the returns, the candidate signal has to beat it
        # or it is not adding anything.
        market_value = {k: float(v["price"]) for k, v in prices.items()}
        entry = {"prices": prices, "signal": signal, "marketValue": market_value}
        self._cache[when] = entry
        self._order.append(when)
        while len(self._order) > self._limit:
            self._cache.pop(self._order.pop(0), None)
        log(f"  built {when} in {time.time() - started:.1f}s ({len(signal)} scored)")
        return entry


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--horizon-days", type=int, default=14)
    ap.add_argument("--max-folds", type=int, default=None)
    ap.add_argument("--start", type=str, default=None, help="YYYY-MM-DD")
    ap.add_argument("--end", type=str, default=None, help="YYYY-MM-DD")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if panel.is_shallow():
        print(
            "[ce-backtest] shallow clone: run `git fetch --unshallow` first. "
            "A backtest over a shallow clone silently measures a few days.",
            file=sys.stderr,
        )
        return 2

    def _parse(value: str | None) -> date | None:
        return datetime.strptime(value, "%Y-%m-%d").date() if value else None

    try:
        available = panel.available_dates(start=_parse(args.start), end=_parse(args.end))
    except panel.PanelUnavailable as exc:
        print(f"[ce-backtest] no panel: {exc}", file=sys.stderr)
        return 1

    if not available:
        print("[ce-backtest] panel is empty for the requested window", file=sys.stderr)
        return 1

    log(f"panel {available[0]} -> {available[-1]} ({len(available)} dates)")
    planned = bt.folds(available, args.horizon_days)
    log(f"horizon {args.horizon_days}d -> {len(planned)} non-overlapping folds")
    if args.max_folds:
        log(f"capped at {args.max_folds} folds")

    cache = _DayCache()

    # Rows the signal scored that the outcome layer could not score.
    # `forward_returns` reports a reason per row and every consumer then
    # filters on `excessReturn is not None`, so without this the drop is
    # invisible — and it is not a random drop: a player who leaves the
    # anchor board between origin and horizon has usually been dropped by
    # the market. rho is computed on the survivors either way; this is
    # what lets a reader know how many there were.
    attrition_by_fold: dict[str, dict] = {}

    def outcome_fn(origin: date, horizon: date) -> dict[str, float]:
        returns = oc.forward_returns(cache.prices(origin), cache.prices(horizon))
        attrition_by_fold[origin.isoformat()] = oc.attrition(cache.signal(origin).keys(), returns)
        return {
            k: v["excessReturn"] for k, v in returns.items() if v.get("excessReturn") is not None
        }

    try:
        summary = bt.run_backtest(
            available,
            args.horizon_days,
            signal_fn=cache.signal,
            outcome_fn=outcome_fn,
            benchmark_fns={"marketValue": cache.market_rank_signal},
            max_folds=args.max_folds,
            on_fold=lambda r: log(
                f"  fold {r.fold.origin} -> {r.fold.horizon}: "
                + (
                    f"rho={r.spearman:+.3f} n={r.n_pairs}"
                    if r.usable and r.spearman is not None
                    else f"unusable ({r.reason or 'no correlation'})"
                )
            ),
        )
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"[ce-backtest] failed: {exc}", file=sys.stderr)
        return 1

    summary["modelVersion"] = MODEL_VERSION
    summary["measuredAt"] = datetime.now(timezone.utc).isoformat()
    summary["target"] = "cohort-excess market return of the anchor board"
    # Stamp the configuration this number describes. A measurement that
    # does not say what it measured cannot be checked against the thing
    # it is quoted about.
    summary["configuration"] = dict(validation_scope.MEASURED_CONFIGURATION)
    _offered = sum(int(a.get("of") or 0) for a in attrition_by_fold.values())
    _dropped = sum(int(a.get("dropped") or 0) for a in attrition_by_fold.values())
    _reasons: dict[str, int] = {}
    for a in attrition_by_fold.values():
        for reason, count in (a.get("byReason") or {}).items():
            _reasons[str(reason)] = _reasons.get(str(reason), 0) + int(count)
    summary["attrition"] = {
        "scoredRows": _offered,
        "unscorable": _dropped,
        "rate": (_dropped / _offered) if _offered else None,
        "byReason": dict(sorted(_reasons.items())),
        "byFold": attrition_by_fold,
        "note": (
            "Rows the signal scored that had no measurable outcome, and so were "
            "absent from rho. Not a random sample — a player usually leaves the "
            "anchor board because the market dropped him."
        ),
    }
    summary["caveats"] = [
        "Replays today's pipeline over past inputs: inputs cannot leak, but the model is current.",
        "Measures market movement, not fantasy production — the panel covers an offseason.",
        "Folds are non-overlapping; the fold count is the honest sample size.",
    ]

    log("")
    log(f"VERDICT: {summary['verdict']}")
    for name, stats in summary.get("benchmarks", {}).items():
        log(
            f"  vs {name}: mean rho {stats['meanSpearman']:+.3f}, beaten in {stats['beatenInFolds']}"
        )

    if args.dry_run:
        print(json.dumps(summary, indent=2))
        return 0

    if not summary.get("foldsUsable"):
        print("[ce-backtest] no usable folds; refusing to write a measurement", file=sys.stderr)
        return 1

    out = args.out or (
        OUT_DIR / f"consensus-edge-backtest-{date.today().isoformat()}-h{args.horizon_days}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n")
    log(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
