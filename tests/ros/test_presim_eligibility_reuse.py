"""The best-ball presim derives slot eligibility once per pool shape.

Performance repair, 2026-10-27 (Workstream H): the presim re-solved one
roster's pool up to ``BEST_BALL_PRESIM_MAX_WEEKS`` times and re-derived slot
eligibility on every solve, though eligibility depends only on position /
fantasy positions and never on the drawn points.  That was ~85% of the live
canonical forecast's CPU time.  These tests pin the two properties the
repair must keep:

* the answer is IDENTICAL to the per-call derivation (same draws, same
  lineups, same means and standard deviations, bit for bit);
* the derivation runs once per distinct pool shape, not once per solve.
"""

from __future__ import annotations

import random

import pytest

from src.ros import lineup, playoff_sim

SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "DL", "LB", "DB", "IDP_FLEX"]


def _p(pid, pos, ros, fpos=None):
    return {
        "playerId": pid,
        "canonicalName": pid,
        "position": pos,
        "rosValue": ros,
        "fantasyPositions": list(fpos or [pos]),
    }


def _roster(prefix: str) -> dict:
    players = [
        _p(f"{prefix}qb1", "QB", 8000.0),
        _p(f"{prefix}qb2", "QB", 3500.0),
        _p(f"{prefix}rb1", "RB", 5000.0),
        _p(f"{prefix}rb2", "RB", 3000.0),
        _p(f"{prefix}rb3", "RB", 1500.0),
        _p(f"{prefix}wr1", "WR", 6000.0),
        _p(f"{prefix}wr2", "WR", 4000.0),
        _p(f"{prefix}wr3", "WR", 2000.0),
        _p(f"{prefix}te1", "TE", 3000.0),
        _p(f"{prefix}te2", "TE", 900.0),
        # A hybrid IDP — eligibility over fantasyPositions is the part the
        # precompute must reproduce exactly.
        _p(f"{prefix}edge", "DL", 2500.0, ["DL", "LB"]),
        _p(f"{prefix}lb1", "LB", 2200.0),
        _p(f"{prefix}db1", "DB", 1800.0),
        _p(f"{prefix}db2", "DB", 1200.0),
        _p(f"{prefix}zero", "WR", 0.0),  # unpriced: never enters the pool
    ]
    return {"starters": players[:8], "bench": players[8:]}


ROSTERS = {"a": _roster("a_"), "b": _roster("b_")}
WEEKS = list(range(8, 15))
UNAVAILABLE = {("a_qb1", 9), ("a_qb1", 10), ("b_wr1", 12), ("b_edge", 8)}


def _uncached_presim(monkeypatch, *, weeks=None, unavailable=None):
    """The presim exactly as it ran before the repair: every solve derives
    eligibility itself (no cache handed to the weekly scorer)."""
    original = playoff_sim._bestball_weekly_score

    def per_call(pool, slots, rng, model=None, eligibility_cache=None):
        return original(pool, slots, rng, model, None)

    monkeypatch.setattr(playoff_sim, "_bestball_weekly_score", per_call)
    try:
        return playoff_sim._bestball_presim(
            ROSTERS, SLOTS, random.Random(20260428), weeks=weeks, unavailable=unavailable
        )
    finally:
        monkeypatch.setattr(playoff_sim, "_bestball_weekly_score", original)


@pytest.mark.parametrize(
    ("weeks", "unavailable"),
    [(None, None), (WEEKS, set()), (WEEKS, UNAVAILABLE)],
    ids=["no_calendar", "calendar", "calendar_with_absences"],
)
def test_reuse_is_bit_identical_to_per_call_derivation(monkeypatch, weeks, unavailable):
    cached = playoff_sim._bestball_presim(
        ROSTERS, SLOTS, random.Random(20260428), weeks=weeks, unavailable=unavailable
    )
    per_call = _uncached_presim(monkeypatch, weeks=weeks, unavailable=unavailable)
    assert cached == per_call  # exact float equality, not approximate
    assert set(cached) == {"a", "b"}


def test_eligibility_derived_once_per_pool_shape(monkeypatch):
    calls: list[int] = []
    real = playoff_sim.precompute_slot_eligibility

    def counting(pool, slots, **kw):
        calls.append(len(pool))
        return real(pool, slots, **kw)

    monkeypatch.setattr(playoff_sim, "precompute_slot_eligibility", counting)
    out = playoff_sim._bestball_presim(
        ROSTERS, SLOTS, random.Random(3), weeks=WEEKS, unavailable=UNAVAILABLE
    )
    assert set(out) == {"a", "b"}
    # Team a: full pool + one without a_qb1 (weeks 9, 10).  Team b: full
    # pool + one without b_wr1 + one without b_edge.  Five shapes, however
    # many hundred weeks were drawn.
    assert len(calls) == 5


def test_pool_with_conflicting_duplicate_id_is_solved_the_ordinary_way():
    # One id carried with two position shapes is outside the precompute's
    # contract (its map is left untagged), so the weekly scorer must not
    # hand it to the solver — the answer equals the per-call derivation.
    pool = [
        _p("dup", "QB", 5000.0),
        _p("dup", "WR", 4000.0),
        _p("rb", "RB", 3000.0),
    ]
    slots = ["QB", "WR", "RB"]
    cache: dict = {}
    for seed in range(20):
        with_cache = playoff_sim._bestball_weekly_score(
            pool, slots, random.Random(seed), None, cache
        )
        without = playoff_sim._bestball_weekly_score(pool, slots, random.Random(seed))
        assert with_cache == without
    assert list(cache.values()) == [False]


def test_precompute_contract_still_matches_fresh_derivation():
    """The solver-side equivalence the repair relies on: a tagged
    precomputed map gives the same assignment as deriving it per call."""
    pool = [
        lineup.RosterPlayer(
            player_id=p["playerId"],
            canonical_name=p["canonicalName"],
            position=p["position"],
            ros_value=float(p["rosValue"]) + i * 0.5,
            fantasy_positions=tuple(p["fantasyPositions"]),
        )
        for i, p in enumerate(ROSTERS["a"]["starters"] + ROSTERS["a"]["bench"])
        if p["rosValue"] > 0
    ]
    pre = lineup.precompute_slot_eligibility(pool, SLOTS)
    assert pre.derived_for is not None
    fresh = lineup.solve_optimal_assignment(pool, SLOTS)
    reused = lineup.solve_optimal_assignment(pool, SLOTS, precomputed_eligibility=pre)
    assert {i: p.player_id for i, p in fresh.items()} == {i: p.player_id for i, p in reused.items()}
