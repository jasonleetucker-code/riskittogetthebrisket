"""Private multi-team War Room fixtures — REAL ``/api/trade/analyze-multi``
bodies (N-team spec §3.1), for Lane B's component tests.

Each scenario runs the production engine
(``analyze_service.analyze_trade_n`` -> ``analyze_service.multi_team_payload``,
the exact assembly the route serves) and adds the route's per-request stamps
in their real shape (``record_decision`` receipt ids are ``null`` — what the
route publishes when the box-local log cannot be written — and a fixed
``tradeRunId``; timing is omitted).  Boards:

* the newest COMPLETE archived scrape (real dynasty_main rosters, values and
  picks; ``tests/trade/multi_team_support.real_board``) for the 3- and 4-team
  scenarios, routed from a recorded 3-team own-league trade's structure;
* the LABELLED synthetic league for states the archive cannot pin (a forced
  cut, stale rosters, an unpriced asset).

Seams pinned so a fixture is machine-independent, all LABELLED: posture (a
synthetic window through the REAL posture owner), league-scored projections
(a synthetic per-game table derived from board value), the points model, the
NFL season and positional scarcity — the same seams as
``tests/trade/war_room_ui_payloads.py``.

Because the real board moves with every valuation change, the committed files
are checked by SHAPE (``test_multi_team_ui_fixtures.py``), not byte for byte.
Regenerate::

    python -m tests.trade.multi_team_ui_payloads
"""

from __future__ import annotations

import contextlib
import json
import random
import sys
from pathlib import Path
from unittest import mock

from src.league_intel.sim_calibration import DEFAULT_POINTS_MODEL
from src.roster_intel import best_ball_utility as bbu
from src.trade import analyze_service as svc
from src.trade import trade_ledger as tl
from tests.trade import multi_team_support as mts
from tests.trade.war_room_ui_payloads import _synthetic_posture

OUT_DIR = (
    Path(__file__).resolve().parents[2] / "frontend" / "__tests__" / "fixtures" / "trade-multi"
)


def _ppg_from_board(snap):
    """LABELLED synthetic league-scored projections: board value / 400."""

    def ppg(ids, season, scoring_settings):
        out = {}
        for i in ids:
            row = snap.rows_by_player_id.get(str(i))
            v = (row or {}).get("rankDerivedValue")
            if isinstance(v, (int, float)) and v > 0:
                out[i] = round(float(v) / 400.0, 1)
        return out, {
            "state": "available",
            "source": "SYNTHETIC_FIXTURE_PROJECTIONS",
            "horizon": "PRESEASON_FULL_SEASON",
            "description": "labelled synthetic per-game table (board value / 400)",
            "season": season,
            "families": ["synthetic"],
        }

    return ppg


@contextlib.contextmanager
def _seams(snap):
    with (
        mock.patch.object(bbu, "league_scored_ppg_by_id", _ppg_from_board(snap)),
        mock.patch.object(bbu, "load_points_model", lambda: DEFAULT_POINTS_MODEL),
        mock.patch.object(bbu, "DEFAULT_DRAWS", 200),
        mock.patch("src.bdvm.actuals.current_nfl_season", lambda today=None: 2026),
        mock.patch(
            "src.trade.roster_capacity._league_scarcity",
            lambda league_key, contract: (
                None,
                "positional scarcity not used in this fixture (LABELLED) — multiplier inert",
            ),
        ),
    ):
        yield


def _posture(*_a, **_k):
    return _synthetic_posture()


def _real():
    contract, snap, label = mts.real_board()
    return contract, snap, label


def _scenario_three_team_team_context():
    _c, snap, label = _real()
    replay = mts.structure_replays(snap, sides=3)[0]
    return (
        snap,
        replay["teams"],
        replay["legs"],
        "team_context",
        label,
        (
            "A recorded 3-team own-league trade's routing on today's archived rosters, "
            "Team Context ON (synthetic posture + projections, LABELLED)."
        ),
    )


def _scenario_three_team_asset_only():
    snap, teams, legs, _m, label, _d = _scenario_three_team_team_context()
    return (
        snap,
        teams,
        legs,
        "asset_only",
        label,
        "The same 3-team trade with Use Team Context OFF.",
    )


def _scenario_four_team_asset_only():
    _c, snap, label = _real()

    # The first seeded ledger in which every team gets a definite market
    # answer (no unpriced / quarantined / stale asset), so the fixture shows four
    # real per-team results.  Deterministic search over a fixed seed range.
    for seed in range(20261020, 20261220):
        teams, legs = mts.random_ledger(snap, random.Random(seed), n_teams=4, max_per_team=2)
        ledger = tl.validate_ledger(snap, teams=teams, legs=legs, policy=tl.private_policy())
        probe = svc.analyze_trade_n(snap, ledger, mode="market_fairness", counterfactuals=False)
        if all(t["fairness"]["state"] != "UNABLE" for t in probe["teams"].values()):
            break
    return (
        snap,
        teams,
        legs,
        "asset_only",
        label,
        ("A seeded 4-team routed trade of priced players and owned picks on the archived board."),
    )


def _scenario_three_team_forced_cut():
    contract = mts.synthetic_league()
    settings = {**mts.SYNTH_SETTINGS, "rosterSize": 5}
    snap = tl.build_trade_snapshot(
        contract, league_key=mts.SYNTH_KEY, roster_settings=settings, now=mts.PINNED_NOW
    )
    legs = [
        {"id": "p:101", "from": 1, "to": 2},
        {"id": "p:102", "from": 1, "to": 2},
        {"id": "p:104", "from": 1, "to": 2},
        {"id": "p:201", "from": 2, "to": 1},
        {"id": "p:401", "from": 4, "to": 1},
        {"id": "p:103", "from": 1, "to": 4},
    ]
    return (
        snap,
        [1, 2, 4],
        legs,
        "team_context",
        "synthetic",
        (
            "LABELLED synthetic league with a 5-man cap: team B receives three for one and "
            "must release a player (forced drop from its post-trade roster)."
        ),
    )


def _scenario_three_team_stale_rosters():
    snap = mts.synthetic_snapshot(roster_source="last_good")
    legs = [
        {"id": "p:101", "from": 1, "to": 2},
        {"id": "p:102", "from": 1, "to": 3},
        {"id": "p:201", "from": 2, "to": 1},
        {"id": "p:301", "from": 3, "to": 1},
    ]
    return (
        snap,
        [1, 2, 3],
        legs,
        "team_context",
        "synthetic",
        (
            "Spec I14 routing on restored (stale) rosters: ownership cannot be proven, so "
            "every team is Unavailable and market fairness is UNABLE."
        ),
    )


def _scenario_three_team_unpriced_asset():
    snap = mts.synthetic_snapshot()
    legs = [
        {"id": "p:105", "from": 1, "to": 2},
        {"id": "p:201", "from": 2, "to": 3},
        {"id": "p:301", "from": 3, "to": 1},
    ]
    return (
        snap,
        [1, 2, 3],
        legs,
        "asset_only",
        "synthetic",
        (
            "A 3-team cycle carrying a rostered player the board does not price: the two "
            "teams it touches are UNABLE (asset_not_evaluable), never priced at 0."
        ),
    )


SCENARIOS = {
    "three-team-team-context": _scenario_three_team_team_context,
    "three-team-asset-only": _scenario_three_team_asset_only,
    "four-team-asset-only": _scenario_four_team_asset_only,
    "three-team-forced-cut": _scenario_three_team_forced_cut,
    "three-team-stale-rosters": _scenario_three_team_stale_rosters,
    "three-team-unpriced-asset": _scenario_three_team_unpriced_asset,
}


def build(name: str) -> dict:
    snap, teams, legs, mode, board, description = SCENARIOS[name]()
    ledger = tl.validate_ledger(snap, teams=teams, legs=legs, policy=tl.private_policy())
    with _seams(snap):
        result = svc.analyze_trade_n(
            snap,
            ledger,
            mode=mode,
            counterfactuals=True,
            posture_resolver=_posture if mode == "team_context" else None,
        )
    body = svc.multi_team_payload(
        result,
        snap=snap,
        ledger=ledger,
        league_key=snap.league_key,
        perspective=ledger.teams[0],
        expected_generation=None,
    )
    for t in body["teams"]:
        t["analysis"]["decisionRunId"] = None
    body["decisionRunIds"] = {str(t["rosterId"]): None for t in body["teams"]}
    body["tradeRunId"] = "fixture"
    body["valuationMode"] = "market"
    payload = json.loads(json.dumps(body, default=list))
    payload["_fixture"] = {
        "scenario": name,
        "description": description,
        "board": board,
        "generator": "tests/trade/multi_team_ui_payloads.py",
        "request": {"teams": teams, "assets": legs, "useTeamContext": mode == "team_context"},
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
