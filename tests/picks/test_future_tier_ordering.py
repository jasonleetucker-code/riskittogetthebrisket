"""F-1 — an earlier pick must be worth more than a later one.

The derived-year surface (`derivedYearModel.stepByTierRound`) carries an
independent measured ratio per (tier, round) cell.  The ratios RISE with
tier — late picks decay less year-over-year than early ones — which
compresses the Early–Late spread.  Nothing constrained that compression
to stop before it CROSSES, and on 2029 it does:

    2029 R1: Early=3593  Mid=3676  Late=3446    <- Mid > Early

Six of the twenty-four (year, round) tier cells were inverted, all of
them 2029, the only fully derived year.  The trade calculator therefore
booked a GAIN for downgrading a 2029 early first to a mid first, and
`/rankings` published `2029 Mid 1st` at #117 above `2029 Early 1st` at
#123.  The pick census checked finiteness, not-zero-as-missing and
provenance — never order.

The repair constrains the SURFACE, not the output: within a round the
year step may not increase from Early to Late, enforced by isotonic
projection (pool-adjacent-violators).  Because a constant ratio applied
to a strictly ordered template year yields a strictly ordered derived
year, ordering is preserved BY CONSTRUCTION, for every source, with no
epsilon and no output clamp.
"""

from __future__ import annotations

import re
import unittest

TIERS = ("early", "mid", "late")
_TIER_ROW = re.compile(r"^(\d{4})\s+(Early|Mid|Late)\s+(\d)(?:st|nd|rd|th)$")


class TestTheStepSurfaceCannotInvertOrdering(unittest.TestCase):
    """Deterministic — reads the config owner, not a board."""

    def _surface(self):
        from src.api.data_contract import _load_pick_year_discount, _year_step_for

        cfg = _load_pick_year_discount()
        rounds = sorted(
            {int(k.split(".")[1]) for k in (cfg.get("yearStepByTierRound") or {}) if "." in k}
        )
        return {r: [_year_step_for(t, r, cfg) for t in TIERS] for r in rounds}

    def test_the_step_never_increases_from_early_to_late(self):
        """The invariant that makes ordering structural.

        A ratio that rises with tier compresses the spread; if it rises
        by more than the spread, the order crosses.  Requiring the ratio
        to be non-increasing removes the possibility for ANY correctly
        ordered template year, without needing to know its values.
        """
        offenders = {
            rnd: dict(zip(TIERS, steps))
            for rnd, steps in self._surface().items()
            if not (steps[0] >= steps[1] >= steps[2])
        }
        self.assertEqual(
            offenders,
            {},
            "year-step rises with tier in these rounds, so a correctly ordered "
            "template year can cross when it is applied",
        )

    def test_every_step_is_a_usable_ratio(self):
        for rnd, steps in self._surface().items():
            for tier, step in zip(TIERS, steps):
                with self.subTest(round=rnd, tier=tier):
                    self.assertGreater(step, 0.05)
                    self.assertLessEqual(step, 1.0)

    def test_a_constant_ratio_preserves_a_strict_ordering(self):
        """Why non-increasing is sufficient, stated as a test rather than
        as a comment: equal ratios cannot reorder a strictly ordered
        template, so pooling never produces a tie in VALUE space."""
        template = {"early": 5034.0, "mid": 4551.0, "late": 4133.0}
        for rnd, steps in self._surface().items():
            derived = [template[t] * s for t, s in zip(TIERS, steps)]
            with self.subTest(round=rnd):
                self.assertTrue(
                    derived[0] > derived[1] > derived[2],
                    f"round {rnd}: {dict(zip(TIERS, derived))}",
                )


class TestTheBoardItselfIsOrdered(unittest.TestCase):
    """The invariant on a real contract.

    Asserts ALL-OF-THEM rather than a count or a floor, so it stays a
    statement about our code rather than about which sources answered
    (`docs/ops/STABILIZATION_2026-08-16.md` §3d).
    """

    @classmethod
    def setUpClass(cls):
        from tests.archive_fixtures import newest_complete_raw_payload

        raw, name = newest_complete_raw_payload()
        if not raw:
            raise unittest.SkipTest("no complete archived scrape available")
        from src.api.data_contract import build_api_data_contract

        cls.archive = name
        cls.rows = build_api_data_contract(raw).get("playersArray") or []

    def _cells(self):
        cells: dict[tuple[int, int], dict[str, float]] = {}
        for row in self.rows:
            m = _TIER_ROW.match(str(row.get("displayName") or "").strip())
            if not m:
                continue
            value = row.get("rankDerivedValue")
            if isinstance(value, (int, float)):
                cells.setdefault((int(m.group(1)), int(m.group(3))), {})[m.group(2).lower()] = (
                    float(value)
                )
        return cells

    def test_every_tier_cell_is_ordered_early_over_mid_over_late(self):
        violations = {
            f"{year} R{rnd}": tiers
            for (year, rnd), tiers in sorted(self._cells().items())
            if len(tiers) == 3 and not (tiers["early"] > tiers["mid"] > tiers["late"])
        }
        self.assertEqual(violations, {}, f"tier ordering violated on {self.archive}: {violations}")

    def test_the_cells_exist_at_all(self):
        """A guard that passes because it found nothing to check is not a
        guard — this is what makes the assertion above non-vacuous."""
        self.assertTrue(self._cells(), "no future pick tier rows on the board")


if __name__ == "__main__":
    unittest.main()
