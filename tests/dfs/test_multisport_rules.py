"""NBA / NHL classic rule sets (DraftKings + FanDuel): research-mode, brute-force-verified solving.

The rule sets are UNVERIFIED encodings (official pages refuse automated
access); these tests prove the SOLVER is exact under them, not that the rules
are the platforms' current rules.  Pools are synthetic.
"""

from __future__ import annotations

import itertools
import random

import pytest

from src.dfs.imports import SlateAthlete
from src.dfs.optimizer import optimize, parse_constraints, validate_lineup
from src.dfs.rules import capability_matrix, get_ruleset
from src.dfs.slate import canonical_from_platform_file

pytest.importorskip("scipy")

TEAMS = ("AA", "BB", "CC", "DD")
GAME = {"AA": "AA@BB", "BB": "AA@BB", "CC": "CC@DD", "DD": "CC@DD"}
OPP = {"AA": "BB", "BB": "AA", "CC": "DD", "DD": "CC"}


def _pool(seed: int, positions: list[list[str]], cap_scale: float) -> list[SlateAthlete]:
    rnd = random.Random(seed)
    out = []
    for i, pos in enumerate(positions):
        team = rnd.choice(TEAMS)
        out.append(
            SlateAthlete(
                player_id=str(5000 + i),
                name=f"S{i}",
                positions=pos,
                team=team,
                opponent=OPP[team],
                game=GAME[team],
                salary=int(rnd.randrange(35, 75) * 100 * cap_scale),
                projection=round(rnd.uniform(5, 55), 2),
            )
        )
    return out


def _brute(rs, pool, c=None):
    """Best legal total by exhaustive slot assignment (sets deduplicated)."""
    by_id = {a.player_id: a for a in pool}
    best = None
    seen: set[frozenset[str]] = set()

    def rec(k, chosen):
        nonlocal best
        if k == len(rs.slots):
            key = frozenset(chosen)
            if key in seen:
                return
            seen.add(key)
            assignment = list(zip([s.name for s in rs.slots], chosen))
            if validate_lineup(assignment, rs, by_id, c):
                return
            tot = round(sum(by_id[p].projection for p in chosen), 2)
            if best is None or tot > best:
                best = tot
            return
        for a in pool:
            if a.player_id in chosen or not set(a.positions) & set(rs.slots[k].eligible):
                continue
            rec(k + 1, chosen + [a.player_id])

    rec(0, [])
    return best


CASES = [
    (
        "fanduel.nba.classic",
        [["PG"]] * 3 + [["SG"]] * 3 + [["SF"]] * 3 + [["PF"]] * 3 + [["C"]] * 2,
        1.2,
    ),
    (
        "draftkings.nba.classic",
        [["PG"], ["PG", "SG"], ["SG"], ["SF"], ["SF", "PF"], ["PF"], ["C"], ["C"], ["PG"]],
        1.0,
    ),
    ("draftkings.nhl.classic", [["C"]] * 3 + [["W"]] * 4 + [["D"]] * 3 + [["G"]] * 2, 1.0),
    ("fanduel.nhl.classic", [["C"]] * 3 + [["W"]] * 3 + [["D"]] * 3 + [["G"]] * 2, 1.1),
]


@pytest.mark.parametrize("rid,positions,scale", CASES)
@pytest.mark.parametrize("seed", range(3))
def test_solver_matches_brute_force(rid, positions, scale, seed):
    rs = get_ruleset(rid)
    pool = _pool(seed, positions, scale)
    res = optimize(rs, pool, parse_constraints({}, rs, pool))
    expected = _brute(rs, pool)
    if expected is None:
        assert res["status"] == "infeasible"
    else:
        assert res["status"] == "optimal"
        assert res["lineups"][0]["projection"] == pytest.approx(expected, abs=1e-6)


def test_nba_and_nhl_are_research_only_never_money_ready():
    rows = {(r["platform"], r["sport"]): r for r in capability_matrix() if r["format"] == "classic"}
    for sport in ("nba", "nhl"):
        for platform in ("draftkings", "fanduel"):
            assert rows[(platform, sport)]["readiness"] == "research_only"
            rs = get_ruleset(f"{platform}.{sport}.classic")
            assert rs.verification["state"] == "unverified" and rs.verification["blocker"]


DK_HEAD = "Position,Name + ID,Name,ID,Roster Position,Salary,Game Info,TeamAbbrev,AvgPointsPerGame"


def test_a_dk_nba_file_now_builds_and_its_roster_slots_are_cross_checked():
    rows = [
        ("PG", "PG/G/UTIL", "AAA"),
        ("PG/SG", "PG/SG/G/UTIL", "AAA"),
        ("SF", "SF/F/UTIL", "BBB"),
        ("PF/C", "PF/C/F/UTIL", "BBB"),
    ]
    text = (
        DK_HEAD
        + "\n"
        + "\n".join(
            f"{p},X ({i}),Syn {i},{i},{r},5000,AAA@BBB 10/22/2026 07:30PM ET,{t},1.0"
            for i, (p, r, t) in enumerate(rows, start=700)
        )
    )
    slate, rs, extra = canonical_from_platform_file(text, ("draftkings", "nba", "classic"))
    assert rs.key == "draftkings.nba.classic@2026.1"
    assert extra["eligibilityCrossCheck"]["state"] == "agrees"
    assert slate.athletes[1].positions == ["PG", "SG"]


def test_multi_position_player_fills_one_slot_only():
    rs = get_ruleset("draftkings.nba.classic")
    pool = _pool(
        9, [["PG"], ["PG", "SG"], ["SG"], ["SF"], ["SF", "PF"], ["PF"], ["C"], ["C"], ["PG"]], 1.0
    )
    res = optimize(rs, pool, parse_constraints({}, rs, pool))
    if res["built"]:
        ids = [p["playerId"] for p in res["lineups"][0]["players"]]
        assert len(ids) == len(set(ids)) == 8
    else:
        assert res["status"] == "infeasible"


def test_exactly_n_lineups_on_a_new_sport():
    rs = get_ruleset("fanduel.nhl.classic")
    pool = _pool(3, [["C"]] * 5 + [["W"]] * 5 + [["D"]] * 5 + [["G"]] * 3, 1.0)
    res = optimize(rs, pool, parse_constraints({"lineups": 4, "minUnique": 2}, rs, pool))
    assert res["built"] == 4 or res["shortfall"]["conflict"]["state"] in (
        "isolated",
        "rules_or_pool",
    )
    for a, b in itertools.combinations(
        [set(p["playerId"] for p in lu["players"]) for lu in res["lineups"]], 2
    ):
        assert len(a - b) >= 2


def test_parity_cases_are_not_vacuous():
    """The parity test above also 'passes' when both sides say infeasible.
    Measured 2026-09-30: an over-cap salary range made all 12 cases vacuous.
    Require that the cases genuinely exercise feasible optima."""
    feasible = sum(
        _brute(get_ruleset(rid), _pool(seed, positions, scale)) is not None
        for rid, positions, scale in CASES
        for seed in range(3)
    )
    assert feasible == len(CASES) * 3


def test_dk_mma_matches_brute_force_and_imposes_no_unverified_bout_rule():
    rs = get_ruleset("draftkings.mma.classic")
    rnd = random.Random(77)
    pool = []
    for bout in range(6):
        for corner in ("A", "B"):
            pid = f"{bout}{corner}"
            pool.append(
                SlateAthlete(
                    player_id=f"70{bout}{'1' if corner == 'A' else '2'}",
                    name=f"Syn Fighter {pid}",
                    positions=["F"],
                    team=f"F{pid}",
                    opponent=f"F{bout}{'B' if corner == 'A' else 'A'}",
                    game=f"F{bout}A@F{bout}B",
                    salary=rnd.randrange(60, 100) * 100,
                    projection=round(rnd.uniform(20, 110), 2),
                )
            )
    res = optimize(rs, pool, parse_constraints({}, rs, pool))
    best = None
    for combo in itertools.combinations(pool, 6):
        if sum(a.salary for a in combo) <= rs.salary_cap:
            tot = round(sum(a.projection for a in combo), 2)
            best = tot if best is None or tot > best else best
    assert best is not None and res["status"] == "optimal"
    assert res["lineups"][0]["projection"] == pytest.approx(best, abs=1e-6)
    # The owner CAN impose a same-bout exclusion with a conditional rule.
    a, b = pool[0].player_id, pool[1].player_id
    c = parse_constraints({"conditionals": [{"when": [a], "then": [b], "thenMax": 0}]}, rs, pool)
    ids = {p["playerId"] for p in optimize(rs, pool, c)["lineups"][0]["players"]}
    assert not {a, b} <= ids


def test_nhl_skater_4_3_stack_matches_brute_force_both_ways():
    """A 4-3 skater stack: one team with 4+ skaters and a second team with 3+.

    Exercised on seeds where it is infeasible (reported, never relaxed) AND
    where it binds (costs points versus the free optimum) — neither vacuous.
    """
    rs = get_ruleset("draftkings.nhl.classic")
    skaters = ["C", "W", "D"]
    outcomes = set()
    for seed in range(3):
        pool = _pool(seed, [["C"]] * 3 + [["W"]] * 4 + [["D"]] * 3 + [["G"]] * 2, 1.0)
        c = parse_constraints(
            {
                "teamStacks": [
                    {"scope": "team", "size": 4, "count": 1, "positions": skaters},
                    {"scope": "team", "size": 3, "count": 2, "positions": skaters},
                ]
            },
            rs,
            pool,
        )
        res = optimize(rs, pool, c)
        expected = _brute(rs, pool, c)
        if expected is None:
            assert res["status"] == "infeasible"
            assert res["shortfall"]["conflict"]["state"] == "isolated"
            outcomes.add("infeasible")
            continue
        assert res["status"] == "optimal"
        assert res["lineups"][0]["projection"] == pytest.approx(expected, abs=1e-6)
        if expected < _brute(rs, pool):
            outcomes.add("binding")
    assert outcomes == {"infeasible", "binding"}
