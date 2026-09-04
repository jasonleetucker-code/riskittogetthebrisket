"""C5-GD-02b — the scheduled caller for the Game Day prediction archive.

Covers the resolution half (`src/ros/game_day_capture.py`): the pregame
window gate, best-ball slot eligibility across Superflex / FLEX / TE /
IDP, the IR+taxi subtraction, and the missing-estimate semantics the
archive's own contract requires.

Deliberately network-free — every Sleeper payload here is a literal, so
these run in the hard gate rather than under `livedata`.
"""

from __future__ import annotations

import pytest

from src.ros.game_day_archive import load_snapshots_for_week, record_snapshot
from src.ros.game_day_capture import (
    GameDayCaptureRefusal,
    build_capture,
    build_team_roster,
    estimate_index_from_ensemble,
    week_has_begun,
)

# A real-shaped Superflex + TE + IDP league: the shape dynasty_main
# actually runs (measured 2026-09-04: 21 lineup slots from Sleeper's
# roster_positions), trimmed to the slots these tests exercise.
_ROSTER_POSITIONS = [
    "QB",
    "RB",
    "RB",
    "WR",
    "WR",
    "TE",
    "FLEX",
    "SUPER_FLEX",
    "DL",
    "LB",
    "DB",
    "IDP_FLEX",
    "BN",
    "BN",
    "BN",
    "IR",
    "TAXI",
]

_PLAYERS_META = {
    "qb1": {"full_name": "Real Quarterback", "position": "QB", "fantasy_positions": ["QB"]},
    "rb1": {"full_name": "Real Runningback", "position": "RB", "fantasy_positions": ["RB"]},
    "wr1": {"full_name": "Real Receiver", "position": "WR", "fantasy_positions": ["WR"]},
    "te1": {"full_name": "Real Tightend", "position": "TE", "fantasy_positions": ["TE"]},
    "lb1": {"full_name": "Real Linebacker", "position": "LB", "fantasy_positions": ["LB"]},
    "dl1": {"full_name": "Real Lineman", "position": "DL", "fantasy_positions": ["DL", "LB"]},
    "k1": {"full_name": "Real Kicker", "position": "K", "fantasy_positions": ["K"]},
    "ir1": {"full_name": "Hurt Guy", "position": "WR", "fantasy_positions": ["WR"]},
    "taxi1": {"full_name": "Stashed Rookie", "position": "RB", "fantasy_positions": ["RB"]},
}

_LEAGUE = {
    "roster_positions": _ROSTER_POSITIONS,
    # A non-empty card so `scoring_fingerprint` returns a real identity.
    "scoring_settings": {"rec": 1.0, "pass_td": 4.0, "pass_yd": 0.04, "rush_td": 6.0},
}

_ROSTER = {
    "roster_id": 7,
    "players": ["qb1", "rb1", "wr1", "te1", "lb1", "dl1", "k1", "ir1", "taxi1"],
    "reserve": ["ir1"],
    "taxi": ["taxi1"],
}


def _slots():
    from src.ros.lineup import starter_slots_from_roster_positions

    return starter_slots_from_roster_positions(_ROSTER_POSITIONS)


# ── the pregame window gate ────────────────────────────────────────


def test_week_has_not_begun_before_kickoff():
    """Sleeper reports every team at 0.0 with empty player scores."""
    matchups = [
        {"roster_id": 1, "points": 0.0, "players_points": {}},
        {"roster_id": 2, "points": 0, "players_points": {"qb1": 0.0}},
    ]
    assert week_has_begun(matchups) is False


def test_week_has_begun_on_a_team_total():
    assert week_has_begun([{"roster_id": 1, "points": 12.4, "players_points": {}}]) is True


def test_week_has_begun_on_a_single_player_score():
    """The Thursday-night game alone closes the window, even while every
    team total is still rounding to zero."""
    matchups = [{"roster_id": 1, "points": 0.0, "players_points": {"qb1": 0.0, "rb1": 3.2}}]
    assert week_has_begun(matchups) is True


def test_absent_matchups_have_not_begun():
    assert week_has_begun(None) is False
    assert week_has_begun([]) is False


def test_malformed_scores_do_not_crash_the_gate():
    matchups = [{"points": "not-a-number", "players_points": {"x": None, "y": "nope"}}]
    assert week_has_begun(matchups) is False


def test_build_refuses_a_pregame_capture_after_kickoff():
    """The directive's hard rule: never reconstruct a 'pregame' snapshot
    once games have started and label it pregame."""
    with pytest.raises(GameDayCaptureRefusal) as exc:
        build_capture(
            league_key="dynasty_main",
            season=2026,
            week=1,
            capture_kind="pregame",
            league_payload=_LEAGUE,
            rosters=[_ROSTER],
            matchups=[{"roster_id": 1, "points": 44.0}],
            players_meta=_PLAYERS_META,
        )
    assert "already begun" in str(exc.value)


def test_in_game_capture_is_allowed_after_kickoff():
    """The gate is specific to the `pregame` claim — a later capture of a
    started week is exactly what `in_game` is for."""
    build = build_capture(
        league_key="dynasty_main",
        season=2026,
        week=1,
        capture_kind="in_game",
        league_payload=_LEAGUE,
        rosters=[_ROSTER],
        matchups=[{"roster_id": 1, "points": 44.0}],
        players_meta=_PLAYERS_META,
    )
    assert build.capture_kind == "in_game"
    assert len(build.teams) == 1


# ── best-ball lineup eligibility ───────────────────────────────────


def _eligibility(**kwargs):
    rows = build_team_roster(
        roster=_ROSTER,
        players_meta=_PLAYERS_META,
        starter_slots=_slots(),
        estimates=kwargs.get("estimates", {}),
        estimate_source_label=kwargs.get("label"),
    )
    return {r.player_id: r for r in rows}


def test_superflex_flex_te_and_idp_are_all_eligible():
    rows = _eligibility()
    for pid in ("qb1", "rb1", "wr1", "te1", "lb1", "dl1"):
        assert rows[pid].is_lineup_eligible is True, f"{pid} should fill a slot"


def test_a_position_the_league_starts_nowhere_is_not_eligible():
    """This league runs no K slot, so a kicker is rostered-but-unstartable
    — a real state, captured as data rather than dropped."""
    rows = _eligibility()
    assert rows["k1"].is_lineup_eligible is False
    assert "k1" in rows  # still captured


def test_ir_and_taxi_players_are_captured_but_not_eligible():
    """Sleeper lists IR and taxi players inside `players`; without
    subtracting them a stashed rookie reads as an available starter."""
    rows = _eligibility()
    assert rows["ir1"].is_lineup_eligible is False
    assert rows["taxi1"].is_lineup_eligible is False
    assert rows["ir1"].position == "WR"  # captured, with its real position


def test_a_hybrid_defender_is_eligible_through_its_second_position():
    """`dl1` ships as DL with fantasy_positions ["DL","LB"] — Sleeper
    evaluates eligibility over all of them."""
    rows = _eligibility()
    assert rows["dl1"].is_lineup_eligible is True


# ── missing is never zero ──────────────────────────────────────────


def test_uncovered_players_record_none_not_zero():
    rows = _eligibility(estimates={"real quarterback": 21.0}, label="ros_ensemble:X")
    assert rows["qb1"].point_estimate == 21.0
    assert rows["qb1"].estimate_source == "ros_ensemble:X"
    # Everyone else is genuinely uncovered.
    assert rows["rb1"].point_estimate is None
    assert rows["rb1"].estimate_source is None


def test_no_projection_snapshot_still_captures_every_roster():
    """A league with no projection source is still worth capturing:
    roster composition on the morning of Week 1 is itself perishable."""
    build = build_capture(
        league_key="dynasty_main",
        season=2026,
        week=1,
        capture_kind="pregame",
        league_payload=_LEAGUE,
        rosters=[_ROSTER],
        matchups=[],
        players_meta=_PLAYERS_META,
        estimates={},
        estimate_source_label=None,
    )
    have, total = build.estimate_coverage
    assert (have, total) == (0, 9)
    assert all(p.point_estimate is None for p in build.teams[0].roster)


def test_estimate_coverage_reports_partial_coverage():
    build = build_capture(
        league_key="dynasty_main",
        season=2026,
        week=1,
        capture_kind="pregame",
        league_payload=_LEAGUE,
        rosters=[_ROSTER],
        matchups=[],
        players_meta=_PLAYERS_META,
        estimates={"real quarterback": 21.0, "real receiver": 13.5},
        estimate_source_label="ros_ensemble:X",
    )
    assert build.estimate_coverage == (2, 9)


def test_a_zero_estimate_is_kept_as_a_real_claim():
    """0.0 means 'expected to score nothing', which is not the same
    statement as 'we have no estimate'."""
    rows = _eligibility(estimates={"real kicker": 0.0}, label="ros_ensemble:X")
    assert rows["k1"].point_estimate == 0.0
    assert rows["k1"].estimate_source == "ros_ensemble:X"


# ── fail-closed structural refusals ────────────────────────────────


def test_no_scoring_card_refuses_the_capture():
    with pytest.raises(ValueError, match="scoring card"):
        build_capture(
            league_key="dynasty_main",
            season=2026,
            week=1,
            capture_kind="pregame",
            league_payload={"roster_positions": _ROSTER_POSITIONS, "scoring_settings": {}},
            rosters=[_ROSTER],
            matchups=[],
            players_meta=_PLAYERS_META,
        )


def test_no_starter_slots_refuses_the_capture():
    """Without slots, `is_lineup_eligible` would be invented."""
    with pytest.raises(ValueError, match="starter slots"):
        build_capture(
            league_key="dynasty_main",
            season=2026,
            week=1,
            capture_kind="pregame",
            league_payload={
                "roster_positions": [],
                "scoring_settings": _LEAGUE["scoring_settings"],
            },
            rosters=[_ROSTER],
            matchups=[],
            players_meta=_PLAYERS_META,
            roster_settings={},
        )


def test_scoring_config_id_is_the_factual_fingerprint():
    """Not the `scoringProfile` label — W18-F001's whole point."""
    from src.league_comparison.sleeper_scoring import scoring_fingerprint

    build = build_capture(
        league_key="dynasty_main",
        season=2026,
        week=1,
        capture_kind="pregame",
        league_payload=_LEAGUE,
        rosters=[_ROSTER],
        matchups=[],
        players_meta=_PLAYERS_META,
    )
    assert build.scoring_config_id == scoring_fingerprint(_LEAGUE["scoring_settings"])


def test_an_empty_roster_is_reported_not_raised():
    build = build_capture(
        league_key="dynasty_main",
        season=2026,
        week=1,
        capture_kind="pregame",
        league_payload=_LEAGUE,
        rosters=[_ROSTER, {"roster_id": 9, "players": []}],
        matchups=[],
        players_meta=_PLAYERS_META,
    )
    assert len(build.teams) == 1
    assert any("no players" in n for n in build.notes)


def test_a_duplicate_player_id_is_collapsed_not_fatal():
    """The archive refuses a duplicate player_id outright; a Sleeper
    roster listing one twice is a host artifact, not two roster spots."""
    rows = build_team_roster(
        roster={"roster_id": 1, "players": ["qb1", "qb1", "rb1"]},
        players_meta=_PLAYERS_META,
        starter_slots=_slots(),
        estimates={},
        estimate_source_label=None,
    )
    assert [r.player_id for r in rows] == ["qb1", "rb1"]


def test_unknown_players_are_captured_with_an_empty_position():
    """An unmapped Sleeper id still occupies a roster spot. Its position
    stays empty rather than becoming a guess."""
    rows = build_team_roster(
        roster={"roster_id": 1, "players": ["ghost"]},
        players_meta=_PLAYERS_META,
        starter_slots=_slots(),
        estimates={},
        estimate_source_label=None,
    )
    assert len(rows) == 1
    assert rows[0].position == ""
    assert rows[0].is_lineup_eligible is False


# ── the estimate index ─────────────────────────────────────────────


def test_estimate_index_skips_rows_with_no_value():
    class _Obs:
        def __init__(self, k, v):
            self.player_key = k
            self.combined_league_scored_fpg = v

    idx = estimate_index_from_ensemble([_Obs("a", 12.0), _Obs("b", None), _Obs("", 3.0)])
    assert idx == {"a": 12.0}


# ── append-only, end to end through the real store ─────────────────


def test_capture_writes_once_and_refuses_the_rerun(tmp_path):
    """A retried cron must not overwrite the earlier observation — the
    earlier one is the better evidence."""
    from src.ros.game_day_archive import GameDayArchiveError

    build = build_capture(
        league_key="dynasty_main",
        season=2026,
        week=1,
        capture_kind="pregame",
        league_payload=_LEAGUE,
        rosters=[_ROSTER],
        matchups=[],
        players_meta=_PLAYERS_META,
    )
    team = build.teams[0]
    kwargs = dict(
        league_key=build.league_key,
        season=build.season,
        week=build.week,
        team_id=team.team_id,
        capture_kind=build.capture_kind,
        scoring_config_id=build.scoring_config_id,
        starter_slots=build.starter_slots,
        roster=team.roster,
        base_dir=tmp_path,
    )
    record_snapshot(**kwargs)
    with pytest.raises(GameDayArchiveError):
        record_snapshot(**kwargs)

    stored = load_snapshots_for_week("dynasty_main", 2026, 1, base_dir=tmp_path)
    assert len(stored) == 1
    assert stored[0].starter_slots == build.starter_slots
    assert len(stored[0].roster) == 9
