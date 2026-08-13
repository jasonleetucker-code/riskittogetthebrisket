"""Which of a league's scoring rules does the realized-points engine score?

A Sleeper ``scoring_settings`` dict is just keys and rates. When
:func:`src.nfl_data.realized_points.compute_weekly_points` does not
recognise a key, nothing raises — the rule contributes zero and the
player's realized points come out quietly low. That has now happened
three separate times in this codebase:

* ``idp_pass_def`` scored 0 all season (11,119 points, cornerbacks).
* ``idp_qb_hit`` scored 0 all season (6,545 points, edge rushers).
* Fixing only the first inverted the measured DB-vs-DL scoring tilt,
  because a partial correction to a *relative* quantity is a directional
  bias, not just a smaller error.

There was already a coverage check, in
``league_comparison/service.py`` — but it compared the league's keys
against a **hand-maintained** list of what the engine supposedly
handled, and a hand-maintained mirror of behaviour drifts from it. This
module replaces that list with a measurement.

**Coverage is probed, not parsed.** :func:`engine_reads_key` sets a key
to zero, then to a nonzero rate, against a stat row rich enough for
every threshold in the engine to fire, and reports whether the output
moved. That is the actual question — "does this rule change the score?"
— and it cannot be fooled by *how* the engine is written.

Parsing was tried first and got it wrong twice in the same sitting: a
regex for ``scoring.get("literal")`` missed the yardage bonuses and the
two-point keys, which the engine implements by looping over list
literals. A first probe attempt then produced its own false negative,
because the sample row's yardage sat below the 300/400 thresholds it
was meant to exercise. Hence :data:`_MAXIMAL_ROW` and
:func:`test_the_probe_row_can_fire_every_threshold`.

Every key resolves to exactly one :class:`Coverage` state. ``GAP`` is
the state that must not exist silently — it means a rule the league
pays and the engine ignores, with the data available to do better.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Iterable

from src.nfl_data.realized_points import compute_weekly_points


class Coverage(str, Enum):
    """What the engine does with one scoring key."""

    SCORED = "scored"
    """The engine reads it (directly or via a Sleeper alias)."""

    NOT_APPLICABLE = "not_applicable"
    """A real rule for an asset class this platform does not value —
    team defense, kickers, special teams.  Ignoring it is correct: no
    DST or K is a tradeable asset on this board."""

    UNSCORABLE = "unscorable"
    """A rule for a player we DO value, which the available data cannot
    reconstruct.  Distinct from NOT_APPLICABLE: this one is a real
    understatement of a real player's points, recorded rather than
    hidden."""

    GAP = "gap"
    """A rule we value, could score from data already on the feed, and
    do not.  This state is a defect."""


#: Positions probed. A key that only fires for one position group still
#: counts as scored.
_PROBE_POSITIONS = ("QB", "RB", "WR", "TE", "LB", "CB", "DE")

#: A stat row large enough that EVERY threshold bonus in the engine can
#: fire. Undersized values here silently turn threshold keys into false
#: gaps — that is not hypothetical, it happened while writing this.
_MAXIMAL_ROW: dict[str, Any] = {
    "season": 2025,
    "week": 1,
    "passing_yards": 600,
    "passing_tds": 6,
    # CORRECTED 2026-08-13 (B7 / W18-F003).  These three carried ONLY the
    # pre-2025 spellings, so the probe asked the engine a question no
    # production row asks it.  Three rules mapped to columns the unified
    # release had renamed therefore classified SCORED — behaviourally
    # true of the probe, factually false of every real row — and `gap`
    # came back empty, so no warning reached /api/league-comparison or
    # Provenance.inputs_complete.  The auditor was defeated by exactly
    # the defect it exists to catch.
    #
    # The probe must be written in the vocabulary the FEED ships, not the
    # one the engine happens to read; that is what makes this guard catch
    # the NEXT rename rather than ratify it.  Both spellings are present
    # because the engine legitimately accepts both (candidate columns in
    # `realized_points._SIMPLE_KEYS`) and a backfill over an older season
    # still supplies the retired name.
    "passing_interceptions": 2,
    "interceptions": 2,
    "sacks_suffered": 3,
    "sacks": 3,
    "completions": 45,
    "attempts": 60,
    "passing_first_downs": 30,
    "passing_2pt_conversions": 2,
    "rushing_yards": 300,
    "rushing_tds": 3,
    "carries": 30,
    "rushing_first_downs": 15,
    "rushing_2pt_conversions": 2,
    "receptions": 20,
    "receiving_yards": 300,
    "receiving_tds": 3,
    "receiving_first_downs": 15,
    "receiving_2pt_conversions": 2,
    "fumbles_lost_total": 2,
    "fumbles_lost": 2,
    # PLAYER special teams, added with the st_/kr_yd/pr_yd
    # reclassification.  Without these the probe cannot fire the newly
    # scored rules and they read as false GAPs — the undersized-row
    # hazard this row's own docstring warns about.
    "kickoff_return_yards": 120,
    "punt_return_yards": 60,
    "special_teams_tds": 1,
    # KICKER, added with the fgm/fgmiss/xpm/xpmiss reclassification.
    "pat_made": 6,
    "pat_missed": 2,
    "fg_made": 5,
    "fg_missed": 3,
    "fg_made_distance": 210,
    "fg_made_0_19": 1,
    "fg_made_20_29": 1,
    "fg_made_30_39": 1,
    "fg_made_40_49": 1,
    "fg_made_50_59": 1,
    "fg_made_60_": 1,
    "fg_missed_0_19": 1,
    "fg_missed_20_29": 1,
    "fg_missed_30_39": 1,
    "fg_missed_40_49": 1,
    "fg_missed_50_59": 1,
    "fg_missed_60_": 1,
    "def_tackles_solo": 15,
    "def_tackles_with_assist": 8,
    "def_tackle_assists": 8,
    "def_tackles_for_loss": 4,
    "def_sacks": 4,
    "def_sack_yards": 30,
    "def_qb_hits": 6,
    "def_pass_defended": 5,
    "def_interceptions": 2,
    "def_interception_yards": 60,
    "def_fumbles_forced": 2,
    "def_fumble_recovery_own": 2,
    "def_fumble_recovery_yards_own": 25,
    "def_tds": 2,
    "def_safeties": 1,
}

#: Key prefixes belonging to asset classes this platform does not value.
#: Team defense and kickers are not tradeable assets on this board, so
#: their rules are correctly ignored.
#
# CORRECTED 2026-08-13 (B7 / W18-F003).  ``st_``, ``kr_yd`` and ``pr_yd``
# were in this tuple, which says "an asset class this platform does not
# value".  They are not: they are paid to the RB, WR, TE and LB this
# board ranks, values and starts.  Measured over 1,339 host player-weeks
# on dynasty_main's live card: ``kr_yd`` 69 rows / 150.77 pts,
# ``st_tkl_solo`` 32 / 49.21, ``pr_yd`` 29 / 22.43, ``st_td`` 4 / 24.00 —
# earned by K, LB, RB, TE and WR.
#
# NOT_APPLICABLE was the most silent state available: it suppresses a key
# from ``describe_gaps`` AND from ``Provenance.inputGaps``, so these were
# not scored, not warned about, and not even recorded as unscorable.
#
# The DST spellings keep this classification and are listed separately —
# ``st_`` never matched ``def_st_``, which has its own entry, so the
# player/DST split is a prefix change and nothing more.
# CORRECTED 2026-08-13 (B7 / W18-F003), second part: the KICKER family
# (fgm*, fgmiss*, xpm, xpmiss) also left this tuple.  The engine read no
# kicker key at all, so every kicker scored a well-formed 0.000 with no
# reason and no flag, and NOT_APPLICABLE kept that silent -- while
# config/leagues/registry.json gives dynasty_main "K": 1 as a starting
# slot, so it is a legitimate question a user can ask.  All of it is on
# the weekly feed (fg_made_*/fg_missed_*/fg_made_distance/pat_made/
# pat_missed), so none of it needed play-by-play.
_NOT_APPLICABLE_PREFIXES: tuple[str, ...] = (
    "pts_allow",
    "yds_allow",
    "def_st_",
    "def_3_and_out",
    "def_4_and_stop",
    "def_forced_punts",
    "def_pr_",
    "def_kr_",
    "def_2pt",
    "def_td",
    "def_pass_def",
    # Ownership of this one is not settled by any artifact in the tree —
    # whether a field-goal return is credited to a player or to the team
    # defense. Left NOT_APPLICABLE rather than guessed; revisit with
    # evidence rather than by preference.
    "fg_ret_yd",
    "blk_kick",
)

#: Exact keys in the same category. These are the UNPREFIXED spellings
#: Sleeper uses for TEAM-defense events — ``sack`` / ``int`` / ``ff``
#: are the DST versions of ``idp_sack`` / ``idp_int`` / ``idp_ff``, and
#: conflating the two would double-count every defender.
_NOT_APPLICABLE_KEYS: frozenset[str] = frozenset(
    {
        "sack",
        "sack_yd",
        "int",
        "int_ret_yd",
        "ff",
        "fum",
        "fum_rec",
        "fum_rec_td",
        "fum_ret_yd",
        "safe",
        "tkl",
        "tkl_ast",
        "tkl_solo",
        "tkl_loss",
        "qb_hit",
        "pass_att",
        "bonus_def_fum_td_50p",
        "bonus_def_int_td_50p",
        "bonus_sack_2p",
        "bonus_tkl_10p",
        "blk_kick_ret_yd",
    }
)

#: Rules for players we DO value that the weekly feed cannot
#: reconstruct, each with the reason. Listing them is the point: an
#: understatement nobody can see is the failure mode this module exists
#: for. Every entry needs a data source, not a code change.
UNSCORABLE_REASONS: dict[str, str] = {
    "rec_0_4": "reception distance bands need play-by-play; weekly stats carry only a reception count",
    "rec_5_9": "reception distance bands need play-by-play",
    "rec_10_19": "reception distance bands need play-by-play",
    "rec_20_29": "reception distance bands need play-by-play",
    "rec_30_39": "reception distance bands need play-by-play",
    "rec_40p": "reception distance bands need play-by-play",
    "rush_40p": "long-run bonus needs play-by-play",
    "pass_td_40p": "long-TD bonus needs play-by-play",
    "pass_td_50p": "long-TD bonus needs play-by-play",
    "rec_td_40p": "long-TD bonus needs play-by-play",
    "rec_td_50p": "long-TD bonus needs play-by-play",
    "rush_td_40p": "long-TD bonus needs play-by-play",
    "rush_td_50p": "long-TD bonus needs play-by-play",
    "pass_cmp_40p": "long-completion bonus needs play-by-play",
    "pass_int_td": "pick-six thrown is not a column on the weekly feed",
    "idp_blk_kick": "blocked kicks are not a column on the weekly defensive feed",
    "idp_pass_def_3p": "per-game PD threshold; nflverse PD counts are season-aggregated on some releases",
    # ADDED 2026-08-13 (B7 / W18-F003), with the prefix change above.
    # These three are PLAYER special-teams rules — real points for
    # players this board values — but the weekly feed publishes no
    # special-teams tackle, forced-fumble or fumble-recovery column, so
    # they are genuinely unscorable rather than a gap. Declared, so they
    # reach describe_gaps() and Provenance.inputGaps instead of vanishing.
    #
    # Their siblings kr_yd / pr_yd / st_td ARE on the feed
    # (kickoff_return_yards / punt_return_yards / special_teams_tds) and
    # are now scored, so they must NOT appear here.
    "st_tkl_solo": "special-teams tackles are not a column on the weekly feed",
    "st_ff": "special-teams forced fumbles are not a column on the weekly feed",
    "st_fum_rec": "special-teams fumble recoveries are not a column on the weekly feed",
}


def engine_reads_key(key: str, *, positions: Iterable[str] = _PROBE_POSITIONS) -> bool:
    """Does setting ``key`` to a nonzero rate change the engine's output?

    The behavioural definition of "scored". See the module docstring for
    why this is not done by reading the source.
    """
    for pos in positions:
        row = dict(_MAXIMAL_ROW)
        row["position"] = pos
        off = compute_weekly_points(row, {key: 0.0}, position=pos)
        on = compute_weekly_points(row, {key: 7.0}, position=pos)
        off_pts = off.fantasy_points if off else 0.0
        on_pts = on.fantasy_points if on else 0.0
        if off_pts != on_pts:
            return True
    return False


def classify(key: str) -> Coverage:
    """Resolve one scoring key to its coverage state.

    Order matters: SCORED wins over everything, because a key the engine
    demonstrably reads is scored regardless of which family its name
    suggests.
    """
    if engine_reads_key(key):
        return Coverage.SCORED
    if key in _NOT_APPLICABLE_KEYS or key.startswith(_NOT_APPLICABLE_PREFIXES):
        return Coverage.NOT_APPLICABLE
    if key in UNSCORABLE_REASONS:
        return Coverage.UNSCORABLE
    return Coverage.GAP


def audit_scoring_settings(
    scoring_settings: dict[str, Any],
) -> dict[Coverage, dict[str, float]]:
    """Classify every NONZERO rule in a league's scoring settings.

    Zero-rated keys are skipped: Sleeper ships dozens of them for unused
    categories, and a rule worth nothing cannot cost anything. A key
    that later goes nonzero gets classified then — which is exactly the
    behaviour wanted for a newly linked league.
    """
    out: dict[Coverage, dict[str, float]] = {c: {} for c in Coverage}
    for key, raw in (scoring_settings or {}).items():
        try:
            rate = float(raw or 0)
        except (TypeError, ValueError):
            continue
        if rate == 0.0:
            continue
        out[classify(str(key))][str(key)] = rate
    return out


def scored_keys_for(scoring_settings: dict[str, Any]) -> set[str]:
    """The keys this engine actually scores — the derived replacement
    for a hand-maintained ``handled`` set."""
    return set(audit_scoring_settings(scoring_settings)[Coverage.SCORED])


def describe_gaps(scoring_settings: dict[str, Any]) -> list[str]:
    """Human-readable lines for the warnings/methodology surface."""
    audit = audit_scoring_settings(scoring_settings)
    lines: list[str] = []
    for key, rate in sorted(audit[Coverage.GAP].items(), key=lambda kv: -abs(kv[1])):
        lines.append(f"{key} ({rate:g}/event) is not scored — realized points are understated.")
    for key, rate in sorted(audit[Coverage.UNSCORABLE].items(), key=lambda kv: -abs(kv[1])):
        lines.append(f"{key} ({rate:g}/event) cannot be scored: {UNSCORABLE_REASONS[key]}.")
    return lines
