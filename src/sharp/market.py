"""Unified Sleeper + FFPC Sharp market signals from normalized movements.

The MANAGER POOL this board reads is not defined here — it comes from
``src/sharp/cohort.py``, which is the one definition shared with every
other sharp feature (today: the Sharp Roster Percentage board).  The
cohort names are re-exported below so ``sharp_market.cohort_members``
and ``sharp_market.CohortMember`` keep resolving for existing callers
and tests, and so ``market_payload`` still reads ``cohort_members`` as
a module global that tests can monkeypatch.
"""

from __future__ import annotations

import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

from src.intel import platform_ledger, signals
from src.utils.share_cap import apply_share_cap
from src.sharp import consensus

# Re-exported for the same reason as the cohort names below: the curated
# population moved to ``cohort.py``, but tests patch
# ``market.curated_model.curated_cohort_members`` to isolate themselves from
# the real curated store.  ``curated_model`` is the MODULE object, shared with
# ``cohort``, so patching an attribute on it still reaches the live caller.
from src.sharp import curated as curated_model  # noqa: F401 — patched seam
from src.sharp import platform_records  # noqa: F401 — patched seam
from src.sharp import score as sharp_score
from src.sharp.cohort import (  # noqa: F401 — re-exported shared cohort surface
    ALLOWED_QUALIFICATION as _ALLOWED_QUALIFICATION,
)
from src.sharp.cohort import (  # noqa: F401
    FFPC_CONFIG_PATH,
    CohortMember,
    cohort_members,
    curated_industry_members,
    curated_members,
    load_ffpc_config,
    provisional_members,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
# Quality assigned to a movement whose manager is not in the cohort map.
# Deliberately the FLOOR, not 1.0: a qualified member's quality is
# `score / 100` and so is always below 1.0, which made the old 1.0
# default rank an unrecognised manager above every genuine sharp. An
# unknown contributor should count for the least, not the most.
UNMATCHED_MANAGER_QUALITY = 0.0

# Ceiling on any one manager's / league's share of an asset's evidence.
# Matches `config/consensus_edge/params_v1.json` (0.34 each, ADR-011) on
# purpose: the two boards aggregate the same movements from the same
# cohort, and letting them bound concentration differently would mean
# "the sharps are buying him" meant two different things on two pages.
_CONCENTRATION_CAPS = {"manager": 0.34, "league": 0.34}

_ALLOWED_WINDOWS = ("48h", "7d", "14d", "30d", "90d", "all")
_ALLOWED_SORTS = ("strength", "net", "volume", "velocity", "buys", "sells")
_ALLOWED_PLATFORMS = ("all", "sleeper", "ffpc")


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


def _capped_buy_sell(entry: dict[str, Any]) -> tuple[float, float]:
    """Buy/sell counts with per-manager and per-league concentration capped.

    Consensus Edge has bounded this since ADR-011; ``src/sharp`` did not
    bound it at all, so one manager active in ten leagues contributed ten
    observations and ``breadth_factor = m/(m+3)`` saturated far too fast
    to push back. Same shared implementation, same declared shares.

    Returns FRACTIONAL weights, which is why they are reported beside the
    integer counts rather than replacing them: ``volume``, ``tradeCount``
    and ``uniqueManagers`` keep answering "what happened", and these
    answer "how much of it should count". Conflating the two would make
    the board misreport its own evidence.

    Buys and sells are scaled by the SAME per-contributor factor, so a
    cap can shrink a lean but can never flip its direction.
    """
    caps = _CONCENTRATION_CAPS
    scales: list[dict[str, float]] = []
    for bucket, share in (("byManager", caps["manager"]), ("byLeague", caps["league"])):
        totals = {k: float(v["buys"] + v["sells"]) for k, v in (entry.get(bucket) or {}).items()}
        capped = apply_share_cap(totals, share)
        scales.append({k: (capped[k] / v if v > 0 else 1.0) for k, v in totals.items()})
    mgr_scale, lg_scale = scales

    buys = sells = 0.0
    for manager, tally in (entry.get("byManager") or {}).items():
        # A manager's movements are spread across leagues, so the league
        # factor cannot be read off the manager bucket. Apply the manager
        # factor here and the league factor in the second pass, matching
        # how `sharp_flow.aggregate_asset` composes them per movement.
        factor = mgr_scale.get(manager, 1.0)
        buys += tally["buys"] * factor
        sells += tally["sells"] * factor
    total_mgr = buys + sells
    lg_total = sum(
        (tally["buys"] + tally["sells"]) * lg_scale.get(league, 1.0)
        for league, tally in (entry.get("byLeague") or {}).items()
    )
    raw_total = float(entry["buys"] + entry["sells"])
    if raw_total > 0 and total_mgr > 0:
        league_factor = (lg_total / raw_total) if raw_total else 1.0
        buys *= league_factor
        sells *= league_factor
    return buys, sells


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
                # Per-contributor tallies, so concentration can be capped
                # at output time. One manager active in ten leagues used
                # to contribute ten unbounded observations.
                "byManager": {},
                "byLeague": {},
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
        # Canonical key first, raw key as the fallback — the same order
        # the breadth dedup above uses. The two used to disagree: breadth
        # counted `canonicalManagerKey` while quality looked up the raw
        # `managerKey`, so one human's linked accounts deduped to one
        # manager for breadth and were priced by whichever raw key each
        # movement carried.
        #
        # The default is UNMATCHED_MANAGER_QUALITY, not 1.0. A cohort
        # member's quality is `score/100` and is always below 1.0, so
        # defaulting an unrecognised manager to 1.0 ranked them ABOVE
        # every genuine sharp — an inversion that is currently
        # unreachable (`query_movements` filters on the same key list
        # this map is built from, so every row's key is present) but is
        # one join change away from being live, and would fail in the
        # flattering direction.
        manager_quality = quality.get(
            canonical_manager,
            quality.get(str(row.get("managerKey")), UNMATCHED_MANAGER_QUALITY),
        )
        entry["qualityTotal"] += manager_quality
        entry["qualityObservations"] += 1
        league_key = str(row.get("leagueKey"))
        is_buy = action == "add"
        for bucket, key in (("byManager", canonical_manager), ("byLeague", league_key)):
            tally = entry[bucket].setdefault(key, {"buys": 0, "sells": 0})
            tally["buys" if is_buy else "sells"] += 1
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
        weighted_buys, weighted_sells = _capped_buy_sell(entry)
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
            # RAW counts: what actually happened. Left integer and
            # uncapped on purpose — `volume`, `tradeCount` and
            # `uniqueManagers` are evidence descriptions, and a capped
            # number in those fields would misreport the record.
            "buys": buys,
            "sells": sells,
            "net": buys - sells,
            "volume": volume,
            "buyRate": buys / volume if volume else None,
            # CAPPED weights: how much of it should count. Per-manager
            # and per-league concentration bounded at 0.34 each, the same
            # bound Consensus Edge applies. These are what `strength`
            # is computed from.
            "weightedBuys": round(weighted_buys, 4),
            "weightedSells": round(weighted_sells, 4),
            "weightedNet": round(weighted_buys - weighted_sells, 4),
            "weightedVolume": round(weighted_buys + weighted_sells, 4),
            "concentrationCapped": (
                round(weighted_buys + weighted_sells, 4) < round(float(volume), 4)
            ),
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
    network_by_manager = {item.manager_key: item.network for item in members}
    platforms = None if platform == "all" else [platform]

    needed_windows = list(dict.fromkeys((window, "48h", "30d")))
    per_window: dict[str, dict[str, dict[str, Any]]] = {}
    person_view: dict[str, dict[str, Any]] = {}
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
        if name == window:
            # One vote per PERSON, with a diminishing-independence discount for
            # analysts sharing an outlet. Movement counts above stay untouched
            # and remain the audit trail -- this is an additional lens, not a
            # replacement, so a person's ten leagues stop reading as ten
            # independent experts without any raw data being hidden.
            person_view = consensus.aggregate_person_consensus(
                movements, quality, network_by_manager
            )

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
        # Strength reads the CAPPED weights. This is the whole point of
        # the cap: `net`/`volume` describe the record and must stay raw,
        # while the number a user acts on must not be ten observations
        # from one manager wearing the authority of ten managers.
        strength = signals.signal_strength(
            net=item.get("weightedNet", item["net"]),
            volume=item.get("weightedVolume", item["volume"]),
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
        person = person_view.get(asset_id) or {}
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
                # Person-level consensus for THIS window only. Never summed
                # with another window, and never a substitute for the movement
                # counts above.
                "personConsensus": person or None,
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
                            # The capped weights travel with the raw
                            # counts. A consumer that sees `volume: 10`
                            # and no `weightedVolume` cannot tell one
                            # manager from ten, which is the whole
                            # distinction the cap exists to draw.
                            "weightedBuys",
                            "weightedSells",
                            "weightedNet",
                            "weightedVolume",
                            "concentrationCapped",
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
    provisional_by_platform = {"sleeper": 0, "ffpc": 0}
    for item in coverage_members:
        if item.qualification_method == "automated_qualified":
            target = automated_by_platform
        elif item.qualification_method == "curated_high_stakes":
            target = curated_by_platform
        else:
            target = provisional_by_platform
        target[item.platform] = target.get(item.platform, 0) + 1
    for name, value in source_coverage.items():
        value["qualifiedManagers"] = automated_by_platform.get(name, 0)
        value["automatedQualifiedManagers"] = automated_by_platform.get(name, 0)
        value["curatedManagers"] = curated_by_platform.get(name, 0)
        value["provisionalManagers"] = provisional_by_platform.get(name, 0)
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
