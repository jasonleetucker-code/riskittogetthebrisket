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
IDP_STAT_KEYS: tuple[str, ...] = (
    "idp_tkl_solo",
    "idp_tkl_ast",
    "idp_tkl_loss",
    "idp_sack",
    "idp_hit",
    "idp_int",
    "idp_pd",
    "idp_ff",
    "idp_fum_rec",
    "idp_def_td",
)


@dataclass
class LeagueScoring:
    league_id: str
    season: int | None
    scoring_map: dict[str, float] = field(default_factory=dict)
    idp_weights: dict[str, float] = field(default_factory=dict)
    unknown_keys: dict[str, float] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        present_idp = {k: v for k, v in self.idp_weights.items() if abs(v) > 0.0}
        return {
            "league_id": self.league_id,
            "season": self.season,
            "active_idp_stats": present_idp,
            "inactive_idp_stats": sorted(
                k for k in IDP_STAT_KEYS if abs(self.idp_weights.get(k, 0.0)) < 1e-9
            ),
            "unknown_key_count": len(self.unknown_keys),
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
    return LeagueScoring(
        league_id=str(league.get("league_id") or ""),
        season=season,
        scoring_map=scoring_map,
        idp_weights=idp_weights,
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
