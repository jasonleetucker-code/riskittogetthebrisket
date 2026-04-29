"""Per-source value history persistence.

Sister of ``src/api/rank_history.py``.  Where ``rank_history`` stores
only the final blended consensus rank per player per day, this module
stores **per-source values** so the frontend can render "how each
source has valued this player over time" alongside "how the blend has
moved".

On-disk shape (``data/source_value_history.jsonl``)::

    {
      "date": "2026-04-23",
      "players": {
        "Malik Nabers::offense": {
          "blended":     8154,
          "blendedRank": 17,
          "sources": {
            "ktc":        7844,
            "fp_sf":      8580,
            "dynasty_nerds_sf_tep": 8632,
            ...
          }
        },
        ...
      }
    }

Every source value is on the normalized 1-9999 scale (the
``valueContribution`` field from ``sourceRankMeta`` when the blended
contract is available, else ``canonicalSiteValues`` from the raw
scrape).  Keeping sources on the same scale as the blended line lets
the chart overlay them with a shared Y axis.

Retention: mirrors ``rank_history`` at 180 daily snapshots.  One
JSONL line per date, trimmed + deduped on append.

Storage cost: ~12 sources × 1200 players × ~6 bytes ≈ 85 KB per
snapshot.  180 days ≈ 15 MB on disk — trivial relative to the daily
``dynasty_data_*.json`` exports at ~3-4 MB each.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

HISTORY_PATH: Path = Path(__file__).resolve().parents[2] / "data" / "source_value_history.jsonl"
# Mirror rank_history's three-year retention so the two logs stay in
# lockstep; a per-source chart can render the same 3-year window the
# blended rank chart can.  At ~85 KB per snapshot (1,200 players ×
# 12 sources), three years ≈ 90 MB on disk — manageable.  The trim
# happens on each append, so long-running deployments stay bounded.
MAX_SNAPSHOTS: int = 365 * 3
# Charts still open on a 180-day window by default — that's where
# the "value history · 180d" callout comes from.  Callers that want
# the full tail pass ``days=1095`` (or larger, clamped to
# MAX_SNAPSHOTS server-side).
DEFAULT_HISTORY_WINDOW_DAYS: int = 180


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


_OFFENSE_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})
_IDP_POSITIONS = frozenset(
    {"DL", "DE", "DT", "EDGE", "NT", "LB", "OLB", "ILB", "MLB",
     "DB", "CB", "S", "FS", "SS"}
)


def _infer_asset_class(row: dict[str, Any]) -> str:
    """Mirror of ``rank_history._infer_asset_class`` — keep in sync so
    player keys hash identically across both snapshot files and the
    two histories can be joined by the same composite key.
    """
    asset = str(row.get("assetClass") or "").strip().lower()
    if asset in ("offense", "idp", "pick"):
        return asset
    pos = str(row.get("position") or row.get("pos") or "").strip().upper()
    if pos == "PICK":
        return "pick"
    if pos in _OFFENSE_POSITIONS:
        return "offense"
    if pos in _IDP_POSITIONS:
        return "idp"
    return "unknown"


def _player_key(row: dict[str, Any]) -> str | None:
    name = row.get("canonicalName") or row.get("displayName") or row.get("name")
    if not name:
        return None
    return f"{name}::{_infer_asset_class(row)}"


def _extract_player_entry(row: dict[str, Any]) -> dict[str, Any] | None:
    """Pull the per-player (blended, blendedRank, sources, sourceRanks)
    quad.

    Prefers ``sourceRankMeta[key].valueContribution`` (the normalized
    1-9999 vote each source cast into the blend) because it's the
    same number rendered as the chip bars in PlayerPopup.  Falls back
    to ``canonicalSiteValues`` for legacy rows — the raw source scale
    isn't normalized but it's the best we have.

    ``sourceRanks`` is the per-source RANK (1 = best) for each
    contributing source, sourced from ``row.sourceRanks`` (the
    backend-stamped per-source rank map).  Stored alongside values so
    the PlayerPopup chart can render rank trajectories on a separate
    Y axis from the value chart.
    """
    if not isinstance(row, dict):
        return None

    blended = row.get("rankDerivedValue")
    blended_rank = row.get("canonicalConsensusRank")

    # Coerce numerics; the contract normally has them as ints but
    # tolerate floats from legacy rows.
    try:
        blended_val = int(blended) if blended is not None else None
    except (TypeError, ValueError):
        blended_val = None
    try:
        blended_rank_val = int(blended_rank) if blended_rank is not None else None
    except (TypeError, ValueError):
        blended_rank_val = None

    sources: dict[str, int] = {}
    meta = row.get("sourceRankMeta")
    if isinstance(meta, dict):
        for key, entry in meta.items():
            if not isinstance(entry, dict):
                continue
            contribution = entry.get("valueContribution")
            try:
                v = int(contribution) if contribution is not None else None
            except (TypeError, ValueError):
                v = None
            if v is not None and v > 0:
                sources[str(key)] = v
    # Fallback: legacy ``canonicalSiteValues`` (raw per-source values).
    # Not normalized but still useful for pre-contract-builder rows.
    if not sources:
        canonical = row.get("canonicalSiteValues") or row.get("_canonicalSiteValues")
        if isinstance(canonical, dict):
            for key, value in canonical.items():
                try:
                    v = int(value) if value is not None else None
                except (TypeError, ValueError):
                    v = None
                if v is not None and v > 0:
                    sources[str(key)] = v

    # Per-source ranks (1 = best).  ``row.sourceRanks`` is the
    # primary source; falls back to ``effectiveSourceRanks`` (the
    # post-Hampel set) which the contract stamps too.
    source_ranks: dict[str, int] = {}
    rank_map = row.get("sourceRanks") or row.get("effectiveSourceRanks")
    if isinstance(rank_map, dict):
        for key, value in rank_map.items():
            try:
                r = int(value) if value is not None else None
            except (TypeError, ValueError):
                r = None
            if r is not None and r > 0:
                source_ranks[str(key)] = r

    if (
        blended_val is None
        and blended_rank_val is None
        and not sources
        and not source_ranks
    ):
        return None

    entry: dict[str, Any] = {"sources": sources}
    if source_ranks:
        entry["sourceRanks"] = source_ranks
    if blended_val is not None:
        entry["blended"] = blended_val
    if blended_rank_val is not None:
        entry["blendedRank"] = blended_rank_val
    return entry


def _extract_all(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return ``{playerKey: {blended, blendedRank, sources}}`` for every
    row in the contract that has at least one source value stamped.
    """
    out: dict[str, dict[str, Any]] = {}
    arr = contract.get("playersArray")
    if not isinstance(arr, list):
        data = contract.get("data") or {}
        arr = data.get("playersArray") if isinstance(data, dict) else None

    if isinstance(arr, list):
        for row in arr:
            if not isinstance(row, dict):
                continue
            key = _player_key(row)
            entry = _extract_player_entry(row)
            if not key or not entry:
                continue
            out[key] = entry

    # Also try the legacy ``players`` dict, keyed by display name —
    # this is the path that backfill needs, since pre-contract-builder
    # exports only have the dict.
    if not out:
        players = contract.get("players")
        if isinstance(players, dict):
            for name, row in players.items():
                if not isinstance(row, dict):
                    continue
                scoped = {"displayName": name, **row}
                key = _player_key(scoped)
                entry = _extract_player_entry(scoped)
                if not key or not entry:
                    continue
                out[key] = entry
    return out


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
    """Write today's per-source value snapshot, deduped per UTC date.

    Returns True when a line was written, False when the contract
    had no stampable rows.
    """
    path = path or HISTORY_PATH
    players = _extract_all(contract)
    if not players:
        return False

    date = date or _today_utc()
    entry = {"date": date, "players": players}

    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_lines(path)
    existing = [e for e in existing if e.get("date") != date]
    existing.append(entry)
    existing.sort(key=lambda e: e.get("date") or "")
    if len(existing) > max_snapshots:
        existing = existing[-max_snapshots:]

    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for e in existing:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")
    tmp.replace(path)
    return True


def _norm_name_key(raw_key: str) -> tuple[str, str]:
    """``"Malik Nabers::offense"`` → ("malik nabers", "offense"). Split
    is permissive — keys without ``::`` resolve to asset ``""``.
    """
    if "::" in raw_key:
        name, asset = raw_key.split("::", 1)
    else:
        name, asset = raw_key, ""
    return name.strip().lower(), asset.strip().lower()


def _median(values: list[int | float]) -> float | None:
    """Plain median — no numpy dep."""
    xs = sorted(v for v in values if isinstance(v, (int, float)))
    n = len(xs)
    if n == 0:
        return None
    if n % 2 == 1:
        return float(xs[n // 2])
    return (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def load_player_history(
    name: str,
    *,
    days: int = DEFAULT_HISTORY_WINDOW_DAYS,
    asset_class: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Return ``{dates, blended: [{date, value, rank, derived?}],
    sources: {key: [{date, value}, ...]},
    sourceRanks: {key: [{date, rank}, ...]}}`` for a single player.

    ``blended[].derived`` is ``True`` when the entry's ``value`` was
    reconstructed from the median of per-source values (i.e. the
    historical export pre-dated the contract-builder pipeline so no
    true blended value was persisted).  The chart renders derived and
    recorded points with the same stroke but lets the legend note the
    reconstruction.

    ``sourceRanks`` is sparse — only populated for snapshots written
    after the rank-history extension (2026-04-29 onward).  Older
    snapshots silently omit per-source ranks; the chart shows fewer
    data points until the rolling 180-day window catches up.

    Case-insensitive name match.  When a name collides across asset
    classes (rare — the scraper collapses offense/IDP same-names
    upstream), pass ``asset_class`` to disambiguate.
    """
    path = path or HISTORY_PATH
    entries = _read_lines(path)
    if not entries:
        return {"dates": [], "blended": [], "sources": {}, "sourceRanks": {}}
    entries.sort(key=lambda e: e.get("date") or "")
    windowed = entries[-max(1, int(days)):]

    needle = name.strip().lower()
    asset = (asset_class or "").strip().lower()

    dates: list[str] = []
    blended: list[dict[str, Any]] = []
    sources_accum: dict[str, list[dict[str, Any]]] = {}
    source_ranks_accum: dict[str, list[dict[str, Any]]] = {}

    for snap in windowed:
        date = snap.get("date")
        if not isinstance(date, str):
            continue
        players = snap.get("players") or {}
        if not isinstance(players, dict):
            continue
        hit_key: str | None = None
        for raw_key in players.keys():
            n, a = _norm_name_key(raw_key)
            if n != needle:
                continue
            if asset and a != asset:
                continue
            hit_key = raw_key
            # Prefer an explicit asset-class match over asset="".
            if asset:
                break
        if hit_key is None:
            continue
        entry = players.get(hit_key)
        if not isinstance(entry, dict):
            continue
        dates.append(date)
        bv = entry.get("blended")
        br = entry.get("blendedRank")
        sources = entry.get("sources") or {}
        ranks = entry.get("sourceRanks") or {}

        # If the snapshot is pre-contract-builder (no blended value
        # persisted) derive an approximate blend from the median of
        # per-source values.  The real pipeline uses a trimmed mean-
        # median + MAD penalty + shrinkage — median alone is within
        # ~5% for most players and tracks the right trend.
        derived = False
        value_out: int | None = None
        if isinstance(bv, (int, float)):
            value_out = int(bv)
        elif isinstance(sources, dict) and sources:
            numeric = [v for v in sources.values() if isinstance(v, (int, float)) and v > 0]
            med = _median(numeric)
            if med is not None:
                value_out = int(round(med))
                derived = True

        blended.append({
            "date": date,
            "value": value_out,
            "rank": int(br) if isinstance(br, (int, float)) else None,
            "derived": derived,
        })
        if isinstance(sources, dict):
            for key, value in sources.items():
                try:
                    v = int(value)
                except (TypeError, ValueError):
                    continue
                sources_accum.setdefault(str(key), []).append({"date": date, "value": v})
        if isinstance(ranks, dict):
            for key, rank_val in ranks.items():
                try:
                    r = int(rank_val)
                except (TypeError, ValueError):
                    continue
                if r <= 0:
                    continue
                source_ranks_accum.setdefault(str(key), []).append(
                    {"date": date, "rank": r}
                )

    return {
        "dates": dates,
        "blended": blended,
        "sources": sources_accum,
        "sourceRanks": source_ranks_accum,
    }


def load_all_player_names(
    *,
    path: Path | None = None,
    days: int = DEFAULT_HISTORY_WINDOW_DAYS,
) -> list[str]:
    """Return every distinct display name seen in the last ``days``
    snapshots.  Useful for admin endpoints; not currently wired.
    """
    path = path or HISTORY_PATH
    entries = _read_lines(path)[-max(1, int(days)):]
    names: set[str] = set()
    for snap in entries:
        players = snap.get("players") or {}
        if not isinstance(players, dict):
            continue
        for raw_key in players.keys():
            n, _ = _norm_name_key(raw_key)
            if n:
                names.add(n)
    return sorted(names)


def backfill_from_exports(
    export_paths: Iterable[Path],
    *,
    path: Path | None = None,
    max_snapshots: int = MAX_SNAPSHOTS,
) -> int:
    """Rebuild the snapshot log from a set of ``dynasty_data_*.json``
    exports.  Returns the number of snapshots written.

    Each export file is expected to have a ``date`` field at the top
    level (set by the scraper).  Duplicate dates are deduped; newest
    export wins.
    """
    path = path or HISTORY_PATH
    snapshots: dict[str, dict[str, Any]] = {}
    for export_path in export_paths:
        try:
            with Path(export_path).open("r", encoding="utf-8") as f:
                contract = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        date = contract.get("date")
        if not isinstance(date, str):
            # Fall back to parsing the filename stem: dynasty_data_YYYY-MM-DD.
            stem = Path(export_path).stem
            for token in stem.split("_"):
                if len(token) == 10 and token[4] == "-" and token[7] == "-":
                    date = token
                    break
        if not isinstance(date, str):
            continue
        players = _extract_all(contract)
        if not players:
            continue
        snapshots[date] = {"date": date, "players": players}

    path.parent.mkdir(parents=True, exist_ok=True)
    # Merge with any existing lines so a partial backfill doesn't
    # clobber days we've already persisted.
    existing = _read_lines(path)
    merged: dict[str, dict[str, Any]] = {}
    for snap in existing:
        d = snap.get("date")
        if isinstance(d, str):
            merged[d] = snap
    for d, snap in snapshots.items():
        merged[d] = snap
    sorted_snaps = [merged[d] for d in sorted(merged.keys())]
    if len(sorted_snaps) > max_snapshots:
        sorted_snaps = sorted_snaps[-max_snapshots:]

    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for snap in sorted_snaps:
            f.write(json.dumps(snap, separators=(",", ":")) + "\n")
    tmp.replace(path)
    return len(snapshots)
