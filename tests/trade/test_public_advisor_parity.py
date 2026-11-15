"""Brisket Trade Advisor ⇄ private engine parity (directive §10 / §11; spec I11).

The public answer is a REDUCTION of the same shared N-team engine result the
private calculator reads — never a second evaluation.  For the same contract
and ledger, from every perspective, these tests assert:

* public per-team ``result`` == the private ``/api/trade/analyze-multi``
  team's ``fairness.state`` (FAIR / NOT_FAIR / UNABLE), in BOTH private modes
  (Team Context on and off — fairness is the gross market band, so it is the
  same quantity in every mode, spec §2.8);
* public ``overall`` == the private ``summary.fairnessOverall``;
* at N = 2, FAIR == the market band the existing 2-team ``/api/trade/analyze``
  route classifies (``lenses.market.detail.band.level == "fair"``) for each
  side;
* public ``unavailableAssetIds`` are exactly the private team's unpriced /
  unverifiable legs.

The private multi-team flag is forced ON here regardless of its production
default (spec §6.1); the public product does not depend on it.
"""

from __future__ import annotations

from typing import Any

import pytest

import server
from src.trade import analyze_service, public_advisor
from tests.api import trade_advisor_support as S
from tests.api.trade_advisor_support import (  # noqa: F401 — pytest fixtures, used by name
    advisor_app_fixture,
    advisor_client_fixture,
)

_PUBLIC = {"FAIR": "FAIR", "NOT_FAIR": "NOT_FAIR", "UNABLE": "UNABLE_TO_DETERMINE"}

SHAPES: dict[str, tuple[list[tuple[str, int, int]], tuple[int, ...]]] = {
    "2: fair 1-for-1 IDP": (S.FAIR_TWO, (1, 3)),
    "2: elite swap": (S.NOT_FAIR_TWO, (1, 2)),
    "2: consolidation (VA applies)": ([("p:102", 1, 2), ("p:105", 1, 2), ("p:201", 2, 1)], (1, 2)),
    "2: players for picks": ([("p:103", 1, 2), ("pick:main:2027:r1:o2", 2, 1)], (1, 2)),
    "2: mixed packages": (
        [
            ("pick:main:2027:r2:o2", 1, 2),
            ("p:102", 1, 2),
            ("p:204", 2, 1),
            ("pick:main:2028:r1:o2", 2, 1),
        ],
        (1, 2),
    ),
    "2: unpriced kicker": ([("p:205", 2, 1), ("p:102", 1, 2)], (1, 2)),
    "2: off-board ghost": ([("p:9999", 1, 2), ("p:202", 2, 1)], (1, 2)),
    "3: circular fair": (S.FAIR_THREE, (1, 3, 4)),
    "3: circular elite": ([("p:101", 1, 2), ("p:201", 2, 3), ("p:301", 3, 1)], (1, 2, 3)),
    "3: one sender, two destinations": (
        [("p:101", 1, 2), ("p:102", 1, 3), ("p:201", 2, 1), ("p:302", 3, 1)],
        (1, 2, 3),
    ),
    "4: two disjoint pairs": (S.MIXED_FOUR, (1, 2, 3, 4)),
    "4: picks-only cycle": (
        [
            ("pick:main:2027:r1:o1", 1, 2),
            ("pick:main:2027:r1:o2", 2, 3),
            ("pick:main:2027:r1:o3", 3, 4),
            ("pick:main:2027:r1:o4", 4, 1),
        ],
        (1, 2, 3, 4),
    ),
    "4: offense + IDP + picks": (
        [
            ("p:101", 1, 2),
            ("p:104", 1, 3),
            ("p:201", 2, 4),
            ("p:203", 2, 1),
            ("p:301", 3, 1),
            ("pick:main:2028:r1:o4", 4, 3),
            ("p:403", 4, 2),
        ],
        (1, 2, 3, 4),
    ),
}


@pytest.fixture
def private_session(monkeypatch):
    from src.api import feature_flags
    from src.trade import comparable_trades as ct

    monkeypatch.setenv("RISKIT_FEATURE_TRADE_MULTI_TEAM_ANALYSIS", "1")
    feature_flags.reload()
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    monkeypatch.setattr(
        server, "_get_auth_session", lambda request: {"username": "t", "sleeper_user_id": ""}
    )
    monkeypatch.setattr(
        ct, "comparable_trades", lambda *a, **k: {"state": "unavailable", "reason": "test"}
    )
    yield
    monkeypatch.delenv("RISKIT_FEATURE_TRADE_MULTI_TEAM_ANALYSIS")
    feature_flags.reload()


def _private(client, legs, teams, *, team_context: bool) -> dict[str, Any]:
    res = client.post(
        "/api/trade/analyze-multi",
        json={
            "leagueKey": "main",
            "teams": list(teams),
            "assets": [{"id": a, "from": f, "to": t} for a, f, t in legs],
            "useTeamContext": team_context,
            "counterfactuals": False,
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


def _public(client, legs, teams, perspective) -> dict[str, Any]:
    res = client.post(S.ANALYZE, json=S.trade_body(*legs, teams=teams, perspective=perspective))
    assert res.status_code == 200, res.text
    return res.json()


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_public_fairness_equals_the_private_engine_from_every_perspective(
    advisor_client, private_session, shape
):
    legs, teams = SHAPES[shape]
    privates = [_private(advisor_client, legs, teams, team_context=tc) for tc in (True, False)]
    for perspective in teams:
        public = _public(advisor_client, legs, teams, perspective)
        assert public["teamCount"] == len(teams)
        for private in privates:
            by_rid = {t["rosterId"]: t for t in private["teams"]}
            for row in public["teams"]:
                fairness = by_rid[row["rosterId"]]["fairness"]
                assert row["result"] == _PUBLIC[fairness["state"]], (shape, row["rosterId"])
                assert row["reasonCode"] == fairness["reasonCode"], (shape, row["rosterId"])
            overall = private["summary"]["fairnessOverall"]
            assert public["overall"]["result"] == _PUBLIC[overall["state"]], shape
            assert public["overall"]["reasonCode"] == overall["reasonCode"], shape


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_unavailable_ids_are_the_private_teams_own_unpriced_or_unverifiable_legs(
    advisor_client, private_session, shape
):
    legs, teams = SHAPES[shape]
    private = _private(advisor_client, legs, teams, team_context=False)
    public = _public(advisor_client, legs, teams, teams[0])
    by_rid = {t["rosterId"]: t for t in private["teams"]}
    for row in public["teams"]:
        t = by_rid[row["rosterId"]]
        reason = t["fairness"]["reasonCode"]
        if reason == "asset_not_evaluable":
            expected = sorted(
                r["assetId"]
                for r in [*t["gives"], *t["receives"]]
                if r["valueState"] in ("unpriced", "off_board")
            )
        elif reason == "ownership_unverifiable":
            expected = sorted(set(t["unverifiableAssetIds"]))
        else:
            expected = []
        assert row["unavailableAssetIds"] == expected, (shape, row["rosterId"])


@pytest.mark.parametrize("shape", sorted(k for k in SHAPES if k.startswith("2:")))
def test_two_team_fair_equals_the_existing_war_room_market_band(
    advisor_client, private_session, shape
):
    """N = 2: the public verdict is the gross market band the existing
    ``/api/trade/analyze`` route classifies for each side — no new rule."""
    legs, teams = SHAPES[shape]
    contract = server.latest_contract_data
    by_rid = {t["roster_id"]: t for t in contract["sleeper"]["teams"]}
    rows = {r.get("playerId"): r for r in contract["playersArray"] if r.get("playerId")}
    details = {d["assetId"]: d for t in by_rid.values() for d in (t.get("pickDetails") or [])}
    public = _public(advisor_client, legs, teams, teams[0])
    for row in public["teams"]:
        me = row["rosterId"]
        body: dict[str, Any] = {
            "leagueKey": "main",
            "team": by_rid[me]["ownerId"],
            "playersIn": [],
            "playersOut": [],
            "playerIdsIn": [],
            "playerIdsOut": [],
            "picksIn": [],
            "picksOut": [],
            "pickAssetIdsIn": [],
            "pickAssetIdsOut": [],
        }
        for aid, _f, to in legs:
            inc = to == me
            if aid.startswith("p:"):
                pid = aid[2:]
                name = rows[pid]["displayName"] if pid in rows else S.GHOST_NAME
                body["playersIn" if inc else "playersOut"].append(name)
                body["playerIdsIn" if inc else "playerIdsOut"].append(pid)
            else:
                body["picksIn" if inc else "picksOut"].append(details[aid]["label"])
                body["pickAssetIdsIn" if inc else "pickAssetIdsOut"].append(aid)
        res = advisor_client.post("/api/trade/analyze", json=body)
        assert res.status_code == 200, res.text
        analysis = res.json()["analysis"]
        market = analysis["lenses"]["market"]
        if row["result"] == "UNABLE_TO_DETERMINE":
            assert analysis["decision"]["headline"] in ("NOT_ENOUGH_EVIDENCE", "NO"), shape
            continue
        level = market["detail"]["band"]["level"]
        assert (row["result"] == "FAIR") == (level == "fair"), (shape, me, level)


def test_the_shapes_cover_every_public_result(advisor_client):
    seen = set()
    for legs, teams in SHAPES.values():
        out = _public(advisor_client, legs, teams, teams[0])
        seen |= {t["result"] for t in out["teams"]}
        seen.add(out["overall"]["result"])
    assert seen == {"FAIR", "NOT_FAIR", "UNABLE_TO_DETERMINE"}


def test_two_team_states_are_always_equal(advisor_client):
    """I18: at N = 2 both teams' states are equal (UNABLE included), so the
    overall equals each team's state."""
    for legs, teams in SHAPES.values():
        if len(teams) != 2:
            continue
        out = _public(advisor_client, legs, teams, teams[0])
        a, b = out["teams"]
        assert a["result"] == b["result"] == out["overall"]["result"]


def test_public_and_private_read_one_snapshot(advisor_client, private_session):
    """R7: both routes obtain their snapshot through ``trade_ledger.snapshot_for``
    with the same arguments, so one memo entry serves both."""
    from src.trade import trade_ledger

    trade_ledger.clear_snapshot_memo()
    legs, teams = SHAPES["3: circular fair"]
    _public(advisor_client, legs, teams, teams[0])
    _private(advisor_client, legs, teams, team_context=False)
    assert len(trade_ledger._MEMO) == 1


def test_evaluate_is_the_reduction_of_analyze_trade_n(advisor_client, monkeypatch):
    """The public evaluation runs the engine exactly once, in market_fairness
    mode with counterfactuals off, and nothing else."""
    calls = []
    real = analyze_service.analyze_trade_n

    def spy(snap, ledger, **kw):
        calls.append(kw)
        return real(snap, ledger, **kw)

    monkeypatch.setattr(analyze_service, "analyze_trade_n", spy)
    legs, teams = SHAPES["4: two disjoint pairs"]
    _public(advisor_client, legs, teams, 2)
    assert calls == [{"mode": "market_fairness", "counterfactuals": False}]
    snap = public_advisor.snapshot(server.latest_contract_data, league_key="main")
    assert snap.team_count == 4
