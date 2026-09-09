"""Manager completeness (acceptance scenario 6, 2026-09).

The Week 1 Power Rankings directive reported "10 managers listed without
a score" in a 12-manager league. Two independent, compounding bugs were
found and are pinned separately:

    1. ``src/public_league/snapshot_store.py`` dropped ``Manager.is_retired``
       on the persist/load round-trip, so a cold-started process serving
       straight from the persisted snapshot resurrected retired owners
       into current-view tables — see
       ``tests/public_league/test_snapshot_store_retirement_roundtrip.py``.
    2. ``power_v2._enumerate_owner_ids``'s precedence made prior-season
       history the effective backstop whenever team-strength was empty
       AND the current-season branch failed to contribute — a real,
       reachable state for a league that expanded rosters (this league
       went 10 -> 12 teams for 2026), which silently bottomed the table
       out at the pre-expansion owner count.

This file pins the REPAIR: current-season roster membership is primary,
so no registered, non-retired, current-season owner can be dropped by a
stale or partial upstream source.
"""

from __future__ import annotations

import unittest

from src.public_league.identity import Manager
from src.ros import power_v2
from tests.ros.test_power_v2 import _make_snapshot


class TestManagerCompletenessUnderPartialUpstreamSources(unittest.TestCase):
    """``_enumerate_owner_ids`` must return every registry-passing
    current-season roster owner, regardless of which OTHER sources are
    empty, stale, or partial. A populated current roster also excludes
    historical-only/stale extra owners."""

    def test_empty_team_strength_rows_still_enumerates_every_current_owner(self):
        """The exact reachable state: a fresh deploy / failed scrape
        cycle leaves team-strength empty. Every current-season roster
        owner must still appear."""
        rosters = [{"owner_id": f"owner-{i:02d}", "roster_id": i} for i in range(1, 13)]
        snapshot = _make_snapshot(rosters=rosters)
        ids = power_v2._enumerate_owner_ids(snapshot, [], [])
        self.assertEqual(set(ids), {f"owner-{i:02d}" for i in range(1, 13)})
        self.assertEqual(len(ids), 12)

    def test_stale_partial_team_strength_file_does_not_shrink_the_table(self):
        """A team-strength snapshot written before a roster expansion
        (e.g. mid-refresh-cycle) carries only a SUBSET of current owners.
        The union must still include every current-season owner, not
        just the ones the stale file happens to know about."""
        rosters = [{"owner_id": f"owner-{i:02d}", "roster_id": i} for i in range(1, 13)]
        snapshot = _make_snapshot(rosters=rosters)
        # Stale file: only the first 10 (pre-expansion) owners.
        stale_rows = [{"ownerId": f"owner-{i:02d}"} for i in range(1, 11)]
        ids = power_v2._enumerate_owner_ids(snapshot, stale_rows, [])
        self.assertEqual(set(ids), {f"owner-{i:02d}" for i in range(1, 13)})
        self.assertEqual(len(ids), 12)

    def test_new_owners_with_zero_history_are_not_dropped(self):
        """The real expansion case named in the directive: two managers
        (Blaine, jstuedle) are brand new for 2026 with NO 2024/2025
        roster at all. ``historical_owner_ids`` (derived from
        ``career_state.keys()``) is empty for them, and if history were
        the primary or only source they would vanish. Current-season
        rosters must catch them regardless."""
        rosters = [
            {"owner_id": "veteran-01", "roster_id": 1},
            {"owner_id": "veteran-02", "roster_id": 2},
            {"owner_id": "new-blaine", "roster_id": 3},
            {"owner_id": "new-jstuedle", "roster_id": 4},
        ]
        snapshot = _make_snapshot(rosters=rosters)
        # historical_owner_ids only knows the two veterans -- exactly the
        # "10 pre-expansion owners" shape the real defect produced.
        ids = power_v2._enumerate_owner_ids(snapshot, [], ["veteran-01", "veteran-02"])
        self.assertEqual(set(ids), {"veteran-01", "veteran-02", "new-blaine", "new-jstuedle"})

    def test_current_season_excludes_historical_only_owners(self):
        """A populated current roster is authoritative membership.

        A registry-valid owner who exists only in history must not reappear
        in the current Power table or expand a 12-team league beyond 12 rows.
        History is only a fallback when current roster membership is absent.
        """
        rosters = [{"owner_id": "current-1", "roster_id": 1}]
        snapshot = _make_snapshot(rosters=rosters)
        snapshot.managers.by_owner_id["legacy"] = Manager(owner_id="legacy", display_name="Legacy")
        ids = power_v2._enumerate_owner_ids(snapshot, [], ["legacy"])
        self.assertEqual(ids, ["current-1"])

    def test_end_to_end_build_section_lists_all_twelve_with_no_missing_manager(self):
        """The full pipeline, not just the enumeration helper: a 12-team
        league with an empty team-strength file (the reachable preseason
        state) must produce exactly 12 rows in the headline ranking."""
        rosters = [{"owner_id": f"owner-{i:02d}", "roster_id": i} for i in range(1, 13)]
        snapshot = _make_snapshot(rosters=rosters)
        section = power_v2.build_section(snapshot, lens=power_v2.LENS_FORWARD_LOOKING)
        owner_ids = {r["ownerId"] for r in section["currentRanking"]}
        self.assertEqual(len(section["currentRanking"]), 12)
        self.assertEqual(owner_ids, {f"owner-{i:02d}" for i in range(1, 13)})

    def test_retired_owners_never_leak_into_the_current_table(self):
        """Non-vacuity for the companion round-trip fix: even with a
        registry that DOES carry a retired manager, ``ordered_managers()``
        (which ``_enumerate_owner_ids`` gates on) must exclude them from
        this current-view table."""
        rosters = [{"owner_id": "active-1", "roster_id": 1}]
        snapshot = _make_snapshot(rosters=rosters)
        snapshot.managers.by_owner_id["retired-owner"] = Manager(
            owner_id="retired-owner", display_name="Retired", is_retired=True
        )
        # Even if a stale team-strength row or history entry names them.
        ids = power_v2._enumerate_owner_ids(
            snapshot,
            [{"ownerId": "retired-owner"}],
            ["retired-owner"],
        )
        self.assertNotIn("retired-owner", ids)
        self.assertEqual(ids, ["active-1"])


if __name__ == "__main__":
    unittest.main()
