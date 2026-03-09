#!/usr/bin/env python
"""Build historical scoring translation dataset for 2023-2025.

Preferred data source: nfl-data-py weekly dataset.
Output: data/scoring_history_nfl_data_py_2023_2025.csv
"""

from __future__ import annotations

import json
import os
from typing import Dict

import pandas as pd


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
OUT_PATH = os.path.join(DATA_DIR, "scoring_history_nfl_data_py_2023_2025.csv")


NFL_COLS: Dict[str, str] = {
    "pass_yd": "passing_yards",
    "pass_td": "passing_tds",
    "pass_int": "interceptions",
    "pass_cmp": "completions",
    "pass_inc": "incompletions",
    "pass_fd": "passing_first_downs",
    "rush_yd": "rushing_yards",
    "rush_td": "rushing_tds",
    "rush_fd": "rushing_first_downs",
    "rec": "receptions",
    "rec_yd": "receiving_yards",
    "rec_td": "receiving_tds",
    "rec_fd": "receiving_first_downs",
    "fum_lost": "fumbles_lost",
}


def _load_scoring_map(path: str) -> Dict[str, float]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    scoring_map = payload.get("scoring_map", {}) if isinstance(payload, dict) else {}
    return {str(k): float(v) for k, v in (scoring_map or {}).items() if isinstance(v, (int, float))}


def _score_row(row: pd.Series, scoring_map: Dict[str, float]) -> float:
    pts = 0.0
    for key, wt in scoring_map.items():
        col = NFL_COLS.get(key)
        if not col:
            continue
        val = row.get(col, 0.0)
        try:
            pts += float(val or 0.0) * float(wt)
        except Exception:
            continue
    return pts


def main() -> int:
    os.makedirs(DATA_DIR, exist_ok=True)
    custom_cfg_path = os.path.join(DATA_DIR, "custom_scoring_config.json")
    baseline_cfg_path = os.path.join(DATA_DIR, "baseline_scoring_config.json")
    custom_map = _load_scoring_map(custom_cfg_path)
    baseline_map = _load_scoring_map(baseline_cfg_path)
    if not custom_map or not baseline_map:
        print("[history] Missing scoring config files. Run scraper first (non-fatal).")
        return 0

    try:
        import nfl_data_py as nfl
    except Exception:
        print("[history] nfl_data_py is not installed; skipping nfl-data-py dataset build.")
        return 0

    df = nfl.import_weekly_data([2023, 2024, 2025], downcast=True)
    if df is None or df.empty:
        print("[history] nfl_data_py returned no data.")
        return 1

    needed = [
        "season",
        "week",
        "player_id",
        "player_name",
        "position",
        "recent_team",
    ]
    keep = [c for c in needed if c in df.columns]
    out = df[keep].copy()

    for canonical, col in NFL_COLS.items():
        out[canonical] = df[col].fillna(0.0) if col in df.columns else 0.0

    out["baseline_points"] = out.apply(lambda r: _score_row(r, baseline_map), axis=1)
    out["league_points"] = out.apply(lambda r: _score_row(r, custom_map), axis=1)
    out["raw_scoring_delta"] = out["league_points"] - out["baseline_points"]
    out["raw_scoring_ratio"] = out["league_points"] / out["baseline_points"].clip(lower=1.0)
    out["td_dependency"] = (
        (out["pass_td"] + out["rush_td"] + out["rec_td"])
        / (out["pass_yd"] + out["rush_yd"] + out["rec_yd"]).clip(lower=1.0)
    )
    out["first_down_sensitivity"] = out["pass_fd"] + out["rush_fd"] + out["rec_fd"]
    out["reception_profile"] = out["rec"] / (out["rec"] + out.get("rush_att", 0.0)).clip(lower=1.0)

    out.to_csv(OUT_PATH, index=False)
    print(f"[history] Wrote {OUT_PATH} ({len(out)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
