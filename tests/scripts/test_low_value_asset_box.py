"""Low-value-asset confirmatory box script (owner directive 2026-10-20).

Pins: exactly one read-only guard per process (the Phase 3 module's own guard
is never installed alongside), the guard precedes every application import,
the league-disjoint split and prospective cut, the preregistered piece
classes, and aggregate-only output on synthetic trades.  Research only.
"""

from __future__ import annotations

import importlib.util
import json
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "low_value_asset_box", REPO / "scripts" / "low_value_asset_box.py"
)
# Loading the script registers its sibling research modules in sys.modules; the
# entries are restored afterwards so no later test module sees this module's
# copies (tests/process_state_isolation.py).  B keeps its own references.
_NAMES = (
    "low_value_asset_box",
    "low_value_asset_treatments",
    "package_model_phase3_research",
    "package_model_phase2_research",
    "package_model_hybrid_research",
)
_saved = {n: sys.modules.get(n) for n in _NAMES}
B = importlib.util.module_from_spec(_spec)
sys.modules["low_value_asset_box"] = B
_spec.loader.exec_module(B)
for _n, _m in _saved.items():
    if _m is None:
        sys.modules.pop(_n, None)
    else:
        sys.modules[_n] = _m


def test_single_guard_and_guard_precedes_app_imports():
    src = (REPO / "scripts" / "low_value_asset_box.py").read_text(encoding="utf-8")
    assert src.index("GUARD.install()") < src.index("sys.path.insert(0, str(REPO))")
    assert src.index("GUARD.install()") < src.index('_load("package_model_phase3_research")')
    # Phase 3's module would install a second guard if it saw "--box".
    assert 'sys.argv = [a for a in _argv if a != "--box"]' in src
    assert "import subprocess" not in src


def test_split_is_league_disjoint_and_prospective_by_date():
    assert B.split_bucket("x", "2026-10-21") == "prospective"
    assert B.split_bucket(None, "2026-10-01") == "noLeague"
    seen = {B.split_bucket(f"lg{i}", "2026-10-01") for i in range(50)}
    assert seen == {"discovery", "confirmation"}
    assert all(
        B.split_bucket("lg7", d) == B.split_bucket("lg7", "2026-09-01")
        for d in ("2026-07-20", "2026-10-20")
    )


def test_piece_class_uses_position_anchors(monkeypatch):
    monkeypatch.setattr(B, "ANCHORS", {"WR": 2100.0, "LB": 800.0, "*": 1800.0})
    monkeypatch.setattr(B, "STARTER_LINES", {"WR": 4000.0, "LB": 1600.0, "*": 3500.0})
    assert B.piece_class(1500.0, "player", "LB") == "usable"
    assert B.piece_class(1500.0, "player", "WR") == "filler"
    assert B.piece_class(1700.0, "player", "LB") == "starter"
    assert B.piece_class(2000.0, "pick", None) == "usable"


def _row(i, rng):
    nA = 1
    nB = rng.choice([1, 2, 2, 3, 5])
    kinds = [
        ["player", rng.choice(["WR", "RB", "LB"]), None, f"player:{9000 + i}{k}"] for k in range(nA)
    ]
    kindsB = [
        ["pick", None, 2027, "mpick:2027:r1"]
        if k % 2
        else ["player", "WR", None, f"player:{8000 + i}{k}"]
        for k in range(nB)
    ]
    return {
        "date": f"2026-10-{1 + i % 19:02d}",
        "league": f"league-{i % 40}",
        "source": "ktc_trade_database",
        "A": [float(rng.randint(2000, 9000)) for _ in range(nA)],
        "B": [float(rng.randint(300, 5000)) for _ in range(nB)],
        "meta": [kinds, kindsB],
    }


def test_analysis_is_aggregate_only():
    rng = random.Random(4)
    rows = [_row(i, rng) for i in range(400)]
    out = B.analyse(rows)
    B.P2.assert_aggregate_only(out)
    blob = json.dumps(out)
    assert "league-3" not in blob and "player:" not in blob
    assert out["M3_servedValueDynamics"]["available"] in (True, False)


def test_frozen_anchors_match_the_shadow_replay_evidence():
    ev = json.loads(
        (
            REPO / "docs/valuation/evidence/low_value_assets_2026-10-20/shadow_replay.json"
        ).read_text()
    )["S1_replacementAnchors"]
    assert {k: float(v) for k, v in ev["replacementAnchorDict"].items()} == B.ANCHORS
    for pos, line in B.STARTER_LINES.items():
        if pos != "*":
            assert ev["byPosition"][pos]["lowestStarterAcross12OptimalLineups"] == line
