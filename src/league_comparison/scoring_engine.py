"""Apply a Sleeper ``scoring_settings`` dict to weekly NFL stat rows
and aggregate to per-player season totals.

This module is a thin orchestrator around the existing
:func:`src.nfl_data.realized_points.compute_weekly_points` — which is
already the single source of truth for Sleeper-format fantasy scoring.

Output: a list of :class:`PlayerSeasonScore` records, one per
``(player_id_gsis, position, season)`` triple, that downstream metrics
code can sort/filter/sample.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from src.nfl_data import realized_points as _rp
from src.utils.name_clean import POSITION_ALIASES

_LOGGER = logging.getLogger(__name__)


# Positions we report on (offense + IDP).  Anything else (kickers,
# team defenses, OL/HC/etc) is dropped — out of scope for a positional
# scoring-balance comparison.
_OFFENSE_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})
_IDP_POSITIONS = frozenset({"DL", "LB", "DB"})
_TRACKED_POSITIONS = _OFFENSE_POSITIONS | _IDP_POSITIONS


@dataclass(frozen=True)
class PlayerSeasonScore:
    player_id: str
    player_name: str
    position: str          # canonicalised: QB / RB / WR / TE / DL / LB / DB
    raw_position: str      # what nflverse reported (DT, EDGE, OLB, etc.)
    season: int
    total_points: float
    games_played: int


def _canonical_position(raw_pos: str | None) -> str | None:
    """Map a raw nflverse position to one of our tracked groups, or None.

    Uses ``POSITION_ALIASES`` from ``src.utils.name_clean`` for the
    standard offense aliases, and an explicit IDP collapse table since
    nflverse uses fine-grained labels (DT/DE/EDGE → DL, ILB/OLB/MLB →
    LB, CB/S/FS/SS → DB).
    """
    if not raw_pos:
        return None
    raw = str(raw_pos).strip().upper()
    if not raw:
        return None
    aliased = POSITION_ALIASES.get(raw, raw)
    if aliased in _OFFENSE_POSITIONS:
        return aliased
    # IDP collapse — keep this local to scoring_engine; not all callers
    # of POSITION_ALIASES want this collapse.
    if aliased in {"DL", "DT", "DE", "EDGE", "NT"}:
        return "DL"
    if aliased in {"LB", "ILB", "OLB", "MLB"}:
        return "LB"
    if aliased in {"DB", "CB", "S", "FS", "SS"}:
        return "DB"
    return None


def compute_player_season_scores(
    rows: Iterable[dict[str, Any]],
    scoring_settings: dict[str, Any],
    *,
    season: int | None = None,
) -> list[PlayerSeasonScore]:
    """Aggregate weekly rows to season totals under one league's scoring.

    ``rows`` is the output of ``fetch_weekly_stats`` — already a list of
    plain dicts.  ``scoring_settings`` is the Sleeper dict from
    ``LeagueScoringInfo.scoring_settings``.

    ``season`` is informational; if None we infer it from the rows.
    """
    if not scoring_settings:
        return []

    # Group by (player_id, season) so a multi-team year stays unified
    # (player traded mid-season — rows from both teams roll into one
    # season total).
    bucket: dict[tuple[str, int], dict[str, Any]] = defaultdict(
        lambda: {
            "name": "",
            "raw_position": "",
            "canonical": None,
            "total": 0.0,
            "games": 0,
        }
    )

    for row in rows or []:
        pid = str(row.get("player_id") or row.get("player_id_gsis") or "").strip()
        if not pid:
            continue
        raw_pos = str(row.get("position") or "").strip().upper()
        canonical = _canonical_position(raw_pos)
        if canonical not in _TRACKED_POSITIONS:
            continue
        try:
            row_season = int(row.get("season") or season or 0)
        except (TypeError, ValueError):
            continue
        if row_season <= 0:
            continue

        rp = _rp.compute_weekly_points(row, scoring_settings, position=canonical)
        if rp is None:
            continue
        pts = float(rp.fantasy_points)

        key = (pid, row_season)
        b = bucket[key]
        if not b["name"]:
            b["name"] = str(row.get("player_display_name") or row.get("player_name") or pid)
        if not b["raw_position"]:
            b["raw_position"] = raw_pos
        b["canonical"] = canonical
        b["total"] += pts
        # Count any game where the player had a stat row, regardless
        # of whether they scored — matches the "games played" intuition
        # for sample sizes.
        b["games"] += 1

    out: list[PlayerSeasonScore] = []
    for (pid, yr), b in bucket.items():
        if b["canonical"] is None:
            continue
        out.append(
            PlayerSeasonScore(
                player_id=pid,
                player_name=b["name"],
                position=b["canonical"],
                raw_position=b["raw_position"],
                season=yr,
                total_points=round(float(b["total"]), 2),
                games_played=int(b["games"]),
            )
        )
    return out
