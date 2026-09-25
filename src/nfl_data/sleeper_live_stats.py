"""Live weekly stat lines from Sleeper — read-only Game Day adapter.

Source
------
``GET https://api.sleeper.app/v1/stats/nfl/regular/<season>/<week>``,
fetched through :func:`src.league_comparison.sleeper_stats.fetch_week_stats_response`,
which is the ONE owner of that HTTP call.  This module owns only what the
historical path does not need: an UNCACHED read with bounded timeout,
per-line parsing into :class:`StatLine`, fetch metadata, and stat-correction
detection between two observations.

What the v1 payload does and does NOT carry (measured 2026-09-25 on a
week-3 capture taken during the Thursday game): a JSON object keyed by
Sleeper ``player_id`` whose values are ``{stat_key: number}``.  It carries
**no** ``updated_at``, **no** ``game_id`` and **no** ``team`` per row, so
those :class:`StatLine` fields are ``None`` on this shape — unknown, never
defaulted.  The same object also carries TEAM entries under two spellings
(``GB`` and ``TEAM_GB``); they are kept apart from player lines using
:func:`src.nfl_data.realized_points.is_host_player_entry`, the existing
owner of the player-vs-team distinction.

The parser also accepts the row-list shape Sleeper uses on its other
stats/projections surfaces (``[{"player_id", "stats", "updated_at",
"game_id", "team", ...}]``) and reads those fields when present.  That
shape is NOT fetched here; it is accepted so a provider shape change
degrades into more metadata rather than an empty board.

Invariants
----------
* **Missing is not zero.**  A player absent from the payload has no
  :class:`StatLine` — :meth:`LiveStatsSnapshot.line` returns ``None``.  A
  player present with an empty stat object is a different, real state
  (listed, nothing recorded yet) and is kept as an empty ``stats`` dict.
* **Never raises** on network, HTTP, JSON or row errors.  A malformed row
  is skipped and counted; a non-numeric stat value is dropped and counted.
* **No scoring here.**  ``stats`` stays in Sleeper's own stat keys so the
  exact league scorer, :mod:`src.league_intel.scorer`, can price it
  against the league's real scoring card.  This module never computes
  points and never trusts Sleeper's generic ``pts_*`` fields as a league
  score (they are kept as ordinary stat keys only).
* **Not wired.**  No endpoint consumes this yet; cadence, caching and
  budget belong to the future shared background collector.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.league_comparison.sleeper_stats import fetch_week_stats_response
from src.nfl_data.realized_points import is_host_player_entry

_LOGGER = logging.getLogger(__name__)

#: Bounded per-request timeout for the live read.  Shorter than the
#: historical path's 15 s: a live poll that cannot answer quickly should
#: yield a degraded observation, not block the collector.
LIVE_TIMEOUT_SEC = 8.0

#: ``payload_shape`` values.
SHAPE_PLAYER_MAP = "player_map"
SHAPE_ROW_LIST = "row_list"
SHAPE_UNRECOGNIZED = "unrecognized"
SHAPE_MISSING = "missing"


@dataclass(frozen=True)
class StatLine:
    """One entry's accumulated stat line for the week.

    ``stats`` uses Sleeper stat keys verbatim (``pass_yd``, ``idp_tkl_solo``,
    ``xpm`` …), numeric values only.  ``updated_at`` / ``game_id`` /
    ``team`` are ``None`` when the payload did not state them.
    """

    player_id: str
    stats: Mapping[str, float]
    updated_at: datetime | None = None
    game_id: str | None = None
    team: str | None = None
    is_team_entry: bool = False


@dataclass(frozen=True)
class LiveStatsSnapshot:
    """One observation of the weekly stat dump plus how it was obtained."""

    season: int
    week: int
    observed_at: datetime
    source_url: str | None
    http_status: int | None
    error: str | None
    payload_shape: str
    #: Individual players, keyed by Sleeper player_id.
    lines: Mapping[str, StatLine] = field(default_factory=dict)
    #: Team (DST / team-total) entries, kept apart from players.
    team_lines: Mapping[str, StatLine] = field(default_factory=dict)
    #: Entries present in the raw payload, before any skipping.
    row_count: int = 0
    #: Entries skipped as malformed (non-object value, no id, …).
    skipped_rows: int = 0
    #: Individual stat values dropped as non-numeric.
    skipped_values: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None

    def line(self, player_id: str) -> StatLine | None:
        """The player's line, or ``None`` when the feed does not list him.

        ``None`` means UNKNOWN / not reported — never zero production.
        """
        return self.lines.get(str(player_id))


def _parse_updated_at(raw: Any) -> datetime | None:
    """Sleeper stamps ``updated_at`` as epoch MILLISECONDS on its row shape."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        seconds = raw / 1000.0 if raw > 1e11 else float(raw)
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(raw, str) and raw.strip():
        text = raw.strip()
        if text.isdigit():
            return _parse_updated_at(int(text))
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _numeric_stats(raw: Mapping[str, Any]) -> tuple[dict[str, float], int]:
    stats: dict[str, float] = {}
    dropped = 0
    for key, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            dropped += 1
            continue
        stats[str(key)] = float(value)
    return stats, dropped


def _opt_str(raw: Any) -> str | None:
    if raw is None or isinstance(raw, bool):
        return None
    text = str(raw).strip()
    return text or None


def parse_week_stats(
    payload: Any,
    *,
    season: int,
    week: int,
    observed_at: datetime,
    source_url: str | None = None,
    http_status: int | None = None,
    error: str | None = None,
) -> LiveStatsSnapshot:
    """Parse a weekly stat payload (either Sleeper shape) without raising."""
    lines: dict[str, StatLine] = {}
    team_lines: dict[str, StatLine] = {}
    skipped_rows = 0
    skipped_values = 0

    entries: Iterable[tuple[Any, Any, Mapping[str, Any]]]
    if payload is None:
        shape = SHAPE_MISSING
        entries = ()
    elif isinstance(payload, Mapping):
        shape = SHAPE_PLAYER_MAP
        entries = [(pid, value, {}) for pid, value in payload.items()]
    elif isinstance(payload, list):
        shape = SHAPE_ROW_LIST
        collected: list[tuple[Any, Any, Mapping[str, Any]]] = []
        for row in payload:
            if isinstance(row, Mapping):
                collected.append((row.get("player_id"), row.get("stats"), row))
            else:
                collected.append((None, None, {}))
        entries = collected
    else:
        shape = SHAPE_UNRECOGNIZED
        entries = ()

    row_count = 0
    for pid_raw, stats_raw, row in entries:
        row_count += 1
        pid = _opt_str(pid_raw)
        if pid is None or not isinstance(stats_raw, Mapping):
            skipped_rows += 1
            continue
        stats, dropped = _numeric_stats(stats_raw)
        skipped_values += dropped
        team = _opt_str(row.get("team"))
        is_team = not is_host_player_entry(pid)
        line = StatLine(
            player_id=pid,
            stats=stats,
            updated_at=_parse_updated_at(row.get("updated_at")),
            game_id=_opt_str(row.get("game_id")),
            team=team.upper() if team else None,
            is_team_entry=is_team,
        )
        (team_lines if is_team else lines)[pid] = line

    if shape == SHAPE_UNRECOGNIZED and error is None:
        error = "unrecognized_payload_shape"
    if shape == SHAPE_MISSING and error is None:
        error = "missing_payload"

    return LiveStatsSnapshot(
        season=int(season),
        week=int(week),
        observed_at=observed_at,
        source_url=source_url,
        http_status=http_status,
        error=error,
        payload_shape=shape,
        lines=lines,
        team_lines=team_lines,
        row_count=row_count,
        skipped_rows=skipped_rows,
        skipped_values=skipped_values,
    )


def fetch_live_week_stats(
    season: int,
    week: int,
    *,
    fetcher: Callable[[str], Any] | None = None,
    timeout: float = LIVE_TIMEOUT_SEC,
    now: Callable[[], datetime] | None = None,
) -> LiveStatsSnapshot:
    """One uncached observation of the week's stat dump.  Never raises.

    ``observed_at`` is taken when the request is issued (our clock, UTC);
    the v1 payload has no provider timestamp to set beside it.  ``fetcher``
    and ``now`` are test hooks.
    """
    clock = now or (lambda: datetime.now(timezone.utc))
    observed_at = clock()
    response = fetch_week_stats_response(season, week, fetcher=fetcher, timeout=timeout)
    if response.error is not None:
        _LOGGER.warning(
            "sleeper_live_stats.fetch_failed season=%s week=%s status=%s err=%s",
            season,
            week,
            response.http_status,
            response.error,
        )
    return parse_week_stats(
        response.payload,
        season=season,
        week=week,
        observed_at=observed_at,
        source_url=response.url,
        http_status=response.http_status,
        error=response.error,
    )


# ── Stat corrections ──────────────────────────────────────────────────

#: ``StatCorrection.kind`` values.
CORRECTION_CHANGED = "changed"
CORRECTION_MISSING_IN_CURRENT = "missing_in_current"
CORRECTION_FIRST_SEEN_AFTER_FINAL = "first_seen_after_final"


@dataclass(frozen=True)
class StatCorrection:
    """A stat line that moved after its game was already final.

    ``changes`` maps each differing stat key to ``(before, after)``; a side
    is ``None`` when that observation did not carry the key (absent, not 0).
    For ``missing_in_current`` the player vanished from the feed: that is
    reported, never read as his stats becoming zero.
    """

    player_id: str
    game_id: str
    kind: str
    changes: Mapping[str, tuple[float | None, float | None]]


@dataclass(frozen=True)
class StatCorrectionReport:
    corrections: tuple[StatCorrection, ...]
    #: Players whose line changed but whose game could not be identified,
    #: so whether the change is a post-final correction is UNKNOWN.
    unattributable: tuple[str, ...]


def _lines_of(obs: LiveStatsSnapshot | Mapping[str, StatLine]) -> Mapping[str, StatLine]:
    return obs.lines if isinstance(obs, LiveStatsSnapshot) else obs


def _stat_diff(
    before: Mapping[str, float], after: Mapping[str, float]
) -> dict[str, tuple[float | None, float | None]]:
    diff: dict[str, tuple[float | None, float | None]] = {}
    for key in sorted(set(before) | set(after)):
        b = before.get(key)
        a = after.get(key)
        if b != a:
            diff[key] = (b, a)
    return diff


def detect_stat_corrections(
    previous: LiveStatsSnapshot | Mapping[str, StatLine],
    current: LiveStatsSnapshot | Mapping[str, StatLine],
    final_game_ids: Iterable[str],
    *,
    player_game_ids: Mapping[str, str] | None = None,
) -> StatCorrectionReport:
    """Players whose stats changed after their game was already final.

    ``final_game_ids`` must be the games that were ALREADY final when
    ``previous`` was observed.  A game that went final between the two
    observations legitimately changes lines on its way to final; that is
    not a correction, and passing it here would call it one.

    A player's game comes from his line's ``game_id`` (current, then
    previous) and otherwise from ``player_game_ids`` — required for the v1
    payload, which states no game per row.  A changed line whose game
    cannot be identified goes to ``unattributable`` rather than being
    guessed into or out of the correction set.
    """
    prev_lines = _lines_of(previous)
    cur_lines = _lines_of(current)
    finals = {str(g) for g in final_game_ids}
    mapping = player_game_ids or {}
    corrections: list[StatCorrection] = []
    unattributable: list[str] = []

    for pid in sorted(set(prev_lines) | set(cur_lines)):
        prev = prev_lines.get(pid)
        cur = cur_lines.get(pid)
        if prev is not None and cur is not None:
            changes = _stat_diff(prev.stats, cur.stats)
            if not changes:
                continue
        else:
            changes = {}
        game_id = (
            (cur.game_id if cur is not None else None)
            or (prev.game_id if prev is not None else None)
            or _opt_str(mapping.get(pid))
        )
        if game_id is None:
            unattributable.append(pid)
            continue
        if game_id not in finals:
            continue
        if cur is None:
            prev_stats = prev.stats if prev is not None else {}
            corrections.append(
                StatCorrection(
                    pid,
                    game_id,
                    CORRECTION_MISSING_IN_CURRENT,
                    {k: (v, None) for k, v in sorted(prev_stats.items())},
                )
            )
        elif prev is None:
            corrections.append(
                StatCorrection(
                    pid,
                    game_id,
                    CORRECTION_FIRST_SEEN_AFTER_FINAL,
                    {k: (None, v) for k, v in sorted(cur.stats.items())},
                )
            )
        else:
            corrections.append(StatCorrection(pid, game_id, CORRECTION_CHANGED, changes))

    return StatCorrectionReport(tuple(corrections), tuple(unattributable))


__all__ = [
    "CORRECTION_CHANGED",
    "CORRECTION_FIRST_SEEN_AFTER_FINAL",
    "CORRECTION_MISSING_IN_CURRENT",
    "LIVE_TIMEOUT_SEC",
    "LiveStatsSnapshot",
    "StatCorrection",
    "StatCorrectionReport",
    "StatLine",
    "detect_stat_corrections",
    "fetch_live_week_stats",
    "parse_week_stats",
]
