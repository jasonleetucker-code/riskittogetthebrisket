"""Per-player rank history persistence.

On every contract rebuild we append a compact snapshot of
``{canonicalName: canonicalConsensusRank}`` to ``data/rank_history.jsonl``.
Later reads reconstruct a per-player time series so the frontend
``RankChangeGlyph`` (which accepts a ``history`` prop and degrades to
a delta arrow when absent) can render an actual sparkline.

JSONL is chosen deliberately:

* Append-only write is atomic at the OS level for lines <4 KB — no
  locking, no temp-file rename dance.
* Each line is independently parseable so a partial / corrupt final
  line doesn't break the whole history (the reader skips and
  continues).
* Text-friendly for ``git diff`` if we ever archive a slice.

Retention: we keep the newest ``MAX_SNAPSHOTS`` entries on disk
(currently 180 — six months of daily scrapes).  The trim happens
lazily on each append so a long-running deployment stays bounded.
Dedup: only one snapshot per UTC date is retained; a re-run on the
same day overwrites the existing entry.

Public API
──────────

    append_snapshot(contract, date=None)
        Write today's snapshot.  ``date`` defaults to UTC today in
        ``YYYY-MM-DD`` form.  Idempotent per date.

    load_history(days=30)
        Return ``{canonicalName: [{date, rank}, ...]}`` for the most
        recent ``days`` snapshots.

    stamp_contract_with_history(contract, days=30)
        Mutate ``contract['playersArray']`` in place, stamping
        ``rankHistory`` onto each player row.  The frontend
        ``RankChangeGlyph`` picks it up automatically — zero
        frontend changes needed to activate sparklines once the
        log has >=2 entries.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

HISTORY_PATH: Path = Path(__file__).resolve().parents[2] / "data" / "rank_history.jsonl"

# Keep six months of daily scrapes.  At ~1,200 players × ~5 bytes per
# rank-entry the on-disk footprint is ~1 MB — trivial, even if a
# scrape runs more than once a day the trim keeps it bounded.
MAX_SNAPSHOTS: int = 180

# Default sparkline window.  30 days is enough for a meaningful
# trend line without dominating the rankings-row rendering footprint.
DEFAULT_HISTORY_WINDOW_DAYS: int = 30


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _extract_ranks(contract: dict[str, Any]) -> dict[str, int]:
    """Flatten a live contract into ``{canonicalName: rank}``.

    Accepts either the top-level contract shape or the ``data``-
    wrapped API envelope.  Skips rows without a ranked stamp; we
    only record players who actually have a rank on the board.
    """
    arr = contract.get("playersArray")
    if not isinstance(arr, list):
        data = contract.get("data") or {}
        arr = data.get("playersArray") if isinstance(data, dict) else None
    if not isinstance(arr, list):
        return {}

    out: dict[str, int] = {}
    for row in arr:
        if not isinstance(row, dict):
            continue
        name = row.get("canonicalName") or row.get("displayName")
        rank = row.get("canonicalConsensusRank")
        if not name or not isinstance(rank, int) or rank <= 0:
            continue
        out[str(name)] = int(rank)
    return out


def _read_lines(path: Path) -> list[dict[str, Any]]:
    """Parse the JSONL file line-by-line; tolerate corrupt lines."""
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
                # Skip corrupt lines — append-only writes can
                # theoretically leave a half-written final line if
                # the host dies mid-flush.  We'd rather drop that
                # one line than abort every reader.
                continue
            if isinstance(entry, dict):
                out.append(entry)
    return out


def append_snapshot(
    contract: dict[str, Any],
    *,
    date: str | None = None,
    path: Path | None = None,
    max_snapshots: int = MAX_SNAPSHOTS,
) -> bool:
    """Append today's rank snapshot.

    Returns ``True`` if a new line was written, ``False`` if the
    contract had no ranked rows to persist (nothing to do).

    Idempotent per date — if an entry for ``date`` already exists
    it's overwritten, not duplicated.
    """
    path = path or HISTORY_PATH
    ranks = _extract_ranks(contract)
    if not ranks:
        return False

    date = date or _today_utc()
    entry = {"date": date, "ranks": ranks}

    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_lines(path)
    # Remove any existing entry for the same date (most recent wins).
    existing = [e for e in existing if e.get("date") != date]
    existing.append(entry)
    # Sort chronologically and trim to the retention window.
    existing.sort(key=lambda e: e.get("date") or "")
    if len(existing) > max_snapshots:
        existing = existing[-max_snapshots:]

    # Atomic rewrite via a temp file + rename so a concurrent reader
    # never sees a half-rewritten file.  JSONL is strictly append-
    # compatible but the dedup pass above requires a full rewrite.
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for e in existing:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")
    tmp.replace(path)
    return True


def load_history(
    days: int = DEFAULT_HISTORY_WINDOW_DAYS,
    *,
    path: Path | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return the last ``days`` snapshots flipped into per-player series.

    Output shape::

        {
          "Ja'Marr Chase": [
            {"date": "2026-03-25", "rank": 2},
            {"date": "2026-03-26", "rank": 2},
            ...
          ],
          ...
        }

    Players who don't appear in every snapshot get gaps.  The
    frontend sparkline path handles gaps; no imputation here.
    """
    path = path or HISTORY_PATH
    entries = _read_lines(path)
    if not entries:
        return {}
    entries.sort(key=lambda e: e.get("date") or "")
    windowed = entries[-max(1, int(days)):]

    per_player: dict[str, list[dict[str, Any]]] = {}
    for e in windowed:
        date = e.get("date")
        ranks = e.get("ranks") or {}
        if not isinstance(date, str) or not isinstance(ranks, dict):
            continue
        for name, rank in ranks.items():
            if not isinstance(rank, int):
                try:
                    rank = int(rank)
                except (TypeError, ValueError):
                    continue
            per_player.setdefault(str(name), []).append({"date": date, "rank": rank})
    return per_player


def stamp_contract_with_history(
    contract: dict[str, Any],
    *,
    days: int = DEFAULT_HISTORY_WINDOW_DAYS,
    path: Path | None = None,
) -> int:
    """Mutate the contract so each player row carries ``rankHistory``.

    Returns the number of players that had a history series attached.

    Called at contract build time so the frontend ``RankChangeGlyph``
    (which already accepts a ``history`` prop) upgrades from a single-
    delta arrow to a real sparkline with zero frontend changes.
    """
    history = load_history(days=days, path=path)
    if not history:
        return 0

    arr = contract.get("playersArray")
    if not isinstance(arr, list):
        data = contract.get("data") or {}
        arr = data.get("playersArray") if isinstance(data, dict) else None
    if not isinstance(arr, list):
        return 0

    stamped = 0
    for row in arr:
        if not isinstance(row, dict):
            continue
        name = row.get("canonicalName") or row.get("displayName")
        if not name:
            continue
        series = history.get(str(name))
        if series:
            row["rankHistory"] = series
            stamped += 1
    return stamped
