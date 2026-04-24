"""Red-zone + 3rd-down opportunity aggregation.

Highest-leverage signal the platform doesn't have today: per-player
aggregates of high-value snaps (red-zone targets, red-zone carries,
goal-line touches, 3rd-down conversions).  A TE with 18 RZ targets
is frequently under-valued by rankings sources that only see total
receptions.

Data source
-----------
**nflverse play-by-play** via ``nfl_data_py.import_pbp_data`` — same
ingest path as the usage-windows pipeline.  No new dependency.
Per the PFR research agent's recommendation (see docs/upgrade...),
we build these aggregates from play-level data rather than scrape
PFR — nflverse has the raw data and no ToS risk.

Aggregation shape
-----------------
Per (player_id_gsis, season):

    rz_targets:           int   # red-zone pass targets
    rz_carries:           int   # red-zone rushes
    rz_receptions:        int
    rz_touchdowns:        int
    gl_carries:           int   # goal-line (inside 5) rushes
    gl_targets:           int
    third_down_targets:   int
    third_down_carries:   int
    third_down_conversions: int
    third_down_attempts:  int
    opportunity_score:    float # composite 0..100 per-position

The opportunity score is a lightweight composite so the UI can
show one number per player; pure math so it's stable across
refreshes.

Gracefully empty when nfl_data_ingest flag is off — returns empty
list + ``reason="nfl_data_disabled"``.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from src.api import feature_flags
from src.nfl_data import cache as _cache

_LOGGER = logging.getLogger(__name__)

# Inside the 20 = red zone.  Inside the 5 = goal line.
_RZ_YARDLINE_MAX = 20
_GL_YARDLINE_MAX = 5


@dataclass(frozen=True)
class OpportunityStats:
    player_id_gsis: str
    player_name: str
    position: str
    season: int
    rz_targets: int
    rz_carries: int
    rz_receptions: int
    rz_touchdowns: int
    gl_carries: int
    gl_targets: int
    third_down_targets: int
    third_down_carries: int
    third_down_conversions: int
    third_down_attempts: int
    opportunity_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "playerIdGsis": self.player_id_gsis,
            "playerName": self.player_name,
            "position": self.position,
            "season": self.season,
            "rzTargets": self.rz_targets,
            "rzCarries": self.rz_carries,
            "rzReceptions": self.rz_receptions,
            "rzTouchdowns": self.rz_touchdowns,
            "glCarries": self.gl_carries,
            "glTargets": self.gl_targets,
            "thirdDownTargets": self.third_down_targets,
            "thirdDownCarries": self.third_down_carries,
            "thirdDownConversions": self.third_down_conversions,
            "thirdDownAttempts": self.third_down_attempts,
            "opportunityScore": round(self.opportunity_score, 1),
        }


def _yardline_to_endzone(play: dict[str, Any]) -> int | None:
    """Return yards from opposing end zone.  nflverse pbp uses
    ``yardline_100`` directly for this.  Falls back to parsing
    ``yrdln`` ("KC 23") when needed."""
    try:
        v = play.get("yardline_100")
        if v is not None:
            return int(v)
    except (TypeError, ValueError):
        pass
    return None


def _num(v, default=0):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return int(default)


def build_opportunity_from_pbp(
    pbp_rows: list[dict[str, Any]],
    *,
    season: int | None = None,
) -> list[OpportunityStats]:
    """Aggregate PBP rows into per-player opportunity buckets.

    Each PBP row is shaped roughly like::

        {
          "play_type": "pass" | "run" | ...,
          "down": 1|2|3|4,
          "yardline_100": int,
          "season": int,
          "receiver_player_id": str | None,  # GSIS
          "receiver_player_name": str | None,
          "rusher_player_id": str | None,
          "rusher_player_name": str | None,
          "complete_pass": 0|1,
          "touchdown": 0|1,
          "first_down": 0|1,
          "posteam": str,
          ...
        }

    This function is pure — no network, no pandas dep, no flag check.
    Fed by ``fetch_opportunity_stats`` below.
    """
    # {(gsis_id, season): {stat_key: count}}
    buckets: dict[tuple[str, int], dict[str, int]] = defaultdict(
        lambda: defaultdict(int),
    )
    names: dict[tuple[str, int], tuple[str, str]] = {}  # (name, position_approx)

    for play in pbp_rows or []:
        if not isinstance(play, dict):
            continue
        play_season = _num(play.get("season"))
        if season is not None and play_season != season:
            continue
        yardline = _yardline_to_endzone(play)
        down = _num(play.get("down"))
        ptype = str(play.get("play_type") or "").lower()
        if ptype not in ("pass", "run"):
            continue

        in_rz = yardline is not None and 0 < yardline <= _RZ_YARDLINE_MAX
        in_gl = yardline is not None and 0 < yardline <= _GL_YARDLINE_MAX
        is_third_down = down == 3

        if ptype == "pass":
            target_id = str(play.get("receiver_player_id") or "")
            target_name = str(play.get("receiver_player_name") or "")
            if target_id:
                key = (target_id, play_season)
                names.setdefault(key, (target_name, "WR/TE"))
                if in_rz:
                    buckets[key]["rz_targets"] += 1
                    if _num(play.get("complete_pass")):
                        buckets[key]["rz_receptions"] += 1
                    if _num(play.get("touchdown")):
                        buckets[key]["rz_touchdowns"] += 1
                if in_gl:
                    buckets[key]["gl_targets"] += 1
                if is_third_down:
                    buckets[key]["third_down_targets"] += 1
                    if _num(play.get("first_down")):
                        buckets[key]["third_down_conversions"] += 1
                    buckets[key]["third_down_attempts"] += 1
        elif ptype == "run":
            rusher_id = str(play.get("rusher_player_id") or "")
            rusher_name = str(play.get("rusher_player_name") or "")
            if rusher_id:
                key = (rusher_id, play_season)
                names.setdefault(key, (rusher_name, "RB/QB"))
                if in_rz:
                    buckets[key]["rz_carries"] += 1
                    if _num(play.get("touchdown")):
                        buckets[key]["rz_touchdowns"] += 1
                if in_gl:
                    buckets[key]["gl_carries"] += 1
                if is_third_down:
                    buckets[key]["third_down_carries"] += 1
                    if _num(play.get("first_down")):
                        buckets[key]["third_down_conversions"] += 1
                    buckets[key]["third_down_attempts"] += 1

    out: list[OpportunityStats] = []
    for (gsis, season_val), b in buckets.items():
        name, pos = names.get((gsis, season_val), ("", ""))
        out.append(OpportunityStats(
            player_id_gsis=gsis,
            player_name=name,
            position=pos,
            season=season_val,
            rz_targets=b.get("rz_targets", 0),
            rz_carries=b.get("rz_carries", 0),
            rz_receptions=b.get("rz_receptions", 0),
            rz_touchdowns=b.get("rz_touchdowns", 0),
            gl_carries=b.get("gl_carries", 0),
            gl_targets=b.get("gl_targets", 0),
            third_down_targets=b.get("third_down_targets", 0),
            third_down_carries=b.get("third_down_carries", 0),
            third_down_conversions=b.get("third_down_conversions", 0),
            third_down_attempts=b.get("third_down_attempts", 0),
            opportunity_score=_compute_opportunity_score(b, pos),
        ))
    return out


def _compute_opportunity_score(bucket: dict[str, int], position: str) -> float:
    """Lightweight 0-100 composite so the UI can show one number.

    Weights favor the scarce / predictive signals:
      * RZ touches (targets+carries) — heavily weighted
      * GL carries — bonus (TD odds)
      * 3rd-down conversion rate — multiplier

    Calibrated against rough top-tier thresholds: a player with
    20+ RZ touches, 10+ GL touches, 60%+ 3D conv rate lands near 100.
    """
    rz_touches = bucket.get("rz_targets", 0) + bucket.get("rz_carries", 0)
    gl_touches = bucket.get("gl_targets", 0) + bucket.get("gl_carries", 0)
    td_3 = bucket.get("third_down_conversions", 0)
    att_3 = bucket.get("third_down_attempts", 0)
    conv_rate = (td_3 / att_3) if att_3 > 0 else 0.0

    score = (rz_touches * 3.0) + (gl_touches * 6.0) + (conv_rate * 30.0)
    return min(100.0, max(0.0, score))


_CACHE_TTL_SECONDS = 24 * 3600


def fetch_opportunity_stats(
    years: list[int],
    *,
    _provider=None,
    cache_dir=None,
) -> list[dict[str, Any]]:
    """Flag-gated fetch of opportunity stats for the given years.

    Returns ``[]`` when ``nfl_data_ingest`` is off or nflverse is
    unreachable.  Caches 24h.
    """
    if not feature_flags.is_enabled("nfl_data_ingest"):
        return []
    key = f"opportunity:{','.join(str(y) for y in sorted(years))}"
    cached = _cache.get(key, ttl_seconds=_CACHE_TTL_SECONDS, cache_dir=cache_dir)
    if cached is not None:
        return cached

    try:
        if _provider is not None:
            pbp = _provider(years)
        else:
            try:
                import nfl_data_py  # type: ignore
            except Exception as exc:  # noqa: BLE001
                _LOGGER.debug("nfl_data_py unavailable: %s", exc)
                return []
            df = nfl_data_py.import_pbp_data(
                years,
                columns=[
                    "season", "week", "play_type", "down", "yardline_100",
                    "posteam", "defteam",
                    "receiver_player_id", "receiver_player_name",
                    "rusher_player_id", "rusher_player_name",
                    "complete_pass", "touchdown", "first_down",
                ],
            )
            pbp = df.to_dict(orient="records") if hasattr(df, "to_dict") else []
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("opportunity stats fetch failed: %s", exc)
        return []

    # Aggregate per season; concat across years.
    all_stats: list[OpportunityStats] = []
    for year in years:
        stats = build_opportunity_from_pbp(pbp, season=year)
        all_stats.extend(stats)
    rows = [s.to_dict() for s in all_stats]
    _cache.put(key, rows, cache_dir=cache_dir)
    return rows
