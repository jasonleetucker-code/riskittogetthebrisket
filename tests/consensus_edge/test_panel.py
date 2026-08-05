"""As-of reconstruction, and the leakage it exists to prevent.

The panel replays TODAY's pipeline over a PAST date's inputs.  That is
only meaningful if the inputs really are the past date's — and the
pipeline reads a large part of its input from ``CSVs/site_raw`` on disk,
which is always current.  Forgetting to redirect that read produces a
board that looks entirely valid and is contaminated with the future.

Measured on 2026-05-01: without ``csv_root``, **682 of 692** priced rows
carried a fair value computed partly from August data.  A backtest built
on that would report excellent accuracy and mean nothing.  Hence
:class:`TestNoLookAheadLeakage`, which is the most important class here.
"""

from __future__ import annotations

import functools
import unittest
from datetime import date, timedelta

from src.api.data_contract import build_api_data_contract
from src.consensus_edge import panel
from src.consensus_edge.fair_value import fair_value_index

_deep_only = unittest.skipIf(
    panel.is_shallow(),
    "shallow clone: as-of reconstruction needs full history (git fetch --unshallow)",
)

# The offense market anchor.  Fair value is routed per asset class from
# the board that excluded that class's anchor, and offense is the only
# class the anchor-free build can price at all, so a replay without this
# CSV prices nothing.
_ANCHOR_STEM = "ktcSfTep"


@functools.lru_cache(maxsize=1)
def _oldest_replayable_date() -> date:
    """Oldest panel date whose replay materialises the offense anchor CSV.

    The leakage tests below want the OLDEST date — it maximises the gap
    between the historical CSVs and today's, which is the difference they
    exist to detect.  They used to take ``available_dates()[0]``
    literally, which is 2026-04-16; ``CSVs/site_raw/ktcSfTep.csv`` was
    first committed on 2026-04-27.  For those eleven days the replay has
    no anchor at all, so both sides of the comparison come back unpriced
    and the test fails on its own has-enough-data guard rather than on
    leakage.

    Scanning for the precondition rather than hardcoding the date keeps
    this honest if history is ever rewritten or the anchor changes: the
    test still runs on the oldest date it CAN run on, and skips loudly if
    there is none.  Roughly a dozen git materialisations, ~2s, cached.
    """
    for target in panel.available_dates():
        with panel.panel_day(target) as day:
            if _ANCHOR_STEM in day.csv_sources:
                return target
    raise unittest.SkipTest(f"no panel date materialises {_ANCHOR_STEM}.csv")


@_deep_only
class TestAvailability(unittest.TestCase):
    def setUp(self):
        self.dates = panel.available_dates()

    def test_the_panel_is_not_empty(self):
        self.assertGreater(
            len(self.dates), 30, "expected a multi-month panel from committed history"
        )

    def test_dates_are_contiguous_and_ordered(self):
        for earlier, later in zip(self.dates, self.dates[1:]):
            self.assertEqual(later - earlier, timedelta(days=1))

    def test_the_window_can_be_narrowed(self):
        start, end = self.dates[5], self.dates[10]
        narrowed = panel.available_dates(start=start, end=end)
        self.assertEqual(narrowed[0], start)
        self.assertEqual(narrowed[-1], end)

    def test_an_impossible_window_yields_nothing_rather_than_raising(self):
        self.assertEqual(panel.available_dates(start=date(2030, 1, 1)), [])


@_deep_only
class TestReconstruction(unittest.TestCase):
    def test_a_day_reconstructs_with_both_inputs(self):
        target = panel.available_dates()[len(panel.available_dates()) // 2]
        with panel.panel_day(target) as day:
            self.assertEqual(day.as_of, target)
            self.assertTrue(day.payload.get("players"), "payload has no players")
            self.assertTrue(day.csv_root and day.csv_root.is_dir())
            self.assertGreater(len(day.csv_sources), 10, "too few source CSVs materialised")
            self.assertTrue(day.model_is_current, "a git replay always uses current model code")

    def test_the_temporary_tree_is_removed_on_exit(self):
        target = panel.available_dates()[-1]
        with panel.panel_day(target) as day:
            root = day.csv_root
            self.assertTrue(root.is_dir())
        self.assertFalse(root.exists(), "replay CSVs outlived their context manager")

    def test_a_reconstructed_payload_builds_a_real_board(self):
        target = panel.available_dates()[len(panel.available_dates()) // 2]
        with panel.panel_day(target) as day:
            contract = build_api_data_contract(day.payload, csv_root=day.csv_root)
        priced = [r for r in contract["playersArray"] if r.get("rankDerivedValue")]
        self.assertGreater(len(priced), 200, "historical board is implausibly thin")


@_deep_only
class TestNoLookAheadLeakage(unittest.TestCase):
    """The panel must not be able to see the future.

    Both tests here compare a properly-scoped replay against a
    deliberately unscoped one.  If the unscoped variant ever stops
    differing, either the redirect silently stopped working or the CSVs
    stopped changing — and both mean this suite is no longer testing
    anything, so the assertion is written to fail in that case.
    """

    def test_omitting_csv_root_changes_the_answer(self):
        target = _oldest_replayable_date()
        with panel.panel_day(target) as day:
            contaminated = fair_value_index(day.payload)
            clean = fair_value_index(day.payload, csv_root=day.csv_root)

        compared = [
            k
            for k in clean
            if k in contaminated and clean[k]["fairValue"] and contaminated[k]["fairValue"]
        ]
        self.assertGreater(len(compared), 50, "not enough overlap to detect leakage")
        differing = [
            k for k in compared if abs(clean[k]["fairValue"] - contaminated[k]["fairValue"]) > 1
        ]
        self.assertGreater(
            len(differing),
            0,
            "csv_root made no difference — the historical redirect is not working, "
            "so every 'historical' fair value may be computed from current data",
        )

    def test_a_replayed_board_uses_the_historical_source_files(self):
        target = _oldest_replayable_date()
        with panel.panel_day(target) as day:
            historical = build_api_data_contract(day.payload, csv_root=day.csv_root)
            current_csvs = build_api_data_contract(day.payload)

        def values(contract):
            return {
                r.get("displayName"): r.get("rankDerivedValue")
                for r in contract["playersArray"]
                if r.get("rankDerivedValue")
            }

        hist, curr = values(historical), values(current_csvs)
        shared = set(hist) & set(curr)
        moved = [k for k in shared if hist[k] != curr[k]]
        self.assertGreater(
            len(moved),
            0,
            "the same payload scored identically against historical and current CSVs",
        )


@_deep_only
class TestShallowCloneRefusal(unittest.TestCase):
    """A shallow clone must refuse, not quietly under-report.

    The whole project nearly shipped on the belief that 21 days of
    history existed, because a shallow clone answers questions about
    history without mentioning that it only has some of it.
    """

    def test_shallow_detection_raises_with_an_actionable_message(self):
        from unittest import mock

        with mock.patch.object(panel, "is_shallow", return_value=True):
            with self.assertRaises(panel.PanelUnavailable) as ctx:
                panel.available_dates()
        self.assertIn("unshallow", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()


@_deep_only
class TestRetainedPlayerctx(unittest.TestCase):
    """Dated playerctx snapshots, replayed by the same git primitives.

    ADR-026 deferred retention partly on my own claim that it would need
    "zero new replay code". That was wrong — `available_dates` intersects
    two hardcoded pathspecs and `PanelDay` had no field for it — and
    these pin the design that replaced the claim.
    """

    def test_a_date_before_retention_is_none_not_an_error(self):
        """Absence must not take a fold down with it.

        Retention started 2026-08-05. Every existing panel date predates
        it, so if a missing snapshot raised — the way a missing payload
        correctly does — the whole panel would stop reconstructing.
        """
        target = panel.available_dates()[0]
        with panel.panel_day(target) as day:
            self.assertIsNone(day.playerctx)
            self.assertIsNone(day.playerctx_commit)
            # And the day is otherwise fully usable.
            self.assertTrue(day.payload)

    def test_retention_does_not_narrow_the_panel(self):
        """The trap that would have traded 111 dates for zero.

        If playerctx joined `available_dates`' intersection, the panel
        would collapse to dates on or after retention started and grow
        back one per week — every existing measurement lost to a feature
        with no data yet.
        """
        self.assertGreater(len(panel.available_dates()), 30)
        self.assertNotIn(panel.PLAYERCTX_REL, (panel.LATEST_REL, panel.SITE_RAW_REL))

    def test_the_lookup_is_absent_rather_than_raising_for_an_unretained_date(self):
        self.assertIsNone(panel.playerctx_asof(panel.available_dates()[0]))
