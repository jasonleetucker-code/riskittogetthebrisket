"""Expand standings + the 2026 Waiver King eligibility override, end to end.

Owner directive 2026-09-26.  Built through the real ``awards.build_section``
on a synthetic four-team league whose waiver metric is, by construction,

    Joel 150 · Blaine 140 · Manager C 130 · Manager D 120

Pinned:
  * winner fall-through — the 2026 Waiver King is C, never Joel/Blaine and
    never "no winner";
  * metric preservation — Joel/Blaine's waiver metric is unchanged and still
    published, with metric rank 1/2 and an explicit ineligible label;
  * season scoping — the same data as 2027 crowns Joel; 2026 viewed from a
    later current season still crowns C;
  * award isolation — every other award, race and finalist list is
    byte-identical with the rule switched off;
  * standings — ≤ 12 rows, canonical order, entity per award, current season
    only, no zero padding.
"""

from __future__ import annotations

import copy
import json

import pytest

from src.public_league import award_eligibility, awards
from src.public_league.identity import build_manager_registry
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot

JOEL = "712035316776669184"
BLAINE = "1303549304882892800"
C = "owner-c"
D = "owner-d"
OWNERS = [JOEL, BLAINE, C, D]
NAMES = {JOEL: "Joel", BLAINE: "Blaine", C: "Cara", D: "Dev"}
LEAGUE_2026 = "1312006700437352448"

# Waiver pickup points per week (weeks 2 and 3 → season metric = 2 × this).
WAIVER_PER_WEEK = {JOEL: 75.0, BLAINE: 70.0, C: 65.0, D: 60.0}
# Base starter points per week: Joel also leads the team awards, so an
# over-broad rule would visibly strip him of them.
BASE = {JOEL: 120.0, BLAINE: 90.0, C: 80.0, D: 70.0}


def _users():
    return [{"user_id": o, "display_name": NAMES[o], "metadata": {}} for o in OWNERS]


def _rosters():
    return [
        {
            "roster_id": i,
            "owner_id": o,
            "players": [f"base_{i}", f"wav_{i}"],
            "settings": {"wins": 0, "losses": 0, "fpts": 0},
        }
        for i, o in enumerate(OWNERS, start=1)
    ]


def _week(week: int) -> list[dict]:
    out = []
    for i, o in enumerate(OWNERS, start=1):
        pts = {f"base_{i}": BASE[o]}
        starters = [f"base_{i}"]
        if week >= 2:
            pts[f"wav_{i}"] = WAIVER_PER_WEEK[o]
            starters.append(f"wav_{i}")
        out.append(
            {
                "matchup_id": 1 if i <= 2 else 2,
                "roster_id": i,
                "points": sum(pts.values()),
                "starters": starters,
                "players_points": pts,
            }
        )
    return out


def _season(label: str, league_id: str, *, status: str) -> SeasonSnapshot:
    league = {
        "league_id": league_id,
        "season": label,
        "status": status,
        "total_rosters": 4,
        "settings": {"playoff_week_start": 15, "last_scored_leg": 3},
    }
    return SeasonSnapshot(
        season=label,
        league_id=league_id,
        league=league,
        users=_users(),
        rosters=_rosters(),
        matchups_by_week={w: _week(w) for w in (1, 2, 3)},
        transactions_by_week={
            1: [
                {
                    "transaction_id": f"add-{label}-{i}",
                    "type": "free_agent",
                    "status": "complete",
                    "created": 100 + i,
                    "roster_ids": [i],
                    "adds": {f"wav_{i}": i},
                    "drops": None,
                }
                for i in range(1, 5)
            ]
        },
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )


def _snapshot(*seasons: SeasonSnapshot) -> PublicLeagueSnapshot:
    snap = PublicLeagueSnapshot(
        root_league_id=seasons[0].league_id,
        generated_at="2026-10-01T00:00:00Z",
        seasons=list(seasons),
        managers=build_manager_registry(
            [{"league": s.league, "users": s.users, "rosters": s.rosters} for s in seasons]
        ),
    )
    nfl = {}
    for i in range(1, 5):
        nfl[f"base_{i}"] = {"position": "RB", "team": "BUF", "full_name": f"Base {i}"}
        nfl[f"wav_{i}"] = {"position": "WR", "team": "KC", "full_name": f"Waiver {i}"}
    snap.nfl_players = nfl
    return snap


def _live_2026():
    return _snapshot(_season("2026", LEAGUE_2026, status="in_season"))


def _award(section, season, key):
    row = next(r for r in section["bySeason"] if r["season"] == season)
    return next((a for a in row["awards"] if a["key"] == key), None)


def _race(section, key):
    return next(r for r in section["awardRaces"] if r["key"] == key)


@pytest.fixture
def no_rules(monkeypatch):
    def _off():
        monkeypatch.setattr(award_eligibility, "load_overrides", lambda path=None: ())

    return _off


# ── the metric, by construction ─────────────────────────────────────────


def test_the_raw_metric_ranks_joel_blaine_c_d():
    snap = _live_2026()
    rows = awards._waiver_king_scores(snap, snap.seasons[0])
    assert [(r["ownerId"], r["pointsGained"]) for r in rows] == [
        (JOEL, 150.0),
        (BLAINE, 140.0),
        (C, 130.0),
        (D, 120.0),
    ]


# ── winner fall-through + metric preservation ───────────────────────────


def test_2026_waiver_king_falls_through_to_the_best_eligible_manager():
    sec = awards.build_section(_live_2026())
    award = _award(sec, "2026", "waiver_king")
    assert award["ownerId"] == C
    assert award["value"]["pointsGained"] == 130.0
    race = _race(sec, "waiver_king")
    assert [x["ownerId"] for x in race["leaders"]] == [C, D]
    assert [x["rank"] for x in race["leaders"]] == [1, 2]


def test_their_real_metric_stays_published_and_labelled():
    race = _race(awards.build_section(_live_2026()), "waiver_king")
    st = race["standings"]
    assert [(r["ownerId"], r["rank"], r["awardRank"], r["eligible"]) for r in st] == [
        (JOEL, 1, None, False),
        (BLAINE, 2, None, False),
        (C, 3, 1, True),
        (D, 4, 2, True),
    ]
    assert st[0]["value"]["pointsGained"] == 150.0
    assert st[1]["value"]["pointsGained"] == 140.0
    for row in st[:2]:
        assert row["ineligibleReason"] == "owner_season_eligibility_override"
        assert row["ineligibleLabel"] == "Ineligible for 2026 award"
    assert "ineligibleLabel" not in st[2]


def test_the_waiver_metric_itself_is_identical_with_and_without_the_rule(no_rules):
    snap = _live_2026()
    before = awards._waiver_king_scores(snap, snap.seasons[0])
    no_rules()
    after = awards._waiver_king_scores(snap, snap.seasons[0])
    assert before == after


# ── season scoping ──────────────────────────────────────────────────────


def test_2027_starts_with_no_rule():
    snap = _snapshot(_season("2027", "1400000000000000001", status="in_season"))
    sec = awards.build_section(snap)
    assert _award(sec, "2027", "waiver_king")["ownerId"] == JOEL
    st = _race(sec, "waiver_king")["standings"]
    assert all(r["eligible"] for r in st)
    assert st[0]["ownerId"] == JOEL and st[0]["awardRank"] == 1


def test_historical_2026_keeps_its_rule_when_viewed_from_a_later_season():
    snap = _snapshot(
        _season("2027", "1400000000000000001", status="in_season"),
        _season("2026", LEAGUE_2026, status="complete"),
    )
    sec = awards.build_section(snap)
    assert _award(sec, "2026", "waiver_king")["ownerId"] == C
    finalists_2026 = next(r for r in sec["bySeason"] if r["season"] == "2026")["finalists"]
    assert JOEL not in [f["ownerId"] for f in finalists_2026["waiver_king"]]
    assert BLAINE not in [f["ownerId"] for f in finalists_2026["waiver_king"]]
    assert _award(sec, "2027", "waiver_king")["ownerId"] == JOEL


# ── award isolation ─────────────────────────────────────────────────────


def _strip_waiver(section):
    out = copy.deepcopy(section)
    out["awardRaces"] = [r for r in out["awardRaces"] if r["key"] != "waiver_king"]
    for row in out["bySeason"]:
        row["awards"] = [a for a in row["awards"] if a["key"] != "waiver_king"]
        row["finalists"].pop("waiver_king", None)
    out.pop("hottestRace", None)
    return out


def test_every_other_award_is_byte_identical_without_the_rule(no_rules):
    with_rule = awards.build_section(_live_2026())
    no_rules()
    without = awards.build_section(_live_2026())
    assert json.dumps(_strip_waiver(with_rule), sort_keys=True) == json.dumps(
        _strip_waiver(without), sort_keys=True
    )
    # And the rule really changed Waiver King — the comparison is not vacuous.
    assert _award(without, "2026", "waiver_king")["ownerId"] == JOEL


def test_joel_still_wins_what_he_leads():
    sec = awards.build_section(_live_2026())
    for key in ("top_offense", "points_king", "highest_single_week"):
        assert _award(sec, "2026", key)["ownerId"] == JOEL, key
    for key in ("top_offense", "weekly_hammer"):
        race = _race(sec, key)
        assert race["leaders"][0]["ownerId"] == JOEL, key
        assert all(r["eligible"] for r in race["standings"]), key


# ── standings shape ─────────────────────────────────────────────────────


def test_standings_follow_the_race_order_and_entity():
    sec = awards.build_section(_live_2026())
    offense = _race(sec, "top_offense")
    assert offense["standingsEntity"] == "team"
    assert [r["ownerId"] for r in offense["standings"]] == [JOEL, BLAINE, C, D]
    assert offense["standingsTotal"] == 4
    assert [r["teamName"] for r in offense["standings"]]  # team identity travels
    for key in ("top_rb", "top_wr", "league_mvp"):
        race = next((r for r in sec["awardRaces"] if r["key"] == key), None)
        if race is None:
            continue
        assert race["standingsEntity"] == "player"
        assert all(r["value"]["playerId"] for r in race["standings"])
        assert race["leaders"] == [
            {k: r[k] for k in ("rank", "ownerId", "displayName", "value")}
            for r in race["standings"][: len(race["leaders"])]
        ]


def test_event_awards_rank_team_weeks_without_padding():
    sec = awards.build_section(_live_2026())
    high = _award(sec, "2026", "highest_single_week")
    assert high["standingsEntity"] == "event"
    pts = [r["value"]["points"] for r in high["standings"]]
    assert pts == sorted(pts, reverse=True)
    assert len(high["standings"]) == min(12, high["standingsTotal"]) == 12
    assert high["standings"][0]["detail"].startswith("Week ")
    low = _award(sec, "2026", "lowest_single_week")
    assert [r["value"]["points"] for r in low["standings"]] == sorted(
        r["value"]["points"] for r in low["standings"]
    )


def test_no_row_is_ever_padded_past_the_qualifying_pool():
    sec = awards.build_section(_live_2026())
    for race in sec["awardRaces"]:
        st = race.get("standings")
        if st is None:
            continue
        assert len(st) == min(awards.STANDINGS_LIMIT, race["standingsTotal"]), race["key"]


def test_ties_share_a_rank_rather_than_inventing_one():
    sec = awards.build_section(_live_2026())
    hammer = _race(sec, "weekly_hammer")["standings"]
    zero = [r for r in hammer if r["value"]["highScoreFinishes"] == 0]
    # Every non-leader has 0 finishes and different highest weeks, so they
    # are NOT tied (the published measurement differs) ...
    assert not any(r.get("tied") for r in zero)
    # ... and a genuine tie (identical measurement) shares the rank.
    rows = [{"ownerId": o, "x": 1} for o in (C, D)]
    snap = _live_2026()
    out = awards._standings(
        snap, snap.seasons[0], "k", rows, lambda r: {"x": r["x"]}, entity="manager"
    )["standings"]
    assert [(r["rank"], r.get("tied", False), r["awardRank"]) for r in out] == [
        (1, False, 1),
        (1, True, 1),
    ]


def test_history_seasons_carry_no_standings():
    snap = _snapshot(
        _season("2027", "1400000000000000001", status="in_season"),
        _season("2026", LEAGUE_2026, status="complete"),
    )
    sec = awards.build_section(snap)
    past = next(r for r in sec["bySeason"] if r["season"] == "2026")
    assert not any("standings" in a for a in past["awards"])
    assert all(
        "standings" not in f for fl in past["finalists"].values() for f in fl
    )  # finalists stay the concise leaders


# ── OPOY / DPOY terminology (owner clarification 2026-09-26) ───────────


def test_offensive_and_defensive_awards_are_player_of_the_year_not_mvp():
    """Presentation only: keys, formulas and rankings are unchanged; League
    MVP keeps its name.  The two awards have different eligibility semantics
    from League MVP, and calling all three "MVP" hid that."""
    sec = awards.build_section(_live_2026())
    labels = {r["key"]: r["label"] for r in sec["awardRaces"]}
    assert labels["off_mvp"] == "Offensive Player of the Year Race"
    assert labels["league_mvp"] == "League MVP Race"
    season_labels = {a["key"]: a["label"] for a in sec["bySeason"][0]["awards"]}
    assert season_labels.get("off_mvp", "Offensive Player of the Year") == (
        "Offensive Player of the Year"
    )
    assert "MVP" not in awards.AWARD_DESCRIPTIONS["off_mvp"]
    assert "MVP" not in awards.AWARD_DESCRIPTIONS["def_mvp"]
    body = json.dumps(sec)
    assert "Offensive MVP" not in body and "Defensive MVP" not in body
    # Same rows as League MVP's VORP board: the rename moved no number.
    race = next(r for r in sec["awardRaces"] if r["key"] == "off_mvp")
    snap = _live_2026()
    rows = awards._season_row_sets(snap, snap.seasons[0])["off_mvp"]
    assert [x["value"]["playerId"] for x in race["standings"]] == [
        r["playerId"] for r in rows if r.get("vorp", 0) > 0
    ][: awards.STANDINGS_LIMIT]
