"""Truthfulness and roster-join tests for the League Conduct Board."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from src.public_league import build_public_snapshot
from src.public_league.conduct import build_section
from src.public_league.snapshot import PublicLeagueSnapshot
from tests.public_league.fixtures import build_stub_client, install_stubs


_COMMITTED_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "public_league" / "conduct_registry.json"
)


def _incident(
    incident_id: str,
    *,
    category: str = "domesticViolence",
    status: str = "allegedNoCharge",
    bases: list[str] | None = None,
    sources: list[dict[str, str]] | None = None,
) -> dict:
    chosen_bases = bases or ["credibleAllegation"]
    row = {
        "incidentId": incident_id,
        "date": "2025-01-02",
        "dateLabel": "January 2, 2025",
        "lastVerified": "2026-08-23",
        "category": category,
        "summary": f"Documented summary for {incident_id}.",
        "status": status,
        "statusLabel": f"Status for {incident_id}",
        "disposition": f"Disposition for {incident_id}.",
        "qualifyingBasis": chosen_bases,
        "sources": (
            [{"label": "Reliable report", "url": "https://example.com/report"}]
            if sources is None
            else sources
        ),
    }
    if "violenceRelatedDiscipline" in chosen_bases:
        row["discipline"] = {
            "organization": "NFL",
            "description": "Three-game personal-conduct suspension",
            "date": "2025-02-01",
        }
    return row


def _player(player_id: str, name: str, incidents: list[dict]) -> dict:
    return {
        "sleeperPlayerId": player_id,
        "playerName": name,
        "incidents": incidents,
    }


def _registry(players: list[dict]) -> dict:
    return {
        "schemaVersion": 1,
        "lastReviewed": "2026-08-23",
        "players": players,
    }


def _team(data: dict, owner_id: str) -> dict:
    return next(team for team in data["teams"] if team["ownerId"] == owner_id)


class ConductSectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_stubs(build_stub_client())
        cls.snapshot = build_public_snapshot("L2025", max_seasons=2)

    def test_main_tally_is_unique_players_while_incidents_stay_separate(self) -> None:
        registry = _registry(
            [
                _player(
                    "p-rookie-a",
                    "Rudy Rook",
                    [
                        _incident("rudy-allegation"),
                        _incident(
                            "rudy-plea",
                            status="pleaded",
                            bases=[
                                "formalLegalAction",
                                "convictionOrPlea",
                                "violenceRelatedDiscipline",
                            ],
                        ),
                    ],
                ),
                _player(
                    "p-idp1",
                    "Kim DL-One",
                    [
                        _incident(
                            "kim-charge",
                            status="chargedPending",
                            bases=["credibleAllegation", "formalLegalAction"],
                        )
                    ],
                ),
            ]
        )

        data = build_section(self.snapshot, registry=registry)

        self.assertTrue(data["available"])
        self.assertEqual(data["totals"]["flaggedPlayers"], 2)
        self.assertEqual(data["totals"]["incidents"], 3)
        self.assertEqual(data["totals"]["breakdown"]["credibleAllegation"], 2)
        self.assertEqual(data["totals"]["breakdown"]["formalLegalAction"], 2)
        self.assertEqual(data["totals"]["breakdown"]["convictionOrPlea"], 1)
        self.assertEqual(data["totals"]["breakdown"]["violenceRelatedDiscipline"], 1)

        owner_a = _team(data, "owner-A")
        self.assertEqual(owner_a["flaggedPlayerCount"], 1)
        self.assertEqual(owner_a["incidentCount"], 2)
        self.assertEqual(owner_a["players"][0]["playerName"], "Rudy Rook")

    def test_score_formula_weights_outcome_discipline_and_repeat_incidents(self) -> None:
        registry = _registry(
            [
                _player(
                    "p-rookie-a",
                    "Rudy Rook",
                    [_incident("allegation")],
                ),
                _player(
                    "p-rb3",
                    "Eve RB-Three",
                    [
                        _incident(
                            "plea",
                            status="pleaded",
                            bases=["formalLegalAction", "convictionOrPlea"],
                        )
                    ],
                ),
                _player(
                    "p-wr3",
                    "Hal WR-Three",
                    [
                        _incident(
                            "league-finding",
                            category="weapons",
                            status="leagueFinding",
                            bases=["violenceRelatedDiscipline"],
                        )
                    ],
                ),
                _player(
                    "p-idp1",
                    "Kim DL-One",
                    [
                        _incident("repeat-one", category="seriousCrime"),
                        _incident("repeat-two", category="seriousCrime"),
                    ],
                ),
            ]
        )

        data = build_section(self.snapshot, registry=registry)

        owner_a = _team(data, "owner-A")
        owner_b = _team(data, "owner-B")
        owner_c = _team(data, "owner-C")
        owner_d = _team(data, "owner-D")

        # Same category, but an allegation receives 20% of the severity
        # points while a documented plea receives 100%.
        self.assertEqual(owner_a["score"], 10.0)
        self.assertEqual(owner_b["score"], 50.0)
        # 40 severity × .85 league finding + 10 discipline points.
        self.assertEqual(owner_c["score"], 44.0)
        # Two 30 × .20 incidents plus a 10 × .20 outcome-scaled repeat bonus.
        self.assertEqual(owner_d["score"], 14.0)
        repeat_player = owner_d["players"][0]
        self.assertEqual(repeat_player["incidentPoints"], 12.0)
        self.assertEqual(repeat_player["repeatIncidentBonus"], 2.0)
        self.assertTrue(repeat_player["isRepeatIncidentPlayer"])

        self.assertEqual(
            [team["ownerId"] for team in data["teams"]],
            ["owner-B", "owner-C", "owner-D", "owner-A"],
        )
        self.assertEqual([team["rank"] for team in data["teams"]], [1, 2, 3, 4])
        self.assertEqual(data["totals"]["score"], 118.0)
        self.assertEqual(data["scoring"]["disciplineBonus"], 10.0)
        self.assertEqual(data["scoring"]["repeatIncidentBonus"], 10.0)

    def test_acquittal_scores_zero_and_equal_scores_share_a_rank(self) -> None:
        registry = _registry(
            [
                _player(
                    "p-rookie-a",
                    "Rudy Rook",
                    [
                        _incident(
                            "acquitted",
                            status="acquitted",
                            bases=["credibleAllegation", "formalLegalAction"],
                        )
                    ],
                )
            ]
        )

        data = build_section(self.snapshot, registry=registry)

        self.assertEqual(_team(data, "owner-A")["score"], 0.0)
        self.assertEqual(
            _team(data, "owner-A")["players"][0]["incidents"][0]["score"],
            0.0,
        )
        self.assertEqual({team["rank"] for team in data["teams"]}, {1})

    def test_reserve_and_taxi_slots_count_but_draft_picks_do_not(self) -> None:
        snapshot = copy.deepcopy(self.snapshot)
        roster = snapshot.current_season.rosters[0]
        roster["reserve"] = ["p-reserve-only"]
        roster["taxi"] = ["p-taxi-only"]
        roster["starters"] = ["p-reserve-only"]  # duplicate slot is still one player
        roster["draft_picks"] = ["p-pick-only"]
        snapshot.nfl_players.update(
            {
                "p-reserve-only": {
                    "full_name": "Reserve Only",
                    "position": "WR",
                    "team": "MIN",
                },
                "p-taxi-only": {
                    "full_name": "Taxi Only",
                    "position": "RB",
                    "team": "DET",
                },
                "p-pick-only": {
                    "full_name": "Pick Only",
                    "position": "QB",
                    "team": "CHI",
                },
            }
        )
        registry = _registry(
            [
                _player("p-reserve-only", "Reserve Only", [_incident("reserve")]),
                _player("p-taxi-only", "Taxi Only", [_incident("taxi")]),
                _player("p-pick-only", "Pick Only", [_incident("pick")]),
            ]
        )

        data = build_section(snapshot, registry=registry)
        owner_a = _team(data, "owner-A")

        self.assertEqual(owner_a["flaggedPlayerCount"], 2)
        self.assertEqual(
            {player["playerId"] for player in owner_a["players"]},
            {"p-reserve-only", "p-taxi-only"},
        )
        self.assertNotIn("p-pick-only", {p["playerId"] for p in owner_a["players"]})
        self.assertEqual(data["dataQuality"]["unrosteredRegistryPlayerCount"], 1)

    def test_roster_move_moves_flag_without_changing_registry(self) -> None:
        registry = _registry([_player("p-rookie-a", "Rudy Rook", [_incident("rudy")])])
        before = build_section(self.snapshot, registry=registry)
        self.assertEqual(_team(before, "owner-A")["flaggedPlayerCount"], 1)
        self.assertEqual(_team(before, "owner-D")["flaggedPlayerCount"], 0)

        moved = copy.deepcopy(self.snapshot)
        moved.current_season.rosters[0]["players"].remove("p-rookie-a")
        moved.current_season.rosters[3]["players"].append("p-rookie-a")
        after = build_section(moved, registry=registry)

        self.assertEqual(_team(after, "owner-A")["flaggedPlayerCount"], 0)
        self.assertEqual(_team(after, "owner-D")["flaggedPlayerCount"], 1)
        self.assertEqual(after["totals"]["flaggedPlayers"], 1)

    def test_unsourced_or_malformed_incidents_are_withheld(self) -> None:
        registry = _registry(
            [
                _player(
                    "p-rookie-a",
                    "Rudy Rook",
                    [
                        _incident("valid"),
                        _incident("unsourced", sources=[]),
                    ],
                ),
                _player(
                    "p-idp1",
                    "Kim DL-One",
                    [_incident("only-unsourced", sources=[])],
                ),
            ]
        )

        data = build_section(self.snapshot, registry=registry)

        self.assertEqual(data["totals"]["flaggedPlayers"], 1)
        self.assertEqual(data["totals"]["incidents"], 1)
        self.assertEqual(data["dataQuality"]["rejectedIncidentCount"], 2)
        self.assertEqual(data["dataQuality"]["rejectedPlayerCount"], 1)
        self.assertEqual(
            _team(data, "owner-A")["players"][0]["incidents"][0]["incidentId"],
            "valid",
        )

    def test_legal_statuses_and_dispositions_are_not_collapsed(self) -> None:
        alleged = _incident("alleged", status="allegedNoCharge")
        alleged["disposition"] = "No criminal charge was reported."
        acquitted = _incident(
            "acquitted",
            status="acquitted",
            bases=["credibleAllegation", "formalLegalAction"],
        )
        acquitted["disposition"] = "A jury returned a not-guilty verdict."
        registry = _registry([_player("p-rookie-a", "Rudy Rook", [alleged, acquitted])])

        data = build_section(self.snapshot, registry=registry)
        incidents = _team(data, "owner-A")["players"][0]["incidents"]
        by_status = {incident["status"]: incident for incident in incidents}

        self.assertEqual(
            by_status["allegedNoCharge"]["disposition"], "No criminal charge was reported."
        )
        self.assertEqual(
            by_status["acquitted"]["disposition"], "A jury returned a not-guilty verdict."
        )
        self.assertNotEqual(
            by_status["allegedNoCharge"]["statusLabel"],
            by_status["acquitted"]["statusLabel"],
        )

    def test_all_teams_are_returned_including_zero_match_teams(self) -> None:
        data = build_section(
            self.snapshot,
            registry=_registry([_player("p-rookie-a", "Rudy Rook", [_incident("rudy")])]),
        )

        self.assertEqual(len(data["teams"]), len(self.snapshot.current_season.rosters))
        self.assertEqual(_team(data, "owner-C")["flaggedPlayerCount"], 0)
        self.assertEqual(_team(data, "owner-C")["players"], [])

    def test_committed_registry_is_fully_source_gated_and_publishable(self) -> None:
        data = build_section(self.snapshot)

        self.assertTrue(data["available"])
        self.assertGreater(data["dataQuality"]["acceptedPlayerCount"], 0)
        self.assertGreater(data["dataQuality"]["acceptedIncidentCount"], 0)
        self.assertEqual(data["dataQuality"]["rejectedPlayerCount"], 0)
        self.assertEqual(data["dataQuality"]["rejectedIncidentCount"], 0)

    def test_committed_registry_contains_all_screenshot_requested_players(self) -> None:
        registry = json.loads(_COMMITTED_REGISTRY_PATH.read_text(encoding="utf-8"))
        registry_players = {
            player["sleeperPlayerId"]: player["playerName"] for player in registry["players"]
        }
        expected_players = {
            "138": "Ben Roethlisberger",
            "1264": "Justin Tucker",
            "4017": "Deshaun Watson",
            "4098": "Kareem Hunt",
            "5850": "Josh Jacobs",
            "6789": "Henry Ruggs",
            "7571": "Rashod Bateman",
            "9493": "Puka Nacua",
            "10229": "Rashee Rice",
            "12512": "Quinshon Judkins",
        }

        self.assertEqual(
            {player_id: registry_players.get(player_id) for player_id in expected_players},
            expected_players,
        )

    def test_no_current_season_is_unavailable_not_a_confident_zero(self) -> None:
        snapshot = PublicLeagueSnapshot(
            root_league_id="missing",
            generated_at="2026-08-23T12:00:00Z",
        )
        data = build_section(snapshot, registry=_registry([]))

        self.assertFalse(data["available"])
        self.assertEqual(data["unavailableReason"], "noCurrentSeason")
        self.assertEqual(data["teams"], [])

    def test_invalid_registry_withholds_the_entire_board(self) -> None:
        data = build_section(
            self.snapshot,
            registry={"schemaVersion": 999, "lastReviewed": "today", "players": []},
        )

        self.assertFalse(data["available"])
        self.assertEqual(data["unavailableReason"], "registryInvalid")
        self.assertEqual(data["totals"]["flaggedPlayers"], 0)
        self.assertEqual(data["teams"], [])


if __name__ == "__main__":
    unittest.main()
