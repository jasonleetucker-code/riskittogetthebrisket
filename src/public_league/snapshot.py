"""Public league snapshot — pipeline that fetches the last N dynasty
seasons from Sleeper and hands a normalized shape to every section
module.

This module MUST NOT read the private canonical pipeline, the private
``latest_data`` / ``latest_contract_data`` state, or any file
containing private rankings / edge signals.  The only inputs are the
league id + the Sleeper public API (via ``sleeper_client``).

The snapshot is intentionally "dumb": it pulls the raw Sleeper
payloads and normalizes them minimally (identity, season ordering).
Section modules do the actual compute on top of this snapshot so
every section sees the same consistent input.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import sleeper_client
from .identity import ManagerRegistry, build_manager_registry
from .sleeper_client import PUBLIC_MAX_SEASONS


# Weeks we will pull matchup + transaction payloads for.  Regular
# season + full playoffs covers every dynasty scoring format Sleeper
# supports today.  Weeks with no games return [] from Sleeper so the
# over-fetch is cheap.
_WEEK_RANGE = range(1, 19)


@dataclass
class SeasonSnapshot:
    """All Sleeper data the public pipeline needs for one season."""
    season: str
    league_id: str
    league: dict[str, Any]
    users: list[dict[str, Any]]
    rosters: list[dict[str, Any]]
    matchups_by_week: dict[int, list[dict[str, Any]]]
    transactions_by_week: dict[int, list[dict[str, Any]]]
    drafts: list[dict[str, Any]]
    draft_picks_by_draft: dict[str, list[dict[str, Any]]]
    traded_picks: list[dict[str, Any]]
    winners_bracket: list[dict[str, Any]]
    losers_bracket: list[dict[str, Any]]

    @property
    def is_complete(self) -> bool:
        """True if the season looks finished / post-playoffs."""
        status = str(self.league.get("status") or "").lower()
        return status in {"complete", "post_season", "postseason"}

    @property
    def season_type(self) -> str:
        return str(self.league.get("season_type") or "regular")

    @property
    def num_teams(self) -> int:
        total_rosters = int(self.league.get("total_rosters") or 0)
        if total_rosters:
            return total_rosters
        return len(self.rosters)


@dataclass
class PublicLeagueSnapshot:
    """Top-level public snapshot — one per request (cheap to rebuild)."""
    root_league_id: str
    generated_at: str
    seasons: list[SeasonSnapshot] = field(default_factory=list)
    managers: ManagerRegistry = field(default_factory=ManagerRegistry)

    @property
    def current_season(self) -> SeasonSnapshot | None:
        return self.seasons[0] if self.seasons else None

    @property
    def previous_seasons(self) -> list[SeasonSnapshot]:
        return self.seasons[1:]

    @property
    def season_ids(self) -> list[str]:
        return [s.season for s in self.seasons]

    @property
    def league_ids(self) -> list[str]:
        return [s.league_id for s in self.seasons]

    def season_by_league_id(self, league_id: str) -> SeasonSnapshot | None:
        want = str(league_id or "")
        for s in self.seasons:
            if s.league_id == want:
                return s
        return None


def _fetch_season(league_obj: dict[str, Any]) -> SeasonSnapshot:
    """Materialize a single SeasonSnapshot from a league object."""
    league_id = str(league_obj.get("league_id") or "")
    users = sleeper_client.fetch_users(league_id)
    rosters = sleeper_client.fetch_rosters(league_id)

    matchups: dict[int, list[dict[str, Any]]] = {}
    transactions: dict[int, list[dict[str, Any]]] = {}
    for week in _WEEK_RANGE:
        ms = sleeper_client.fetch_matchups(league_id, week)
        if ms:
            matchups[week] = ms
        tx = sleeper_client.fetch_transactions(league_id, week)
        if tx:
            transactions[week] = tx

    drafts = sleeper_client.fetch_drafts(league_id)
    draft_picks_by_draft: dict[str, list[dict[str, Any]]] = {}
    for draft in drafts:
        draft_id = str(draft.get("draft_id") or "")
        if not draft_id:
            continue
        draft_picks_by_draft[draft_id] = sleeper_client.fetch_draft_picks(draft_id)

    traded_picks = sleeper_client.fetch_traded_picks(league_id)
    winners = sleeper_client.fetch_winners_bracket(league_id)
    losers = sleeper_client.fetch_losers_bracket(league_id)

    season_key = str(league_obj.get("season") or "")
    return SeasonSnapshot(
        season=season_key,
        league_id=league_id,
        league=league_obj,
        users=users,
        rosters=rosters,
        matchups_by_week=matchups,
        transactions_by_week=transactions,
        drafts=drafts,
        draft_picks_by_draft=draft_picks_by_draft,
        traded_picks=traded_picks,
        winners_bracket=winners,
        losers_bracket=losers,
    )


def build_public_snapshot(
    root_league_id: str,
    max_seasons: int = PUBLIC_MAX_SEASONS,
) -> PublicLeagueSnapshot:
    """Build a PublicLeagueSnapshot for the last ``max_seasons`` dynasty
    seasons starting from ``root_league_id``.

    The chain walk follows Sleeper ``previous_league_id`` links.  If
    the chain is shorter than ``max_seasons`` (e.g. league is in its
    first season), the snapshot simply has fewer entries — every
    section module handles the short case.
    """
    snapshot = PublicLeagueSnapshot(
        root_league_id=str(root_league_id or "").strip(),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    if not snapshot.root_league_id:
        return snapshot

    chain = sleeper_client.walk_league_chain(snapshot.root_league_id, max_seasons=max_seasons)
    if not chain:
        return snapshot

    snapshot.seasons = [_fetch_season(league) for league in chain]
    snapshot.managers = build_manager_registry(
        [
            {
                "league": s.league,
                "users": s.users,
                "rosters": s.rosters,
            }
            for s in snapshot.seasons
        ]
    )
    return snapshot
