"""Weekly streaming solver: exactness against a brute-force oracle, plus contracts.

The oracle enumerates EVERY add set and drop set on small random instances and
applies the module's stated problem (capacity, legality, FAAB, dynasty budget,
every add starts, tie order).  The solver must return the same plan whenever it
reports ``optimal``.  The oracle applies no candidate filter and no bound, so every cut the solver
makes is checked rather than assumed, in one and two weeks, with and without
the dynasty budget.
"""

from __future__ import annotations

import itertools
import random

import pytest

from src.waivers import streaming_solver as ss

SLOTS = ("DL", "LB", "LB", "DB", "IDP_FLEX")
POSITIONS = ("DL", "LB", "DB")


def _p(pid, pos, pts, dyn=100.0, bid=0, fp=()):
    if not isinstance(pts, tuple):
        pts = (pts,)
    return ss.StreamPlayer(
        player_id=pid,
        name=pid,
        position=pos,
        weekly_points=pts,
        dynasty_value=dyn,
        bid=bid,
        fantasy_positions=fp,
    )


def _inp(roster, fas, *, droppable, open_spots=0, k=3, balance=100, beta=0.0, weights=(1.0,), **kw):
    return ss.SolverInput(
        roster=tuple(roster),
        free_agents=tuple(fas),
        slots=SLOTS,
        droppable_ids=frozenset(droppable),
        open_spots=open_spots,
        max_adds=k,
        faab_balance=balance,
        dynasty_budget=beta,
        week_weights=weights,
        **kw,
    )


# ── oracle ───────────────────────────────────────────────────────────


def _oracle(inp: ss.SolverInput):
    ev = ss._Evaluator(inp)
    roster = frozenset(p.player_id for p in inp.roster)
    base = ev.value(roster)
    base_fill = ev.fill(roster)
    players = ev.players
    best = None
    fas = [p.player_id for p in inp.free_agents]
    drops_pool = sorted(i for i in inp.droppable_ids if i in roster)
    for na in range(0, inp.max_adds + 1):
        for adds in itertools.combinations(sorted(fas), na):
            bid = sum(players[a].bid for a in adds)
            if inp.faab_balance is None and bid > 0:
                continue
            if inp.faab_balance is not None and bid > inp.faab_balance:
                continue
            if any(all(w is None for w in players[a].weekly_points) for a in adds):
                continue
            for nd in range(0, len(drops_pool) + 1):
                if na - nd > inp.open_spots:
                    continue
                for drops in itertools.combinations(drops_pool, nd):
                    if nd > max(0, na - inp.open_spots):
                        continue  # the solver drops exactly the forced count
                    final = (roster | set(adds)) - set(drops)
                    if ev.fill(final) < base_fill:
                        continue
                    v = ev.value(final)
                    if not all(v > ev.value(final - {a}) + 1e-9 for a in adds):
                        continue
                    loss = sum(ss._dyn(players[d]) for d in drops) - sum(
                        ss._dyn(players[a]) for a in adds
                    )
                    if loss > inp.dynasty_budget + 1e-9:
                        continue
                    if not adds:
                        continue
                    plan = ss.StreamPlan(
                        adds=tuple(sorted(adds)),
                        drops=tuple(sorted(drops)),
                        weekly_gain=v - base,
                        gain_by_week=(),
                        net_dynasty_loss=loss,
                        faab_total=bid,
                    )
                    if best is None or plan.key() < best.key():
                        best = plan
    return best


def _random_instance(rng: random.Random, weeks: int = 1):
    def pts(hi):
        out = tuple(
            round(rng.uniform(0, hi), 1) if rng.random() > 0.1 else None for _ in range(weeks)
        )
        return out if weeks > 1 else out[0]

    roster = []
    for i in range(rng.randint(4, 7)):
        pos = rng.choice(POSITIONS)
        roster.append(_p(f"r{i}", pos, pts(15), dyn=float(rng.randint(50, 900))))
    fas = []
    for i in range(rng.randint(2, 6)):
        pos = rng.choice(POSITIONS)
        dyn = float(rng.randint(10, 600)) if rng.random() > 0.2 else None
        fas.append(_p(f"f{i}", pos, pts(18), dyn=dyn, bid=rng.choice([0, 0, 0, 5, 20])))
    droppable = [p.player_id for p in roster if rng.random() < 0.6]
    return _inp(
        roster,
        fas,
        droppable=droppable,
        open_spots=rng.choice([0, 0, 1]),
        k=rng.randint(1, 3),
        balance=rng.choice([0, 10, 100]),
        beta=rng.choice([0.0, 0.0, 200.0, 10_000.0]),
        weights=(1.0,) if weeks == 1 else tuple(round(1.0 - 0.15 * w, 2) for w in range(weeks)),
    )


def _assert_matches_oracle(inp):
    res = ss.solve_streaming(inp)
    want = _oracle(inp)
    assert res.status == ss.STATUS_OPTIMAL
    got = res.best if res.recommend_move else None
    if want is None or want.weekly_gain <= 1e-9:
        assert got is None
    else:
        assert got is not None, f"oracle found {want}"
        assert got.weekly_gain == pytest.approx(want.weekly_gain)
        assert got.net_dynasty_loss == pytest.approx(want.net_dynasty_loss)
        assert (got.adds, got.drops) == (want.adds, want.drops)
    # The larger-budget comparison is exact too.
    free = _oracle(ss.SolverInput(**{**inp.__dict__, "dynasty_budget": 1e18}))
    shown = res.best_unbudgeted or got
    if free is None or free.weekly_gain <= 1e-9:
        assert shown is None
    else:
        assert res.unbudgeted_status == ss.STATUS_OPTIMAL
        assert shown is not None and shown.weekly_gain == pytest.approx(free.weekly_gain)


@pytest.mark.parametrize("seed", range(150))
def test_matches_brute_force_oracle(seed):
    _assert_matches_oracle(_random_instance(random.Random(seed)))


@pytest.mark.parametrize("seed", range(60))
def test_matches_brute_force_oracle_over_two_weeks(seed):
    _assert_matches_oracle(_random_instance(random.Random(50_000 + seed), weeks=2))


# ── behaviour ────────────────────────────────────────────────────────


def _base_roster():
    return [
        _p("dl1", "DL", 8.0, dyn=900),
        _p("lb1", "LB", 9.0, dyn=1500),
        _p("lb2", "LB", 4.0, dyn=200),  # low-value veteran starter
        _p("db1", "DB", 7.0, dyn=800),
        _p("flex", "LB", 3.0, dyn=150),
    ]


def test_obvious_streamer_swaps_the_weak_starter():
    roster = _base_roster()
    fas = [_p("fa_lb", "LB", 10.0, dyn=180)]
    res = ss.solve_streaming(_inp(roster, fas, droppable=["lb2", "flex"], k=1))
    assert res.recommend_move
    # Releasing the 3.0 flex costs the lineup 3 points; releasing the 4.0
    # starter costs 4 but only after the 3.0 flex slides in.  The solver
    # finds the larger net gain and the dynasty budget (0) is respected.
    assert res.best.adds == ("fa_lb",)
    assert res.best.drops == ("flex",)
    assert res.best.weekly_gain == pytest.approx(10.0 - 3.0)
    assert res.best.net_dynasty_loss <= 0.0


def test_protected_player_is_never_dropped():
    roster = _base_roster()
    fas = [_p("fa_lb", "LB", 10.0, dyn=10)]
    res = ss.solve_streaming(_inp(roster, fas, droppable=[], k=1))
    assert not res.recommend_move
    assert res.best is None


def test_dynasty_budget_blocks_and_unbudgeted_reports_the_price():
    roster = _base_roster()
    fas = [_p("fa_lb", "LB", 10.0, dyn=0)]
    res = ss.solve_streaming(_inp(roster, fas, droppable=["flex"], k=1, beta=0.0))
    assert not res.recommend_move  # dropping flex (150) for a 0-value add loses 150
    assert res.best_unbudgeted is not None
    assert res.best_unbudgeted.net_dynasty_loss == pytest.approx(150.0)
    res2 = ss.solve_streaming(_inp(roster, fas, droppable=["flex"], k=1, beta=150.0))
    assert res2.recommend_move and res2.best.drops == ("flex",)


def test_no_move_when_gain_below_materiality():
    roster = _base_roster()
    fas = [_p("fa_lb", "LB", 3.5, dyn=180)]
    res = ss.solve_streaming(_inp(roster, fas, droppable=["flex"], k=1, materiality=2.0))
    assert not res.recommend_move
    assert res.best is None
    assert res.alternatives and res.alternatives[0].weekly_gain == pytest.approx(0.5)


def test_unprojected_free_agent_is_excluded_never_zero():
    roster = _base_roster()
    fas = [_p("fa_x", "LB", None, dyn=50)]
    res = ss.solve_streaming(_inp(roster, fas, droppable=["flex"], k=1))
    assert res.excluded_free_agents == {"fa_x": "unprojected"}
    assert not res.recommend_move


def test_multiple_moves_never_reuse_a_drop_and_respect_faab():
    roster = _base_roster()
    fas = [
        _p("fa_lb", "LB", 10.0, dyn=300, bid=30),
        _p("fa_db", "DB", 9.0, dyn=300, bid=30),
        _p("fa_dl", "DL", 12.0, dyn=300, bid=50),
    ]
    res = ss.solve_streaming(_inp(roster, fas, droppable=["flex", "lb2"], k=3, balance=60))
    assert res.recommend_move
    assert len(set(res.best.drops)) == len(res.best.drops)
    assert res.best.faab_total <= 60
    assert len(res.best.adds) - len(res.best.drops) <= 0


def test_multiweek_horizon_sums_weighted_weeks():
    roster = [_p("lb1", "LB", (5.0, 5.0)), _p("lb2", "LB", (2.0, 2.0)), _p("db1", "DB", (5.0, 5.0))]
    fas = [_p("fa", "LB", (0.0, 9.0), dyn=500)]  # bye this week, strong next week
    slots_inp = ss.SolverInput(
        roster=tuple(roster),
        free_agents=tuple(fas),
        slots=("LB", "LB", "DB"),
        droppable_ids=frozenset({"lb2"}),
        open_spots=0,
        max_adds=1,
        faab_balance=100,
        week_weights=(1.0, 1.0),
    )
    res = ss.solve_streaming(slots_inp)
    assert res.recommend_move
    assert res.best.gain_by_week == pytest.approx((-2.0, 7.0))
    assert res.best.weekly_gain == pytest.approx(5.0)


def test_capacity_curve_has_diminishing_steps_and_recommended_k():
    roster = _base_roster()
    fas = [
        _p("a", "LB", 10.0, dyn=300),
        _p("b", "DB", 9.0, dyn=300),
        _p("c", "DL", 8.5, dyn=300),
    ]
    rows = ss.capacity_curve(_inp(roster, fas, droppable=["flex", "lb2"], k=7), max_k=4)
    gains = [r["bestGainPoints"] for r in rows]
    assert gains == sorted(gains)
    assert rows[0]["bestGainPoints"] == 0.0
    k = ss.recommended_capacity(rows, materiality=1.0)
    assert 0 <= k <= 4
    assert all(r["marginalGainPoints"] >= 1.0 for r in rows[1 : k + 1])


def test_deterministic():
    inp = _random_instance(random.Random(7))
    a = ss.solve_streaming(inp).to_dict()
    b = ss.solve_streaming(inp).to_dict()
    assert a == b


def test_node_limit_is_reported_never_passed_off_as_optimal():
    rng = random.Random(3)
    roster = [_p(f"r{i}", rng.choice(POSITIONS), rng.uniform(0, 10)) for i in range(8)]
    fas = [_p(f"f{i}", rng.choice(POSITIONS), rng.uniform(5, 15), dyn=1000) for i in range(12)]
    inp = _inp(roster, fas, droppable=[p.player_id for p in roster], k=4, node_limit=5)
    res = ss.solve_streaming(inp)
    assert res.status == ss.STATUS_BOUNDED
    assert any("node_limit" in n for n in res.notes)


def test_negative_budget_refused():
    with pytest.raises(ValueError):
        ss.solve_streaming(_inp(_base_roster(), [], droppable=[], beta=-1.0))


# ── bounded results, side search, capacity curve ─────────────────────


def _larger_instance(seed=11, n_fa=40, k=4):
    rng = random.Random(seed)
    roster = [
        _p(f"r{i}", rng.choice(POSITIONS), round(rng.uniform(2, 14), 1), dyn=rng.randint(100, 3000))
        for i in range(14)
    ]
    fas = [
        _p(f"f{i}", rng.choice(POSITIONS), round(rng.uniform(0, 15), 1), dyn=rng.randint(0, 900))
        for i in range(n_fa)
    ]
    droppable = [p.player_id for p in sorted(roster, key=lambda p: p.dynasty_value)[:8]]
    return _inp(roster, fas, droppable=droppable, k=k, beta=0.0)


def test_bounded_gap_is_a_ceiling_on_the_true_optimum():
    inp = _larger_instance()
    exact = ss.solve_streaming(inp)
    assert exact.status == ss.STATUS_OPTIMAL
    cut = ss.solve_streaming(ss.SolverInput(**{**inp.__dict__, "node_limit": 3}))
    assert cut.status == ss.STATUS_BOUNDED
    found = cut.best.weekly_gain if cut.best else 0.0
    assert cut.bound_gap is not None
    assert exact.best.weekly_gain <= found + cut.bound_gap + 1e-6


def test_side_search_limit_never_makes_the_main_answer_bounded(monkeypatch):
    inp = _larger_instance()
    monkeypatch.setattr(ss, "UNBUDGETED_NODE_SHARE", 1e-9)
    res = ss.solve_streaming(inp)
    assert res.status == ss.STATUS_OPTIMAL
    assert res.unbudgeted_status in (ss.STATUS_OPTIMAL, ss.STATUS_BOUNDED)
    assert res.to_dict()["bestUnbudgetedStatus"] == res.unbudgeted_status
    off = ss.solve_streaming(inp, unbudgeted=False)
    assert off.unbudgeted_status is None and off.best_unbudgeted is None
    assert off.best == res.best


def test_capacity_curve_rows_equal_fresh_solves():
    inp = _larger_instance(k=7)
    rows = ss.capacity_curve(inp, max_k=5)
    for row in rows:
        fresh = ss.solve_streaming(
            ss.SolverInput(**{**inp.__dict__, "max_adds": row["capacity"], "materiality": 0.0}),
            unbudgeted=False,
        )
        gain = fresh.best.weekly_gain if fresh.best else 0.0
        assert row["bestGainPoints"] == pytest.approx(round(gain, 3))
        assert row["adds"] == (list(fresh.best.adds) if fresh.best else [])
        assert row["status"] == ss.STATUS_OPTIMAL


def test_negative_week_weight_refused():
    with pytest.raises(ValueError):
        ss.solve_streaming(_inp(_base_roster(), [], droppable=[], weights=(1.0, -0.5)))


# ── regions found by independent review ──────────────────────────────


def _wide_instance(rng: random.Random):
    """Ties, tight budgets, IDP flex, two-group players, zero-weight weeks,
    negative points, several open spots: the regions review fuzzed."""
    weeks = rng.choice([1, 1, 2, 3])
    slots = rng.choice(
        [SLOTS, ("DB",), ("DB", "IDP_FLEX"), ("LB", "LB", "IDP_FLEX"), ("DL", "LB", "DB")]
    )

    def pts():
        return tuple(
            None if rng.random() < 0.15 else float(rng.choice([-1, 0, 2, 3, 3, 5, 7, 9]))
            for _ in range(weeks)
        )

    def fp(pos):
        return rng.choice([(), (), (pos, "LB")]) if pos == "DL" else ()

    roster = []
    for i in range(rng.randint(2, 5)):
        pos = rng.choice(POSITIONS)
        roster.append(
            _p(f"r{i}", pos, pts(), dyn=float(rng.choice([0, 10, 50, 100, 500])), fp=fp(pos))
        )
    fas = []
    for i in range(rng.randint(1, 4)):
        pos = rng.choice(POSITIONS)
        fas.append(
            _p(
                f"f{i}",
                pos,
                pts(),
                dyn=rng.choice([None, 0.0, 10.0, 100.0]),
                bid=rng.choice([0, 0, 5, 10]),
                fp=fp(pos),
            )
        )
    droppable = [p.player_id for p in roster if rng.random() < 0.7]
    dyn_values = sorted({p.dynasty_value for p in roster if p.player_id in droppable})
    return ss.SolverInput(
        roster=tuple(roster),
        free_agents=tuple(fas),
        slots=slots,
        droppable_ids=frozenset(droppable),
        open_spots=rng.choice([0, 0, 1, 2, 3]),
        max_adds=rng.randint(1, 3),
        faab_balance=rng.choice([None, 0, 5, 100]),
        dynasty_budget=rng.choice([0.0, *dyn_values, 1e9]),
        week_weights=tuple(rng.choice([1.0, 0.5, 0.0]) for _ in range(weeks)),
    )


@pytest.mark.parametrize("seed", range(400))
def test_matches_brute_force_oracle_in_review_regions(seed):
    _assert_matches_oracle(_wide_instance(random.Random(90_000 + seed)))


def test_tight_budget_does_not_break_the_bound():
    # The Lagrangian multipliers ran away on an exactly tight budget and the
    # bound lost precision, pruning the optimum while reporting "optimal".
    roster = [_p("r0", "DL", (None,), dyn=50.0), _p("r3", "LB", (3.7,), dyn=500.0)]
    fas = [_p("f3", "DB", (9.3,), dyn=0.0)]
    inp = ss.SolverInput(
        roster=tuple(roster),
        free_agents=tuple(fas),
        slots=("DB",),
        droppable_ids=frozenset({"r0", "r3"}),
        open_spots=0,
        max_adds=1,
        faab_balance=0,
        dynasty_budget=50.0,
    )
    res = ss.solve_streaming(inp)
    assert res.recommend_move and res.best.adds == ("f3",) and res.best.drops == ("r0",)
    two = ss.SolverInput(
        roster=(_p("r0", "DL", (2.0, None), dyn=10.0), _p("r1", "DB", (2.0, 0.0), dyn=100.0)),
        free_agents=(_p("f1", "DB", (3.0, 3.0), dyn=0.0),),
        slots=("DB", "IDP_FLEX"),
        droppable_ids=frozenset({"r0", "r1"}),
        open_spots=0,
        max_adds=1,
        faab_balance=5,
        dynasty_budget=10.0,
        week_weights=(1.0, 1.0),
    )
    _assert_matches_oracle(two)
    assert ss.solve_streaming(two).best.drops == ("r0",)


def test_multiweek_does_not_drop_a_dominated_twin_that_matters():
    # b looks dominated by a1/a2, but {b, x} is the plan with the smaller
    # dynasty loss: x starts in week 2 only when b, not a twin, holds week 1.
    inp = ss.SolverInput(
        roster=(),
        free_agents=(
            _p("x", "LB", (None, 5.0), dyn=500.0),
            _p("b", "LB", (3.0, 2.0), dyn=10.0),
            _p("a1", "LB", (3.0, 5.0), dyn=10.0),
            _p("a2", "LB", (3.0, 5.0), dyn=10.0),
        ),
        slots=("LB",),
        droppable_ids=frozenset(),
        open_spots=2,
        max_adds=2,
        faab_balance=100,
        week_weights=(1.0, 1.0),
    )
    _assert_matches_oracle(inp)
    assert ss.solve_streaming(inp).best.adds == ("b", "x")


def test_negative_projections_are_floored_and_said():
    inp = ss.SolverInput(
        roster=(_p("r1", "LB", (3.0, -1.0, 3.0), dyn=0.0),),
        free_agents=(_p("f2", "LB", (3.0, None, 4.0), dyn=0.0),),
        slots=("LB",),
        droppable_ids=frozenset({"r1"}),
        open_spots=0,
        max_adds=1,
        faab_balance=0,
        week_weights=(0.5, 1.0, 0.0),
    )
    _assert_matches_oracle(inp)
    assert any("negative weekly projection" in n for n in ss.solve_streaming(inp).notes)


def test_equal_plans_prefer_the_cheaper_claim():
    inp = ss.SolverInput(
        roster=(),
        free_agents=(_p("f0", "DL", 2.0, dyn=100.0, bid=10), _p("f3", "DL", 2.0, dyn=100.0, bid=0)),
        slots=("IDP_FLEX",),
        droppable_ids=frozenset(),
        open_spots=2,
        max_adds=1,
        faab_balance=100,
        dynasty_budget=50.0,
    )
    _assert_matches_oracle(inp)
    assert ss.solve_streaming(inp).best.adds == ("f3",)
