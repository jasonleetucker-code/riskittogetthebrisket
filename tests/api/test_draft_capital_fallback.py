"""Tests for the Sleeper-derived draft-capital fallback.

We mock the Sleeper HTTP calls so tests run offline."""

from __future__ import annotations


from src.api import draft_capital_fallback as dcf


def _stub_fetch_json(responses):
    """Return a patched _fetch_json that reads from a URL→response map."""

    def fake(url):
        for key, resp in responses.items():
            if key in url:
                return resp
        return None

    return fake


def _contract_with_picks():
    return {
        "playersArray": [
            {
                "displayName": "2026 Pick 1.01",
                "rankDerivedValue": 9000,
                "assetClass": "pick",
            },
            {
                "displayName": "2026 Pick 2.05",
                "rankDerivedValue": 4500,
                "assetClass": "pick",
            },
        ]
    }


def test_returns_error_when_sleeper_unreachable(monkeypatch):
    monkeypatch.setattr(dcf, "_fetch_json", lambda _url: None)
    result = dcf.build_sleeper_derived(
        "L1",
        _contract_with_picks(),
        current_season=2026,
        num_teams=12,
    )
    assert result.get("error") == "sleeper_unreachable"


def test_basic_build_returns_expected_shape(monkeypatch):
    responses = {
        "/rosters": [{"roster_id": i, "owner_id": str(100 + i)} for i in range(1, 11)],
        "/users": [{"user_id": str(100 + i), "display_name": f"Team{i}"} for i in range(1, 11)],
        "/traded_picks": [],
    }
    monkeypatch.setattr(dcf, "_fetch_json", _stub_fetch_json(responses))
    result = dcf.build_sleeper_derived(
        "L1",
        _contract_with_picks(),
        current_season=2026,
        num_teams=10,
        draft_rounds=4,
    )
    assert result["source"] == "sleeper_derived"
    assert result["numTeams"] == 10
    assert result["totalBudget"] == 1200
    # Only seasons the contract actually priced are baked into
    # teamTotals; consumers must skip those years when adding roster
    # picks so the class isn't counted twice (regression guard for the
    # stack-effect builder).  This fixture prices two 2026 rows and
    # nothing for 2027, so 2027 is NOT covered — the consumer sources
    # those picks from the board instead.
    assert result["coveredPickYears"] == [2026]
    # 10 teams × 4 rounds × 2 seasons = 80 picks, of which the fixture
    # contract can price exactly two (1.01 and 2.05, both 2026).
    assert len(result["picks"]) == 80
    assert result["pricedPickCount"] == 2
    assert result["unpricedPickCount"] == 78
    # Sum of per-pick dollars = total budget, spread across the priced
    # picks alone: 9000 and 4500 out of 13500 → $800 and $400.
    priced = [p for p in result["picks"] if not p["isUnpriced"]]
    assert sorted(p["adjustedDollarValue"] for p in priced) == [400, 800]
    assert sum(p["adjustedDollarValue"] for p in priced) == 1200
    # Team totals sum to total budget.
    team_total = sum(t["auctionDollars"] for t in result["teamTotals"])
    assert team_total == 1200


def test_traded_pick_updates_ownership(monkeypatch):
    responses = {
        "/rosters": [
            {"roster_id": 1, "owner_id": "u1"},
            {"roster_id": 2, "owner_id": "u2"},
        ],
        "/users": [
            {"user_id": "u1", "display_name": "Alpha"},
            {"user_id": "u2", "display_name": "Beta"},
        ],
        "/traded_picks": [
            # Team 2's 2026 1st (slot 2) now owned by Team 1.
            {
                "season": "2026",
                "round": 1,
                "roster_id": 2,
                "owner_id": 1,
            }
        ],
    }
    monkeypatch.setattr(dcf, "_fetch_json", _stub_fetch_json(responses))
    result = dcf.build_sleeper_derived(
        "L1",
        _contract_with_picks(),
        current_season=2026,
        num_teams=2,
        draft_rounds=1,
    )
    # Find the traded pick.
    traded = [p for p in result["picks"] if p["isTraded"]]
    assert len(traded) == 1
    assert traded[0]["currentOwner"] == "Alpha"
    assert traded[0]["originalOwner"] == "Beta"


def test_round_to_budget_sums_exactly(monkeypatch):
    # Non-round-number values that need largest-remainder distribution.
    out = dcf._round_to_budget([1.1, 2.2, 3.3, 4.4, 5.5], target_total=100)  # noqa: SLF001
    assert sum(out) == 100


def test_pick_value_from_contract_exact_match():
    contract = _contract_with_picks()
    v = dcf._pick_value_from_contract(contract, 2026, 1, 1)  # noqa: SLF001
    assert v == 9000.0


def test_pick_value_from_contract_returns_none_on_a_miss():
    """A pick the contract does not carry is UNPRICED, not cheap.

    This used to return a hardcoded per-round constant (7000/4000/
    2000/1200/700/300).  Those numbers sat on the same 0-9999 scale as
    the Hill-calibrated real ones and were normalized into the same
    $1200 pool, so nothing downstream could tell them apart."""
    assert dcf._pick_value_from_contract({}, 2027, 1, 1) is None  # noqa: SLF001
    assert dcf._pick_value_from_contract({}, 2027, 4, 5) is None  # noqa: SLF001
    # A populated contract that simply lacks the requested season is the
    # LIVE case: the contract carries current-year slot picks only.
    assert dcf._pick_value_from_contract(_contract_with_picks(), 2027, 1, 1) is None  # noqa: SLF001
    assert dcf._pick_value_from_contract(None, 2026, 1, 1) is None  # noqa: SLF001


def test_unpriced_picks_are_excluded_from_the_dollar_pool(monkeypatch):
    """The C1 regression, with hand-computed dollars.

    Two teams, one round, and a contract that prices ONLY the current
    season — exactly the live shape (the contract carries 2026 slot
    picks and nothing for 2027).  Four picks are generated::

        2026 1.01  raw 9000   (priced)
        2026 1.02  raw 3000   (priced)
        2027 1.01  ---        (unpriced)
        2027 1.02  ---        (unpriced)

    Correct: the $1200 pool is split between the two priced picks in
    9000:3000 ratio → 9000/12000 × 1200 = $900 and 3000/12000 × 1200 =
    $300.  Both are exact, so largest-remainder rounding has nothing to
    distribute.

    Before the fix the two 2027 picks each took the flat table's round-1
    constant of 7000, so the pool was 9000+3000+7000+7000 = 26000 and
    1.01 collected 9000/26000 × 1200 = $415 — a real pick's dollar value
    cut by more than half by two numbers nobody computed."""
    responses = {
        "/rosters": [
            {"roster_id": 1, "owner_id": "u1"},
            {"roster_id": 2, "owner_id": "u2"},
        ],
        "/users": [
            {"user_id": "u1", "display_name": "Alpha"},
            {"user_id": "u2", "display_name": "Beta"},
        ],
        "/traded_picks": [],
    }
    monkeypatch.setattr(dcf, "_fetch_json", _stub_fetch_json(responses))
    contract = {
        "playersArray": [
            {"displayName": "2026 Pick 1.01", "rankDerivedValue": 9000, "assetClass": "pick"},
            {"displayName": "2026 Pick 1.02", "rankDerivedValue": 3000, "assetClass": "pick"},
        ]
    }
    result = dcf.build_sleeper_derived(
        "L1",
        contract,
        current_season=2026,
        num_teams=2,
        draft_rounds=1,
    )
    by_key = {(p["season"], p["pick"]): p for p in result["picks"]}

    assert by_key[(2026, "1.01")]["dollarValue"] == 900
    assert by_key[(2026, "1.01")]["adjustedDollarValue"] == 900
    assert by_key[(2026, "1.01")]["isUnpriced"] is False
    assert by_key[(2026, "1.02")]["dollarValue"] == 300

    # The unpriced picks are emitted (ownership is still real) but carry
    # no dollars and say so.
    for pick_label in ("1.01", "1.02"):
        row = by_key[(2027, pick_label)]
        assert row["dollarValue"] is None
        assert row["adjustedDollarValue"] is None
        assert row["isUnpriced"] is True

    # The whole budget still lands, on the priced picks alone.
    assert sum(p["dollarValue"] for p in result["picks"] if not p["isUnpriced"]) == 1200

    # Coverage tells the truth about what was priced, not about the
    # loop bounds.
    assert result["coveredPickYears"] == [2026]
    assert result["unpricedPickCount"] == 2
    assert result["pricedPickCount"] == 2
    assert result["unpricedPickYears"] == [2027]

    # Team totals follow the priced dollars: slot 1 → Alpha, slot 2 →
    # Beta, and the 2027 picks add nothing to either.
    totals = {t["team"]: t["auctionDollars"] for t in result["teamTotals"]}
    assert totals == {"Alpha": 900, "Beta": 300}


def test_a_fully_unpriced_board_prices_nothing(monkeypatch):
    """No contract at all → no invented dollars anywhere.

    The route guards this case with a 503 (see
    ``test_draft_capital_data_not_ready.py``); this pins the builder's
    own behaviour so the guard is defending an honest empty board rather
    than papering over a fabricated one."""
    responses = {
        "/rosters": [{"roster_id": 1, "owner_id": "u1"}],
        "/users": [{"user_id": "u1", "display_name": "A"}],
        "/traded_picks": [],
    }
    monkeypatch.setattr(dcf, "_fetch_json", _stub_fetch_json(responses))
    result = dcf.build_sleeper_derived(
        "L1",
        {},
        current_season=2026,
        num_teams=1,
        draft_rounds=4,
    )
    assert result["coveredPickYears"] == []
    assert result["pricedPickCount"] == 0
    assert result["unpricedPickCount"] == 8  # 1 team × 4 rounds × 2 seasons
    assert all(p["dollarValue"] is None for p in result["picks"])
    assert all(t["auctionDollars"] == 0 for t in result["teamTotals"])
