"""Weekly IDP Streaming UI fixtures, generated from the REAL composer.

``frontend/__tests__/fixtures/idp-streaming/*.json`` are what the streaming
component tests and the E2E journey render.  Each scenario is built here by
running :func:`src.waivers.streaming.assemble_streaming` on real projection and
drop-assessment rows (the same injection pattern ``test_streaming.py`` uses),
then stamped exactly as ``server.py::post_waiver_streaming`` stamps a 200.
``test_streaming_ui_fixtures.py`` regenerates every scenario and requires byte
equality, so a payload-shape change fails until the fixtures — and therefore
the frontend tests — are regenerated with it::

    python -m tests.waivers.streaming_ui_payloads
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

from src.ros.weekly_league_projections import (
    LeagueScoredWeeklyProjection,
    ProjectionCoverage,
    SourceContribution,
    WeeklyProjectionSet,
)
from src.waivers import streaming as st
from src.waivers.drop_assessment import DropReason, DynastyDropAssessment
from tests.waivers.test_streaming import _Bid, _Drops

FIXTURE_DIR = (
    Path(__file__).resolve().parents[2] / "frontend" / "__tests__" / "fixtures" / "idp-streaming"
)
SLOTS = ("DL", "DL", "LB", "LB", "DB", "DB", "IDP_FLEX")

# (playerId, name, position, team, opponent, points by week)
ROSTER = [
    ("9001", "Darius Hale", "DL", "CHI", "DET", (9.5, 8.0)),
    ("9002", "Marcus Oyelaran", "DL", "NYJ", "MIA", (7.0, 7.5)),
    ("9003", "Trent Kowalski", "LB", "PIT", "BAL", (12.0, 11.0)),
    ("9004", "Elijah Banks", "LB", "ATL", "TB", (4.0, 3.5)),  # declining veteran
    ("9005", "Jaylen Ross", "LB", "SEA", "SF", (5.5, 6.5)),  # ascending rookie
    ("9006", "Corey Vance", "DB", "DAL", "PHI", (8.0, 7.5)),
    ("9007", "Andre Whitfield", "DB", "LAC", "KC", (3.0, 2.5)),  # veteran churn
    ("9008", "Sam Okafor", "DB", "HOU", "IND", (None, None)),  # unprojected
]

FREE_AGENTS = [
    ("9101", "Nick Lambright", "LB", "CIN", "CLE", (10.5, 9.0)),
    ("9102", "Tyrell Gaines", "DB", "GB", "MIN", (9.0, 8.5)),
    ("9103", "Owen Pruitt", "DL", "DEN", "LV", (6.5, 6.0)),
    ("9104", "Bryce Mendel", "LB", "NO", "CAR", (None, 7.0)),
]

# Board (dynasty) rows: every rostered defender, and only some free agents.
BOARD = {
    "9101": {"rankDerivedValue": 1450.0, "displayName": "Nick Lambright", "position": "LB"},
    "9103": {"rankDerivedValue": 600.0, "displayName": "Owen Pruitt", "position": "DL"},
}

for _pid, _name, _pos, *_rest in ROSTER:
    BOARD[_pid] = {"displayName": _name, "position": _pos}

ASSESS = {
    "9001": (
        "protected",
        4200.0,
        3100.0,
        "weekly_starter_high_value",
        "Weekly starter worth far more than any free agent.",
    ),
    "9002": (
        "conditional",
        1600.0,
        700.0,
        "moderate_value_above_replacement",
        "Holds value above the best free agent at DL.",
    ),
    "9003": (
        "protected",
        5100.0,
        4000.0,
        "weekly_starter_high_value",
        "Weekly starter worth far more than any free agent.",
    ),
    "9004": (
        "churn",
        350.0,
        0.0,
        "below_replacement_veteran",
        "Age 31 with declining snaps; below waiver level.",
    ),
    "9005": (
        "protected",
        1900.0,
        900.0,
        "ascending_young_defender",
        "Age 22 with rising defensive snap share: developmental asset.",
    ),
    "9006": (
        "protected",
        2600.0,
        1500.0,
        "weekly_starter_high_value",
        "Weekly starter worth far more than any free agent.",
    ),
    "9007": ("churn", 250.0, 0.0, "below_replacement_veteran", "Age 30, below waiver level at DB."),
    "9008": (
        "conditional",
        800.0,
        200.0,
        "unprojected_this_week",
        "No projection this week; small value above replacement.",
    ),
}


def _projection(pid, name, pos, team, opp, pts, week):
    if pts is None:
        return None
    return LeagueScoredWeeklyProjection(
        player_id=pid,
        name=name,
        position=pos,
        team=team,
        season=2026,
        week=week,
        weekly_points=pts,
        state="projected",
        reason="ok",
        sources=(
            SourceContribution(
                source_key="sleeper_weekly",
                family="sleeper",
                provider_model=None,
                fetched_at="2026-10-29T06:00:00+00:00",
                updated_at=None,
                weekly_points=pts,
                imputed_points=0.0,
            ),
        ),
        combine_method="single_source",
        coverage=ProjectionCoverage(
            league_paid_keys=("idp_tkl_solo", "idp_tkl_ast", "idp_sack", "idp_pass_def"),
            covered_keys=("idp_tkl_solo", "idp_tkl_ast", "idp_sack"),
            uncovered_keys=("idp_pass_def",),
            coverage_share=0.75,
        ),
        opponent=opp,
    )


def _sets(weeks):
    out = []
    for i, w in enumerate(weeks):
        rows = {}
        for pid, name, pos, team, opp, pts in (*ROSTER, *FREE_AGENTS):
            p = _projection(pid, name, pos, team, opp, pts[i], w)
            if p is not None:
                rows[pid] = p
        out.append(
            WeeklyProjectionSet(
                league_key="dynasty_main",
                season=2026,
                week=w,
                as_of="2026-10-29T06:00:00+00:00",
                scoring_fingerprint="sf1:fixture",
                scoring_evidence_state="fresh",
                refusal=None,
                source_states=(),
                players=rows,
                schedule_state="ok",
                bye_teams=(),
                current_week=9,
                cache_key=f"fixture-{w}",
            )
        )
    return out


def _assessments():
    names = {pid: (name, pos) for pid, name, pos, *_ in ROSTER}
    rows = []
    for pid, (cls, value, cost, code, detail) in ASSESS.items():
        name, pos = names[pid]
        rows.append(
            DynastyDropAssessment(
                player_id=pid,
                name=name,
                position=pos,
                drop_class=cls,
                dynasty_value=value,
                replacement_value=value - cost,
                value_above_replacement=cost,
                dynasty_cost=cost,
                confidence="high",
                reasons=(DropReason(code=code, detail=detail),),
                inputs={},
                locks=(),
                development_flags=("rising_snap_share",) if pid == "9005" else (),
                roster_role="unknown",
                recovery_risk={"state": "unmeasured"},
            )
        )
    counts = {"churn": 0, "conditional": 0, "protected": 0}
    for r in rows:
        counts[r.drop_class] += 1
    return _Drops(tuple(rows), summary={"counts": counts, "rosterPlayers": len(rows)})


def _build(
    request: dict[str, Any],
    *,
    weeks,
    cfg=None,
    week_rule: str = "current_week",
    ladders: dict[str, list[float]] | None = None,
) -> dict[str, Any]:
    cfg = cfg or st.load_streaming_config()
    req = st.parse_streaming_request({"teamOwnerId": "owner-me", **request}, cfg)
    team = {
        "ownerId": "owner-me",
        "name": "Risk It To Get The Brisket",
        "playerIds": [pid for pid, *_ in ROSTER],
    }
    payload = st.assemble_streaming(
        league_key="dynasty_main",
        team=team,
        owner_id="owner-me",
        season=2026,
        weeks=list(weeks),
        current_week=9,
        projection_sets=_sets(weeks),
        slots=SLOTS,
        slots_source="sleeper_roster_positions",
        board_rows_by_id=BOARD,
        rostered_keys={pid for pid, *_ in ROSTER},
        drop_assessment=_assessments(),
        fa_bids={"9101": _Bid("9101", 4)},
        fa_bid_methodology="market_aware",
        ladders=ladders or {"DL": [600.0, 300.0], "LB": [1450.0, 400.0], "DB": [300.0]},
        faab_remaining=62,
        open_spots=0,
        open_spots_note=None,
        # compute_streaming stamps how the week was chosen; assemble passes it through.
        request={**req, "weekRule": week_rule},
        cfg=cfg,
        posture={"label": "PUSH", "confidence": 0.71},
    )
    # The route's own stamps (server.py::post_waiver_streaming).
    payload["advisoryOnly"] = True
    payload["rosterSource"] = "live_overlay"
    payload["rostersAsOf"] = "2026-10-29T06:00:00+00:00"
    payload["valuationMode"] = "market"
    return payload


def _bounded_cfg() -> st.StreamingConfig:
    # A node limit of 1 truncates the exact search: the solver reports
    # ``bounded`` with its proven gap instead of claiming optimality.
    base = st.load_streaming_config()
    # A request work budget of 1 node also leaves the larger capacity-curve
    # rows unsearched: their gain is a lower bound (``searched: false``).
    return dataclasses.replace(base, node_limit_single_week=1, request_work_budget=1)


SCENARIOS = {
    # Two-week horizon, budget 300: a two-move plan with a partial dynasty
    # change (one add is off the board), an alternative single move,
    # protections and an unprojected roster defender.
    "recommend": lambda: _build(
        {"horizonWeeks": 2, "capacity": 2, "dynastyBudget": 300},
        weeks=(9, 10),
        week_rule="next_week_on_waiver_days",
    ),
    # The same roster at the default budget of 0: one move, and the second
    # (releasing a DB worth 250 over replacement) is what a larger budget buys.
    "budget-limited": lambda: _build(
        {"horizonWeeks": 2, "capacity": 2},
        weeks=(9, 10),
        week_rule="next_week_on_waiver_days",
    ),
    # DL only: no legal DL move improves the lineup — the explicit no-move state.
    "no-move": lambda: _build({"position": "DL", "capacity": 1}, weeks=(9,)),
    # A truncated search: status ``bounded`` with its proven gap.
    "bounded": lambda: _build({"capacity": 3}, weeks=(9,), cfg=_bounded_cfg()),
    # DB only, budget 0, and no priced DB on the wire: releasing the churn DB
    # costs his full 250, so the dynasty budget is what stops the move.
    "budget-binds": lambda: _build(
        {"position": "DB", "capacity": 1},
        weeks=(9,),
        ladders={"DL": [600.0, 300.0], "LB": [1450.0, 400.0], "DB": []},
    ),
}


def build(name: str) -> dict[str, Any]:
    return SCENARIOS[name]()


def serialize(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def fixture_path(name: str) -> Path:
    return FIXTURE_DIR / f"{name}.json"


def main() -> int:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for name in sorted(SCENARIOS):
        fixture_path(name).write_text(serialize(build(name)), encoding="utf-8")
        print(f"wrote {fixture_path(name)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
