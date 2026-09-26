"""Live team-strength fallback (2026-09).

``team_ros_strength`` -- 41% of the Power Rankings weight vector -- used
to hard-depend on a single scheduled-batch-written file
(``data/ros/team_strength/latest.json``), with no fallback when that
file was missing (a fresh deploy, a cold-start window, a failed scrape
cycle). This file pins the repair:

    * ``compute_team_strength_from_snapshot`` -- the PRIMARY fallback,
      computed live from a ``PublicLeagueSnapshot`` already in hand
      (current-season rosters + ``snapshot.nfl_players``), no network.
    * ``compute_team_strength_live`` -- the SECOND-TIER fallback for
      callers with no snapshot, via a cached Sleeper overlay fetch.
    * ``load_or_compute_team_strength`` -- the one read-side entry
      point: persisted file -> snapshot tier -> overlay tier, and it
      prefers the persisted file when present.

Same resilience pattern ``src/api/roster_intelligence.py`` already
applies to the sibling dynasty-value Team Strength concept, applied here
to the ROS-production concept this module owns.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.api import league_registry
from src.ros import team_strength
from tests.ros.test_power_v2 import _make_snapshot


def _fake_cfg(starters=None):
    return league_registry.LeagueConfig(
        key="test_league",
        display_name="Test League",
        sleeper_league_id="test-sleeper-id",
        scoring_profile="test",
        roster_settings={"starters": starters if starters is not None else {"WR": 1}},
        idp_enabled=False,
    )


def _aggregate(pairs):
    """pairs: {canonical player name (lowercase, matching the hydrated
    roster player's normalized name): rosValue}"""
    return [
        {"canonicalName": name, "position": "WR", "rosValue": val, "confidence": 0.9}
        for name, val in pairs.items()
    ]


class TestComputeTeamStrengthFromSnapshot(unittest.TestCase):
    def _snapshot_with_players(self):
        rosters = [
            {"owner_id": "alpha", "roster_id": 1},
            {"owner_id": "beta", "roster_id": 2},
        ]
        snapshot = _make_snapshot(rosters=rosters)
        for roster in snapshot.current_season.rosters:
            roster["players"] = [f"p-{roster['owner_id']}"]
        # ``full_name`` here is what ``hydrate_roster_players`` runs
        # through ``normalize_player_name`` to build the join key --
        # the aggregate fixture below must produce the SAME normalized
        # name (lowercased "alphaplayer"/"betaplayer") or the join misses
        # and every player prices at 0 regardless of rosValue.
        snapshot.nfl_players = {
            "p-alpha": {"full_name": "Alphaplayer", "position": "WR", "fantasy_positions": ["WR"]},
            "p-beta": {"full_name": "Betaplayer", "position": "WR", "fantasy_positions": ["WR"]},
        }
        return snapshot

    def test_computes_real_rows_from_snapshot_alone_no_network(self):
        snapshot = self._snapshot_with_players()
        agg = _aggregate({"alphaplayer": 90.0, "betaplayer": 30.0})
        with (
            patch.object(league_registry, "get_default_league", return_value=_fake_cfg()),
            patch.object(league_registry, "get_league_by_key", return_value=_fake_cfg()),
            patch.object(team_strength, "load_ros_aggregate_players", return_value=agg),
        ):
            rows = team_strength.compute_team_strength_from_snapshot(snapshot)
        self.assertEqual(len(rows), 2)
        by_owner = {r["ownerId"]: r for r in rows}
        self.assertIn("alpha", by_owner)
        self.assertIn("beta", by_owner)
        self.assertGreater(
            by_owner["alpha"]["teamRosStrength"], by_owner["beta"]["teamRosStrength"]
        )

    def test_returns_empty_when_no_league_config_resolvable(self):
        snapshot = self._snapshot_with_players()
        with (
            patch.object(league_registry, "get_default_league", return_value=None),
            patch.object(league_registry, "get_league_by_key", return_value=None),
        ):
            rows = team_strength.compute_team_strength_from_snapshot(snapshot)
        self.assertEqual(rows, [])

    def test_returns_empty_when_no_starter_slots_configured(self):
        snapshot = self._snapshot_with_players()
        empty_cfg = _fake_cfg(starters={})
        with (
            patch.object(league_registry, "get_default_league", return_value=empty_cfg),
            patch.object(league_registry, "get_league_by_key", return_value=empty_cfg),
        ):
            rows = team_strength.compute_team_strength_from_snapshot(snapshot)
        self.assertEqual(rows, [])

    def test_returns_empty_when_ros_aggregate_missing(self):
        snapshot = self._snapshot_with_players()
        with (
            patch.object(league_registry, "get_default_league", return_value=_fake_cfg()),
            patch.object(league_registry, "get_league_by_key", return_value=_fake_cfg()),
            patch.object(team_strength, "load_ros_aggregate_players", return_value=[]),
        ):
            rows = team_strength.compute_team_strength_from_snapshot(snapshot)
        self.assertEqual(rows, [])

    def test_returns_empty_when_no_current_season(self):
        empty_snapshot = _make_snapshot(rosters=[])
        rows = team_strength.compute_team_strength_from_snapshot(empty_snapshot)
        self.assertEqual(rows, [])

    def test_never_raises_on_a_malformed_roster(self):
        """Defensive: a roster missing ``players`` entirely must not crash
        the fallback -- it hydrates to an empty roster, not an exception."""
        rosters = [{"owner_id": "alpha", "roster_id": 1}]
        snapshot = _make_snapshot(rosters=rosters)
        # Deliberately no `players` key.  A usable NFL dump IS set: without
        # one the fallback now refuses outright (D1, 2026-09-26 -- an empty
        # dump scores every player zero), which would hide the malformed-
        # roster path this test exists to exercise.
        snapshot.nfl_players = {"p-alpha": {"full_name": "Alpha Player", "position": "WR"}}
        agg = _aggregate({"p-alpha": 90.0})
        with (
            patch.object(league_registry, "get_default_league", return_value=_fake_cfg()),
            patch.object(league_registry, "get_league_by_key", return_value=_fake_cfg()),
            patch.object(team_strength, "load_ros_aggregate_players", return_value=agg),
        ):
            rows = team_strength.compute_team_strength_from_snapshot(snapshot)
        # Does not raise; produces a degenerate but well-formed row.
        self.assertEqual(len(rows), 1)


class TestComputeTeamStrengthLiveNeverHitsNetworkInTests(unittest.TestCase):
    def test_returns_empty_with_no_resolvable_league(self):
        with (
            patch.object(league_registry, "get_default_league", return_value=None),
            patch.object(league_registry, "get_league_by_key", return_value=None),
        ):
            rows = team_strength.compute_team_strength_live()
        self.assertEqual(rows, [])

    def test_returns_empty_and_never_calls_fetch_sleeper_overlay_with_no_aggregate(self):
        from src.api import sleeper_overlay

        calls = []
        with (
            patch.object(league_registry, "get_default_league", return_value=_fake_cfg()),
            patch.object(league_registry, "get_league_by_key", return_value=_fake_cfg()),
            patch.object(team_strength, "load_ros_aggregate_players", return_value=[]),
            patch.object(
                sleeper_overlay,
                "fetch_sleeper_overlay",
                lambda **k: calls.append(k) or {"teams": []},
            ),
        ):
            rows = team_strength.compute_team_strength_live()
        self.assertEqual(rows, [])
        self.assertEqual(calls, [], "must short-circuit on a missing aggregate before any fetch")

    def test_uses_the_injected_nfl_players_without_a_second_fetch(self):
        from src.api import sleeper_overlay
        from src.public_league import sleeper_client

        agg = _aggregate({"p1": 90.0})
        overlay_teams = {
            "teams": [
                {"ownerId": "alpha", "roster_id": 1, "name": "Alpha", "playerIds": ["1"]},
            ]
        }
        fetch_calls = []
        with (
            patch.object(league_registry, "get_default_league", return_value=_fake_cfg()),
            patch.object(league_registry, "get_league_by_key", return_value=_fake_cfg()),
            patch.object(team_strength, "load_ros_aggregate_players", return_value=agg),
            patch.object(sleeper_overlay, "fetch_sleeper_overlay", return_value=overlay_teams),
            patch.object(
                sleeper_client,
                "fetch_nfl_players",
                lambda: fetch_calls.append(1) or {},
            ),
        ):
            rows = team_strength.compute_team_strength_live(
                nfl_players={"1": {"full_name": "Player One", "position": "WR"}}
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(fetch_calls, [], "an injected nfl_players dict must skip the 5MB fetch")


class TestLoadOrComputeTeamStrengthPrecedence(unittest.TestCase):
    def test_prefers_the_persisted_file_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            target = tmp_root / "team_strength" / "latest.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(
                    [
                        {
                            "ownerId": "persisted-owner",
                            "teamRosStrength": 42.0,
                            "startingLineupScore": 42.0,
                        }
                    ]
                )
            )
            with patch.object(team_strength, "ROS_DATA_DIR", tmp_root):
                rows = team_strength.load_or_compute_team_strength()
        self.assertEqual(
            rows,
            [{"ownerId": "persisted-owner", "teamRosStrength": 42.0, "startingLineupScore": 42.0}],
        )

    def test_falls_back_to_snapshot_tier_when_file_missing(self):
        rosters = [{"owner_id": "alpha", "roster_id": 1}]
        snapshot = _make_snapshot(rosters=rosters)
        for roster in snapshot.current_season.rosters:
            roster["players"] = ["p-alpha"]
        snapshot.nfl_players = {"p-alpha": {"full_name": "Alpha Player", "position": "WR"}}
        agg = _aggregate({"alpha player": 50.0})
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(team_strength, "ROS_DATA_DIR", Path(tmp)),
                patch.object(league_registry, "get_default_league", return_value=_fake_cfg()),
                patch.object(league_registry, "get_league_by_key", return_value=_fake_cfg()),
                patch.object(team_strength, "load_ros_aggregate_players", return_value=agg),
            ):
                rows = team_strength.load_or_compute_team_strength(snapshot=snapshot, persist=False)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ownerId"], "alpha")

    def test_returns_empty_list_when_every_tier_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(team_strength, "ROS_DATA_DIR", Path(tmp)),
                patch.object(league_registry, "get_default_league", return_value=None),
                patch.object(league_registry, "get_league_by_key", return_value=None),
            ):
                rows = team_strength.load_or_compute_team_strength()
        self.assertEqual(rows, [])

    def test_never_raises_on_total_failure(self):
        """The fallback's whole purpose is to keep the caller safe --
        confirm it degrades to [] rather than propagating an exception
        even when the league registry itself is broken."""
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(team_strength, "ROS_DATA_DIR", Path(tmp)),
                patch.object(
                    league_registry,
                    "get_default_league",
                    side_effect=RuntimeError("registry exploded"),
                ),
            ):
                try:
                    rows = team_strength.load_or_compute_team_strength()
                except RuntimeError:
                    self.fail("load_or_compute_team_strength must never raise")
        self.assertEqual(rows, [])

    def test_stale_persisted_file_is_not_trusted(self):
        """A persisted snapshot older than the freshness budget must not
        be served -- it must fall through exactly as if the file were
        missing.  Confirmed via ``test_returns_empty_list_when_every_tier_fails``'s
        own registry-mocking pattern (every fallback tier also fails),
        so a non-empty result would only be explainable by the stale
        file having been trusted.
        """
        import os
        import time

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            target = tmp_root / "team_strength" / "latest.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(
                    [
                        {
                            "ownerId": "stale-owner",
                            "teamRosStrength": 99.0,
                            "startingLineupScore": 99.0,
                        }
                    ]
                )
            )
            # 7 hours old -- past the 6-hour freshness budget.
            stale_time = time.time() - 7 * 3600
            os.utime(target, (stale_time, stale_time))
            with (
                patch.object(team_strength, "ROS_DATA_DIR", tmp_root),
                patch.object(league_registry, "get_default_league", return_value=None),
                patch.object(league_registry, "get_league_by_key", return_value=None),
            ):
                rows = team_strength.load_or_compute_team_strength()
        self.assertEqual(rows, [])

    def test_fresh_persisted_file_within_budget_is_still_trusted(self):
        """The staleness guard must not be so aggressive it rejects a
        file the scheduled refresh legitimately just wrote."""
        import os
        import time

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            target = tmp_root / "team_strength" / "latest.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(
                    [
                        {
                            "ownerId": "fresh-owner",
                            "teamRosStrength": 88.0,
                            "startingLineupScore": 88.0,
                        }
                    ]
                )
            )
            # 1 hour old -- comfortably within the 6-hour budget.
            fresh_time = time.time() - 1 * 3600
            os.utime(target, (fresh_time, fresh_time))
            with patch.object(team_strength, "ROS_DATA_DIR", tmp_root):
                rows = team_strength.load_or_compute_team_strength()
        self.assertEqual(
            rows, [{"ownerId": "fresh-owner", "teamRosStrength": 88.0, "startingLineupScore": 88.0}]
        )

    def test_two_leagues_do_not_collide_on_one_persisted_file(self):
        """Before this fix, every caller of ``load_or_compute_team_strength``
        with no ``league_key`` (which was most of them) read/wrote the
        SAME default-league path regardless of which league was actually
        being computed.  Two distinct league keys must resolve to two
        distinct files."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            with patch.object(team_strength, "ROS_DATA_DIR", tmp_root):
                team_strength.write_team_strength_snapshot(
                    [
                        {
                            "ownerId": "league-a-owner",
                            "teamRosStrength": 10.0,
                            "startingLineupScore": 10.0,
                        }
                    ],
                    league_key="league_a",
                )
                team_strength.write_team_strength_snapshot(
                    [
                        {
                            "ownerId": "league-b-owner",
                            "teamRosStrength": 20.0,
                            "startingLineupScore": 20.0,
                        }
                    ],
                    league_key="league_b",
                )
                rows_a = team_strength.load_or_compute_team_strength("league_a")
                rows_b = team_strength.load_or_compute_team_strength("league_b")
        self.assertEqual(
            rows_a,
            [{"ownerId": "league-a-owner", "teamRosStrength": 10.0, "startingLineupScore": 10.0}],
        )
        self.assertEqual(
            rows_b,
            [{"ownerId": "league-b-owner", "teamRosStrength": 20.0, "startingLineupScore": 20.0}],
        )
        self.assertNotEqual(rows_a, rows_b)

    def test_persist_writes_atomically_and_is_readable_on_the_next_call(self):
        rosters = [{"owner_id": "alpha", "roster_id": 1}]
        snapshot = _make_snapshot(rosters=rosters)
        for roster in snapshot.current_season.rosters:
            roster["players"] = ["p-alpha"]
        snapshot.nfl_players = {"p-alpha": {"full_name": "Alpha Player", "position": "WR"}}
        agg = _aggregate({"alpha player": 50.0})
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(team_strength, "ROS_DATA_DIR", Path(tmp)),
                patch.object(league_registry, "get_default_league", return_value=_fake_cfg()),
                patch.object(league_registry, "get_league_by_key", return_value=_fake_cfg()),
                patch.object(team_strength, "load_ros_aggregate_players", return_value=agg),
            ):
                first = team_strength.load_or_compute_team_strength(snapshot=snapshot, persist=True)
                self.assertEqual(len(first), 1)
                persisted = team_strength.load_team_strength_snapshot()
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted[0]["ownerId"], "alpha")


if __name__ == "__main__":
    unittest.main()
