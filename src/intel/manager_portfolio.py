"""Manager Intelligence — any Sleeper username's leagues and player portfolio.

Batch A of the Manager Intelligence directive (owner, 2026-10-16;
``docs/OWNER_REQUESTED_TODO.md`` "Manager Intelligence"): resolve a Sleeper
username to its permanent user id, discover that user's leagues for a season,
read their rosters, and aggregate every owned player ONCE with the leagues it
is owned in.

Nothing here is a second pipeline.  It composes canonical owners:

* Sleeper HTTP — ``src/public_league/sleeper_client`` (classified fetches:
  a 429 is never mistaken for "no leagues");
* league type — ``src/intel/league_filter`` (``settings.type``: 2 dynasty,
  1 keeper, 0 redraft; unknown stays unknown);
* league format and roster slots — ``src/sharp/roster_collect``
  (``league_format``, ``_sleeper_assets``: taxi/IR players are members of
  ``players`` and only LABELLED, never double-counted);
* player value — ``src/sharp/roster_percentage.build_player_index`` over the
  live contract: joined by Sleeper player id, never by name.  A player the
  board does not price has ``value: None`` — MISSING IS NEVER ZERO.

Scopes never mix: the portfolio aggregates one league type at a time
(``dynasty`` by default).  Values come from the one canonical board, which is
a Superflex / TE-premium board, so a portfolio value total is published only
over the Superflex leagues it describes; other formats report their counts
with ``value: None`` and the reason.

Exposure is ``leagues owned / leagues that could hold that player`` — an IDP
player is measured against the leagues with IDP slots, a kicker against the
leagues with a K slot — and both numbers are published, so the denominator is
never implied.

Bounded: one season, at most ``max_leagues`` leagues per scope (``truncated``
says when more existed), a small thread pool, and a short memo keyed by the
case-folded username (Sleeper usernames are unique under case-folding).  The
payload carries the permanent ``manager.userId``, which is the identity every
later batch (saved managers, alerts) keys on — never the username.
"""

from __future__ import annotations

import math
import statistics
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from src.intel import league_filter
from src.public_league import sleeper_client
from src.sharp import roster_collect
from src.sharp.roster_percentage import build_player_index

#: Scope labels, from Sleeper ``settings.type``.
SCOPE_DYNASTY = "dynasty"
SCOPE_KEEPER = "keeper"
SCOPE_REDRAFT = "redraft"
SCOPE_UNKNOWN = "unknown"
SCOPES = (SCOPE_DYNASTY, SCOPE_KEEPER, SCOPE_REDRAFT, SCOPE_UNKNOWN)

_TYPE_TO_SCOPE = {2: SCOPE_DYNASTY, 1: SCOPE_KEEPER, 0: SCOPE_REDRAFT}

IDP_POSITIONS = frozenset({"DL", "LB", "DB", "DE", "DT", "CB", "S", "ILB", "OLB", "EDGE"})
OFFENSE_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})

DEFAULT_MAX_LEAGUES = 60
DEFAULT_WORKERS = 6
CACHE_TTL_SECONDS = 15 * 60
_CACHE_MAX_ENTRIES = 256

#: The canonical board's format (``_compute_unified_rankings`` is scoped to
#: the Superflex / TE-premium scoring profile).  Values are comparable only
#: against leagues of that shape.
BOARD_FORMAT = "superflex"

STATUS_OK = "ok"
STATUS_PARTIAL = "partial"
STATUS_NOT_FOUND = "not_found"
STATUS_RATE_LIMITED = "rate_limited"
STATUS_UPSTREAM_UNAVAILABLE = "upstream_unavailable"

Fetch = Callable[..., tuple[str, Any]]


def league_scope(league: dict[str, Any]) -> str:
    """``dynasty`` / ``keeper`` / ``redraft`` / ``unknown`` — never guessed."""
    return _TYPE_TO_SCOPE.get(league_filter.league_type(league), SCOPE_UNKNOWN)


def _roster_for_user(rosters: list[dict[str, Any]], user_id: str) -> tuple[dict | None, bool]:
    """The user's roster and whether they hold it as a co-owner."""
    for roster in rosters:
        if isinstance(roster, dict) and str(roster.get("owner_id") or "") == user_id:
            return roster, False
    for roster in rosters:
        if not isinstance(roster, dict):
            continue
        co_owners = [str(c) for c in (roster.get("co_owners") or []) if c]
        if user_id in co_owners:
            return roster, True
    return None, False


def _slot_assets(roster: dict[str, Any]) -> list[tuple[str, str]]:
    """``[(player_id, slot)]`` with slot in starter / bench / taxi / reserve."""
    starters = {str(p).strip() for p in (roster.get("starters") or []) if str(p or "").strip()}
    out: list[tuple[str, str]] = []
    for asset in roster_collect._sleeper_assets(roster):  # noqa: SLF001 — canonical slot rule
        pid = asset.canonical_asset_id
        if asset.slot != "active":
            out.append((pid, asset.slot))
        else:
            out.append((pid, "starter" if pid in starters else "bench"))
    return out


def _record(roster: dict[str, Any]) -> dict[str, Any]:
    settings = roster.get("settings") if isinstance(roster.get("settings"), dict) else {}

    def _int(key: str) -> int | None:
        try:
            return int(settings.get(key))
        except (TypeError, ValueError):
            return None

    fpts = _int("fpts")
    dec = _int("fpts_decimal")
    return {
        "wins": _int("wins"),
        "losses": _int("losses"),
        "ties": _int("ties"),
        # Sleeper splits points into an integer and a hundredths field; a
        # missing hundredths field means the integer is all we know.
        "pointsFor": (None if fpts is None else float(fpts) if dec is None else fpts + dec / 100.0),
    }


def _player_meta(
    player_id: str, board: dict[str, dict[str, Any]], directory: dict[str, Any]
) -> dict[str, Any]:
    row = board.get(player_id) or {}
    raw = directory.get(player_id) if isinstance(directory, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    name = row.get("displayName") or raw.get("full_name")
    if not name and (raw.get("first_name") or raw.get("last_name")):
        name = f"{raw.get('first_name') or ''} {raw.get('last_name') or ''}".strip()
    position = row.get("position") or (str(raw.get("position") or "").upper() or None)
    team = row.get("nflTeam") or (str(raw.get("team") or "").upper() or None)
    age = row.get("age") if row.get("age") is not None else raw.get("age")
    years_exp = raw.get("years_exp")
    rookie = bool(row.get("isRookie")) or (years_exp == 0 if years_exp is not None else False)
    return {
        "playerId": player_id,
        "name": name or None,
        "position": position,
        "nflTeam": team,
        "age": age if isinstance(age, (int, float)) else None,
        "isRookie": rookie,
        "injuryStatus": raw.get("injury_status") or None,
        "value": row.get("value"),
        "overallRank": row.get("overallRank"),
    }


def _eligible(league: dict[str, Any], position: str | None) -> bool | None:
    """Could this league roster a player at ``position``?  ``None`` = unknown."""
    fmt = league.get("format") or {}
    pos = (position or "").upper()
    if pos in IDP_POSITIONS:
        return fmt.get("idp")
    if pos == "K":
        return fmt.get("kicker")
    if pos in ("DEF", "DST"):
        return fmt.get("teamDefense")
    return True


def _format_group(league: dict[str, Any]) -> str:
    superflex = (league.get("format") or {}).get("superflex")
    if superflex is True:
        return "superflex"
    if superflex is False:
        return "1qb"
    return "unknown"


def aggregate_portfolio(
    leagues: list[dict[str, Any]],
    *,
    board: dict[str, dict[str, Any]],
    directory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate read leagues (``state == "ok"``) into one row per player.

    Pure: ``leagues`` carry their own ``assets`` / ``format``; ``board`` is
    :func:`build_player_index` output.  Every owned instance is kept in the
    player's ``leagues`` list, so the aggregate never loses a league.
    """
    directory = directory or {}
    read = [lg for lg in leagues if lg.get("state") == "ok"]
    by_player: dict[str, dict[str, Any]] = {}
    for lg in read:
        for pid, slot in lg.get("assets") or []:
            entry = by_player.get(pid)
            if entry is None:
                entry = _player_meta(pid, board, directory)
                entry["leagues"] = []
                by_player[pid] = entry
            entry["leagues"].append({"leagueId": lg["leagueId"], "slot": slot})

    players: list[dict[str, Any]] = []
    for entry in by_player.values():
        owned = len(entry["leagues"])
        eligibility = [_eligible(lg, entry["position"]) for lg in read]
        eligible_n = sum(1 for e in eligibility if e)
        unknown_n = sum(1 for e in eligibility if e is None)
        denominator = eligible_n if eligible_n >= owned else owned
        entry["leaguesOwned"] = owned
        entry["exposure"] = {
            "owned": owned,
            "eligibleLeagues": denominator,
            "eligibilityUnknownLeagues": unknown_n,
            "share": round(owned / denominator, 4) if denominator else None,
        }
        players.append(entry)
    # Unpriced players sort after every priced one (an absent value is not 0).
    players.sort(
        key=lambda p: (
            -p["leaguesOwned"],
            -p["value"] if p["value"] is not None else math.inf,
            p["name"] or "",
        )
    )

    return {"players": players, "summary": _summary(read, players)}


def _summary(read: list[dict[str, Any]], players: list[dict[str, Any]]) -> dict[str, Any]:
    instances = sum(p["leaguesOwned"] for p in players)
    by_position: Counter[str] = Counter()
    instances_by_position: Counter[str] = Counter()
    offense = idp = other = 0
    for p in players:
        pos = p["position"] or "UNKNOWN"
        by_position[pos] += 1
        instances_by_position[pos] += p["leaguesOwned"]
        if pos in OFFENSE_POSITIONS:
            offense += p["leaguesOwned"]
        elif pos in IDP_POSITIONS:
            idp += p["leaguesOwned"]
        else:
            other += p["leaguesOwned"]
    ages = [p["age"] for p in players if isinstance(p["age"], (int, float))]
    top10 = sum(p["leaguesOwned"] for p in players[:10])

    groups: dict[str, dict[str, Any]] = {}
    for lg in read:
        group = groups.setdefault(
            _format_group(lg),
            {"leagues": 0, "instances": 0, "pricedInstances": 0, "boardValue": 0},
        )
        group["leagues"] += 1
        for pid, _slot in lg.get("assets") or []:
            group["instances"] += 1
    value_by_pid = {p["playerId"]: p["value"] for p in players}
    for lg in read:
        group = groups[_format_group(lg)]
        for pid, _slot in lg.get("assets") or []:
            value = value_by_pid.get(pid)
            if isinstance(value, (int, float)):
                group["pricedInstances"] += 1
                group["boardValue"] += int(value)
    for name, group in groups.items():
        if name != BOARD_FORMAT:
            # The canonical board is a Superflex board; summing it over a 1QB
            # (or unknown-format) league would publish a number nobody computed.
            group["boardValue"] = None
            group["valueNote"] = "canonical_board_is_superflex"

    return {
        "leaguesRead": len(read),
        # A total is published only when every read league states its size.
        "rosterSpots": (
            sum(int(lg["rosterSpots"]) for lg in read)
            if read and all(lg.get("rosterSpots") for lg in read)
            else None
        ),
        "ownedInstances": instances,
        "uniquePlayers": len(players),
        "playersByPosition": dict(sorted(by_position.items())),
        "instancesByPosition": dict(sorted(instances_by_position.items())),
        "offenseInstances": offense,
        "idpInstances": idp,
        "otherInstances": other,
        "ageMean": round(statistics.fmean(ages), 1) if ages else None,
        "ageMedian": statistics.median(ages) if ages else None,
        "ageKnownPlayers": len(ages),
        "rookieInstances": sum(p["leaguesOwned"] for p in players if p["isRookie"]),
        "injuredInstances": sum(p["leaguesOwned"] for p in players if p["injuryStatus"]),
        "unpricedPlayers": sum(1 for p in players if p["value"] is None),
        "top10InstanceShare": round(top10 / instances, 4) if instances else None,
        "byFormat": groups,
    }


def _read_league(league: dict[str, Any], user_id: str, fetch_rosters: Fetch) -> dict[str, Any]:
    league_id = str(league.get("league_id") or "")
    fmt = roster_collect.league_format(league)
    entry: dict[str, Any] = {
        "leagueId": league_id,
        "name": league.get("name") or None,
        "season": str(league.get("season") or "") or None,
        "status": league.get("status") or None,
        "scope": league_scope(league),
        "format": fmt,
        "totalRosters": league.get("total_rosters"),
        "rosterSpots": len([p for p in (league.get("roster_positions") or []) if p]) or None,
        "previousLeagueId": (str(league.get("previous_league_id") or "") or None)
        if str(league.get("previous_league_id") or "") not in ("", "0")
        else None,
    }
    kind, rosters = fetch_rosters(league_id)
    if kind != sleeper_client.FETCH_OK:
        entry["state"] = (
            STATUS_RATE_LIMITED if kind == sleeper_client.FETCH_RATE_LIMITED else "unavailable"
        )
        entry["assets"] = []
        return entry
    roster, co_owned = _roster_for_user(rosters or [], user_id)
    if roster is None:
        entry["state"] = "no_roster"
        entry["assets"] = []
        return entry
    entry["state"] = "ok"
    entry["rosterId"] = roster.get("roster_id")
    entry["coOwned"] = co_owned
    entry["record"] = _record(roster)
    entry["assets"] = _slot_assets(roster)
    entry["playerCount"] = len(entry["assets"])
    return entry


def _current_season(fetch_state: Callable[[], Any]) -> str:
    state = fetch_state() or {}
    season = str(state.get("league_season") or state.get("season") or "").strip()
    return season or str(time.gmtime().tm_year)


def build_manager_profile(
    username: str,
    *,
    contract: dict[str, Any] | None,
    scope: str = SCOPE_DYNASTY,
    season: str | None = None,
    max_leagues: int = DEFAULT_MAX_LEAGUES,
    workers: int = DEFAULT_WORKERS,
    fetch_user: Fetch = sleeper_client.fetch_user_classified,
    fetch_leagues: Fetch = sleeper_client.fetch_user_leagues_classified,
    fetch_rosters: Fetch = sleeper_client.fetch_rosters_classified,
    fetch_state: Callable[[], Any] = sleeper_client.fetch_nfl_state,
    fetch_directory: Callable[[], Any] = sleeper_client.fetch_nfl_players,
    now: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """The Manager Intelligence profile payload for one username.

    ``status`` is ``ok`` / ``partial`` (some leagues unreadable) /
    ``not_found`` / ``rate_limited`` / ``upstream_unavailable``.  Never
    raises for an upstream failure; never fabricates an unread league.
    """
    if scope not in SCOPES:
        scope = SCOPE_DYNASTY
    kind, user = fetch_user(username)
    if kind != sleeper_client.FETCH_OK:
        return {
            "status": {
                sleeper_client.FETCH_NOT_FOUND: STATUS_NOT_FOUND,
                sleeper_client.FETCH_RATE_LIMITED: STATUS_RATE_LIMITED,
            }.get(kind, STATUS_UPSTREAM_UNAVAILABLE),
            "query": username,
        }
    user_id = str(user["user_id"])
    season = str(season or _current_season(fetch_state))
    kind, leagues = fetch_leagues(user_id, season)
    manager = {
        "userId": user_id,
        "username": user.get("username") or None,
        "displayName": user.get("display_name") or user.get("username") or None,
        "avatar": user.get("avatar") or None,
    }
    if kind != sleeper_client.FETCH_OK:
        return {
            "status": STATUS_RATE_LIMITED
            if kind == sleeper_client.FETCH_RATE_LIMITED
            else STATUS_UPSTREAM_UNAVAILABLE,
            "query": username,
            "manager": manager,
            "season": season,
        }

    leagues = [lg for lg in leagues or [] if isinstance(lg, dict) and lg.get("league_id")]
    scope_counts = Counter(league_scope(lg) for lg in leagues)
    in_scope = [lg for lg in leagues if league_scope(lg) == scope]
    in_scope.sort(key=lambda lg: str(lg.get("name") or ""))
    truncated = len(in_scope) > max_leagues
    in_scope = in_scope[:max_leagues]

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(in_scope)))) as pool:
        read = list(pool.map(lambda lg: _read_league(lg, user_id, fetch_rosters), in_scope))

    board = build_player_index(contract)
    directory = fetch_directory() or {}
    aggregate = aggregate_portfolio(read, board=board, directory=directory)

    failed = [lg for lg in read if lg["state"] in ("unavailable", STATUS_RATE_LIMITED)]
    status = STATUS_PARTIAL if failed else STATUS_OK
    league_rows = []
    for lg in read:
        row = {k: v for k, v in lg.items() if k != "assets"}
        league_rows.append(row)

    return {
        "status": status,
        "query": username,
        "manager": manager,
        "season": season,
        "scope": scope,
        "leagueCounts": {s: scope_counts.get(s, 0) for s in SCOPES},
        "leaguesInScope": len(in_scope),
        "truncated": truncated,
        "maxLeagues": max_leagues,
        "leaguesUnreadable": len(failed),
        "leagues": league_rows,
        "players": aggregate["players"],
        "summary": aggregate["summary"],
        "valueBasis": {
            "field": "rankDerivedValue",
            "board": "canonical Superflex / TE-premium board",
            "note": "Values are the canonical board's; they are summed only over Superflex leagues.",
        },
        "notIncluded": {
            "draftPicks": "batch_b",
            "trades": "batch_b",
            "careerRecord": "batch_e",
            "otherSeasons": "batch_b",
        },
        "fetchedAt": int(now() * 1000),
    }


# ── per-process memo ────────────────────────────────────────────────────

_cache: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}
_cache_lock = threading.Lock()


def drop_expired_payloads_locked(
    cache: dict[Any, tuple[float, Any]], now: float, ttl: float
) -> None:
    """Sweep a ``key -> (stamp, payload)`` memo of entries past ``ttl``.

    Shared by the intel payload memos (memory follow-up 2026-10-20): their
    expiry was lazy, so an entry stayed resident until the SAME key was asked
    again or the cap evicted it -- ~350 KB per activity payload, up to its cap
    of 128.  A reader never returns an entry with ``now - stamp >= ttl``, so
    dropping those changes no answer.  ``now`` is the putter's request-start
    clock, which is never later than a concurrent reader's.  Lock held.
    """
    for k in [k for k, (stamp, _) in cache.items() if now - stamp >= ttl]:
        cache.pop(k, None)


def cached_manager_profile(
    username: str,
    *,
    contract: dict[str, Any] | None,
    scope: str = SCOPE_DYNASTY,
    season: str | None = None,
    now: Callable[[], float] = time.time,
    **kwargs: Any,
) -> dict[str, Any]:
    """:func:`build_manager_profile`, memoised for ``CACHE_TTL_SECONDS``.

    Only ``ok`` answers are memoised — a failure must let the next request
    retry.  Keyed by the lower-cased query (Sleeper usernames are unique
    under case-folding), scope and season.
    """
    key = (str(username).strip().lower(), scope, str(season or ""))
    t = now()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and t - hit[0] < CACHE_TTL_SECONDS:
            return {**hit[1], "cached": True}
    payload = build_manager_profile(
        username, contract=contract, scope=scope, season=season, now=now, **kwargs
    )
    if payload.get("status") == STATUS_OK:
        with _cache_lock:
            drop_expired_payloads_locked(_cache, t, CACHE_TTL_SECONDS)
            if len(_cache) >= _CACHE_MAX_ENTRIES:
                oldest = min(_cache, key=lambda k: _cache[k][0])
                _cache.pop(oldest, None)
            _cache[key] = (t, payload)
    return {**payload, "cached": False}


def reset_cache() -> None:
    with _cache_lock:
        _cache.clear()
