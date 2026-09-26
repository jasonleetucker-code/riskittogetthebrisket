"""Trade War Room UI fixtures — REAL ``/api/trade/analyze`` payloads.

The War Room component renders the analyze packet verbatim, so its tests must
read what the backend actually emits.  This module runs the production path —
``src.api.trade_simulator.simulate_trade(include_roster_utility=True)`` then
``src.trade.analyze_trade.analyze_trade`` — over the synthetic league of
``tests/api/test_trade_nfl_exposure`` (8-man cap, 7 rostered), with two seams
pinned so the output is deterministic everywhere:

* projections: a LABELLED SYNTHETIC per-game table (``PPG``) at the
  projection-basis seam (no production projection snapshot is committed);
* weekly variance: the documented fallback ``PointsModel`` constants;
* positional scarcity (cut-cost multiplier): inert, labelled in the notes.

``test_war_room_ui_fixtures.py`` regenerates every scenario and requires byte
equality, so a backend change the UI reads fails there until the fixtures
are regenerated::

    python -m tests.trade.war_room_ui_payloads
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

from src.api import trade_simulator
from src.league_intel.sim_calibration import DEFAULT_POINTS_MODEL
from src.roster_intel import best_ball_utility as bbu
from src.trade.analyze_trade import analyze_trade
from tests.api.test_trade_nfl_exposure import _SETTINGS, _contract, _us

OUT_DIR = (
    Path(__file__).resolve().parents[2] / "frontend" / "__tests__" / "fixtures" / "trade-war-room"
)

#: LABELLED SYNTHETIC per-game projections (points, exact league scoring).
PPG = {
    "qb min": 20.0,
    "rb min": 12.0,
    "wr kc": 13.0,
    "wr phi": 9.0,
    "te free": 6.0,
    "wr buf star": 19.0,
    "rb buf depth": 4.0,
}

#: name -> (players_in, players_out, picks_in, picks_out, team_context, with_team, description)
SCENARIOS: dict[str, tuple] = {
    "consolidation": (
        ["WR Buf Star"],
        ["WR Kc", "WR Phi"],
        [],
        [],
        True,
        True,
        "2-for-1: two part-time WRs for one every-week WR; fits (7/8 -> 6/8).",
    ),
    "forced-cut": (
        ["WR Buf Star", "RB Buf Depth"],
        [],
        [],
        ["2027 Round 1"],
        True,
        True,
        "Two players for a pick on a 7/8 roster: picks free no spot, one cut required.",
    ),
    "asset-only": (
        ["WR Buf Star"],
        ["WR Kc", "WR Phi"],
        [],
        [],
        False,
        True,
        "The consolidation trade with Use Team Context OFF (Asset-Only).",
    ),
    "partial-coverage": (
        ["WR Buf Star"],
        ["RB Unpriced"],
        [],
        [],
        True,
        True,
        "A traded player with no projection: the roster lens abstains.",
    ),
}


def _ppg(ids, season, scoring_settings):
    return (
        {i: PPG[i.lower()] for i in ids if i.lower() in PPG},
        {
            "state": "available",
            "source": "SYNTHETIC_FIXTURE_PROJECTIONS",
            "horizon": "PRESEASON_FULL_SEASON",
            "description": "labelled synthetic per-game table (tests/trade/war_room_ui_payloads.py)",
            "season": season,
            "families": ["synthetic"],
        },
    )


def build(name: str) -> dict:
    players_in, players_out, picks_in, picks_out, context, with_team, description = SCENARIOS[name]
    contract = _contract(league_key="main")
    with (
        mock.patch.object(bbu, "league_scored_ppg_by_id", _ppg),
        mock.patch.object(bbu, "load_points_model", lambda: DEFAULT_POINTS_MODEL),
        mock.patch("src.bdvm.actuals.current_nfl_season", lambda today=None: 2026),
        # Positional scarcity comes from the gameplan bundle, which depends on
        # the machine's registry and ROS data — pinned inert and labelled.
        mock.patch(
            "src.trade.roster_capacity._league_scarcity",
            lambda league_key, contract: (
                None,
                "positional scarcity not used in this fixture (LABELLED) — multiplier inert",
            ),
        ),
    ):
        result = trade_simulator.simulate_trade(
            contract,
            resolved_team=_us(contract) if with_team else None,
            players_in=players_in,
            players_out=players_out,
            picks_in=picks_in,
            picks_out=picks_out,
            roster_settings=_SETTINGS,
            league_key="main",
            include_roster_utility=context,
        )
    result["leagueKey"] = "main"
    result["teamContext"] = {"applied": context, "mode": "team" if context else "asset_only"}
    result["analysis"] = analyze_trade(result)
    payload = json.loads(json.dumps(result, default=list))
    payload["_fixture"] = {
        "scenario": name,
        "description": description,
        "generator": "tests/trade/war_room_ui_payloads.py",
        "request": {
            "teamName": "Us",
            "playersIn": players_in,
            "playersOut": players_out,
            "picksIn": picks_in,
            "picksOut": picks_out,
            "useTeamContext": context,
        },
    }
    return payload


def fixture_path(name: str) -> Path:
    return OUT_DIR / f"{name}.json"


def serialize(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, indent=1) + "\n"


def main(argv: list[str] | None = None) -> int:
    names = (argv if argv else None) or list(SCENARIOS)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name in names:
        fixture_path(name).write_text(serialize(build(name)), encoding="utf-8")
        print(f"wrote {fixture_path(name)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
