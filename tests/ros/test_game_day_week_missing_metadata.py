"""Regression coverage for W1-28 issue #1368.

A rostered player whose metadata row is absent is unknown evidence, not a
positively-known teamless dynasty stash. Missing metadata must never be
coerced to inactive/zero merely because schedule evidence exists for other
players.
"""

from src.ros.game_day_week import GameEvidence, resolve_scoring_week


LEAGUE = {"settings": {"best_ball": 1, "league_average_match": 1, "num_teams": 2}}


def test_missing_player_metadata_stays_unknown_and_blocks_final() -> None:
    result = resolve_scoring_week(
        league_key="test_league",
        league_payload=LEAGUE,
        rosters=[
            {"roster_id": 1, "players": ["missing_meta"]},
            {"roster_id": 2, "players": ["known_player"]},
        ],
        matchups=[
            {
                "roster_id": 1,
                "matchup_id": 1,
                "points": 10.0,
                "players_points": {},
            },
            {
                "roster_id": 2,
                "matchup_id": 1,
                "points": 5.0,
                "players_points": {"known_player": 5.0},
            },
        ],
        players_meta={
            "known_player": {
                "full_name": "Known Player",
                "position": "QB",
                "fantasy_positions": ["QB"],
                "team": "KC",
            }
        },
        starter_slots=["QB"],
        game_evidence={
            "KC": GameEvidence(
                state="completed",
                source="test:schedule",
                observed_at=1.0,
                kickoff_at=1.0,
            )
        },
        now=2.0,
    )

    team = next(team for team in result.week.teams if team.team_id == "1")
    player = next(player for player in team.players if player.player_id == "missing_meta")

    assert result.mode == "live"
    assert player.state == "unknown"
    assert player.points_scored is None
    assert player.projected_remaining is None
    assert any("game-state coverage incomplete" in note for note in result.week.notes)
