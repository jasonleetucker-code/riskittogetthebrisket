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
        order, year, reason, _ = rule_slot_forecasts(sim(THREE), teams3())
        assert reason is None and year == 2027
        assert [r["rosterId"] for r in order] == [3, 1, 2]
        # Every slot used exactly once — a permutation, never a shared slot.
        assert [r["projectedSlot"] for r in order] == [1, 2, 3]

    def test_distribution_and_expected_slot_are_published(self):
        order, _, _, _ = rule_slot_forecasts(sim(THREE), teams3())
        t1 = next(r for r in order if r["rosterId"] == 1)
        assert t1["slotDistribution"] == [0.0, 0.6, 0.4]
        assert t1["expectedSlot"] == 2.4
        assert t1["mostLikelySlot"] == 2

    def test_confidence_is_the_weighted_mass_within_one_slot(self):
        """Label = P(within one slot) of the forecast shrunk by the same weight
        the pick market uses: a week-5 forecast is not "high", a final one is."""
        final = sim(THREE)
        final["regularSeasonProgress"] = {"weeksFinal": 14, "weeksTotal": 14}
        order, _, _, weight = rule_slot_forecasts(final, teams3())
        by = {r["rosterId"]: r for r in order}
        assert weight["forecastWeight"] == 1.0
        assert by[3]["slotWindowProbability"] == 1.0 and by[3]["confidence"] == "high"
        early, _, _, weight = rule_slot_forecasts(sim(THREE), teams3())
        assert 0 < weight["forecastWeight"] < 0.5
        assert {r["confidence"] for r in early} != {"high"}
        unknown = sim(THREE)
        unknown["regularSeasonProgress"] = None
        order, _, _, weight = rule_slot_forecasts(unknown, teams3())
        assert weight == {"forecastWeight": 0.0, "forecastWeightBasis": "season_progress_unknown"}
        # Zero weight is uniform: no slot reads better than the window share.
        assert all(r["confidence"] != "high" for r in order)

    def test_ties_on_expected_slot_break_on_roster_id(self):
        same = {1: [0.5, 0.5], 2: [0.5, 0.5]}
        order, _, _, _ = rule_slot_forecasts(sim(same), teams3())
        assert [r["rosterId"] for r in order] == [1, 2]

    def test_unknowns_are_reasons_never_an_order(self):
        def reason(payload, **kw):
            return rule_slot_forecasts(payload, teams3(), **kw)[2]

        assert reason(None) == pp.NO_SEASON_SIMULATION
        no_rule = sim(THREE)
        no_rule["draftOrderRule"] = None
        assert reason(no_rule) == pp.NO_DRAFT_ORDER_RULE
        no_season = sim(THREE)
        no_season["season"] = None
        assert reason(no_season) == pp.SIMULATED_SEASON_UNKNOWN

    def test_an_unsimulable_simulation_is_named_never_read_as_no_rule(self):
        """The refusal shape ``simulate_playoff_odds`` returns (preseason, the
        rollover-to-draft window): no draftOrderRule / season keys at all."""
        refusal = {
            "playoffOdds": [],
            "unsimulable": {"reason": "no_games_played_and_none_scheduled"},
        }
        for kw in ({}, {"league_rule": "reverse_record_lower_pf", "rule_known": True}):
            got = rule_slot_forecasts(refusal, teams3(), **kw)[2]
            assert got == "season_simulation_unsimulable:no_games_played_and_none_scheduled"

    def test_the_owner_decides_whether_a_rule_exists(self):
        # A league with no recorded rule gets no forecast whatever the sim says.
        got = rule_slot_forecasts(sim(THREE), teams3(), league_rule=None, rule_known=True)
        assert got[2] == pp.NO_DRAFT_ORDER_RULE
        # A league WITH a rule whose sim published no rule output: a sim gap.
        bare = sim(THREE)
        bare["draftOrderRule"] = None
        got = rule_slot_forecasts(
            bare, teams3(), league_rule="reverse_record_lower_pf", rule_known=True
        )
        assert got[2] == pp.NO_SLOT_DISTRIBUTION
        # A sim produced under a different rule is refused.
        other = sim(THREE, rule="some_other_rule")
        got = rule_slot_forecasts(
            other, teams3(), league_rule="reverse_record_lower_pf", rule_known=True
        )
        assert got[2] == pp.SIMULATION_RULE_MISMATCH

    def test_a_partial_order_is_refused_never_compressed(self):
        """One simulated team that cannot be joined (owner changed inside the
        cache window, orphan roster) or carries a malformed distribution
        refuses the whole order: dropping it would shift every later slot."""
        unjoined = {1: [0.0, 1.0, 0.0], 2: [0.0, 0.0, 1.0], 9: [1.0, 0.0, 0.0]}
        order, _, reason, _ = rule_slot_forecasts(sim(unjoined), teams3())
        assert (order, reason) == ([], pp.SIMULATION_JOIN_INCOMPLETE)
        for bad in (
            {1: [0.0, "x", 1.0], 2: [0.0, 0.0, 1.0], 3: [1.0, 0.0, 0.0]},
            {1: [-0.1, 1.1, 0.0], 2: [0.0, 0.0, 1.0], 3: [1.0, 0.0, 0.0]},
            {1: [0.5, 0.5], 2: [0.0, 0.0, 1.0], 3: [1.0, 0.0, 0.0]},
        ):
            order, _, reason, _ = rule_slot_forecasts(sim(bad), teams3())
            assert (order, reason) == ([], pp.NO_SLOT_DISTRIBUTION)


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
        # dynasty_new has no recorded rule: refused even with a full simulation.
        out = build_pick_projections(teams, sim(THREE), league_key="dynasty_new")
        assert out["picks"][0]["slotForecastUnavailableReason"] == pp.NO_DRAFT_ORDER_RULE
        assert out["meta"]["draftOrderRule"] is None
        for payload, reason in cases:
            out = build_pick_projections(teams, payload, current_season=2026)
            (p,) = out["picks"]
            assert p["projectedSlot"] is None
            assert p["slotForecastUnavailableReason"] == reason
            assert out["projectedOrder"] == []
            assert out["meta"]["slotForecastUnavailableReason"] == reason

    def test_a_known_rule_survives_an_unsimulable_window(self):
        """Preseason / rollover: dynasty_main HAS a rule; meta says so."""
        refusal = {
            "playoffOdds": [],
            "unsimulable": {"reason": "no_games_played_and_none_scheduled"},
        }
        teams = teams3({1: [pick(2027, 1, 1, 1)]})
        out = build_pick_projections(teams, refusal, league_key="dynasty_main", current_season=2026)
        assert out["meta"]["draftOrderRule"] == "reverse_record_lower_pf"
        assert out["picks"][0]["slotForecastUnavailableReason"].startswith(
            pp.SIMULATION_UNSIMULABLE + ":"
        )

    def test_a_class_before_the_simulated_draft_is_not_called_beyond_it(self):
        teams = teams3({1: [pick(2026, 1, 1, 1), pick(2027, 1, 1, 1)]})
        picks = build_pick_projections(teams, sim(THREE), current_season=2025)["picks"]
        by = {p["season"]: p for p in picks}
        assert by[2026]["slotForecastUnavailableReason"] == pp.BEFORE_SIMULATED_SEASON
        assert by[2027]["projectedSlot"] == 2

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

    def test_meta_reports_the_forecast_weight_it_used(self):
        meta = build_pick_projections(teams3(), sim(THREE))["meta"]
        assert meta["forecastWeightBasis"] == "provisional_season_progress"
        assert 0 < meta["forecastWeight"] < 1


class TestPickProjectionsEndpoint:
    def _client(self):
        app = FastAPI()
        app.include_router(ros_api.router)
        return TestClient(app)

    def _pin_league(self, monkeypatch):
        from types import SimpleNamespace

        import src.api.league_registry as registry

        # dynasty_main: the league with a recorded draft-order rule.
        fake_cfg = SimpleNamespace(key="dynasty_main", sleeper_league_id="123456")
        monkeypatch.setattr(registry, "get_league_by_key", lambda *a, **k: fake_cfg)
        monkeypatch.setattr(registry, "default_league_key", lambda: "dynasty_main")

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
        assert "error" not in body and body["leagueKey"] == "dynasty_main"
        assert seen == ["dynasty_main"]
        assert {p["originalRosterId"]: p["projectedSlot"] for p in body["picks"]} == {3: 1, 1: 2}

    def test_team_strength_cannot_decide_the_order(self, monkeypatch):
        """Behavioural: Team Strength says team 1 is weakest, the rule's
        simulation says team 3 is.  The simulation wins, and the endpoint
        never even reads Team Strength."""
        self._pin_league(monkeypatch)
        teams = teams3({1: [pick(2027, 1, 1, 1)], 3: [pick(2027, 1, 3, 3)]})
        import src.api.sleeper_overlay as overlay
        import src.ros.playoff_sim as playoff_sim

        def _strength(*_a, **_k):
            raise AssertionError("Team Strength must not be read for draft order")

        monkeypatch.setattr(ros_api, "load_or_compute_team_strength", _strength)
        monkeypatch.setattr(overlay, "fetch_sleeper_teams_overlay", lambda **k: {"teams": teams})
        monkeypatch.setattr(playoff_sim, "_load_cached_payload", lambda key=None: sim(THREE))
        body = self._client().get("/api/ros/pick-projections").json()
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
