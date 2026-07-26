"""LI-7 / ADR-009 — TE-premium invariants that must not silently break.

Two load-bearing facts about how TE value is priced, both verified in
code rather than trusted from comments:

1. The market anchor ``ktcSfTep`` is a TE++ board — KTC publishes it
   for leagues that start two TEs, so it ALREADY embeds the structural
   2-TE premium.  It must therefore receive neither blend-time TE
   multiplier, or the anchor itself would be double-counted.
2. The league grants TEs no *scoring* premium in 2026: a TE and a WR
   with identical receiving lines score identically.  Any future
   league-adjusted TE correction must be netted against what the blend
   already embeds, never stacked on top of it.
"""

from __future__ import annotations

import pytest

from src.league_intel.config import load_canonical_config
from src.league_intel.scorer import score_stat_line

TOL = 0.01


class TestMarketAnchorExemption:
    """Guards against re-introducing a double-count on the anchor."""

    def test_both_ktc_boards_are_exempt_from_both_multipliers(self):
        from src.api.data_contract import _TE_BLANKET_KTC_EXEMPT_KEYS

        assert "ktcSfTep" in _TE_BLANKET_KTC_EXEMPT_KEYS
        assert "ktc" in _TE_BLANKET_KTC_EXEMPT_KEYS

    def test_exemption_gates_the_whole_multiplier_block(self):
        """The exemption must guard BOTH the non-native and native
        branches.  If a refactor ever moves one branch outside the
        `source_key not in _TE_BLANKET_KTC_EXEMPT_KEYS` guard, the
        market anchor starts getting boosted and this test fails."""
        import inspect

        from src.api import data_contract

        src = inspect.getsource(data_contract._compute_unified_rankings)
        guard = "if row_is_te and source_key not in _TE_BLANKET_KTC_EXEMPT_KEYS:"
        assert guard in src, "TE multiplier exemption guard changed shape — re-verify ADR-009"

        after = src.split(guard, 1)[1]
        block = after.split("all_values.append", 1)[0]
        # Both multiplier applications must live inside the guarded block.
        assert "effective_non_tep_multiplier" in block
        assert "effective_native_multiplier" in block

    def test_multiplier_constants_are_where_adr_009_says(self):
        from src.api.data_contract import (
            _TE_BLANKET_NATIVE_MULTIPLIER,
            _TE_BLANKET_NON_NATIVE_MULTIPLIER,
        )

        # Pinned so a change is a deliberate, reviewed act — ADR-009
        # explains why these are NOT the league's own TE premium.
        assert _TE_BLANKET_NON_NATIVE_MULTIPLIER == 1.15
        assert _TE_BLANKET_NATIVE_MULTIPLIER == 1.10


class TestLeagueHasNoTeScoringPremium:
    """The empirical basis for ADR-009's retraction."""

    @pytest.fixture(scope="class")
    @classmethod
    def cfg(cls):
        return load_canonical_config()

    RECEIVING = {"rec": 6, "rec_yd": 78, "rec_td": 1, "rec_10_19": 3, "rec_20_29": 1, "rec_0_4": 2}

    def test_te_and_wr_score_identically_in_2026(self, cfg):
        te = dict(self.RECEIVING, bonus_fd_te=4)
        wr = dict(self.RECEIVING, bonus_fd_wr=4)
        te_pts = score_stat_line(te, cfg).total_points
        wr_pts = score_stat_line(wr, cfg).total_points
        assert te_pts == pytest.approx(wr_pts, abs=TOL)
        assert te_pts == pytest.approx(21.55, abs=TOL)

    def test_te_bonus_keys_are_genuinely_zero_not_absent(self, cfg):
        """`bonus_rec_te: 0.0` is an exposed zero, not missing data —
        the exact inference ADR-009 retracts."""
        assert "bonus_rec_te" in cfg.scoring_settings
        assert cfg.scoring_settings["bonus_rec_te"] == 0.0
        assert cfg.scoring_settings["bonus_fd_te"] == cfg.scoring_settings["bonus_fd_wr"] == 1.0

    def test_2025_did_have_a_premium(self):
        """Control: the same comparison on 2025 rates shows +16.2%, so
        the 2026 result is a real change, not a broken comparison."""
        import json
        from pathlib import Path

        rates = json.loads(
            (Path(__file__).parent / "fixtures" / "scoring_settings_2025.json").read_text()
        )
        te = dict(self.RECEIVING, bonus_fd_te=4, bonus_rec_te=6)
        wr = dict(self.RECEIVING, bonus_fd_wr=4)
        te_pts = score_stat_line(te, rates).total_points
        wr_pts = score_stat_line(wr, rates).total_points
        assert te_pts > wr_pts
        assert te_pts / wr_pts == pytest.approx(1.162, abs=0.002)
