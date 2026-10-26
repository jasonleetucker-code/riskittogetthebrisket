"""Candidate D (``src/league_valuation/cross_position.py``): shadow, research only.

The lineup owner is injected, exactly as in production research code: the tests use
``src.ros.lineup.solve_optimal_assignment`` through a port, and check it against an
independent brute-force best-ball optimum on tiny leagues so a drift in either would
fail here.
"""

from __future__ import annotations

import math
import random

import pytest

from src.league_valuation import cross_position as cp
from src.league_valuation.replacement_shadow import LineupPlayer
from src.ros import lineup as lu


class Port:
    """The canonical lineup owner behind ``LineupPort`` (exact, no fallback)."""

    def solve(self, players, slots):
        pool = [
            lu.RosterPlayer(
                player_id=p.player_id,
                canonical_name=p.player_id,
                position=p.position,
                ros_value=float(p.points),
                fantasy_positions=tuple(p.fantasy_positions),
            )
            for p in players
        ]
        got = lu.solve_optimal_assignment(pool, list(slots), objective=lu.OBJECTIVE_REALIZED_POINTS)
        return {int(i): rp.player_id for i, rp in got.items()}

    def slot_family(self, slot):
        return lu.normalize_slot(slot)


PORT = Port()
SLOTS = ["QB", "RB", "FLEX"]
FLEX_OK = {"RB", "WR", "TE"}


def brute_force(players: list[LineupPlayer], slots: list[str]) -> float:
    """An independent exact best-ball optimum by enumeration (tiny leagues only).

    The host's rule: the lineup is a maximum-weight BASIS -- as many slots as can be
    filled are filled, even by a negative score -- so compare (filled, total) pairs.
    """

    def ok(slot: str, p: LineupPlayer) -> bool:
        return p.position in FLEX_OK if slot == "FLEX" else p.position == slot

    best: tuple[int, float] = (0, 0.0)

    def walk(i: int, used: frozenset[int], filled: int, total: float) -> None:
        nonlocal best
        if i == len(slots):
            if (filled, total) > best:
                best = (filled, total)
            return
        walk(i + 1, used, filled, total)  # leave the slot empty
        for j, p in enumerate(players):
            if j not in used and ok(slots[i], p):
                walk(i + 1, used | {j}, filled + 1, total + p.points)

    walk(0, frozenset(), 0, 0.0)
    return best[1]


def test_port_matches_an_independent_brute_force_optimum():
    rng = random.Random(5)
    for _ in range(40):
        players = [
            LineupPlayer(f"p{i}", rng.choice(["QB", "RB", "WR", "TE"]), (), rng.uniform(-2, 25))
            for i in range(rng.randint(2, 7))
        ]
        got = cp.lineup_total(
            PORT,
            SLOTS,
            [p.player_id for p in players],
            {p.player_id: p.points for p in players},
            {p.player_id: (p.position, ()) for p in players},
        )
        # a slot nobody eligible can fill scores nothing; negative scores are still started
        # when the slot can be filled (the host's best-ball rule)
        assert got == pytest.approx(brute_force(players, SLOTS))


# ── a hand-computed toy league ───────────────────────────────────────────────

POS = {"a1": "QB", "a2": "RB", "a3": "RB", "b1": "QB", "b2": "RB", "b3": "WR", "x": "RB"}
MU = {"a1": 20.0, "a2": 10.0, "a3": 8.0, "b1": 15.0, "b2": 12.0, "b3": 9.0, "x": 11.0}
TEAMS = {"A": ["a1", "a2", "a3"], "B": ["b1", "b2", "b3"]}


def toy_inputs(mu=None, availability=1.0, residual=0.0) -> cp.SimInputs:
    mu = dict(MU if mu is None else mu)
    return cp.SimInputs(
        mu=mu,
        availability={k: availability for k in mu},
        own_residuals={},
        pooled={"QB": (residual,), "RB": (residual,), "WR": (residual,)},
        stratum={k: POS[k] for k in mu},
        position={k: POS[k] for k in mu},
        fantasy_positions={k: () for k in mu},
        teams=TEAMS,
        slots=SLOTS,
    )


def test_toy_league_matches_the_hand_computation():
    # Team A: QB 20, RB 10, FLEX 8 = 38.  Team B: QB 15, RB 12, FLEX 9 = 36.
    # x (an 11-point RB nobody rosters): +3 to A (RB 11, FLEX 10), +2 to B (FLEX 11) -> 2.5.
    # a2 (10): A loses 10 (38 -> 28), B gains 1 (RB 12, FLEX max(a2 10, b3 9)) -> 5.5.
    res = cp.run_serial(toy_inputs(), PORT, ["x", "a2"], weeks=4, seed=1)
    assert res.value["x"] == pytest.approx(2.5)
    assert res.value["a2"] == pytest.approx(5.5)
    assert res.promotes is False
    assert res.transform == "identity_league_points_per_week"


def test_value_is_an_identity_transform_on_the_points_scale():
    # Doubling every projected point doubles D: no rescaling, no calibration, no market.
    base = cp.run_serial(toy_inputs(), PORT, list(MU), weeks=3, seed=1)
    twice = cp.run_serial(
        toy_inputs({k: 2 * v for k, v in MU.items()}), PORT, list(MU), weeks=3, seed=1
    )
    for k in MU:
        assert twice.value[k] == pytest.approx(2 * base.value[k])


def test_unknown_rostered_player_is_not_assignable_and_not_zero():
    # b2 has no projection: UNKNOWN.  B's lineup is then QB 15, RB nobody, FLEX 9.
    mu = {k: v for k, v in MU.items() if k != "b2"}
    res = cp.run_serial(toy_inputs(mu), PORT, ["x"], weeks=2, seed=1)
    # x into B: RB 11 (FLEX 9) vs QB 15 + FLEX 9 = 24 -> 15 + 11 + 9 = 35, gain 11.
    # x into A: +3.  League average (3 + 11) / 2 = 7.
    assert res.value["x"] == pytest.approx(7.0)
    assert "b2" not in res.value  # never evaluated, never given a value


def test_player_without_mu_is_never_evaluated():
    res = cp.run_serial(toy_inputs(), PORT, ["x", "ghost"], weeks=2, seed=1)
    assert "ghost" not in res.value


# ── availability and residual sets ───────────────────────────────────────────


def test_availability_formula_and_bounds():
    assert cp.availability_rate(16, 17, 0.8, 4.0) == pytest.approx((16 + 3.2) / 21)
    assert cp.availability_rate(0, 17, 0.8, 4.0) == pytest.approx(3.2 / 21)
    assert cp.availability_rate(5, 10, 0.9, 0.0) == pytest.approx(0.5)
    assert cp.availability_rate(0, 0, 0.7, 4.0) == pytest.approx(0.7)  # no team games: the prior
    assert cp.availability_rate(30, 17, 1.0, 4.0) == 1.0  # capped
    with pytest.raises(ValueError):
        cp.availability_rate(0, 0, 0.5, 0.0)
    with pytest.raises(ValueError):
        cp.availability_rate(1, 1, 1.5, 4.0)


def test_pseudo_count_pulls_toward_the_position_mean():
    low = cp.availability_rate(2, 17, 0.8, 0.0)
    mid = cp.availability_rate(2, 17, 0.8, 4.0)
    high = cp.availability_rate(2, 17, 0.8, 16.0)
    assert low < mid < high < 0.8


def test_residuals_sum_to_zero_and_empty_for_no_games():
    r = cp.residuals_of([10.0, 14.0, 6.0])
    assert math.fsum(r) == pytest.approx(0.0)
    assert cp.residuals_of([]) == ()


def test_pooled_residuals_use_only_players_with_enough_own_residuals():
    own = {"a": tuple(range(6)), "b": (1.0, 2.0), "c": tuple(range(7)), "d": tuple(range(8))}
    stratum = {"a": "WR", "b": "WR", "c": "WR", "d": "TE"}
    pools = cp.pooled_residual_sets(own, stratum, eligible_ids=["a", "b", "c", "d"], min_own=6)
    assert pools["WR"] == tuple(float(x) for x in list(range(6)) + list(range(7)))
    assert pools["TE"] == tuple(float(x) for x in range(8))
    # a stratum with no qualifying player gets no pool rather than a made-up one
    assert "QB" not in cp.pooled_residual_sets(own, stratum, eligible_ids=["b"], min_own=6)


def test_residual_set_prefers_own_then_pooled_and_flags_the_unsimulable():
    inp = cp.SimInputs(
        mu={"p": 10.0, "q": 9.0, "r": 8.0},
        availability={"p": 1.0, "q": 1.0},
        own_residuals={"p": tuple([1.0] * 6), "q": (5.0,)},
        pooled={"WR": (7.0, 8.0)},
        stratum={"p": "WR", "q": "WR", "r": "TE"},
        position={},
        fantasy_positions={},
        teams={},
        slots=[],
    )
    assert inp.residual_set("p") == tuple([1.0] * 6)
    assert inp.residual_set("q") == (7.0, 8.0)  # fewer than six own: the pooled set
    assert inp.unsimulable() == {"r": "no_availability"}
    assert inp.simulable() == ["p", "q"]


# ── the simulation is reproducible and chunk-invariant ───────────────────────


def varied_inputs() -> cp.SimInputs:
    rng = random.Random(9)
    mu = {k: v for k, v in MU.items()}
    own = {k: tuple(rng.uniform(-4, 4) for _ in range(8)) for k in mu}
    return cp.SimInputs(
        mu=mu,
        availability={k: rng.uniform(0.6, 1.0) for k in mu},
        own_residuals=own,
        pooled={"QB": (0.0,), "RB": (0.0,), "WR": (0.0,)},
        stratum={k: POS[k] for k in mu},
        position={k: POS[k] for k in mu},
        fantasy_positions={k: () for k in mu},
        teams=TEAMS,
        slots=SLOTS,
    )


def test_same_seed_same_result_and_a_different_seed_differs():
    inp = varied_inputs()
    a = cp.run_serial(inp, PORT, ["x", "a2", "b3"], weeks=30, seed=7)
    b = cp.run_serial(inp, PORT, ["x", "a2", "b3"], weeks=30, seed=7)
    c = cp.run_serial(inp, PORT, ["x", "a2", "b3"], weeks=30, seed=8)
    assert dict(a.value) == dict(b.value)
    assert dict(a.value) != dict(c.value)


def test_weeks_are_independent_streams_so_chunking_cannot_change_the_answer():
    inp = varied_inputs()
    ids = ["x", "a2", "b3"]
    forward = [cp.simulate_week(inp, PORT, s, ids, seed=7) for s in range(12)]
    shuffled = [cp.simulate_week(inp, PORT, s, ids, seed=7) for s in reversed(range(12))]
    one = cp.summarize_weeks(forward, seed=7)
    two = cp.summarize_weeks(sorted(shuffled, key=lambda w: w.week), seed=7)
    assert dict(one.value) == dict(two.value)
    serial = cp.run_serial(inp, PORT, ids, weeks=12, seed=7)
    assert dict(serial.value) == dict(one.value)


def test_week_draws_do_not_depend_on_who_played():
    # The residual index is drawn whether or not the player played, so changing one
    # player's availability must not shift every later player's residual draw.
    inp = varied_inputs()
    base = cp.draw_week(inp, cp.week_rng(3, 0))
    tweaked = cp.SimInputs(
        **{
            **inp.__dict__,
            "availability": {
                **inp.availability,
                "a1": 1.0 if inp.availability["a1"] < 1.0 else 0.99,
            },
        }
    )
    other = cp.draw_week(tweaked, cp.week_rng(3, 0))
    for pid in inp.simulable():
        if pid == "a1":
            continue
        assert base[pid] == other[pid]


def test_sigma_zero_ablation_removes_residual_variance_only():
    inp = varied_inputs()
    full = cp.draw_week(inp, cp.week_rng(2, 0), sigma=True)
    flat = cp.draw_week(inp, cp.week_rng(2, 0), sigma=False)
    for pid, v in flat.items():
        assert v in (0.0, inp.mu[pid])  # played at mu, or did not play
    played_flat = {p for p, v in flat.items() if v != 0.0}
    played_full = {p for p, v in full.items() if v != 0.0}
    assert played_flat <= played_full | {p for p, v in full.items() if v == 0.0}


def test_own_team_only_restricts_a_rostered_player_to_his_team():
    inp = toy_inputs()
    league = cp.run_serial(inp, PORT, ["a2", "x"], weeks=2, seed=1)
    own = cp.run_serial(inp, PORT, ["a2", "x"], weeks=2, seed=1, own_team_only=True)
    assert own.value["a2"] == pytest.approx(10.0)  # A alone: 38 -> 28
    assert league.value["a2"] == pytest.approx(5.5)
    assert own.value["x"] == pytest.approx(league.value["x"])  # unrostered: unchanged


def test_standard_error_is_reported_and_ties_are_not_broken():
    res = cp.run_serial(varied_inputs(), PORT, ["x", "a2"], weeks=40, seed=3)
    assert all(math.isfinite(res.mc_se[k]) and res.mc_se[k] >= 0 for k in ("x", "a2"))
    assert res.weeks == 40 and res.seed == 3


def test_fingerprints_are_stable_and_change_with_content():
    a = cp.inputs_fingerprint(varied_inputs())
    assert a == cp.inputs_fingerprint(varied_inputs())
    assert a != cp.inputs_fingerprint(toy_inputs())
    assert cp.stable_hash({"a": 1.0, "b": 2.0}) == cp.stable_hash({"b": 2.0, "a": 1.0})
    assert cp.stable_hash({"a": 1.0}) != cp.stable_hash({"a": 1.0000001})


# ── F finding: per-scope quantile matching cannot move a cross-position level ─


def _level_stats(rows_values):
    vals = sorted(rows_values, reverse=True)
    return {"sum": sum(vals), "top3": sum(vals[:3]), "n": len(vals)}


def test_fair_value_cannot_correct_an_idp_level_error_by_construction():
    """A board whose IDP level is uniformly wrong against offense.

    Every IDP value is the offense-order value scaled down by 0.6 (the whole IDP scope
    is priced too low relative to offense, while the IDP order is perfect).  The
    challenger quantile-matches each scope to ITS OWN values, so whatever utility order
    it is shown, the IDP scope keeps exactly the same multiset of values, and the
    cross-scope level gap is untouched.
    """
    from tests.league_valuation._builders import bdvm_entry, params_with, payload, row, run

    params = params_with(
        kMax__value=1.0,
        quality__byProjectionFamilies={"0": 0.0, "1": 1.0, "2": 1.0, "3": 1.0},
    )
    rng = random.Random(11)
    offense = [(f"{2000 + i}", p) for i, p in enumerate(["QB", "RB", "WR", "TE"] * 6)]
    idp = [(f"{3000 + i}", p) for i, p in enumerate(["DL", "LB", "DB"] * 8)]
    off_vals = sorted(rng.sample(range(2000, 9900), len(offense)), reverse=True)
    idp_vals = sorted([int(0.6 * v) for v in rng.sample(range(2000, 9900), len(idp))], reverse=True)
    rows = []
    for (pid, pos), v in zip(offense, off_vals):
        rows.append(row(pid, pos, v, None))
    for (pid, pos), v in zip(idp, idp_vals):
        rows.append(row(pid, pos, v, None))
    ordered = sorted(rows, key=lambda r: -r["rankDerivedValue"])
    for i, r in enumerate(ordered):
        r["canonicalConsensusRank"] = i + 1

    for seed in range(5):
        r2 = random.Random(100 + seed)
        entries = [
            bdvm_entry(r["playerId"], r["position"], r2.uniform(0, 1000), r2.uniform(-5, 10))
            for r in rows
        ]
        fb = run(rows, payload(entries), params=params)
        by_scope = {"OFFENSE": [], "IDP": []}
        before = {"OFFENSE": [], "IDP": []}
        for r in rows:
            v = fb.values[f"player:{r['playerId']}"]
            assert v.state == "available"
            by_scope[v.scope].append(v.fair_value_exact)
            before[v.scope].append(float(r["rankDerivedValue"]))
        for scope in by_scope:
            assert sorted(by_scope[scope]) == pytest.approx(sorted(before[scope]))
            assert _level_stats(by_scope[scope])["sum"] == pytest.approx(
                _level_stats(before[scope])["sum"]
            )
        # the cross-position level gap (mean offense value / mean IDP value) is unchanged
        gap_before = (sum(before["OFFENSE"]) / len(before["OFFENSE"])) / (
            sum(before["IDP"]) / len(before["IDP"])
        )
        gap_after = (sum(by_scope["OFFENSE"]) / len(by_scope["OFFENSE"])) / (
            sum(by_scope["IDP"]) / len(by_scope["IDP"])
        )
        assert gap_after == pytest.approx(gap_before)
        assert gap_before > 1.5  # the constructed level error is still there after the model
        moved = sum(
            1
            for r in rows
            if fb.values[f"player:{r['playerId']}"].fair_value != r["rankDerivedValue"]
        )
        assert moved > 0  # the model did act: this is not a vacuous no-op
