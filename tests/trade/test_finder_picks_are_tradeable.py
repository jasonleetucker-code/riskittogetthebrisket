"""Draft picks are assets the finder can actually propose.

Audit finding W09-F003: ``_resolve_roster`` read only ``t["players"]``
from the Sleeper team dict.  Picks live in the SIBLING key ``t["picks"]``
("2026 1st", "2027 1st", ...), so 25 picks sat in the gated asset pool
and ZERO appeared in any of the 480 trades the engine returned across
all 12 teams.  Player-plus-pick and pick-for-player are the two most
common dynasty trade shapes, and neither was proposable.

The second half of the same repair is the market-evidence guard.  Once
picks became resolvable, 478 of those 480 trades contained a 2029 pick,
because the ingestion path copies a source's nearest published year
onto years it never priced: a 2029 first's ``ktc`` / ``idpTradeCalc``
numbers are byte-identical to the 2028 first's, while our board applies
another year of discount.  That gap is one fabricated number compared
with one real one, not an arbitrage signal.
"""

from __future__ import annotations

from src.trade import finder as F


def _contract() -> dict:
    """A minimal contract carrying the shapes this repair depends on."""
    players = {
        "Star WR": {
            "_finalAdjusted": 7000,
            "_canonicalSiteValues": {"ktcSfTep": 7000},
            "_sites": 2,
        },
        "Good RB": {
            "_finalAdjusted": 5600,
            "_canonicalSiteValues": {"ktcSfTep": 4600},
            "_sites": 2,
        },
        "Depth WR": {
            "_finalAdjusted": 3000,
            "_canonicalSiteValues": {"ktcSfTep": 2900},
            "_sites": 2,
        },
        "2026 Pick 1.06": {
            "_finalAdjusted": 4900,
            "_canonicalSiteValues": {"ktcSfTep": 5600},
            "_sites": 2,
        },
        "2027 Mid 1st": {
            "_finalAdjusted": 5600,
            "_canonicalSiteValues": {"ktcSfTep": 5579},
            "_sites": 2,
        },
        # The fabricated year: its market number is a copy of 2028's
        # while the board discounts it another year.
        "2029 Mid 1st": {
            "_finalAdjusted": 2400,
            "_canonicalSiteValues": {"ktcSfTep": 4578},
            "_sites": 1,
        },
    }
    rows = [
        {"displayName": "Star WR", "position": "WR", "rankDerivedValue": 7000},
        {"displayName": "Good RB", "position": "RB", "rankDerivedValue": 5600},
        {"displayName": "Depth WR", "position": "WR", "rankDerivedValue": 3000},
        {"displayName": "2026 Pick 1.06", "position": "PICK", "rankDerivedValue": 4900},
        {"displayName": "2027 Mid 1st", "position": "PICK", "rankDerivedValue": 5600},
        {"displayName": "2029 Mid 1st", "position": "PICK", "rankDerivedValue": 2400},
    ]
    return {
        "players": players,
        "playersArray": rows,
        # The published per-market pick board: 2026-2028 only, exactly
        # like the live contract.
        "pickAnchors": {
            "ktc": {"2026 1.06": 5600, "2027 Mid 1st": 5579},
            "idpTradeCalc": {"2026 1.06": 5575},
        },
        "pickAliases": {"2026 Mid 1st": "2026 Pick 1.06"},
        "sleeper": {
            "teams": [
                {
                    "name": "Mine",
                    "players": ["Star WR", "Depth WR"],
                    # Sleeper's roster spelling, not the board's.
                    "picks": ["2026 1st", "2027 1st", "2027 1st", "2029 1st"],
                },
                {
                    "name": "Theirs",
                    "players": ["Good RB"],
                    "picks": [],
                },
            ]
        },
    }


def _pool_by_name(contract: dict) -> dict[str, F.Asset]:
    pool = F.build_asset_pool(
        contract["players"],
        market_top_n=150,
        board_values=F.board_values_from_contract(contract),
        positions=F.positions_from_contract(contract),
        pick_market_keys=F.pick_market_keys_from_contract(contract),
    )
    return {a.name: a for a in pool}


class TestRosterResolution:
    def test_a_teams_picks_resolve_onto_the_board(self):
        c = _contract()
        roster = F._resolve_roster("Mine", c["sleeper"]["teams"], _pool_by_name(c), c["pickAliases"])
        names = {a.name for a in roster}
        assert "2026 Pick 1.06" in names, "current-year pick missing from the roster"
        assert "2027 Mid 1st" in names, "future-year pick missing from the roster"

    def test_players_are_still_resolved(self):
        c = _contract()
        roster = F._resolve_roster("Mine", c["sleeper"]["teams"], _pool_by_name(c), c["pickAliases"])
        assert {"Star WR", "Depth WR"} <= {a.name for a in roster}

    def test_duplicate_pick_labels_collapse_to_one_asset(self):
        # The team holds two 2027 firsts.  The board prices a TIER, not
        # an owner, so both resolve to one row — emitting it twice would
        # let the generators build "2027 Mid 1st + 2027 Mid 1st" out of
        # a single priced asset.
        c = _contract()
        roster = F._resolve_roster("Mine", c["sleeper"]["teams"], _pool_by_name(c), c["pickAliases"])
        assert sum(1 for a in roster if a.name == "2027 Mid 1st") == 1


class TestPickMarketEvidence:
    def test_a_pick_no_market_priced_carries_no_market_value(self):
        c = _contract()
        pool = _pool_by_name(c)
        # 2029 has no pickAnchors entry in any market, so its market
        # number is not an observation and cannot anchor an arbitrage.
        assert "2029 Mid 1st" not in pool

    def test_picks_the_market_did_price_keep_their_anchor(self):
        c = _contract()
        pool = _pool_by_name(c)
        assert pool["2026 Pick 1.06"].has_market
        assert pool["2027 Mid 1st"].has_market

    def test_the_guard_is_disabled_without_anchors(self):
        # Older fixtures / raw payloads carry no ``pickAnchors``; the
        # guard must not silently delete their picks.
        c = _contract()
        assert F.pick_market_keys_from_contract({}) is None
        pool = F.build_asset_pool(
            c["players"],
            market_top_n=150,
            board_values=F.board_values_from_contract(c),
            positions=F.positions_from_contract(c),
            pick_market_keys=None,
        )
        assert any(a.name == "2029 Mid 1st" for a in pool)


class TestTradesContainPicks:
    def test_at_least_one_returned_trade_contains_a_pick(self):
        c = _contract()
        out = F.find_trades(
            c["players"], "Mine", ["Theirs"], c["sleeper"]["teams"], contract=c
        )
        with_pick = [
            t
            for t in out["trades"]
            if any(a["position"] == "PICK" for a in [*t["give"], *t["receive"]])
        ]
        assert with_pick, "no returned trade contains a pick"

    def test_unpriced_picks_are_reported_not_hidden(self):
        c = _contract()
        out = F.find_trades(
            c["players"], "Mine", ["Theirs"], c["sleeper"]["teams"], contract=c
        )
        meta = out["metadata"]
        assert meta["picksWithoutMarketAnchor"] == 1
        assert meta["picksWithoutMarketAnchorNames"] == ["2029 Mid 1st"]
