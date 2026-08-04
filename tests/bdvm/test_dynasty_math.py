"""Dynasty-math invariants: the Phase-3 gates.

Aging and survival stay separate; ascension is bounded and never a
generic youth multiplier; option surplus behaves like an option; the
risk-neutral output exists; results are deterministic.
"""

from __future__ import annotations

import math
import unittest

from src.bdvm.curves import (
    aging_mult,
    ascension_mult,
    compute_kappa,
    draft_capital_decay,
    effective_age,
)
from src.bdvm.engine import DynastyEngine, PlayerInput
from src.bdvm.league_config import BdvmLeagueConfig, DEFAULT_POS_GROUPS
from src.bdvm.params import load_param_set
from src.bdvm.replacement import ReplacementEngine
from src.bdvm.surplus import expected_positive_surplus, season_starter_value
from src.bdvm.survival import RiskProfile, hazard, survival_path

PARAMS = load_param_set("params_v1")


def _pool(top, decay):
    return lambda rank: top * math.exp(-decay * max(0, rank - 1))


POOLS = {
    "QB": _pool(24.0, 0.020),
    "RB": _pool(20.0, 0.028),
    "WR": _pool(19.0, 0.024),
    "TE": _pool(16.0, 0.045),
    "DL": _pool(16.0, 0.030),
    "LB": _pool(19.0, 0.018),
    "DB": _pool(14.0, 0.020),
}

CFG = BdvmLeagueConfig(
    league_key="t",
    teams=12,
    starters={"QB": 1, "RB": 2, "WR": 3, "TE": 1, "DL": 2, "LB": 3, "DB": 3},
    flex={
        "FLEX": (1, ("RB", "WR", "TE")),
        "SUPERFLEX": (1, ("QB", "RB", "WR", "TE")),
        "IDP_FLEX": (1, ("DL", "LB", "DB")),
    },
    waiver_buffer={
        "QB": 0.85,
        "RB": 0.75,
        "WR": 1.00,
        "TE": 0.40,
        "DL": 0.50,
        "LB": 0.50,
        "DB": 0.50,
    },
    default_buffer=0.5,
    pos_groups=dict(DEFAULT_POS_GROUPS),
    scoring_settings={"rec": 1.0},
)


def make_engine(**kwargs) -> DynastyEngine:
    repl = ReplacementEngine(CFG, POOLS)
    return DynastyEngine(CFG, repl, PARAMS, pools=POOLS, **kwargs)


class TestAgingSurvivalSeparation(unittest.TestCase):
    def test_hazard_ignores_career_load(self):
        """Mileage lives in the CURVE (effective age); the hazard reads
        chronological age.  Same age + risk ⇒ same hazard regardless of
        workload — no double-counting."""
        risk = RiskProfile()
        h = hazard(PARAMS, "RB", 26.0, risk, dc_decay=0.5)
        # hazard() has no career-load argument at all — structural guarantee —
        # and the survival path of two same-age RBs with different loads
        # is identical while their mu paths differ.
        heavy = PlayerInput(
            player_id="a",
            name="a",
            position="RB",
            age=26.0,
            nfl_season=5,
            fpg=15.0,
            games=16.0,
            career_load=2000.0,
        )
        light = PlayerInput(
            player_id="b",
            name="b",
            position="RB",
            age=26.0,
            nfl_season=5,
            fpg=15.0,
            games=16.0,
            career_load=0.0,
        )
        eng = make_engine()
        rows_heavy = eng.season_path(heavy, 4)
        rows_light = eng.season_path(light, 4)
        for rh, rl in zip(rows_heavy, rows_light):
            self.assertAlmostEqual(rh["survival"], rl["survival"], places=12)
        self.assertLess(rows_heavy[2]["mu"], rows_light[2]["mu"])
        self.assertGreater(h, 0.0)

    def test_effective_age_only_increases(self):
        self.assertEqual(effective_age(PARAMS, "RB", 25.0, 0.0), 25.0)
        self.assertEqual(effective_age(PARAMS, "RB", 25.0, 750.0), 25.0)
        self.assertGreater(effective_age(PARAMS, "RB", 25.0, 1500.0), 25.0)
        # capped
        self.assertAlmostEqual(effective_age(PARAMS, "RB", 25.0, 10_000.0), 27.5)

    def test_old_rb_decays_faster_than_old_pocket_qb(self):
        rb_30 = aging_mult(PARAMS, "RB", 30.0)
        qb_30 = aging_mult(PARAMS, "QB", 30.0, "pocket")
        self.assertLess(rb_30, qb_30)
        s_rb = survival_path(PARAMS, "RB", 29.0, RiskProfile(), 0.3, 3)
        s_qb = survival_path(PARAMS, "QB", 29.0, RiskProfile(), 0.3, 3)
        self.assertLess(s_rb[3], s_qb[3])


class TestAscension(unittest.TestCase):
    def test_bounded_and_saturating(self):
        self.assertEqual(ascension_mult(PARAMS, 0.30, 0), 1.0)
        self.assertEqual(ascension_mult(PARAMS, -0.10, 3), 1.0)  # κ<=0 → no boost
        m5 = ascension_mult(PARAMS, 0.30, 5)
        self.assertLess(m5, 1.30 + 1e-9)
        self.assertGreater(m5, ascension_mult(PARAMS, 0.30, 1))

    def test_kappa_forced_zero_for_veterans_without_role_change(self):
        k = compute_kappa(PARAMS, nfl_season=5, draft_capital_score=1.0, opportunity_score=1.0)
        self.assertEqual(k, 0.0)
        k_role_change = compute_kappa(
            PARAMS, nfl_season=5, opportunity_score=0.8, documented_role_change=True
        )
        self.assertGreater(k_role_change, 0.0)

    def test_kappa_clipped(self):
        k = compute_kappa(
            PARAMS, nfl_season=1, draft_capital_score=1.0, college_score=1.0, opportunity_score=1.0
        )
        self.assertLessEqual(k, 0.60)
        k_neg = compute_kappa(PARAMS, nfl_season=1, incumbency=1.0)
        self.assertGreaterEqual(k_neg, -0.15)

    def test_draft_capital_decay_schedule(self):
        self.assertAlmostEqual(draft_capital_decay(PARAMS, 1), 1.0)
        self.assertAlmostEqual(draft_capital_decay(PARAMS, 2), math.exp(-0.45))
        self.assertLess(draft_capital_decay(PARAMS, 6), 0.12)


class TestOptionSurplus(unittest.TestCase):
    def test_option_vs_truncated_vs_plain_below_replacement(self):
        mu, sigma, r, games = 5.0, 4.0, 7.0, 16.0
        opt = season_starter_value(mu, sigma, r, games, mode="option")
        trunc = season_starter_value(mu, sigma, r, games, mode="truncated")
        plain = season_starter_value(mu, sigma, r, games, mode="plain")
        self.assertGreater(opt, trunc)  # upside priced
        self.assertEqual(trunc, 0.0)
        self.assertLess(plain, 0.0)  # plain difference goes negative

    def test_option_converges_to_plain_far_above_replacement(self):
        mu, sigma, r = 25.0, 3.0, 7.0
        opt = expected_positive_surplus(mu, sigma, r)
        self.assertAlmostEqual(opt, mu - r, delta=0.01)

    def test_wider_range_worth_more_near_replacement(self):
        r = 7.0
        narrow = expected_positive_surplus(7.0, 1.0, r)
        wide = expected_positive_surplus(7.0, 5.0, r)
        self.assertGreater(wide, narrow)

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            season_starter_value(10, 2, 7, 16, mode="banana")

    def test_engine_ablation_modes_reorder_uncertain_assets(self):
        """The §3.3 ablation is wired end-to-end: under `plain`, a volatile
        near-replacement player loses value vs the option formulation."""
        volatile = PlayerInput(
            player_id="v",
            name="v",
            position="CB",
            age=24.0,
            nfl_season=2,
            fpg=8.0,
            games=16.0,
            risk=RiskProfile(role_uncertainty=0.5, event_volatility=0.7),
        )
        opt_engine = make_engine(surplus_mode="option")
        plain_engine = make_engine(surplus_mode="plain")
        v_opt = opt_engine.fundamental_values(volatile)["balanced"]
        v_plain = plain_engine.fundamental_values(volatile)["balanced"]
        self.assertGreater(v_opt, v_plain)


class TestStrategyAndDeterminism(unittest.TestCase):
    def _proven_star_and_dart_throw(self):
        star = PlayerInput(
            player_id="s",
            name="star",
            position="WR",
            age=26.0,
            nfl_season=5,
            fpg=16.0,
            games=16.5,
            risk=RiskProfile(role_security=0.9, production_z=1.5, role_uncertainty=0.08),
        )
        dart = PlayerInput(
            player_id="d",
            name="dart",
            position="WR",
            age=22.0,
            nfl_season=1,
            fpg=6.0,
            games=15.0,
            kappa=0.55,
            risk=RiskProfile(
                role_security=0.5, production_z=-0.5, role_uncertainty=0.55, small_sample=1.0
            ),
        )
        return star, dart

    def test_young_dart_throw_does_not_outrank_proven_star(self):
        star, dart = self._proven_star_and_dart_throw()
        eng = make_engine()
        eng.calibrate([star, dart])
        v_star = eng.value(star).trade_value
        v_dart = eng.value(dart).trade_value
        for strategy in ("contender", "balanced", "rebuilder"):
            self.assertGreater(
                v_star[strategy],
                v_dart[strategy],
                msg=f"6-FPG rookie must not outrank a 16-FPG star ({strategy})",
            )

    def test_risk_neutral_geq_balanced_fundamental(self):
        star, dart = self._proven_star_and_dart_throw()
        eng = make_engine()
        for p in (star, dart):
            f = eng.fundamental_values(p)
            self.assertGreaterEqual(f["risk_neutral"] + 1e-9, f["balanced"])

    def test_deterministic_reproducibility(self):
        star, _ = self._proven_star_and_dart_throw()
        eng = make_engine()
        eng.calibrate([star])
        v1 = eng.value(star)
        v2 = eng.value(star)
        self.assertEqual(v1.trade_value, v2.trade_value)
        self.assertEqual(v1.probs, v2.probs)
        self.assertEqual(v1.seasons, v2.seasons)

    def test_every_future_year_is_decomposable(self):
        """Phase-3 gate: mu(t) = mu(0) × trajectory × ascension exactly."""
        p = PlayerInput(
            player_id="x",
            name="x",
            position="WR",
            age=23.0,
            nfl_season=2,
            fpg=14.0,
            games=16.0,
            kappa=0.30,
            career_load=140.0,
        )
        eng = make_engine()
        rows = eng.season_path(p, 4)
        a0 = effective_age(PARAMS, "WR", 23.0, 140.0)
        base = aging_mult(PARAMS, "WR", a0)
        for r in rows:
            t = int(r["t"])
            load = 140.0 + t * float(PARAMS["annual_load_rate"]["WR"])
            a_t = effective_age(PARAMS, "WR", 23.0 + t, load)
            expected_mu = (
                14.0 * (aging_mult(PARAMS, "WR", a_t) / base) * ascension_mult(PARAMS, 0.30, t)
            )
            self.assertAlmostEqual(r["mu"], expected_mu, places=9)

    def test_floor_median_ceiling_ordering(self):
        p = PlayerInput(
            player_id="x", name="x", position="WR", age=25.0, nfl_season=4, fpg=13.0, games=16.0
        )
        eng = make_engine()
        eng.calibrate([p])
        rng = eng.value(p).range_
        self.assertLessEqual(rng["floor_p20"], rng["median"] + 1e-6)
        self.assertLessEqual(rng["median"], rng["ceiling_p85"] + 1e-6)


class TestValueScaleBounds(unittest.TestCase):
    """The 0-10000 scale is a BOUND, and the band is a band.

    Both gates here were open: ``scale.trade_value_max`` was declared in
    params and read by nothing, and the floor/median/ceiling triple could
    come back with the ceiling BELOW the median (audit H6, 2026-08-04).
    """

    def _star(self):
        # The reference's young elite QB — the asset calibration anchors on.
        return PlayerInput(
            player_id="s",
            name="star",
            position="QB",
            age=24.0,
            nfl_season=3,
            fpg=22.5,
            games=16.5,
            archetype="dual",
            career_load=1150,
            kappa=0.06,
            risk=RiskProfile(0.92, 0.95, 0.85, 0.70, 1.8, 0.8, 0.08, 0.28, 0.0),
        )

    def _deep_bench_flier(self):
        # 2.5 FPG against a 6.15 WR replacement level: the option value is
        # ALL variance, so the p20/p85 paths and the expectation disagree.
        return PlayerInput(
            player_id="d",
            name="deep",
            position="WR",
            age=24.0,
            nfl_season=2,
            fpg=2.5,
            games=16.0,
            risk=RiskProfile(role_uncertainty=0.6, event_volatility=0.6, small_sample=1.0),
        )

    def test_ceiling_is_bounded_by_the_declared_scale_max(self):
        star, deep = self._star(), self._deep_bench_flier()
        eng = make_engine()
        eng.calibrate([star, deep])
        rng = eng.value(star).range_
        cap = float(PARAMS["scale"]["trade_value_max"])
        # Calibration pins the top asset's MEDIAN at target_top_value, and
        # that number sits below the cap deliberately — so the bound acts
        # on the p85 path (uncapped: ~19.7k) without moving the board.
        self.assertAlmostEqual(rng["median"], float(PARAMS["scale"]["target_top_value"]), places=6)
        # STRICTLY under, not equal to, the cap.  An earlier version of
        # this assertion demanded exact equality, which pinned a hard
        # `min(cap, x)` in place — and that clamp is not injective: on an
        # elite-heavy ladder it collapsed seven distinct ceilings
        # spanning an ~1.8x uncapped range onto one identical 10000.0.
        self.assertLess(rng["ceiling_p85"], cap)
        self.assertGreater(rng["ceiling_p85"], rng["median"])
        for v in eng.value(star).trade_value.values():
            self.assertLessEqual(v, cap)

    def test_the_bound_does_not_collapse_distinct_ceilings(self):
        """The bound must be order-preserving where it binds.

        Math audit C4, applied to BDVM: a hard clamp turns a resolution
        problem into a tie, and this band is rendered directly by
        ``frontend/lib/bdvm.js``.  Two players whose uncapped p85 paths
        differ must still differ after bounding.
        """
        from src.bdvm.engine import _under_ceiling

        cap = float(PARAMS["scale"]["trade_value_max"])
        # Uncapped ceilings measured on an elite-heavy ladder.
        uncapped = [20324.0, 18213.9, 14470.9, 14379.7, 11236.0, 10001.0]
        bounded = [_under_ceiling(v, ceiling=cap) for v in uncapped]
        self.assertEqual(len(set(bounded)), len(uncapped))
        # Order preserved, and every one strictly under the cap.
        self.assertEqual(bounded, sorted(bounded, reverse=True))
        for b in bounded:
            self.assertLess(b, cap)
        # Identity well below the knee — the board itself must not move.
        for v in (0.0, 1.0, 5000.0, 9800.0):
            self.assertEqual(_under_ceiling(v, ceiling=cap), v)

    def test_band_never_inverts_on_a_below_replacement_flier(self):
        star, deep = self._star(), self._deep_bench_flier()
        eng = make_engine()
        eng.calibrate([star, deep])
        rng = eng.value(deep).range_
        self.assertGreater(rng["median"], 0.0, "the option value of variance is real value")
        self.assertLessEqual(rng["floor_p20"], rng["median"])
        # Strict: a p85 outcome must be worth MORE than the expectation.
        # Before the fix this was 0.0 against a 41.4 median — the quantile
        # paths priced truncated surplus while the median priced the option.
        self.assertGreater(rng["ceiling_p85"], rng["median"])


if __name__ == "__main__":
    unittest.main()
