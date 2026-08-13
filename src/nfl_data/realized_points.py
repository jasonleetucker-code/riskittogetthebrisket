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

    IDP:
        idp_tkl_solo, idp_tkl_ast, idp_tkl, idp_tkl_loss
        idp_sack, idp_sack_yd, idp_hit
        idp_pd, idp_int, idp_int_ret_yd
        idp_ff, idp_fum_rec, idp_fum_ret_yd
        idp_def_td, idp_safe, idp_blk_kick

The IDP scoring path consumes nflverse ``def_*`` columns.  Rows
where ``position`` is not in the IDP set skip the IDP keys entirely
so the offense path is unaffected.

Two caveats on those columns, both corrected 2026-07-27 and explained
in full above ``_IDP_KEYS``: the 2025 unified release renamed
``def_safety`` and removed ``def_tackles`` outright, and no nflverse
column has ever carried combined tackles.  Every ``def_*`` read here
goes through a candidate list, and tackles through ``_tackle_view``.

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

from src.scoring.sleeper_ingest import KEY_ALIASES as _SLEEPER_KEY_ALIASES


# ── Scoring-key mapping ───────────────────────────────────────────
#
# Maps a Sleeper scoring_setting key to a callable that takes the
# stat row and returns the stat value to multiply by the points.
# Split into simple_keys (direct column read) and bonus_keys
# (threshold-based boolean).

# CORRECTED 2026-08-13 (B7 / W18-F003).  Three of these read columns the
# 2025 unified nflverse release renamed, and failed exactly the way the
# IDP block below failed before its own 2026-07-27 correction:
# ``stat_row.get`` returns None, ``_num`` turns it into 0.0, and the rule
# is skipped as though the player had recorded nothing.  The offense half
# was simply missed by that repair.
#
# These three are PENALTIES, so the silent skip inflates rather than
# understates — the same football scored 18.00 points higher spelled the
# modern way on dynasty_main's card (pass_int -4, pass_sack -1,
# fum_lost -4), with the INT / Sacks Taken / Fum Lost lines absent from
# the breakdown entirely.  Measured across 636 host player-weeks: 208
# points never charged, and 81% of the QB signed error.
#
# Now a CANDIDATE TUPLE, the shape ``_IDP_KEYS`` already uses and the
# shape the comment above that block already claimed both shared.  Live
# name first so a modern row wins; the retired name is kept second so a
# backfill over an older season still scores.  This also removes the
# reason ``src/bdvm/baseline.py::_RAW_ALIASES`` and
# ``src/nfl_data/actuals_store.py`` each carry a private copy of the same
# rename — the engine now absorbs it for every caller.
_SIMPLE_KEYS: dict[str, tuple[tuple[str, ...], str]] = {
    # (candidate stat_row keys, human_label)
    "pass_yd": (("passing_yards",), "Pass Yds"),
    "pass_td": (("passing_tds",), "Pass TD"),
    "pass_int": (("passing_interceptions", "interceptions"), "INT"),
    "pass_sack": (("sacks_suffered", "sacks"), "Sacks Taken"),
    "rush_yd": (("rushing_yards",), "Rush Yds"),
    "rush_td": (("rushing_tds",), "Rush TD"),
    "rec": (("receptions",), "Rec"),
    "rec_yd": (("receiving_yards",), "Rec Yds"),
    "rec_td": (("receiving_tds",), "Rec TD"),
    "fum_lost": (("fumbles_lost_total", "fumbles_lost"), "Fum Lost"),
    # ADDED 2026-07-28.  Per-play scoring the engine never read, found
    # by src/nfl_data/scoring_coverage.py.  Both columns are on the
    # unified feed and both rules are live in dynasty_main: pass_cmp at
    # 0.15/completion (1,762 unscored points across 2025) and rush_att
    # at 0.08/carry (1,225).  ``pass_inc`` is the third of this family
    # and is derived rather than read — see below.
    "pass_cmp": (("completions",), "Completions"),
    "rush_att": (("carries",), "Rush Att"),
    # ADDED 2026-08-13 (B7 / W18-F003).  PLAYER special teams, landing
    # with the ``st_``/``kr_yd``/``pr_yd`` reclassification in
    # scoring_coverage.  These were treated as belonging to an asset
    # class this platform does not value; they are paid to the RB, WR, TE
    # and LB it ranks and starts.  Measured over 1,339 host player-weeks
    # on dynasty_main's card: kr_yd 69 rows / 150.77 pts, pr_yd 29 /
    # 22.43, st_td 4 / 24.00.
    #
    # DST's ``def_kr_yd`` / ``def_pr_yd`` / ``def_st_td`` are a different
    # rule family for an asset class this board genuinely does not value,
    # and stay unscored.
    "kr_yd": (("kickoff_return_yards",), "KR Yds"),
    "pr_yd": (("punt_return_yards",), "PR Yds"),
    "st_td": (("special_teams_tds",), "ST TD"),
}


# Position-scoped first-down bonuses.  Sleeper exposes TWO first-down
# families and a dump can carry both: ``pass_fd`` / ``rush_fd`` /
# ``rec_fd`` are scoped by PLAY TYPE, while ``bonus_fd_qb`` / ``_rb`` /
# ``_te`` / ``_wr`` are scoped by the receiving player's POSITION.  In
# dynasty_main the play-type keys are all 0.0 and the position-scoped
# ones carry the rates, which is what establishes they are distinct
# rules rather than aliases of each other.
#
# A position-scoped bonus pays the player for every first down they
# gain, by any means — a QB scrambling for a first down and an RB
# catching one both count — so all three first-down columns are summed
# and the rate is chosen by the player's position.
#
# Worth 13,323 unscored points across 2025, and asymmetric by position
# (QB 4,134 / RB 3,840 / WR 3,823 / TE 1,526).  That asymmetry is why
# this mattered beyond a magnitude error: a per-position understatement
# tilts any RELATIVE comparison between positions, the same way the
# ``idp_pass_def`` alias gap inverted the measured DB-vs-DL tilt.
_FIRST_DOWN_BONUS_KEYS: dict[str, str] = {
    "QB": "bonus_fd_qb",
    "RB": "bonus_fd_rb",
    "WR": "bonus_fd_wr",
    "TE": "bonus_fd_te",
}

#: Columns summed to get a player's total first downs.  Mirrored by
#: ``first_down_rate.FIRST_DOWN_COLUMNS``, which uses it as a PRESENCE
#: check ("does this line supply first downs at all"), so it stays flat.
_FIRST_DOWN_COLUMNS: tuple[str, ...] = (
    "passing_first_downs",
    "rushing_first_downs",
    "receiving_first_downs",
)

# ADDED 2026-08-13 (B7 / W18-F003).  The two feeds do not mean the same
# thing by "first down".  **Sleeper EXCLUDES scoring plays** from
# ``pass_fd`` / ``rush_fd`` / ``rec_fd``; nflverse's ``*_first_downs``
# INCLUDE them.  Summing the nflverse columns therefore over-counts by
# exactly the player's touchdown count in that play type.
#
# Host-verified on the golden fixtures, 3/3 exact: Josh Allen 2025 wk14
# carries ``bonus_fd_qb = 13`` with ``pass_fd 10 + rush_fd 3`` and 4
# touchdowns, where the raw columns sum to 17.  CMC +2 on 2 TDs; Diggs
# +0 on 0 TDs.
#
# This one is an OVER-charge, opposite in sign to the renamed-column and
# reception-band defects.  That is why it cannot be deferred: on the
# measured sample RB net error is ~0% only because these cancel, so
# repairing the understatements alone would invert RB direction.  The
# same argument the module header at ``scoring_coverage.py`` makes about
# partial corrections to relative quantities.
_FIRST_DOWN_TD_COLUMNS: dict[str, str] = {
    "passing_first_downs": "passing_tds",
    "rushing_first_downs": "rushing_tds",
    "receiving_first_downs": "receiving_tds",
}


# Defensive scoring keys → nflverse ``def_*`` stat columns.  Only
# applied to rows whose ``position`` is in the IDP set below; for
# offensive players the column either doesn't exist on the row or
# is zero, so the loop is a no-op.  Extends the same shape as
# ``_SIMPLE_KEYS`` so the ``compute_weekly_points`` scoring loop
# can iterate both with one code path.
# CORRECTED 2026-07-27.  Three of these mappings read columns that the
# 2025 unified nflverse release does not have, and a fourth carried the
# wrong quantity.  Each failed silently — ``stat_row.get`` returns None,
# ``_num`` turns it into 0.0, and the key is skipped as though the
# player had recorded nothing.  An IDP league scored zero tackles all
# season and nothing said so.
#
#   def_safety   → def_safeties      (renamed; see #589's URL change)
#   def_tackles  → REMOVED           (no replacement column at all)
#
# And the semantics, measured against the retired 2024 defensive release
# rather than assumed:
#
#   * ``def_tackles_solo`` counts UNASSISTED tackles only — it excludes
#     ``def_tackles_with_assist``.  342 of 9,994 rows have solo 0 with
#     with_assist > 0, which is impossible if one contained the other.
#     So ``idp_tkl_solo`` off the raw column under-reported every
#     defender who was assisted on a stop.
#   * ``def_tackles`` was ``solo + with_assist`` — an exact identity on
#     9,994 of 9,994 rows.  That is the gamebook SOLO total, NOT
#     combined tackles, so ``idp_tkl`` was scoring the wrong quantity
#     even when the column existed.
#
# Cross-checked against a real box score: Zack Baun (PHI) 2024 wk1 reads
# solo 9 / with_assist 2 / assists 4 — gamebook 11 solo, 4 assists, 15
# combined, which is his actual line.
#
# Values are now tuples of CANDIDATE columns (first present wins) so a
# backfill over pre-2025 seasons and a live pull over the current one go
# through one table.  The three tackle keys are resolved by
# :func:`_tackle_view` instead, because no single column carries them.
_IDP_KEYS: dict[str, tuple[tuple[str, ...], str]] = {
    "idp_tkl_loss": (("def_tackles_for_loss",), "TFL"),
    "idp_sack": (("def_sacks",), "Sack"),
    "idp_sack_yd": (("def_sack_yards",), "Sack Yds"),
    "idp_hit": (("def_qb_hits",), "QB Hit"),
    "idp_pd": (("def_pass_defended", "def_passes_defended"), "PD"),
    "idp_int": (("def_interceptions",), "INT"),
    "idp_int_ret_yd": (("def_interception_yards",), "INT Ret Yds"),
    "idp_ff": (("def_fumbles_forced",), "FF"),
    # Not def_-prefixed in the unified release.
    "idp_fum_rec": (("def_fumble_recovery_own", "fumble_recovery_own"), "FR"),
    "idp_fum_ret_yd": (
        ("def_fumble_recovery_yards_own", "fumble_recovery_yards_own"),
        "FR Ret Yds",
    ),
    "idp_def_td": (("def_tds",), "Def TD"),
    "idp_safe": (("def_safeties", "def_safety"), "Safety"),
}

# Resolved by ``_tackle_view`` rather than a column read.  Ordered
# solo, assist, combined — matching the tuple that function returns.
_IDP_TACKLE_KEYS: tuple[tuple[str, str], ...] = (
    ("idp_tkl_solo", "Solo Tkl"),
    ("idp_tkl_ast", "Ast Tkl"),
    ("idp_tkl", "Tkl"),
)

# Sleeper publishes some rules under more than one SCORING key name and
# league dumps use either.  ``src/scoring/sleeper_ingest.KEY_ALIASES``
# already normalizes these for the translation layer, but realized
# points only read the canonical spelling — a league whose dump says
# ``idp_pass_def`` (the live dynasty_main league does, at 5.32/event)
# silently scored passes-defended as 0.  Applied only when the
# canonical key is absent so a dump carrying both can never
# double-count.  (Distinct from the STAT-column candidates above:
# those absorb nflverse renames, this absorbs Sleeper's.)
#
# DERIVED, not hand-listed.  This started as a one-entry literal
# ``{"idp_pass_def": "idp_pd"}`` fixing the key that was noticed.
# ``KEY_ALIASES`` knows **eight**, and a second one is live in this very
# league — ``idp_qb_hit`` at 2.13/event, which the module reads as
# ``idp_hit``.  Measured on 2025: passes-defended cost 11,119 points and
# QB hits 6,545.
#
# Half-fixing was not half-right, it was differently wrong: PD is a
# cornerback stat and QB hits are an edge-rusher stat, so correcting
# only PD tilts DB up against DL by 11k points with no offsetting
# credit to the linemen who were owed 6.5k.  A partial correction to a
# *relative* ranking introduces a bias that no correction at all does
# not.
#
# Deriving from the one map that already enumerates them means the next
# alias Sleeper adds is picked up by both layers at once, instead of
# drifting until someone notices a position group scoring low.
_SCORING_KEY_ALIASES: dict[str, str] = {
    alias: canonical for alias, canonical in _SLEEPER_KEY_ALIASES.items() if alias != canonical
}


# Position labels that count as IDP scoring eligible.  nflverse uses
# both the abstract group (DL/LB/DB) and the specific listing
# (DT/DE/EDGE/ILB/OLB/CB/S/FS/SS/NT) — accept both.
_IDP_POSITIONS = frozenset(
    {
        "DL",
        "DT",
        "DE",
        "EDGE",
        "NT",
        "LB",
        "ILB",
        "OLB",
        "MLB",
        "DB",
        "CB",
        "S",
        "FS",
        "SS",
    }
)


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


def _first_num(stat_row: dict[str, Any], columns: tuple[str, ...]) -> float:
    """First candidate column present with a value; 0.0 if none are.

    The candidate list is what absorbs nflverse's 2025 renames without
    breaking a backfill over older seasons — see the note above
    ``_IDP_KEYS``.
    """
    for col in columns:
        val = stat_row.get(col)
        if val is not None and val != "":
            return _num(val)
    return 0.0


def _tackle_view(stat_row: dict[str, Any]) -> tuple[float, float, float]:
    """``(gamebook solo, assists, combined)`` from any nflverse schema.

    Pre-2025 rows publish ``def_tackles``, which IS the gamebook solo
    total.  The unified 2025+ release dropped it, so solo is rebuilt as
    ``def_tackles_solo + def_tackles_with_assist``.  Combined is always
    solo plus ``def_tackle_assists`` — no column carries it.

    Mirrors ``src.nfl_data.actuals_store._tackle_view``; the two are
    pinned to each other by
    ``tests/nfl_data/test_realized_points.py::test_tackle_view_matches_the_actuals_store``.
    """
    published = stat_row.get("def_tackles")
    if published is not None and published != "":
        solo = _num(published)
    else:
        solo = _num(stat_row.get("def_tackles_solo")) + _num(
            stat_row.get("def_tackles_with_assist")
        )
    assists = _num(stat_row.get("def_tackle_assists"))
    return solo, assists, solo + assists


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
    for alias, canonical in _SCORING_KEY_ALIASES.items():
        if alias in scoring and canonical not in scoring:
            scoring[canonical] = scoring[alias]
    breakdown: list[tuple[str, float, float]] = []
    total = 0.0

    # Simple keys — direct stat × points.  Candidate columns, so a
    # vendor rename cannot silently drop a live rule (see _SIMPLE_KEYS).
    for key, (stat_columns, label) in _SIMPLE_KEYS.items():
        pts_per = scoring.get(key, 0.0)
        if pts_per == 0.0:
            continue
        stat = _first_num(stat_row, stat_columns)
        if stat == 0:
            continue
        contribution = stat * pts_per
        breakdown.append((label, stat, contribution))
        total += contribution

    # Incompletions — derived, not a column.  nflverse publishes
    # attempts and completions; Sleeper charges the difference.  Guarded
    # against a negative result so a malformed row can never award
    # points for a penalty rule (dynasty_main pays -0.22/incompletion).
    inc_rate = scoring.get("pass_inc", 0.0)
    if inc_rate != 0.0:
        incompletions = _num(stat_row.get("attempts")) - _num(stat_row.get("completions"))
        if incompletions > 0:
            contribution = incompletions * inc_rate
            breakdown.append(("Incompletions", incompletions, contribution))
            total += contribution

    # Position-specific bonus rec (TE premium).
    pos = (position or str(stat_row.get("position") or "")).upper()
    te_bonus = scoring.get("bonus_rec_te", 0.0)
    if pos == "TE" and te_bonus:
        recs = _num(stat_row.get("receptions"))
        if recs:
            breakdown.append(("TE Rec Bonus", recs, recs * te_bonus))
            total += recs * te_bonus

    # Position-scoped first-down bonus.  See _FIRST_DOWN_BONUS_KEYS for
    # why all three columns are summed and why this is keyed on position
    # rather than play type.
    fd_key = _FIRST_DOWN_BONUS_KEYS.get(pos)
    if fd_key:
        fd_rate = scoring.get(fd_key, 0.0)
        if fd_rate != 0.0:
            # Per play type, and clamped at zero on each pair: a
            # malformed row must never turn a bonus into a penalty.
            first_downs = 0.0
            for fd_col in _FIRST_DOWN_COLUMNS:
                gained = _num(stat_row.get(fd_col))
                scoring_plays = _num(stat_row.get(_FIRST_DOWN_TD_COLUMNS[fd_col]))
                first_downs += max(0.0, gained - scoring_plays)
            if first_downs:
                contribution = first_downs * fd_rate
                breakdown.append(("First Downs", first_downs, contribution))
                total += contribution

    # IDP keys — only fire for defensive positions.  Sleeper's
    # stacked-scoring stance: a sack on a solo tackle credits
    # ``idp_sack`` + ``idp_sack_yd`` + ``idp_hit`` + ``idp_tkl_loss``
    # + ``idp_tkl_solo`` simultaneously when each category is set on
    # the league.  Each ``def_*`` column on the nflverse defensive
    # stat row tracks one event-stat independently, so iterating each
    # _IDP_KEYS entry separately produces the correct stacked total
    # without any explicit "stack bonus" logic.
    if _is_idp_position(pos):
        for key, (stat_keys, label) in _IDP_KEYS.items():
            pts_per = scoring.get(key, 0.0)
            if pts_per == 0.0:
                continue
            stat = _first_num(stat_row, stat_keys)
            if stat == 0:
                continue
            contribution = stat * pts_per
            breakdown.append((label, stat, contribution))
            total += contribution

        # Tackles come from _tackle_view, not a column read — nflverse
        # publishes no combined-tackle column, and its ``solo`` column
        # is unassisted-only.  See the note above _IDP_KEYS.
        tackle_stats = _tackle_view(stat_row)
        for (key, label), stat in zip(_IDP_TACKLE_KEYS, tackle_stats):
            pts_per = scoring.get(key, 0.0)
            if pts_per == 0.0 or stat == 0:
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
            # Sleeper's 5+/10+ thresholds are on COMBINED tackles, which
            # is the third element of the view.  This previously read
            # ``def_tackles`` — the gamebook solo count pre-2025, and
            # absent entirely after, so the bonus stopped firing.
            tkls = tackle_stats[2]
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
        season=season,
        week=week,
        fantasy_points=total,
        breakdown=breakdown,
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
