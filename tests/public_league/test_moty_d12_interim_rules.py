"""Owner Decision 12 — unified Manager of the Year stays a validation-only candidate.

State of ``main`` when this was written: the OFFICIAL Manager of the Year is
``awards._manager_of_the_year_scores`` (30/25/15/15/15) and decides the card and
the race; the unified candidate's implementation exists only on the unmerged
PR #1513.  So this file pins two things:

1. the official method and its display are unchanged, and nothing in the
   official award path reads the candidate or its policy; and
2. every Decision 12 interim rule, as enforced by the ``main``-side owner
   ``src/public_league/moty_candidate_policy.py`` that any candidate surface
   must go through.
"""

from __future__ import annotations

import ast
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.public_league import awards
from src.public_league import moty_candidate_policy as policy
from src.public_league.awards import (
    _manager_of_the_year_scores,
    _minmax,
    _trader_of_the_year_scores,
    _waiver_king_scores,
)
from tests.public_league.fixtures import build_test_snapshot
from tests.public_league.test_awards import _with_player_points

REPO = Path(__file__).resolve().parents[2]
C, P, U = policy.COMPLETE, policy.PARTIAL, policy.UNAVAILABLE


# ── 1. official method and display unchanged ───────────────────────────────


def test_official_moty_formula_is_unchanged():
    snapshot = _with_player_points(build_test_snapshot())
    season = snapshot.seasons[0]
    traders, _ = _trader_of_the_year_scores(snapshot, season)
    waivers = _waiver_king_scores(snapshot, season)
    rows = _manager_of_the_year_scores(snapshot, season, traders, waivers)
    assert rows
    n = len(rows)
    finish = _minmax({r["ownerId"]: float(n - r["finishRank"]) for r in rows})
    win = _minmax({r["ownerId"]: float(r["winPct"]) for r in rows})
    pf = _minmax({r["ownerId"]: float(r["pointsFor"]) for r in rows})
    trade = _minmax({r["ownerId"]: float(r["tradePointsGained"]) for r in rows})
    waiver = _minmax({r["ownerId"]: float(r["waiverPointsGained"]) for r in rows})
    for r in rows:
        o = r["ownerId"]
        expected = (
            0.30 * finish[o] + 0.25 * win[o] + 0.15 * pf[o] + 0.15 * trade[o] + 0.15 * waiver[o]
        )
        assert r["compositeScore"] == pytest.approx(expected, abs=1e-3)
    assert set(rows[0]) == {
        "ownerId",
        "displayName",
        "wins",
        "losses",
        "ties",
        "winPct",
        "pointsFor",
        "finishRank",
        "tradePointsGained",
        "waiverPointsGained",
        "compositeScore",
    }


def test_official_moty_docstring_states_the_official_weights():
    doc = awards._manager_of_the_year_scores.__doc__ or ""
    assert "30% final finish + 25% regular-season win%" in doc
    assert "15% trade impact" in doc and "15% waiver impact" in doc


def test_official_moty_display_unchanged():
    awards_jsx = (REPO / "frontend/app/league/sections/awards.jsx").read_text(encoding="utf-8")
    shared_jsx = (REPO / "frontend/app/league/shared.jsx").read_text(encoding="utf-8")
    help_jsx = (REPO / "frontend/components/help/AwardsHelp.jsx").read_text(encoding="utf-8")
    assert "return `${fmtNumber(value.compositeScore, 3)} score`;" in awards_jsx
    assert (
        "return `Score ${fmtNumber(value.compositeScore, 3)}${finish} · "
        "${value.wins}-${value.losses} · ${fmtNumber(value.pointsFor, 1)} PF`;"
    ) in shared_jsx
    assert "30% final finish, 25%" in help_jsx
    assert "It has no record or playoff requirement." in help_jsx


def test_official_award_path_never_reads_the_candidate():
    """Only the candidate may import the policy; the official path imports neither."""
    for rel in (
        "src/public_league/awards.py",
        "src/public_league/public_contract.py",
        "frontend/app/league/sections/awards.jsx",
        "frontend/app/league/shared.jsx",
    ):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert "moty_candidate_policy" not in text, rel
        assert "manager_of_the_year import" not in text, rel
    tree = ast.parse((REPO / "src/public_league/awards.py").read_text(encoding="utf-8"))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert "src.public_league.manager_of_the_year" not in imported


def test_no_unified_candidate_is_published_on_main():
    """No awards payload carries a unified score; when #1513 lands it must
    go through ``candidate_presentation`` (and update this assertion)."""
    snapshot = _with_player_points(build_test_snapshot())
    section = awards.build_section(snapshot)
    blob = repr(section)
    for marker in ("unifiedCandidate", "moty-unified", "measuredPoints"):
        assert marker not in blob


# ── 2. the Decision 12 interim rules ───────────────────────────────────────


def test_label_promotion_and_earliest_season():
    assert policy.CANDIDATE_LABEL == "validation-only candidate"
    assert policy.PROMOTION_STATE == "not_promoted"
    assert policy.EARLIEST_ELIGIBLE_OFFICIAL_SEASON == 2027
    full = [policy.ComponentEvidence(k, C, 50.0) for k in policy.APPROVED_WEIGHTS]
    for season in (2024, 2025, 2026):
        view = policy.candidate_presentation(season, full)
        assert view["label"] == "validation-only candidate"
        assert view["official"] is False
        assert view["seasonCouldBeOfficial"] is False
    assert policy.candidate_presentation(2027, full)["seasonCouldBeOfficial"] is True
    assert policy.candidate_presentation(2027, full)["official"] is False


def test_approved_weights_unchanged():
    assert dict(policy.APPROVED_WEIGHTS) == {"A": 0.40, "T": 0.25, "W": 0.15, "D": 0.10, "P": 0.10}
    assert sum(policy.APPROVED_WEIGHTS.values()) == pytest.approx(1.0)


def test_unavailable_trade_is_not_redistributed_and_no_100_point_score():
    comps = [
        policy.ComponentEvidence("A", C, 80.0),
        policy.ComponentEvidence("T", U, reason="trade_decision_time_value_incomplete"),
        policy.ComponentEvidence("W", P, 60.0, reason="faab_unpriced"),
        policy.ComponentEvidence("D", P, 40.0, reason="dropped_player_production_unknown"),
        policy.ComponentEvidence("P", C, 100.0),
    ]
    view = policy.candidate_presentation(2026, comps)
    assert view["definitiveScore"] is None
    assert view["complete"] is False
    # Measured: 0.40·80 + 0.10·100 = 42 out of 50; nothing rescaled.
    assert view["measuredPoints"] == pytest.approx(42.0)
    assert view["measurablePoints"] == pytest.approx(50.0)
    assert view["weights"]["T"] == 0.25
    assert view["possibleRange"] == {"low": pytest.approx(42.0), "high": pytest.approx(92.0)}
    t = next(r for r in view["components"] if r["key"] == "T")
    assert t["state"] == "UNAVAILABLE" and t["score"] is None


def test_missing_component_is_unavailable_never_zero():
    view = policy.candidate_presentation(2026, [policy.ComponentEvidence("A", C, 70.0)])
    states = {r["key"]: (r["state"], r["score"]) for r in view["components"]}
    assert states["T"] == ("UNAVAILABLE", None)
    assert view["definitiveScore"] is None
    with pytest.raises(ValueError):
        policy.ComponentEvidence("T", U, 0.0, reason="x")
    with pytest.raises(ValueError):
        policy.ComponentEvidence("W", P, 30.0)  # partial must say why


def test_range_not_apparent_winner():
    a = policy.candidate_presentation(
        2026,
        [
            policy.ComponentEvidence("A", C, 90.0),
            policy.ComponentEvidence("T", U, reason="trade_decision_time_value_incomplete"),
        ],
    )
    b = policy.candidate_presentation(2026, [policy.ComponentEvidence("A", C, 70.0)])
    c = policy.candidate_presentation(2026, [policy.ComponentEvidence("A", C, 0.0)])
    # 36 vs 28 measured, but 60 open points let b (and c) still finish first.
    assert policy.could_finish_first({"a": a, "b": b, "c": c}) == ["a", "b", "c"]
    full = {
        m: policy.candidate_presentation(
            2027, [policy.ComponentEvidence(k, C, s) for k in policy.APPROVED_WEIGHTS]
        )
        for m, s in (("x", 90.0), ("y", 50.0))
    }
    assert policy.could_finish_first(full) == ["x"]


def test_rebuilding_and_no_trade_seasons_not_penalized():
    assert policy.trade_component_state(trades=0, valued_at_decision_time=0) == (C, None)
    # Sold for picks, decision-time future value missing → UNAVAILABLE, not a low score.
    state, reason = policy.trade_component_state(trades=4, valued_at_decision_time=1)
    assert (state, reason) == (U, "trade_decision_time_value_incomplete")
    assert policy.trade_component_state(trades=3, valued_at_decision_time=3) == (C, None)


def test_faab_transfers_stay_unpriced():
    assert policy.trade_component_state(trades=2, valued_at_decision_time=2, faab_trades=1) == (
        U,
        "faab_transfer_unpriced",
    )
    assert policy.waiver_component_state(faab_spent_unpriced=True, dropped_players_unknown=0) == (
        P,
        "faab_unpriced",
    )


def test_unknown_dropped_player_production_stays_unknown():
    assert policy.waiver_component_state(faab_spent_unpriced=False, dropped_players_unknown=2) == (
        P,
        "dropped_player_production_unknown",
    )
    assert policy.waiver_component_state(faab_spent_unpriced=False, dropped_players_unknown=0) == (
        C,
        None,
    )


def test_point_in_time_values_only():
    trade_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert policy.value_is_point_in_time(datetime(2026, 7, 31, tzinfo=timezone.utc), trade_at)
    assert not policy.value_is_point_in_time(datetime(2026, 10, 18, tzinfo=timezone.utc), trade_at)


def test_draft_expectations_prior_period_only():
    assert policy.draft_expectation_is_out_of_sample([2023, 2024], 2025)
    assert not policy.draft_expectation_is_out_of_sample([2024, 2025], 2025)
    assert not policy.draft_expectation_is_out_of_sample([], 2025)


def test_policy_module_never_promotes():
    src = (REPO / "src/public_league/moty_candidate_policy.py").read_text(encoding="utf-8")
    assert not re.search(r'"official":\s*True', src)
    assert "OFFICIAL_FROM_SEASON" not in src
