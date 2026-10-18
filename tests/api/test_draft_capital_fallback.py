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


def _pick_row(name, value):
    """A board pick row as the canonical resolver indexes it."""
    return {
        "displayName": name,
        "canonicalName": name,
        "rankDerivedValue": value,
        "assetClass": "pick",
    }


def _all_picks(result):
    """Every owned pick: the upcoming class (``picks``) plus every later class
    (``additionalClassPicks``) — the two never share a class."""
    return result["picks"] + result["additionalClassPicks"]


def _contract_with_picks():
    # ``Pick R.06`` is the current class's GENERIC grade (centre-slot
    # convention, ``pick_value_resolution``): the fallback's slots are
    # stand-ins, so every pick of a round prices at that row.  The 1.01 /
    # 2.05 rows stay for the slot-lookup unit tests below.
    return {
        "playersArray": [
            _pick_row("2026 Pick 1.01", 9000),
            _pick_row("2026 Pick 2.05", 4500),
            _pick_row("2026 Pick 1.06", 9000),
            _pick_row("2026 Pick 2.06", 4500),
        ]
    }


def test_returns_error_when_sleeper_unreachable(monkeypatch):
    monkeypatch.setattr(dcf, "_fetch_json", lambda _url: None)
    result = dcf.build_sleeper_derived(
        "L1",
        _contract_with_picks(),
        current_season=2026,
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
    # 10 teams × 4 rounds × 4 owned classes (the league-scoped horizon, no
    # evidence retiring any) = 160 picks: the upcoming class in ``picks``,
    # every later class in ``additionalClassPicks`` (the workbook path's
    # shape).  The fixture prices the 2026 round-1 and round-2 generic grades
    # only, so every 2026 R1 / R2 pick is priced — identically within its
    # round, because the slots are stand-ins.
    assert sorted({p["season"] for p in result["picks"]}) == [2026]
    assert sorted({p["season"] for p in result["additionalClassPicks"]}) == [2027, 2028, 2029]
    assert len(_all_picks(result)) == 160
    assert result["pricedPickCount"] == 20
    assert result["unpricedPickCount"] == 140
    # The 2026 class is its own $1,200 pool (owner decision 2026-10-18),
    # spread across its priced picks alone: 10 × 9000 + 10 × 4500 = 135000
    # → $80 and $40 each.
    priced = [p for p in _all_picks(result) if not p["isUnpriced"]]
    assert sorted({p["adjustedDollarValue"] for p in priced}) == [40, 80]
    assert sum(p["adjustedDollarValue"] for p in priced) == 1200
    assert all(p["slotStatus"] == "unknown" for p in _all_picks(result))
    # Team totals (the upcoming class — the auction budgets) sum to its pool.
    team_total = sum(t["auctionDollars"] for t in result["teamTotals"])
    assert team_total == 1200
    # A fully unpriced class holds no dollars and no budget.
    assert result["budgetPolicy"]["unpricedClasses"] == [2027, 2028, 2029]
    assert result["budgetPolicy"]["allYearsBudget"] == 1200


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
    """The C1 regression, with hand-computed dollars, under the owner's
    "$1,200 per draft class" basis (2026-10-18).

    Two teams, one round, four owned classes, and a contract that prices
    2026 (generic grade 9000) and 2028 (generic grade 3000) but NOT 2027 or
    2029.  Eight picks are generated; each priced CLASS is its own pool::

        2026 R1 x2  raw 9000   (priced)   → $600 each ($1,200 class)
        2027 R1 x2  ---        (unpriced) → null
        2028 R1 x2  raw 3000   (priced)   → $600 each ($1,200 class)
        2029 R1 x2  ---        (unpriced) → null

    The old shared pool gave $450 / $150 (24000 of value across both
    classes) — a class's dollars depended on how another class was priced.

    Before the C1 fix unpriced picks took the flat table's round-1
    constant of 7000 and diluted every real pick's dollars."""
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
            _pick_row("2026 Pick 1.01", 12000),  # a stand-in slot must NOT read this
            _pick_row("2026 Pick 1.06", 9000),
            _pick_row("2028 Round 1", 3000),
        ]
    }
    result = dcf.build_sleeper_derived(
        "L1",
        contract,
        current_season=2026,
        # ``num_teams`` was removed in #655 — the count comes from the roster
        # feed, which the stub above declares as two.
        draft_rounds=1,
    )
    by_key = {(p["season"], p["pick"]): p for p in _all_picks(result)}

    for label in ("1.01", "1.02"):
        assert by_key[(2026, label)]["dollarValue"] == 600
        assert by_key[(2026, label)]["adjustedDollarValue"] == 600
        assert by_key[(2026, label)]["isUnpriced"] is False
        assert by_key[(2026, label)]["valueBasis"] == "canonical_generic_round"
        assert by_key[(2028, label)]["dollarValue"] == 600

    # The unpriced picks are emitted (ownership is still real) but carry
    # no dollars and say so.
    for season in (2027, 2029):
        for pick_label in ("1.01", "1.02"):
            row = by_key[(season, pick_label)]
            assert row["dollarValue"] is None
            assert row["adjustedDollarValue"] is None
            assert row["isUnpriced"] is True

    # Each priced class lands its whole $1,200, on its priced picks alone;
    # an unpriced class lands nothing (never a phantom $1,200).
    for season, expected in ((2026, 1200), (2027, 0), (2028, 1200), (2029, 0)):
        assert (
            sum(
                p["dollarValue"]
                for p in _all_picks(result)
                if p["season"] == season and not p["isUnpriced"]
            )
            == expected
        )
        assert result["yearSummaries"][str(season)]["totalDollars"] == expected
    # All Years = N × $1,200 over the PRICED classes, each pick once.
    assert result["allYearsSummary"]["totalDollars"] == 2400
    assert result["allYearsSummary"]["pickCount"] == 8

    # Coverage tells the truth about what ``teamTotals`` holds: the upcoming
    # class, priced.  The completeness counts span every class.
    assert result["coveredPickYears"] == [2026]
    assert result["unpricedPickCount"] == 4
    assert result["pricedPickCount"] == 4
    assert result["unpricedPickYears"] == [2027, 2029]

    # Team totals are the upcoming class's per-team dollars (the auction
    # budgets); All Years adds the 2028 class on top, and the unpriced picks
    # add nothing to either team.
    totals = {t["team"]: t["auctionDollars"] for t in result["teamTotals"]}
    assert totals == {"Alpha": 600, "Beta": 600}
    all_years = {t["team"]: t["auctionDollars"] for t in result["allYearsTeamTotals"]}
    assert all_years == {"Alpha": 1200, "Beta": 1200}
    policy = result["budgetPolicy"]
    assert policy["basis"] == "per_class_pool"
    assert policy["status"] == "owner_confirmed"
    assert policy["decidedBy"] == "owner" and policy["decidedAt"] == "2026-10-18"
    assert policy["classBudgets"] == {"2026": 1200, "2027": 1200, "2028": 1200, "2029": 1200}
    assert policy["unpricedClasses"] == [2027, 2029]
    assert policy["allYearsBudget"] == 2400


def test_one_class_cannot_move_another_classes_dollars(monkeypatch):
    """Sabotage guard for the per-class basis: repricing a LATER class must
    not move a single dollar of the upcoming class (the auction budgets).
    Under the retired shared pool, doubling 2028's value took dollars off
    every 2026 pick."""
    monkeypatch.setattr(dcf, "_fetch_json", _stub_fetch_json(_two_team_responses([])))

    def build(v2028):
        return dcf.build_sleeper_derived(
            "L1",
            {
                "playersArray": [
                    _pick_row("2026 Pick 1.06", 9000),
                    _pick_row("2026 Pick 2.06", 3000),
                    _pick_row("2028 Round 1", v2028),
                ]
            },
            current_season=2026,
            draft_rounds=2,
        )

    low, high = build(1000), build(8000)
    assert [p["dollarValue"] for p in low["picks"]] == [p["dollarValue"] for p in high["picks"]]
    assert low["teamTotals"] == high["teamTotals"]
    # 2026: 2 × 9000 + 2 × 3000 = 24000 → $450 per first, $150 per second.
    assert sorted({p["dollarValue"] for p in low["picks"]}) == [150, 450]
    # 2028 (round 1 priced, round 2 not): its own $1,200 whatever its scale.
    for out in (low, high):
        y2028 = [p for p in out["additionalClassPicks"] if p["season"] == 2028]
        assert sum(p["dollarValue"] for p in y2028 if not p["isUnpriced"]) == 1200


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
        draft_rounds=4,
    )
    assert result["coveredPickYears"] == []
    assert result["pricedPickCount"] == 0
    assert result["unpricedPickCount"] == 16  # 1 team × 4 rounds × 4 owned classes
    assert all(p["dollarValue"] is None for p in _all_picks(result))
    assert result["budgetPolicy"]["allYearsBudget"] == 0
    assert all(t["auctionDollars"] == 0 for t in result["teamTotals"])


# ── /traded_picks fail-closed (missing is never zero) ────────────────
#
# A failed /traded_picks fetch used to read as "no trades" (``... or []``):
# the board folded DEFAULT ownership and priced every team's capital off
# it.  A 200 list -- even an empty one -- is an observation; anything else
# is unknown and the board is refused with the module's {error, message}
# shape.  The rule is ``src/identity/picks.traded_picks_observation``.


def _two_team_responses(traded):
    return {
        "/rosters": [
            {"roster_id": 1, "owner_id": "u1"},
            {"roster_id": 2, "owner_id": "u2"},
        ],
        "/users": [
            {"user_id": "u1", "display_name": "Alpha"},
            {"user_id": "u2", "display_name": "Beta"},
        ],
        "/traded_picks": traded,
    }


def _build(monkeypatch, traded):
    monkeypatch.setattr(dcf, "_fetch_json", _stub_fetch_json(_two_team_responses(traded)))
    return dcf.build_sleeper_derived(
        "L1", _contract_with_picks(), current_season=2026, draft_rounds=1
    )


def test_a_failed_traded_picks_fetch_refuses_the_board_not_defaults(monkeypatch):
    # ``_fetch_json`` returns None on ANY failure — the failed-fetch signal.
    result = _build(monkeypatch, None)
    assert result.get("error") == "pick_ownership_unavailable"
    assert result["message"]
    assert result["pickOwnershipState"] == "unavailable"
    assert result["pickOwnershipReason"] == "traded_picks_fetch_failed"
    # No owned picks and no capital are emitted on top of unknown ownership.
    assert "picks" not in result
    assert "teamTotals" not in result


def test_a_non_list_200_body_is_unavailable(monkeypatch):
    for body in ({"error": "rate limited"}, "oops", 0):
        result = _build(monkeypatch, body)
        assert result.get("error") == "pick_ownership_unavailable", body
        assert "picks" not in result


def test_an_empty_successful_list_still_gives_default_ownership(monkeypatch):
    result = _build(monkeypatch, [])
    assert "error" not in result
    assert result["picks"]
    assert not any(p["isTraded"] for p in result["picks"])
    assert all(p["currentOwner"] == p["originalOwner"] for p in result["picks"])
    # Success adds no state keys: the board shape is unchanged.
    assert "pickOwnershipState" not in result
    assert "pickOwnershipReason" not in result


def test_rosters_unreachable_still_wins_over_traded_picks(monkeypatch):
    """Ordering is unchanged: no rosters is ``sleeper_unreachable`` even when
    /traded_picks also failed."""
    monkeypatch.setattr(dcf, "_fetch_json", lambda _url: None)
    result = dcf.build_sleeper_derived("L1", _contract_with_picks(), current_season=2026)
    assert result["error"] == "sleeper_unreachable"


def test_a_ten_team_four_round_league_gets_exactly_1200_per_class_over_its_own_40_picks(
    monkeypatch,
):
    """Owner addendum 2026-10-18 (dynasty_new's shape): each class is its own
    $1,200.00 over its REAL 40 picks — never a synthesized 72 — exact in
    integer cents, with values that do not divide evenly."""
    responses = {
        "/rosters": [{"roster_id": i, "owner_id": str(100 + i)} for i in range(1, 11)],
        "/users": [{"user_id": str(100 + i), "display_name": f"Team{i}"} for i in range(1, 11)],
        "/traded_picks": [
            {"season": "2027", "round": 1, "roster_id": 3, "owner_id": 7},
            {"season": "2028", "round": 2, "roster_id": 5, "owner_id": 1},
        ],
    }
    monkeypatch.setattr(dcf, "_fetch_json", _stub_fetch_json(responses))
    rows = []
    for season, base in ((2026, 7777), (2027, 6543), (2028, 5321)):
        for rnd in range(1, 5):
            name = f"2026 Pick {rnd}.06" if season == 2026 else f"{season} Round {rnd}"
            rows.append(_pick_row(name, base // rnd + 13))
    from src.identity.pick_lifecycle import LeagueDraftYears

    result = dcf.build_sleeper_derived(
        "L1",
        {"playersArray": rows},
        current_season=2026,
        draft_rounds=4,
        league_draft_years=LeagueDraftYears(
            anchor_year=2026,
            upcoming_draft_year=2026,
            owned_pick_seasons=(2026, 2027, 2028),
            retired_seasons=(),
        ),
    )
    every = _all_picks(result)
    for season in (2026, 2027, 2028):
        picks = [p for p in every if p["season"] == season]
        assert len(picks) == 40  # 10 teams × 4 rounds, the league's real shape
        assert sum(round(p["dollarValue"] * 100) for p in picks) == 120000
        rows_y = result["teamTotalsByYear"][str(season)]
        assert sum(round(r["auctionDollars"] * 100) for r in rows_y) == 120000
    # The upcoming class is the auction budget basis; All Years sums classes.
    assert sum(round(t["auctionDollars"] * 100) for t in result["teamTotals"]) == 120000
    assert sum(round(r["auctionDollars"] * 100) for r in result["allYearsTeamTotals"]) == 360000
    assert result["allYearsSummary"]["totalDollars"] == 3600
    assert result["budgetPolicy"]["allYearsBudget"] == 3600
    # Traded picks fold through the canonical ownership owner.
    moved = {(p["season"], p["round"], p["originalOwner"]): p["currentOwner"] for p in every}
    assert moved[(2027, 1, "Team3")] == "Team7"
    assert moved[(2028, 2, "Team5")] == "Team1"
