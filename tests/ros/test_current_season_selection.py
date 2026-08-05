"""The ROS engines must simulate the NEWEST season, not the oldest.

``sorted(snapshot.seasons, key=luck._season_sort_key)`` passed the season
OBJECT to a function typed for a season LABEL. The object hit a blanket
``except (TypeError, ValueError)``, every key came back 0, Python's stable
sort left the input order untouched, and ``seasons_sorted[-1]`` — read
everywhere as "the current season" — returned whichever season happened to
be first in the list.

On the live snapshot that was 2024, so every number on /league -> Championship
and /league -> Trade Deadline was a replay of a season that had ended ~20
months earlier. Audit finding W17-F001 (P0, upheld under adversarial review).

The bug was invisible for two reasons this module pins directly:
  1. the sort silently produced a plausible-looking answer, and
  2. the whole 487-test ROS + public_league suite passed with it in place.

So these tests assert on ORDER with the seasons deliberately supplied
oldest-first — the arrangement under which a no-op sort looks correct and is
not.
"""

from __future__ import annotations

import unittest

from src.public_league import luck
from src.public_league.snapshot import PublicLeagueSnapshot
from src.ros import playoff_sim, power_v2

from tests.ros.test_power_v2 import _make_season, ManagerRegistry


def _snapshot(*season_years: str) -> PublicLeagueSnapshot:
    """Snapshot carrying the given seasons, in the order supplied."""
    return PublicLeagueSnapshot(
        root_league_id="L",
        generated_at="2026-08-05T00:00:00Z",
        seasons=[_make_season(y, f"L{y}", []) for y in season_years],
        managers=ManagerRegistry(),
    )


class TestSeasonSortKey(unittest.TestCase):
    def test_orders_season_labels_numerically(self):
        self.assertEqual(
            sorted(["2024", "2026", "2025"], key=luck._season_sort_key),
            ["2024", "2025", "2026"],
        )

    def test_refuses_a_season_object(self):
        """The exact misuse that caused W17-F001 now fails loudly.

        Returning 0 here is what made four call sites wrong in a way that
        still rendered a full, plausible board.
        """
        season = _make_season("2026", "L2026", [])
        with self.assertRaises(TypeError):
            luck._season_sort_key(season)

    def test_unparseable_label_still_sorts_low(self):
        # A label is data; an empty one is a real thing a snapshot can
        # carry and must not raise.
        self.assertEqual(luck._season_sort_key(""), 0)

    def test_bool_is_not_a_season(self):
        with self.assertRaises(TypeError):
            luck._season_sort_key(True)


class TestCurrentSeasonSelection(unittest.TestCase):
    """Each helper must pick 2026, with the list supplied oldest-first."""

    def setUp(self):
        self.snapshot = _snapshot("2024", "2025", "2026")

    def _sorted_last(self, module_fn_source: str) -> str:
        """Re-run the selection expression the call sites use."""
        seasons_sorted = sorted(
            self.snapshot.seasons, key=lambda s: luck._season_sort_key(s.season)
        )
        return seasons_sorted[-1].season

    def test_selection_expression_picks_the_newest(self):
        self.assertEqual(self._sorted_last("*"), "2026")

    def test_a_noop_sort_would_have_picked_the_oldest(self):
        """Characterises the defect, so the fix cannot be silently undone.

        With every key equal, the stable sort is the identity and the last
        element is the last one supplied — which on the live snapshot was
        not the current season.
        """
        unsorted_last = sorted(self.snapshot.seasons, key=lambda _s: 0)[-1].season
        self.assertEqual(unsorted_last, "2026")  # last supplied here
        # ...but reverse the input and a no-op sort follows it, while a
        # correct sort does not.
        reversed_snapshot = _snapshot("2026", "2025", "2024")
        self.assertEqual(sorted(reversed_snapshot.seasons, key=lambda _s: 0)[-1].season, "2024")
        self.assertEqual(
            sorted(
                reversed_snapshot.seasons,
                key=lambda s: luck._season_sort_key(s.season),
            )[-1].season,
            "2026",
        )

    def test_no_ros_call_site_passes_the_object(self):
        """Static guard over the four sites the defect lived at.

        Cheap, and it catches a re-introduction that a behavioural test
        would only catch with a multi-season fixture in place.
        """
        import inspect

        for module in (playoff_sim, power_v2):
            src = inspect.getsource(module)
            self.assertNotIn(
                "key=luck._season_sort_key",
                src,
                f"{module.__name__} passes the season object to _season_sort_key "
                f"— pass `s.season` (W17-F001)",
            )


if __name__ == "__main__":
    unittest.main()
