"""Resolve each input league to a per-season league object.

Target seasons default to ``[2022, 2023, 2024, 2025]``. Every season
that cannot be resolved is reported as a warning — the tool must
never silently substitute the wrong year.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .sleeper_client import fetch_league_chain

DEFAULT_SEASONS: tuple[int, ...] = (2022, 2023, 2024, 2025)


@dataclass
class SeasonResolution:
    season: int
    league_id: str | None
    league: dict[str, Any] | None
    resolved: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "league_id": self.league_id,
            "league_name": (self.league or {}).get("name") if self.league else None,
            "resolved": self.resolved,
            "reason": self.reason,
        }


@dataclass
class LeagueChain:
    input_league_id: str
    walk: list[dict[str, Any]] = field(default_factory=list)
    seasons: dict[int, SeasonResolution] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_league_id": self.input_league_id,
            "chain": [
                {
                    "league_id": node.get("league_id"),
                    "season": _coerce_season(node.get("season")),
                    "name": node.get("name"),
                    "previous_league_id": node.get("previous_league_id"),
                }
                for node in self.walk
            ],
            "seasons": {str(s): res.to_dict() for s, res in self.seasons.items()},
            "warnings": list(self.warnings),
        }


def _coerce_season(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def resolve_seasons(
    league_id: str,
    *,
    seasons: Iterable[int] = DEFAULT_SEASONS,
    max_hops: int = 10,
    chain_fetcher: Callable[[str, int], list[dict[str, Any]]] | None = None,
) -> LeagueChain:
    """Walk a Sleeper league back through ``previous_league_id``.

    Each target season is matched against the league ``season`` field
    emitted by Sleeper. A season with no matching league is recorded
    with ``resolved=False`` and a user-visible reason.
    """
    fetcher = chain_fetcher or fetch_league_chain
    chain = LeagueChain(input_league_id=str(league_id or "").strip())
    if not chain.input_league_id:
        chain.warnings.append("Empty league ID supplied.")
        for season in seasons:
            chain.seasons[int(season)] = SeasonResolution(
                season=int(season),
                league_id=None,
                league=None,
                resolved=False,
                reason="No league ID supplied.",
            )
        return chain

    walk = fetcher(chain.input_league_id, max_hops)
    chain.walk = list(walk)
    if not walk:
        chain.warnings.append(
            f"Could not fetch league {chain.input_league_id} from Sleeper."
        )

    by_season: dict[int, dict[str, Any]] = {}
    for node in walk:
        season = _coerce_season(node.get("season"))
        if season is None:
            continue
        by_season.setdefault(season, node)

    for season in sorted({int(s) for s in seasons}):
        node = by_season.get(season)
        if node is None:
            chain.seasons[season] = SeasonResolution(
                season=season,
                league_id=None,
                league=None,
                resolved=False,
                reason=(
                    f"Season {season} not found in previous_league_id chain for "
                    f"{chain.input_league_id}."
                ),
            )
            chain.warnings.append(
                f"Missing season {season} for league {chain.input_league_id}."
            )
            continue
        chain.seasons[season] = SeasonResolution(
            season=season,
            league_id=str(node.get("league_id") or ""),
            league=node,
            resolved=True,
        )
    return chain
