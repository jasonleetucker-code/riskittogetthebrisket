"""A matchup whose roster has no resolvable owner must still build.

The defect this pins, measured against live Sleeper on 2026-08-05:
**28 of 158** advertised public matchup recaps returned 404.

Two validity criteria disagreed.  ``matchup_recap.list_matchups`` admits a
pair on "two entries and either side scored" and never checks owner
attribution, while ``_side_block`` returned ``None`` whenever
``metrics.resolve_owner`` came back empty — and
``build_matchup_recap`` bails if either side is ``None``, so
``server.py`` 404s.  ``identity.build_manager_registry`` deliberately does
not register rosters whose owner is orphaned or in ``_RETIRED_OWNER_IDS``
(see ``test_identity_retirement.py``), so every 2024 game involving the two
retired managers advertised a link that could not be built.

The asymmetry was the defect, not the retirement list.  The archive keeps
every real game reachable, attributed to the roster rather than to a
person; retired managers stay out of dropdowns and franchise pages because
that filtering lives in ``identity.py``, which is untouched.

Guard both directions — a resolved owner must NOT acquire the fallback,
or the retirement list would be silently doing nothing.
"""

from __future__ import annotations

import unittest

from src.public_league import matchup_recap

from tests.public_league.fixtures import build_test_snapshot


class TestUnresolvedOwnerStillBuilds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = build_test_snapshot()

    def _first_built_matchup(self):
        for row in matchup_recap.list_matchups(self.snapshot):
            built = matchup_recap.build_matchup_recap(
                self.snapshot, str(row["season"]), int(row["week"]), int(row["matchupId"])
            )
            if built is not None:
                return row, built
        self.fail("fixture produced no buildable matchup at all")

    def test_every_advertised_matchup_can_be_built(self):
        """The index must not advertise a recap the detail cannot build.

        This is the invariant the 28/158 violated.  It is asserted over the
        whole index rather than a sample, because the failing subset was a
        specific season/roster pair that a sample would miss.
        """
        rows = matchup_recap.list_matchups(self.snapshot)
        self.assertGreater(len(rows), 0, "fixture snapshot advertises no matchups")
        unbuildable = [
            f"{r['season']} wk{r['week']} m{r['matchupId']}"
            for r in rows
            if matchup_recap.build_matchup_recap(
                self.snapshot, str(r["season"]), int(r["week"]), int(r["matchupId"])
            )
            is None
        ]
        self.assertEqual(
            unbuildable,
            [],
            "list_matchups advertised recaps that build_matchup_recap returns None for — "
            "server.py 404s on each of these:\n" + "\n".join(unbuildable),
        )

    def test_unresolved_owner_renders_a_labelled_side(self):
        """Strip a roster's owner and the recap must survive, labelled."""
        row, _ = self._first_built_matchup()
        season = self.snapshot.season_by_year(str(row["season"]))

        # Drop every roster->owner mapping for this league so both sides
        # resolve empty — the both-retired case, which is also the one that
        # would break a winner comparison keyed on ownerId.
        registry = self.snapshot.managers
        removed = {k: v for k, v in registry.roster_to_owner.items() if k[0] == season.league_id}
        self.assertTrue(removed, "fixture had no roster->owner rows to remove")
        for key in removed:
            del registry.roster_to_owner[key]
        try:
            built = matchup_recap.build_matchup_recap(
                self.snapshot, str(row["season"]), int(row["week"]), int(row["matchupId"])
            )
            self.assertIsNotNone(built, "an unresolved owner must not 404 the whole recap")
            for side_name in ("home", "away"):
                side = built[side_name]
                self.assertFalse(side["ownerResolved"], f"{side_name} should be flagged unresolved")
                self.assertEqual(side["displayName"], "Former manager")
                self.assertTrue(
                    side["teamName"].startswith("Team "),
                    f"expected a roster-derived team name, got {side['teamName']!r}",
                )
                self.assertTrue(
                    side["ownerId"].startswith("retired:"),
                    f"expected a synthetic owner id, got {side['ownerId']!r}",
                )

            # The load-bearing uniqueness property: the UI marks a winner
            # with `winnerOwnerId === side.ownerId`.  A shared "" would make
            # BOTH sides compare equal and both render as the winner.
            self.assertNotEqual(
                built["home"]["ownerId"],
                built["away"]["ownerId"],
                "synthetic owner ids must differ per roster or the winner "
                "comparison marks both sides the winner",
            )
        finally:
            registry.roster_to_owner.update(removed)

    def test_resolved_owner_is_untouched(self):
        """The fallback must not fire for a manager who IS registered."""
        _, built = self._first_built_matchup()
        for side_name in ("home", "away"):
            side = built[side_name]
            self.assertTrue(
                side["ownerResolved"],
                f"{side_name} resolved in the fixture; fallback must not fire",
            )
            self.assertNotEqual(side["displayName"], "Former manager")
            self.assertFalse(side["ownerId"].startswith("retired:"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
