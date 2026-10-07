"""As-known injury history: an append-only log of every fetched ESPN injury snapshot.

``scripts/refresh_injury_feed.py`` overwrites ``data/nfl_data/injuries_prior.json``
on every run and keeps only status TRANSITIONS as BDVM events.  What the injury
report actually said at a given moment -- the status a player carried at
kickoff, at a waiver deadline, when an alert fired -- was therefore never kept.
It cannot be re-fetched later: ESPN serves the CURRENT report only.  This module
keeps it (Adaptive Learning G4 / IC-1 evidence closure).  It changes no event,
no value and no served field, and nothing serves from it.

**Store.**  Gitignored ``data/nfl_data/injury_history/`` (override:
``RISKIT_INJURY_HISTORY_DIR``), monthly ``ledger-YYYY-MM.jsonl`` + a
``ledger.keys`` index through the neutral append-only owner
``src/utils/append_ledger``.  Never rewritten.  Box-local and backed up by
``deploy/backup/riskit-state-backup.sh``; ``data/nfl_data/`` is outside every
path the scheduled refresh force-adds, so it stays private.

**Records.**  Two kinds, one key rule ``(provider, contentSha256, fetchedAt)``:

* ``snapshot`` -- the whole report as fetched, written when its content differs
  from the most recent recorded state;
* ``reobserved`` -- a small "still this content at fetchedAt" row, written when
  a later fetch returns IDENTICAL content.  The content is deduplicated (never
  stored twice in a row), but the observation is kept, so a reader can tell
  "the report still said this at T" from "collection stopped before T".

The same fetch (one cache entry, one ``fetchedAt``) can never be recorded twice
whatever its kind -- a re-run inside the feed's 30-minute cache TTL is a no-op.
A report that goes A -> B -> A records A again as a snapshot: as-of reads need
the third state.

**Fetch proof.**  ``fetch_injuries`` returns ``[]`` both for "no injuries" and
for "the fetch failed".  A snapshot is recorded only when the response cache
proves a fetch: an entry whose content equals what was returned and whose
``fetched_at`` is inside the TTL measured from BEFORE the call.  What that
establishes is narrow and stated exactly: ESPN answered, with a body of the
injuries SHAPE (``injury_feed.payload_shape_error`` refuses to cache anything
else), and this is what it said.  It cannot detect a well-shaped report whose
CONTENT is wrong.  A network error, an open breaker, shape drift, or a failed
cache write (``cache.put`` raises, so the refresh exits non-zero) records
nothing.

**Identity.**  ESPN athlete id -> Sleeper id by EXACT external id only, through
the canonical owner ``src.identity.resolution.resolve_canonical_v2`` called with
the ESPN id alone (no name, so no name rung can fire).  An id the directory does
not carry, an id two Sleeper players share, or no directory at all stays
``unresolved`` with its reason.  Never a fuzzy guess.

**Missing is null.**  ESPN fields the feed left empty are ``None``, never ``""``
or ``0``.  ``providerAsOf`` is ``None`` with a reason: the endpoint publishes no
snapshot timestamp, and the fetch time is not the provider's as-of.

**As-of reads** (:func:`as_known_at`) select only records fetched at or before
the requested instant.  A future record is never selectable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils import append_ledger as _al

LOG = logging.getLogger("nfl_data.injury_history")

SCHEMA = "injury-history/v1"
PROVIDER = "espn"
KIND_SNAPSHOT = "snapshot"
KIND_REOBSERVED = "reobserved"

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = REPO_ROOT / "data" / "nfl_data" / "injury_history"
ENV_DIR = "RISKIT_INJURY_HISTORY_DIR"

#: Sleeper player directories already kept on the box, in preference order.
#: Read-only; this module never fetches one.
DIRECTORY_CANDIDATES = (
    REPO_ROOT / "data" / "playerctx" / "sleeper_players.json",
    REPO_ROOT / "data" / "public_league" / "nfl_players.json",
)

#: The ESPN fields kept per entry: ``InjuryEntry.to_dict`` key -> record key.
_ENTRY_FIELDS = (
    "espnAthleteId",
    "fullName",
    "position",
    "teamAbbrev",
    "status",
    "bodyPart",
    "description",
    "dateReported",
    "returning",
)

PROVIDER_AS_OF_NULL_REASON = "espn_injuries_endpoint_publishes_no_snapshot_timestamp"


def store_dir() -> Path:
    override = os.environ.get(ENV_DIR, "").strip()
    return Path(override) if override else DEFAULT_DIR


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _parse_iso(stamp: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _null_if_blank(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return value


# ── content ─────────────────────────────────────────────────────────


def provider_entries(entries: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The provider's own fields, blanks as None, in a stable order (by ESPN id)."""
    out = [{k: _null_if_blank(e.get(k)) for k in _ENTRY_FIELDS} for e in entries]
    return sorted(out, key=lambda e: (str(e.get("espnAthleteId") or ""), str(e.get("fullName"))))


def content_sha256(entries: Sequence[Mapping[str, Any]]) -> str:
    """Hash of WHAT the provider said -- identity resolution is not part of it,
    so a refreshed Sleeper directory can never make an unchanged report look new."""
    text = json.dumps(list(entries), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record_key(content_sha: str, fetched_at: str) -> str:
    return hashlib.sha256(
        json.dumps([SCHEMA, PROVIDER, content_sha, fetched_at]).encode("utf-8")
    ).hexdigest()[:32]


# ── fetch proof ─────────────────────────────────────────────────────


def proven_fetch_time(
    returned: Sequence[Mapping[str, Any]],
    *,
    started_at: float,
    ttl_seconds: float,
    cache_dir: Path | None = None,
) -> tuple[float | None, str | None]:
    """``(fetched_at, None)`` when the response cache proves ``returned`` was fetched.

    ``started_at`` is the epoch taken BEFORE ``fetch_injuries`` was called.  The
    proof is: the cache entry exists, holds exactly ``returned``, and its
    ``fetched_at`` was inside the TTL at the start of the call (so
    ``fetch_injuries`` served or wrote it rather than failing past it).
    Otherwise ``(None, reason)``.
    """
    from src.nfl_data import cache as _cache  # noqa: PLC0415
    from src.nfl_data.injury_feed import CACHE_KEY  # noqa: PLC0415

    fetched_at = _cache.entry_fetched_at(CACHE_KEY, cache_dir=cache_dir)
    if fetched_at is None:
        return None, "no_cache_entry"
    if started_at - fetched_at > ttl_seconds:
        return None, "cache_entry_older_than_ttl"
    cached = _cache.get(CACHE_KEY, ttl_seconds=ttl_seconds, cache_dir=cache_dir, allow_stale=True)
    if not isinstance(cached, list) or cached != [dict(e) for e in returned]:
        return None, "returned_entries_differ_from_cache_entry"
    return fetched_at, None


# ── identity (exact external id only) ───────────────────────────────


def load_directory(
    candidates: Sequence[Path] = DIRECTORY_CANDIDATES,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """The first readable Sleeper directory, plus provenance (path, mtime, size)."""
    for path in candidates:
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            stat = Path(path).stat()
        except (OSError, ValueError):
            continue
        if isinstance(raw, dict) and raw:
            rel = str(path)
            try:
                rel = Path(path).resolve().relative_to(REPO_ROOT).as_posix()
            except ValueError:
                pass
            return raw, {
                "path": rel,
                "modifiedAt": _iso(stat.st_mtime),
                "playerCount": len(raw),
            }
    return None, {"path": None, "nullReason": "no_readable_sleeper_directory"}


class EspnIdResolver:
    """ESPN athlete id -> Sleeper id, exact id only, via the canonical owner."""

    def __init__(self, directory: Mapping[str, Any] | None):
        from src.identity.resolution import build_sleeper_index  # noqa: PLC0415

        self._index = build_sleeper_index(directory) if directory else None
        counts: Counter[str] = Counter()
        for pdata in (directory or {}).values():
            if isinstance(pdata, dict):
                espn = str(pdata.get("espn_id") or "").strip()
                if espn:
                    counts[espn] += 1
        # The owner's index keeps the FIRST player for a shared ESPN id; which
        # one is first is directory order, i.e. a guess.  Refuse those instead.
        self._shared = {k for k, n in counts.items() if n > 1}

    def resolve(self, espn_id: Any) -> dict[str, Any]:
        eid = str(espn_id or "").strip()
        if not eid:
            return {"status": "unresolved", "sleeperId": None, "reason": "no_espn_id"}
        if self._index is None:
            return {"status": "unresolved", "sleeperId": None, "reason": "no_sleeper_directory"}
        if eid in self._shared:
            return {
                "status": "unresolved",
                "sleeperId": None,
                "reason": "espn_id_shared_by_multiple_sleeper_players",
            }
        from src.identity.resolution import resolve_canonical_v2  # noqa: PLC0415

        res = resolve_canonical_v2(self._index, espn_id=eid)
        if res.resolved and res.method == "espn_id":
            return {
                "status": "resolved",
                "sleeperId": res.sleeper_id,
                "method": "espn_id",
                "policy": res.policy,
            }
        return {
            "status": "unresolved",
            "sleeperId": None,
            "reason": "espn_id_not_in_sleeper_directory",
        }


# ── capture ─────────────────────────────────────────────────────────


def _latest_state(base: Path) -> tuple[str | None, str | None]:
    """(contentSha256, snapshotKey) of the most recently written record, if any."""
    files = _al.ledger_files(base)
    if not files:
        return None, None
    tail = _al.last_record(files[-1])
    if not tail or tail.get("schema") != SCHEMA:
        return None, None
    snap_key = tail.get("key") if tail.get("kind") == KIND_SNAPSHOT else tail.get("snapshotKey")
    return tail.get("contentSha256"), snap_key


def build_record(
    entries: Iterable[Mapping[str, Any]],
    *,
    fetched_at: float,
    resolver: EspnIdResolver,
    directory_provenance: Mapping[str, Any],
    recorded_at: str | None = None,
    previous: tuple[str | None, str | None] = (None, None),
) -> dict[str, Any]:
    """The record a fetch produces: a full snapshot, or a re-observation of the last one."""
    content = provider_entries(entries)
    content_sha = content_sha256(content)
    fetched_iso = _iso(fetched_at)
    base = {
        "schema": SCHEMA,
        "key": record_key(content_sha, fetched_iso),
        "provider": PROVIDER,
        "fetchedAt": fetched_iso,
        "recordedAt": recorded_at or datetime.now(timezone.utc).isoformat(),
        "providerAsOf": None,
        "contentSha256": content_sha,
        "entryCount": len(content),
    }
    prev_sha, prev_key = previous
    if prev_sha == content_sha and prev_key:
        return {
            **base,
            "kind": KIND_REOBSERVED,
            "snapshotKey": prev_key,
            "nullReasons": {"providerAsOf": PROVIDER_AS_OF_NULL_REASON},
        }
    from src.nfl_data.injury_feed import ENDPOINT_URL  # noqa: PLC0415

    resolved = [{**e, "identity": resolver.resolve(e.get("espnAthleteId"))} for e in content]
    nulls = {"providerAsOf": PROVIDER_AS_OF_NULL_REASON}
    return {
        **base,
        "kind": KIND_SNAPSHOT,
        "endpoint": ENDPOINT_URL,
        "identityDirectory": dict(directory_provenance),
        "unresolvedCount": sum(1 for e in resolved if e["identity"]["status"] != "resolved"),
        "entries": resolved,
        "nullReasons": nulls,
    }


def capture(
    entries: Iterable[Mapping[str, Any]],
    *,
    fetched_at: float,
    base: Path | None = None,
    directory: Mapping[str, Any] | None = None,
    directory_provenance: Mapping[str, Any] | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Append one fetched report.  Returns ``{"written": bool, "kind", "key"}``.

    ``directory`` defaults to the first readable box directory
    (:data:`DIRECTORY_CANDIDATES`); it is loaded only when a full snapshot is
    needed.
    """
    base = Path(base) if base is not None else store_dir()
    entries = [dict(e) for e in entries]
    previous = _latest_state(base)
    is_reobservation = bool(previous[1]) and previous[0] == content_sha256(
        provider_entries(entries)
    )
    if not is_reobservation and directory is None and directory_provenance is None:
        directory, directory_provenance = load_directory()
    record = build_record(
        entries,
        fetched_at=fetched_at,
        resolver=EspnIdResolver(None if is_reobservation else directory),
        directory_provenance=directory_provenance or {},
        recorded_at=recorded_at,
        previous=previous,
    )
    written = _al.append_record(base, record)
    return {"written": written, "kind": record["kind"], "key": record["key"]}


def capture_safely(entries: Iterable[Mapping[str, Any]], **kwargs: Any) -> dict[str, Any] | None:
    """:func:`capture`, but never raises -- the refresh must not fail on its archive."""
    try:
        return capture(entries, **kwargs)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("injury history capture failed (refresh unaffected): %s", exc)
        return None


# ── as-of read ──────────────────────────────────────────────────────


def as_known_at(when: datetime | str, base: Path | None = None) -> dict[str, Any]:
    """The injury report as this system knew it at ``when``.

    Only records with ``fetchedAt <= when`` are eligible -- a later fetch is
    never selectable.  Returns ``{"state": "known", "snapshot", "lastObservedAt",
    "observedAgeSeconds"}`` or ``{"state": "unavailable", "reason"}``.
    """
    base = Path(base) if base is not None else store_dir()
    at = when if isinstance(when, datetime) else _parse_iso(when)
    if at is None:
        return {"state": "unavailable", "reason": "unparseable_as_of"}
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    snapshots: dict[str, dict[str, Any]] = {}
    latest: tuple[datetime, dict[str, Any]] | None = None
    for record in _al.iter_all_records(base):
        if record.get("schema") != SCHEMA:
            continue
        fetched = _parse_iso(record.get("fetchedAt"))
        if fetched is None or fetched > at:
            continue
        if record.get("kind") == KIND_SNAPSHOT:
            snapshots[str(record.get("key"))] = record
        if latest is None or fetched > latest[0]:
            latest = (fetched, record)
    if latest is None:
        return {"state": "unavailable", "reason": "no_capture_at_or_before"}
    fetched, record = latest
    snap_key = (
        record.get("key") if record.get("kind") == KIND_SNAPSHOT else record.get("snapshotKey")
    )
    snapshot = snapshots.get(str(snap_key))
    if snapshot is None:
        return {"state": "unavailable", "reason": "reobservation_without_its_snapshot"}
    return {
        "state": "known",
        "snapshot": snapshot,
        "lastObservedAt": record.get("fetchedAt"),
        "observedAgeSeconds": (at - fetched).total_seconds(),
    }
