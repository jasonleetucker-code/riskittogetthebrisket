from __future__ import annotations

from collections import defaultdict

from src.data_models import RawAssetRecord
from src.identity.schema import MasterPlayer
from src.utils import normalize_player_name


def build_master_players(records: list[RawAssetRecord]) -> tuple[dict[str, MasterPlayer], list[str]]:
    """
    Phase-1 identity bootstrap:
    - key by normalized name
    - retain aliases and capture light conflicts for manual review
    """
    players: dict[str, MasterPlayer] = {}
    conflicts: list[str] = []
    seen_positions: dict[str, set[str]] = defaultdict(set)
    seen_names: dict[str, set[str]] = defaultdict(set)

    for rec in records:
        if rec.asset_type != "player":
            continue
        norm = normalize_player_name(rec.display_name)
        if not norm:
            continue
        pid = f"player::{norm}"
        if pid not in players:
            players[pid] = MasterPlayer(
                player_id=pid,
                display_name=rec.display_name,
                normalized_name=norm,
                position_family=rec.position or "",
                team=rec.team or "",
                aliases={rec.display_name},
                metadata={"sources": {rec.source_id}},
            )
        else:
            players[pid].aliases.add(rec.display_name)
            sources = set(players[pid].metadata.get("sources", set()))
            sources.add(rec.source_id)
            players[pid].metadata["sources"] = sources

        seen_positions[pid].add(rec.position or "")
        seen_names[pid].add(rec.display_name)

    for pid, pos_set in seen_positions.items():
        pos_clean = {p for p in pos_set if p}
        if len(pos_clean) > 1:
            conflicts.append(f"{pid}: multiple position families detected {sorted(pos_clean)}")

    # Convert non-serializable set to list for consistent downstream writes.
    for p in players.values():
        srcs = p.metadata.get("sources", set())
        if isinstance(srcs, set):
            p.metadata["sources"] = sorted(srcs)
    return players, conflicts


def build_identity_report(records: list[RawAssetRecord]) -> dict:
    """
    Produce a lightweight identity quality report for Phase-1 pipeline auditing.
    """
    players, conflicts = build_master_players(records)
    coverage: dict[str, set[str]] = defaultdict(set)
    unresolved: list[dict] = []

    for rec in records:
        if rec.asset_type != "player":
            continue
        norm = normalize_player_name(rec.display_name)
        if not norm:
            unresolved.append(
                {
                    "display_name": rec.display_name,
                    "source_id": rec.source_id,
                    "reason": "empty_normalized_name",
                }
            )
            continue
        coverage[f"player::{norm}"].add(rec.source_id)

    single_source: list[dict] = []
    for pid, sources in coverage.items():
        if len(sources) == 1:
            p = players.get(pid)
            single_source.append(
                {
                    "player_id": pid,
                    "display_name": p.display_name if p else pid,
                    "sources": sorted(sources),
                }
            )

    multi_source: list[dict] = []
    for pid, sources in coverage.items():
        if len(sources) > 1:
            p = players.get(pid)
            multi_source.append(
                {
                    "player_id": pid,
                    "display_name": p.display_name if p else pid,
                    "sources": sorted(sources),
                }
            )

    report = {
        "record_count": len(records),
        "player_record_count": sum(1 for r in records if r.asset_type == "player"),
        "master_player_count": len(players),
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
        "unresolved_count": len(unresolved),
        "unresolved_records": unresolved,
        "single_source_count": len(single_source),
        "single_source_players": single_source,
        "multi_source_count": len(multi_source),
        "multi_source_players": multi_source,
    }
    return report
