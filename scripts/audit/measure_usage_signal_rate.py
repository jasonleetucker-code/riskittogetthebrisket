"""How often would the usage-signal engine actually fire?

``src/news/usage_signals.py`` has been in the tree, complete and unit
tested, with zero production callers, while
``src/api/feature_flags.py`` reported ``usage_signals: True`` and
asserted it "fires via unified_signal_engine".  Before wiring it, this
measures what it would emit against real data.

MEASURED 2026-07-27 on the persisted 2025 season, and the answer is that
it is not ready to wire
────────────────────────────────────────────────────────────────────────
Evaluated at every mid-season week rather than at each player's last
week — the terminal week is disproportionately an injury exit, so
scoring the engine there overstates it by selection alone::

    week   active players   BUY   SELL   alert rate
      6         885          90     59      16.8%
     10         841          72     57      15.3%
     14         851          82     82      19.3%
     18         948         156     76      24.5%
                                        ---------
                            mean weekly rate  17.8%

**One in six active players, every week, indefinitely.**  That is not a
signal; it is a weather report.  The rate is stable across thirteen
weeks, so it is the engine's resting behaviour and not a bad week.

WHY THRESHOLD TUNING DOES NOT RESCUE IT
────────────────────────────────────────
The obvious fix — floor the standard deviation so a near-constant window
stops producing enormous z-scores — makes it **worse**, 19% to 32%.  A
floor raises the denominator, but it also admits every window with
``sd == 0`` that the current code skips by dividing-by-zero-guard, and
those are exactly the players who sat for four weeks and then played.

Dropping the z-score entirely for a plain absolute-move rule does not
help either: requiring a **30 percentage point** swing in snap share
still fires on 21% of players.

The conclusion is about the statistic, not the constants.  A four-
observation z-score on a bounded 0-1 share has almost no discriminating
power, because week-to-week snap share in the NFL genuinely moves that
much — blowouts, package rotation, one-week injuries, and returns from
them.  Calibrating this needs a different formulation (persistence
across consecutive weeks, or a role-change model that knows about the
depth chart), which is new work rather than a constant to re-tune.

So the engine stays unwired, ``usage_signals`` now defaults **OFF**,
and its registry comment no longer claims behaviour it does not have.
Re-run this after any change to the detector; the number to beat is a
low-single-digit weekly rate.

Usage::

    python3 scripts/audit/measure_usage_signal_rate.py
    python3 scripts/audit/measure_usage_signal_rate.py --season 2025 --json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.nfl_data import actuals_store  # noqa: E402
from src.nfl_data.usage_windows import build_rolling_windows  # noqa: E402
from src.news.usage_signals import _BUY_Z, _SELL_Z, _ACTIVE_STARTER_SNAP_PCT  # noqa: E402

#: Weeks 1-5 cannot produce a full trailing window, so including them
#: would report a low rate for a reason that has nothing to do with the
#: detector.
FIRST_SCORED_WEEK = 6


def measure(season: int, *, actuals_dir: Path | None = None) -> dict[str, Any]:
    rows = actuals_store.usage_stat_rows(season, actuals_dir=actuals_dir)
    if not rows:
        return {
            "error": (
                f"no persisted actuals for {season}; run "
                f"scripts/persist_nfl_actuals.py --seasons {season} first"
            )
        }

    windows = build_rolling_windows(rows)
    current = {(r["player_id_gsis"], r["week"]): r for r in rows}
    joined = sum(1 for r in rows if r.get("snap_pct") is not None)

    weeks: list[dict[str, Any]] = []
    for week in sorted({w.week for w in windows if w.week >= FIRST_SCORED_WEEK}):
        active = [w for w in windows if w.week == week]
        buy = sell = scored = 0
        for w in active:
            row = current.get((w.player_id, week))
            if not row or row.get("snap_pct") is None:
                continue
            scored += 1
            if w.snap_pct_z is None:
                continue
            if w.snap_pct_z >= _BUY_Z:
                buy += 1
            elif w.snap_pct_z <= _SELL_Z and w.snap_pct_mean >= _ACTIVE_STARTER_SNAP_PCT:
                sell += 1
        total = buy + sell
        weeks.append(
            {
                "week": week,
                "activePlayers": scored,
                "buy": buy,
                "sell": sell,
                "alerts": total,
                "alertRate": round(total / scored, 4) if scored else None,
            }
        )

    rates = [w["alertRate"] for w in weeks if w["alertRate"] is not None]
    return {
        "season": season,
        "flatRows": len(rows),
        "snapJoined": joined,
        "snapJoinRate": round(joined / len(rows), 4),
        "thresholds": {
            "buyZ": _BUY_Z,
            "sellZ": _SELL_Z,
            "activeStarterSnapPct": _ACTIVE_STARTER_SNAP_PCT,
        },
        "meanWeeklyAlertRate": round(statistics.fmean(rates), 4) if rates else None,
        "weeks": weeks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2025)
    parser.add_argument("--dir", default=None, help="Override the actuals directory.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = measure(args.season, actuals_dir=Path(args.dir) if args.dir else None)
    if "error" in result:
        print(f"[usage-signal-rate] {result['error']}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print(
        f"[usage-signal-rate] {result['season']}: {result['flatRows']} player-weeks, "
        f"{result['snapJoinRate']:.2%} with snaps joined"
    )
    print("  week  active   BUY  SELL  alerts   rate")
    for w in result["weeks"]:
        rate = f"{w['alertRate']:.1%}" if w["alertRate"] is not None else "n/a"
        print(
            f"  {w['week']:4d}  {w['activePlayers']:6d}  {w['buy']:4d}  "
            f"{w['sell']:4d}  {w['alerts']:6d}  {rate:>6}"
        )
    mean = result["meanWeeklyAlertRate"]
    print(f"\n  mean weekly alert rate: {mean:.1%}" if mean is not None else "\n  no scored weeks")
    if mean is not None and mean > 0.05:
        print(
            "  ^ too high to wire.  One in six active players every week is a "
            "weather report, not a signal.  See this module's docstring.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
