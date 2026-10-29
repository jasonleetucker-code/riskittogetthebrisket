"""Point-in-time archive of FULL weekly projection pools (RET evidence).

A weekly projection is perishable: once a week is played, what a provider
projected BEFORE kickoff is gone unless it was captured then (same reason as
:mod:`src.ros.game_day_archive`, which archives only rostered players' point
estimates).  Backtesting a streaming rule needs the whole pool — free agents
included — and needs the raw stat lines, so the league card used later can
re-score them.  This module is that store, and only that store: it records
what a fetch returned; it resolves, scores and decides nothing.

One capture = one gzip JSON file::

    data/projections/weekly_archive/<season>/w<week>/<source>_<fetchedAt>.json.gz

holding the source's raw rows exactly as served (every position, free agents
and placeholders included), the provider ``updated_at`` stamps they carried,
our fetch time, a content hash, and — optionally — league-scored points per
player for each league card the collector scored them under (keyed by
``scoring_fingerprint``, never by a scoring-profile LABEL).

Why NOT under ``data/ros/``: ``scheduled-refresh.yml`` force-adds
``data/ros/`` to a PUBLIC repository every two hours (see
:mod:`src.ros.game_day_live` and :func:`src.ros.pick_forecast_snapshot.check_store_path`);
third-party projection pools must not ship that way.  ``data/`` is gitignored
as a whole and ``data/projections/`` is in no force-add list.
:func:`check_store_path` refuses a ``data/ros/`` root.

Append-only, and idempotent on content
--------------------------------------
* a file is never overwritten (exclusive create);
* a capture whose raw content hash equals the LATEST capture's for the same
  ``(season, week, source)`` is a no-op (``unchanged``) — an unchanged
  re-download is not a new observation, so it adds no file (the latest file's
  ``fetchedAt`` stays the time the content was FIRST seen, which is the
  conservative point-in-time claim);
* ``fetchedAt`` is the caller's real fetch instant and must be timezone-aware.

Seasonal intelligence lane only.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.config_loader import repo_root

__all__ = [
    "ARCHIVE_ROOT",
    "SCHEMA_VERSION",
    "ArchiveWriteResult",
    "CaptureRecord",
    "WeeklyArchiveError",
    "check_store_path",
    "content_hash",
    "list_captures",
    "load_capture",
    "record_capture",
]

ARCHIVE_ROOT = repo_root() / "data" / "projections" / "weekly_archive"
SCHEMA_VERSION = 1
_FORCE_ADDED_ROOT = repo_root() / "data" / "ros"
_SOURCE_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")


class WeeklyArchiveError(ValueError):
    """A malformed capture or a refused store path."""


def check_store_path(base: Path) -> Path:
    """Refuse a store under the force-added (public) ``data/ros/`` tree."""
    resolved = Path(base).resolve()
    ros = _FORCE_ADDED_ROOT.resolve()
    if resolved == ros or ros in resolved.parents:
        raise WeeklyArchiveError(
            f"{resolved} is under data/ros/, which scheduled-refresh.yml force-adds to a "
            "public repository; the weekly projection archive must live elsewhere"
        )
    return resolved


def content_hash(rows: Any) -> str:
    """sha256 over the canonical JSON of the raw rows (key order normalized)."""
    blob = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _utc(value: datetime | str, *, what: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise WeeklyArchiveError(f"{what} {value!r} is not ISO-8601") from exc
    if dt.tzinfo is None:
        raise WeeklyArchiveError(f"{what} {value!r} is naive; timezone-aware required")
    return dt.astimezone(timezone.utc)


def _week_dir(base: Path, season: int, week: int) -> Path:
    return base / str(int(season)) / f"w{int(week)}"


def _stamp(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S") + f"{dt.microsecond // 1000:03d}Z"


@dataclass(frozen=True)
class CaptureRecord:
    path: Path
    source_key: str
    season: int
    week: int
    fetched_at: str
    content_sha256: str


@dataclass(frozen=True)
class ArchiveWriteResult:
    #: ``written`` | ``unchanged`` (content identical to the latest capture).
    status: str
    path: Path | None
    content_sha256: str
    row_count: int


def list_captures(
    season: int, week: int, *, source_key: str | None = None, base_dir: Path | None = None
) -> list[CaptureRecord]:
    """Captures for one week, oldest first (filename order = fetch order)."""
    root = _week_dir(check_store_path(base_dir or ARCHIVE_ROOT), season, week)
    if not root.is_dir():
        return []
    out = []
    for path in sorted(root.glob("*.json.gz")):
        src, _, rest = path.name.partition("_")
        if source_key is not None and src != source_key:
            continue
        head = _read_header(path)
        out.append(
            CaptureRecord(
                path=path,
                source_key=src,
                season=int(head.get("season", season)),
                week=int(head.get("week", week)),
                fetched_at=str(head.get("fetchedAt") or ""),
                content_sha256=str(head.get("contentSha256") or ""),
            )
        )
    return out


def _read_header(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    return {k: v for k, v in data.items() if k != "rows"}


def load_capture(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def record_capture(
    *,
    source_key: str,
    season: int,
    week: int,
    fetched_at: datetime | str,
    rows: Sequence[Any] | Mapping[str, Any],
    provider_updated_at: Iterable[str | None] = (),
    source_url: str | None = None,
    model_company: str | None = None,
    league_scored: Mapping[str, Mapping[str, Any]] | None = None,
    extra: Mapping[str, Any] | None = None,
    hash_content: Any = None,
    base_dir: Path | None = None,
) -> ArchiveWriteResult:
    """Append one capture of ``source_key``'s raw pool for one week.

    ``rows`` is the provider payload exactly as served (a list of rows, or
    an envelope object).  ``league_scored`` is ``{scoring_fingerprint:
    {"leagueKeys": [...], "points": {playerId: float}}}`` — optional, and
    never a substitute for the raw rows.

    ``hash_content`` (default: ``rows``) is what the unchanged-check hashes:
    the caller passes the rows minus fields that churn without new content
    (a render timestamp, a re-stamped ``updated_at``), so a re-download whose
    projections did not change is not recorded as a new observation."""
    if not _SOURCE_KEY_RE.match(str(source_key or "")):
        raise WeeklyArchiveError(f"source_key {source_key!r} must be a census-style camelCase key")
    if int(week) < 1 or int(season) < 2000:
        raise WeeklyArchiveError(f"implausible season/week {season!r}/{week!r}")
    fetched = _utc(fetched_at, what="fetched_at")
    root = check_store_path(base_dir or ARCHIVE_ROOT)
    digest = content_hash(rows if hash_content is None else hash_content)
    row_count = len(rows) if isinstance(rows, Sequence) else len(rows.get("players") or [])

    week_dir = _week_dir(root, season, week)
    prior = sorted(week_dir.glob(f"{source_key}_*.json.gz")) if week_dir.is_dir() else []
    if prior and str(_read_header(prior[-1]).get("contentSha256") or "") == digest:
        return ArchiveWriteResult("unchanged", prior[-1], digest, row_count)

    stamps = sorted({s for s in provider_updated_at if s})
    record = {
        "schemaVersion": SCHEMA_VERSION,
        "sourceKey": source_key,
        "season": int(season),
        "week": int(week),
        "fetchedAt": fetched.isoformat(),
        "sourceUrl": source_url,
        "modelCompany": model_company,
        "contentSha256": digest,
        "rowCount": row_count,
        "providerUpdatedAtMin": stamps[0] if stamps else None,
        "providerUpdatedAtMax": stamps[-1] if stamps else None,
        "leagueScored": {k: dict(v) for k, v in sorted((league_scored or {}).items())},
        "extra": dict(extra or {}),
        "rows": rows,
    }
    week_dir.mkdir(parents=True, exist_ok=True)
    path = week_dir / f"{source_key}_{_stamp(fetched)}.json.gz"
    payload = json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")
    # Exclusive create: an existing file is never overwritten.
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise WeeklyArchiveError(
            f"{path} already exists; captures are append-only and never overwritten"
        ) from exc
    with os.fdopen(fd, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
        gz.write(payload)
    return ArchiveWriteResult("written", path, digest, row_count)
