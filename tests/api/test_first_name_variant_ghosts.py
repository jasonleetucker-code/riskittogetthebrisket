"""W06-F001 — one human must not occupy a resolved row and a ghost row.

The board's merge key is a canonical NAME. The scraper's dedup pass folds
punctuation and initial variants by ``normalize_lookup_name``, which does
NOT fold first-name drift: "Matt Hibner" and "Matthew Hibner" normalize
differently, so the vendor spelling became its own row — unresolved, with
no position, no rank, no value, and holding the vendor votes that should
have counted for the real player.

Reproduced on the 2026-08-12 board before the repair:

    Matthew Hibner   ghost, 6 stranded source votes  <- Matt Hibner (TE, 13324)
    Jamarion Miller  ghost, 1 stranded source vote   <- Jam Miller  (RB, 13403)

Exactly the two players the finding named, still live.

The repair is a RULE, not two more entries in ``CANONICAL_NAME_ALIASES``
— enumerating these two would have fixed these two and left the next pair
for the next audit. The rule lives in ``src/utils/name_clean.py`` because
that module is the canonical owner of name handling for both the scraper
and the identity matcher.

**The identity gate is the load-bearing half.** ``is_first_name_variant``
is permissive enough to match "Chris Smith" / "Christian Smith", who may
be two people. A merge additionally requires that exactly one side carries
a Sleeper id and the other carries none — two independently identified
players both have ids and can never be fused — and an ambiguous ghost is
left alone. An explicit ghost beats a confident wrong merge.
"""

from __future__ import annotations

import unittest

from src.utils.name_clean import is_first_name_variant


class TestTheRuleMatchesRealDrift(unittest.TestCase):
    def test_the_two_live_ghosts(self):
        self.assertTrue(is_first_name_variant("Matt Hibner", "Matthew Hibner"))
        self.assertTrue(is_first_name_variant("Jam Miller", "Jamarion Miller"))

    def test_it_is_symmetric(self):
        self.assertEqual(
            is_first_name_variant("Matt Hibner", "Matthew Hibner"),
            is_first_name_variant("Matthew Hibner", "Matt Hibner"),
        )

    def test_common_shortenings(self):
        for a, b in (("Rob Henry", "Robert Henry"), ("Chris Jones", "Christian Jones")):
            self.assertTrue(is_first_name_variant(a, b), f"{a} / {b}")


class TestTheRuleRefusesDistinctPlayers(unittest.TestCase):
    """The direction that matters. Every one of these is a real board pair."""

    def test_different_first_names_never_match(self):
        for a, b in (
            ("Rob Henry", "Derrick Henry"),
            ("Rob Henry", "Hunter Henry"),
            ("Christen Miller", "Jamarion Miller"),
            ("Kendre Miller", "Ventrell Miller"),
            ("Suntarine Perkins", "Harold Perkins"),
            ("Elijah Moore", "Skyy Moore"),
        ):
            self.assertFalse(is_first_name_variant(a, b), f"{a} / {b} were treated as one player")

    def test_a_two_letter_prefix_is_not_enough(self):
        """ "Ty Johnson" and "Tyler Johnson" are different people."""
        self.assertFalse(is_first_name_variant("Ty Johnson", "Tyler Johnson"))

    def test_an_initial_is_not_a_variant(self):
        self.assertFalse(is_first_name_variant("J Smith", "Jamarion Smith"))

    def test_surnames_must_match_exactly(self):
        self.assertFalse(is_first_name_variant("Matt Smith", "Matthew Jones"))

    def test_middle_parts_must_match(self):
        self.assertFalse(is_first_name_variant("Chris Del Rio", "Christian Rio"))

    def test_identical_names_are_not_a_variant_pair(self):
        self.assertFalse(is_first_name_variant("Matt Hibner", "Matt Hibner"))

    def test_single_token_names_are_refused(self):
        self.assertFalse(is_first_name_variant("Matthew", "Matt"))
        self.assertFalse(is_first_name_variant("", ""))

    def test_kenneth_kenny_is_not_a_prefix_pair(self):
        """Handled by CANONICAL_NAME_ALIASES, and correctly NOT by this rule.

        "Kenny" is not a prefix of "Kenneth", so the prefix rule declines
        it. That is the right answer: an authoritative alias belongs in
        the alias table, and this rule must not grow into a general
        nickname guesser.
        """
        self.assertFalse(is_first_name_variant("Kenneth Walker", "Kenny Walker"))


class TestTheGateBlocksWhatTheRuleCannot(unittest.TestCase):
    """The caller-side contract, stated as a test so it cannot be dropped.

    Simulates the scraper's gate: merge only when exactly one candidate
    matches AND the ghost has no id while the candidate does.
    """

    @staticmethod
    def _merge(players: dict) -> dict:
        identified = {n for n, e in players.items() if e.get("_sleeperId")}
        ghosts = [n for n, e in players.items() if not e.get("_sleeperId")]
        out = {k: dict(v) for k, v in players.items()}
        for ghost in sorted(ghosts):
            matches = [n for n in identified if is_first_name_variant(ghost, n)]
            if len(matches) != 1:
                continue
            primary = matches[0]
            for k, v in out[ghost].items():
                if not str(k).startswith("_") and k not in out[primary]:
                    out[primary][k] = v
            out.pop(ghost)
        return out

    def test_the_ghost_is_absorbed_and_its_votes_survive(self):
        got = self._merge(
            {
                "Matt Hibner": {"_sleeperId": "13324", "ktc": 100},
                "Matthew Hibner": {"dlfSf": 250, "idpTradeCalc": 300},
            }
        )
        self.assertEqual(set(got), {"Matt Hibner"})
        self.assertEqual(got["Matt Hibner"]["dlfSf"], 250)
        self.assertEqual(got["Matt Hibner"]["idpTradeCalc"], 300)
        self.assertEqual(got["Matt Hibner"]["ktc"], 100)

    def test_two_identified_players_are_never_fused(self):
        """Even when the name rule says yes."""
        got = self._merge(
            {
                "Chris Smith": {"_sleeperId": "111"},
                "Christian Smith": {"_sleeperId": "222"},
            }
        )
        self.assertEqual(set(got), {"Chris Smith", "Christian Smith"})

    def test_an_ambiguous_ghost_is_left_alone(self):
        """Two identified rows both prefix the ghost — refuse, don't guess.

        Note what does NOT count as ambiguous: "Matt Smith" identified,
        "Matthias Smith" identified, "Matthew Smith" a ghost. Only "Matt"
        prefixes "Matthew" ("Matthias" does not), so that is a single
        match and merging it is correct. Ambiguity requires two genuine
        prefix candidates, which is rare precisely because the prefix
        rule is strict.
        """
        got = self._merge(
            {
                "Chris Smith": {"_sleeperId": "111"},
                "Christ Smith": {"_sleeperId": "222"},
                "Christian Smith": {"dlfSf": 10},
            }
        )
        self.assertIn("Christian Smith", got)
        self.assertEqual(len(got), 3)

    def test_a_ghost_with_no_match_stays_a_ghost(self):
        got = self._merge({"Barika Kpeenu": {}, "Matt Hibner": {"_sleeperId": "13324"}})
        self.assertEqual(set(got), {"Barika Kpeenu", "Matt Hibner"})


if __name__ == "__main__":
    unittest.main()
