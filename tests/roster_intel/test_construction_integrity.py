"""Roster Construction V1 integrity on REAL host data: dynasty_main 2026, weeks 1-7.

``fixtures/dynasty_main_2026_w1_7.json`` is the league's own Sleeper record for
its seven finalized 2026 weeks (matchup fields only: every roster's
``players`` / ``players_points`` / awarded ``starters`` / ``points``) plus the
host directory's ``position`` / ``fantasy_positions``.  It runs through the
production path (snapshot -> ``season_input_from_snapshot`` ->
``compute_league_season``), so these pin owner decision D1 (2026-11-01) on the
host's own answers, not on lineups our solver produced:

* every finalized team-week reproduces the host's awarded points;
* the recomputed lineup IS the host's awarded lineup (same players);
* each real starter is attributed exactly once, to his own position family —
  FLEX / SUPER_FLEX starts included;
* the league's real rules: 2 TE slots, 9 IDP slots, K only in K;
* ownership follows the week-by-week rosters (real mid-season moves);
* optimal starts, the counterfactual and dynasty value stay separate concepts.

Evidence: ``docs/roster_construction/evidence/PARITY_CENSUS_2026-11-01.md``.
"""

from __future__ import annotations

import copy
import json
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from src.api import roster_construction_api as api
from src.public_league.identity import ManagerRegistry
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot
from src.roster_intel import construction as rc
from src.ros.lineup import lineup_position, slot_eligible_positions

FIX = Path(__file__).resolve().parent / "fixtures" / "dynasty_main_2026_w1_7.json"
IDP = ("DL", "LB", "DB")


def _snapshot(raw: dict) -> PublicLeagueSnapshot:
    league = dict(raw["league"])
    league["league_id"] = "RC2026REAL"
    weeks = {int(w): rows for w, rows in raw["matchupsByWeek"].items()}
    rids = sorted({r["roster_id"] for rows in weeks.values() for r in rows})
    season = SeasonSnapshot(
        season="2026",
        league_id="RC2026REAL",
        league=league,
        users=[],
        rosters=[{"roster_id": rid, "owner_id": "", "players": []} for rid in rids],
        matchups_by_week=weeks,
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )
    return PublicLeagueSnapshot(
        root_league_id="RC2026REAL",
        generated_at="2026-11-01T15:23:27+00:00",
        seasons=[season],
        managers=ManagerRegistry(),
        nfl_players=raw["players"],
    )


@pytest.fixture(scope="module")
def raw():
    return json.loads(FIX.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ls(raw):
    snap = _snapshot(raw)
    si = api.season_input_from_snapshot(snap, snap.seasons[0])
    return rc.compute_league_season(si, api.load_priors())


def _host(raw, wk, rid):
    return next(r for r in raw["matchupsByWeek"][str(wk)] if r["roster_id"] == rid)


def test_fixture_is_the_full_finalized_league(ls):
    assert ls.included_weeks == list(range(1, 8))
    assert ls.team_ids == list(range(1, 13))
    assert ls.si.lineup_mode == rc.LINEUP_BEST_BALL
    assert ls.si.contradicted == {}
    assert api.lineup_config_status(ls.si, is_current=True) == {"available": True, "reason": None}


def test_every_team_week_reproduces_the_host_score(ls, raw):
    for wk in ls.included_weeks:
        for rid, sol in ls.solutions[wk].items():
            assert sol.valid and sol.parity == rc.PARITY_REPRODUCED, (wk, rid, sol.reason)
            assert sol.unobserved == ()
            assert sol.score == pytest.approx(_host(raw, wk, rid)["points"], abs=0.011)


def test_recomputed_lineup_is_the_host_awarded_lineup(ls, raw):
    """Ties (two 0-point TEs; a 1.33-point DL vs a 1.33-point LB) follow the
    host, and a slot the host left EMPTY stays empty (a 0-point player who did
    not play is not credited a start)."""
    for wk in ls.included_weeks:
        for rid, sol in ls.solutions[wk].items():
            host = [p for p in _host(raw, wk, rid)["starters"] if p and p != "0"]
            assert sol.assigned_ids == frozenset(host), (wk, rid)
    # The two measured shapes, pinned explicitly.
    w5r3 = {pid for _i, _s, pid, _p in ls.solutions[5][3].assigned}
    assert "13366" in w5r3 and "12648" not in w5r3  # host's DL, not the tied LB
    assert "LB" not in [s for _i, s, pid, _p in ls.solutions[5][3].assigned if pid == "13366"]
    assert ls.solutions[4][7].unfilled_slots == ["WR"]  # host left WR3 empty
    assert "13477" not in ls.solutions[4][7].assigned_ids


def test_each_starter_attributed_once_to_his_own_position(ls):
    for wk in ls.included_weeks:
        for sol in ls.solutions[wk].values():
            ids = [pid for _i, _s, pid, _p in sol.assigned]
            assert len(ids) == len(set(ids)) and set(ids) <= set(sol.roster)
    for rid in ls.team_ids:
        prod = ls.production[rid]
        lineups = sum(ls.solutions[wk][rid].score for wk in ls.included_weeks)
        assert sum(prod[g]["points"] for g in ls.groups) == pytest.approx(lineups, abs=0.05)
        starts = sum(prod[g]["appearances"] for g in ls.groups)
        filled = sum(len(ls.solutions[wk][rid].assigned) for wk in ls.included_weeks)
        assert starts == filled  # no start counted twice, none dropped
        for g in ls.groups:
            for c in prod[g]["topContributors"]:
                assert rc.group_of(ls.si.players[c["playerId"]]) == g


def test_flex_and_superflex_starts_are_credited_to_the_real_position(ls):
    seen = Counter()
    for wk in ls.included_weeks:
        for sol in ls.solutions[wk].values():
            for _i, slot, pid, _p in sol.assigned:
                if slot in ("FLEX", "SUPER_FLEX"):
                    g = rc.group_of(ls.si.players[pid])
                    assert g in {lineup_position(p) for p in slot_eligible_positions(slot)}
                    seen[(slot, g)] += 1
    assert seen[("FLEX", "WR")] and seen[("SUPER_FLEX", "QB")]
    # The slot allocation table books those starts under the player's OWN
    # group, whatever slot seated him: an IDP group may hold another IDP slot a
    # host-listed hybrid (DL/LB) fills, and the two-way CB (Sleeper
    # fantasy_positions DB+WR) started at WR stays DB production, his host
    # position — never re-attributed to the slot's family.
    for rid in ls.team_ids:
        for g, row in ls.production[rid].items():
            for slot in row["slotAllocation"]:
                if slot in (g, "FLEX", "SUPER_FLEX") or (g in IDP and slot in IDP):
                    continue
                assert (g, slot) == ("DB", "WR"), (rid, g, slot)


def test_real_slot_rules_two_te_nine_idp_and_k(ls):
    slots = list(ls.si.slots)
    assert Counter(slots)["TE"] == 2
    assert sum(Counter(slots)[s] for s in IDP) == 9
    assert Counter(slots)["K"] == 1 and "K" not in slot_eligible_positions("FLEX")
    assert set(ls.groups) == {"QB", "RB", "WR", "TE", "K", "DL", "LB", "DB"}
    for wk in ls.included_weeks:
        for sol in ls.solutions[wk].values():
            per = Counter(s for _i, s, _pid, _p in sol.assigned)
            assert per["TE"] <= 2 and per["K"] <= 1
            for _i, slot, pid, _p in sol.assigned:
                meta = ls.si.players[pid]
                if slot == "K":
                    assert rc.group_of(meta) == "K"
                if slot in IDP:
                    # Family or a host-listed hybrid (DL/LB, DB/LB) — never an offense player.
                    fams = {lineup_position(p) for p in meta.fantasy_positions} | {
                        rc.group_of(meta)
                    }
                    assert slot in fams


def test_ownership_follows_week_by_week_rosters(ls, raw):
    owner: dict[str, dict[int, int]] = defaultdict(dict)
    for wk, rows in raw["matchupsByWeek"].items():
        for r in rows:
            for p in r["players"]:
                owner[p][int(wk)] = r["roster_id"]
    moved = {p: w for p, w in owner.items() if len(set(w.values())) > 1}
    assert len(moved) >= 50  # a real season of trades and waiver moves
    for pid, weeks in sorted(moved.items())[:40]:
        for rid in set(weeks.values()):
            led = rc.player_ledger(ls, rid, pid)
            held = sorted(w for w, r in weeks.items() if r == rid)
            assert led["ownedWeeks"] == len(held)
            spells = [
                w for s in led["ownershipSpells"] for w in range(s["fromWeek"], s["toWeek"] + 1)
            ]
            assert spells == held
            assert led["starts"]["of"] <= led["ownedWeeks"]
            # Points only ever count for the team that held him that week.
            booked = sum(
                p for wk in held for _i, _s, x, p in ls.solutions[wk][rid].assigned if x == pid
            )
            assert led["startedPoints"] == pytest.approx(booked, abs=0.011)
    # 11566 (QB): roster 1 weeks 1-2, roster 7 weeks 3-7.
    assert rc.player_ledger(ls, 1, "11566")["ownedWeeks"] == 2
    assert rc.player_ledger(ls, 7, "11566")["ownedWeeks"] == 5


def test_optimal_starts_and_counterfactual_are_separate_concepts(ls):
    rid = 7
    end_roster = ls.solutions[7][rid].roster
    hypo, meta = rc.hypothetical_starts(ls, rid, end_roster)
    assert meta["scenario"] == rc.SCENARIO_END_ROSTER and meta["expost"] is True
    differs = 0
    for pid in end_roster:
        led = rc.player_ledger(ls, rid, pid)
        h = hypo[pid]
        assert h["of"] <= len(ls.included_weeks)
        differs += int(h["of"] != led["starts"]["of"] or h["value"] != led["starts"]["value"])
    assert differs  # the counterfactual is not the realized ledger relabelled


def test_dynasty_value_is_independent_of_historical_production(ls):
    rosters = {rid: list(ls.solutions[7][rid].roster) for rid in ls.team_ids}
    pos = {p: ls.si.players[p].position for r in rosters.values() for p in r}
    values = {p: 1000.0 + i for i, p in enumerate(sorted(pos))}
    from tests.roster_intel.rc_support import make_contract

    contract = make_contract("k", rosters, values, pos)
    before = copy.deepcopy(contract)
    block = rc.positional_value(api.value_input_from_contract(contract, "k"), ls.groups)
    # Each position's value is exactly the sum of its players' canonical
    # values — nothing from lineups, starts or points enters it.
    for rid, players in rosters.items():
        for g in ls.groups:
            want = sum(values[p] for p in players if lineup_position(pos[p]) == g)
            assert block["perTeam"][rid][g]["total"] == pytest.approx(want, abs=0.01)
    # And the production side is unaffected by value: the same league-season
    # yields identical production with or without a contract.
    assert contract == before  # read only: rankDerivedValue never written back
    view_a = rc.build_team_view(ls, 7, api.value_input_from_contract(contract, "k"), posture=None)
    view_b = rc.build_team_view(ls, 7, rc.ValueInput(available=False, reason="x"), posture=None)
    assert [p["production"] for p in view_a["positions"]] == [
        p["production"] for p in view_b["positions"]
    ]
