"""First downs per yard, measured — for scoring lines that omit them.

The problem
───────────
This league pays a first-down bonus: 1.00 for RB/WR/TE, 0.67 for QB.
Realized scoring reads it straight off nflverse's ``*_first_downs``
columns and is exact.

**Projections do not have those columns.**  No projection source
publishes first downs — Mike Clay's guide emits attempts, completions,
yards, receptions and touchdowns, and that is typical.  So a projected
stat line scored through the same engine contributes **zero** first-down
points, and the omission is large:

    QB  4,200 pass yds + 320 rush   understated  30.5%
    RB  1,150 rush + 400 rec        understated  22.5%
    WR  1,250 rec                   understated  23.6%
    TE    820 rec                   understated  24.6%

Worse than large, it is **uneven** — 1.44x for a QB against 1.29x for a
back — so it does not cancel out of a relative comparison the way a
uniform scale error would.  And worst of all it is *mixed*: BDVM's
reconstructed baseline scores REAL weekly rows, which do carry the
columns, so a player covered by a real projection source would sit ~24%
below an otherwise identical player still on the proxy, inside the same
snapshot.

Why imputing here is measurement and not invention
──────────────────────────────────────────────────
First downs are very nearly a function of yards.  Fit through the origin
on 2023-25 regular seasons, players with 200+ total yards:

    pos    n    fd/yard    R^2     yards per first down
    QB   186    0.04998   0.9896          20.0
    RB   241    0.04964   0.9417          20.1
    WR   355    0.04715   0.9382          21.2
    TE   142    0.05090   0.9105          19.6

All four positions are within 8% of each other and all are essentially
**one first down per twenty yards**.  The constants drift 2.0-4.8%
across the three seasons, so this is not a quantity that needs refitting
often.

Through the origin deliberately: zero yards must mean zero first downs.
A fitted intercept — +1.2 for WRs, +4.2 for TEs on the same data — would
hand free first downs to a player projected for almost nothing.

So the choice is not "impute or stay pure".  It is between a number that
is right to within R^2 = 0.91-0.99, and a *guaranteed* 22-30% error that
is different per position.  The first is better, and it is only honest
if it is labelled — hence :func:`with_imputed_first_downs` returning
whether it fired, and callers stamping it.

What this deliberately does NOT do
──────────────────────────────────
* **Never touches a line that already has first downs.**  A source that
  supplies them is authoritative and is passed through untouched, so the
  double-count guard is structural rather than a rule someone has to
  remember.
* **Never guesses a position it has not measured.**  An unknown position
  returns ``None``, not a league-average rate.
* **Never runs on realized stats.**  Those have the real columns; this
  module exists for the projection boundary only.
* **Does not become a valuation axis.**  Whether first downs carry
  signal *beyond* yards is a different question, and it was measured
  and answered no — see ``docs/first-down-signal.md``.

A league that does not pay first downs is unaffected without a gate:
``compute_weekly_points`` multiplies by a rate of 0.0.
"""

from __future__ import annotations

import statistics
from typing import Any, Iterable, Mapping

__all__ = [
    "FIRST_DOWNS_PER_YARD",
    "FIRST_DOWN_COLUMNS",
    "FIT_R_SQUARED",
    "YARD_COLUMNS",
    "SLEEPER_PROJECTED_FD_KEYS",
    "SLEEPER_YARD_KEYS",
    "fit_first_downs_per_yard",
    "imputed_first_down_column",
    "imputed_sleeper_first_down_bonus",
    "supplies_first_downs",
    "with_imputed_first_downs",
]

#: Columns a stat line may carry first downs in.  Mirrors
#: ``realized_points._FIRST_DOWN_COLUMNS`` — they must agree, or this
#: module would impute on top of a line the scorer already reads.
FIRST_DOWN_COLUMNS: tuple[str, ...] = (
    "passing_first_downs",
    "rushing_first_downs",
    "receiving_first_downs",
)

#: Columns summed to get the yardage first downs are imputed from.
YARD_COLUMNS: tuple[str, ...] = (
    "passing_yards",
    "rushing_yards",
    "receiving_yards",
)

#: FITTED, not chosen.  See the module docstring for the table and
#: :func:`fit_first_downs_per_yard` for the refitter.  Regenerate with::
#:
#:     python3 -c "from src.nfl_data.first_down_rate import *; \
#:                 from src.nfl_data.ingest import fetch_weekly_stats; \
#:                 print(fit_first_downs_per_yard(fetch_weekly_stats([2023,2024,2025])))"
FIRST_DOWNS_PER_YARD: dict[str, float] = {
    "QB": 0.04998,
    "RB": 0.04964,
    "WR": 0.04715,
    "TE": 0.05090,
}

#: How well yards determines first downs, per position.  Shipped
#: alongside the rate rather than buried in a commit message, because a
#: caller deciding whether to trust an imputed value needs to know that
#: a QB's is near-deterministic and a TE's is merely good.
FIT_R_SQUARED: dict[str, float] = {
    "QB": 0.9896,
    "RB": 0.9417,
    "WR": 0.9382,
    "TE": 0.9105,
}

#: Which column an imputed count is written to, per position — the one
#: that carries the bulk of that position's yardage.  The scorer sums
#: all three, so the choice only matters for legibility.
_IMPUTE_COLUMN: dict[str, str] = {
    "QB": "passing_first_downs",
    "RB": "rushing_first_downs",
    "WR": "receiving_first_downs",
    "TE": "receiving_first_downs",
}

#: Below this the imputation is skipped.  A line projecting a handful of
#: yards produces a fractional first down, and the fit's population was
#: players with 200+ yards — extrapolating it onto a 12-yard projection
#: claims precision the measurement does not have.
MIN_YARDS_TO_IMPUTE: float = 1.0


def _num(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    return out if out == out else 0.0  # NaN check


def imputed_first_down_column(position: str | None) -> str | None:
    """Where an imputed count would land, or ``None`` if unmeasured."""
    return _IMPUTE_COLUMN.get(str(position or "").strip().upper())


def supplies_first_downs(stat_line: Mapping[str, Any] | None) -> bool:
    """Does this line already carry first downs?

    A present-but-zero column counts as supplied.  A source that emits
    the column explicitly is telling us the player had none, and
    overwriting that with an estimate would discard real information.
    """
    if not stat_line:
        return False
    return any(column in stat_line for column in FIRST_DOWN_COLUMNS)


def with_imputed_first_downs(
    stat_line: Mapping[str, Any] | None,
    position: str | None,
) -> tuple[dict[str, Any], bool]:
    """``(line, imputed)`` — the line to score, and whether we added to it.

    Returns a copy always; the caller's line is never mutated.  The bool
    is not decoration: a value that silently might or might not include
    an estimate is exactly the ambiguity this module exists to remove.
    """
    line = dict(stat_line or {})
    if not line or supplies_first_downs(line):
        return line, False

    pos = str(position or "").strip().upper()
    rate = FIRST_DOWNS_PER_YARD.get(pos)
    column = _IMPUTE_COLUMN.get(pos)
    if rate is None or column is None:
        return line, False

    yards = sum(_num(line.get(col)) for col in YARD_COLUMNS)
    if yards < MIN_YARDS_TO_IMPUTE:
        return line, False

    line[column] = yards * rate
    return line, True


def fit_first_downs_per_yard(
    weekly_rows: Iterable[Mapping[str, Any]],
    *,
    min_yards: float = 200.0,
    regular_season_only: bool = True,
) -> dict[str, Any]:
    """Refit the constants from nflverse weekly rows.

    Fits ``first_downs = k * yards`` **through the origin** per position
    — see the module docstring for why an intercept is the wrong shape
    here — and reports R^2 alongside so a drifting fit is visible rather
    than silently shipped.
    """
    totals: dict[str, dict[str, float]] = {}
    position_of: dict[str, str] = {}
    for row in weekly_rows or []:
        if regular_season_only and str(row.get("season_type") or "REG").upper() != "REG":
            continue
        player_id = str(row.get("player_id") or "").strip()
        pos = str(row.get("position") or "").strip().upper()
        if not player_id or pos not in FIRST_DOWNS_PER_YARD:
            continue
        season = row.get("season") or 0
        key = f"{player_id}:{season}"
        position_of[key] = pos
        bucket = totals.setdefault(key, {"fd": 0.0, "yds": 0.0})
        bucket["fd"] += sum(_num(row.get(col)) for col in FIRST_DOWN_COLUMNS)
        bucket["yds"] += sum(_num(row.get(col)) for col in YARD_COLUMNS)

    by_position: dict[str, list[tuple[float, float]]] = {}
    for key, bucket in totals.items():
        if bucket["yds"] < min_yards:
            continue
        by_position.setdefault(position_of[key], []).append((bucket["yds"], bucket["fd"]))

    out: dict[str, Any] = {"rates": {}, "r2": {}, "n": {}}
    for pos, pairs in sorted(by_position.items()):
        if len(pairs) < 20:
            continue
        sxx = sum(y * y for y, _ in pairs)
        if sxx <= 0:
            continue
        rate = sum(y * f for y, f in pairs) / sxx
        mean_fd = statistics.fmean([f for _, f in pairs])
        ss_res = sum((f - rate * y) ** 2 for y, f in pairs)
        ss_tot = sum((f - mean_fd) ** 2 for _, f in pairs)
        out["rates"][pos] = round(rate, 5)
        out["r2"][pos] = round(1 - ss_res / ss_tot, 4) if ss_tot > 0 else 0.0
        out["n"][pos] = len(pairs)
    return out


# ── Sleeper-keyed projection lines (Game Day weekly baseline) ───────────

#: Sleeper stat keys carrying the yardage the fit is defined over, in the
#: same order as :data:`YARD_COLUMNS`.
SLEEPER_YARD_KEYS: tuple[str, ...] = ("pass_yd", "rush_yd", "rec_yd")

#: Sleeper's per-play-type first-down keys.  On the WEEKLY PROJECTION rows
#: (RotoWire via Sleeper) these are NOT first-down counts: measured on the
#: full 2026 week-3 capture, 677 of 677 rows carrying one equal the matching
#: yardage / 10 exactly (Lamar Jackson: pass_yd 273.55, pass_fd 27.35 — about
#: twice the single-game NFL record).  They are never read as first downs
#: here, and a league card that pays them makes a projected line unscorable
#: rather than silently priced on a yardage proxy.
SLEEPER_PROJECTED_FD_KEYS: tuple[str, ...] = ("pass_fd", "rush_fd", "rec_fd")


def imputed_sleeper_first_down_bonus(
    stat_line: Mapping[str, Any] | None,
    position: str | None,
    scoring_settings: Mapping[str, Any] | None,
) -> tuple[str, float, float] | None:
    """``(bonus key, imputed first downs, points)`` for a Sleeper-keyed line.

    The league-paid ``bonus_fd_<pos>`` is a count of ALL the player's first
    downs, which no projection publishes.  This reuses the canonical fit
    (:func:`with_imputed_first_downs` — same rates, same minimum, same
    refusal of unmeasured positions) over the line's Sleeper yardage and
    prices the count at the card's own rate.  ``None`` when the card does
    not pay the bonus, the line already supplies it, the position is
    unmeasured, or the yardage is below the fit's floor.  The result is OUR
    estimate and callers must label it as such.
    """
    pos = str(position or "").strip().upper()
    key = f"bonus_fd_{pos.lower()}"
    try:
        rate = float((scoring_settings or {}).get(key) or 0.0)
    except (TypeError, ValueError):
        return None
    if rate == 0.0:
        return None
    line = stat_line or {}
    if key in line:
        return None
    nflverse_line = {
        column: _num(line.get(sleeper_key))
        for column, sleeper_key in zip(YARD_COLUMNS, SLEEPER_YARD_KEYS)
    }
    imputed_line, imputed = with_imputed_first_downs(nflverse_line, pos)
    if not imputed:
        return None
    column = imputed_first_down_column(pos)
    count = _num(imputed_line.get(column)) if column else 0.0
    return key, count, count * rate
