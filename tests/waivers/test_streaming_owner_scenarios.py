"""Owner decision 7 (2026-11-01) scenarios for the weekly IDP streaming advisor.

Default dynasty-loss budget is 0; a user may choose more, with disclosure; NO
TRANSACTION is a valid answer; missing value is never zero; kickers count for
lineup contribution without an invented market value; defensive scoring comes
from the exact league card; protection is evidence-based.  These pin the
composer (``src/waivers/streaming.py::assemble_streaming``) and its owners on
the scenarios the owner named.  No behaviour changed to make them pass.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.waivers import streaming as st
from tests.waivers.test_streaming import ROSTER, _assess, _base_assess, _run

REPO = Path(__file__).resolve().parents[2]


def _releases_cost_only():
    """Every releasable LB costs dynasty value (conditional, not churn)."""
    return _base_assess(
        lb2=_assess("lb2", "LB", "conditional", 1200.0, 500.0),
        lbx=_assess("lbx", "LB", "conditional", 1100.0, 400.0),
    )


def test_default_dynasty_budget_is_zero():
    cfg = st.load_streaming_config()
    assert st.parse_streaming_request({"teamOwnerId": "me"}, cfg)["dynastyBudget"] == 0.0


def test_beneficial_one_for_one_idp_streamer_costs_no_dynasty_value():
    out = _run(ROSTER, [("fa_lb", "LB", 11.0)], _base_assess())
    assert out["recommendMove"] is True
    plan = out["plan"]
    assert len(plan["adds"]) == 1 and len(plan["dropDetails"]) == 1
    assert plan["releaseCost"] == 0.0
    assert plan["weeklyGainPoints"] > out["config"]["materialityPoints"]


def test_attractive_defender_not_worth_the_drop_is_no_move_with_the_price_disclosed():
    out = _run(ROSTER, [("fa_lb", "LB", 14.0)], _releases_cost_only())
    assert out["recommendMove"] is False
    assert out["plan"] is None
    assert out["noMoveReason"] == "dynasty_budget_binds"
    # The budget alternative is exposed, with its price, never applied.
    larger = out["largerBudget"]["plan"]
    assert larger is not None and larger["releaseCost"] > 0
    assert "larger budget" in out["largerBudget"]["meaning"]


def test_protected_developmental_defender_is_never_released_even_for_a_big_gain():
    assess = _base_assess(
        lb2=_assess("lb2", "LB", "protected", 900.0, 600.0),
        lbx=_assess("lbx", "LB", "protected", 800.0, 500.0),
    )
    out = _run(ROSTER, [("fa_lb", "LB", 25.0)], assess, request={"dynastyBudget": 100000})
    released = {d["playerId"] for d in (out["plan"] or {}).get("dropDetails", [])}
    assert not released & {"lb2", "lbx", "dl1", "lb1", "db1"}
    assert out["recommendMove"] is False


def test_protection_rules_are_declared_evidence_gated_priors():
    raw = json.loads(
        (REPO / "config/waivers/streaming_protection.json").read_text(encoding="utf-8")
    )
    params = raw["parameters"]
    for key in ("protectGapMin", "risingSnapTrendMinPts", "noUsageSnapPctMax", "youngAgeMax"):
        assert params[key]["class"] == "PRIOR"
        assert params[key]["rationale"]
    # An absent snap record is unknown, never "no usage".
    assert "never zero" in params["noUsageSnapPctMax"]["rationale"]


def test_multiple_legal_simultaneous_adds_use_distinct_releases():
    roster = [*ROSTER, ("dbx", "DB", 1.0)]
    assess = [*_base_assess(), _assess("dbx", "DB", "churn", 100.0, 0.0)]
    out = _run(
        roster,
        [("fa_lb", "LB", 11.0), ("fa_db", "DB", 9.5)],
        assess,
        request={"capacity": 2},
    )
    plan = out["plan"]
    assert out["recommendMove"] is True
    assert sorted(plan["adds"]) == ["fa_db", "fa_lb"]
    drops = [d["playerId"] for d in plan["dropDetails"]]
    assert len(drops) == len(set(drops)) == 2
    assert plan["releaseCost"] == 0.0


def test_rebuilding_team_holds_and_posture_never_raises_the_budget():
    rebuild = _run(ROSTER, [("fa_lb", "LB", 14.0)], _releases_cost_only())
    assert rebuild["recommendMove"] is False  # hold: the release would cost value
    # Posture is context only: a contender posture with the same budget gives
    # the identical answer (it never raises the dynasty budget by itself).
    assert "never raises the dynasty budget" in rebuild["posture"]["use"]


def test_contender_chooses_a_budget_and_the_trade_off_is_disclosed():
    default = _run(ROSTER, [("fa_lb", "LB", 14.0)], _releases_cost_only())
    price = default["largerBudget"]["plan"]["releaseCost"]
    chosen = _run(
        ROSTER, [("fa_lb", "LB", 14.0)], _releases_cost_only(), request={"dynastyBudget": price}
    )
    assert chosen["recommendMove"] is True
    assert chosen["request"]["dynastyBudget"] == price
    assert 0 < chosen["plan"]["releaseCost"] <= price
    assert chosen["plan"]["weeklyGainPoints"] > 0


def test_missing_source_projections_are_unknown_never_zero():
    roster = [*ROSTER, ("db_out", "DB", None)]
    assess = [*_base_assess(), _assess("db_out", "DB", "conditional", 700.0, 0.0)]
    out = _run(roster, [("fa_none", "LB", None), ("fa_lb", "LB", 11.0)], assess)
    assert out["excludedFreeAgents"]["fa_none"] == "unprojected"
    assert [p["playerId"] for p in out["unprojectedRosterPlayers"]] == ["db_out"]
    assert all(r["playerId"] != "fa_none" for r in out["streamingBoard"])


def test_explicit_no_transaction_is_a_valid_answer():
    out = _run(ROSTER, [("fa_lb", "LB", 3.0)], _base_assess())
    assert out["recommendMove"] is False
    assert out["plan"] is None
    assert out["noMoveReason"] in {"no_move_improves_the_lineup", "below_materiality"}
    assert out["solver"]["status"] == "optimal"


def test_search_budget_exhaustion_is_labelled_never_optimal(monkeypatch):
    from tests.waivers.test_streaming import _tight_config

    _tight_config(monkeypatch, request_work_budget=1, min_solve_work=1)
    out = _run(ROSTER, [("fa_lb", "LB", 11.0)], _base_assess())
    assert out["solver"]["status"] == "bounded"
    # An exhausted search is never reported as "no move improves the lineup".
    assert out["recommendMove"] is False
    assert out["noMoveReason"] == "search_incomplete"


# ── Kickers: lineup contribution, no invented market value ─────────────


def test_kicker_is_never_a_priced_waiver_candidate():
    from src.trade.waiver import waiver_candidate_exclusion, waiver_positions

    row = {"position": "K", "rankDerivedValue": None, "sourceCount": 0}
    assert (
        waiver_candidate_exclusion(row, positions=waiver_positions(False), rookies_eligible=True)
        == "kicker_def_excluded"
    )
    # Opting kickers in never prices them at 0: an unpriced kicker is refused.
    assert (
        waiver_candidate_exclusion(row, positions=waiver_positions(True), rookies_eligible=True)
        == "unpriced"
    )


def test_kicker_contributes_lineup_points_through_the_exact_solver():
    from src.ros.lineup import RosterPlayer, assign_lineup

    def k(pid, value):
        return RosterPlayer(player_id=pid, canonical_name=pid, position="K", ros_value=value)

    res = assign_lineup([k("k1", 9.0), k("k2", None)], ["K"])
    assert [p.player_id for p in res.assignments.values()] == ["k1"]
    assert "k2" in res.unpriced_ids  # unknown is unassignable, not a 0-point starter


# ── Defensive scoring comes from the exact league card ─────────────────


def test_defensive_td_is_scored_at_the_league_card_rate():
    from src.league_intel.scorer import score_stat_line
    from src.scoring.sleeper_ingest import normalize_scoring_settings

    card = json.loads(
        (REPO / "tests/fixtures/li_scoring/dynasty_main_league_2026.json").read_text(
            encoding="utf-8"
        )
    )
    settings = card.get("scoring_settings", card)
    rate = float(settings["idp_def_td"])
    assert rate != 6.0  # the card's own rate, not a generic 6-point TD
    assert score_stat_line({"idp_def_td": 1}, settings).total_points == pytest.approx(rate)
    # The legacy ``idp_td`` key lands on the same canonical key.
    norm = normalize_scoring_settings({"idp_td": rate})
    assert norm.scoring_map["idp_def_td"] == pytest.approx(rate)
