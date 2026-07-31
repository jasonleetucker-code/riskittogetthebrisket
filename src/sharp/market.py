"""Unified Sleeper + FFPC Sharp market signals from normalized movements."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

from src.intel import platform_ledger, signals
from src.sharp import platform_records
from src.sharp import score as sharp_score

REPO_ROOT = Path(__file__).resolve().parents[2]
FFPC_CONFIG_PATH = REPO_ROOT / "config" / "sharp" / "ffpc_sources.json"
_ALLOWED_WINDOWS = ("48h", "7d", "14d", "30d", "90d", "all")
_ALLOWED_SORTS = ("strength", "net", "volume", "velocity", "buys", "sells")
_ALLOWED_PLATFORMS = ("all", "sleeper", "ffpc")
_ALLOWED_QUALIFICATION = ("all", "automated", "curated")


@lru_cache(maxsize=4)
def load_ffpc_config(path: str | None = None) -> dict[str, Any]:
    target = Path(path) if path else FFPC_CONFIG_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


@lru_cache(maxsize=1)
def _local_asset_catalog() -> dict[str, dict[str, Any]]:
    """Best-effort display metadata from existing local snapshots.

    This never performs network I/O on a request.  The FFPC collector
    hydrates the canonical catalog from Sleeper's directory, while this
    fallback lets the Sleeper-only board retain player names before FFPC
    has ever been enabled.
    """
    catalog: dict[str, dict[str, Any]] = {}
    sleeper_path = REPO_ROOT / "data" / "intel" / "ffpc" / "sleeper_players.json"
    try:
        raw = json.loads(sleeper_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if isinstance(raw, dict):
        for source_id, item in raw.items():
            if not isinstance(item, dict):
                continue
            name = str(item.get("full_name") or item.get("search_full_name") or "").strip()
            if name:
                catalog[str(source_id)] = {
                    "displayName": name,
                    "position": str(item.get("position") or "").strip().upper() or None,
                    "nflTeam": str(item.get("team") or "").strip().upper() or None,
                }

    playerctx_path = REPO_ROOT / "data" / "playerctx" / "snapshot.json"
    try:
        snapshot = json.loads(playerctx_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        snapshot = {}
    if isinstance(snapshot, dict):
        players = snapshot.get("players") or {}
        for source_id, record_key in (snapshot.get("sleeperIndex") or {}).items():
            item = players.get(record_key) if isinstance(players, dict) else None
            if not isinstance(item, dict):
                continue
            name = str(
                item.get("fullName")
                or item.get("full_name")
                or item.get("name")
                or item.get("playerName")
                or ""
            ).strip()
            if not name:
                continue
            catalog.setdefault(
                str(source_id),
                {
                    "displayName": name,
                    "position": str(item.get("position") or "").strip().upper() or None,
                    "nflTeam": str(item.get("team") or item.get("nflTeam") or "").strip().upper()
                    or None,
                },
            )
    return catalog


def _fallback_asset_metadata(asset_id: str) -> dict[str, Any]:
    if asset_id.startswith("pick:"):
        parts = asset_id.split(":")
        display = f"{parts[1]} Round {parts[2]} Pick" if len(parts) >= 3 else asset_id
        if len(parts) > 3:
            display += f" ({':'.join(parts[3:])})"
        return {"displayName": display, "position": "PICK", "nflTeam": None}
    return _local_asset_catalog().get(asset_id, {})


@dataclass(frozen=True)
class CohortMember:
    manager_key: str
    platform: str
    qualification_method: str
    quality: float
    display_name: str | None = None
    methodology_version: str | None = None
    source_rationale: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "managerKey": self.manager_key,
            "platform": self.platform,
            "qualificationMethod": self.qualification_method,
            "quality": round(self.quality, 4),
            "displayName": self.display_name,
            "methodologyVersion": self.methodology_version,
            "sourceRationale": self.source_rationale,
        }


def curated_members(config: dict[str, Any]) -> list[CohortMember]:
    out = []
    for raw in config.get("curatedManagers") or []:
        if not isinstance(raw, dict):
            continue
        manager_key = str(raw.get("managerKey") or "").strip()
        if not manager_key.startswith("ffpc:"):
            continue
        if not bool(raw.get("verified")) or not bool(raw.get("allowedToContribute")):
            continue
        weight = max(0.0, min(1.0, float(raw.get("weight") or 0.75)))
        out.append(
            CohortMember(
                manager_key=manager_key,
                platform="ffpc",
                qualification_method="curated_high_stakes",
                quality=weight,
                display_name=str(raw.get("publicDisplayName") or "") or None,
                source_rationale=str(raw.get("sourceRationale") or "") or None,
            )
        )
    return out


def cohort_members(
    *,
    qualification: str = "all",
    ledger_path: Path | None = None,
    ffpc_config: dict[str, Any] | None = None,
) -> tuple[list[CohortMember], dict[str, Any]]:
    if qualification not in _ALLOWED_QUALIFICATION:
        raise ValueError(f"unsupported qualification: {qualification}")
    records, evidence = platform_records.build_manager_records(ledger_path=ledger_path)
    scored = sharp_score.score_managers(records)
    config = ffpc_config if ffpc_config is not None else load_ffpc_config()
    ffpc_enabled = bool(config.get("enabled"))
    automatic = [
        CohortMember(
            manager_key=item.user_id,
            platform=item.user_id.split(":", 1)[0],
            qualification_method="automated_qualified",
            quality=max(0.0, min(1.0, float(item.score or 0.0) / 100.0)),
            methodology_version=item.methodology_version,
        )
        for item in scored
        if item.qualified and (item.user_id.split(":", 1)[0] != "ffpc" or ffpc_enabled)
    ]
    curated_enabled = bool(ffpc_enabled and config.get("allowCuratedInCombinedSignals"))
    curated = curated_members(config) if curated_enabled else []
    if qualification == "automated":
        selected = automatic
    elif qualification == "curated":
        selected = curated
    else:
        selected = [*automatic, *curated]

    # A manager may be explicitly linked to one canonical identity and
    # appear through two methods. Automated qualification wins; otherwise
    # the higher configured quality wins.
    by_key: dict[str, CohortMember] = {}
    for item in selected:
        prior = by_key.get(item.manager_key)
        if (
            prior is None
            or item.qualification_method == "automated_qualified"
            or item.quality > prior.quality
        ):
            by_key[item.manager_key] = item
    coverage = {
        "automatedQualifiedManagers": len(automatic),
        "curatedManagers": len(curated),
        "curatedContributionEnabled": curated_enabled,
        "evidenceManagers": len(evidence),
        "methodologyVersion": sharp_score.methodology_version(),
    }
    return list(by_key.values()), coverage


def _aggregate_window(
    rows: Sequence[dict[str, Any]],
    quality: dict[str, float],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        asset_id = str(row.get("canonicalAssetId") or "")
        if not asset_id:
            continue
        entry = grouped.setdefault(
            asset_id,
            {
                "assetId": asset_id,
                "displayName": row.get("displayName") or asset_id,
                "assetType": row.get("assetType") or "player",
                "nflTeam": row.get("nflTeam"),
                "position": row.get("position"),
                "buys": 0,
                "sells": 0,
                "managerKeys": set(),
                "leagueKeys": set(),
                "transactionKeys": set(),
                "movementKeys": set(),
                "qualityTotal": 0.0,
                "qualityObservations": 0,
                "lastTs": None,
                "sources": {},
            },
        )
        action = row.get("action")
        if action == "add":
            entry["buys"] += 1
        elif action == "drop":
            entry["sells"] += 1
        else:
            continue
        canonical_manager = str(row.get("canonicalManagerKey") or row.get("managerKey"))
        entry["managerKeys"].add(canonical_manager)
        entry["leagueKeys"].add(str(row.get("leagueKey")))
        entry["transactionKeys"].add(str(row.get("transactionKey")))
        entry["movementKeys"].add(str(row.get("movementKey")))
        manager_quality = quality.get(str(row.get("managerKey")), 1.0)
        entry["qualityTotal"] += manager_quality
        entry["qualityObservations"] += 1
        timestamp = int(row.get("timestampMs") or 0)
        if timestamp and (entry["lastTs"] is None or timestamp > entry["lastTs"]):
            entry["lastTs"] = timestamp

        platform = str(row.get("platform") or "unknown")
        source = entry["sources"].setdefault(
            platform,
            {
                "buys": 0,
                "sells": 0,
                "managerKeys": set(),
                "leagueKeys": set(),
                "transactionKeys": set(),
                "movementKeys": set(),
                "lastTs": None,
            },
        )
        source["buys" if action == "add" else "sells"] += 1
        source["managerKeys"].add(canonical_manager)
        source["leagueKeys"].add(str(row.get("leagueKey")))
        source["transactionKeys"].add(str(row.get("transactionKey")))
        source["movementKeys"].add(str(row.get("movementKey")))
        if timestamp and (source["lastTs"] is None or timestamp > source["lastTs"]):
            source["lastTs"] = timestamp

    output: dict[str, dict[str, Any]] = {}
    for asset_id, entry in grouped.items():
        fallback = _fallback_asset_metadata(asset_id)
        if not entry.get("displayName") or entry.get("displayName") == asset_id:
            entry["displayName"] = fallback.get("displayName") or asset_id
        entry["position"] = entry.get("position") or fallback.get("position")
        entry["nflTeam"] = entry.get("nflTeam") or fallback.get("nflTeam")
        buys, sells = entry["buys"], entry["sells"]
        volume = buys + sells
        sources = {}
        for platform, source in entry["sources"].items():
            source_volume = source["buys"] + source["sells"]
            sources[platform] = {
                "buys": source["buys"],
                "sells": source["sells"],
                "net": source["buys"] - source["sells"],
                "volume": source_volume,
                "uniqueManagers": len(source["managerKeys"]),
                "uniqueLeagues": len(source["leagueKeys"]),
                "tradeCount": len(source["transactionKeys"]),
                "movementCount": len(source["movementKeys"]),
                "lastTs": source["lastTs"],
            }
        output[asset_id] = {
            "assetId": asset_id,
            "displayName": entry["displayName"],
            "assetType": entry["assetType"],
            "nflTeam": entry["nflTeam"],
            "position": entry["position"],
            "buys": buys,
            "sells": sells,
            "net": buys - sells,
            "volume": volume,
            "buyRate": buys / volume if volume else None,
            "uniqueManagers": len(entry["managerKeys"]),
            "uniqueLeagues": len(entry["leagueKeys"]),
            "tradeCount": len(entry["transactionKeys"]),
            "movementCount": len(entry["movementKeys"]),
            "lastTs": entry["lastTs"],
            # Observation-weighted mean of the actual managers who made
            # each movement. This replaces the previous cohort-wide mean.
            "managerQuality": (
                entry["qualityTotal"] / entry["qualityObservations"]
                if entry["qualityObservations"]
                else 1.0
            ),
            "sources": sources,
        }
    return output


def _sort_rows(rows: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    def key(row: dict[str, Any]):
        if sort == "volume":
            return (-row["volume"], -abs(row["net"]), row["assetId"])
        if sort == "velocity":
            return (-(row.get("velocity") or 0.0), -row["volume"], row["assetId"])
        if sort == "buys":
            return (-row["buys"], -row["volume"], row["assetId"])
        if sort == "sells":
            return (-row["sells"], -row["volume"], row["assetId"])
        if sort == "net":
            return (-row["net"], -row["volume"], row["assetId"])
        return (-row["signalStrength"], -row["volume"], row["assetId"])

    return sorted(rows, key=key)


def market_payload(
    *,
    window: str = "30d",
    sort: str = "strength",
    asset_type: str = "all",
    platform: str = "all",
    qualification: str = "all",
    limit: int = 100,
    now_ms: int | None = None,
    ledger_path: Path | None = None,
    ffpc_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if window not in _ALLOWED_WINDOWS:
        raise ValueError(f"window must be one of {_ALLOWED_WINDOWS}")
    if sort not in _ALLOWED_SORTS:
        raise ValueError(f"sort must be one of {_ALLOWED_SORTS}")
    if asset_type not in ("all", "player", "pick"):
        raise ValueError("assetType must be player|pick|all")
    if platform not in _ALLOWED_PLATFORMS:
        raise ValueError(f"platform must be one of {_ALLOWED_PLATFORMS}")
    limit = max(1, min(500, int(limit)))
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    config = ffpc_config if ffpc_config is not None else load_ffpc_config()
    members, cohort_coverage = cohort_members(
        qualification=qualification,
        ledger_path=ledger_path,
        ffpc_config=config,
    )
    manager_keys = [item.manager_key for item in members]
    quality = {item.manager_key: item.quality for item in members}
    platforms = None if platform == "all" else [platform]

    needed_windows = list(dict.fromkeys((window, "48h", "30d")))
    per_window: dict[str, dict[str, dict[str, Any]]] = {}
    for name in needed_windows:
        since, until = signals.window_bounds(name, now)
        movements = platform_ledger.query_movements(
            manager_keys=manager_keys,
            since_ms=since,
            until_ms=until,
            platforms=platforms,
            asset_type=asset_type,
            canonical_only=True,
            path=ledger_path,
        )
        per_window[name] = _aggregate_window(movements, quality)

    primary = per_window.get(window, {})
    short = per_window.get("48h", {})
    long = per_window.get("30d", {})
    rows = []
    for asset_id, item in primary.items():
        short_item = short.get(asset_id)
        long_item = long.get(asset_id)
        velocity = signals.velocity(
            {**short_item, "_spanMs": signals.WINDOWS_MS["48h"]} if short_item else None,
            {**long_item, "_spanMs": signals.WINDOWS_MS["30d"]} if long_item else None,
        )
        strength = signals.signal_strength(
            net=item["net"],
            volume=item["volume"],
            unique_managers=item["uniqueManagers"],
            manager_quality=item["managerQuality"],
        )
        confidence = signals.confidence_tier(
            item["volume"], item["uniqueManagers"], item["uniqueLeagues"]
        )
        source_labels = [
            "Sleeper" if value == "sleeper" else "FFPC" if value == "ffpc" else value
            for value in sorted(item["sources"])
        ]
        rows.append(
            {
                "assetId": asset_id,
                "displayName": item["displayName"],
                "assetType": item["assetType"],
                "nflTeam": item.get("nflTeam"),
                "position": item.get("position"),
                "buys": item["buys"],
                "sells": item["sells"],
                "net": item["net"],
                "volume": item["volume"],
                "uniqueManagers": item["uniqueManagers"],
                "uniqueLeagues": item["uniqueLeagues"],
                "tradeCount": item["tradeCount"],
                "movementCount": item["movementCount"],
                "windows": {
                    window: {
                        k: item[k]
                        for k in (
                            "buys",
                            "sells",
                            "net",
                            "volume",
                            "buyRate",
                            "uniqueManagers",
                            "uniqueLeagues",
                            "tradeCount",
                            "movementCount",
                            "lastTs",
                        )
                    }
                },
                "sources": item["sources"],
                "sourceCount": len(item["sources"]),
                "sourceLabels": source_labels,
                "signalStrength": strength,
                "confidence": confidence,
                "velocity": velocity,
                "managerQuality": round(item["managerQuality"], 4),
                "lastTs": item["lastTs"],
            }
        )
    rows = _sort_rows(rows, sort)[:limit]

    source_coverage = platform_ledger.platform_coverage(ledger_path)
    coverage_members, _coverage_meta = cohort_members(
        qualification="all",
        ledger_path=ledger_path,
        ffpc_config=config,
    )
    automated_by_platform = {"sleeper": 0, "ffpc": 0}
    curated_by_platform = {"sleeper": 0, "ffpc": 0}
    for item in coverage_members:
        target = (
            automated_by_platform
            if item.qualification_method == "automated_qualified"
            else curated_by_platform
        )
        target[item.platform] = target.get(item.platform, 0) + 1
    for name, value in source_coverage.items():
        value["qualifiedManagers"] = automated_by_platform.get(name, 0)
        value["automatedQualifiedManagers"] = automated_by_platform.get(name, 0)
        value["curatedManagers"] = curated_by_platform.get(name, 0)
        value["enabled"] = name != "ffpc" or bool(config.get("enabled"))
        if name == "ffpc" and not config.get("enabled"):
            value["status"] = "disabled"
        elif (value.get("latestIngestion") or {}).get("status") == "failed":
            value["status"] = "degraded"
        elif value.get("lastUpdatedAt") is None:
            value["status"] = "no_data"
        else:
            value["status"] = "ok"

    return {
        "status": "ok" if manager_keys else "cohort_building",
        "generatedAt": now,
        "methodologyVersion": sharp_score.methodology_version(),
        "query": {
            "window": window,
            "sort": sort,
            "assetType": asset_type,
            "platform": platform,
            "qualification": qualification,
            "limit": limit,
        },
        "assets": rows,
        "cohort": {
            **cohort_coverage,
            "selectedManagers": len(members),
            "qualificationMethods": sorted({m.qualification_method for m in members}),
        },
        "coverage": {
            "platforms": source_coverage,
            "unmappedAssets": len(platform_ledger.unmapped_assets(ledger_path, platform="ffpc")),
        },
        "formula": {
            "managerQuality": (
                "observation-weighted mean of each contributing manager's Sharp Score/100 "
                "or configured curated weight"
            ),
            "signalStrength": (
                "normalized net × sample confidence × manager breadth × asset manager quality"
            ),
            "windows": "each window is independently filtered from raw normalized movements",
        },
    }


def audit_payload(
    canonical_asset_id: str,
    *,
    window: str = "30d",
    qualification: str = "all",
    ledger_path: Path | None = None,
    ffpc_config: dict[str, Any] | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    members, _ = cohort_members(
        qualification=qualification,
        ledger_path=ledger_path,
        ffpc_config=ffpc_config,
    )
    methods = {m.manager_key: m.qualification_method for m in members}
    since, until = signals.window_bounds(window, now)
    rows = platform_ledger.audit_asset(
        canonical_asset_id,
        manager_keys=list(methods),
        since_ms=since,
        until_ms=until,
        path=ledger_path,
    )
    for row in rows:
        row["qualificationMethod"] = methods.get(row["manager"])
    return {
        "assetId": canonical_asset_id,
        "window": window,
        "movements": rows,
        "movementCount": len(rows),
    }
