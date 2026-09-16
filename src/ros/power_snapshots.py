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

# What produced the ranking rows in a snapshot.  A snapshot written before this
# field existed has no ``rankSource`` key at all; absent means ENGINE, because
# that was the only publisher then.
RANK_SOURCE_ENGINE = "canonical_engine"
RANK_SOURCE_ATTESTED = "owner_attested_published_card"


def _safe_part(value: str) -> str:
    safe = "".join(c for c in str(value or "") if c.isalnum() or c in {"_", "-"})
    if not safe:
        raise ValueError("snapshot key may not be empty")
    return safe


def snapshot_path(league_key: str, season: str | int, week: int) -> Path:
    # Week 0 is the PRESEASON publication. It is a real, publishable ranking —
    # the canonical blend answers before any game is scored — and it is the only
    # thing that can give Week 1 a legitimate movement baseline. Without it
    # Week 1 has nothing to move against, and the honest answer there is "no
    # movement", never a number borrowed from a different season.
    if int(week) < 0:
        raise ValueError("Power snapshots require week >= 0 (0 = preseason)")
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


def season_snapshots(league_key: str, season: str | int) -> list[dict[str, Any]]:
    """Every published week of one season, ordered by week ascending.

    Scoped to ``season`` so a history view can never chain last year's ranking
    onto this year's. Unreadable files are skipped rather than failing the whole
    read: one corrupt week must not erase the season's history.
    """
    root = ROS_DATA_DIR / "power_snapshots" / _safe_part(league_key) / _safe_part(str(season))
    if not root.is_dir():
        return []
    out: list[tuple[int, dict[str, Any]]] = []
    for path in root.glob("week_*.json"):
        try:
            week_num = int(path.stem.split("_", 1)[1])
        except (ValueError, IndexError):
            continue
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            out.append((week_num, payload))
    return [payload for _, payload in sorted(out, key=lambda item: item[0])]


def rank_source(snapshot: dict[str, Any] | None) -> str:
    """What produced a snapshot's rows.

    A snapshot published before ``rankSource`` existed carries no such key, and
    the only publisher then was the canonical engine — so absent is ENGINE, not
    unknown.
    """
    return str((snapshot or {}).get("rankSource") or RANK_SOURCE_ENGINE)


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
    """Movement against exactly Week N-1, never a loose latest snapshot.

    The lookup is scoped to ``season``, so it can never reach across a season
    boundary into last year's ranking. Week 0 (preseason) is the first
    publishable week and therefore has no predecessor; Week 1 looks up Week 0
    and finds nothing unless a preseason ranking was actually published, which
    yields ``None`` — an honest "no baseline", not a fabricated flat.
    """
    if int(week) <= 0:
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
                int(prior_rank) - int(rank) if prior_rank is not None and rank is not None else None
            ),
            "previousOfficialPowerScore": prior_score,
            "powerScoreDelta": (
                round(float(score) - float(prior_score), 2)
                if prior_score is not None and score is not None
                else None
            ),
        }
    return out


def _write_temp_payload(path: Path, payload: dict[str, Any]) -> str:
    """Serialize ``payload`` completely off-path and fsync it.

    Returns the temp file's name.  Callers decide how it becomes visible; this
    function only guarantees that what lands on disk is whole.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return tmp_name


def _publish_create_once(path: Path, payload: dict[str, Any]) -> bool:
    """Publish ``payload`` at ``path`` only if nothing is published there yet.

    The atomic hard-link is what makes create-once a property of the filesystem
    rather than of caller discipline: it fails if another publisher already won
    the week.  Returns whether this call created the snapshot.
    """
    tmp_name = _write_temp_payload(path, payload)
    try:
        try:
            os.link(tmp_name, path)
        except FileExistsError:
            return False
        return True
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _publish_replace(path: Path, payload: dict[str, Any]) -> None:
    """Replace an existing publication atomically.

    Deliberately narrow: :func:`restate_movement` is the ONLY caller, and it
    proves field-by-field that nothing but movement changed before calling here.
    Everything else publishes through :func:`_publish_create_once`.
    """
    tmp_name = _write_temp_payload(path, payload)
    try:
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


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
        # Frozen with the week, like every other number here. A sub-rank is an
        # ordinal over the league AS IT WAS that week, so recomputing it later
        # against a changed roster would silently restate a published week.
        "componentRanks": dict(row.get("componentRanks") or {}),
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
    if season in (None, "") or not isinstance(week, int) or week < 0:
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
        # Week 0 is a preseason publication: a canonical ranking with no games
        # behind it. Stamped so a consumer never has to infer it from the week
        # number, and so a share card can say which kind of week it is.
        "preseason": int(week) == 0,
        "finalizedAt": published_at,
        "rankSource": RANK_SOURCE_ENGINE,
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
    return path, _publish_create_once(path, payload)


_MOVEMENT_FIELDS: tuple[str, ...] = (
    "priorRank",
    "rankDelta",
    "priorPowerScore",
    "powerScoreDelta",
)

_COMPONENT_KEYS: tuple[str, ...] = (
    "team_ros_strength",
    "all_play",
    "recent",
    "team_vorp",
    "wl_record",
)


def _attested_ranking_row(row: dict[str, Any], movement: dict[str, Any]) -> dict[str, Any]:
    """An attested row carries an ORDER and nothing else.

    Every quantity the engine would have computed is ``None``, not 0 and not a
    value recovered from a later week. A reader that asks this row for a Power
    score gets "unavailable", which is the truth: the attestation records where
    the teams stood, not what the engine scored them.
    """
    return {
        "ownerId": str(row.get("ownerId")),
        "displayName": row.get("displayName"),
        "teamName": row.get("teamName"),
        "rank": int(row["rank"]),
        "powerScore": None,
        "priorRank": movement.get("previousOfficialRank"),
        "rankDelta": movement.get("weekRankDelta"),
        "priorPowerScore": movement.get("previousOfficialPowerScore"),
        "powerScoreDelta": movement.get("powerScoreDelta"),
        "record": None,
        "pointsPerGame": None,
        "recentAvg": None,
        "allPlay": None,
        "rosStrengthPercentile": None,
        "teamVorp": None,
        "components": dict.fromkeys(_COMPONENT_KEYS),
        "componentRanks": {},
    }


def record_attested_snapshot(
    *,
    league_key: str,
    season: str | int,
    week: int,
    rows: list[dict[str, Any]],
    attestation: dict[str, Any],
    methodology_version: str | None = None,
    finalized_at: str | None = None,
) -> tuple[Path, bool]:
    """Publish a ranking the OWNER attests the site displayed, not one we scored.

    This exists for exactly one situation: a week whose publication was missed,
    where the ranking itself is not recoverable because the inputs that produced
    it have since moved on. The spec forbids back-dating today's ROS strength
    into an older week, and this does not do that — it records the order that
    was actually published, stamped ``rankSource: owner_attested_published_card``
    and carrying no Power score at all, so nothing downstream can mistake it for
    an engine output or reconstruct a score from it.

    Create-once applies exactly as it does to an engine publication.
    """
    if not rows:
        raise ValueError("cannot publish an empty attested Power snapshot")

    ranks: list[int] = []
    owner_ids: set[str] = set()
    for row in rows:
        owner_id = str(row.get("ownerId") or "")
        rank = row.get("rank")
        if not owner_id:
            raise ValueError("every attested row must name an ownerId")
        if owner_id in owner_ids:
            raise ValueError(f"attested rows repeat ownerId {owner_id}")
        owner_ids.add(owner_id)
        if not isinstance(rank, int) or isinstance(rank, bool):
            raise ValueError(f"attested row for {owner_id} has a non-integer rank")
        ranks.append(rank)

    # A screenshot is transcribed by hand, so the ranks are checked for exactly
    # the errors a hand transcription makes: a skipped position or a duplicated
    # one. A published card is 1..N with no gaps and no ties.
    if sorted(ranks) != list(range(1, len(ranks) + 1)):
        raise ValueError(
            f"attested ranks must be a complete 1..{len(ranks)} sequence, got {sorted(ranks)}"
        )
    if not attestation:
        raise ValueError("an attested snapshot must say where its ranking came from")

    path = snapshot_path(league_key, season, week)
    if path.exists():
        return path, False

    ordered = sorted(rows, key=lambda row: int(row["rank"]))
    movement = movement_against_previous(
        league_key=league_key,
        season=season,
        week=int(week),
        rankings=[{"ownerId": row["ownerId"], "rank": row["rank"]} for row in ordered],
    )
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "leagueKey": str(league_key),
        "season": str(season),
        "week": int(week),
        "preseason": int(week) == 0,
        "finalizedAt": finalized_at or datetime.now(timezone.utc).isoformat(),
        "rankSource": RANK_SOURCE_ATTESTED,
        "attestation": dict(attestation),
        "methodologyVersion": methodology_version,
        # We did not recompute this ranking, so we cannot claim to know the
        # scoring configuration that produced it. Unknown, never a fingerprint
        # copied from a different week.
        "scoringConfigFingerprint": None,
        "blend": {},
        "weights": {},
        "effectiveWeights": {},
        "ranking": [
            _attested_ranking_row(row, movement.get(str(row["ownerId"])) or {}) for row in ordered
        ],
    }
    return path, _publish_create_once(path, payload)


def restate_movement(
    *,
    league_key: str,
    season: str | int,
    week: int,
    reason: str,
) -> tuple[Path, bool]:
    """Fill in movement a published week could not know at publication time.

    Create-once protects a published RANKING. It cannot protect a comparison
    with a week that did not exist yet: a snapshot published while its
    predecessor was missing froze ``priorRank``/``rankDelta`` as ``None``, and
    that ``None`` stops being true the moment the predecessor is published.

    So this is deliberately not a general edit path:

    * movement is recomputed from the two FROZEN snapshots only — never from
      today's engine, today's roster or today's ROS data;
    * a ``None`` may become a number, and a number may stay itself. A number may
      never become a DIFFERENT number, so a published arrow cannot be rewritten;
    * every other field is compared key by key and the write is refused if any
      of them would move;
    * the change is recorded in ``restatements`` rather than applied silently.

    Returns whether anything was written. Re-running is a no-op.
    """
    path = snapshot_path(league_key, season, week)
    snapshot = load_snapshot(league_key, season, week)
    if snapshot is None:
        raise ValueError(f"no published snapshot at {path}")
    rows = snapshot.get("ranking") or []
    if not rows:
        raise ValueError(f"published snapshot at {path} has no ranking rows")

    movement = movement_against_previous(
        league_key=league_key,
        season=season,
        week=int(week),
        rankings=rows,
    )

    changed: list[dict[str, Any]] = []
    new_rows: list[dict[str, Any]] = []
    for row in rows:
        owner_id = str(row.get("ownerId") or "")
        computed = movement.get(owner_id) or {}
        updated = dict(row)
        updated["priorRank"] = computed.get("previousOfficialRank")
        updated["rankDelta"] = computed.get("weekRankDelta")
        updated["priorPowerScore"] = computed.get("previousOfficialPowerScore")
        updated["powerScoreDelta"] = computed.get("powerScoreDelta")

        if set(updated) != set(row):
            raise ValueError(f"restatement would change the row shape for owner {owner_id}")
        for key in row:
            if key in _MOVEMENT_FIELDS:
                before, after = row.get(key), updated.get(key)
                if before is not None and before != after:
                    raise ValueError(
                        f"refusing to rewrite published movement for owner {owner_id}: "
                        f"{key} {before!r} -> {after!r}"
                    )
                continue
            if row.get(key) != updated.get(key):
                raise ValueError(
                    f"restatement may only touch movement, but {key} would change "
                    f"for owner {owner_id}"
                )

        row_delta = {
            key: {"from": row.get(key), "to": updated.get(key)}
            for key in _MOVEMENT_FIELDS
            if row.get(key) != updated.get(key)
        }
        if row_delta:
            changed.append({"ownerId": owner_id, "fields": row_delta})
        new_rows.append(updated)

    if not changed:
        return path, False

    payload = dict(snapshot)
    payload["ranking"] = new_rows
    payload["restatements"] = [
        *(snapshot.get("restatements") or []),
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "reason": str(reason),
            "fields": list(_MOVEMENT_FIELDS),
            "changed": changed,
        },
    ]
    _publish_replace(path, payload)
    return path, True
