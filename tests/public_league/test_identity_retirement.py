"""Tests for retirement semantics in
``src.public_league.identity.build_manager_registry``.

C9-HIST-01: retirement is a CURRENT-STATE label, not a historical-
erasure instruction. A retired owner's real past seasons are real
history — a season that fielded N rosters must report N standings
rows, whoever holds those rosters today. The filter therefore only
removes retired owners from forward-facing directories
(``ordered_managers()`` / ``to_public_list()``, used by manager
dropdowns and franchise-page listings); it does NOT drop their
aliases or their ``roster_to_owner`` entries, and it does NOT shrink
a season's standings.

(Owner-approved correction, recorded 2026-08-20: the prior version of
this file pinned the opposite behavior — full historical erasure via
the orphan-roster path — which is what produced the defect this
corrects: a season declaring N teams but reporting fewer standings
rows whenever a now-retired owner was active in it.)
"""

from __future__ import annotations

import unittest

from src.public_league import metrics
from src.public_league.identity import (
    _RETIRED_OWNER_IDS,
    build_manager_registry,
)
from src.public_league.snapshot import SeasonSnapshot


def _season(
    *,
    league_id: str,
    season: str,
    roster_owner_pairs: list[tuple[int, str]],
    user_names: dict[str, str],
) -> dict:
    return {
        "league": {"league_id": league_id, "season": season},
        "users": [{"user_id": uid, "display_name": name} for uid, name in user_names.items()],
        "rosters": [{"roster_id": rid, "owner_id": owner} for rid, owner in roster_owner_pairs],
    }


class TestRetiredOwnerFilter(unittest.TestCase):
    def test_retired_owners_constant_contains_known_retirees(self):
        """If this test fails, someone broke the retirement list.
        Update this test + the _RETIRED_OWNER_IDS constant together."""
        self.assertIn("714976074907336704", _RETIRED_OWNER_IDS)  # Bwalk903
        self.assertIn("720849338183548928", _RETIRED_OWNER_IDS)  # SheriffB

    def test_retired_owner_is_in_the_registry_flagged(self):
        """A retired owner with a 2024 alias IS in the manager registry
        (their history is real) but is flagged ``is_retired``."""
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
        self.assertIn("714976074907336704", keys)
        self.assertIn("720849338183548928", keys)
        self.assertFalse(registry.by_owner_id["active_owner"].is_retired)
        self.assertTrue(registry.by_owner_id["714976074907336704"].is_retired)
        self.assertTrue(registry.by_owner_id["720849338183548928"].is_retired)

    def test_public_list_excludes_retirees(self):
        """``to_public_list`` (the forward-facing directory) still
        excludes them — that half of the original contract is unchanged."""
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

    def test_ordered_managers_include_retired_opts_back_in(self):
        """The exclusion is a directory default, not data loss — a caller
        that explicitly wants the all-time list can still get it."""
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
        default_names = {m.display_name for m in registry.ordered_managers()}
        all_names = {m.display_name for m in registry.ordered_managers(include_retired=True)}
        self.assertNotIn("Bwalk903", default_names)
        self.assertIn("Bwalk903", all_names)

    def test_retired_owner_roster_to_owner_mapping_is_preserved(self):
        """The retiree's historical roster slot IS in ``roster_to_owner`` —
        so a section module attributing a 2024 matchup to their roster
        resolves the real owner, not the orphan fallback."""
        seasons = [
            _season(
                league_id="2024lg",
                season="2024",
                roster_owner_pairs=[(5, "714976074907336704")],
                user_names={"714976074907336704": "Bwalk903"},
            ),
        ]
        registry = build_manager_registry(seasons)
        self.assertEqual(registry.roster_to_owner.get(("2024lg", 5)), "714976074907336704")

    def test_a_season_with_a_retired_owner_keeps_its_full_roster_count(self):
        """C9-HIST-01's concrete symptom: a season that fielded N rosters
        must resolve N owners, even when some are now retired — never
        fewer, whoever holds the roster today."""
        seasons = [
            _season(
                league_id="2024lg",
                season="2024",
                roster_owner_pairs=[
                    (1, "owner_a"),
                    (2, "owner_b"),
                    (3, "714976074907336704"),  # retired, but active in 2024
                    (4, "720849338183548928"),  # retired, but active in 2024
                ],
                user_names={
                    "owner_a": "Aguilar315",
                    "owner_b": "Brenthany",
                    "714976074907336704": "Bwalk903",
                    "720849338183548928": "SheriffB",
                },
            ),
        ]
        registry = build_manager_registry(seasons)
        resolved = [registry.owner_for_roster("2024lg", rid) for rid in (1, 2, 3, 4)]
        self.assertEqual(
            resolved, ["owner_a", "owner_b", "714976074907336704", "720849338183548928"]
        )

    def test_season_standings_reports_every_roster_including_retired_owners(self):
        """The end-to-end symptom C9-HIST-01 was opened for: a season
        declaring N rosters must produce N standings rows via
        metrics.season_standings, not N-minus-retired-owners."""
        seasons = [
            _season(
                league_id="2024lg",
                season="2024",
                roster_owner_pairs=[
                    (1, "owner_a"),
                    (2, "owner_b"),
                    (3, "714976074907336704"),  # retired, but active in 2024
                    (4, "720849338183548928"),  # retired, but active in 2024
                ],
                user_names={
                    "owner_a": "Aguilar315",
                    "owner_b": "Brenthany",
                    "714976074907336704": "Bwalk903",
                    "720849338183548928": "SheriffB",
                },
            ),
        ]
        registry = build_manager_registry(seasons)
        rosters = [
            {"roster_id": 1, "owner_id": "owner_a", "settings": {"wins": 5, "losses": 8}},
            {"roster_id": 2, "owner_id": "owner_b", "settings": {"wins": 7, "losses": 6}},
            {
                "roster_id": 3,
                "owner_id": "714976074907336704",
                "settings": {"wins": 9, "losses": 4},
            },
            {
                "roster_id": 4,
                "owner_id": "720849338183548928",
                "settings": {"wins": 3, "losses": 10},
            },
        ]
        season = SeasonSnapshot(
            season="2024",
            league_id="2024lg",
            league={"league_id": "2024lg", "season": "2024", "total_rosters": len(rosters)},
            users=[],
            rosters=rosters,
            matchups_by_week={},
            transactions_by_week={},
            drafts=[],
            draft_picks_by_draft={},
            traded_picks=[],
            winners_bracket=[],
            losers_bracket=[],
        )
        standings = metrics.season_standings(season, registry)
        self.assertEqual(len(standings), len(rosters))
        self.assertEqual(
            {row["ownerId"] for row in standings},
            {"owner_a", "owner_b", "714976074907336704", "720849338183548928"},
        )

    def test_non_retired_owners_still_build_normally(self):
        """Sanity: the filter only affects the DIRECTORY view, not everyone."""
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
