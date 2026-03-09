from __future__ import annotations

from collections import defaultdict

from src.data_models import RawAssetRecord, utc_now_iso
from src.identity.models import PickAliasRow, PickRow, PlayerAliasRow, PlayerRow
from src.identity.schema import MasterPlayer
from src.utils import normalize_player_name

MATCH_QUARANTINE_THRESHOLD = 0.90


def _confidence_for_record(rec: RawAssetRecord) -> tuple[float, str]:
    """
    Confidence ladder (non-negotiable rules):
    - 1.00 exact external ID
    - 0.98 exact normalized name + team + position
    - 0.93 exact normalized name + position
    - 0.85 exact normalized name only (quarantine/manual bucket)
    """
    if str(rec.external_asset_id).strip():
        return 1.00, "exact_id"
    has_team = bool((rec.team_normalized_guess or rec.team_raw).strip())
    has_pos = bool((rec.position_normalized_guess or rec.position_raw).strip())
    if has_team and has_pos:
        return 0.98, "exact_name_team_position"
    if has_pos:
        return 0.93, "exact_name_position"
    return 0.85, "exact_name_only"


def build_master_players(records: list[RawAssetRecord]) -> tuple[dict[str, MasterPlayer], list[str]]:
    players: dict[str, MasterPlayer] = {}
    conflicts: list[str] = []
    seen_positions: dict[str, set[str]] = defaultdict(set)

    for rec in records:
        if rec.asset_type != "player":
            continue
        norm = rec.name_normalized_guess or normalize_player_name(rec.display_name)
        if not norm:
            continue
        pid = f"player::{norm}"
        if pid not in players:
            players[pid] = MasterPlayer(
                player_id=pid,
                display_name=rec.display_name,
                normalized_name=norm,
                position_family=rec.position_normalized_guess or rec.position_raw or "",
                team=rec.team_normalized_guess or rec.team_raw or "",
                aliases={rec.display_name},
                metadata={"sources": {rec.source}},
            )
        else:
            players[pid].aliases.add(rec.display_name)
            srcs = set(players[pid].metadata.get("sources", set()))
            srcs.add(rec.source)
            players[pid].metadata["sources"] = srcs
        seen_positions[pid].add(rec.position_normalized_guess or rec.position_raw or "")

    for pid, pos_set in seen_positions.items():
        pos_clean = {p for p in pos_set if p}
        if len(pos_clean) > 1:
            conflicts.append(f"{pid}: multiple position families detected {sorted(pos_clean)}")

    for p in players.values():
        srcs = p.metadata.get("sources", set())
        if isinstance(srcs, set):
            p.metadata["sources"] = sorted(srcs)
    return players, conflicts


def build_identity_resolution(
    records: list[RawAssetRecord],
    quarantine_threshold: float = MATCH_QUARANTINE_THRESHOLD,
) -> dict:
    now = utc_now_iso()
    players_master, conflicts = build_master_players(records)

    players_rows: dict[str, PlayerRow] = {}
    player_aliases: list[PlayerAliasRow] = []
    picks_rows: dict[str, PickRow] = {}
    pick_aliases: list[PickAliasRow] = []
    unresolved: list[dict] = []
    low_confidence: list[dict] = []

    ext_alias_owner: dict[tuple[str, str], str] = {}
    duplicate_aliases: list[dict] = []

    for idx, rec in enumerate(records, start=1):
        if rec.asset_type == "player":
            norm = rec.name_normalized_guess or normalize_player_name(rec.display_name)
            if not norm:
                unresolved.append(
                    {
                        "source": rec.source,
                        "snapshot_id": rec.snapshot_id,
                        "external_name": rec.external_name,
                        "reason": "empty_normalized_name",
                    }
                )
                continue

            player_id = f"player::{norm}"
            confidence, method = _confidence_for_record(rec)

            if player_id not in players_rows:
                players_rows[player_id] = PlayerRow(
                    player_id=player_id,
                    sleeper_id="",
                    full_name=rec.display_name,
                    search_name=norm,
                    team=rec.team_normalized_guess or rec.team_raw,
                    position=rec.position_normalized_guess or rec.position_raw,
                    position_group=rec.position_normalized_guess or rec.position_raw,
                    rookie_class_year=rec.pick_year_guess if rec.rookie_flag else None,
                    age=float(rec.age_raw) if str(rec.age_raw).strip().replace(".", "", 1).isdigit() else None,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
            else:
                players_rows[player_id].updated_at = now

            alias_id = f"palias::{rec.source}::{idx}"
            alias = PlayerAliasRow(
                alias_id=alias_id,
                player_id=player_id,
                source=rec.source,
                external_asset_id=rec.external_asset_id,
                external_name=rec.external_name or rec.display_name,
                name_normalized=norm,
                team_raw=rec.team_raw,
                position_raw=rec.position_raw,
                match_confidence=confidence,
                match_method=method,
                first_seen_snapshot_id=rec.snapshot_id,
                last_seen_snapshot_id=rec.snapshot_id,
            )
            player_aliases.append(alias)

            if confidence < quarantine_threshold:
                low_confidence.append(
                    {
                        "player_id": player_id,
                        "external_name": rec.external_name or rec.display_name,
                        "source": rec.source,
                        "match_confidence": confidence,
                        "match_method": method,
                    }
                )

            if rec.external_asset_id:
                key = (rec.source, rec.external_asset_id)
                owner = ext_alias_owner.get(key)
                if owner is None:
                    ext_alias_owner[key] = player_id
                elif owner != player_id:
                    duplicate_aliases.append(
                        {
                            "source": rec.source,
                            "external_asset_id": rec.external_asset_id,
                            "player_a": owner,
                            "player_b": player_id,
                        }
                    )

        elif rec.asset_type == "pick":
            year = rec.pick_year_guess or 0
            rnd = rec.pick_round_guess or 0
            slot_known = bool(rec.pick_slot_guess and rec.pick_slot_guess.replace(".", "").isdigit())
            slot_number = None
            if slot_known:
                try:
                    slot_number = int(float(rec.pick_slot_guess))
                except (TypeError, ValueError):
                    slot_number = None
            pick_id = rec.asset_key or f"pick::{year}::{rnd}::{rec.pick_slot_guess or 'UNKNOWN'}"
            if pick_id not in picks_rows:
                picks_rows[pick_id] = PickRow(
                    pick_id=pick_id,
                    season=year,
                    round=rnd,
                    slot_known=slot_known,
                    slot_number=slot_number,
                    bucket=rec.pick_slot_guess if not slot_known else "",
                    league_id="",
                    description=rec.display_name,
                    created_at=now,
                )
            confidence, method = _confidence_for_record(rec)
            pick_aliases.append(
                PickAliasRow(
                    pick_alias_id=f"pkalias::{rec.source}::{idx}",
                    pick_id=pick_id,
                    source=rec.source,
                    external_asset_id=rec.external_asset_id,
                    external_name=rec.external_name or rec.display_name,
                    year_guess=rec.pick_year_guess,
                    round_guess=rec.pick_round_guess,
                    bucket_guess=rec.pick_slot_guess,
                    match_confidence=confidence,
                    match_method=method,
                )
            )

    coverage: dict[str, set[str]] = defaultdict(set)
    for rec in records:
        if rec.asset_type != "player":
            continue
        norm = rec.name_normalized_guess or normalize_player_name(rec.display_name)
        if norm:
            coverage[f"player::{norm}"].add(rec.source)

    single_source = []
    multi_source = []
    for pid, sources in coverage.items():
        row = players_rows.get(pid)
        item = {
            "player_id": pid,
            "display_name": row.full_name if row else pid,
            "sources": sorted(sources),
        }
        if len(sources) == 1:
            single_source.append(item)
        else:
            multi_source.append(item)

    return {
        "generated_at": now,
        "quarantine_threshold": quarantine_threshold,
        "record_count": len(records),
        "master_player_count": len(players_rows),
        "player_alias_count": len(player_aliases),
        "pick_count": len(picks_rows),
        "pick_alias_count": len(pick_aliases),
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
        "duplicate_alias_count": len(duplicate_aliases),
        "duplicate_aliases": duplicate_aliases,
        "unresolved_count": len(unresolved),
        "unresolved_records": unresolved,
        "low_confidence_count": len(low_confidence),
        "low_confidence_matches": low_confidence,
        "single_source_count": len(single_source),
        "single_source_players": single_source,
        "multi_source_count": len(multi_source),
        "multi_source_players": multi_source,
        "players": [p.to_dict() for p in players_rows.values()],
        "player_aliases": [a.to_dict() for a in player_aliases],
        "picks": [p.to_dict() for p in picks_rows.values()],
        "pick_aliases": [a.to_dict() for a in pick_aliases],
    }


def build_identity_report(records: list[RawAssetRecord]) -> dict:
    """
    Backward-compatible alias for existing scaffold call sites.
    """
    return build_identity_resolution(records)

