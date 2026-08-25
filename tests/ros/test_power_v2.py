"""Tests for the ROS-driven power-rankings v2.

Verifies the formula composition + handling of missing inputs +
graceful degradation when ROS team-strength snapshot is absent.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.public_league.identity import Manager, ManagerRegistry
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot
from src.ros import power_v2


class TestStreakScore(unittest.TestCase):
    def test_no_history_returns_neutral(self):
        self.assertEqual(power_v2._streak_score_from_outcomes([]), 0.5)

    def test_winning_streak_above_neutral(self):
        s = power_v2._streak_score_from_outcomes([1.0, 1.0, 1.0])
        self.assertGreater(s, 0.5)

    def test_losing_streak_below_neutral(self):
        s = power_v2._streak_score_from_outcomes([0.0, 0.0])
        self.assertLess(s, 0.5)

    def test_streak_caps_at_one(self):
        s = power_v2._streak_score_from_outcomes([1.0] * 20)
        self.assertLessEqual(s, 1.0)

    def test_streak_floors_at_zero(self):
        s = power_v2._streak_score_from_outcomes([0.0] * 20)
        self.assertGreaterEqual(s, 0.0)


class TestPercentile(unittest.TestCase):
    def test_top_value_yields_high_percentile(self):
        values = [10, 20, 30, 40, 50]
        self.assertGreater(power_v2._percentile(values, 50), 0.8)

    def test_bottom_value_low_percentile(self):
        values = [10, 20, 30, 40, 50]
        self.assertLess(power_v2._percentile(values, 10), 0.2)

    def test_empty_returns_zero(self):
        self.assertEqual(power_v2._percentile([], 5), 0.0)


class TestLoadTeamStrength(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        with patch.object(power_v2, "ROS_DATA_DIR", Path("/nonexistent")):
            self.assertEqual(power_v2._load_team_strength_percentiles(), {})

    def test_loads_and_percentiles(self):
        # Use a temp dir so we never touch the production snapshot —
        # under the real ROS_DATA_DIR this test would wipe live data.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            target = tmp_root / "team_strength" / "latest.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(
                    [
                        {"ownerId": "alpha", "teamRosStrength": 90.0},
                        {"ownerId": "beta", "teamRosStrength": 60.0},
                        {"ownerId": "gamma", "teamRosStrength": 30.0},
                    ]
                )
            )
            with patch.object(power_v2, "ROS_DATA_DIR", tmp_root):
                result = power_v2._load_team_strength_percentiles()
            self.assertEqual(set(result.keys()), {"alpha", "beta", "gamma"})
            self.assertGreater(result["alpha"], result["beta"])
            self.assertGreater(result["beta"], result["gamma"])


class TestWeights(unittest.TestCase):
    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(power_v2.WEIGHTS.values()), 1.0, places=2)

    def test_team_ros_strength_dominates(self):
        # Per spec: 0.38 is the largest individual weight.
        self.assertEqual(
            max(power_v2.WEIGHTS.values()),
            power_v2.WEIGHTS["team_ros_strength"],
        )


class TestDisplayNameResolution(unittest.TestCase):
    """Regression: power_v2 used to call ``registry.display_name_for(oid)``
    behind a ``hasattr`` guard.  ``ManagerRegistry`` doesn't define that
    method (the canonical helper is the module-level
    ``src.public_league.metrics.display_name_for(snapshot, owner_id)``),
    so the hasattr always returned False and ``displayName`` fell back
    to the raw Sleeper owner_id.  The /league Power Rankings table then
    rendered numeric IDs in the OWNER column.

    The fix imports ``metrics.display_name_for`` and calls it directly.
    These tests pin the new path:

      1. ``metrics.display_name_for`` is the canonical helper used
         everywhere else in the public_league pipeline (records.py,
         streaks.py, activity.py).  Verify it resolves to the
         manager's human-readable display name when registered.
      2. Falls back to owner_id when the registry has no entry —
         matching ``metrics.display_name_for``'s contract so a
         pre-snapshot orphan ownerId doesn't crash with AttributeError.

    The build_section integration is implicitly covered by the
    line that calls ``_metrics.display_name_for(snapshot, oid)``;
    these unit tests pin the helper itself so a future refactor of
    metrics.py won't silently regress the call site.
    """

    def test_metrics_display_name_for_resolves_registered_owner(self):
        from src.public_league.identity import Manager, ManagerRegistry
        from src.public_league.snapshot import PublicLeagueSnapshot
        from src.public_league import metrics

        registry = ManagerRegistry(
            by_owner_id={
                "owner-A": Manager(
                    owner_id="owner-A",
                    display_name="Russini Panini",
                    current_team_name="Russini Panini",
                ),
            },
        )
        snapshot = PublicLeagueSnapshot(
            root_league_id="L1",
            generated_at="2026-04-29T00:00:00Z",
            seasons=[],
            managers=registry,
        )
        # The canonical helper power_v2 now uses.
        self.assertEqual(
            metrics.display_name_for(snapshot, "owner-A"),
            "Russini Panini",
        )

    def test_metrics_display_name_for_falls_back_to_owner_id(self):
        from src.public_league.identity import ManagerRegistry
        from src.public_league.snapshot import PublicLeagueSnapshot
        from src.public_league import metrics

        snapshot = PublicLeagueSnapshot(
            root_league_id="L1",
            generated_at="2026-04-29T00:00:00Z",
            seasons=[],
            managers=ManagerRegistry(),
        )
        # Unknown owner_id falls through to the raw string — never
        # raises on missing manager.
        self.assertEqual(
            metrics.display_name_for(snapshot, "orphan-owner"),
            "orphan-owner",
        )

    def test_power_v2_uses_metrics_helper_not_registry_method(self):
        """Pin the source of the bug: ``ManagerRegistry`` does NOT
        expose ``display_name_for`` as a method.  Any future code
        that re-introduces ``registry.display_name_for(...)`` would
        silently fall back to owner_id again.  This test is the
        canary."""
        from src.public_league.identity import ManagerRegistry

        self.assertFalse(
            hasattr(ManagerRegistry, "display_name_for"),
            "If ManagerRegistry gains a display_name_for method, "
            "update power_v2.py to call it directly and remove this "
            "test — the bug it pins becomes irrelevant.",
        )


def _make_season(
    year: str,
    league_id: str,
    rosters: list[dict],
    matchups_by_week: dict[int, list[dict]] | None = None,
    *,
    is_complete: bool = False,
) -> SeasonSnapshot:
    """Build a minimally-populated SeasonSnapshot for build_section tests."""
    league = {
        "league_id": league_id,
        "season": year,
        "season_type": "regular",
        "settings": {"playoff_week_start": 15},
        "total_rosters": len(rosters),
    }
    if is_complete:
        league["status"] = "complete"
    return SeasonSnapshot(
        season=year,
        league_id=league_id,
        league=league,
        users=[],
        rosters=rosters,
        matchups_by_week=matchups_by_week or {},
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )


def _make_snapshot(
    rosters: list[dict],
    matchups_by_week: dict[int, list[dict]] | None = None,
    *,
    is_complete: bool = False,
    season_year: str = "2026",
) -> PublicLeagueSnapshot:
    """Build a minimal snapshot whose ManagerRegistry is consistent with
    the supplied rosters.  Each roster's owner_id is registered as an
    active manager so ``_enumerate_owner_ids`` includes them.
    """
    league_id = f"L{season_year}"
    registry = ManagerRegistry()
    for r in rosters:
        oid = str(r.get("owner_id") or "")
        if not oid:
            continue
        registry.by_owner_id[oid] = Manager(owner_id=oid, display_name=oid)
        # ``roster_to_owner`` is LOAD-BEARING, not bookkeeping.
        # ``luck._season_weekly_scores`` attributes a matchup row to an
        # owner through it and SKIPS any row it cannot resolve, so a
        # registry without it yields zero scored weeks — every component
        # falls back to its neutral default and every owner scores the
        # SAME number however different the fixture's points are.
        # Fixtures built that way assert shape while measuring nothing
        # about the data: measured 2026-08-19, every owner in
        # ``test_power_lenses._scored_snapshot`` scored an identical
        # 33.64 across three weeks of deliberately different points.
        try:
            registry.roster_to_owner[(league_id, int(r.get("roster_id")))] = oid
        except (TypeError, ValueError):
            continue
    season = _make_season(
        season_year,
        league_id,
        rosters,
        matchups_by_week,
        is_complete=is_complete,
    )
    return PublicLeagueSnapshot(
        root_league_id=league_id,
        generated_at="2026-04-30T00:00:00Z",
        seasons=[season],
        managers=registry,
    )


class TestIsPreseason(unittest.TestCase):
    def test_no_current_season_is_preseason(self):
        snapshot = PublicLeagueSnapshot(
            root_league_id="L1",
            generated_at="2026-04-30T00:00:00Z",
            seasons=[],
            managers=ManagerRegistry(),
        )
        self.assertTrue(power_v2._is_preseason(snapshot))

    def test_no_scored_matchups_is_preseason(self):
        # A current season exists but no week has any scored matchups —
        # going-into-the-new-year before any games kick off.
        snapshot = _make_snapshot(
            rosters=[{"owner_id": "alpha", "roster_id": 1}],
            matchups_by_week={1: [{"roster_id": 1, "points": 0}]},
        )
        self.assertTrue(power_v2._is_preseason(snapshot))

    def test_completed_season_is_preseason(self):
        # Last year is in the snapshot and marked complete — we're
        # between seasons.  Even with prior scored games, this counts as
        # going into the new year.
        snapshot = _make_snapshot(
            rosters=[{"owner_id": "alpha", "roster_id": 1}],
            matchups_by_week={1: [{"roster_id": 1, "points": 100}]},
            is_complete=True,
            season_year="2025",
        )
        self.assertTrue(power_v2._is_preseason(snapshot))

    def test_in_progress_season_is_not_preseason(self):
        snapshot = _make_snapshot(
            rosters=[{"owner_id": "alpha", "roster_id": 1}],
            matchups_by_week={1: [{"roster_id": 1, "points": 110.4}]},
        )
        self.assertFalse(power_v2._is_preseason(snapshot))


class TestEnumerateOwnerIds(unittest.TestCase):
    def test_team_strength_takes_precedence(self):
        snapshot = _make_snapshot(
            rosters=[{"owner_id": "alpha", "roster_id": 1}],
        )
        ts_rows = [
            {"ownerId": "alpha"},
            {"ownerId": "bravo"},
        ]
        snapshot.managers.by_owner_id["bravo"] = Manager(owner_id="bravo", display_name="Bravo")
        ids = power_v2._enumerate_owner_ids(snapshot, ts_rows, [])
        self.assertEqual(ids, ["alpha", "bravo"])

    def test_falls_through_to_current_season_rosters(self):
        # Two new owners on the current Sleeper league; team_strength
        # snapshot empty (e.g. ROS scrape hasn't run yet).
        snapshot = _make_snapshot(
            rosters=[
                {"owner_id": "new1", "roster_id": 1},
                {"owner_id": "new2", "roster_id": 2},
            ],
        )
        ids = power_v2._enumerate_owner_ids(snapshot, [], [])
        self.assertEqual(set(ids), {"new1", "new2"})

    def test_includes_historical_owners_still_registered(self):
        snapshot = _make_snapshot(
            rosters=[{"owner_id": "alpha", "roster_id": 1}],
        )
        snapshot.managers.by_owner_id["legacy"] = Manager(owner_id="legacy", display_name="Legacy")
        ids = power_v2._enumerate_owner_ids(snapshot, [], ["legacy"])
        self.assertIn("legacy", ids)

    def test_drops_unregistered_historical_owners(self):
        # Retired owners are filtered out at registry build time, so
        # historical-only owners that aren't in by_owner_id should not
        # leak into the table.
        snapshot = _make_snapshot(
            rosters=[{"owner_id": "alpha", "roster_id": 1}],
        )
        ids = power_v2._enumerate_owner_ids(snapshot, [], ["retired"])
        self.assertNotIn("retired", ids)

    def test_unregistered_current_season_roster_owner_filtered(self):
        # The current-season fallback also runs through the registry
        # gate.  Sleeper sometimes leaves a departed owner attached to
        # a roster slot through the transition window, and the
        # registry's ``_RETIRED_OWNER_IDS`` filter is the canonical
        # place to express "this owner_id has left the league".
        # ``_enumerate_owner_ids`` must respect that — otherwise
        # retired managers would re-surface in ROS rankings even after
        # the operator added them to the retirement list.
        snapshot = _make_snapshot(
            rosters=[{"owner_id": "alpha", "roster_id": 1}],
        )
        # Simulate a retired-but-still-on-roster owner: the snapshot
        # has them on a roster but the registry build dropped them.
        snapshot.current_season.rosters.append(
            {"owner_id": "retired-but-rostered", "roster_id": 99}
        )
        ids = power_v2._enumerate_owner_ids(snapshot, [], [])
        self.assertIn("alpha", ids)
        self.assertNotIn("retired-but-rostered", ids)

    def test_stale_team_strength_owner_filtered_against_registry(self):
        # The team-strength file is written by a scheduled scrape and
        # can lag the live snapshot.  If a manager leaves the league
        # between scrapes, their ownerId stays in
        # ``team_strength/latest.json`` until the next refresh — but
        # they're already gone from the snapshot's current season and
        # have been pruned from ``by_owner_id``.  Without this filter
        # the rankings table would render an extra row past league
        # size during the season-transition window.
        snapshot = _make_snapshot(
            rosters=[{"owner_id": "alpha", "roster_id": 1}],
        )
        ts_rows = [
            {"ownerId": "alpha"},  # registered, keep
            {"ownerId": "departed"},  # stale entry, drop
        ]
        ids = power_v2._enumerate_owner_ids(snapshot, ts_rows, [])
        self.assertIn("alpha", ids)
        self.assertNotIn("departed", ids)


class TestBuildSectionPreseason(unittest.TestCase):
    """End-to-end build for a going-into-2026 fixture.

    Twelve rosters in the current Sleeper league, two of them new owners
    with no historical participation.  The team-strength snapshot lists
    all twelve.  No regular-season matchups are scored.  Expected
    behaviour:

      * ``currentRanking`` returns 12 rows — every roster appears,
        including the two newcomers.
      * ``preseason`` is True.
      * Historical-results components (PPG, recent, W/L, all-play, streak,
        luck regression) all appear in ``missingInputs`` so they're
        excluded from the score weighting.
      * ``effectiveWeights`` only contains the forward-looking
        components: team_ros_strength, roster_health, schedule_adjusted
        (when available).
    """

    def test_twelve_owners_preseason(self):
        rosters = [{"owner_id": f"owner-{i:02d}", "roster_id": i} for i in range(1, 13)]
        # Two of the twelve are brand new — keep them out of the
        # historical-careers walk by virtue of empty matchups.
        snapshot = _make_snapshot(rosters=rosters)
        ts_rows = [
            {
                "ownerId": f"owner-{i:02d}",
                "teamRosStrength": 100 - i * 5,
                "healthAvailabilityScore": 100,
            }
            for i in range(1, 13)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            target = tmp_root / "team_strength" / "latest.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(ts_rows))
            with patch.object(power_v2, "ROS_DATA_DIR", tmp_root):
                section = power_v2.build_section(snapshot)

        self.assertEqual(len(section["currentRanking"]), 12)
        self.assertTrue(section["preseason"])
        for component in power_v2._HISTORICAL_RESULTS_COMPONENTS:
            self.assertIn(
                component,
                section["missingInputs"],
                f"preseason should drop {component} from active weights",
            )
        # Forward-looking only in effectiveWeights.
        eff = section["effectiveWeights"]
        for component in power_v2._HISTORICAL_RESULTS_COMPONENTS:
            self.assertNotIn(component, eff)
        self.assertIn("team_ros_strength", eff)
        # ``roster_health`` was REMOVED 2026-08-18: it was
        # ``healthAvailabilityScore / 100`` republished from the auth-gated
        # rosTeamStrength section onto the PUBLIC rosPower section, and it was
        # already counted inside the team_ros_strength composite
        # (team_strength.WEIGHT_HEALTH). Its 0.03 folded into
        # team_ros_strength, so preseason is now a single forward-looking
        # component. See tests/api/test_public_power_leaks_no_private_quantity.py.
        self.assertNotIn("roster_health", eff)
        # Each row carries a non-empty score (renormalised onto the
        # forward-looking inputs, not deflated by the dropped weights).
        scores = [row["powerScore"] for row in section["currentRanking"]]
        self.assertTrue(all(s >= 0 for s in scores))
        self.assertTrue(any(s > 0 for s in scores))

    def test_in_progress_season_keeps_historical_components(self):
        # Sanity check that the preseason gate doesn't always fire.
        rosters = [{"owner_id": f"o{i}", "roster_id": i} for i in range(1, 4)]
        matchups = {
            1: [
                {"roster_id": 1, "points": 110.0},
                {"roster_id": 2, "points": 90.0},
                {"roster_id": 3, "points": 85.0},
            ],
        }
        snapshot = _make_snapshot(rosters=rosters, matchups_by_week=matchups)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            target = tmp_root / "team_strength" / "latest.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(
                    [
                        {
                            "ownerId": f"o{i}",
                            "teamRosStrength": 50.0,
                            "healthAvailabilityScore": 100,
                        }
                        for i in range(1, 4)
                    ]
                )
            )
            with patch.object(power_v2, "ROS_DATA_DIR", tmp_root):
                section = power_v2.build_section(snapshot)
        self.assertFalse(section["preseason"])
        # Historical components should NOT have been auto-flagged
        # missing in an active season.
        for component in power_v2._HISTORICAL_RESULTS_COMPONENTS:
            self.assertNotIn(component, section["missingInputs"])


if __name__ == "__main__":
    unittest.main()
