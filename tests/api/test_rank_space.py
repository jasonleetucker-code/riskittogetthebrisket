"""The primitive that makes ranks from different boards comparable.

These are the properties the market gap rests on. The module is
deliberately policy-free — it does not know what a retail source is — so
what is pinned here is arithmetic and abstention, not signal semantics.
"""

from __future__ import annotations

import unittest

from src.api.rank_space import (
    PER_MILLE,
    RANK_SPACE_UNIT,
    mean_rank_space,
    pool_depths,
    position_basis,
    to_rank_space,
)


class TestPoolDepths(unittest.TestCase):
    def test_depth_is_the_deepest_rank_observed(self) -> None:
        depths = pool_depths(
            [
                {"a": 10, "b": 400},
                {"a": 250, "b": 100},
                {"a": 30},
            ]
        )
        self.assertEqual(depths, {"a": 250, "b": 400})

    def test_a_source_nobody_ranked_simply_has_no_depth(self) -> None:
        """Absent, not zero — a zero depth would divide by nothing."""
        self.assertEqual(pool_depths([{"a": 5}]), {"a": 5})
        self.assertNotIn("b", pool_depths([{"a": 5}]))

    def test_junk_ranks_do_not_establish_a_depth(self) -> None:
        depths = pool_depths([{"a": None, "b": "40", "c": 0, "d": -3, "e": True, "f": 12}])
        self.assertEqual(depths, {"f": 12})

    def test_non_mapping_entries_are_skipped(self) -> None:
        self.assertEqual(pool_depths([None, "nope", {"a": 4}]), {"a": 4})


class TestToRankSpace(unittest.TestCase):
    def test_places_a_rank_on_its_own_boards_scale(self) -> None:
        self.assertAlmostEqual(to_rank_space(50, 500), 0.10)
        self.assertAlmostEqual(to_rank_space(50, 100), 0.50)

    def test_the_same_ordinal_means_different_things_on_different_boards(self) -> None:
        """The finding, as one assertion.

        Measured on the live board: draftSharks rank 143 of 683 is a
        BETTER placement than ktcSfTep rank 121 of 469, and ordinal
        arithmetic said the reverse.
        """
        self.assertLess(to_rank_space(143, 683), to_rank_space(121, 469))

    def test_unusable_input_is_none_never_zero(self) -> None:
        """0.0 is the TOP of a board — the most valuable placement there
        is — so coercing an unknown into it would be the substitution
        this whole remediation pass exists to remove."""
        for rank, depth in ((None, 100), (10, None), (0, 100), (10, 0), (-1, 100), (10, -1)):
            with self.subTest(rank=rank, depth=depth):
                self.assertIsNone(to_rank_space(rank, depth))

    def test_booleans_are_not_ranks(self) -> None:
        self.assertIsNone(to_rank_space(True, 100))
        self.assertIsNone(to_rank_space(10, True))


class TestMeanRankSpace(unittest.TestCase):
    def test_averages_in_rank_space_not_ordinal_space(self) -> None:
        value, excluded = mean_rank_space({"a": 50, "b": 500}, {"a": 100, "b": 1000})
        self.assertAlmostEqual(value, 0.50)  # both are half-way down
        self.assertEqual(excluded, 0)

    def test_reports_what_it_could_not_place(self) -> None:
        """ "The mean of the four we could place" is a different claim
        from "the mean of six", and a caller that cannot tell them apart
        will make the second."""
        value, excluded = mean_rank_space({"a": 50, "b": 20}, {"a": 100})
        self.assertAlmostEqual(value, 0.50)
        self.assertEqual(excluded, 1)

    def test_nothing_placeable_is_none(self) -> None:
        value, excluded = mean_rank_space({"a": 50}, {})
        self.assertIsNone(value)
        self.assertEqual(excluded, 1)

    def test_keys_restricts_the_population(self) -> None:
        ranks = {"a": 10, "b": 900}
        depths = {"a": 100, "b": 1000}
        value, _ = mean_rank_space(ranks, depths, ["a"])
        self.assertAlmostEqual(value, 0.10)

    def test_a_key_absent_from_ranks_is_not_an_exclusion(self) -> None:
        """Asking about a source this row never had is not a failure to
        place one it did."""
        _value, excluded = mean_rank_space({"a": 10}, {"a": 100}, ["a", "b"])
        self.assertEqual(excluded, 0)


class TestPositionBasis(unittest.TestCase):
    def test_uses_the_median_not_the_mean(self) -> None:
        """A handful of genuinely mispriced players must not move the
        constant that describes everyone else."""
        gaps = [0.10, 0.11, 0.12, 0.13, 9.0, 0.09, 0.10, 0.11]
        basis = position_basis({"TE": gaps}, min_sample=8)
        self.assertAlmostEqual(basis["TE"], 0.11, places=6)
        # The contrast is the point: one absurd outlier drags the mean
        # more than tenfold past every real observation, and a basis
        # that moved like that would subtract a fiction from every other
        # player at the position.
        self.assertGreater(sum(gaps) / len(gaps), 1.0)

    def test_a_position_below_the_sample_floor_gets_no_basis(self) -> None:
        """De-meaning off three players invents a constant out of the
        very noise it exists to remove, so the caller must abstain."""
        basis = position_basis({"K": [0.1, 0.2, 0.3]}, min_sample=8)
        self.assertNotIn("K", basis)

    def test_junk_values_do_not_count_toward_the_sample(self) -> None:
        gaps = [0.1] * 7 + [None, "x", True]
        basis = position_basis({"TE": gaps}, min_sample=8)
        self.assertNotIn("TE", basis)

    def test_the_measured_live_shape_reproduces(self) -> None:
        """Sanity check against the numbers this batch was designed on.

        TE and PICK are the basis offsets; WR/RB/QB sit near zero. The
        6x separation is what makes de-meaning worth doing at all.
        """
        basis = position_basis(
            {
                "TE": [0.121] * 10,
                "PICK": [-0.109] * 10,
                "WR": [0.020] * 10,
                "QB": [-0.007] * 10,
            },
            min_sample=8,
        )
        self.assertGreater(basis["TE"] * PER_MILLE, 100)
        self.assertLess(basis["PICK"] * PER_MILLE, -100)
        self.assertLess(abs(basis["WR"] * PER_MILLE), 25)
        self.assertLess(abs(basis["QB"] * PER_MILLE), 25)


class TestUnitIsSelfDescribing(unittest.TestCase):
    def test_the_unit_string_travels_with_the_number(self) -> None:
        """The magnitude changed units in this batch, from ordinal ranks
        to this. A consumer still gating on the old unit would produce a
        plausible wrong answer rather than an error, so every payload
        stamps what it is."""
        self.assertEqual(RANK_SPACE_UNIT, "rankSpacePerMille")
        self.assertEqual(PER_MILLE, 1000)


if __name__ == "__main__":
    unittest.main()
