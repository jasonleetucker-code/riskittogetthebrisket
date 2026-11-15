"""``manager_scout.offer_evidence`` — descriptive counts, never a probability."""

from __future__ import annotations

from src.intel import manager_scout as ms


def _scout(*, trades=4, state="measured"):
    trading = {
        "state": state,
        "sampleSize": trades,
        "tradeCount": trades,
        "window": {"seasons": ["2025", "2026"]},
        "received": {
            "assets": 9,
            "players": 7,
            "picks": 2,
            "byPosition": {"RB": 3, "WR": 2, "DE": 1, "UNRESOLVED": 1},
        },
        "packageShape": {"consolidating": 1, "expanding": 2, "even": 1},
        "partners": [{"ownerId": "me", "trades": 2}, {"ownerId": "x", "trades": 1}],
    }
    return {
        "managers": [
            {"ownerId": "opp", "tradeTendencies": trading},
            {"ownerId": "me", "tradeTendencies": {"state": "insufficient_sample", "tradeCount": 0}},
        ]
    }


def _ev(scout, recv, send, opp="opp", me="me"):
    return ms.offer_evidence(
        scout,
        opponent_owner_id=opp,
        requester_owner_id=me,
        they_receive=recv,
        they_send=send,
    )


RB = {"name": "a", "position": "RB", "isPick": False}
DL = {"name": "b", "position": "DL", "isPick": False}
TE = {"name": "c", "position": "TE", "isPick": False}
PICK = {"name": "2027 Round 1", "position": "PICK", "isPick": True}


def test_counts_what_they_received_by_offered_position_with_its_sample():
    ev = _ev(_scout(), [RB, DL, TE], [RB])
    assert ev["state"] == "measured"
    assert ev["basis"] == ms.OFFER_EVIDENCE_BASIS
    pos = {p["position"]: p for p in ev["positionsTheyWouldReceive"]}
    assert pos["RB"]["receivedBefore"] == 3
    # Positions are compared in the canonical family: DE history counts as DL.
    assert pos["DL"]["receivedBefore"] == 1
    # A position never received is a real zero count over a real sample.
    assert pos["TE"]["receivedBefore"] == 0
    assert {p["ofPlayersReceived"] for p in pos.values()} == {7}
    assert ev["unresolvedPositionReceived"] == 1
    assert ev["tradesWithRequester"] == 2


def test_shape_is_structural_from_the_opponents_side():
    # They receive three, send one -> expanding for them.
    ev = _ev(_scout(), [RB, DL, TE], [RB])
    assert ev["offerShapeForThem"] == "expanding"
    assert ev["sameShapeBefore"] == 2
    ev = _ev(_scout(), [RB], [RB, DL])
    assert ev["offerShapeForThem"] == "consolidating"
    assert ev["sameShapeBefore"] == 1


def test_picks_reported_only_when_the_package_sends_them_picks():
    assert _ev(_scout(), [RB], [RB])["picksTheyWouldReceive"] is None
    ev = _ev(_scout(), [RB, PICK], [RB])
    assert ev["picksTheyWouldReceive"] == {
        "offeredToThem": 1,
        "receivedBefore": 2,
        "ofAssetsReceived": 9,
    }
    assert "PICK" not in {p["position"] for p in ev["positionsTheyWouldReceive"]}


def test_no_trades_is_insufficient_not_zero_percent():
    ev = _ev(_scout(), [RB], [RB], opp="me", me="opp")
    assert ev["state"] == "insufficient_sample"
    assert ev["sampleSize"] == 0
    assert "positionsTheyWouldReceive" not in ev


def test_every_missing_input_is_an_explained_unavailable_state():
    assert _ev(None, [RB], [RB])["reason"] == "manager_scout_unavailable"
    assert _ev(_scout(), [RB], [RB], opp="")["reason"] == "opponent_owner_unresolved"
    assert _ev(_scout(), [RB], [RB], opp="ghost")["reason"] == "opponent_profile_missing"
    down = {
        "managers": [
            {
                "ownerId": "opp",
                "tradeTendencies": {"state": "unavailable", "reason": "acquisition_store_missing"},
            }
        ]
    }
    ev = _ev(down, [RB], [RB])
    assert (ev["state"], ev["reason"]) == ("unavailable", "acquisition_store_missing")


def test_unknown_requester_is_none_not_zero_trades_together():
    assert _ev(_scout(), [RB], [RB], me="")["tradesWithRequester"] is None
    assert _ev(_scout(), [RB], [RB], me="stranger")["tradesWithRequester"] == 0


def test_carries_no_label_threshold_or_probability_field():
    ev = _ev(_scout(), [RB, PICK], [RB])
    banned = ("probab", "likel", "accept", "label", "score", "fit")
    assert not [k for k in ev if any(b in k.lower() for b in banned)]


def test_an_unrecorded_count_is_none_never_zero():
    scout = _scout()
    trading = scout["managers"][0]["tradeTendencies"]
    trading["received"] = {"assets": 9}  # no players / picks / byPosition block
    trading["packageShape"] = None
    trading["partners"] = None
    ev = _ev(scout, [RB, PICK], [RB])
    assert ev["state"] == "measured"
    assert ev["positionsTheyWouldReceive"] == [
        {"position": "RB", "receivedBefore": None, "ofPlayersReceived": None}
    ]
    assert ev["picksTheyWouldReceive"]["receivedBefore"] is None
    assert ev["sameShapeBefore"] is None
    assert ev["tradesWithRequester"] is None
    assert ev["unresolvedPositionReceived"] is None


def test_a_missing_trade_count_is_unavailable():
    scout = _scout()
    scout["managers"][0]["tradeTendencies"].pop("tradeCount")
    ev = _ev(scout, [RB], [RB])
    assert (ev["state"], ev["reason"]) == ("unavailable", "trade_count_unrecorded")
