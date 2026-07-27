"""Production engine vs. the verified BDVM reference (Appendix C).

The 13 hypothetical archetypes from the reference are run through the
PRODUCTION package (``src/bdvm``) configured with the same priors
(``config/bdvm/params_v1.json``) and synthetic pools.  Every trade
value, replacement level and probability must reproduce the appendix
numbers — this is the acceptance fixture required by Phase 0 of the
integration prompt, applied to the production code path.
"""

from __future__ import annotations

import math
import unittest

from src.bdvm.engine import DynastyEngine, PlayerInput
from src.bdvm.league_config import BdvmLeagueConfig, DEFAULT_POS_GROUPS
from src.bdvm.params import load_param_set
from src.bdvm.replacement import ReplacementEngine
from src.bdvm.survival import RiskProfile

PARAMS = load_param_set("params_v1")

REFERENCE_CFG = BdvmLeagueConfig(
    league_key="reference_demo",
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
    scoring_settings={"rec": 1.0},  # engine does not read scoring; projections do
    roster_size=35,
)


def synthetic_pool(top_fpg: float, decay: float):
    return lambda rank: top_fpg * math.exp(-decay * max(0, rank - 1))


POOLS = {
    "QB": synthetic_pool(24.0, 0.020),
    "RB": synthetic_pool(20.0, 0.028),
    "WR": synthetic_pool(19.0, 0.024),
    "TE": synthetic_pool(16.0, 0.045),
    "DL": synthetic_pool(16.0, 0.030),
    "LB": synthetic_pool(19.0, 0.018),
    "DB": synthetic_pool(14.0, 0.020),
}


def _p(
    player_id,
    name,
    pos,
    age,
    nfl_season,
    fpg,
    games,
    sigma_source,
    archetype,
    career_load,
    kappa,
    risk,
):
    return PlayerInput(
        player_id=player_id,
        name=name,
        position=pos,
        age=age,
        nfl_season=nfl_season,
        fpg=fpg,
        games=games,
        sigma_source=sigma_source,
        archetype=archetype,
        career_load=career_load,
        kappa=kappa,
        risk=risk,
    )


PLAYERS = [
    _p(
        "p1",
        "Young elite QB (dual)",
        "QB",
        24.0,
        3,
        22.5,
        16.5,
        0.9,
        "dual",
        1150,
        0.06,
        RiskProfile(0.92, 0.95, 0.85, 0.70, 1.8, 0.8, 0.08, 0.28, 0.0),
    ),
    _p(
        "p2",
        "Aging productive QB (pocket)",
        "QB",
        34.0,
        12,
        19.0,
        16.0,
        0.7,
        "pocket",
        6200,
        0.0,
        RiskProfile(0.88, 0.80, 0.55, 0.62, 1.0, 0.7, 0.10, 0.25, 0.0),
    ),
    _p(
        "p3",
        "Young RB, three-down",
        "RB",
        23.0,
        2,
        15.5,
        15.5,
        1.1,
        None,
        310,
        0.18,
        RiskProfile(0.80, 0.85, 0.80, 0.65, 1.1, 0.7, 0.15, 0.35, 0.0),
    ),
    _p(
        "p4",
        "Aging RB, heavy mileage",
        "RB",
        29.0,
        8,
        14.5,
        15.0,
        1.3,
        None,
        1720,
        0.0,
        RiskProfile(0.72, 0.70, 0.35, 0.45, 0.9, 0.6, 0.20, 0.35, 0.0),
    ),
    _p(
        "p5",
        "Young ascending WR",
        "WR",
        23.0,
        2,
        14.0,
        16.0,
        1.4,
        None,
        140,
        0.30,
        RiskProfile(0.72, 0.88, 0.85, 0.70, 0.7, 0.7, 0.22, 0.30, 0.0),
    ),
    _p(
        "p6",
        "Veteran WR, stable role",
        "WR",
        30.0,
        9,
        15.5,
        16.0,
        0.8,
        None,
        980,
        0.0,
        RiskProfile(0.86, 0.70, 0.60, 0.68, 1.2, 0.7, 0.10, 0.28, 0.0),
    ),
    _p(
        "p7",
        "Young TE, year-2 leap",
        "TE",
        24.0,
        2,
        10.5,
        16.0,
        1.2,
        None,
        95,
        0.28,
        RiskProfile(0.70, 0.80, 0.85, 0.70, 0.6, 0.7, 0.25, 0.35, 0.0),
    ),
    _p(
        "p8",
        "Elite EDGE rusher",
        "EDGE",
        26.0,
        5,
        14.5,
        16.0,
        0.9,
        None,
        2600,
        0.04,
        RiskProfile(0.90, 0.90, 0.80, 0.68, 1.6, 0.8, 0.08, 0.55, 0.0),
    ),
    _p(
        "p9",
        "Three-down LB, green dot",
        "LB",
        25.0,
        3,
        17.5,
        16.5,
        0.8,
        None,
        2100,
        0.08,
        RiskProfile(0.92, 0.75, 0.75, 0.72, 1.4, 0.85, 0.07, 0.20, 0.05),
    ),
    _p(
        "p10",
        "Volatile boundary CB",
        "CB",
        26.0,
        4,
        9.0,
        16.0,
        1.1,
        "boundary",
        2500,
        0.0,
        RiskProfile(0.70, 0.65, 0.55, 0.62, 0.3, 0.6, 0.35, 0.70, 0.0),
    ),
    _p(
        "p11",
        "Box safety, tackle floor",
        "S",
        27.0,
        5,
        11.5,
        16.0,
        0.7,
        "box",
        2900,
        0.0,
        RiskProfile(0.85, 0.55, 0.60, 0.70, 0.9, 0.65, 0.12, 0.25, 0.35),
    ),
    _p(
        "p12",
        "Rookie WR, 1st-rd capital",
        "WR",
        22.0,
        1,
        9.0,
        15.0,
        2.2,
        None,
        0,
        0.55,
        RiskProfile(0.55, 0.95, 0.90, 0.60, -0.4, 0.6, 0.55, 0.35, 1.0),
    ),
    _p(
        "p13",
        "Late-round breakout WR",
        "WR",
        25.0,
        3,
        13.0,
        16.0,
        1.6,
        None,
        330,
        0.10,
        RiskProfile(0.62, 0.15, 0.45, 0.66, 0.6, 0.6, 0.35, 0.35, 0.0),
    ),
]

# Appendix C golden numbers: (contender, balanced, rebuilder) trade values.
GOLDEN_TRADE_VALUES = {
    "p1": (9800, 7974, 6265),
    "p2": (3458, 2112, 1128),
    "p3": (8492, 6615, 4982),
    "p4": (2674, 1406, 520),
    "p5": (9693, 9800, 9800),
    "p6": (4368, 2485, 1144),
    "p7": (5875, 6367, 6782),
    "p8": (6301, 4712, 3387),
    "p9": (8946, 6661, 4750),
    "p10": (2055, 1328, 786),
    "p11": (3239, 2087, 1228),
    "p12": (6160, 7051, 7958),
    "p13": (6140, 4857, 3719),
}

GOLDEN_REPLACEMENT = {
    "QB": 12.40,
    "RB": 6.35,
    "WR": 6.15,
    "TE": 6.80,
    "DL": 6.70,
    "LB": 7.32,
    "DB": 6.17,
}

GOLDEN_STARTABLE = {"QB": 24, "RB": 33, "WR": 36, "TE": 15, "DL": 24, "LB": 48, "DB": 36}

# Appendix C probability rows (P>repl, P elite, P start 3y, P breakout, P collapse 1y)
GOLDEN_PROBS = {
    "p3": (0.89, 0.40, 0.58, 0.36, 0.21),
    "p4": (0.87, 0.35, 0.01, 0.01, 0.65),
    "p9": (0.97, 0.51, 0.66, 0.24, 0.12),
    "p12": (0.63, 0.18, 0.55, 0.52, 0.38),
}


class TestEngineReproducesReference(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repl = ReplacementEngine(REFERENCE_CFG, POOLS)
        cls.engine = DynastyEngine(REFERENCE_CFG, cls.repl, PARAMS, pools=POOLS)
        cls.engine.calibrate(PLAYERS)
        cls.valuations = {p.player_id: cls.engine.value(p) for p in PLAYERS}

    def test_replacement_levels_match_appendix(self):
        for group, expected in GOLDEN_REPLACEMENT.items():
            self.assertAlmostEqual(
                self.repl.R(group), expected, places=2, msg=f"replacement FPG for {group}"
            )

    def test_startable_slots_match_appendix(self):
        for group, expected in GOLDEN_STARTABLE.items():
            self.assertEqual(
                self.repl.startable(group), expected, msg=f"startable slots for {group}"
            )

    def test_trade_values_match_appendix(self):
        for pid, (cont, bal, reb) in GOLDEN_TRADE_VALUES.items():
            v = self.valuations[pid]
            self.assertLessEqual(
                abs(v.trade_value["contender"] - cont),
                1.0,
                msg=f"{pid} contender {v.trade_value['contender']:.1f} != {cont}",
            )
            self.assertLessEqual(
                abs(v.trade_value["balanced"] - bal),
                1.0,
                msg=f"{pid} balanced {v.trade_value['balanced']:.1f} != {bal}",
            )
            self.assertLessEqual(
                abs(v.trade_value["rebuilder"] - reb),
                1.0,
                msg=f"{pid} rebuilder {v.trade_value['rebuilder']:.1f} != {reb}",
            )

    def test_probabilities_match_appendix(self):
        for pid, (p_above, p_elite, p_s3, p_break, p_coll) in GOLDEN_PROBS.items():
            probs = self.valuations[pid].probs
            self.assertAlmostEqual(probs["p_above_replacement"], p_above, places=2)
            self.assertAlmostEqual(probs["p_elite_season"], p_elite, places=2)
            self.assertAlmostEqual(probs["p_starter_in_3y"], p_s3, places=2)
            self.assertAlmostEqual(probs["p_breakout"], p_break, places=2)
            self.assertAlmostEqual(probs["p_value_collapse_1y"], p_coll, places=2)

    def test_scarcity_lb_vs_safety(self):
        """The LB/S requirement: more points must not mean more value."""
        lb_r = self.repl.R("LB")
        db_r = self.repl.R("DB")
        self.assertGreater(lb_r, db_r)
        # Mid LB at 12.5 FPG has MORE points but LESS surplus than the
        # box safety at 11.5 FPG.
        self.assertLess(12.5 - lb_r, 11.5 - db_r)

    def test_risk_neutral_strategy_present_and_sane(self):
        """The 4th profile (λ=0) exists and dominates balanced pre-scale."""
        for pid, v in self.valuations.items():
            self.assertIn("risk_neutral", v.fundamental)
            self.assertGreaterEqual(
                v.fundamental["risk_neutral"] + 1e-9,
                v.fundamental["balanced"],
                msg=f"{pid}: risk-neutral fundamental must be >= balanced (λ>0 penalises)",
            )

    def test_aging_rb_year0_share(self):
        """85% of the aging RB's balanced value sits in season 0."""
        e = self.valuations["p4"].explain
        self.assertAlmostEqual(e["year_0_share"], 0.85, delta=0.01)
        self.assertAlmostEqual(e["traj_5y"], -0.95, delta=0.01)


if __name__ == "__main__":
    unittest.main()
