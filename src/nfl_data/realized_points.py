"""Compute true per-week fantasy points per player per league.

Input: a ``WeeklyStatRow``-shaped dict (either from
``src.nfl_data.ingest.fetch_weekly_stats`` or a test fixture)
plus a league-specific scoring dict (from Sleeper's
``league.scoring_settings``).

Output: ``{fantasyPoints, breakdown}`` where ``breakdown`` is
a map of stat-category → points contribution so the UI can
show "5.2 pass yds + 4 pass TD + 1.5 rush + −2 INT = 8.7".

Why this module exists separately from ``src.scoring``
------------------------------------------------------
The existing ``src.scoring.feature_engineering`` computes
RANKINGS features (confidence, volatility, market edge).
Realized fantasy points are a different beast — they're the
actual scoreboard number, not a feature derived from rankings.
Keeping them in ``src.nfl_data`` keeps the package boundary
tight: everything in ``src.nfl_data`` requires live NFL stats,
everything else in ``src.scoring`` works off the canonical
contract.

League scoring rules — what we map
----------------------------------
Sleeper's ``scoring_settings`` uses these keys (incomplete —
there are 100+, we map the ~40 that cover >99% of fantasy
production in any league format):

    Offense:
        pass_yd, pass_td, pass_int, pass_2pt, pass_sack
        rush_yd, rush_td, rush_2pt
        rec, rec_yd, rec_td, rec_2pt, bonus_rec_te
        fum_lost
        bonus_pass_yd_300, bonus_pass_yd_400, bonus_rush_yd_100,
        bonus_rush_yd_200, bonus_rec_yd_100, bonus_rec_yd_200

    IDP (added 2026-04-26 for the IDP scoring-fit pass):
        idp_tkl_solo, idp_tkl_ast, idp_tkl, idp_tkl_loss
        idp_sack, idp_sack_yd, idp_hit
        idp_pd, idp_int, idp_int_ret_yd
        idp_ff, idp_fum_rec, idp_fum_ret_yd
        idp_def_td, idp_safe, idp_blk_kick

The IDP scoring path consumes nflverse ``def_*`` columns (see
``nflverse_direct.fetch_weekly_defensive_stats``).  Rows where
``position`` is not in the IDP set skip the IDP keys entirely so
the offense path is unaffected.

Degradation
-----------
* Missing scoring_settings → returns fantasyPoints=0 with
  reason="no_scoring_settings" in the breakdown.
* Missing stat row → returns None (caller handles empty).
* Zero or negative stats → included verbatim (a −1 INT
  contribution is real).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ── Scoring-key mapping ───────────────────────────────────────────
#
# Maps a Sleeper scoring_setting key to a callable that takes the
# stat row and returns the stat value to multiply by the points.
# Split into simple_keys (direct column read) and bonus_keys
# (threshold-based boolean).

_SIMPLE_KEYS: dict[str, tuple[str, str]] = {
    # (stat_row_key, human_label)
    "pass_yd": ("passing_yards", "Pass Yds"),
    "pass_td": ("passing_tds", "Pass TD"),
    "pass_int": ("interceptions", "INT"),
    "pass_sack": ("sacks", "Sacks Taken"),
    "rush_yd": ("rushing_yards", "Rush Yds"),
    "rush_td": ("rushing_tds", "Rush TD"),
    "rec": ("receptions", "Rec"),
    "rec_yd": ("receiving_yards", "Rec Yds"),
    "rec_td": ("receiving_tds", "Rec TD"),
    "fum_lost": ("fumbles_lost", "Fum Lost"),
}


# Defensive scoring keys → nflverse ``def_*`` stat columns.  Only
# applied to rows whose ``position`` is in the IDP set below; for
# offensive players the column either doesn't exist on the row or
# is zero, so the loop is a no-op.  Extends the same shape as
# ``_SIMPLE_KEYS`` so the ``compute_weekly_points`` scoring loop
# can iterate both with one code path.
_IDP_KEYS: dict[str, tuple[str, str]] = {
    "idp_tkl_solo": ("def_tackles_solo", "Solo Tkl"),
    "idp_tkl_ast": ("def_tackle_assists", "Ast Tkl"),
    "idp_tkl": ("def_tackles", "Tkl"),
    "idp_tkl_loss": ("def_tackles_for_loss", "TFL"),
    "idp_sack": ("def_sacks", "Sack"),
    "idp_sack_yd": ("def_sack_yards", "Sack Yds"),
    "idp_hit": ("def_qb_hits", "QB Hit"),
    "idp_pd": ("def_pass_defended", "PD"),
    "idp_int": ("def_interceptions", "INT"),
    "idp_int_ret_yd": ("def_interception_yards", "INT Ret Yds"),
    "idp_ff": ("def_fumbles_forced", "FF"),
    "idp_fum_rec": ("def_fumble_recovery_own", "FR"),
    "idp_fum_ret_yd": ("def_fumble_recovery_yards_own", "FR Ret Yds"),
    "idp_def_td": ("def_tds", "Def TD"),
    "idp_safe": ("def_safety", "Safety"),
}


# Position labels that count as IDP scoring eligible.  nflverse uses
# both the abstract group (DL/LB/DB) and the specific listing
# (DT/DE/EDGE/ILB/OLB/CB/S/FS/SS/NT) — accept both.
_IDP_POSITIONS = frozenset({
    "DL", "DT", "DE", "EDGE", "NT",
    "LB", "ILB", "OLB", "MLB",
    "DB", "CB", "S", "FS", "SS",
})


def _is_idp_position(position: str | None) -> bool:
    if not position:
        return False
    return str(position).upper() in _IDP_POSITIONS


@dataclass(frozen=True)
class RealizedPoints:
    season: int
    week: int
    fantasy_points: float
    # Ordered list of (label, stat, points) tuples — UI-friendly.
    breakdown: list[tuple[str, float, float]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "week": self.week,
            "fantasyPoints": round(self.fantasy_points, 2),
            "breakdown": [
                {"label": lab, "stat": round(float(s), 2), "points": round(float(p), 2)}
                for (lab, s, p) in self.breakdown
            ],
        }


def _num(val: Any) -> float:
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return 0.0


def compute_weekly_points(
    stat_row: dict[str, Any] | None,
    scoring_settings: dict[str, Any] | None,
    *,
    position: str | None = None,
) -> RealizedPoints | None:
    """Return realized fantasy points for one player-week.

    ``position`` lets us apply position-specific bonuses (e.g.
    ``bonus_rec_te`` adds per-reception points to TEs only).
    Missing position → only applies position-agnostic rules.
    """
    if not stat_row:
        return None
    season = int(_num(stat_row.get("season")))
    week = int(_num(stat_row.get("week")))
    if not scoring_settings:
        return RealizedPoints(
            season=season,
            week=week,
            fantasy_points=0.0,
            breakdown=[("no_scoring_settings", 0.0, 0.0)],
        )
    scoring = {str(k): _num(v) for k, v in scoring_settings.items()}
    breakdown: list[tuple[str, float, float]] = []
    total = 0.0

    # Simple keys — direct stat × points.
    for key, (stat_key, label) in _SIMPLE_KEYS.items():
        pts_per = scoring.get(key, 0.0)
        if pts_per == 0.0:
            continue
        stat = _num(stat_row.get(stat_key))
        if stat == 0:
            continue
        contribution = stat * pts_per
        breakdown.append((label, stat, contribution))
        total += contribution

    # Position-specific bonus rec (TE premium).
    pos = (position or str(stat_row.get("position") or "")).upper()
    te_bonus = scoring.get("bonus_rec_te", 0.0)
    if pos == "TE" and te_bonus:
        recs = _num(stat_row.get("receptions"))
        if recs:
            breakdown.append(("TE Rec Bonus", recs, recs * te_bonus))
            total += recs * te_bonus

    # IDP keys — only fire for defensive positions.  Sleeper's
    # stacked-scoring stance: a sack on a solo tackle credits
    # ``idp_sack`` + ``idp_sack_yd`` + ``idp_hit`` + ``idp_tkl_loss``
    # + ``idp_tkl_solo`` simultaneously when each category is set on
    # the league.  Each ``def_*`` column on the nflverse defensive
    # stat row tracks one event-stat independently, so iterating each
    # _IDP_KEYS entry separately produces the correct stacked total
    # without any explicit "stack bonus" logic.
    if _is_idp_position(pos):
        for key, (stat_key, label) in _IDP_KEYS.items():
            pts_per = scoring.get(key, 0.0)
            if pts_per == 0.0:
                continue
            stat = _num(stat_row.get(stat_key))
            if stat == 0:
                continue
            contribution = stat * pts_per
            breakdown.append((label, stat, contribution))
            total += contribution

        # Per-game tackle-volume thresholds (Sleeper exposes these
        # as ``idp_tkl_5p`` and ``idp_tkl_10p`` for ≥5 and ≥10 combined
        # tackles in a single game).  Read off the per-game combined
        # tackle count.
        for key, thresh, label in [
            ("idp_tkl_5p", 5, "5+ Tkl"),
            ("idp_tkl_10p", 10, "10+ Tkl"),
        ]:
            pts_per = scoring.get(key, 0.0)
            if pts_per == 0.0:
                continue
            tkls = _num(stat_row.get("def_tackles"))
            if tkls >= thresh:
                breakdown.append((label, tkls, pts_per))
                total += pts_per

    # Threshold bonuses.
    for key, (stat_key, thresh, label) in [
        ("bonus_pass_yd_300", ("passing_yards", 300, "300+ Pass")),
        ("bonus_pass_yd_400", ("passing_yards", 400, "400+ Pass")),
        ("bonus_rush_yd_100", ("rushing_yards", 100, "100+ Rush")),
        ("bonus_rush_yd_200", ("rushing_yards", 200, "200+ Rush")),
        ("bonus_rec_yd_100", ("receiving_yards", 100, "100+ Rec")),
        ("bonus_rec_yd_200", ("receiving_yards", 200, "200+ Rec")),
    ]:
        pts_per = scoring.get(key, 0.0)
        if pts_per == 0.0:
            continue
        stat = _num(stat_row.get(stat_key))
        if stat >= thresh:
            breakdown.append((label, stat, pts_per))
            total += pts_per

    # 2-point conversions (Sleeper tracks these separately in some
    # dumps; we tolerate absence).
    for key, stat_key, label in [
        ("pass_2pt", "passing_2pt_conversions", "Pass 2pt"),
        ("rush_2pt", "rushing_2pt_conversions", "Rush 2pt"),
        ("rec_2pt", "receiving_2pt_conversions", "Rec 2pt"),
    ]:
        pts_per = scoring.get(key, 0.0)
        if pts_per == 0.0:
            continue
        stat = _num(stat_row.get(stat_key))
        if stat:
            contribution = stat * pts_per
            breakdown.append((label, stat, contribution))
            total += contribution

    return RealizedPoints(
        season=season, week=week, fantasy_points=total, breakdown=breakdown,
    )


def compute_cumulative_points(
    stat_rows: list[dict[str, Any]],
    scoring_settings: dict[str, Any] | None,
    *,
    position: str | None = None,
) -> dict[str, Any]:
    """Aggregate weekly results across a list of stat rows.

    Returns::

        {
            "weeks": [RealizedPoints.to_dict(), ...],
            "totalPoints": float,
            "weekCount": int,
            "averagePoints": float,
            "bestWeek": RealizedPoints.to_dict() | None,
            "worstWeek": RealizedPoints.to_dict() | None,
        }
    """
    weekly: list[RealizedPoints] = []
    for row in stat_rows or []:
        rp = compute_weekly_points(row, scoring_settings, position=position)
        if rp is not None:
            weekly.append(rp)
    if not weekly:
        return {
            "weeks": [],
            "totalPoints": 0.0,
            "weekCount": 0,
            "averagePoints": 0.0,
            "bestWeek": None,
            "worstWeek": None,
        }
    weekly.sort(key=lambda rp: (rp.season, rp.week))
    total = sum(rp.fantasy_points for rp in weekly)
    best = max(weekly, key=lambda rp: rp.fantasy_points)
    worst = min(weekly, key=lambda rp: rp.fantasy_points)
    return {
        "weeks": [rp.to_dict() for rp in weekly],
        "totalPoints": round(total, 2),
        "weekCount": len(weekly),
        "averagePoints": round(total / len(weekly), 2),
        "bestWeek": best.to_dict(),
        "worstWeek": worst.to_dict(),
    }


def value_vs_realized_delta(
    expected_fantasy_points: float | None,
    realized_total: float,
    week_count: int,
) -> dict[str, Any]:
    """Compute a 'value vs. realized' diagnostic.

    We don't have true projections (our app uses rankings, not
    projected points), so the caller passes an ``expected`` — often
    this is a positional-average extrapolation from rank tier.
    Returns None values when expected isn't available.
    """
    if expected_fantasy_points is None or week_count <= 0:
        return {"expected": None, "realized": realized_total, "delta": None, "deltaPct": None}
    avg_realized = realized_total / week_count
    delta = avg_realized - expected_fantasy_points
    pct = (delta / expected_fantasy_points * 100) if expected_fantasy_points else None
    return {
        "expected": round(expected_fantasy_points, 2),
        "realized": round(avg_realized, 2),
        "delta": round(delta, 2),
        "deltaPct": round(pct, 1) if pct is not None else None,
    }
