"""Trade Simulator NFL-team exposure before/after (C2-EXP-01, #786).

The manifest's acceptance evidence for this unit is a **non-influence
test**: exposure is descriptive context on the simulate payload and must not
move the trade's value, equity, team impact, roster capacity, final-roster
simulation or Analyze Trade verdict.  That is proven three ways below —
byte-identical outputs with the block present vs absent, byte-identical
outputs when every NFL team on the board is perturbed (the exposure input
changes, nothing else may), and a structural guard that nothing in the
trade chain reads the block back.

The rest pins the issue's own test list: coherent shares, the exact
post-transaction roster, proportional movement, explicit missing values and
picks never assigned to a franchise.
"""

from __future__ import annotations

import copy
import json
import pathlib

import pytest
from fastapi.testclient import TestClient

import server
from src.api import terminal, trade_simulator
from src.api.roster_intelligence import build_league_roster_intelligence, trade_nfl_exposure
from src.trade.analyze_trade import analyze_trade
from tests.api.test_league_routing import two_league_registry  # noqa: F401 — fixture

REPO = pathlib.Path(__file__).resolve().parents[2]

_SETTINGS = {
    "teamCount": 12,
    "rosterSize": 8,
    "taxiSize": 0,
    "starters": {"QB": 1, "RB": 1, "WR": 1, "FLEX": 1},
}


def _row(name, value, pos, team):
    return {
        "displayName": name,
        "canonicalName": name,
        "assetClass": "offense",
        "position": pos,
        "pos": pos,
        "team": team,
        "rankDerivedValue": value,
        "values": {"full": value} if value else {},
    }


def _contract(*, league_key=None):
    rows = [
        _row("QB Min", 6000.0, "QB", "MIN"),
        _row("RB Min", 3000.0, "RB", "MIN"),
        _row("WR Kc", 4000.0, "WR", "KC"),
        _row("WR Phi", 2000.0, "WR", "PHI"),
        _row("TE Free", 500.0, "TE", "FA"),
        # Rostered, on the board, but unpriced: never weighted, never zero.
        _row("RB Unpriced", None, "RB", "DAL"),
        # Incoming targets.
        _row("WR Buf Star", 7000.0, "WR", "BUF"),
        _row("RB Buf Depth", 300.0, "RB", "BUF"),
        # A pick row: must never be joined as a player.
        {
            "displayName": "2027 Round 1",
            "canonicalName": "2027 Round 1",
            "assetClass": "pick",
            "pos": "PICK",
            "rankDerivedValue": 3500.0,
            "values": {"full": 3500.0},
        },
    ]
    roster = ["QB Min", "RB Min", "WR Kc", "WR Phi", "TE Free", "RB Unpriced", "Ghost Player"]
    us = {
        "ownerId": "o1",
        "name": "Us",
        "roster_id": 1,
        "players": roster,
        "playerIds": [n.lower() for n in roster],
        "picks": ["2027 Round 1"],
    }
    them = {
        "ownerId": "o2",
        "name": "Them",
        "roster_id": 2,
        "players": ["WR Buf Star", "RB Buf Depth"],
        "playerIds": ["wr buf star", "rb buf depth"],
        "picks": [],
    }
    contract = {"playersArray": rows, "sleeper": {"teams": [us, them]}}
    if league_key:
        contract["meta"] = {"leagueKey": league_key}
    return contract


def _us(contract):
    return terminal.resolve_team(contract, owner_id="o1", name=None)


def _exposure(contract, *, players_in=(), players_out=()):
    return trade_nfl_exposure(
        contract,
        roster_players=_us(contract)["players"],
        players_in=list(players_in),
        players_out=list(players_out),
    )


def _simulate(contract, *, players_in, players_out, picks_out=()):
    return trade_simulator.simulate_trade(
        contract,
        resolved_team=_us(contract),
        players_in=list(players_in),
        players_out=list(players_out),
        picks_out=list(picks_out),
        roster_settings=_SETTINGS,
        league_key=None,
    )


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


# ══ Non-influence — the manifest's acceptance evidence ═════════════

_TRADE = {"players_in": ["WR Buf Star"], "players_out": ["WR Kc"], "picks_out": ["2027 Round 1"]}


def test_value_and_grade_outputs_are_byte_identical_with_and_without_exposure():
    contract = _contract()
    without = _simulate(contract, **_TRADE)
    without_bytes = _canon(without)
    analysis_without = _canon(analyze_trade(copy.deepcopy(without)))

    block = _exposure(contract, players_in=_TRADE["players_in"], players_out=_TRADE["players_out"])
    with_block = {**copy.deepcopy(without), "nflExposure": block}

    assert block["moved"], "fixture must actually move exposure"
    # Every non-exposure field — value delta, equity, team impact, roster
    # capacity, final legal roster — is byte-identical.
    assert _canon({k: v for k, v in with_block.items() if k != "nflExposure"}) == without_bytes
    # And the verdict layered on top does not see it.
    assert _canon(analyze_trade(with_block)) == analysis_without
    # Computing exposure mutated neither the simulation nor the contract.
    assert _canon(without) == without_bytes
    assert _canon(contract) == _canon(_contract())


def test_perturbing_every_nfl_team_moves_exposure_and_nothing_else():
    """The exposure INPUT changes; if any grade/value path read it, this fails."""
    base = _contract()
    moved = _contract()
    for row in moved["playersArray"]:
        if row.get("assetClass") != "pick":
            row["team"] = "NYJ"

    sim_base = _simulate(base, **_TRADE)
    sim_moved = _simulate(moved, **_TRADE)
    assert _canon(sim_base) == _canon(sim_moved)
    assert _canon(analyze_trade(sim_base)) == _canon(analyze_trade(sim_moved))

    exp_base = _exposure(base, players_in=["WR Buf Star"], players_out=["WR Kc"])
    exp_moved = _exposure(moved, players_in=["WR Buf Star"], players_out=["WR Kc"])
    assert _canon(exp_base) != _canon(exp_moved)


def test_nothing_in_the_trade_chain_reads_the_exposure_block():
    """Structural half: the grade/value modules never name the block."""
    readers = []
    paths = [*(REPO / "src/trade").rglob("*.py"), REPO / "src/api/trade_simulator.py"]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if "nflExposure" in text or "roster_intel.exposure" in text:
            readers.append(path.relative_to(REPO).as_posix())
    assert readers == []


def test_the_block_carries_no_flag_verdict_or_penalty():
    blob = repr(_exposure(_contract(), players_in=["WR Buf Star"], players_out=["WR Kc"])).lower()
    for banned in (
        "flag",
        "verdict",
        "grade",
        "penalty",
        "recommend",
        "warning",
        "concentrationrisk",
        "overexposed",
    ):
        assert banned not in blob, banned


# ══ The issue's own test list ══════════════════════════════════════


def test_before_is_the_roster_intelligence_full_roster_population():
    """One population, one answer: the simulator's BEFORE is what
    ``/api/roster/intelligence`` reports for the same roster."""
    contract = _contract()
    league = build_league_roster_intelligence(contract)
    team = next(t for t in league["teams"].values() if t["teamName"] == "Us")
    assert _exposure(contract)["before"] == team["nflExposure"]["fullRoster"]


def test_value_weighted_shares_are_coherent():
    out = _exposure(_contract(), players_in=["WR Buf Star"], players_out=["WR Kc"])
    for side in ("before", "after"):
        shares = [b["share"] for b in out[side]["buckets"]]
        assert sum(shares) == pytest.approx(100.0, abs=0.01)
    # Priced placeable roster: 6000+3000+4000+2000+500 = 15500; MIN = 9000.
    before = {b["team"]: b for b in out["before"]["buckets"]}
    assert out["before"]["pricedValue"] == 15500.0
    assert before["MIN"]["share"] == pytest.approx(100 * 9000 / 15500, abs=1e-3)


def test_after_is_the_exact_post_transaction_roster():
    out = _exposure(_contract(), players_in=["WR Buf Star"], players_out=["WR Kc"])
    after = {b["team"]: b for b in out["after"]["buckets"]}
    assert "KC" not in after  # the only KC player left
    assert after["BUF"]["playerIds"] == ["WR Buf Star"]
    assert out["after"]["pricedValue"] == 15500.0 - 4000.0 + 7000.0
    changes = {c["team"]: c for c in out["changes"]}
    # An exited franchise is as visible as an entered one.
    assert changes["KC"]["shareAfter"] == 0.0 and changes["KC"]["delta"] < 0
    assert changes["BUF"]["shareBefore"] == 0.0 and changes["BUF"]["delta"] > 0


def test_high_value_acquisition_moves_exposure_more_than_low_value():
    star = _exposure(_contract(), players_in=["WR Buf Star"])
    depth = _exposure(_contract(), players_in=["RB Buf Depth"])
    star_buf = next(c for c in star["changes"] if c["team"] == "BUF")["delta"]
    depth_buf = next(c for c in depth["changes"] if c["team"] == "BUF")["delta"]
    assert star_buf > depth_buf > 0
    assert star_buf == pytest.approx(100 * 7000 / (15500 + 7000), abs=1e-3)
    assert depth_buf == pytest.approx(100 * 300 / (15500 + 300), abs=1e-3)


def test_missing_values_are_explicit_never_zero():
    out = _exposure(_contract(), players_in=["Nobody Known"])
    # On the board but unpriced, and not on the board at all: both unpriced.
    assert set(out["before"]["unpricedIds"]) == {"RB Unpriced", "Ghost Player"}
    assert set(out["after"]["unpricedIds"]) == {"RB Unpriced", "Ghost Player", "Nobody Known"}
    # They add nothing to the denominator — the priced value is unchanged.
    assert out["after"]["pricedValue"] == out["before"]["pricedValue"]
    assert out["moved"] == []


def test_picks_are_never_assigned_to_an_nfl_team():
    out = _exposure(_contract(), players_in=["WR Buf Star"])
    ids = {
        pid for side in ("before", "after") for b in out[side]["buckets"] for pid in b["playerIds"]
    }
    assert "2027 Round 1" not in ids
    # Even a pick label passed where a player belongs never joins a pick row
    # (pick rows are excluded from the join), so it gets no team and no share.
    misrouted = _exposure(_contract(), players_in=["2027 Round 1"])
    assert "2027 Round 1" in misrouted["after"]["unpricedIds"]
    assert misrouted["moved"] == []


def test_free_agents_are_not_a_franchise():
    out = _exposure(_contract())
    fa = next(b for b in out["before"]["buckets"] if b["team"] == "FA")
    assert fa["isFranchise"] is False


def test_an_outgoing_player_not_on_the_roster_frees_nothing_and_is_reported():
    out = _exposure(_contract(), players_out=["WR Buf Star"])
    assert out["outgoingNotOnRoster"] == ["WR Buf Star"]
    assert out["moved"] == []


def test_names_join_case_insensitively_like_the_simulator():
    lower = _exposure(_contract(), players_in=["wr buf star"], players_out=["wr kc"])
    exact = _exposure(_contract(), players_in=["WR Buf Star"], players_out=["WR Kc"])
    assert lower == exact


def test_block_names_its_scope_and_scale():
    out = _exposure(_contract())
    assert out["scope"] == "full_roster"
    assert out["before"]["scope"] == "full_roster"
    assert out["valueScale"] == "rankDerivedValue"
    assert out["descriptiveOnly"] is True


# ══ Endpoint wiring ════════════════════════════════════════════════


def _session(_request):
    return {"username": "alice", "auth_method": "sleeper", "sleeper_user_id": "o1"}


def _post(monkeypatch, path, body):
    with TestClient(server.app, raise_server_exceptions=True) as client:
        monkeypatch.setattr(server, "latest_contract_data", _contract(league_key="main"))
        monkeypatch.setattr(server, "_get_auth_session", _session)
        return client.post(path, json=body)


_BODY = {"leagueKey": "main", "team": "o1", "playersIn": ["WR Buf Star"], "playersOut": ["WR Kc"]}


def test_simulate_endpoint_attaches_the_exposure_block(two_league_registry, monkeypatch):  # noqa: F811
    res = _post(monkeypatch, "/api/trade/simulate", _BODY)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["nflExposure"]["scope"] == "full_roster"
    assert {c["team"] for c in body["nflExposure"]["moved"]} >= {"KC", "BUF"}


def test_analyze_endpoint_verdict_ignores_the_exposure_block(two_league_registry, monkeypatch):  # noqa: F811
    res = _post(monkeypatch, "/api/trade/analyze", _BODY)
    assert res.status_code == 200, res.text
    body = res.json()
    assert "nflExposure" in body
    stripped = {k: v for k, v in body.items() if k not in ("nflExposure", "analysis")}
    assert _canon(analyze_trade(stripped)) == _canon(body["analysis"])


def test_simulate_endpoint_degrades_when_exposure_fails(two_league_registry, monkeypatch):  # noqa: F811
    def boom(*_a, **_k):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(server._roster_intelligence, "trade_nfl_exposure", boom)
    res = _post(monkeypatch, "/api/trade/simulate", _BODY)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["nflExposure"]["unavailable"] == "RuntimeError"
    assert "equity" in body and "delta" in body
