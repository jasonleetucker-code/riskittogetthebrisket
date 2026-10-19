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

import contextlib
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
    "partial-long-term": (
        ["WR Buf Star"],
        ["WR Kc"],
        [],
        [],
        True,
        True,
        "Long-term value strategy, incoming player unprojected: the roster lens abstains "
        "and the decision stands on trade value (the abstention is not an evidence gap).",
    ),
    "roster-unmeasured": (
        ["WR Buf Star"],
        ["WR Kc", "WR Phi"],
        [],
        [],
        True,
        True,
        "The consolidation trade with the roster-capacity check raising (LABELLED failure "
        "injection): the simulator's own failure shapes -- rosterCapacity "
        "{'unavailable': 'KeyError'} and rosterUtility roster_capacity_unavailable.",
    ),
    "roster-error": (
        ["WR Buf Star"],
        ["WR Kc", "WR Phi"],
        [],
        [],
        True,
        True,
        "The consolidation trade with the roster simulation raising (LABELLED failure "
        "injection): the simulator's own error:<Exception> reason reaches the packet.",
    ),
    "strategy-cut-no": (
        ["WR Buf Star", "RB Buf Depth"],
        ["WR Kc"],
        [],
        [],
        True,
        True,
        "Long-term strategy on a full 8/8 roster of valuable players (LABELLED synthetic "
        "values): +value before the forced cut, -value after it, lineup much stronger -- "
        "the strategy decides NO.",
    ),
    "superflex-holes": (
        ["WR Buf Star"],
        ["WR Kc", "WR Phi"],
        [],
        [],
        True,
        True,
        "The consolidation trade in a LABELLED superflex / IDP lineup the 7-man roster "
        "cannot fill: real lineupHoles with repeated and flex slot codes.",
    ),
    "ktc-rollback": (
        ["WR Buf Star"],
        ["WR Kc", "WR Phi"],
        [],
        [],
        True,
        True,
        "The consolidation trade with the KTC package model active (the config rollback "
        "path, LABELLED): its own packageModel label reaches the packet.",
    ),
    "outgoing-not-held": (
        ["WR Buf Star"],
        ["RB Buf Depth"],
        [],
        [],
        True,
        True,
        "Sending a player this roster does not hold: the capacity owner's " "'free no spot' note.",
    ),
    "comparables-formats": (
        ["WR Buf Star"],
        ["WR Kc", "WR Phi"],
        [],
        [],
        True,
        True,
        "The consolidation trade with four LABELLED synthetic comparable trades, one per "
        "format disposition; each reason line is written by the real "
        "comparable_trades._reasons.",
    ),
    "over-limit": (
        ["WR Buf Star"],
        ["WR Kc"],
        [],
        [],
        True,
        True,
        "A 9-man roster against the 8-man limit (LABELLED): the capacity owner's "
        "'already over the limit' note.",
    ),
}

#: Per-scenario extras, kept out of the tuple so existing scenarios are unchanged:
#: ``team_goal`` -- the user's strategy override (``teamGoal``);
#: ``unprojected`` -- PPG keys withheld from the projection seam;
#: ``raise_in`` -- functions made to raise ``KeyError`` (a LABELLED failure
#: injection): the simulator's own exception handling writes whatever it
#: writes, so the packet carries the REAL failure shapes, never hand-typed ones.
SCENARIO_OPTIONS: dict[str, dict] = {
    "partial-long-term": {"team_goal": "LONG_TERM", "unprojected": ("wr buf star",)},
    # `simulate_trade` -> rosterCapacity {"unavailable": "KeyError", ...}, and
    # with no capacity, rosterUtility "roster_capacity_unavailable".
    "roster-unmeasured": {"raise_in": ("src.trade.roster_capacity.assess_roster_capacity",)},
    # `simulate_trade` -> rosterUtility "error:KeyError".
    "roster-error": {"raise_in": ("src.trade.roster_capacity.evaluate_final_roster_utility",)},
    "strategy-cut-no": {"team_goal": "LONG_TERM", "contract_edit": "full_valuable_roster"},
    "superflex-holes": {
        "starters": {
            "QB": 1,
            "RB": 3,
            "WR": 4,
            "SUPER_FLEX": 2,
            "WR_RB_FLEX": 1,
            "DB": 2,
            "IDP_FLEX": 1,
        }
    },
    "ktc-rollback": {"package_model": "ktc_2026_04"},
    "over-limit": {"contract_edit": "over_limit_roster"},
    "comparables-formats": {"comparables": "one_per_disposition"},
}


def _comparables_one_per_disposition() -> dict:
    """A comparables payload in `comparable_trades.comparable_trades`' shape
    (LABELLED synthetic trades) whose reason lines come from the REAL
    `comparable_trades._reasons`, one trade per format disposition."""
    from src.trade import comparable_trades as ct
    from src.trade import market_trade_reference as ref

    star = {"kind": "player", "label": "WR Buf Star"}
    faab = {"kind": "faab", "faabAmount": 5}
    kc = {"kind": "player", "label": "WR Kc"}
    trades = []
    # The lens shows the first three; VALIDATED_TRANSFORMABLE, which no
    # translator produces today (TARGET_FORMAT_CENSUS.md), is the one left out.
    dispositions = (
        "NATIVE_COMPARABLE",
        "BROAD_CONTEXT",
        "TARGET_UNSUPPORTED",
        "VALIDATED_TRANSFORMABLE",
    )
    for i, disposition in enumerate(dispositions):
        reasons = ct._reasons(
            align={
                "sameDirection": [(star, ref.MATCH_EXACT), (faab, ref.MATCH_EXACT)],
                "oppositeDirection": [(kc, ref.MATCH_EXACT)] if i == 2 else [],
                "a": 0,
                "b": 1,
            },
            names={},
            size_a=1,
            size_b=2,
            sides=[[star], [kc, faab]],
            topology=1.0 if i % 2 == 0 else 0.5,
            fmt_state=ct.FORMAT_KNOWN,
            disposition=disposition,
            age=i * 9,
        )
        trades.append(
            {
                "occurredDate": f"2026-09-0{i + 1}",
                "comparability": {"score": round(0.9 - i * 0.1, 2), "reasons": reasons},
                "formatMatch": {"disposition": disposition, "appliesToThisLeague": True},
                "sourceFamilies": ["synthetic"],
                "sides": None,
            }
        )
    return {
        "state": "ok",
        "trades": trades,
        "candidates": len(trades),
        "belowMinScore": 0,
        "scanCapped": False,
        "since": "2026-07-01",
        "methodology": {"status": "PROVISIONAL"},
    }


_COMPARABLES = {"one_per_disposition": _comparables_one_per_disposition}


def _full_valuable_roster(contract: dict) -> dict:
    """LABELLED synthetic values: an 8/8 roster with no cheap bench player, so
    the forced cut releases real value (3,000) and the package value turns
    negative after it."""
    from tests.api.test_trade_nfl_exposure import _row

    values = {"WR Kc": 8000.0, "WR Phi": 3000.0, "TE Free": 3000.0, "RB Buf Depth": 3300.0}
    for r in contract["playersArray"]:
        if r["displayName"] in values:
            r["rankDerivedValue"] = values[r["displayName"]]
            r["values"] = {"full": values[r["displayName"]]}
    contract["playersArray"] += [
        _row("RB Bench One", 3000.0, "RB", "NYJ"),
        _row("WR Bench Two", 3100.0, "WR", "NYJ"),
        _row("TE Bench Three", 3200.0, "TE", "NYJ"),
    ]
    us = contract["sleeper"]["teams"][0]
    us["players"] = [
        "QB Min",
        "RB Min",
        "WR Kc",
        "WR Phi",
        "TE Free",
        "RB Bench One",
        "WR Bench Two",
        "TE Bench Three",
    ]
    us["playerIds"] = [n.lower() for n in us["players"]]
    return contract


def _over_limit_roster(contract: dict) -> dict:
    """LABELLED: two more priced players on the 7-man roster -> 9 of 8."""
    from tests.api.test_trade_nfl_exposure import _row

    contract["playersArray"] += [
        _row("RB Bench One", 1500.0, "RB", "NYJ"),
        _row("WR Bench Two", 1400.0, "WR", "NYJ"),
    ]
    us = contract["sleeper"]["teams"][0]
    us["players"] = [*us["players"], "RB Bench One", "WR Bench Two"]
    us["playerIds"] = [n.lower() for n in us["players"]]
    return contract


_CONTRACT_EDITS = {
    "full_valuable_roster": _full_valuable_roster,
    "over_limit_roster": _over_limit_roster,
}


def _raise_keyerror(*_args, **_kwargs):
    raise KeyError("LABELLED failure injection (tests/trade/war_room_ui_payloads.py)")


def _ppg(ids, season, scoring_settings, *, unprojected=()):
    return (
        {i: PPG[i.lower()] for i in ids if i.lower() in PPG and i.lower() not in unprojected},
        {
            "state": "available",
            "source": "SYNTHETIC_FIXTURE_PROJECTIONS",
            "horizon": "PRESEASON_FULL_SEASON",
            "description": "labelled synthetic per-game table (tests/trade/war_room_ui_payloads.py)",
            "season": season,
            "families": ["synthetic"],
        },
    )


def _synthetic_posture() -> dict:
    """The REAL posture owner on a LABELLED synthetic window.

    The route resolves posture from the league bundle (machine data); the
    fixture pins a strong, mid-age roster in the offseason so the UI renders
    the owner's genuine output shape.
    """
    from src.roster_intel.window import (
        CompetitiveWindow,
        WindowInputs,
        _softmax_affinities,
        competitive_posture,
        season_timing,
    )

    aff = _softmax_affinities(0.85, 0.5, 0.18)
    window = CompetitiveWindow(
        aff, WindowInputs(0.85, 0.5, "championshipOdds", 8), max(aff, key=aff.get)
    )
    block = competitive_posture(
        window, season_timing(None, False, 13), own_first_round_pick_held=True
    ).to_dict()
    block["notes"] = [*block["notes"], "SYNTHETIC_FIXTURE_WINDOW (LABELLED)"]
    return {"available": True, **block}


def build(name: str) -> dict:
    players_in, players_out, picks_in, picks_out, context, with_team, description = SCENARIOS[name]
    options = SCENARIO_OPTIONS.get(name, {})
    unprojected = tuple(options.get("unprojected", ()))
    contract = _contract(league_key="main")
    if options.get("contract_edit"):
        contract = _CONTRACT_EDITS[options["contract_edit"]](contract)
    settings = dict(_SETTINGS)
    if options.get("starters"):
        settings["starters"] = dict(options["starters"])
    with contextlib.ExitStack() as injected:
        for target in options.get("raise_in", ()):
            injected.enter_context(mock.patch(target, _raise_keyerror))
        if options.get("package_model"):
            pinned = {"active": options["package_model"], "shadow": []}
            injected.enter_context(
                mock.patch("src.valuation_math.package_model._config", lambda: pinned)
            )
        result = _simulate(
            contract,
            players_in,
            players_out,
            picks_in,
            picks_out,
            context,
            with_team,
            unprojected,
            settings,
        )
        result["leagueKey"] = "main"
        result["teamContext"] = {"applied": context, "mode": "team" if context else "asset_only"}
        comparables = _COMPARABLES[options["comparables"]]() if options.get("comparables") else None
        result["analysis"] = analyze_trade(result, comparables, team_goal=options.get("team_goal"))
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
    if options.get("team_goal"):
        payload["_fixture"]["teamGoal"] = options["team_goal"]
    return payload


def _simulate(
    contract,
    players_in,
    players_out,
    picks_in,
    picks_out,
    context,
    with_team,
    unprojected,
    settings=_SETTINGS,
):
    with (
        mock.patch.object(
            bbu,
            "league_scored_ppg_by_id",
            lambda ids, season, scoring_settings: _ppg(
                ids, season, scoring_settings, unprojected=unprojected
            ),
        ),
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
            roster_settings=settings,
            league_key="main",
            include_roster_utility=context,
            competitive_posture=_synthetic_posture() if with_team else None,
        )
    return result


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
