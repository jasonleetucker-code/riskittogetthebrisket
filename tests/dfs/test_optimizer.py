"""DFS optimizer: exact agreement with brute force, hard-constraint honesty."""

from __future__ import annotations

import itertools
import random

import pytest

from src.dfs.imports import SlateAthlete
from src.dfs.optimizer import (
    ConstraintError,
    exposure_bounds,
    exposure_minimums,
    optimize,
    parse_constraints,
    validate_lineup,
)
from src.dfs.rules import get_ruleset

pytest.importorskip("scipy")

DK = get_ruleset("draftkings.nfl.classic")
FD = get_ruleset("fanduel.nfl.classic")


def _pool(seed: int, dst_pos: str = "DST", teams=("AA", "BB", "CC", "DD")) -> list[SlateAthlete]:
    rnd = random.Random(seed)
    games = {teams[0]: "AA@BB", teams[1]: "AA@BB", teams[2]: "CC@DD", teams[3]: "CC@DD"}
    opp = {teams[0]: teams[1], teams[1]: teams[0], teams[2]: teams[3], teams[3]: teams[2]}
    counts = {"QB": 3, "RB": 5, "WR": 6, "TE": 3, dst_pos: 3}
    out = []
    n = 0
    for pos, k in counts.items():
        for _ in range(k):
            n += 1
            team = rnd.choice(teams)
            out.append(
                SlateAthlete(
                    player_id=str(1000 + n),
                    name=f"P{n}",
                    positions=[pos],
                    team=team,
                    opponent=opp[team],
                    game=games[team],
                    salary=rnd.randrange(30, 90) * 100,
                    projection=round(rnd.uniform(-1, 25), 2),
                )
            )
    return out


def _brute_force(ruleset, pool, cap=None):
    """Best legal total by enumeration (order-free sets)."""
    by_pos = {}
    for a in pool:
        by_pos.setdefault(a.positions[0], []).append(a)
    dst = "DST" if "DST" in by_pos else "D"
    best = None
    for qb in by_pos["QB"]:
        for d in by_pos[dst]:
            for te in by_pos["TE"]:
                for rbs in itertools.combinations(by_pos["RB"], 2):
                    for wrs in itertools.combinations(by_pos["WR"], 3):
                        used = {qb.player_id, d.player_id, te.player_id} | {
                            x.player_id for x in rbs + wrs
                        }
                        for fx in by_pos["RB"] + by_pos["WR"] + by_pos["TE"]:
                            if fx.player_id in used:
                                continue
                            lu = [qb, *rbs, *wrs, te, fx, d]
                            sal = sum(a.salary for a in lu)
                            if sal > (cap or ruleset.salary_cap):
                                continue
                            teams = {}
                            for a in lu:
                                teams[a.team] = teams.get(a.team, 0) + 1
                            if (
                                ruleset.max_players_per_team
                                and max(teams.values()) > ruleset.max_players_per_team
                            ):
                                continue
                            if ruleset.min_teams and len(teams) < ruleset.min_teams:
                                continue
                            if ruleset.min_games and len({a.game for a in lu}) < ruleset.min_games:
                                continue
                            tot = round(sum(a.projection for a in lu), 2)
                            if best is None or tot > best:
                                best = tot
    return best


@pytest.mark.parametrize("seed", range(6))
def test_matches_brute_force_draftkings(seed):
    pool = _pool(seed)
    c = parse_constraints({}, DK, pool)
    res = optimize(DK, pool, c)
    expected = _brute_force(DK, pool)
    if expected is None:
        assert res["status"] == "infeasible"
        return
    assert res["status"] == "optimal"
    assert res["lineups"][0]["projection"] == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("seed", range(6))
def test_matches_brute_force_fanduel_team_rules(seed):
    pool = _pool(100 + seed, dst_pos="D")
    for a in pool:
        a.salary = int(a.salary * 1.2)
    c = parse_constraints({}, FD, pool)
    res = optimize(FD, pool, c)
    expected = _brute_force(FD, pool)
    if expected is None:
        assert res["status"] == "infeasible"
        return
    assert res["status"] == "optimal"
    assert res["lineups"][0]["projection"] == pytest.approx(expected, abs=1e-6)


def test_every_returned_lineup_passes_the_independent_validator():
    pool = _pool(7)
    c = parse_constraints({"lineups": 5, "minUnique": 2}, DK, pool)
    res = optimize(DK, pool, c)
    by_id = {a.player_id: a for a in pool}
    for lu in res["lineups"]:
        assert (
            validate_lineup([(p["slot"], p["playerId"]) for p in lu["players"]], DK, by_id, c) == []
        )


def test_validator_catches_what_the_solver_must_not_do():
    pool = _pool(8)
    by_id = {a.player_id: a for a in pool}
    qb = [a for a in pool if a.positions == ["QB"]][0]
    bad = [(s.name, qb.player_id) for s in DK.slots]
    errs = validate_lineup(bad, DK, by_id)
    assert any("twice" in e for e in errs)
    assert any("not eligible" in e for e in errs)


def test_locks_and_excludes_are_hard():
    pool = _pool(3)
    worst_wr = min((a for a in pool if a.positions == ["WR"]), key=lambda a: a.projection)
    best = max(pool, key=lambda a: a.projection)
    c = parse_constraints({"locks": [worst_wr.player_id], "excludes": [best.player_id]}, DK, pool)
    res = optimize(DK, pool, c)
    ids = {p["playerId"] for p in res["lineups"][0]["players"]}
    assert worst_wr.player_id in ids and best.player_id not in ids


def test_conflict_is_isolated_not_relaxed():
    pool = _pool(4)
    qbs = [a.player_id for a in pool if a.positions == ["QB"]][:2]
    c = parse_constraints({"locks": qbs, "salaryMin": 1000}, DK, pool)
    res = optimize(DK, pool, c)
    assert res["built"] == 0 and res["status"] == "infeasible"
    conflict = res["shortfall"]["conflict"]
    assert conflict["state"] == "isolated"
    assert sorted(conflict["items"]) == sorted(f"lock:{q}" for q in qbs)  # salaryMin is not blamed
    assert len(conflict["described"]) == 2


def test_lock_and_exclude_same_player_is_refused():
    pool = _pool(4)
    pid = pool[0].player_id
    with pytest.raises(ConstraintError):
        parse_constraints({"locks": [pid], "excludes": [pid]}, DK, pool)


def test_exactly_n_unique_lineups_or_explicit_shortfall():
    pool = _pool(11)
    c = parse_constraints({"lineups": 4, "minUnique": 3}, DK, pool)
    res = optimize(DK, pool, c)
    assert res["built"] == 4 and res["shortfall"] is None
    sets = [set(p["playerId"] for p in lu["players"]) for lu in res["lineups"]]
    for a, b in itertools.combinations(sets, 2):
        assert len(a - b) >= 3
    # Totals are non-increasing: each lineup is the best remaining under the rule.
    totals = [lu["projection"] for lu in res["lineups"]]
    assert totals == sorted(totals, reverse=True)

    # 9 unique players per lineup forces disjoint lineups; only 3 QBs → at most 3.
    c = parse_constraints({"lineups": 5, "minUnique": 9}, DK, pool)
    res = optimize(DK, pool, c)
    assert res["built"] <= 3 and res["shortfall"]["missing"] == 5 - res["built"]
    assert res["status"] == "partial"
    assert "uniqueness" in res["shortfall"]["conflict"]["items"]


def test_exposure_caps_round_down_and_are_enforced():
    pool = _pool(12)
    c = parse_constraints({"lineups": 3, "maxExposure": 0.5}, DK, pool)
    caps = exposure_bounds(c, pool)
    assert set(caps.values()) == {1}  # floor(0.5 * 3) = 1, never rounded up to 2
    res = optimize(DK, pool, c)
    for row in res["exposure"]:
        assert row["count"] <= 1


def test_missing_projection_is_never_zero():
    pool = _pool(13)
    pool[0].projection = None
    c = parse_constraints({}, DK, pool)
    res = optimize(DK, pool, c)
    assert pool[0].player_id in res["excludedUnprojected"]
    assert pool[0].player_id not in {p["playerId"] for p in res["lineups"][0]["players"]}
    c = parse_constraints({"locks": [pool[0].player_id]}, DK, pool)
    with pytest.raises(ConstraintError) as exc:
        optimize(DK, pool, c)
    assert exc.value.code == "LOCKED_PLAYER_UNPROJECTED"


def test_stack_and_bring_back():
    pool = _pool(14)
    c = parse_constraints(
        {
            "stacks": [
                {"primary": ["QB"], "secondary": ["WR", "TE"], "minSecondary": 2, "bringBack": 1}
            ]
        },
        DK,
        pool,
    )
    res = optimize(DK, pool, c)
    if res["built"]:
        players = res["lineups"][0]["players"]
        qb = next(p for p in players if p["slot"] == "QB")
        mates = [
            p for p in players if p["team"] == qb["team"] and p["positions"][0] in ("WR", "TE")
        ]
        opp = [p for p in players if p["team"] == qb["opponent"]]
        assert len(mates) >= 2 and len(opp) >= 1
    else:
        assert res["shortfall"]["conflict"]["state"] in ("isolated", "rules_or_pool")


def test_scoring_identity_ignores_flex_permutation():
    pool = _pool(15)
    res = optimize(DK, pool, parse_constraints({}, DK, pool))
    lu = res["lineups"][0]
    ids = lu["scoringIdentity"].split("|")
    assert ids == sorted(ids) and len(ids) == 9
    assert lu["assignmentIdentity"].startswith("QB=")


def test_min_games_rule_fails_closed_when_game_unknown():
    pool = _pool(16)
    pool[3].game = None
    with pytest.raises(ConstraintError) as exc:
        optimize(DK, pool, parse_constraints({}, DK, pool))
    assert exc.value.code == "GAME_UNKNOWN"


# ── review findings (independent review, 2026-09-30) ──────────────────


def test_objective_is_not_rounded_before_solving():
    pool = _pool(21)
    wrs = [a for a in pool if a.positions == ["WR"]]
    for a in wrs:
        a.projection = 1.0
    wrs[0].projection, wrs[1].projection = 30.001, 30.004
    wrs[0].salary = wrs[1].salary = 3000
    # At most one of the two near-identical WRs: the unrounded objective
    # must pick 30.004 over 30.001 (rounded to 2 dp they would tie).
    c = parse_constraints(
        {"groups": [{"players": [wrs[0].player_id, wrs[1].player_id], "max": 1}]}, DK, pool
    )
    ids = {p["playerId"] for p in optimize(DK, pool, c)["lineups"][0]["players"]}
    assert wrs[1].player_id in ids and wrs[0].player_id not in ids


def test_lock_exhausted_by_exposure_is_infeasible_not_timed_out():
    pool = _pool(22)
    pid = pool[0].player_id
    res = optimize(
        DK, pool, parse_constraints({"locks": [pid], "playerMaxExposure": {pid: 0.5}}, DK, pool)
    )
    assert res["status"] == "infeasible" and res["shortfall"]["reason"] == "infeasible"


@pytest.mark.parametrize(
    "raw",
    [
        [1],
        {"groups": [{"players": [[1]], "min": 1}]},
        {"maxExposure": 10**400},
        {"lineups": 10**400},
        {"lineups": float("inf")},
    ],
)
def test_malformed_constraints_are_refused_not_crashed(raw):
    pool = _pool(23)
    with pytest.raises(ConstraintError):
        parse_constraints(raw, DK, pool)


def test_game_unknown_only_matters_for_selectable_players():
    pool = _pool(24)
    pool[3].game = None
    res = optimize(DK, pool, parse_constraints({"excludes": [pool[3].player_id]}, DK, pool))
    assert res["built"] == 1


# ── conditional rules (if A then B / not B / at least N of G) ─────────


def _brute_with(ruleset, pool, c):
    by_id = {a.player_id: a for a in pool}
    by_pos = {}
    for a in pool:
        by_pos.setdefault(a.positions[0], []).append(a)
    best = None
    for qb in by_pos["QB"]:
        for d in by_pos["DST"]:
            for te in by_pos["TE"]:
                for rbs in itertools.combinations(by_pos["RB"], 2):
                    for wrs in itertools.combinations(by_pos["WR"], 3):
                        used = {qb.player_id, d.player_id, te.player_id} | {
                            x.player_id for x in rbs + wrs
                        }
                        for fx in by_pos["RB"] + by_pos["WR"] + by_pos["TE"]:
                            if fx.player_id in used:
                                continue
                            lu = [qb, *rbs, *wrs, te, fx, d]
                            assignment = list(
                                zip([s.name for s in ruleset.slots], [a.player_id for a in lu])
                            )
                            if validate_lineup(assignment, ruleset, by_id, c):
                                continue
                            tot = round(sum(a.projection for a in lu), 2)
                            best = tot if best is None or tot > best else best
    return best


def _unconstrained_ids(pool):
    res = optimize(DK, pool, parse_constraints({}, DK, pool))
    return res, {p["playerId"] for p in res["lineups"][0]["players"]}


def test_if_a_then_not_b_is_exact_and_binds():
    pool = _pool(31)
    res, ids = _unconstrained_ids(pool)
    chosen = [p["playerId"] for p in res["lineups"][0]["players"]]
    a, b = chosen[0], chosen[1]  # both in the unconstrained optimum -> the rule must bind
    c = parse_constraints({"conditionals": [{"when": [a], "then": [b], "thenMax": 0}]}, DK, pool)
    got = optimize(DK, pool, c)
    got_ids = {p["playerId"] for p in got["lineups"][0]["players"]}
    assert not ({a, b} <= got_ids)
    assert got["lineups"][0]["projection"] < res["lineups"][0]["projection"]  # it bound
    assert got["lineups"][0]["projection"] == pytest.approx(_brute_with(DK, pool, c), abs=1e-6)


def test_if_a_then_at_least_n_of_group_is_exact():
    pool = _pool(32)
    res, ids = _unconstrained_ids(pool)
    qb = next(p["playerId"] for p in res["lineups"][0]["players"] if p["slot"] == "QB")
    outsiders = [
        a.player_id for a in pool if a.player_id not in ids and a.positions[0] in ("WR", "TE")
    ][:4]
    c = parse_constraints(
        {"conditionals": [{"when": [qb], "then": outsiders, "thenMin": 2}]}, DK, pool
    )
    got = optimize(DK, pool, c)
    expected = _brute_with(DK, pool, c)
    assert got["lineups"][0]["projection"] == pytest.approx(expected, abs=1e-6)
    got_ids = {p["playerId"] for p in got["lineups"][0]["players"]}
    assert qb not in got_ids or len(got_ids & set(outsiders)) >= 2


def test_conditional_contradiction_is_isolated_to_the_rule_and_lock():
    pool = _pool(33)
    wr = [a.player_id for a in pool if a.positions == ["WR"]]
    c = parse_constraints(
        {
            "locks": [wr[0], wr[1]],
            "conditionals": [
                {"label": "Never together", "when": [wr[0]], "then": [wr[1]], "thenMax": 0}
            ],
        },
        DK,
        pool,
    )
    res = optimize(DK, pool, c)
    assert res["status"] == "infeasible"
    items = set(res["shortfall"]["conflict"]["items"])
    assert "cond:0" in items and items <= {"cond:0", f"lock:{wr[0]}", f"lock:{wr[1]}"}
    assert any(
        d.startswith("Never together: if") for d in res["shortfall"]["conflict"]["described"]
    )


def test_conditional_input_is_validated():
    pool = _pool(34)
    a, b = pool[0].player_id, pool[1].player_id
    for bad in (
        {"conditionals": [{"when": [a], "then": [a], "thenMax": 0}]},
        {"conditionals": [{"when": [a], "then": [b]}]},
        {"conditionals": [{"when": ["nope"], "then": [b], "thenMin": 1}]},
        {"conditionals": [{"when": [a], "then": [b], "thenMin": 2, "thenMax": 1}]},
    ):
        with pytest.raises(ConstraintError):
            parse_constraints(bad, DK, pool)


# ── owner forecast overrides vs selection boosts (DFS-§8-08) ──────────


def test_override_is_a_forecast_used_in_totals_and_never_written_back():
    pool = _pool(41)
    res, ids = _unconstrained_ids(pool)
    outsider = next(a for a in pool if a.player_id not in ids and a.positions[0] == "WR")
    before = outsider.projection
    c = parse_constraints({"projectionOverrides": {outsider.player_id: 60.0}}, DK, pool)
    got = optimize(DK, pool, c)
    row = next(p for p in got["lineups"][0]["players"] if p["playerId"] == outsider.player_id)
    assert (
        row["ownerOverride"] == 60.0
        and row["projection"] == before
        and row["slotProjection"] == 60.0
    )
    assert outsider.projection == before  # the slate's forecast is untouched
    assert got["lineups"][0]["projection"] == pytest.approx(
        sum(p["slotProjection"] for p in got["lineups"][0]["players"])
    )


def test_override_can_supply_a_missing_forecast():
    pool = _pool(42)
    pool[0].projection = None
    c = parse_constraints(
        {"projectionOverrides": {pool[0].player_id: 30.0}, "locks": [pool[0].player_id]}, DK, pool
    )
    got = optimize(DK, pool, c)
    assert got["built"] == 1 and pool[0].player_id not in got["excludedUnprojected"]


def test_boost_tilts_selection_but_never_enters_the_reported_total():
    pool = _pool(43)
    res, ids = _unconstrained_ids(pool)
    base_total = res["lineups"][0]["projection"]
    outsiders = sorted(
        (a for a in pool if a.player_id not in ids and a.positions[0] in ("WR", "RB", "TE")),
        key=lambda a: -a.projection,
    )
    flipped = None
    for o in outsiders:
        got = optimize(DK, pool, parse_constraints({"boosts": {o.player_id: 0.5}}, DK, pool))
        if o.player_id in {p["playerId"] for p in got["lineups"][0]["players"]}:
            flipped = (o, got)
            break
    assert flipped is not None, "fixture must contain a boost that changes selection (non-vacuous)"
    o, got = flipped
    lu = got["lineups"][0]
    assert lu["projection"] < base_total  # the boost bought a worse FORECAST, as the owner chose
    assert lu["projection"] == pytest.approx(
        sum(p["projection"] for p in lu["players"])
    )  # unboosted
    row = next(p for p in lu["players"] if p["playerId"] == o.player_id)
    assert row["preferenceBoost"] == 0.5 and row["slotProjection"] == row["projection"]


def test_override_and_boost_inputs_are_bounded():
    pool = _pool(44)
    pid = pool[0].player_id
    for bad in (
        {"boosts": {pid: 2}},
        {"boosts": {pid: True}},
        {"projectionOverrides": {pid: "12"}},
        {"projectionOverrides": {"nope": 5}},
        {"projectionOverrides": {pid: float("nan")}},
    ):
        with pytest.raises(ConstraintError):
            parse_constraints(bad, DK, pool)


# ── Minimum exposure ─────────────────────────────────────────────────────


def _worst_projected(pool, pos):
    return min((a for a in pool if a.positions == [pos]), key=lambda a: a.projection)


def test_min_exposure_rounds_up_and_is_met_by_a_player_the_optimizer_would_skip():
    pool = _pool(31)
    weak = _worst_projected(pool, "RB")
    c = parse_constraints(
        {"lineups": 5, "minUnique": 1, "playerMinExposure": {weak.player_id: 0.5}}, DK, pool
    )
    assert exposure_minimums(c, pool) == {weak.player_id: 3}  # ceil(0.5 * 5), never down to 2
    unforced = optimize(DK, pool, parse_constraints({"lineups": 5}, DK, pool))
    assert all(
        weak.player_id not in {p["playerId"] for p in lu["players"]} for lu in unforced["lineups"]
    )
    res = optimize(DK, pool, c)
    assert res["built"] == 5 and res["minimumExposureUnmet"] == []
    hits = [weak.player_id in {p["playerId"] for p in lu["players"]} for lu in res["lineups"]]
    assert sum(hits) >= 3
    # Latest-deadline construction: the forced appearances sit at the END, so
    # the first lineups are the owner's best by projection.
    assert hits[-3:] == [True, True, True]
    assert res["lineups"][0]["projection"] == unforced["lineups"][0]["projection"]


def test_min_above_max_is_refused_before_solving():
    pool = _pool(32)
    pid = pool[3].player_id
    c = parse_constraints(
        {"lineups": 4, "playerMinExposure": {pid: 0.75}, "playerMaxExposure": {pid: 0.5}}, DK, pool
    )
    with pytest.raises(ConstraintError) as e:
        optimize(DK, pool, c)
    assert e.value.code == "INVALID_CONSTRAINT" and e.value.detail["players"][0]["min"] == 3


def test_min_exposure_player_cannot_be_excluded_or_unprojected():
    pool = _pool(33)
    pid = pool[4].player_id
    with pytest.raises(ConstraintError):
        parse_constraints({"excludes": [pid], "playerMinExposure": {pid: 0.2}}, DK, pool)
    pool[4].projection = None
    with pytest.raises(ConstraintError) as e:
        optimize(DK, pool, parse_constraints({"playerMinExposure": {pid: 0.2}}, DK, pool))
    assert e.value.code == "MIN_EXPOSURE_PLAYER_UNPROJECTED"


def test_conflicting_minimums_are_isolated_and_reported_unmet_not_relaxed():
    # Two quarterbacks both required in every lineup cannot share one QB slot.
    pool = _pool(34)
    qbs = [a.player_id for a in pool if a.positions == ["QB"]][:2]
    c = parse_constraints({"lineups": 2, "playerMinExposure": {qbs[0]: 1.0, qbs[1]: 1.0}}, DK, pool)
    res = optimize(DK, pool, c)
    assert res["built"] == 0 and res["shortfall"]["reason"] == "infeasible"
    assert res["shortfall"]["conflict"]["items"] == ["min_exposure"]
    assert "Minimum exposures due" in res["shortfall"]["conflict"]["described"][0]
    assert {u["playerId"] for u in res["minimumExposureUnmet"]} == set(qbs)


# ── Team / game stacks (sport-neutral) ───────────────────────────────────


def _team_tally(lineup, pool_by_id, scope="team", positions=None):
    out = {}
    for p in lineup["players"]:
        a = pool_by_id[p["playerId"]]
        if positions and not set(a.positions) & set(positions):
            continue
        key = a.team if scope == "team" else a.game
        out[key] = out.get(key, 0) + 1
    return sorted(out.values(), reverse=True)


@pytest.mark.parametrize("seed", [41, 42, 43])
def test_team_stack_matches_brute_force(seed):
    pool = _pool(seed)
    raw = {"teamStacks": [{"scope": "team", "size": 3, "count": 1}]}
    c = parse_constraints(raw, DK, pool)
    res = optimize(DK, pool, c)
    best = _brute_with(DK, pool, c)
    by_id = {a.player_id: a for a in pool}
    assert best is not None  # non-vacuity: these seeds have a stacked lineup
    assert res["built"] == 1
    assert res["lineups"][0]["projection"] == pytest.approx(best, abs=1e-6)
    assert _team_tally(res["lineups"][0], by_id)[0] >= 3


def test_team_stack_binds_and_is_not_vacuous():
    pool = _pool(44)
    by_id = {a.player_id: a for a in pool}
    free = optimize(DK, pool, parse_constraints({}, DK, pool))["lineups"][0]
    need = _team_tally(free, by_id)[0] + 1  # one more than the free optimum naturally stacks
    c = parse_constraints({"teamStacks": [{"scope": "team", "size": need}]}, DK, pool)
    res = optimize(DK, pool, c)
    assert res["built"] == 1
    assert _team_tally(res["lineups"][0], by_id)[0] >= need
    assert res["lineups"][0]["projection"] < free["projection"]  # it cost points: it bound
    assert not validate_lineup(
        [(p["slot"], p["playerId"]) for p in res["lineups"][0]["players"]], DK, by_id, c
    )


def test_two_stacks_and_game_scope_with_positions():
    pool = _pool(45)
    by_id = {a.player_id: a for a in pool}
    c = parse_constraints(
        {
            "teamStacks": [
                {"scope": "game", "size": 4, "count": 2, "positions": ["WR", "RB", "TE", "QB"]}
            ]
        },
        DK,
        pool,
    )
    res = optimize(DK, pool, c)
    assert res["built"] == 1
    tally = _team_tally(res["lineups"][0], by_id, "game", ["WR", "RB", "TE", "QB"])
    assert len([n for n in tally if n >= 4]) >= 2


def test_impossible_team_stack_is_isolated_not_dropped():
    pool = _pool(46)
    # One QB slot and QB is not FLEX-eligible: no lineup can hold two QBs.
    c = parse_constraints(
        {"teamStacks": [{"scope": "team", "size": 2, "positions": ["QB"], "label": "QB pair"}]},
        DK,
        pool,
    )
    res = optimize(DK, pool, c)
    assert res["built"] == 0
    assert res["shortfall"]["conflict"]["items"] == ["teamstack:0"]
    assert "QB pair" in res["shortfall"]["conflict"]["described"][0]


@pytest.mark.parametrize(
    "stack",
    [
        {"scope": "league", "size": 3},
        {"size": 1},
        {"size": 5, "count": 2},  # 10 > 9 slots
        {"size": 3, "positions": ["G"]},
        "3",
    ],
)
def test_team_stack_input_is_validated(stack):
    with pytest.raises(ConstraintError):
        parse_constraints({"teamStacks": [stack]}, DK, _pool(47))


def test_every_highs_call_runs_on_the_one_solver_thread(monkeypatch):
    """Solves started from different threads all execute on one pinned thread.

    Calling HiGHS from whichever request thread ran a build crashed the process
    (Windows access violation in a native thread, ~1 run in 5 of this suite).
    """
    import threading

    import scipy.optimize

    seen = []
    real = scipy.optimize.milp

    def spy(*args, **kwargs):
        seen.append(threading.current_thread().name)
        return real(*args, **kwargs)

    monkeypatch.setattr(scipy.optimize, "milp", spy)
    pool = _pool(71)
    c = parse_constraints({}, DK, pool)
    workers = [threading.Thread(target=optimize, args=(DK, pool, c)) for _ in range(3)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    optimize(DK, pool, c)
    assert len(seen) == 4
    assert len(set(seen)) == 1 and seen[0].startswith("dfs-highs")
