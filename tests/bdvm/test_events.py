"""Structured event system: closed ontology, decay, module targeting."""

from __future__ import annotations

import math
import unittest

from src.bdvm.engine import DynastyEngine, PlayerInput
from src.bdvm.events import (
    EventError,
    PlayerEvent,
    apply_events,
    decay_scale,
    effective_impact,
)
from src.bdvm.league_config import BdvmLeagueConfig, DEFAULT_POS_GROUPS
from src.bdvm.params import load_param_set
from src.bdvm.replacement import ReplacementEngine

PARAMS = load_param_set("params_v1")


def ev(
    event_type="DEPTH_CHART_COMPETITION_ADDED",
    *,
    confidence=1.0,
    reliability=1.0,
    effective="2026-07-20",
    reflected=False,
    impact=None,
    half_life=None,
):
    return PlayerEvent(
        event_id="e1",
        player_key="x",
        event_type=event_type,
        effective_date=effective,
        confidence=confidence,
        source_reliability=reliability,
        already_in_projection=reflected,
        impact=impact,
        half_life_days=half_life,
    )


class TestDecayAndOntology(unittest.TestCase):
    def test_unknown_event_type_rejected(self):
        with self.assertRaises(EventError):
            effective_impact(ev("VIBES_SHIFT"), "2026-07-27")

    def test_reflected_event_contributes_nothing(self):
        self.assertEqual(decay_scale(ev(reflected=True), "2026-07-27"), 0.0)
        self.assertEqual(effective_impact(ev(reflected=True), "2026-07-27"), {})

    def test_half_life_decay(self):
        fresh = decay_scale(ev(effective="2026-07-27"), "2026-07-27")
        self.assertAlmostEqual(fresh, 1.0)
        # DEPTH_CHART_COMPETITION_ADDED half-life is 45 days
        halved = decay_scale(ev(effective="2026-06-12"), "2026-07-27")
        self.assertAlmostEqual(halved, 0.5, places=2)

    def test_confidence_and_reliability_scale(self):
        s = decay_scale(ev(confidence=0.8, reliability=0.5, effective="2026-07-27"), "2026-07-27")
        self.assertAlmostEqual(s, 0.4)

    def test_speculation_widens_sigma_only(self):
        impact = effective_impact(ev(confidence=0.4), "2026-07-27")
        self.assertIn("sigma_mult", impact)
        self.assertNotIn("mu_pct", impact)
        self.assertNotIn("role_security_delta", impact)
        self.assertNotIn("hazard_mult", impact)

    def test_multiplicative_channels_scale_in_log_space(self):
        full = effective_impact(ev(), "2026-07-27")["sigma_mult"]
        half = effective_impact(ev(confidence=0.5), "2026-07-27")["sigma_mult"]
        self.assertAlmostEqual(half, math.exp(math.log(full) * 0.5), places=9)


class TestApplyEvents(unittest.TestCase):
    def _player(self, **kw):
        defaults = dict(
            player_id="p", name="p", position="WR", age=25.0, nfl_season=3, fpg=12.0, games=16.0
        )
        defaults.update(kw)
        return PlayerInput(**defaults)

    def test_mu_and_risk_and_games_channels(self):
        p = self._player()
        adjusted, audit = apply_events(p, [ev()], as_of="2026-07-20")
        # DEPTH_CHART_COMPETITION_ADDED: mu -8%, role_security -0.15,
        # sigma x1.20, hazard x1.10 at full strength
        self.assertAlmostEqual(adjusted.fpg, 12.0 * 0.92, places=6)
        self.assertAlmostEqual(adjusted.risk.role_security, 0.6 - 0.15, places=6)
        self.assertAlmostEqual(adjusted.event_sigma_mult, 1.20, places=6)
        self.assertAlmostEqual(adjusted.event_hazard_mult, 1.10, places=6)
        self.assertTrue(audit[0]["applied"])
        # original untouched
        self.assertEqual(p.fpg, 12.0)

    def test_injury_reduces_games_with_clamps(self):
        p = self._player(games=16.5)
        adjusted, _ = apply_events(
            p, [ev("SUSPENSION", impact={"games_delta": -30.0})], as_of="2026-07-20"
        )
        self.assertEqual(adjusted.games, 0.0)  # clamped, never negative

    def test_no_events_is_identity(self):
        p = self._player()
        adjusted, audit = apply_events(p, [], as_of="2026-07-27")
        self.assertIs(adjusted, p)
        self.assertEqual(audit, [])

    def test_event_never_touches_final_score_directly(self):
        """Events shift module inputs; the value change must flow through
        the engine (hazard hook lowers survival → lower value)."""
        cfg = BdvmLeagueConfig(
            league_key="t",
            teams=12,
            starters={"WR": 3},
            flex={},
            waiver_buffer={"WR": 1.0},
            default_buffer=0.5,
            pos_groups=dict(DEFAULT_POS_GROUPS),
            scoring_settings={"rec": 1.0},
        )
        pools = {"WR": lambda r: 19.0 * math.exp(-0.024 * max(0, r - 1))}
        engine = DynastyEngine(cfg, ReplacementEngine(cfg, pools), PARAMS, pools=pools)
        p = self._player(fpg=14.0)
        demoted, _ = apply_events(p, [ev("DEPTH_CHART_DEMOTION")], as_of="2026-07-20")
        v_base = engine.fundamental_values(p)["balanced"]
        v_demoted = engine.fundamental_values(demoted)["balanced"]
        self.assertLess(v_demoted, v_base)


if __name__ == "__main__":
    unittest.main()
