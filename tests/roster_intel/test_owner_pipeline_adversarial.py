"""The owner pipeline, attacked rather than described.

    actual lineup config → solve starters → fill FLEX/SF/IDP_FLEX
      → remove starters → reserve demand → meaningful core
      → Team Strength / Weakness

Two properties have to hold no matter what is thrown at it:

**No player can be counted twice.**  Not across starter/reserve, not
across position groups, not through a flex slot, not through the
Superflex fold, and not by being both seated and reported unfilled.

**No alternate production path can bypass the chain.**  A second way to
compute any link is how two answers to one question survive, and this
lane exists because there were five.

Randomised over seeded rosters and league shapes — including
non-laminar flex sets and configured eligibility — because the failure
mode is set-dependent and a hand-picked fixture is exactly what it
hides behind.
"""

from __future__ import annotations

import ast
import pathlib
import random

import pytest

from src.roster_intel.core import build_meaningful_core, reserve_demand
from src.roster_intel.strength import build_team_strength
from src.roster_intel.weakness import build_position_ranks, build_team_weakness
from src.ros.lineup import RosterPlayer

REPO = pathlib.Path(__file__).resolve().parents[2]

_POSITIONS = ["QB", "RB", "WR", "TE", "DL", "LB", "DB", "K", "MLB", "EDGE", "FS"]

_LEAGUE_SHAPES = [
    ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"],
    ["QB", "RB", "WR", "TE", "FLEX", "FLEX", "IDP_FLEX", "DL", "LB", "DB"],
    # Non-laminar: REC_FLEX (WR/TE) beside FLEX (RB/WR/TE) — the shape a
    # slot-ordered greedy silently gets wrong.
    ["QB", "RB", "WR", "FLEX", "REC_FLEX", "WR_RB_FLEX"],
    ["QB", "QB", "SUPER_FLEX", "DL", "DL", "LB", "DB", "IDP_FLEX", "K"],
    ["QB", "FLEX"],
]

_ELIGIBILITIES = [
    None,
    {"FLEX": ("WR", "TE")},
    {"FLEX": ("RB",), "IDP_FLEX": ("LB", "DB")},
    {"SUPER_FLEX": ("QB",)},
]


def _roster(rng, size):
    pool = []
    for i in range(size):
        pos = rng.choice(_POSITIONS)
        # ~12% unpriced, so the UNKNOWN path is exercised throughout.
        value = None if rng.random() < 0.12 else round(rng.uniform(0.0, 1000.0), 2)
        pool.append(
            RosterPlayer(
                player_id=f"p{i}",
                canonical_name=f"p{i}",
                position=pos,
                ros_value=value,
                fantasy_positions=(("DL", "LB") if pos == "EDGE" and i % 3 == 0 else ()),
            )
        )
    return pool


def _cases(n=180):
    rng = random.Random(20260819)
    for _ in range(n):
        yield (
            _roster(rng, rng.randint(0, 30)),
            rng.choice(_LEAGUE_SHAPES),
            rng.choice(_ELIGIBILITIES),
        )


# ══ Nobody is counted twice ════════════════════════════════════════


def test_no_player_appears_twice_in_the_core_under_any_shape():
    for pool, slots, eligibility in _cases():
        core = build_meaningful_core(pool, slots, slot_eligibility=eligibility)
        ids = [m.player_id for m in core.members]
        assert len(ids) == len(set(ids)), (slots, eligibility, ids)


def test_starters_and_reserves_are_disjoint_and_exhaust_the_core():
    for pool, slots, eligibility in _cases():
        core = build_meaningful_core(pool, slots, slot_eligibility=eligibility)
        starters = {m.player_id for m in core.members if m.role == "starter"}
        reserves = {m.player_id for m in core.members if m.role == "reserve"}
        assert not (starters & reserves)
        assert starters | reserves == set(core.core_ids)


def test_a_seated_player_is_never_also_reported_unpriced_or_unfilled():
    """Being in the lineup and being unpriceable are mutually exclusive,
    and a filled slot cannot also be unfilled."""
    for pool, slots, eligibility in _cases():
        core = build_meaningful_core(pool, slots, slot_eligibility=eligibility)
        seated = {m.player_id for m in core.members}
        assert not (seated & set(core.unpriced_ids))
        filled = [m.slot for m in core.members if m.role == "starter"]
        for slot in core.unfilled_starter_slots:
            assert filled.count(slot) < slots.count(slot) if slot in slots else True


def test_the_core_never_exceeds_the_ceiling_the_demand_declares():
    for pool, slots, eligibility in _cases():
        core = build_meaningful_core(pool, slots, slot_eligibility=eligibility)
        demand = reserve_demand(slots, slot_eligibility=eligibility)
        ceiling = len([s for s in slots if s]) + demand.total()
        assert len(core.members) <= ceiling, (slots, eligibility, len(core.members), ceiling)


def test_the_superflex_fold_does_not_double_count_a_quarterback():
    """The one place a player could be counted twice by ARITHMETIC: SF
    adds QB demand, and the SF starter also leaves the pool."""
    pool = [RosterPlayer(f"QB{i}", f"QB{i}", "QB", 900.0 - i * 10) for i in range(5)]
    slots = ["QB", "SUPER_FLEX"]
    core = build_meaningful_core(pool, slots, config={"reserveMultiplier": 1.5})
    ids = [m.player_id for m in core.members]
    assert len(ids) == len(set(ids))
    # 1 QB + 1 SF -> basis 2 -> ceil(1.5*2)=3 meaningful QBs: two seated
    # as starters, one as the reserve.
    assert len(ids) == 3
    assert sum(1 for m in core.members if m.role == "starter") == 2


def test_team_strength_sums_each_core_member_exactly_once():
    for pool, slots, eligibility in _cases(60):
        core = build_meaningful_core(pool, slots, slot_eligibility=eligibility)
        strength = build_team_strength(core)
        assert strength.total == pytest.approx(sum(m.value for m in core.members))
        grouped = sum(g.value for g in strength.by_position.values())
        assert grouped == pytest.approx(strength.total)


def test_weakness_rungs_never_credit_one_player_to_two_positions():
    ranks = build_position_ranks(
        [(f"p{i}", p, 1000.0 - i) for i, p in enumerate(_POSITIONS * 4)], population="t"
    )
    for pool, slots, eligibility in _cases(60):
        core = build_meaningful_core(pool, slots, slot_eligibility=eligibility)
        weakness = build_team_weakness(core, ranks, team_count=12)
        seen: dict[str, str] = {}
        for position, need in weakness.by_position.items():
            for rung in need.rungs:
                if not rung.player_id:
                    continue
                assert seen.setdefault(rung.player_id, position) == position, rung.player_id


# ══ Nothing bypasses the chain ═════════════════════════════════════


_CHAIN = ("core.py", "strength.py", "weakness.py", "age_portfolio.py", "simulation.py")


def test_only_the_core_owner_solves_a_lineup():
    """``assign_lineup`` / ``solve_optimal_assignment`` may be called by
    the core and by the droppability adapter's feasibility guard — and
    by nothing else in the chain. A second solve is a second answer."""
    callers = {}
    for path in sorted((REPO / "src/roster_intel").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "assign_lineup(" in source or "solve_optimal_assignment(" in source:
            callers[path.name] = True
    assert set(callers) <= {"core.py", "marginal.py"}, callers


def test_the_chain_derives_reserve_demand_in_exactly_one_place():
    hits = [
        p.name
        for p in sorted((REPO / "src/roster_intel").glob("*.py"))
        if "math.ceil" in p.read_text(encoding="utf-8")
    ]
    assert hits == ["core.py"], hits


def test_no_chain_module_selects_a_roster_population_with_a_private_top_n():
    """The rule the lane brief names: consumers must not invent their own
    top-N. A sliced sort over players is what that looks like."""
    for name in _CHAIN:
        source = (REPO / "src/roster_intel" / name).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
                body = node.body
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                ):
                    body[0].value.value = ""
        stripped = ast.unparse(tree)
        assert "TOP_N" not in stripped, name
        assert "[:12]" not in stripped and "[:24]" not in stripped, name


def test_every_chain_output_is_reachable_only_through_build_meaningful_core():
    """Strength, weakness and the age portfolio all take a
    ``MeaningfulCore`` — none accepts a raw pool, so none can be handed a
    population selected some other way."""
    import inspect

    from src.roster_intel.age_portfolio import build_age_portfolio
    from src.roster_intel.strength import build_team_strength as bts
    from src.roster_intel.weakness import build_team_weakness as btw

    for fn in (bts, btw, build_age_portfolio):
        first = list(inspect.signature(fn).parameters.values())[0]
        assert first.name == "core", (fn.__name__, first.name)
