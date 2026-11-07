"""CW-40 P1 re-audit, batch t1 -- regression tests for findings that
re-verified CLOSED on current main.

    W08-F002 / F003 / F004 / F005 / F007   frontend/__tests__/audit-cw40-batch-t1.test.js
    W09-F001  suggestions: roster analysed whole, empty answers explained
    W09-F002  finder: package shapes are not all 1-for-2
    W09-F003  finder: picks reach generated trades (posture-aware, Team Context ON)
    W09-F004  suggestions: DB eligibility through the positional floor
    W09-F005  Monte Carlo: no 9999 clamp bias; synthetic band is labelled
    W09-F006  withdrawn valuation lens: no value moves, mode stamped market

Record: docs/audits/remediation_2026-11-06/CW40_P1_BATCH_t1.md

Boards come from the tracked export archive via
``tests.archive_fixtures.newest_complete_contract`` -- never the network.
Assertions are invariants, not absolute counts over the live board.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from src.trade import monte_carlo
from src.trade.valuation_scope import WITHDRAWN_NOTE, scoped_contract
from tests.api.test_league_routing import (  # noqa: F401  (fixture re-use)
    _install_contract_for_league,
    two_league_registry,
)
from tests.archive_fixtures import newest_complete_contract

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def board():
    contract, name = newest_complete_contract()
    if contract is None:
        pytest.skip("no complete archived board available")
    teams = (contract.get("sleeper") or {}).get("teams") or []
    if len(teams) < 4:
        pytest.skip("archived board carries no league rosters")
    return contract


# --------------------------------------------------------------- W09-F001 / F004


@pytest.fixture(scope="module")
def suggestion_runs(board):
    from src.trade.suggestions import (
        _apply_board_top_n_filter,
        build_asset_pool_from_contract,
        generate_suggestions_from_pool,
    )

    full = build_asset_pool_from_contract(board, ktc_top_n=0)
    pool = _apply_board_top_n_filter(list(full), 150)
    # dynasty_main's demand (the registry is isolated under pytest, so it is
    # stated here exactly as tests/trade/test_suggestions_coverage... does).
    needs = {"QB": 2, "RB": 3, "WR": 4, "TE": 2, "DL": 3, "LB": 3, "DB": 3}
    teams = board["sleeper"]["teams"]
    runs = []
    for t in teams:
        res = generate_suggestions_from_pool(
            roster_names=list(t["players"]),
            pool=pool,
            league_rosters=None,
            starter_needs=needs,
            ktc_top_n=150,
            roster_pool=full,
            team_count=len(teams),
        )
        runs.append((t["name"], res))
    return runs, pool


def test_w09_f001_every_roster_is_analysed_whole_not_through_the_top_150(suggestion_runs):
    runs, _pool = suggestion_runs
    for name, res in runs:
        meta = res["metadata"]
        assert meta["rosterAnalysisPool"] == "full_board", name
        # The audit measured 3-21 of 44-58 matched (5-36%).
        assert meta["rosterMatched"] >= 0.8 * meta["rosterProvided"], (name, meta)
        # Whatever did not match is NAMED, not silently dropped.
        assert len(meta["rosterUnpriced"]) >= meta["rosterProvided"] - meta["rosterMatched"] - 1


def test_w09_f001_an_empty_answer_always_carries_its_reason(suggestion_runs):
    runs, _pool = suggestion_runs
    for name, res in runs:
        if res["totalSuggestions"] == 0:
            assert res["metadata"].get("noResultReason"), name
            assert res["metadata"].get("noResultLabel"), name
            assert "generatorDiagnostics" in res["metadata"], name


def test_w09_f004_dbs_enter_the_pool_through_the_positional_floor(suggestion_runs):
    runs, pool = suggestion_runs
    # On the audited board the global top-150 held zero DBs; the floor is what
    # admits them, and it says so.
    floors = [res["metadata"]["positionalFloor"] for _n, res in runs]
    assert all(f["applied"] for f in floors)
    top150_db = sum(1 for p in pool if p.position == "DB")
    added_db = floors[0]["addedByPosition"].get("DB", 0)
    assert added_db > 0, "no DB admitted by the positional floor"
    assert top150_db + added_db >= 12, "fewer DBs than one team's starter demand"
    # the engine's own diagnostic sees the demanded DB position
    assert runs[0][1]["metadata"]["starterNeeds"]["DB"] == 3


# --------------------------------------------------------------------- W09-F002 / F003


def _finder(board, team, *, ctx, postures=None, max_results=100000):
    from src.trade.finder import find_trades

    teams = board["sleeper"]["teams"]
    return find_trades(
        players=board["players"],
        my_team=team,
        opponent_teams=[t["name"] for t in teams if t["name"] != team],
        sleeper_teams=teams,
        contract=board,
        use_team_context=ctx,
        postures=postures,
        max_results=max_results,
    )


def _shape(tc):
    return (len(tc["give"]), len(tc["receive"]))


def test_w09_f002_finder_returns_more_than_one_package_shape(board):
    team = (
        next(t["name"] for t in board["sleeper"]["teams"] if t["name"] == "Jason")
        if any(t["name"] == "Jason" for t in board["sleeper"]["teams"])
        else board["sleeper"]["teams"][0]["name"]
    )
    res = _finder(board, team, ctx=False)
    trades = res["trades"]
    assert trades, "finder returned nothing"
    shapes = [_shape(t) for t in trades]
    # Audited defect: every returned trade was 1-for-2; 1-for-1 ranked 2,159th and
    # 2-for-1 never qualified.
    assert {(1, 1), (2, 1)} <= set(shapes), Counter(shapes)
    # What a user actually sees (the default page of results) is not one shape.
    assert len(set(shapes[:40])) >= 2, Counter(shapes[:40])
    assert shapes.index((1, 1)) < 40


def test_w09_f003_picks_reach_generated_trades_under_team_context(board):
    teams = board["sleeper"]["teams"]
    me = max(teams, key=lambda t: len(t.get("pickDetails") or []))["name"]
    postures = {t["name"]: "RETOOL" for t in teams}
    postures[me] = "PUSH"
    res = _finder(board, me, ctx=True, postures=postures)
    gen = res["metadata"]["pickGeneration"]
    assert gen["applied"] is True
    if not (gen.get("myOwnedPicks") or {}).get("priced"):
        pytest.skip("requesting team owns no priced picks on this archived board")
    with_pick = [
        t
        for t in res["trades"]
        if any(a.get("position") == "PICK" for a in t["give"] + t["receive"])
    ]
    assert with_pick, "no pick-inclusive trade was returned for a PUSH->RETOOL pair"
    assert gen["pickInclusiveReturned"] == len(with_pick)
    for t in with_pick:
        picks = [a for a in t["give"] + t["receive"] if a.get("position") == "PICK"]
        assert all(p.get("assetId", "").startswith("pick:") for p in picks)
        assert "posture_aware_pick" in t["flags"]


def test_w09_f003_picks_stay_out_when_no_posture_pair_exists(board):
    me = board["sleeper"]["teams"][0]["name"]
    res = _finder(board, me, ctx=True, postures=None, max_results=200)
    assert res["metadata"]["pickGeneration"]["applied"] is False
    assert not any(
        a.get("position") == "PICK" for t in res["trades"] for a in t["give"] + t["receive"]
    )


# --------------------------------------------------------------------------- W09-F005


def _sim_mean(value: int) -> float:
    elite = monte_carlo.build_trade_player(
        {"name": "Elite", "team": "AAA", "pos": "TE", "rankDerivedValue": value}
    )
    anchor = monte_carlo.build_trade_player(
        {"name": "Anchor", "team": "BBB", "pos": "WR", "rankDerivedValue": 5000}
    )
    res = monte_carlo.simulate_trade([elite], [anchor], n_sims=20000, seed=7)
    return res.side_a_mean


def test_w09_f005_top_of_board_asset_is_not_biased_down_by_a_9999_clamp(board):
    top = max(
        int(r["rankDerivedValue"])
        for r in board["playersArray"]
        if isinstance(r.get("rankDerivedValue"), (int, float))
    )
    assert top > 9000
    mean = _sim_mean(top)
    # The audited bias was -5.07% (9947 simulated at 9441.9).  An unbiased
    # symmetric band has E[draw] == p50 up to sampling error.
    assert abs(mean - top) / top < 0.01, (top, mean)


def test_w09_f005_the_flat_band_is_labelled_synthetic():
    elite = monte_carlo.build_trade_player(
        {"name": "E", "team": "A", "pos": "QB", "rankDerivedValue": 8000}
    )
    other = monte_carlo.build_trade_player(
        {"name": "O", "team": "B", "pos": "QB", "rankDerivedValue": 7000}
    )
    out = monte_carlo.simulate_trade([elite], [other], n_sims=500, seed=1).to_dict()
    assert out["bandSources"] == {monte_carlo.BAND_SOURCE_SYNTHETIC: 2}
    assert "synthesized" in out["disclaimer"]


# --------------------------------------------------------------------------- W09-F006


def test_w09_f006_the_withdrawn_lens_serves_the_same_board_and_says_so(board):
    same, mode, note = scoped_contract(board, "leagueAdjusted")
    assert same is board
    assert (mode, note) == ("market", WITHDRAWN_NOTE)
    plain, mode2, note2 = scoped_contract(board, "market")
    assert plain is board and (mode2, note2) == ("market", None)


def test_w09_f006_no_engine_reads_a_second_offense_only_board(board):
    assert not any("offenseOnlyRankDerivedValue" in r for r in board["playersArray"])
    for rel in (
        "src/trade/finder.py",
        "src/trade/suggestions.py",
        "src/api/trade_simulator.py",
        "src/league_intel/overlay.py",
    ):
        assert "offenseOnlyRankDerivedValue" not in (REPO / rel).read_text(encoding="utf-8"), rel


@pytest.mark.usefixtures("two_league_registry")
def test_w09_f006_simulate_route_values_and_stamp_are_lens_invariant(monkeypatch):
    """The audited all-offense trade, through the real route."""
    rows = [
        {
            "displayName": n,
            "canonicalName": n,
            "legacyRef": n,
            "assetClass": "offense",
            "position": p,
            "pos": p,
            "rankDerivedValue": v,
            "values": {"full": v},
            "canonicalConsensusRank": i + 1,
        }
        for i, (n, p, v) in enumerate(
            [("Bowers", "TE", 9950), ("Taylor", "RB", 7482), ("Mahomes", "QB", 6472)]
        )
    ]
    answers = {}
    with TestClient(server.app, raise_server_exceptions=True) as c:
        stub = _install_contract_for_league(monkeypatch, "main")
        stub["playersArray"] = rows
        stub["sleeper"]["teams"] = [
            {"ownerId": "oA", "name": "Team A", "roster_id": 1, "players": ["Bowers"], "picks": []},
            {
                "ownerId": "oB",
                "name": "Team B",
                "roster_id": 2,
                "players": ["Taylor", "Mahomes"],
                "picks": [],
            },
        ]
        monkeypatch.setattr(
            server, "_get_auth_session", lambda r: {"username": "t", "sleeper_user_id": "oA"}
        )
        for mode in ("market", "leagueAdjusted"):
            res = c.post(
                "/api/trade/simulate",
                json={
                    "leagueKey": "main",
                    "teamName": "Team A",
                    "playersIn": ["Taylor", "Mahomes"],
                    "playersOut": ["Bowers"],
                    "valuationMode": mode,
                },
            )
            assert res.status_code == 200, res.text
            answers[mode] = res.json()
    m, a = answers["market"], answers["leagueAdjusted"]
    assert a["valuationMode"] == "market"
    assert a.get("valuationNote") == WITHDRAWN_NOTE
    assert m["valuationMode"] == "market"
    for side in ("sending", "receiving"):
        assert {x["name"]: x["value"] for x in m[side]} == {x["name"]: x["value"] for x in a[side]}
    assert json.dumps(m.get("equity"), sort_keys=True) == json.dumps(
        a.get("equity"), sort_keys=True
    )
