"""Replacement-engine mechanics + the Phase-2 monotonicity gates.

No cross-position rank is accepted until replacement logic passes
mechanical and football sanity checks (master prompt Phase 2 gate).
"""

from __future__ import annotations

import math
import unittest

from src.bdvm.league_config import BdvmLeagueConfig, DEFAULT_POS_GROUPS
from src.bdvm.pool import PoolCurve
from src.bdvm.replacement import ReplacementEngine, ReplacementUnavailableError

SCORING = {"rec": 1.0}


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

BUFFERS = {
    "QB": 0.85,
    "RB": 0.75,
    "WR": 1.00,
    "TE": 0.40,
    "DL": 0.50,
    "LB": 0.50,
    "DB": 0.50,
    "DT": 0.50,
    "EDGE": 0.50,
    "CB": 0.50,
    "S": 0.50,
}


def make_cfg(*, teams=12, starters=None, flex=None, pos_groups=None, buffers=None):
    return BdvmLeagueConfig(
        league_key="t",
        teams=teams,
        starters=starters or {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "DL": 2, "LB": 3, "DB": 3},
        flex=flex
        if flex is not None
        else {
            "FLEX": (1, ("RB", "WR", "TE")),
            "SUPERFLEX": (1, ("QB", "RB", "WR", "TE")),
            "IDP_FLEX": (1, ("DL", "LB", "DB")),
        },
        waiver_buffer=buffers or BUFFERS,
        default_buffer=0.5,
        pos_groups=pos_groups or dict(DEFAULT_POS_GROUPS),
        scoring_settings=SCORING,
    )


class TestMonotonicity(unittest.TestCase):
    def test_more_teams_lowers_replacement_everywhere(self):
        r12 = ReplacementEngine(make_cfg(teams=12), POOLS)
        r14 = ReplacementEngine(make_cfg(teams=14), POOLS)
        for g in ("QB", "RB", "WR", "TE", "DL", "LB", "DB"):
            self.assertLessEqual(
                r14.R(g),
                r12.R(g) + 1e-9,
                msg=f"{g}: 14-team replacement must not exceed 12-team",
            )

    def test_more_required_starters_lowers_replacement(self):
        base = ReplacementEngine(make_cfg(), POOLS)
        deeper = make_cfg(starters={"QB": 1, "RB": 2, "WR": 3, "TE": 1, "DL": 2, "LB": 4, "DB": 3})
        r = ReplacementEngine(deeper, POOLS)
        self.assertLess(r.R("LB"), base.R("LB"))
        self.assertGreater(r.startable("LB"), base.startable("LB"))

    def test_superflex_deepens_qb_replacement(self):
        sf = ReplacementEngine(make_cfg(), POOLS)
        one_qb = make_cfg(
            flex={
                "FLEX": (1, ("RB", "WR", "TE")),
                "IDP_FLEX": (1, ("DL", "LB", "DB")),
            }
        )
        r1 = ReplacementEngine(one_qb, POOLS)
        # Superflex absorbs QBs: more startable QBs, lower replacement FPG,
        # hence larger per-QB surplus.  No QB multiplier anywhere.
        self.assertGreater(sf.startable("QB"), r1.startable("QB"))
        self.assertLess(sf.R("QB"), r1.R("QB"))

    def test_bigger_waiver_buffer_lowers_replacement(self):
        base = ReplacementEngine(make_cfg(), POOLS)
        deep_buf = dict(BUFFERS, WR=2.0)
        r = ReplacementEngine(make_cfg(buffers=deep_buf), POOLS)
        self.assertLess(r.R("WR"), base.R("WR"))


class TestFormatSensitivity(unittest.TestCase):
    def test_dt_required_vs_combined_dl(self):
        """A DT-required league collapses DT replacement and lifts mid-DT
        surplus — configurable, never hard-coded (BDVM §4.5)."""
        dt_pool = synthetic_pool(11.0, 0.030)  # DTs score less than EDGEs
        edge_pool = synthetic_pool(16.0, 0.030)

        combined = make_cfg()  # DT+EDGE share the "DL" group
        combined_pools = dict(POOLS)
        r_combined = ReplacementEngine(combined, combined_pools)

        split_groups = dict(DEFAULT_POS_GROUPS, DT="DT", EDGE="EDGE", DE="EDGE")
        split = make_cfg(
            starters={"QB": 1, "RB": 2, "WR": 3, "TE": 1, "DT": 1, "EDGE": 1, "LB": 3, "DB": 3},
            pos_groups=split_groups,
        )
        split_pools = {**POOLS, "DT": dt_pool, "EDGE": edge_pool}
        r_split = ReplacementEngine(split, split_pools)

        mid_dt_fpg = 9.0
        surplus_combined = mid_dt_fpg - r_combined.R("DL")
        surplus_split = mid_dt_fpg - r_split.R("DT")
        self.assertGreater(
            surplus_split,
            surplus_combined,
            "a mid-tier DT must gain surplus when the league requires a DT slot",
        )

    def test_cb_s_required_vs_combined_db(self):
        """Same DB-family demand (3 slots), same underlying players: a
        CB-required split must reprice CBs vs the merged-DB format,
        because safeties crowd CBs out of a combined pool."""
        cb_vals = [12.0 * math.exp(-0.03 * k) for k in range(200)]
        s_vals = [14.0 * math.exp(-0.02 * k) for k in range(200)]
        cb_pool = PoolCurve(tuple(cb_vals))
        s_pool = PoolCurve(tuple(s_vals))
        merged_pool = PoolCurve(tuple(sorted(cb_vals + s_vals, reverse=True)))

        combined = make_cfg(
            starters={"QB": 1, "RB": 2, "WR": 3, "TE": 1, "DL": 2, "LB": 3, "DB": 3},
            flex={},
        )
        r_combined = ReplacementEngine(combined, {**POOLS, "DB": merged_pool})

        split_groups = dict(DEFAULT_POS_GROUPS, CB="CB", S="S", FS="S", SS="S")
        split = make_cfg(
            starters={"QB": 1, "RB": 2, "WR": 3, "TE": 1, "DL": 2, "LB": 3, "CB": 1, "S": 2},
            pos_groups=split_groups,
            flex={},
        )
        r_split = ReplacementEngine(split, {**POOLS, "CB": cb_pool, "S": s_pool})

        mid_cb = 8.0
        surplus_split = mid_cb - r_split.R("CB")
        surplus_combined = mid_cb - r_combined.R("DB")
        self.assertGreater(
            surplus_split,
            surplus_combined,
            "a CB-required slot must expand CB surplus vs the merged DB pool",
        )
        self.assertGreater(
            abs(r_split.R("CB") - r_combined.R("DB")),
            0.3,
            "the two formats must produce materially different replacement levels",
        )


class TestMechanics(unittest.TestCase):
    def test_vols_diagnostic_is_at_least_vorp(self):
        r = ReplacementEngine(make_cfg(), POOLS)
        for g, gr in r.groups.items():
            self.assertGreaterEqual(
                gr.worst_starter_fpg + 1e-9,
                gr.replacement_fpg,
                msg=f"{g}: VOLS (worst starter) must sit above the waiver baseline",
            )

    def test_pool_exhaustion_is_flagged_not_fabricated(self):
        """A replacement rank past the end of the pool is MISSING, not 0.0.

        R is the origin of the whole value scale: with R = 0 every
        player's surplus silently becomes his entire FPG, and the payload
        looks exactly like a real answer (audit H7).  The engine refuses
        instead — callers price such players as ``unpriced``.
        """
        tiny = PoolCurve(tuple([10.0, 9.0, 8.0]))
        cfg = make_cfg(
            starters={"QB": 1},
            flex={},
            pos_groups={"QB": "QB"},
        )
        r = ReplacementEngine(cfg, {"QB": tiny})
        gr = r.groups["QB"]
        self.assertTrue(gr.pool_exhausted)
        self.assertIsNone(gr.replacement_fpg)
        self.assertFalse(r.has_replacement("QB"))
        with self.assertRaises(ReplacementUnavailableError):
            r.R("QB")
        self.assertIsNone(r.to_dict()["QB"]["replacementFpg"])

    def test_group_without_a_pool_has_no_replacement_level(self):
        """Second route to a fabricated zero: no projections for the group."""
        cfg = make_cfg(starters={"QB": 1, "LB": 2}, flex={}, pos_groups={"QB": "QB", "LB": "LB"})
        r = ReplacementEngine(cfg, {"QB": PoolCurve(tuple(24.0 - 0.1 * k for k in range(60)))})
        self.assertTrue(r.has_replacement("QB"))
        self.assertFalse(r.has_replacement("LB"))
        with self.assertRaises(ReplacementUnavailableError):
            r.R("LB")

    def test_group_with_no_lineup_slots_has_no_replacement_level(self):
        """Third route: the group never entered the flex/starter solve."""
        r = ReplacementEngine(make_cfg(), POOLS)
        self.assertFalse(r.has_replacement("K"))
        with self.assertRaises(ReplacementUnavailableError):
            r.R("K")

    def test_to_dict_shape(self):
        r = ReplacementEngine(make_cfg(), POOLS)
        d = r.to_dict()
        self.assertEqual(d["QB"]["method"], "dynamic_vorp")
        self.assertIn("replacementRank", d["QB"])
        self.assertIn("worstStarterFpg", d["QB"])


if __name__ == "__main__":
    unittest.main()
