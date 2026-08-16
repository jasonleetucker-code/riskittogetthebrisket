"""C1-ID-01 RED→GREEN: two production matchers disagreeing on real players.

The C1-U2 execution-map RED is "two matchers disagreeing on a real player
on the live board".  Measured on the 2026-08-15 board against the real
Sleeper directory: 10 of 949 player rows, in three defect classes.  This
file pins the disagreement itself (the RED — reproduced through the
engine's legacy-faithful V1 policy and the mapper's own ladder, on real
directory data) and the consolidation's answer (the GREEN — one canonical
policy, CANONICAL_V2, giving one defensible answer per input).

The full measurement is
``docs/identity/C1_ID_01_IDENTITY_CONSOLIDATION.md`` §3; the live corpus
snapshot is the dual-read artifact the scraper now writes every cycle.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.identity import resolution as R
from src.identity import unified_mapper

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "identity_directory_subset.json"


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = json.loads(FIXTURE.read_text(encoding="utf-8"))["players"]
        # unified_mapper indexes the Sleeper-directory shape; the fixture
        # entries lack the "player_id" field Sleeper embeds, so mirror the
        # key in (exactly what the live dump carries).
        cls.mapper_dir = {pid: {**p, "player_id": pid} for pid, p in cls.directory.items()}
        cls.index = R.build_sleeper_index(cls.directory)


class TestRedClassOne_MapperServesTheWrongHomonym(_Base):
    """Class 1: the mapper's name+pos rung takes the FIRST directory hit,
    so for homonym families it serves whichever entry the dump happened to
    list first — measured on the live board serving the RETIRED Frank Gore
    (232) where the scraper (and the board stamp) serve the rostered
    Frank Gore Jr. (11573)."""

    def test_red_the_two_matchers_disagree_on_frank_gore(self):
        # The fixture preserves the live dump's key order (Sr 232 before
        # Jr 11573), which is the order under which the live board's
        # measurement produced mapper -> 232.
        scraper_view = R.resolve_scraper_attach_v1(self.index, "Frank Gore", preferred_pos="RB")
        mapper_view = unified_mapper.resolve_player(
            self.mapper_dir, name="Frank Gore", position="RB"
        )
        self.assertTrue(scraper_view.resolved)
        self.assertIsNotNone(mapper_view)
        # The disagreement IS the finding: same player string, same
        # position, two production matchers, two different humans.
        self.assertEqual(scraper_view.sleeper_id, "11573")
        self.assertEqual(mapper_view.sleeper_id, "232")
        self.assertNotEqual(scraper_view.sleeper_id, mapper_view.sleeper_id)

    def test_red_the_mapper_answer_depends_on_directory_insertion_order(self):
        """The sharpest statement of the defect: same directory CONTENT,
        different insertion order, different HUMAN.  Canonical identity
        must be deterministic; the mapper's name_pos rung is first-wins
        over dict order, so it is not."""
        forward = self.mapper_dir
        backward = dict(reversed(list(self.mapper_dir.items())))
        a = unified_mapper.resolve_player(forward, name="Frank Gore", position="RB")
        b = unified_mapper.resolve_player(backward, name="Frank Gore", position="RB")
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertNotEqual(
            a.sleeper_id,
            b.sleeper_id,
            "if this now FAILS because the two orders agree, the mapper's "
            "first-wins rung has been fixed — move this pin to the engine's "
            "V1 fidelity suite and update the C1-ID-01 design doc",
        )

    def test_green_canonical_v2_serves_the_rostered_player(self):
        got = R.resolve_canonical_v2(self.index, name="Frank Gore", position="RB")
        self.assertTrue(got.resolved)
        self.assertEqual(got.sleeper_id, "11573")


class TestRedClassTwo_MapperRefusesWhereScraperResolves(_Base):
    """Class 2: multi-candidate names where the mapper's name_unique rung
    requires exactly one candidate and its fuzzy walk fails, while the
    scraper's candidate scoring picks the rostered player (measured:
    Chris Jones DL, Milton Williams DL)."""

    def test_red_disagreement_on_chris_jones(self):
        scraper_view = R.resolve_scraper_attach_v1(self.index, "Chris Jones", preferred_pos="DL")
        mapper_view = unified_mapper.resolve_player(
            self.mapper_dir, name="Chris Jones", position="DL"
        )
        self.assertTrue(scraper_view.resolved)
        # The mapper either refuses outright or lands elsewhere; both
        # shapes are the measured disagreement.
        if mapper_view is not None:
            self.assertNotEqual(scraper_view.sleeper_id, mapper_view.sleeper_id)


class TestRedClassThree_ScraperFalseMergesAbsentPlayers(_Base):
    """Class 3: the scraper's unguarded initial+last rung hands an
    absent-from-directory player a sibling or homonym — Whit Weeks →
    West Weeks (his actual brother), Rod Moore → Rahim Moore, Jamarion
    Miller → Jordan Miller.  The mapper correctly refuses all three."""

    CASES = (
        ("Whit Weeks", "13785"),  # West Weeks
        ("Rod Moore", "873"),  # Rahim Moore
        ("Jamarion Miller", "12103"),  # Jordan Miller
    )

    def test_red_the_two_matchers_disagree(self):
        for ghost, wrong_id in self.CASES:
            scraper_view = R.resolve_scraper_attach_v1(self.index, ghost)
            mapper_view = unified_mapper.resolve_player(self.mapper_dir, name=ghost)
            self.assertTrue(scraper_view.resolved, ghost)
            self.assertEqual(scraper_view.sleeper_id, wrong_id, ghost)
            self.assertIsNone(mapper_view, ghost)

    def test_green_canonical_v2_refuses_all_three(self):
        for ghost, _wrong_id in self.CASES:
            got = R.resolve_canonical_v2(self.index, name=ghost)
            self.assertFalse(got.resolved, ghost)
            self.assertEqual(got.reason, R.REASON_NO_CANDIDATE, ghost)


class TestGreenOneOwnerProperty(_Base):
    """The consolidation invariant: for every input in the RED corpus,
    the canonical engine gives exactly ONE answer — resolved with
    provenance, or explicitly unresolved with a reason.  No silent
    first-wins, no policy-dependent identity once cutover completes."""

    RED_INPUTS = (
        ("Byron Young", "DL"),
        ("Chris Johnson", "DB"),
        ("Chris Jones", "DL"),
        ("Frank Gore", "RB"),
        ("Jamarion Miller", None),
        ("Kyle Williams", "WR"),
        ("Milton Williams", "DL"),
        ("Myles Murphy", "DL"),
        ("Rod Moore", None),
        ("Whit Weeks", None),
    )

    def test_every_red_input_gets_one_explicit_answer(self):
        for name, pos in self.RED_INPUTS:
            got = R.resolve_canonical_v2(self.index, name=name, position=pos)
            if got.resolved:
                self.assertTrue(got.sleeper_id)
                self.assertTrue(got.method)
                self.assertIsNotNone(got.confidence)
            else:
                self.assertIn(
                    got.reason,
                    (R.REASON_AMBIGUOUS, R.REASON_NO_CANDIDATE),
                    f"{name}: unresolved must carry an explicit reason",
                )
                if got.reason == R.REASON_AMBIGUOUS:
                    self.assertGreaterEqual(
                        len(got.candidate_ids),
                        2,
                        f"{name}: an ambiguity refusal must name its candidates",
                    )


if __name__ == "__main__":
    unittest.main()
