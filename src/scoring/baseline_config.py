from __future__ import annotations

from typing import Dict, List

from .types import ScoringConfig


BASELINE_SCORING_VERSION = "baseline-test-v2-2026-03-09"


# Baseline is a comparison environment only. It is not the live league.
BASELINE_SCORING_MAP: Dict[str, float] = {
    # Passing
    "pass_yd": 0.04,
    "pass_td": 4.0,
    "pass_int": -2.0,
    "pass_fd": 0.0,
    "pass_cmp": 0.0,
    "pass_inc": 0.0,
    # Rushing
    "rush_yd": 0.1,
    "rush_td": 6.0,
    "rush_fd": 0.0,
    # Receiving
    "rec_yd": 0.1,
    "rec_td": 6.0,
    "rec_fd": 0.0,
    "rec": 1.0,
    # Position-asymmetric reception aliases
    "bonus_rec_rb": 0.0,
    "bonus_rec_wr": 0.0,
    "bonus_rec_te": 0.5,
    # First-down aliases
    "bonus_fd_qb": 0.0,
    "bonus_fd_rb": 0.0,
    "bonus_fd_wr": 0.0,
    "bonus_fd_te": 0.0,
    # Turnovers
    "fum": -1.0,
    "fum_lost": -2.0,
    # Bonuses
    "bonus_pass_yd_300": 0.0,
    "bonus_rush_yd_100": 0.0,
    "bonus_rec_yd_100": 0.0,
    "bonus_pass_td_50+": 0.0,
    "bonus_rush_td_40+": 0.0,
    "bonus_rec_td_40+": 0.0,
    # Returns
    "kick_ret_td": 0.0,
    "punt_ret_td": 0.0,
    # IDP
    "idp_tkl_solo": 1.5,
    "idp_tkl_ast": 0.75,
    "idp_tkl_loss": 1.0,
    "idp_sack": 4.0,
    "idp_hit": 1.0,
    "idp_int": 4.0,
    "idp_pd": 1.5,
    "idp_ff": 3.0,
    "idp_fum_rec": 3.0,
    "idp_def_td": 6.0,
}


DEFAULT_ROSTER_POSITIONS: List[str] = [
    "QB",
    "RB",
    "WR",
    "TE",
    "FLEX",
    "SUPER_FLEX",
    "DL",
    "LB",
    "DB",
]


def build_default_baseline_config(league_id: str = "baseline-test-default", season: int | None = None) -> ScoringConfig:
    return ScoringConfig(
        scoring_version=BASELINE_SCORING_VERSION,
        league_id=str(league_id),
        season=season,
        roster_positions=list(DEFAULT_ROSTER_POSITIONS),
        scoring_map=dict(BASELINE_SCORING_MAP),
        metadata={
            "kind": "baseline_comparison_only",
            "notes": "Used only for scoring translation, never as live league scoring.",
        },
    )

