"""W18-F002 RED — a cross-league sleeper block must not be a chimera.

On the ``sleeper_matches=False`` branch (``server.py`` ~3466-3486) the
overlay carries ``positions``, ``playerIds``, ``idToPlayer``,
``scoringSettings``, ``rosterPositions`` and ``leagueSettings`` forward from
the LOADED league, lays the requested league's ``teams``/``trades``/
``waivers`` on top, and then sets ``meta.sleeperDataReady = True``
unconditionally — while also stamping ``sleeperLoadedLeagueKey``, a pair the
documented contract says cannot co-occur.

The result is League B's real teams welded to League A's scoring card,
roster slots and team count, published as ready. ``useTeam.js`` reads the
flag, so the data-not-ready state that exists precisely for this case never
renders.

**This fixture is deliberately independent of the real dynasty_main →
dynasty_new pair.** That pair is only reachable today because W18-F001 lets
two differently-scored leagues share a profile label; once F001 is repaired
it will correctly 503 before the overlay runs. A regression that depended on
it would evaporate at exactly the moment it became load-bearing. So League A
and League B here are genuinely scoring-COMPATIBLE and differ only in
league-specific configuration — the case that must still work correctly
after F001, and the case that proves F002 is its own defect.

The invariant:

    sleeperDataReady is true IFF every league-specific field represented as
    ready belongs to the requested league.

NFL-wide maps (``positions``, ``playerIds``, ``idToPlayer`` — player id ↔
name for the whole league universe) are genuinely league-independent and may
be reused. Scoring settings, roster positions, league settings and
team-count semantics are league-specific and may not be inherited.

The repair is expected to give this merge a name and an owner so it can be
tested at all; today it is inline in a request handler, which is why no test
covers it.
"""

from __future__ import annotations

import unittest

# League A — the LOADED contract's league.
LOADED_SLEEPER = {
    "leagueId": "AAA",
    "teams": [{"rosterId": 1, "name": "A-Team"}],
    "positions": {"Josh Allen": "QB"},
    "playerIds": {"Josh Allen": "4017"},
    "idToPlayer": {"4017": "Josh Allen"},
    "scoringSettings": {"rec": 1.0, "pass_td": 4.0},
    "rosterPositions": ["QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX"] + ["BN"] * 52,
    "leagueSettings": {"num_teams": 12},
}

# League B — the REQUESTED league. Same scoring (so it survives the F001
# repair), different roster shape and team count.
OVERLAY_B = {
    "leagueId": "BBB",
    "teams": [{"rosterId": 9, "name": "B-Team"}],
    "trades": [],
    "waivers": [],
}
LEAGUE_B_TRUTH = {
    "scoringSettings": {"rec": 1.0, "pass_td": 4.0},
    "rosterPositions": ["QB", "RB", "WR", "TE", "FLEX"] + ["BN"] * 22,
    "leagueSettings": {"num_teams": 10},
}

#: League-specific: may never be inherited from another league.
LEAGUE_SPECIFIC = ("scoringSettings", "rosterPositions", "leagueSettings")
#: League-independent: safe to reuse across leagues.
NFL_WIDE = ("positions", "playerIds", "idToPlayer")


class TestTheMergeHasAnOwner(unittest.TestCase):
    """It must be callable to be testable. Today it is inline in a route."""

    def test_the_cross_league_merge_is_a_named_function(self):
        from src.api import sleeper_overlay

        self.assertTrue(
            hasattr(sleeper_overlay, "merge_cross_league_sleeper_block"),
            "the cross-league sleeper merge is still inline in server.py, so "
            "the readiness contract cannot be tested or owned",
        )


class TestNoChimeraIsEverPublishedAsReady(unittest.TestCase):
    def _merge(self, requested_config=None):
        from src.api.sleeper_overlay import merge_cross_league_sleeper_block

        return merge_cross_league_sleeper_block(
            loaded_sleeper=LOADED_SLEEPER,
            overlay=OVERLAY_B,
            requested_league_config=requested_config,
        )

    def test_the_forbidden_state_cannot_occur(self):
        """League B teams + League A config + ready:true."""
        block, ready = self._merge(requested_config=None)
        if ready:
            for field in LEAGUE_SPECIFIC:
                self.assertNotEqual(
                    block.get(field),
                    LOADED_SLEEPER[field],
                    f"{field} was inherited from the loaded league while the "
                    "block was published as ready — this is the chimera",
                )

    def test_unproven_league_config_fails_closed(self):
        """No requested-league truth available → not ready, and absent."""
        block, ready = self._merge(requested_config=None)
        self.assertFalse(
            ready,
            "sleeperDataReady was true without the requested league's own "
            "scoring settings, roster positions or league settings",
        )
        for field in LEAGUE_SPECIFIC:
            self.assertIsNone(
                block.get(field),
                f"{field} carried the loaded league's value forward instead of "
                "being left absent",
            )

    def test_requested_league_config_permits_a_legitimate_ready(self):
        """Preserve useful cross-league functionality where it is honest.

        When the requested league's own configuration IS available, the
        block is genuinely that league's and may publish ready.
        """
        block, ready = self._merge(requested_config=LEAGUE_B_TRUTH)
        self.assertTrue(ready, "a fully-owned requested-league block was refused")
        for field in LEAGUE_SPECIFIC:
            self.assertEqual(block.get(field), LEAGUE_B_TRUTH[field], field)

    def test_nfl_wide_maps_are_still_reused(self):
        """Degrading these would be an unnecessary loss — they are not
        league-specific."""
        block, _ = self._merge(requested_config=LEAGUE_B_TRUTH)
        for field in NFL_WIDE:
            self.assertEqual(block.get(field), LOADED_SLEEPER[field], field)

    def test_the_requested_leagues_teams_always_win(self):
        for cfg in (None, LEAGUE_B_TRUTH):
            block, _ = self._merge(requested_config=cfg)
            self.assertEqual(block.get("teams"), OVERLAY_B["teams"])
            self.assertEqual(block.get("leagueId"), "BBB")


class TestReadyRequiresACOMPLETEConfig(unittest.TestCase):
    """W18-F002, owner review gap 2 — truthy scoring is not a whole league.

    The first repair gated readiness on ``config.get("scoringSettings")``
    alone. But ``_fetch_league_config`` builds its block with
    ``list(info.get("roster_positions") or [])`` and
    ``dict(info.get("settings") or {})``, so a partial Sleeper response
    yields valid scoring beside ``rosterPositions: []`` and
    ``leagueSettings: {}`` — and that published as ready.

    What the consumers actually require, traced rather than assumed:

    * ``src/bdvm/league_config.py:204`` gates on
      ``if roster_positions and scoring:`` — an EMPTY list fails that test
      and silently falls through to the registry's advisory settings, so
      an empty array is not a complete league, it is a missing one.
    * the same builder reads ``league_settings["num_teams"]`` and raises
      ``LeagueConfigError`` at ``teams <= 1``, so ``leagueSettings`` with
      no team count cannot construct a league either.
    * ``frontend/lib/starter-slots.js`` puts live ``rosterPositions``
      ABOVE the registry in its truth ladder, so an empty live list would
      beat correct registry settings and produce an empty lineup.

    Hence: no empty-but-present value here is legitimately "complete".
    A Sleeper league always has lineup slots and a team count; their
    absence means the fetch did not produce them.
    """

    @staticmethod
    def _merge(config):
        from src.api.sleeper_overlay import merge_cross_league_sleeper_block

        return merge_cross_league_sleeper_block(
            loaded_sleeper=LOADED_SLEEPER,
            overlay=OVERLAY_B,
            requested_league_config=config,
        )

    def test_scoring_without_roster_positions_is_not_ready(self):
        block, ready = self._merge(
            {
                "scoringSettings": {"rec": 1.0},
                "rosterPositions": [],
                "leagueSettings": {"num_teams": 10},
            }
        )
        self.assertFalse(ready, "an empty lineup was published as a complete league")
        for field in LEAGUE_SPECIFIC:
            self.assertIsNone(block.get(field), field)

    def test_scoring_without_league_settings_is_not_ready(self):
        block, ready = self._merge(
            {
                "scoringSettings": {"rec": 1.0},
                "rosterPositions": ["QB", "RB"],
                "leagueSettings": {},
            }
        )
        self.assertFalse(ready, "an empty leagueSettings block was treated as complete")
        self.assertIsNone(block.get("leagueSettings"))

    def test_league_settings_without_a_team_count_is_not_ready(self):
        """``num_teams`` is what the consumer actually needs; a settings
        blob missing it cannot construct a league."""
        _, ready = self._merge(
            {
                "scoringSettings": {"rec": 1.0},
                "rosterPositions": ["QB", "RB"],
                "leagueSettings": {"taxi_slots": 5},
            }
        )
        self.assertFalse(ready)

    def test_a_one_team_league_is_not_ready(self):
        """``league_config`` raises at ``teams <= 1``; do not publish a
        block it will refuse."""
        _, ready = self._merge(
            {
                "scoringSettings": {"rec": 1.0},
                "rosterPositions": ["QB", "RB"],
                "leagueSettings": {"num_teams": 1},
            }
        )
        self.assertFalse(ready)

    def test_malformed_config_is_not_ready(self):
        for bad in (
            {
                "scoringSettings": "not a dict",
                "rosterPositions": ["QB"],
                "leagueSettings": {"num_teams": 10},
            },
            {
                "scoringSettings": {"rec": 1.0},
                "rosterPositions": "QB,RB",
                "leagueSettings": {"num_teams": 10},
            },
            {"scoringSettings": {"rec": 1.0}, "rosterPositions": ["QB"], "leagueSettings": []},
            "not a mapping at all",
            [],
        ):
            with self.subTest(repr(bad)[:40]):
                block, ready = self._merge(bad)
                self.assertFalse(ready)
                for field in LEAGUE_SPECIFIC:
                    self.assertIsNone(block.get(field), field)

    def test_a_complete_config_is_ready(self):
        """Non-vacuity: the strictness must not refuse a real league."""
        block, ready = self._merge(LEAGUE_B_TRUTH)
        self.assertTrue(ready)
        for field in LEAGUE_SPECIFIC:
            self.assertEqual(block.get(field), LEAGUE_B_TRUTH[field], field)


class TestTheTransportIsNotTheContract(unittest.TestCase):
    """``leagueConfig`` is how the overlay carries the requested league's
    own config across; it must not surface as a contract field, and it
    must not be a second way for config to reach the block unchecked."""

    def test_league_config_is_consumed_not_echoed(self):
        from src.api.sleeper_overlay import merge_cross_league_sleeper_block

        block, ready = merge_cross_league_sleeper_block(
            loaded_sleeper=LOADED_SLEEPER,
            overlay={**OVERLAY_B, "leagueConfig": LEAGUE_B_TRUTH},
            requested_league_config=None,
        )
        self.assertTrue(ready, "the overlay carried the requested league's own config")
        self.assertIsNone(block.get("leagueConfig"), "transport field leaked into the block")
        for field in LEAGUE_SPECIFIC:
            self.assertEqual(block.get(field), LEAGUE_B_TRUTH[field], field)

    def test_an_overlay_carrying_bare_league_fields_is_still_refused(self):
        """An overlay that puts scoringSettings at the top level — not
        under ``leagueConfig`` — must not slip past the ownership check
        just because the key happens to be spelled right."""
        from src.api.sleeper_overlay import merge_cross_league_sleeper_block

        block, ready = merge_cross_league_sleeper_block(
            loaded_sleeper=LOADED_SLEEPER,
            overlay={**OVERLAY_B, "scoringSettings": {"rec": 9.0}},
            requested_league_config=None,
        )
        self.assertFalse(ready)
        self.assertIsNone(block.get("scoringSettings"))


class TestTheDiagnosticIsNotTheFix(unittest.TestCase):
    """Dropping ``sleeperLoadedLeagueKey`` would hide the chimera, not fix it.

    Pinned so a future change cannot "resolve" the contradiction by
    deleting the field that reveals it.
    """

    def test_readiness_is_decided_by_ownership_not_by_a_diagnostic(self):
        from src.api.sleeper_overlay import merge_cross_league_sleeper_block

        block, ready = merge_cross_league_sleeper_block(
            loaded_sleeper=LOADED_SLEEPER,
            overlay=OVERLAY_B,
            requested_league_config=None,
        )
        self.assertFalse(ready)
        self.assertIsNone(block.get("scoringSettings"))


if __name__ == "__main__":
    unittest.main()
