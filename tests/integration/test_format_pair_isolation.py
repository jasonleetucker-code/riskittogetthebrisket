"""Format-pair isolation: one league's settings never decide another's answer.

Owner directive 2026-11-08 section 5: "Test critical combinations of league
settings ... and make sure one format's logic does not contaminate another
format's results."

Two synthetic leagues differ on every axis the canonical league-scoped owners
read:

======================  ==============================  ==========================
axis                    League A ("fmt_a")              League B ("fmt_b")
======================  ==============================  ==========================
QB rule                 superflex                       1QB
defense                 IDP (DL/LB/DB slots)            offense only
TE scoring              premium (bonus_rec_te 0.5)      none
teams                   12                              10
playoffs                7 teams, re-seed                6 teams, fixed bracket
roster size             58                              30
divisions               3, recorded "no playoff effect" none
FAAB balance            known ($30 of $100)             unknown
======================  ==============================  ==========================

For every surface below the expectations are written out by hand from those
settings (never read back from the function under test), and each surface is
called A, B, A, B so that any module-level cache or shared state that carries
one league's answer into the other shows up as a changed answer.

Surfaces covered (all pure and offline): lineup slots / eligibility
(``src/ros/lineup.py``), playoff structure + divisions
(``src/public_league/playoff_structure.py``), roster cap
(``src/trade/roster_capacity.py``), FAAB comparability target + gate
(``src/trade/faab_comparability.py``), FAAB need and unknown balance
(``src/trade/faab_engine.py``), waiver add-pool position gate
(``src/trade/waiver.py``).

Surfaces NOT covered: anything needing the live contract or Sleeper network
(the ``/api/data`` scoring-fingerprint gate, the ``sleeper_overlay`` merge,
draft capital, the public-league snapshot builders). Those need a loaded
contract or HTTP and belong to their own owners' tests.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.public_league import playoff_structure as ps
from src.ros import lineup
from src.trade import faab_comparability as fc
from src.trade import faab_engine as engine
from src.trade import roster_capacity as rc
from src.trade import waiver

# -- the two synthetic leagues ------------------------------------------------

KEY_A, KEY_B, KEY_UNRECORDED = "fmt_a", "fmt_b", "fmt_unrecorded"

ROSTER_POSITIONS_A = (
    ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "SUPER_FLEX"]
    + ["DL", "DL", "LB", "LB", "DB", "DB"]
    + ["BN"] * 8
)
ROSTER_POSITIONS_B = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "BN", "BN", "BN", "IR"]

SETTINGS_A = {
    "rosterSize": 58,
    "teamCount": 12,
    "starters": {
        "QB": 1,
        "RB": 2,
        "WR": 2,
        "TE": 1,
        "FLEX": 2,
        "SUPER_FLEX": 1,
        "DL": 2,
        "LB": 2,
        "DB": 2,
    },
}
SETTINGS_B = {
    "rosterSize": 30,
    "teamCount": 10,
    "starters": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1},
}

CARD_A = {"rec": 1.0, "bonus_rec_te": 0.5, "bonus_rec_wr": 0.0, "bonus_rec_rb": 0.0}
CARD_B = {"rec": 1.0, "bonus_rec_te": 0.0, "bonus_rec_wr": 0.0, "bonus_rec_rb": 0.0}


def _season(settings: dict, rosters: list | None = None, metadata: dict | None = None):
    return SimpleNamespace(
        league={"settings": settings, "metadata": metadata or {}}, rosters=rosters or []
    )


SEASON_A = _season(
    {"playoff_teams": 7, "playoff_seed_type": 1, "playoff_week_start": 15, "divisions": 3},
    rosters=[{"roster_id": i, "settings": {"division": (i - 1) % 3 + 1}} for i in range(1, 13)],
    metadata={"division_1": "East", "division_2": "West", "division_3": "North"},
)
SEASON_B = _season(
    {"playoff_teams": 6, "playoff_seed_type": 0, "playoff_week_start": 15},
    rosters=[{"roster_id": i, "settings": {}} for i in range(1, 11)],
)


@pytest.fixture
def recorded_rules(tmp_path, monkeypatch):
    """A synthetic rules file that records ONLY fmt_a (never dynasty_main's rule)."""
    path = tmp_path / "playoff_rules.json"
    path.write_text(
        json.dumps(
            {
                "rules": {
                    KEY_A: {
                        "qualification": "overall_record",
                        "seeding": "overall_record",
                        "standingsTiebreakers": ["points_for"],
                        "divisionCount": 3,
                        "divisionPlayoffEffect": "none",
                        "divisionChampion": "best_overall_record_in_division",
                        "divisionChampionTiebreakers": ["points_for"],
                        "approvedAt": "2026-11-08",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ps, "_RULES_PATH", path)
    return path


def _abab(fn_a, fn_b):
    """Call A, B, A, B and return the four answers (cache/state carry-over probe)."""
    return fn_a(), fn_b(), fn_a(), fn_b()


# -- 1. lineup slots and eligibility (superflex vs 1QB, IDP vs offense-only) ---


def test_starter_slots_follow_each_leagues_own_lineup():
    a1, b1, a2, b2 = _abab(
        lambda: lineup.resolve_starter_slots(roster_positions=ROSTER_POSITIONS_A),
        lambda: lineup.resolve_starter_slots(roster_positions=ROSTER_POSITIONS_B),
    )
    expect_a = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "SUPER_FLEX"] + [
        "DL",
        "DL",
        "LB",
        "LB",
        "DB",
        "DB",
    ]
    expect_b = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"]  # BN and IR are not slots
    assert a1 == a2 == (expect_a, "sleeper_roster_positions")
    assert b1 == b2 == (expect_b, "sleeper_roster_positions")


def test_registry_starters_ladder_is_per_league_and_unknown_is_refusal():
    a = lineup.resolve_starter_slots(roster_settings=SETTINGS_A)
    b = lineup.resolve_starter_slots(roster_settings=SETTINGS_B)
    a_again = lineup.resolve_starter_slots(roster_settings=SETTINGS_A)
    unknown = lineup.resolve_starter_slots(roster_settings={})
    assert a == a_again
    assert a[1] == b[1] == "registry_starters"
    assert sorted(a[0]) == sorted(
        ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "SUPER_FLEX"]
        + ["DL", "DL", "LB", "LB", "DB", "DB"]
    )
    assert sorted(b[0]) == sorted(["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"])
    # An unconfigured league is a refusal -- it never inherits either lineup.
    assert unknown == ([], None)


def test_qb_and_defender_eligibility_only_where_the_league_has_the_slot():
    def qb_slots(slots):
        return [s for s in slots if "QB" in lineup.slot_eligible_positions(s)]

    def idp_slots(slots):
        return [s for s in slots if lineup.slot_eligible_positions(s) & {"DL", "LB", "DB"}]

    slots_a = lineup.resolve_starter_slots(roster_positions=ROSTER_POSITIONS_A)[0]
    slots_b = lineup.resolve_starter_slots(roster_positions=ROSTER_POSITIONS_B)[0]
    for _ in range(2):  # A, B, A, B
        # Superflex league: a QB can fill QB and SUPER_FLEX; 1QB league: QB only.
        assert qb_slots(slots_a) == ["QB", "SUPER_FLEX"]
        assert qb_slots(slots_b) == ["QB"]
        # IDP league starts six defenders; the offense-only league starts none.
        assert idp_slots(slots_a) == ["DL", "DL", "LB", "LB", "DB", "DB"]
        assert idp_slots(slots_b) == []
    # FLEX itself never admits a QB in either league (shared table, no leak).
    assert "QB" not in lineup.slot_eligible_positions("FLEX")
    assert "QB" in lineup.slot_eligible_positions("SUPER_FLEX")


# -- 2. playoff structure and divisions ----------------------------------------


def test_playoff_bracket_is_each_leagues_own(recorded_rules):
    a1, b1, a2, b2 = _abab(
        lambda: ps.resolve_playoff_structure(SEASON_A, KEY_A),
        lambda: ps.resolve_playoff_structure(SEASON_B, KEY_B),
    )
    for a in (a1, a2):
        assert (a.teams, a.byes, a.seed_type) == (7, 1, ps.SEED_TYPE_RESEED)  # 7 pads to 8
        assert a.divisions == 3
        assert a.division_rule == ps.DIVISION_RULE_RECORDED
        assert a.rules is not None and a.rules.division_count == 3
        assert not a.division_qualification_unknown
    for b in (b1, b2):
        assert (b.teams, b.byes, b.seed_type) == (6, 2, ps.SEED_TYPE_FIXED)  # 6 pads to 8
        assert b.divisions is None
        assert b.division_rule == ps.DIVISION_RULE_NONE
        assert b.rules is None
        assert not b.divisions_in_play
    assert a1.to_dict() == a2.to_dict()
    assert b1.to_dict() == b2.to_dict()


def test_unrecorded_league_never_inherits_another_leagues_division_rule(recorded_rules):
    # Same host settings as A (divisions ON), but a key the record does not name.
    other = ps.resolve_playoff_structure(SEASON_A, KEY_UNRECORDED)
    keyless = ps.resolve_playoff_structure(SEASON_A, None)
    recorded = ps.resolve_playoff_structure(SEASON_A, KEY_A)
    again = ps.resolve_playoff_structure(SEASON_A, KEY_UNRECORDED)
    for s in (other, keyless, again):
        assert s.rules is None
        assert s.division_rule == ps.DIVISION_RULE_UNRECORDED
        assert s.division_qualification_unknown
    assert recorded.division_rule == ps.DIVISION_RULE_RECORDED
    # The shipped dynasty_main record must not reach a synthetic key either way.
    assert ps.league_playoff_rules("dynasty_main") is None  # tmp file records fmt_a only


def test_division_assignments_per_league(recorded_rules):
    def owner_of(rid):
        return f"owner{rid}"

    struct_a = ps.resolve_playoff_structure(SEASON_A, KEY_A)
    struct_b = ps.resolve_playoff_structure(SEASON_B, KEY_B)
    struct_x = ps.resolve_playoff_structure(SEASON_A, KEY_UNRECORDED)

    def run():
        return (
            ps.resolve_division_assignments(SEASON_A, struct_a, owner_of),
            ps.resolve_division_assignments(SEASON_B, struct_b, owner_of),
            ps.resolve_division_assignments(SEASON_A, struct_x, owner_of),
        )

    first, second = run(), run()
    for a, b, x in (first, second):
        assert a.available and a.count == 3
        assert a.members() == {
            1: ["owner1", "owner10", "owner4", "owner7"],
            2: ["owner11", "owner2", "owner5", "owner8"],
            3: ["owner12", "owner3", "owner6", "owner9"],
        }
        assert a.names == {1: "East", 2: "West", 3: "North"}
        # No divisions: not applicable -- never "unavailable", never A's three.
        assert (b.state, b.reason, b.count, dict(b.by_owner)) == (
            "not_applicable",
            ps.REASON_NO_DIVISIONS,
            None,
            {},
        )
        # Divisions on but no recorded champion rule: refused with the named reason.
        assert (x.state, x.reason) == ("unavailable", ps.REASON_DIVISION_RULE_UNRECORDED)
        assert not x.by_owner


# -- 3. roster capacity ---------------------------------------------------------


def test_roster_cap_per_league_and_unknown_stays_unknown():
    a1, b1, a2, b2 = _abab(
        lambda: rc.league_roster_limit(KEY_A, SETTINGS_A),
        lambda: rc.league_roster_limit(KEY_B, SETTINGS_B),
    )
    assert (a1, b1, a2, b2) == (58, 30, 58, 30)
    # Unknown is None -- not unlimited, and not a neighbour's 58 or 30.
    assert rc.league_roster_limit(KEY_UNRECORDED, {}) is None
    assert rc.league_roster_limit(KEY_UNRECORDED, {"rosterSize": None}) is None
    assert rc.league_roster_limit(KEY_UNRECORDED, {"rosterSize": 0}) is None
    assert rc.league_taxi_size(KEY_A, SETTINGS_A) == 0 == rc.league_taxi_size(KEY_B, SETTINGS_B)
    assert rc.league_taxi_size(KEY_A, {"taxiSize": 5}) == 5
    assert rc.league_taxi_size(KEY_B, SETTINGS_B) == 0  # A's taxi never leaks


def test_live_slot_list_of_one_league_is_not_read_for_another():
    contract_a = {
        "meta": {"leagueKey": KEY_A},
        "sleeper": {"rosterPositions": ROSTER_POSITIONS_A},
    }
    # A's contract answers A and refuses B.
    assert rc.live_roster_positions(contract_a, KEY_A) == ROSTER_POSITIONS_A
    assert rc.live_roster_positions(contract_a, KEY_B) is None
    reading_a = rc.resolve_roster_limit(contract_a, KEY_A, SETTINGS_A)
    reading_b = rc.resolve_roster_limit(contract_a, KEY_B, SETTINGS_B)
    reading_a2 = rc.resolve_roster_limit(contract_a, KEY_A, SETTINGS_A)
    assert (reading_a.limit, reading_a.live_limit) == (58, len(ROSTER_POSITIONS_A))
    assert reading_a.disagreement is not None  # 58 configured vs 23 live slots
    assert reading_a.disagreement["registryRosterSize"] == 58
    # B applies its own 30, sees no live list, and inherits no disagreement note.
    assert (reading_b.limit, reading_b.live_limit) == (30, None)
    assert reading_b.disagreement is None and reading_b.starter_disagreement is None
    assert reading_a2 == reading_a


# -- 4. FAAB comparability target and gate --------------------------------------


def _target_a():
    return fc.TargetFormat.from_roster_settings(
        SETTINGS_A, league_key=KEY_A, scoring_settings=CARD_A, scoring_evidence="fresh"
    )


def _target_b():
    return fc.TargetFormat.from_roster_settings(
        SETTINGS_B, league_key=KEY_B, scoring_settings=CARD_B, scoring_evidence="fresh"
    )


def test_target_format_is_a_fact_of_each_leagues_own_settings_and_card():
    a1, b1, a2, b2 = _abab(_target_a, _target_b)
    assert a1 == a2 and b1 == b2
    assert (a1.superflex, a1.tep, a1.idp, a1.teams, a1.is_2te) == (True, True, True, 12, False)
    assert (b1.superflex, b1.tep, b1.idp, b1.teams, b1.is_2te) == (False, False, False, 10, False)
    assert (a1.league_key, b1.league_key) == (KEY_A, KEY_B)
    assert a1.tep_level is None and b1.tep_level is None  # severity stays dormant


def test_tep_is_proved_by_fresh_card_never_by_label_or_stale_card():
    def tep(card, evidence, settings=SETTINGS_A):
        return fc.TargetFormat.from_roster_settings(
            settings, scoring_settings=card, scoring_evidence=evidence
        ).tep

    # A's premium card proves TEP only while fresh; unproven is None (fails closed).
    assert tep(CARD_A, "fresh") is True
    assert tep(CARD_A, "stale") is None
    assert tep(CARD_A, "missing") is None
    assert tep(None, "fresh") is None
    # Same A roster settings with B's card: B's "no premium" answer, not A's.
    assert tep(CARD_B, "fresh") is False
    # A card that pays every position the same first-down bonus is not a premium.
    flat = {"bonus_fd_te": 1.0, "bonus_fd_wr": 1.0, "bonus_fd_rb": 1.0}
    assert tep(flat, "fresh") is False
    # And B's settings with A's premium card are TEP: the card decides, not the league.
    assert tep(CARD_A, "fresh", SETTINGS_B) is True


def test_comparability_gate_admits_only_leagues_matching_the_target():
    sf_tep_12 = fc.SourceFormat(
        superflex=True,
        tep_level=1,
        is_2te=False,
        teams=12,
        rosters_per_player=1,
        original_budget=100.0,
    )
    qb1_base_10 = fc.SourceFormat(
        superflex=False,
        tep_level=0,
        is_2te=False,
        teams=10,
        rosters_per_player=1,
        original_budget=100.0,
    )
    for _ in range(2):  # A, B, A, B
        a_with_sf = fc.classify(sf_tep_12, _target_a())
        b_with_sf = fc.classify(sf_tep_12, _target_b())
        a_with_qb1 = fc.classify(qb1_base_10, _target_a())
        b_with_qb1 = fc.classify(qb1_base_10, _target_b())
        assert (a_with_sf.excluded, a_with_sf.tier) == (False, fc.TIER_A)
        assert (b_with_qb1.excluded, b_with_qb1.tier) == (False, fc.TIER_A)
        assert b_with_sf.excluded
        assert set(b_with_sf.reasons) == {"superflex_mismatch", "tep_mismatch"}
        # 10 vs 12 teams is within the tolerance of 2, so it is NOT a hard mismatch.
        assert a_with_qb1.excluded
        assert set(a_with_qb1.reasons) == {"superflex_mismatch", "tep_mismatch"}
    # A target that cannot prove its own TEP excludes everything -- never "no premium".
    unproven = fc.TargetFormat.from_roster_settings(
        SETTINGS_B, scoring_settings=CARD_A, scoring_evidence="stale"
    )
    verdict = fc.classify(qb1_base_10, unproven)
    assert verdict.excluded and "target_format_unknown:tep" in verdict.reasons
    assert fc.unprovable_target_fields(unproven) == ("tep",)
    assert fc.unprovable_target_fields(_target_a()) == ()
    assert fc.unprovable_target_fields(_target_b()) == ()


def test_idp_claims_need_idp_evidence_in_every_league():
    # The population gate reads the retained feed, not the target league's IDP flag.
    for _ in range(2):
        assert fc.population_prices_position("LB", any_idp_source=False) is False
        assert fc.population_prices_position("LB", any_idp_source=True) is True
        assert fc.population_prices_position("QB", any_idp_source=False) is True


# -- 5. FAAB need and unknown balance --------------------------------------------


def test_positional_demand_comes_from_each_leagues_own_starters():
    sa, sb = SETTINGS_A["starters"], SETTINGS_B["starters"]
    for _ in range(2):  # A, B, A, B
        # Superflex counts QB demand above the single direct slot; 1QB is exactly 1.
        assert engine.starter_slots_for_position("QB", sa) > 1.0
        assert engine.starter_slots_for_position("QB", sb) == 1.0
        # Defenders: demanded where slots exist, a measured zero where they do not.
        assert engine.starter_slots_for_position("LB", sa) == 2.0
        assert engine.starter_slots_for_position("LB", sb) == 0.0
    # An unconfigured league is UNKNOWN (None): never "starts nobody", never A's lineup.
    assert engine.starter_slots_for_position("LB", None) is None
    anchors = engine.Anchors(v_allin=3000.0, v_repl=1500.0, band=1500.0, starter_slots=20)
    assert engine.classify_need([], "LB", sb, anchors) == "neutral"  # not started: no need
    assert engine.classify_need([], "LB", sa, anchors) == "starterHole"
    assert engine.classify_need([], "LB", None, anchors) == "unknown"


def test_unknown_faab_balance_is_not_borrowed_from_another_league():
    anchors = engine.Anchors(v_allin=3000.0, v_repl=1500.0, band=1500.0, starter_slots=20)
    player = engine.PlayerInput(name="Target", value=3000.0, position="WR")
    league_a = engine.LeagueContext(original_budget=100, league_key=KEY_A, in_season=False)
    league_b = engine.LeagueContext(original_budget=200, league_key=KEY_B, in_season=False)
    team_a = engine.TeamContext(faab_remaining=30, open_roster_spots=1)
    team_b = engine.TeamContext(faab_remaining=None, open_roster_spots=1)

    def ceil(league, team):
        return engine.team_ceiling(player, anchors, league, team)

    a1, b1, a2, b2 = _abab(lambda: ceil(league_a, team_a), lambda: ceil(league_b, team_b))
    assert a1 == a2 and b1 == b2
    # A: worth up to its whole $100 budget, but capped by its known $30 balance.
    assert (a1["budget"], a1["remaining"], a1["teamCeilingDollars"]) == (100, 30, 30.0)
    # B: its own $200 original budget; the $30 from A never caps it.
    assert b1["budget"] == 200
    assert b1["remaining"] != 30
    assert b1["teamCeilingDollars"] > 30.0
    # Objective worth is a function of format and player, not of either team's balance.
    assert a1["objectivePct"] == b1["objectivePct"]

    # A rival with no visible balance is excluded from the clearing math.
    rival_known = engine.RivalTeam(owner_id="r1", faab_remaining=50)
    rival_unknown = engine.RivalTeam(owner_id="r2", faab_remaining=None)
    result_a = engine.recommend(
        player, league_a, team_a, anchors=anchors, rivals=[rival_known, rival_unknown]
    )
    result_b = engine.recommend(player, league_b, team_b, anchors=anchors, rivals=[rival_unknown])
    assert "1 rivals with visible balances" in str(result_a)
    assert "no rival balances available" in str(result_b)
    assert "1 rivals with visible balances" not in str(result_b)


# -- 6. waiver add-pool position gate --------------------------------------------

POSITIONS = {"QB", "RB", "WR", "TE", "DL", "LB", "DB"}


def _exclusion(row, slots):
    return waiver.waiver_candidate_exclusion(
        row, positions=POSITIONS, rookies_eligible=True, starter_slots=slots
    )


def test_idp_candidates_refused_only_in_the_offense_only_league():
    slots_a = lineup.resolve_starter_slots(roster_positions=ROSTER_POSITIONS_A)[0]
    slots_b = lineup.resolve_starter_slots(roster_positions=ROSTER_POSITIONS_B)[0]
    base = {"rankDerivedValue": 6000, "sourceCount": 5}
    lb = {**base, "position": "LB", "name": "Linebacker"}
    qb = {**base, "position": "QB", "name": "Quarterback"}
    for _ in range(2):  # A, B, A, B
        assert _exclusion(lb, slots_a) is None
        assert _exclusion(lb, slots_b) == "position_not_started"
        # Offense is startable in both leagues.
        assert _exclusion(qb, slots_a) is None
        assert _exclusion(qb, slots_b) is None
    # Unknown lineup refuses nothing for position: unknown is not "offense only".
    assert _exclusion(lb, None) is None
    assert _exclusion(lb, []) is None
