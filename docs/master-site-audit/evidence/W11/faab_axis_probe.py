"""W11 evidence — FAAB recommender axis sensitivity probe.

Read-only.  Calls ``src.trade.faab_recommender.recommend_faab`` directly
with the exact inputs ``server.py::post_waiver_faab_recommend`` assembles
for the live ``dynasty_main`` league, then sweeps one axis at a time.

Run from the repo root::

    .venv/bin/python docs/master-site-audit/evidence/W11/faab_axis_probe.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))

from src.api import faab_analytics  # noqa: E402
from src.public_league import snapshot_store  # noqa: E402
from src.trade.faab_recommender import recommend_faab  # noqa: E402

SNAP = snapshot_store.load_snapshot()
SUMMARY = faab_analytics.summarize_league_faab(SNAP) if SNAP is not None else None

# Live board values measured from GET /api/data on 2026-08-04.
TOP_FA_POOL = 1908.0  # Marlin Klein, best unrostered player
CASES = {
    "Josh Allen (board #1)": 9988.0,
    "Josh Jacobs (#109)": 3859.0,
    "Jaylen Warren (#176)": 2937.0,
    "J.K. Dobbins (#209)": 2660.0,
    "Marlin Klein (top FA, #325)": 1908.0,
    "AJ Dillon (unpriced)": 0.0,
}


def base(value: float, **over: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "add_player_value": value,
        "add_player_position": "RB",
        "add_player_name": "probe",
        "league_faab_summary": SUMMARY,
        "league_budget": 100,
        "top_value_in_pool": TOP_FA_POOL,
    }
    kwargs.update(over)
    return kwargs


def main() -> None:
    out: dict[str, object] = {}

    out["budgetSweep"] = {
        str(rem): {
            name: recommend_faab(**base(v, team_faab_remaining=rem))["standard"]
            for name, v in CASES.items()
        }
        for rem in (100, 50, 20, 5, 1, 0)
    }

    out["dropSideSweep"] = {
        str(drop): recommend_faab(**base(3859.0, drop_player_value=drop))["standard"]
        for drop in (0, 500, 2000, 3858, 3859, 5000)
    }

    out["trendingSweep"] = {
        str(c): recommend_faab(**base(3859.0, sleeper_trending={"count": c}))["standard"]
        for c in (0, 999, 1000, 5000, 10000, 100000)
    }

    out["positionSweep"] = {
        pos: recommend_faab(**base(0.0, add_player_position=pos))["standard"]
        for pos in ("QB", "RB", "WR", "TE", "DL", "LB", "DB", "K")
    }

    out["contentionSweep"] = {
        str(clearing): recommend_faab(
            **base(
                3859.0,
                contention={"clearing": clearing, "topRival": clearing - 1},
                next_best_fa_value=0.0,
            )
        )["standard"]
        for clearing in (10, 40, 60, 90, 200)
    }

    out["noAnalytics"] = {
        name: recommend_faab(**base(v, league_faab_summary=None))["standard"]
        for name, v in CASES.items()
    }

    print(json.dumps(out, indent=1))
    dest = REPO / "docs/master-site-audit/evidence/W11/axis-sweep.json"
    dest.write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
