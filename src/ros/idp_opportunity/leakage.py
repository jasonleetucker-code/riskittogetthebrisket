"""Point-in-time season store and the no-leakage guard.

:class:`SeasonData` holds a whole season.  Nothing that builds a feature may read it
directly: features are built from an :class:`AsOfView` whose ``cutoff`` is the target
week ``W``.  Every timed accessor refuses a week ``>= W`` with :class:`LeakageError`.
Two pre-game facts about week ``W`` itself are readable, each through a named method
that says what it is: the scheduled opponent (:meth:`AsOfView.pregame_opponent`) and
the week-``W`` injury report (:meth:`AsOfView.pregame_injury_report`, labelled
point-in-time UNVERIFIED because the published file carries no timestamp).

Pure: no I/O, no clock.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

__all__ = ["AsOfView", "LeakageError", "SeasonData"]


class LeakageError(RuntimeError):
    """A feature for week ``W`` tried to read data from week ``>= W``."""


@dataclass(frozen=True)
class SeasonData:
    """One season of inputs, keyed by week.  Immutable by convention.

    * ``stats`` — ``{week: {sleeper_id: stat line}}`` (Sleeper keys, incl. ``def_snp``
      and ``tm_def_snp``).
    * ``team_of`` — ``{week: {sleeper_id: (team, opponent)}}`` from nflverse.
    * ``offense`` — ``{week: {team: {"dropbacks", "wr_targets"}}}`` (that team's OFFENSE).
    * ``schedule`` — ``{week: {team: opponent}}`` (pre-game fact).
    * ``injury_report`` — ``{week: {team: {sleeper_id: status}}}`` (pre-game, PIT unverified).
    * ``positions`` — ``{sleeper_id: (family, subgroup)}``.
    """

    season: int
    stats: Mapping[int, Mapping[str, Mapping[str, Any]]]
    team_of: Mapping[int, Mapping[str, tuple[str, str]]] = field(default_factory=dict)
    offense: Mapping[int, Mapping[str, Mapping[str, float]]] = field(default_factory=dict)
    schedule: Mapping[int, Mapping[str, str]] = field(default_factory=dict)
    injury_report: Mapping[int, Mapping[str, Mapping[str, str]]] = field(default_factory=dict)
    positions: Mapping[str, tuple[str, str]] = field(default_factory=dict)

    def view(self, cutoff_week: int) -> AsOfView:
        return AsOfView(self, int(cutoff_week))


class AsOfView:
    """Everything knowable before week ``cutoff`` kicks off."""

    __slots__ = ("_data", "cutoff")

    def __init__(self, data: SeasonData, cutoff: int) -> None:
        self._data = data
        self.cutoff = int(cutoff)

    # -- guard -------------------------------------------------------------
    def _check(self, week: int, what: str) -> int:
        w = int(week)
        if w >= self.cutoff:
            raise LeakageError(
                f"{what} for week {w} requested by a feature for week {self.cutoff}: "
                "only weeks before the target week may be read"
            )
        return w

    @property
    def season(self) -> int:
        return self._data.season

    def narrow(self, cutoff: int) -> AsOfView:
        """A view with an EARLIER (or equal) cutoff.  Widening is refused."""
        if int(cutoff) > self.cutoff:
            raise LeakageError(f"cannot widen a week-{self.cutoff} view to week {cutoff}")
        return AsOfView(self._data, int(cutoff))

    # -- timed data (weeks < cutoff) ----------------------------------------
    def weeks_before(self) -> list[int]:
        return sorted(w for w in self._data.stats if w < self.cutoff)

    def stats_week(self, week: int) -> Mapping[str, Mapping[str, Any]]:
        return self._data.stats.get(self._check(week, "stat lines"), {})

    def team_week(self, week: int) -> Mapping[str, tuple[str, str]]:
        return self._data.team_of.get(self._check(week, "team / opponent"), {})

    def offense_week(self, week: int) -> Mapping[str, Mapping[str, float]]:
        return self._data.offense.get(self._check(week, "offense volume"), {})

    # -- static attribute -----------------------------------------------------
    def position(self, sleeper_id: str) -> tuple[str, str] | None:
        return self._data.positions.get(str(sleeper_id))

    # -- labelled pre-game facts about the cutoff week -------------------------
    def pregame_opponent(self, team: str) -> str | None:
        """Week ``cutoff``'s scheduled opponent — published before the season."""
        return self._data.schedule.get(self.cutoff, {}).get(team)

    def pregame_injury_report(self, team: str) -> Mapping[str, str]:
        """Week ``cutoff``'s injury-report statuses for ``team``.

        A pre-game document by NFL rule, but the published file is not timestamped or
        immutably archived: point-in-time UNVERIFIED.  Only M3 / M5 read it.
        """
        return self._data.injury_report.get(self.cutoff, {}).get(team, {})
