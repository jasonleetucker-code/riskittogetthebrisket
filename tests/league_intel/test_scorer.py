"""LI-2 — deterministic exact scorer: unit tests for every stacking rule.

Rates here are the live 2026 league rates (canonical snapshot).  The
stacking MECHANICS asserted here were empirically confirmed against
Sleeper-awarded 2025 scores (see test_golden_scoring.py and
docs/league-intelligence/SCORING_VALIDATION.md): Sleeper scoring is a
pure dot product over the keys present in both the stat line and the
scoring settings — every co-present key stacks.
"""

from __future__ import annotations

import pytest

from src.league_intel.config import load_canonical_config
from src.league_intel.scorer import score_stat_line

TOL = 0.01


@pytest.fixture(scope="module")
def cfg():
    return load_canonical_config()


def total(stat_line, cfg):
    return score_stat_line(stat_line, cfg).total_points


class TestPickSixStacking:
    def test_pick_six_charges_both_keys(self, cfg):
        """Sleeper stat lines carry pass_int AND pass_int_td for a
        pick-six (empirical: 2025 w1 pid 11565 had pass_int=1,
        pass_int_td=1).  Both rates apply: -4 + -2 = -6."""
        bd = score_stat_line({"pass_int": 1, "pass_int_td": 1}, cfg)
        assert bd.total_points == pytest.approx(-6.0, abs=TOL)
        keys = {c.scoring_key for c in bd.components}
        assert keys == {"pass_int", "pass_int_td"}

    def test_non_returned_int_only_base_penalty(self, cfg):
        assert total({"pass_int": 2}, cfg) == pytest.approx(-8.0, abs=TOL)


class TestReceptionStacking:
    def test_base_rec_stacks_with_distance_band(self, cfg):
        """rec (0.08) + band both award: a 12-yard catch = rec 0.08 +
        rec_10_19 0.67 + 12 × rec_yd 0.05."""
        line = {"rec": 1, "rec_10_19": 1, "rec_yd": 12}
        rate_yd = cfg.scoring_settings["rec_yd"]
        assert total(line, cfg) == pytest.approx(0.08 + 0.67 + 12 * rate_yd, abs=TOL)

    def test_bands_are_per_reception_counts(self, cfg):
        line = {"rec": 3, "rec_0_4": 1, "rec_5_9": 1, "rec_40p": 1, "rec_yd": 55}
        expected = 3 * 0.08 + 0.17 + 0.42 + 1.92 + 55 * cfg.scoring_settings["rec_yd"]
        assert total(line, cfg) == pytest.approx(expected, abs=TOL)


class TestFirstDownBonuses:
    def test_bonus_fd_stat_drives_position_bonus(self, cfg):
        """Sleeper precomputes bonus_fd_<pos> as a stat key equal to
        first downs gained (empirical: bonus_fd_rb == rush_fd + rec_fd
        on every 2025 sample; bonus_fd_qb also counts pass_fd).  The
        generic pass_fd/rush_fd/rec_fd rates are 0 in this league, so
        the position bonus is the only first-down scoring."""
        line = {"bonus_fd_rb": 3, "rush_fd": 2, "rec_fd": 1}
        bd = score_stat_line(line, cfg)
        assert bd.total_points == pytest.approx(3 * 1.0, abs=TOL)
        # rush_fd / rec_fd appear as zero-point components (explainability)
        zero_keys = {c.scoring_key for c in bd.components if c.rate == 0.0}
        assert {"rush_fd", "rec_fd"} <= zero_keys

    def test_qb_first_down_rate(self, cfg):
        assert total({"bonus_fd_qb": 12}, cfg) == pytest.approx(12 * 0.67, abs=TOL)


class TestIdpStacking:
    def test_sack_play_stacks_all_events(self, cfg):
        """One sack play emits idp_sack + idp_sack_yd + idp_qb_hit +
        idp_tkl_loss + idp_tkl_solo (+ idp_tkl) simultaneously
        (empirical: 2025 w1 pid 10970).  All nonzero rates award."""
        s = cfg.scoring_settings
        line = {
            "idp_sack": 1,
            "idp_sack_yd": 7,
            "idp_qb_hit": 1,
            "idp_tkl_loss": 1,
            "idp_tkl_solo": 1,
            "idp_tkl": 1,  # rate 0 in this league — zero-point component
        }
        expected = (
            s["idp_sack"]
            + 7 * s["idp_sack_yd"]
            + s["idp_qb_hit"]
            + s["idp_tkl_loss"]
            + s["idp_tkl_solo"]
        )
        bd = score_stat_line(line, cfg)
        assert bd.total_points == pytest.approx(expected, abs=TOL)

    def test_individual_defender_block_uses_idp_key(self, cfg):
        """Individual defenders carry idp_blk_kick only; the plain
        blk_kick stat appears solely on TEAM/DEF rows (empirical, all
        2025 samples) — no double-counting for rostered players."""
        assert total({"idp_blk_kick": 1}, cfg) == pytest.approx(5.32, abs=TOL)


class TestKicker:
    def test_pure_per_yard_field_goals(self, cfg):
        """fgm rate is 0 (no base make points); fgm_yds 0.07/yd."""
        line = {"fgm": 2, "fgm_yds": 94, "xpm": 2, "xpa": 2, "fga": 2}
        bd = score_stat_line(line, cfg)
        assert bd.total_points == pytest.approx(94 * 0.07 + 2 * 2.31, abs=TOL)
        assert any(c.scoring_key == "fgm" and c.awarded_points == 0.0 for c in bd.components)

    def test_miss_bands_stack_with_base_miss(self, cfg):
        s = cfg.scoring_settings
        line = {"fgmiss": 1, "fgmiss_50_59": 1, "xpmiss": 1}
        expected = s["fgmiss"] + s["fgmiss_50_59"] + s["xpmiss"]
        assert total(line, cfg) == pytest.approx(expected, abs=TOL)


class TestScorerContract:
    def test_pure_dot_product_over_shared_keys(self, cfg):
        """Keys absent from scoring settings are ignored entirely."""
        bd = score_stat_line({"gp": 1, "off_snp": 60, "fgm_pct": 100.0}, cfg)
        assert bd.total_points == 0.0
        assert bd.components == []
        assert bd.warnings == []

    def test_deterministic_component_order_and_total(self, cfg):
        line_a = {"rush_yd": 88, "rec": 4, "rec_yd": 31, "rush_td": 1}
        line_b = dict(reversed(list(line_a.items())))
        a = score_stat_line(line_a, cfg)
        b = score_stat_line(line_b, cfg)
        assert a.total_points == b.total_points  # bit-identical, not approx
        assert [c.scoring_key for c in a.components] == [c.scoring_key for c in b.components]
        assert [c.scoring_key for c in a.components] == sorted(c.scoring_key for c in a.components)

    def test_non_numeric_stat_warns_and_skips(self, cfg):
        bd = score_stat_line({"rush_yd": "n/a", "rec": 2}, cfg)
        assert bd.total_points == pytest.approx(2 * 0.08, abs=TOL)
        assert len(bd.warnings) == 1 and "rush_yd" in bd.warnings[0]

    def test_none_stat_skipped_silently(self, cfg):
        bd = score_stat_line({"rush_yd": None, "rec": 1}, cfg)
        assert bd.total_points == pytest.approx(0.08, abs=TOL)
        assert bd.warnings == []

    def test_accepts_plain_scoring_mapping(self):
        bd = score_stat_line({"rush_yd": 10}, {"rush_yd": 0.1})
        assert bd.total_points == pytest.approx(1.0, abs=TOL)

    def test_rejects_bad_config_type(self):
        with pytest.raises(TypeError):
            score_stat_line({"rush_yd": 10}, 42)

    def test_to_dict_shape(self, cfg):
        d = score_stat_line({"rush_td": 1}, cfg).to_dict()
        assert set(d) == {"totalPoints", "components", "warnings"}
        assert d["components"][0] == {
            "scoringKey": "rush_td",
            "rawStat": 1.0,
            "rate": 6.0,
            "awardedPoints": 6.0,
        }
