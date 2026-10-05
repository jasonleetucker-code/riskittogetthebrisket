"""Competitive Posture (#840 / C7-POST-01) — the canonical owner's properties.

Owner decision 2026-09-24: continuous evidence model; PUSH / HOLD / RETOOL /
REBUILD published only as an explained probabilistic classification with
confidence and components; no single hard threshold; HOLD when ambiguous;
never a veto.  Mapping owner-chosen 2026-10-03 (declared map + season timing,
PRIOR).  These tests pin the semantics, not fitted accuracy — nothing here is
fitted, and ``parameterStatus`` says so.
"""

from __future__ import annotations

import pytest

from src.roster_intel.window import (
    POSTURE_LABELS,
    CompetitiveWindow,
    WindowInputs,
    _softmax_affinities,
    competitive_posture,
    compute_window,
    season_timing,
)

OFFSEASON = season_timing(None, False, 11)
WEEK_1 = season_timing(1, True, 11)
DEADLINE = season_timing(11, True, 11)


def _window(comp: float, traj: float, *, source: str = "championshipOdds", ages: int = 10):
    aff = _softmax_affinities(comp, traj, 0.18)
    return CompetitiveWindow(aff, WindowInputs(comp, traj, source, ages), max(aff, key=aff.get))


def _post(comp, traj, timing=WEEK_1, **kw):
    return competitive_posture(_window(comp, traj, **kw), timing)


# ── Shape ────────────────────────────────────────────────────────────


def test_four_labels_sum_to_one_and_ship_their_components():
    out = _post(0.6, 0.5).to_dict()
    assert set(out["probabilities"]) == set(POSTURE_LABELS)
    assert sum(out["probabilities"].values()) == pytest.approx(1.0)
    comp = out["components"]
    assert {"directional", "labelStability", "window", "windowInputs", "timing"} <= set(comp)
    assert out["parameterStatus"] == "PRIOR" and out["isVerdict"] is False


# ── The addendum's posture-level scenarios ───────────────────────────


def test_strong_contender_pushes():
    assert _post(0.95, 0.45).label == "PUSH"


def test_old_high_probability_roster_pushes():
    assert _post(0.85, 0.15).label == "PUSH"


def test_old_weak_roster_rebuilds():
    assert _post(0.08, 0.25).label == "REBUILD"


def test_young_low_probability_roster_retools_around_its_core():
    assert _post(0.35, 0.85).label == "RETOOL"


def test_balanced_roster_holds():
    assert _post(0.55, 0.55).label == "HOLD"


def test_bubble_team_firms_up_as_the_deadline_approaches():
    early = _post(0.75, 0.5, WEEK_1)
    late = _post(0.75, 0.5, DEADLINE)
    assert late.label == early.label == "PUSH"
    assert late.confidence > early.confidence


def test_same_competitiveness_means_more_at_the_deadline_than_in_the_offseason():
    off = _post(0.15, 0.3, OFFSEASON)
    dl = _post(0.15, 0.3, DEADLINE)
    assert dl.probabilities["REBUILD"] > off.probabilities["REBUILD"]


def test_owning_ones_first_is_reported_and_changes_no_probability():
    w = _window(0.1, 0.3)
    owns = competitive_posture(w, WEEK_1, own_first_round_pick_held=True)
    traded = competitive_posture(w, WEEK_1, own_first_round_pick_held=False)
    assert owns.probabilities == traded.probabilities
    assert owns.to_dict()["components"]["ownFirstRoundPickHeld"] is True
    assert traded.to_dict()["components"]["ownFirstRoundPickHeld"] is False


# ── Missing is never a guess ─────────────────────────────────────────


def test_no_competitiveness_evidence_is_hold_not_a_direction():
    p = _post(0.5, 0.2, source="unavailable")
    assert p.label == "HOLD" and p.probabilities["HOLD"] == 1.0


def test_unknown_deadline_applies_no_sharpening_and_says_so():
    unknown = season_timing(6, True, None)
    assert unknown.progress is None
    p = _post(0.75, 0.5, unknown)
    assert any("timing unknown" in n for n in p.notes)
    assert p.probabilities == _post(0.75, 0.5, OFFSEASON).probabilities


def test_season_timing_resolves_only_facts():
    assert season_timing(None, False, 11).phase == "offseason"
    assert season_timing(12, True, 11).phase == "post_deadline"
    assert season_timing(6, True, 0).trade_deadline_week is None
    assert season_timing(1, True, 11).progress == 0.0
    assert season_timing(11, True, 11).progress == 1.0
    assert season_timing(None, None, 11).phase == "unknown"


def test_weaker_measurement_widens_the_hold_region():
    # Same placement: a lineup-score proxy is a weaker measurement than
    # simulated odds, so the posture must be at least as hesitant.
    odds = _post(0.62, 0.55, source="championshipOdds")
    proxy = _post(0.62, 0.55, source="lineupScoreRank")
    assert proxy.probabilities["HOLD"] >= odds.probabilities["HOLD"]


# ── No hard threshold: directions change only through HOLD ───────────


@pytest.mark.parametrize("traj", [0.2, 0.5, 0.8])
@pytest.mark.parametrize("timing", [OFFSEASON, WEEK_1, DEADLINE])
def test_competitiveness_sweep_never_jumps_between_directions(traj, timing):
    labels = [_post(c / 100, traj, timing).label for c in range(0, 101)]
    for a, b in zip(labels, labels[1:]):
        if a != b:
            assert "HOLD" in (a, b), f"{a} -> {b} without passing HOLD (traj={traj})"


def test_override_follows_stated_intent():
    from src.ros.lineup import RosterPlayer

    pool = [RosterPlayer(player_id="a", canonical_name="A", position="QB", ros_value=10.0)]
    w = compute_window("o", pool, ["QB"], override_state="rebuild")
    p = competitive_posture(w, WEEK_1)
    assert p.label == "REBUILD" and p.probabilities["HOLD"] == 0.0


# ── Inputs the posture reads ─────────────────────────────────────────


def test_zero_title_odds_ties_break_on_playoff_odds():
    from src.roster_intel.window import league_competitiveness

    rows = [
        {"ownerId": "champ", "championshipOdds": 0.99, "playoffOdds": 1.0},
        {"ownerId": "alive", "championshipOdds": 0.0, "playoffOdds": 0.98},
        {"ownerId": "out", "championshipOdds": 0.0, "playoffOdds": 0.0},
    ]
    alive, _ = league_competitiveness("alive", playoff_odds=rows)
    out, _ = league_competitiveness("out", playoff_odds=rows)
    assert alive > out


def test_title_odds_still_decide_when_they_differ():
    from src.roster_intel.window import league_competitiveness

    rows = [
        {"ownerId": "a", "championshipOdds": 0.30, "playoffOdds": 0.50},
        {"ownerId": "b", "championshipOdds": 0.20, "playoffOdds": 0.99},
    ]
    assert (
        league_competitiveness("a", playoff_odds=rows)[0]
        > league_competitiveness("b", playoff_odds=rows)[0]
    )


def _contract_with_picks(details_by_owner):
    teams = []
    for rid, (owner, details) in enumerate(details_by_owner.items(), start=1):
        teams.append({"ownerId": owner, "roster_id": rid, "name": owner, "pickDetails": details})
    return {"sleeper": {"teams": teams}}


def _pd(season, rnd, frm):
    return {"season": season, "round": rnd, "fromRosterId": frm}


def test_own_first_is_read_from_the_canonical_pick_fold():
    from src.api.gameplan import _own_first_round_pick_held

    c = _contract_with_picks(
        {
            "a": [_pd(2027, 1, 1), _pd(2028, 1, 1)],
            "b": [_pd(2027, 1, 1 + 10), _pd(2028, 1, 2)],  # traded its 2027 1st away
        }
    )
    assert _own_first_round_pick_held(c, "a") is True
    assert _own_first_round_pick_held(c, "b") is False


def test_own_first_is_unknown_when_any_inventory_is_unpublished():
    from src.api.gameplan import _own_first_round_pick_held

    c = _contract_with_picks({"a": [_pd(2027, 1, 1)], "b": None})
    assert _own_first_round_pick_held(c, "a") is None
