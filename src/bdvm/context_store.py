"""Materialised player-context snapshot: written out of band, read by requests.

WHY THIS EXISTS
---------------

Routing the request path to a cache-only read (``cache_only=True``) stopped
``/api/bdvm/*`` from DOWNLOADING the nflverse corpus, but not from PARSING it.
Measured on a fully warmed cache, 2026-08-20:

    id_map        read      25,046 rows    0.30 s
    weekly_stats  read     112,450 rows    9.13 s   <-- a 369 MB JSON entry
    snap_counts   read     157,615 rows    0.81 s
    build_player_context  23,939 players   8.93 s total

Nine seconds of GIL-bound JSON parsing inside the serving process is still a
heavy cache build started by an interactive request, and still long enough to
starve ``/api/data`` past the Next bridge's 4 s inter-chunk timeout.  The row
count is not what makes it expensive — snap counts are MORE rows and cost 0.81 s
— it is that weekly stat rows are very wide.

So the artifact the request path reads is the BUILT CONTEXT, not the rows it was
built from: 23,939 players, 6.2 MB, **0.20 s** to load and rehydrate, and equal
to the in-process build (``==`` on the dataclass map, verified).

This is the shape ``scripts/refresh_playerctx.py`` → ``data/playerctx/snapshot.json``
→ ``src/playerctx/store.py`` already established, and the read posture
``src/consensus_edge/inputs.py::player_context`` already documents: *populated
there and empty everywhere else*.

WHAT IT DOES NOT DO
-------------------

It never builds.  A missing or unreadable snapshot returns ``None``, and the
caller degrades to the empty context it has always used when a fetch failed —
neutral priors, never zeroed career load.  Falling back to an in-request build
would reinstate the nine seconds this module exists to remove.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from src.bdvm.context import PlayerContext

_LOGGER = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_DIR = REPO_ROOT / "data" / "bdvm" / "context"

#: Bumped only for a deliberate format change.  It is NOT the guard against a
#: ``PlayerContext`` field being added and nobody remembering to bump it —
#: ``_FIELDS`` below is, so an unbumped change fails closed to "missing"
#: instead of raising ``TypeError`` inside a request.
SCHEMA_VERSION = 1

_FIELDS = frozenset(f.name for f in dataclasses.fields(PlayerContext))


def snapshot_path(season: int, *, base_dir: Path | None = None) -> Path:
    return (base_dir or SNAPSHOT_DIR) / f"context_{int(season)}.json"


def write_snapshot(
    season: int,
    context: Mapping[str, PlayerContext],
    *,
    base_dir: Path | None = None,
) -> Path:
    """Persist ``context`` for ``season``.  Atomic: tmp file then rename.

    ``builtAt`` is the provenance the reader reports an age from — file mtime
    would be reset by a copy or a deploy and would then claim a freshness the
    data does not have.
    """
    path = snapshot_path(season, base_dir=base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "season": int(season),
        "builtAt": datetime.now(timezone.utc).isoformat(),
        "playerCount": len(context),
        "players": [dataclasses.asdict(v) for v in context.values()],
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)
    return path


def _read_header(season: int, base_dir: Path | None) -> dict[str, Any] | None:
    path = snapshot_path(season, base_dir=base_dir)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    if doc.get("schemaVersion") != SCHEMA_VERSION:
        return None
    # A snapshot that does not SAY which season it is cannot be matched to
    # one.  Coercing an absent season to 0 would read as "season 0", which is
    # a claim the file never made; the honest answer is that it is unusable.
    stamped = doc.get("season")
    if not isinstance(stamped, int) or isinstance(stamped, bool) or stamped != int(season):
        return None
    return doc


def load_snapshot(season: int, *, base_dir: Path | None = None) -> dict[str, PlayerContext] | None:
    """The materialised context for ``season``, or ``None`` when unusable.

    ``None`` covers absent, unreadable, wrong-season, wrong-schema and
    field-drifted — every one of which the caller must treat as "no context",
    never as a partially populated one.  A half-built context is worse than no
    context: it would price the players it happened to cover with real career
    loads and the rest with neutral priors, in one board, invisibly.
    """
    doc = _read_header(season, base_dir)
    if doc is None:
        return None
    rows = doc.get("players")
    if not isinstance(rows, list):
        return None
    out: dict[str, PlayerContext] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != _FIELDS:
            _LOGGER.warning(
                "bdvm context snapshot: field drift for season %s; treating as missing", season
            )
            return None
        out[str(row["player_key"])] = PlayerContext(**row)
    return out


def snapshot_age_seconds(season: int, *, base_dir: Path | None = None) -> float | None:
    """Seconds since the snapshot was BUILT, or None when there is none."""
    doc = _read_header(season, base_dir)
    if doc is None:
        return None
    try:
        built = datetime.fromisoformat(str(doc.get("builtAt")))
    except (TypeError, ValueError):
        return None
    if built.tzinfo is None:
        built = built.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - built).total_seconds())


def snapshot_player_count(season: int, *, base_dir: Path | None = None) -> int | None:
    doc = _read_header(season, base_dir)
    if doc is None:
        return None
    try:
        return int(doc.get("playerCount"))
    except (TypeError, ValueError):
        return None
