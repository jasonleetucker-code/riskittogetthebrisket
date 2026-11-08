"""League-specific division rules in the canonical playoff engine (owner, 2026-11-08).

The owner's rules for ``dynasty_main``: 12 teams, 3 divisions, 7 playoff teams.
The seven best OVERALL records qualify and are seeded 1-7 by overall record;
standings ties are broken by most points scored.  Divisions decide the schedule
and a separate division-champion payout only — no automatic berth, no seeding
advantage, no bye.  Recorded in ``config/leagues/playoff_rules.json``.

CW-49 (2026-11-07) assumed Sleeper's default (every division winner qualifies)
for every league and refused ``dynasty_main`` outright.  These tests pin the
correction with INDEPENDENT oracles — answers computed by hand from the rules,
never by calling the engine twice:

* a division champion with a losing record MISSES the playoffs, and a team that
  does not win its division QUALIFIES (finished season, exact);
* standings ties of any size are broken by Points For, never head-to-head or
  division record (exact);
* division-title odds equal hand enumeration of one remaining week (Monte Carlo
  within tolerance), and are a different number from playoff odds;
* counting division titles leaves every playoff, seed and draft-slot number
  bit-identical;
* the draft-slot forecast is published for a league that plays in divisions.

Host evidence the rule is real: the 2025 ``dynasty_main`` bracket seeded a
four-way 15-11 tie strictly by Points For (rosters 8, 2, 5, 3 at
5567 / 5561 / 5549 / 5381 -> seeds 2-5).
"""

from __future__ import annotations

import json
import random
from types import SimpleNamespace
from unittest import mock

import pytest

from src.public_league import playoff_odds, playoff_structure
from src.public_league.playoff_structure import (
    DIVISION_RULE_RECORDED,
    league_playoff_rules,
    resolve_division_assignments,
    resolve_playoff_structure,
)
from src.ros import playoff_sim

_LEAGUE = "division_rules_test_league"


def _rules_file(tmp_path, *, division_count=2, **overrides):
    entry = {
        "qualification": "overall_record",
        "seeding": "overall_record",
        "standingsTiebreakers": ["points_for"],
        "divisionCount": division_count,
        "divisionPlayoffEffect": "none",
        "divisionPurposes": ["schedule", "champion_payout"],
        "divisionChampion": "best_overall_record_in_division",
        "divisionChampionTiebreakers": ["points_for"],
        "approvedBy": "owner",
        "approvedAt": "2026-11-08",
    }
    entry.update(overrides)
    path = tmp_path / "playoff_rules.json"
    path.write_text(json.dumps({"rules": {_LEAGUE: entry}}), encoding="utf-8")
    return path


class _Registry:
    """Just enough of ``ManagerRegistry`` for ``metrics.resolve_owner``."""

    def __init__(self, by_roster):
        self.by_owner_id = {}
        self.roster_to_owner = {("L1", rid): owner for rid, owner in by_roster.items()}

    def owner_for_roster(self, league_id, roster_id, week=None):  # pragma: no cover - shape only
        return self.roster_to_owner.get((league_id, int(roster_id)), "")


def _snapshot(owners_divisions, *, playoff_teams=2, host_divisions=0, names=None):
    """``owners_divisions``: ``[(owner, division), ...]`` in roster-id order."""
    rosters = [
        {"roster_id": i + 1, "owner_id": owner, "settings": {"division": div}}
        for i, (owner, div) in enumerate(owners_divisions)
    ]
    settings = {
        "playoff_teams": playoff_teams,
        "playoff_seed_type": 1,
        "playoff_week_start": 15,
        "divisions": host_divisions,
    }
    metadata = {f"division_{k}": v for k, v in (names or {}).items()}
    season = SimpleNamespace(
        season="2026",
        league_id="L1",
        league={"settings": settings, "metadata": metadata},
        rosters=rosters,
        matchups_by_week={},
        regular_season_weeks=[],
        num_teams=len(rosters),
    )
    registry = _Registry({i + 1: owner for i, (owner, _div) in enumerate(owners_divisions)})
    return SimpleNamespace(managers=registry, current_season=season, seasons=[season])


def _run(snapshot, rules_path, *, record, pf, schedule, means=None, n=4000, seed=7, draft=False):
    owners = sorted(record)
    means = means or {o: 100.0 for o in owners}
    dists = {
        o: playoff_sim._TeamDist(
            owner_id=o, mean=means[o], sd=12.0, pf_to_date=pf[o], basis="empirical"
        )
        for o in owners
    }
    patches = [
        mock.patch.object(playoff_structure, "_RULES_PATH", rules_path),
        mock.patch.object(
            playoff_sim,
            "_current_standings",
            lambda *a, **k: (record, {"medianGame": False, "state": "not_applicable"}),
        ),
        mock.patch.object(playoff_sim, "_remaining_schedule", lambda *a, **k: list(schedule)),
        mock.patch.object(playoff_sim, "_load_ros_strength_map", lambda *a, **k: {}),
        mock.patch.object(playoff_sim, "_league_best_ball", lambda *a, **k: False),
        mock.patch.object(
            playoff_sim, "_build_team_distributions", lambda *a, **k: (dists, dict(pf))
        ),
        mock.patch.object(playoff_odds, "_final_week_set", lambda *a, **k: set(range(1, 9))),
        mock.patch("src.ros.team_strength.resolve_snapshot_league_key", lambda *a, **k: _LEAGUE),
    ]
    if draft:
        patches.append(
            mock.patch(
                "src.public_league.draft_order.league_draft_order_rule",
                lambda *a, **k: "reverse_record_lower_pf",
            )
        )
    for p in patches:
        p.start()
    try:
        return playoff_sim.simulate_playoff_odds(snapshot, n_simulations=n, rng=random.Random(seed))
    finally:
        for p in patches:
            p.stop()


def _row(out, owner):
    return next(r for r in out["playoffOdds"] if r["ownerId"] == owner)


def _rec(wins, losses):
    return {"wins": wins, "losses": losses, "ties": 0}


# ── the live record ─────────────────────────────────────────────────────


def test_dynasty_main_records_divisions_with_no_playoff_effect():
    rules = league_playoff_rules("dynasty_main")
    assert rules is not None
    assert rules.qualification == "overall_record"
    assert rules.seeding == "overall_record"
    assert rules.standings_tiebreakers == ("points_for",)
    assert rules.division_count == 3
    assert rules.divisions_affect_playoffs is False
    assert rules.division_champion == "best_overall_record_in_division"
    # The payout tiebreaker is NOT confirmed (owner master directive 2026-11-08
    # §11 / §26): a record tie at the top is reported, never resolved.
    assert rules.division_champion_tiebreakers == ()
    assert rules.division_tiebreaker_confirmed is False


@pytest.mark.parametrize("host_divisions", [0, 3, "unreadable"])
def test_dynasty_main_is_never_refused_for_its_divisions(host_divisions):
    season = SimpleNamespace(
        league={
            "settings": {
                "playoff_teams": 7,
                "playoff_seed_type": 1,
                "playoff_week_start": 15,
                "divisions": host_divisions,
            }
        }
    )
    structure = resolve_playoff_structure(season, "dynasty_main")
    assert structure.division_rule == DIVISION_RULE_RECORDED
    assert structure.division_qualification_unknown is False
    assert playoff_sim._division_refusal(structure) is None
    assert structure.teams == 7 and structure.byes == 1


def test_a_league_without_a_record_is_not_given_dynasty_mains_rules():
    assert league_playoff_rules("dynasty_new") is None
    assert league_playoff_rules(None) is None
    season = SimpleNamespace(
        league={"settings": {"playoff_teams": 6, "playoff_seed_type": 0, "divisions": 2}}
    )
    structure = resolve_playoff_structure(season, "dynasty_new")
    assert structure.division_qualification_unknown is True


@pytest.mark.parametrize(
    "override",
    [
        {"qualification": "division_winners_first"},
        {"seeding": "division_winners_top_seeds"},
        {"standingsTiebreakers": ["head_to_head", "points_for"]},
        {"divisionPlayoffEffect": "automatic_berth"},
        {"divisionChampionTiebreakers": ["division_record"]},
        {"divisionCount": 0},
    ],
)
def test_a_record_the_engine_cannot_play_counts_as_no_record(tmp_path, override):
    path = _rules_file(tmp_path, **override)
    assert league_playoff_rules(_LEAGUE, path=path) is None


# ── oracle 1: a division champion gets NO playoff advantage (exact) ────


def test_a_division_champion_can_miss_and_a_non_champion_can_qualify(tmp_path):
    """Finished season, 4 teams, 2 divisions, 2 playoff spots.

    Division 1 {a, b}: a 7-1, b 6-2.  Division 2 {c, d}: c 2-6, d 1-7.
    By hand: the two best OVERALL records qualify -> a and b.  Division
    champions -> a (div 1) and c (div 2).  So c wins its division and misses
    the playoffs; b qualifies without winning its division.  Under Sleeper's
    default (every division winner qualifies) c would be in and b out — the
    advantage this league does not grant.
    """
    snap = _snapshot([("a", 1), ("b", 1), ("c", 2), ("d", 2)])
    record = {"a": _rec(7, 1), "b": _rec(6, 2), "c": _rec(2, 6), "d": _rec(1, 7)}
    pf = {"a": 900.0, "b": 880.0, "c": 700.0, "d": 650.0}
    out = _run(snap, _rules_file(tmp_path), record=record, pf=pf, schedule=[], n=200)
    assert "unsimulable" not in out
    assert out["divisionOdds"]["state"] == "available"
    expected = {
        #     playoff, division title
        "a": (1.0, 1.0),
        "b": (1.0, 0.0),
        "c": (0.0, 1.0),
        "d": (0.0, 0.0),
    }
    for owner, (playoff, title) in expected.items():
        row = _row(out, owner)
        assert row["playoffOdds"] == playoff, owner
        assert row["divisionChampionOdds"] == title, owner
    assert _row(out, "c")["seedDistribution"][2] == 1.0  # seeded on record: 3rd
    assert _row(out, "b")["seedDistribution"][1] == 1.0


# ── oracle 2: ties of any size go to Points For (exact) ────────────────


def test_a_three_way_record_tie_is_seeded_strictly_by_points_for(tmp_path):
    """Finished season, 4 teams.  b, c and d all 5-3; a 3-5.  PF: c 950 >
    d 940 > b 930.  By hand: seeds c, d, b, a — no head-to-head, no division
    record.  With 2 spots: c and d qualify, b misses on PF alone.  Division
    1 {a, b}: b (better record).  Division 2 {c, d}: c (tied record, more PF).
    """
    snap = _snapshot([("a", 1), ("b", 1), ("c", 2), ("d", 2)])
    record = {"a": _rec(3, 5), "b": _rec(5, 3), "c": _rec(5, 3), "d": _rec(5, 3)}
    pf = {"a": 990.0, "b": 930.0, "c": 950.0, "d": 940.0}
    out = _run(snap, _rules_file(tmp_path), record=record, pf=pf, schedule=[], n=200)
    seeds = {r["ownerId"]: r["seedDistribution"].index(1.0) + 1 for r in out["playoffOdds"]}
    assert seeds == {"c": 1, "d": 2, "b": 3, "a": 4}
    assert {r["ownerId"]: r["playoffOdds"] for r in out["playoffOdds"]} == {
        "c": 1.0,
        "d": 1.0,
        "b": 0.0,
        "a": 0.0,
    }
    titles = {r["ownerId"]: r["divisionChampionOdds"] for r in out["playoffOdds"]}
    assert titles == {"a": 0.0, "b": 1.0, "c": 1.0, "d": 0.0}


# ── oracle 3: one remaining week, enumerated by hand ───────────────────


def test_division_title_odds_match_hand_enumeration(tmp_path):
    """All four teams 4-4; week 9 pairs a v c and b v d (cross-division),
    every team the same distribution, so each game is an independent 50/50.
    Points For to date are 10,000 apart, so one week's score never reorders
    them: PF order d > c > b > a decides every record tie.

    By hand (four equally likely outcomes):
      * playoffs (2 spots): exactly the two game winners finish 5-4 -> every
        team 1/2.
      * division 1 {a, b}: a wins it only when a wins AND b loses -> 1/4;
        b otherwise (both win or both lose ties to b on PF) -> 3/4.
      * division 2 {c, d}: c only when c wins and d loses -> 1/4; d -> 3/4.
    """
    snap = _snapshot([("a", 1), ("b", 1), ("c", 2), ("d", 2)])
    record = {o: _rec(4, 4) for o in "abcd"}
    pf = {"a": 10_000.0, "b": 20_000.0, "c": 30_000.0, "d": 40_000.0}
    out = _run(
        snap,
        _rules_file(tmp_path),
        record=record,
        pf=pf,
        schedule=[(9, "a", "c"), (9, "b", "d")],
        n=20_000,
        seed=11,
    )
    tol = 0.015  # ~4.5 standard errors at n = 20,000
    for owner in "abcd":
        assert _row(out, owner)["playoffOdds"] == pytest.approx(0.5, abs=tol)
    for owner, title in {"a": 0.25, "b": 0.75, "c": 0.25, "d": 0.75}.items():
        assert _row(out, owner)["divisionChampionOdds"] == pytest.approx(title, abs=tol)
    # Each division crowns exactly one champion per simulation (published
    # odds are rounded to 4 places, so a two-team sum may be 1e-4 off).
    by_div: dict[int, float] = {}
    for r in out["playoffOdds"]:
        by_div[r["division"]] = by_div.get(r["division"], 0.0) + r["divisionChampionOdds"]
    assert by_div == {1: pytest.approx(1.0, abs=2e-4), 2: pytest.approx(1.0, abs=2e-4)}


# ── titles are counted without disturbing anything else ────────────────


def test_counting_division_titles_leaves_every_other_number_bit_identical(tmp_path):
    record = {o: _rec(4, 4) for o in "abcd"}
    pf = {"a": 900.0, "b": 910.0, "c": 905.0, "d": 920.0}
    means = {"a": 100.0, "b": 104.0, "c": 98.0, "d": 102.0}
    schedule = [(9, "a", "b"), (9, "c", "d"), (10, "a", "c"), (10, "b", "d")]
    with_divisions = _run(
        _snapshot([("a", 1), ("b", 1), ("c", 2), ("d", 2)]),
        _rules_file(tmp_path),
        record=record,
        pf=pf,
        schedule=schedule,
        means=means,
        draft=True,
    )
    # Same league, no division assignments on the rosters: titles unavailable.
    without = _run(
        _snapshot([("a", None), ("b", None), ("c", None), ("d", None)]),
        _rules_file(tmp_path),
        record=record,
        pf=pf,
        schedule=schedule,
        means=means,
        draft=True,
    )
    assert without["divisionOdds"]["reason"] == "roster_division_missing_or_out_of_range"
    division_keys = {
        "division",
        "divisionName",
        "divisionChampionOdds",
        "divisionChampionOddsCi",
        "divisionTitleBasis",
        "divisionTitleTieOdds",
    }
    strip = [
        {k: v for k, v in r.items() if k not in division_keys}
        for r in with_divisions["playoffOdds"]
    ]
    assert strip == without["playoffOdds"]
    assert all("draftSlotDistribution" in r for r in strip)


# ── the draft-slot forecast survives divisions ─────────────────────────


def test_a_recorded_league_with_divisions_on_publishes_playoff_and_draft_slot_odds(tmp_path):
    snap = _snapshot([("a", 1), ("b", 1), ("c", 2), ("d", 2)], host_divisions=2)
    record = {o: _rec(4, 4) for o in "abcd"}
    pf = {o: 900.0 + i for i, o in enumerate("abcd")}
    out = _run(
        snap,
        _rules_file(tmp_path),
        record=record,
        pf=pf,
        schedule=[(9, "a", "b"), (9, "c", "d")],
        draft=True,
        n=1000,
    )
    assert "unsimulable" not in out
    assert sum(r["playoffOdds"] for r in out["playoffOdds"]) == pytest.approx(2.0, abs=1e-9)
    for r in out["playoffOdds"]:
        assert sum(r["draftSlotDistribution"]) == pytest.approx(1.0, abs=1e-9)
    assert out["playoffStructure"]["divisionRule"] == DIVISION_RULE_RECORDED


def test_an_unrecorded_league_still_publishes_its_draft_order_to_the_pick_consumers(tmp_path):
    """Qualifying is withheld, the draft order is not: both draft-slot
    consumers read the regular-season rows through ``draft_slot_rows``."""
    snap = _snapshot([("a", 1), ("b", 1), ("c", 2), ("d", 2)], host_divisions=2)
    record = {o: _rec(4, 4) for o in "abcd"}
    pf = {o: 900.0 + i for i, o in enumerate("abcd")}
    no_record = tmp_path / "none.json"
    no_record.write_text(json.dumps({"rules": {}}), encoding="utf-8")
    out = _run(
        snap, no_record, record=record, pf=pf, schedule=[(9, "a", "b"), (9, "c", "d")], draft=True
    )
    assert out["playoffOdds"] == []
    assert out["unsimulable"]["scope"] == "qualification"
    assert playoff_sim.run_stopping_refusal(out) is None
    rows = playoff_sim.draft_slot_rows(out)
    assert {r["ownerId"] for r in rows} == set("abcd")
    for r in rows:
        assert sum(r["draftSlotDistribution"]) == pytest.approx(1.0, abs=1e-9)

    from src.ros import pick_projection

    teams = [{"roster_id": i + 1, "ownerId": o, "name": f"Team {o}"} for i, o in enumerate("abcd")]
    projected, draft_year, reason, _ = pick_projection.rule_slot_forecasts(
        out, teams, league_rule="reverse_record_lower_pf", rule_known=True
    )
    assert reason is None
    assert draft_year == 2027
    assert sorted(r["projectedSlot"] for r in projected) == [1, 2, 3, 4]

    from src.trade import pick_market

    contract = {"sleeper": {"teams": teams}}
    forecasts = pick_market.owned_pick_forecasts(out, contract)
    assert set(forecasts) == {1, 2, 3, 4}


def test_a_run_stopping_refusal_is_still_a_stop():
    assert playoff_sim.run_stopping_refusal({"unsimulable": {"reason": "x"}}) == {"reason": "x"}
    assert (
        playoff_sim.draft_slot_rows({"unsimulable": {"reason": "x"}, "regularSeasonOdds": [{}]})
        == []
    )


# ── division assignments fail closed ───────────────────────────────────


def _structure(tmp_path, host_divisions=0, **override):
    season = SimpleNamespace(
        league={
            "settings": {"playoff_teams": 2, "playoff_seed_type": 1, "divisions": host_divisions}
        }
    )
    with mock.patch.object(playoff_structure, "_RULES_PATH", _rules_file(tmp_path, **override)):
        return resolve_playoff_structure(season, _LEAGUE)


def test_division_names_come_from_the_league_metadata(tmp_path):
    snap = _snapshot([("a", 1), ("b", 2)], names={1: "The Pit", 2: "Barbacoa"})
    assign = resolve_division_assignments(
        snap.current_season, _structure(tmp_path), lambda rid: {1: "a", 2: "b"}[rid]
    )
    assert assign.available
    assert assign.by_owner == {"a": 1, "b": 2}
    assert assign.to_dict()["names"] == {"1": "The Pit", "2": "Barbacoa"}


@pytest.mark.parametrize(
    "assignments, host_divisions, reason",
    [
        ([("a", 1), ("b", None)], 0, "roster_division_missing_or_out_of_range"),
        ([("a", 1), ("b", 3)], 0, "roster_division_missing_or_out_of_range"),
        ([("a", 1), ("b", 1)], 0, "division_has_no_teams"),
        ([("a", 1), ("b", 2)], 3, "division_count_conflicts_with_host_setting"),
    ],
)
def test_division_assignments_fail_closed(tmp_path, assignments, host_divisions, reason):
    snap = _snapshot(assignments)
    owners = {i + 1: o for i, (o, _d) in enumerate(assignments)}
    assign = resolve_division_assignments(
        snap.current_season, _structure(tmp_path, host_divisions), owners.get
    )
    assert assign.state == "unavailable"
    assert assign.reason == reason


def test_a_league_without_divisions_has_no_division_odds(tmp_path):
    season = SimpleNamespace(league={"settings": {"playoff_teams": 2, "playoff_seed_type": 1}})
    structure = resolve_playoff_structure(season, None)
    assign = resolve_division_assignments(season, structure, lambda rid: "")
    assert assign.state == "not_applicable"


# ── an UNCONFIRMED title tiebreaker: ties reported, never resolved ─────


def test_unconfirmed_tiebreaker_reports_ties_instead_of_resolving_them(tmp_path):
    """Same one-week league as the enumeration oracle, but the record leaves
    the division-title tiebreaker unconfirmed.  By hand (four equally likely
    outcomes; Points For to date must NOT decide anything now):

      * division 1 {a, b}: a outright only when a wins and b loses -> 1/4;
        b outright only when b wins and a loses -> 1/4; tied at the top
        (both win or both lose) -> 1/2, for a AND for b.
      * division 2 {c, d}: the same, 1/4 / 1/4 / 1/2.
      * playoff odds are untouched by the division rule: 1/2 each.
    """
    snap = _snapshot([("a", 1), ("b", 1), ("c", 2), ("d", 2)])
    record = {o: _rec(4, 4) for o in "abcd"}
    pf = {"a": 10_000.0, "b": 20_000.0, "c": 30_000.0, "d": 40_000.0}
    rules = _rules_file(tmp_path, divisionChampionTiebreakers=[])
    out = _run(
        snap,
        rules,
        record=record,
        pf=pf,
        schedule=[(9, "a", "c"), (9, "b", "d")],
        n=20_000,
        seed=11,
    )
    tol = 0.015
    assert out["divisionOdds"]["championRule"]["tiebreakerStatus"] == "unconfirmed"
    assert out["divisionOdds"]["championRule"]["tiebreakers"] == []
    for owner in "abcd":
        row = _row(out, owner)
        assert row["divisionTitleBasis"] == "outright_only"
        assert row["divisionChampionOdds"] == pytest.approx(0.25, abs=tol)
        assert row["divisionTitleTieOdds"] == pytest.approx(0.5, abs=tol)
        assert row["playoffOdds"] == pytest.approx(0.5, abs=tol)
    # Outright titles plus the tied seasons cover every season exactly once per
    # division: P(a out) + P(b out) + P(tie) = 1 (each tie counted once).
    for x, y in (("a", "b"), ("c", "d")):
        rx, ry = _row(out, x), _row(out, y)
        total = rx["divisionChampionOdds"] + ry["divisionChampionOdds"] + rx["divisionTitleTieOdds"]
        assert total == pytest.approx(1.0, abs=2e-4)


def test_a_confirmed_tiebreaker_still_resolves_ties_and_carries_no_tie_field(tmp_path):
    snap = _snapshot([("a", 1), ("b", 1), ("c", 2), ("d", 2)])
    record = {o: _rec(4, 4) for o in "abcd"}
    pf = {"a": 10_000.0, "b": 20_000.0, "c": 30_000.0, "d": 40_000.0}
    out = _run(snap, _rules_file(tmp_path), record=record, pf=pf, schedule=[], n=200)
    for owner in "abcd":
        row = _row(out, owner)
        assert row["divisionTitleBasis"] == "tiebreaker_applied"
        assert "divisionTitleTieOdds" not in row
    assert out["divisionOdds"]["championRule"]["tiebreakerStatus"] == "confirmed"


def test_a_finished_season_with_a_division_tie_names_no_champion(tmp_path):
    """Finished season, division 1 tied 5-3 / 5-3: with the tiebreaker
    unconfirmed neither team is the division champion (0 outright, 1.0 tied);
    division 2 has a clear winner."""
    snap = _snapshot([("a", 1), ("b", 1), ("c", 2), ("d", 2)])
    record = {"a": _rec(5, 3), "b": _rec(5, 3), "c": _rec(6, 2), "d": _rec(2, 6)}
    pf = {"a": 900.0, "b": 950.0, "c": 800.0, "d": 700.0}
    rules = _rules_file(tmp_path, divisionChampionTiebreakers=[])
    out = _run(snap, rules, record=record, pf=pf, schedule=[], n=200)
    assert (_row(out, "a")["divisionChampionOdds"], _row(out, "a")["divisionTitleTieOdds"]) == (
        0.0,
        1.0,
    )
    assert (_row(out, "b")["divisionChampionOdds"], _row(out, "b")["divisionTitleTieOdds"]) == (
        0.0,
        1.0,
    )
    assert (_row(out, "c")["divisionChampionOdds"], _row(out, "c")["divisionTitleTieOdds"]) == (
        1.0,
        0.0,
    )


def test_the_draft_order_record_basis_is_marked_provisional(tmp_path):
    snap = _snapshot([("a", 1), ("b", 1), ("c", 2), ("d", 2)])
    record = {o: _rec(4, 4) for o in "abcd"}
    pf = {o: 900.0 + i for i, o in enumerate("abcd")}
    out = _run(snap, _rules_file(tmp_path), record=record, pf=pf, schedule=[], n=200, draft=True)
    assert out["draftOrderRecordBasis"] == "head_to_head_with_half_win_ties"
    assert out["draftOrderRecordBasisState"] == "provisional_median_game_counting_unresolved"
