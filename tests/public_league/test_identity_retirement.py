"""Tests for the retired-owner filter in
``src.public_league.identity.build_manager_registry``.

The filter drops rosters whose owner_id sits in
``_RETIRED_OWNER_IDS`` so former league members don't appear in
the public league contract's managers list or franchise dropdowns.
Historical matchup/trade data that references their old roster
slot falls through to the orphaned-roster path already handled by
the section modules.
"""
from __future__ import annotations

import unittest

from src.public_league.identity import (
    _RETIRED_OWNER_IDS,
    build_manager_registry,
)


def _season(
    *,
    league_id: str,
    season: str,
    roster_owner_pairs: list[tuple[int, str]],
    user_names: dict[str, str],
) -> dict:
    return {
        "league": {"league_id": league_id, "season": season},
        "users": [
            {"user_id": uid, "display_name": name}
            for uid, name in user_names.items()
        ],
        "rosters": [
            {"roster_id": rid, "owner_id": owner}
            for rid, owner in roster_owner_pairs
        ],
    }


class TestRetiredOwnerFilter(unittest.TestCase):
    def test_retired_owners_constant_contains_known_retirees(self):
        """If this test fails, someone broke the retirement list.
        Update this test + the _RETIRED_OWNER_IDS constant together."""
        self.assertIn("714976074907336704", _RETIRED_OWNER_IDS)  # Bwalk903
        self.assertIn("720849338183548928", _RETIRED_OWNER_IDS)  # SheriffB

    def test_retired_owner_not_in_registry(self):
        """A retired owner with a 2024 alias should NOT appear in the
        manager registry even though Sleeper's archive has their
        roster."""
        seasons = [
            _season(
                league_id="2026lg",
                season="2026",
                roster_owner_pairs=[(1, "active_owner")],
                user_names={"active_owner": "Jason"},
            ),
            _season(
                league_id="2024lg",
                season="2024",
                roster_owner_pairs=[
                    (1, "active_owner"),
                    (5, "714976074907336704"),  # Bwalk903
                    (9, "720849338183548928"),  # SheriffB
                ],
                user_names={
                    "active_owner": "Jason",
                    "714976074907336704": "Bwalk903",
                    "720849338183548928": "SheriffB",
                },
            ),
        ]
        registry = build_manager_registry(seasons)
        keys = set(registry.by_owner_id.keys())
        self.assertIn("active_owner", keys)
        self.assertNotIn("714976074907336704", keys)
        self.assertNotIn("720849338183548928", keys)

    def test_public_list_excludes_retirees(self):
        """``to_public_list`` should also exclude them — same code
        path — but we pin it explicitly in case a future
        refactor diverges the two."""
        seasons = [
            _season(
                league_id="2024lg",
                season="2024",
                roster_owner_pairs=[
                    (1, "active_owner"),
                    (2, "714976074907336704"),
                ],
                user_names={
                    "active_owner": "Jason",
                    "714976074907336704": "Bwalk903",
                },
            ),
        ]
        registry = build_manager_registry(seasons)
        names = [m["displayName"] for m in registry.to_public_list()]
        self.assertIn("Jason", names)
        self.assertNotIn("Bwalk903", names)

    def test_retired_owner_roster_to_owner_mapping_is_orphaned(self):
        """The retiree's historical roster slot should NOT be in the
        ``roster_to_owner`` lookup — which means any section module
        that tries to attribute a 2024 matchup to their roster will
        see the orphan path and filter it out, consistent with how
        un-assigned rosters are already handled."""
        seasons = [
            _season(
                league_id="2024lg",
                season="2024",
                roster_owner_pairs=[(5, "714976074907336704")],
                user_names={"714976074907336704": "Bwalk903"},
            ),
        ]
        registry = build_manager_registry(seasons)
        self.assertNotIn(("2024lg", 5), registry.roster_to_owner)

    def test_non_retired_owners_still_build_normally(self):
        """Sanity: the filter only affects retirees, not everyone."""
        seasons = [
            _season(
                league_id="2026lg",
                season="2026",
                roster_owner_pairs=[
                    (1, "owner_a"),
                    (2, "owner_b"),
                    (3, "owner_c"),
                ],
                user_names={
                    "owner_a": "Aguilar315",
                    "owner_b": "Brenthany",
                    "owner_c": "Jason",
                },
            ),
        ]
        registry = build_manager_registry(seasons)
        self.assertEqual(len(registry.by_owner_id), 3)


if __name__ == "__main__":
    unittest.main()
