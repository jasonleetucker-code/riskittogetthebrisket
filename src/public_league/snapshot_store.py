"""Persistence layer for the public league snapshot.

Writes a normalized snapshot + assembled public contract to
``data/public_league/`` so the backend can serve the public
``/api/public/league*`` routes from disk on cold start (and so the
full history is replayable without hitting Sleeper live).

Files:
    data/public_league/snapshot.json   — raw Sleeper payloads per season
    data/public_league/contract.json   — assembled public contract
    data/public_league/identity.json   — compact manager registry
    data/public_league/nfl_players.json — cached players/nfl dump
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .identity import Manager, ManagerRegistry, TeamAlias
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "public_league"
SNAPSHOT_PATH = DATA_DIR / "snapshot.json"
CONTRACT_PATH = DATA_DIR / "contract.json"
IDENTITY_PATH = DATA_DIR / "identity.json"
NFL_PLAYERS_PATH = DATA_DIR / "nfl_players.json"


def _season_to_dict(season: SeasonSnapshot) -> dict[str, Any]:
    return {
        "season": season.season,
        "leagueId": season.league_id,
        "league": season.league,
        "users": season.users,
        "rosters": season.rosters,
        "matchupsByWeek": {str(k): v for k, v in season.matchups_by_week.items()},
        "transactionsByWeek": {str(k): v for k, v in season.transactions_by_week.items()},
        "drafts": season.drafts,
        "draftPicksByDraft": season.draft_picks_by_draft,
        "tradedPicks": season.traded_picks,
        "winnersBracket": season.winners_bracket,
        "losersBracket": season.losers_bracket,
    }


def _season_from_dict(d: dict[str, Any]) -> SeasonSnapshot:
    return SeasonSnapshot(
        season=str(d.get("season") or ""),
        league_id=str(d.get("leagueId") or ""),
        league=d.get("league") or {},
        users=d.get("users") or [],
        rosters=d.get("rosters") or [],
        matchups_by_week={int(k): v for k, v in (d.get("matchupsByWeek") or {}).items()},
        transactions_by_week={int(k): v for k, v in (d.get("transactionsByWeek") or {}).items()},
        drafts=d.get("drafts") or [],
        draft_picks_by_draft=d.get("draftPicksByDraft") or {},
        traded_picks=d.get("tradedPicks") or [],
        winners_bracket=d.get("winnersBracket") or [],
        losers_bracket=d.get("losersBracket") or [],
    )


def _manager_to_dict(m: Manager) -> dict[str, Any]:
    return {
        "ownerId": m.owner_id,
        "displayName": m.display_name,
        "avatar": m.avatar,
        "currentRosterId": m.current_roster_id,
        "currentTeamName": m.current_team_name,
        "currentLeagueId": m.current_league_id,
        "aliases": [asdict(a) for a in m.aliases],
    }


def _registry_to_dict(reg: ManagerRegistry) -> dict[str, Any]:
    return {
        "byOwnerId": {oid: _manager_to_dict(m) for oid, m in reg.by_owner_id.items()},
        "rosterToOwner": [
            {"leagueId": lid, "rosterId": rid, "ownerId": owner}
            for (lid, rid), owner in reg.roster_to_owner.items()
        ],
    }


def _registry_from_dict(d: dict[str, Any]) -> ManagerRegistry:
    reg = ManagerRegistry()
    for oid, row in (d.get("byOwnerId") or {}).items():
        m = Manager(
            owner_id=str(oid),
            display_name=str(row.get("displayName") or ""),
            avatar=str(row.get("avatar") or ""),
            current_roster_id=row.get("currentRosterId"),
            current_team_name=str(row.get("currentTeamName") or ""),
            current_league_id=str(row.get("currentLeagueId") or ""),
            aliases=[
                TeamAlias(
                    season=str(a.get("season") or ""),
                    league_id=str(a.get("league_id") or ""),
                    team_name=str(a.get("team_name") or ""),
                    display_name=str(a.get("display_name") or ""),
                    avatar=str(a.get("avatar") or ""),
                    roster_id=a.get("roster_id"),
                )
                for a in (row.get("aliases") or [])
            ],
        )
        reg.by_owner_id[str(oid)] = m
    for entry in d.get("rosterToOwner") or []:
        try:
            lid = str(entry.get("leagueId") or "")
            rid = int(entry.get("rosterId"))
            owner = str(entry.get("ownerId") or "")
        except (TypeError, ValueError):
            continue
        if lid and owner:
            reg.roster_to_owner[(lid, rid)] = owner
    return reg


def snapshot_to_dict(snapshot: PublicLeagueSnapshot, include_nfl_players: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "rootLeagueId": snapshot.root_league_id,
        "generatedAt": snapshot.generated_at,
        "seasons": [_season_to_dict(s) for s in snapshot.seasons],
        "managers": _registry_to_dict(snapshot.managers),
    }
    if include_nfl_players:
        out["nflPlayers"] = snapshot.nfl_players
    return out


def snapshot_from_dict(d: dict[str, Any]) -> PublicLeagueSnapshot:
    snapshot = PublicLeagueSnapshot(
        root_league_id=str(d.get("rootLeagueId") or ""),
        generated_at=str(d.get("generatedAt") or ""),
    )
    snapshot.seasons = [_season_from_dict(s) for s in d.get("seasons") or []]
    snapshot.managers = _registry_from_dict(d.get("managers") or {})
    nfl = d.get("nflPlayers")
    if isinstance(nfl, dict):
        snapshot.nfl_players = nfl
    return snapshot


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp-{int(time.time() * 1000)}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def persist_snapshot(
    snapshot: PublicLeagueSnapshot,
    contract: dict[str, Any] | None = None,
    persist_nfl_players: bool = True,
) -> None:
    """Write the snapshot + optional contract + identity registry to disk.

    ``persist_nfl_players`` keeps the NFL players dump in its own file
    so the snapshot.json stays small + readable.  The snapshot file
    itself never embeds the full player dump — loaders re-attach it
    from nfl_players.json.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(SNAPSHOT_PATH, snapshot_to_dict(snapshot, include_nfl_players=False))
    _atomic_write_json(IDENTITY_PATH, _registry_to_dict(snapshot.managers))
    if contract is not None:
        _atomic_write_json(CONTRACT_PATH, contract)
    if persist_nfl_players and snapshot.nfl_players:
        _atomic_write_json(NFL_PLAYERS_PATH, snapshot.nfl_players)


def load_snapshot() -> PublicLeagueSnapshot | None:
    """Load the persisted snapshot, or ``None`` if missing/corrupt."""
    if not SNAPSHOT_PATH.exists():
        return None
    try:
        payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("Failed to load snapshot.json: %s", exc)
        return None
    snapshot = snapshot_from_dict(payload)
    if NFL_PLAYERS_PATH.exists():
        try:
            snapshot.nfl_players = json.loads(NFL_PLAYERS_PATH.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            log.warning("Failed to load nfl_players.json: %s", exc)
    return snapshot


def load_contract() -> dict[str, Any] | None:
    if not CONTRACT_PATH.exists():
        return None
    try:
        return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("Failed to load contract.json: %s", exc)
        return None
