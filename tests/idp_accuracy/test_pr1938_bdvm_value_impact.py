"""Pure-function tests for ``scripts/idp_accuracy/pr1938_bdvm_value_impact.py``.

No network and no snapshot.  The script's ``main`` needs a BDVM projection
snapshot (box-local) or public nflverse data, so only its deterministic diff
logic is unit-tested here: ``diff_payloads``, ``_trade_keys``, ``_rostered``.
``pr1938_case_oracle.py`` and ``pr1938_market_board_parity.py`` are untested
research scripts (network / subprocess); the permanent guard for the
market-board claim is ``test_market_board_does_not_read_realized_points.py``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "idp_accuracy" / "pr1938_bdvm_value_impact.py"
)
_spec = importlib.util.spec_from_file_location("pr1938_bdvm_value_impact", _SCRIPT)
impact = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(impact)  # type: ignore[union-attr]


def _player(pid, name, pos, balanced, signal="HOLD", fpg=10.0):
    return {
        "playerId": pid,
        "name": name,
        "position": pos,
        "group": pos,
        "tradeValue": {"balanced": balanced},
        "projection": {"fpg": fpg},
        "signal": {"signal": signal},
        "market": {"gap": 0.0},
    }


def _payload(players, repl):
    return {"status": "ok", "players": players, "replacement": repl}


@pytest.fixture()
def diff():
    base = _payload(
        [
            _player("1", "Alpha", "WR", 3000.0, "BUY"),
            _player("2", "Bravo", "LB", 2000.0, "SELL"),
            _player("3", "Charlie", "S", 1000.0, "HOLD"),
            _player("4", "Delta", "TE", 500.0, "HOLD"),
        ],
        {"WR": {"replacementFpg": 10.0}},
    )
    new = _payload(
        [
            _player("1", "Alpha", "WR", 3300.0, "STRONG_BUY"),  # up 10%, actionable flip
            _player("2", "Bravo", "LB", 1900.0, "STRONG_SELL"),  # down 5%, flip, unrostered
            _player("3", "Charlie", "S", 1000.2, "BUY"),  # sub-point move, flip
            _player("4", "Delta", "TE", 500.0, "HOLD"),  # unchanged
        ],
        {"WR": {"replacementFpg": 10.1}},
    )
    rostered = {"1": "roster:1", "3": "roster:2"}
    return impact.diff_payloads(base, new, rostered)


def test_value_and_rank_changes_count_only_real_moves(diff):
    assert diff["pricedCurrent"] == diff["pricedCorrected"] == 4
    assert diff["valueChanged"] == 2  # Charlie's 0.2 is below the whole-point threshold
    assert diff["byPosition"]["WR"]["up"] == 1
    assert diff["byPosition"]["LB"]["down"] == 1
    assert diff["byPosition"]["S"]["valueChanged"] == 0
    assert diff["rankChanged"] == 0  # the order 1 > 2 > 3 > 4 holds in both arms
    assert diff["absDeltaPctAmongChanged"]["atLeast10pct"] == 1
    assert diff["absDeltaPctAmongChanged"]["atLeast5pct"] == 2
    assert diff["replacementChanged"] is True


def test_signal_flips_and_alert_transitions_are_roster_scoped_and_actionable(diff):
    flips = {f["name"]: (f["from"], f["to"]) for f in diff["signalFlips"]["list"]}
    assert flips == {
        "Alpha": ("BUY", "STRONG_BUY"),
        "Bravo": ("SELL", "STRONG_SELL"),
        "Charlie": ("HOLD", "BUY"),
    }
    assert diff["signalFlips"]["rosteredCount"] == 2
    # Bravo flipped to an actionable signal but nobody rosters him: no alert.
    alerts = {f["name"] for f in diff["alertTransitionsRostered"]["list"]}
    assert alerts == {"Alpha", "Charlie"}
    assert diff["alertTransitionsRostered"]["byTeam"] == {"roster:1": 1, "roster:2": 1}


def test_rank_moves_are_reported():
    base = _payload([_player("1", "A", "WR", 100.0), _player("2", "B", "WR", 90.0)], {})
    new = _payload([_player("1", "A", "WR", 80.0), _player("2", "B", "WR", 90.0)], {})
    d = impact.diff_payloads(base, new, {})
    assert d["rankChanged"] == 2
    assert d["rankMove"]["max"] == 1
    assert d["replacementChanged"] is False


def test_trade_keys_identify_who_gives_what_independent_of_order():
    t1 = {"from": {"ownerId": "u1", "gives": ["B", "A"]}, "to": {"ownerId": "u2", "gives": ["C"]}}
    t2 = {"from": {"ownerId": "u1", "gives": ["A", "B"]}, "to": {"ownerId": "u2", "gives": ["C"]}}
    t3 = {"from": {"ownerId": "u1", "gives": ["A"]}, "to": {"ownerId": "u2", "gives": ["C"]}}
    keys = impact._trade_keys({"trades": [t1, t2, t3]})
    assert keys[0] == keys[1] != keys[2]


def test_rostered_labels_by_roster_id_never_by_manager_name():
    contract = {
        "sleeper": {
            "teams": [
                {"name": "Some Manager", "roster_id": 7, "playerIds": ["11", "12"]},
                {"name": "Other", "roster_id": 3, "playerIds": ["13"]},
            ]
        }
    }
    assert impact._rostered(contract) == {"11": "roster:7", "12": "roster:7", "13": "roster:3"}
