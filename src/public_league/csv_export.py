"""CSV exports for every public-league section.

The goal is to make every dataset that renders on the /league page
available as a plain CSV download.  Dynasty nerds live in spreadsheets;
championing records / trades / rookie drafts / standings as CSV is the
kind of detail that gets a league talking.

Every exporter is a pure function that takes the already-built section
payload (from ``public_contract.build_section_payload``) and returns
``(filename, csv_text)``.  The server route wraps the text in a
``text/csv; charset=utf-8`` response with a ``Content-Disposition``
attachment header.

This module is NOT allowed to import from any private pipeline module.
It composes over the already-safety-checked public section payloads.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Callable


def _write_csv(rows: list[dict[str, Any]], fieldnames: list[str]) -> str:
    """Render a list of dicts to CSV text using ``fieldnames`` as the
    header row.  Missing keys serialize as empty strings.
    """
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: _cell(row.get(k)) for k in fieldnames})
    return buf.getvalue()


def _cell(value: Any) -> str:
    """Flatten a cell value to something CSV-safe.

    Lists of scalars become pipe-delimited strings so analysts can still
    filter on them.  Nested dicts become JSON-ish text.  None becomes
    empty string.  Everything else is coerced via ``str``.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return " | ".join(_cell(v) for v in value)
    if isinstance(value, dict):
        # Flatten to "k=v; k=v" — intentionally readable rather than JSON.
        return "; ".join(f"{k}={_cell(v)}" for k, v in value.items())
    return str(value)


# ── History ────────────────────────────────────────────────────────────────
def export_history(data: dict[str, Any]) -> tuple[str, str]:
    rows: list[dict[str, Any]] = []
    for season_block in data.get("seasons", []):
        season = season_block["season"]
        for standing in season_block.get("standings", []):
            rows.append({
                "season": season,
                "leagueId": season_block["leagueId"],
                "standing": standing["standing"],
                "finalPlace": standing.get("finalPlace"),
                "madePlayoffs": standing.get("madePlayoffs"),
                "ownerId": standing["ownerId"],
                "teamName": standing["teamName"],
                "wins": standing["wins"],
                "losses": standing["losses"],
                "ties": standing["ties"],
                "pointsFor": standing["pointsFor"],
                "pointsAgainst": standing["pointsAgainst"],
                "winPct": standing["winPct"],
            })
    fields = [
        "season", "leagueId", "standing", "finalPlace", "madePlayoffs",
        "ownerId", "teamName", "wins", "losses", "ties",
        "pointsFor", "pointsAgainst", "winPct",
    ]
    return "history-standings.csv", _write_csv(rows, fields)


# ── Hall of Fame (special — lives on ``history.hallOfFame``) ──────────────
def export_hall_of_fame(data: dict[str, Any]) -> tuple[str, str]:
    rows = data.get("hallOfFame", [])
    fields = [
        "ownerId", "displayName", "currentTeamName", "seasonsPlayed",
        "wins", "losses", "ties", "pointsFor", "pointsAgainst",
        "championships", "finalsAppearances", "playoffAppearances",
        "regularSeasonFirstPlace", "toiletBowls",
        "bestFinish", "worstFinish",
    ]
    return "hall-of-fame.csv", _write_csv(rows, fields)


# ── Rivalries ──────────────────────────────────────────────────────────────
def export_rivalries(data: dict[str, Any]) -> tuple[str, str]:
    rows: list[dict[str, Any]] = []
    for r in data.get("rivalries", []):
        owner_a = r["ownerIds"][0] if r.get("ownerIds") else ""
        owner_b = r["ownerIds"][1] if len(r.get("ownerIds", [])) > 1 else ""
        names = r.get("displayNames") or []
        rows.append({
            "ownerIdA": owner_a,
            "displayNameA": names[0] if len(names) > 0 else "",
            "ownerIdB": owner_b,
            "displayNameB": names[1] if len(names) > 1 else "",
            "totalMeetings": r["totalMeetings"],
            "regularSeasonMeetings": r["regularSeasonMeetings"],
            "playoffMeetings": r["playoffMeetings"],
            "winsA": r["winsA"],
            "winsB": r["winsB"],
            "ties": r["ties"],
            "pointsA": r["pointsA"],
            "pointsB": r["pointsB"],
            "gamesDecidedByFive": r["gamesDecidedByFive"],
            "gamesDecidedByTen": r["gamesDecidedByTen"],
            "seasonsWhereSeriesSplit": r["seasonsWhereSeriesSplit"],
            "meetingsInMostRecentSeason": r["meetingsInMostRecentSeason"],
            "rivalryIndex": r["rivalryIndex"],
        })
    fields = [
        "ownerIdA", "displayNameA", "ownerIdB", "displayNameB",
        "totalMeetings", "regularSeasonMeetings", "playoffMeetings",
        "winsA", "winsB", "ties",
        "pointsA", "pointsB",
        "gamesDecidedByFive", "gamesDecidedByTen",
        "seasonsWhereSeriesSplit", "meetingsInMostRecentSeason",
        "rivalryIndex",
    ]
    return "rivalries.csv", _write_csv(rows, fields)


# ── Awards ─────────────────────────────────────────────────────────────────
def export_awards(data: dict[str, Any]) -> tuple[str, str]:
    rows: list[dict[str, Any]] = []
    for season_row in data.get("bySeason", []):
        for a in season_row.get("awards", []):
            rows.append({
                "season": season_row["season"],
                "leagueId": season_row["leagueId"],
                "seasonStatus": season_row.get("seasonStatus"),
                "key": a["key"],
                "label": a["label"],
                "ownerId": a["ownerId"],
                "displayName": a["displayName"],
                "teamName": a.get("teamName"),
                "value": a.get("value"),
                "description": a.get("description"),
            })
    # Live races appended with season="_race" so filters are easy.
    for race in data.get("awardRaces", []):
        for leader in race.get("leaders", []):
            rows.append({
                "season": "_race",
                "leagueId": "",
                "seasonStatus": "in_progress",
                "key": race["key"],
                "label": race["label"],
                "ownerId": leader["ownerId"],
                "displayName": leader["displayName"],
                "teamName": "",
                "value": {**leader.get("value", {}), "rank": leader["rank"]},
                "description": race.get("description"),
            })
    fields = [
        "season", "leagueId", "seasonStatus",
        "key", "label", "ownerId", "displayName", "teamName",
        "value", "description",
    ]
    return "awards.csv", _write_csv(rows, fields)


# ── Records ────────────────────────────────────────────────────────────────
def export_records(data: dict[str, Any]) -> tuple[str, str]:
    rows: list[dict[str, Any]] = []

    def _tag(kind: str, rs: list[dict[str, Any]]):
        for r in rs:
            rows.append({"category": kind, **r})

    _tag("highest_single_week", data.get("singleWeekHighest", []))
    _tag("lowest_single_week", data.get("singleWeekLowest", []))
    _tag("biggest_margin", data.get("biggestMargin", []))
    _tag("narrowest_victory", data.get("narrowestVictory", []))
    _tag("most_points_in_loss", data.get("mostPointsInLoss", []))
    _tag("fewest_points_in_win", data.get("fewestPointsInWin", []))
    for r in data.get("mostPointsInSeason", []):
        rows.append({"category": "most_points_in_season", **r})
    for r in data.get("mostPointsAgainstInSeason", []):
        rows.append({"category": "most_points_against_in_season", **r})
    for r in data.get("longestWinStreaks", []):
        rows.append({"category": "longest_win_streak", **r})
    for r in data.get("longestLossStreaks", []):
        rows.append({"category": "longest_loss_streak", **r})

    fields = [
        "category", "ownerId", "displayName", "teamName",
        "season", "leagueId", "week", "isPlayoff",
        "points", "opponentPoints", "margin", "result",
        "length", "start", "end",
        "totalPoints", "totalPointsAgainst", "avgPoints", "weeksPlayed",
    ]
    return "records.csv", _write_csv(rows, fields)


# ── Franchise index ────────────────────────────────────────────────────────
def export_franchise(data: dict[str, Any], owner_id: str | None = None) -> tuple[str, str]:
    # Owner-scoped: season-by-season results for that one franchise.
    if owner_id:
        detail = (data.get("detail") or {}).get(owner_id)
        if not detail:
            return f"franchise-{owner_id}.csv", "season,message\n,No franchise record found\n"
        rows = []
        for r in detail.get("seasonResults", []):
            rows.append({
                "ownerId": owner_id,
                "displayName": detail.get("displayName"),
                **r,
            })
        fields = [
            "ownerId", "displayName",
            "season", "leagueId", "rosterId", "teamName",
            "wins", "losses", "ties",
            "pointsFor", "pointsAgainst",
            "standing", "finalPlace", "madePlayoffs",
        ]
        return f"franchise-{owner_id}.csv", _write_csv(rows, fields)

    # No owner: index summary.
    rows = data.get("index", [])
    fields = [
        "ownerId", "displayName", "currentTeamName", "avatar",
        "seasonsPlayed", "wins", "losses", "championships", "bestFinish",
    ]
    return "franchises.csv", _write_csv(rows, fields)


# ── Activity ───────────────────────────────────────────────────────────────
def export_activity(data: dict[str, Any]) -> tuple[str, str]:
    rows: list[dict[str, Any]] = []
    for t in data.get("feed", []):
        for side in t.get("sides", []):
            assets_str = " | ".join(
                a.get("playerName") or a.get("label") or ""
                for a in side.get("receivedAssets", [])
            )
            rows.append({
                "transactionId": t["transactionId"],
                "season": t["season"],
                "leagueId": t["leagueId"],
                "week": t.get("week"),
                "createdAt": t.get("createdAt"),
                "totalAssets": t["totalAssets"],
                "ownerId": side["ownerId"],
                "displayName": side.get("displayName") or side.get("teamName"),
                "teamName": side.get("teamName"),
                "receivedPlayerCount": side.get("receivedPlayerCount", 0),
                "receivedPickCount": side.get("receivedPickCount", 0),
                "notableAssetCount": side.get("notableAssetCount", 0),
                "receivedAssets": assets_str,
            })
    fields = [
        "transactionId", "season", "leagueId", "week", "createdAt",
        "totalAssets", "ownerId", "displayName", "teamName",
        "receivedPlayerCount", "receivedPickCount", "notableAssetCount",
        "receivedAssets",
    ]
    return "trade-activity.csv", _write_csv(rows, fields)


# ── Draft ──────────────────────────────────────────────────────────────────
def export_draft(data: dict[str, Any]) -> tuple[str, str]:
    rows: list[dict[str, Any]] = []
    for d in data.get("drafts", []):
        for p in d.get("picks", []):
            rows.append({
                "draftId": d["draftId"],
                "season": d["season"],
                "leagueId": d["leagueId"],
                "type": d.get("type"),
                "status": d.get("status"),
                **p,
            })
    fields = [
        "draftId", "season", "leagueId", "type", "status",
        "round", "pickNo", "rosterId", "ownerId", "teamName",
        "playerId", "playerName", "position", "nflTeam",
    ]
    return "draft-picks.csv", _write_csv(rows, fields)


# ── Weekly recap ──────────────────────────────────────────────────────────
def export_weekly(data: dict[str, Any]) -> tuple[str, str]:
    rows: list[dict[str, Any]] = []
    for w in data.get("weeks", []):
        for m in w.get("matchups", []):
            home = m.get("home") or {}
            away = m.get("away") or {}
            rows.append({
                "season": w["season"],
                "leagueId": w["leagueId"],
                "week": w["week"],
                "isPlayoff": w.get("isPlayoff"),
                "homeOwnerId": home.get("ownerId"),
                "homeDisplayName": home.get("displayName"),
                "homePoints": home.get("points"),
                "awayOwnerId": away.get("ownerId"),
                "awayDisplayName": away.get("displayName"),
                "awayPoints": away.get("points"),
                "margin": m.get("margin"),
                "winnerOwnerId": m.get("winnerOwnerId"),
            })
    fields = [
        "season", "leagueId", "week", "isPlayoff",
        "homeOwnerId", "homeDisplayName", "homePoints",
        "awayOwnerId", "awayDisplayName", "awayPoints",
        "margin", "winnerOwnerId",
    ]
    return "weekly-matchups.csv", _write_csv(rows, fields)


# ── Superlatives ───────────────────────────────────────────────────────────
def export_superlatives(data: dict[str, Any]) -> tuple[str, str]:
    rows: list[dict[str, Any]] = []
    for key, block in data.items():
        if not isinstance(block, dict) or "winner" not in block:
            continue
        winner = block["winner"]
        if not winner:
            continue
        rows.append({"superlative": key, **winner})
        # Also emit the full ranking so analysts can slice alternate orderings.
        for i, entry in enumerate(block.get("ranking", [])):
            if i == 0:
                continue
            rows.append({"superlative": f"{key}_ranking_{i+1}", **entry})
    fields = [
        "superlative", "ownerId", "displayName", "rosterSize",
        "qb", "rb", "wr", "te", "idp", "rookies",
        "trades", "waivers", "weightedPickScore", "balanceScore",
    ]
    return "superlatives.csv", _write_csv(rows, fields)


# ── Archives ───────────────────────────────────────────────────────────────
def export_archives(data: dict[str, Any], kind: str | None = None) -> tuple[str, str]:
    if kind and kind in data:
        rows = data[kind]
        # Flatten nested asset lists into pipe-delimited columns.
        flattened = []
        for r in rows:
            flat = {}
            for k, v in r.items():
                flat[k] = _cell(v)
            flattened.append(flat)
        fields = sorted({k for r in flattened for k in r.keys()})
        return f"archives-{kind}.csv", _write_csv(flattened, fields)
    # Default: trades (most useful single archive).
    return export_archives(data, kind="trades")


# ── Overview ───────────────────────────────────────────────────────────────
def export_overview(data: dict[str, Any]) -> tuple[str, str]:
    vitals = data.get("leagueVitals") or {}
    rows: list[dict[str, Any]] = [
        {"field": "seasonRangeLabel", "value": data.get("seasonRangeLabel")},
        {"field": "seasonsCovered", "value": vitals.get("seasonsCovered")},
        {"field": "managers", "value": vitals.get("managers")},
        {"field": "totalTrades", "value": vitals.get("totalTrades")},
        {"field": "totalWaivers", "value": vitals.get("totalWaivers")},
        {"field": "totalScoredWeeks", "value": vitals.get("totalScoredWeeks")},
    ]
    champ = data.get("currentChampion") or {}
    if champ:
        rows.append({"field": "currentChampion.displayName", "value": champ.get("displayName")})
        rows.append({"field": "currentChampion.season", "value": champ.get("season")})
    return "overview.csv", _write_csv(rows, ["field", "value"])


# ── Registry ───────────────────────────────────────────────────────────────
EXPORTERS: dict[str, Callable[[dict[str, Any]], tuple[str, str]]] = {
    "overview": export_overview,
    "history": export_history,
    "hall_of_fame": export_hall_of_fame,
    "rivalries": export_rivalries,
    "awards": export_awards,
    "records": export_records,
    "activity": export_activity,
    "draft": export_draft,
    "weekly": export_weekly,
    "superlatives": export_superlatives,
}


def export_section(section: str, data: dict[str, Any], **kwargs) -> tuple[str, str]:
    """Route to the right exporter.  Raises KeyError if unknown."""
    if section == "franchise":
        return export_franchise(data, owner_id=kwargs.get("owner_id"))
    if section == "archives":
        return export_archives(data, kind=kwargs.get("kind"))
    if section == "hallOfFame":
        return export_hall_of_fame(data)
    if section not in EXPORTERS:
        raise KeyError(f"No CSV exporter for section {section!r}")
    return EXPORTERS[section](data)
