"""``Manager.is_retired`` persist/load round-trip (2026-09).

Root cause of the Week 1 Power Rankings "10 managers" / "14 managers"
report: ``_manager_to_dict`` did not serialize ``is_retired`` and
``_registry_from_dict`` did not restore it, so EVERY manager rehydrated
from a persisted snapshot silently became "not retired" regardless of
the real ``_RETIRED_OWNER_IDS`` list -- a cold-started process serving
straight from ``data/public_league/snapshot.json`` (``server.py``'s
startup load) resurrected retired owners into current-view tables (Power
Rankings' owner list among them) with fabricated scores.

Fails before the fix, passes after -- the second test in particular
pins the re-derivation that makes an ALREADY-PERSISTED, pre-fix snapshot
retire correctly on the very next deploy without needing to be rewritten
first.
"""

from __future__ import annotations

import unittest

from src.public_league import identity as _identity
from src.public_league.identity import Manager, ManagerRegistry
from src.public_league.snapshot import PublicLeagueSnapshot
from src.public_league.snapshot_store import snapshot_from_dict, snapshot_to_dict


class TestIsRetiredRoundTrips(unittest.TestCase):
    def test_a_retired_manager_stays_retired_through_persist_and_load(self):
        retired_id = next(iter(_identity._RETIRED_OWNER_IDS))
        registry = ManagerRegistry()
        registry.by_owner_id[retired_id] = Manager(
            owner_id=retired_id, display_name="Retired Owner", is_retired=True
        )
        registry.by_owner_id["active"] = Manager(
            owner_id="active", display_name="Active Owner", is_retired=False
        )
        snapshot = PublicLeagueSnapshot(root_league_id="L1", generated_at="2026-09-08T00:00:00Z")
        snapshot.managers = registry

        rehydrated = snapshot_from_dict(snapshot_to_dict(snapshot))

        self.assertTrue(rehydrated.managers.by_owner_id[retired_id].is_retired)
        self.assertFalse(rehydrated.managers.by_owner_id["active"].is_retired)

    def test_ordered_managers_excludes_the_round_tripped_retiree(self):
        """End-to-end proof: not just that the flag survives, but that
        the forward-facing directory (what ``power_v2._enumerate_owner_ids``
        actually gates on) honors it after a real persist/load cycle."""
        retired_id = next(iter(_identity._RETIRED_OWNER_IDS))
        registry = ManagerRegistry()
        registry.by_owner_id[retired_id] = Manager(
            owner_id=retired_id, display_name="Retired Owner", is_retired=True
        )
        registry.by_owner_id["active"] = Manager(
            owner_id="active", display_name="Active Owner", is_retired=False
        )
        snapshot = PublicLeagueSnapshot(root_league_id="L1", generated_at="2026-09-08T00:00:00Z")
        snapshot.managers = registry

        rehydrated = snapshot_from_dict(snapshot_to_dict(snapshot))
        ordered_ids = {m.owner_id for m in rehydrated.managers.ordered_managers()}

        self.assertEqual(ordered_ids, {"active"})
        self.assertIn(
            retired_id,
            rehydrated.managers.by_owner_id,
            "retirement filters the DIRECTORY, not the underlying registry -- "
            "history/franchise-page consumers still need the raw entry",
        )


class TestOldFormatSnapshotsRetireCorrectlyWithoutRewriting(unittest.TestCase):
    """FAILS BEFORE THE FIX, PASSES AFTER.  A snapshot persisted before
    ``isRetired`` existed on disk (no key at all in ``byOwnerId.<id>``)
    must still retire correctly on the very next read -- re-deriving
    from ``_RETIRED_OWNER_IDS`` is what makes this safe without a
    migration step or a rewrite of every already-persisted snapshot."""

    def test_a_pre_fix_payload_with_no_isRetired_key_still_retires(self):
        retired_id = next(iter(_identity._RETIRED_OWNER_IDS))
        old_format_payload = {
            "rootLeagueId": "L1",
            "generatedAt": "2026-09-08T00:00:00Z",
            "seasons": [],
            "managers": {
                "byOwnerId": {
                    retired_id: {
                        "ownerId": retired_id,
                        "displayName": "Retired Owner",
                        "avatar": "",
                        "currentRosterId": None,
                        "currentTeamName": "",
                        "currentLeagueId": "",
                        # Deliberately NO "isRetired" key -- the exact
                        # shape a pre-fix persisted snapshot has.
                        "aliases": [],
                    },
                    "active": {
                        "ownerId": "active",
                        "displayName": "Active Owner",
                        "avatar": "",
                        "currentRosterId": None,
                        "currentTeamName": "",
                        "currentLeagueId": "",
                        "aliases": [],
                    },
                },
                "rosterToOwner": [],
            },
        }

        rehydrated = snapshot_from_dict(old_format_payload)

        self.assertTrue(
            rehydrated.managers.by_owner_id[retired_id].is_retired,
            "an old on-disk snapshot with no isRetired key must still retire "
            "via the _RETIRED_OWNER_IDS re-derivation",
        )
        self.assertFalse(rehydrated.managers.by_owner_id["active"].is_retired)
        ordered_ids = {m.owner_id for m in rehydrated.managers.ordered_managers()}
        self.assertEqual(ordered_ids, {"active"})

    def test_a_non_retired_owner_with_no_isRetired_key_stays_active(self):
        """Non-vacuity: the re-derivation must not retire EVERYONE on an
        old-format payload -- only owners actually in _RETIRED_OWNER_IDS."""
        old_format_payload = {
            "rootLeagueId": "L1",
            "generatedAt": "2026-09-08T00:00:00Z",
            "seasons": [],
            "managers": {
                "byOwnerId": {
                    "never-retired": {
                        "ownerId": "never-retired",
                        "displayName": "Still Active",
                        "avatar": "",
                        "currentRosterId": None,
                        "currentTeamName": "",
                        "currentLeagueId": "",
                        "aliases": [],
                    },
                },
                "rosterToOwner": [],
            },
        }
        rehydrated = snapshot_from_dict(old_format_payload)
        self.assertFalse(rehydrated.managers.by_owner_id["never-retired"].is_retired)


if __name__ == "__main__":
    unittest.main()
