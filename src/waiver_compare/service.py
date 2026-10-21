"""Waiver-compare payload: league rosters + available players, valued.

Read-only.  Rosters come live from Sleeper (through the public pipeline's
pooled, 60 s TTL client) and are refreshed far more often than the values,
which ride the existing scheduled scrape.  Nothing here mutates a league.

A player is UNAVAILABLE when any roster holds them — active, bench, taxi or
IR (``players`` ∪ ``taxi`` ∪ ``reserve``).  The waiver pool is every
available player that at least one of the two sources values; a free agent
neither source prices has no value to rank by and is not listed.
"""

from __future__ import annotations

import math
import threading
import time
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable, Mapping

from src.utils.name_clean import normalize_position, resolve_idp_position
from src.utils.owner_names import owner_label
from src.waiver_compare.values import (
    IDPTC_KEY,
    SOURCE_SETTINGS,
    PlayerValue,
    ValueIndex,
    build_value_index,
    combine,
)
from src.sources.ktc_market import KTC_MARKET_KEY

#: The league this page serves, by its stable registry key — the Sleeper id
#: behind it rolls over each season and is resolved from the registry.
LEAGUE_KEY = "dynasty_main"

PAYLOAD_TTL_SECONDS = 60.0

POSITIONS = ("QB", "RB", "WR", "TE", "DL", "LB", "DB")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def roster_player_ids(roster: Mapping[str, Any]) -> list[str]:
    """Every player a roster holds: active/bench, taxi and IR, deduplicated."""
    seen: dict[str, None] = {}
    for field in ("players", "taxi", "reserve"):
        for pid in roster.get(field) or ():
            if pid is None:
                continue
            key = str(pid).strip()
            if key and key != "0":
                seen.setdefault(key, None)
    return list(seen)


def _sleeper_name(meta: Mapping[str, Any]) -> str:
    full = str(meta.get("full_name") or "").strip()
    if full:
        return full
    parts = [str(meta.get("first_name") or "").strip(), str(meta.get("last_name") or "").strip()]
    return " ".join(p for p in parts if p)


def _sleeper_position(meta: Mapping[str, Any]) -> str:
    idp = resolve_idp_position(meta.get("fantasy_positions"), meta.get("position"))
    if idp:
        return idp
    return normalize_position(meta.get("position")) or str(meta.get("position") or "").upper()


def _sleeper_age(meta: Mapping[str, Any], today: date) -> int | None:
    birth = str(meta.get("birth_date") or "").strip()
    if birth:
        try:
            b = date.fromisoformat(birth[:10])
        except ValueError:
            b = None
        if b is not None:
            years = today.year - b.year - ((today.month, today.day) < (b.month, b.day))
            if 0 < years < 60:
                return years
    raw = meta.get("age")
    try:
        out = int(float(raw))
    except (TypeError, ValueError):
        return None
    return out if 0 < out < 60 else None


def _whole(value: float | None) -> int | None:
    if value is None or not math.isfinite(value):
        return None
    return int(math.floor(value))


def _round_value(value: float | None) -> float | int | None:
    """Keep the exact average; integers stay integers on the wire."""
    if value is None:
        return None
    return int(value) if float(value).is_integer() else round(value, 1)


def player_record(
    pid: str,
    valued: PlayerValue | None,
    meta: Mapping[str, Any] | None,
    today: date,
) -> dict[str, Any]:
    meta = meta or {}
    if valued is not None:
        name = valued.name or _sleeper_name(meta)
        position = valued.position or _sleeper_position(meta)
        team = valued.team or meta.get("team")
        age = _whole(valued.age)
        if age is None:
            age = _sleeper_age(meta, today)
        ktc, idptc, value = valued.ktc, valued.idptc, valued.combined
    else:
        name = _sleeper_name(meta)
        position = _sleeper_position(meta)
        team = meta.get("team")
        age = _sleeper_age(meta, today)
        ktc = idptc = value = None
    return {
        "id": pid,
        "name": name or f"Unknown player ({pid})",
        "pos": position or None,
        "team": str(team) if team else None,
        "age": age,
        "ktc": _round_value(ktc),
        "idptc": _round_value(idptc),
        "value": _round_value(value),
    }


def _value_sort_key(rec: Mapping[str, Any]) -> tuple:
    # Highest value first; ties broken by name so the order is stable.
    return (-(rec["value"] or 0.0), str(rec["name"]).lower(), rec["id"])


def _source_freshness(contract: Mapping[str, Any]) -> dict[str, Any]:
    stamps = (contract.get("dataFreshness") or {}).get("sourceTimestamps") or {}
    weighting = (contract.get("sourceWeighting") or {}).get("sources") or {}
    out: dict[str, Any] = {}
    for short, settings in SOURCE_SETTINGS.items():
        key = settings["sourceKey"]
        stamp = stamps.get(key) or {}
        players_subset = ((weighting.get(key) or {}).get("subsets") or {}).get("players") or {}
        out[short] = {
            **settings,
            "fetchedAt": stamp.get("mtime"),
            "staleness": stamp.get("staleness") or "unknown",
            "dataChangedAt": players_subset.get("sourceDataAsOf"),
        }
    return out


def build_payload(
    *,
    contract: Mapping[str, Any],
    rosters: Iterable[Mapping[str, Any]],
    users: Iterable[Mapping[str, Any]] | None,
    nfl_players: Mapping[str, Any] | None,
    league: Mapping[str, Any],
    rosters_fetched_at: str,
    rosters_state: str,
    today: date | None = None,
    value_index: ValueIndex | None = None,
) -> dict[str, Any]:
    today = today or datetime.now(timezone.utc).date()
    index = value_index or build_value_index(contract.get("playersArray") or ())
    nfl = nfl_players or {}
    user_by_id = {str(u.get("user_id")): u for u in (users or ()) if isinstance(u, Mapping)}

    records: dict[str, dict[str, Any]] = {}

    def _record(pid: str) -> dict[str, Any]:
        rec = records.get(pid)
        if rec is None:
            rec = player_record(pid, index.by_player_id.get(pid), nfl.get(pid), today)
            records[pid] = rec
        return rec

    teams: list[dict[str, Any]] = []
    owned: set[str] = set()
    for roster in rosters:
        if not isinstance(roster, Mapping):
            continue
        rid = roster.get("roster_id")
        user = user_by_id.get(str(roster.get("owner_id") or "")) or {}
        team_name = str(
            (user.get("metadata") or {}).get("team_name")
            or user.get("display_name")
            or f"Team {rid}"
        ).strip()
        pids = roster_player_ids(roster)
        owned.update(pids)
        team_records = sorted((_record(pid) for pid in pids), key=_value_sort_key)
        teams.append(
            {
                "rosterId": rid,
                "teamName": team_name,
                "ownerName": owner_label(user) or None,
                "playerIds": [r["id"] for r in team_records],
            }
        )
    teams.sort(key=lambda t: str(t["teamName"]).lower())

    waiver_ids = [pid for pid in index.by_player_id if pid not in owned]
    waiver_records = sorted((_record(pid) for pid in waiver_ids), key=_value_sort_key)

    return {
        "ok": True,
        "generatedAt": _utc_now_iso(),
        "league": {"key": league.get("key"), "name": league.get("name")},
        "values": {
            "formula": "(KTC + IDPTC) / 2 when both exist; otherwise the one available value",
            "asOf": contract.get("scrapeTimestamp"),
            "sources": _source_freshness(contract),
            "valuedPlayers": len(index.by_player_id),
            "unidentifiedRows": index.unidentified_rows,
            "withheldIdentityConflicts": len(index.conflicting_ids),
        },
        "rosters": {"fetchedAt": rosters_fetched_at, "state": rosters_state},
        "positions": list(POSITIONS),
        "teams": teams,
        "waiverIds": [r["id"] for r in waiver_records],
        "players": records,
    }


def _contract_token(contract: Mapping[str, Any]) -> tuple:
    # id() alone can be reused by a later dict once the old one is freed.
    return (id(contract), contract.get("generatedAt"), contract.get("scrapeTimestamp"))


class WaiverCompareService:
    """Live loader: Sleeper rosters + the loaded contract, briefly cached.

    Every fetcher is injectable so tests never touch the network.  The last
    successful roster read is kept so a Sleeper blip serves the previous
    ownership LABELLED stale (``rosters.state = "stale"``) instead of an
    error — and never an empty league that would put every player on waivers.
    """

    def __init__(
        self,
        *,
        fetch_rosters: Callable[[str], tuple[str, Any]] | None = None,
        fetch_users: Callable[[str], tuple[str, Any]] | None = None,
        fetch_players: Callable[[], Mapping[str, Any]] | None = None,
        clock: Callable[[], float] = time.monotonic,
        ttl_seconds: float = PAYLOAD_TTL_SECONDS,
    ) -> None:
        from src.public_league import sleeper_client as sc

        self._fetch_rosters = fetch_rosters or sc.fetch_rosters_classified
        self._fetch_users = fetch_users or sc.fetch_league_users_classified
        self._fetch_players = fetch_players or sc.fetch_nfl_players
        self._clock = clock
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._cache: tuple[tuple, float, dict[str, Any]] | None = None
        self._last_good: dict[str, tuple[list, list, str]] = {}
        self._index_cache: tuple[tuple, ValueIndex] | None = None

    def _index_for(self, contract: Mapping[str, Any]) -> ValueIndex:
        token = _contract_token(contract)
        cached = self._index_cache
        if cached is not None and cached[0] == token:
            return cached[1]
        index = build_value_index(contract.get("playersArray") or ())
        self._index_cache = (token, index)
        return index

    def payload(
        self, contract: Mapping[str, Any] | None, league: Mapping[str, Any] | None
    ) -> tuple[int, dict[str, Any]]:
        if not league or not league.get("sleeperLeagueId"):
            return 503, {"ok": False, "error": "league_unavailable"}
        if not isinstance(contract, Mapping) or not contract.get("playersArray"):
            return 503, {"ok": False, "error": "values_unavailable"}
        league_id = str(league["sleeperLeagueId"])
        key = (_contract_token(contract), league_id)
        now = self._clock()
        with self._lock:
            cached = self._cache
            if cached is not None and cached[0] == key and now - cached[1] < self._ttl:
                return 200, cached[2]

        kind, rosters = self._fetch_rosters(league_id)
        if kind == "ok" and isinstance(rosters, list) and rosters:
            ukind, users = self._fetch_users(league_id)
            users = users if ukind == "ok" and isinstance(users, list) else []
            fetched_at, state = _utc_now_iso(), "live"
            self._last_good[league_id] = (rosters, users, fetched_at)
        elif league_id in self._last_good:
            rosters, users, fetched_at = self._last_good[league_id]
            state = "stale"
        else:
            return 503, {"ok": False, "error": "rosters_unavailable"}

        body = build_payload(
            contract=contract,
            rosters=rosters,
            users=users,
            nfl_players=self._fetch_players() or {},
            league=league,
            rosters_fetched_at=fetched_at,
            rosters_state=state,
            value_index=self._index_for(contract),
        )
        if state == "live":
            with self._lock:
                self._cache = (key, now, body)
        return 200, body


__all__ = [
    "IDPTC_KEY",
    "KTC_MARKET_KEY",
    "LEAGUE_KEY",
    "WaiverCompareService",
    "build_payload",
    "combine",
    "roster_player_ids",
]
