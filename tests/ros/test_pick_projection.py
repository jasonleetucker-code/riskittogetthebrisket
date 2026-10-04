"""Pick Projector — slots from the season simulation under the draft-order rule.

The canonical rule (``src/public_league/draft_order.py``, owner decision
2026-10-04) decides which team picks where; the season simulation applies it
in every simulated season and publishes ``draftSlotDistribution``.  These
tests pin that the projector reads THAT, never Team Strength rank; that only
the class after the simulated season is forecast; that unknown is ``None`` with
a named reason (never slot 0); and the endpoint's degraded states.  No live
network anywhere.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.ros.api as ros_api
from src.ros import pick_projection as pp
from src.ros.pick_projection import build_pick_projections, rule_slot_forecasts


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


def sim(dists: dict[int, list[float]], *, season: int = 2026, rule: str | None = None) -> dict:
    """A season-simulation payload: one playoffOdds row per roster id."""
    return {
        "season": season,
        "draftOrderRule": rule if rule is not None else "reverse_record_lower_pf",
        "n_simulations": 4000,
        "regularSeasonProgress": {"weeksFinal": 5, "weeksTotal": 14},
        "playoffOdds": [
            {
                "ownerId": f"owner{rid}",
                "draftSlotDistribution": dist,
                "finalWins": {"p50": 7},
                "finalPointsFor": {"p50": 1500.0},
            }
            for rid, dist in dists.items()
        ],
    }


THREE = {
    # Team 3 is the clear worst (slot 1); 1 and 2 split slots 2 and 3.
    1: [0.0, 0.6, 0.4],
    2: [0.0, 0.4, 0.6],
    3: [1.0, 0.0, 0.0],
}


def teams3(extra: dict[int, list[dict]] | None = None) -> list[dict]:
    extra = extra or {}
    return [team(r, f"Team {r}", extra.get(r, [])) for r in (1, 2, 3)]


class TestRuleSlotForecasts:
    def test_order_follows_expected_rule_slot(self):
        order, year, reason = rule_slot_forecasts(sim(THREE), teams3())
        assert reason is None and year == 2027
        assert [r["rosterId"] for r in order] == [3, 1, 2]
        # Every slot used exactly once — a permutation, never a shared slot.
        assert [r["projectedSlot"] for r in order] == [1, 2, 3]

    def test_distribution_and_expected_slot_are_published(self):
        order, _, _ = rule_slot_forecasts(sim(THREE), teams3())
        t1 = next(r for r in order if r["rosterId"] == 1)
        assert t1["slotDistribution"] == [0.0, 0.6, 0.4]
        assert t1["expectedSlot"] == 2.4
        assert t1["mostLikelySlot"] == 2

    def test_confidence_is_the_mass_within_one_slot(self):
        order, _, _ = rule_slot_forecasts(sim(THREE), teams3())
        by = {r["rosterId"]: r for r in order}
        assert by[3]["slotWindowProbability"] == 1.0 and by[3]["confidence"] == "high"
        wide = {1: [0.1] * 10, 2: [0.1] * 10, 3: [0.1] * 10}
        flat, _, _ = rule_slot_forecasts(sim(wide), teams3())
        assert all(r["confidence"] == "low" for r in flat)

    def test_ties_on_expected_slot_break_on_roster_id(self):
        same = {1: [0.5, 0.5], 2: [0.5, 0.5]}
        order, _, _ = rule_slot_forecasts(sim(same), teams3())
        assert [r["rosterId"] for r in order] == [1, 2]

    def test_unknowns_are_reasons_never_an_order(self):
        assert rule_slot_forecasts(None, teams3()) == ([], None, pp.NO_SEASON_SIMULATION)
        no_rule = sim(THREE)
        no_rule["draftOrderRule"] = None
        assert rule_slot_forecasts(no_rule, teams3())[2] == pp.NO_DRAFT_ORDER_RULE
        no_season = sim(THREE)
        no_season["season"] = None
        assert rule_slot_forecasts(no_season, teams3())[2] == pp.SIMULATED_SEASON_UNKNOWN
        rollover = sim(THREE)
        for r in rollover["playoffOdds"]:
            r.pop("draftSlotDistribution")
        assert rule_slot_forecasts(rollover, teams3()) == ([], 2027, pp.NO_SLOT_DISTRIBUTION)

    def test_a_malformed_distribution_row_is_skipped_not_zeroed(self):
        bad = {1: [0.0, "x", 1.0], 2: [-0.1, 1.1], 3: [1.0, 0.0, 0.0]}
        order, _, _ = rule_slot_forecasts(sim(bad), teams3())
        assert [r["rosterId"] for r in order] == [3]


class TestBuildPickProjections:
    def test_next_class_gets_the_original_teams_rule_slot(self):
        teams = teams3({1: [pick(2027, 1, 3, 1)]})  # team 1 holds team 3's first
        (p,) = build_pick_projections(teams, sim(THREE))["picks"]
        assert p["projectedSlot"] == 1 and p["label"] == "2027 1.01"
        assert p["originalRosterId"] == 3 and p["ownerRosterId"] == 1
        assert p["slotDistribution"] == [1.0, 0.0, 0.0]
        assert p["slotForecastUnavailableReason"] is None

    def test_pick_number_math_spans_rounds(self):
        teams = teams3({2: [pick(2027, 2, 2, 2)]})
        (p,) = build_pick_projections(teams, sim(THREE))["picks"]
        assert p["projectedSlot"] == 3 and p["projectedPickNumber"] == 6

    def test_later_classes_carry_no_slot_never_a_guess(self):
        teams = teams3({1: [pick(2028, 1, 1, 1), pick(2029, 1, 1, 1)]})
        picks = build_pick_projections(teams, sim(THREE))["picks"]
        assert [p["season"] for p in picks] == [2028, 2029]
        for p in picks:
            assert p["projectedSlot"] is None and p["projectedPickNumber"] is None
            assert p["confidence"] is None and p["label"] == f"{p['season']} Round 1"
            assert p["slotForecastUnavailableReason"] == pp.BEYOND_SIMULATED_SEASON

    def test_no_rule_or_no_simulation_lists_picks_without_slots(self):
        teams = teams3({1: [pick(2027, 1, 1, 1)]})
        cases = ((None, pp.NO_SEASON_SIMULATION), (sim(THREE, rule=""), pp.NO_DRAFT_ORDER_RULE))
        for payload, reason in cases:
            out = build_pick_projections(teams, payload, current_season=2026)
            (p,) = out["picks"]
            assert p["projectedSlot"] is None
            assert p["slotForecastUnavailableReason"] == reason
            assert out["projectedOrder"] == []
            assert out["meta"]["slotForecastUnavailableReason"] == reason

    def test_current_and_past_classes_are_excluded(self):
        teams = teams3({1: [pick(2026, 1, 1, 1), pick(2025, 1, 1, 1)]})
        assert build_pick_projections(teams, sim(THREE))["picks"] == []

    def test_an_unsimulated_origin_is_counted_not_guessed(self):
        teams = teams3({1: [pick(2027, 1, 9, 1)]})
        out = build_pick_projections(teams, sim(THREE))
        (p,) = out["picks"]
        assert p["projectedSlot"] is None
        assert p["slotForecastUnavailableReason"] == pp.ORIGIN_NOT_SIMULATED
        assert out["meta"]["unprojectablePicks"] == 1

    def test_meta_names_the_rule_and_the_simulation(self):
        meta = build_pick_projections(teams3(), sim(THREE))["meta"]
        assert meta["source"] == "season_simulation"
        assert meta["projectorVersion"] == pp.PROJECTOR_VERSION
        assert meta["draftOrderRule"] == "reverse_record_lower_pf"
        assert meta["simulatedSeason"] == 2026 and meta["forecastDraftYear"] == 2027
        assert meta["regularSeasonProgress"] == {"weeksFinal": 5, "weeksTotal": 14}

    def test_team_strength_cannot_decide_the_order(self):
        """The retired route ordered by ``teamRosStrength``; nothing reads it now."""
        import inspect

        code = inspect.getsource(pp).split('"""', 2)[2]  # past the module docstring
        assert "teamRosStrength" not in code
        assert not hasattr(pp, "project_draft_order")


class TestPickProjectionsEndpoint:
    def _client(self):
        app = FastAPI()
        app.include_router(ros_api.router)
        return TestClient(app)

    def _pin_league(self, monkeypatch):
        from types import SimpleNamespace

        import src.api.league_registry as registry

        fake_cfg = SimpleNamespace(key="test_league", sleeper_league_id="123456")
        monkeypatch.setattr(registry, "get_league_by_key", lambda *a, **k: fake_cfg)
        monkeypatch.setattr(registry, "default_league_key", lambda: "test_league")

    def test_overlay_failure_degrades_explicitly(self, monkeypatch):
        self._pin_league(monkeypatch)
        import src.api.sleeper_overlay as overlay

        monkeypatch.setattr(overlay, "fetch_sleeper_teams_overlay", lambda **k: None)
        body = self._client().get("/api/ros/pick-projections").json()
        assert body["error"] == "no_teams"
        assert body["picks"] == []

    def test_happy_path_reads_the_cached_simulation(self, monkeypatch):
        self._pin_league(monkeypatch)
        teams = teams3({1: [pick(2027, 1, 1, 1)], 3: [pick(2027, 1, 3, 3)]})
        import src.api.sleeper_overlay as overlay
        import src.ros.playoff_sim as playoff_sim

        monkeypatch.setattr(overlay, "fetch_sleeper_teams_overlay", lambda **k: {"teams": teams})
        seen: list = []
        monkeypatch.setattr(
            playoff_sim, "_load_cached_payload", lambda key=None: seen.append(key) or sim(THREE)
        )
        body = self._client().get("/api/ros/pick-projections").json()
        assert "error" not in body and body["leagueKey"] == "test_league"
        assert seen == ["test_league"]
        assert {p["originalRosterId"]: p["projectedSlot"] for p in body["picks"]} == {3: 1, 1: 2}

    def test_no_simulation_is_not_an_error(self, monkeypatch):
        self._pin_league(monkeypatch)
        teams = teams3({1: [pick(2027, 1, 1, 1)]})
        import src.api.sleeper_overlay as overlay
        import src.ros.playoff_sim as playoff_sim

        monkeypatch.setattr(overlay, "fetch_sleeper_teams_overlay", lambda **k: {"teams": teams})
        monkeypatch.setattr(playoff_sim, "_load_cached_payload", lambda key=None: None)
        body = self._client().get("/api/ros/pick-projections").json()
        assert "error" not in body
        (p,) = body["picks"]
        assert p["projectedSlot"] is None
        assert body["meta"]["slotForecastUnavailableReason"] == pp.NO_SEASON_SIMULATION
