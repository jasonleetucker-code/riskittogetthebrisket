"""Weekly IDP streaming composer: the acceptance scenarios at the composer level.

``assemble_streaming`` is pure, so every owner's output is injected: real
:class:`WeeklyProjectionSet` / :class:`LeagueScoredWeeklyProjection` rows and
real :class:`DynastyDropAssessment` rows, with a minimal team-level wrapper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from src.ros.weekly_league_projections import LeagueScoredWeeklyProjection, WeeklyProjectionSet
from src.waivers import streaming as st
from src.waivers.drop_assessment import DropReason, DynastyDropAssessment

SLOTS = ("DL", "LB", "LB", "DB")


def _proj(pid, pos, pts, week=9, state=None):
    return LeagueScoredWeeklyProjection(
        player_id=pid,
        name=pid,
        position=pos,
        team="AAA",
        season=2026,
        week=week,
        weekly_points=pts,
        state=state or ("projected" if pts is not None else "unprojected"),
        reason="test",
    )


def _set(rows, week=9):
    return WeeklyProjectionSet(
        league_key="t",
        season=2026,
        week=week,
        as_of="2026-10-29T00:00:00+00:00",
        scoring_fingerprint="sf1:test",
        scoring_evidence_state="caller_supplied",
        refusal=None,
        source_states=(),
        players={r.player_id: r for r in rows},
        schedule_state="ok",
        bye_teams=(),
        current_week=8,
        cache_key="k",
    )


def _assess(pid, pos, cls, value, cost):
    return DynastyDropAssessment(
        player_id=pid,
        name=pid,
        position=pos,
        drop_class=cls,
        dynasty_value=value,
        replacement_value=None if value is None else value - cost,
        value_above_replacement=None if value is None else cost,
        dynasty_cost=cost,
        confidence="high",
        reasons=(DropReason(code=f"test_{cls}", detail=cls),),
        inputs={},
        locks=(),
        development_flags=(),
        roster_role="unknown",
        recovery_risk={"state": "unmeasured"},
    )


@dataclass
class _Drops:
    assessments: tuple
    summary: dict = field(default_factory=lambda: {"counts": {}})

    def by_player_id(self):
        return {a.player_id: a for a in self.assessments}

    def to_dict(self):
        return {"summary": self.summary}


@dataclass
class _Bid:
    player_id: str
    bid: int
    bid_detail: dict = field(default_factory=dict)


def _run(
    roster_rows,
    fa_rows,
    assessments,
    *,
    weeks=(9,),
    request=None,
    bids=None,
    board=None,
    ladders=None,
    faab=100,
    open_spots=0,
):
    cfg = st.load_streaming_config()
    req = st.parse_streaming_request({"teamOwnerId": "me", **(request or {})}, cfg)
    sets = []
    for i, w in enumerate(weeks):
        rows = [
            _proj(pid, pos, pts[i] if isinstance(pts, tuple) else pts, week=w)
            for pid, pos, pts in (*roster_rows, *fa_rows)
        ]
        sets.append(_set(rows, week=w))
    team = {"ownerId": "me", "name": "Me", "playerIds": [pid for pid, _, _ in roster_rows]}
    return st.assemble_streaming(
        league_key="t",
        team=team,
        owner_id="me",
        season=2026,
        weeks=list(weeks),
        current_week=8,
        projection_sets=sets,
        slots=SLOTS,
        slots_source="test",
        board_rows_by_id=board or {},
        rostered_keys={pid.lower() for pid, _, _ in roster_rows},
        drop_assessment=_Drops(tuple(assessments)),
        fa_bids={pid: _Bid(pid, b) for pid, b in (bids or {}).items()},
        fa_bid_methodology="market_aware",
        # Default: a priced free agent at every family worth more than any
        # churn player here, so churn releases cost nothing.
        ladders=ladders if ladders is not None else {f: [5000.0] * 4 for f in ("DL", "LB", "DB")},
        faab_remaining=faab,
        open_spots=open_spots,
        open_spots_note=None,
        request=req,
        cfg=cfg,
    )


ROSTER = [
    ("dl1", "DL", 9.0),
    ("lb1", "LB", 10.0),
    ("lb2", "LB", 4.0),  # low-value veteran starter, declining
    ("db1", "DB", 8.0),
    ("lbx", "LB", 2.0),  # bench
]


def _base_assess(**over):
    rows = {
        "dl1": _assess("dl1", "DL", "protected", 3000.0, 2000.0),
        "lb1": _assess("lb1", "LB", "protected", 4000.0, 3000.0),
        "lb2": _assess("lb2", "LB", "churn", 300.0, 0.0),
        "db1": _assess("db1", "DB", "protected", 2500.0, 1500.0),
        "lbx": _assess("lbx", "LB", "churn", 200.0, 0.0),
    }
    rows.update(over)
    return list(rows.values())


def test_scenario_1_obvious_streamer():
    out = _run(ROSTER, [("fa_lb", "LB", 11.0)], _base_assess())
    assert out["recommendMove"] is True
    plan = out["plan"]
    assert [a["playerId"] for a in plan["addDetails"]] == ["fa_lb"]
    # The 11.0 replaces the 4.0 starter; releasing either churn LB then costs
    # no points and no dynasty value, so the two plans tie and id order picks.
    assert [d["playerId"] for d in plan["dropDetails"]] == ["lb2"]
    assert plan["weeklyGainPoints"] == pytest.approx(7.0)
    assert plan["releaseCost"] == 0.0
    # The directive's dynasty change is reported, not optimised: the add is
    # off the board, so it is partial.
    assert plan["dynastyValueChange"]["state"] == "partial_unknown_add_values"
    assert plan["addDetails"][0]["bidBasis"] == "off_board_zero_claim_only"


def test_scenario_2_protected_young_player_is_never_released():
    assess = _base_assess(
        lbx=_assess("lbx", "LB", "protected", 900.0, 400.0),
        lb2=_assess("lb2", "LB", "protected", 1500.0, 1000.0),
    )
    out = _run(ROSTER, [("fa_lb", "LB", 11.0)], assess)
    assert out["recommendMove"] is False
    assert out["plan"] is None
    assert out["noMoveReason"] == "no_droppable_player"


def test_scenario_3_no_beneficial_move():
    out = _run(ROSTER, [("fa_lb", "LB", 4.3)], _base_assess())
    assert out["recommendMove"] is False
    assert out["noMoveReason"] == "below_materiality"
    assert out["alternatives"][0]["weeklyGainPoints"] == pytest.approx(0.3)


def test_scenario_4_multiple_moves_without_reuse_and_within_faab():
    roster = [*ROSTER, ("dbx", "DB", 1.0)]
    assess = [*_base_assess(), _assess("dbx", "DB", "churn", 100.0, 0.0)]
    fas = [("fa_lb", "LB", 11.0), ("fa_db", "DB", 9.5), ("fa_dl", "DL", 12.0)]
    out = _run(
        roster,
        fas,
        assess,
        request={"capacity": 3},
        bids={"fa_lb": 30, "fa_db": 30, "fa_dl": 50},
        board={k: {"rankDerivedValue": 100.0} for k in ("fa_lb", "fa_db", "fa_dl")},
        faab=60,
    )
    plan = out["plan"]
    assert out["recommendMove"]
    assert plan["faabTotal"] <= 60
    drops = [d["playerId"] for d in plan["dropDetails"]]
    assert len(drops) == len(set(drops)) == len(plan["adds"])


def test_dynasty_budget_charges_a_second_release_against_a_deeper_free_agent():
    # Two churn LBs; the LB free-agent ladder is 400 then 100.  With capacity 2
    # each release is charged against rung 2 (100), not both against 400.
    assess = _base_assess(
        lb2=_assess("lb2", "LB", "churn", 300.0, 0.0),
        lbx=_assess("lbx", "LB", "churn", 200.0, 0.0),
    )
    out = _run(
        ROSTER,
        [("fa_lb", "LB", 11.0), ("fa_lb2", "LB", 12.0)],
        assess,
        request={"capacity": 2},
        ladders={"LB": [400.0, 100.0]},
    )
    board = {r["playerId"]: r for r in out["safeToDrop"]["players"]}
    assert board["lb2"]["releaseCost"] == 200.0
    assert board["lbx"]["releaseCost"] == 100.0
    # Budget 0: no release that costs dynasty value is proposed.
    assert out["recommendMove"] is False or out["plan"]["releaseCost"] == 0.0
    assert out["largerBudget"]["plan"] is not None


def test_scenario_7_missing_projections_are_unavailable_never_zero():
    roster = [*ROSTER, ("dl_hurt", "DL", None)]
    assess = [*_base_assess(), _assess("dl_hurt", "DL", "conditional", 500.0, 0.0)]
    out = _run(roster, [("fa_x", "DL", None)], assess)
    assert out["excludedFreeAgents"]["fa_x"] == "unprojected"
    assert [p["playerId"] for p in out["unprojectedRosterPlayers"]] == ["dl_hurt"]
    assert all(r["playerId"] != "fa_x" for r in out["streamingBoard"])


def test_scenario_9_capacity_curve_and_recommended_capacity():
    roster = [*ROSTER, ("dbx", "DB", 1.0)]
    assess = [*_base_assess(), _assess("dbx", "DB", "churn", 100.0, 0.0)]
    fas = [("fa_lb", "LB", 11.0), ("fa_db", "DB", 9.5), ("fa_lb3", "LB", 4.2)]
    out = _run(roster, fas, assess, request={"capacity": 3})
    curve = out["capacityCurve"]
    assert [r["capacity"] for r in curve] == list(range(0, 8))
    gains = [r["bestGainPoints"] for r in curve]
    assert gains == sorted(gains)
    assert out["recommendedCapacity"] == 2  # the third add gains 0.2 < materiality


def test_multiweek_horizon_and_weights():
    out = _run(
        ROSTER,
        [("fa_lb", "LB", (11.0, 3.0))],
        _base_assess(),
        weeks=(9, 10),
        request={"horizonWeeks": 2},
    )
    assert out["weeks"] == [9, 10]
    assert out["weekWeights"] == [1.0, 0.85]
    # Week 1 gain 7.0, week 2: the 3.0 add is benched behind 4.0 and 10.0 → 0.
    assert out["plan"]["gainByWeekPoints"] == [7.0, 0.0]


def test_position_filter_limits_adds_and_drops():
    out = _run(
        ROSTER,
        [("fa_lb", "LB", 11.0), ("fa_db", "DB", 20.0)],
        _base_assess(),
        request={"position": "DB"},
    )
    assert all(r["position"] == "DB" for r in out["streamingBoard"])
    assert out["plan"] is None  # no DB is droppable


def test_unknown_faab_balance_allows_zero_claims_only():
    out = _run(
        ROSTER,
        [("fa_lb", "LB", 11.0)],
        _base_assess(),
        bids={"fa_lb": 5},
        board={"fa_lb": {"rankDerivedValue": 100.0}},
        faab=None,
    )
    assert out["faab"]["state"] == "unknown_zero_claims_only"
    assert out["recommendMove"] is False


@pytest.mark.parametrize(
    "body, code",
    [
        ({"position": "QB"}, "bad_position"),
        ({"capacity": 9}, "bad_capacity"),
        ({"capacity": True}, "bad_capacity"),
        ({"week": 19}, "bad_week"),
        ({"horizonWeeks": 5}, "bad_horizonWeeks"),
        ({"dynastyBudget": -1}, "bad_dynastyBudget"),
        ({"capacityCurve": "yes"}, "bad_capacityCurve"),
    ],
)
def test_request_validation(body, code):
    cfg = st.load_streaming_config()
    with pytest.raises(ValueError, match=code):
        st.parse_streaming_request({"teamOwnerId": "me", **body}, cfg)


def test_config_refuses_when_missing_or_malformed(tmp_path):
    with pytest.raises(st.StreamingConfigError):
        st.load_streaming_config(tmp_path / "absent.json")
    bad = tmp_path / "bad.json"
    bad.write_text('{"materialityPoints": {"value": 1, "class": "FITTED"}}', encoding="utf-8")
    with pytest.raises(st.StreamingConfigError):
        st.load_streaming_config(bad)


def test_payload_never_mixes_units():
    out = _run(ROSTER, [("fa_lb", "LB", 11.0)], _base_assess())
    plan: dict[str, Any] = out["plan"]
    assert {"weeklyGainPoints", "releaseCost", "dynastyValueChange", "faabTotal"} <= set(plan)
    assert "score" not in plan and "total" not in plan
