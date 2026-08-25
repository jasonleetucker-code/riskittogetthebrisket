from src import packages as substrate
from src.trade import finder


def _asset(name: str, value: int = 2000) -> finder.Asset:
    return finder.Asset(
        name=name,
        position="WR",
        team="X",
        model_value=value,
        market_value=value,
        source_count=5,
        market_source="ktcSfTep",
    )


def test_equal_count_mode_only_enumerates_one_for_one_and_two_for_two(monkeypatch):
    """The /arbitrage policy cannot regress back to an asymmetric package."""

    def fake_score(give, receive):
        return finder.TradeCandidate(
            give=list(give),
            receive=list(receive),
            board_delta=1,
            arbitrage_score=1.0,
        )

    monkeypatch.setattr(finder, "_score_trade", fake_score)

    mine = [_asset("Mine A", 3000), _asset("Mine B", 2500), _asset("Mine C", 2000)]
    theirs = [_asset("Opp A", 3000), _asset("Opp B", 2500), _asset("Opp C", 2000)]

    trades, report = finder._generate_packages(
        mine,
        theirs,
        substrate.UNCONSTRAINED_OUTGOING,
        equal_count_only=True,
    )

    sizes = {(len(trade.give), len(trade.receive)) for trade in trades}
    assert sizes == {(1, 1), (2, 2)}
    assert all(len(trade.give) == len(trade.receive) for trade in trades)
    assert report["mode"] == "equal_count_only"
    assert "twoForTwo" in report
    assert "asymmetric" not in report


def _player(value: int = 2000) -> dict:
    return {
        "_finalAdjusted": value,
        "_sites": 5,
        "position": "WR",
        "_canonicalSiteValues": {"ktcSfTep": value},
    }


def test_session_exclusions_reduce_both_search_pools_before_generation(monkeypatch):
    """X is a search constraint, not a top-N post-filter.

    Capturing the arguments to the canonical package generator proves the
    excluded outgoing AND incoming players are already gone before any package
    is constructed or scored.
    """

    seen: dict[str, object] = {}

    def capture_generation(my_assets, opp_assets, outgoing_policy, *, equal_count_only=False):
        seen["mine"] = [asset.name for asset in my_assets]
        seen["opp"] = [asset.name for asset in opp_assets]
        seen["equal"] = equal_count_only
        return [], {"captured": True}

    monkeypatch.setattr(finder, "_generate_packages", capture_generation)

    players = {
        "Keep Mine": _player(2400),
        "Exclude Mine": _player(2200),
        "Keep Opp": _player(2300),
        "Exclude Opp": _player(2100),
    }
    teams = [
        {
            "name": "Mine",
            "ownerId": "owner-mine",
            "players": ["Keep Mine", "Exclude Mine"],
        },
        {
            "name": "Opp",
            "ownerId": "owner-opp",
            "players": ["Keep Opp", "Exclude Opp"],
        },
    ]

    result = finder.find_trades(
        players,
        "Mine",
        [
            "Opp",
            {
                finder.ARBITRAGE_CONTROL_KEY: {
                    "equalCountOnly": True,
                    "excludePlayers": ["Exclude Mine", "Exclude Opp"],
                }
            },
        ],
        teams,
        market_top_n=0,
        use_team_context=False,
    )

    assert seen == {
        "mine": ["Keep Mine"],
        "opp": ["Keep Opp"],
        "equal": True,
    }
    assert result["metadata"]["packageMode"] == "equal_count_only"
    assert result["metadata"]["sessionExcludedPlayers"] == ["Exclude Mine", "Exclude Opp"]
    assert result["metadata"]["sessionExcludedCount"] == 2
    assert result["metadata"]["searchableMyRosterSize"] == 1


def test_default_finder_mode_keeps_existing_asymmetric_shapes(monkeypatch):
    """The owner request is scoped to /arbitrage, not a global finder rewrite."""

    def fake_score(give, receive):
        return finder.TradeCandidate(
            give=list(give),
            receive=list(receive),
            board_delta=1,
            arbitrage_score=1.0,
        )

    monkeypatch.setattr(finder, "_score_trade", fake_score)

    mine = [_asset("Mine A", 3000), _asset("Mine B", 2500)]
    theirs = [_asset("Opp A", 3000), _asset("Opp B", 2500)]
    trades, report = finder._generate_packages(
        mine,
        theirs,
        substrate.UNCONSTRAINED_OUTGOING,
    )

    sizes = {(len(trade.give), len(trade.receive)) for trade in trades}
    assert (1, 1) in sizes
    assert (2, 1) in sizes
    assert (1, 2) in sizes
    assert "asymmetric" in report
