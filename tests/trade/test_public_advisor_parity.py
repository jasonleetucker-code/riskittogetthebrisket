"""Brisket Trade Advisor ⇄ private War Room parity (design §11 group A).

The advisor must evaluate a 2-team trade with the SAME engine the private
"Final decision" War Room uses.  These tests send the same trade through:

* the private route ``POST /api/trade/analyze`` (authenticated, Team Context
  on, names + ``pickAssetIds`` exactly as the War Room sends them), and
* ``public_advisor._evaluate_trade_internal`` (the public path's internals),

with the posture and projection seams fixed once so both see identical
inputs, and assert the decision is identical — headline, graded leaning,
deciding component, component A/B, confidence and the named evidence gaps —
and that the public category is the mapping of that decision.  The only
permitted difference is ``whatWouldChange`` (the public path skips the
counterfactual search; it runs after everything compared here).

``test_public_advisor_archive_parity.py`` repeats the comparison on a REAL
board.  Parity pins the DEFAULT board — no
``customValue``, no ``siteWeights``, no TE slider (the War Room ignores those
too).
"""

from __future__ import annotations

from typing import Any

import pytest

import server
from src.trade import public_advisor
from src.trade import trade_decision as td
from tests.api import trade_advisor_support as S
from tests.api.trade_advisor_support import (  # noqa: F401 — pytest fixtures, used by name
    advisor_app_fixture,
    advisor_client_fixture,
)

COMPARED = ("headline", "leaning", "deciding", "components", "confidence", "primaryReason")

SHAPES: dict[str, list[tuple[str, int, int]]] = {
    "1-for-1 offense": [("p:103", 1, 2), ("p:202", 2, 1)],
    "premium for several": [("p:201", 2, 1), ("p:103", 1, 2), ("p:102", 1, 2)],
    "many for many": [("p:101", 1, 2), ("p:104", 1, 2), ("p:201", 2, 1), ("p:203", 2, 1)],
    "IDP only": [("p:104", 1, 2), ("p:203", 2, 1)],
    "mixed offense and defense": [("p:103", 1, 2), ("p:105", 1, 2), ("p:201", 2, 1)],
    "players for picks": [("p:103", 1, 2), ("pick:main:2027:r1:o2", 2, 1)],
    "picks for players": [("pick:main:2027:r1:o1", 1, 2), ("p:202", 2, 1)],
    "mixed packages": [
        ("pick:main:2027:r2:o2", 1, 2),
        ("p:102", 1, 2),
        ("p:204", 2, 1),
        ("pick:main:2028:r1:o2", 2, 1),
    ],
    "value adjustment applies": [("p:102", 1, 2), ("p:105", 1, 2), ("p:201", 2, 1)],
    "unpriced kicker": [("p:205", 2, 1), ("p:102", 1, 2)],
}


def _private_body(contract: dict[str, Any], legs, perspective: int) -> dict[str, Any]:
    teams = {t["roster_id"]: t for t in contract["sleeper"]["teams"]}
    rows = {r.get("playerId"): r for r in contract["playersArray"] if r.get("playerId")}
    details = {d["assetId"]: d for t in teams.values() for d in (t.get("pickDetails") or [])}
    body: dict[str, Any] = {
        "leagueKey": "main",
        "team": teams[perspective]["ownerId"],
        "playersIn": [],
        "playersOut": [],
        "picksIn": [],
        "picksOut": [],
        "pickAssetIdsIn": [],
        "pickAssetIdsOut": [],
    }
    for aid, _frm, to in legs:
        incoming = to == perspective
        if aid.startswith("p:"):
            body["playersIn" if incoming else "playersOut"].append(rows[aid[2:]]["displayName"])
        else:
            body["picksIn" if incoming else "picksOut"].append(details[aid]["label"])
            body["pickAssetIdsIn" if incoming else "pickAssetIdsOut"].append(aid)
    return body


@pytest.fixture
def private_session(monkeypatch):
    from src.trade import comparable_trades as ct

    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    monkeypatch.setattr(
        server, "_get_auth_session", lambda request: {"username": "t", "sleeper_user_id": ""}
    )
    monkeypatch.setattr(
        ct, "comparable_trades", lambda *a, **k: {"state": "unavailable", "reason": "test"}
    )


def _public_internal(contract, legs, perspective):
    from src.api import public_trade_advisor_api as api

    snap = api._snapshot_for(contract, "main")
    trade = public_advisor.validate_trade(
        snap, perspective=perspective, teams=[1, 2], legs=list(legs)
    )
    return public_advisor._evaluate_trade_internal(snap, trade)


@pytest.mark.parametrize("perspective", [1, 2])
@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_public_decision_equals_the_private_war_room(
    advisor_client,
    private_session,
    shape,
    perspective,
):
    contract = server.latest_contract_data
    legs = SHAPES[shape]
    res = advisor_client.post("/api/trade/analyze", json=_private_body(contract, legs, perspective))
    assert res.status_code == 200, res.text
    private = res.json()["analysis"]["decision"]
    result, internals = _public_internal(contract, legs, perspective)
    if "analysis" not in internals:
        # The adapter refused before the engine (no board row): the private
        # engine must agree the trade cannot be decided.
        assert private["headline"] == "NOT_ENOUGH_EVIDENCE", shape
        assert result.category == "UNAVAILABLE"
        return
    public = internals["analysis"]["decision"]
    for key in COMPARED:
        assert public[key] == private[key], (shape, perspective, key)
    assert [g["code"] for g in public["missingEvidence"]] == [
        g["code"] for g in private["missingEvidence"]
    ]
    if public["headline"] != "NOT_ENOUGH_EVIDENCE" and public["deciding"] != "executionGate":
        assert public["whatWouldChange"] == []  # the counterfactual search did not run
    assert result.category == td.public_category_from_decision(private)
    # And the public HTTP answer is that category.
    body = S.two_team_body(*legs, perspective=perspective)
    out = advisor_client.post(S.ANALYZE, json=body).json()
    assert out["category"] == result.category


def test_the_shapes_cover_more_than_one_category(advisor_client):
    cats = set()
    for legs in SHAPES.values():
        for p in (1, 2):
            cats.add(
                advisor_client.post(S.ANALYZE, json=S.two_team_body(*legs, perspective=p)).json()[
                    "category"
                ]
            )
    assert len(cats) >= 3, cats


def test_perspective_reversal_never_gives_both_sides_a_strong_win(advisor_client):
    for shape, legs in SHAPES.items():
        a = advisor_client.post(S.ANALYZE, json=S.two_team_body(*legs, perspective=1)).json()
        b = advisor_client.post(S.ANALYZE, json=S.two_team_body(*legs, perspective=2)).json()
        assert not (
            a["category"] == "STRONGLY_FAVORABLE" and b["category"] == "STRONGLY_FAVORABLE"
        ), shape
