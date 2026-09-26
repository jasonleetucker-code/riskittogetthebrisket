"""The recap's scoring-tone sentence is a fact about THIS league's own weeks.

The old block compared the week with hard-coded 150 / 130 / 95 / 100-point
marks and counted only the top-3 sides.  Measured on the persisted snapshot
2026-09-26: all 36 recaps carried a tone sentence -- 18 "3 of N teams cracked
150+, a high-scoring week across the board" (every one false: e.g. 2026 week 2,
all 12 teams scored 278+) and 18 "well above league norm" with no norm
measured.  The only claim now made is a rank within the season's earlier
finished weeks.
"""

from __future__ import annotations

import unittest

from src.public_league import weekly_recap
from tests.public_league.test_recap_finished_weeks import _season, _snapshot, _week


def _summaries(weeks: dict[int, list[dict]]) -> dict[int, str]:
    snap = _snapshot(_season(weeks, last_scored_leg=max(weeks)))
    section = weekly_recap.build_section(snap)
    return {r["week"]: r["summary"] for r in section["weeks"]}


class ScoringToneTests(unittest.TestCase):
    def test_no_fixed_threshold_claims_ever(self):
        # Every side scores 278+: the old block said "3 of 4 teams cracked 150+".
        summaries = _summaries({1: _week(300.0, 290.0, 285.0, 278.0)})
        text = summaries[1]
        self.assertNotIn("cracked", text)
        self.assertNotIn("league norm", text)
        self.assertNotIn("Sluggish", text)

    def test_first_week_makes_no_tone_claim(self):
        text = _summaries({1: _week(300.0, 290.0, 285.0, 278.0)})[1]
        self.assertNotIn("so far", text)

    def test_highest_and_lowest_are_ranks_within_the_season(self):
        summaries = _summaries(
            {
                1: _week(300.0, 290.0, 285.0, 278.0),  # avg 288.25
                2: _week(320.0, 310.0, 305.0, 300.0),  # avg 308.75 -> highest so far
                3: _week(250.0, 240.0, 235.0, 230.0),  # avg 238.75 -> lowest so far
                4: _week(290.0, 280.0, 275.0, 270.0),  # avg 278.75 -> neither
            }
        )
        self.assertIn(
            "308.8 points per side — the highest weekly average of the 2026 season so far",
            summaries[2],
        )
        self.assertIn(
            "238.8 points per side — the lowest weekly average of the 2026 season so far",
            summaries[3],
        )
        self.assertNotIn("so far", summaries[4])


if __name__ == "__main__":
    unittest.main()
