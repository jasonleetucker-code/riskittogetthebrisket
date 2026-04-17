"""Manager identity for the public league experience.

The authoritative aggregation key for every section module is the
Sleeper ``owner_id`` (a Sleeper ``user_id``).  Two invariants must
hold across all public sections:

    1. The same human is never split across team-name renames.  If
       Jason renames his team between seasons, history under the
       previous name still attributes to his owner_id.
    2. Two different owner_ids are never merged just because a
       ``roster_id`` slot or team name happens to match.  When an
       orphaned roster changes hands, history must attribute to the
       owner who actually held the roster at the time.

Display metadata (team name, avatar) is stored as a per-season alias
list.  The most recent alias wins for primary display, but every
season's alias is retained so franchise pages can show the lineage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class TeamAlias:
    """Per-season team-name snapshot for a manager."""
    season: str
    league_id: str
    team_name: str
    display_name: str = ""
    avatar: str = ""
    roster_id: int | None = None


@dataclass
class Manager:
    """Owner-id-keyed manager identity for the public league."""
    owner_id: str
    display_name: str = ""
    avatar: str = ""
    aliases: list[TeamAlias] = field(default_factory=list)
    # roster_id the manager held in the most recent season (if any).
    current_roster_id: int | None = None
    current_team_name: str = ""
    current_league_id: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        """Slim, public-safe serialization of a manager."""
        return {
            "ownerId": self.owner_id,
            "displayName": self.display_name or self.current_team_name or "Unknown",
            "avatar": self.avatar or "",
            "currentTeamName": self.current_team_name or "",
            "currentRosterId": self.current_roster_id,
            "currentLeagueId": self.current_league_id or "",
            "aliases": [
                {
                    "season": a.season,
                    "leagueId": a.league_id,
                    "teamName": a.team_name,
                    "displayName": a.display_name,
                    "avatar": a.avatar,
                    "rosterId": a.roster_id,
                }
                for a in self.aliases
            ],
        }


@dataclass
class ManagerRegistry:
    """Collection of managers keyed by owner_id."""
    by_owner_id: dict[str, Manager] = field(default_factory=dict)
    # (league_id, roster_id) -> owner_id, built from each season's
    # roster snapshot.  Used to attribute matchups / trades / picks
    # to the owner who held a roster AT THAT SEASON — never a later
    # or earlier owner.
    roster_to_owner: dict[tuple[str, int], str] = field(default_factory=dict)

    def owner_for_roster(self, league_id: str, roster_id: Any) -> str:
        """Look up the owner_id for (league_id, roster_id), or ``""``."""
        try:
            rid_int = int(roster_id)
        except (TypeError, ValueError):
            return ""
        return self.roster_to_owner.get((str(league_id or ""), rid_int), "")

    def ordered_managers(self) -> list[Manager]:
        return sorted(self.by_owner_id.values(), key=lambda m: m.display_name.lower())

    def to_public_list(self) -> list[dict[str, Any]]:
        return [m.to_public_dict() for m in self.ordered_managers()]


def _season_key(league: dict[str, Any]) -> str:
    """Return a stable string season key for a league object."""
    season = league.get("season") or league.get("season_type") or ""
    return str(season or "").strip()


def build_manager_registry(seasons: Iterable[dict[str, Any]]) -> ManagerRegistry:
    """Build the manager registry from ordered season payloads.

    Each element in ``seasons`` must be a dict shaped like::

        {
            "league": {...},           # Sleeper league object
            "users":   [...],          # Sleeper users list
            "rosters": [...],          # Sleeper rosters list
        }

    Seasons must be ordered current → previous (most recent first).
    The first season's alias wins for ``display_name`` / avatar.
    """
    registry = ManagerRegistry()
    for idx, season in enumerate(seasons):
        league = season.get("league") or {}
        users = season.get("users") or []
        rosters = season.get("rosters") or []
        league_id = str(league.get("league_id") or "")
        season_key = _season_key(league)

        user_by_id: dict[str, dict[str, Any]] = {}
        for u in users:
            uid = str(u.get("user_id") or "")
            if uid:
                user_by_id[uid] = u

        for roster in rosters:
            owner_id = str(roster.get("owner_id") or "").strip()
            if not owner_id:
                # Orphaned roster — skip; we refuse to invent a
                # pseudo-owner.  History for this roster in this season
                # will simply be attributed to "" and filtered out.
                continue
            try:
                rid_int = int(roster.get("roster_id"))
            except (TypeError, ValueError):
                rid_int = None

            user = user_by_id.get(owner_id) or {}
            metadata = user.get("metadata") or {}
            team_name = (
                metadata.get("team_name")
                or user.get("display_name")
                or f"Team {rid_int if rid_int is not None else owner_id}"
            )
            display_name = user.get("display_name") or team_name
            avatar = str(user.get("avatar") or metadata.get("avatar") or "")

            alias = TeamAlias(
                season=season_key,
                league_id=league_id,
                team_name=str(team_name),
                display_name=str(display_name),
                avatar=avatar,
                roster_id=rid_int,
            )

            manager = registry.by_owner_id.get(owner_id)
            if manager is None:
                manager = Manager(
                    owner_id=owner_id,
                    display_name=str(display_name),
                    avatar=avatar,
                )
                registry.by_owner_id[owner_id] = manager

            manager.aliases.append(alias)

            # Current-season attribution wins for primary display.
            if idx == 0:
                manager.display_name = str(display_name)
                manager.avatar = avatar
                manager.current_team_name = str(team_name)
                manager.current_roster_id = rid_int
                manager.current_league_id = league_id

            if rid_int is not None and league_id:
                registry.roster_to_owner[(league_id, rid_int)] = owner_id

    # Dedupe aliases by (season, league_id, team_name) preserving first
    # occurrence so rescans don't multiply entries.
    for manager in registry.by_owner_id.values():
        seen: set[tuple[str, str, str]] = set()
        deduped: list[TeamAlias] = []
        for alias in manager.aliases:
            key = (alias.season, alias.league_id, alias.team_name)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(alias)
        manager.aliases = deduped

    return registry
