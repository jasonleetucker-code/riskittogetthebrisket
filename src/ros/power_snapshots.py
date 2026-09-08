"""Immutable public-safe weekly snapshots for canonical Power Rankings.

The live Power engine can recalculate whenever fresh ROS/player data lands. A
league-share movement arrow cannot: once Week N is published, Week N must keep
meaning the same ranking forever. This module owns that small append-only
publication record.

Only already-public Power outputs are persisted here. Raw team-strength rows,
lineups, player values, health/depth decomposition and other private ROS inputs
must never enter this store.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.ros import ROS_DATA_DIR

SCHEMA_VERSION = 1


def _safe_part(value: str) -> str:
    safe = "".join(c for c in str(value or "") if c.isalnum() or c in {"_", "-"})
    if not safe:
        raise ValueError("snapshot key may not be empty")
    return safe


def snapshot_path(league_key: str, season: str | int, week: int) -> Path:
    if int(week) < 1:
        raise ValueError("weekly Power snapshots require week >= 1")
    return (
        ROS_DATA_DIR
        / "power_snapshots"
        / _safe_part(league_key)
        / _safe_part(str(season))
        / f"week_{int(week):02d}.json"
    )


def load_snapshot(league_key: str, season: str | int, week: int) -> dict[str, Any] | None:
    path = snapshot_path(league_key, season, week)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def latest_snapshot(
    league_key: str,
    *,
    season: str | int | None = None,
) -> dict[str, Any] | None:
    root = ROS_DATA_DIR / "power_snapshots" / _safe_part(league_key)
    if not root.exists():
        return None
    season_dirs = [root / _safe_part(str(season))] if season is not None else list(root.iterdir())
    candidates: list[tuple[int, int, Path]] = []
    for season_dir in season_dirs:
        if not season_dir.is_dir():
            continue
        try:
            season_num = int(season_dir.name)
        except ValueError:
            season_num = 0
        for path in season_dir.glob("week_*.json"):
            try:
                week_num = int(path.stem.split("_", 1)[1])
            except (ValueError, IndexError):
                continue
            candidates.append((season_num, week_num, path))
    if not candidates:
        return None
    _, _, path = max(candidates, key=lambda item: (item[0], item[1]))
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def scoring_config_fingerprint(snapshot: Any) -> str:
    """Stable fingerprint of current season scoring and roster configuration."""
    current = getattr(snapshot, "current_season", None)
    league = getattr(current, "league", {}) if current is not None else {}
    payload = {
        "scoring_settings": league.get("scoring_settings") or {},
        "roster_positions": league.get("roster_positions") or [],
        "settings": league.get("settings") or {},
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def movement_against_previous(
    *,
    league_key: str,
    season: str | int,
    week: int,
    rankings: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Movement against exactly Week N-1, never a loose latest snapshot."""
    if int(week) <= 1:
        return {
            str(row.get("ownerId") or ""): {
                "previousOfficialRank": None,
                "weekRankDelta": None,
                "previousOfficialPowerScore": None,
                "powerScoreDelta": None,
            }
            for row in rankings
            if row.get("ownerId")
        }
    prior = load_snapshot(league_key, season, int(week) - 1)
    prior_rows = (prior or {}).get("ranking") or []
    by_owner = {str(row.get("ownerId") or ""): row for row in prior_rows if row.get("ownerId")}
    out: dict[str, dict[str, Any]] = {}
    for row in rankings:
        oid = str(row.get("ownerId") or "")
        if not oid:
            continue
        previous = by_owner.get(oid) or {}
        prior_rank = previous.get("rank")
        rank = row.get("rank")
        prior_score = previous.get("powerScore")
        score = row.get("powerScore")
        out[oid] = {
            "previousOfficialRank": prior_rank,
            "weekRankDelta": (
                int(prior_rank) - int(rank)
                if prior_rank is not None and rank is not None
                else None
            ),
            "previousOfficialPowerScore": prior_score,
            "powerScoreDelta": (
                round(float(score) - float(prior_score), 2)
                if prior_score is not None and score is not None
                else None
            ),
        }
    return out


def _public_ranking_row(row: dict[str, Any], movement: dict[str, Any]) -> dict[str, Any]:
    components = row.get("components") or {}
    return {
        "ownerId": row.get("ownerId"),
        "displayName": row.get("displayName"),
        "teamName": row.get("teamName"),
        "rank": row.get("rank"),
        "powerScore": row.get("powerScore"),
        "priorRank": movement.get("previousOfficialRank"),
        "rankDelta": movement.get("weekRankDelta"),
        "priorPowerScore": movement.get("previousOfficialPowerScore"),
        "powerScoreDelta": movement.get("powerScoreDelta"),
        "record": row.get("record"),
        "pointsPerGame": components.get("pointsPerGame"),
        "recentAvg": components.get("recentAvg"),
        "allPlay": components.get("all_play"),
        "rosStrengthPercentile": row.get("rosStrengthPercentile"),
        "teamVorp": components.get("team_vorp"),
        "components": {
            key: components.get(key)
            for key in (
                "team_ros_strength",
                "all_play",
                "recent",
                "team_vorp",
                "wl_record",
            )
        },
    }


def record_snapshot(
    *,
    league_key: str,
    section: dict[str, Any],
    scoring_fingerprint: str,
    finalized_at: str | None = None,
) -> tuple[Path, bool]:
    """Create one immutable snapshot for section asOfSeason/asOfWeek.

    Returns a path plus whether this call created it. Existing snapshots are
    never rewritten.
    """
    season = section.get("asOfSeason")
    week = section.get("asOfWeek")
    if season in (None, "") or not isinstance(week, int) or week < 1:
        raise ValueError("Power section must identify a scored season/week before publication")
    rankings = section.get("currentRanking") or []
    if not rankings or any(row.get("rank") is None for row in rankings):
        raise ValueError("cannot publish an empty or unrankable Power snapshot")

    path = snapshot_path(league_key, season, week)
    if path.exists():
        return path, False

    movement = movement_against_previous(
        league_key=league_key,
        season=season,
        week=week,
        rankings=rankings,
    )
    published_at = finalized_at or datetime.now(timezone.utc).isoformat()
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "leagueKey": str(league_key),
        "season": str(season),
        "week": int(week),
        "finalizedAt": published_at,
        "methodologyVersion": section.get("methodologyVersion"),
        "scoringConfigFingerprint": str(scoring_fingerprint),
        "blend": section.get("blend") or {},
        "weights": section.get("weights") or {},
        "effectiveWeights": section.get("effectiveWeights") or {},
        "ranking": [
            _public_ranking_row(
                row,
                movement.get(str(row.get("ownerId") or "")) or {},
            )
            for row in rankings
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write completely off-path, fsync it, then publish with an atomic
    # hard-link that fails if another publisher already won the week. This
    # preserves both invariants at once: readers never observe partial JSON,
    # and an existing official snapshot is never overwritten.
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp_name, path)
        except FileExistsError:
            return path, False
        return path, True
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
