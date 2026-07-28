"""Score projected stat lines under exact league scoring.

Reuses the production stats→points path
(``src.nfl_data.realized_points.compute_weekly_points``) rather than
introducing a second scoring engine — ADR-005/ADR-006 established that
Sleeper ``scoring_settings`` keys are the event vocabulary and that
scoring is a pure dot product plus threshold bonuses.  BDVM feeds the
same code a *per-game projected* stat line instead of a realized weekly
row, so any league config that scores history correctly scores
projections identically (raw-stat/direct-point consistency for free).

Stat-line vocabulary = the nflverse stat-row columns that
``compute_weekly_points`` reads: ``passing_yards``, ``passing_tds``,
``interceptions``, ``rushing_yards``, ``rushing_tds``, ``receptions``,
``receiving_yards``, ``receiving_tds``, ``fumbles_lost``,
``def_tackles_solo``, ``def_tackle_assists``, ``def_sacks``, … (see the
``_SIMPLE_KEYS`` / ``_IDP_KEYS`` maps in ``realized_points``).

Known limitation (documented, second-order): threshold bonuses
(``bonus_pass_yd_300`` etc.) are evaluated against the per-game *mean*
stat line, so a projection that averages 290 pass yards contributes no
300-yard-game bonus even though some individual weeks would clear it.

The vocabulary gap that is NOT second-order: **first downs.**  The
scorer reads them from ``*_first_downs`` columns and no projection
source publishes those, so a projected line scored as-is contributes
zero first-down points under a card that pays 1.00 each — understating
a QB by 30% and a back by 22%, unevenly, and putting real-source
players ~24% below proxy players who were scored from realized rows
that do have the columns.  ``impute_first_downs=True`` closes it from
the measured one-per-twenty-yards relationship; see
:mod:`src.nfl_data.first_down_rate` for the fit and for why this is
measurement rather than invention.
"""

from __future__ import annotations

from typing import Any, Mapping

from src.nfl_data.first_down_rate import with_imputed_first_downs
from src.nfl_data.realized_points import compute_weekly_points

# Positions whose stat lines may carry IDP keys.
IDP_TRUE_POSITIONS = frozenset(
    {"DT", "EDGE", "DE", "NT", "LB", "ILB", "OLB", "MLB", "CB", "S", "FS", "SS", "DL", "DB"}
)


def score_stat_line_per_game(
    stat_line: Mapping[str, Any],
    scoring_settings: Mapping[str, Any],
    *,
    position: str,
    impute_first_downs: bool = False,
) -> float:
    """Fantasy points for one per-game projected stat line.

    ``position`` gates position-conditional rules (TE reception bonus,
    IDP keys) exactly as the realized path does.

    ``impute_first_downs`` fills the one vocabulary gap between a
    projection and a realized row — see the module docstring.  It
    defaults to False so nothing changes implicitly and the one caller
    that wants it says so at the call site; it is a no-op on a line that
    already carries first downs, on an unmeasured position, and in a
    league that does not pay the bonus.
    """
    row, _ = (
        with_imputed_first_downs(stat_line, position)
        if impute_first_downs
        else (dict(stat_line), False)
    )
    row.setdefault("season", 0)
    row.setdefault("week", 0)
    result = compute_weekly_points(row, dict(scoring_settings), position=position)
    if result is None:  # only when stat_line is empty/falsy
        return 0.0
    return float(result.fantasy_points)


def season_line_to_per_game(stat_line: Mapping[str, Any], games: float) -> dict[str, float]:
    """Convert a season-total projected stat line to per-game."""
    if games <= 0:
        raise ValueError(f"games must be positive, got {games}")
    out: dict[str, float] = {}
    for key, val in stat_line.items():
        try:
            out[key] = float(val) / games
        except (TypeError, ValueError):
            continue
    return out


def is_idp_position(position: str | None) -> bool:
    return bool(position) and str(position).upper() in IDP_TRUE_POSITIONS
