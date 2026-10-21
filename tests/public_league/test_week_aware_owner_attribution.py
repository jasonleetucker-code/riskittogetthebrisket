"""Week-aware owner attribution across the public league sections.

The committed hand-offs (``config/leagues/roster_ownership_changes.json``,
read only through ``src/public_league/ownership.py``):

* dynasty_main roster 11 — Joel (``jstuedle``) -> John (``jnesselhauf``),
  effective week 6;
* dynasty_main roster 12 — Blaine (``ughb``) -> schoeppeya, effective week 7.

Sleeper reports only a roster's CURRENT owner, so every section that resolved
a matchup's owner without its week credited the departed manager's weeks to
his successor: Joel's weeks 1-5 showed under John and Blaine's weeks 1-6 under
schoeppeya — single-week highs, margins, streaks, rivalry series, luck rows,
weekly recaps, and the team name on a departed manager's trade side.

These tests run the real section builders over a synthetic two-season
snapshot against the COMMITTED config (no monkeypatched hand-off), so both
records are exercised.  The shape: 2026 regular-season weeks 1-8, roster 11
plays roster 1 and roster 12 plays roster 2 every week; roster 11 wins weeks
1-5 and loses 6-8, roster 12 loses weeks 1-6 and wins 7-8.  A 2025 season in a
different league id puts other managers on rosters 11/12 and must not move.
"""

from __future__ import annotations

import pytest

from src.public_league import (
    activity,
    luck,
    metrics,
    records,
    rivalries,
    streaks,
    superlatives,
    weekly,
    weekly_recap,
)
from src.public_league.identity import build_manager_registry
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot

LEAGUE = "1312006700437352448"  # dynasty_main 2026, the league both records name
PREV = "PREV-2025-LEAGUE"  # an earlier season: a different Sleeper league id

JOEL = "712035316776669184"
JOHN = "735693375101108224"
BLAINE = "1303549304882892800"
NEW = "1393410658032177152"  # schoeppeya
JASON = "468418790212759552"
OPP2 = "900000000000000002"
OLD11 = "900000000000000011"  # roster 11's 2025 owner
OLD12 = "900000000000000012"  # roster 12's 2025 owner

JOHN_TEAM = "John Current Team"
NEW_TEAM = "Schoeppeya Current Team"

WEEKS_2026 = range(1, 9)
WEEKS_2025 = range(1, 4)


def expected_owner(rid: int, week: int) -> str:
    """Ground truth, written out by hand — never computed by the code under test."""
    if rid == 11:
        return JOEL if week < 6 else JOHN
    if rid == 12:
        return BLAINE if week < 7 else NEW
    return {1: JASON, 2: OPP2}[rid]


def _points_2026(rid: int, week: int) -> float:
    if rid == 11:
        # Wins weeks 1-5 (week 5 is the season's single-week high), loses 6-8.
        return {5: 500.0}.get(week, 300.0) if week < 6 else 200.0
    if rid == 1:
        return 250.0
    if rid == 12:
        # Loses weeks 1-6 (week 6 is the season's single-week low), wins 7-8.
        if week < 7:
            return 100.0 if week == 6 else 210.0
        return 480.0 if week == 7 else 400.0
    return 260.0  # roster 2


def _entry(rid: int, matchup_id: int, points: float) -> dict:
    return {
        "roster_id": rid,
        "matchup_id": matchup_id,
        "points": points,
        "starters": [],
        "players_points": {},
    }


def _user(uid: str, display: str, team: str) -> dict:
    return {"user_id": uid, "display_name": display, "metadata": {"team_name": team}}


def _roster(rid: int, owner: str) -> dict:
    return {"roster_id": rid, "owner_id": owner, "players": [], "settings": {}}


def _trade(leg: int, tx_id: str) -> dict:
    return {
        "transaction_id": tx_id,
        "type": "trade",
        "status": "complete",
        "leg": leg,
        "created": 1_760_000_000_000 + leg,
        "roster_ids": [11, 12],
        "adds": {f"p{tx_id}a": 11, f"p{tx_id}b": 12},
        "drops": {f"p{tx_id}a": 12, f"p{tx_id}b": 11},
        "draft_picks": [],
    }


def _season_2026() -> SeasonSnapshot:
    matchups = {
        wk: [
            _entry(11, 1, _points_2026(11, wk)),
            _entry(1, 1, _points_2026(1, wk)),
            _entry(12, 2, _points_2026(12, wk)),
            _entry(2, 2, _points_2026(2, wk)),
        ]
        for wk in WEEKS_2026
    }
    return SeasonSnapshot(
        season="2026",
        league_id=LEAGUE,
        league={
            "league_id": LEAGUE,
            "season": "2026",
            # ``complete`` makes every listed week final (metrics.final_weeks);
            # attribution, not the live-week gate, is under test here.
            "status": "complete",
            "total_rosters": 4,
            "settings": {"playoff_week_start": 15},
        },
        users=[
            _user(JASON, "JasonLeeTucker", "Jason Team"),
            _user(OPP2, "opp2", "Opp Two Team"),
            _user(JOHN, "jnesselhauf", JOHN_TEAM),
            _user(NEW, "schoeppeya", NEW_TEAM),
        ],
        rosters=[_roster(1, JASON), _roster(2, OPP2), _roster(11, JOHN), _roster(12, NEW)],
        matchups_by_week=matchups,
        # Week 3: both departed managers trade with each other; week 7: both
        # successors do.
        transactions_by_week={3: [_trade(3, "t3")], 7: [_trade(7, "t7")]},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )


def _season_2025() -> SeasonSnapshot:
    matchups = {
        wk: [
            _entry(11, 1, 300.0),
            _entry(1, 1, 250.0),
            _entry(12, 2, 210.0),
            _entry(2, 2, 260.0),
        ]
        for wk in WEEKS_2025
    }
    return SeasonSnapshot(
        season="2025",
        league_id=PREV,
        league={
            "league_id": PREV,
            "season": "2025",
            "status": "complete",
            "total_rosters": 4,
            "settings": {"playoff_week_start": 15},
        },
        users=[
            _user(JASON, "JasonLeeTucker", "Jason Team"),
            _user(OPP2, "opp2", "Opp Two Team"),
            _user(OLD11, "old11", "Old Eleven"),
            _user(OLD12, "old12", "Old Twelve"),
        ],
        rosters=[_roster(1, JASON), _roster(2, OPP2), _roster(11, OLD11), _roster(12, OLD12)],
        matchups_by_week=matchups,
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )


def _snapshot() -> PublicLeagueSnapshot:
    seasons = [_season_2026(), _season_2025()]
    registry = build_manager_registry(
        [{"league": s.league, "users": s.users, "rosters": s.rosters} for s in seasons]
    )
    return PublicLeagueSnapshot(
        root_league_id=LEAGUE,
        generated_at="2026-10-20T00:00:00+00:00",
        seasons=seasons,
        managers=registry,
    )


@pytest.fixture(scope="module")
def snap() -> PublicLeagueSnapshot:
    return _snapshot()


def _league_for(season: str) -> str:
    return LEAGUE if season == "2026" else PREV


def _expected_for(season: str, rid: int, week: int) -> str:
    if season == "2025":
        return {11: OLD11, 12: OLD12, 1: JASON, 2: OPP2}[rid]
    return expected_owner(rid, week)


# ── the owner and its fallbacks ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("rid", "week", "owner"),
    [
        (11, 5, JOEL),
        (11, 6, JOHN),
        (12, 6, BLAINE),
        (12, 7, NEW),
        (11, None, JOHN),  # no week: the current owner, as ownership.py defines
        (12, None, NEW),
    ],
)
def test_resolve_owner_and_team_name_follow_the_week(snap, rid, week, owner):
    assert metrics.resolve_owner(snap.managers, LEAGUE, rid, week) == owner
    name = metrics.team_name(snap, LEAGUE, rid, week)
    current = {11: JOHN_TEAM, 12: NEW_TEAM}[rid]
    if owner in (JOHN, NEW):
        assert name == current
    else:
        # The outgoing manager's own alias for that league-season, supplied by
        # the same owner (identity.register_handed_off_owners).
        assert name == {JOEL: "jstuedle", BLAINE: "ughb"}[owner]


def test_an_earlier_season_is_never_reattributed(snap):
    for week in WEEKS_2025:
        assert metrics.resolve_owner(snap.managers, PREV, 11, week) == OLD11
        assert metrics.resolve_owner(snap.managers, PREV, 12, week) == OLD12
        assert metrics.team_name(snap, PREV, 11, week) == "Old Eleven"


# ── weekly ──────────────────────────────────────────────────────────────


def test_weekly_matchups_and_highlights_are_the_weeks_managers(snap):
    section = weekly.build_section(snap)
    seen = 0
    for wk in section["weeks"]:
        for m in wk["matchups"]:
            for side in (m["home"], m["away"]):
                assert side["ownerId"] == _expected_for(wk["season"], side["rosterId"], wk["week"])
                seen += 1
        for key in ("highestScorer", "lowestScorer"):
            side = wk["highlights"][key]
            assert side["ownerId"] == _expected_for(wk["season"], side["rosterId"], wk["week"])
    assert seen == 4 * (len(WEEKS_2026) + len(WEEKS_2025))
    by_key = {(w["season"], w["week"]): w for w in section["weeks"]}
    assert by_key[("2026", 5)]["highlights"]["highestScorer"]["ownerId"] == JOEL
    assert by_key[("2026", 5)]["highlights"]["highestScorer"]["teamName"] == "jstuedle"
    assert by_key[("2026", 6)]["highlights"]["lowestScorer"]["ownerId"] == BLAINE
    assert by_key[("2026", 7)]["highlights"]["highestScorer"]["ownerId"] == NEW


def test_pre_week_standings_carry_the_rosters_record_to_that_weeks_owner(snap):
    season = snap.seasons[0]
    entering_6 = {r["ownerId"]: r for r in metrics.pre_week_standings(season, snap.managers, 6)}
    # Roster 11 enters week 6 at 5-0 — the roster's record, held by John now.
    assert entering_6[JOHN]["wins"] == 5 and JOEL not in entering_6
    assert entering_6[BLAINE]["losses"] == 5 and NEW not in entering_6
    entering_7 = {r["ownerId"]: r for r in metrics.pre_week_standings(season, snap.managers, 7)}
    assert entering_7[NEW]["losses"] == 6 and BLAINE not in entering_7
    # The same games credited to an earlier week's owner, for a caller
    # comparing against that week.
    as_of_5 = metrics.pre_week_standings(season, snap.managers, 6, owner_week=5)
    assert {r["ownerId"] for r in as_of_5} == {JOEL, BLAINE, JASON, OPP2}


# ── records ─────────────────────────────────────────────────────────────


def test_record_book_rows_belong_to_the_weeks_manager(snap):
    for row in records._weekly_side_rows_individual(snap) + records._weekly_side_rows(snap):
        assert row["ownerId"] == _expected_for(row["season"], row["rosterId"], row["week"])
    section = records.build_section(snap)
    top = section["singleWeekHighest"][0]
    assert (top["ownerId"], top["week"], top["points"], top["teamName"]) == (
        JOEL,
        5,
        500.0,
        "jstuedle",
    )
    low = section["singleWeekLowest"][0]
    assert (low["ownerId"], low["week"], low["teamName"]) == (BLAINE, 6, "ughb")
    margin = section["biggestMargin"][0]
    assert (margin["ownerId"], margin["week"]) == (JOEL, 5)


def test_record_book_streaks_split_at_the_hand_off(snap):
    section = records.build_section(snap)
    wins = {r["ownerId"]: r["length"] for r in section["longestWinStreaks"]}
    losses = {r["ownerId"]: r["length"] for r in section["longestLossStreaks"]}
    assert wins[JOEL] == 5 and losses[JOHN] == 3
    assert losses[BLAINE] == 6 and wins[NEW] == 2
    assert JOHN not in wins and NEW not in losses
    joel = next(r for r in section["longestWinStreaks"] if r["ownerId"] == JOEL)
    assert joel["start"]["teamName"] == joel["end"]["teamName"] == "jstuedle"
    # 2025's roster-11 owner keeps his own 3-game streak.
    assert wins[OLD11] == 3


def test_season_totals_split_by_manager(snap):
    totals = {
        (r["ownerId"], r["season"]): r["weeksPlayed"] for r in records._season_scoring_totals(snap)
    }
    assert totals[(JOEL, "2026")] == 5 and totals[(JOHN, "2026")] == 3
    assert totals[(BLAINE, "2026")] == 6 and totals[(NEW, "2026")] == 2
    assert totals[(OLD11, "2025")] == 3


# ── streaks section ─────────────────────────────────────────────────────


def test_streak_events_and_active_streaks_follow_the_week(snap):
    weeks_by_owner: dict[tuple[str, str], set[int]] = {}
    for ev in streaks._all_events(snap):
        weeks_by_owner.setdefault((ev["ownerId"], ev["season"]), set()).add(ev["week"])
    assert weeks_by_owner[(JOEL, "2026")] == {1, 2, 3, 4, 5}
    assert weeks_by_owner[(JOHN, "2026")] == {6, 7, 8}
    assert weeks_by_owner[(BLAINE, "2026")] == {1, 2, 3, 4, 5, 6}
    assert weeks_by_owner[(NEW, "2026")] == {7, 8}
    assert weeks_by_owner[(OLD11, "2025")] == weeks_by_owner[(OLD12, "2025")] == {1, 2, 3}
    section = streaks.build_section(snap)
    active = {(s["ownerId"], s["type"]): s["length"] for s in section["activeStreaks"]}
    assert active[(JOHN, "lossStreak")] == 3  # weeks 6-8 only, not Joel's wins
    assert active[(NEW, "winStreak")] == 2  # weeks 7-8 only, not Blaine's losses


# ── rivalries ───────────────────────────────────────────────────────────


def test_rivalry_series_are_the_managers_who_met(snap):
    pairs = {
        frozenset(p["ownerIds"]): p["totalMeetings"]
        for p in rivalries.build_section(snap)["rivalries"]
    }
    assert pairs[frozenset({JOEL, JASON})] == 5
    assert pairs[frozenset({JOHN, JASON})] == 3
    assert pairs[frozenset({BLAINE, OPP2})] == 6
    assert pairs[frozenset({NEW, OPP2})] == 2
    assert pairs[frozenset({OLD11, JASON})] == 3


# ── luck ────────────────────────────────────────────────────────────────


def test_luck_rows_are_manager_rows_and_the_team_view_stays_available(snap):
    season_rows = {
        (r["ownerId"], r["season"]): r for r in luck.build_section(snap)["byOwnerSeason"]
    }
    assert season_rows[(JOEL, "2026")]["gamesPlayed"] == 5
    assert season_rows[(JOEL, "2026")]["teamName"] == "jstuedle"
    assert season_rows[(JOHN, "2026")]["gamesPlayed"] == 3
    assert season_rows[(JOHN, "2026")]["teamName"] == JOHN_TEAM
    assert season_rows[(BLAINE, "2026")]["gamesPlayed"] == 6
    assert season_rows[(NEW, "2026")]["gamesPlayed"] == 2
    assert season_rows[(OLD11, "2025")]["gamesPlayed"] == 3
    # The team-level view (Pick Forecast's all-play input) keeps each roster's
    # whole season on its current owner.
    franchise = {
        (r["ownerId"], r["season"]): r
        for r in luck.build_section(snap, by_franchise=True)["byOwnerSeason"]
    }
    assert franchise[(JOHN, "2026")]["gamesPlayed"] == 8
    assert franchise[(NEW, "2026")]["gamesPlayed"] == 8
    assert (JOEL, "2026") not in franchise and (BLAINE, "2026") not in franchise


# ── weekly recap ────────────────────────────────────────────────────────


def test_weekly_recap_sides_and_trade_parties_follow_the_week(snap):
    section = weekly_recap.build_section(snap)
    recaps = section["byKey"]
    for key, recap in recaps.items():
        season, week = key.split(":")
        for m in recap["matchups"]:
            for side in (m["home"], m["away"]):
                assert side["ownerId"] == _expected_for(season, side["rosterId"], int(week))
    assert {p["ownerId"] for p in recaps["2026:3"]["trades"][0]["parties"]} == {JOEL, BLAINE}
    assert {p["ownerId"] for p in recaps["2026:7"]["trades"][0]["parties"]} == {JOHN, NEW}


# ── activity feed ───────────────────────────────────────────────────────


def test_activity_feed_names_a_pre_cutover_side_by_that_weeks_manager(snap):
    feed = {t["week"]: t for t in activity.build_section(snap)["feed"]}
    pre = {s["rosterId"]: s for s in feed[3]["sides"]}
    assert (pre[11]["ownerId"], pre[11]["teamName"]) == (JOEL, "jstuedle")
    assert (pre[12]["ownerId"], pre[12]["teamName"]) == (BLAINE, "ughb")
    post = {s["rosterId"]: s for s in feed[7]["sides"]}
    assert (post[11]["ownerId"], post[11]["teamName"]) == (JOHN, JOHN_TEAM)
    assert (post[12]["ownerId"], post[12]["teamName"]) == (NEW, NEW_TEAM)


def test_superlative_activity_counts_follow_the_transaction_week(snap):
    counts = superlatives._activity_counts(snap)
    assert counts[JOEL]["trades"] == 1 and counts[BLAINE]["trades"] == 1
    assert counts[JOHN]["trades"] == 1 and counts[NEW]["trades"] == 1


# ── player journey, rookie draft, season awards ─────────────────────────
#
# The base fixture carries no players or draft, so these build a variant of
# it: one player on roster 11 and one on roster 12, started every 2026 week,
# and a 2026 rookie draft in which both handed-off rosters pick (the draft
# precedes week 1, so the OUTGOING managers made those picks).

P11 = "journey-p11"
P12 = "journey-p12"
R11_PICK = "rookie-r11"
R12_PICK = "rookie-r12"


def _journey_points(pid: str, week: int) -> float:
    # Week 1 is each player's season low; week 8 the high.
    return {1: 4.0, 8: 40.0}.get(week, 20.0) + (0.5 if pid == P12 else 0.0)


def _journey_snapshot() -> PublicLeagueSnapshot:
    import dataclasses

    base = _snapshot()
    s26, s25 = base.seasons
    matchups = {}
    for wk, entries in s26.matchups_by_week.items():
        rows = []
        for e in entries:
            e = dict(e)
            pid = {11: P11, 12: P12}.get(e["roster_id"])
            if pid:
                e["players"] = [pid]
                e["starters"] = [pid]
                e["players_points"] = {pid: _journey_points(pid, wk)}
            rows.append(e)
        matchups[wk] = rows
    draft_id = "rookie-2026"

    def _pick(rid: int, pick_no: int, pid: str) -> dict:
        return {
            "round": 1,
            "pick_no": pick_no,
            "roster_id": rid,
            "player_id": pid,
            "metadata": {"first_name": "Rookie", "last_name": pid, "position": "WR"},
        }

    s26 = dataclasses.replace(
        s26,
        matchups_by_week=matchups,
        drafts=[{"draft_id": draft_id, "type": "linear", "status": "complete"}],
        draft_picks_by_draft={
            draft_id: [_pick(11, 1, R11_PICK), _pick(12, 2, R12_PICK), _pick(1, 3, "rookie-r1")]
        },
    )
    return dataclasses.replace(base, seasons=[s26, s25])


@pytest.fixture(scope="module")
def jsnap() -> PublicLeagueSnapshot:
    return _journey_snapshot()


@pytest.mark.parametrize(
    ("pid", "rid", "before", "after", "cutover"),
    [(P11, 11, JOEL, JOHN, 6), (P12, 12, BLAINE, NEW, 7)],
)
def test_player_journey_weeks_belong_to_the_weeks_manager(jsnap, pid, rid, before, after, cutover):
    from src.public_league import player_journey

    journey = player_journey.build_player_journey(jsnap, pid)
    season = next(s for s in journey["bySeason"] if s["season"] == "2026")
    for row in season["weeklyLog"]:
        assert row["ownerId"] == (before if row["week"] < cutover else after), row
    by_owner = {r["ownerId"]: r for r in season["byOwner"]}
    assert by_owner[before]["weeksRostered"] == cutover - 1
    assert by_owner[after]["weeksRostered"] == 8 - (cutover - 1)
    pts_before = sum(_journey_points(pid, w) for w in range(1, cutover))
    assert by_owner[before]["pointsTotal"] == round(pts_before, 2)
    totals = {r["ownerId"]: r for r in journey["totalsByOwner"]}
    assert totals[before]["weeksRostered"] == cutover - 1
    # Week 1 (the low) was the departed manager's; week 8 (the high) the new one's.
    assert (season["worstWeek"]["week"], season["worstWeek"]["ownerId"]) == (1, before)
    assert (season["bestWeek"]["week"], season["bestWeek"]["ownerId"]) == (8, after)
    assert journey["worstWeek"]["ownerId"] == before
    assert journey["bestWeek"]["ownerId"] == after


@pytest.mark.parametrize(
    ("pid", "drafter", "team"), [(R11_PICK, JOEL, "jstuedle"), (R12_PICK, BLAINE, "ughb")]
)
def test_rookie_draft_picks_belong_to_the_outgoing_manager_on_both_surfaces(
    jsnap, pid, drafter, team
):
    from src.public_league import draft, player_journey

    origin = player_journey._draft_origin(jsnap, pid)
    assert origin["ownerId"] == drafter
    section = draft.build_section(jsnap)
    d26 = next(d for d in section["drafts"] if d["season"] == "2026")
    for rows in (d26["picks"], d26["firstRoundRecap"]):
        row = next(p for p in rows if p["playerId"] == pid)
        # ownerId and teamName agree with each other and with the journey.
        assert (row["ownerId"], row["teamName"]) == (drafter, team)
    other = next(p for p in d26["picks"] if p["playerId"] == "rookie-r1")
    assert (other["ownerId"], other["teamName"]) == (JASON, "Jason Team")


def test_season_award_team_name_finds_a_departed_managers_roster(jsnap):
    from src.public_league import awards

    s26, s25 = jsnap.seasons
    # A departed manager is not on Sleeper's current rosters; the same owner
    # (ownership.handed_off_roster) supplies the roster, and the name is his
    # own alias for the league-season, never the successor's team.
    assert awards._award_team_name(jsnap, s26, JOEL) == "jstuedle"
    assert awards._award_team_name(jsnap, s26, BLAINE) == "ughb"
    # Current owners: exactly what metrics.team_name (no week) answers.
    assert awards._award_team_name(jsnap, s26, JOHN) == JOHN_TEAM
    assert awards._award_team_name(jsnap, s26, JASON) == metrics.team_name(jsnap, LEAGUE, 1)
    assert awards._award_team_name(jsnap, s25, OLD11) == "Old Eleven"
    # A 2026 departed manager held nothing in 2025; an unknown owner nothing.
    assert awards._award_team_name(jsnap, s25, JOEL) == ""
    assert awards._award_team_name(jsnap, s26, "") == ""
