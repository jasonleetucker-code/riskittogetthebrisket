"""Deterministic, idempotent backfill from ``exports/archive/``.

The archive zips are the repo's only retained evidence before the
live recorders began, and they carry the RAW scraper payload — per-site
vendor values, the scraper's own composite, partial Sleeper identity —
and NOT the canonical board (no ``rankDerivedValue``, no
``canonicalConsensusRank``; audit W04-F009 measured 0 of 129 archives
carrying any canonical field).

So this backfill records exactly what the archives prove and nothing
more:

* ``source_value`` observations for the three vendor-published
  top-level fields (``ktc``, ``ktcSfTep``, ``idpTradeCalc``).  These
  are genuine site values in the raw payload; the synthetic encodings
  live under ``_canonicalSiteValues``, which this module deliberately
  never reads.
* ``scraper_blend`` observations for ``_composite`` and
  ``_finalAdjusted`` — the scraper's own blend, a different named
  quantity from canonical value, retained as evidence.

It deliberately does NOT rebuild canonical values by replaying the
payload through today's ``build_api_data_contract`` — that is the
today's-model-presented-as-history pattern the replay spec §12 forbids
and the retired ``scripts/backfill_rank_history.py`` approach
implemented.  A canonical-value query for an archive-only date answers
``unavailable``, which is the truth.

Selection is one bundle per UTC date (the producer's ``manifest.json``
date claim is authoritative over the filename), walking same-day
bundles newest-first so a single corrupt upload cannot drop a day —
the same proven fallback shape the legacy backfill used.  Same input
directory → same selected bundles → same observation rows; a rerun
writes nothing new (idempotence is enforced by the store's identity
key, and verified by the backfill tests).
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any, Iterator

from src.history import keys, store

DEFAULT_ARCHIVE_DIR: Path = Path(__file__).resolve().parents[2] / "exports" / "archive"

_FILENAME_RE = re.compile(r"^dynasty_export_(\d{8})_(\d{6})\.zip$")

ORIGIN_PREFIX = "backfill:archive"

# The vendor-published per-row fields in the raw payload.  Top-level
# keys only — never ``_canonicalSiteValues`` (synthetic encodings).
_RAW_RETAIL_KEYS = ("ktc", "ktcSfTep", "idpTradeCalc")

_BLEND_FIELDS = (("_composite", "composite"), ("_finalAdjusted", "finalAdjusted"))


def _date_from_ymd(ymd: str) -> str:
    return f"{ymd[0:4]}-{ymd[4:6]}-{ymd[6:8]}"


def _iter_candidate_zips(archive_dir: Path) -> Iterator[tuple[str, str, Path]]:
    if not archive_dir.exists() or not archive_dir.is_dir():
        return
    for p in sorted(archive_dir.iterdir()):
        if not p.is_file() or p.suffix != ".zip":
            continue
        m = _FILENAME_RE.match(p.name)
        if not m:
            continue
        yield _date_from_ymd(m.group(1)), m.group(2), p


def _select_by_date(archive_dir: Path) -> list[tuple[str, list[Path]]]:
    by_date: dict[str, list[tuple[str, Path]]] = {}
    for date_str, hms, path in _iter_candidate_zips(archive_dir):
        by_date.setdefault(date_str, []).append((hms, path))
    out: list[tuple[str, list[Path]]] = []
    for date_str in sorted(by_date):
        candidates = sorted(by_date[date_str], key=lambda t: t[0], reverse=True)
        out.append((date_str, [p for _, p in candidates]))
    return out


def _load_raw(zip_path: Path) -> tuple[str | None, dict[str, Any] | None]:
    """(manifest_date, raw_payload) or (None, None) on a corrupt bundle."""
    try:
        with zipfile.ZipFile(zip_path) as z:
            manifest_date: str | None = None
            try:
                with z.open("manifest.json") as mf:
                    manifest = json.load(mf)
                if isinstance(manifest, dict) and isinstance(manifest.get("date"), str):
                    manifest_date = manifest["date"]
            except (KeyError, json.JSONDecodeError):
                pass
            data_name = None
            for n in z.namelist():
                if n.startswith("dynasty_data_") and n.endswith(".json"):
                    data_name = n
                    break
            if data_name is None and "dynasty_data.json" in z.namelist():
                data_name = "dynasty_data.json"
            if data_name is None:
                return manifest_date, None
            with z.open(data_name) as df:
                raw = json.load(df)
            if not isinstance(raw, dict):
                return manifest_date, None
            if manifest_date is None and isinstance(raw.get("date"), str):
                manifest_date = raw["date"]
            return manifest_date, raw
    except (zipfile.BadZipFile, OSError, json.JSONDecodeError):
        return None, None


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def observations_from_raw(
    raw: dict[str, Any],
    *,
    observed_date: str,
    origin: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Ledger observations for one raw scraper payload."""
    players = raw.get("players")
    if not isinstance(players, dict):
        return [], {"rows": 0, "observations": 0, "unresolved": 0}

    sleeper = raw.get("sleeper") if isinstance(raw.get("sleeper"), dict) else {}
    # In the RAW scraper payload the ``sleeper.positions`` map is keyed
    # by display NAME (the contract's id-keyed map is built later, at
    # contract time).  Verified against the real archives.
    positions_by_name = (
        sleeper.get("positions") if isinstance(sleeper.get("positions"), dict) else {}
    )

    observed_at = str(raw.get("scrapeTimestamp") or "") or None
    zone = None
    if observed_at:
        zone = "utc" if ("+" in observed_at or observed_at.endswith("Z")) else "naive"

    out: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for name, row in players.items():
        if not isinstance(row, dict):
            continue
        pick_key = keys.pick_asset_key(name)
        if pick_key is not None:
            asset_key, asset_class = pick_key, keys.ASSET_CLASS_PICK
            position = "PICK"
            player_id = None
        else:
            player_id = str(row.get("_sleeperId") or "") or None
            position = None
            if isinstance(positions_by_name.get(name), str):
                position = positions_by_name[name]
            asset_key = keys.player_asset_key(player_id, name, position)
            if asset_key is None:
                unresolved.append(str(name))
                continue
            group = keys.canonical_position_group(position) if position else ""
            if group == "OFFENSE":
                asset_class = keys.ASSET_CLASS_OFFENSE
            elif group == "IDP":
                asset_class = keys.ASSET_CLASS_IDP
            else:
                asset_class = "unknown"

        base = {
            "asset_key": asset_key,
            "asset_class": asset_class,
            "observed_date": observed_date,
            "observed_at": observed_at,
            "observed_at_zone": zone,
            "display_name": str(name),
            "position": position,
            "player_id": player_id,
            "scope": None,
            "pipeline_version": None,
            "rank": None,
            "tier": None,
            "confidence": None,
            "origin": origin,
        }

        for skey in _RAW_RETAIL_KEYS:
            got = _num(row.get(skey))
            if got is not None:
                out.append({**base, "lane": store.LANE_SOURCE, "source_key": skey, "value": got})

        for field, subkey in _BLEND_FIELDS:
            got = _num(row.get(field))
            if got is not None:
                out.append({**base, "lane": store.LANE_SCRAPER, "source_key": subkey, "value": got})

    return out, {
        "rows": len(players),
        "observations": len(out),
        "unresolved": len(unresolved),
        "unresolvedNames": unresolved[:20],
    }


def backfill_archive(
    archive_dir: Path | None = None,
    *,
    path: Path | None = None,
    dry_run: bool = False,
    since: str | None = None,
) -> dict[str, Any]:
    """Backfill the ledger from every archived date.  Deterministic and
    idempotent; returns full counts including per-date results."""
    archive_dir = archive_dir or DEFAULT_ARCHIVE_DIR
    per_date: list[dict[str, Any]] = []
    totals = {
        "dates": 0,
        "written": 0,
        "duplicates": 0,
        "contentConflicts": 0,
        "rejected": 0,
        "unresolved": 0,
        "unreadableDates": 0,
    }

    for filename_date, candidates in _select_by_date(archive_dir):
        chosen = None
        for candidate in candidates:
            manifest_date, raw = _load_raw(candidate)
            if raw is None:
                continue
            effective_date = manifest_date or filename_date
            if since and effective_date < since:
                chosen = ("skipped-since", None, candidate, effective_date)
                break
            chosen = ("ok", raw, candidate, effective_date)
            break

        if chosen is None:
            totals["unreadableDates"] += 1
            per_date.append({"date": filename_date, "status": "unreadable"})
            continue
        status, raw, zip_path, effective_date = chosen
        if status == "skipped-since":
            continue

        origin = f"{ORIGIN_PREFIX}:zip={zip_path.name}"
        observations, summary = observations_from_raw(
            raw, observed_date=effective_date, origin=origin
        )
        if dry_run:
            per_date.append(
                {
                    "date": effective_date,
                    "zip": zip_path.name,
                    "status": "would-write",
                    "observations": summary["observations"],
                    "unresolved": summary["unresolved"],
                }
            )
            totals["dates"] += 1
            totals["unresolved"] += summary["unresolved"]
            continue

        result = store.write_observations(observations, path=path)
        totals["dates"] += 1
        totals["written"] += result["written"]
        totals["duplicates"] += result["duplicates"]
        totals["contentConflicts"] += len(result["contentConflicts"])
        totals["rejected"] += len(result["rejected"])
        totals["unresolved"] += summary["unresolved"]
        per_date.append(
            {
                "date": effective_date,
                "zip": zip_path.name,
                "status": "written",
                "written": result["written"],
                "duplicates": result["duplicates"],
                "unresolved": summary["unresolved"],
                "rejected": len(result["rejected"]),
            }
        )

    return {"totals": totals, "dates": per_date, "dryRun": dry_run}
