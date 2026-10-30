"""Golden payloads for the Roster Construction UI lane.

The JSON files under ``frontend/__tests__/fixtures/roster-construction/`` are
produced by the REAL module (snapshot -> player_impact -> construction) from
the deterministic synthetic league below.  The frontend renders them
byte-for-byte; this test fails when the backend's output drifts from them.

Regenerate after an intended contract change::

    RC_REGEN_GOLDEN=1 python -m pytest tests/roster_intel/test_construction_golden.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from tests.roster_intel.rc_support import (
    DYNASTY_MAIN_SLOTS,
    _starters,
    build_snapshot,
    compute,
    league_of,
    make_contract,
    positions_of,
)

FIXTURE_DIR = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "__tests__"
    / "fixtures"
    / "roster-construction"
)
BEST_BALL = FIXTURE_DIR / "golden-best-ball-v1.json"
MANAGED = FIXTURE_DIR / "golden-managed-v1.json"


def _league():
    teams = league_of(6)
    # Team 1: an injured, valuable TE beside weak healthy TEs (RC-D1, NO_ACTION).
    for pid in [p for p, s in teams[1].items() if s[0] == "TE"]:
        teams[1][pid] = ("TE", lambda _w: 2.0)
    teams[1]["t1-te9"] = ("TE", lambda _w: 0.0)
    # Team 1: a valuable 4th QB behind three better ones (RC-D6, REVIEW).
    for pid, v in zip([p for p, s in teams[1].items() if s[0] == "QB"], (40.0, 38.0, 36.0)):
        teams[1][pid] = ("QB", lambda _w, v=v: v)
    teams[1]["t1-qb4"] = ("QB", lambda w: 21.0 + (w % 2))
    # Team 1: two elite RBs with no backups (RC-D2, REVIEW).
    for pid in [p for p, s in teams[1].items() if s[0] == "RB"]:
        del teams[1][pid]
    teams[1]["t1-rbx"] = ("RB", lambda w: 0.0 if w in (2, 5) else 40.0)
    teams[1]["t1-rby"] = ("RB", lambda w: 0.0 if w in (3, 6) else 40.0)
    # A mid-season trade: t2-wr1 moves to team 1 after week 4.
    own = {"t2-wr1": {w: (2 if w <= 4 else 1) for w in range(1, 9)}}
    return teams, own


def _contract(teams, key="dynasty_main"):
    pos = positions_of(teams)
    values = {pid: float(1000 + (i * 37) % 4000) for i, pid in enumerate(sorted(pos))}
    special = {"t1-te9": 9000.0, "t1-qb4": 9500.0, "t1-qb3": 100.0, "t6-k1": None}
    values.update({k: v for k, v in special.items() if k in pos})
    ages = {pid: float(22 + (i * 5) % 12) for i, pid in enumerate(sorted(pos))}
    rosters = {rid: sorted(t) for rid, t in teams.items()}
    if "t1-te9" in pos:  # the best-ball league's mid-season trade
        rosters[1] = sorted(set(rosters[1]) | {"t2-wr1"})
        rosters[2] = sorted(set(rosters[2]) - {"t2-wr1"})
    return make_contract(key, rosters, values, pos, ages)


def build_golden_best_ball() -> dict:
    teams, own = _league()
    snap = build_snapshot(teams, ownership=own, season="2025", league_id="GOLDEN2025")
    snap.nfl_players["t1-te9"]["injury_status"] = "IR"
    payload, _ = compute(
        snap,
        contract=_contract(teams),
        league_key="dynasty_main",
        roster_id=1,
        roster_limit=58,
        posture={"label": "PUSH", "source": "competitive_posture", "asOf": "current"},
    )
    payload["generatedAt"] = snap.generated_at
    return payload


def build_golden_managed() -> dict:
    teams = league_of(4)
    pos = positions_of(teams)

    def submitted(rid, wk, roster):
        prev = {p: teams[rid][p][1](max(1, wk - 1)) for p in roster if p in teams[rid]}
        return _starters(prev, pos, list(DYNASTY_MAIN_SLOTS))[0]

    snap = build_snapshot(
        teams, best_ball=0, managed_starters=submitted, season="2025", league_id="GOLDENM"
    )
    payload, _ = compute(
        snap,
        contract=_contract(teams, key="dynasty_new"),
        league_key="dynasty_new",
        roster_id=2,
        posture={"label": None, "reason": "posture_is_current_season_only"},
    )
    payload["generatedAt"] = snap.generated_at
    return payload


def _dump(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _check(path: Path, payload: dict) -> None:
    text = _dump(payload)
    if os.environ.get("RC_REGEN_GOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert path.is_file(), f"missing golden {path}; regenerate with RC_REGEN_GOLDEN=1"
    assert (
        path.read_text(encoding="utf-8") == text
    ), f"{path.name} drifted from the backend; if intended, regenerate with RC_REGEN_GOLDEN=1"


def test_best_ball_golden_matches_backend():
    payload = build_golden_best_ball()
    rules = {(d["rule"], d["position"]): d for d in payload["diagnoses"]}
    assert rules[("RC-D1", "TE")]["verdict"] == "NO_ACTION"
    assert rules[("RC-D6", "QB")]["verdict"] == "REVIEW"
    assert rules[("RC-D2", "RB")]["verdict"] == "REVIEW"
    _check(BEST_BALL, payload)


def test_managed_golden_matches_backend():
    payload = build_golden_managed()
    assert payload["lineupBasis"] == "hypothetical_optimal"
    _check(MANAGED, payload)
