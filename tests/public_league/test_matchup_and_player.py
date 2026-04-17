"""Tests for matchup recap + player journey views."""
from __future__ import annotations

import copy
import unittest

from src.public_league import matchup_recap, player_journey

from tests.public_league.fixtures import build_test_snapshot


def _with_player_points(snapshot):
    """Copy + inject per-player scoring so the journey/recap logic has
    something to chew on."""
    snap = copy.deepcopy(snapshot)
    def _stamp(entry, pp, starters):
        entry["players_points"] = pp
        entry["starters"] = starters
    s2025 = snap.seasons[0]
    stamps = {
        1: {
            1: ({"p-qb1": 40.5, "p-rb1": 35.0, "p-wr1": 20.0, "p-te1": 15.0, "p-rookie-a": 10.0}, ["p-qb1","p-rb1","p-wr1","p-te1","p-rookie-a"]),
            2: ({"p-qb2": 50.0, "p-rb2": 30.0, "p-wr2": 25.0, "p-te1": 15.2, "p-rookie-b": 15.0}, ["p-qb2","p-rb2","p-wr2","p-te1","p-rookie-b"]),
        },
        2: {
            1: ({"p-qb1": 60.0, "p-rb1": 35.0, "p-wr1": 25.8, "p-te1": 15.0, "p-rookie-a": 10.0}, ["p-qb1","p-rb1","p-wr1","p-te1","p-rookie-a"]),
            3: ({"p-wr1": 25.0, "p-wr2": 25.0, "p-wr3": 30.0, "p-rb1": 32.1, "p-qb1": 30.0}, ["p-wr1","p-wr2","p-wr3","p-rb1","p-qb1"]),
        },
    }
    for wk, by_rid in stamps.items():
        for e in s2025.matchups_by_week.get(wk) or []:
            rid = int(e.get("roster_id"))
            if rid in by_rid:
                pp, st = by_rid[rid]
                _stamp(e, pp, st)
    return snap


class MatchupRecapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_unknown_season_returns_none(self) -> None:
        self.assertIsNone(matchup_recap.build_matchup_recap(self.snapshot, "1999", 1, 1))

    def test_unknown_matchup_returns_none(self) -> None:
        self.assertIsNone(matchup_recap.build_matchup_recap(self.snapshot, "2025", 1, 99))

    def test_recap_shape_week_1(self) -> None:
        recap = matchup_recap.build_matchup_recap(self.snapshot, "2025", 1, 1)
        self.assertIsNotNone(recap)
        self.assertEqual(recap["week"], 1)
        self.assertEqual(recap["matchupId"], 1)
        self.assertIsNotNone(recap["home"])
        self.assertIsNotNone(recap["away"])
        # Fixture: B beats A by 14.7 in week 1.
        self.assertEqual(recap["winnerOwnerId"], "owner-B")
        self.assertEqual(recap["margin"], 14.7)
        # Starters emitted with per-player points.
        self.assertTrue(any(s["points"] > 0 for s in recap["home"]["starters"]))
        self.assertTrue(recap["home"]["topScorer"])

    def test_narrative_mentions_top_scorer(self) -> None:
        recap = matchup_recap.build_matchup_recap(self.snapshot, "2025", 1, 1)
        self.assertIn("owner-B", recap["winnerOwnerId"])
        self.assertIn("Week 1", recap["narrative"])
        self.assertIn("Led by", recap["narrative"])

    def test_playoff_flag_set_for_week_15(self) -> None:
        recap = matchup_recap.build_matchup_recap(self.snapshot, "2025", 15, 1)
        self.assertIsNotNone(recap)
        self.assertTrue(recap["isPlayoff"])

    def test_list_matchups_enumerates_pairs(self) -> None:
        matchups = matchup_recap.list_matchups(self.snapshot)
        self.assertTrue(matchups)
        # Fixture has multiple weeks with 2 matchups each + 1 final.
        by_season = {}
        for m in matchups:
            by_season.setdefault(m["season"], 0)
            by_season[m["season"]] += 1
        self.assertIn("2025", by_season)
        self.assertIn("2024", by_season)


class PlayerJourneyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _with_player_points(build_test_snapshot())

    def test_unknown_player_returns_none(self) -> None:
        self.assertIsNone(player_journey.build_player_journey(self.snapshot, "does-not-exist"))

    def test_empty_player_id_returns_none(self) -> None:
        self.assertIsNone(player_journey.build_player_journey(self.snapshot, ""))

    def test_journey_shape_for_rostered_player(self) -> None:
        journey = player_journey.build_player_journey(self.snapshot, "p-rb2")
        self.assertIsNotNone(journey)
        self.assertEqual(journey["identity"]["playerId"], "p-rb2")
        self.assertEqual(journey["identity"]["position"], "RB")
        self.assertIn("totalsByOwner", journey)
        self.assertIn("ownershipArc", journey)
        # p-rb2 was on roster 2 in 2024, then traded to roster 1 (owner-A) in 2025.
        arc_owners = [a["ownerId"] for a in journey["ownershipArc"]]
        self.assertIn("owner-B", arc_owners)

    def test_journey_captures_trade_event(self) -> None:
        journey = player_journey.build_player_journey(self.snapshot, "p-rb2")
        self.assertIsNotNone(journey)
        kinds = {e["kind"] for e in journey.get("events", [])}
        self.assertIn("add", kinds)
        self.assertIn("drop", kinds)

    def test_list_players_with_activity_is_nonempty(self) -> None:
        players = player_journey.list_players_with_activity(self.snapshot)
        self.assertTrue(players)
        ids = {p["playerId"] for p in players}
        # Fixture trade moves p-rb2, p-wr2, p-wr3 — all should surface.
        for pid in ("p-rb2", "p-wr2", "p-wr3"):
            self.assertIn(pid, ids)


try:
    from fastapi.testclient import TestClient
    _HAVE_TC = True
except Exception:  # noqa: BLE001
    _HAVE_TC = False


@unittest.skipUnless(_HAVE_TC, "fastapi TestClient not installed")
class MatchupAndPlayerRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import os
        from tests.public_league.fixtures import install_stubs, build_stub_client

        install_stubs(build_stub_client())
        os.environ["SLEEPER_LEAGUE_ID"] = "L2025"
        from server import app, _public_league_cache
        _public_league_cache.clear()
        _public_league_cache.update({
            "snapshot": None,
            "snapshot_league_id": None,
            "fetched_at": 0.0,
        })
        cls.client = TestClient(app)

    def test_matchup_route_returns_payload(self) -> None:
        r = self.client.get("/api/public/league/matchup/2025/1/1")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["matchup"]["week"], 1)
        self.assertIn("home", body["matchup"])
        self.assertIn("managers", body["league"])

    def test_matchup_unknown_returns_404(self) -> None:
        r = self.client.get("/api/public/league/matchup/2025/1/99")
        self.assertEqual(r.status_code, 404)

    def test_matchups_index_route(self) -> None:
        r = self.client.get("/api/public/league/matchups")
        self.assertEqual(r.status_code, 200)
        self.assertIn("matchups", r.json())

    def test_player_route_returns_journey(self) -> None:
        r = self.client.get("/api/public/league/player/p-rb2")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["player"]["identity"]["playerId"], "p-rb2")

    def test_player_unknown_returns_404(self) -> None:
        r = self.client.get("/api/public/league/player/not-a-real-player")
        self.assertEqual(r.status_code, 404)

    def test_players_index_route(self) -> None:
        r = self.client.get("/api/public/league/players")
        self.assertEqual(r.status_code, 200)
        self.assertGreater(len(r.json()["players"]), 0)

    def test_matchup_payload_never_leaks_private_fields(self) -> None:
        r = self.client.get("/api/public/league/matchup/2025/1/1")
        blob = r.text.lower()
        for banned in ("ourvalue", "edgesignals", "edgescore", "tradefinder", "siteweights"):
            self.assertNotIn(banned, blob)

    def test_player_payload_never_leaks_private_fields(self) -> None:
        r = self.client.get("/api/public/league/player/p-rb2")
        blob = r.text.lower()
        for banned in ("ourvalue", "edgesignals", "edgescore", "tradefinder", "siteweights"):
            self.assertNotIn(banned, blob)


if __name__ == "__main__":
    unittest.main()
