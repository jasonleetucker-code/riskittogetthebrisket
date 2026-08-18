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

from src.league_intel.scorer import score_stat_line as _score_stat_line
from src.scoring.sleeper_ingest import KEY_ALIASES as _SLEEPER_KEY_ALIASES
from src.utils.name_clean import POSITION_ALIASES as _POSITION_ALIASES


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
    # ADDED 2026-08-13 (B7 / W18-F003).  KICKER.  The engine read no
    # kicker key at all, so every kicker scored a well-formed 0.000 with
    # no reason and no flag -- and dynasty_main starts K:1.  Nothing here
    # needs play-by-play: the weekly feed carries the made/missed bands,
    # total made-FG distance, and PATs outright.
    "xpm": (("pat_made",), "XP Made"),
    "xpmiss": (("pat_missed",), "XP Miss"),
    "fgm_yds": (("fg_made_distance",), "FG Yds"),
    "fgmiss": (("fg_missed",), "FG Miss"),
    "fgm": (("fg_made",), "FG Made"),
}

#: Distance-banded kicker rules → the feed's own bands.  Separate from
#: ``_SIMPLE_KEYS`` because a Sleeper band can span more than one nflverse
#: band: ``fgm_50p`` means 50+, which the feed splits into ``fg_made_50_59``
#: and ``fg_made_60_``.  Candidate columns pick the FIRST present, so a
#: sum needs its own structure — getting this wrong would silently drop
#: every 60-yard kick from a league that pays for 50+.
_FG_BAND_KEYS: dict[str, tuple[tuple[str, ...], str]] = {
    "fgm_0_19": (("fg_made_0_19",), "FG 0-19"),
    "fgm_20_29": (("fg_made_20_29",), "FG 20-29"),
    "fgm_30_39": (("fg_made_30_39",), "FG 30-39"),
    "fgm_40_49": (("fg_made_40_49",), "FG 40-49"),
    "fgm_50_59": (("fg_made_50_59",), "FG 50-59"),
    "fgm_60p": (("fg_made_60_",), "FG 60+"),
    "fgm_50p": (("fg_made_50_59", "fg_made_60_"), "FG 50+"),
    "fgmiss_0_19": (("fg_missed_0_19",), "FG Miss 0-19"),
    "fgmiss_20_29": (("fg_missed_20_29",), "FG Miss 20-29"),
    "fgmiss_30_39": (("fg_missed_30_39",), "FG Miss 30-39"),
    "fgmiss_40_49": (("fg_missed_40_49",), "FG Miss 40-49"),
    "fgmiss_50_59": (("fg_missed_50_59",), "FG Miss 50-59"),
    "fgmiss_60p": (("fg_missed_60_",), "FG Miss 60+"),
    "fgmiss_50p": (("fg_missed_50_59", "fg_missed_60_"), "FG Miss 50+"),
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

#: IDP rules whose stat is a SUM ACROSS SEVERAL COLUMNS.  Separate from
#: ``_IDP_KEYS`` because that table resolves through ``_first_num``
#: (first candidate present wins), which is the right shape for absorbing
#: a rename and the wrong shape for a total: it would score the first
#: block type and silently drop the rest.  Same distinction, and the same
#: reason, as ``_FG_BAND_KEYS`` versus ``_SIMPLE_KEYS``.
#
# ADDED 2026-08-18 (#802).  ``idp_blk_kick`` was declared UNSCORABLE —
# "blocked kicks are not a column on the weekly defensive feed" — while
# all three columns below were populated on the very feed this engine
# already reads.  A rule we can score and do not is a GAP; recording it
# as permanently impossible suppressed it from ``describe_gaps`` and the
# provenance surface, so the defect could not be seen either.
#
# Measured on 2025 REG at the live 5.32/event: 44 player-weeks, 234.08
# points, split punt 9 / PAT 12 / FG 23 — the field-goal blocks alone are
# more than half, which is what a first-present lookup would have lost.
# Earned by DE, DT, SAF, LB and NT: the IDP assets this board ranks.
#
# IDP-SCOPED ON PURPOSE.  Three of 2025's 44 blocks were made by an RB, a
# TE and an OT.  ``idp_blk_kick`` is Sleeper's IDP rule and those players
# are not scored by it; the team ``blk_kick`` rule is a different family
# for an asset class this board does not value.  Not an oversight — the
# alternative pays a blocked kick under a rule the league does not apply
# to that player.
_IDP_SUM_KEYS: dict[str, tuple[tuple[str, ...], str]] = {
    "idp_blk_kick": (("def_punt_blocks", "def_pat_blocks", "def_fg_blocks"), "Blk Kick"),
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


# Position labels that count as IDP scoring eligible.  nflverse uses both
# the abstract group (DL/LB/DB) and the specific listing
# (DT/DE/EDGE/ILB/OLB/CB/S/SAF/FS/SS/NT) — accept both.
#
# DERIVED, not restated (2026-08-18).  This was a hand-maintained literal,
# and it drifted from ``POSITION_ALIASES`` — the map CLAUDE.md names the
# single source of truth for position families — in the way a mirror
# always eventually does: the list was missing ``SAF``, the spelling the
# 2025 unified release uses for a safety on 1,423 player-weeks.  Every
# safety therefore skipped the whole IDP block below and scored a
# well-formed 0.000, worth 10,842.88 points across 2025 REG on the live
# card.  The same omission had already been found and patched *locally*
# by two other consumers, which is precisely why it survived here.
#
# Deriving means the next spelling the owner learns is scored
# automatically instead of waiting to be noticed as a position group
# scoring suspiciously low.  Pinned by
# ``tests/nfl_data/test_idp_position_coverage.py``.
_IDP_FAMILIES = frozenset({"DL", "LB", "DB"})
_IDP_POSITIONS = frozenset(
    raw for raw, family in _POSITION_ALIASES.items() if family in _IDP_FAMILIES
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


#: Per-game tackle-volume thresholds, on COMBINED tackles.
_IDP_TACKLE_THRESHOLDS: tuple[tuple[str, int, str], ...] = (
    ("idp_tkl_5p", 5, "5+ Tkl"),
    ("idp_tkl_10p", 10, "10+ Tkl"),
)

#: Yardage thresholds.  Sleeper publishes these as COUNTS on its own
#: stat line (``rush_40p: 1.0``), which is why the normalizer emits 1.0
#: rather than the qualifying yardage.
_YARDAGE_THRESHOLDS: tuple[tuple[str, str, int, str], ...] = (
    ("bonus_pass_yd_300", "passing_yards", 300, "300+ Pass"),
    ("bonus_pass_yd_400", "passing_yards", 400, "400+ Pass"),
    ("bonus_rush_yd_100", "rushing_yards", 100, "100+ Rush"),
    ("bonus_rush_yd_200", "rushing_yards", 200, "200+ Rush"),
    ("bonus_rec_yd_100", "receiving_yards", 100, "100+ Rec"),
    ("bonus_rec_yd_200", "receiving_yards", 200, "200+ Rec"),
)

#: Two-point conversions.
_TWO_PT_KEYS: tuple[tuple[str, str, str], ...] = (
    ("pass_2pt", "passing_2pt_conversions", "Pass 2pt"),
    ("rush_2pt", "rushing_2pt_conversions", "Rush 2pt"),
    ("rec_2pt", "receiving_2pt_conversions", "Rec 2pt"),
)

#: Sleeper scoring key → the label the breakdown shows.  Assembled from
#: the mapping tables plus the derived rules that have no table.
_SLEEPER_KEY_LABELS: dict[str, str] = {
    **{k: label for k, (_cols, label) in _SIMPLE_KEYS.items()},
    **{k: label for k, (_cols, label) in _FG_BAND_KEYS.items()},
    **{k: label for k, (_cols, label) in _IDP_KEYS.items()},
    **{k: label for k, (_cols, label) in _IDP_SUM_KEYS.items()},
    **dict(_IDP_TACKLE_KEYS),
    **{k: label for (k, _t, label) in _IDP_TACKLE_THRESHOLDS},
    **{k: label for (k, _c, _t, label) in _YARDAGE_THRESHOLDS},
    **{k: label for (k, _c, label) in _TWO_PT_KEYS},
    "pass_inc": "Incompletions",
    "bonus_rec_te": "TE Rec Bonus",
    **{k: "First Downs" for k in _FIRST_DOWN_BONUS_KEYS.values()},
}


def sleeper_stat_line_from_row(
    stat_row: dict[str, Any],
    *,
    position: str | None = None,
) -> dict[str, float]:
    """Normalize a provider stat row into a SLEEPER-KEYED stat line.

    This is the source→canonical half of realized scoring, and it is
    deliberately **scoring-independent**: normalization is about DATA,
    scoring is about RULES, and mixing them is what produced W18-F003.
    An allow-list scorer keyed on provider column names skips a rule in
    silence the moment a vendor renames a column, because a missing
    column and a rule that scores nothing are the same thing to it.

    Emitting the host's own vocabulary removes that failure mode
    structurally: after this, a missing key is a missing STAT, and the
    canonical scorer's dot product cannot drop a rule the line carries.
    Sleeper's real stat lines already publish the derived keys this
    emits — ``bonus_fd_qb: 13.0``, ``pass_inc: 6.0``, ``rush_40p: 1.0``
    are all stats on the host's wire format, not scorer inventions.

    Only NONZERO stats are emitted, matching what the host publishes and
    keeping the breakdown to events that happened.
    """
    line: dict[str, float] = {}
    pos = (position or str(stat_row.get("position") or "")).upper()

    def _put(key: str, value: float) -> None:
        if value:
            line[key] = value

    for key, (columns, _label) in _SIMPLE_KEYS.items():
        _put(key, _first_num(stat_row, columns))

    # Banded kicker rules are SUMMED: one Sleeper band can span several
    # of the feed's (``fgm_50p`` covers 50-59 and 60+).
    for key, (columns, _label) in _FG_BAND_KEYS.items():
        _put(key, sum(_num(stat_row.get(col)) for col in columns))

    # Incompletions — derived. nflverse publishes attempts and
    # completions; Sleeper charges the difference.  Clamped so a
    # malformed row can never award points for a penalty rule.
    _put("pass_inc", max(0.0, _num(stat_row.get("attempts")) - _num(stat_row.get("completions"))))

    # Position-scoped rules.  The rate lives on a position-specific KEY,
    # so the position decision belongs here, in normalization.
    if pos == "TE":
        _put("bonus_rec_te", _num(stat_row.get("receptions")))
    fd_key = _FIRST_DOWN_BONUS_KEYS.get(pos)
    if fd_key:
        first_downs = 0.0
        for fd_col in _FIRST_DOWN_COLUMNS:
            gained = _num(stat_row.get(fd_col))
            scoring_plays = _num(stat_row.get(_FIRST_DOWN_TD_COLUMNS[fd_col]))
            first_downs += max(0.0, gained - scoring_plays)
        _put(fd_key, first_downs)

    if _is_idp_position(pos):
        for key, (columns, _label) in _IDP_KEYS.items():
            _put(key, _first_num(stat_row, columns))
        # Summed, not first-present — see ``_IDP_SUM_KEYS``.
        for key, (columns, _label) in _IDP_SUM_KEYS.items():
            _put(key, sum(_num(stat_row.get(col)) for col in columns))
        solo, assists, combined = _tackle_view(stat_row)
        for (key, _label), stat in zip(_IDP_TACKLE_KEYS, (solo, assists, combined)):
            _put(key, stat)
        for key, threshold, _label in _IDP_TACKLE_THRESHOLDS:
            _put(key, 1.0 if combined >= threshold else 0.0)

    for key, column, threshold, _label in _YARDAGE_THRESHOLDS:
        _put(key, 1.0 if _num(stat_row.get(column)) >= threshold else 0.0)

    for key, column, _label in _TWO_PT_KEYS:
        _put(key, _num(stat_row.get(column)))

    return line


#: Precomputed fantasy TOTALS the league host publishes on the same line
#: as the raw stats.  These are never stats and must never be scored: a
#: card that paid ``pts_ppr`` at 1.0 would score the whole line twice.
#: Excluded structurally rather than by trusting that no card names them.
HOST_DERIVED_TOTALS: frozenset[str] = frozenset(
    {"pts_ppr", "pts_std", "pts_half_ppr", "pts_idp", "kick_pts"}
)

#: Row fields that identify the player-week rather than describe it.
_HOST_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "season",
        "week",
        "season_type",
        "position",
        "player_id",
        "player_id_gsis",
        "gsis_id",
        "player_name",
        "player_display_name",
        "team",
        "recent_team",
        "opponent",
        "source",
    }
)

#: Sleeper stat keys that are RANKS or RATES rather than event counts.
#: They share the line with real stats and are meaningless to multiply by
#: a per-event rate.
_HOST_NON_EVENT_PREFIXES: tuple[str, ...] = ("pos_rank_", "tm_")


def is_host_player_entry(entry_id: Any) -> bool:
    """Is this host stat entry an individual PLAYER rather than a team DST?

    Sleeper keys players by numeric id and team defenses by their alpha
    team code (``PHI``, ``KC``).  That distinction is the whole player/DST
    separation, and it cannot be replaced by a key-family rule: measured
    on the host's own wk14 2025 dump, ``st_tkl_solo`` appears on 87 player
    entries AND 28 team entries, and ``kr_yd`` on 45 and 28 — one key
    name, two different meanings.  Scoring a team entry as a player pays
    a DST rule (``pts_allow``, ``int``, ``fum_rec``) to an individual.

    A PLAYER is identified positively, and that direction is deliberate.
    Identifying TEAMS instead was tried and under-caught: the host's dump
    carries **two** team-entry families, bare team codes (``PHI``, ``HOU``)
    and prefixed ones (``TEAM_BUF``, ``TEAM_LAR``), 28 of each in the wk14
    2025 dump.  A "short alphabetic id" rule cleared all 28 prefixed ones,
    because ``TEAM_BUF`` is neither short nor purely alphabetic.  An
    allow-list of what a player looks like cannot fail that way: a new
    team-entry spelling is refused by default, where a deny-list of team
    shapes silently admits it.

    Player ids are numeric (``4034``); rows rebuilt by
    ``league_comparison.sleeper_stats.fetch_sleeper_weekly_stats`` carry a
    GSIS id (``00-0034796``) instead, which is digits and hyphens.  Both
    are accepted; nothing else is.
    """
    text = str(entry_id or "").strip()
    if not text:
        return False
    return text.replace("-", "").isdigit()


def host_stat_line(stat_row: dict[str, Any]) -> dict[str, float]:
    """The host's OWN stat line, ready to score, with nothing translated.

    This is the counterpart to :func:`sleeper_stat_line_from_row` for rows
    that already arrived in Sleeper's vocabulary.  There is deliberately
    no mapping table: the host publishes the same keys the scoring card is
    written in, so translating them into nflverse column names and back —
    which is what the league-comparison fallback does today — can only
    lose the categories nflverse has no column for.

    What it does do is drop the three things on the line that are not
    per-event stats: identifying metadata, precomputed fantasy totals, and
    rank/rate fields.  Then it reconciles Sleeper's own alias spellings so
    a line carrying both ``idp_pass_def`` and ``idp_pd`` pays that rule
    once rather than twice.
    """
    line: dict[str, float] = {}
    for key, raw in (stat_row or {}).items():
        name = str(key)
        if name in _HOST_METADATA_KEYS or name in HOST_DERIVED_TOTALS:
            continue
        if name.startswith(_HOST_NON_EVENT_PREFIXES):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value:
            line[name] = value

    # Stat-side alias reconciliation — a COLLAPSE onto the canonical
    # spelling, not a copy.
    #
    # Copying was tried first and double-counted, caught by the golden
    # host-awarded fixtures: ``compute_weekly_points`` already copies an
    # alias RATE onto the canonical key, so a card written as
    # ``idp_qb_hit`` ends up paying both spellings.  Add the stat under
    # both spellings as well and the rule is paid twice — the tackle-LB
    # archetype came out 29.7956 against the host's own 27.6.
    #
    # Collapsing makes exactly-once structural: after this, the line
    # carries at most ONE key per rule, so no arrangement of card
    # spellings can match a rule twice.  The pop is what makes it a
    # collapse rather than a copy, and it is the whole guard.
    for alias, canonical in _SCORING_KEY_ALIASES.items():
        if alias not in line:
            continue
        value = line.pop(alias)
        line.setdefault(canonical, value)
    return line


def compute_weekly_points(
    stat_row: dict[str, Any] | None,
    scoring_settings: dict[str, Any] | None,
    *,
    position: str | None = None,
    source: str = "nflverse",
) -> RealizedPoints | None:
    """Return realized fantasy points for one player-week.

    Two stages, and the split is the point (B7 / W18-F003):

    1. :func:`sleeper_stat_line_from_row` normalizes the provider row
       into the host's own stat vocabulary;
    2. ``src.league_intel.scorer.score_stat_line`` — the canonical
       scorer, validated against Sleeper's own ``players_points`` over
       1,339 player-weeks at max |Δ| 0.0050 — scores it.

    Before this, the two engines were inverted: the host-validated one
    had a single non-test caller and the allow-list one reached every
    production consumer while having no host-truth test at all.  A dot
    product over ``stat_line ∩ scoring_settings`` cannot silently skip a
    live rule; an allow-list keyed on vendor column names does exactly
    that, which is what W18-F003 measured.

    ``position`` still matters, but only to NORMALIZATION: it selects
    which position-scoped key a stat lands on (``bonus_fd_qb`` vs
    ``bonus_fd_rb``), and whether IDP rules apply at all.

    ``source`` names the vocabulary the row arrived in (#802).
    ``"nflverse"`` (the default, and the champion path) normalizes through
    :func:`sleeper_stat_line_from_row`.  ``"sleeper"`` means the row is
    ALREADY the host's own stat line and is scored as-is via
    :func:`host_stat_line` — no round-trip, and no derivation, because the
    host publishes ``pass_inc``, ``bonus_fd_qb`` and the tackle split
    directly rather than requiring them to be reconstructed.

    A host row that is a TEAM entry returns ``None``: team defense is not
    an asset class this board values, and its line carries rules
    (``pts_allow``, ``int``, ``fum_rec``) that would be nonsense paid to a
    player.  Refusing is the honest answer — a zero would say the player
    played and scored nothing.
    """
    if not stat_row:
        return None
    if source not in ("nflverse", "sleeper"):
        raise ValueError(
            f"unknown stat source {source!r}; expected 'nflverse' or 'sleeper'. "
            "Guessing a vocabulary is how a rule gets silently skipped."
        )
    if source == "sleeper":
        # The host's OWN id is the reliable discriminator; a row rebuilt by
        # the league-comparison producer carries a GSIS id in ``player_id``.
        entry_id = stat_row.get("player_id_sleeper") or stat_row.get("player_id")
        if not is_host_player_entry(entry_id):
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
    # Alias rates are copied onto the canonical key the normalizer emits.
    # Sleeper ships several spellings for one IDP rule and a league card
    # may carry either; the canonical scorer matches on key equality, so
    # the reconciliation has to happen before it runs.
    for alias, canonical in _SCORING_KEY_ALIASES.items():
        if alias in scoring and canonical not in scoring:
            scoring[canonical] = scoring[alias]

    if source == "sleeper":
        stat_line = host_stat_line(stat_row)
    else:
        stat_line = sleeper_stat_line_from_row(stat_row, position=position)
    result = _score_stat_line(stat_line, scoring)

    # Breakdown keeps its human labels; an unlabelled key falls back to
    # its scoring key rather than being dropped, so a rule that moves the
    # total can never be missing from the audit trail.
    breakdown: list[tuple[str, float, float]] = [
        (_SLEEPER_KEY_LABELS.get(c.scoring_key, c.scoring_key), c.raw_stat, c.awarded_points)
        for c in result.components
        if c.awarded_points
    ]

    return RealizedPoints(
        season=season,
        week=week,
        fantasy_points=result.total_points,
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
