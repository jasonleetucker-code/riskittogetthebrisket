#!/usr/bin/env python3
"""FAAB Market Heat — descriptive backtest of trending velocity vs real bids.

Joins this league's REAL historical waiver/free-agent claims (persisted by
``scripts/fetch_faab_history.py`` under ``data/faab/``, via
``src.trade.faab_history.load_bid_history``) to the trending-add velocity
recorded for that player at the claim's own instant (``src.trade.
faab_heat_metrics.trending_velocity``, itself reading the real capture in
``src.retention.evidence_store``). Reports DESCRIPTIVE statistics only —
sample size and a simple correlation between velocity and bid-as-percent-
of-budget. It selects and validates NO production coefficient, and nothing
here is read by ``src.trade.faab_engine`` or any recommend path.

    python scripts/faab_heat_backtest.py
    python scripts/faab_heat_backtest.py --league dynasty_new --json

Exit codes follow the repo's script convention: 0 ok, 1 error, 2 no data
(a report with ``status: "insufficient_sample"`` is exit 0 — that is a
successful, honest measurement, not a failure to run).

READ THIS BEFORE QUOTING ANY NUMBER THIS SCRIPT PRINTS
────────────────────────────────────────────────────────
Real trending capture (``C1-RET-05``) only began recording a persisted
series on 2026-08-16. Every run before that series has accumulated enough
history to span the requested windows will honestly report
``"insufficient_sample"`` — that is the correct, expected output while the
observation count is thin, not a bug. See ``scripts/faab_backtest.py`` for
the sibling OLD-vs-NEW bid backtest and its own stated caveats; this script
answers a narrower, different question (does trending velocity move with
bid size at all) and does not repeat that script's per-claim bid modeling.

NO LOOKAHEAD
────────────
Every velocity window is computed strictly at-or-before the claim's own
instant (``trending_velocity``'s own contract) — a claim can never be
joined to trending data that arrived after it was made.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.trade.faab_heat_metrics import DEFAULT_WINDOWS_HOURS, trending_velocity  # noqa: E402
from src.trade.faab_history import history_path, load_bid_history  # noqa: E402

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NO_DATA = 2

#: Below this many joined (velocity, bidPct) pairs for a window, the
#: correlation is not reported as a number — a correlation over a handful
#: of points is not evidence, it's noise dressed as a statistic.
MIN_SAMPLE_FOR_CORRELATION = 10

#: Sleeper's transaction timestamps are ambiguous seconds-vs-milliseconds
#: across endpoints (the same heuristic src/acquisition/events.py::
#: _normalise_ms already applies to this exact field pair). faab_history's
#: own producer stores the RAW value with no normalization, so this script
#: — its first real consumer — normalizes defensively rather than assume.
_MS_THRESHOLD = 10_000_000_000


def _created_at_ms(raw: Any) -> int | None:
    """``None`` for a genuinely unknown transaction time.

    ``faab_history.fetch_bid_history`` stores ``int(status_updated or
    created or 0)`` — a documented ``or 0`` coercion of "we don't know"
    into epoch zero (pre-existing in that file, out of this unit's scope).
    Zero (and any non-positive value) is treated here as unknown, never as
    a real 1970 instant.
    """
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return n * 1000 if n < _MS_THRESHOLD else n


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        return None
    return cov / ((var_x**0.5) * (var_y**0.5))


def build_report(
    payload: dict[str, Any],
    *,
    windows_hours: tuple[int, ...] = DEFAULT_WINDOWS_HOURS,
    min_sample: int = MIN_SAMPLE_FOR_CORRELATION,
    path=None,
) -> dict[str, Any]:
    claims: list[dict[str, Any]] = []
    for season in payload.get("seasons") or []:
        claims.extend(season.get("adds") or [])

    total = len(claims)
    undated = 0
    joined_by_window: dict[str, list[tuple[float, float]]] = {f"{h}h": [] for h in windows_hours}

    for claim in claims:
        bid_pct = claim.get("bidPct")
        player_id = claim.get("playerId")
        if bid_pct is None or not player_id:
            continue
        ms = _created_at_ms(claim.get("createdAt"))
        if ms is None:
            undated += 1
            continue
        velocity = trending_velocity(str(player_id), ms, windows_hours=windows_hours, path=path)
        for window_key, window_result in velocity["windows"].items():
            delta = window_result.get("deltaCount")
            if delta is not None:
                joined_by_window[window_key].append((float(delta), float(bid_pct)))

    windows_report: dict[str, Any] = {}
    for window_key, pairs in joined_by_window.items():
        n = len(pairs)
        entry: dict[str, Any] = {"sampleSize": n}
        if n < min_sample:
            entry["status"] = "insufficient_sample"
            entry["correlation"] = None
        else:
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]
            entry["status"] = "descriptive_only"
            entry["correlation"] = _pearson(xs, ys)
        windows_report[window_key] = entry

    return {
        "totalClaims": total,
        "undatedClaimsExcluded": undated,
        "windows": windows_report,
        "note": (
            "descriptive only -- no coefficient chosen, nothing here feeds "
            "src.trade.faab_engine or any recommend endpoint"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--league", default="dynasty_main", help="league key (default dynasty_main)"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    league_key = str(args.league)
    payload = load_bid_history(league_key)
    if not payload:
        print(
            f"no bid history for league '{league_key}' at {history_path(league_key)}\n"
            f"  run: python scripts/fetch_faab_history.py --league {league_key}",
            file=sys.stderr,
        )
        return EXIT_NO_DATA

    report = build_report(payload)
    report["leagueKey"] = league_key

    if args.json:
        print(json.dumps(report, indent=2))
        return EXIT_OK

    print(f"FAAB Market Heat -- trending-velocity backtest for {league_key!r}")
    print(
        f"  {report['totalClaims']} historical claims, {report['undatedClaimsExcluded']} excluded (undated)"
    )
    for window_key, entry in report["windows"].items():
        if entry["status"] == "insufficient_sample":
            print(
                f"  {window_key}: insufficient sample (n={entry['sampleSize']} < {MIN_SAMPLE_FOR_CORRELATION})"
            )
        else:
            corr = entry["correlation"]
            corr_str = f"{corr:.3f}" if corr is not None else "undefined (no variance)"
            print(
                f"  {window_key}: n={entry['sampleSize']}  correlation(velocity, bidPct)={corr_str}"
            )
    print(f"  {report['note']}")
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(EXIT_ERROR)
