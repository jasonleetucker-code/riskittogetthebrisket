"""Which leagues the rookie-auction curve is configured for — fail closed.

Owner scope correction 2026-10-18: ``dynasty_main`` ("Risk It to Get the
Brisket") is the only league in scope.  The approved spreadsheet formula and
the $1,200-per-class budget apply to it specifically — 12 teams, 6 rounds, 72
picks per class, offense and IDP rookies.  Every other league key is NOT
CONFIGURED: the engine refuses it rather than adapting the formula, and
nothing here deletes or rewrites another league's records.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["LeagueDraftScope", "LeagueNotConfiguredError", "SCOPED_LEAGUES", "league_scope"]


class LeagueNotConfiguredError(LookupError):
    """The rookie-auction curve is not configured for this league."""


@dataclass(frozen=True)
class LeagueDraftScope:
    league_key: str
    team_count: int
    rounds: int
    budget_dollars_per_class: int
    idp_eligible: bool

    @property
    def pick_count(self) -> int:
        return self.team_count * self.rounds


SCOPED_LEAGUES: dict[str, LeagueDraftScope] = {
    "dynasty_main": LeagueDraftScope(
        league_key="dynasty_main",
        team_count=12,
        rounds=6,
        budget_dollars_per_class=1200,
        idp_eligible=True,
    ),
}


def league_scope(league_key: str | None) -> LeagueDraftScope:
    scope = SCOPED_LEAGUES.get(str(league_key or ""))
    if scope is None:
        raise LeagueNotConfiguredError(
            f"rookie-auction curve not configured for league {league_key!r} "
            "(owner scope 2026-10-18: dynasty_main only)"
        )
    return scope
