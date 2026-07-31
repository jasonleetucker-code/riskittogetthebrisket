"""Semantic FFPC public-page parser.

The parser keys off normalized table headers, labels, query parameters,
and data attributes. CSS class names are treated only as optional hints.
It accepts HTML snapshots so unit tests and reprocessing never require a
live request.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag

from src.platforms.assets import AssetResolver, normalize_asset_name
from src.platforms.base import (
    NormalizedBatch,
    NormalizedLeague,
    NormalizedManager,
    NormalizedManagerSeason,
    NormalizedMembership,
    NormalizedMovement,
    NormalizedTransaction,
    QUAL_INSUFFICIENT,
)
from src.platforms.ffpc.identity import resolve_identity

_HEADER_ALIASES = {
    "date": {"date", "timestamp", "processed", "transaction date", "time"},
    "type": {"type", "transaction type", "move"},
    "transaction_id": {"transaction id", "trans id", "id", "trade id"},
    "manager": {"manager", "owner", "user", "franchise owner"},
    "team": {"team", "team name", "franchise", "entry"},
    "team_id": {"team id", "entry id", "franchise id"},
    "counterparty": {"counterparty", "trade partner", "with"},
    "counterparty_team_id": {"counterparty team id", "partner team id"},
    "action": {"action", "direction", "added/dropped", "add/drop"},
    "player": {"player", "asset", "player/pick"},
    "player_id": {"player id", "asset id"},
    "position": {"position", "pos"},
    "nfl_team": {"nfl team", "pro team", "club"},
    "faab": {"faab", "bid", "winning bid", "waiver amount"},
    "week": {"week", "period"},
    "season": {"season", "year"},
    "wins": {"wins", "w"},
    "losses": {"losses", "l"},
    "ties": {"ties", "t"},
    "points_for": {"points for", "pf", "pts for"},
    "points_against": {"points against", "pa", "pts against"},
    "rank": {"rank", "place", "finish"},
    "playoffs": {"playoffs", "made playoffs", "postseason"},
    "champion": {"champion", "winner", "title"},
    "runner_up": {"runner up", "runner-up", "second"},
    "complete": {"complete", "completed", "season complete", "final"},
    "overall_pick": {"overall pick", "pick no", "pick number", "selection", "overall"},
    "round": {"round", "rd"},
    "slot": {"slot", "pick slot"},
    "original_owner": {"original owner", "original team", "from team"},
    "discriminator": {"discriminator", "asset discriminator"},
    "roster": {"roster", "players"},
}

_ACTION_ADD = {"add", "added", "acquire", "acquired", "receive", "received", "gets", "got"}
_ACTION_DROP = {"drop", "dropped", "release", "released", "send", "sent", "gives", "gave"}
_TRADE_TYPES = {"trade", "traded"}
_WAIVER_TYPES = {"waiver", "waivers", "blind bidding", "faab"}
_FREE_AGENT_TYPES = {"free agent", "free-agent", "freeagent", "add/drop"}
_TRUE = {"1", "true", "yes", "y", "x", "✓", "champion", "winner", "made"}


def _text(value: Any) -> str:
    if isinstance(value, Tag):
        value = value.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _header(value: Any) -> str:
    value = _text(value).lower().replace("#", " number ")
    value = re.sub(r"[^a-z0-9/ -]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _canonical_header(value: Any) -> str:
    normalized = _header(value)
    for canonical, aliases in _HEADER_ALIASES.items():
        if normalized in aliases:
            return canonical
    return normalized.replace(" ", "_")


def _table_rows(table: Tag) -> list[dict[str, Any]]:
    header_cells = table.select("thead tr th")
    if not header_cells:
        first = table.find("tr")
        header_cells = first.find_all(["th", "td"]) if first else []
    headers = [_canonical_header(c) for c in header_cells]
    if not headers:
        return []
    rows = []
    body_rows = table.select("tbody tr") or table.find_all("tr")[1:]
    for tr in body_rows:
        cells = tr.find_all(["td", "th"], recursive=False)
        if not cells or all(not _text(c) for c in cells):
            continue
        row: dict[str, Any] = {}
        for index, cell in enumerate(cells):
            key = headers[index] if index < len(headers) else f"column_{index}"
            row[key] = _text(cell)
            row[f"_{key}_tag"] = cell
        row["_row_tag"] = tr
        rows.append(row)
    return rows


def _find_tables(soup: BeautifulSoup, required: set[str]) -> list[tuple[Tag, list[dict[str, Any]]]]:
    matches = []
    for table in soup.find_all("table"):
        rows = _table_rows(table)
        if not rows:
            continue
        keys = {k for k in rows[0] if not k.startswith("_")}
        if required.issubset(keys):
            matches.append((table, rows))
    return matches


def _query_id(url: str | None, *keys: str) -> str | None:
    if not url:
        return None
    query = {k.lower(): v for k, v in parse_qs(urlparse(url).query).items()}
    for key in keys:
        values = query.get(key.lower())
        if values and _text(values[0]):
            return _text(values[0])
    return None


def _data_or_query(
    tag: Tag | None, url: str | None, attrs: Iterable[str], query: Iterable[str]
) -> str | None:
    if tag:
        for attr in attrs:
            value = _text(tag.get(attr))
            if value:
                return value
        link = tag.find("a", href=True)
        if link:
            for key in query:
                value = _query_id(link.get("href"), key)
                if value:
                    return value
    for key in query:
        value = _query_id(url, key)
        if value:
            return value
    return None


def _int(value: Any) -> int | None:
    match = re.search(r"-?\d+", _text(value).replace(",", ""))
    return int(match.group()) if match else None


def _float(value: Any) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", _text(value).replace(",", ""))
    return float(match.group()) if match else None


def _bool(value: Any) -> bool | None:
    raw = _text(value).lower()
    if not raw:
        return None
    if raw in _TRUE:
        return True
    if raw in {"0", "false", "no", "n", "-"}:
        return False
    return None


def _timestamp_ms(value: Any, *, default: int | None = None) -> int:
    raw = _text(value)
    if raw.isdigit():
        number = int(raw)
        return number if number > 10_000_000_000 else number * 1000
    variants = [raw, raw.replace(" ET", ""), raw.replace(" EST", ""), raw.replace(" EDT", "")]
    for candidate in variants:
        if not candidate:
            continue
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp() * 1000)
        except ValueError:
            pass
        for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M", "%m/%d/%Y", "%Y-%m-%d %H:%M"):
            try:
                parsed = datetime.strptime(candidate, fmt).replace(tzinfo=timezone.utc)
                return int(parsed.timestamp() * 1000)
            except ValueError:
                continue
    if default is not None:
        return int(default)
    raise ValueError(f"unparseable FFPC timestamp: {raw!r}")


def _tx_type(value: Any) -> str:
    raw = _text(value).lower()
    if raw in _TRADE_TYPES or "trade" in raw:
        return "trade"
    if raw in _WAIVER_TYPES or "waiver" in raw or "faab" in raw:
        return "waiver"
    if raw in _FREE_AGENT_TYPES or "free agent" in raw:
        return "free_agent"
    return ""


def _action(value: Any, tx_type: str) -> str:
    raw = _text(value).lower()
    if raw in _ACTION_ADD or any(token in raw for token in ("add", "acquir", "receiv", "gets")):
        return "add"
    if raw in _ACTION_DROP or any(token in raw for token in ("drop", "releas", "sent", "gives")):
        return "drop"
    # A waiver table sometimes omits action because every row is a claim.
    if tx_type in ("waiver", "free_agent") and not raw:
        return "add"
    return ""


def _row_source_id(
    row: dict[str, Any], key: str, data_names: tuple[str, ...], query_names: tuple[str, ...]
) -> str | None:
    direct = _text(row.get(key))
    if direct:
        return direct
    tag = row.get(f"_{key}_tag") or row.get("_row_tag")
    return _data_or_query(tag, None, data_names, query_names)


def _fingerprint(parts: Iterable[Any]) -> str:
    normalized = "\x1f".join(_text(p).lower() for p in parts)
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


@dataclass
class ParsedFFPCPage:
    batch: NormalizedBatch
    page_types: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)


class FFPCParser:
    def __init__(self, resolver: AssetResolver) -> None:
        self.resolver = resolver

    def parse(
        self,
        html: str,
        *,
        source_url: str,
        source_league_id: str,
        season: str | None = None,
        format_type: str | None = None,
        fetched_ms: int | None = None,
        sharp_eligible: bool = False,
        verified_global_ids: Iterable[str] = (),
        season_complete: bool | None = None,
    ) -> ParsedFFPCPage:
        soup = BeautifulSoup(html or "", "html.parser")
        batch = NormalizedBatch(platform="ffpc")
        result = ParsedFFPCPage(batch=batch)
        league_id = str(source_league_id)
        league_key = f"ffpc:{league_id}"
        page_text = _text(soup).lower()
        inferred_dynasty = None
        if format_type:
            inferred_dynasty = "dynasty" in format_type.lower()
        elif "dynasty" in page_text:
            inferred_dynasty = True
        source_sharp_eligible = bool(sharp_eligible and inferred_dynasty is True)
        batch.leagues.append(
            NormalizedLeague.build(
                "ffpc",
                league_id,
                season=season,
                name=self._league_name(soup),
                total_rosters=None,
                format_type=format_type,
                is_dynasty=inferred_dynasty,
                # This may be true only through an explicit source
                # configuration assertion; page wording alone never
                # certifies league age or format.
                sharp_eligible=source_sharp_eligible,
                metadata={
                    "sourceUrl": source_url,
                    "publicOnly": True,
                    "operatorVerifiedSharpEligibility": source_sharp_eligible,
                },
            )
        )

        verified_ids = {str(value).strip() for value in verified_global_ids if str(value).strip()}
        standings = self._parse_standings(
            soup,
            league_id=league_id,
            league_key=league_key,
            season=season,
            source_url=source_url,
            source_sharp_eligible=source_sharp_eligible,
            verified_global_ids=verified_ids,
            season_complete=season_complete,
        )
        if any(standings):
            result.page_types.add("standings")
            batch.managers.extend(standings[0])
            batch.memberships.extend(standings[1])
            batch.manager_seasons.extend(standings[2])

        roster_items = self._parse_rosters(
            soup,
            league_id=league_id,
            league_key=league_key,
            source_url=source_url,
        )
        if roster_items[0] or roster_items[1]:
            result.page_types.add("rosters")
            batch.managers.extend(roster_items[0])
            batch.memberships.extend(roster_items[1])
            batch.counters["unmappedPlayers"] = (
                batch.counters.get("unmappedPlayers", 0) + roster_items[2]
            )

        draft_results, draft_unmapped = self._parse_draft_results(
            soup, league_id=league_id, source_url=source_url
        )
        if draft_results:
            result.page_types.add("draft")
            batch.draft_results.extend(draft_results)
            batch.counters["unmappedPlayers"] = (
                batch.counters.get("unmappedPlayers", 0) + draft_unmapped
            )

        transactions = self._parse_transactions(
            soup,
            league_id=league_id,
            league_key=league_key,
            season=season,
            source_url=source_url,
            default_timestamp=fetched_ms,
        )
        if any(transactions[:3]):
            result.page_types.add("transactions")
            batch.managers.extend(transactions[0])
            batch.transactions.extend(transactions[1])
            batch.movements.extend(transactions[2])
            batch.counters.update(transactions[3])

        # Deduplicate entity rows without merging identities by name.
        batch.managers = list({m.manager_key: m for m in batch.managers}.values())
        batch.memberships = list(
            {(m.league_key, m.manager_key): m for m in batch.memberships}.values()
        )
        if not result.page_types:
            result.errors.append("no_supported_ffpc_tables")
        batch.warnings.extend(result.errors)
        return result

    @staticmethod
    def _league_name(soup: BeautifulSoup) -> str | None:
        meta = soup.find("meta", attrs={"name": re.compile("league[-_ ]?name", re.I)})
        if meta and _text(meta.get("content")):
            return _text(meta.get("content"))
        for selector in ("h1", "h2", "title"):
            tag = soup.find(selector)
            if tag and _text(tag):
                return _text(tag)
        return None

    def _parse_standings(
        self,
        soup: BeautifulSoup,
        *,
        league_id: str,
        league_key: str,
        season: str | None,
        source_url: str,
        source_sharp_eligible: bool,
        verified_global_ids: set[str],
        season_complete: bool | None,
    ):
        managers: list[NormalizedManager] = []
        memberships: list[NormalizedMembership] = []
        seasons: list[NormalizedManagerSeason] = []
        tables = _find_tables(soup, {"team", "wins", "losses"})
        for _table, rows in tables:
            team_count = len(rows)
            for row in rows:
                team_name = _text(row.get("team"))
                manager_name = _text(row.get("manager")) or team_name
                team_tag = row.get("_team_tag") or row.get("_row_tag")
                team_id = _data_or_query(
                    team_tag,
                    None,
                    ("data-team-id", "data-entry-id"),
                    ("teamid", "entryid"),
                )
                profile_url = None
                if isinstance(team_tag, Tag):
                    link = team_tag.find("a", href=True)
                    profile_url = link.get("href") if link else None
                global_id = _data_or_query(
                    row.get("_row_tag"),
                    None,
                    ("data-site-user-id", "data-user-id"),
                    (),
                ) or _query_id(profile_url, "siteuserid", "userid", "user_id")
                identity = resolve_identity(
                    league_id=league_id,
                    team_id=team_id,
                    manager_name=manager_name,
                    profile_url=profile_url,
                    explicit_global_id=global_id,
                    verified_global=bool(global_id and global_id in verified_global_ids),
                )
                managers.append(
                    NormalizedManager.build(
                        "ffpc",
                        identity.source_manager_id,
                        display_name=manager_name or team_name,
                        source_identity_type=identity.identity_type,
                        identity_scope=identity.identity_scope,
                        identity_confidence=identity.confidence,
                        metadata={"sourceUrl": source_url, "teamName": team_name},
                    )
                )
                memberships.append(
                    NormalizedMembership(
                        platform="ffpc",
                        league_key=league_key,
                        manager_key=identity.manager_key,
                        source_team_id=identity.team_id,
                        roster_id=identity.team_id,
                        team_name=team_name,
                        metadata={"sourceUrl": source_url},
                    )
                )
                explicit_complete = _bool(row.get("complete"))
                is_complete = (
                    bool(season_complete)
                    if season_complete is not None
                    else bool(explicit_complete)
                )
                wins = _int(row.get("wins"))
                losses = _int(row.get("losses"))
                ties = _int(row.get("ties"))
                rank = _int(row.get("rank"))
                made_playoffs = _bool(row.get("playoffs"))
                is_champion = _bool(row.get("champion"))
                is_runner_up = _bool(row.get("runner_up"))
                exclusion: list[str] = []
                if identity.identity_type in ("league_scoped_team", "name_only"):
                    exclusion.append("league_scoped_identity")
                elif identity.identity_type != "global_verified":
                    exclusion.append("insufficient_multi_league_identity")
                if not is_complete:
                    exclusion.append("missing_completed_season")
                if not season:
                    exclusion.append("unknown_season")
                if not source_sharp_eligible:
                    exclusion.append("unknown_or_ineligible_league_format")
                for value, reason in (
                    (wins, "missing_wins"),
                    (losses, "missing_losses"),
                    (ties, "missing_ties"),
                    (rank, "missing_final_standing"),
                    (made_playoffs, "missing_playoff_result"),
                    (is_champion, "missing_championship_result"),
                ):
                    if value is None:
                        exclusion.append(reason)
                row_sharp_eligible = not exclusion and team_count > 1
                seasons.append(
                    NormalizedManagerSeason(
                        platform="ffpc",
                        league_key=league_key,
                        season=str(season or "unknown"),
                        manager_key=identity.manager_key,
                        roster_id=identity.team_id,
                        wins=wins,
                        losses=losses,
                        ties=ties,
                        points_for=_float(row.get("points_for")),
                        points_against=_float(row.get("points_against")),
                        made_playoffs=made_playoffs,
                        is_champion=is_champion,
                        is_runner_up=is_runner_up,
                        finish_rank=rank,
                        team_count=team_count,
                        is_complete=is_complete,
                        sharp_eligible=row_sharp_eligible,
                        source_identity_type=identity.identity_type,
                        evidence_status=(
                            "automated_evidence" if row_sharp_eligible else QUAL_INSUFFICIENT
                        ),
                        exclusion_reasons=tuple(dict.fromkeys(exclusion)),
                        metadata={
                            "sourceUrl": source_url,
                            "publicOnly": True,
                            "operatorVerifiedSharpEligibility": source_sharp_eligible,
                        },
                    )
                )
        return managers, memberships, seasons

    def _parse_rosters(
        self,
        soup: BeautifulSoup,
        *,
        league_id: str,
        league_key: str,
        source_url: str,
    ) -> tuple[list[NormalizedManager], list[NormalizedMembership], int]:
        managers: dict[str, NormalizedManager] = {}
        memberships: dict[str, dict[str, Any]] = {}
        unmapped = 0
        for _table, rows in _find_tables(soup, {"team", "player"}):
            keys = {key for key in rows[0] if not key.startswith("_")} if rows else set()
            if "type" in keys or "action" in keys or ({"overall_pick", "round", "slot"} & keys):
                continue
            for row in rows:
                team_name = _text(row.get("team"))
                manager_name = _text(row.get("manager")) or team_name
                tag = row.get("_team_tag") or row.get("_row_tag")
                team_id = _data_or_query(
                    tag,
                    None,
                    ("data-team-id", "data-entry-id"),
                    ("teamid", "entryid"),
                )
                identity = resolve_identity(
                    league_id=league_id,
                    team_id=team_id,
                    manager_name=manager_name,
                    explicit_global_id=_data_or_query(
                        tag,
                        None,
                        ("data-site-user-id",),
                        (),
                    ),
                )
                managers[identity.manager_key] = NormalizedManager.build(
                    "ffpc",
                    identity.source_manager_id,
                    display_name=manager_name,
                    source_identity_type=identity.identity_type,
                    identity_scope=identity.identity_scope,
                    identity_confidence=identity.confidence,
                    metadata={"sourceUrl": source_url},
                )

                player_name = _text(row.get("player"))
                source_asset_id = _row_source_id(
                    row,
                    "player_id",
                    ("data-player-id", "data-asset-id"),
                    ("playerid", "assetid"),
                ) or "name:" + _fingerprint(
                    (
                        player_name,
                        _text(row.get("position")),
                        _text(row.get("nfl_team")),
                    )
                )
                resolution = self.resolver.resolve(
                    platform="ffpc",
                    source_asset_id=source_asset_id,
                    name=player_name,
                    nfl_team=_text(row.get("nfl_team")) or None,
                    position=_text(row.get("position")) or None,
                )
                if not resolution.resolved:
                    unmapped += 1
                membership = memberships.setdefault(
                    identity.manager_key,
                    {
                        "identity": identity,
                        "teamName": team_name,
                        "assets": [],
                    },
                )
                membership["assets"].append(
                    {
                        "sourceAssetId": source_asset_id,
                        "canonicalAssetId": resolution.canonical_asset_id,
                        "displayName": player_name or None,
                        "position": _text(row.get("position")) or None,
                        "nflTeam": _text(row.get("nfl_team")) or None,
                        "matchMethod": resolution.match_method,
                        "matchConfidence": resolution.confidence,
                        "mappingReason": resolution.reason,
                    }
                )

        normalized_memberships = []
        for manager_key, item in memberships.items():
            identity = item["identity"]
            normalized_memberships.append(
                NormalizedMembership(
                    platform="ffpc",
                    league_key=league_key,
                    manager_key=manager_key,
                    source_team_id=identity.team_id,
                    roster_id=identity.team_id,
                    team_name=item["teamName"],
                    metadata={
                        "sourceUrl": source_url,
                        "rosterAssets": item["assets"],
                    },
                )
            )
        return list(managers.values()), normalized_memberships, unmapped

    def _parse_draft_results(
        self,
        soup: BeautifulSoup,
        *,
        league_id: str,
        source_url: str,
    ) -> tuple[list[dict[str, Any]], int]:
        results: list[dict[str, Any]] = []
        unmapped = 0
        for table in soup.find_all("table"):
            rows = _table_rows(table)
            if not rows:
                continue
            keys = {key for key in rows[0] if not key.startswith("_")}
            if "player" not in keys or not ({"overall_pick", "round", "slot"} & keys):
                continue
            for row in rows:
                player_name = _text(row.get("player"))
                source_asset_id = _row_source_id(
                    row,
                    "player_id",
                    ("data-player-id", "data-asset-id"),
                    ("playerid", "assetid"),
                ) or "name:" + _fingerprint(
                    (player_name, _text(row.get("position")), _text(row.get("nfl_team")))
                )
                resolution = self.resolver.resolve(
                    platform="ffpc",
                    source_asset_id=source_asset_id,
                    name=player_name,
                    nfl_team=_text(row.get("nfl_team")) or None,
                    position=_text(row.get("position")) or None,
                )
                if not resolution.resolved:
                    unmapped += 1
                team_tag = row.get("_team_tag") or row.get("_row_tag")
                team_id = _data_or_query(
                    team_tag,
                    None,
                    ("data-team-id", "data-entry-id"),
                    ("teamid", "entryid"),
                )
                results.append(
                    {
                        "platform": "ffpc",
                        "sourceLeagueId": league_id,
                        "overallPick": _int(row.get("overall_pick")),
                        "round": _int(row.get("round")),
                        "slot": _int(row.get("slot")),
                        "teamId": team_id,
                        "teamName": _text(row.get("team")) or None,
                        "sourceAssetId": source_asset_id,
                        "canonicalAssetId": resolution.canonical_asset_id,
                        "playerName": player_name or None,
                        "position": _text(row.get("position")) or None,
                        "nflTeam": _text(row.get("nfl_team")) or None,
                        "matchMethod": resolution.match_method,
                        "matchConfidence": resolution.confidence,
                        "mappingReason": resolution.reason,
                        "sourceUrl": source_url,
                    }
                )
        return results, unmapped

    def _parse_transactions(
        self,
        soup: BeautifulSoup,
        *,
        league_id: str,
        league_key: str,
        season: str | None,
        source_url: str,
        default_timestamp: int | None,
    ):
        managers: list[NormalizedManager] = []
        prepared: list[dict[str, Any]] = []
        counters = {
            "transactionsDiscovered": 0,
            "transactionsDeduplicated": 0,
            "movementsSkippedAsDuplicates": 0,
            "unmappedPlayers": 0,
            "ambiguousManagerIdentities": 0,
            "parseFailures": 0,
        }
        candidates: list[dict[str, Any]] = []
        for table in soup.find_all("table"):
            rows = _table_rows(table)
            if not rows:
                continue
            keys = {key for key in rows[0] if not key.startswith("_")}
            if "player" in keys and ("action" in keys or "type" in keys):
                candidates.extend(rows)

        for row in candidates:
            tx_type = _tx_type(row.get("type"))
            action = _action(row.get("action"), tx_type)
            if not tx_type or not action:
                continue
            try:
                timestamp_ms = _timestamp_ms(row.get("date"), default=default_timestamp)
            except ValueError:
                counters["parseFailures"] += 1
                continue

            team_name = _text(row.get("team"))
            manager_name = _text(row.get("manager")) or team_name
            team_tag = row.get("_team_tag") or row.get("_row_tag")
            team_id = _data_or_query(
                team_tag,
                None,
                ("data-team-id", "data-entry-id"),
                ("teamid", "entryid"),
            )
            global_id = _data_or_query(
                team_tag,
                None,
                ("data-site-user-id", "data-user-id"),
                (),
            )
            identity = resolve_identity(
                league_id=league_id,
                team_id=team_id,
                manager_name=manager_name,
                explicit_global_id=global_id,
            )
            if identity.identity_type in ("league_scoped_team", "name_only"):
                counters["ambiguousManagerIdentities"] += 1
            managers.append(
                NormalizedManager.build(
                    "ffpc",
                    identity.source_manager_id,
                    display_name=manager_name or None,
                    source_identity_type=identity.identity_type,
                    identity_scope=identity.identity_scope,
                    identity_confidence=identity.confidence,
                    metadata={"sourceUrl": source_url, "teamName": team_name},
                )
            )

            counterparty_team_id = _text(row.get("counterparty_team_id")) or None
            counterparty_name = _text(row.get("counterparty")) or None
            counterparty_identity = None
            if counterparty_team_id or counterparty_name:
                counterparty_identity = resolve_identity(
                    league_id=league_id,
                    team_id=counterparty_team_id,
                    manager_name=counterparty_name,
                )
                managers.append(
                    NormalizedManager.build(
                        "ffpc",
                        counterparty_identity.source_manager_id,
                        display_name=counterparty_name,
                        source_identity_type=counterparty_identity.identity_type,
                        identity_scope=counterparty_identity.identity_scope,
                        identity_confidence=counterparty_identity.confidence,
                        metadata={"sourceUrl": source_url, "counterpartyOnly": True},
                    )
                )

            asset_name = _text(row.get("player"))
            pick_match = re.search(
                r"\b(20\d{2})\s*(?:(?:round|rd|r)\s*)?([1-6])(?:st|nd|rd|th)?\b",
                asset_name.lower(),
            )
            asset_type = "pick" if pick_match else "player"
            pick_season = pick_match.group(1) if pick_match else None
            pick_round = pick_match.group(2) if pick_match else None
            pick_owner = _text(row.get("original_owner")) or None
            if not pick_owner and asset_type == "pick":
                owner_match = re.search(
                    r"(?:from|original(?:ly)? owned by)\s+(.+)$", asset_name, re.I
                )
                pick_owner = owner_match.group(1).strip() if owner_match else None
            normalized_pick_owner = (
                re.sub(r"\s+", "-", pick_owner.strip().lower()) if pick_owner else None
            )
            source_asset_id = _row_source_id(
                row,
                "player_id",
                ("data-player-id", "data-asset-id"),
                ("playerid", "assetid"),
            )
            if not source_asset_id and asset_type == "pick" and pick_season and pick_round:
                source_asset_id = f"pick:{pick_season}:{pick_round}"
                if normalized_pick_owner:
                    source_asset_id += f":{normalized_pick_owner}"
            if not source_asset_id:
                source_asset_id = "name:" + _fingerprint(
                    (asset_name, _text(row.get("position")), _text(row.get("nfl_team")))
                )
            resolution = self.resolver.resolve(
                platform="ffpc",
                source_asset_id=source_asset_id,
                name=asset_name,
                nfl_team=_text(row.get("nfl_team")) or None,
                position=_text(row.get("position")) or None,
                asset_type=asset_type,
                pick_season=pick_season,
                pick_round=pick_round,
                pick_original_owner=normalized_pick_owner,
            )
            if not resolution.resolved:
                counters["unmappedPlayers"] += 1

            row_tag = row.get("_row_tag")
            authoritative_tx_id = _text(row.get("transaction_id")) or _data_or_query(
                row_tag,
                None,
                ("data-transaction-id", "data-trade-id"),
                ("transactionid", "tradeid"),
            )
            team_token = str(team_id or normalize_asset_name(team_name) or identity.manager_key)
            counterparty_token = str(
                counterparty_team_id
                or normalize_asset_name(counterparty_name)
                or (counterparty_identity.manager_key if counterparty_identity else "")
            )
            prepared.append(
                {
                    "row": row,
                    "txType": tx_type,
                    "action": action,
                    "identity": identity,
                    "counterpartyIdentity": counterparty_identity,
                    "timestampMs": timestamp_ms,
                    "week": _int(row.get("week")),
                    "season": _text(row.get("season")) or season,
                    "authoritativeTxId": authoritative_tx_id or None,
                    "teamToken": team_token,
                    "counterpartyToken": counterparty_token,
                    "sourceAssetId": source_asset_id,
                    "assetName": asset_name,
                    "assetType": asset_type,
                    "resolution": resolution,
                    "pickOwner": normalized_pick_owner,
                    "faabBid": _int(row.get("faab")),
                }
            )

        # Authoritative source ids win.  Without one, waivers remain
        # one row/claim each, while trade rows are grouped by timestamp
        # and connected participating-team sets.  The resulting fingerprint
        # uses sorted participants/assets, never display order, so two
        # team-side renderings of the same trade converge.
        unkeyed_trade_groups: dict[tuple[str | None, int, tuple[str, ...]], list[int]] = {}
        for index, item in enumerate(prepared):
            if item["authoritativeTxId"]:
                # FFPC public-page transaction ids are not documented as
                # globally unique. Scope them to the configured league
                # before the platform prefix is applied.
                item["sourceTxId"] = f"league:{league_id}:tx:{item['authoritativeTxId']}"
            elif item["txType"] != "trade":
                item["sourceTxId"] = f"league:{league_id}:fingerprint:" + _fingerprint(
                    (
                        league_id,
                        item["season"],
                        item["txType"],
                        item["timestampMs"],
                        item["teamToken"],
                        item["sourceAssetId"],
                        item["action"],
                        item["faabBid"],
                    )
                )
            else:
                participant_pair = tuple(
                    sorted(
                        {
                            token
                            for token in (
                                item["teamToken"],
                                item["counterpartyToken"],
                            )
                            if token
                        }
                    )
                )
                # Pair scoping prevents two trades made by the same
                # manager at the same displayed timestamp from being
                # collapsed into one transaction.
                unkeyed_trade_groups.setdefault(
                    (item["season"], item["timestampMs"], participant_pair),
                    [],
                ).append(index)

        for (row_season, timestamp_ms, participants), component in unkeyed_trade_groups.items():
            assets = sorted(
                {
                    str(
                        prepared[index]["resolution"].canonical_asset_id
                        or prepared[index]["sourceAssetId"]
                    )
                    for index in component
                }
            )
            faab_values = sorted(
                str(prepared[index]["faabBid"])
                for index in component
                if prepared[index]["faabBid"] is not None
            )
            source_tx_id = f"league:{league_id}:fingerprint:" + _fingerprint(
                (
                    league_id,
                    row_season,
                    "trade",
                    timestamp_ms,
                    *participants,
                    *assets,
                    *faab_values,
                )
            )
            for index in component:
                prepared[index]["sourceTxId"] = source_tx_id

        transactions: dict[str, NormalizedTransaction] = {}
        movements: dict[str, NormalizedMovement] = {}
        seen_raw_movement_keys: set[str] = set()
        seen_transaction_references: set[str] = set()
        for item in prepared:
            source_tx_id = str(item["sourceTxId"])
            transaction_key = f"ffpc:{source_tx_id}"
            if transaction_key in seen_transaction_references:
                counters["transactionsDeduplicated"] += 1
            else:
                seen_transaction_references.add(transaction_key)
            if transaction_key not in transactions:
                transactions[transaction_key] = NormalizedTransaction.build(
                    "ffpc",
                    source_tx_id,
                    league_key=league_key,
                    season=str(item["season"] or "") or None,
                    week=item["week"],
                    transaction_type=item["txType"],
                    status="complete",
                    created_ms=item["timestampMs"],
                    source_url=source_url,
                    metadata={
                        "publicOnly": True,
                        "sourceReference": source_tx_id,
                        "authoritativeSourceId": bool(item["authoritativeTxId"]),
                    },
                )
            resolution = item["resolution"]
            discriminator = (
                _text(item["row"].get("discriminator"))
                or item["pickOwner"]
                or item["sourceAssetId"]
            )
            source_movement_id = _fingerprint(
                (
                    source_tx_id,
                    item["identity"].manager_key,
                    item["action"],
                    resolution.canonical_asset_id or item["sourceAssetId"],
                    discriminator,
                )
            )
            movement_key = f"ffpc:{source_movement_id}"
            if movement_key in seen_raw_movement_keys:
                counters["movementsSkippedAsDuplicates"] += 1
                continue
            seen_raw_movement_keys.add(movement_key)
            movements[movement_key] = NormalizedMovement.build(
                "ffpc",
                source_movement_id,
                transaction_key=transaction_key,
                league_key=league_key,
                canonical_asset_id=resolution.canonical_asset_id,
                source_asset_id=item["sourceAssetId"],
                source_name=item["assetName"],
                asset_type=item["assetType"],
                action=item["action"],
                manager_key=item["identity"].manager_key,
                roster_id=item["identity"].team_id,
                counterparty_manager_key=(
                    item["counterpartyIdentity"].manager_key
                    if item["counterpartyIdentity"]
                    else None
                ),
                timestamp_ms=item["timestampMs"],
                week=item["week"],
                faab_bid=item["faabBid"],
                source_url=source_url,
                metadata={
                    "sourceReference": source_tx_id,
                    "normalizedName": resolution.normalized_name,
                    "nflTeam": _text(item["row"].get("nfl_team")) or None,
                    "position": _text(item["row"].get("position")) or None,
                    "matchMethod": resolution.match_method,
                    "matchConfidence": resolution.confidence,
                    "mappingReason": resolution.reason,
                    "mappingCandidates": list(resolution.candidates),
                    "qualificationMethod": "unresolved_at_ingest",
                    "publicOnly": True,
                },
            )

        counters["transactionsDiscovered"] = len(transactions)
        return managers, list(transactions.values()), list(movements.values()), counters
