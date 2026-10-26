"""Lane D (best-ball volatility by archetype): engine, definitions and evidence integrity.

Research only.  What is pinned here, in the order a reviewer would ask:

1. the vectorized lineup solver is the owner's solver (``src.ros.lineup``) on the same weeks;
2. eligibility, fine positions and archetypes come from provenance and never from performance;
3. a missing week is never a zero score (bye excluded, DNP a real zero, no-appearance unknown);
4. the maths has the properties the argument rests on (Jensen gap >= 0, a sure starter has none,
   volatile beats stable only where the cut line is near, the deterministic limit equals the owner);
5. the committed evidence file is internally consistent, carries no manager / team identity, and the
   write-up quotes the same numbers;
6. nothing in production imports this lane, and the lane imports nothing it must not.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import numpy as np
import pytest

from scripts.idp_accuracy import d_data as D
from scripts.idp_accuracy import d_engine as E
from scripts.idp_accuracy import d_report as R
from scripts.idp_accuracy import d_study as S
from src.ros.lineup import (
    OBJECTIVE_REALIZED_POINTS,
    RosterPlayer,
    solve_optimal_assignment,
)

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / "docs/valuation/idp_accuracy/evidence/bestball_archetypes.json"
DOC = REPO / "docs/valuation/idp_accuracy/D_BESTBALL.md"

SLOTS = [
    "QB", "RB", "RB", "WR", "WR", "WR", "TE", "TE", "FLEX", "FLEX", "SUPER_FLEX", "K",
    "DL", "DL", "DL", "LB", "LB", "LB", "DB", "DB", "DB",
]  # fmt: skip


def _entity(pid, pos, fps, played, n_games=None, *, arch=None, bye=None, team="AAA"):
    sig = E.signature_for(pid, pos, fps, SLOTS)
    played = np.asarray(played, float)
    return E.Entity(
        pid=pid,
        name=pid,
        lpos=pos,
        sub=E.subproblem_of(sig) or "off",
        sig=sig,
        arch=arch or pos,
        fine=pos,
        team=team,
        bye_week=bye,
        played=played,
        n_games=len(played) if n_games is None else n_games,
    )


def _shape():
    z = np.ones(300)
    return E.ShapeReference({"POS_DL": z, "POS_LB": z, "POS_DB": z}, {"POS_DL": 0.5}, {}, None)


# ── 1. the solver is the owner's solver ──────────────────────────────────────


def _pool_spec():
    spec = []
    spec += [("QB", ["QB"])] * 3 + [("RB", ["RB"])] * 9 + [("WR", ["WR"])] * 10
    spec += [("TE", ["TE"])] * 5 + [("K", ["K"])] * 2
    spec += [("DL", ["DL"])] * 6 + [("DL", ["DL", "LB"])] * 3
    spec += [("LB", ["LB"])] * 5 + [("LB", ["DL", "LB"])] * 2
    spec += [("DB", ["DB"])] * 5 + [("DB", ["DB", "LB"])] * 2
    return spec


def test_vectorized_solver_equals_the_owner_solver_week_by_week():
    spec = _pool_spec()
    players = [
        RosterPlayer(
            player_id=f"p{i}",
            canonical_name=f"p{i}",
            position=pos,
            ros_value=0.0,
            fantasy_positions=tuple(fp),
        )
        for i, (pos, fp) in enumerate(spec)
    ]
    sigs = [E.signature_for(p.player_id, p.position, p.fantasy_positions, SLOTS) for p in players]
    subs = [E.subproblem_of(s) for s in sigs]
    off, idp = E.split_slots(SLOTS)
    solvers = {
        "off": E.LineupSolver(off, [s for s, u in zip(sigs, subs) if u == "off"]),
        "idp": E.LineupSolver(idp, [s for s, u in zip(sigs, subs) if u == "idp"]),
    }
    rng = np.random.default_rng(7)
    X = rng.gamma(2.0, 4.0, size=(120, len(players))) - rng.random((120, len(players))) * 3.0
    X[rng.random(X.shape) < 0.15] = 0.0  # DNP-style zeros, plus negatives from the shift
    for d in range(X.shape[0]):
        pool = [
            RosterPlayer(
                player_id=p.player_id,
                canonical_name=p.canonical_name,
                position=p.position,
                ros_value=float(X[d, i]),
                fantasy_positions=p.fantasy_positions,
            )
            for i, p in enumerate(players)
        ]
        owner = sum(
            p.ros_value
            for p in solve_optimal_assignment(
                pool, SLOTS, objective=OBJECTIVE_REALIZED_POINTS
            ).values()
        )
        mine = 0.0
        for sub in ("off", "idp"):
            cols = [i for i, u in enumerate(subs) if u == sub]
            tid = np.array([solvers[sub].type_id[sigs[i]] for i in cols])
            mine += solvers[sub].solve(X[d : d + 1, cols], tid)[0]
        assert mine == pytest.approx(owner, abs=1e-9), d


def test_solver_batches_many_weeks_at_once_identically():
    sigs = [frozenset({"DL"}), frozenset({"LB"}), frozenset({"DL", "LB"})]
    idp = ["DL", "DL", "DL", "LB", "LB", "LB"]
    solver = E.LineupSolver(idp, sigs)
    rng = np.random.default_rng(3)
    X = rng.random((50, 9)) * 20
    tid = np.array([solver.type_id[sigs[i % 3]] for i in range(9)])
    batch = solver.solve(X, tid)
    single = np.array([solver.solve(X[d : d + 1], tid)[0] for d in range(50)])
    assert np.allclose(batch, single)


def test_solver_fills_a_fillable_slot_even_with_a_negative_score_and_leaves_unfillable_ones_empty():
    solver = E.LineupSolver(["DL", "DL"], [frozenset({"DL"})])
    tid = np.array([0, 0, 0])
    # two slots, three players; the owner's best-ball basis takes the best TWO, signs included
    assert solver.solve(np.array([[-1.0, -2.0, -3.0]]), tid)[0] == pytest.approx(-3.0)
    # a single player cannot fill the second slot: it stays empty (0), it is not invented
    assert solver.solve(np.array([[5.0]]), np.array([0]))[0] == pytest.approx(5.0)
    assert solver.solve(np.zeros((4, 0)), np.array([], dtype=int)).tolist() == [0.0] * 4


def test_eligibility_comes_from_the_owner_not_a_private_table():
    assert E.signature_for("a", "DL", ["DL", "LB"], SLOTS) == frozenset({"DL", "LB"})
    assert E.signature_for("b", "RB", ["RB"], SLOTS) == frozenset({"RB", "FLEX", "SUPER_FLEX"})
    assert E.signature_for("c", "QB", ["QB"], SLOTS) == frozenset({"QB", "SUPER_FLEX"})
    assert E.signature_for("d", "K", ["K"], SLOTS) == frozenset({"K"})
    assert E.signature_for("e", "OL", ["OL"], SLOTS) == frozenset()  # not lineup eligible
    # a two-way DB/WR spans both sub-problems: out of scope, reported, not silently half-solved
    assert E.subproblem_of(E.signature_for("f", "DB", ["DB", "WR"], SLOTS)) is None
    assert E.subproblem_of(frozenset()) is None


def test_engine_reproduces_the_best_ball_library_within_its_monte_carlo_error():
    """Same data, same Gaussian weekly model, two independent implementations of the marginal.

    ``src.bestball.marginal`` (one scalar lineup solve per simulated week) and this lane's vectorized
    engine are fed the library's own synthetic roster, free-agent pool and ``PointsModel`` draw rule
    (``max(0, N(mean, max(0.5, mean * cv)))``).  The library publishes the Monte-Carlo standard error
    of each estimate; every difference must sit inside it.  Selection of the replacement is the
    library's rule (rank-1 free agent per opened slot family, best re-solve wins).
    """
    from src.bestball import marginal as lib
    from src.bestball.params import load_marginal_params, with_overrides
    from src.bestball.replacement import waiver_candidates
    from src.league_intel.sim_calibration import PointsModel
    from src.roster_intel import best_ball_utility as bbu
    from tests.fixtures.bestball.synthetic_league import (
        SEASON,
        build_league,
        ppg_lookup_for,
        roster_for,
        rostered_ids,
    )

    league = build_league()
    params = with_overrides(load_marginal_params(), draws=300)
    pool = waiver_candidates(
        league["contract"], rostered_ids(league), season=SEASON, scoring_settings={},
        params=params, ppg_lookup=ppg_lookup_for(league["ppg"]),
    )  # fmt: skip
    roster = roster_for(league, 0)
    pm = PointsModel()
    bbu.clear_before_side_cache()
    res = lib.marginal_bestball_utility_for_roster(
        roster, league["slots"], waiver_pool=pool, params=params, max_players=16,
        points_model=pm, owner_id="t0",
    )  # fmt: skip
    theirs = {e.player_id: e for e in res.entries if e.delta_ppg is not None}
    assert len(theirs) >= 12

    by_id = {r["playerId"]: r for r in league["contract"]["playersArray"] if r.get("playerId")}
    fa_ids = [c.player_id for c in pool.candidates]
    roster_ids = [p.player_id for p in roster]
    ents = []
    for pid in dict.fromkeys(roster_ids + fa_ids):
        pos = by_id[pid]["position"]
        sig = E.signature_for(pid, pos, [pos], league["slots"])
        ents.append(_entity(pid, pos, [pos], [league["ppg"][pid]] * 4))
        assert ents[-1].sig == sig
    n = 6000
    rng = np.random.default_rng(5)
    X = np.zeros((n, len(ents)))
    for i, e in enumerate(ents):
        sd = max(0.5, e.mu_cond * pm.cv_for(e.lpos))
        X[:, i] = np.maximum(0.0, rng.normal(e.mu_cond, sd, size=n))
    sc = E.Scenario(draws=n, deltas=(), cand_ranks=(1,), repl_mode="best")
    ds = E.DrawSet.from_matrix(ents, X, sc)
    pools = E.build_pools(ents, [roster_ids], set(fa_ids), league["slots"], set())
    idx = {e.pid: i for i, e in enumerate(ents)}
    out = E.evaluate_marginals(ds, pools, [idx[p] for p in theirs], {idx[p]: 0 for p in roster_ids})
    zs = []
    for pid, e in theirs.items():
        mine = out[idx[pid]].base_with
        se = float(np.hypot(e.mc_standard_error or 0.0, mine.std(ddof=1) / np.sqrt(n)))
        zs.append((float(mine.mean()) - e.delta_ppg) / max(se, 1e-9))
    zs = np.array(zs)
    assert np.abs(zs).max() < 4.0, zs
    assert abs(zs.mean()) < 0.8, zs  # no systematic offset between the two implementations


# ── 2. fine positions and archetypes are provenance, not performance ─────────


def _idx():
    r26 = [
        {
            "sleeper_id": "1",
            "gsis_id": "g1",
            "team": "KC",
            "full_name": "Edge Rusher",
            "depth_chart_position": "DE",
            "position": "DL",
        },
        {
            "sleeper_id": "",
            "gsis_id": "g2",
            "team": "LA",
            "full_name": "Wes Bailey Jr.",
            "depth_chart_position": "OLB",
            "position": "LB",
        },
        {
            "sleeper_id": "",
            "gsis_id": "g3",
            "team": "NE",
            "full_name": "Twin Name",
            "depth_chart_position": "ILB",
            "position": "LB",
        },
        {
            "sleeper_id": "",
            "gsis_id": "g4",
            "team": "NE",
            "full_name": "Twin Name",
            "depth_chart_position": "SS",
            "position": "DB",
        },
        {
            "sleeper_id": "5",
            "gsis_id": "g5",
            "team": "DAL",
            "full_name": "Generic Backer",
            "depth_chart_position": "LB",
            "position": "LB",
        },
        {
            "sleeper_id": "6",
            "gsis_id": "g6",
            "team": "DAL",
            "full_name": "Nose",
            "depth_chart_position": "NT",
            "position": "DL",
        },
        {
            "sleeper_id": "7",
            "gsis_id": "g7",
            "team": "DAL",
            "full_name": "Mike",
            "depth_chart_position": "MLB",
            "position": "LB",
        },
        {
            "sleeper_id": "8",
            "gsis_id": "g8",
            "team": "DAL",
            "full_name": "Free",
            "depth_chart_position": "FS",
            "position": "DB",
        },
    ]
    return D.build_fine_index(r26, [])


def test_fine_position_join_order_and_unknowns():
    idx = _idx()
    assert D.resolve_fine("1", {}, idx) == ("DE", "sleeper_id:roster_2026")
    assert D.resolve_fine("x", {"gsis_id": " g1 "}, idx)[1].startswith(
        "gsis_id"
    )  # stray space tolerated
    fine, how = D.resolve_fine("x", {"full_name": "Wesley Bailey", "team": "LAR"}, idx)
    assert (fine, how) == (
        "UNKNOWN",
        "no_nflverse_roster_match",
    )  # "Wes" is not "Wesley": no guessing
    fine, how = D.resolve_fine("x", {"full_name": "Wes Bailey", "team": "LAR"}, idx)
    assert (fine, how) == ("OLB", "name_team:roster_2026")  # suffix dropped, LA == LAR
    assert D.resolve_fine("x", {"full_name": "Twin Name", "team": "NE"}, idx) == (
        "UNKNOWN",
        "ambiguous_name_team",
    )
    assert D.resolve_fine("5", {}, idx) == ("UNKNOWN", "nflverse_generic_position:LB")
    assert (
        D.resolve_fine("6", {}, idx)[0] == "DT"
        and D.resolve_fine("7", {}, idx)[0] == "ILB"
        and D.resolve_fine("8", {}, idx)[0] == "S"
    )


def test_sleeper_depth_chart_is_only_a_fallback_for_a_silent_nflverse():
    idx = _idx()
    meta = {"full_name": "Nobody", "team": "ZZZ", "depth_chart_position": "LDE"}
    assert D.resolve_fine("x", meta, idx) == ("DE", "sleeper_depth_chart")
    # nflverse speaks (generic LB): Sleeper's depth chart is still allowed to refine it, labelled as such
    meta5 = {"depth_chart_position": "MLB"}
    assert D.resolve_fine("5", meta5, idx) == ("ILB", "sleeper_depth_chart")
    assert D.resolve_fine("x", {"full_name": "Nobody", "team": "ZZZ"}, idx)[0] == "UNKNOWN"


def test_archetype_rules_use_only_provenance_fields():
    a = D.archetype_for
    assert a("DE", "DL", ("DL",)) == "EDGE"
    assert (
        a("OLB", "LB", ("DL", "LB")) == "EDGE"
    )  # host lists him at DL: a rusher by the host's own eligibility
    assert a("OLB", "LB", ("LB",)) == "OLB"
    assert a("DT", "DL", ("DL",)) == "DT"
    assert a("ILB", "LB", ("LB",)) == "ILB"
    assert a("CB", "DB", ("DB",)) == "CB"
    assert a("S", "DB", ("DB",)) == "S"
    assert a("UNKNOWN", "LB", ("LB",)) == "UNK_LB"  # never merged into a fine archetype
    assert a("RB", "RB", ("RB",)) == "RB"
    # the function signature has no stat argument: an archetype cannot depend on a player's results
    import inspect

    assert list(inspect.signature(a).parameters) == ["fine", "position_group", "fantasy_positions"]


# ── 3. a missing week is never a zero score ──────────────────────────────────

CARD = {"idp_tkl_solo": 1.0, "idp_sack": 3.0, "rush_yd": 0.1}


def _lines():
    # week 1 played, week 2 DNP (team played), week 3 absent but team on bye, week 4 absent
    return {
        1: {
            "1001": {
                "gp": 1,
                "def_snp": 40,
                "tm_def_snp": 60,
                "idp_tkl_solo": 4,
                "idp_sack": 1,
                "gms_active": 1,
            }
        },
        2: {"1001": {"gms_active": 1, "tm_def_snp": 55}},
        3: {},
        4: {},
    }


def test_week_status_separates_played_dnp_bye_and_unknown():
    directory = {
        "1001": {"position": "DL", "team": "BBB"},
        "1002": {"position": "DL", "team": None},
    }
    lines = _lines()
    lines[1]["1002"] = {"gp": 1, "def_snp": 10, "idp_tkl_solo": 2}
    play = {"BBB": {1, 2, 4}}  # BBB is on bye in week 3
    s = D.build_season(lines, directory, CARD, play, 2026, (1, 2, 3, 4))
    wk = s["1001"].weeks
    assert (wk[1].status, wk[2].status, wk[3].status, wk[4].status) == (
        "played",
        "dnp",
        "bye",
        "dnp",
    )
    assert wk[1].points == pytest.approx(7.0)  # 4 solo + 1 sack at the card
    assert wk[2].points is None and wk[3].points is None  # not zero: absent
    # no team at all: the week cannot be classified, so it is unknown rather than a guessed zero
    assert all(o.status == "unknown" for w, o in s["1002"].weeks.items() if w != 1)
    assert s["1001"].played_points() == [7.0]
    # best ball pays a real 0.0 for the DNP and for the unrecorded game, and nothing for the bye
    assert s["1001"].best_ball_points() == [7.0, 0.0, 0.0]


def test_entity_availability_counts_dnp_but_not_bye_or_unknown():
    e = _entity("x", "DL", ["DL"], [8.0, 12.0], n_games=4)  # 2 appearances in 4 non-bye weeks
    assert e.p_active == pytest.approx(0.5)
    assert e.mu_cond == pytest.approx(10.0) and e.mu_unc == pytest.approx(5.0)
    assert (
        _entity("y", "DL", ["DL"], [], n_games=4).mu_cond == 0.0
    )  # no appearance: nothing to distribute


# ── 4. the maths ──────────────────────────────────────────────────────────────


def _universe(ents, fa, teams, extra_slots=None):
    pools = E.build_pools(ents, teams, {e.pid for e in fa}, SLOTS, set())
    return pools


def _idp_world(p_scores, others, fas, *, bye=None):
    """One team holding ``others`` + (the evaluated player), a free-agent pool, all DL."""
    p = _entity("P", "DL", ["DL"], p_scores)
    team = [_entity(f"o{i}", "DL", ["DL"], s) for i, s in enumerate(others)]
    fa = [_entity(f"f{i}", "DL", ["DL"], s) for i, s in enumerate(fas)]
    ents = [p, *team, *fa]
    pools = E.build_pools(ents, [[e.pid for e in team] + ["P"]], {e.pid for e in fa}, SLOTS, set())
    return ents, pools


def _run(ents, pools, **kw):
    sc = E.Scenario(
        model=kw.pop("model", "E"),
        avail=kw.pop("avail", "always"),
        byes=kw.pop("byes", "none"),
        draws=kw.pop("draws", 4000),
        **kw,
    )
    ds = E.DrawSet(ents, _shape(), sc)
    res = E.evaluate_marginals(ds, pools, [0], {0: 0})
    return ds, res[0]


def test_empirical_draws_use_only_the_observed_weeks():
    ents, pools = _idp_world([3.0, 9.0, 21.0], [[5.0] * 3] * 3, [[1.0] * 3])
    ds = E.DrawSet(ents, _shape(), E.Scenario(model="E", avail="always", byes="none", draws=500))
    assert set(np.unique(ds.S[:, 0])) <= {3.0, 9.0, 21.0}
    assert set(np.unique(ds.S[:, 0])) == {3.0, 9.0, 21.0}


def test_availability_is_the_observed_share_and_the_bye_week_is_out_for_that_team_only():
    p = _entity("P", "DL", ["DL"], [10.0, 10.0], n_games=4, bye=9)  # 50% active, bye in week 9
    other = _entity("Q", "DL", ["DL"], [7.0], n_games=1, bye=12)
    weeks = (8, 9, 10, 11)
    ds = E.DrawSet([p, other], _shape(), E.Scenario(model="E", draws=4000, remaining_weeks=weeks))
    nobye = E.DrawSet(
        [p, other], _shape(), E.Scenario(model="E", byes="none", draws=4000, remaining_weeks=weeks)
    )
    assert nobye.AB[:, 0].mean() == pytest.approx(0.5, abs=0.04)  # observed availability only
    assert ds.AB[:, 0].mean() == pytest.approx(0.5 * 0.75, abs=0.04)  # plus the bye in 1 of 4 weeks
    assert ds.AB[:, 1].mean() == pytest.approx(
        1.0, abs=1e-9
    )  # Q's bye (week 12) is outside the window
    assert ds.AB[:, 0][ds.AB[:, 0] > 0].size < ds.AB.shape[0]


def test_deterministic_limit_equals_the_owner_solver():
    # every player scores exactly the same number every week and is always active: the engine's
    # marginal must be the owner's with-minus-without lineup difference, to the last digit
    others = [[14.0] * 4, [11.0] * 4, [9.0] * 4, [6.0] * 4]
    fas = [[12.0] * 4, [8.0] * 4, [7.0] * 4, [3.0] * 4, [2.0] * 4]
    for p_level in (16.0, 10.0, 5.0):
        ents, pools = _idp_world([p_level] * 4, others, fas)
        _, res = _run(ents, pools, draws=50, deltas=(), cand_ranks=(1, 2, 3, 4, 5))
        mu = {e.pid: e.mu_cond for e in ents}

        def lineup(names):
            pool = [
                RosterPlayer(
                    player_id=n,
                    canonical_name=n,
                    position="DL",
                    ros_value=mu[n],
                    fantasy_positions=("DL",),
                )
                for n in names
            ]
            return sum(
                p.ros_value
                for p in solve_optimal_assignment(
                    pool, SLOTS, objective=OBJECTIVE_REALIZED_POINTS
                ).values()
            )

        team = ["o0", "o1", "o2", "o3"]
        with_p = lineup(team + ["P"])
        without = sorted((lineup(team + [f"f{i}"]) for i in range(5)), reverse=True)[
            2
        ]  # median of 5
        assert res.base_with.mean() == pytest.approx(with_p - without, abs=1e-9)


def test_jensen_gap_is_never_negative_and_a_sure_starter_has_none():
    # a sure starter: far above every other DL, so spread cannot change whether he starts
    others = [[8.0, 12.0, 10.0, 9.0]] * 4
    ents, pools = _idp_world([60.0, 62.0, 61.0, 63.0], others, [[2.0] * 4])
    ds, res = _run(ents, pools, draws=3000)
    j = res.base_with - res.deltas[-1.0]
    assert j.mean() == pytest.approx(0.0, abs=0.05)
    # a fringe player (mean at the cut line) has a real, positive gap
    ents, pools = _idp_world([1.0, 19.0, 2.0, 18.0], others, [[2.0] * 4])
    ds, res = _run(ents, pools, draws=3000)
    j = res.base_with - res.deltas[-1.0]
    assert j.mean() > 0.4
    # Jensen: with the same mean, more spread can only add expected lineup value
    assert (res.deltas[0.5] - res.base_with).mean() > 0


def test_a_volatile_bench_player_beats_a_stable_twin_with_the_same_mean():
    others = [[9.0, 13.0, 11.0, 10.0], [12.0, 8.0, 10.0, 11.0], [10.0, 10.0, 10.0, 10.0]]
    stable = [10.0, 10.0, 10.0, 10.0]
    boom = [0.0, 20.0, 0.0, 20.0]
    e1, p1 = _idp_world(stable, others, [[2.0] * 4])
    e2, p2 = _idp_world(boom, others, [[2.0] * 4])
    _, r1 = _run(e1, p1, draws=4000)
    _, r2 = _run(e2, p2, draws=4000)
    assert r2.base_with.mean() > r1.base_with.mean() + 0.3
    # and the strip of the volatile player's spread removes exactly that edge
    assert (r2.base_with - r2.deltas[-1.0]).mean() > 0.3


def test_volatile_replacement_shrinks_a_stable_players_marginal_below_the_deterministic_one():
    # the other side of the same coin: best ball makes a boom/bust free agent worth more than his mean
    others = [[11.0, 9.0, 10.0, 10.0]] * 3
    stable_p = [12.0] * 4
    fa_boom = [[0.0, 20.0, 0.0, 22.0]]
    ents, pools = _idp_world(stable_p, others, fa_boom)
    _, res = _run(ents, pools, draws=4000, cand_ranks=(1,))
    det = E.deterministic_marginals(ents, pools, [0], {0: 0}, (1,), "median")[0][0]
    assert res.base_with.mean() < det - 0.15


def test_median_replacement_is_robust_where_best_of_picks_the_luckiest():
    vals = [
        ("a", np.array([5.0])),
        ("b", np.array([9.0])),
        ("c", np.array([6.0])),
        ("d", np.array([7.0])),
        ("e", np.array([30.0])),
    ]
    assert E._pick_replacement(vals, "best")[0] == "e"
    assert E._pick_replacement(vals, "median")[0] == "d"
    with pytest.raises(ValueError):
        E._pick_replacement(vals, "mean")


def test_mean_preserving_scale_keeps_the_conditional_mean_and_scales_the_spread():
    ents, _ = _idp_world([4.0, 8.0, 18.0, 6.0], [[5.0] * 4], [[1.0] * 4])
    ds = E.DrawSet(ents, _shape(), E.Scenario(model="E", avail="always", byes="none", draws=6000))
    mu = ents[0].mu_cond
    base, wide, flat = ds.column(0), ds.column(0, 0.5), ds.column(0, -1.0)
    # the scaling is an exact affine map about the conditional mean, draw by draw ...
    assert np.allclose(wide, mu + 1.5 * (base - mu))
    assert np.allclose(flat, mu)
    # ... so the expectation (mu) is untouched and only the spread moves, by exactly the factor
    assert wide.std() == pytest.approx(1.5 * base.std(), rel=1e-9)
    se = base.std() / np.sqrt(base.size)
    assert abs(base.mean() - mu) < 4 * se and abs(wide.mean() - mu) < 4 * 1.5 * se


def test_week_bootstrap_resamples_weeks_and_keeps_events_aligned_with_scores():
    e = _entity("x", "DL", ["DL"], [3.0, 9.0, 12.0], n_games=5)
    e.ev_counts = np.array(
        [[1.0], [2.0], [3.0]]
    )  # event count == week index + 1, score = 3 * count
    e.played = np.array([3.0, 6.0, 9.0])
    rng = np.random.default_rng(1)
    for _ in range(50):
        b = E._bootstrap_entity(e, rng)
        assert b.n_games == 5 and b.n_played <= 5
        assert np.allclose(b.played, 3.0 * b.ev_counts[:, 0])


def test_event_model_keeps_the_players_observed_mean_and_is_poisson_in_spread():
    e = _entity("x", "DL", ["DL"], [5.0, 5.0, 5.0, 5.0])
    e.ev_counts = np.array([[1.0]] * 4)  # one event type, 1 per game, worth 5 points
    shape = E.ShapeReference({"POS_DL": np.ones(300)}, {"POS_DL": 0.5}, {}, np.array([5.0]))
    ds = E.DrawSet([e], shape, E.Scenario(model="Q", avail="always", byes="none", draws=20000))
    assert ds.S[:, 0].mean() == pytest.approx(5.0, abs=0.15)
    assert ds.S[:, 0].var() == pytest.approx(25.0, rel=0.1)  # 5^2 * lambda(1)


# ── 5. the evidence file ──────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ev():
    assert EVIDENCE.exists(), "run scripts/idp_accuracy/d_run.py to produce the evidence"
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def _walk(obj, path=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield path + (k,), v
            yield from _walk(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, path + (i,))


def test_evidence_schema_pins_and_status(ev):
    assert ev["schema"] == "idp_accuracy.bestball_archetypes.v1" and ev["lane"] == "D"
    assert ev["status"] == "RESEARCH_EVIDENCE_NOT_FOR_PROMOTION"
    pv = ev["provenance"]
    assert pv["leagueKey"] == "dynasty_main" and pv["leagueId"] == "1312006700437352448"
    assert pv["scoringFingerprint"] == D.PINNED_SCORING_FINGERPRINT == "sf1:9e51824690d091f9"
    assert pv["scoringFingerprintMatchesLaneA"] is True
    assert (
        pv["statisticsWeeks"] == [1, 2, 3, 4, 5, 6]
        and pv["season"] == 2026
        and pv["shapeSeason"] == 2025
    )
    assert "SHAPE only" in pv["shapeUse"] or "SHAPE" in pv["shapeUse"]
    assert pv["parameters"]["weekBootstrapReplicates"] >= 40 and pv["parameters"]["draws"] >= 1000
    for name, rec in pv["datasets"].items():
        assert re.fullmatch(r"[0-9a-f]{64}", rec["sha256"]), name


def test_public_artifact_carries_no_manager_team_or_roster_identity(ev):
    banned_keys = {
        "ownerId",
        "owner_id",
        "rosterId",
        "roster_id",
        "displayName",
        "display_name",
        "username",
        "teamName",
        "team_name",
        "Mown",
        "MdetOwn",
        "avatar",
        "managers",
        "users",
    }
    for path, _ in _walk(ev):
        assert path[-1] not in banned_keys, path
    # a rostered-by-whom statement is never made; the only league facts are counts
    assert "ownership" not in json.dumps(ev["population"]).lower()
    # players are NFL players: every row has a name, a Sleeper (public) id and no team-of-manager field
    for p in ev["players"]:
        assert set(p) >= {"name", "sleeperId", "archetype", "family"}
        assert not ({"owner", "manager", "roster", "team"} & {k.lower() for k in p})


def test_population_and_player_table_agree(ev):
    pop = ev["population"]
    assert pop["evaluated"] == len(ev["players"])
    assert sum(pop["evaluatedByArchetype"].values()) == pop["evaluated"]
    assert pop["teams"] == 12 and len(pop["startingSlots"]) == 21
    assert all(not a.startswith("UNK_") for a in pop["evaluatedByArchetype"])
    assert {p["archetype"] for p in ev["players"]} <= {
        "EDGE",
        "DT",
        "OLB",
        "ILB",
        "CB",
        "S",
        "QB",
        "RB",
        "WR",
        "TE",
        "K",
    }
    assert all(p["appearances"] >= S.MIN_OBS_EVAL for p in ev["players"])


def test_every_interval_is_ordered_and_every_group_estimate_is_recomputable(ev):
    for path, v in _walk(ev):
        if (
            path
            and path[-1] in ("ci95", "ciBonferroni")
            and isinstance(v, list)
            and v
            and v[0] is not None
        ):
            assert v[0] <= v[1], path
    by_group = {}
    for p in ev["players"]:
        by_group.setdefault(p["archetype"], []).append(p)
    for row in ev["volatilityPremium"]:
        members = [a for a in R.GROUP_MEMBERS[row["group"]] if a in by_group]
        rs = [p for a in members for p in by_group[a]]
        assert row["n"] == len(rs)
        # the published per-player values are rounded to 2 dp; the PLUG-IN group ratio is recomputable
        ratio = sum(p["volatilityPremium"] for p in rs) / sum(p["ppg"] for p in rs)
        assert row["JoverPpg"]["plugIn"] == pytest.approx(ratio, abs=0.004), row["group"]
        assert row["J"]["plugIn"] == pytest.approx(
            np.mean([p["volatilityPremium"] for p in rs]), abs=0.02
        )


def test_bias_corrected_estimates_sit_inside_their_own_intervals_and_the_correction_is_published(
    ev,
):
    corrected = [
        (r["group"], k, r[k])
        for r in ev["volatilityPremium"]
        for k in ("J", "JoverPpg", "JperWeeklySd", "sdOverPpg")
    ]
    assert corrected
    for group, key, e in corrected:
        lo, hi = e["ci95"]
        assert lo <= e["est"] <= hi, (group, key, e)
        # est is the plug-in minus the bootstrap bias, exactly as documented
        assert e["est"] == pytest.approx(
            e["plugIn"] - e["bootBias"], abs=0.0015 + 0.002 * abs(e["plugIn"])
        ), (group, key)
    for c in ev["contrasts"]:
        for metric in ("JoverPpg", "JperWeeklySd", "sdOverPpg"):
            m = c[metric]
            assert m["ci95"][0] <= m["diff"] <= m["ci95"][1], (c["contrast"], metric)
    # rank agreements are NOT bias-corrected: the plug-in is the estimate
    for r in ev["rankComparison"]["byFamily"]:
        assert r["rhoPpgVsBestBall"]["est"] == r["rhoPpgVsBestBall"]["plugIn"]


def test_volatility_premium_is_a_jensen_gap_so_no_group_estimate_is_negative(ev):
    for row in ev["volatilityPremium"]:
        assert row["J"]["plugIn"] >= 0 and row["J"]["est"] >= 0, row["group"]
    for p in ev["players"]:
        # per-player: negative only within Monte-Carlo error (3 standard errors)
        assert p["volatilityPremium"] >= -3 * max(p["volatilityPremiumMcSe"], 0.005) - 0.01, p[
            "name"
        ]


def test_ranks_in_the_player_table_are_consistent_with_the_values(ev):
    by = {}
    for p in ev["players"]:
        by.setdefault(p["rankGroup"], []).append(p)
    assert {"DL", "LB", "DB", "DL/LB", "QB", "RB", "WR", "TE", "K"} <= set(by)
    for grp, rs in by.items():
        assert all(r["familySize"] == len(rs) for r in rs)
        # published values are rounded to 2 dp, so players within 0.011 ppg of each other may swap
        for a in rs:
            for b in rs:
                if a["ppg"] > b["ppg"] + 0.011:
                    assert a["rankPpg"] < b["rankPpg"], (grp, a["name"], b["name"])
                if a["bestBallMarginal"] > b["bestBallMarginal"] + 0.011:
                    assert a["rankBestBall"] < b["rankBestBall"], (grp, a["name"], b["name"])


def test_contrast_families_carry_the_multiple_testing_interval(ev):
    assert len(ev["contrasts"]) == 5
    for c in ev["contrasts"]:
        for metric in ("JoverPpg", "JperWeeklySd", "sdOverPpg"):
            m = c[metric]
            assert m["bonferroniFamilySize"] == 5
            lo95, hi95 = m["ci95"]
            lob, hib = m["ciBonferroni"]
            assert (
                lob <= lo95 + 1e-9 and hib >= hi95 - 1e-9
            )  # a Bonferroni interval is never narrower
            # "excludes zero" flags are consistent with the intervals they summarise
            assert m["ciExcludesZero95"] == (lo95 > 0 or hi95 < 0)
            assert m["ciExcludesZeroBonferroni"] == (lob > 0 or hib < 0)
    for s in ev["profileSplit"]:
        assert s["bonferroniFamilySize"] == len(ev["profileSplit"])
    names = {c["contrast"] for c in ev["distributionChoice"]["contrastsByModel"]}
    assert names == {c["contrast"] for c in ev["contrasts"]}


def test_verified_and_provisional_inputs_are_separated(ev):
    cls = ev["varianceAssumptions"]["classification"]
    assert any("event counts" in v for v in cls["verified"])
    assert any("Poisson" in v for v in cls["provisionalVarianceAssumptions"])
    assert any("independent" in v for v in cls["provisionalVarianceAssumptions"])
    assert ev["distributionChoice"][
        "byGroup"
    ], "empirical vs parametric comparison must be published"
    assert ev["reliability"]["splitHalf2025"] and ev["reliability"]["yearOverYear2025to2026"]
    assert ev["roleChange"]["available"] is True and ev["realizedCheck"]["byFamily"]


def test_definitions_fixed_before_the_results_are_still_the_ones_in_force():
    assert (S.MIN_OBS_EVAL, S.FA_MIN_PLAYED) == (3, 2)
    assert S.SHAPE_MATCHED == (10, 5.0) and S.SHAPE_UNFILTERED == (8, 0.5)
    assert E.Scenario().remaining_weeks == tuple(range(7, 18))
    assert E.Scenario().cand_ranks == (1, 2, 3, 4, 5) and E.Scenario().repl_mode == "median"
    assert R.INNER == 20
    assert R.GROUP_MEMBERS["EDGE"] == ("EDGE",) and R.GROUP_MEMBERS["IDP (all six)"] == (
        "EDGE",
        "DT",
        "OLB",
        "ILB",
        "CB",
        "S",
    )
    assert (
        R.BIG_PLAY_IDP
        and "idp_tkl_solo" not in R.BIG_PLAY_IDP
        and "idp_tkl_loss" not in R.BIG_PLAY_IDP
    )


def test_every_results_table_in_the_write_up_is_the_generated_one(ev):
    from scripts.idp_accuracy import d_tables as T

    text = DOC.read_text(encoding="utf-8")
    in_doc = T.blocks_in(text)
    assert set(in_doc) == set(T.RENDERERS), set(T.RENDERERS) ^ set(in_doc)
    for name, body in T.render_all(ev).items():
        assert in_doc[name] == body, f"table {name!r} is stale: run d_tables.py --write"


def test_write_up_quotes_the_headline_and_pins_provenance(ev):
    text = DOC.read_text(encoding="utf-8")
    idp, off = ev["headline"]["idp"], ev["headline"]["offense"]
    for v in (idp["JoverPpg"]["est"], off["JoverPpg"]["est"]):
        assert f"{100 * v:.1f}%" in text, v
    assert f"{idp['J']['est']:.2f}" in text and f"{off['J']['est']:.2f}" in text
    assert ev["provenance"]["scoringFingerprint"] in text
    for needle in (
        "RESEARCH_EVIDENCE_NOT_FOR_PROMOTION",
        "UNRESOLVED",
        "Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f",
        "Deviations",
    ):
        assert needle in text, needle
    # the document never names a manager, a team owner or a league roster
    assert not re.search(
        r"(?i)\b(owner|manager|roster id|display name)\s*:", text.split("## Reproduce")[0]
    )


def test_profile_key_sets_use_the_scorers_component_keys():
    """The host stat line says idp_pass_def / idp_qb_hit; the scorer reports idp_pd / idp_hit."""
    from src.nfl_data.realized_points import compute_weekly_points

    card = {
        "idp_tkl_solo": 1.33, "idp_tkl_ast": 0.8, "idp_tkl_loss": 4.24, "idp_sack": 2.92,
        "idp_qb_hit": 2.12, "idp_pass_def": 5.3, "idp_int": 5.3, "idp_ff": 4.24, "idp_fum_rec": 3.19,
    }  # fmt: skip
    line = {k: 1 for k in card} | {"player_id": "1001", "season": 2026, "week": 1, "gp": 1}
    res = compute_weekly_points(line, card, position="DL", source="sleeper")
    emitted = {c[0] for c in res.components if c[3]}
    known = {k for keys in R.KEYSETS.values() for k in keys}
    assert emitted <= known, emitted - known
    assert {"idp_pd", "idp_hit"} <= emitted
    assert set(R.BIG_PLAY_IDP) >= {"idp_pd", "idp_hit", "idp_sack", "idp_int"}


# ── 6. isolation ──────────────────────────────────────────────────────────────


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_this_lane_imports_nothing_it_must_not_and_nothing_imports_it():
    mine = [
        REPO / "scripts/idp_accuracy" / f
        for f in ("d_data.py", "d_engine.py", "d_study.py", "d_report.py", "d_run.py")
    ]
    for path in mine:
        for m in _imports(path):
            assert not (m == "src.bestball" or m.startswith("src.bestball.")), (path.name, m)
            assert not m.startswith("src.league_valuation"), (path.name, m)
            assert "server" != m, (path.name, m)
    offenders = []
    for path in [REPO / "server.py", *(REPO / "src").rglob("*.py")]:
        if any(
            m == "scripts.idp_accuracy" or m.startswith("scripts.idp_accuracy.")
            for m in _imports(path)
        ):
            offenders.append(str(path.relative_to(REPO)))
    assert offenders == []


def test_the_lane_writes_only_its_own_artifacts():
    src = (REPO / "scripts/idp_accuracy/d_run.py").read_text(encoding="utf-8")
    assert "docs/valuation/idp_accuracy/evidence/bestball_archetypes.json" in src
    assert "data/idp_accuracy/work" in src
    # no flag, config or served-value file is named as an output anywhere in the lane
    for name in ("d_data.py", "d_engine.py", "d_study.py", "d_report.py", "d_run.py"):
        text = (REPO / "scripts/idp_accuracy" / name).read_text(encoding="utf-8")
        for forbidden in (
            "config/feature_flags",
            "rankDerivedValue",
            "config/weights",
            "config/bridges",
            "write_text(json.dumps(inp",
        ):
            assert forbidden not in text, (name, forbidden)
