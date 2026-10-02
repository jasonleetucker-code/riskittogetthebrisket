"""Field model: every lineup legal, targets approached measurably, assumptions switchable."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.dfs import field, ownership
from src.dfs.imports import apply_projection_csv, parse_draftkings_salaries
from src.dfs.optimizer import validate_lineup
from src.dfs.rules import get_ruleset

FIX = Path(__file__).parent / "fixtures"
DK = get_ruleset("draftkings.nfl.classic")
SLOTS = [s.name for s in DK.slots]


@pytest.fixture(scope="module")
def slate():
    athletes, _ = parse_draftkings_salaries(
        (FIX / "synthetic_dk_nfl_classic_salaries.csv").read_text(encoding="utf-8")
    )
    apply_projection_csv(
        athletes, (FIX / "synthetic_dk_nfl_classic_projections.csv").read_text(encoding="utf-8")
    )
    own = {k: v for k, v in ownership.structural_baseline(athletes, DK).items() if v is not None}
    return athletes, own


def test_every_generated_lineup_is_legal_and_uses_the_salary_floor(slate):
    athletes, own = slate
    res = field.generate(athletes, DK, own, sport="nfl", size=400, seed=1)
    by_id = {a.player_id: a for a in athletes}
    assert len(res.lineups) == 400 and res.exhausted == 0
    floor = field.DEFAULT_PARAMS["min_salary_share"] * DK.salary_cap
    for lu in res.lineups:
        assert not validate_lineup(list(zip(SLOTS, lu)), DK, by_id)
        assert sum(by_id[x].salary for x in lu) >= floor
    assert res.fit["salaryUsed"]["p10"] >= floor


def test_raking_closes_the_gap_to_a_feasible_target(slate):
    """Raking toward a target a legal field CAN realize (another field's frequencies)."""
    athletes, _ = slate
    alt = {
        k: v
        for k, v in ownership.structural_baseline(athletes, DK, {"bv": 2.5, "bp": 0.0}).items()
        if v
    }
    feasible = field.implied_ownership(
        athletes, DK, sport="nfl", weights=alt, size=4000, seed=77, params={"stack_strength": 0.0}
    )
    feasible = {k: v for k, v in feasible.items() if v > 0}
    one = field.generate(
        athletes,
        DK,
        feasible,
        sport="nfl",
        size=3000,
        seed=5,
        params={"rake_rounds": 1, "stack_strength": 0.0},
    )
    raked = field.generate(
        athletes,
        DK,
        feasible,
        sport="nfl",
        size=3000,
        seed=5,
        params={"rake_rounds": 4, "stack_strength": 0.0},
    )
    assert raked.fit["ownershipGap"]["mae"] < 0.6 * one.fit["ownershipGap"]["mae"]


def test_structural_targets_can_be_infeasible_and_the_gap_is_reported_not_hidden(slate):
    """Negative finding, pinned: the structural baseline ignores the salary cap, so
    its targets cannot all be realized together — the residual is reported."""
    athletes, own = slate
    res = field.generate(
        athletes, DK, own, sport="nfl", size=2000, seed=2, params={"rake_rounds": 4}
    )
    assert res.fit["ownershipGap"]["mae"] > 2.0


def test_implied_ownership_is_feasible_by_construction(slate):
    athletes, own = slate
    imp = field.implied_ownership(athletes, DK, sport="nfl", weights=own, size=2000, seed=3)
    by_id = {a.player_id: a for a in athletes}
    qb = sum(v for k, v in imp.items() if "QB" in by_id[k].positions)
    assert qb == pytest.approx(100.0, abs=1e-6) and sum(imp.values()) == pytest.approx(
        900.0, abs=0.01
    )


def test_stack_strength_is_a_real_switch(slate):
    athletes, own = slate
    by_id = {a.player_id: a for a in athletes}

    def qb_stack_share(res):
        n = 0
        for lu in res.lineups:
            qb = next(by_id[x] for x in lu if "QB" in by_id[x].positions)
            n += any(
                by_id[x].team == qb.team and set(by_id[x].positions) & {"WR", "TE"} for x in lu
            )
        return n / len(res.lineups)

    off = field.generate(
        athletes,
        DK,
        own,
        sport="nfl",
        size=800,
        seed=4,
        params={"stack_strength": 0.0, "rake_rounds": 1},
    )
    on = field.generate(
        athletes,
        DK,
        own,
        sport="nfl",
        size=800,
        seed=4,
        params={"stack_strength": 4.0, "rake_rounds": 1},
    )
    assert qb_stack_share(on) > qb_stack_share(off) + 0.05


def test_players_without_a_target_are_never_drafted_and_seeds_reproduce(slate):
    athletes, own = slate
    own = dict(own)
    dropped = next(k for k in own if by_pos(athletes, k) == "WR")
    del own[dropped]
    a = field.generate(athletes, DK, own, sport="nfl", size=200, seed=9)
    b = field.generate(athletes, DK, own, sport="nfl", size=200, seed=9)
    assert a.lineups == b.lineups
    assert all(dropped not in lu for lu in a.lineups)
    with pytest.raises(ValueError):
        field.generate(athletes, DK, own, sport="nfl", size=field.MAX_FIELD_SAMPLE + 1, seed=1)


def by_pos(athletes, pid):
    return next(a.positions[0] for a in athletes if a.player_id == pid)
