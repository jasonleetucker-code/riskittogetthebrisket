"""Live Median Race — the league render block, ranking, movement and archive.

Pins what ``src.api.matchup_intel.median_race_block`` and the generation
chain in ``src.ros.game_day_live`` publish: every roster once, ranked by the
simulation's own probabilities with a documented deterministic tie-break,
the objective bubble, honest current / final medians, movement only against a
comparable superseded generation, and calibration evidence in the
append-only generation index.  Real replay payloads come from the committed
Game Day fixtures (pinned byte-equal to the endpoint).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.api.matchup_intel import median_race_block
from src.ros import game_day_live as live
from tests.game_day import ui_payloads


def _fixture(name):
    return json.loads(ui_payloads.fixture_path(name).read_text(encoding="utf-8"))


# ── Real replay payloads ────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["pregame", "halftime", "week-final", "pending"])
def test_every_league_roster_appears_exactly_once(name):
    p = _fixture(name)
    race = p["medianRace"]
    ids = [t["rosterId"] for t in race["teams"]]
    assert sorted(ids) == sorted(t["rosterId"] for t in p["leagueTeams"])
    assert len(ids) == len(set(ids))
    assert [t["rank"] for t in race["teams"]] == list(range(1, len(ids) + 1))


def test_the_selected_row_matches_the_hero_exactly():
    for name in ("pregame", "halftime", "halftime-opponent"):
        p = _fixture(name)
        race = p["medianRace"]
        assert race["selectedRosterId"] == p["team"]["rosterId"]
        row = next(t for t in race["teams"] if t["rosterId"] == race["selectedRosterId"])
        assert row["beatMedianPct"] == p["team"]["outcome"]["beatMedianPct"]
        assert row["medianMarginMean"] == p["team"]["outcome"]["medianMarginMean"]
        assert row["ownerId"] == p["team"]["ownerId"]


def test_forecast_rows_order_by_probability_then_margin():
    race = _fixture("halftime")["medianRace"]
    assert race["state"] == "forecast"
    keys = [(-t["beatMedianPct"], -t["medianMarginMean"]) for t in race["teams"]]
    assert keys == sorted(keys)
    assert race["projectedMedianP10"] <= race["projectedMedianP50"] <= race["projectedMedianP90"]


def test_halftime_movement_is_against_the_superseded_generation():
    race = _fixture("halftime")["medianRace"]
    # The replay collector ticked pre-kickoff, then at capture: comparable.
    assert race["movement"]["comparedToGenerationId"]
    assert any(t["movementPp"] not in (None, 0.0) for t in race["teams"])


def test_pregame_scores_are_known_zeros_and_the_median_is_projected():
    race = _fixture("pregame")["medianRace"]
    assert race["currentMedianState"] == "pregame" and race["currentMedian"] == 0.0
    assert all(t["scoreNow"] == 0.0 for t in race["teams"])
    assert race["projectedMedianMean"] is not None
    # The first generation of the week has no predecessor: no movement.
    assert race["movement"] is None
    assert all(t["movementPp"] is None for t in race["teams"])


def test_final_resolves_to_actual_results_not_a_stale_forecast():
    race = _fixture("week-final")["medianRace"]
    assert race["state"] == "final"
    assert race["projectedMedianMean"] is None
    assert race["bubble"] == []
    for t in race["teams"]:
        expected = (
            "BEAT"
            if t["finalScore"] > race["finalMedian"]
            else "TIE"
            if t["finalScore"] == race["finalMedian"]
            else "MISS"
        )
        assert t["finalResult"] == expected
    scores = [t["finalScore"] for t in race["teams"]]
    assert scores == sorted(scores, reverse=True)


def test_pending_publishes_facts_and_no_probabilities():
    race = _fixture("pending")["medianRace"]
    assert race["state"] == "pending"
    assert all(t["beatMedianPct"] is None for t in race["teams"])
    assert race["projectedMedianMean"] is None
    known = [t["scoreNow"] for t in race["teams"]]
    assert known == sorted(known, reverse=True)


# ── median_race_block over synthetic sides ──────────────────────────────


def _side(rid, pct, *, margin=0.0, mean=100.0, now=50.0, complete=True, actual=None):
    return {
        "rosterId": rid,
        "ownerId": f"o{rid}",
        "teamName": f"Team {rid}",
        "displayName": f"mgr {rid}",
        "scoreNow": {"bestBallFromBankedPoints": now, "complete": complete},
        "actualScore": actual,
        "outcome": {
            "beatMedianPct": pct,
            "beatMedianState": "OK" if pct is not None else "NOT_APPLICABLE",
            "medianMarginMean": margin,
            "projectedMean": mean,
        },
    }


SIM = SimpleNamespace(
    threshold_semantics="median",
    median_distribution={"mean": 101.0, "p10": 90.0, "p50": 100.5, "p90": 112.0, "draws": 400},
)


def _block(sides, *, mode="live", enabled=True, pending=False, sim=SIM):
    return median_race_block(
        {s["rosterId"]: s for s in sides},
        simulation=sim,
        rules=SimpleNamespace(median_enabled=enabled),
        mode=mode,
        pending=pending,
        median_verified=(True, None),
    )


def test_ties_break_by_margin_then_projection_then_roster():
    race = _block(
        [
            _side("3", 50.0, margin=1.0, mean=100),
            _side("1", 50.0, margin=2.0, mean=90),
            _side("2", 50.0, margin=2.0, mean=95),
            _side("4", 50.0, margin=2.0, mean=95),
        ]
    )
    assert [t["rosterId"] for t in race["teams"]] == ["2", "4", "1", "3"]


def test_the_bubble_is_probability_distance_from_fifty():
    race = _block(
        [_side("1", 97.0), _side("2", 55.0), _side("3", 49.0), _side("4", 36.0), _side("5", 60.5)]
    )
    assert race["bubble"] == ["3", "2", "5"]


def test_current_median_needs_every_score_complete():
    ok = _block([_side("1", 60, now=10), _side("2", 40, now=20), _side("3", 50, now=30)])
    assert ok["currentMedian"] == 20.0 and ok["currentMedianState"] == "complete"
    partial = _block([_side("1", 60, now=10), _side("2", 40, now=20, complete=False)])
    assert partial["currentMedian"] is None
    assert partial["currentMedianState"] == "incomplete_live_scoring"
    missing = _block([_side("1", 60, now=10), _side("2", 40, now=None)])
    assert missing["currentMedian"] is None


def test_final_exact_median_is_a_tie():
    race = _block(
        [
            _side("1", None, actual=10.0),
            _side("2", None, actual=20.0),
            _side("3", None, actual=20.0),
            _side("4", None, actual=30.0),
        ],
        mode="final",
    )
    by = {t["rosterId"]: t["finalResult"] for t in race["teams"]}
    assert race["finalMedian"] == 20.0
    assert by == {"1": "MISS", "2": "TIE", "3": "TIE", "4": "BEAT"}


def test_final_with_a_missing_score_does_not_invent_a_median():
    race = _block([_side("1", None, actual=10.0), _side("2", None, actual=None)], mode="final")
    assert race["state"] == "final_scores_incomplete"
    assert race["finalMedian"] is None
    assert all(t["finalResult"] is None for t in race["teams"])


@pytest.mark.parametrize("enabled,state", [(False, "not_applicable"), (None, "unverified")])
def test_no_median_leg_publishes_no_projection(enabled, state):
    race = _block([_side("1", None), _side("2", None)], enabled=enabled)
    assert race["state"] == state
    assert race["projectedMedianMean"] is None and race["bubble"] == []


def test_identity_is_the_roster_and_owner_ids_not_the_name():
    race = _block([_side("1", 60), _side("2", 40)])
    row = race["teams"][0]
    assert (row["rosterId"], row["ownerId"]) == ("1", "o1")


# ── Movement through the real generation chain ──────────────────────────


def _generation(seq, pcts, *, model="game-day-sim-v4", state="forecast"):
    sides = {rid: _side(rid, pct, margin=pct - 50) for rid, pct in pcts.items()}
    race = (
        _block(list(sides.values()))
        if state == "forecast"
        else _block(list(sides.values()), pending=True)
    )
    return {
        "schemaVersion": live.GENERATION_SCHEMA_VERSION,
        "generationId": f"lg:2026:w4:{seq}",
        "leagueKey": "lg",
        "season": 2026,
        "week": 4,
        "sequence": float(seq),
        "computedAt": f"2026-09-27T17:{seq:02d}:00Z",
        "modelVersion": model,
        "render": {"shared": {"mode": "live"}, "sides": sides, "medianRace": race},
    }


@pytest.fixture
def live_root(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "LIVE_ROOT", tmp_path)
    live._generation_cache.clear()
    return tmp_path


def _order(gen):
    return [(t["rosterId"], t["beatMedianPct"]) for t in gen["render"]["medianRace"]["teams"]]


def test_a_new_generation_reorders_and_moves(live_root):
    assert live.write_generation(_generation(1, {"A": 75.0, "B": 55.0, "C": 40.0}))
    assert live.write_generation(_generation(2, {"A": 62.0, "B": 80.0, "C": 35.0}))
    gen = live.load_generation("lg", 2026, 4)
    assert _order(gen) == [("B", 80.0), ("A", 62.0), ("C", 35.0)]
    moves = {t["rosterId"]: t["movementPp"] for t in gen["render"]["medianRace"]["teams"]}
    assert moves == {"B": 25.0, "A": -13.0, "C": -5.0}
    assert gen["render"]["medianRace"]["movement"]["comparedToGenerationId"] == "lg:2026:w4:1"


def test_an_older_generation_arriving_late_never_rolls_the_board_back(live_root):
    live.write_generation(_generation(1, {"A": 75.0, "B": 55.0, "C": 40.0}))
    live.write_generation(_generation(3, {"A": 62.0, "B": 80.0, "C": 35.0}))
    assert live.write_generation(_generation(2, {"A": 99.0, "B": 1.0, "C": 50.0})) is False
    assert _order(live.load_generation("lg", 2026, 4))[0] == ("B", 80.0)


def test_no_movement_across_model_versions(live_root):
    live.write_generation(_generation(1, {"A": 75.0, "B": 55.0}, model="game-day-sim-v3"))
    live.write_generation(_generation(2, {"A": 62.0, "B": 80.0}))
    race = live.load_generation("lg", 2026, 4)["render"]["medianRace"]
    assert race["movement"] is None
    assert all(t["movementPp"] is None for t in race["teams"])


def test_no_movement_against_a_non_forecast_predecessor(live_root):
    live.write_generation(_generation(1, {"A": 75.0, "B": 55.0}, state="pending"))
    live.write_generation(_generation(2, {"A": 62.0, "B": 80.0}))
    assert live.load_generation("lg", 2026, 4)["render"]["medianRace"]["movement"] is None


def test_the_generation_index_keeps_calibration_evidence(live_root):
    live.write_generation(_generation(1, {"A": 75.0, "B": 55.0, "C": 40.0}))
    rows = live.load_generation_history("lg", 2026, 4)
    summary = rows[-1]["medianRace"]
    assert summary["projectedMedianMean"] == 101.0
    assert summary["projectedMedianP10"] == 90.0 and summary["projectedMedianP90"] == 112.0
    assert summary["teams"]["A"]["beatMedianPct"] == 75.0
    assert rows[-1]["modelVersion"] == "game-day-sim-v4"
    assert rows[-1]["computedAt"]
