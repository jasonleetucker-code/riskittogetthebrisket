"""Score the league host's own stat line, instead of round-tripping it (#802).

THE DEFECT
----------
``league_comparison.sleeper_stats._FIELD_MAP`` translates Sleeper's short stat
keys **into** nflverse long column names.  ``realized_points`` then translates
them **back** into Sleeper keys to score them.  Any category with no nflverse
column is destroyed in the middle hop — even though the source vocabulary and
the destination vocabulary both carry it.

Measured against dynasty_main's live card and the host's own wk14 2025 dump:
**50 of the 85 rules the card pays** are published by the host and cannot
traverse ``_FIELD_MAP``.  That is every player special-teams category, the whole
kicker family, all six ``rec_*`` distance bands, the first-down bonuses,
``pass_cmp``, ``pass_inc``, ``rush_att``, ``idp_pass_def`` and ``idp_blk_kick``.
Restricted to player entries it is ~451 points in one week; ~7,676 across a
17-week season.

The fix is not more ``_FIELD_MAP`` entries.  Sleeper's stat line **is** the
canonical scoring vocabulary — ``league_intel.scorer.score_stat_line`` scores it
directly and is validated against the host's own ``players_points`` over 1,339
player-weeks at max |Δ| 0.0050.  The round-trip should not exist.

THE TWO HAZARDS THIS PATH INTRODUCES, AND WHY THEY ARE TESTED HARD
------------------------------------------------------------------
1. **Player vs team.**  The host's dump contains team-defense entries beside
   player entries, and ``st_tkl_solo`` / ``kr_yd`` are published under ONE key
   name on BOTH — meaning the team's total and the player's own.  The split
   therefore cannot be done by key family; it must be done by entry kind.
   Getting it wrong pays a DST rule to a player.

2. **Derived totals.**  The host publishes ``pts_ppr`` / ``pts_std`` /
   ``pts_half_ppr`` / ``pts_idp`` — whole precomputed fantasy scores — on the
   same line as the raw stats.  Scoring one would not be a small error; it
   would double the entire line.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.api import feature_flags
from src.nfl_data.realized_points import (
    HOST_DERIVED_TOTALS,
    compute_weekly_points,
    host_stat_line,
    is_host_player_entry,
)

EVIDENCE = Path(__file__).resolve().parents[2] / "docs" / "master-site-audit" / "evidence" / "W18"


@pytest.fixture(scope="module")
def card() -> dict:
    doc = json.loads(
        (EVIDENCE / "sleeper_league_1312006700437352448.json").read_text(encoding="utf-8")
    )
    return doc.get("scoring_settings") or {}


@pytest.fixture(scope="module")
def host_week() -> dict:
    return json.loads((EVIDENCE / "sleeper_stats_2025_wk14.json").read_text(encoding="utf-8"))


# ── the categories the round-trip destroyed ──────────────────────────


HOST_ONLY_KEYS = [
    "st_tkl_solo", "st_ff", "rec_0_4", "rec_5_9", "rec_10_19",
    "rec_20_29", "rec_30_39", "rec_40p", "pass_int_td",
]


@pytest.mark.parametrize("key", HOST_ONLY_KEYS)
def test_host_only_categories_score_on_the_host_path(key, card):
    """Each of these is UNSCORABLE from nflverse and paid by the card."""
    rate = float(card.get(key) or 0)
    assert rate, f"{key} is not paid by the live card — fixture drift"
    row = {"season": 2025, "week": 14, "position": "SAF", "player_id": "4034", key: 2}
    rp = compute_weekly_points(row, card, position="SAF", source="sleeper")
    assert rp is not None
    assert rp.fantasy_points == pytest.approx(2 * rate, abs=1e-9), f"{key} did not score"


def test_the_host_path_scores_what_the_nflverse_path_cannot(card):
    """The whole point, in one assertion."""
    row = {"season": 2025, "week": 14, "position": "WR", "player_id": "4034",
           "rec": 5, "rec_yd": 60, "rec_5_9": 3, "rec_10_19": 2, "st_tkl_solo": 1}
    host = compute_weekly_points(row, card, position="WR", source="sleeper")
    # The same row through the champion path: rec/rec_yd are nflverse-shaped
    # names it does not read, and the bands have no nflverse column at all.
    assert host.fantasy_points > 0
    labels = {lab for lab, _s, _p in host.breakdown}
    assert any("5-9" in lab or "rec_5_9" in lab for lab in labels), labels


# ── player vs team separation ────────────────────────────────────────


def test_team_entries_are_not_player_entries():
    assert is_host_player_entry("4034")
    assert is_host_player_entry(4034)
    # The host's dump carries TWO team-entry families, and a rule tuned to
    # the first admits all 28 of the second.
    for team in ("PHI", "KC", "SF", "GB", "LAR", "JAX"):
        assert not is_host_player_entry(team)
    for team in ("TEAM_BUF", "TEAM_LAR", "TEAM_NYJ", "TEAM_KC"):
        assert not is_host_player_entry(team), "prefixed team entries are not players"


def test_a_gsis_id_is_a_player_not_a_team():
    """``fetch_sleeper_weekly_stats`` stamps a GSIS id into ``player_id``.
    A digits-only test would refuse every real player it produces — trading
    the DST double-count for a different silent zero."""
    assert is_host_player_entry("00-0034796")
    assert is_host_player_entry("00-0039918")


def test_a_producer_row_carrying_a_gsis_id_still_scores(card):
    row = {"season": 2025, "week": 14, "position": "WR",
           "player_id": "00-0034796", "player_id_sleeper": "4034", "rec": 4}
    rp = compute_weekly_points(row, card, position="WR", source="sleeper")
    assert rp is not None and rp.fantasy_points > 0


def test_the_hosts_own_id_decides_when_both_are_present(card):
    """A team row rebuilt by the producer keeps its alpha id in
    ``player_id_sleeper``; that is the field that must decide."""
    row = {"season": 2025, "week": 14, "position": "DEF",
           "player_id": "PHI", "player_id_sleeper": "PHI", "pts_allow": 13}
    assert compute_weekly_points(row, card, position="DEF", source="sleeper") is None


def test_a_team_entry_is_refused_rather_than_scored_as_a_player(card):
    """A DST line carries ``pts_allow``, ``int``, ``fum_rec`` — rules that would
    pay a player for his defense's production."""
    team_row = {"season": 2025, "week": 14, "player_id": "PHI",
                "pts_allow": 13, "int": 2, "fum_rec": 1, "st_tkl_solo": 9}
    assert compute_weekly_points(team_row, card, position="DEF", source="sleeper") is None


def test_shared_name_keys_are_the_reason_the_filter_must_exist(host_week):
    """``st_tkl_solo`` and ``kr_yd`` appear on both entry kinds under one name,
    so no key-family rule can separate them."""
    for key in ("st_tkl_solo", "kr_yd"):
        on_players = any(
            str(p).isdigit() and isinstance(l, dict) and l.get(key) for p, l in host_week.items()
        )
        on_teams = any(
            not str(p).isdigit() and isinstance(l, dict) and l.get(key)
            for p, l in host_week.items()
        )
        assert on_players and on_teams, key


# ── derived totals must never be scored ──────────────────────────────


@pytest.mark.parametrize("total", ["pts_ppr", "pts_std", "pts_half_ppr", "pts_idp"])
def test_precomputed_fantasy_totals_are_never_scored(total):
    assert total in HOST_DERIVED_TOTALS
    line = host_stat_line({"season": 2025, "week": 1, "player_id": "1", total: 22.4, "rec": 3})
    assert total not in line
    assert line.get("rec") == 3.0


def test_scoring_a_derived_total_would_double_the_line():
    """Non-vacuity for the guard above: if the card ever paid pts_ppr at 1.0 the
    line would score itself twice."""
    row = {"season": 2025, "week": 1, "player_id": "1", "rec": 3, "pts_ppr": 99.0}
    rp = compute_weekly_points(row, {"rec": 1.0, "pts_ppr": 1.0}, position="WR", source="sleeper")
    assert rp.fantasy_points == 3.0


# ── stat-side alias reconciliation (no double counting) ──────────────


def test_a_line_carrying_both_alias_spellings_pays_the_rule_once():
    """Sleeper ships several spellings for one IDP rule.  A card paying the
    canonical key and a line carrying both spellings must pay once."""
    row = {"season": 2025, "week": 1, "player_id": "1", "position": "CB",
           "idp_pass_def": 3, "idp_pd": 3}
    rp = compute_weekly_points(row, {"idp_pd": 5.32}, position="CB", source="sleeper")
    assert rp.fantasy_points == pytest.approx(3 * 5.32, abs=1e-9)


def test_an_alias_spelled_stat_reaches_a_canonically_spelled_rule():
    row = {"season": 2025, "week": 1, "player_id": "1", "position": "CB", "idp_pass_def": 3}
    rp = compute_weekly_points(row, {"idp_pd": 5.32}, position="CB", source="sleeper")
    assert rp.fantasy_points == pytest.approx(3 * 5.32, abs=1e-9)


def test_metadata_never_becomes_a_stat():
    line = host_stat_line(
        {"season": 2025, "week": 14, "player_id": "1", "position": "WR",
         "player_name": "X", "team": "PHI", "season_type": "REG", "rec": 4}
    )
    assert set(line) == {"rec"}


# ── the champion path is untouched ───────────────────────────────────


def test_the_default_source_is_still_nflverse(card):
    """Flag off, no source argument: byte-identical to before."""
    row = {"season": 2025, "week": 1, "position": "WR",
           "receiving_yards": 100, "receptions": 7, "receiving_tds": 1}
    default = compute_weekly_points(row, card, position="WR")
    explicit = compute_weekly_points(row, card, position="WR", source="nflverse")
    assert default.fantasy_points == explicit.fantasy_points
    assert default.fantasy_points > 0


def test_the_flag_is_off_by_default():
    feature_flags.reload()
    assert feature_flags.is_enabled("host_native_scoring") is False


def test_an_unknown_source_is_refused_not_guessed():
    with pytest.raises(ValueError):
        compute_weekly_points(
            {"season": 2025, "week": 1, "rec": 1}, {"rec": 1.0}, position="WR", source="espn"
        )


# ── reconciliation against the LEAGUE HOST's own awarded points ───────
#
# This is the evidence that gates promotion, and it is available only
# because the challenger removes a step rather than adding one.
#
# ``score_stat_line`` is already validated against Sleeper's own
# ``players_points`` (tests/league_intel/test_golden_scoring.py, 1,339
# player-weeks, max |Δ| 0.0050).  Host-native scoring is that scorer
# applied to the host's own line with nothing in between — so it inherits
# that validation exactly, and these tests prove the inheritance is real
# rather than asserted.
#
# The champion path cannot be validated this way at all: it would have to
# rename the host's line into nflverse columns and back first, which is
# the step that loses the rules.

GOLDEN = Path(__file__).resolve().parents[1] / "league_intel" / "fixtures"
HOST_TOL = 0.011  # the host displays 2-decimal scores


@pytest.fixture(scope="module")
def scoring_2025() -> dict:
    return json.loads((GOLDEN / "scoring_settings_2025.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def golden_cases() -> list:
    return json.loads((GOLDEN / "golden_player_weeks.json").read_text(encoding="utf-8"))


def test_host_native_reproduces_every_host_awarded_score(golden_cases, scoring_2025):
    """16 real 2025 player-weeks, 16 archetypes, against the league's own
    scoreboard — including the kicker, the pick-six QB and five IDP roles."""
    assert golden_cases, "golden fixtures missing"
    failures = []
    for case in golden_cases:
        row = {
            "season": 2025,
            "week": case.get("week"),
            "player_id": str(case.get("playerId") or "1"),
            "position": case.get("position"),
            **case["statLine"],
        }
        rp = compute_weekly_points(
            row, scoring_2025, position=case.get("position"), source="sleeper"
        )
        assert rp is not None, case["archetype"]
        delta = abs(rp.fantasy_points - float(case["expectedPoints"]))
        if delta > HOST_TOL:
            failures.append(
                f"{case['archetype']} {case['name']}: "
                f"got {rp.fantasy_points:.4f} want {case['expectedPoints']} (Δ{delta:.4f})"
            )
    assert not failures, "host-native scoring disagrees with the host:\n" + "\n".join(failures)


def test_the_idp_archetypes_reconcile_specifically(golden_cases, scoring_2025):
    """Stacking semantics: solo / assist / combined tackles, sacks + TFL, and
    PD + INT must each be paid once and only once.  A double count shows up
    here as a positive delta on exactly the defensive archetypes."""
    idp = [c for c in golden_cases if c["archetype"] in
           ("tackle LB", "edge rusher", "interior DL", "box safety", "ballhawk corner")]
    assert len(idp) == 5, "IDP archetype coverage shrank"
    for case in idp:
        row = {"season": 2025, "week": case.get("week"), "player_id": "1",
               "position": case.get("position"), **case["statLine"]}
        rp = compute_weekly_points(
            row, scoring_2025, position=case.get("position"), source="sleeper"
        )
        assert rp.fantasy_points == pytest.approx(
            float(case["expectedPoints"]), abs=HOST_TOL
        ), case["archetype"]


def test_the_kicker_archetypes_reconcile(golden_cases, scoring_2025):
    """The whole kicker family is unreachable through _FIELD_MAP."""
    kickers = [c for c in golden_cases if c["archetype"].startswith("kicker")]
    assert kickers
    for case in kickers:
        row = {"season": 2025, "week": case.get("week"), "player_id": "1",
               "position": case.get("position"), **case["statLine"]}
        rp = compute_weekly_points(
            row, scoring_2025, position=case.get("position"), source="sleeper"
        )
        assert rp.fantasy_points == pytest.approx(
            float(case["expectedPoints"]), abs=HOST_TOL
        ), case["archetype"]


def test_a_card_written_in_alias_spelling_pays_the_rule_once():
    """Regression for a real double count found by the golden fixtures.

    ``compute_weekly_points`` copies an alias RATE onto the canonical key,
    so a card written as ``idp_qb_hit`` pays BOTH spellings.  An earlier
    version of ``host_stat_line`` also copied the STAT onto both, and the
    rule was then paid twice — the tackle-LB archetype scored 29.7956
    against the host's own 27.6.

    One QB hit, one rule, one payment.
    """
    row = {"season": 2025, "week": 1, "player_id": "1", "position": "LB", "idp_qb_hit": 1}
    rp = compute_weekly_points(row, {"idp_qb_hit": 2.2}, position="LB", source="sleeper")
    assert rp.fantasy_points == pytest.approx(2.2, abs=1e-9)


def test_the_collapse_leaves_at_most_one_key_per_rule():
    """Structural statement of the guard above: whatever spellings arrive,
    the line that reaches the scorer carries one key per rule."""
    from src.nfl_data.realized_points import _SCORING_KEY_ALIASES

    line = host_stat_line(
        {"season": 2025, "week": 1, "player_id": "1",
         "idp_qb_hit": 1, "idp_hit": 1, "idp_pass_def": 2, "idp_pd": 2}
    )
    for alias, canonical in _SCORING_KEY_ALIASES.items():
        assert not (alias in line and canonical in line), f"{alias}/{canonical} both survived"
        assert alias not in line, f"{alias} should have collapsed onto {canonical}"


def test_no_team_entry_in_the_real_host_dump_is_taken_for_a_player(host_week):
    """Census over the host's own wk14 dump rather than a hand-listed set.

    This is the assertion that caught the ``TEAM_*`` family: 56 team entries
    exist, and an earlier deny-list rule admitted exactly half of them.
    """
    admitted = [
        pid for pid in host_week
        if not str(pid).replace("-", "").isdigit() and is_host_player_entry(pid)
    ]
    assert not admitted, f"{len(admitted)} team entries taken for players: {admitted[:6]}"


def test_every_player_entry_in_the_real_host_dump_is_admitted(host_week):
    """Non-vacuity for the guard above: a filter that refuses everything
    would pass the previous test and score nobody."""
    admitted = sum(1 for pid in host_week if is_host_player_entry(pid))
    assert admitted > 2000, f"only {admitted} player entries admitted"
