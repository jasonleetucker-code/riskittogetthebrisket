"""Perfect Draft roster context — the payload and the route.

Two properties dominate this file:

* **Open roster spots are real and per-team.**  Measured on the live league,
  five of twelve teams sit at exactly the 58-man cap while another has 14
  spots free.  A rookie added into a free spot displaces nobody, so treating
  every addition as a cut would overstate the cost badly for some teams and
  not at all for others.

* **Nothing leaks between teams.**  Every number in this payload is specific
  to one roster.  The cache key carries team identity for exactly that
  reason, and an unresolvable team is an error rather than a silent fallback
  to whichever team sorted first — that would be the worst possible failure
  mode for a tool whose entire output is roster-specific.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest
from fastapi.testclient import TestClient

import server
from src.api import draft_optimizer_api, feature_flags, league_registry
from src.draft.context import build_roster_context, list_draft_teams


def _row(pid, name, pos, value):
    return {
        "playerId": pid,
        "canonicalName": name,
        "displayName": name,
        "legacyRef": name,
        "position": pos,
        "rankDerivedValue": value,
        "assetClass": "offense",
    }


def _contract(league_key="pd_main", roster_a=None, roster_b=None):
    roster_a = roster_a or ["Star QB", "Star WR", "Bench WR"]
    roster_b = roster_b or ["Other QB"]
    return {
        "meta": {"leagueKey": league_key},
        "generatedAt": "2026-07-30T00:00:00Z",
        "playersArray": [
            _row("qb1", "Star QB", "QB", 8000),
            _row("wr1", "Star WR", "WR", 7000),
            _row("wr2", "Bench WR", "WR", 1500),
            _row("qb2", "Other QB", "QB", 6000),
            _row("fa1", "Free WR", "WR", 1200),
            _row("fa2", "Free QB", "QB", 3000),
            _row("x1", "Unranked Body", "WR", None),
        ],
        "sleeper": {
            "teams": [
                {
                    "name": "Alpha",
                    "ownerId": "owner-a",
                    "roster_id": 1,
                    "players": list(roster_a),
                    "playerIds": [],
                },
                {
                    "name": "Beta",
                    "ownerId": "owner-b",
                    "roster_id": 2,
                    "players": list(roster_b),
                    "playerIds": [],
                },
            ]
        },
    }


@pytest.fixture(autouse=True)
def _registry(tmp_path, monkeypatch):
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "defaultLeagueKey": "pd_main",
                "leagues": [
                    {
                        "key": "pd_main",
                        "displayName": "PD Main",
                        "sleeperLeagueId": "L-PD-MAIN",
                        "scoringProfile": "prof_a",
                        "active": True,
                        "rosterSettings": {
                            "teamCount": 2,
                            "rosterSize": 5,
                            "taxiSize": 0,
                            "starters": {"QB": 1, "WR": 1},
                        },
                    },
                    {
                        "key": "pd_side",
                        "displayName": "PD Side",
                        "sleeperLeagueId": "L-PD-SIDE",
                        "scoringProfile": "prof_a",
                        "active": True,
                        "rosterSettings": {"teamCount": 2, "rosterSize": 5},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()
    draft_optimizer_api.reset_cache()
    yield
    league_registry.reload_registry()
    draft_optimizer_api.reset_cache()


class TestContextPayload:
    def test_open_spots_are_the_gap_between_roster_size_and_headcount(self):
        ctx = build_roster_context(_contract(), "pd_main", team_name="Alpha")
        assert ctx["rosterSize"] == 5
        assert ctx["rosterCount"] == 3
        assert ctx["openRosterSpots"] == 2

    def test_a_full_roster_has_no_open_spots(self):
        full = ["Star QB", "Star WR", "Bench WR", "Other QB", "Unranked Body"]
        ctx = build_roster_context(_contract(roster_a=full), "pd_main", team_name="Alpha")
        assert ctx["rosterCount"] == 5
        assert ctx["openRosterSpots"] == 0

    def test_waiver_levels_exclude_every_rostered_player_league_wide(self):
        ctx = build_roster_context(_contract(), "pd_main", team_name="Alpha")
        # Other QB is on Beta's roster, so the QB waiver level is Free QB.
        assert ctx["waiverValues"]["QB"] == 3000.0
        assert ctx["waiverValues"]["WR"] == 1200.0

    def test_the_cut_ladder_respects_the_starting_lineup(self):
        ctx = build_roster_context(_contract(), "pd_main", team_name="Alpha")
        cut_ids = [r["playerId"] for r in ctx["cutLadder"]["rungs"]]
        # QB1 fills the only QB slot; one WR must remain for the WR slot.
        assert "qb1" not in cut_ids
        assert "wr2" in cut_ids

    def test_a_roster_player_missing_from_the_board_is_kept_and_flagged(self):
        contract = _contract(roster_a=["Star QB", "Star WR", "Ghost Player"])
        ctx = build_roster_context(contract, "pd_main", team_name="Alpha")
        assert ctx["rosterCount"] == 3  # still occupies a spot
        assert ctx["counts"]["unmatchedRosterPlayers"] == 1
        assert "Ghost Player" in ctx["unmatchedRosterPlayers"]
        assert any("did not join to the board" in n for n in ctx["notes"])

    def test_stamps_its_value_scale(self):
        ctx = build_roster_context(_contract(), "pd_main", team_name="Alpha")
        assert ctx["valueScale"] == "rankDerivedValue"

    def test_resolves_a_team_by_owner_id_and_roster_id(self):
        by_owner = build_roster_context(_contract(), "pd_main", owner_id="owner-b")
        by_roster = build_roster_context(_contract(), "pd_main", roster_id=2)
        assert by_owner["team"]["name"] == by_roster["team"]["name"] == "Beta"

    def test_an_unknown_team_raises_rather_than_guessing(self):
        with pytest.raises(ValueError, match="unknown_team"):
            build_roster_context(_contract(), "pd_main", team_name="Nobody")

    def test_no_rosters_raises(self):
        with pytest.raises(ValueError, match="no_rosters_loaded"):
            build_roster_context({"playersArray": []}, "pd_main", team_name="Alpha")

    def test_lists_teams_without_leaking_a_sleeper_league_id(self):
        teams = list_draft_teams(_contract())
        assert [t["name"] for t in teams] == ["Alpha", "Beta"]
        blob = json.dumps(teams)
        assert "L-PD-MAIN" not in blob


class TestTaxiHonesty:
    def test_a_taxi_league_says_the_feed_does_not_exist(self, tmp_path, monkeypatch):
        path = tmp_path / "taxi.json"
        path.write_text(
            json.dumps(
                {
                    "defaultLeagueKey": "pd_main",
                    "leagues": [
                        {
                            "key": "pd_main",
                            "displayName": "PD Main",
                            "sleeperLeagueId": "L",
                            "scoringProfile": "prof_a",
                            "active": True,
                            "rosterSettings": {
                                "teamCount": 2,
                                "rosterSize": 5,
                                "taxiSize": 3,
                                "starters": {"QB": 1, "WR": 1},
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
        league_registry.reload_registry()
        ctx = build_roster_context(_contract(), "pd_main", team_name="Alpha")
        # Carried as a parameter, but never faked into open spots — nothing
        # in this codebase ingests Sleeper's per-player taxi assignment.
        assert ctx["taxiSize"] == 3
        assert ctx["taxiSlotsAvailable"] == 0
        assert any("taxi relief is NOT modelled" in n for n in ctx["notes"])


class TestCacheIsolation:
    def test_two_teams_never_share_a_cached_payload(self):
        contract = _contract()
        a = draft_optimizer_api.get_roster_context(contract, "pd_main", team_name="Alpha")
        b = draft_optimizer_api.get_roster_context(contract, "pd_main", team_name="Beta")
        assert a["team"]["name"] == "Alpha"
        assert b["team"]["name"] == "Beta"
        assert a["rosterCount"] != b["rosterCount"]

    def test_the_same_team_is_served_from_cache(self):
        contract = _contract()
        first = draft_optimizer_api.get_roster_context(contract, "pd_main", team_name="Alpha")
        with mock.patch.object(
            draft_optimizer_api, "build_roster_context", side_effect=AssertionError("rebuilt")
        ):
            again = draft_optimizer_api.get_roster_context(contract, "pd_main", team_name="Alpha")
        assert again is first

    def test_a_new_contract_invalidates(self):
        first = draft_optimizer_api.get_roster_context(_contract(), "pd_main", team_name="Alpha")
        fresh = _contract(roster_a=["Star QB"])
        fresh["generatedAt"] = "2026-07-31T00:00:00Z"
        second = draft_optimizer_api.get_roster_context(fresh, "pd_main", team_name="Alpha")
        assert first["rosterCount"] != second["rosterCount"]


# ── The route ────────────────────────────────────────────────────────


@pytest.fixture
def api(monkeypatch):
    client = TestClient(server.app)
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True, raising=False)
    return client


class TestRoute:
    def test_serves_the_team_list_without_a_team_identifier(self, api, monkeypatch):
        monkeypatch.setattr(server, "latest_contract_data", _contract(), raising=False)
        res = api.get("/api/draft/roster-context")
        assert res.status_code == 200, res.text
        body = res.json()
        assert [t["name"] for t in body["teams"]] == ["Alpha", "Beta"]
        assert body["context"] is None
        assert body["leagueKey"] == "pd_main"

    def test_serves_a_context_for_a_named_team(self, api, monkeypatch):
        monkeypatch.setattr(server, "latest_contract_data", _contract(), raising=False)
        res = api.get("/api/draft/roster-context", params={"teamName": "Alpha"})
        assert res.status_code == 200, res.text
        assert res.json()["context"]["team"]["name"] == "Alpha"

    def test_an_unknown_team_is_a_400_not_another_teams_numbers(self, api, monkeypatch):
        monkeypatch.setattr(server, "latest_contract_data", _contract(), raising=False)
        res = api.get("/api/draft/roster-context", params={"teamName": "Nobody"})
        assert res.status_code == 400
        assert res.json()["error"] == "unknown_team"

    def test_a_cold_contract_503s(self, api, monkeypatch):
        monkeypatch.setattr(server, "latest_contract_data", None, raising=False)
        res = api.get("/api/draft/roster-context")
        assert res.status_code == 503
        assert res.json()["error"] == "data_not_ready"

    def test_a_league_whose_rosters_are_not_loaded_503s(self, api, monkeypatch):
        # This is what scopes the feature to the league with a real rookie
        # pool: a league served only by the Sleeper-derived draft-capital
        # fallback has no genuine pool, and lands here rather than producing
        # a confident plan built on placeholder players.
        monkeypatch.setattr(server, "latest_contract_data", _contract(), raising=False)
        res = api.get("/api/draft/roster-context", params={"leagueKey": "pd_side"})
        assert res.status_code == 503
        assert res.json()["error"] == "data_not_ready"

    def test_an_unknown_league_is_a_400(self, api, monkeypatch):
        monkeypatch.setattr(server, "latest_contract_data", _contract(), raising=False)
        res = api.get("/api/draft/roster-context", params={"leagueKey": "nope"})
        assert res.status_code == 400
        assert res.json()["error"] == "unknown_league"

    def test_the_flag_gates_the_route(self, api, monkeypatch):
        monkeypatch.setattr(server, "latest_contract_data", _contract(), raising=False)
        monkeypatch.setenv("RISKIT_FEATURE_PERFECT_DRAFT", "0")
        feature_flags.reload()
        try:
            res = api.get("/api/draft/roster-context")
            assert res.status_code == 503
            assert res.json() == {"error": "feature_disabled", "flag": "perfect_draft"}
        finally:
            monkeypatch.delenv("RISKIT_FEATURE_PERFECT_DRAFT", raising=False)
            feature_flags.reload()


class TestFeasibilityObjectiveIsIrrelevant:
    """The cut ladder's lineup guard is a COUNT, and a count does not
    depend on the objective.

    ``build_roster_assets`` used to read ``rosValue`` off the contract
    row and coerce a missing one to ``0.0`` — a missing-as-zero over a
    field the contract does not carry at all (0 of 983 rows on the live
    board).  It was replaced by an explicit constant, which is only
    correct if the property below actually holds, so the property is
    pinned rather than assumed.
    """

    def test_the_filled_slot_count_is_the_same_for_any_objective(self):
        """``solve_optimal_assignment`` is a matroid greedy with
        augmenting paths: it never evicts an assigned player, so the
        matching it returns is maximum-cardinality whatever the weights
        are.  Weights decide WHO starts, not HOW MANY."""
        import random

        from src.draft.displacement import RosterAsset, _filled_slot_count

        slots = ["QB", "WR", "WR", "FLEX", "SUPER_FLEX"]
        base = [
            RosterAsset("p1", "P1", "QB", 900.0),
            RosterAsset("p2", "P2", "QB", 400.0),
            RosterAsset("p3", "P3", "WR", 800.0),
            RosterAsset("p4", "P4", "WR", 300.0),
            RosterAsset("p5", "P5", "RB", 700.0),
            RosterAsset("p6", "P6", "TE", 100.0),
        ]
        expected = _filled_slot_count(base, slots)
        rng = random.Random(20260818)
        for _ in range(50):
            shuffled = [
                RosterAsset(
                    a.player_id, a.name, a.position, a.board_value, ros_value=rng.random() * 1000
                )
                for a in base
            ]
            assert _filled_slot_count(shuffled, slots) == expected

    def test_an_unpriced_player_still_counts_toward_feasibility(self):
        """The constant is ``0.0`` and not ``None`` on purpose: ``None``
        is UNKNOWN and the solver excludes it, but a player the board
        could not price still occupies a body that can legally fill a
        slot."""
        from src.draft.context import _FEASIBILITY_OBJECTIVE
        from src.draft.displacement import RosterAsset, _filled_slot_count

        assert _FEASIBILITY_OBJECTIVE is not None
        unpriced = RosterAsset("u", "U", "QB", None, ros_value=_FEASIBILITY_OBJECTIVE)
        assert _filled_slot_count([unpriced], ["QB"]) == 1
        assert _filled_slot_count([RosterAsset("u", "U", "QB", None, ros_value=None)], ["QB"]) == 0
