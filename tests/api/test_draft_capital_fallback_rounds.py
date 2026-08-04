"""The Sleeper-derived draft-capital board's round count.

``build_sleeper_derived`` declared ``draft_rounds: int = 4`` and the one call
site never passed it.  The default league runs **6** rounds; every other league
was therefore built as a 4-round draft, and because ``_TARGET_TOTAL_BUDGET`` is
normalized across whatever picks the loop produces, the wrong count silently
redistributed the entire $1200 across every team's ``auctionDollars``.  The two
leagues' boards were not nominally comparable and nothing said so.

What hid it was the parameter beside it: ``num_teams`` was also declared and
also never used for anything — ``actual_num_teams`` comes from the roster feed
— so team count self-corrected from Sleeper while round count did not, and at
the call site both looked equally wired.  ``num_teams`` is gone.
"""

from __future__ import annotations

import pytest

from src.api import draft_capital_fallback as fb


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Every test states its own Sleeper responses; none may reach the wire."""
    calls: dict[str, object] = {}

    def _fake(url, *a, **kw):
        for key, payload in calls.items():
            if key in url:
                return payload
        return None

    monkeypatch.setattr(fb, "_fetch_json", _fake)
    return calls


def test_it_reads_the_round_count_from_sleeper(_no_network):
    _no_network["/drafts"] = [{"settings": {"rounds": 6}}]
    assert fb.resolve_draft_rounds("123") == (6, "sleeper")


def test_it_falls_back_to_what_the_registry_declares(_no_network):
    _no_network["/drafts"] = []
    assert fb.resolve_draft_rounds("123", declared=5) == (5, "registry")


def test_it_says_so_when_nothing_knows(_no_network):
    _no_network["/drafts"] = None
    rounds, source = fb.resolve_draft_rounds("123")
    assert rounds == fb.DEFAULT_DRAFT_ROUNDS
    assert source == "default"


def test_a_nonsense_round_count_is_refused_rather_than_used(_no_network):
    """Sleeper's own clamp is 1..6; anything outside it is not a draft."""
    _no_network["/drafts"] = [{"settings": {"rounds": 99}}]
    assert fb.resolve_draft_rounds("123", declared=3) == (3, "registry")
    _no_network["/drafts"] = [{"settings": {"rounds": 0}}]
    assert fb.resolve_draft_rounds("123")[1] == "default"


def _sleeper(rounds):
    return {
        "/rosters": [
            {"roster_id": 1, "owner_id": "u1"},
            {"roster_id": 2, "owner_id": "u2"},
        ],
        "/users": [
            {"user_id": "u1", "display_name": "Alpha"},
            {"user_id": "u2", "display_name": "Beta"},
        ],
        "/traded_picks": [],
        "/drafts": [{"settings": {"rounds": rounds}}] if rounds else [],
    }


def test_the_board_is_built_for_the_number_of_rounds_the_league_runs(_no_network):
    _no_network.update(_sleeper(6))
    out = fb.build_sleeper_derived("123", {}, current_season=2026)
    assert out["draftRounds"] == 6
    assert out["draftRoundsSource"] == "sleeper"
    # 2 seasons x 6 rounds x 2 teams.
    assert len(out["picks"]) == 24


# Prices every current-season slot up to six rounds.  A contract is REQUIRED to
# state the budget claim below: since the D-2 / audit-finding-C1 fix an unpriced
# pick carries ``dollarValue: None`` and is excluded from the pool, so an empty
# contract yields a board with no dollars at all rather than one priced off a
# flat per-round table.  Next-year picks stay unpriced here, exactly as they are
# live — the live contract carries current-year slot picks only.
_PRICED_CONTRACT = {
    "playersArray": [
        {
            "displayName": f"2026 Pick {rnd}.0{slot}",
            "rankDerivedValue": 9000 - 500 * (2 * (rnd - 1) + (slot - 1)),
            "assetClass": "pick",
        }
        for rnd in range(1, 7)
        for slot in (1, 2)
    ]
}


def test_the_round_count_rescales_every_team_total(_no_network):
    """Why the bug mattered, stated as arithmetic rather than as a worry."""
    _no_network.update(_sleeper(6))
    six = fb.build_sleeper_derived("123", _PRICED_CONTRACT, current_season=2026)
    _no_network.update(_sleeper(4))
    four = fb.build_sleeper_derived("123", _PRICED_CONTRACT, current_season=2026)

    assert six["draftRounds"] == 6
    assert four["draftRounds"] == 4
    # The same $1200 is spread over a different number of picks, so per-pick
    # dollars — and therefore every team's auction budget composition — differ.
    assert len(six["picks"]) != len(four["picks"])
    priced = lambda board: [p for p in board["picks"] if not p["isUnpriced"]]
    assert len(priced(six)) == 12  # 6 rounds x 2 teams, current season only
    assert len(priced(four)) == 8
    assert sum(p["dollarValue"] for p in priced(six)) == fb._TARGET_TOTAL_BUDGET
    assert sum(p["dollarValue"] for p in priced(four)) == fb._TARGET_TOTAL_BUDGET
    # The rescaling itself: the same top pick is worth less when the budget has
    # to cover more picks.
    top = lambda board: next(p for p in priced(board) if p["pick"] == "1.01")
    assert top(six)["dollarValue"] < top(four)["dollarValue"]


def test_an_explicit_count_wins_and_is_labelled_as_such(_no_network):
    _no_network.update(_sleeper(6))
    out = fb.build_sleeper_derived("123", {}, current_season=2026, draft_rounds=2)
    assert out["draftRounds"] == 2
    assert out["draftRoundsSource"] == "explicit"


def test_team_count_still_comes_from_the_roster_feed(_no_network):
    """The parameter that used to shadow it is gone; the behaviour is not."""
    _no_network.update(_sleeper(4))
    out = fb.build_sleeper_derived("123", {}, current_season=2026)
    assert out["numTeams"] == 2


def test_num_teams_is_no_longer_accepted(_no_network):
    _no_network.update(_sleeper(4))
    with pytest.raises(TypeError):
        fb.build_sleeper_derived("123", {}, current_season=2026, num_teams=12)


def test_the_rookie_board_reaches_the_second_league_when_the_profile_matches(_no_network):
    """Why /draft was showing a hardcoded rookie list outside the main league.

    The fallback emitted none of the eight ``rookie*`` fields and no
    ``overallPick``, so the frontend's sync bailed on the first row and fell
    back to filtering the DEFAULT league's contract — leaving ``boardValue``
    undefined, which is the optimizer's primary input.

    Sharing the board is correct rather than a leak: rookie values follow the
    scoring profile, not the league key, and the two live leagues share one.
    """
    _no_network.update(_sleeper(1))
    rookies = [
        {"name": "Jeremiyah Love", "pos": "RB", "dollar": 135, "boardValue": 7835,
         "ktcDollar": 130, "idpTradeCalcDollar": None, "dispersionCV": 0.03,
         "singleSource": False},
        {"name": "Carnell Tate", "pos": "WR", "dollar": 100, "boardValue": 6160,
         "ktcDollar": 98, "idpTradeCalcDollar": None, "dispersionCV": None,
         "singleSource": True},
    ]
    out = fb.build_sleeper_derived("123", {}, current_season=2026, rookies=rookies)
    current = [p for p in out["picks"] if p["season"] == 2026]
    assert out["rookieSource"] == "contract"
    assert [p["overallPick"] for p in current] == [1, 2]
    assert current[0]["rookieName"] == "Jeremiyah Love"
    assert current[0]["rookieBoardValue"] == 7835
    assert current[1]["rookieSingleSource"] is True
    # A null CV stays null — unobserved, not agreed.
    assert current[1]["rookieDispersionCV"] is None


def test_next_seasons_slots_get_no_rookie_names(_no_network):
    """That class does not exist yet; inventing names for it would be fiction."""
    _no_network.update(_sleeper(1))
    rookies = [{"name": "A", "pos": "RB", "dollar": 1, "boardValue": 1000}] * 4
    out = fb.build_sleeper_derived("123", {}, current_season=2026, rookies=rookies)
    future = [p for p in out["picks"] if p["season"] == 2027]
    assert future
    assert all("rookieName" not in p for p in future)


def test_omitting_the_rookie_board_leaves_the_payload_exactly_as_before(_no_network):
    _no_network.update(_sleeper(1))
    out = fb.build_sleeper_derived("123", {}, current_season=2026)
    assert out["rookieSource"] == "none"
    assert all("rookieName" not in p for p in out["picks"])
    # overallPick is unconditional — the frontend sorts on it before it can
    # know whether any rookie fields are present.
    assert all("overallPick" in p for p in out["picks"])
