"""Every scoring rule a league pays must have a known disposition.

Three silent-zero scoring bugs reached production before this existed:
``idp_pass_def`` (11,119 points, cornerbacks), ``idp_qb_hit`` (6,545,
edge rushers), and then the inverted DB-vs-DL tilt caused by fixing only
the first. All three had the same shape — a key the engine did not read,
contributing zero, with nothing raising.

There *was* a check, in ``league_comparison/service.py``. It compared the
league's keys against a hand-maintained list of what the engine
supposedly handled, and it was wrong in both directions: it omitted
``idp_tkl_solo`` / ``idp_tkl_ast`` (the highest-volume IDP stats, which
the engine does score) so warned about them falsely, and it lumped
correctly-ignored DST and kicker rules in with real gaps so the signal
drowned in noise.

These tests pin the replacement. The properties that matter:

* coverage is decided by **probing** the engine, not parsing it;
* the probe can actually exercise every threshold, so a threshold key
  cannot read as a false gap;
* the four states are distinguishable, so "correctly ignored" never
  hides "silently dropped";
* the shipped league configs contain **zero** GAPs.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.nfl_data import realized_points as rp
from src.nfl_data.scoring_coverage import (
    _MAXIMAL_ROW,
    Coverage,
    HOST_PATH_UNREACHABLE,
    UNSCORABLE_REASONS,
    audit_scoring_settings,
    classify,
    engine_reads_key,
)


def test_the_probe_row_can_fire_every_threshold():
    """Non-vacuity for the probe itself, and a real bug it already had.

    The first version of this probe used a row with 350 passing yards,
    which is below the ``bonus_pass_yd_400`` cutoff — so that key, and
    every other threshold above the sample values, reported as an unread
    gap when the engine handles them fine. A probe that under-reports
    coverage manufactures phantom defects, which is how a check gets
    disabled.
    """
    for key in (
        "bonus_pass_yd_300",
        "bonus_pass_yd_400",
        "bonus_rush_yd_100",
        "bonus_rush_yd_200",
        "bonus_rec_yd_100",
        "bonus_rec_yd_200",
        "idp_tkl_5p",
        "idp_tkl_10p",
    ):
        assert engine_reads_key(key), (
            f"{key} reads as unscored. The engine implements it; the probe row "
            "is too small to reach its threshold."
        )


def test_the_probe_detects_a_key_the_engine_genuinely_ignores():
    """The other direction — it must not report everything as scored."""
    assert not engine_reads_key("definitely_not_a_real_scoring_key")
    assert not engine_reads_key("pts_allow_0")


def test_the_four_states_are_distinguishable():
    assert classify("pass_yd") is Coverage.SCORED
    assert classify("pts_allow_0") is Coverage.NOT_APPLICABLE
    assert classify("rec_40p") is Coverage.UNSCORABLE
    assert classify("definitely_not_a_real_scoring_key") is Coverage.GAP


def test_scored_wins_over_family_prefix():
    """A key the engine demonstrably reads is SCORED regardless of what
    its name looks like.

    ``def_td`` is a team-defense key and ``idp_def_td`` is the
    individual one; a prefix rule applied before the probe would
    misfile the second.
    """
    assert classify("idp_def_td") is Coverage.SCORED
    assert classify("def_td") is Coverage.NOT_APPLICABLE


def test_team_defense_keys_are_not_confused_with_their_idp_twins():
    """``sack`` / ``int`` / ``ff`` are the DST spellings of
    ``idp_sack`` / ``idp_int`` / ``idp_ff``.

    Treating the unprefixed ones as IDP would double-count every
    defender's production.
    """
    for team_key, idp_key in (("sack", "idp_sack"), ("int", "idp_int"), ("ff", "idp_ff")):
        assert classify(team_key) is Coverage.NOT_APPLICABLE, team_key
        assert classify(idp_key) is Coverage.SCORED, idp_key


def test_the_keys_fixed_in_this_change_are_now_scored():
    """The seven gaps the audit found on the live dynasty_main card.

    Worth 16,516 unscored points across 2025, and asymmetric by
    position — which is what made them dangerous to a relative
    comparison rather than merely imprecise.
    """
    for key in (
        "bonus_fd_qb",
        "bonus_fd_rb",
        "bonus_fd_wr",
        "bonus_fd_te",
        "pass_cmp",
        "pass_inc",
        "rush_att",
    ):
        assert engine_reads_key(key), f"{key} is still unscored"


def test_unscorable_entries_each_carry_a_reason():
    """An UNSCORABLE key is a permanent, known understatement. Without a
    stated reason it is indistinguishable from something nobody got
    round to.
    """
    for key, reason in UNSCORABLE_REASONS.items():
        assert reason and len(reason) > 15, f"{key} has no usable reason"
        assert classify(key) in (Coverage.UNSCORABLE, Coverage.SCORED), key


def test_zero_rated_rules_are_ignored():
    """Sleeper ships dozens of zeroed keys for unused categories. A rule
    worth nothing cannot cost anything, and warning about it is the
    noise that got the old check ignored."""
    audit = audit_scoring_settings({"definitely_not_real": 0.0, "pass_yd": 0.04})
    assert audit[Coverage.GAP] == {}
    assert audit[Coverage.SCORED] == {"pass_yd": 0.04}


def test_a_nonzero_unknown_rule_is_reported_as_a_gap():
    audit = audit_scoring_settings({"some_new_sleeper_rule": 2.5})
    assert audit[Coverage.GAP] == {"some_new_sleeper_rule": 2.5}


# ── V1-49 / #1020 ────────────────────────────────────────────────────


def test_punt_ret_td_is_a_bare_weekly_feed_key():
    """No play-by-play needed — real, distinct from st_td/kr_yd/pr_yd."""
    assert classify("punt_ret_td") is Coverage.SCORED
    assert engine_reads_key("punt_ret_td")


def test_kick_ret_td_needs_the_pbp_supplement():
    """Real, but only reachable with play-by-play attached — no bare
    weekly column exists for it (unlike punt_ret_td)."""
    assert classify("kick_ret_td") is Coverage.UNSCORABLE
    assert classify("kick_ret_td", pbp_supplement=True) is Coverage.SCORED
    assert not engine_reads_key("kick_ret_td")
    assert engine_reads_key("kick_ret_td", pbp_supplement=True)


def test_idp_return_td_keys_are_closed_as_unsupported():
    """Investigated, not fabricated: no real Sleeper scoring UI category
    and no host-truth instance exists for either key (see the reason
    string and tests/nfl_data/test_individual_special_teams.py for the
    full evidence). CLOSED as unsupported, never DERIVABLE_FROM_PLAY_BY_PLAY
    and never HOST_PUBLISHED — either would misrepresent the finding."""
    from src.nfl_data.scoring_coverage import DERIVABLE_FROM_PLAY_BY_PLAY, HOST_PUBLISHED

    for key in ("idp_def_pr_td", "idp_def_kr_td"):
        assert classify(key) is Coverage.UNSCORABLE
        assert key in UNSCORABLE_REASONS
        assert key not in DERIVABLE_FROM_PLAY_BY_PLAY
        assert key not in HOST_PUBLISHED


#: The operator's ACTUAL scoring cards, snapshotted 2026-07-28.
#:
#: A first version of this pointed at
#: ``tests/league_intel/fixtures/scoring_settings_2025.json``, which is a
#: real Sleeper card but a DIFFERENT configuration — it pays
#: ``bonus_fd_te`` 1.35 and zeroes ``pass_cmp`` / ``rush_att``. Auditing
#: it would have looked like a live guard while checking rules the
#: operator does not use, so the gaps this change fixes would not have
#: been covered. Auditing a network fetch instead would make the test
#: ``livedata``-marked, and CI deselects those — a gap detector CI never
#: runs is precisely the failure mode this module exists to stop.
_LIVE_CARDS = Path(__file__).resolve().parent / "fixtures" / "live_scoring_cards_2026-07-28.json"


def _live_cards() -> dict:
    return json.loads(_LIVE_CARDS.read_text())


def test_the_live_league_cards_have_no_gaps():
    """The assertion that matters, against real operator scoring.

    If Sleeper adds a rule, or the operator enables one the engine
    cannot read, this fails and names it. That matters most for the
    stated "link any Sleeper account" goal, where the next league's card
    is one nobody reviewed — a stranger's league can easily pay
    ``idp_solo`` where this one pays ``idp_tkl_solo``.
    """
    for name, card in _live_cards().items():
        gaps = audit_scoring_settings(card)[Coverage.GAP]
        assert not gaps, (
            f"{name} pays rules the engine ignores, so its realized points "
            f"are understated: {sorted(gaps)}"
        )


def test_the_live_card_audit_is_not_vacuous():
    """The cards must contain rules and reach several states.

    A fixture that quietly emptied would make the assertion above pass
    while checking nothing.
    """
    cards = _live_cards()
    assert set(cards) == {"dynasty_main", "baseline"}
    audit = audit_scoring_settings(cards["dynasty_main"])
    assert len(audit[Coverage.SCORED]) >= 25, "implausibly few scored rules"
    assert audit[Coverage.NOT_APPLICABLE], "no DST/K rules — is this the real card?"
    assert audit[Coverage.UNSCORABLE], (
        "dynasty_main pays distance-banded receptions, which cannot be "
        "reconstructed from weekly stats; if that changed, update "
        "UNSCORABLE_REASONS rather than deleting this"
    )


def test_the_live_card_would_have_failed_before_this_change():
    """Proof the guard fires on the state that actually shipped.

    Removes the keys this change added and confirms every one of them
    reappears as a gap on the real card. Asserts against the card's own
    nonzero set rather than a hardcoded list, so it stays honest if the
    operator changes their scoring.
    """
    card = _live_cards()["dynasty_main"]
    added = ("bonus_fd_qb", "bonus_fd_rb", "bonus_fd_wr", "bonus_fd_te", "pass_cmp", "rush_att")
    expected = {k for k in added if float(card.get(k) or 0) != 0.0}
    assert expected, "the live card pays none of the added keys — fixture is stale"

    saved_simple = dict(rp._SIMPLE_KEYS)
    saved_fd = dict(rp._FIRST_DOWN_BONUS_KEYS)
    try:
        for k in ("pass_cmp", "rush_att"):
            rp._SIMPLE_KEYS.pop(k, None)
        rp._FIRST_DOWN_BONUS_KEYS.clear()
        gaps = set(audit_scoring_settings(card)[Coverage.GAP])
        missing = expected - gaps
        assert not missing, f"guard failed to detect regressed keys: {sorted(missing)}"
    finally:
        rp._SIMPLE_KEYS.clear()
        rp._SIMPLE_KEYS.update(saved_simple)
        rp._FIRST_DOWN_BONUS_KEYS.clear()
        rp._FIRST_DOWN_BONUS_KEYS.update(saved_fd)


def test_a_missing_alias_shows_up_as_a_gap():
    """THE REGRESSION, reconstructed.

    Removes ``idp_qb_hit`` from the alias map — exactly the state PR
    #606's measurement was taken in — and asserts the audit reports it.
    """
    full = dict(rp._SCORING_KEY_ALIASES)
    card = {"idp_qb_hit": 2.13, "idp_sack": 2.92}
    try:
        assert audit_scoring_settings(card)[Coverage.GAP] == {}
        rp._SCORING_KEY_ALIASES = {k: v for k, v in full.items() if k != "idp_qb_hit"}
        gaps = audit_scoring_settings(card)[Coverage.GAP]
        assert "idp_qb_hit" in gaps, (
            "the half-fixed alias state is not detected — this is the exact "
            "condition that shipped an inverted DB-vs-DL tilt"
        )
    finally:
        rp._SCORING_KEY_ALIASES = full


def test_the_maximal_row_stays_maximal():
    """Guards the probe's fixture against quiet shrinkage.

    Every threshold the engine checks must remain reachable; someone
    trimming these numbers to "realistic" values would silently reopen
    the false-gap failure above.
    """
    assert _MAXIMAL_ROW["passing_yards"] >= 400
    assert _MAXIMAL_ROW["rushing_yards"] >= 200
    assert _MAXIMAL_ROW["receiving_yards"] >= 200
    assert _MAXIMAL_ROW["def_tackles_solo"] + _MAXIMAL_ROW["def_tackles_with_assist"] >= 10
    assert (
        _MAXIMAL_ROW["attempts"] > _MAXIMAL_ROW["completions"]
    ), "attempts must exceed completions or pass_inc cannot fire"


# ── Coverage verdicts are nflverse-path-scoped (V1-49 prerequisite) ────
#
# ``engine_reads_key`` probes with nflverse COLUMN names and never passes
# ``source=``, so every verdict this module returns describes the
# champion path. That was silent; ``HOST_PATH_UNREACHABLE`` states it and
# these tests keep the claim honest against the committed host dumps.

_HOST_DUMPS = sorted(
    (Path(__file__).resolve().parents[2] / "docs" / "master-site-audit" / "evidence" / "W18").glob(
        "sleeper_stats_2025_wk*.json"
    )
)


def _host_player_entries():
    """Every PLAYER entry across the committed 2025 REG host dumps.

    Numeric-id filter matches ``realized_points.is_host_player_entry`` —
    Sleeper keys team defenses by alpha code and several ST keys appear
    on BOTH, so an unfiltered scan would measure the wrong population.
    """
    out = []
    for path in _HOST_DUMPS:
        raw = json.loads(path.read_text(encoding="utf-8"))
        out.extend(v or {} for k, v in raw.items() if k.replace("-", "").isdigit())
    return out


def test_the_host_dumps_are_actually_present_and_populated():
    """Non-vacuity: an empty scan would make every claim below pass."""
    assert len(_HOST_DUMPS) == 3, [p.name for p in _HOST_DUMPS]
    entries = _host_player_entries()
    assert len(entries) > 6000, len(entries)


def test_the_host_publishes_the_combined_st_td_and_the_return_yardage():
    """The control. If the host published NO special teams at all, the
    asymmetry below would be uninteresting."""
    entries = _host_player_entries()
    for key in ("st_td", "kr_yd", "pr_yd"):
        assert any(key in e for e in entries), key


def test_every_host_path_unreachable_key_is_genuinely_absent_from_the_host():
    """The record must stay measured, not become a stale comment."""
    entries = _host_player_entries()
    for key in HOST_PATH_UNREACHABLE:
        present = sum(1 for e in entries if key in e)
        assert present == 0, f"{key} now appears on {present} host player entries"


def test_punt_ret_td_is_scored_on_nflverse_but_recorded_unreachable_on_the_host():
    """Both halves matter: it really is scored on the champion path, and
    it really is unreachable on the challenger one."""
    assert classify("punt_ret_td") is Coverage.SCORED
    assert "punt_ret_td" in HOST_PATH_UNREACHABLE
    # The nflverse column it is scored from is likewise never on a host row.
    assert all("pt_return_tds" not in e for e in _host_player_entries())


def test_kick_ret_td_is_not_double_recorded():
    """It is already UNSCORABLE without the supplement and its
    UNSCORABLE_REASONS entry already records the host gap — listing it
    again would be a second owner for one fact."""
    assert "kick_ret_td" not in HOST_PATH_UNREACHABLE
    assert "kick_ret_td" in UNSCORABLE_REASONS


def test_every_recorded_reason_names_its_measurement():
    for key, reason in HOST_PATH_UNREACHABLE.items():
        assert len(reason) > 80, f"{key} is recorded without a real justification"
        assert "measured" in reason, f"{key} does not say what was measured"
