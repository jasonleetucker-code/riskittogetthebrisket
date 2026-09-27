"""The board view is a lossless projection of Rankings' consumed fields."""

from copy import deepcopy

import pytest

from src.api import bdvm_api


def test_board_preserves_presence_values_order_and_envelope_without_mutation():
    payload = {
        "status": "ok",
        "meta": {"scoringFingerprint": "league-a", "generatedAt": "observed"},
        "picks": [{"name": "pick"}],
        "unpriced": [{"reason": "missing_projection"}],
        "players": [
            {
                "playerId": "same",
                "name": "First",
                "market": {"gap": 0, "marketValue": None, "unused": 123},
                "tradeValue": {"balanced": 0, "contender": 99},
                "signal": {"signal": "HOLD", "reason": "exact reason", "other": 1},
                "projection": {"anyProxy": True, "fpg": 22},
                "path": [{"value": 100}],
            },
            {"playerId": "same", "name": "Last", "market": {"gap": None}},
            {"name": "No ID", "market": {}, "projection": None},
        ],
    }
    before = deepcopy(payload)
    result = bdvm_api.project_bdvm_board(payload)
    assert result == {
        **before,
        "players": [
            {
                "playerId": "same",
                "name": "First",
                "market": {"gap": 0, "marketValue": None},
                "tradeValue": {"balanced": 0},
                "signal": {"signal": "HOLD", "reason": "exact reason"},
                "projection": {"anyProxy": True},
            },
            {"playerId": "same", "name": "Last", "market": {"gap": None}},
            {"name": "No ID", "market": {}, "projection": None},
        ],
    }
    assert payload == before
    result["players"][0]["market"]["gap"] = 25
    assert payload == before  # projection never rewrites the cached valuation


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "no_projection_snapshot", "players": [], "meta": {"reason": "none"}},
        {"error": "bdvm_unavailable"},
        {"status": "ok", "players": None},
        {"status": "ok"},
    ],
)
def test_non_board_states_are_unchanged(payload):
    assert bdvm_api.project_bdvm_board(payload) == payload
