"""The Ring Club: championship rings per NFL player (owner directive 2026-11-23).

Pins the eligibility rule in ``src/public_league/championship_rings.py`` on
synthetic seasons built from Sleeper-shaped payloads.  Each season is a
four-team league with a two-team final; ``_season`` builds its matchups, the
winners bracket and the frozen roster from plain player lists so every case
reads as the rule it pins.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.public_league import championship_rings as cr
from src.public_league.identity import build_manager_registry
from src.public_league.public_contract import assert_public_payload_safe
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot

CHAMP, RUNNER_UP, OTHER_A, OTHER_B = 1, 2, 3, 4

PLAYERS = {
    "p1": {"full_name": "Alpha Ace", "position": "QB", "team": "BUF"},
    "p2": {"full_name": "Bravo Back", "position": "RB", "team": "KC"},
    "p3": {"full_name": "Charlie Catch", "position": "WR", "team": None},
    "p4": {"full_name": "Delta Deep", "position": "TE", "team": "SF"},
    "p5": {"full_name": "Echo End", "position": "DL", "team": "DAL"},
    "p6": {"full_name": "Foxtrot Free", "position": "LB", "team": "NYJ"},
    "p7": {"full_name": "Golf Guard", "position": "WR", "team": "MIA"},
    "BUF": {"full_name": "Buffalo Bills", "position": "DEF", "team": "BUF"},
}


def _season(
    year: str,
    *,
    closing: list[str],
    weeks: tuple[int, ...] = (16, 17),
    champion: int | None = CHAMP,
    final_weeks_rows: dict[int, list[str]] | None = None,
    roster_players: list[str] | None = None,
    taxi: list[str] | None = None,
    reserve: list[str] | None = None,
    round_type: int | None = 1,
    status: str = "complete",
    owner_of_champ: str = "owner-A",
    team_name: str = "Team A",
    taxi_slots: int = 0,
) -> SeasonSnapshot:
    """A decided season whose champion holds ``closing`` in the final week.

    ``weeks`` are the final's scoring weeks (two-week final by default, the
    league's measured shape).  ``final_weeks_rows`` overrides the champion's
    ``players`` per week (e.g. a different roster in the first leg).
    """
    league_id = f"L{year}"
    matchups: dict[int, list[dict[str, Any]]] = {}
    for wk in (14, 15, *weeks):
        if wk in weeks:
            champ_players = (final_weeks_rows or {}).get(wk, closing)
            rows = [
                {"roster_id": CHAMP, "matchup_id": 1, "points": 120.0, "players": champ_players},
                {"roster_id": RUNNER_UP, "matchup_id": 1, "points": 100.0, "players": ["x1"]},
                {"roster_id": OTHER_A, "matchup_id": 2, "points": 90.0, "players": ["x2"]},
                {"roster_id": OTHER_B, "matchup_id": 2, "points": 80.0, "players": ["x3"]},
            ]
        else:
            rows = [
                {"roster_id": CHAMP, "matchup_id": 1, "points": 110.0, "players": closing},
                {"roster_id": OTHER_B, "matchup_id": 1, "points": 90.0, "players": ["x3"]},
                {"roster_id": RUNNER_UP, "matchup_id": 2, "points": 95.0, "players": ["x1"]},
                {"roster_id": OTHER_A, "matchup_id": 2, "points": 85.0, "players": ["x2"]},
            ]
        matchups[wk] = rows
    # Round 1 is week 14, round 2 week 15, and the final (round 3) the
    # remaining week(s): the league's measured three-round shape.
    final_round = 3
    bracket = [
        {"r": 1, "m": 1, "t1": CHAMP, "t2": OTHER_B, "w": CHAMP, "l": OTHER_B},
        {"r": 2, "m": 2, "t1": RUNNER_UP, "t2": OTHER_A, "w": RUNNER_UP, "l": OTHER_A},
        {
            "r": final_round,
            "m": 3,
            "t1": CHAMP,
            "t2": RUNNER_UP,
            "w": champion,
            "l": RUNNER_UP if champion == CHAMP else None,
            "p": 1,
        },
    ]
    settings: dict[str, Any] = {"playoff_week_start": 14, "taxi_slots": taxi_slots}
    if round_type is not None:
        settings["playoff_round_type"] = round_type
    rosters = [
        {
            "roster_id": CHAMP,
            "owner_id": owner_of_champ,
            "players": roster_players if roster_players is not None else list(closing),
            "taxi": taxi or [],
            "reserve": reserve or [],
        },
        {"roster_id": RUNNER_UP, "owner_id": "owner-B", "players": ["x1"]},
        {"roster_id": OTHER_A, "owner_id": "owner-C", "players": ["x2"]},
        {"roster_id": OTHER_B, "owner_id": "owner-D", "players": ["x3"]},
    ]
    users = [
        {
            "user_id": owner_of_champ,
            "display_name": owner_of_champ.title(),
            "metadata": {"team_name": team_name},
        },
        {"user_id": "owner-B", "display_name": "Bea", "metadata": {"team_name": "Team B"}},
        {"user_id": "owner-C", "display_name": "Cal", "metadata": {"team_name": "Team C"}},
        {"user_id": "owner-D", "display_name": "Dee", "metadata": {"team_name": "Team D"}},
    ]
    return SeasonSnapshot(
        season=year,
        league_id=league_id,
        league={
            "league_id": league_id,
            "season": year,
            "status": status,
            "total_rosters": 4,
            "settings": settings,
        },
        users=users,
        rosters=rosters,
        matchups_by_week=matchups,
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=bracket if champion is not None else [{**b, "w": None} for b in bracket],
        losers_bracket=[],
    )


def _snapshot(*seasons: SeasonSnapshot, history: str | None = "complete") -> PublicLeagueSnapshot:
    ordered = sorted(seasons, key=lambda s: s.season, reverse=True)
    registry = build_manager_registry(
        [{"league": s.league, "users": s.users, "rosters": s.rosters} for s in ordered]
    )
    snap = PublicLeagueSnapshot(
        root_league_id=ordered[0].league_id if ordered else "L",
        generated_at="2026-11-23T00:00:00Z",
        seasons=ordered,
        managers=registry,
        nfl_players=dict(PLAYERS),
    )
    snap.history_coverage = {"state": history} if history is not None else None
    return snap


def _club(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    club = cr.build_ring_club(snapshot)
    assert_public_payload_safe(club)
    return club


def _rings(snapshot: PublicLeagueSnapshot) -> dict[str, list[str]]:
    return {pid: sorted(by) for pid, by in cr.ring_ledger(snapshot).rings.items()}


# ── ring counts: zero, one, two, three ─────────────────────────────────────


def test_zero_one_two_and_three_rings():
    snap = _snapshot(
        _season("2022", closing=["p1", "p2", "p3"]),
        _season("2023", closing=["p1", "p2"]),
        _season("2024", closing=["p1", "p4"]),
    )
    rings = _rings(snap)
    assert rings["p1"] == ["2022", "2023", "2024"]
    assert rings["p2"] == ["2022", "2023"]
    assert rings["p3"] == ["2022"]
    assert rings["p4"] == ["2024"]
    assert "p5" not in rings  # never on a championship roster: no ring

    club = _club(snap)
    names = [m["playerName"] for m in club["members"]]
    assert names == ["Alpha Ace", "Bravo Back"]  # one-ring players never appear
    alpha, bravo = club["members"]
    assert (alpha["rings"], alpha["prestige"], alpha["seasons"]) == (
        3,
        True,
        ["2022", "2023", "2024"],
    )
    assert (bravo["rings"], bravo["prestige"]) == (2, False)
    assert club["memberCount"] == 2 and club["emptyState"] is None
    assert club["coverage"]["singleRingPlayers"] == 2


def test_rings_with_different_franchises_belong_to_the_player():
    snap = _snapshot(
        _season("2022", closing=["p1"], owner_of_champ="owner-A", team_name="Team A"),
        _season("2024", closing=["p1"], owner_of_champ="owner-X", team_name="Team X"),
        _season("2026", closing=["p1"], owner_of_champ="owner-Z", team_name="Team Z"),
    )
    (member,) = _club(snap)["members"]
    assert member["rings"] == 3
    assert [(c["season"], c["ownerId"], c["teamName"]) for c in member["championships"]] == [
        ("2022", "owner-A", "Team A"),
        ("2024", "owner-X", "Team X"),
        ("2026", "owner-Z", "Team Z"),
    ]


# ── who is on the closing roster ───────────────────────────────────────────


def test_bench_and_injured_reserve_players_qualify():
    # The matchup row lists every rostered player, starters or not, and the
    # host includes injured reserve in it (measured on the 2024 champion).
    snap = _snapshot(
        _season("2024", closing=["p1", "p2"], reserve=["p2"]),
        _season("2025", closing=["p1", "p2"], reserve=["p2"]),
    )
    assert _rings(snap)["p2"] == ["2024", "2025"]


def test_taxi_player_omitted_from_the_matchup_row_is_credited_from_a_frozen_roster():
    season = _season(
        "2025",
        closing=["p1"],
        roster_players=["p1", "p6"],
        taxi=["p6"],
        taxi_slots=3,
    )
    close = cr.championship_close(season)
    assert close.status == cr.STATUS_VERIFIED
    assert "p6" in close.player_ids
    assert close.held_slots_unverified is False


def test_taxi_player_is_not_credited_when_the_frozen_roster_moved_after_the_close():
    # The roster gained p7 after the championship: it no longer proves who was
    # on the taxi squad at the close, so the taxi player is not credited and
    # the season is flagged partial (verified only for the players named).
    season = _season(
        "2025",
        closing=["p1"],
        roster_players=["p1", "p6", "p7"],
        taxi=["p6"],
        taxi_slots=3,
    )
    close = cr.championship_close(season)
    assert close.player_ids == frozenset({"p1"})
    assert close.held_slots_unverified is True
    club = _club(_snapshot(season))
    assert club["coverage"]["state"] == "incomplete"
    assert club["coverage"]["partialSeasons"] == ["2025"]
    assert club["emptyState"]["kind"] == "coverage_incomplete"


def test_player_traded_away_before_the_close_earns_nothing():
    # On the roster in the first leg of the two-week final, gone by the
    # second: the championship concluded without him.
    season = _season("2025", closing=["p1"], final_weeks_rows={16: ["p1", "p3"], 17: ["p1"]})
    assert cr.championship_close(season).player_ids == frozenset({"p1"})


def test_player_added_after_the_championship_earns_nothing():
    # The frozen roster gained p5 after the final; the closing week's row is
    # the source, so p5 earns no ring.
    season = _season("2025", closing=["p1", "p2"], roster_players=["p1", "p2", "p5"])
    close = cr.championship_close(season)
    assert close.status == cr.STATUS_VERIFIED
    assert "p5" not in close.player_ids


def test_one_week_final_closes_on_its_only_week():
    season = _season("2025", closing=["p1"], weeks=(16,), round_type=0)
    close = cr.championship_close(season)
    assert (close.status, close.closing_week) == (cr.STATUS_VERIFIED, 16)


def test_team_defense_units_are_not_individual_players():
    snap = _snapshot(_season("2024", closing=["p1", "BUF"]), _season("2025", closing=["p1", "BUF"]))
    assert "BUF" not in _rings(snap)


# ── missing, undecided and unverifiable seasons ────────────────────────────


def test_undecided_championship_awards_nothing():
    season = _season("2026", closing=["p1"], champion=None, status="in_season")
    assert cr.championship_close(season).status == cr.STATUS_UNDECIDED
    club = _club(_snapshot(_season("2025", closing=["p1"]), season))
    assert club["coverage"]["state"] == "complete"
    assert club["emptyState"]["kind"] == "no_multi_champions"
    assert _rings(_snapshot(season)) == {}


def test_missing_closing_roster_is_unverified_not_zero():
    season = _season("2024", closing=[])
    close = cr.championship_close(season)
    assert (close.status, close.reason) == (cr.STATUS_UNVERIFIED, cr.REASON_CLOSING_ROSTER_EMPTY)
    club = _club(_snapshot(season, _season("2025", closing=["p1"])))
    assert club["coverage"]["unverifiedSeasons"] == ["2024"]
    assert club["emptyState"]["kind"] == "coverage_incomplete"
    assert "2024" in club["emptyState"]["message"]


def test_final_pairing_missing_from_the_matchups_is_unverified():
    season = _season("2024", closing=["p1"])
    for wk in (16, 17):
        season.matchups_by_week[wk] = [
            r for r in season.matchups_by_week[wk] if r["roster_id"] != RUNNER_UP
        ]
    assert cr.championship_close(season).reason == cr.REASON_FINAL_PAIRING_NOT_FOUND


def test_closing_week_that_disagrees_with_league_settings_is_unverified():
    # Settings say a one-week final (week 16) but the finalists met in 16-17.
    season = _season("2024", closing=["p1"], round_type=0)
    close = cr.championship_close(season)
    assert (close.status, close.reason) == (cr.STATUS_UNVERIFIED, cr.REASON_CLOSING_WEEK_MISMATCH)


def test_closing_week_not_yet_final_is_unverified():
    # A decided bracket but a host clock that has not finished the closing
    # week (status in season, last scored leg 16): no ring yet.
    season = _season("2026", closing=["p1"], status="in_season")
    season.league["settings"]["last_scored_leg"] = 16
    close = cr.championship_close(season)
    assert (close.status, close.reason) == (cr.STATUS_UNVERIFIED, cr.REASON_CLOSING_WEEK_NOT_FINAL)


def test_unknown_or_truncated_league_history_cannot_confirm_an_empty_club():
    for history in (None, "truncated", "unverified"):
        club = _club(_snapshot(_season("2025", closing=["p1"]), history=history))
        assert club["coverage"]["state"] == "incomplete"
        assert club["coverage"]["historyComplete"] is False
        assert club["emptyState"]["kind"] == "coverage_incomplete"
        assert "earlier seasons" in club["emptyState"]["message"]


def test_no_decided_championship_yet():
    club = _club(_snapshot(_season("2026", closing=["p1"], champion=None, status="in_season")))
    assert club["coverage"]["state"] == "none"
    assert club["emptyState"]["kind"] == "no_championships_yet"


def test_confirmed_empty_club_uses_the_owner_wording():
    club = _club(_snapshot(_season("2024", closing=["p1"]), _season("2025", closing=["p2"])))
    assert club["members"] == []
    assert club["emptyState"] == {
        "kind": "no_multi_champions",
        "title": "THE RING CLUB",
        "message": cr.EMPTY_CONFIRMED_MESSAGE,
    }
    assert club["coverage"]["verifiedSeasons"] == ["2024", "2025"]


# ── idempotence, identity and updates ──────────────────────────────────────


def test_duplicate_season_imports_never_award_twice():
    s2024 = _season("2024", closing=["p1"])
    s2025 = _season("2025", closing=["p1"])
    once = _club(_snapshot(s2024, s2025))
    twice = _club(_snapshot(s2024, s2025, _season("2025", closing=["p1"])))
    assert [m["rings"] for m in once["members"]] == [2]
    assert [m["rings"] for m in twice["members"]] == [2]
    # A player listed twice in one closing row is still one ring.
    dup = _snapshot(_season("2024", closing=["p1", "p1"]), _season("2025", closing=["p1"]))
    assert _club(dup)["members"][0]["rings"] == 2


def test_identity_is_the_player_id_not_the_name():
    players = dict(PLAYERS)
    players["p8"] = {"full_name": "Alpha Ace", "position": "LB", "team": "NYG"}  # same name
    snap = _snapshot(_season("2024", closing=["p1", "p8"]), _season("2025", closing=["p1", "p8"]))
    snap.nfl_players = players
    members = _club(snap)["members"]
    assert sorted(m["playerId"] for m in members) == ["p1", "p8"]
    assert {m["position"] for m in members} == {"QB", "LB"}


def test_unknown_player_is_still_credited_and_named_honestly():
    snap = _snapshot(_season("2024", closing=["p404"]), _season("2025", closing=["p404"]))
    (member,) = _club(snap)["members"]
    assert member["playerId"] == "p404"
    assert member["nflTeam"] is None
    assert member["playerName"]  # a stable label, never blank


def test_new_championship_updates_counts_and_admits_new_members():
    seasons = [_season("2024", closing=["p1", "p2"]), _season("2025", closing=["p1"])]
    before = _club(_snapshot(*seasons))
    assert [(m["playerId"], m["rings"]) for m in before["members"]] == [("p1", 2)]
    after = _club(_snapshot(*seasons, _season("2026", closing=["p1", "p2"])))
    assert [(m["playerId"], m["rings"]) for m in after["members"]] == [("p1", 3), ("p2", 2)]


# ── ranking and ties ───────────────────────────────────────────────────────


def test_ties_share_a_rank_and_order_alphabetically():
    snap = _snapshot(
        _season("2023", closing=["p3", "p2", "p1", "p4"]),
        _season("2024", closing=["p3", "p2", "p1"]),
        _season("2025", closing=["p1"]),
    )
    members = _club(snap)["members"]
    assert [(m["playerName"], m["rings"], m["rank"], m["tied"]) for m in members] == [
        ("Alpha Ace", 3, 1, False),
        ("Bravo Back", 2, 2, True),
        ("Charlie Catch", 2, 2, True),
    ]


# ── player profile ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("closings", "expected"),
    [
        ((["p2"], ["p3"]), (0, False)),
        ((["p1"], ["p3"]), (1, False)),
        ((["p1"], ["p1"]), (2, True)),
    ],
)
def test_player_rings_for_the_profile(closings, expected):
    snap = _snapshot(_season("2024", closing=closings[0]), _season("2025", closing=closings[1]))
    rings = cr.player_rings(snap, "p1")
    assert (rings["rings"], rings["ringClubMember"]) == expected
    assert len(rings["championships"]) == expected[0]
