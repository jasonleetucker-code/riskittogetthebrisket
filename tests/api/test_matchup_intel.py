"""`src/api/matchup_intel.py` — private pregame matchup intelligence (W1-14/W1-15).

The assembly owns no arithmetic, so what is worth pinning is the boundary
behaviour: which team it answers about, what it does when the inputs are
thin, and whether the lineage it publishes actually describes the numbers
beside it. A win probability with no stated projection source or coverage
is a number, not intelligence.
"""

from __future__ import annotations

import unittest
from unittest import mock

from src.api import matchup_intel

SLOTS = ["QB", "RB", "RB", "WR", "WR", "FLEX"]

LEAGUE = {
    "settings": {"best_ball": 1, "league_average_match": 1, "num_teams": 2},
    "roster_positions": SLOTS,
    "scoring_settings": {"rec": 1.0},
}

USERS = [
    {"user_id": "own-A", "display_name": "Ann", "metadata": {"team_name": "Alpha Squad"}},
    # No custom team name — the display name must carry through, not a blank.
    {"user_id": "own-B", "display_name": "Bob", "metadata": {}},
]

ROSTERS = [
    {"roster_id": 1, "owner_id": "own-A", "players": ["p1", "p2", "p3"]},
    {"roster_id": 2, "owner_id": "own-B", "players": ["p4", "p5", "p6"]},
]

MATCHUPS = [
    {"roster_id": 1, "matchup_id": 1, "points": 0},
    {"roster_id": 2, "matchup_id": 1, "points": 0},
]

PLAYERS = {
    "p1": {"full_name": "Ann Alpha", "position": "QB", "fantasy_positions": ["QB"]},
    "p2": {"full_name": "Bob Bravo", "position": "RB", "fantasy_positions": ["RB"]},
    "p3": {"full_name": "Cy Charlie", "position": "WR", "fantasy_positions": ["WR"]},
    "p4": {"full_name": "Dee Delta", "position": "WR", "fantasy_positions": ["WR"]},
    "p5": {"full_name": "Eve Echo", "position": "RB", "fantasy_positions": ["RB"]},
    "p6": {"full_name": "Fay Foxtrot", "position": "QB", "fantasy_positions": ["QB"]},
}

ESTIMATES = {
    "ann alpha": 20.0,
    "bob bravo": 12.0,
    "cy charlie": 11.0,
    "dee delta": 10.0,
    "eve echo": 9.0,
    "fay foxtrot": 18.0,
}


def _patch_fetch(matchups=None):
    return mock.patch.object(
        matchup_intel,
        "_fetch_league_week",
        return_value=matchup_intel._LeagueFetch(
            league=LEAGUE,
            users=USERS,
            rosters=ROSTERS,
            matchups=MATCHUPS if matchups is None else matchups,
            players=PLAYERS,
            fetched_at=1_700_000_000.0,
        ),
    )


def _patch_estimates(estimates=None, label="test:ensemble"):
    return mock.patch.object(
        matchup_intel,
        "_resolve_estimates",
        return_value=(
            dict(ESTIMATES if estimates is None else estimates),
            label,
            ("clayProjections",),
            (),
        ),
    )


def _build(**over):
    kwargs = dict(
        league_key="test_league",
        sleeper_league_id="L1",
        owner_id="own-A",
        season=2026,
        week=1,
        contract=None,
        team_count=2,
        roster_settings={"starters": {"QB": 1, "RB": 2, "WR": 2, "FLEX": 1}},
        draws=200,
        seed=4,
    )
    kwargs.update(over)
    return matchup_intel.build_matchup_intel(**kwargs)


class MatchupIdentityTests(unittest.TestCase):
    def test_it_answers_about_the_requested_team_and_names_the_opponent(self) -> None:
        with _patch_fetch(), _patch_estimates():
            out = _build()
        self.assertEqual(out["team"]["ownerId"], "own-A")
        self.assertEqual(out["team"]["teamName"], "Alpha Squad")
        self.assertEqual(out["opponent"]["ownerId"], "own-B")
        self.assertEqual(out["mode"], "pregame")

    def test_a_manager_with_no_custom_team_name_shows_their_display_name(self) -> None:
        # Not a blank, and not a fabricated one.
        with _patch_fetch(), _patch_estimates():
            out = _build()
        self.assertEqual(out["opponent"]["teamName"], "Bob")

    def test_an_owner_with_no_roster_is_refused_not_answered_about(self) -> None:
        with _patch_fetch(), _patch_estimates():
            with self.assertRaises(matchup_intel.TeamNotInLeague):
                _build(owner_id="own-Z")

    def test_no_scheduled_opponent_is_null_and_said_out_loud(self) -> None:
        with _patch_fetch(matchups=[]), _patch_estimates():
            out = _build()
        self.assertIsNone(out["opponent"])
        self.assertTrue(any("no scheduled opponent" in n for n in out["notes"]))


class ProbabilityTests(unittest.TestCase):
    def test_both_sides_get_an_outcome_and_they_are_complementary(self) -> None:
        with _patch_fetch(), _patch_estimates():
            out = _build()
        a = out["team"]["outcome"]
        b = out["opponent"]["outcome"]
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        total = a["winMatchupPct"] + b["winMatchupPct"] + a["tieMatchupPct"]
        self.assertAlmostEqual(total, 100.0, delta=0.05)

    def test_no_projections_yields_no_probability_rather_than_fifty_percent(self) -> None:
        with _patch_fetch(), _patch_estimates(estimates={}, label=None):
            out = _build()
        self.assertIsNone(out["team"]["outcome"])
        self.assertIsNone(out["lineage"]["simulation"])
        self.assertEqual(out["lineage"]["estimateCoverage"], {"priced": 0, "active": 6})
        self.assertTrue(any("no projection snapshot" in n for n in out["notes"]))

    def test_an_unpriced_player_is_reported_on_his_own_side(self) -> None:
        thin = {k: v for k, v in ESTIMATES.items() if k != "cy charlie"}
        with _patch_fetch(), _patch_estimates(estimates=thin):
            out = _build()
        self.assertIn("p3", out["team"]["unpricedPlayerIds"])
        self.assertNotIn("p3", out["opponent"]["unpricedPlayerIds"])


class ExpectedLineupTests(unittest.TestCase):
    def test_the_mean_lineup_is_filled_from_the_leagues_own_slots(self) -> None:
        with _patch_fetch(), _patch_estimates():
            out = _build()
        lineup = out["team"]["expectedLineup"]
        filled = {s["slot"] for s in lineup["slots"]}
        self.assertTrue(filled.issubset(set(SLOTS)))
        self.assertEqual(
            lineup["projectedTotal"],
            round(sum(s["projectedPoints"] for s in lineup["slots"]), 2),
        )

    def test_an_unpriced_player_never_enters_the_lineup_pool(self) -> None:
        # He would otherwise be a 0.0 the solver could seat on a thin roster.
        thin = {k: v for k, v in ESTIMATES.items() if k != "cy charlie"}
        with _patch_fetch(), _patch_estimates(estimates=thin):
            out = _build()
        lineup = out["team"]["expectedLineup"]
        self.assertIn("p3", lineup["unpricedPlayerIds"])
        self.assertNotIn("p3", [s["playerId"] for s in lineup["slots"]])


class RefusalTests(unittest.TestCase):
    def test_a_week_that_has_begun_is_its_own_error(self) -> None:
        started = [dict(MATCHUPS[0], points=14.2), MATCHUPS[1]]
        with _patch_fetch(matchups=started), _patch_estimates():
            with self.assertRaises(matchup_intel.WeekInProgress):
                _build()

    def test_no_rosters_is_refused(self) -> None:
        empty = matchup_intel._LeagueFetch(
            league=LEAGUE, users=USERS, rosters=[], matchups=[], players=PLAYERS, fetched_at=0.0
        )
        with mock.patch.object(matchup_intel, "_fetch_league_week", return_value=empty):
            with self.assertRaises(matchup_intel.MatchupIntelError):
                _build()


class LineageTests(unittest.TestCase):
    """W1-15: the numbers must arrive with their provenance attached."""

    def test_lineage_names_the_projection_source_and_its_horizon_caveat(self) -> None:
        with _patch_fetch(), _patch_estimates():
            out = _build()
        lin = out["lineage"]
        self.assertEqual(lin["projectionSource"], "test:ensemble")
        self.assertIn("WEEKLY", lin["projectionHorizonNote"])
        self.assertEqual(lin["projectionSourcesLoaded"], ["clayProjections"])

    def test_the_horizon_caveat_is_absent_when_there_is_no_source(self) -> None:
        # A caveat about a projection that does not exist would be noise.
        with _patch_fetch(), _patch_estimates(estimates={}, label=None):
            out = _build()
        self.assertIsNone(out["lineage"]["projectionSource"])
        self.assertIsNone(out["lineage"]["projectionHorizonNote"])

    def test_lineage_carries_the_league_rules_it_actually_simulated(self) -> None:
        with _patch_fetch(), _patch_estimates():
            out = _build()
        lin = out["lineage"]
        self.assertTrue(lin["bestBall"])
        self.assertIs(lin["medianEnabled"], True)
        self.assertEqual(lin["teamCount"], 2)
        self.assertEqual(lin["starterSlotSource"], "sleeper_roster_positions")

    def test_the_unverified_threshold_semantics_travel_with_the_answer(self) -> None:
        # The median leg's host semantics are unverified (W1-23 is BLOCKED),
        # and a private surface must not present it as settled.
        with _patch_fetch(), _patch_estimates():
            out = _build()
        sim = out["lineage"]["simulation"]
        self.assertFalse(sim["thresholdSemanticsVerified"])
        self.assertEqual(sim["thresholdSemantics"], "median")
        self.assertEqual(sim["draws"], 200)


class ArchiveEvidenceTests(unittest.TestCase):
    """W1-26 — the pregame archive's own timestamp travels with the answer.

    The archive is the ONLY record of what was knowable before the outcome,
    so a surface that silently shows nothing when nothing was captured
    cannot be told apart from one whose capture ran. The three states stay
    distinct here rather than in the renderer.
    """

    def test_nothing_captured_is_its_own_state(self) -> None:
        with _patch_fetch(), _patch_estimates():
            out = _build()
        arch = out["lineage"]["archive"]
        # No archive on disk for a synthetic league — and that is a real
        # answer, not an error.
        self.assertEqual(arch["state"], "not_captured")
        self.assertEqual(arch["teamsCaptured"], 0)

    def test_an_unreadable_archive_is_not_reported_as_empty(self) -> None:
        with (
            _patch_fetch(),
            _patch_estimates(),
            mock.patch(
                "src.ros.game_day_archive.load_snapshots_for_week",
                side_effect=PermissionError("nope"),
            ),
        ):
            out = _build()
        arch = out["lineage"]["archive"]
        self.assertEqual(arch["state"], "unreadable")
        self.assertIn("PermissionError", arch["reason"])

    def test_a_captured_week_reports_the_earliest_stamp(self) -> None:
        # A later capture is a DIFFERENT observation, not a fresher version
        # of the same one, so the pregame evidence is the earliest.
        class _Snap:
            def __init__(self, at, kind="pregame"):
                self.captured_at = at
                self.capture_kind = kind

        snaps = [_Snap("2026-09-09T18:02:11+00:00"), _Snap("2026-09-09T20:30:00+00:00")]
        with (
            _patch_fetch(),
            _patch_estimates(),
            mock.patch("src.ros.game_day_archive.load_snapshots_for_week", return_value=snaps),
        ):
            out = _build()
        arch = out["lineage"]["archive"]
        self.assertEqual(arch["state"], "captured")
        self.assertEqual(arch["teamsCaptured"], 2)
        self.assertEqual(arch["capturedAt"], "2026-09-09T18:02:11+00:00")
        self.assertEqual(arch["latestCapturedAt"], "2026-09-09T20:30:00+00:00")
        self.assertEqual(arch["captureKinds"], ["pregame"])
