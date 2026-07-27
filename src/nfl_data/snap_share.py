"""Per-player snap share, joined onto GSIS ids.

Tier 3. Snap share is the cleanest available proxy for opportunity: a
back-up receiver who out-produces his snap count is a small sample, and
a starter whose snap share is falling is a sell signal the raw stat line
does not show for weeks.

THE JOIN IS THE WHOLE PROBLEM
─────────────────────────────
nflverse's snap-count release keys on ``pfr_player_id`` — Pro Football
Reference ids like ``ShahRa00`` — while every other durable artifact in
this repo keys on GSIS (``00-0036322``). Nothing joins them directly.

``fetch_id_map`` (nflverse's ``players.csv``) is the cross-walk, and it
is good enough: of 25,035 rows, 22,554 carry BOTH ``gsis_id`` and
``pfr_id``, measured 2026-07-27. The remaining 2,481 are gsis-only,
mostly pre-PFR-era or practice-squad entries that never took a snap.

**Unjoinable rows are counted, never silently dropped.** A snap row whose
PFR id is absent from the cross-walk is real playing time this repo
cannot attribute, and a coverage number that quietly excluded it would
read as completeness. :class:`SnapShareResult` reports
``unjoinedRows`` and ``unjoinedPlayers`` on every run.

WHY SEASON AGGREGATES AND A WEEKLY SERIES
─────────────────────────────────────────
The season mean answers "is this player a starter"; the weekly series
answers "is he becoming one, or ceasing to be". Those are different
questions and the second is the one with trade value, so both are
persisted. The series is small — 18 floats per player — so this stays
well under the size of the weekly actuals beside it.

Offense and defense percentages are kept SEPARATE rather than summed
into a single "snap share". A linebacker at 0.95 defensive snaps and a
receiver at 0.95 offensive snaps are both starters, but adding a
two-way player's numbers would produce 1.4 and mean nothing.
"""

from __future__ import annotations

import json
import logging
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "SNAP_SHARE_SCHEMA_VERSION",
    "SnapShareResult",
    "build_pfr_to_gsis",
    "default_snap_dir",
    "load_snap_share",
    "persist_snap_share",
    "snap_path",
]

SNAP_SHARE_SCHEMA_VERSION = "2026-07-27.v1"

#: Below this many games a season mean is not a description of a role.
MIN_GAMES = 3


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_snap_dir() -> Path:
    """Beside the weekly actuals — same durability contract."""
    return _repo_root() / "data" / "nfl_data" / "actuals"


def snap_path(season: int, *, snap_dir: Path | None = None) -> Path:
    return (snap_dir or default_snap_dir()) / f"snap_share_{int(season)}.jsonl"


def _num(raw: Any) -> float:
    if raw is None or raw == "":
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def build_pfr_to_gsis(id_map_rows: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """``{pfr_id: gsis_id}`` from nflverse's players cross-walk.

    Rows carrying only one of the two identifiers are skipped — they
    cannot participate in this join by definition, and including them
    with an empty value would produce a key that silently matches
    nothing.
    """
    out: dict[str, str] = {}
    for row in id_map_rows or []:
        if not isinstance(row, Mapping):
            continue
        pfr = str(row.get("pfr_id") or "").strip()
        gsis = str(row.get("gsis_id") or "").strip()
        if pfr and gsis:
            out[pfr] = gsis
    return out


class SnapShareResult:
    """What one persist run produced, including what it could not join."""

    __slots__ = (
        "seasons",
        "rows_fetched",
        "players",
        "unjoined_rows",
        "unjoined_players",
        "paths",
    )

    def __init__(self) -> None:
        self.seasons: list[int] = []
        self.rows_fetched = 0
        self.players = 0
        self.unjoined_rows = 0
        self.unjoined_players: set[str] = set()
        self.paths: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SNAP_SHARE_SCHEMA_VERSION,
            "seasons": list(self.seasons),
            "rowsFetched": self.rows_fetched,
            "players": self.players,
            # Real playing time this repo cannot attribute. Reported so
            # a coverage figure is never mistaken for completeness.
            "unjoinedRows": self.unjoined_rows,
            "unjoinedPlayers": len(self.unjoined_players),
            "paths": list(self.paths),
        }


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def persist_snap_share(
    seasons: Sequence[int],
    *,
    snap_dir: Path | None = None,
    cache_dir: Path | None = None,
    season_types: Sequence[str] | None = ("REG",),
    _snap_provider=None,
    _id_map_provider=None,
) -> SnapShareResult:
    """Fetch snap counts, join to GSIS, and persist per-season.

    One file per season, one JSONL line per season. Re-running replaces
    the season's line.

    The ``_*_provider`` hooks are test seams; production passes neither.
    """
    from src.nfl_data.ingest import fetch_id_map, fetch_snap_counts  # noqa: PLC0415

    result = SnapShareResult()
    wanted_types = {str(s).upper() for s in season_types} if season_types else None

    id_rows = (
        _id_map_provider() if _id_map_provider is not None else fetch_id_map(cache_dir=cache_dir)
    )
    pfr_to_gsis = build_pfr_to_gsis(id_rows)
    if not pfr_to_gsis:
        _LOGGER.warning(
            "snap_share: the id cross-walk resolved no pfr->gsis pairs; "
            "every snap row would be unjoinable, so nothing is written"
        )
        return result

    for season in seasons:
        season = int(season)
        rows = (
            _snap_provider(season)
            if _snap_provider is not None
            else fetch_snap_counts([season], cache_dir=cache_dir)
        )
        result.rows_fetched += len(rows or [])

        players: dict[str, dict[str, Any]] = {}
        for row in rows or []:
            if not isinstance(row, Mapping):
                continue
            if wanted_types is not None:
                gt = str(row.get("game_type") or "REG").upper()
                if gt not in wanted_types:
                    continue
            pfr = str(row.get("pfr_player_id") or "").strip()
            if not pfr:
                continue
            gsis = pfr_to_gsis.get(pfr)
            if not gsis:
                result.unjoined_rows += 1
                result.unjoined_players.add(pfr)
                continue
            try:
                week = int(_num(row.get("week")))
            except (TypeError, ValueError):
                continue
            rec = players.get(gsis)
            if rec is None:
                rec = {
                    "name": str(row.get("player") or ""),
                    "position": str(row.get("position") or "").upper(),
                    "weeks": {},
                }
                players[gsis] = rec
            rec["weeks"][str(week)] = {
                "offenseSnaps": int(_num(row.get("offense_snaps"))),
                "offensePct": round(_num(row.get("offense_pct")), 4),
                "defenseSnaps": int(_num(row.get("defense_snaps"))),
                "defensePct": round(_num(row.get("defense_pct")), 4),
            }

        if not players:
            _LOGGER.warning(
                "snap_share: season %d produced no joinable rows (%d fetched, "
                "%d unjoined) — nothing written",
                season,
                len(rows or []),
                result.unjoined_rows,
            )
            continue

        for rec in players.values():
            weeks = rec["weeks"]
            off = [w["offensePct"] for w in weeks.values() if w["offensePct"] > 0]
            dfn = [w["defensePct"] for w in weeks.values() if w["defensePct"] > 0]
            rec["games"] = len(weeks)
            # Offense and defense stay separate: summing a two-way
            # player's shares would exceed 1.0 and describe nobody.
            rec["offensePctMean"] = round(statistics.fmean(off), 4) if off else 0.0
            rec["defensePctMean"] = round(statistics.fmean(dfn), 4) if dfn else 0.0
            # A mean over one or two games is not a role. Say so rather
            # than letting a reader infer reliability from the number.
            rec["meanIsReliable"] = len(weeks) >= MIN_GAMES

        entry = {
            "schemaVersion": SNAP_SHARE_SCHEMA_VERSION,
            "season": season,
            "seasonTypes": sorted(wanted_types) if wanted_types else ["ALL"],
            "capturedAt": _now_utc(),
            "playerCount": len(players),
            "unjoinedRows": result.unjoined_rows,
            "players": dict(sorted(players.items())),
        }

        path = snap_path(season, snap_dir=snap_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            f.write(json.dumps(entry, separators=(",", ":"), sort_keys=True) + "\n")
        tmp.replace(path)

        result.seasons.append(season)
        result.players += len(players)
        result.paths.append(str(path))
        _LOGGER.info(
            "snap_share=written season=%d players=%d unjoined_rows=%d path=%s",
            season,
            len(players),
            result.unjoined_rows,
            path,
        )

    return result


def load_snap_share(season: int, *, snap_dir: Path | None = None) -> dict[str, Any] | None:
    path = snap_path(season, snap_dir=snap_dir)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        return json.loads(text.splitlines()[0])
    except json.JSONDecodeError:
        _LOGGER.warning("snap_share: unparseable file at %s", path)
        return None
