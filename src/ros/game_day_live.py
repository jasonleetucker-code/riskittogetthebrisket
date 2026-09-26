"""Game Day U5 — THE shared live collector and its versioned generations.

What this module owns
---------------------
* **Acquisition cadence.** One bounded background tick
  (``scripts/run_game_day_live.py`` under the ``dynasty-game-day-live``
  systemd timer) fetches the ESPN scoreboard, Sleeper live stats, Sleeper
  weekly projections and every active league's Sleeper league / users /
  rosters / matchups.  When ESPN fails (an HTTP 403, a timeout, backoff) and
  the SportsDataIO provider is eligible (flag ``sportsdataio_live_game_state``
  + ``SPORTSDATAIO_API_KEY``), live game state is read from SportsDataIO
  instead — ONE provider per tick, never a merge of two providers' states
  for a game, with the chosen provider and the reason recorded
  (:func:`collect_live_game_state`).  :func:`decide_cadence` reads the
  OBSERVED game windows: ~60 s while any game is in progress, a few minutes near a
  kickoff, hourly otherwise.  A live update never needs a deployment, a
  scrape, or a simulation per viewer.
* **Observations, persisted append-only.**  Every fetch is written to a
  keyed observation log (:class:`KeyedObservationLog`) under
  ``data/game_day/live/`` — NFL-wide sources once under the ``_nfl``
  pseudo-league, league sources under ``<leagueKey>``.  A restart after
  kickoff therefore never loses the pre-kickoff weekly projection a
  baseline is locked to (U4's in-memory memo did).
* **Generations.**  Per league-week, ``generation.json`` is one versioned,
  atomically-written answer for EVERY team: the input as-of stamps, the
  resolved state, the simulation output and the rendered payload parts
  (``src/api/matchup_intel.py::render_league``).  A new generation is
  computed only when the input CONTENT changed (:func:`input_fingerprint`
  hashes normalized content, never fetch timestamps), so an unchanged poll
  costs a few requests and a hash.  An older tick can never replace a newer
  generation.
* **Serving + freshness.**  :func:`serve_league_render` is what the API
  reads: the latest generation (no network, no simulation) with a
  ``freshness`` block — per-source ``observedAt`` / ``fetchedAt``, the
  generation's ``computedAt``, ``payloadAgeSeconds``, ``state``
  (``current`` / ``partial`` / ``degraded`` / ``stale``) and
  ``refreshInProgress``.  The simulation NEVER runs on a request thread:
  with no usable generation the API answers a PENDING payload from cheap
  factual inputs (``state: "pending"``) and starts ONE background compute
  per league-week (:func:`ensure_background_compute`), whose generation the
  next poll serves labelled ``request_generation`` / ``degraded``.  A stale
  generation is served with its true as-of — never blanked — while the
  same background path refreshes it.
* **Corrections.**  Host points are the scoring source of record; a changed
  host value changes the fingerprint and publishes a new generation (the
  superseded one stays in ``generations.jsonl``).  Post-final stat changes
  the host has not absorbed yet are reported, never rescored — see
  :func:`update_stat_corrections`.

What it does NOT own
--------------------
Every number: resolution (``game_day_week``), baselines
(``game_day_estimates``), the simulation (``game_day_sim``) and the payload
assembly (``matchup_intel``) are called unchanged.  This module decides WHEN
they run and WHAT inputs they see, and says how fresh the answer is.

Why not under ``data/ros/``
---------------------------
``scheduled-refresh.yml`` force-adds ``data/ros/`` to the public repo every
2 hours (see ``game_day_sim._SIM_CACHE_ROOT``).  Generations hold private
win probabilities and lineups, so the root is ``data/game_day/live/`` —
gitignored with the rest of ``data/`` and never force-added.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.config_loader import repo_root

# ── Paths ────────────────────────────────────────────────────────────────

#: Root of every persisted Game Day live artefact.  Redirected per test by
#: ``tests/runtime_data_isolation.py``.
LIVE_ROOT: Path = repo_root() / "data" / "game_day" / "live"

#: Pseudo league key for NFL-wide sources (ESPN, live stats, projections):
#: fetched once per tick, stored once, read by every league.
NFL_KEY = "_nfl"
_COLLECTOR_DIR = "_collector"

#: Bumped when the generation layout or render semantics change, so a
#: generation written by an older layout is never served as current.
GENERATION_SCHEMA_VERSION = 1
PRODUCER = "game_day_live_collector"
#: Producer of a generation computed in the BACKGROUND because a request
#: found no usable collector generation (Game Day G).  Same store, same
#: layout; served labelled ``request_generation`` + ``degraded`` and
#: replaced by the collector's own next publication.
PRODUCER_REQUEST = "game_day_request_compute"

# ── Cold-request background compute (Game Day G) ─────────────────────────

#: At most this many background league-week computes run at once in one
#: process (one per league-week by construction; this bounds the SUM, since
#: season/week are request parameters).  Past it a request answers pending
#: with ``background_compute_capacity_exhausted`` and the next poll retries.
MAX_BACKGROUND_COMPUTES = 2
#: A failed background compute is reported (``freshness.state == "failed"``)
#: and not retried until this long after it finished — a broken input must
#: not turn every poll into a new 30-second compute.
BACKGROUND_RETRY_AFTER_SECONDS = 30.0
#: Finished-attempt records kept per process (oldest dropped first).
BACKGROUND_HISTORY_MAX = 64

# ── Cadence (seconds) ────────────────────────────────────────────────────

CADENCE_LIVE_SECONDS = 60.0
CADENCE_NEAR_KICKOFF_SECONDS = 180.0
CADENCE_IDLE_SECONDS = 3600.0
#: How far ahead of a kickoff the near-kickoff cadence starts.
NEAR_KICKOFF_WINDOW_SECONDS = 90 * 60.0
#: A passed kickoff with no observed final is treated as live this long.
LIVE_WINDOW_AFTER_KICKOFF_SECONDS = 6 * 3600.0
#: Repo convention (``SCRAPE_INTERVAL_HOURS * 3``): an answer is stale after
#: three missed cadence intervals.  Live: 180 s — the same number as
#: ``game_day_week.LIVE_STATE_MAX_AGE_SECONDS``.
STALE_AFTER_INTERVALS = 3.0
#: The collector is "absent" for a league-week when it has not ticked it
#: for this long (two idle intervals plus slack).
COLLECTOR_ABSENT_AFTER_SECONDS = 2 * CADENCE_IDLE_SECONDS + 600.0

#: Weekly projections: re-fetched this often while a kickoff is near …
WEEKLY_NEAR_KICKOFF_INTERVAL_SECONDS = 600.0
#: … and this often while every remaining kickoff is further away.
WEEKLY_IDLE_INTERVAL_SECONDS = 3 * 3600.0
#: At least one fetch is forced inside this window before each kickoff, so
#: the kickoff lock has a recent real observation.
PRE_KICKOFF_FINAL_WINDOW_SECONDS = 600.0
#: Live stats after games end (stat-correction evidence).
LIVE_STATS_POSTGAME_INTERVAL_SECONDS = 3600.0

#: Hard cap on network requests in one tick (bounded by construction:
#: 1 NFL state + 1 ESPN + at most 1 SportsDataIO fallback + 1 live stats +
#: 1 projections + 1 players DB + 4 per league — 14 for today's two active
#: leagues; the cap leaves room for five more).  A fetch past it is skipped
#: and recorded, never silent.
MAX_REQUESTS_PER_TICK = 30
#: Persisted per-source backoff (the in-process circuit breaker does not
#: survive a oneshot run): after this many consecutive failures a source is
#: skipped for ``min(60 * 2**(n - threshold), 600)`` seconds.
BACKOFF_FAILURE_THRESHOLD = 3
BACKOFF_MAX_SECONDS = 600.0
#: Sleeper asks for the players DB at most daily.
PLAYERS_DB_MAX_AGE_SECONDS = 24 * 3600.0
PLAYERS_DB_MISSING_RETRY_SECONDS = 3600.0
#: A tick lock older than this is abandoned (matches TimeoutStartSec).
LOCK_STALE_SECONDS = 900.0

#: Raw observation logs are kept this many weeks back (generations, their
#: index and the league-week state are kept for the whole season).
RAW_RETENTION_WEEKS = 4
#: Keyframe every N content-bearing records so a damaged line only breaks
#: its own segment of a delta chain.
KEYFRAME_EVERY = 100
#: Operational tick log is trimmed to this many lines.
TICK_LOG_MAX_LINES = 5000

# ── Time helpers ─────────────────────────────────────────────────────────


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def _epoch(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, datetime):
        return value.timestamp()
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _dt(value: Any) -> datetime | None:
    ts = _epoch(value)
    return datetime.fromtimestamp(ts, tz=timezone.utc) if ts is not None else None


def _counter(value: Any) -> int:
    """A stored COUNT (keyframe distance, failure streak, event tally).

    Nothing recorded yet is a count of zero — a count, not a measurement,
    so this is the one place a ``None`` legitimately becomes ``0``.
    """
    return 0 if value is None else int(value)


def _content_hash(content: Any) -> str:
    blob = json.dumps(content, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ── Atomic file writes ───────────────────────────────────────────────────


def _atomic_write_json(path: Path, payload: Any) -> None:
    """Per-writer tempfile + replace; never exposes a partial file.

    The same pattern as ``game_day_sim._write_sim_cache`` (carried from
    #1346): Windows can briefly deny the replace while another process
    finishes its own rename, so retry and never unlink the live file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp = Path(handle.name)
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"), default=str)
        for attempt in range(3):
            try:
                tmp.replace(path)
                break
            except PermissionError as exc:
                if os.name != "nt" or getattr(exc, "winerror", None) not in (5, 32) or attempt == 2:
                    raise
                time.sleep(0.01)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _append_line(path: Path, record: Mapping[str, Any]) -> None:
    """Append one JSON line.  A torn trailing write (a crash mid-line) is
    cut back to the last complete line first — otherwise the next record
    would be glued onto garbage and lost too."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str) + "\n"
    if path.exists():
        with path.open("rb+") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            if size:
                fh.seek(size - 1)
                if fh.read(1) != b"\n":
                    fh.seek(0)
                    data = fh.read()
                    cut = data.rfind(b"\n") + 1
                    fh.seek(cut)
                    fh.truncate()
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(line)
        fh.flush()


# ── Keyed observation log ────────────────────────────────────────────────


@dataclass(frozen=True)
class Observation:
    """One reconstructed observation: its record metadata and full content."""

    seq: int
    fetched_at: str | None
    status: str
    meta: Mapping[str, Any]
    content: Mapping[str, Any] | None
    kind: str


def _lines_reversed(path: Path, chunk: int = 1 << 16) -> Iterator[bytes]:
    """Complete lines of ``path``, last first, reading backwards in chunks."""
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        pos = fh.tell()
        rem = b""
        while pos > 0:
            step = min(chunk, pos)
            pos -= step
            fh.seek(pos)
            parts = (fh.read(step) + rem).split(b"\n")
            rem = parts[0]
            for line in reversed(parts[1:]):
                if line:
                    yield line
        if rem:
            yield rem


class KeyedObservationLog:
    """Append-only JSONL of one source's observations, keyed-delta encoded.

    Content is a ``{key: value}`` map (games by ESPN id, projection rows and
    stat lines by player id, league objects by kind:id).  Each record is one
    of: ``keyframe`` (full content), ``delta`` (``set`` / ``drop`` against
    the previous content), ``unchanged`` (same content hash; only its own
    ``fetchedAt`` / ``meta``) or ``failure`` (no content; ``meta`` names the
    error).  Nothing is ever rewritten.  ``<source>.head.json`` caches the
    latest content so a writer never replays the log; it is a cache — when
    it disagrees with the log's last record it is rebuilt from the log.
    """

    def __init__(self, directory: Path, source: str):
        self.source = source
        self.log_path = directory / f"{source}.jsonl"
        self.head_path = directory / f"{source}.head.json"

    # -- reading --

    def head(self) -> dict[str, Any] | None:
        head = _read_json(self.head_path)
        if not isinstance(head, dict):
            head = None
        last = self._last_seq()
        if last is None:
            return None
        if head is None or head.get("seq") != last:
            head = self._rebuild_head()
        return head

    def _last_seq(self) -> int | None:
        """``seq`` of the last COMPLETE record (a torn trailing write is
        skipped).  Reads backwards, so a multi-megabyte keyframe line is
        found whole rather than cut at an arbitrary block boundary."""
        if not self.log_path.exists():
            return None
        for raw in _lines_reversed(self.log_path):
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            if isinstance(rec, dict) and isinstance(rec.get("seq"), int):
                return rec["seq"]
        return None

    def _rebuild_head(self) -> dict[str, Any] | None:
        head: dict[str, Any] | None = None
        for obs, since_keyframe in self._replay():
            prev_content = head.get("content") if head else None
            head = {
                "seq": obs.seq,
                "fetchedAt": (
                    obs.fetched_at if obs.content is not None else (head or {}).get("fetchedAt")
                ),
                "status": obs.status,
                "meta": dict(obs.meta),
                "content": dict(obs.content) if obs.content is not None else prev_content,
                "contentHash": (
                    _content_hash(obs.content)
                    if obs.content is not None
                    else (head or {}).get("contentHash")
                ),
                "sinceKeyframe": since_keyframe,
                "lastOkFetchedAt": (
                    obs.fetched_at if obs.status == "ok" else (head or {}).get("lastOkFetchedAt")
                ),
                "lastOkMeta": (
                    dict(obs.meta) if obs.status == "ok" else (head or {}).get("lastOkMeta")
                ),
            }
        if head is not None:
            _atomic_write_json(self.head_path, head)
        return head

    def _replay(self) -> Iterator[tuple[Observation, int]]:
        if not self.log_path.exists():
            return
        state: dict[str, Any] | None = None
        broken = False
        since_keyframe = 0
        with self.log_path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                try:
                    rec = json.loads(raw)
                except ValueError:
                    broken = True
                    continue
                if not isinstance(rec, dict):
                    broken = True
                    continue
                if not isinstance(rec.get("seq"), int):
                    broken = True
                    continue
                kind = rec.get("kind")
                if kind == "keyframe":
                    state = dict(rec.get("set") or {})
                    broken = False
                    since_keyframe = 0
                elif kind == "delta":
                    if state is None or broken:
                        broken = True
                        continue
                    state = dict(state)
                    state.update(rec.get("set") or {})
                    for k in rec.get("drop") or ():
                        state.pop(k, None)
                    since_keyframe += 1
                elif kind == "unchanged":
                    if state is None or broken:
                        continue
                elif kind == "failure":
                    yield (
                        Observation(
                            seq=rec["seq"],
                            fetched_at=rec.get("fetchedAt"),
                            status=str(rec.get("status") or "error"),
                            meta=rec.get("meta") or {},
                            content=None,
                            kind="failure",
                        ),
                        since_keyframe,
                    )
                    continue
                else:
                    broken = True
                    continue
                yield (
                    Observation(
                        seq=rec["seq"],
                        fetched_at=rec.get("fetchedAt"),
                        status=str(rec.get("status") or "ok"),
                        meta=rec.get("meta") or {},
                        content=state,
                        kind=str(kind),
                    ),
                    since_keyframe,
                )

    def observations(self, *, ok_only: bool = True) -> list[Observation]:
        """Every reconstructable observation in log order."""
        return [
            obs
            for obs, _ in self._replay()
            if not ok_only or (obs.status == "ok" and obs.content is not None)
        ]

    # -- writing --

    def append(
        self,
        *,
        fetched_at: str,
        status: str,
        meta: Mapping[str, Any],
        content: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Append one observation; returns ``{"kind", "changedKeys", "droppedKeys"}``."""
        head = self.head()
        seq = (head["seq"] + 1) if head else 1
        record: dict[str, Any] = {
            "v": 1,
            "seq": seq,
            "fetchedAt": fetched_at,
            "status": status,
            "meta": dict(meta),
        }
        info = {"kind": "failure", "changedKeys": 0, "droppedKeys": 0}
        prev = (head or {}).get("content")
        if status != "ok" or content is None:
            record["kind"] = "failure"
            new_head = dict(head or {})
            new_head.update(seq=seq, status=status, meta=dict(meta))
            new_head.setdefault("content", None)
        else:
            content = dict(content)
            digest = _content_hash(content)
            since = _counter((head or {}).get("sinceKeyframe"))
            if prev is not None and (head or {}).get("contentHash") == digest:
                record["kind"] = "unchanged"
                info["kind"] = "unchanged"
            elif prev is None or since + 1 >= KEYFRAME_EVERY:
                record["kind"] = "keyframe"
                record["set"] = content
                since = 0
                info.update(kind="keyframe", changedKeys=len(content))
            else:
                changed = {k: v for k, v in content.items() if prev.get(k, _MISSING) != v}
                dropped = sorted(k for k in prev if k not in content)
                record["kind"] = "delta"
                record["set"] = changed
                record["drop"] = dropped
                since += 1
                info.update(kind="delta", changedKeys=len(changed), droppedKeys=len(dropped))
            new_head = {
                "seq": seq,
                "fetchedAt": fetched_at,
                "status": status,
                "meta": dict(meta),
                "content": content,
                "contentHash": digest,
                "sinceKeyframe": since,
                "lastOkFetchedAt": fetched_at,
                "lastOkMeta": dict(meta),
            }
        record["contentHash"] = new_head.get("contentHash")
        _append_line(self.log_path, record)
        _atomic_write_json(self.head_path, new_head)
        return info


class _Missing:
    pass


_MISSING = _Missing()


# ── Store layout ─────────────────────────────────────────────────────────


def league_week_dir(league_key: str, season: int, week: int) -> Path:
    return LIVE_ROOT / str(league_key) / str(int(season)) / f"week_{int(week)}"


def _observations_dir(league_key: str, season: int, week: int) -> Path:
    return league_week_dir(league_key, season, week) / "observations"


def observation_log(league_key: str, season: int, week: int, source: str) -> KeyedObservationLog:
    return KeyedObservationLog(_observations_dir(league_key, season, week), source)


def generation_path(league_key: str, season: int, week: int) -> Path:
    return league_week_dir(league_key, season, week) / "generation.json"


def _generation_index_path(league_key: str, season: int, week: int) -> Path:
    return league_week_dir(league_key, season, week) / "generations.jsonl"


def league_state_path(league_key: str, season: int, week: int) -> Path:
    return league_week_dir(league_key, season, week) / "state.json"


def _collector_dir() -> Path:
    return LIVE_ROOT / _COLLECTOR_DIR


def collector_state_path() -> Path:
    return _collector_dir() / "state.json"


def _lock_path() -> Path:
    return _collector_dir() / "tick.lock"


def _players_db_path() -> Path:
    return LIVE_ROOT / NFL_KEY / "nfl_players.json"


# ── Source serialization ─────────────────────────────────────────────────

SOURCE_ESPN = "espn_scoreboard"
SOURCE_SDIO = "sportsdataio_scores"
#: TickReport key naming which provider supplied this tick's live state.
SOURCE_LIVE_SELECTION = "live_game_state"
SOURCE_LIVE_STATS = "sleeper_live_stats"
SOURCE_WEEKLY = "sleeper_weekly_projections"
SOURCE_LEAGUE = "sleeper_league_week"

_GAME_DT_FIELDS = ("kickoff",)
#: Per-game fields that are the SNAPSHOT's clock, not the game's content —
#: kept out of the content hash so an unchanged game is "unchanged".
_GAME_SNAPSHOT_FIELDS = ("observed_at", "provider_timestamp", "provider_timestamp_source")


def scoreboard_to_observation(snapshot: Any) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    """``(status, meta, content)`` for one live-game-state snapshot (any provider).

    Content is keyed by :attr:`ObservedGameState.game_key` — ESPN's bare
    event id (unchanged from the ESPN-only layout), ``sportsdataio:<id>``
    for SportsDataIO.  Each provider has its OWN log, so keys never mix.
    """
    meta = {
        "provider": getattr(snapshot, "provider", "espn"),
        "observedAt": _iso(_epoch(snapshot.observed_at)),
        "enabled": bool(snapshot.enabled),
        "sourceUrl": snapshot.source_url,
        "httpStatus": snapshot.http_status,
        "error": snapshot.error,
        "providerTimestamp": _iso(_epoch(snapshot.provider_timestamp)),
        "providerTimestampSource": snapshot.provider_timestamp_source,
        "season": snapshot.season,
        "seasonType": snapshot.season_type,
        "week": snapshot.week,
        "eventCount": snapshot.event_count,
        "skippedEvents": snapshot.skipped_events,
        "order": [g.game_key for g in snapshot.games],
    }
    if not snapshot.enabled:
        return "disabled", meta, None
    if not snapshot.ok:
        return "error", meta, None
    content: dict[str, Any] = {}
    for g in snapshot.games:
        row = asdict(g)
        for key in _GAME_SNAPSHOT_FIELDS:
            row.pop(key, None)
        for key in _GAME_DT_FIELDS:
            row[key] = _iso(_epoch(row.get(key)))
        content[str(g.game_key)] = row
    return "ok", meta, content


def scoreboard_from_observation(meta: Mapping[str, Any], content: Mapping[str, Any] | None) -> Any:
    """Rebuild the :class:`ScoreboardSnapshot` a stored observation came from."""
    from src.nfl_data.live_game_state import ObservedGameState, ScoreboardSnapshot

    observed_at = _dt(meta.get("observedAt")) or datetime.now(timezone.utc)
    provider_ts = _dt(meta.get("providerTimestamp"))
    games = []
    if content:
        order = [str(k) for k in (meta.get("order") or ())]
        keys = [k for k in order if k in content] + sorted(k for k in content if k not in order)
        for key in keys:
            row = dict(content[key])
            row["kickoff"] = _dt(row.get("kickoff"))
            row["observed_at"] = observed_at
            row["provider_timestamp"] = provider_ts
            row["provider_timestamp_source"] = meta.get("providerTimestampSource")
            games.append(ObservedGameState(**row))
    return ScoreboardSnapshot(
        provider=str(meta.get("provider") or "espn"),
        observed_at=observed_at,
        enabled=bool(meta.get("enabled", True)),
        source_url=meta.get("sourceUrl"),
        http_status=meta.get("httpStatus"),
        error=meta.get("error"),
        provider_timestamp=provider_ts,
        provider_timestamp_source=meta.get("providerTimestampSource"),
        season=meta.get("season"),
        season_type=meta.get("seasonType"),
        week=meta.get("week"),
        games=tuple(games),
        event_count=_counter(meta.get("eventCount")),
        skipped_events=_counter(meta.get("skippedEvents")),
    )


def weekly_to_observation(result: Any) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    """``(status, meta, content)`` for one weekly projections fetch.

    Rows with no ``game_id`` (Sleeper's no-projection placeholders) are not
    retained — the same rule as the request path; they are never a
    projection of zero.
    """
    meta = {
        "observedAt": result.observed_at,
        "url": result.url,
        "reason": result.reason,
        "season": result.season,
        "week": result.week,
    }
    if result.status != "ok":
        return str(result.status), meta, None
    content = {}
    for row in result.rows:
        pid = row.get("player_id")
        if pid is None or not row.get("game_id"):
            continue
        content[str(pid)] = dict(row)
    meta["rowsReceived"] = len(result.rows)
    return "ok", meta, content


def weekly_from_observation(
    obs: Observation, *, season: int | None = None, week: int | None = None
) -> Any:
    """A stored weekly observation back as a ``FetchResult``.

    Season and week come from the observation's own meta; the log's key
    (``season`` / ``week``, which the caller read it by) answers only when
    the meta does not.  Neither known is a malformed record — refused, never
    stamped as week 0.
    """
    from src.ros.sleeper_weekly_projections import FetchResult

    meta = obs.meta
    stored_season = meta.get("season") if meta.get("season") is not None else season
    stored_week = meta.get("week") if meta.get("week") is not None else week
    if stored_season is None or stored_week is None:
        raise ValueError("stored weekly observation carries no season/week")
    rows = tuple(obs.content[k] for k in sorted(obs.content or {}))
    return FetchResult(
        status="ok",
        season=int(stored_season),
        week=int(stored_week),
        url=str(meta.get("url") or ""),
        observed_at=meta.get("observedAt"),
        rows=rows,
        reason=str(meta.get("reason") or ""),
    )


_weekly_history_cache: dict[str, tuple[tuple[int, int], list[Any]]] = {}


def load_weekly_history(season: int, week: int) -> list[Any]:
    """Every stored weekly projection fetch for the week, as ``FetchResult``s.

    Cached per log file version: the request path may call this on every
    on-demand compute, and replaying the log is the expensive part.
    """
    log = observation_log(NFL_KEY, season, week, SOURCE_WEEKLY)
    try:
        st = log.log_path.stat()
    except OSError:
        return []
    stamp = (st.st_mtime_ns, st.st_size)
    key = str(log.log_path)
    hit = _weekly_history_cache.get(key)
    if hit is not None and hit[0] == stamp:
        return list(hit[1])
    history = [weekly_from_observation(o, season=season, week=week) for o in log.observations()]
    _weekly_history_cache[key] = (stamp, history)
    return list(history)


def live_stats_to_observation(snapshot: Any) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    meta = {
        "observedAt": _iso(_epoch(snapshot.observed_at)),
        "sourceUrl": snapshot.source_url,
        "httpStatus": snapshot.http_status,
        "error": snapshot.error,
        "payloadShape": snapshot.payload_shape,
        "rowCount": snapshot.row_count,
        "skippedRows": snapshot.skipped_rows,
        "skippedValues": snapshot.skipped_values,
        "season": snapshot.season,
        "week": snapshot.week,
    }
    if not snapshot.ok:
        return "error", meta, None
    content: dict[str, Any] = {}
    for pid, line in snapshot.lines.items():
        content[f"p:{pid}"] = dict(line.stats)
    for tid, line in snapshot.team_lines.items():
        content[f"t:{tid}"] = dict(line.stats)
    return "ok", meta, content


def league_fetch_to_content(fetched: Any) -> dict[str, Any]:
    content: dict[str, Any] = {"league": dict(fetched.league or {})}
    for u in fetched.users or ():
        content[f"user:{u.get('user_id')}"] = dict(u)
    for r in fetched.rosters or ():
        content[f"roster:{r.get('roster_id')}"] = dict(r)
    for m in fetched.matchups or ():
        content[f"matchup:{m.get('roster_id')}"] = dict(m)
    return content


# ── Players DB (the full Sleeper dump is fetched at most daily) ──────────


def load_players_meta(
    fetch_players: Callable[[], Mapping[str, Any]],
    rostered_ids: set[str],
    *,
    now: float,
    budget: RequestBudget | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(players_meta, stamp)``.  Kept to players on an NFL team plus every
    rostered player — exactly the population ``game_day_estimates``'s
    shared-name refusal counts, so a trimmed dump answers identically."""
    path = _players_db_path()
    cached = _read_json(path)
    fetched_at = _epoch((cached or {}).get("fetchedAt")) if isinstance(cached, dict) else None
    players = (cached or {}).get("players") if isinstance(cached, dict) else None
    missing = rostered_ids - set(players or {})
    age = (now - fetched_at) if fetched_at is not None else None
    need = players is None or age is None or age > PLAYERS_DB_MAX_AGE_SECONDS
    if not need and missing and age > PLAYERS_DB_MISSING_RETRY_SECONDS:
        need = True
    if need and (budget is None or budget.take("sleeper_players_db")):
        try:
            raw = fetch_players() or {}
        except Exception:  # noqa: BLE001 — keep the last good dump
            raw = {}
        if raw:
            trimmed = {
                str(pid): meta
                for pid, meta in raw.items()
                if isinstance(meta, Mapping) and (meta.get("team") or str(pid) in rostered_ids)
            }
            _atomic_write_json(path, {"fetchedAt": _iso(now), "players": trimmed})
            return trimmed, {"status": "ok", "fetchedAt": _iso(now), "players": len(trimmed)}
    if players is None:
        return {}, {"status": "unavailable", "fetchedAt": None, "players": 0}
    return dict(players), {
        "status": "ok" if not need else "stale_last_good",
        "fetchedAt": _iso(fetched_at),
        "players": len(players),
        "missingRosteredIds": len(missing),
    }


_players_db_cache: dict[str, tuple[tuple[int, int], dict[str, Any], float | None]] = {}


def persisted_players_meta(rostered_ids: set[str], *, now: float | None = None) -> dict | None:
    """The collector's persisted players DB, or ``None`` unless it is within
    :data:`PLAYERS_DB_MAX_AGE_SECONDS` and holds every rostered id (the same
    population rule :func:`load_players_meta` trims to).  Disk only; parsed
    once per file version."""
    path = _players_db_path()
    try:
        st = path.stat()
    except OSError:
        return None
    stamp = (st.st_mtime_ns, st.st_size)
    hit = _players_db_cache.get(str(path))
    if hit is None or hit[0] != stamp:
        cached = _read_json(path)
        players = (cached or {}).get("players") if isinstance(cached, dict) else None
        if not isinstance(players, dict):
            return None
        hit = (stamp, players, _epoch(cached.get("fetchedAt")))
        _players_db_cache[str(path)] = hit
    _, players, fetched_at = hit
    now = time.time() if now is None else now
    if fetched_at is None or now - fetched_at > PLAYERS_DB_MAX_AGE_SECONDS:
        return None
    if not set(rostered_ids) <= set(players):
        return None
    return players


# ── Cadence ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GameWindow:
    game_id: str
    kickoff_at: float | None
    #: ``not_started`` / ``in_progress`` / ``completed`` / ``unknown``.
    state: str


@dataclass(frozen=True)
class CadenceDecision:
    phase: str  # "live" | "near_kickoff" | "idle"
    interval_seconds: float
    next_due_at: float
    stale_after_seconds: float
    reason: str
    next_kickoff_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "intervalSeconds": self.interval_seconds,
            "nextDueAt": _iso(self.next_due_at),
            "staleAfterSeconds": self.stale_after_seconds,
            "reason": self.reason,
            "nextKickoffAt": _iso(self.next_kickoff_at),
        }


def _is_live(w: GameWindow, now: float) -> bool:
    if w.state == "in_progress":
        return True
    if w.state in ("unknown", "not_started") and w.kickoff_at is not None:
        # A passed kickoff with no observed final: find out, every minute.
        return w.kickoff_at <= now < w.kickoff_at + LIVE_WINDOW_AFTER_KICKOFF_SECONDS
    return False


def _upcoming_kickoffs(windows: Sequence[GameWindow], now: float) -> list[float]:
    return sorted(
        w.kickoff_at
        for w in windows
        if w.kickoff_at is not None and w.kickoff_at > now and w.state in ("not_started", "unknown")
    )


def decide_cadence(windows: Sequence[GameWindow], now: float) -> CadenceDecision:
    """How often to tick, from the OBSERVED game windows (never a weekday).

    No windows at all (no schedule cache AND no scoreboard) is UNKNOWN, not
    idle: games may be live unobserved, so the tick keeps the near-kickoff
    cadence until a source answers.
    """
    upcoming = _upcoming_kickoffs(windows, now)
    next_kickoff = upcoming[0] if upcoming else None
    live = [w.game_id for w in windows if _is_live(w, now)]
    if not windows:
        return CadenceDecision(
            phase="unknown",
            interval_seconds=CADENCE_NEAR_KICKOFF_SECONDS,
            next_due_at=now + CADENCE_NEAR_KICKOFF_SECONDS,
            stale_after_seconds=CADENCE_NEAR_KICKOFF_SECONDS * STALE_AFTER_INTERVALS,
            reason="no game windows observed (schedule and scoreboard both unavailable)",
        )
    if live:
        phase, interval, reason = "live", CADENCE_LIVE_SECONDS, f"{len(live)} game(s) live"
    elif next_kickoff is not None and next_kickoff - now <= NEAR_KICKOFF_WINDOW_SECONDS:
        phase, interval = "near_kickoff", CADENCE_NEAR_KICKOFF_SECONDS
        reason = f"kickoff in {int(next_kickoff - now)}s"
    else:
        phase, interval = "idle", CADENCE_IDLE_SECONDS
        reason = "no game live or near kickoff"
    candidates = [now + interval]
    if next_kickoff is not None:
        window_start = next_kickoff - NEAR_KICKOFF_WINDOW_SECONDS
        if window_start > now:
            candidates.append(window_start)
        candidates.append(next_kickoff)
    return CadenceDecision(
        phase=phase,
        interval_seconds=interval,
        next_due_at=max(now + 30.0, min(candidates)),
        stale_after_seconds=interval * STALE_AFTER_INTERVALS,
        reason=reason,
        next_kickoff_at=next_kickoff,
    )


def weekly_projection_due(
    last_fetch_at: float | None, windows: Sequence[GameWindow], now: float
) -> tuple[bool, str]:
    """Whether to fetch weekly projections this tick.

    Only a fetch taken BEFORE a game's kickoff can become that game's
    baseline, so once every game has kicked off there is nothing to fetch.
    Inside the final window before a kickoff one fetch is forced, so the
    kickoff lock holds a recent real observation rather than an old one.
    """
    if not windows:
        # Kickoffs unknown: keep collecting on the near-kickoff interval so a
        # pre-kickoff observation exists whenever the schedule reappears.
        if last_fetch_at is None or now - last_fetch_at >= WEEKLY_NEAR_KICKOFF_INTERVAL_SECONDS:
            return True, "kickoffs_unknown"
        return False, "recent_enough"
    upcoming = _upcoming_kickoffs(windows, now)
    if not upcoming:
        return False, "no_upcoming_kickoff"
    k = upcoming[0]
    if last_fetch_at is None:
        return True, "no_observation_yet"
    if now >= k - PRE_KICKOFF_FINAL_WINDOW_SECONDS and last_fetch_at < (
        k - PRE_KICKOFF_FINAL_WINDOW_SECONDS
    ):
        return True, "pre_kickoff_final_window"
    interval = (
        WEEKLY_NEAR_KICKOFF_INTERVAL_SECONDS
        if k - now <= NEAR_KICKOFF_WINDOW_SECONDS
        else WEEKLY_IDLE_INTERVAL_SECONDS
    )
    if now - last_fetch_at >= interval:
        return True, f"interval_{int(interval)}s"
    return False, "recent_enough"


def live_stats_due(
    last_fetch_at: float | None, windows: Sequence[GameWindow], now: float
) -> tuple[bool, str]:
    if not windows:
        return True, "game_windows_unknown"
    if any(_is_live(w, now) for w in windows):
        return True, "game_live"
    if any(w.state == "completed" for w in windows):
        if last_fetch_at is None or now - last_fetch_at >= LIVE_STATS_POSTGAME_INTERVAL_SECONDS:
            return True, "postgame_corrections"
        return False, "recent_enough"
    return False, "no_game_started"


def windows_from_evidence(evidence: Mapping[str, Any]) -> list[GameWindow]:
    """Per-game windows from per-team evidence (``GameEvidence`` objects or
    their payload dicts, as published in ``lineage.gameEvidence``)."""
    seen: dict[str, GameWindow] = {}
    for team, ev in (evidence or {}).items():
        if isinstance(ev, Mapping):
            gid, kickoff, state = ev.get("gameId"), ev.get("kickoffAt"), ev.get("state")
        else:
            gid, kickoff, state = ev.game_id, ev.kickoff_at, ev.state
        gid = str(gid or f"team:{team}")
        if gid not in seen:
            seen[gid] = GameWindow(game_id=gid, kickoff_at=_epoch(kickoff), state=str(state))
    return list(seen.values())


def observed_windows(
    schedule_rows: Sequence[Mapping[str, Any]],
    snapshot: Any,
    *,
    season: int,
    week: int,
    now: float,
) -> list[GameWindow]:
    """Game windows from the schedule merged with the latest scoreboard."""
    return windows_from_evidence(
        observed_evidence(schedule_rows, snapshot, season=season, week=week, now=now)
    )


def observed_evidence(
    schedule_rows: Sequence[Mapping[str, Any]],
    snapshot: Any,
    *,
    season: int,
    week: int,
    now: float,
) -> dict[str, Any]:
    """``{nfl team: GameEvidence}`` — the schedule merged with the latest scoreboard."""
    from src.ros.game_day_week import (
        merge_game_evidence,
        observed_game_evidence,
        schedule_game_evidence,
    )

    schedule = schedule_game_evidence(
        list(schedule_rows), season=season, week=week, observed_at=None, now=now
    )
    observed = observed_game_evidence(
        snapshot, schedule_rows=list(schedule_rows), season=season, week=week, now=now
    )
    return merge_game_evidence(schedule, observed)


# ── Post-final stat changes (Game Day D) ─────────────────────────────────
#
# Banked points come from the HOST (Sleeper league matchups'
# ``players_points``, under the league's own scoring), which absorbs stat
# corrections itself: a corrected host value changes the league
# observation, so the input fingerprint changes and a NEW generation is
# published (the superseded one stays in ``generations.jsonl`` and the raw
# league log).  Sleeper's live STATS can show a correction before the host
# re-scores it.  That is detected and REPORTED (``statCorrections`` +
# freshness reason ``stat_correction_pending_host``) — never rescored from
# the stat line: host points remain the scoring source of record.

#: What banked points are read from.
SCORING_SOURCE_OF_RECORD = "sleeper:league matchups players_points (host scoring)"
#: ``statCorrections`` entry states.
CORRECTION_PENDING_HOST = "pending_host"
CORRECTION_REFLECTED = "reflected_in_host"
CORRECTION_NOT_SCORED = "not_scored_by_league"
#: Freshness reason while a detected correction is not in the host's points.
REASON_CORRECTION_PENDING_HOST = "stat_correction_pending_host"
#: Host points are published to two decimals.
_HOST_POINTS_TOLERANCE = 0.005


def raw_stat_changes(
    previous: Mapping[str, Any] | None, current: Mapping[str, Any] | None
) -> dict[str, dict[str, list[float | None]]]:
    """``{player_id: {stat: [before, after]}}`` between two stored live-stats
    contents (``p:<id>`` player lines only; ``None`` = key absent, not 0)."""
    prev, cur = previous or {}, current or {}
    out: dict[str, dict[str, list[float | None]]] = {}
    for key in sorted(set(prev) | set(cur)):
        if not key.startswith("p:") or prev.get(key) == cur.get(key):
            continue
        before = prev.get(key) if isinstance(prev.get(key), Mapping) else {}
        after = cur.get(key) if isinstance(cur.get(key), Mapping) else {}
        diff = {
            k: [before.get(k), after.get(k)]
            for k in sorted(set(before) | set(after))
            if before.get(k) != after.get(k)
        }
        if diff:
            out[key[2:]] = diff
    return out


def attribute_post_final_changes(
    changes: Mapping[str, Mapping[str, Any]],
    *,
    players_meta: Mapping[str, Any],
    evidence: Mapping[str, Any],
    final_first_seen: Mapping[str, str],
    previous_fetched_at: float | None,
    detected_at: float,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """``(post_final, unattributable)``: keep only changes to a player whose
    game was ALREADY observed final when the previous stats observation was
    fetched.  A game that went final between the two observations changes
    lines on its way to final — that is not a correction.  A player whose
    game cannot be identified is listed, never guessed in or out."""
    from src.ros.game_day_week import _normalize_nfl_team

    post: dict[str, dict[str, Any]] = {}
    unattributable: list[str] = []
    for pid, diff in changes.items():
        team = _normalize_nfl_team((players_meta.get(pid) or {}).get("team"))
        ev = evidence.get(team) if team else None
        game_id = getattr(ev, "game_id", None) if ev is not None else None
        if not game_id:
            unattributable.append(pid)
            continue
        first_final = _epoch(final_first_seen.get(game_id))
        if first_final is None or previous_fetched_at is None or first_final > previous_fetched_at:
            continue
        post[pid] = {
            "playerId": pid,
            "gameId": game_id,
            "detectedAt": _iso(detected_at),
            "statChanges": {k: list(v) for k, v in diff.items()},
        }
    return post, sorted(unattributable)


def _record_finals(
    gstate: dict[str, Any],
    windows: Sequence[GameWindow],
    *,
    season: int,
    week: int,
    now: float,
) -> dict[str, str]:
    """``{game_id: when a final was FIRST observed}`` for this week, kept in
    the collector state (reset when the week changes)."""
    block = gstate.get("finalFirstSeenAt") or {}
    if block.get("season") != season or block.get("week") != week:
        block = {"season": season, "week": week, "games": {}}
    games = dict(block.get("games") or {})
    for w in windows:
        if w.state == "completed" and w.game_id not in games:
            games[w.game_id] = _iso(now)
    gstate["finalFirstSeenAt"] = {"season": season, "week": week, "games": games}
    return games


def _host_points(matchups: Sequence[Mapping[str, Any]]) -> tuple[dict[str, float | None], set]:
    """``({player_id: host points}, rostered ids)`` from matchup rows."""
    points: dict[str, float | None] = {}
    rostered: set[str] = set()
    for row in matchups or ():
        rostered |= {str(p) for p in (row.get("players") or ()) if p}
        for pid, pts in (row.get("players_points") or {}).items():
            try:
                points[str(pid)] = float(pts)
            except (TypeError, ValueError):
                points[str(pid)] = None
    return points, rostered


def _host_changed(before: float | None, now: float | None) -> bool:
    if before is None or now is None:
        return before is not now
    return abs(float(before) - float(now)) > _HOST_POINTS_TOLERANCE


def update_stat_corrections(
    existing: Mapping[str, Any] | None,
    post_final: Mapping[str, Mapping[str, Any]],
    *,
    previous_matchups: Sequence[Mapping[str, Any]] | None,
    matchups: Sequence[Mapping[str, Any]],
    scoring_card: Mapping[str, Any],
    now: float,
) -> dict[str, dict[str, Any]]:
    """One league-week's ``statCorrections`` after this tick.

    A post-final change to a player ROSTERED in this league whose changed
    stats move points under this league's card (the exact scorer, applied to
    the changed keys only — a diagnostic, never a score) is
    ``pending_host`` until the host's own points for him move from their
    value BEFORE the change was seen; then ``reflected_in_host``.  A change
    this league does not score is ``not_scored_by_league``.
    """
    from src.league_intel.scorer import score_stat_line

    host_now, rostered = _host_points(matchups)
    host_before, _ = _host_points(previous_matchups or ())
    out = {str(pid): dict(e) for pid, e in (existing or {}).items()}
    for pid, change in post_final.items():
        if pid not in rostered:
            continue
        prior = out.get(pid) or {}
        still_pending = prior.get("state") == CORRECTION_PENDING_HOST
        merged = {k: list(v) for k, v in (prior.get("statChanges") or {}).items()}
        for k, (before, after) in change["statChanges"].items():
            merged[k] = [merged[k][0] if k in merged else before, after]
        before_line = {k: v[0] for k, v in merged.items() if v[0] is not None}
        after_line = {k: v[1] for k, v in merged.items() if v[1] is not None}
        delta = (
            score_stat_line(after_line, scoring_card).total_points
            - score_stat_line(before_line, scoring_card).total_points
        )
        baseline = (
            prior.get("hostPointsBefore")
            if still_pending
            else host_before.get(pid, host_now.get(pid))
        )
        out[pid] = {
            "playerId": pid,
            "gameId": change["gameId"],
            "detectedAt": prior.get("detectedAt") if still_pending else change["detectedAt"],
            "statChanges": merged,
            "scoredDeltaUnderLeagueCard": round(delta, 4),
            "hostPointsBefore": baseline,
            "hostPointsNow": host_now.get(pid),
            "state": CORRECTION_NOT_SCORED if abs(delta) < 1e-9 else CORRECTION_PENDING_HOST,
            "reflectedAt": None,
        }
    for entry in out.values():
        if entry.get("state") != CORRECTION_PENDING_HOST:
            continue
        entry["hostPointsNow"] = host_now.get(entry["playerId"])
        if _host_changed(entry.get("hostPointsBefore"), entry["hostPointsNow"]):
            entry.update(state=CORRECTION_REFLECTED, reflectedAt=_iso(now))
    return out


def _matchups_from_content(content: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    return [v for k, v in (content or {}).items() if k.startswith("matchup:")]


# ── Fingerprint ──────────────────────────────────────────────────────────

#: Keys that carry WHEN something was fetched or computed, never what it
#: said.  Stripped before hashing so an unchanged poll is "unchanged".
_VOLATILE_KEYS = frozenset({"observedAt", "sleeperFetchedAt", "cached", "cacheComputedAt"})


def _strip_volatile(obj: Any) -> Any:
    if isinstance(obj, Mapping):
        return {k: _strip_volatile(v) for k, v in obj.items() if k not in _VOLATILE_KEYS}
    if isinstance(obj, (list, tuple)):
        return [_strip_volatile(v) for v in obj]
    return obj


def input_fingerprint(assembly: Any, *, draws: int, seed: int) -> str:
    """Identity of a generation's INPUT CONTENT.

    Two parts, both content-only: the pre-simulation render of every team
    with fetch/compute timestamps removed (everything a reader sees that is
    not the forecast), and the simulation's own input fingerprint (rules,
    every team's players, opponents, draws, seed, points model).  A clock
    that moved, a projection re-fetched unchanged, or a scoreboard polled
    at halftime does not change it; a point scored, a clock tick, a
    provider line change or a roster move does.
    """
    from src.api import matchup_intel as mi
    from src.ros.game_day_sim import simulation_input_fingerprint

    if assembly.simulation is not None:
        raise ValueError("fingerprint the assembly before simulating it")
    pre = _strip_volatile(mi.render_league(assembly))
    resolution = assembly.scoring.week
    sim_fp = simulation_input_fingerprint(
        rules=resolution.rules,
        teams=resolution.teams,
        opponents=resolution.opponents,
        draws=draws,
        seed=seed,
    )
    return _content_hash({"schema": GENERATION_SCHEMA_VERSION, "render": pre, "simulation": sim_fp})


# ── Source stamps and freshness ──────────────────────────────────────────


def _live_state_stamp(snapshot: Any) -> dict[str, Any]:
    """The freshness stamp for one live-game-state snapshot, naming its provider."""
    from src.nfl_data.live_game_state import PROVIDER_FLAGS, provider_source_label

    if snapshot is None:
        return {"source": "espn:scoreboard", "status": "unavailable", "fetchedAt": None}
    name = getattr(snapshot, "provider", "espn")
    fetched = _iso(_epoch(snapshot.observed_at))
    provider_ts = _iso(_epoch(snapshot.provider_timestamp))
    status = "disabled" if not snapshot.enabled else ("ok" if snapshot.ok else "error")
    return {
        "source": provider_source_label(name),
        "provider": name,
        "flag": PROVIDER_FLAGS.get(name, "game_day_live_game_state"),
        "status": status,
        "error": snapshot.error,
        "fetchedAt": fetched,
        "observedAt": provider_ts or fetched,
        "observedAtBasis": snapshot.provider_timestamp_source or "fetch_time",
        "gamesObserved": len(snapshot.games),
    }


def source_stamps(inputs: Any, lineage: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Per-source ``observedAt`` / ``fetchedAt`` / status for one input set.

    ``fetchedAt`` is when WE fetched; ``observedAt`` is when the source says
    its content was true, where it says so (``observedAtBasis`` names the
    evidence), otherwise the fetch time with basis ``fetch_time``.
    """
    fetched = inputs.fetched
    weekly = lineage.get("weeklyProjection") or {}
    ok_fetches = [f for f in inputs.weekly_fetches if getattr(f, "status", None) == "ok"]
    newest_fetch = max((f.observed_at for f in ok_fetches if f.observed_at), default=None)
    league_fetched = _iso(fetched.fetched_at)
    live = _live_state_stamp(inputs.live_snapshot)
    espn = (
        live
        if live.get("provider", "espn") == "espn"
        else {"source": "espn:scoreboard", "provider": "espn", "status": "not_used"}
    )
    return {
        # The provider whose state these numbers were built on.  The
        # collector overwrites this (and adds every provider's attempt)
        # with the tick's recorded selection.
        "liveGameState": live,
        "espnScoreboard": espn,
        "sleeperLeague": {
            "source": "sleeper:league+users+rosters+matchups",
            "status": "ok" if fetched.rosters else "empty",
            "fetchedAt": league_fetched,
            "observedAt": league_fetched,
            "observedAtBasis": "fetch_time",
            "rosters": len(fetched.rosters or ()),
            "matchups": len(fetched.matchups or ()),
        },
        "weeklyProjections": {
            "source": "sleeper:projections (RotoWire via Sleeper)",
            "flag": "sleeper_weekly_projections",
            "status": weekly.get("state") or inputs.weekly_state,
            "reason": weekly.get("reason") or inputs.weekly_reason,
            "fetchedAt": newest_fetch,
            "observedAt": weekly.get("asOf"),
            "observedAtBasis": "provider_updated_at",
            "fetchesRetained": len(ok_fetches),
        },
        "nflverseSchedule": {
            "source": "nflverse:schedules (cache)",
            "status": "ok" if inputs.schedule_rows else "unavailable",
            "fetchedAt": _iso(inputs.schedule_observed_at),
            "observedAt": _iso(inputs.schedule_observed_at),
            "observedAtBasis": "cache_write_time",
        },
        "preseasonProjection": {
            "source": lineage.get("preseasonProjectionSource"),
            "status": "ok" if lineage.get("preseasonProjectionSource") else "unavailable",
        },
    }


#: ``current`` / ``partial`` / ``degraded`` / ``stale`` describe a SERVED
#: generation; ``pending`` (a background compute is running or about to)
#: and ``failed`` (the last background compute failed; retried after
#: :data:`BACKGROUND_RETRY_AFTER_SECONDS`) describe a payload that carries
#: no forecast at all (Game Day G).
FRESHNESS_STATES = ("current", "partial", "degraded", "stale", "pending", "failed")


def _partial_reasons(sources: Mapping[str, Mapping[str, Any]], mode: str | None) -> list[str]:
    reasons: list[str] = []
    if mode == "final":
        return reasons
    # Generations written before provider selection carry only espnScoreboard.
    live = sources.get("liveGameState") or sources.get("espnScoreboard") or {}
    if mode != "pregame" and live.get("status") not in ("ok", None):
        reasons.append(f"live_game_state:{live.get('status')}")
        # Name each provider's own failure, so "partial" says WHY.
        for name, key in (("espn", "espnScoreboard"), ("sportsdataio", "sportsDataIoScores")):
            attempt = sources.get(key)
            if not attempt or attempt is live:
                continue
            if attempt.get("status") in ("ok", None, "not_needed"):
                continue
            last = attempt.get("lastAttempt") or {}
            detail = (
                attempt.get("error")
                or last.get("error")
                or ",".join(attempt.get("reasons") or ())
                or attempt.get("status")
            )
            reasons.append(f"live_game_state.{name}:{detail}")
    weekly = sources.get("weeklyProjections") or {}
    if weekly and weekly.get("status") != "ok":
        reasons.append(f"weekly_projections:{weekly.get('status')}")
    league = sources.get("sleeperLeague") or {}
    if league and league.get("status") != "ok":
        reasons.append(f"sleeper_league:{league.get('status')}")
    sched = sources.get("nflverseSchedule") or {}
    if sched and sched.get("status") != "ok":
        reasons.append("nflverse_schedule:unavailable")
    return reasons


def build_freshness(
    *,
    served_from: str,
    sources: Mapping[str, Mapping[str, Any]],
    as_of: float | None,
    computed_at: float | None,
    now: float,
    cadence: CadenceDecision,
    mode: str | None,
    generation_id: str | None = None,
    simulation_computed_at: float | None = None,
    last_verified_at: float | None = None,
    refresh_in_progress: bool = False,
    refresh_started_at: float | None = None,
    collector: Mapping[str, Any] | None = None,
    degraded_reasons: Sequence[str] = (),
    extra_partial_reasons: Sequence[str] = (),
    stat_corrections: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The payload's ``freshness`` block.

    ``payloadAgeSeconds`` is now minus ``asOf`` — the last moment the payload
    was KNOWN to reflect the freshest collected evidence (the latest tick
    that confirmed its inputs unchanged, else when its inputs were fetched).
    ``state``, worst first: ``stale`` (older than three cadence intervals
    for the current phase), ``degraded`` (not the collector's current
    answer), ``partial`` (a source was unavailable, or a detected stat
    correction the host has not yet absorbed — ``extra_partial_reasons``,
    which apply in every mode including ``final``), ``current``.
    """
    age = (now - as_of) if as_of is not None else None
    reasons: list[str] = []
    stale = age is None or age > cadence.stale_after_seconds
    if stale:
        reasons.append(
            "payload_age_unknown"
            if age is None
            else f"payload_age_{int(age)}s_exceeds_{int(cadence.stale_after_seconds)}s"
        )
    reasons.extend(degraded_reasons)
    partial = [*_partial_reasons(sources, mode), *extra_partial_reasons]
    reasons.extend(partial)
    state = (
        "stale"
        if stale
        else "degraded"
        if degraded_reasons
        else "partial"
        if partial
        else "current"
    )
    stamped_sources = {}
    for name, src in sources.items():
        entry = dict(src)
        fetched = _epoch(entry.get("fetchedAt"))
        entry["ageSeconds"] = round(now - fetched, 1) if fetched is not None else None
        stamped_sources[name] = entry
    return {
        "state": state,
        "reasons": reasons,
        "servedFrom": served_from,
        "generationId": generation_id,
        "generationComputedAt": _iso(computed_at),
        "simulationComputedAt": _iso(simulation_computed_at),
        "lastVerifiedAt": _iso(last_verified_at),
        "asOf": _iso(as_of),
        "payloadAgeSeconds": round(age, 1) if age is not None else None,
        "staleAfterSeconds": cadence.stale_after_seconds,
        "phase": cadence.phase,
        "refreshInProgress": bool(refresh_in_progress),
        "refreshStartedAt": _iso(refresh_started_at),
        "collector": dict(collector) if collector is not None else None,
        "sources": stamped_sources,
        "statCorrections": dict(stat_corrections) if stat_corrections is not None else None,
    }


# ── Generations ──────────────────────────────────────────────────────────

_generation_cache: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
_generation_cache_lock = threading.Lock()
_generation_write_lock = threading.Lock()


def load_generation(league_key: str, season: int, week: int) -> dict[str, Any] | None:
    """The latest generation, parsed once per file version (mtime, size)."""
    path = generation_path(league_key, season, week)
    try:
        st = path.stat()
    except OSError:
        return None
    stamp = (st.st_mtime_ns, st.st_size)
    key = str(path)
    with _generation_cache_lock:
        hit = _generation_cache.get(key)
        if hit is not None and hit[0] == stamp:
            return hit[1]
    gen = _read_json(path)
    if not isinstance(gen, dict) or gen.get("schemaVersion") != GENERATION_SCHEMA_VERSION:
        return None
    with _generation_cache_lock:
        _generation_cache[key] = (stamp, gen)
    return gen


def write_generation(generation: Mapping[str, Any]) -> bool:
    """Atomically publish ``generation`` unless a NEWER one is already there.

    Order is decided by ``sequence`` (the epoch at which the tick fetched its
    inputs), so a slow tick that started earlier can never overwrite what a
    later tick published.  Returns whether it was written.

    ``generation.json`` holds only the LATEST answer; every published
    generation is also appended to ``generations.jsonl`` (never rewritten)
    with ``supersedes`` naming the one it replaced, so an answer that a
    later input (a stat correction, a scored point) changed stays
    retrievable as it was known — see :func:`load_generation_history`.
    """
    league_key = generation["leagueKey"]
    season, week = int(generation["season"]), int(generation["week"])
    path = generation_path(league_key, season, week)
    with _generation_write_lock:
        current = _read_json(path)
        previous_id = None
        if isinstance(current, dict) and current.get("schemaVersion") == GENERATION_SCHEMA_VERSION:
            # A stored generation with no sequence cannot be shown newer, so
            # it is superseded rather than protected.
            current_seq = current.get("sequence")
            if current_seq is not None and float(current_seq) >= float(generation["sequence"]):
                return False
            previous_id = current.get("generationId")
        generation = {**dict(generation), "supersedes": previous_id}
        generation["render"] = _with_median_movement(
            generation.get("render"),
            current if previous_id is not None else None,
            generation,
        )
        _atomic_write_json(path, generation)
        _append_line(
            _generation_index_path(league_key, season, week),
            _generation_index_row(generation),
        )
    return True


def _with_median_movement(
    render: Any,
    previous: Mapping[str, Any] | None,
    generation: Mapping[str, Any],
) -> Any:
    """The Live Median Race's movement: each team's beat-median probability
    change, in percentage points, since the generation this one SUPERSEDES.

    Consumes the existing versioned generation chain — no second history.
    Only a comparable predecessor counts: the same league-week file (by
    construction), the same ``modelVersion``, and both published as a
    ``forecast``.  Otherwise movement is absent, never 0.
    """
    if not isinstance(render, Mapping):
        return render
    race = render.get("medianRace")
    if not isinstance(race, Mapping) or race.get("state") != "forecast":
        return render
    prev_race = ((previous or {}).get("render") or {}).get("medianRace") or {}
    if (
        previous is None
        or previous.get("modelVersion") != generation.get("modelVersion")
        or prev_race.get("state") != "forecast"
    ):
        return render
    before = {
        str(t.get("rosterId")): t.get("beatMedianPct")
        for t in prev_race.get("teams") or ()
        if isinstance(t, Mapping)
    }
    teams = []
    for t in race.get("teams") or ():
        row = dict(t)
        old, new = before.get(str(row.get("rosterId"))), row.get("beatMedianPct")
        if isinstance(old, (int, float)) and isinstance(new, (int, float)):
            row["movementPp"] = round(float(new) - float(old), 1)
        teams.append(row)
    return {
        **dict(render),
        "medianRace": {
            **dict(race),
            "teams": teams,
            "movement": {
                "comparedToGenerationId": previous.get("generationId"),
                "comparedToComputedAt": previous.get("computedAt"),
            },
        },
    }


def _median_race_summary(render: Mapping[str, Any]) -> dict[str, Any] | None:
    """Calibration evidence for the median race, kept in the append-only
    generation index: what the league median was projected to be at this
    generation's cutoff, each team's beat-median probability, and — once
    final — the actual median and each team's actual BEAT / MISS / TIE."""
    race = render.get("medianRace")
    if not isinstance(race, Mapping):
        return None
    return {
        "state": race.get("state"),
        "verified": race.get("verified"),
        "currentMedian": race.get("currentMedian"),
        "projectedMedianMean": race.get("projectedMedianMean"),
        "projectedMedianP10": race.get("projectedMedianP10"),
        "projectedMedianP50": race.get("projectedMedianP50"),
        "projectedMedianP90": race.get("projectedMedianP90"),
        "finalMedian": race.get("finalMedian"),
        "teams": {
            str(t.get("rosterId")): {
                "beatMedianPct": t.get("beatMedianPct"),
                "medianMarginMean": t.get("medianMarginMean"),
                "finalScore": t.get("finalScore"),
                "finalResult": t.get("finalResult"),
            }
            for t in race.get("teams") or ()
            if isinstance(t, Mapping)
        },
    }


def _generation_index_row(generation: Mapping[str, Any]) -> dict[str, Any]:
    """Summary appended per published generation: calibration-useful, and
    the AS-KNOWN record of what was served (banked score, host score and
    forecast per side) plus the raw league observation ``seq`` it was built
    from, so a later correction never erases what an earlier answer said."""
    sides = (generation.get("render") or {}).get("sides") or {}
    inputs = generation.get("inputs") or {}
    return {
        "generationId": generation["generationId"],
        "supersedes": generation.get("supersedes"),
        "producer": generation.get("producer"),
        "sequence": generation["sequence"],
        "inputsFetchedAt": generation.get("inputsFetchedAt"),
        "computedAt": generation.get("computedAt"),
        "inputFingerprint": generation.get("inputFingerprint"),
        "leagueObservationSeq": inputs.get("leagueObservationSeq"),
        "mode": ((generation.get("render") or {}).get("shared") or {}).get("mode"),
        "modelVersion": generation.get("modelVersion"),
        "medianRace": _median_race_summary(generation.get("render") or {}),
        "outcomes": {
            rid: {
                "winMatchupPct": (s.get("outcome") or {}).get("winMatchupPct"),
                "beatMedianPct": (s.get("outcome") or {}).get("beatMedianPct"),
                "expectedFinalBestBall": (s.get("outcome") or {}).get("expectedFinalBestBall"),
                "actualScore": s.get("actualScore"),
                "pointsBanked": s.get("pointsBanked"),
                "scoreNow": s.get("scoreNow"),
            }
            for rid, s in sides.items()
        },
    }


def load_generation_history(league_key: str, season: int, week: int) -> list[dict[str, Any]]:
    """Every published generation's index row for the league-week, oldest
    first (the append-only ``generations.jsonl``).  A damaged line is skipped,
    never fatal."""
    path = _generation_index_path(league_key, season, week)
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def build_generation(
    *,
    assembly: Any,
    render: Mapping[str, Any],
    fingerprint: str,
    sources: Mapping[str, Any],
    inputs_fetched_at: float,
    computed_at: float,
    compute_seconds: float,
    draws: int,
    seed: int,
    extra_inputs: Mapping[str, Any] | None = None,
    producer: str = PRODUCER,
) -> dict[str, Any]:
    from src.ros.game_day_sim import MODEL_VERSION

    resolution = assembly.scoring.week
    sim = assembly.simulation
    sim_body = None
    if sim is not None:
        sim_body = asdict(sim)
    return {
        "schemaVersion": GENERATION_SCHEMA_VERSION,
        "generationId": (
            f"{assembly.league_key}:{assembly.season}:w{assembly.week}:"
            f"{int(inputs_fetched_at * 1000)}:{fingerprint[:12]}"
        ),
        "producer": producer,
        "leagueKey": assembly.league_key,
        "season": assembly.season,
        "week": assembly.week,
        "sequence": inputs_fetched_at,
        "inputsFetchedAt": _iso(inputs_fetched_at),
        "computedAt": _iso(computed_at),
        "computeSeconds": round(compute_seconds, 3),
        "modelVersion": MODEL_VERSION,
        "draws": draws,
        "seed": seed,
        "inputFingerprint": fingerprint,
        "inputs": {"sources": dict(sources), **dict(extra_inputs or {})},
        "resolved": {
            "mode": assembly.scoring.mode,
            "teams": [asdict(t) for t in resolution.teams],
            "opponents": dict(resolution.opponents),
            "hostScores": dict(assembly.scoring.host_scores),
        },
        "simulation": sim_body,
        "simulationError": assembly.sim_error,
        "render": dict(render),
    }


# ── League-week state + lock ─────────────────────────────────────────────


def load_league_state(league_key: str, season: int, week: int) -> dict[str, Any]:
    state = _read_json(league_state_path(league_key, season, week))
    return state if isinstance(state, dict) else {}


def _save_league_state(league_key: str, season: int, week: int, state: Mapping[str, Any]) -> None:
    _atomic_write_json(league_state_path(league_key, season, week), state)


def _lock_info() -> dict[str, Any] | None:
    info = _read_json(_lock_path())
    return info if isinstance(info, dict) else None


def lock_is_fresh(now: float) -> bool:
    info = _lock_info()
    started = _epoch((info or {}).get("startedAt"))
    return started is not None and now - started < LOCK_STALE_SECONDS


def _acquire_lock(now: float) -> bool:
    path = _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"pid": os.getpid(), "startedAt": _iso(now)})
    for _ in range(2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if lock_is_fresh(now):
                return False
            # Abandoned by a run that died: take it over.
            try:
                path.unlink()
            except OSError:
                return False
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        return True
    return False


def _release_lock() -> None:
    try:
        _lock_path().unlink()
    except OSError:
        pass


def collector_active(state: Mapping[str, Any], now: float) -> bool:
    """Has the collector ticked this league-week recently (or is it ticking)?"""
    if state.get("refreshStartedAt") and lock_is_fresh(now):
        return True
    last = _epoch(state.get("lastTickFinishedAt"))
    return last is not None and now - last <= COLLECTOR_ABSENT_AFTER_SECONDS


# ── Serving (the API path) ───────────────────────────────────────────────


def stat_corrections_summary(state: Mapping[str, Any] | None) -> dict[str, Any]:
    """The ``freshness.statCorrections`` block from a league-week state.

    Host points stay the scoring source of record: a post-final stat change
    seen in Sleeper's live stats is REPORTED here until the host's own
    player points move, and never rescored from the stat line.
    """
    entries = list(((state or {}).get("statCorrections") or {}).values())
    pending = sorted(
        (e for e in entries if e.get("state") == CORRECTION_PENDING_HOST),
        key=lambda e: str(e.get("playerId")),
    )
    return {
        "scoringSourceOfRecord": SCORING_SOURCE_OF_RECORD,
        "pendingHost": [dict(e) for e in pending],
        "reflectedInHostCount": sum(1 for e in entries if e.get("state") == CORRECTION_REFLECTED),
        "notScoredByLeagueCount": sum(
            1 for e in entries if e.get("state") == CORRECTION_NOT_SCORED
        ),
    }


def _generation_freshness(
    gen: Mapping[str, Any], state: Mapping[str, Any], now: float
) -> dict[str, Any]:
    render = gen.get("render") or {}
    lineage = render.get("lineage") or {}
    mode = (render.get("shared") or {}).get("mode")
    cadence = decide_cadence(windows_from_evidence(lineage.get("gameEvidence") or {}), now)
    verified = (
        _epoch(state.get("lastVerifiedAt"))
        if state.get("generationId") == gen.get("generationId")
        else None
    )
    fetched = _epoch(gen.get("inputsFetchedAt"))
    as_of = max(t for t in (verified, fetched) if t is not None) if (verified or fetched) else None
    degraded: list[str] = []
    producer = gen.get("producer") or PRODUCER
    if producer != PRODUCER:
        # Computed in the background for a request, not by the collector.
        degraded.append(
            (gen.get("inputs") or {}).get("requestComputeReason") or "no_collector_generation"
        )
    if state and state.get("lastTickOk") is False:
        degraded.append(f"last_collector_tick_failed:{state.get('lastError')}")
    latest_fp = state.get("latestInputFingerprint")
    if latest_fp and latest_fp != gen.get("inputFingerprint") and not state.get("refreshStartedAt"):
        degraded.append("generation_behind_latest_evidence")
    refreshing = bool(state.get("refreshStartedAt")) and lock_is_fresh(now)
    sim = gen.get("simulation")
    corrections = stat_corrections_summary(state)
    return build_freshness(
        served_from=SERVED_COLLECTOR if producer == PRODUCER else SERVED_REQUEST_GENERATION,
        sources=(gen.get("inputs") or {}).get("sources") or {},
        as_of=as_of,
        computed_at=_epoch(gen.get("computedAt")),
        now=now,
        cadence=cadence,
        mode=mode,
        generation_id=gen.get("generationId"),
        simulation_computed_at=_epoch(gen.get("computedAt")) if sim else None,
        last_verified_at=verified,
        refresh_in_progress=refreshing,
        refresh_started_at=_epoch(state.get("refreshStartedAt")) if refreshing else None,
        collector={
            "lastTickFinishedAt": state.get("lastTickFinishedAt"),
            "lastTickOk": state.get("lastTickOk"),
            "lastTickOutcome": state.get("lastTickOutcome"),
            "cadence": state.get("cadence"),
        }
        if state
        else None,
        degraded_reasons=degraded,
        extra_partial_reasons=[REASON_CORRECTION_PENDING_HOST]
        if corrections["pendingHost"]
        else [],
        stat_corrections=corrections,
    )


#: ``freshness.servedFrom`` values.
SERVED_COLLECTOR = "collector_generation"
SERVED_REQUEST_GENERATION = "request_generation"
SERVED_PENDING = "pending_factual"


def serve_league_render(
    *,
    league_key: str,
    sleeper_league_id: str,
    season: int,
    week: int,
    roster_settings: Mapping[str, Any] | None = None,
    draws: int,
    seed: int,
) -> tuple[Mapping[str, Any], dict[str, Any]]:
    """``(league render, freshness)`` for the API.  Never runs the simulation
    on the request thread.

    1. The latest generation for this league-week (same draws and seed) —
       served as-is with its true as-of while it is not stale or the
       collector is active for it.
    2. A STALE generation nobody is refreshing (collector absent) — still
       served immediately at its true age, while ONE background compute
       refreshes it (``backgroundCompute`` / ``refreshInProgress``).
    3. No usable generation — a PENDING payload from cheap factual inputs
       (``matchup_intel.pending_league_render``: rosters, host scores, game
       states and the banked best-ball lineup; every forecast field
       withheld; ``freshness.state == "pending"``), and ONE background
       compute per league-week whose generation the next poll serves.  A
       failed background compute answers ``freshness.state == "failed"``
       with the error named — never a fabricated number.
    """
    now = time.time()
    gen = load_generation(league_key, season, week)
    state = load_league_state(league_key, season, week)
    params = {
        "league_key": league_key,
        "sleeper_league_id": sleeper_league_id,
        "season": int(season),
        "week": int(week),
        "roster_settings": roster_settings,
        "draws": int(draws),
        "seed": int(seed),
    }
    key = background_key(**params)
    if gen is not None and gen.get("draws") == draws and gen.get("seed") == seed:
        fresh = _generation_freshness(gen, state, now)
        if fresh["state"] != "stale" or collector_active(state, now):
            return gen["render"], fresh
        bg = ensure_background_compute(
            key, reason="collector_absent_generation_stale", now=now, **params
        )
        return gen["render"], _with_background(fresh, bg)
    reason = "no_collector_generation" if gen is None else "generation_draws_or_seed_differ"
    from src.api import matchup_intel as mi

    render, inputs = mi.pending_league_render(
        league_key=league_key,
        sleeper_league_id=sleeper_league_id,
        season=int(season),
        week=int(week),
        roster_settings=roster_settings,
    )
    bg = ensure_background_compute(key, reason=reason, fetched=inputs.fetched, now=now, **params)
    return render, _pending_freshness(render, inputs, bg, time.time())


def _with_background(fresh: Mapping[str, Any], bg: Mapping[str, Any]) -> dict[str, Any]:
    """A served (stale) generation's freshness, plus its background refresh."""
    out = dict(fresh)
    reasons = list(out.get("reasons") or ())
    if bg["state"] == "running":
        out["refreshInProgress"] = True
        out["refreshStartedAt"] = bg.get("startedAt")
        reasons.append("background_refresh_running")
    elif bg["state"] == "failed":
        reasons.append(f"background_refresh_failed:{bg.get('error')}")
    elif bg["state"] == "capacity_exhausted":
        reasons.append("background_compute_capacity_exhausted")
    out["reasons"] = reasons
    out["backgroundCompute"] = dict(bg)
    return out


def _pending_freshness(
    render: Mapping[str, Any], inputs: Any, bg: Mapping[str, Any], now: float
) -> dict[str, Any]:
    """The ``freshness`` block of a PENDING payload.

    ``state`` is ``pending`` while a background compute runs (or could not
    start for capacity and will on the next poll) and ``failed`` when the
    last attempt failed and its retry window has not passed.  Sources are
    only what the pending payload actually read; ``weeklyProjections``
    says ``pending`` because projections were not read, not that none exist.
    """
    lineage = render.get("lineage") or {}
    cadence = decide_cadence(windows_from_evidence(lineage.get("gameEvidence") or {}), now)
    fresh = build_freshness(
        served_from=SERVED_PENDING,
        sources=source_stamps(inputs, lineage),
        as_of=_epoch(inputs.fetched.fetched_at),
        computed_at=None,
        now=now,
        cadence=cadence,
        mode=(render.get("shared") or {}).get("mode"),
        refresh_in_progress=bg["state"] == "running",
        refresh_started_at=_epoch(bg.get("startedAt")) if bg["state"] == "running" else None,
    )
    if bg["state"] == "failed":
        state, lead = "failed", [f"generation_failed:{bg.get('error')}"]
    else:
        state, lead = "pending", [PENDING_REASON]
        if bg["state"] == "capacity_exhausted":
            lead.append("background_compute_capacity_exhausted")
        previous = bg.get("previous") or {}
        if previous.get("outcome") == "failed":
            lead.append(f"previous_attempt_failed:{previous.get('error')}")
    fresh["state"] = state
    fresh["reasons"] = [*lead, *fresh["reasons"]]
    fresh["backgroundCompute"] = dict(bg)
    return fresh


#: The pending payload's reason (and ``matchup_intel.PENDING_REASON``).
PENDING_REASON = "generation_pending"


@dataclass
class BackgroundAttempt:
    """One background league-week compute, as the serving path reports it."""

    league_key: str
    season: int
    week: int
    reason: str
    started_at: float
    finished_at: float | None = None
    #: ``written`` | ``superseded_by_newer_generation`` | ``failed``.
    outcome: str | None = None
    error: str | None = None
    generation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "leagueKey": self.league_key,
            "season": self.season,
            "week": self.week,
            "reason": self.reason,
            "startedAt": _iso(self.started_at),
            "finishedAt": _iso(self.finished_at),
            "outcome": self.outcome,
            "error": self.error,
            "generationId": self.generation_id,
        }


_background_lock = threading.Lock()
_background_running: dict[tuple, BackgroundAttempt] = {}
_background_threads: dict[tuple, threading.Thread] = {}
_background_last: dict[tuple, BackgroundAttempt] = {}


def background_key(
    *,
    league_key: str,
    sleeper_league_id: str,
    season: int,
    week: int,
    roster_settings: Mapping[str, Any] | None,
    draws: int,
    seed: int,
) -> tuple:
    """One background compute per (league-week, draws, seed, settings)."""
    settings_key = json.dumps(dict(roster_settings or {}), sort_keys=True, default=str)
    return (
        league_key,
        sleeper_league_id,
        int(season),
        int(week),
        int(draws),
        int(seed),
        settings_key,
    )


def ensure_background_compute(
    key: tuple,
    *,
    reason: str,
    league_key: str,
    sleeper_league_id: str,
    season: int,
    week: int,
    roster_settings: Mapping[str, Any] | None,
    draws: int,
    seed: int,
    fetched: Any = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Start at most ONE background compute for ``key``; return its status.

    ``state``: ``running`` (``triggered`` says whether THIS call started
    it), ``failed`` (the last attempt failed less than
    :data:`BACKGROUND_RETRY_AFTER_SECONDS` ago — not retried yet) or
    ``capacity_exhausted`` (:data:`MAX_BACKGROUND_COMPUTES` already run).
    Concurrent callers share the one running compute; nothing here blocks
    on it.
    """
    now = time.time() if now is None else now
    with _background_lock:
        running = _background_running.get(key)
        last = _background_last.get(key)
        previous = last.to_dict() if last is not None else None
        if running is not None:
            return {
                "state": "running",
                "triggered": False,
                **running.to_dict(),
                "previous": previous,
            }
        if (
            last is not None
            and last.outcome == "failed"
            and last.finished_at is not None
            and now - last.finished_at < BACKGROUND_RETRY_AFTER_SECONDS
        ):
            return {
                "state": "failed",
                "triggered": False,
                **last.to_dict(),
                "retryAfter": _iso((last.finished_at or now) + BACKGROUND_RETRY_AFTER_SECONDS),
            }
        if len(_background_running) >= MAX_BACKGROUND_COMPUTES:
            return {
                "state": "capacity_exhausted",
                "triggered": False,
                "limit": MAX_BACKGROUND_COMPUTES,
                "previous": previous,
            }
        attempt = BackgroundAttempt(
            league_key=league_key, season=int(season), week=int(week), reason=reason, started_at=now
        )
        thread = threading.Thread(
            target=_run_background,
            args=(key, attempt),
            kwargs={
                "league_key": league_key,
                "sleeper_league_id": sleeper_league_id,
                "season": int(season),
                "week": int(week),
                "roster_settings": roster_settings,
                "draws": int(draws),
                "seed": int(seed),
                "reason": reason,
                "fetched": fetched,
            },
            name=f"game-day-compute:{league_key}:{season}:w{week}",
            daemon=True,
        )
        _background_running[key] = attempt
        _background_threads[key] = thread
    try:
        thread.start()
    except RuntimeError as exc:  # the interpreter could not start a thread
        _finish_background(key, attempt, "failed", f"{type(exc).__name__}: {exc}", None)
        return {"state": "failed", "triggered": False, **attempt.to_dict()}
    return {"state": "running", "triggered": True, **attempt.to_dict(), "previous": previous}


def _finish_background(
    key: tuple,
    attempt: BackgroundAttempt,
    outcome: str,
    error: str | None,
    generation_id: str | None,
) -> None:
    attempt.finished_at = time.time()
    attempt.outcome, attempt.error, attempt.generation_id = outcome, error, generation_id
    with _background_lock:
        _background_running.pop(key, None)
        _background_threads.pop(key, None)
        _background_last.pop(key, None)
        _background_last[key] = attempt
        while len(_background_last) > BACKGROUND_HISTORY_MAX:
            _background_last.pop(next(iter(_background_last)))


def _run_background(key: tuple, attempt: BackgroundAttempt, **params: Any) -> None:
    try:
        generation = compute_request_generation(**params)
        written = write_generation(generation)
    except Exception as exc:  # noqa: BLE001 — reported by the next poll, never raised into it
        _finish_background(key, attempt, "failed", f"{type(exc).__name__}: {exc}", None)
        return
    _finish_background(
        key,
        attempt,
        "written" if written else "superseded_by_newer_generation",
        None,
        generation["generationId"],
    )


def compute_request_generation(
    *,
    league_key: str,
    sleeper_league_id: str,
    season: int,
    week: int,
    roster_settings: Mapping[str, Any] | None,
    draws: int,
    seed: int,
    reason: str,
    fetched: Any = None,
) -> dict[str, Any]:
    """The request path's full compute, as a generation (background thread only).

    Acquisition through the request-path seams (``prepare_league_week``),
    then the SAME fingerprint, simulation, render and generation layout the
    collector uses — only ``producer`` (:data:`PRODUCER_REQUEST`) and
    ``inputs.requestComputeReason`` differ, and the serving path labels it
    ``request_generation`` + ``degraded`` accordingly.
    """
    from src.api import matchup_intel as mi

    started = time.time()
    assembly = mi.prepare_league_week(
        league_key=league_key,
        sleeper_league_id=sleeper_league_id,
        season=season,
        week=week,
        roster_settings=roster_settings,
        fetched=fetched,
    )
    fingerprint = input_fingerprint(assembly, draws=draws, seed=seed)
    mi.run_league_simulation(assembly, draws=draws, seed=seed)
    render = mi.render_league(assembly)
    inputs = assembly.inputs
    computed_at = time.time()
    return build_generation(
        assembly=assembly,
        render=render,
        fingerprint=fingerprint,
        sources=source_stamps(inputs, render.get("lineage") or {}),
        inputs_fetched_at=inputs.now,
        computed_at=computed_at,
        compute_seconds=computed_at - started,
        draws=draws,
        seed=seed,
        extra_inputs={"requestComputeReason": reason},
        producer=PRODUCER_REQUEST,
    )


def background_status(key: tuple) -> dict[str, Any] | None:
    """The running or last-finished background attempt for ``key``."""
    with _background_lock:
        attempt = _background_running.get(key) or _background_last.get(key)
        return attempt.to_dict() if attempt is not None else None


def wait_for_background(timeout: float | None = None) -> bool:
    """Join every running background compute (tests, scripts).  Returns
    whether all finished within ``timeout``."""
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        with _background_lock:
            threads = list(_background_threads.values())
        if not threads:
            return True
        for thread in threads:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            thread.join(remaining)
        if deadline is not None and time.monotonic() >= deadline:
            with _background_lock:
                return not _background_threads


def reset_background_state() -> None:
    """Forget finished attempts (tests).  Running computes are left alone."""
    with _background_lock:
        _background_last.clear()


# ── The collector tick ───────────────────────────────────────────────────


class RequestBudget:
    """Counts network requests in one tick; refuses past the cap."""

    def __init__(self, limit: int = MAX_REQUESTS_PER_TICK):
        self.limit = int(limit)
        self.used: list[str] = []
        self.refused: list[str] = []

    def take(self, name: str) -> bool:
        if len(self.used) >= self.limit:
            self.refused.append(name)
            return False
        self.used.append(name)
        return True


@dataclass(frozen=True)
class LeagueTarget:
    league_key: str
    sleeper_league_id: str
    roster_settings: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class Clients:
    """Every external call the collector makes — injectable for tests."""

    nfl_state: Callable[[], Mapping[str, Any] | None]
    league: Callable[[str], Mapping[str, Any] | None]
    users: Callable[[str], list]
    rosters: Callable[[str], list]
    matchups: Callable[[str, int], list]
    nfl_players: Callable[[], Mapping[str, Any]]
    scoreboard: Callable[[int, int], Any]
    live_stats: Callable[[int, int], Any]
    weekly: Callable[[int, int], Any]
    schedule: Callable[[int], tuple]
    preseason: Callable[[int, Mapping[str, Any]], tuple]
    leagues: Callable[[], list[LeagueTarget]]
    #: Live-game-state FALLBACK provider (SportsDataIO), read only when the
    #: ESPN scoreboard did not produce a fresh observation this tick.
    fallback_scoreboard: Callable[[int, int], Any] | None = None
    #: ``(last_healthy: bool | None) -> capability`` with ``.eligible``,
    #: ``.available``, ``.health_state`` and ``.reasons`` — checked BEFORE
    #: any fallback request, so an absent key or an off flag costs nothing.
    fallback_capability: Callable[[bool | None], Any] | None = None


def default_clients() -> Clients:
    from src.api import league_registry
    from src.api import matchup_intel as mi
    from src.nfl_data import sportsdataio_live_game_state as sdio
    from src.nfl_data.live_game_state import PROVIDER_SPORTSDATAIO, fetch_live_game_state
    from src.nfl_data.sleeper_live_stats import fetch_live_week_stats
    from src.public_league import sleeper_client
    from src.ros.sleeper_weekly_projections import fetch_weekly_projection_rows

    def _leagues() -> list[LeagueTarget]:
        out = []
        for cfg in league_registry.active_leagues():
            sid = str(getattr(cfg, "sleeper_league_id", "") or "").strip()
            if not sid:
                continue
            try:
                settings = league_registry.get_league_roster_settings(cfg.key) or {}
            except Exception:  # noqa: BLE001 — optional, same as the route
                settings = {}
            out.append(LeagueTarget(cfg.key, sid, dict(settings)))
        return out

    return Clients(
        nfl_state=sleeper_client.fetch_nfl_state,
        league=sleeper_client.fetch_league,
        users=sleeper_client.fetch_users,
        rosters=sleeper_client.fetch_rosters,
        matchups=sleeper_client.fetch_matchups,
        nfl_players=sleeper_client.fetch_nfl_players,
        scoreboard=lambda season, week: fetch_live_game_state(week=int(week), season_type=2),
        live_stats=lambda season, week: fetch_live_week_stats(int(season), int(week)),
        weekly=lambda season, week: fetch_weekly_projection_rows(int(season), int(week)),
        schedule=mi._schedule_context,
        preseason=mi._resolve_estimates,
        leagues=_leagues,
        fallback_scoreboard=lambda season, week: fetch_live_game_state(
            provider=PROVIDER_SPORTSDATAIO, season=int(season), week=int(week), season_type=2
        ),
        fallback_capability=lambda last_healthy: sdio.capability(last_healthy=last_healthy),
    )


@dataclass
class TickReport:
    outcome: str  # "ran" | "not_due" | "locked" | "out_of_season" | "no_week" | "error"
    exit_code: int
    season: int | None = None
    week: int | None = None
    cadence: dict[str, Any] | None = None
    leagues: dict[str, dict[str, Any]] = field(default_factory=dict)
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    requests: list[str] = field(default_factory=list)
    requests_refused: list[str] = field(default_factory=list)
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_collector_state() -> dict[str, Any]:
    state = _read_json(collector_state_path())
    return state if isinstance(state, dict) else {}


def tick_due(now: float, state: Mapping[str, Any] | None = None) -> bool:
    """Cheap pre-check the script runs before importing anything heavy."""
    state = load_collector_state() if state is None else state
    due = _epoch(state.get("nextDueAt"))
    return due is None or now >= due - 5.0


def _source_backoff(health: Mapping[str, Any], name: str, now: float) -> float | None:
    until = _epoch((health.get(name) or {}).get("backoffUntil"))
    return until if until is not None and until > now else None


def _record_health(
    health: dict[str, Any], name: str, ok: bool, now: float, error: str | None = None
) -> None:
    entry = dict(health.get(name) or {})
    if ok:
        entry.update(consecutiveFailures=0, backoffUntil=None, lastOkAt=_iso(now), lastError=None)
    else:
        n = _counter(entry.get("consecutiveFailures")) + 1
        entry.update(consecutiveFailures=n, lastError=error, lastFailureAt=_iso(now))
        if n >= BACKOFF_FAILURE_THRESHOLD:
            wait = min(60.0 * 2 ** (n - BACKOFF_FAILURE_THRESHOLD), BACKOFF_MAX_SECONDS)
            entry["backoffUntil"] = _iso(now + wait)
    health[name] = entry


def _log_tick(report: TickReport) -> None:
    path = _collector_dir() / "ticks.jsonl"
    _append_line(path, report.to_dict())
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) > TICK_LOG_MAX_LINES:
        path.write_text(
            "\n".join(lines[-TICK_LOG_MAX_LINES // 2 :]) + "\n", encoding="utf-8", newline="\n"
        )


def prune_retention(season: int, week: int) -> list[str]:
    """Delete raw observation logs older than :data:`RAW_RETENTION_WEEKS`.

    Keeps ``generation.json``, ``generations.jsonl`` and ``state.json`` for
    every league-week (the week's final answer and its calibration index).
    """
    import shutil

    removed = []
    if not LIVE_ROOT.is_dir():
        return removed
    for key_dir in LIVE_ROOT.iterdir():
        if not key_dir.is_dir() or key_dir.name == _COLLECTOR_DIR:
            continue
        for season_dir in key_dir.iterdir():
            if not season_dir.is_dir() or not season_dir.name.isdigit():
                continue
            s = int(season_dir.name)
            for week_dir in season_dir.iterdir():
                name = week_dir.name
                if not (week_dir.is_dir() and name.startswith("week_") and name[5:].isdigit()):
                    continue
                w = int(name[5:])
                old = s < season or (s == season and w < week - RAW_RETENTION_WEEKS)
                obs = week_dir / "observations"
                if old and obs.is_dir():
                    shutil.rmtree(obs, ignore_errors=True)
                    removed.append(str(obs))
    return removed


def run_tick(
    *,
    clients: Clients | None = None,
    clock: Callable[[], float] = time.time,
    force: bool = False,
    draws: int | None = None,
    seed: int | None = None,
) -> TickReport:
    """One bounded collector tick.  Never raises; see :class:`TickReport`.

    Exit codes (the script's): 0 ran with every league ok, 1 at least one
    league (or the tick) failed, 2 nothing to do (not due, locked by a
    running tick, out of season, no week).
    """
    from src.api import matchup_intel as mi

    draws = mi.DEFAULT_DRAWS if draws is None else int(draws)
    seed = mi.DEFAULT_SEED if seed is None else int(seed)
    start = clock()
    report = TickReport(outcome="ran", exit_code=0, started_at=_iso(start))
    gstate = load_collector_state()
    if not force and not tick_due(start, gstate):
        report.outcome, report.exit_code = "not_due", 2
        return report
    if not _acquire_lock(start):
        report.outcome, report.exit_code = "locked", 2
        return report
    try:
        clients = clients or default_clients()
        _run_tick_locked(clients, clock, report, gstate, draws=draws, seed=seed)
    except Exception as exc:  # noqa: BLE001 — a tick reports, it never crashes the timer
        report.outcome, report.exit_code = "error", 1
        report.error = f"{type(exc).__name__}: {exc}"
    finally:
        report.finished_at = _iso(clock())
        try:
            _log_tick(report)
        finally:
            _release_lock()
    return report


def _run_tick_locked(
    clients: Clients,
    clock: Callable[[], float],
    report: TickReport,
    gstate: dict[str, Any],
    *,
    draws: int,
    seed: int,
) -> None:
    from src.api import matchup_intel as mi

    budget = RequestBudget()
    health: dict[str, Any] = dict(gstate.get("sourceHealth") or {})
    tick_start = clock()

    def _finish(outcome: str, code: int, next_due: float, cadence: dict | None = None) -> None:
        report.outcome, report.exit_code = outcome, code
        report.requests, report.requests_refused = budget.used, budget.refused
        gstate.update(
            nextDueAt=_iso(next_due),
            lastTickAt=_iso(tick_start),
            lastOutcome=outcome,
            sourceHealth=health,
            cadence=cadence,
        )
        _atomic_write_json(collector_state_path(), gstate)

    budget.take("sleeper_nfl_state")
    nfl = clients.nfl_state() or {}
    season_type = str(nfl.get("season_type") or "")
    try:
        season, week = int(nfl.get("season")), int(nfl.get("week"))
    except (TypeError, ValueError):
        _finish("no_week", 2, tick_start + CADENCE_IDLE_SECONDS)
        return
    report.season, report.week = season, week
    if season_type != "regular" or week < 1:
        _finish("out_of_season", 2, tick_start + 6 * CADENCE_IDLE_SECONDS)
        return

    # ── NFL-wide sources ──
    snapshot, live_sources = collect_live_game_state(
        clients, health, budget, season=season, week=week, now=tick_start
    )
    espn_source = live_sources["espnScoreboard"]
    report.sources[SOURCE_ESPN] = espn_source
    report.sources[SOURCE_SDIO] = live_sources["sportsDataIoScores"]
    report.sources[SOURCE_LIVE_SELECTION] = live_sources["liveGameState"]

    schedule_rows, schedule_observed_at, _ = clients.schedule(season)
    evidence = observed_evidence(schedule_rows, snapshot, season=season, week=week, now=clock())
    windows = windows_from_evidence(evidence)
    final_first_seen = _record_finals(gstate, windows, season=season, week=week, now=tick_start)

    stats_log = observation_log(NFL_KEY, season, week, SOURCE_LIVE_STATS)
    stats_head = stats_log.head() or {}
    due, why = live_stats_due(_epoch(stats_head.get("lastOkFetchedAt")), windows, clock())
    stats_source: dict[str, Any] = {"status": "not_due", "reason": why}
    stat_changes: dict[str, dict[str, Any]] = {}
    if due and _source_backoff(health, SOURCE_LIVE_STATS, clock()) is None:
        if budget.take(SOURCE_LIVE_STATS):
            live = clients.live_stats(season, week)
            status, meta, content = live_stats_to_observation(live)
            info = stats_log.append(
                fetched_at=meta["observedAt"], status=status, meta=meta, content=content
            )
            _record_health(health, SOURCE_LIVE_STATS, status == "ok", clock(), meta.get("error"))
            if status == "ok" and stats_head.get("content") is not None:
                stat_changes = raw_stat_changes(stats_head.get("content"), content)
            stats_source = {
                "source": "sleeper:stats (v1)",
                "status": status,
                "error": meta.get("error"),
                "fetchedAt": meta["observedAt"],
                "observedAt": meta["observedAt"],
                "observedAtBasis": "fetch_time",
                "linesChanged": info["changedKeys"],
                "linesDropped": info["droppedKeys"],
                "consumedByScoring": False,
            }
        else:
            stats_source = {"status": "budget_exhausted"}
    report.sources[SOURCE_LIVE_STATS] = stats_source

    weekly_log = observation_log(NFL_KEY, season, week, SOURCE_WEEKLY)
    weekly_head = weekly_log.head() or {}
    due, why = weekly_projection_due(_epoch(weekly_head.get("lastOkFetchedAt")), windows, clock())
    weekly_source: dict[str, Any] = {"status": "not_due", "reason": why}
    weekly_disabled_reason: str | None = None
    if due and _source_backoff(health, SOURCE_WEEKLY, clock()) is None:
        if budget.take(SOURCE_WEEKLY):
            result = clients.weekly(season, week)
            status, meta, content = weekly_to_observation(result)
            if status == "feature_disabled":
                weekly_disabled_reason = result.reason
            else:
                weekly_log.append(
                    fetched_at=meta.get("observedAt") or _iso(clock()),
                    status=status,
                    meta=meta,
                    content=content,
                )
                _record_health(health, SOURCE_WEEKLY, status == "ok", clock(), meta.get("reason"))
            weekly_source = {"status": status, "reason": why, "fetchedAt": meta.get("observedAt")}
        else:
            weekly_source = {"status": "budget_exhausted"}
    report.sources[SOURCE_WEEKLY] = weekly_source

    weekly_history = load_weekly_history(season, week)
    kickoffs = sorted({w.kickoff_at for w in windows if w.kickoff_at is not None})
    weekly_history = mi._prune_weekly_history(weekly_history, kickoffs) if weekly_history else []
    if weekly_disabled_reason is not None and not weekly_history:
        weekly_fetches, weekly_state, weekly_reason = (), "feature_disabled", weekly_disabled_reason
    elif weekly_history:
        weekly_fetches, weekly_state, weekly_reason = tuple(weekly_history), "ok", None
    else:
        weekly_fetches, weekly_state, weekly_reason = (
            (),
            "no_usable_fetch",
            "no weekly projection observation stored for this week",
        )
    coverage = pre_kickoff_coverage(windows, [f.observed_at for f in weekly_history])

    # ── Leagues ──
    targets = clients.leagues()
    fetched_by_league: dict[str, Any] = {}
    rostered: set[str] = set()
    for target in targets:
        lstate = load_league_state(target.league_key, season, week)
        lstate["refreshStartedAt"] = _iso(clock())
        _save_league_state(target.league_key, season, week, lstate)
        try:
            fetched = _fetch_league(clients, target, week, budget, clock)
        except Exception as exc:  # noqa: BLE001 — one league must not sink the tick
            fetched = exc
        fetched_by_league[target.league_key] = fetched
        if not isinstance(fetched, Exception):
            rostered |= {
                str(pid) for r in fetched.rosters for pid in (r.get("players") or ()) if pid
            }
    players, players_stamp = load_players_meta(
        clients.nfl_players, rostered, now=clock(), budget=budget
    )
    report.sources["sleeper_players_db"] = players_stamp
    post_final, unattributable = attribute_post_final_changes(
        stat_changes,
        players_meta=players,
        evidence=evidence,
        final_first_seen=final_first_seen,
        previous_fetched_at=_epoch(stats_head.get("lastOkFetchedAt")),
        detected_at=tick_start,
    )
    if stat_changes:
        stats_source["postFinalChanges"] = len(post_final)
        stats_source["unattributableChanges"] = len(unattributable)

    preseason_cache: dict[str, tuple] = {}
    any_failed = False
    for target in targets:
        key = target.league_key
        lstate = load_league_state(key, season, week)
        result = _process_league(
            mi,
            target,
            season=season,
            week=week,
            fetched=fetched_by_league.get(key),
            players=players,
            clients=clients,
            clock=clock,
            snapshot=snapshot,
            live_sources=live_sources,
            schedule_rows=schedule_rows,
            schedule_observed_at=schedule_observed_at,
            weekly=(weekly_fetches, weekly_state, weekly_reason),
            preseason_cache=preseason_cache,
            coverage=coverage,
            live_stats_source=stats_source,
            lstate=lstate,
            tick_start=tick_start,
            draws=draws,
            seed=seed,
            health=health,
            post_final=post_final,
        )
        report.leagues[key] = result
        any_failed = any_failed or not result.get("ok")

    # From the tick's START: a tick that spent 25 s simulating must still be
    # due at the next minute's firing, not skipped until the one after.
    cadence = decide_cadence(windows, tick_start)
    for target in targets:
        lstate = load_league_state(target.league_key, season, week)
        lstate["cadence"] = cadence.to_dict()
        _save_league_state(target.league_key, season, week, lstate)
    report.cadence = cadence.to_dict()
    try:
        prune_retention(season, week)
    except Exception:  # noqa: BLE001 — housekeeping never fails a tick
        pass
    _finish("ran", 1 if any_failed else 0, cadence.next_due_at, cadence.to_dict())


def _last_healthy(health: Mapping[str, Any], name: str) -> bool | None:
    entry = health.get(name) or {}
    if _counter(entry.get("consecutiveFailures")) > 0:
        return False
    return True if entry.get("lastOkAt") else None


def _stale_candidate(log: KeyedObservationLog) -> tuple[float, Any] | None:
    head = log.head()
    if not head or head.get("content") is None or not head.get("lastOkMeta"):
        return None
    stamp = _epoch(head["lastOkMeta"].get("observedAt"))
    # An unknown observation time ranks below every known one (never as
    # "newest"), but the observation itself stays usable as a last resort.
    rank = stamp if stamp is not None else float("-inf")
    return rank, scoreboard_from_observation(head["lastOkMeta"], head["content"])


def last_good_live_snapshot(season: int, week: int) -> Any:
    """The newest persisted good live-game-state observation for the week
    (any provider), at its true as-of; ``None`` when none is stored.  Disk
    only — the pending request path reads this instead of the network."""
    candidates = []
    for source in (SOURCE_ESPN, SOURCE_SDIO):
        found = _stale_candidate(observation_log(NFL_KEY, season, week, source))
        if found is not None:
            candidates.append(found)
    if not candidates:
        return None
    return max(candidates, key=lambda c: c[0])[1]


def collect_live_game_state(
    clients: Clients,
    health: dict[str, Any],
    budget: RequestBudget,
    *,
    season: int,
    week: int,
    now: float,
) -> tuple[Any, dict[str, dict[str, Any]]]:
    """``(snapshot, stamps)`` — this tick's ONE live-game-state observation.

    Order, each step reached only when the previous produced no fresh
    observation:

    1. **ESPN** (primary; free, no quota) unless in persisted backoff.
    2. **SportsDataIO** (fallback) when ESPN failed or is backing off AND the
       provider is eligible — both flags on and ``SPORTSDATAIO_API_KEY``
       present, checked without a request — AND it is not itself backing off.
    3. **Last good** observation of whichever provider has the NEWER one, at
       its true as-of (the resolver marks it stale past
       ``LIVE_STATE_MAX_AGE_SECONDS``, so it never passes as fresh).

    One provider's snapshot is returned whole; two providers' states are
    never merged for a game.  ``stamps`` has ``liveGameState`` (the chosen
    provider, ``status`` and ``selectionReason``), ``espnScoreboard`` and
    ``sportsDataIoScores`` (each provider's own attempt).  With the Game Day
    master flag off ESPN answers ``disabled`` and no fallback is tried — the
    master switch gates every provider.
    """
    from src.nfl_data.live_game_state import PROVIDER_SOURCE_LABELS

    sdio_label = PROVIDER_SOURCE_LABELS["sportsdataio"]
    espn_log = observation_log(NFL_KEY, season, week, SOURCE_ESPN)
    sdio_log = observation_log(NFL_KEY, season, week, SOURCE_SDIO)

    espn_fresh = None
    if _source_backoff(health, SOURCE_ESPN, now) is not None:
        espn_source: dict[str, Any] = {
            "source": "espn:scoreboard",
            "provider": "espn",
            "status": "skipped_backoff",
        }
    elif not budget.take(SOURCE_ESPN):
        espn_source = {
            "source": "espn:scoreboard",
            "provider": "espn",
            "status": "budget_exhausted",
        }
    else:
        espn_fresh = clients.scoreboard(season, week)
        status, meta, content = scoreboard_to_observation(espn_fresh)
        espn_log.append(fetched_at=meta["observedAt"], status=status, meta=meta, content=content)
        if status == "ok":
            _record_health(health, SOURCE_ESPN, True, now)
        elif status != "disabled":
            _record_health(health, SOURCE_ESPN, False, now, meta.get("error"))
        espn_source = _live_state_stamp(espn_fresh)

    def _chosen(stamp: Mapping[str, Any], status: str, reason: str) -> dict:
        return {**dict(stamp), "status": status, "selectionReason": reason}

    if espn_fresh is not None and espn_fresh.enabled and espn_fresh.ok:
        sdio_source = {"source": sdio_label, "provider": "sportsdataio", "status": "not_needed"}
        return espn_fresh, {
            "liveGameState": _chosen(espn_source, "ok", "primary_ok"),
            "espnScoreboard": espn_source,
            "sportsDataIoScores": sdio_source,
        }
    if espn_fresh is not None and not espn_fresh.enabled:
        sdio_source = {
            "source": sdio_label,
            "provider": "sportsdataio",
            "status": "disabled",
            "reason": "game_day_live_game_state master flag is off",
        }
        return espn_fresh, {
            "liveGameState": _chosen(espn_source, "disabled", "master_flag_off"),
            "espnScoreboard": espn_source,
            "sportsDataIoScores": sdio_source,
        }
    espn_reason = (espn_fresh.error if espn_fresh is not None else None) or espn_source["status"]

    # ── fallback: SportsDataIO ──
    sdio_fresh = None
    sdio_source = {"source": sdio_label, "provider": "sportsdataio"}
    cap = (
        clients.fallback_capability(_last_healthy(health, SOURCE_SDIO))
        if clients.fallback_capability is not None
        else None
    )
    if cap is not None:
        sdio_source["capability"] = {
            "eligible": bool(cap.eligible),
            "available": bool(cap.available),
            "healthState": cap.health_state,
            "reasons": list(cap.reasons),
        }
    if clients.fallback_scoreboard is None:
        sdio_source["status"] = "not_configured"
    elif cap is not None and not cap.eligible:
        sdio_source.update(status="unavailable", reasons=list(cap.reasons))
    elif _source_backoff(health, SOURCE_SDIO, now) is not None:
        sdio_source["status"] = "skipped_backoff"
    elif not budget.take(SOURCE_SDIO):
        sdio_source["status"] = "budget_exhausted"
    else:
        sdio_fresh = clients.fallback_scoreboard(season, week)
        status, meta, content = scoreboard_to_observation(sdio_fresh)
        sdio_log.append(fetched_at=meta["observedAt"], status=status, meta=meta, content=content)
        error = str(meta.get("error") or "")
        if status == "ok":
            _record_health(health, SOURCE_SDIO, True, now)
        elif status != "disabled" and not error.startswith("credential_missing"):
            _record_health(health, SOURCE_SDIO, False, now, error)
        stamp = _live_state_stamp(sdio_fresh)
        if "capability" in sdio_source:
            stamp["capability"] = sdio_source["capability"]
        sdio_source = stamp
    if sdio_fresh is not None and sdio_fresh.enabled and sdio_fresh.ok:
        return sdio_fresh, {
            "liveGameState": _chosen(sdio_source, "ok", f"espn_unavailable:{espn_reason}"),
            "espnScoreboard": espn_source,
            "sportsDataIoScores": sdio_source,
        }
    sdio_reason = (
        (sdio_fresh.error if sdio_fresh is not None else None)
        or ",".join(sdio_source.get("reasons") or ())
        or sdio_source.get("status")
    )
    why = f"no_fresh_provider:espn={espn_reason};sportsdataio={sdio_reason}"

    # ── last good, newest across providers ──
    candidates = []
    for provider, log in (("espn", espn_log), ("sportsdataio", sdio_log)):
        found = _stale_candidate(log)
        if found is not None:
            candidates.append((found[0], provider, found[1]))
    if candidates:
        _, provider, stale = max(candidates, key=lambda c: c[0])
        stamp = {**_live_state_stamp(stale), "status": "stale_last_good"}
        if provider == "espn":
            espn_source = {**stamp, "lastAttempt": espn_source}
        else:
            sdio_source = {**stamp, "lastAttempt": sdio_source}
        return stale, {
            "liveGameState": _chosen(stamp, "stale_last_good", why),
            "espnScoreboard": espn_source,
            "sportsDataIoScores": sdio_source,
        }
    failed = espn_fresh if espn_fresh is not None else sdio_fresh
    unavailable = {
        **(_live_state_stamp(failed) if failed is not None else {}),
        "source": "none",
        "provider": None,
        "status": "unavailable",
        "selectionReason": why,
    }
    return failed, {
        "liveGameState": unavailable,
        "espnScoreboard": espn_source,
        "sportsDataIoScores": sdio_source,
    }


def pre_kickoff_coverage(
    windows: Sequence[GameWindow], fetch_times: Sequence[str | None]
) -> dict[str, Any]:
    """Per game: the last weekly projection fetch at or before its kickoff."""
    stamps = sorted(t for t in (_epoch(f) for f in fetch_times) if t is not None)
    games = {}
    missing = []
    for w in windows:
        if w.kickoff_at is None:
            continue
        before = [t for t in stamps if t <= w.kickoff_at]
        last = before[-1] if before else None
        games[w.game_id] = {
            "kickoffAt": _iso(w.kickoff_at),
            "lastPreKickoffFetchAt": _iso(last),
            "leadSeconds": round(w.kickoff_at - last, 1) if last is not None else None,
        }
        if last is None:
            missing.append(w.game_id)
    return {"games": games, "gamesWithoutPreKickoffObservation": sorted(missing)}


def _fetch_league(
    clients: Clients,
    target: LeagueTarget,
    week: int,
    budget: RequestBudget,
    clock: Callable[[], float],
) -> Any:
    from src.api import matchup_intel as mi

    sid = target.sleeper_league_id
    for name in ("league", "users", "rosters", "matchups"):
        if not budget.take(f"sleeper_{name}:{target.league_key}"):
            raise RuntimeError("request budget exhausted before this league")
    league = clients.league(sid) or {}
    users = list(clients.users(sid) or [])
    rosters = list(clients.rosters(sid) or [])
    matchups = list(clients.matchups(sid, week) or [])
    return mi._LeagueFetch(
        league=dict(league),
        users=users,
        rosters=rosters,
        matchups=matchups,
        players={},
        fetched_at=clock(),
    )


def _process_league(
    mi: Any,
    target: LeagueTarget,
    *,
    season: int,
    week: int,
    fetched: Any,
    players: Mapping[str, Any],
    clients: Clients,
    clock: Callable[[], float],
    snapshot: Any,
    live_sources: Mapping[str, Mapping[str, Any]],
    schedule_rows: list,
    schedule_observed_at: float | None,
    weekly: tuple,
    preseason_cache: dict[str, tuple],
    coverage: Mapping[str, Any],
    live_stats_source: Mapping[str, Any],
    lstate: dict[str, Any],
    tick_start: float,
    draws: int,
    seed: int,
    health: dict[str, Any],
    post_final: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble one league-week; publish a generation only if inputs changed."""
    from dataclasses import replace

    key = target.league_key
    timings: dict[str, float] = {}
    out: dict[str, Any] = {"ok": False}
    health_name = f"{SOURCE_LEAGUE}:{key}"
    try:
        if isinstance(fetched, Exception) or fetched is None:
            raise RuntimeError(f"league fetch failed: {fetched}")
        if not players:
            # Without player metadata every position is unknown and every
            # player ineligible — refuse rather than publish that.
            raise RuntimeError("Sleeper players metadata unavailable")
        fetched = replace(fetched, players=players)
        log = observation_log(key, season, week, SOURCE_LEAGUE)
        previous_content = (log.head() or {}).get("content")
        status = "ok" if fetched.rosters else "error"
        log.append(
            fetched_at=_iso(fetched.fetched_at),
            status=status,
            meta={"sleeperLeagueId": target.sleeper_league_id, "week": week},
            content=league_fetch_to_content(fetched) if status == "ok" else None,
        )
        _record_health(
            health, health_name, status == "ok", clock(), None if fetched.rosters else "no rosters"
        )
        # The raw league record this tick's answer is built from (append-only;
        # the host's as-known player points stay retrievable by this seq).
        league_seq = (log.head() or {}).get("seq")
        try:
            lstate["statCorrections"] = update_stat_corrections(
                lstate.get("statCorrections"),
                post_final or {},
                previous_matchups=_matchups_from_content(previous_content),
                matchups=fetched.matchups,
                scoring_card=fetched.league.get("scoring_settings") or {},
                now=tick_start,
            )
            lstate.pop("statCorrectionsError", None)
        except Exception as exc:  # noqa: BLE001 — a diagnostic never sinks the league
            lstate["statCorrectionsError"] = f"{type(exc).__name__}: {exc}"

        scoring_card = fetched.league.get("scoring_settings") or {}
        card_key = _content_hash(scoring_card)
        if card_key not in preseason_cache:
            preseason_cache[card_key] = clients.preseason(season, scoring_card)
        weekly_fetches, weekly_state, weekly_reason = weekly
        t0 = clock()
        inputs = mi.LiveInputs(
            fetched=fetched,
            schedule_rows=schedule_rows,
            schedule_observed_at=schedule_observed_at,
            now=clock(),
            live_snapshot=snapshot,
            weekly_fetches=tuple(weekly_fetches),
            weekly_state=weekly_state,
            weekly_reason=weekly_reason,
            preseason=preseason_cache[card_key],
        )
        assembly = mi.assemble_league_week(
            inputs,
            league_key=key,
            season=season,
            week=week,
            roster_settings=target.roster_settings,
        )
        fp = input_fingerprint(assembly, draws=draws, seed=seed)
        timings["assembleSeconds"] = round(clock() - t0, 3)
        current = load_generation(key, season, week)
        lstate["latestInputFingerprint"] = fp
        if (
            current is not None
            and current.get("inputFingerprint") == fp
            and current.get("draws") == draws
            and current.get("seed") == seed
            # A background request-path generation is republished under the
            # collector's own name (the simulation cache makes it cheap).
            and (current.get("producer") or PRODUCER) == PRODUCER
        ):
            out.update(ok=True, outcome="inputs_unchanged", generationId=current["generationId"])
            lstate.update(
                generationId=current["generationId"],
                generationFingerprint=fp,
                lastVerifiedAt=_iso(tick_start),
            )
        else:
            t1 = clock()
            mi.run_league_simulation(assembly, draws=draws, seed=seed)
            timings["simulateSeconds"] = round(clock() - t1, 3)
            t2 = clock()
            render = mi.render_league(assembly)
            sources = source_stamps(inputs, render.get("lineage") or {})
            for name, stamp in (live_sources or {}).items():
                if stamp:
                    sources[name] = dict(stamp)
            sources["sleeperLiveStats"] = dict(live_stats_source)
            timings["renderSeconds"] = round(clock() - t2, 3)
            computed_at = clock()
            generation = build_generation(
                assembly=assembly,
                render=render,
                fingerprint=fp,
                sources=sources,
                inputs_fetched_at=tick_start,
                computed_at=computed_at,
                compute_seconds=computed_at - t0,
                draws=draws,
                seed=seed,
                extra_inputs={
                    "preKickoffCoverage": dict(coverage),
                    "leagueObservationSeq": league_seq,
                },
            )
            t3 = clock()
            written = write_generation(generation)
            timings["writeSeconds"] = round(clock() - t3, 3)
            timings["sourceToGenerationSeconds"] = round(clock() - tick_start, 3)
            if written:
                out.update(
                    ok=True, outcome="generation_written", generationId=generation["generationId"]
                )
                lstate.update(
                    generationId=generation["generationId"],
                    generationFingerprint=fp,
                    lastVerifiedAt=_iso(tick_start),
                )
            else:
                out.update(ok=True, outcome="superseded_by_newer_generation")
            if assembly.sim_error:
                out["simulationError"] = assembly.sim_error
        lstate.update(lastTickOk=True, lastError=None)
    except Exception as exc:  # noqa: BLE001 — recorded, and the previous generation stays served
        out.update(ok=False, outcome="error", error=f"{type(exc).__name__}: {exc}")
        lstate.update(lastTickOk=False, lastError=out["error"])
    lstate.update(
        leagueKey=key,
        season=season,
        week=week,
        lastTickStartedAt=_iso(tick_start),
        lastTickFinishedAt=_iso(clock()),
        lastTickOutcome=out.get("outcome"),
        refreshStartedAt=None,
        timings=timings,
        preKickoffCoverage=dict(coverage),
    )
    _save_league_state(key, season, week, lstate)
    out["timings"] = timings
    return out
