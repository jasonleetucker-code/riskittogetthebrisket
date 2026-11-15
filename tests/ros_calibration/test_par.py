"""PAR uses the canonical replacement owner and never coerces unknowns."""

from __future__ import annotations

from src.ros_calibration import par


def test_substitute_values_copies_and_marks_unpriced():
    teams = [
        {
            "players": [
                {"playerId": "a", "position": "LB", "rosValue": 50.0},
                {"playerId": "b", "position": "LB"},
            ]
        }
    ]
    vals = {"a": 12.5, "b": None}
    out = par.substitute_values(teams, lambda p: vals[p["playerId"]])
    assert out[0]["players"][0]["rosValue"] == 12.5
    assert out[0]["players"][1]["rosValue"] == 0.0
    # originals untouched
    assert teams[0]["players"][0]["rosValue"] == 50.0
    assert "rosValue" not in teams[0]["players"][1]


def test_par_for_unknowns_are_none():
    assert par.par_for("LB", None, {"LB": 5.0}) is None
    assert par.par_for("LB", 7.0, {}) is None
    assert par.par_for("LB", 7.0, {"LB": None}) is None
    assert par.par_for("LB", 7.0, {"LB": 5.0}) == 2.0


def test_replacement_points_runs_canonical_owner():
    slots = ["QB", "LB"]
    teams = []
    for t in range(4):
        teams.append(
            {
                "players": [
                    {"playerId": f"q{t}", "position": "QB", "rosValue": 20.0 + t},
                    {"playerId": f"l{t}", "position": "LB", "rosValue": 8.0 + t},
                    {"playerId": f"l{t}b", "position": "LB", "rosValue": 3.0 + t},
                ]
            }
        )
    rep = par.replacement_points(teams, slots)
    assert rep["QB"] is not None and rep["LB"] is not None
    assert rep["QB"] > rep["LB"]
