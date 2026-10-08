"""TODO-2026-09-26-D3 — median games count in the record, the simulation,
seeding and draft order EXACTLY as the host counts them.

``dynasty_main`` runs ``league_average_match = 1``: every regular-season week
is two games, head-to-head plus one against the league median.  Measured
2026-09-26, the host showed 4-0 where the simulator showed 2-0.

EVIDENCE (primary, both recorded in the fixture's provenance):

* Sleeper's support article "Extra Game Each Week Against League Median"
  (``docs/game-day/MEDIAN_SEMANTICS_VERIFICATION.md``): the threshold is the
  average of the two middle scores; a score exactly on it is a TIE.
* Sleeper's own records, captured read-only 2026-10-08 after four finished
  weeks (``tests/fixtures/public_league/median_record_parity_2026w4.json``):
  dynasty_main (median on) — roster ``settings.wins/losses/ties`` equal
  H2H + median for 12 of 12 rosters; dynasty_new (median off) — equal H2H
  alone for 10 of 10.  The parity tests below replay that capture.

What this pins: record parity with the host for both leagues; the median
on / off / unverified states; ties against the median; simulated median wins
reaching seeding, expected wins and the draft-order record; the golden
playoff numbers byte-identical when the median is off; and the #1699 review
follow-ups F1 (an unfillable fixed bracket is a named refusal, not a
``ValueError``) and F2 (missing title odds cite ``championshipUnavailable``).
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from src.public_league import playoff_odds
from src.roster_intel.engine import analyze_roster
from src.ros import playoff_sim
from tests.ros.test_one_playoff_engine import (
    _PRE_CONSOLIDATION_PATH,
    _league,
    _with_strength,
)
from tests.ros.test_one_playoff_engine import engine as _one_engine

REPO = Path(__file__).resolve().parents[2]

#: The C5-PLAY-01 parity file's own ``engine`` fixture (no cache file, no
#: best-ball roster reads, a fixed ROS strength map), shared rather than copied.
engine = _one_engine
_PARITY = REPO / "tests" / "fixtures" / "public_league" / "median_record_parity_2026w4.json"


# ── the host's own records ────────────────────────────────────────────


def _captured_season(key: str):
    league = json.loads(_PARITY.read_text(encoding="utf-8"))["leagues"][key]
    weeks = list(range(1, (league["settings"]["playoff_week_start"] or 15)))
    matchups = {int(w): rows for w, rows in league["matchups"].items()}
    season = SimpleNamespace(
        season=league["season"],
        league_id=league["leagueId"],
        league={"settings": league["settings"]},
        num_teams=league["total_rosters"],
        rosters=league["rosters"],
        matchups_by_week=matchups,
        regular_season_weeks=weeks,
    )
    rids = [r["roster_id"] for r in league["rosters"]]
    registry = SimpleNamespace(
        roster_to_owner={(league["leagueId"], rid): f"o{rid}" for rid in rids},
    )
    host = {
        f"o{r['roster_id']}": tuple(r["settings"][k] or 0 for k in ("wins", "losses", "ties"))
        for r in league["rosters"]
    }
    return season, registry, host


@pytest.mark.parametrize("key", ["dynasty_main", "dynasty_new"])
def test_the_record_to_date_is_the_hosts_record(key):
    season, registry, host = _captured_season(key)
    records, rule = playoff_odds.regular_season_standings_to_date(season, registry)
    ours = {o: (r["wins"], r["losses"], r["ties"]) for o, r in records.items()}
    assert ours == host, f"{key}: our record differs from Sleeper's own standings"
    if key == "dynasty_main":
        assert rule["state"] == playoff_odds.MEDIAN_COUNTED
        # Every team played 4 median games beside its 4 H2H games.
        assert all(
            r["medianWins"] + r["medianLosses"] + r["medianTies"] == 4 for r in records.values()
        )
    else:
        assert rule == {"medianGame": False, "state": playoff_odds.MEDIAN_NOT_APPLICABLE}
        assert all("medianWins" not in r for r in records.values())


def test_the_measured_four_oh_is_no_longer_two_oh():
    """The intake's own symptom: after two finished weeks the host showed
    4-0 where the simulator showed 2-0.  Truncated to two weeks, the
    undefeated dynasty_main teams now carry four wins."""
    season, registry, _ = _captured_season("dynasty_main")
    season.league["settings"] = {**season.league["settings"], "last_scored_leg": 2}
    season.matchups_by_week = {w: r for w, r in season.matchups_by_week.items() if w <= 2}
    records = playoff_odds._regular_season_record_to_date(season, registry)
    assert max(r["wins"] for r in records.values()) == 4
    assert all(r["wins"] + r["losses"] + r["ties"] == 4 for r in records.values())


# ── ties against the median and the unverified states ────────────────


def _toy_season(scores_by_week, *, median=1, teams=None, finished=None):
    """Four-team pairs (1v2, 3v4, …) with the given scores."""
    n = len(scores_by_week[0])
    settings = {"last_scored_leg": finished if finished is not None else len(scores_by_week)}
    if median is not None:
        settings["league_average_match"] = median
    matchups = {
        wk + 1: [
            {"roster_id": i + 1, "matchup_id": i // 2 + 1, "points": pts}
            for i, pts in enumerate(scores)
        ]
        for wk, scores in enumerate(scores_by_week)
    }
    season = SimpleNamespace(
        season="2026",
        league_id="LT",
        league={"settings": settings},
        num_teams=teams if teams is not None else n,
        rosters=[{"roster_id": i + 1} for i in range(n)],
        matchups_by_week=matchups,
        regular_season_weeks=list(range(1, len(scores_by_week) + 1)),
    )
    registry = SimpleNamespace(roster_to_owner={("LT", i + 1): f"o{i + 1}" for i in range(n)})
    return season, registry


def test_a_score_exactly_on_the_median_is_a_tie():
    # Middle two scores are both 100, so the median is 100 and both are TIES.
    season, registry = _toy_season([[120.0, 100.0, 100.0, 80.0]])
    records, _ = playoff_odds.regular_season_standings_to_date(season, registry)
    assert (records["o1"]["medianWins"], records["o1"]["wins"]) == (1, 2)
    assert (records["o2"]["medianTies"], records["o2"]["ties"]) == (1, 1)
    assert (records["o3"]["medianTies"], records["o3"]["wins"], records["o3"]["ties"]) == (1, 1, 1)
    assert (records["o4"]["medianLosses"], records["o4"]["losses"]) == (1, 2)


def test_the_median_threshold_is_the_average_of_the_middle_two():
    # Median of 90/110 is 100: a 99.99 loses the median game, a 100.01 wins it.
    season, registry = _toy_season([[130.0, 90.0, 110.0, 70.0]])
    records, _ = playoff_odds.regular_season_standings_to_date(season, registry)
    assert records["o2"]["medianLosses"] == 1 and records["o3"]["medianWins"] == 1


def test_median_off_counts_head_to_head_only():
    season, registry = _toy_season([[120.0, 100.0, 100.0, 80.0]], median=0)
    records, rule = playoff_odds.regular_season_standings_to_date(season, registry)
    assert rule["state"] == playoff_odds.MEDIAN_NOT_APPLICABLE
    assert {o: r["wins"] + r["losses"] + r["ties"] for o, r in records.items()} == {
        f"o{i}": 1 for i in range(1, 5)
    }


def test_an_unknown_median_setting_is_unverified_not_off():
    season, registry = _toy_season([[120.0, 100.0, 100.0, 80.0]], median=None)
    records, rule = playoff_odds.regular_season_standings_to_date(season, registry)
    assert rule["state"] == playoff_odds.MEDIAN_UNVERIFIED
    assert rule["reason"] == "median_setting_unknown" and rule["medianGame"] is None
    assert all(r["wins"] + r["losses"] + r["ties"] == 1 for r in records.values())


def test_an_odd_sized_median_league_is_unverified():
    season, registry = _toy_season([[120.0, 100.0, 90.0, 80.0, 70.0, 60.0]], teams=5)
    _, rule = playoff_odds.regular_season_standings_to_date(season, registry)
    assert rule["state"] == playoff_odds.MEDIAN_UNVERIFIED
    assert rule["reason"] == "median_threshold_unverified_for_league_size"


def test_a_finished_week_missing_a_score_is_unresolved_not_guessed():
    season, registry = _toy_season([[120.0, 100.0, 90.0, None]])
    records, rule = playoff_odds.regular_season_standings_to_date(season, registry)
    assert rule["unresolvedWeeks"] == [1]
    assert all(r.get("medianWins", 0) + r.get("medianLosses", 0) == 0 for r in records.values())


# ── the simulation ────────────────────────────────────────────────────

_FOUR = ["aa", "bb", "cc", "dd"]


def _sim_snapshot(settings):
    season = SimpleNamespace(
        season="2026",
        league_id="L1",
        league={"settings": {"playoff_teams": 2, "playoff_week_start": 15, **settings}},
        num_teams=4,
        rosters=[{"roster_id": i + 1} for i in range(4)],
        matchups_by_week={},
        regular_season_weeks=[],
    )
    return SimpleNamespace(
        managers=SimpleNamespace(by_owner_id={}, roster_to_owner={}),
        current_season=season,
        seasons=[season],
    )


def _simulate(settings, *, means, record=None, schedule=None, sims=50, final_weeks=range(1, 2)):
    dists = {
        o: playoff_sim._TeamDist(owner_id=o, mean=means[o], sd=0.0, pf_to_date=0.0) for o in _FOUR
    }
    record = (
        record if record is not None else {o: {"wins": 0, "losses": 1, "ties": 0} for o in _FOUR}
    )
    schedule = schedule if schedule is not None else [(14, "aa", "dd"), (14, "bb", "cc")]
    with (
        mock.patch.object(playoff_sim, "_current_record", lambda *a, **k: record),
        mock.patch.object(playoff_sim, "_remaining_schedule", lambda *a, **k: schedule),
        mock.patch.object(playoff_sim, "_load_ros_strength_map", lambda *a, **k: {}),
        mock.patch.object(playoff_sim, "_league_best_ball", lambda *a, **k: False),
        mock.patch.object(playoff_sim, "_build_team_distributions", lambda *a, **k: (dists, {})),
        mock.patch.object(playoff_odds, "_final_week_set", lambda *a, **k: set(final_weeks)),
        mock.patch(
            "src.ros.team_strength.resolve_snapshot_league_key", lambda *a, **k: "dynasty_main"
        ),
    ):
        return playoff_sim.simulate_playoff_odds(
            _sim_snapshot(settings),
            n_simulations=sims,
            rng=random.Random(7),
        )


def test_each_simulated_week_awards_a_median_game():
    # Deterministic scores (sd 0): dd beats aa and cc beats bb head to head;
    # the week's median is (95+110)/2 = 102.5, so cc and dd also win the
    # median game.  Two wins each for cc/dd, none for aa/bb.
    means = {"aa": 80.0, "bb": 95.0, "cc": 110.0, "dd": 125.0}
    on = _simulate({"league_average_match": 1}, means=means)
    assert on["standingsRule"]["state"] == playoff_odds.MEDIAN_COUNTED
    wins = {r["ownerId"]: r["expectedWins"] for r in on["playoffOdds"]}
    assert wins == {"aa": 0.0, "bb": 0.0, "cc": 2.0, "dd": 2.0}

    off = _simulate({"league_average_match": 0}, means=means)
    assert {r["ownerId"]: r["expectedWins"] for r in off["playoffOdds"]} == {
        "aa": 0.0,
        "bb": 0.0,
        "cc": 1.0,
        "dd": 1.0,
    }


def test_a_simulated_median_tie_is_half_a_win():
    means = {o: 100.0 for o in _FOUR}
    out = _simulate({"league_average_match": 1}, means=means)
    # H2H tie (0.5) + median tie (0.5) for everyone.
    assert {r["expectedWins"] for r in out["playoffOdds"]} == {1.0}


def test_median_wins_decide_seeding():
    # Head to head alone, bb (3-0 record) is seeded first; once the
    # median games count, dd and cc reach four wins and pass it.
    means = {"aa": 80.0, "bb": 95.0, "cc": 110.0, "dd": 125.0}
    record = {
        "aa": {"wins": 0, "losses": 1, "ties": 0},
        "bb": {"wins": 3, "losses": 0, "ties": 0},
        "cc": {"wins": 0, "losses": 2, "ties": 0},
        "dd": {"wins": 0, "losses": 2, "ties": 0},
    }
    schedule = [(13, "aa", "dd"), (13, "bb", "cc"), (14, "aa", "cc"), (14, "bb", "dd")]
    on = _simulate({"league_average_match": 1}, means=means, record=record, schedule=schedule)
    off = _simulate({"league_average_match": 0}, means=means, record=record, schedule=schedule)
    seed = lambda out: {r["ownerId"]: r["mostLikelySeed"] for r in out["playoffOdds"]}  # noqa: E731
    assert seed(off)["bb"] == 1
    assert seed(on)["dd"] == 1 and seed(on)["bb"] > 1


def test_simulated_median_wins_reach_the_draft_order_record():
    means = {"aa": 80.0, "bb": 95.0, "cc": 110.0, "dd": 125.0}
    with mock.patch(
        "src.public_league.draft_order.league_draft_order_rule",
        lambda *a, **k: "reverse_record_then_lower_pf",
    ):
        out = _simulate({"league_average_match": 1}, means=means, record={})
    final = {r["ownerId"]: r["finalWins"]["mean"] for r in out["playoffOdds"]}
    assert final == {"aa": 0.0, "bb": 0.0, "cc": 2.0, "dd": 2.0}


def test_an_unknown_median_setting_is_published_with_its_reason():
    means = {"aa": 80.0, "bb": 95.0, "cc": 110.0, "dd": 125.0}
    out = _simulate({}, means=means)
    assert out["playoffOdds"], "an unknown setting labels the forecast, it does not refuse it"
    assert out["standingsRule"]["state"] == playoff_odds.MEDIAN_UNVERIFIED
    assert out["standingsRule"]["reason"] == "median_setting_unknown"


def test_a_median_league_with_an_incomplete_remaining_week_refuses():
    means = {"aa": 80.0, "bb": 95.0, "cc": 110.0, "dd": 125.0}
    out = _simulate({"league_average_match": 1}, means=means, schedule=[(14, "aa", "dd")])
    assert out["playoffOdds"] == []
    assert out["unsimulable"]["reason"] == "median_game_week_unsimulable"
    assert out["unsimulable"]["weeks"] == [14]


def test_an_odd_sized_median_league_refuses_rather_than_drop_the_median():
    means = {"aa": 80.0, "bb": 95.0, "cc": 110.0, "dd": 125.0}
    with mock.patch.object(playoff_odds, "_league_team_count", lambda *a, **k: 5):
        out = _simulate({"league_average_match": 1}, means=means)
    assert out["playoffOdds"] == []
    assert out["unsimulable"]["reason"] == "median_threshold_unverified_for_league_size"


# ── golden numbers, median off ────────────────────────────────────────


@pytest.mark.parametrize("median", [0, None])
def test_the_golden_forecast_is_byte_identical_when_the_median_is_off(engine, median):
    """The pre-consolidation pin (``test_one_playoff_engine``), re-run with the
    setting stated OFF and absent: grouping the schedule by week for the median
    game must not move a single draw."""
    pinned = json.loads(_PRE_CONSOLIDATION_PATH.read_text(encoding="utf-8"))
    snap, owners = _league()
    if median is not None:
        snap.current_season.league["settings"]["league_average_match"] = median
    _with_strength(engine, owners)
    out = playoff_sim.simulate_playoff_odds(snap, n_simulations=3000, rng=random.Random(20261007))
    got = {r["ownerId"]: {k: r[k] for k in pinned["fields"]} for r in out["playoffOdds"]}
    assert got == pinned["rows"]


def test_the_median_moves_the_golden_forecast_when_it_is_on(engine):
    """Non-vacuity for the test above: the same league with the median on
    publishes twice the games and different numbers."""
    pinned = json.loads(_PRE_CONSOLIDATION_PATH.read_text(encoding="utf-8"))
    snap, owners = _league()
    snap.current_season.league["settings"]["league_average_match"] = 1
    _with_strength(engine, owners)
    out = playoff_sim.simulate_playoff_odds(snap, n_simulations=3000, rng=random.Random(20261007))
    assert out["standingsRule"]["state"] == playoff_odds.MEDIAN_COUNTED
    got = {r["ownerId"]: {k: r[k] for k in pinned["fields"]} for r in out["playoffOdds"]}
    assert got != pinned["rows"]
    # 14 weeks, two games each.
    assert sum(r["expectedWins"] for r in out["playoffOdds"]) == pytest.approx(14 * 12, abs=0.05)


def test_a_cached_forecast_without_a_standings_rule_is_not_current(engine):
    snap, owners = _league()
    snap.current_season.league["settings"]["league_average_match"] = 1
    _with_strength(engine, owners)
    out = playoff_sim.simulate_playoff_odds(snap, n_simulations=2000, rng=random.Random(1))
    assert playoff_sim.cached_forecast_matches_snapshot(out, snap)
    legacy = {k: v for k, v in out.items() if k != "standingsRule"}
    assert not playoff_sim.cached_forecast_matches_snapshot(legacy, snap)
    snap.current_season.league["settings"]["league_average_match"] = 0
    assert not playoff_sim.cached_forecast_matches_snapshot(out, snap)


def test_the_public_section_publishes_the_hosts_record(engine):
    snap, owners = _league()
    snap.current_season.league["settings"]["league_average_match"] = 1
    _with_strength(engine, owners)
    section = playoff_odds.compute_playoff_odds(
        snap, forecast={"playoffOdds": [], "n_simulations": 0}
    )
    assert section["standingsRule"]["state"] == playoff_odds.MEDIAN_COUNTED
    # Four finished weeks, two games each: 48 wins+losses+ties across 12 teams
    # is 96 results, 48 of them wins (no exact ties in this fixture).
    assert sum(o["currentWins"] for o in section["owners"]) == 48


# ── #1699 review F1 / F2 ──────────────────────────────────────────────


def test_f1_a_fixed_bracket_the_field_cannot_fill_is_a_named_refusal():
    """Four owners in a six-team, two-bye FIXED bracket: round one leaves
    three teams, which no fixed bracket can pair.  On ``main`` before this
    change ``_bracket_order`` raised ``ValueError`` from inside the Monte
    Carlo."""
    means = {"aa": 80.0, "bb": 95.0, "cc": 110.0, "dd": 125.0}
    with mock.patch.object(
        playoff_sim,
        "resolve_playoff_structure",
        lambda *a, **k: SimpleNamespace(
            teams=6,
            byes=2,
            known=True,
            seed_type=0,
            seed_type_reason=None,
            reason=None,
            week_start=15,
            to_dict=lambda: {"teams": 6, "byes": 2, "seedType": 0},
        ),
    ):
        out = _simulate({"league_average_match": 0}, means=means)
    assert out["playoffOdds"], "seeding odds still publish"
    assert out["championshipUnavailable"]["reason"] == "fixed_bracket_field_unplayable"
    assert all(r["championshipOdds"] is None for r in out["playoffOdds"])


def test_f1_the_bracket_itself_never_raises():
    dists = {
        o: playoff_sim._TeamDist(owner_id=o, mean=100.0, sd=10.0, pf_to_date=0.0) for o in _FOUR
    }
    rng = random.Random(3)
    state = rng.getstate()
    assert playoff_sim._simulate_bracket(_FOUR, dists, 2, rng, reseed=False) is None
    assert rng.getstate() == state, "a refused bracket draws nothing"
    assert playoff_sim._fixed_bracket_refusal(6, 2) is None
    assert playoff_sim._fixed_bracket_refusal(4, 2)["reason"] == "fixed_bracket_field_unplayable"


def test_f2_missing_title_odds_cite_championship_unavailable():
    withheld = {"reason": "playoff_seed_type_unknown", "detail": "bracket rule unknown"}
    result = analyze_roster(
        "owner-1",
        [],
        ["QB"],
        playoff_odds=[{"ownerId": "owner-1", "playoffOdds": 0.62, "championshipOdds": None}],
        championship_unavailable=withheld,
    )
    published = result.to_dict()
    assert published["championshipOdds"] is None
    text = " ".join(result.notes) if hasattr(result, "notes") else json.dumps(published)
    assert "championshipUnavailable: playoff_seed_type_unknown" in text
    assert "stops at playoff qualification" not in text
