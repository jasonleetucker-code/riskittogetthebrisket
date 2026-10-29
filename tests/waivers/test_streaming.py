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


# ── review regressions (composer review 2026-10-29) ──────────────────


def test_a_zero_cost_conditional_player_is_never_released_at_budget_zero():
    # The drop assessment calls a release of a conditional player unsafe
    # (unknown/rising signal, low confidence, no locks supplied): no free release.
    assess = _base_assess(
        lb2=_assess("lb2", "LB", "conditional", 300.0, 0.0),
        lbx=_assess("lbx", "LB", "conditional", 200.0, 0.0),
    )
    out = _run(ROSTER, [("fa_lb", "LB", 11.0)], assess)
    assert out["recommendMove"] is False
    board = {r["playerId"]: r for r in out["safeToDrop"]["players"]}
    assert board["lbx"]["releaseCost"] == 200.0
    assert board["lbx"]["releaseCostBasis"] == "conditional_full_value"
    # The larger-budget answer shows what the release would buy, at full value.
    bigger = out["largerBudget"]["plan"]
    assert bigger is not None and bigger["releaseCost"] == 200.0
    # An explicit budget that covers the full value allows it.
    allowed = _run(ROSTER, [("fa_lb", "LB", 11.0)], assess, request={"dynastyBudget": 200})
    assert allowed["recommendMove"] and allowed["plan"]["dropDetails"][0]["playerId"] == "lbx"


def test_a_single_release_is_charged_at_the_first_rung_whatever_the_capacity():
    # LB ladder [400, 100]; churn LBs worth 300 and 200.  One add needs one
    # drop, charged against the best free agent (400) → free, at every capacity.
    assess = _base_assess(
        lb2=_assess("lb2", "LB", "churn", 300.0, 0.0),
        lbx=_assess("lbx", "LB", "churn", 200.0, 0.0),
    )
    fas = [("fa_lb", "LB", 11.0), ("fa_lb2", "LB", 12.0)]
    for cap in (1, 2, 3):
        out = _run(ROSTER, fas, assess, request={"capacity": cap}, ladders={"LB": [400.0, 100.0]})
        assert out["recommendMove"], cap
        assert out["plan"]["releaseCost"] == 0.0
        assert len(out["plan"]["drops"]) == 1


def test_a_larger_capacity_is_never_worse_and_the_curve_matches_the_answers():
    roster = [*ROSTER, ("dbx", "DB", 1.0), ("dlx", "DL", 0.5)]
    assess = [
        *_base_assess(),
        _assess("dbx", "DB", "churn", 100.0, 0.0),
        _assess("dlx", "DL", "churn", 90.0, 0.0),
    ]
    fas = [("fa_lb", "LB", 11.0), ("fa_db", "DB", 9.5), ("fa_dl", "DL", 9.6), ("fa_lb3", "LB", 4.6)]
    gains = []
    curve = None
    for cap in range(0, 6):
        out = _run(roster, fas, assess, request={"capacity": cap})
        alt = out["alternatives"][0]["weeklyGainPoints"] if out["alternatives"] else 0.0
        gains.append(out["plan"]["weeklyGainPoints"] if out["plan"] else alt)
        curve = out["capacityCurve"]
    assert gains == sorted(gains)
    for cap, g in enumerate(gains):
        assert curve[cap]["bestGainPoints"] == pytest.approx(g, abs=1e-3)


def test_recommended_capacity_agrees_with_a_recommended_move():
    # Step 1 alone is below materiality, step 2 crosses it: a recommended
    # 2-add plan must not sit beside recommendedCapacity 0.
    roster = [("lb1", "LB", 10.0), ("lb2", "LB", 4.0), ("db1", "DB", 4.0), ("dl1", "DL", 9.0)]
    assess = [
        _assess("lb1", "LB", "protected", 4000.0, 3000.0),
        _assess("lb2", "LB", "churn", 100.0, 0.0),
        _assess("db1", "DB", "churn", 100.0, 0.0),
        _assess("dl1", "DL", "protected", 3000.0, 2000.0),
    ]
    out = _run(
        roster, [("fa_lb", "LB", 4.6), ("fa_db", "DB", 4.6)], assess, request={"capacity": 2}
    )
    assert out["recommendMove"]
    assert out["recommendedCapacity"] >= len(out["plan"]["adds"])


def test_partial_dynasty_change_is_unknown_not_a_sum_with_zero():
    out = _run(ROSTER, [("fa_lb", "LB", 11.0)], _base_assess())
    change = out["plan"]["dynastyValueChange"]
    assert change["state"] == "partial_unknown_add_values"
    assert change["value"] is None
    assert change["knownValue"] == pytest.approx(-300.0)


def test_players_missing_some_weeks_are_listed():
    roster = [*ROSTER, ("dl_bye", "DL", (6.0, None))]
    assess = [*_base_assess(), _assess("dl_bye", "DL", "protected", 2000.0, 1000.0)]
    out = _run(
        roster, [("fa_lb", "LB", (11.0, 3.0))], assess, weeks=(9, 10), request={"horizonWeeks": 2}
    )
    listed = {p["playerId"]: p for p in out["unprojectedRosterPlayers"]}
    assert listed["dl_bye"]["missingWeeks"] == [10]


def test_board_ties_on_lineup_gain_break_by_projected_points():
    fas = [("a_low", "LB", 1.0), ("b_high", "LB", 3.5)]  # neither beats a starter: gain 0
    out = _run(ROSTER, fas, _base_assess())
    names = [r["playerId"] for r in out["streamingBoard"]]
    assert names.index("b_high") < names.index("a_low")


def test_no_move_reason_names_the_dynasty_budget_when_it_is_what_binds():
    # The only droppable LB is conditional (full value charged): at budget 0
    # nothing can be released, though the lifted search gains 7 points.
    assess = _base_assess(
        lb2=_assess("lb2", "LB", "conditional", 300.0, 0.0),
        lbx=_assess("lbx", "LB", "protected", 900.0, 400.0),
    )
    out = _run(ROSTER, [("fa_lb", "LB", 11.0)], assess)
    assert out["recommendMove"] is False
    assert out["noMoveReason"] == "dynasty_budget_binds"
    assert out["largerBudget"]["plan"]["weeklyGainPoints"] == pytest.approx(7.0)
    # Lift the budget and the same move is recommended.
    out = _run(ROSTER, [("fa_lb", "LB", 11.0)], assess, request={"dynastyBudget": 300})
    assert out["recommendMove"] is True


def _tight_config(monkeypatch, **over):
    import dataclasses

    real = st.load_streaming_config()
    monkeypatch.setattr(
        st, "load_streaming_config", lambda *a, **k: dataclasses.replace(real, **over)
    )


def test_request_work_budget_leaves_curve_rows_unsearched_never_optimal(monkeypatch):
    _tight_config(monkeypatch, request_work_budget=1)
    roster = [*ROSTER, ("dbx", "DB", 1.0)]
    assess = [*_base_assess(), _assess("dbx", "DB", "churn", 100.0, 0.0)]
    fas = [("fa_lb", "LB", 11.0), ("fa_db", "DB", 9.5)]
    out = _run(roster, fas, assess, request={"capacity": 1})
    # The requested capacity is always searched; rows past the budget are not.
    assert out["plan"] is not None and out["solver"]["solvedCapacities"][0] == 1
    unsearched = out["solver"]["unsearchedCapacities"]
    assert unsearched and min(unsearched) > 1
    rows = {r["capacity"]: r for r in out["capacityCurve"]}
    for kk in unsearched:
        assert rows[kk]["searched"] is False
        assert rows[kk]["status"] == "bounded"
    assert any("not searched" in n for n in out["solver"]["notes"])
    again = _run(roster, fas, assess, request={"capacity": 1})
    assert again["solver"] == out["solver"] and again["plan"] == out["plan"]


def test_a_search_stopped_by_its_work_budget_says_so_instead_of_no_move(monkeypatch):
    _tight_config(monkeypatch, request_work_budget=1, min_solve_work=1)
    out = _run(ROSTER, [("fa_lb", "LB", 11.0)], _base_assess())
    assert out["solver"]["status"] == "bounded"
    assert out["recommendMove"] is False
    assert out["noMoveReason"] == "search_incomplete"


def test_a_sub_material_move_beyond_the_budget_is_below_materiality():
    # Only a conditional LB can go (full value charged, budget 0); the move it
    # allows gains 0.3 points: the budget binds nothing material.
    assess = _base_assess(
        lb2=_assess("lb2", "LB", "conditional", 300.0, 0.0),
        lbx=_assess("lbx", "LB", "protected", 900.0, 400.0),
    )
    out = _run(ROSTER, [("fa_lb", "LB", 4.3)], assess)
    assert out["recommendMove"] is False
    assert out["noMoveReason"] == "below_materiality"


def test_default_work_budget_searches_every_curve_row_on_a_small_case():
    out = _run(ROSTER, [("fa_lb", "LB", 11.0)], _base_assess())
    assert out["solver"]["unsearchedCapacities"] == []
    assert all(r["searched"] for r in out["capacityCurve"])
    assert 0 < out["solver"]["workUsed"] <= out["solver"]["requestWorkBudget"]


def test_baseline_points_are_reported_at_capacity_zero_without_a_curve():
    out = _run(
        ROSTER,
        [("fa_lb", "LB", 11.0)],
        _base_assess(),
        request={"capacity": 0, "capacityCurve": False},
    )
    assert out["noMoveReason"] == "capacity_zero"
    assert out["baselinePoints"] == [pytest.approx(31.0)]


def test_board_projection_total_is_unknown_when_a_week_is_missing():
    out = _run(
        ROSTER,
        [("fa_lb", "LB", (11.0, None)), ("fa_db", "DB", (9.0, 9.0))],
        _base_assess(),
        weeks=(9, 10),
        request={"horizonWeeks": 2},
    )
    board = {r["playerId"]: r for r in out["streamingBoard"]}
    assert board["fa_lb"]["weightedProjectedPoints"] is None
    assert board["fa_lb"]["weightedProjectedPointsKnown"] == pytest.approx(11.0)
    assert board["fa_lb"]["missingProjectionWeeks"] == 1
    assert board["fa_db"]["weightedProjectedPoints"] == pytest.approx(9.0 + 0.85 * 9.0)


def test_config_refuses_an_unknown_recommended_capacity_rule(tmp_path):
    import json

    raw = json.loads(st.CONFIG_PATH.read_text(encoding="utf-8"))
    raw["recommendedCapacityRule"]["value"] = "largest_positive_marginal"
    bad = tmp_path / "rule.json"
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(st.StreamingConfigError):
        st.load_streaming_config(bad)


# ── orchestration (compute_streaming) ────────────────────────────────


def _contract():
    rows = [
        {"playerId": pid, "displayName": pid, "position": pos, "rankDerivedValue": 1000.0}
        for pid, pos, _ in ROSTER
    ]
    return {
        "playersArray": rows,
        "sleeper": {
            "teams": [{"ownerId": "me", "name": "Me", "playerIds": [p for p, _, _ in ROSTER]}],
            "rosterPositions": list(SLOTS),
            "leagueSettings": {"playoff_week_start": 15},
        },
    }


def _compute(today, **request):
    from datetime import date  # noqa: PLC0415

    seen: dict[str, Any] = {}

    def load(week, season, current_week):
        seen.setdefault("weeks", []).append(week)
        rows = [_proj(pid, pos, pts, week=week) for pid, pos, pts in ROSTER]
        return _set([*rows, _proj("fa_lb", "LB", 11.0, week=week)], week=week)

    def drops(contract, league_key, owner_id, constraints):
        seen["constraints"] = constraints
        return _Drops(tuple(_base_assess()))

    cfg = st.load_streaming_config()
    req = st.parse_streaming_request({"teamOwnerId": "me", "capacityCurve": False, **request}, cfg)
    out = st.compute_streaming(
        _contract(),
        league_key="t",
        owner_id="me",
        inputs={"teams": _contract()["sleeper"]["teams"], "roster_settings": {"rosterSize": 5}},
        constraints="CONSTRAINTS",
        request=req,
        cfg=cfg,
        today=date.fromisoformat(today),
        load_projections=load,
        assess_drops=drops,
    )
    return out, seen


def test_default_week_on_waiver_days_is_the_next_week():
    out, seen = _compute("2026-10-27")  # Tuesday of week 7's wrap-up
    assert seen["weeks"] == [8] and out["request"]["weekRule"] == "next_week_on_waiver_days"
    out, seen = _compute("2026-10-29")  # Thursday: week 8 is being played
    assert seen["weeks"] == [8] and out["request"]["weekRule"] == "current_week"
    out, seen = _compute("2026-10-27", week=12)
    assert seen["weeks"] == [12] and out["request"]["weekRule"] == "requested"


def test_constraints_reach_the_drop_assessment():
    _out, seen = _compute("2026-10-29")
    assert seen["constraints"] == "CONSTRAINTS"


def test_out_of_season_without_a_week_is_refused():
    with pytest.raises(ValueError, match="not_in_season"):
        _compute("2027-03-01")


def test_drop_policy_errors_map_to_stable_codes(monkeypatch):
    from datetime import date  # noqa: PLC0415

    from src.waivers.drop_assessment import DropAssessmentConfigError, TeamNotInLeague

    cfg = st.load_streaming_config()
    req = st.parse_streaming_request({"teamOwnerId": "me", "capacityCurve": False}, cfg)

    def run(exc):
        def drops(*_a):
            raise exc

        return st.compute_streaming(
            _contract(),
            league_key="t",
            owner_id="me",
            inputs={"teams": _contract()["sleeper"]["teams"]},
            constraints=None,
            request=req,
            cfg=cfg,
            today=date(2026, 10, 29),
            load_projections=lambda w, s, c: _set([], week=w),
            assess_drops=drops,
        )

    for exc, code in (
        (TeamNotInLeague("x"), "unknown_team"),
        (DropAssessmentConfigError("x"), "drop_policy_unreadable"),
        (ValueError("league_mismatch: a vs b"), "league_mismatch"),
    ):
        with pytest.raises(ValueError, match=code):
            run(exc)
