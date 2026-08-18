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

from src.nfl_data.realized_points import (
    PBP_SUPPLEMENT_KEYS,
    PBP_SUPPLEMENT_ROW_KEY,
    compute_weekly_points,
)


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
    # ADDED 2026-08-18 (#802), with the idp_blk_kick reclassification.
    # All three are summed into one blocked-kick total, so all three must
    # be present or the probe under-fires; and without any of them the
    # newly scored rule reads as a false GAP — the undersized-row hazard
    # this row's own docstring warns about, which has already produced
    # two false negatives in this file's history.
    "def_punt_blocks": 1,
    "def_pat_blocks": 1,
    "def_fg_blocks": 1,
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

#: Categories the LEAGUE HOST publishes on its own weekly stat line but
#: the nflverse-derived path cannot reconstruct.
#
# ADDED 2026-08-18 (#802).  Every reason below used to be phrased as a
# statement about the universe — "not a column on the weekly feed",
# "needs play-by-play".  Each is true of NFLVERSE and false of SLEEPER.
# Measured on the host's own dump
# (docs/master-site-audit/evidence/W18/sleeper_stats_2025_wk14.json:
# 232 distinct stat keys against nflverse's ~150), restricted to player
# entries, for one week of 2025:
#
#     st_tkl_solo   87 players   135.66 pts      rec_20_29  40   45.08
#     rec_10_19    108           107.20          rec_30_39  16   25.74
#     rec_5_9      123            73.92          rec_40p     8   19.20
#     rec_0_4       81            18.02          st_ff       3   12.75
#     pass_int_td    1            -2.00          st_fum_rec  0    0.00
#
# ~451 points in one week; ~7,676 across a 17-week regular season, on one
# league's card.  Reporting that as impossible to know is the same
# silencing failure NOT_APPLICABLE was for ``st_``: the key is suppressed
# from the warning surface without the limitation being true.
#
# UNSCORABLE remains the right STATE for the nflverse path — nothing here
# can be scored from the columns that path has.  What changes is that the
# reason names its limiting source, and that a category another
# configured source publishes is recorded as RECOVERABLE rather than
# permanently lost.  Sourcing them is the host-native scoring path; this
# set is what makes the difference visible until then.
#: Rules that nflverse PLAY-BY-PLAY can deterministically reconstruct.
#
# Recorded because "unscorable" must not be read as "unknowable" (#802
# audit).  Play-by-play is already a configured source — see
# ``nflverse_direct._URL_TEMPLATES["pbp"]``, streamed today by
# ``src.nfl_data.reception_depth`` — and it carries yards_gained,
# complete_pass, touchdown, pass_touchdown, rush_touchdown, the
# passer/rusher/receiver id columns, the solo/assist tackler ids and the
# forced-fumble player ids.
#
# The six reception bands are the sharp case: ``reception_depth`` already
# emits them under these exact key names, so for those the word "unscorable"
# describes a missing JOIN, not a missing fact.
DERIVABLE_FROM_PLAY_BY_PLAY: frozenset[str] = frozenset(
    {
        "rec_0_4",
        "rec_5_9",
        "rec_10_19",
        "rec_20_29",
        "rec_30_39",
        "rec_40p",
        "rush_40p",
        "pass_td_40p",
        "pass_td_50p",
        "rec_td_40p",
        "rec_td_50p",
        "rush_td_40p",
        "rush_td_50p",
        "pass_cmp_40p",
        "pass_int_td",
        "st_tkl_solo",
        "st_ff",
        "st_fum_rec",
    }
)

HOST_PUBLISHED: frozenset[str] = frozenset(
    {
        "rec_0_4",
        "rec_5_9",
        "rec_10_19",
        "rec_20_29",
        "rec_30_39",
        "rec_40p",
        "pass_int_td",
        "st_tkl_solo",
        "st_ff",
        "st_fum_rec",
    }
)

#: Rules for players we DO value that the nflverse weekly feed cannot
#: reconstruct, each with the reason. Listing them is the point: an
#: understatement nobody can see is the failure mode this module exists
#: for. Every entry needs a data source, not a code change — and for the
#: entries in :data:`HOST_PUBLISHED` that source already exists.
UNSCORABLE_REASONS: dict[str, str] = {
    # The six reception bands are NOT a source limitation, and saying they
    # were was wrong (#802 audit).  ``src.nfl_data.reception_depth`` already
    # streams nflverse play-by-play and emits these six keys by name — its
    # own docstring explains that the weekly ``receiving_10/16/20/40``
    # columns are cumulative, misaligned and cannot reconstruct ``rec_0_4``,
    # "so the source has to be play-by-play".  The league host publishes them
    # too.  They are unscorable on THIS path only because nothing joins that
    # producer into weekly realized points yet — a wiring gap, not an
    # unavailable fact.
    "rec_0_4": "not on the nflverse weekly feed; derived per player-week by src.nfl_data.pbp_weekly from play-by-play (reconciled to the Sleeper host exactly on 2025 REG weeks 1/3/5/8/11/14/17) — attach it under realized_points.PBP_SUPPLEMENT_ROW_KEY to score it",
    "rec_5_9": "not on the nflverse weekly feed; derived per player-week by src.nfl_data.pbp_weekly from play-by-play (reconciled to the Sleeper host exactly on 2025 REG weeks 1/3/5/8/11/14/17) — attach it under realized_points.PBP_SUPPLEMENT_ROW_KEY to score it",
    "rec_10_19": "not on the nflverse weekly feed; derived per player-week by src.nfl_data.pbp_weekly from play-by-play (reconciled to the Sleeper host exactly on 2025 REG weeks 1/3/5/8/11/14/17) — attach it under realized_points.PBP_SUPPLEMENT_ROW_KEY to score it",
    "rec_20_29": "not on the nflverse weekly feed; derived per player-week by src.nfl_data.pbp_weekly from play-by-play (reconciled to the Sleeper host exactly on 2025 REG weeks 1/3/5/8/11/14/17) — attach it under realized_points.PBP_SUPPLEMENT_ROW_KEY to score it",
    "rec_30_39": "not on the nflverse weekly feed; derived per player-week by src.nfl_data.pbp_weekly from play-by-play (reconciled to the Sleeper host exactly on 2025 REG weeks 1/3/5/8/11/14/17) — attach it under realized_points.PBP_SUPPLEMENT_ROW_KEY to score it",
    "rec_40p": "not on the nflverse weekly feed; derived per player-week by src.nfl_data.pbp_weekly from play-by-play (reconciled to the Sleeper host exactly on 2025 REG weeks 1/3/5/8/11/14/17) — attach it under realized_points.PBP_SUPPLEMENT_ROW_KEY to score it",
    # Long-play bonuses.  "needs play-by-play" was true and "no configured
    # source publishes it" was NOT: play-by-play IS a configured source
    # (``nflverse_direct._URL_TEMPLATES["pbp"]``, already streamed by
    # reception_depth), and it carries yards_gained, complete_pass,
    # touchdown, pass_touchdown, rush_touchdown and the passer/rusher/
    # receiver id columns.  Every one of these is deterministic from it.
    # All are ZERO-RATED on both live cards, so none is a configured rule
    # today — which is why they are recorded rather than built.
    "rush_40p": "not on the weekly feed; deterministic from play-by-play (yards_gained + rusher_player_id) — zero-rated on both live cards",
    "pass_td_40p": "not on the weekly feed; deterministic from play-by-play (pass_touchdown + yards_gained) — zero-rated on both live cards",
    "pass_td_50p": "not on the weekly feed; deterministic from play-by-play (pass_touchdown + yards_gained) — zero-rated on both live cards",
    "rec_td_40p": "not on the weekly feed; deterministic from play-by-play (pass_touchdown + receiver_player_id + yards_gained) — zero-rated on both live cards",
    "rec_td_50p": "not on the weekly feed; deterministic from play-by-play (pass_touchdown + receiver_player_id + yards_gained) — zero-rated on both live cards",
    "rush_td_40p": "not on the weekly feed; deterministic from play-by-play (rush_touchdown + yards_gained) — zero-rated on both live cards",
    "rush_td_50p": "not on the weekly feed; deterministic from play-by-play (rush_touchdown + yards_gained) — zero-rated on both live cards",
    "pass_cmp_40p": "not on the weekly feed; deterministic from play-by-play (complete_pass + yards_gained) — zero-rated on both live cards",
    "pass_int_td": "pick-six thrown is not an nflverse weekly column; derived by src.nfl_data.pbp_weekly from interception + return_touchdown scored by the non-offense (exact against the host over seven 2025 weeks) — attach it under realized_points.PBP_SUPPLEMENT_ROW_KEY to score it",
    "idp_pass_def_3p": "per-game PD threshold; nflverse PD counts are season-aggregated on some releases — zero-rated on both live cards",
    # ADDED 2026-08-13 (B7 / W18-F003), with the prefix change above.
    # These three are PLAYER special-teams rules — real points for
    # players this board values. The nflverse feed publishes no
    # special-teams tackle, forced-fumble or fumble-recovery column.
    # The LEAGUE HOST does (#802), which is why they are in
    # HOST_PUBLISHED: unscorable on this path, recoverable on that one.
    #
    # Their siblings kr_yd / pr_yd / st_td ARE on the nflverse feed
    # (kickoff_return_yards / punt_return_yards / special_teams_tds) and
    # are scored, so they must NOT appear here.
    #
    # ``idp_blk_kick`` was here until 2026-08-18 and was simply wrong:
    # def_punt_blocks / def_pat_blocks / def_fg_blocks are all on the
    # nflverse feed. It is now scored — see realized_points._IDP_SUM_KEYS.
    "st_tkl_solo": "not an nflverse weekly column; derived by src.nfl_data.pbp_weekly from special-teams solo + tackle-with-assist ids (758 of 759 against the host over seven 2025 weeks, exact in six) — attach it under realized_points.PBP_SUPPLEMENT_ROW_KEY to score it",
    "st_ff": "not an nflverse weekly column; derived by src.nfl_data.pbp_weekly from forced_fumble_player_1/2 on special-teams plays (exact against the host over seven 2025 weeks) — attach it under realized_points.PBP_SUPPLEMENT_ROW_KEY to score it",
    "st_fum_rec": "not an nflverse weekly column; derived by src.nfl_data.pbp_weekly from a special-teams fumble recovery by the NON-fumbling team (exact against the host over seven 2025 weeks) — attach it under realized_points.PBP_SUPPLEMENT_ROW_KEY to score it",
}


#: A supplement rich enough to fire every play-by-play-only rule.
#: Same purpose as :data:`_MAXIMAL_ROW`: a probe that cannot fire a rule
#: reports a false GAP.
_MAXIMAL_PBP_SUPPLEMENT: dict[str, float] = {key: 1.0 for key in sorted(PBP_SUPPLEMENT_KEYS)}


def engine_reads_key(
    key: str,
    *,
    positions: Iterable[str] = _PROBE_POSITIONS,
    pbp_supplement: bool = False,
) -> bool:
    """Does setting ``key`` to a nonzero rate change the engine's output?

    The behavioural definition of "scored". See the module docstring for
    why this is not done by reading the source.

    ``pbp_supplement`` says whether the caller's pipeline joins the
    play-by-play producer (:mod:`src.nfl_data.pbp_weekly`) onto its stat
    rows. It defaults to False — the bare nflverse weekly path — because
    coverage is a property of the engine AND its inputs, and answering as
    though an input were present when the caller does not supply it is
    the same overstatement this module exists to prevent.
    """
    for pos in positions:
        row = dict(_MAXIMAL_ROW)
        row["position"] = pos
        if pbp_supplement:
            row[PBP_SUPPLEMENT_ROW_KEY] = dict(_MAXIMAL_PBP_SUPPLEMENT)
        off = compute_weekly_points(row, {key: 0.0}, position=pos)
        on = compute_weekly_points(row, {key: 7.0}, position=pos)
        off_pts = off.fantasy_points if off else 0.0
        on_pts = on.fantasy_points if on else 0.0
        if off_pts != on_pts:
            return True
    return False


def classify(key: str, *, pbp_supplement: bool = False) -> Coverage:
    """Resolve one scoring key to its coverage state.

    Order matters: SCORED wins over everything, because a key the engine
    demonstrably reads is scored regardless of which family its name
    suggests.
    """
    if engine_reads_key(key, pbp_supplement=pbp_supplement):
        return Coverage.SCORED
    if key in _NOT_APPLICABLE_KEYS or key.startswith(_NOT_APPLICABLE_PREFIXES):
        return Coverage.NOT_APPLICABLE
    if key in UNSCORABLE_REASONS:
        return Coverage.UNSCORABLE
    return Coverage.GAP


def audit_scoring_settings(
    scoring_settings: dict[str, Any],
    *,
    pbp_supplement: bool = False,
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
        out[classify(str(key), pbp_supplement=pbp_supplement)][str(key)] = rate
    return out


def scored_keys_for(scoring_settings: dict[str, Any], *, pbp_supplement: bool = False) -> set[str]:
    """The keys this engine actually scores — the derived replacement
    for a hand-maintained ``handled`` set."""
    return set(
        audit_scoring_settings(scoring_settings, pbp_supplement=pbp_supplement)[Coverage.SCORED]
    )


def describe_gaps(scoring_settings: dict[str, Any], *, pbp_supplement: bool = False) -> list[str]:
    """Human-readable lines for the warnings/methodology surface.

    An UNSCORABLE rule the LEAGUE HOST publishes is reported as
    *recoverable* rather than as a dead end (#802). The two are different
    statements about the world and must not read the same: one is a
    limitation of the source we chose, the other is a limitation of every
    source we have. Collapsing them is what let ~7,676 points a season be
    described as impossible to know while the host published all of it.
    """
    audit = audit_scoring_settings(scoring_settings, pbp_supplement=pbp_supplement)
    lines: list[str] = []
    for key, rate in sorted(audit[Coverage.GAP].items(), key=lambda kv: -abs(kv[1])):
        lines.append(f"{key} ({rate:g}/event) is not scored — realized points are understated.")
    for key, rate in sorted(audit[Coverage.UNSCORABLE].items(), key=lambda kv: -abs(kv[1])):
        if key in PBP_SUPPLEMENT_KEYS:
            lines.append(
                f"{key} ({rate:g}/event) is not scored because this pipeline does not "
                f"join the play-by-play producer — realized points are understated. "
                f"Recoverable: {UNSCORABLE_REASONS[key]}."
            )
        elif key in HOST_PUBLISHED:
            lines.append(
                f"{key} ({rate:g}/event) is not scored on the nflverse path — "
                f"realized points are understated. Recoverable: {UNSCORABLE_REASONS[key]}."
            )
        else:
            lines.append(f"{key} ({rate:g}/event) cannot be scored: {UNSCORABLE_REASONS[key]}.")
    return lines


def host_recoverable(scoring_settings: dict[str, Any]) -> dict[str, float]:
    """Nonzero rules this league pays that the host could supply and we do not.

    The measurable size of the exact-scoring claim's remaining gap, for the
    validation report and for any surface that wants to state it honestly.
    """
    audit = audit_scoring_settings(scoring_settings)
    return {k: v for k, v in audit[Coverage.UNSCORABLE].items() if k in HOST_PUBLISHED}


def pbp_supplement_recoverable(scoring_settings: dict[str, Any]) -> dict[str, float]:
    """Nonzero rules this league pays that the PBP producer supplies and we do not.

    The remedy is a join, not a new source: build the season with
    ``scripts/build_pbp_weekly.py`` and attach it to the stat rows under
    :data:`~src.nfl_data.realized_points.PBP_SUPPLEMENT_ROW_KEY`. Empty
    means the pipeline calling this is already complete on that axis.
    """
    audit = audit_scoring_settings(scoring_settings)
    return {k: v for k, v in audit[Coverage.UNSCORABLE].items() if k in PBP_SUPPLEMENT_KEYS}
