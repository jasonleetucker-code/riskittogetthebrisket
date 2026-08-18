"""Durable per-player-per-week actuals — the season's box scores, kept.

Why this is not ``data/nfl_data_cache/``
────────────────────────────────────────
That directory is a live, load-bearing TTL cache (``src/nfl_data/cache.py``
writes ``<sha256[:16]>.json`` + a ``.meta.json`` sidecar there, and
``src/api/startup_validation.py`` checks it is writable).  It is **not**
vestigial — it was empty on inspection only because no fetch had run in
that container yet.

It is nonetheless the wrong home for actuals, and for a structural
reason rather than a stylistic one: **everything in it is designed to be
thrown away.**  ``cache.get`` returns ``None`` past ``ttl_seconds``,
``cache.put`` overwrites the same hashed path on every refetch, and any
entry that fails to parse is unlinked on read.  A 24-hour TTL over a
season of box scores means the only thing on disk is the most recent
pull; nothing accumulates.  Week 3 is gone by week 4, and a season's
history can never be reconstructed from it.

So the cache keeps its job (don't hammer nflverse within a day) and this
module keeps a separate, append-only, human-inspectable log beside it.

On-disk shape
─────────────
One file per season, one JSONL line per ``(season, week, seasonType)``,
mirroring ``src/api/source_history.py``'s "one line per snapshot, players
nested inside" layout and ``data/ros/aggregate/history/``'s
one-artifact-per-observation convention::

    data/nfl_data/actuals/player_week_2025.jsonl

    {"season":2025,"week":1,"seasonType":"REG",
     "capturedAt":"2026-07-27T12:00:00+00:00",
     "playerCount":1204,
     "players":{
       "00-0026158":{
         "name":"Joe Flacco","position":"QB","team":"CLE",
         "offense":{"completions":31.0,"attempts":45.0,...},
         "defense":null
       },
       "00-0034857":{
         "name":"D.Slay","position":"CB","team":"PIT",
         "offense":null,
         "defense":{"tackles_solo":5.0,"tackles_combined":5.0,...}
       }
     }}

Keyed by GSIS id because that is the only identifier nflverse guarantees
across both halves of the row and across seasons.  ``offense`` and
``defense`` are nested rather than flattened because
:class:`~src.nfl_data.ingest.WeeklyStatRow` and
:class:`~src.nfl_data.ingest.WeeklyDefensiveStatRow` collide on
``sacks`` and ``interceptions`` — a QB's sacks taken and an edge
rusher's sacks recorded are different numbers under one name.

Column names: nflverse renamed them, and the dataclasses predate it
──────────────────────────────────────────────────────────────────
``WeeklyStatRow`` and ``WeeklyDefensiveStatRow`` were written against the
retired ``player_stats/player_stats_{year}.csv`` and
``player_stats_def_{year}.csv`` releases.  #589 repointed the fetchers at
the unified ``stats_player/stats_player_week_{year}.csv``, which **also
renamed six columns**.  Verified live against the 2025 file, 2026-07-27:

    recent_team        → team
    interceptions      → passing_interceptions
    sacks              → sacks_suffered
    fumbles_lost       → fumbles_lost_total
    def_safety         → def_safeties
    def_tackles        → (removed; see below)

Reading a renamed column yields ``None``/``0`` with no error, so the
mapper below accepts BOTH spellings per field — first candidate present
wins.  The alias lists are the whole guard: a mapper that silently reads
zeros is exactly the shape of defect #589 was.

Tackles: three columns, and none of them mean what their name suggests
─────────────────────────────────────────────────────────────────────
``def_tackles`` has no replacement column in the unified release, and
reconstructing it forced the question of what nflverse's tackle columns
actually count.  Two facts, both measured against the retired 2024
defensive release (9,994 rows) rather than assumed:

1. ``def_tackles == def_tackles_solo + def_tackles_with_assist`` on
   **9,994 of 9,994** rows — an exact identity.  The intuitive
   ``solo + def_tackle_assists`` holds on only 3,058.
2. ``def_tackles_solo`` **excludes** ``def_tackles_with_assist``: 342
   rows have ``solo == 0`` while ``with_assist > 0``, which is
   impossible if one contained the other.

So nflverse's columns map onto the NFL gamebook like this::

    gamebook SOLO     = def_tackles_solo + def_tackles_with_assist
                      = def_tackles                (the retired column)
    gamebook ASSISTS  = def_tackle_assists
    gamebook COMBINED = def_tackles + def_tackle_assists

Cross-checked against real box scores: Zack Baun (PHI) 2024 wk1 reads
solo 9 / with_assist 2 / assists 4, i.e. gamebook 11 solo + 4 assists =
his actual 15-tackle line.  Reading ``def_tackles_solo`` alone would
have reported 9.

``WeeklyDefensiveStatRow``'s three tackle fields are therefore populated
with the **gamebook** definitions, not the raw column values — a field
called ``tackles_combined`` that carries the solo count is the kind of
name/predicate gap this repo keeps paying for.  ``tackles_solo`` is the
gamebook solo total, ``tackles_assist`` is assists, and
``tackles_combined`` is their sum.  :data:`TACKLES_COMBINED_IS_DERIVED`
marks that the last one is computed rather than published.

What is deliberately NOT here
─────────────────────────────
* **Snap counts.**  ``WeeklyStatRow.snap_count`` / ``snap_pct`` stay
  ``None``.  ``fetch_snap_counts`` keys on PFR ids, not GSIS, so joining
  it needs the ``fetch_id_map`` cross-walk — a real piece of work, and
  half-wiring it would put an unjoined column on disk that reads as
  "no snaps played" rather than "not fetched".
* **Fantasy points.**  nflverse publishes ``fantasy_points_ppr``, but
  this league's points come from ``src/nfl_data/realized_points.py``
  against Sleeper's ``scoring_settings``.  Storing a foreign scoring
  system's total next to the stats invites someone to read it as ours.

Both fetchers now hit ONE url
─────────────────────────────
After #589 ``fetch_weekly_stats`` and ``fetch_weekly_defensive_stats``
request the same unified CSV and differ only in how callers read the
result.  :func:`persist_weekly_actuals` calls both anyway (they cache
under separate keys, so the cost is one extra HTTP round-trip on a cold
day) and merges on ``(gsis, season, week, seasonType)``, so the duplicate
rows collapse instead of doubling the file.

No function raises on data problems.  Filesystem errors DO propagate —
a caller persisting actuals needs to know the write failed.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from src.nfl_data import cache as _cache
from src.nfl_data.ingest import (
    WeeklyDefensiveStatRow,
    WeeklyStatRow,
    fetch_id_map,
    fetch_snap_counts,
    fetch_weekly_defensive_stats,
    fetch_weekly_stats,
)

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "ACTUALS_SCHEMA_VERSION",
    "TACKLES_COMBINED_IS_DERIVED",
    "PersistResult",
    "build_snap_index",
    "coverage",
    "default_actuals_dir",
    "load_player_weeks",
    "load_season",
    "normalize_defensive_row",
    "normalize_offensive_row",
    "persist_weekly_actuals",
    "season_path",
    "usage_stat_rows",
]

ACTUALS_SCHEMA_VERSION = "2026-07-27.v2"
"""v2 adds the per-player-week ``snaps`` block (see :func:`build_snap_index`).

Purely additive: a v1 line has no ``snaps`` key at all, which readers
must treat identically to ``snaps: null`` — both mean "not fetched".
Only a populated block carries measured snap counts.
"""

TACKLES_COMBINED_IS_DERIVED = True
"""The three ``defense.tackles_*`` fields are gamebook-derived.

nflverse publishes ``def_tackles_solo`` (unassisted only),
``def_tackles_with_assist`` and ``def_tackle_assists``; the gamebook
numbers a fantasy league scores against are ``solo + with_assist`` and
``assists``.  The derivation is measured (see the module docstring), but
it is still a derivation — a consumer that needs published-only columns
should read the raw nflverse row instead of these fields.
"""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_actuals_dir() -> Path:
    """``data/nfl_data/actuals`` — durable, sibling of the TTL cache."""
    return _repo_root() / "data" / "nfl_data" / "actuals"


def season_path(season: int, *, actuals_dir: Path | None = None) -> Path:
    return (actuals_dir or default_actuals_dir()) / f"player_week_{int(season)}.jsonl"


# ── Column mapping ────────────────────────────────────────────────────
#
# ``field -> (candidate source columns, first match wins)``.  Both the
# unified 2025+ spelling and the retired pre-2025 spelling are listed so
# a backfill over old seasons and a live pull over the current one go
# through one mapper.

_OFFENSE_NUMERIC: dict[str, tuple[str, ...]] = {
    "completions": ("completions",),
    "attempts": ("attempts",),
    "passing_yards": ("passing_yards",),
    "passing_tds": ("passing_tds",),
    # Renamed 2025: interceptions -> passing_interceptions.
    "interceptions": ("passing_interceptions", "interceptions"),
    # Renamed 2025: sacks -> sacks_suffered.  This is sacks TAKEN by a
    # passer, not sacks recorded by a defender (that is defense.sacks).
    "sacks": ("sacks_suffered", "sacks"),
    "carries": ("carries",),
    "rushing_yards": ("rushing_yards",),
    "rushing_tds": ("rushing_tds",),
    "targets": ("targets",),
    "receptions": ("receptions",),
    "receiving_yards": ("receiving_yards",),
    "receiving_tds": ("receiving_tds",),
    # Renamed 2025: fumbles_lost -> fumbles_lost_total.
    "fumbles_lost": ("fumbles_lost_total", "fumbles_lost"),
    # Individual special teams (#802) — see WeeklyStatRow for why these
    # are here.  Adding them to this table also widens
    # _OFFENSE_PRESENCE_COLUMNS, which is intended: a returner whose only
    # production that week was 90 kick-return yards HAS a stat line, and
    # persisting nothing for him is the same "missing is not zero" error
    # one layer down.
    "kickoff_return_yards": ("kickoff_return_yards",),
    "punt_return_yards": ("punt_return_yards",),
    "special_teams_tds": ("special_teams_tds",),
}

_DEFENSE_NUMERIC: dict[str, tuple[str, ...]] = {
    # tackles_solo / tackles_assist / tackles_combined are all derived —
    # see _tackle_view and the module docstring.  They are deliberately
    # absent from this table.
    "tackles_for_loss": ("def_tackles_for_loss",),
    "tackles_for_loss_yards": ("def_tackles_for_loss_yards",),
    "sacks": ("def_sacks",),
    "sack_yards": ("def_sack_yards",),
    "qb_hits": ("def_qb_hits",),
    "passes_defended": ("def_pass_defended", "def_passes_defended"),
    "interceptions": ("def_interceptions",),
    "interception_yards": ("def_interception_yards",),
    "fumbles_forced": ("def_fumbles_forced",),
    # Not def_-prefixed in the unified release.
    "fumble_recovery_own": ("fumble_recovery_own", "def_fumble_recovery_own"),
    "fumble_recovery_opp": ("fumble_recovery_opp", "def_fumble_recovery_opp"),
    "fumble_recovery_yards_own": (
        "fumble_recovery_yards_own",
        "def_fumble_recovery_yards_own",
    ),
    "fumble_recovery_yards_opp": (
        "fumble_recovery_yards_opp",
        "def_fumble_recovery_yards_opp",
    ),
    "def_tds": ("def_tds",),
    # Renamed 2025: def_safety -> def_safeties.
    "safeties": ("def_safeties", "def_safety"),
}

_TACKLE_COLUMNS = (
    "def_tackles",
    "def_tackles_solo",
    "def_tackles_with_assist",
    "def_tackle_assists",
)

_ID_COLUMNS = ("player_id", "player_id_gsis", "gsis_id")
_NAME_COLUMNS = ("player_display_name", "player_name", "full_name")
_TEAM_COLUMNS = ("team", "recent_team", "team_abbr")
_POSITION_COLUMNS = ("position", "position_group")

# Columns that carry ANY defensive production.  A row is persisted with
# a ``defense`` block only when at least one of these is non-zero — the
# unified file gives every offensive player a full set of zeroed def_*
# columns, and writing those would triple the file for no information.
_DEFENSE_PRESENCE_COLUMNS = (
    tuple(col for cols in _DEFENSE_NUMERIC.values() for col in cols) + _TACKLE_COLUMNS
)

_OFFENSE_PRESENCE_COLUMNS = tuple(col for cols in _OFFENSE_NUMERIC.values() for col in cols)


def _num(raw: Any) -> float:
    """Coerce to a finite float, defaulting to 0.0.

    CSV rows arrive as strings or as ``nflverse_direct._coerce_numerics``
    output; DataFrame rows arrive with NaN for missing.  All three land
    on 0.0, which is what a box score means by an absent stat line.
    """
    if raw is None or raw == "":
        return 0.0
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return v if math.isfinite(v) else 0.0


def _first(row: Mapping[str, Any], columns: Sequence[str]) -> Any:
    for col in columns:
        if col in row:
            val = row[col]
            if val is not None and val != "":
                return val
    return None


def _first_numeric(row: Mapping[str, Any], columns: Sequence[str]) -> float:
    return _num(_first(row, columns))


def _str(raw: Any) -> str:
    return "" if raw is None else str(raw).strip()


def _int(raw: Any) -> int:
    return int(_num(raw))


def _any_nonzero(row: Mapping[str, Any], columns: Sequence[str]) -> bool:
    return any(_num(row.get(col)) != 0.0 for col in columns if col in row)


def _tackle_view(row: Mapping[str, Any]) -> tuple[float, float, float]:
    """``(gamebook solo, assists, combined)`` from any nflverse schema.

    Pre-2025 rows carry the published ``def_tackles`` (which IS the
    gamebook solo total); unified 2025+ rows do not, so it is
    reconstructed from ``def_tackles_solo + def_tackles_with_assist``.
    Both paths then add ``def_tackle_assists`` for combined.  See the
    module docstring for the two measurements this rests on.
    """
    published = _first(row, ("def_tackles",))
    if published is not None:
        solo = _num(published)
    else:
        solo = _num(_first(row, ("def_tackles_solo",))) + _num(
            _first(row, ("def_tackles_with_assist",))
        )
    assists = _num(_first(row, ("def_tackle_assists",)))
    return solo, assists, solo + assists


def normalize_offensive_row(row: Mapping[str, Any]) -> WeeklyStatRow | None:
    """Map one raw nflverse row onto :class:`WeeklyStatRow`.

    Returns ``None`` when the row has no GSIS id (nflverse emits a
    handful of unattributed rows per season) or no offensive production
    at all.  ``snap_count`` / ``snap_pct`` stay ``None`` — see the module
    docstring for why they are not joined here.
    """
    if not isinstance(row, Mapping):
        return None
    gsis = _str(_first(row, _ID_COLUMNS))
    if not gsis:
        return None
    if not _any_nonzero(row, _OFFENSE_PRESENCE_COLUMNS):
        return None
    values = {field: _first_numeric(row, cols) for field, cols in _OFFENSE_NUMERIC.items()}
    return WeeklyStatRow(
        player_id_gsis=gsis,
        player_name=_str(_first(row, _NAME_COLUMNS)),
        position=_str(_first(row, _POSITION_COLUMNS)).upper(),
        recent_team=_str(_first(row, _TEAM_COLUMNS)).upper(),
        season=_int(row.get("season")),
        week=_int(row.get("week")),
        **values,
    )


def normalize_defensive_row(row: Mapping[str, Any]) -> WeeklyDefensiveStatRow | None:
    """Map one raw nflverse row onto :class:`WeeklyDefensiveStatRow`.

    Returns ``None`` for rows with no GSIS id or no defensive production.
    The unified release gives every offensive player a zeroed ``def_*``
    block, so the production check is what keeps the file honest about
    who actually played defense.
    """
    if not isinstance(row, Mapping):
        return None
    gsis = _str(_first(row, _ID_COLUMNS))
    if not gsis:
        return None
    if not _any_nonzero(row, _DEFENSE_PRESENCE_COLUMNS):
        return None
    values = {field: _first_numeric(row, cols) for field, cols in _DEFENSE_NUMERIC.items()}
    solo, assists, combined = _tackle_view(row)
    return WeeklyDefensiveStatRow(
        player_id_gsis=gsis,
        player_name=_str(_first(row, _NAME_COLUMNS)),
        position=_str(_first(row, _POSITION_COLUMNS)).upper(),
        team=_str(_first(row, _TEAM_COLUMNS)).upper(),
        season=_int(row.get("season")),
        week=_int(row.get("week")),
        tackles_solo=solo,
        tackles_assist=assists,
        tackles_combined=combined,
        **values,
    )


_IDENTITY_FIELDS = frozenset(
    {"player_id_gsis", "player_name", "position", "recent_team", "team", "season", "week"}
)


def _stat_payload(dc: Any) -> dict[str, Any]:
    """Dataclass → dict, minus the identity fields hoisted to the player
    record.  Keeps each week's line from repeating name/team/season/week
    twice per player."""
    return {k: v for k, v in asdict(dc).items() if k not in _IDENTITY_FIELDS}


def _season_type(row: Mapping[str, Any]) -> str:
    raw = _str(_first(row, ("season_type", "seasonType"))).upper()
    return _normalize_season_type(raw)


# ── Snap counts ───────────────────────────────────────────────────────
#
# Snap counts ship in their own nflverse release, keyed on
# ``pfr_player_id``, while everything in this repo keys on GSIS.  The
# cross-walk is ``players.csv`` (``fetch_id_map``), which carries both.
#
# Measured live 2026-07-27 for 2025: 26,612 snap rows, 22,554 usable
# cross-walk pairs, and **56 snap rows across 8 players** that carry a
# PFR id absent from the cross-walk — a 99.79% join.  Those 56 are
# counted, not dropped silently.

_SNAP_PFR_COLUMNS = ("pfr_player_id", "pfr_id")
_ID_MAP_PFR_COLUMNS = ("pfr_id", "pfr_player_id")
_ID_MAP_GSIS_COLUMNS = ("gsis_id", "player_id_gsis", "player_id")

_SNAP_UNITS: dict[str, tuple[str, str]] = {
    # unit -> (count column, percentage column)
    "offense": ("offense_snaps", "offense_pct"),
    "defense": ("defense_snaps", "defense_pct"),
    "specialTeams": ("st_snaps", "st_pct"),
}


def _normalize_season_type(raw: Any) -> str:
    """``REG`` or ``POST`` — everything non-regular collapses to POST.

    THIS IS LOAD-BEARING FOR THE SNAP JOIN, and it is the trap that a
    naive equality join walks into.  The two releases do not agree on
    the vocabulary: the weekly-stats file spells playoffs ``POST``,
    while the snap-counts file spells them ``WC`` / ``DIV`` / ``CON`` /
    ``SB`` (measured 2026-07-27).  Joining on the raw strings therefore
    matches every regular-season week and **no** playoff week, dropping
    882 of 19,421 stat rows' snaps with no error and no log line.

    Week numbering is continuous across both files (REG 1-18, playoffs
    19-22 in each), so the collapse cannot collide two different rounds
    onto one key.
    """
    text = _str(raw).upper()
    if not text:
        return "REG"
    return "REG" if text == "REG" else "POST"


def _snap_payload(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """One snap row → the stored ``snaps`` block, or ``None``.

    Percentages arrive as 0..1 fractions (measured: ``offense_pct``
    spans exactly 0.0-1.0), which is the scale
    ``usage_signals._ACTIVE_STARTER_SNAP_PCT`` already assumes.  They are
    stored unscaled so nothing downstream has to guess.
    """
    if not isinstance(row, Mapping):
        return None
    out: dict[str, Any] = {}
    for unit, (count_col, pct_col) in _SNAP_UNITS.items():
        out[unit] = _num(row.get(count_col))
        out[f"{unit}Pct"] = _num(row.get(pct_col))
    return out


def build_snap_index(
    season: int,
    *,
    cache_dir: Path | None = None,
    _snap_provider: Any | None = None,
    _id_map_provider: Any | None = None,
) -> tuple[dict[tuple[str, int, str], dict[str, Any]], dict[str, Any]]:
    """``{(gsis, week, seasonType): snaps}`` plus a join report.

    Returns an EMPTY index when either fetch comes back empty, and the
    report says which one.  That distinction matters downstream: an
    empty index means callers must leave ``snaps`` as ``None`` ("not
    fetched") rather than writing zeros, because a stored ``0.0`` is a
    measured fact — the player dressed and took no snaps — and the two
    must never be confused.
    """
    snap_rows = fetch_snap_counts([season], _provider=_snap_provider, cache_dir=cache_dir)
    id_rows = fetch_id_map(_provider=_id_map_provider, cache_dir=cache_dir)

    cross_walk: dict[str, str] = {}
    for row in id_rows or []:
        if not isinstance(row, Mapping):
            continue
        pfr = _str(_first(row, _ID_MAP_PFR_COLUMNS))
        gsis = _str(_first(row, _ID_MAP_GSIS_COLUMNS))
        if pfr and gsis:
            cross_walk[pfr] = gsis

    index: dict[tuple[str, int, str], dict[str, Any]] = {}
    unjoinable = 0
    unjoinable_players: set[str] = set()
    for row in snap_rows or []:
        if not isinstance(row, Mapping):
            continue
        pfr = _str(_first(row, _SNAP_PFR_COLUMNS))
        gsis = cross_walk.get(pfr, "")
        if not gsis:
            unjoinable += 1
            if pfr:
                unjoinable_players.add(pfr)
            continue
        payload = _snap_payload(row)
        if payload is None:
            continue
        key = (gsis, _int(row.get("week")), _normalize_season_type(row.get("game_type")))
        index[key] = payload

    report = {
        "season": int(season),
        "snapRowsFetched": len(snap_rows or []),
        "crossWalkPairs": len(cross_walk),
        "indexed": len(index),
        "unjoinableSnapRows": unjoinable,
        "unjoinablePlayers": len(unjoinable_players),
    }
    if not snap_rows:
        _LOGGER.warning("actuals_store: snap counts empty for season %d", season)
    elif not cross_walk:
        _LOGGER.warning(
            "actuals_store: PFR->GSIS cross-walk empty; %d snap rows unusable for season %d",
            len(snap_rows),
            season,
        )
    return index, report


class PersistResult:
    """What one :func:`persist_weekly_actuals` call actually wrote.

    Every count here is a positive trace.  A run that fetched nothing and
    a run that wrote nothing are different states, and reading zeros off
    a silent success is how a dead ingest path stays dead.
    """

    __slots__ = (
        "seasons",
        "offensive_rows_fetched",
        "defensive_rows_fetched",
        "player_weeks",
        "weeks_written",
        "offense_records",
        "defense_records",
        "skipped_no_id",
        "snap_records",
        "snap_reports",
        "paths",
    )

    def __init__(self) -> None:
        self.seasons: list[int] = []
        self.offensive_rows_fetched = 0
        self.defensive_rows_fetched = 0
        self.player_weeks = 0
        self.weeks_written = 0
        self.offense_records = 0
        self.defense_records = 0
        self.skipped_no_id = 0
        self.snap_records = 0
        self.snap_reports: list[dict[str, Any]] = []
        self.paths: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": ACTUALS_SCHEMA_VERSION,
            "seasons": list(self.seasons),
            "offensiveRowsFetched": self.offensive_rows_fetched,
            "defensiveRowsFetched": self.defensive_rows_fetched,
            "playerWeeks": self.player_weeks,
            "weeksWritten": self.weeks_written,
            "offenseRecords": self.offense_records,
            "defenseRecords": self.defense_records,
            "skippedNoPlayerId": self.skipped_no_id,
            "snapRecords": self.snap_records,
            "snapJoin": list(self.snap_reports),
            "paths": list(self.paths),
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"PersistResult({self.to_dict()})"


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                # A truncated tail from a killed process must not wedge
                # the whole season; drop the bad line and keep the rest.
                _LOGGER.warning("actuals_store: skipping unparseable line in %s", path)
                continue
            if isinstance(entry, dict):
                out.append(entry)
    return out


def _line_key(entry: Mapping[str, Any]) -> tuple[int, int, str]:
    return (
        _int(entry.get("season")),
        _int(entry.get("week")),
        _str(entry.get("seasonType")).upper() or "REG",
    )


def _write_lines(path: Path, entries: Iterable[Mapping[str, Any]]) -> None:
    """Atomic-ish rewrite: tempfile + rename, same as source_history."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, separators=(",", ":"), sort_keys=True) + "\n")
    tmp.replace(path)


def persist_weekly_actuals(
    seasons: Sequence[int],
    *,
    actuals_dir: Path | None = None,
    cache_dir: Path | None = None,
    captured_at: str | None = None,
    refresh: bool = False,
    with_snaps: bool = True,
    _offensive_provider: Any | None = None,
    _defensive_provider: Any | None = None,
    _snap_provider: Any | None = None,
    _id_map_provider: Any | None = None,
) -> PersistResult:
    """Fetch and durably persist player-week actuals for ``seasons``.

    Re-running is safe and idempotent: a ``(season, week, seasonType)``
    already on disk is REPLACED by the fresh pull, never appended
    alongside.  nflverse revises box scores for days after a game — a
    log that kept both copies would make "which one is current?"
    unanswerable, and the whole point of this file is to be the answer.

    Weeks present on disk but absent from the fetch are left untouched,
    so a partial fetch (or a mid-season run over a single year) narrows
    what it updates rather than truncating history.

    ``refresh=True`` evicts this season's entries from the ingest TTL
    cache first.  Without it a re-run inside the 24-hour window is
    served the *previous* pull and the replace above has nothing new to
    write — so a box-score revision published hours after a game would
    be silently invisible until the TTL lapsed.  Default off, because
    the cache exists for a reason; pass it when you are chasing a
    correction rather than filling in a new week.

    ``with_snaps=True`` (default) additionally fetches the snap-counts
    release and the PFR->GSIS cross-walk and attaches a ``snaps`` block
    per player-week.  PR #591 deliberately left these unjoined on the
    grounds that a half-join writes "no snaps played" where it means
    "not fetched" — that objection is answered here by keeping ``None``
    (absent) structurally distinct from ``0.0`` (measured), and by
    reporting the unjoinable rows instead of dropping them.  Pass
    ``with_snaps=False`` for a stats-only pull.

    Returns a :class:`PersistResult`.  The ``_*_provider`` hooks are test
    seams — production passes none of them.
    """
    result = PersistResult()
    result.seasons = [int(s) for s in seasons]
    if not result.seasons:
        return result

    stamp = captured_at or _now_utc()

    for season in result.seasons:
        if refresh:
            keys = [f"weekly_stats:{season}", f"weekly_def_stats:{season}"]
            if with_snaps:
                # The snap release and the cross-walk have their own
                # cache keys.  Evicting only the stats keys leaves a
                # refresh serving yesterday's snaps against today's box
                # scores — and, in a dev container, whatever a unit test
                # last wrote under the default cache dir.
                keys += [f"snap_counts:{season}", "id_map:v1"]
            for key in keys:
                _cache.evict(key, cache_dir=cache_dir)
        offensive = fetch_weekly_stats([season], _provider=_offensive_provider, cache_dir=cache_dir)
        defensive = fetch_weekly_defensive_stats(
            [season], _provider=_defensive_provider, cache_dir=cache_dir
        )
        result.offensive_rows_fetched += len(offensive)
        result.defensive_rows_fetched += len(defensive)

        snap_index: dict[tuple[str, int, str], dict[str, Any]] = {}
        if with_snaps:
            snap_index, snap_report = build_snap_index(
                season,
                cache_dir=cache_dir,
                _snap_provider=_snap_provider,
                _id_map_provider=_id_map_provider,
            )
            result.snap_reports.append(snap_report)

        # (week, seasonType) -> gsis -> record
        weeks: dict[tuple[int, str], dict[str, dict[str, Any]]] = {}

        def _slot(row: Mapping[str, Any], gsis: str, dc: Any) -> dict[str, Any]:
            key = (_int(row.get("week")), _season_type(row))
            bucket = weeks.setdefault(key, {})
            rec = bucket.get(gsis)
            if rec is None:
                rec = {
                    "name": getattr(dc, "player_name", ""),
                    "position": getattr(dc, "position", ""),
                    "team": getattr(dc, "recent_team", None) or getattr(dc, "team", ""),
                    "offense": None,
                    "defense": None,
                    # ``None`` = no snap row joined for this player-week.
                    # A populated block with 0.0 in it means the player
                    # WAS on the snap report and took no snaps in that
                    # unit — a measured fact, not a gap.  Never collapse
                    # the two.
                    "snaps": snap_index.get((gsis, _int(row.get("week")), _season_type(row))),
                }
                bucket[gsis] = rec
            return rec

        for raw in offensive:
            if not isinstance(raw, Mapping):
                continue
            if not _str(_first(raw, _ID_COLUMNS)):
                result.skipped_no_id += 1
                continue
            dc = normalize_offensive_row(raw)
            if dc is None:
                continue
            rec = _slot(raw, dc.player_id_gsis, dc)
            rec["offense"] = _stat_payload(dc)

        for raw in defensive:
            if not isinstance(raw, Mapping):
                continue
            if not _str(_first(raw, _ID_COLUMNS)):
                result.skipped_no_id += 1
                continue
            dc = normalize_defensive_row(raw)
            if dc is None:
                continue
            rec = _slot(raw, dc.player_id_gsis, dc)
            rec["defense"] = _stat_payload(dc)

        if not weeks:
            _LOGGER.warning(
                "actuals_store: season %d produced no persistable rows "
                "(offensive=%d defensive=%d fetched) — nothing written",
                season,
                len(offensive),
                len(defensive),
            )
            continue

        fresh: dict[tuple[int, str], dict[str, Any]] = {}
        for (week, season_type), players in weeks.items():
            # Drop players who ended up with neither block (possible if a
            # row had an id but every stat column was absent).
            players = {
                gsis: rec
                for gsis, rec in players.items()
                if rec["offense"] is not None or rec["defense"] is not None
            }
            if not players:
                continue
            result.offense_records += sum(1 for r in players.values() if r["offense"])
            result.defense_records += sum(1 for r in players.values() if r["defense"])
            result.snap_records += sum(1 for r in players.values() if r.get("snaps") is not None)
            result.player_weeks += len(players)
            fresh[(week, season_type)] = {
                "schemaVersion": ACTUALS_SCHEMA_VERSION,
                "season": season,
                "week": week,
                "seasonType": season_type,
                "capturedAt": stamp,
                "playerCount": len(players),
                "tacklesCombinedDerived": TACKLES_COMBINED_IS_DERIVED,
                "players": players,
            }

        if not fresh:
            continue

        path = season_path(season, actuals_dir=actuals_dir)
        merged: dict[tuple[int, int, str], dict[str, Any]] = {}
        for entry in _read_lines(path):
            merged[_line_key(entry)] = dict(entry)
        for (week, season_type), entry in fresh.items():
            merged[(season, week, season_type)] = entry

        _write_lines(path, [merged[k] for k in sorted(merged.keys())])
        result.weeks_written += len(fresh)
        result.paths.append(str(path))
        _LOGGER.info(
            "actuals_store=written season=%d weeks=%d players=%d path=%s",
            season,
            len(fresh),
            sum(e["playerCount"] for e in fresh.values()),
            path,
        )

    return result


def load_season(
    season: int,
    *,
    actuals_dir: Path | None = None,
    season_types: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Every persisted week for ``season``, ascending by week.

    ``season_types`` filters to e.g. ``("REG",)``; ``None`` returns
    regular season and playoffs together.
    """
    entries = _read_lines(season_path(season, actuals_dir=actuals_dir))
    if season_types is not None:
        wanted = {str(s).upper() for s in season_types}
        entries = [e for e in entries if _str(e.get("seasonType")).upper() in wanted]
    entries.sort(key=_line_key)
    return entries


def load_player_weeks(
    player_id_gsis: str,
    *,
    seasons: Sequence[int] | None = None,
    actuals_dir: Path | None = None,
    season_types: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """One player's persisted weeks, ascending by (season, week).

    Each element is the stored player record plus its ``season``,
    ``week`` and ``seasonType`` hoisted back out of the enclosing line,
    so a caller gets a flat time series without knowing the file layout.
    """
    gsis = _str(player_id_gsis)
    if not gsis:
        return []
    directory = actuals_dir or default_actuals_dir()
    if seasons is None:
        candidates = sorted(directory.glob("player_week_*.jsonl")) if directory.exists() else []
        season_list = []
        for p in candidates:
            try:
                season_list.append(int(p.stem.rsplit("_", 1)[-1]))
            except ValueError:
                continue
    else:
        season_list = [int(s) for s in seasons]

    out: list[dict[str, Any]] = []
    for season in sorted(season_list):
        for entry in load_season(season, actuals_dir=directory, season_types=season_types):
            players = entry.get("players")
            if not isinstance(players, dict):
                continue
            rec = players.get(gsis)
            if not isinstance(rec, dict):
                continue
            out.append(
                {
                    "season": _int(entry.get("season")),
                    "week": _int(entry.get("week")),
                    "seasonType": _str(entry.get("seasonType")).upper() or "REG",
                    "capturedAt": entry.get("capturedAt"),
                    **rec,
                }
            )
    return out


def usage_stat_rows(
    season: int,
    *,
    actuals_dir: Path | None = None,
    season_types: Sequence[str] | None = ("REG",),
) -> list[dict[str, Any]]:
    """Flat per-player-week rows in the shape ``usage_windows`` reads.

    :func:`src.nfl_data.usage_windows.build_rolling_windows` looks up
    ``player_id_gsis``, ``season``, ``week``, ``team``, ``targets``,
    ``carries`` and ``snap_pct`` by name off plain dicts.  This is the
    adapter from the stored nested layout to that shape; without it a
    caller would have to know the file format, which is exactly what
    :func:`load_player_weeks` exists to avoid.

    ``snap_pct`` resolves to the player's DOMINANT unit — whichever of
    offense/defense they took more snaps in that week.  Picking by
    position instead would misfile every two-way and package player, and
    reporting both side by side would leave the choice to a caller that
    has less information than this function does.  ``snapUnit`` records
    which one won so the choice stays auditable.

    ``snap_pct`` is ``None``, never ``0.0``, when no snap row joined —
    ``build_rolling_windows`` coerces ``None`` to 0.0 for the arithmetic,
    but a consumer that needs to distinguish "did not play" from "we do
    not know" can read this field before it gets there.

    Regular season only by default: playoff weeks are a different usage
    regime and blending them into a rolling window silently changes what
    the mean means.
    """
    out: list[dict[str, Any]] = []
    for entry in load_season(season, actuals_dir=actuals_dir, season_types=season_types):
        players = entry.get("players")
        if not isinstance(players, dict):
            continue
        week = _int(entry.get("week"))
        season_type = _str(entry.get("seasonType")).upper() or "REG"
        for gsis, rec in players.items():
            if not isinstance(rec, dict):
                continue
            offense = rec.get("offense") if isinstance(rec.get("offense"), dict) else {}
            snaps = rec.get("snaps") if isinstance(rec.get("snaps"), dict) else None
            snap_pct: float | None = None
            snap_unit = ""
            if snaps is not None:
                offense_snaps = _num(snaps.get("offense"))
                defense_snaps = _num(snaps.get("defense"))
                if defense_snaps > offense_snaps:
                    snap_pct, snap_unit = _num(snaps.get("defensePct")), "defense"
                else:
                    snap_pct, snap_unit = _num(snaps.get("offensePct")), "offense"
            out.append(
                {
                    "player_id_gsis": _str(gsis),
                    "player_name": _str(rec.get("name")),
                    "position": _str(rec.get("position")).upper(),
                    "team": _str(rec.get("team")).upper(),
                    "season": _int(entry.get("season")) or int(season),
                    "week": week,
                    "seasonType": season_type,
                    "targets": _num(offense.get("targets")),
                    "carries": _num(offense.get("carries")),
                    "receptions": _num(offense.get("receptions")),
                    "snap_pct": snap_pct,
                    "snapUnit": snap_unit,
                }
            )
    out.sort(key=lambda r: (r["player_id_gsis"], r["season"], r["week"]))
    return out


def coverage(*, actuals_dir: Path | None = None) -> dict[str, Any]:
    """What is actually on disk, per season.

    Diagnostic surface — the answer to "did the ingest run, and how much
    did it get?" without opening the files.  Reports zeros explicitly
    rather than omitting an empty season, because an absent key and a
    season with no data read the same to a caller.
    """
    directory = actuals_dir or default_actuals_dir()
    seasons: dict[str, Any] = {}
    if directory.exists():
        for path in sorted(directory.glob("player_week_*.jsonl")):
            try:
                season = int(path.stem.rsplit("_", 1)[-1])
            except ValueError:
                continue
            entries = _read_lines(path)
            weeks = sorted({_int(e.get("week")) for e in entries})
            seasons[str(season)] = {
                "weeks": weeks,
                "weekCount": len(entries),
                "playerWeeks": sum(_int(e.get("playerCount")) for e in entries),
                "seasonTypes": sorted(
                    {_str(e.get("seasonType")).upper() or "REG" for e in entries}
                ),
                "capturedAt": max((str(e.get("capturedAt") or "") for e in entries), default=None)
                or None,
                "path": str(path),
            }
    return {
        "schemaVersion": ACTUALS_SCHEMA_VERSION,
        "dir": str(directory),
        "dirExists": directory.exists(),
        "seasons": seasons,
    }
