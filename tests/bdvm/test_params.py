"""Parameter-set loading, hashing, and lookup guards."""

from __future__ import annotations

import unittest

from src.bdvm.params import ParamSetError, load_param_set, reload


class TestParamSet(unittest.TestCase):
    def setUp(self):
        reload()
        self.ps = load_param_set("params_v1")

    def test_param_set_id_is_content_hash(self):
        self.assertTrue(self.ps.param_set_id.startswith("params_v1:"))
        self.assertEqual(len(self.ps.param_set_id.split(":")[1]), 12)
        # stable across loads
        reload()
        self.assertEqual(load_param_set("params_v1").param_set_id, self.ps.param_set_id)

    def test_unknown_set_raises(self):
        with self.assertRaises(ParamSetError):
            load_param_set("params_does_not_exist")

    def test_age_curves_cover_all_positions(self):
        for key in ("QB_pocket", "QB_dual", "RB", "WR", "TE", "DT", "EDGE", "LB", "CB", "S"):
            peak, c_up, c_dn = self.ps.age_curve(key)
            self.assertGreater(peak, 20.0)
            self.assertGreater(c_up, 0.0)
            self.assertGreater(c_dn, 0.0)
        with self.assertRaises(ParamSetError):
            self.ps.age_curve("KICKER")

    def test_modelling_position_fallbacks(self):
        self.assertEqual(self.ps.modelling_position("DT"), "DT")
        self.assertEqual(self.ps.modelling_position("DL"), "EDGE")
        self.assertEqual(self.ps.modelling_position("DB"), "S")
        self.assertEqual(self.ps.modelling_position("LB"), "LB")
        with self.assertRaises(ParamSetError):
            self.ps.modelling_position("PUNTER")

    def test_strategies_include_risk_neutral(self):
        names = self.ps.strategy_names()
        for expected in ("contender", "balanced", "rebuilder", "risk_neutral"):
            self.assertIn(expected, names)
        rn = self.ps.strategy("risk_neutral")
        self.assertEqual(float(rn["risk_lambda"]), 0.0)

    def test_meta_fields(self):
        meta = self.ps.to_meta()
        self.assertIn("paramSetId", meta)
        self.assertEqual(meta["modelVersion"], "1.0.0")


if __name__ == "__main__":
    unittest.main()
