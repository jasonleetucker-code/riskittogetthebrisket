"""Read-time aggregation over crawled intel events.

Events are the raw add/drop rows the crawler extracted from Sleeper
transactions (see ``crawler.py`` for the shape).  Nothing here is
persisted — summaries are computed at read time so window edges are
always relative to "now" and a snapshot never goes stale between
crawls.

Semantics:
    * A trade produces PAIRED add+drop events per side (each roster's
      incoming assets are adds, outgoing are drops).
    * Waiver / free-agent moves produce single-sided events.
    * ``buys`` counts adds, ``sells`` counts drops, ``net = buys −
      sells`` per rolling window.
    * ``leagueCount`` is the number of DISTINCT leagues where the
      asset is currently held by a pool member or was traded by one.
    * ``trendScore = 3·net48h + 2·net7d + 1·net30d``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

WINDOWS_MS: dict[str, int] = {
    "48h": 48 * 3600 * 1000,
    "7d": 7 * 24 * 3600 * 1000,
    "14d": 14 * 24 * 3600 * 1000,
    "30d": 30 * 24 * 3600 * 1000,
}


def _now_ms(now: datetime | int | float | None) -> int:
    if now is None:
        return int(datetime.now(timezone.utc).timestamp() * 1000)
    if isinstance(now, datetime):
        return int(now.timestamp() * 1000)
    return int(now)


def trend_score(net_48h: int, net_7d: int, net_30d: int) -> int:
    return 3 * net_48h + 2 * net_7d + 1 * net_30d


def _empty_windows() -> dict[str, dict[str, int]]:
    return {key: {"buys": 0, "sells": 0, "net": 0} for key in WINDOWS_MS}


def _valid_events(events: list[dict[str, Any]] | None, now: int) -> list[dict[str, Any]]:
    out = []
    for e in events or []:
        if not isinstance(e, dict):
            continue
        ts = e.get("ts")
        if not isinstance(ts, (int, float)) or ts <= 0 or ts > now:
            continue
        if e.get("action") not in ("add", "drop"):
            continue
        if not e.get("assetId"):
            continue
        out.append(e)
    return out


def holdings_from_state(state: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    """Extract ``{leagueId: {ownerId: [assetId, ...]}}`` from a crawl
    state's leagues block."""
    out: dict[str, dict[str, list[str]]] = {}
    for lid, league in (state.get("leagues") or {}).items():
        if not isinstance(league, dict):
            continue
        holdings = league.get("holdings")
        if isinstance(holdings, dict) and holdings:
            out[str(lid)] = {
                str(oid): [str(a) for a in assets or []]
                for oid, assets in holdings.items()
                if isinstance(assets, list)
            }
    return out


def build_asset_summary(
    events: list[dict[str, Any]] | None,
    now: datetime | int | float | None,
    holdings: dict[str, dict[str, list[str]]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Per-asset buy/sell/net counts over the rolling windows.

    Returns ``{assetId: summary}`` where summary is::

        {
            "assetId": str,
            "assetType": "player" | "pick",
            "windows": {"48h": {"buys", "sells", "net"}, "7d": ..., ...},
            "leagueCount": int,     # distinct leagues held OR traded
            "heldLeagueCount": int, # distinct leagues currently held
            "trendScore": int,
            "lastEventTs": int | None,
        }

    Window membership is inclusive at the edge: an event exactly
    ``window`` old still counts (``ts >= now − window``).
    """
    now_ms = _now_ms(now)
    summaries: dict[str, dict[str, Any]] = {}

    def _entry(asset_id: str, asset_type: str | None) -> dict[str, Any]:
        entry = summaries.get(asset_id)
        if entry is None:
            entry = {
                "assetId": asset_id,
                "assetType": asset_type or ("pick" if asset_id.startswith("pick:") else "player"),
                "windows": _empty_windows(),
                "_tradedLeagues": set(),
                "_heldLeagues": set(),
                "trendScore": 0,
                "lastEventTs": None,
            }
            summaries[asset_id] = entry
        return entry

    for event in _valid_events(events, now_ms):
        asset_id = str(event["assetId"])
        entry = _entry(asset_id, event.get("assetType"))
        ts = int(event["ts"])
        age = now_ms - ts
        bucket = "buys" if event["action"] == "add" else "sells"
        for key, window in WINDOWS_MS.items():
            if age <= window:
                entry["windows"][key][bucket] += 1
        lid = str(event.get("leagueId") or "")
        if lid and age <= WINDOWS_MS["30d"]:
            entry["_tradedLeagues"].add(lid)
        if entry["lastEventTs"] is None or ts > entry["lastEventTs"]:
            entry["lastEventTs"] = ts

    for lid, by_owner in (holdings or {}).items():
        for _owner, assets in (by_owner or {}).items():
            for asset_id in assets or []:
                entry = _entry(str(asset_id), None)
                entry["_heldLeagues"].add(str(lid))

    for entry in summaries.values():
        for win in entry["windows"].values():
            win["net"] = win["buys"] - win["sells"]
        entry["leagueCount"] = len(entry["_tradedLeagues"] | entry["_heldLeagues"])
        entry["heldLeagueCount"] = len(entry.pop("_heldLeagues"))
        entry.pop("_tradedLeagues")
        entry["trendScore"] = trend_score(
            entry["windows"]["48h"]["net"],
            entry["windows"]["7d"]["net"],
            entry["windows"]["30d"]["net"],
        )
    return summaries


def build_member_exposure(
    events: list[dict[str, Any]] | None,
    holdings: dict[str, dict[str, list[str]]] | None,
    asset_id: str,
    now: datetime | int | float | None,
) -> list[dict[str, Any]]:
    """Which pool members hold / recently traded ``asset_id``, and in
    how many of their leagues.  Sorted by held-league count desc."""
    now_ms = _now_ms(now)
    asset_id = str(asset_id)
    per_member: dict[str, dict[str, Any]] = {}

    def _member(oid: str) -> dict[str, Any]:
        entry = per_member.get(oid)
        if entry is None:
            entry = {
                "ownerId": oid,
                "heldLeagueCount": 0,
                "buys30d": 0,
                "sells30d": 0,
                "net30d": 0,
                "lastEventTs": None,
                "_held": set(),
            }
            per_member[oid] = entry
        return entry

    for lid, by_owner in (holdings or {}).items():
        for oid, assets in (by_owner or {}).items():
            if asset_id in (assets or []):
                _member(str(oid))["_held"].add(str(lid))

    for event in _valid_events(events, now_ms):
        if str(event["assetId"]) != asset_id:
            continue
        ts = int(event["ts"])
        if now_ms - ts > WINDOWS_MS["30d"]:
            continue
        oid = str(event.get("ownerId") or "")
        if not oid:
            continue
        entry = _member(oid)
        if event["action"] == "add":
            entry["buys30d"] += 1
        else:
            entry["sells30d"] += 1
        if entry["lastEventTs"] is None or ts > entry["lastEventTs"]:
            entry["lastEventTs"] = ts

    out = []
    for entry in per_member.values():
        entry["heldLeagueCount"] = len(entry.pop("_held"))
        entry["net30d"] = entry["buys30d"] - entry["sells30d"]
        out.append(entry)
    out.sort(key=lambda m: (-m["heldLeagueCount"], -(m["buys30d"] + m["sells30d"])))
    return out


def build_member_activity(
    events: list[dict[str, Any]] | None,
    owner_id: str,
    now: datetime | int | float | None,
) -> dict[str, Any]:
    """One member's per-asset activity (their personal buy/sell log
    across every league of theirs we track)."""
    now_ms = _now_ms(now)
    owner_id = str(owner_id)
    member_events = [
        e for e in _valid_events(events, now_ms) if str(e.get("ownerId") or "") == owner_id
    ]
    assets = build_asset_summary(member_events, now_ms)
    ranked = sorted(
        assets.values(),
        key=lambda a: (-abs(a["trendScore"]), -(a["lastEventTs"] or 0)),
    )
    return {
        "ownerId": owner_id,
        "eventCount30d": sum(
            1 for e in member_events if now_ms - int(e["ts"]) <= WINDOWS_MS["30d"]
        ),
        "assets": ranked,
    }
