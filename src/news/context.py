"""Pure contract scans shared by the news producer and legacy server adapters."""

from __future__ import annotations

from .providers.espn_player import DEFAULT_MAX_TARGETS


def _name(row: dict) -> str:
    for key in ("displayName", "name", "canonicalName", "fullName"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _identity(row: dict) -> dict:
    position, team = row.get("position"), row.get("team")
    return {
        "position": position.strip() if isinstance(position, str) and position.strip() else None,
        "team": team.strip().upper() if isinstance(team, str) and team.strip() else None,
    }


def player_names(contract: dict) -> list[str]:
    return [
        name
        for row in contract.get("playersArray") or []
        if isinstance(row, dict) and (name := _name(row))
    ]


def player_meta(contract: dict) -> dict:
    result: dict = {}
    for row in contract.get("playersArray") or []:
        if not isinstance(row, dict) or not (name := _name(row)):
            continue
        identity = _identity(row)
        if name in result and result[name] != identity:
            identity = {"position": None, "team": None}
        result[name] = identity
    return result


def espn_targets(contract: dict) -> list[dict]:
    directory = (contract.get("sleeper") or {}).get("players") or {}
    if not isinstance(directory, dict):
        return []

    def rank(row: dict) -> float:
        try:
            value = float(row.get("canonicalConsensusRank") or row.get("rank") or 0)
            return value if value > 0 else float("inf")
        except (TypeError, ValueError):
            return float("inf")

    rows = (row for row in contract.get("playersArray") or [] if isinstance(row, dict))
    targets: list[dict] = []
    for row in sorted(rows, key=rank):
        entry = directory.get(str(row.get("playerId") or "").strip())
        if not isinstance(entry, dict):
            continue
        espn_id = str(entry.get("espn_id") or "").strip()
        name = _name(row)
        if not espn_id or not name:
            continue
        targets.append({"name": name, "espnId": espn_id, **_identity(row)})
        if len(targets) >= DEFAULT_MAX_TARGETS:
            break
    return targets
