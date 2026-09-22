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
from src.ros import power_v2, team_strength


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
    """``power_v2._load_team_strength_*`` delegate to
    ``team_strength.load_or_compute_team_strength`` (2026-09), which owns
    ``ROS_DATA_DIR``-relative path resolution now — the monkeypatch target
    moved with it. No snapshot is passed in these two tests, so the
    delegate's live-fallback tiers never fire: a missing file with no
    snapshot in hand correctly falls through to [] (compute_team_strength_live
    also finds nothing to work with in this unpatched-registry test
    environment)."""

    def test_missing_file_returns_empty(self):
        with patch.object(team_strength, "ROS_DATA_DIR", Path("/nonexistent")):
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
            with patch.object(team_strength, "ROS_DATA_DIR", tmp_root):
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
    last_scored_leg: int | None = None,
) -> SeasonSnapshot:
    """Build a minimally-populated SeasonSnapshot for build_section tests.

    ``last_scored_leg`` is Sleeper's own "which week have you finished
    scoring" stamp.  Omitted by default so existing fixtures keep riding
    the data-completeness proof in ``metrics.final_regular_season_weeks``,
    which is what they have always effectively used.
    """
    settings: dict = {"playoff_week_start": 15}
    if last_scored_leg is not None:
        settings["last_scored_leg"] = last_scored_leg
    league = {
        "league_id": league_id,
        "season": year,
        "season_type": "regular",
        "settings": settings,
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
    last_scored_leg: int | None = None,
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
        last_scored_leg=last_scored_leg,
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
    def test_current_roster_membership_beats_stale_team_strength_extras(self):
        snapshot = _make_snapshot(
            rosters=[{"owner_id": "alpha", "roster_id": 1}],
        )
        ts_rows = [
            {"ownerId": "alpha"},
            {"ownerId": "bravo"},
        ]
        snapshot.managers.by_owner_id["bravo"] = Manager(owner_id="bravo", display_name="Bravo")
        ids = power_v2._enumerate_owner_ids(snapshot, ts_rows, [])
        self.assertEqual(ids, ["alpha"])

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

    def test_populated_current_roster_excludes_historical_only_owner(self):
        snapshot = _make_snapshot(
            rosters=[{"owner_id": "alpha", "roster_id": 1}],
        )
        snapshot.managers.by_owner_id["legacy"] = Manager(owner_id="legacy", display_name="Legacy")
        ids = power_v2._enumerate_owner_ids(snapshot, [], ["legacy"])
        self.assertEqual(ids, ["alpha"])

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
      * Canonical observed-result inputs are excluded from weighting and
        reported unavailable rather than zero.
      * ``effectiveWeights`` contains only ``team_ros_strength``.
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
            with patch.object(team_strength, "ROS_DATA_DIR", tmp_root):
                section = power_v2.build_section(snapshot)

        self.assertEqual(len(section["currentRanking"]), 12)
        self.assertTrue(section["preseason"])
        # Only canonical weighted inputs belong in missingInputs. Legacy
        # display-only diagnostics (PPG/streak/luck) are not fake "missing
        # weights" now that they no longer participate in the score.
        for component in ("all_play", "recent", "wl_record"):
            self.assertIn(component, section["missingInputs"])
        self.assertTrue(any(item.startswith("team_vorp") for item in section["missingInputs"]))
        # Preseason canonical Power is forward-looking only.
        eff = section["effectiveWeights"]
        self.assertEqual(set(eff), {"team_ros_strength"})
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
        # Sanity check that the preseason gate doesn't always fire. Four
        # scored weeks provide a mature-enough active-season fixture; sample
        # reliability is now handled by the smooth evidence curve rather
        # than per-component activation cliffs.
        rosters = [{"owner_id": f"o{i}", "roster_id": i} for i in range(1, 4)]
        matchups = {
            wk: [
                {"roster_id": 1, "points": 110.0 + wk},
                {"roster_id": 2, "points": 90.0 + wk},
                {"roster_id": 3, "points": 85.0 + wk},
            ]
            for wk in (1, 2, 3, 4)
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
            with patch.object(team_strength, "ROS_DATA_DIR", tmp_root):
                section = power_v2.build_section(snapshot)
        self.assertFalse(section["preseason"])
        # Historical components should NOT have been auto-flagged
        # missing in an active season.
        for component in power_v2._HISTORICAL_RESULTS_COMPONENTS:
            self.assertNotIn(component, section["missingInputs"])


class TestComponentRanks(unittest.TestCase):
    """Per-component sub-ranks, derived in the backend.

    They answer "which of these five things put me here?", which a raw
    percentile does not: #1 of 12 and #9 of 12 can sit a few points apart.
    Derived here rather than in the page because they are ordinals over a
    population, which CLAUDE.md forbids the frontend to compute.
    """

    def _rows(self, values):
        return [
            {"ownerId": oid, "components": {"all_play": v}, "rank": i + 1}
            for i, (oid, v) in enumerate(values.items())
        ]

    def test_higher_percentile_ranks_first(self):
        rows = self._rows({"a": 0.9, "b": 0.5, "c": 0.7})
        power_v2._attach_component_ranks(rows, {"all_play": 0.2})
        got = {r["ownerId"]: r["componentRanks"]["all_play"] for r in rows}
        self.assertEqual(got, {"a": 1, "c": 2, "b": 3})

    def test_ties_share_a_rank_and_skip_the_next(self):
        # Standard competition ranking (1, 1, 3) — the same convention the
        # overall Power rank already uses.
        rows = self._rows({"a": 0.9, "b": 0.9, "c": 0.4})
        power_v2._attach_component_ranks(rows, {"all_play": 0.2})
        got = {r["ownerId"]: r["componentRanks"]["all_play"] for r in rows}
        self.assertEqual(got, {"a": 1, "b": 1, "c": 3})

    def test_missing_component_is_unranked_not_last(self):
        # A team nobody measured is not the worst team at it. MISSING IS NEVER
        # ZERO applied to an ordinal: the key is simply absent.
        rows = self._rows({"a": 0.9, "b": None, "c": 0.4})
        power_v2._attach_component_ranks(rows, {"all_play": 0.2})
        by_owner = {r["ownerId"]: r for r in rows}
        self.assertEqual(by_owner["a"]["componentRanks"]["all_play"], 1)
        self.assertEqual(by_owner["c"]["componentRanks"]["all_play"], 2)
        self.assertNotIn("componentRanks", by_owner["b"])

    def test_unweighted_components_are_not_ranked(self):
        # ``ppg`` is a display diagnostic and carries no weight, so it is not
        # part of "what put me here" and must not be presented as if it were.
        rows = [
            {"ownerId": "a", "components": {"all_play": 0.9, "ppg": 0.1}},
            {"ownerId": "b", "components": {"all_play": 0.4, "ppg": 0.9}},
        ]
        power_v2._attach_component_ranks(rows, {"all_play": 0.2})
        for row in rows:
            self.assertIn("all_play", row["componentRanks"])
            self.assertNotIn("ppg", row["componentRanks"])

    def test_team_vorp_is_absent_while_its_feed_is_unavailable(self):
        # The open dependency: no realized VORP/PAR feed exists, so every row
        # is None and the component yields no ranks at all.
        rows = self._rows({"a": 0.9, "b": 0.4})
        for row in rows:
            row["components"]["team_vorp"] = None
        power_v2._attach_component_ranks(rows, {"all_play": 0.2, "team_vorp": 0.15})
        for row in rows:
            self.assertNotIn("team_vorp", row["componentRanks"])


class TestBuildSectionThreadsLeagueKeyToTeamStrength(unittest.TestCase):
    """Before this fix, ``build_section`` resolved a ``league_key`` from
    the snapshot but never passed it to the team-strength loader, so
    every league's Power Rankings read/wrote the SAME persisted
    ``team_strength/latest.json`` file regardless of which league was
    actually being ranked.  Pins the call-site plumbing directly rather
    than the (already-correct) namespacing primitive underneath it.
    """

    def test_resolved_league_key_reaches_the_team_strength_loader(self):
        rosters = [{"roster_id": i, "owner_id": f"o{i}"} for i in (1, 2)]
        matchups = {
            1: [
                {"roster_id": 1, "matchup_id": 1, "points": 100.0},
                {"roster_id": 2, "matchup_id": 1, "points": 90.0},
            ]
        }
        snapshot = _make_snapshot(rosters, matchups)
        snapshot.root_league_id = "sleeper-league-xyz"

        recorded: list[tuple] = []

        def spy(league_key=None, *, snapshot=None, persist=True):
            recorded.append((league_key, snapshot))
            return []

        with (
            patch.object(team_strength, "load_or_compute_team_strength", spy),
            patch(
                "src.api.league_registry.league_key_for_sleeper_id",
                return_value="resolved_league_key",
            ),
        ):
            power_v2.build_section(snapshot)

        self.assertTrue(recorded, "team-strength loader was never called")
        for league_key, _snap in recorded:
            self.assertEqual(league_key, "resolved_league_key")

    def test_results_only_lens_never_resolves_or_calls_it(self):
        """The existing ``test_results_only_never_reads_team_strength``
        (test_power_lenses.py) already pins that results-only never
        reads team strength; this pins the SAME property from the
        league_key-resolution side, so a future change cannot
        reintroduce the read via the new resolution path alone."""
        rosters = [{"roster_id": i, "owner_id": f"o{i}"} for i in (1, 2)]
        matchups = {
            1: [
                {"roster_id": 1, "matchup_id": 1, "points": 100.0},
                {"roster_id": 2, "matchup_id": 1, "points": 90.0},
            ]
        }
        snapshot = _make_snapshot(rosters, matchups)
        snapshot.root_league_id = "sleeper-league-xyz"

        def boom(*args, **kwargs):
            raise AssertionError("results-only lens resolved a league key")

        with patch("src.api.league_registry.league_key_for_sleeper_id", boom):
            power_v2.build_section(snapshot, lens=power_v2.LENS_RESULTS_ONLY)


# ── The in-progress-week regression ──────────────────────────────────────
# Live values measured from Sleeper league 1312006700437352448 on
# 2026-09-19, mid-week-2.  Week 1 is complete.  Week 2 is IN PROGRESS:
# eight rosters carry a Thursday-night partial, four carry a literal 0.0
# because nobody on them played Thursday.
_LIVE_WEEK1 = {
    1: 404.46, 2: 312.87, 3: 279.96, 4: 363.78, 5: 393.44, 6: 473.30,
    7: 274.70, 8: 452.30, 9: 453.37, 10: 315.67, 11: 319.11, 12: 303.44,
}  # fmt: skip
_LIVE_WEEK2_PARTIAL = {
    1: 0.0, 2: 0.0, 3: 34.99, 4: 33.09, 5: 7.04, 6: 18.05,
    7: 0.0, 8: 27.81, 9: 58.94, 10: 32.92, 11: 0.0, 12: 75.32,
}  # fmt: skip


def _rows(points_by_roster: dict[int, float | None]) -> list[dict]:
    return [
        {"matchup_id": (rid + 1) // 2, "roster_id": rid, "points": pts}
        for rid, pts in sorted(points_by_roster.items())
    ]


class TestCompletedWeekGate(unittest.TestCase):
    """Observed results count COMPLETED league weeks, and only those.

    The defect these pin: ``luck._season_weekly_scores`` iterated every
    regular-season week and filtered per roster-entry on ``points > 0``, so
    a live week was counted as a finished game for whoever happened to have
    a Thursday-night player and dropped for everyone else.  Eight teams'
    averages divided by 2 while four divided by 1, inside one table.
    """

    _ROSTERS = [{"roster_id": r, "owner_id": f"o{r}"} for r in sorted(_LIVE_WEEK1)]

    def _section(self, matchups, *, last_scored_leg=None, rosters=None):
        """Build a section with team strength isolated to a temp dir.

        The isolation is load-bearing: ``team_strength`` WRITES a computed
        snapshot into ``ROS_DATA_DIR``, so an unpatched call would leave a
        synthetic ``latest.json`` in the repo's real ``data/ros`` and break
        every later test that reads it.
        """
        snapshot = _make_snapshot(
            rosters=rosters or self._ROSTERS,
            matchups_by_week=matchups,
            last_scored_leg=last_scored_leg,
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(team_strength, "ROS_DATA_DIR", Path(tmp)):
                return power_v2.build_section(snapshot)

    def _by_name(self, section):
        return {r["displayName"]: r for r in section["currentRanking"]}

    def test_in_progress_week_is_excluded_from_every_team_denominator(self):
        section = self._section(
            {1: _rows(_LIVE_WEEK1), 2: _rows(_LIVE_WEEK2_PARTIAL)},
            last_scored_leg=1,
        )

        self.assertEqual(section["countedWeeks"], [1])
        self.assertEqual(section["blend"]["scoredGames"], 1)
        self.assertFalse(section["blend"]["scoredGamesDiverged"])

        rows = self._by_name(section)
        self.assertEqual(len(rows), 12)
        for rid, week1_points in _LIVE_WEEK1.items():
            row = rows[f"o{rid}"]
            # One shared denominator, or the column is not comparable.
            self.assertEqual(row["gamesUsed"], 1, f"o{rid} denominator")
            self.assertAlmostEqual(row["components"]["pointsPerGame"], week1_points, places=2)

        # The specific number the owner reported. Before the fix this row
        # read 256.16 — (453.37 + 58.94) / 2, a completed week averaged
        # with a Thursday-night sliver.
        self.assertAlmostEqual(rows["o9"]["components"]["pointsPerGame"], 453.37, places=2)

    def test_all_play_field_is_the_whole_league_in_every_counted_week(self):
        """All-play must be measured against 11 rivals, not a shrunken field.

        With four rosters dropped from the live week, all-play was computed
        over 8 teams — silently repricing a 0.20-weight component.
        """
        section = self._section(
            {1: _rows(_LIVE_WEEK1), 2: _rows(_LIVE_WEEK2_PARTIAL)},
            last_scored_leg=1,
        )
        shares = sorted(r["components"]["all_play"] for r in section["currentRanking"])
        expected = [round(k / 11.0, 4) for k in range(12)]
        self.assertEqual(shares, expected)

    def test_a_genuine_zero_in_a_finalised_week_counts_as_a_game(self):
        """MISSING IS NEVER ZERO must not become "zero is never real".

        Once the host says a week is scored, a roster that put up 0.0 played
        that game. Dropping it would shrink that one team's denominator —
        the very asymmetry the gate exists to remove.
        """
        week2 = dict(_LIVE_WEEK1)
        week2[7] = 0.0
        section = self._section(
            {1: _rows(_LIVE_WEEK1), 2: _rows(week2)},
            last_scored_leg=2,
        )
        self.assertEqual(section["countedWeeks"], [1, 2])
        rows = self._by_name(section)
        for rid in _LIVE_WEEK1:
            self.assertEqual(rows[f"o{rid}"], rows[f"o{rid}"] | {"gamesUsed": 2})
        self.assertAlmostEqual(
            rows["o7"]["components"]["pointsPerGame"], _LIVE_WEEK1[7] / 2.0, places=2
        )

    def test_a_roster_week_with_no_points_value_stays_missing(self):
        """An absent score is missing evidence, never a zero-point game."""
        week2 = dict(_LIVE_WEEK1)
        week2[7] = None
        section = self._section(
            {1: _rows(_LIVE_WEEK1), 2: _rows(week2)},
            last_scored_leg=2,
        )
        rows = self._by_name(section)
        self.assertEqual(rows["o7"]["gamesUsed"], 1)
        self.assertAlmostEqual(rows["o7"]["components"]["pointsPerGame"], _LIVE_WEEK1[7], places=2)
        # The shortfall is reported, not silently absorbed.
        self.assertEqual(section["partialWeeks"], [{"week": 2, "observed": 11, "expected": 12}])
        self.assertTrue(section["blend"]["scoredGamesDiverged"])
        # And the shared count is the honest floor, not the luckiest team's.
        self.assertEqual(section["blend"]["scoredGames"], 1)
        self.assertEqual(section["blend"]["scoredGamesMax"], 2)

    def test_host_clock_absent_falls_back_to_data_completeness(self):
        """No ``last_scored_leg`` must still exclude the in-progress week.

        Every pre-existing fixture in this repo rides this path, and it is
        the only proof available when Sleeper omits the stamp.
        """
        section = self._section({1: _rows(_LIVE_WEEK1), 2: _rows(_LIVE_WEEK2_PARTIAL)})
        self.assertEqual(section["countedWeeks"], [1])
        for row in section["currentRanking"]:
            self.assertEqual(row["gamesUsed"], 1)

    def test_stale_host_clock_does_not_withhold_a_fully_scored_week(self):
        """The two proofs are a union, so either one alone admits a week.

        A host clock that lags a refresh cycle must not hide a week every
        roster has finished.
        """
        section = self._section(
            {1: _rows(_LIVE_WEEK1), 2: _rows(_LIVE_WEEK1)},
            last_scored_leg=1,
        )
        self.assertEqual(section["countedWeeks"], [1, 2])
        for row in section["currentRanking"]:
            self.assertEqual(row["gamesUsed"], 2)

    def test_blend_reports_zero_scored_games_in_preseason(self):
        """Preseason suppresses results, so the game count must say 0.

        It used to publish the previous season's count beside
        ``resultsEvidence: 0.0`` — a number untrue of the season described.
        """
        section = self._section({}, last_scored_leg=0)
        self.assertTrue(section["preseason"])
        self.assertEqual(section["blend"]["scoredGames"], 0)
        self.assertEqual(section["blend"]["scoredGamesMax"], 0)
        for row in section["currentRanking"]:
            self.assertEqual(row["gamesUsed"], 0)
            self.assertEqual(row["recentGamesUsed"], 0)


if __name__ == "__main__":
    unittest.main()
