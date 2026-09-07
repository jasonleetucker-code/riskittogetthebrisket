"""Tests for the Manual External AI narrative workflow.

Owner decision 2026-08-14
(docs/WEEKLY_REPORT_STUDIO_MANUAL_AI_ARCHITECTURE_2026-08-14.md): Manual
External AI is the DEFAULT generation mode, makes zero site-side LLM/API
calls, and must feed the same storage/schema/validation boundary as the
On-Demand API path (``generate_article``/``save_article``) — no second
article-generation owner (WEEK_1_LAUNCH_CONTRACT.md row W1-06).

Coverage map:
    * ``build_manual_package`` — zero API calls, provider-neutral, carries
      identity + a deterministic ``sourceSnapshotId``.
    * ``validate_manual_article`` — catches missing fields, cross-week/
      season/matchup/mode identity mismatches, missing matchup-specific
      detail, placeholder leftovers, private-vocabulary leakage onto a
      public page, too-short content, and repetition against prior
      articles / the rest of the weekly batch. A well-formed candidate
      passes cleanly.
    * ``import_manual_article`` — fails closed (no save) on invalid input
      unless ``force``; on success it writes through the SAME
      ``save_article``/``article_path`` every other path uses, stamped
      ``generationMode="MANUAL_IMPORT"``.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from src.public_league import matchup_narrative as mn
from tests.public_league.fixtures import build_test_snapshot


def _good_candidate(**overrides):
    candidate = {
        "season": "2025",
        "week": 16,
        "matchupId": 1,
        "mode": "recap",
        "title": "AAron and Bea Settle It in the Championship",
        "lede": "One team came out on top, and the league's history book gets a new entry.",
        "body": (
            "AAron and Bea met in the championship, and the result is now part of league "
            "lore. Bea's roster produced enough to take the title, closing out a season "
            "that came down to the final week. AAron's build got them to the title game "
            "but fell just short when it mattered most, a familiar story for a team that "
            "spent the whole year one step behind the eventual champion.\n\n"
            "There is no shortage of storylines here — a championship matchup between "
            "AAron and Bea is exactly the kind of finish this league wanted, and both "
            "managers have plenty to build on heading into next season. Bea's title run "
            "is the headline; AAron's runner-up finish is still a real accomplishment in "
            "a league this competitive, and the offseason will be about closing that "
            "final gap.\n\n"
            "Both rosters earned their way to this game the hard way, through a full "
            "regular season and a playoff bracket that did not make it easy on anyone. "
            "Bea now has a championship banner to show for it; AAron has a roster that "
            "was one matchup away from the same result and every reason to believe next "
            "year is the year that gap finally closes for good."
        ),
        "kicker": "Bea's championship is the story of the season.",
        "angleUsed": "championship-stakes",
        "wordCount": 130,
    }
    candidate.update(overrides)
    return candidate


class BuildManualPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = build_test_snapshot()
        cls.brief = mn.build_brief(cls.snapshot, season="2025", week=16, matchup_id=1, mode="recap")
        assert cls.brief is not None

    def test_package_is_provider_neutral_and_carries_identity(self) -> None:
        package = mn.build_manual_package(self.brief)
        self.assertEqual(package["schemaVersion"], mn.SCHEMA_VERSION)
        self.assertEqual(package["stage"], "POSTGAME")
        self.assertEqual(package["season"], "2025")
        self.assertEqual(package["week"], 16)
        self.assertEqual(package["matchupId"], 1)
        self.assertTrue(package["systemPrompt"])
        self.assertTrue(package["userPrompt"])
        # No Anthropic-specific structure (cache_control blocks, message
        # role lists) leaks into the provider-neutral package — it's flat
        # text any chat LLM's system/user fields can take directly.
        self.assertIsInstance(package["systemPrompt"], str)
        self.assertIsInstance(package["userPrompt"], str)
        self.assertIn("MATCHUP BRIEF", package["userPrompt"])

    def test_source_snapshot_id_is_deterministic(self) -> None:
        p1 = mn.build_manual_package(self.brief)
        p2 = mn.build_manual_package(self.brief)
        self.assertEqual(p1["sourceSnapshotId"], p2["sourceSnapshotId"])
        self.assertEqual(len(p1["sourceSnapshotId"]), 16)


class ValidateManualArticleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = build_test_snapshot()
        cls.brief = mn.build_brief(cls.snapshot, season="2025", week=16, matchup_id=1, mode="recap")
        assert cls.brief is not None

    def test_well_formed_candidate_passes(self) -> None:
        result = mn.validate_manual_article(_good_candidate(), brief=self.brief)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.errors, [])

    def test_missing_required_field_fails(self) -> None:
        candidate = _good_candidate()
        del candidate["kicker"]
        result = mn.validate_manual_article(candidate, brief=self.brief)
        self.assertFalse(result.ok)
        self.assertTrue(any("kicker" in e for e in result.errors))

    def test_cross_week_import_fails_closed(self) -> None:
        # Spec §7: "prevent cross-week/cross-season accidental imports."
        candidate = _good_candidate(week=5)
        result = mn.validate_manual_article(candidate, brief=self.brief)
        self.assertFalse(result.ok)
        self.assertTrue(any("week mismatch" in e for e in result.errors))

    def test_cross_season_import_fails_closed(self) -> None:
        candidate = _good_candidate(season="2024")
        result = mn.validate_manual_article(candidate, brief=self.brief)
        self.assertFalse(result.ok)
        self.assertTrue(any("season mismatch" in e for e in result.errors))

    def test_wrong_stage_import_fails_closed(self) -> None:
        candidate = _good_candidate(mode="preview")
        result = mn.validate_manual_article(candidate, brief=self.brief)
        self.assertFalse(result.ok)
        self.assertTrue(any("mode mismatch" in e for e in result.errors))

    def test_missing_matchup_specific_detail_fails(self) -> None:
        candidate = _good_candidate(
            title="A Big Win",
            lede="Someone won the league championship this week.",
            body="It was a great game with a great result for the winning team.",
            kicker="What a season.",
        )
        result = mn.validate_manual_article(candidate, brief=self.brief)
        self.assertFalse(result.ok)
        self.assertTrue(any("matchup-specific detail missing" in e for e in result.errors))

    def test_placeholder_text_fails(self) -> None:
        candidate = _good_candidate(body=_good_candidate()["body"] + "\n\nTODO: add more detail.")
        result = mn.validate_manual_article(candidate, brief=self.brief)
        self.assertFalse(result.ok)
        self.assertTrue(any("placeholder" in e for e in result.errors))

    def test_private_vocabulary_leak_fails(self) -> None:
        candidate = _good_candidate(
            body=_good_candidate()["body"] + "\n\nBea's win probability was always the highest."
        )
        result = mn.validate_manual_article(candidate, brief=self.brief)
        self.assertFalse(result.ok)
        self.assertTrue(any("private decision-intelligence vocabulary" in e for e in result.errors))

    def test_too_short_fails(self) -> None:
        candidate = _good_candidate(body="AAron and Bea played.", lede="Short.")
        result = mn.validate_manual_article(candidate, brief=self.brief)
        self.assertFalse(result.ok)
        self.assertTrue(any("too short" in e for e in result.errors))

    def test_repetition_against_prior_article_is_a_warning_not_an_error(self) -> None:
        prior = [{"title": _good_candidate()["title"], "lede": "Some other lede entirely."}]
        result = mn.validate_manual_article(
            _good_candidate(), brief=self.brief, prior_articles=prior
        )
        self.assertFalse(result.ok)  # identical title -> error, not just a warning
        self.assertTrue(any("identical to a prior article" in e for e in result.errors))

    def test_angle_reused_across_batch_is_only_a_warning(self) -> None:
        candidate = _good_candidate()
        other1 = _good_candidate(matchupId=2, angleUsed="championship-stakes")
        other2 = _good_candidate(matchupId=3, angleUsed="championship-stakes")
        result = mn.validate_manual_article(
            candidate, brief=self.brief, batch=[candidate, other1, other2]
        )
        self.assertTrue(result.ok)
        self.assertTrue(any("reused by" in w for w in result.warnings))


class ImportManualArticleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["LEAGUE_NARRATIVES_DIR"] = self.tmp.name
        self.base = Path(self.tmp.name)
        self.snapshot = build_test_snapshot()
        self.brief = mn.build_brief(
            self.snapshot, season="2025", week=16, matchup_id=1, mode="recap"
        )
        assert self.brief is not None

    def tearDown(self) -> None:
        os.environ.pop("LEAGUE_NARRATIVES_DIR", None)
        self.tmp.cleanup()

    def test_valid_import_saves_through_the_one_canonical_owner(self) -> None:
        article, result = mn.import_manual_article(
            _good_candidate(), brief=self.brief, base=self.base
        )
        self.assertTrue(result.ok)
        self.assertIsNotNone(article)
        self.assertEqual(article["generationMode"], "MANUAL_IMPORT")
        self.assertEqual(article["schemaVersion"], mn.SCHEMA_VERSION)

        # Saved through save_article -> readable through load_article,
        # the SAME storage the provider-generated path and the frontend
        # both use.  No second owner, no second store.
        loaded = mn.load_article("2025", 16, 1, "recap", base=self.base)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["title"], article["title"])
        self.assertEqual(loaded["generationMode"], "MANUAL_IMPORT")

    def test_invalid_import_is_not_saved_without_force(self) -> None:
        bad = _good_candidate(week=99)
        article, result = mn.import_manual_article(bad, brief=self.brief, base=self.base)
        self.assertFalse(result.ok)
        self.assertIsNone(article)
        self.assertIsNone(mn.load_article("2025", 16, 1, "recap", base=self.base))

    def test_force_overrides_a_failing_validation(self) -> None:
        bad = _good_candidate(kicker="")
        article, result = mn.import_manual_article(
            bad, brief=self.brief, base=self.base, force=True
        )
        self.assertFalse(result.ok)
        self.assertIsNotNone(article)
        self.assertEqual(article["validation"]["ok"], False)
        self.assertIsNotNone(mn.load_article("2025", 16, 1, "recap", base=self.base))


if __name__ == "__main__":
    unittest.main()
