"""Extract and normalize a Sleeper league's scoring settings.

Uses ``src.scoring.sleeper_ingest.KEY_ALIASES`` for the canonical
stat-key mapping. The calibration math only cares about the IDP stat
weights, but we preserve offensive weights too so a future offense
calibration can share the same parsing path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.scoring.sleeper_ingest import KEY_ALIASES

# Canonical IDP stat keys the VOR engine knows how to score.
# Must stay in lockstep with the right-hand-side values of
# src/scoring/sleeper_ingest.py::KEY_ALIASES (the canonical names).
# Every key added here should also be pulled from the player stat
# payload in src/idp_calibration/stats_adapter.py so weighted scoring
# has something to consume.
IDP_STAT_KEYS: tuple[str, ...] = (
    # Tackles
    "idp_tkl_solo",
    "idp_tkl_ast",
    "idp_tkl",
    "idp_tkl_loss",
    "idp_tkl_ast_loss",
    # Pressure
    "idp_sack",
    "idp_sack_yd",
    "idp_hit",
    # Turnovers
    "idp_int",
    "idp_int_ret_yd",
    "idp_pd",
    "idp_pass_def_3p",
    "idp_ff",
    "idp_fum_rec",
    "idp_fum_ret_yd",
    # Scoring
    "idp_def_td",
    "idp_safe",
    "idp_blk_kick",
    "idp_def_pr_td",
    "idp_def_kr_td",
    # Volume bonuses
    "idp_tkl_10p",
    "idp_tkl_5p",
)

# Canonical offense stat keys. The cross-family calibration layer
# needs these so we can rescore QB/RB/WR/TE season stats under each
# league's scoring rules and compute offense VOR. Every key here must
# also appear on the RHS of src/scoring/sleeper_ingest.py::KEY_ALIASES.
OFFENSE_STAT_KEYS: tuple[str, ...] = (
    # Passing
    "pass_yd",
    "pass_td",
    "pass_int",
    "pass_int_td",
    "pass_cmp",
    "pass_inc",
    "pass_sack",
    "pass_fd",
    "bonus_pass_yd_300",
    "bonus_pass_td_50+",
    "bonus_fd_qb",
    # Rushing
    "rush_yd",
    "rush_td",
    "rush_fd",
    "bonus_rush_yd_100",
    "bonus_rush_td_40+",
    "bonus_fd_rb",
    # Receiving — flat PPR + tiered PPR buckets (0-4, 5-9, 10-19,
    # 20-29, 30-39, 40+) so leagues that score receptions by catch
    # length get per-bucket credit instead of falling back to flat.
    "rec",
    "rec_0_4",
    "rec_5_9",
    "rec_10_19",
    "rec_20_29",
    "rec_30_39",
    "rec_40p",
    "rec_yd",
    "rec_td",
    "rec_2pt",
    "rec_fd",
    "bonus_rec_rb",
    "bonus_rec_wr",
    "bonus_rec_te",
    "bonus_rec_yd_100",
    "bonus_rec_td_40+",
    "bonus_fd_wr",
    "bonus_fd_te",
    # Turnovers (shared penalty)
    "fum",
    "fum_lost",
    # Return TDs (rare)
    "kick_ret_td",
    "punt_ret_td",
)


@dataclass
class LeagueScoring:
    league_id: str
    season: int | None
    scoring_map: dict[str, float] = field(default_factory=dict)
    idp_weights: dict[str, float] = field(default_factory=dict)
    offense_weights: dict[str, float] = field(default_factory=dict)
    unknown_keys: dict[str, float] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        present_idp = {k: v for k, v in self.idp_weights.items() if abs(v) > 0.0}
        present_offense = {
            k: v for k, v in self.offense_weights.items() if abs(v) > 0.0
        }
        unknown_idp = {
            k: v
            for k, v in self.unknown_keys.items()
            if k.lower().startswith("idp") and abs(v) > 1e-9
        }
        return {
            "league_id": self.league_id,
            "season": self.season,
            "active_idp_stats": present_idp,
            "inactive_idp_stats": sorted(
                k for k in IDP_STAT_KEYS if abs(self.idp_weights.get(k, 0.0)) < 1e-9
            ),
            "active_offense_stats": present_offense,
            "unknown_key_count": len(self.unknown_keys),
            "unknown_idp_keys": unknown_idp,
        }


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_scoring(league: dict[str, Any] | None) -> LeagueScoring:
    if not isinstance(league, dict):
        return LeagueScoring(league_id="", season=None)
    raw = league.get("scoring_settings") or {}
    scoring_map: dict[str, float] = {}
    unknown: dict[str, float] = {}
    if isinstance(raw, dict):
        for key, val in raw.items():
            fv = _to_float(val)
            if fv is None:
                continue
            canonical = KEY_ALIASES.get(str(key).strip())
            if canonical:
                # Keep the strongest non-zero weight if duplicates resolve to the
                # same canonical key (e.g. ``idp_solo`` vs ``idp_tkl_solo``).
                prior = scoring_map.get(canonical, 0.0)
                if abs(fv) >= abs(prior):
                    scoring_map[canonical] = fv
            else:
                unknown[str(key).strip()] = fv
    season = None
    try:
        season = int(str(league.get("season") or "").strip())
    except (TypeError, ValueError):
        season = None
    idp_weights = {k: float(scoring_map.get(k, 0.0)) for k in IDP_STAT_KEYS}
    offense_weights = {k: float(scoring_map.get(k, 0.0)) for k in OFFENSE_STAT_KEYS}
    return LeagueScoring(
        league_id=str(league.get("league_id") or ""),
        season=season,
        scoring_map=scoring_map,
        idp_weights=idp_weights,
        offense_weights=offense_weights,
        unknown_keys=unknown,
    )


def score_line(stat_line: dict[str, Any], weights: dict[str, float]) -> float:
    """Dot-product a normalized stat line against IDP weights.

    ``stat_line`` is expected to be keyed by canonical stat names (same
    alias set as ``KEY_ALIASES`` values). Missing keys contribute 0.
    """
    total = 0.0
    if not stat_line or not weights:
        return 0.0
    for key, weight in weights.items():
        raw = stat_line.get(key)
        if raw is None:
            continue
        try:
            total += float(raw) * float(weight)
        except (TypeError, ValueError):
            continue
    return total
