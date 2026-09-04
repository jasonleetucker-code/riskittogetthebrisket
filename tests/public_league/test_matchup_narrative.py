"""Tests for ``src/public_league/matchup_narrative.py``.

Covers everything *up to* the Claude API call. The actual ``messages.create``
call is exercised separately via a tiny fake client because we don't want
to pay Anthropic per CI run.

Coverage map:
    * Brief assembly for recap mode (uses fixture's wk-16 championship).
    * Brief assembly for preview mode (zero-out points on wk-16).
    * Bracket-round classification correctly tags championship games.
    * Multi-week round detection — synthesize a 2-week championship.
    * Angle pool filtering (data-supported angles only).
    * Persona is deterministic per (season, week, matchup).
    * Storage round-trip (save → load → list).
    * Prompt assembly produces non-empty system + user blocks and the
      brief JSON is embedded verbatim.
    * generate_article happy-path with a fake AsyncAnthropic client.
    * generate_article error path on malformed JSON.
"""

from __future__ import annotations

import copy

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path

from src.public_league import matchup_narrative as mn
from tests.public_league.fixtures import build_test_snapshot


class StorageRoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["LEAGUE_NARRATIVES_DIR"] = self.tmp.name
        self.base = Path(self.tmp.name)

    def tearDown(self) -> None:
        os.environ.pop("LEAGUE_NARRATIVES_DIR", None)
        self.tmp.cleanup()

    def test_article_path_layout(self) -> None:
        p = mn.article_path("2025", 17, 1, "preview", base=self.base)
        self.assertEqual(p, self.base / "2025" / "week-17" / "preview-1.json")

    def test_save_and_load_round_trip(self) -> None:
        article = {
            "mode": "preview",
            "season": "2025",
            "week": 17,
            "matchupId": 1,
            "title": "Test article",
            "lede": "A short lede",
            "body": "Body paragraph.",
            "kicker": "kicker",
            "angleUsed": "championship-stakes",
            "persona": "analyst",
            "wordCount": 100,
            "model": "claude-opus-4-7",
            "generatedAt": "2026-01-01T00:00:00+00:00",
            "isChampionship": True,
            "roundLabel": "Championship",
            "home": {"ownerId": "owner-A", "displayName": "AAron", "teamName": "Brisket Bandits"},
            "away": {"ownerId": "owner-B", "displayName": "Bea", "teamName": "Bea's Beast Mode"},
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        path = mn.save_article(article, base=self.base)
        self.assertTrue(path.exists())

        loaded = mn.load_article("2025", 17, 1, "preview", base=self.base)
        self.assertEqual(loaded["title"], "Test article")
        self.assertEqual(loaded["isChampionship"], True)

    def test_load_missing_returns_none(self) -> None:
        self.assertIsNone(mn.load_article("2025", 17, 99, "preview", base=self.base))

    def test_save_rejects_bad_mode(self) -> None:
        with self.assertRaises(ValueError):
            mn.save_article(
                {"mode": "garbage", "season": "2025", "week": 1, "matchupId": 1}, base=self.base
            )

    def test_list_articles_orders_by_path(self) -> None:
        for week, mid, mode in [(15, 1, "recap"), (16, 1, "preview"), (16, 2, "preview")]:
            mn.save_article(
                {
                    "mode": mode,
                    "season": "2025",
                    "week": week,
                    "matchupId": mid,
                    "title": f"{week}-{mid}-{mode}",
                    "lede": "",
                    "body": "",
                    "kicker": "",
                    "angleUsed": "",
                    "persona": "",
                    "wordCount": 0,
                    "model": "",
                    "generatedAt": "",
                    "isChampionship": False,
                    "roundLabel": "",
                    "home": {},
                    "away": {},
                    "usage": {},
                },
                base=self.base,
            )
        items = mn.list_articles(season="2025", base=self.base)
        self.assertEqual(len(items), 3)
        keys = [(i["week"], i["matchupId"], i["mode"]) for i in items]
        self.assertEqual(sorted(keys), keys)


class BriefAssemblyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = build_test_snapshot()

    def test_recap_brief_for_fixture_championship(self) -> None:
        # Fixture's 2025 wk-16 is the championship: B (145.0) vs A (120.0).
        brief = mn.build_brief(
            self.snapshot,
            season="2025",
            week=16,
            matchup_id=1,
            mode="recap",
        )
        self.assertIsNotNone(brief)
        self.assertEqual(brief.mode, "recap")
        self.assertEqual(brief.season, "2025")
        self.assertEqual(brief.week, 16)
        self.assertTrue(brief.is_playoff)
        self.assertTrue(brief.is_championship)
        self.assertEqual(brief.round_label, "Championship")
        # Sorted by roster_id → home is roster 1 (owner-A), away is roster 2 (owner-B).
        self.assertEqual(brief.home["rosterId"], 1)
        self.assertEqual(brief.away["rosterId"], 2)
        self.assertEqual(brief.home["points"], 120.0)
        self.assertEqual(brief.away["points"], 145.0)
        # Fixture matchup entries don't carry starter lists, so the
        # lineup arrays are empty here. The brief still shapes correctly
        # — production data always has starters because Sleeper writes
        # them on lock; an empty lineup is just defensive against
        # weird/incomplete entries.
        self.assertIsInstance(brief.home["starters"], list)
        self.assertIsInstance(brief.away["starters"], list)

    def test_preview_brief_zero_points(self) -> None:
        snap = build_test_snapshot()
        current = snap.seasons[0]
        current.matchups_by_week[17] = [
            {
                "matchup_id": 1,
                "roster_id": 1,
                "points": 0,
                "starters": ["p-qb1", "p-rb1"],
                "players": ["p-qb1", "p-rb1"],
                "players_points": {"p-qb1": 0, "p-rb1": 0},
            },
            {
                "matchup_id": 1,
                "roster_id": 2,
                "points": 0,
                "starters": ["p-qb2", "p-rb2"],
                "players": ["p-qb2", "p-rb2"],
                "players_points": {"p-qb2": 0, "p-rb2": 0},
            },
        ]
        brief = mn.build_brief(
            snap,
            season="2025",
            week=17,
            matchup_id=1,
            mode="preview",
        )
        self.assertIsNotNone(brief)
        self.assertEqual(brief.mode, "preview")
        # Preview points are None — model shouldn't see fake "0.0" scoring.
        for row in brief.home["starters"]:
            self.assertIsNone(row["points"])

    def test_brief_is_none_for_missing_matchup(self) -> None:
        self.assertIsNone(
            mn.build_brief(
                self.snapshot,
                season="2025",
                week=99,
                matchup_id=1,
                mode="recap",
            )
        )
        self.assertIsNone(
            mn.build_brief(
                self.snapshot,
                season="2025",
                week=16,
                matchup_id=99,
                mode="recap",
            )
        )

    def test_to_dict_is_json_serializable(self) -> None:
        brief = mn.build_brief(
            self.snapshot,
            season="2025",
            week=16,
            matchup_id=1,
            mode="recap",
        )
        # Round-trip through json so the schema survives serialization.
        s = json.dumps(brief.to_dict())
        loaded = json.loads(s)
        self.assertEqual(loaded["mode"], "recap")
        self.assertIn("home", loaded)
        self.assertIn("anglePool", loaded)


class AnglePoolTests(unittest.TestCase):
    def test_first_meeting_added_when_no_h2h(self) -> None:
        pool = mn._angle_pool(
            is_championship=False,
            is_playoff=False,
            h2h_total=0,
            multi_week=None,
            cumulative_close=False,
            underdog_seed_gap=0,
        )
        self.assertIn("first-meeting", pool)
        self.assertNotIn("rivalry-grudge", pool)

    def test_rivalry_grudge_only_with_history(self) -> None:
        pool = mn._angle_pool(
            is_championship=False,
            is_playoff=False,
            h2h_total=10,
            multi_week=None,
            cumulative_close=False,
            underdog_seed_gap=0,
        )
        self.assertIn("rivalry-grudge", pool)
        self.assertNotIn("first-meeting", pool)

    def test_comeback_arc_only_with_lead(self) -> None:
        no_lead = mn._angle_pool(
            is_championship=True,
            is_playoff=True,
            h2h_total=2,
            multi_week={"priorLead": 5.0},
            cumulative_close=True,
            underdog_seed_gap=0,
        )
        self.assertNotIn("comeback-arc", no_lead)
        self.assertIn("razor-thin", no_lead)
        big_lead = mn._angle_pool(
            is_championship=True,
            is_playoff=True,
            h2h_total=2,
            multi_week={"priorLead": 25.0},
            cumulative_close=False,
            underdog_seed_gap=0,
        )
        self.assertIn("comeback-arc", big_lead)

    def test_championship_stakes_always_included(self) -> None:
        pool = mn._angle_pool(
            is_championship=True,
            is_playoff=True,
            h2h_total=0,
            multi_week=None,
            cumulative_close=False,
            underdog_seed_gap=0,
        )
        self.assertEqual(pool[0], "championship-stakes")

    def test_pool_is_deduplicated(self) -> None:
        pool = mn._angle_pool(
            is_championship=False,
            is_playoff=False,
            h2h_total=10,
            multi_week=None,
            cumulative_close=False,
            underdog_seed_gap=5,
        )
        self.assertEqual(len(pool), len(set(pool)))


class PersonaTests(unittest.TestCase):
    def test_persona_is_deterministic(self) -> None:
        a = mn._persona_for("2025", 17, 1)
        b = mn._persona_for("2025", 17, 1)
        self.assertEqual(a, b)
        self.assertIn(a, {"analyst", "storyteller", "sharp-take"})

    def test_persona_varies_across_matchups(self) -> None:
        # Different matchup_ids should hit at least 2 distinct personas.
        seen = {mn._persona_for("2025", 17, mid) for mid in range(20)}
        self.assertGreaterEqual(len(seen), 2)


class MultiWeekRoundTests(unittest.TestCase):
    def test_two_week_championship_cumulative(self) -> None:
        snap = build_test_snapshot()
        current = snap.seasons[0]
        # Mock a wk-16 + wk-17 championship between rosters 1 and 2.
        current.matchups_by_week[16] = [
            {
                "matchup_id": 1,
                "roster_id": 1,
                "points": 100.0,
                "starters": [],
                "players": [],
                "players_points": {},
            },
            {
                "matchup_id": 1,
                "roster_id": 2,
                "points": 120.0,
                "starters": [],
                "players": [],
                "players_points": {},
            },
        ]
        current.matchups_by_week[17] = [
            {
                "matchup_id": 1,
                "roster_id": 1,
                "points": 130.0,
                "starters": ["p-qb1"],
                "players": ["p-qb1"],
                "players_points": {"p-qb1": 30.0},
            },
            {
                "matchup_id": 1,
                "roster_id": 2,
                "points": 90.0,
                "starters": ["p-qb2"],
                "players": ["p-qb2"],
                "players_points": {"p-qb2": 20.0},
            },
        ]
        current.winners_bracket = [
            {"r": 2, "t1": 1, "t2": 2, "w": 1, "l": 2, "p": 1},
        ]
        brief = mn.build_brief(
            snap,
            season="2025",
            week=17,
            matchup_id=1,
            mode="recap",
        )
        self.assertIsNotNone(brief)
        self.assertIsNotNone(brief.multi_week_round)
        mw = brief.multi_week_round
        self.assertEqual(mw["weeksInRound"], 2)
        self.assertEqual(len(mw["priorWeeks"]), 1)
        self.assertEqual(mw["priorWeeks"][0]["week"], 16)
        # Brief sorts home/away by roster_id → home = rid 1, away = rid 2.
        # Prior totals (week 16 only): home=100, away=120 → away leads.
        self.assertEqual(mw["priorTotalHome"], 100.0)
        self.assertEqual(mw["priorTotalAway"], 120.0)
        self.assertEqual(mw["priorLead"], 20.0)
        self.assertEqual(mw["priorLeader"], "away")
        # Recap mode → currentTotal* layered on. Roster 1 = 100+130=230,
        # roster 2 = 120+90=210 → home wins by 20.
        self.assertEqual(mw["currentTotalHome"], 230.0)
        self.assertEqual(mw["currentTotalAway"], 210.0)
        self.assertEqual(mw["currentLeader"], "home")
        self.assertEqual(mw["currentMargin"], 20.0)

    def test_no_multi_week_for_single_week_round(self) -> None:
        snap = build_test_snapshot()
        # Fixture wk-16 championship is single-week — no prior pairing.
        brief = mn.build_brief(
            snap,
            season="2025",
            week=16,
            matchup_id=1,
            mode="recap",
        )
        self.assertIsNotNone(brief)
        self.assertIsNone(brief.multi_week_round)


class PromptAssemblyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = build_test_snapshot()
        cls.brief = mn.build_brief(
            cls.snapshot,
            season="2025",
            week=16,
            matchup_id=1,
            mode="recap",
        )

    def test_prompt_returns_system_and_user_blocks(self) -> None:
        system, messages = mn.assemble_prompt(self.brief, prior_articles=[])
        self.assertEqual(len(system), 1)
        self.assertEqual(system[0]["type"], "text")
        self.assertIn("cache_control", system[0])
        self.assertEqual(messages[0]["role"], "user")
        # The brief is in the user message as JSON.
        self.assertIn("=== MATCHUP BRIEF ===", messages[0]["content"])
        self.assertIn(self.brief.persona, system[0]["text"])

    def test_prior_articles_are_referenced(self) -> None:
        prior = [
            {
                "season": "2025",
                "week": 14,
                "mode": "recap",
                "title": "Prior title",
                "lede": "Prior lede.",
                "generatedAt": "2025-01-01T00:00:00Z",
            },
        ]
        _, messages = mn.assemble_prompt(self.brief, prior_articles=prior)
        self.assertIn("Prior title", messages[0]["content"])
        self.assertIn("Prior lede", messages[0]["content"])
        self.assertIn("DO NOT reuse", messages[0]["content"])

    def test_no_prior_articles_handled(self) -> None:
        _, messages = mn.assemble_prompt(self.brief, prior_articles=None)
        self.assertIn("first one", messages[0]["content"])


class BestBallPromptTests(unittest.TestCase):
    """The format-blurb branch keeps the model from writing
    'so-and-so started so-and-so' in best-ball leagues. Pin both
    branches so a future refactor can't silently drop one."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = build_test_snapshot()

    def _brief(self, *, best_ball: bool):
        brief = mn.build_brief(
            self.snapshot,
            season="2025",
            week=16,
            matchup_id=1,
            mode="recap",
        )
        # build_brief reads best_ball off the Sleeper league settings;
        # the fixture doesn't set it, so we override on the dataclass
        # for this targeted test.
        brief.best_ball = best_ball
        return brief

    def test_best_ball_blurb_warns_against_lineup_framing(self) -> None:
        brief = self._brief(best_ball=True)
        system_blocks, _ = mn.assemble_prompt(brief, prior_articles=[])
        text = system_blocks[0]["text"]
        self.assertIn("BEST-BALL", text)
        self.assertIn("DO NOT", text)
        self.assertIn("started", text)  # "do not write that any manager started..."
        self.assertIn("benched", text)
        self.assertIn("ROSTER CONSTRUCTION", text)

    def test_managed_lineup_blurb_allows_start_sit(self) -> None:
        brief = self._brief(best_ball=False)
        system_blocks, _ = mn.assemble_prompt(brief, prior_articles=[])
        text = system_blocks[0]["text"]
        self.assertIn("managed-lineup", text)
        self.assertIn("Lineup decisions", text)
        # Don't accidentally include the best-ball ban in the
        # managed-lineup branch.
        self.assertNotIn("BEST-BALL", text)

    def test_best_ball_brief_skips_bench_misses(self) -> None:
        # Synthesize a best-ball-shaped fixture: starters + a higher-
        # scoring "bench" player. In a managed brief that surfaces as
        # biggestBenchMiss; in best-ball it should be suppressed so the
        # model isn't tempted to write "left points on the bench."
        snap = build_test_snapshot()
        current = snap.seasons[0]
        current.league = {**(current.league or {}), "settings": {"best_ball": 1}}
        current.matchups_by_week[17] = [
            {
                "matchup_id": 1,
                "roster_id": 1,
                "points": 100.0,
                "starters": ["p-qb1"],
                "players": ["p-qb1", "p-rb2"],
                "players_points": {"p-qb1": 30.0, "p-rb2": 50.0},
            },
            {
                "matchup_id": 1,
                "roster_id": 2,
                "points": 80.0,
                "starters": ["p-qb2"],
                "players": ["p-qb2"],
                "players_points": {"p-qb2": 25.0},
            },
        ]
        brief = mn.build_brief(
            snap,
            season="2025",
            week=17,
            matchup_id=1,
            mode="recap",
        )
        self.assertIsNotNone(brief)
        self.assertTrue(brief.best_ball)
        self.assertIsNone(brief.home["biggestBenchMiss"])
        self.assertEqual(brief.home["topBench"], [])


# ── Fake Anthropic client for generate_article happy-path ──────────────


class _FakeUsage:
    def __init__(
        self,
        *,
        input_tokens: int = 100,
        output_tokens: int = 200,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read_input_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens


class _FakeBlock:
    def __init__(self, type_: str, text: str = "") -> None:
        self.type = type_
        self.text = text


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.content = [_FakeBlock("thinking", ""), _FakeBlock("text", text)]
        self.usage = _FakeUsage()


class _FakeMessages:
    def __init__(self, response_text: str) -> None:
        self._response_text = response_text

    async def create(self, **kwargs):  # noqa: ANN003 — kwargs are SDK-shaped
        return _FakeResponse(self._response_text)


class _FakeClient:
    def __init__(self, response_text: str) -> None:
        self.messages = _FakeMessages(response_text)


class GenerateArticleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = build_test_snapshot()
        cls.brief = mn.build_brief(
            cls.snapshot,
            season="2025",
            week=16,
            matchup_id=1,
            mode="recap",
        )

    def test_happy_path_returns_persisted_shape(self) -> None:
        fake_text = json.dumps(
            {
                "title": "Title",
                "lede": "Lede.",
                "body": "Body.",
                "kicker": "Kicker.",
                "angleUsed": "championship-stakes",
                "wordCount": 200,
            }
        )
        client = _FakeClient(fake_text)
        article = asyncio.run(
            mn.generate_article(client=client, brief=self.brief, prior_articles=[])
        )
        self.assertEqual(article["title"], "Title")
        self.assertEqual(article["body"], "Body.")
        self.assertEqual(article["mode"], "recap")
        self.assertEqual(article["season"], "2025")
        self.assertEqual(article["week"], 16)
        self.assertEqual(article["matchupId"], 1)
        self.assertEqual(article["model"], "claude-opus-4-7")
        self.assertIn("usage", article)
        self.assertEqual(article["usage"]["input_tokens"], 100)
        self.assertIn("home", article)
        self.assertIn("away", article)

    def test_handles_fenced_json(self) -> None:
        fake_text = (
            "```json\n"
            + json.dumps(
                {
                    "title": "T",
                    "lede": "L",
                    "body": "B",
                    "kicker": "K",
                    "angleUsed": "vibes-check",
                    "wordCount": 50,
                }
            )
            + "\n```"
        )
        client = _FakeClient(fake_text)
        article = asyncio.run(
            mn.generate_article(client=client, brief=self.brief, prior_articles=[])
        )
        self.assertEqual(article["title"], "T")

    def test_malformed_json_raises(self) -> None:
        client = _FakeClient("not valid json at all")
        with self.assertRaises(RuntimeError):
            asyncio.run(mn.generate_article(client=client, brief=self.brief, prior_articles=[]))


if __name__ == "__main__":
    unittest.main()


class PriorSeasonFormDirectiveTests(unittest.TestCase):
    """Week 1 hands the model a ``record``/``avgPoints`` pair describing
    LAST season. The per-game ``season`` fields were always in the brief,
    but nothing instructed the model to use them — so the natural
    phrasing ("averaging 118 a week") silently asserts current-season
    form that does not exist yet."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = build_test_snapshot()
        cls.brief = mn.build_brief(cls.snapshot, season="2025", week=16, matchup_id=1, mode="recap")

    def _brief_with_prior_form(self, home: bool = True, away: bool = False):
        brief = copy.deepcopy(self.brief)
        brief.home.setdefault("recentForm", {})["isPriorSeasonOnly"] = home
        brief.away.setdefault("recentForm", {})["isPriorSeasonOnly"] = away
        return brief

    def test_directive_absent_when_form_is_current_season(self) -> None:
        _, messages = mn.assemble_prompt(
            self._brief_with_prior_form(home=False, away=False), prior_articles=[]
        )
        self.assertNotIn("RECENT FORM IS FROM A PREVIOUS SEASON", messages[0]["content"])

    def test_directive_present_and_names_the_affected_side(self) -> None:
        _, messages = mn.assemble_prompt(
            self._brief_with_prior_form(home=True, away=False), prior_articles=[]
        )
        content = messages[0]["content"]
        self.assertIn("RECENT FORM IS FROM A PREVIOUS SEASON", content)
        self.assertIn("the home team", content)
        self.assertNotIn("the away team", content)

    def test_directive_names_both_sides_in_week_one(self) -> None:
        """The real Week 1 shape: neither side has current-season form."""
        _, messages = mn.assemble_prompt(
            self._brief_with_prior_form(home=True, away=True), prior_articles=[]
        )
        content = messages[0]["content"]
        self.assertIn("the home team and the away team", content)

    def test_directive_rides_the_user_message_not_the_cached_system_block(self) -> None:
        """Whether the window is prior-season depends on the week being
        written, so caching it would apply Week 1's instruction to Week 5."""
        system, messages = mn.assemble_prompt(
            self._brief_with_prior_form(home=True, away=True), prior_articles=[]
        )
        self.assertNotIn("RECENT FORM IS FROM A PREVIOUS SEASON", system[0]["text"])
        self.assertIn("RECENT FORM IS FROM A PREVIOUS SEASON", messages[0]["content"])

    def test_brief_still_carries_the_per_game_seasons(self) -> None:
        """The directive tells the model to read a field; that field must
        actually be there."""
        for side in (self.brief.home, self.brief.away):
            games = (side.get("recentForm") or {}).get("games") or []
            for g in games:
                self.assertIn("season", g)
