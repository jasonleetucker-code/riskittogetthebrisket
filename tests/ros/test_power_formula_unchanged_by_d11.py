"""Owner Decision 11 must not change the official Power Rankings formula.

The decision removes a duplicate ROS influence from the playoff / title
simulator only ("Do not change the official Power Rankings formula as a side
effect").  Power (``src/ros/power_v2.py``) reads team ROS strength directly and
never the simulator, so the flag ``playoff_ros_counted_once`` cannot reach it.
This file pins that three ways: the formula constants, the absence of any
import path from Power into the simulator, and a byte-identical section with
the flag on and off.
"""

from __future__ import annotations

import ast
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.api import feature_flags
from src.ros import power_v2, team_strength
from tests.ros.test_power_v2 import _make_snapshot

REPO = Path(__file__).resolve().parents[2]


def test_power_formula_constants_unchanged():
    assert power_v2.WEIGHTS == {
        "team_ros_strength": 0.30,
        "all_play": 0.30,
        "recent": 0.15,
        "team_vorp": 0.15,
        "wl_record": 0.10,
    }
    assert power_v2.FORWARD_COMPONENTS == ("team_ros_strength",)
    assert power_v2.RESULT_COMPONENTS == ("all_play", "recent", "team_vorp", "wl_record")
    assert power_v2._RESULTS_EVIDENCE_TAU_GAMES == 2.0
    assert power_v2._RECENT_WINDOW == 4
    assert power_v2.METHODOLOGY_VERSION == "canonical-power-2026.09-v2"


def test_power_never_reads_the_playoff_simulator():
    tree = ast.parse((REPO / "src" / "ros" / "power_v2.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names = {a.name for a in node.names}
            assert node.module != "src.ros.playoff_sim"
            assert not (node.module == "src.ros" and "playoff_sim" in names)
        if isinstance(node, ast.Import):
            assert all(a.name != "src.ros.playoff_sim" for a in node.names)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value != "playoff_ros_counted_once"


def _section(flag_value: str, monkeypatch) -> dict:
    monkeypatch.setenv("RISKIT_FEATURE_PLAYOFF_ROS_COUNTED_ONCE", flag_value)
    feature_flags.reload()
    rosters = [{"owner_id": f"o{i}", "roster_id": i} for i in range(1, 5)]
    matchups = {
        wk: [
            {"roster_id": 1, "matchup_id": 1, "points": 110.0 + wk},
            {"roster_id": 2, "matchup_id": 1, "points": 90.0 + 3 * wk},
            {"roster_id": 3, "matchup_id": 2, "points": 85.0 + wk},
            {"roster_id": 4, "matchup_id": 2, "points": 80.0 + 2 * wk},
        ]
        for wk in (1, 2, 3, 4, 5)
    }
    snapshot = _make_snapshot(rosters=rosters, matchups_by_week=matchups)
    rows = [
        {
            "ownerId": f"o{i}",
            "teamRosStrength": 40.0 + 7 * i,
            "startingLineupScore": 40.0 + 7 * i,
            "benchDepthScore": 10.0 * i,
            "healthAvailabilityScore": 100,
        }
        for i in range(1, 5)
    ]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "team_strength" / "latest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(rows))
        with patch.object(team_strength, "ROS_DATA_DIR", root):
            section = power_v2.build_section(snapshot)
    section.pop("generatedAt", None)
    return section


def test_power_section_identical_with_flag_on_and_off(monkeypatch):
    try:
        off = _section("0", monkeypatch)
        on = _section("1", monkeypatch)
    finally:
        feature_flags.reload()
    assert json.dumps(off, sort_keys=True, default=str) == json.dumps(
        on, sort_keys=True, default=str
    )
    assert off["currentRanking"]
