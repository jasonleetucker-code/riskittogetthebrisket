"""Pick Projector (Phase 7.1) — projection math + endpoint tests.

Covers: reverse-standings order from team strength, slot-confidence
bands, the original-roster slot rule for traded picks, the
current-season exclusion, and the /api/ros/pick-projections endpoint's
degraded states.  No live network anywhere.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.ros.api as ros_api
from src.ros.pick_projection import build_pick_projections, project_draft_order


def strength_row(rid: int, strength: float, name: str | None = None) -> dict:
    return {
        "rosterId": rid,
        "ownerId": f"owner{rid}",
        "teamName": name or f"Team {rid}",
        "teamRosStrength": strength,
    }


def team(rid: int, name: str, pick_details: list[dict]) -> dict:
    return {
        "name": name,
        "ownerId": f"owner{rid}",
        "roster_id": rid,
        "players": [],
        "playerIds": [],
        "picks": [p.get("label", "") for p in pick_details if isinstance(p, dict)],
        "pickDetails": pick_details,
    }


def pick(season: int, rnd: int, original: int, owner: int) -> dict:
    return {
        "season": str(season),
        "round": rnd,
        "slot": None,
        "original_roster_id": original,
        "owner_roster_id": owner,
        "label": f"{season} Round {rnd}",
    }


class TestProjectDraftOrder:
    def test_weakest_team_picks_first(self):
        rows = [strength_row(1, 900.0), strength_row(2, 400.0), strength_row(3, 650.0)]
        order = project_draft_order(rows)
        assert [r["rosterId"] for r in order] == [2, 3, 1]
        assert [r["projectedSlot"] for r in order] == [1, 2, 3]

    def test_ties_break_on_roster_id_for_determinism(self):
        rows = [strength_row(9, 500.0), strength_row(3, 500.0)]
        order = project_draft_order(rows)
        assert [r["rosterId"] for r in order] == [3, 9]

    def test_rows_without_strength_are_excluded(self):
        rows = [strength_row(1, 500.0), {"rosterId": 2, "teamRosStrength": None}, {"junk": True}]
        order = project_draft_order(rows)
        assert len(order) == 1
        assert order[0]["rosterId"] == 1

    def test_confidence_bands_track_neighbor_gaps(self):
        # 100, 105 clustered; 400 far adrift.  avg gap = 150.
        rows = [strength_row(1, 100.0), strength_row(2, 105.0), strength_row(3, 400.0)]
        order = project_draft_order(rows)
        by_rid = {r["rosterId"]: r for r in order}
        # Clustered pair: min gap 5 / 150 → low.
        assert by_rid[1]["confidence"] == "low"
        assert by_rid[2]["confidence"] == "low"
        # Isolated team: min gap 295 / 150 → high.
        assert by_rid[3]["confidence"] == "high"

    def test_degenerate_league_is_low_confidence(self):
        rows = [strength_row(1, 500.0), strength_row(2, 500.0)]
        assert all(r["confidence"] == "low" for r in project_draft_order(rows))

    def test_empty_input(self):
        assert project_draft_order([]) == []


class TestBuildPickProjections:
    def _fixture(self):
        strength = [
            strength_row(1, 300.0, "Rebuilders"),  # slot 1
            strength_row(2, 600.0, "Middlers"),  # slot 2
            strength_row(3, 900.0, "Champs"),  # slot 3
        ]
        teams = [
            team(1, "Rebuilders", [pick(2027, 1, 1, 1), pick(2026, 1, 1, 1)]),
            # Champs traded their 2027 1st to Middlers.
            team(2, "Middlers", [pick(2027, 1, 3, 2)]),
            team(3, "Champs", [pick(2027, 2, 3, 3)]),
        ]
        return teams, strength

    def test_current_season_picks_are_excluded(self):
        teams, strength = self._fixture()
        out = build_pick_projections(teams, strength, current_season=2026)
        assert all(p["season"] > 2026 for p in out["picks"])

    def test_slot_follows_the_original_roster(self):
        teams, strength = self._fixture()
        out = build_pick_projections(teams, strength, current_season=2026)
        traded = next(p for p in out["picks"] if p["ownerRosterId"] == 2)
        # Champs (slot 3) traded the pick — it projects at THEIR slot.
        assert traded["originalRosterId"] == 3
        assert traded["projectedSlot"] == 3
        assert traded["label"] == "2027 1.03"
        assert traded["ownerTeam"] == "Middlers"
        assert traded["originalTeam"] == "Champs"

    def test_pick_number_math_spans_rounds(self):
        teams, strength = self._fixture()
        out = build_pick_projections(teams, strength, current_season=2026)
        second_rounder = next(p for p in out["picks"] if p["round"] == 2)
        # 3 teams: round 2 slot 3 → overall pick 6.
        assert second_rounder["projectedPickNumber"] == 6

    def test_unprojectable_original_is_counted_not_guessed(self):
        teams = [team(1, "A", [pick(2027, 1, 99, 1)])]
        strength = [strength_row(1, 300.0)]
        out = build_pick_projections(teams, strength, current_season=2026)
        assert out["picks"] == []
        assert out["meta"]["unprojectablePicks"] == 1

    def test_output_sorted_and_meta_stamped(self):
        teams, strength = self._fixture()
        out = build_pick_projections(teams, strength, current_season=2026)
        keys = [(p["season"], p["round"], p["projectedSlot"]) for p in out["picks"]]
        assert keys == sorted(keys)
        assert out["meta"]["teamCount"] == 3
        assert out["meta"]["source"] == "teamRosStrength"

    def test_malformed_rows_are_skipped(self):
        teams = [team(1, "A", [{"season": "notayear", "round": 1}, "junk", None])]
        strength = [strength_row(1, 300.0)]
        out = build_pick_projections(teams, strength, current_season=2026)
        assert out["picks"] == []


class TestPickProjectionsEndpoint:
    def _client(self):
        app = FastAPI()
        app.include_router(ros_api.router)
        return TestClient(app)

    def test_no_snapshot_degrades_explicitly(self, monkeypatch):
        monkeypatch.setattr(ros_api, "load_team_strength_snapshot", lambda *a, **k: None)
        res = self._client().get("/api/ros/pick-projections")
        assert res.status_code == 200
        body = res.json()
        assert body["error"] == "no_snapshot"
        assert body["picks"] == []

    def test_overlay_failure_degrades_explicitly(self, monkeypatch):
        monkeypatch.setattr(
            ros_api,
            "load_team_strength_snapshot",
            lambda *a, **k: [strength_row(1, 300.0)],
        )
        import src.api.sleeper_overlay as overlay

        monkeypatch.setattr(overlay, "fetch_sleeper_teams_overlay", lambda **k: None)
        res = self._client().get("/api/ros/pick-projections")
        body = res.json()
        assert body["error"] == "no_teams"
        assert body["picks"] == []

    def test_happy_path_projects_and_stamps_league(self, monkeypatch):
        from types import SimpleNamespace

        strength = [strength_row(1, 300.0, "Rebuilders"), strength_row(2, 900.0, "Champs")]
        teams = [
            team(1, "Rebuilders", [pick(2027, 1, 1, 1)]),
            team(2, "Champs", [pick(2027, 1, 2, 2)]),
        ]
        monkeypatch.setattr(ros_api, "load_team_strength_snapshot", lambda *a, **k: strength)
        # The endpoint resolves the league lazily through the registry;
        # pin a fake league so the test doesn't depend on the sandbox's
        # registry file carrying a Sleeper id.
        import src.api.league_registry as registry

        fake_cfg = SimpleNamespace(key="test_league", sleeper_league_id="123456")
        monkeypatch.setattr(registry, "get_league_by_key", lambda *a, **k: fake_cfg)
        monkeypatch.setattr(registry, "default_league_key", lambda: "test_league")
        import src.api.sleeper_overlay as overlay

        monkeypatch.setattr(overlay, "fetch_sleeper_teams_overlay", lambda **k: {"teams": teams})
        res = self._client().get("/api/ros/pick-projections")
        body = res.json()
        assert "error" not in body
        assert body["leagueKey"]
        assert len(body["picks"]) == 2
        slots = {p["originalRosterId"]: p["projectedSlot"] for p in body["picks"]}
        assert slots == {1: 1, 2: 2}
