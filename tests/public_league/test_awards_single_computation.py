"""The awards section computes each season's row sets ONCE per build.

The awards pass and the races pass each recomputed every row set, and the
regular-season VORP board was rebuilt for League/Off/Def MVP and both ROY in
each pass -- ten times per season.  Measured on the live snapshot 2026-09-26:
0.83 s median per build before, 0.14 s after, with byte-identical output.
"""

from __future__ import annotations

import unittest
from unittest import mock

from src.public_league import awards
from tests.public_league.fixtures import build_test_snapshot


class SingleComputationTests(unittest.TestCase):
    def test_vorp_board_is_built_once_per_season(self):
        snapshot = build_test_snapshot()
        begun = [s for s in snapshot.seasons if awards._has_begun(s)]
        with mock.patch.object(awards, "_vorp_board", wraps=awards._vorp_board) as spy:
            awards.build_section(snapshot)
        self.assertEqual(spy.call_count, len(begun))

    def test_trade_and_waiver_rows_are_built_once_per_season(self):
        snapshot = build_test_snapshot()
        begun = [s for s in snapshot.seasons if awards._has_begun(s)]
        with (
            mock.patch.object(
                awards, "_trader_of_the_year_scores", wraps=awards._trader_of_the_year_scores
            ) as trader,
            mock.patch.object(
                awards, "_waiver_king_scores", wraps=awards._waiver_king_scores
            ) as waiver,
        ):
            awards.build_section(snapshot)
        self.assertEqual(trader.call_count, len(begun))
        self.assertEqual(waiver.call_count, len(begun))

    def test_shared_rows_produce_the_same_section_as_standalone_passes(self):
        # The races pass run standalone (its own row computation) must match
        # the races published by build_section (shared rows).
        snapshot = build_test_snapshot()
        section = awards.build_section(snapshot)
        for row, season in zip(section["bySeason"], snapshot.seasons):
            if not awards._has_begun(season):
                continue
            standalone = awards._current_season_races(snapshot, season)
            self.assertEqual(row["finalists"], {r["key"]: r["leaders"] for r in standalone})


if __name__ == "__main__":
    unittest.main()
