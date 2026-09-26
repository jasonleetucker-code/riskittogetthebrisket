"""League MVP team-success gate (owner decision 2026-09-26).

League MVP = elite player performance on a SUCCESSFUL fantasy team: the
credited franchise must be in the championship playoff field AND above .500.
Live seasons read the field off the canonical standings order and the
league's own bracket size; finalized seasons read the ACTUAL bracket.
OPOY / DPOY / ROY / positional awards do NOT inherit the gate.

One synthetic six-team league, three regular-season weeks. Each roster
starts a QB (15/wk), an RB and a DL; the RB/DL scores are chosen per test so
the VORP board's order is known. Every roster carries a realistic bench so
replacement levels are full bands (no thin-position exclusion interferes).
"""

from __future__ import annotations

import json

import pytest

from src.public_league import awards
from src.public_league.identity import build_manager_registry
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot
from tests.public_league.fixtures import REAL_LEAGUE_BENCH_DEPTH, add_rostered_bench

OWNERS = [f"owner-{c}" for c in "ABCDEF"]
USERS = [{"user_id": o, "display_name": o[-1], "metadata": {}} for o in OWNERS]
ROSTER_POSITIONS = ["QB", "RB", "DL", "BN", "BN"]

# Default star scoring: the BEST offensive player (rb1) and the best
# defensive player (dl6) sit on teams that will fail the gate.
RB_PPG = {1: 40.0, 2: 38.0, 3: 25.0, 4: 30.0, 5: 20.0, 6: 36.0}
DL_PPG = {1: 6.0, 2: 7.0, 3: 8.0, 4: 9.0, 5: 10.0, 6: 24.0}

# Standings: C 4-0, D 3-1, E 3-1, B 2-2, A 1-3, F 0-4 (D above E on PF).
RECORDS = {1: (1, 3), 2: (2, 2), 3: (4, 0), 4: (3, 1), 5: (3, 1), 6: (0, 4)}
PF = {1: 300, 2: 320, 3: 330, 4: 340, 5: 310, 6: 290}


def _nfl():
    out = {}
    for i in range(1, 7):
        out[f"qb{i}"] = {"full_name": f"QB {i}", "position": "QB", "team": "BUF", "years_exp": 5}
        out[f"rb{i}"] = {"full_name": f"RB {i}", "position": "RB", "team": "KC", "years_exp": 5}
        out[f"dl{i}"] = {"full_name": f"DL {i}", "position": "DL", "team": "DAL", "years_exp": 5}
    return out


def _week(rb_ppg, dl_ppg):
    out = []
    for i in range(1, 7):
        starters = {f"qb{i}": 15.0, f"rb{i}": rb_ppg[i], f"dl{i}": dl_ppg[i]}
        out.append(
            {
                "matchup_id": (i + 1) // 2,
                "roster_id": i,
                "points": round(sum(starters.values()), 2),
                "starters": list(starters),
                "players_points": dict(starters),
            }
        )
    return out


def build(
    *,
    records=RECORDS,
    playoff_teams: int | None = 3,
    status: str = "in_season",
    bracket_rids: list[int] | None = None,
    rb_ppg=RB_PPG,
    dl_ppg=DL_PPG,
) -> dict:
    rosters = [
        {
            "roster_id": i,
            "owner_id": o,
            "players": [f"qb{i}", f"rb{i}", f"dl{i}"],
            "settings": {"wins": records[i][0], "losses": records[i][1], "fpts": PF[i]},
        }
        for i, o in enumerate(OWNERS, start=1)
    ]
    settings = {"playoff_week_start": 15, "last_scored_leg": 3}
    if playoff_teams is not None:
        settings["playoff_teams"] = playoff_teams
    league = {
        "league_id": "GATE",
        "season": "2026",
        "season_type": "regular",
        "status": status,
        "total_rosters": 6,
        "roster_positions": ROSTER_POSITIONS,
        "settings": settings,
    }
    bracket = []
    if bracket_rids:
        # One first-round game per pair of qualified rosters; membership is
        # what the gate reads, the scores do not matter.
        pairs = list(zip(bracket_rids[::2], bracket_rids[1::2]))
        bracket = [{"r": 1, "m": n, "t1": a, "t2": b} for n, (a, b) in enumerate(pairs, 1)]
        if len(bracket_rids) % 2:
            bracket.append({"r": 2, "m": len(pairs) + 1, "t1": bracket_rids[-1], "t2": None})
    season = SeasonSnapshot(
        season="2026",
        league_id="GATE",
        league=league,
        users=USERS,
        rosters=rosters,
        matchups_by_week={w: _week(rb_ppg, dl_ppg) for w in (1, 2, 3)},
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=bracket,
        losers_bracket=[],
    )
    snap = PublicLeagueSnapshot(
        root_league_id="GATE",
        generated_at="2026-10-01T00:00:00Z",
        seasons=[season],
        managers=build_manager_registry([{"league": league, "users": USERS, "rosters": rosters}]),
        nfl_players=_nfl(),
    )
    add_rostered_bench(snap, season, depth=dict(REAL_LEAGUE_BENCH_DEPTH))
    return awards.build_section(snap)


def race(sec, key):
    return next((r for r in sec["awardRaces"] if r["key"] == key), None)


def award(sec, key):
    return next((a for a in sec["bySeason"][0]["awards"] if a["key"] == key), None)


def pids(rows):
    return [r["value"]["playerId"] for r in rows]


def test_the_fixture_puts_the_best_players_on_failing_teams():
    """Guard: without the gate, rb1 (1-3 team) leads OPOY and dl6 (0-4)
    leads DPOY — so the tests below are discriminating."""
    sec = build()
    assert pids(race(sec, "off_mvp")["leaders"])[0] == "rb1"
    assert pids(race(sec, "def_mvp")["leaders"])[0] == "dl6"


# ── Live race ────────────────────────────────────────────────────────


def test_live_race_admits_only_in_field_winning_teams():
    sec = build()  # field = top 3 = C, D, E
    r = race(sec, "league_mvp")
    owners = {s["ownerId"] for s in r["standings"]}
    assert owners <= {"owner-C", "owner-D", "owner-E"}
    assert r["eligibility"]["verified"] is True
    assert r["eligibility"]["basis"] == "current_standings"
    assert r["eligibility"]["playoffTeams"] == 3


@pytest.mark.parametrize(
    "pid,why",
    [
        ("rb1", "team_outside_playoff_field"),  # losing (1-3) and out of the field
        ("rb6", "team_outside_playoff_field"),  # 0-4
        ("rb2", "team_outside_playoff_field"),  # .500 and 4th
    ],
)
def test_top_vorp_players_on_failing_teams_are_outside_the_race(pid, why):
    sec = build()
    r = race(sec, "league_mvp")
    assert pid not in pids(r["standings"])
    outside = {o["playerId"]: o["reason"] for o in r["eligibility"]["outsideTheRace"]}
    assert outside[pid] == why


def test_a_500_team_inside_the_field_is_still_ineligible():
    sec = build(playoff_teams=4)  # field = C, D, E, B — B is exactly .500
    r = race(sec, "league_mvp")
    assert "rb2" not in pids(r["standings"])
    reasons = {o["playerId"]: o["reason"] for o in r["eligibility"]["outsideTheRace"]}
    assert reasons.get("rb2") == "team_record_not_above_500"


def test_a_winning_team_outside_the_field_is_ineligible():
    sec = build(playoff_teams=2)  # field = C, D; E is 3-1 but 3rd
    r = race(sec, "league_mvp")
    assert not {s["ownerId"] for s in r["standings"]} & {"owner-E"}


def test_the_best_eligible_candidate_leads_and_wins():
    sec = build()
    r = race(sec, "league_mvp")
    leader = r["leaders"][0]
    # rb4 (3-1, in the field, VORP 84) — not rb1 (1-3, VORP 114).
    assert leader["value"]["playerId"] == "rb4"
    assert leader["ownerId"] in {"owner-C", "owner-D", "owner-E"}
    win = award(sec, "league_mvp")
    assert win["value"]["playerId"] == leader["value"]["playerId"]
    assert win["ownerId"] == leader["ownerId"]
    # Nobody on an eligible team out-scores the leader on VORP.
    assert leader["value"]["vorp"] == max(s["value"]["vorp"] for s in r["standings"])


# ── Finalized season ─────────────────────────────────────────────────


def test_finalized_season_uses_the_actual_bracket_not_the_standings_order():
    # D (3-1, 2nd in the standings) did NOT make the real bracket; B (.500)
    # did. Final eligibility = actually qualified AND above .500 => C, E.
    sec = build(status="complete", bracket_rids=[3, 5, 2])
    elig = award(sec, "league_mvp")["eligibility"]
    assert elig["basis"] == "final_bracket"
    finalists = race_or_finalists(sec)
    owners = {f["ownerId"] for f in finalists}
    assert owners <= {"owner-C", "owner-E"}
    assert "owner-D" not in owners and "owner-B" not in owners


def race_or_finalists(sec):
    return sec["bySeason"][0]["finalists"]["league_mvp"]


def test_finalized_ineligible_top_vorp_player_does_not_win_the_next_eligible_does():
    sec = build(status="complete", bracket_rids=[3, 5, 2])
    win = award(sec, "league_mvp")
    assert win["value"]["playerId"] not in {"rb1", "rb2", "rb4", "rb6", "dl6"}
    assert win["ownerId"] in {"owner-C", "owner-E"}


def test_a_complete_season_without_a_bracket_is_unverified_not_open():
    sec = build(status="complete", bracket_rids=None)
    win = award(sec, "league_mvp")
    assert win["awaitingEvidence"] is True
    assert win["awaitingReason"] == awards.LEAGUE_MVP_ELIGIBILITY_UNVERIFIED
    assert win["ownerId"] == ""


# ── Honest empty states ──────────────────────────────────────────────


def test_unknown_playoff_field_is_unverified_never_everyone():
    sec = build(playoff_teams=None)
    r = race(sec, "league_mvp")
    assert r["awaitingEvidence"] is True
    assert r["awaitingReason"] == awards.LEAGUE_MVP_ELIGIBILITY_UNVERIFIED
    assert r["leaders"] == [] and "standings" not in r


def test_no_eligible_team_reports_no_eligible_candidate():
    everyone_even = {i: (2, 2) for i in range(1, 7)}
    sec = build(records=everyone_even)
    r = race(sec, "league_mvp")
    assert r["awaitingReason"] == "no_eligible_mvp_candidate"
    assert award(sec, "league_mvp")["awaitingReason"] == "no_eligible_mvp_candidate"


# ── OPOY / DPOY / ROY / positional independence ──────────────────────


def test_opoy_leader_on_a_losing_team_still_leads():
    sec = build()
    assert pids(race(sec, "off_mvp")["leaders"])[0] == "rb1"  # 1-3 team
    assert award(sec, "off_mvp")["value"]["playerId"] == "rb1"


def test_dpoy_leader_on_a_non_playoff_team_still_leads():
    sec = build()
    assert pids(race(sec, "def_mvp")["leaders"])[0] == "dl6"  # 0-4 team
    assert award(sec, "def_mvp")["value"]["playerId"] == "dl6"


def test_no_other_award_or_race_reads_the_gate(monkeypatch):
    """Everything except League MVP is byte-identical whether the gate
    admits every franchise or the real one."""
    gated = build()

    def open_gate(snapshot, season):
        teams = {o: {"eligible": True, "reason": None} for o in OWNERS}
        return {
            "rule": "playoff_field_and_winning_record",
            "verified": True,
            "basis": "test_open",
            "playoffTeams": 6,
            "teams": teams,
        }

    monkeypatch.setattr(awards, "_league_mvp_gate", open_gate)
    ungated = build()

    def strip(sec):
        out = json.loads(json.dumps(sec))
        out["awardRaces"] = [r for r in out["awardRaces"] if r["key"] != "league_mvp"]
        for row in out["bySeason"]:
            row["awards"] = [a for a in row["awards"] if a["key"] != "league_mvp"]
            row["finalists"].pop("league_mvp", None)
        out.pop("hottestRace", None)
        return out

    assert json.dumps(strip(gated), sort_keys=True) == json.dumps(strip(ungated), sort_keys=True)
    # And the gate really changed League MVP (the comparison is not vacuous).
    assert pids(race(ungated, "league_mvp")["standings"])[0] == "rb1"
    assert "rb1" not in pids(race(gated, "league_mvp")["standings"])


# ── Labels / copy ────────────────────────────────────────────────────


def test_labels_and_copy():
    sec = build()
    assert race(sec, "league_mvp")["label"] == "League MVP Race"
    assert award(sec, "league_mvp")["label"] == "League MVP"
    assert race(sec, "off_mvp")["label"] == "Offensive Player of the Year Race"
    assert race(sec, "def_mvp")["label"] == "Defensive Player of the Year Race"
    assert "playoff position" in awards.AWARD_DESCRIPTIONS["league_mvp"]
    for key in ("off_mvp", "def_mvp", "off_roy", "def_roy", "top_qb"):
        assert "playoff" not in awards.AWARD_DESCRIPTIONS[key]
        assert ".500" not in awards.AWARD_DESCRIPTIONS[key]
