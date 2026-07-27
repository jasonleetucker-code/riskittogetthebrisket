"""The trade finder values assets off the canonical board (F-6).

Collaborative audit, finding K.  ``finder.py`` used to read
``players[name]["_finalAdjusted"]`` — a verbatim deep copy of the raw
scraper composite — while ``/rankings``, ``suggestions.py``,
``angle.py``, ``waiver.py`` and ``monte_carlo.py`` all read
``rankDerivedValue``.  The engine's premise is arbitrage between OUR
board and the retail market, so reading a board the product never shows
made the core comparison the wrong one.

These tests pin the migrated behaviour and the two things that make it
safe: the board wins over the composite, and assets the board declines
to price are dropped LOUDLY.
"""

from __future__ import annotations

from src.trade.finder import (
    MIN_ASSET_VALUE,
    SINGLE_SOURCE_DISCOUNT,
    board_values_from_contract,
    build_asset_pool,
    find_trades,
)


def _player(composite: int, *, pos: str = "WR", sites: int = 4, ktc: int | None = None):
    return {
        "position": pos,
        "team": "KC",
        "_finalAdjusted": composite,
        "_sites": sites,
        "_canonicalSiteValues": {"ktcSfTep": ktc if ktc is not None else composite},
    }


def _contract(board: dict[str, int]):
    return {
        "playersArray": [
            {"canonicalName": name, "legacyRef": name, "rankDerivedValue": value}
            for name, value in board.items()
        ]
    }


class TestTheBoardWinsOverTheComposite:
    def test_pool_uses_rank_derived_value_not_the_composite(self):
        players = {"Star WR": _player(9000, ktc=9000)}
        board = board_values_from_contract(_contract({"Star WR": 4321}))
        pool = build_asset_pool(players, market_top_n=0, board_values=board)
        assert [a.model_value for a in pool] == [4321]

    def test_without_a_contract_the_legacy_composite_still_works(self):
        """Fixtures and raw-payload callers keep working."""
        players = {"Star WR": _player(9000, ktc=9000)}
        pool = build_asset_pool(players, market_top_n=0)
        assert [a.model_value for a in pool] == [9000]

    def test_board_lookup_resolves_via_legacy_ref(self):
        """``players`` is keyed by the legacy scraper name, which is not
        always the canonical one."""
        players = {"D.J. Moore": _player(5000)}
        contract = {
            "playersArray": [
                {
                    "canonicalName": "DJ Moore",
                    "legacyRef": "D.J. Moore",
                    "rankDerivedValue": 6100,
                }
            ]
        }
        pool = build_asset_pool(
            players, market_top_n=0, board_values=board_values_from_contract(contract)
        )
        assert [a.model_value for a in pool] == [6100]


class TestTheSingleSourceHaircutIsNotDoubleApplied:
    def test_board_path_applies_no_local_haircut(self):
        """``rankDerivedValue`` already carries the pipeline's 0.30
        retention. Applying the local 0.88 on top would be the double
        discount the original F-6 write-up wrongly claimed already
        existed."""
        players = {"Lonely": _player(5000, sites=1)}
        board = board_values_from_contract(_contract({"Lonely": 2000}))
        pool = build_asset_pool(players, market_top_n=0, board_values=board)
        assert [a.model_value for a in pool] == [2000]

    def test_legacy_path_still_applies_it(self):
        """Deleting it outright would have left single-source assets
        undiscounted on the composite path — a live distortion introduced
        by a fix."""
        players = {"Lonely": _player(5000, sites=1)}
        pool = build_asset_pool(players, market_top_n=0)
        assert [a.model_value for a in pool] == [int(5000 * SINGLE_SOURCE_DISCOUNT)]


class TestUnpricedAssetsLeaveLoudly:
    def test_assets_absent_from_the_board_are_dropped(self):
        players = {"Priced": _player(5000), "Unpriced": _player(5000)}
        board = board_values_from_contract(_contract({"Priced": 4000}))
        pool = build_asset_pool(players, market_top_n=0, board_values=board)
        assert [a.name for a in pool] == ["Priced"]

    def test_the_drop_is_reported_not_merely_performed(self):
        """A silently shorter list reads as 'nothing available' rather
        than 'not priced'. On a real payload this is ~189 assets."""
        players = {
            "Priced": _player(5000),
            "Unpriced A": _player(MIN_ASSET_VALUE + 500),
            "Unpriced B": _player(MIN_ASSET_VALUE + 900),
        }
        teams = [
            {"name": "Me", "players": ["Priced"]},
            {"name": "Them", "players": ["Unpriced A"]},
        ]
        res = find_trades(
            players=players,
            my_team="Me",
            opponent_teams=["Them"],
            sleeper_teams=teams,
            contract=_contract({"Priced": 4000}),
        )
        meta = res.get("metadata") or {}
        assert meta.get("valueSource") == "rankDerivedValue"
        assert meta.get("assetsUnpricedByBoard") == 2
        assert any("no canonical board value" in w for w in res.get("warnings") or [])

    def test_cheap_unpriced_assets_are_not_counted_as_a_loss(self):
        """Only assets that would have cleared the gate are worth
        reporting; counting every unranked scrub would make the number
        meaningless."""
        players = {"Priced": _player(5000), "Scrub": _player(MIN_ASSET_VALUE - 100)}
        teams = [
            {"name": "Me", "players": ["Priced"]},
            {"name": "Them", "players": ["Scrub"]},
        ]
        res = find_trades(
            players=players,
            my_team="Me",
            opponent_teams=["Them"],
            sleeper_teams=teams,
            contract=_contract({"Priced": 4000}),
        )
        assert (res.get("metadata") or {}).get("assetsUnpricedByBoard") == 0

    def test_no_contract_means_no_drop_and_no_claim(self):
        players = {"A": _player(5000), "B": _player(5000)}
        teams = [
            {"name": "Me", "players": ["A"]},
            {"name": "Them", "players": ["B"]},
        ]
        res = find_trades(
            players=players,
            my_team="Me",
            opponent_teams=["Them"],
            sleeper_teams=teams,
        )
        meta = res.get("metadata") or {}
        assert meta.get("valueSource") == "rawComposite"
        assert meta.get("assetsUnpricedByBoard") == 0


class TestBoardDeltaSignIsHonest:
    def test_a_loss_is_not_described_as_a_gain(self):
        """``_build_summary`` hard-coded a ``+`` sign, so a -100 delta
        rendered as 'you gain -100 board value (+-2%)'. Nothing in the
        permitted [MAX_BOARD_LOSS, 0) band reaches a caller today, but
        the formatter must not be the thing standing between a loss and
        a claimed win."""
        from src.trade.finder import _build_summary

        summary = _build_summary(
            edge_label="Slight Edge",
            board_delta=-100,
            board_gain_pct=-0.02,
            opp_appeal=0.25,
            coverage="full",
            confidence_tier="high",
            pkg_size_str="1-for-1",
        )
        assert "you gain -100" not in summary
        assert "you give up 100" in summary
        assert "+-" not in summary

    def test_a_gain_still_reads_as_a_gain(self):
        from src.trade.finder import _build_summary

        summary = _build_summary(
            edge_label="Strong Edge",
            board_delta=500,
            board_gain_pct=0.12,
            opp_appeal=0.25,
            coverage="full",
            confidence_tier="high",
            pkg_size_str="1-for-1",
        )
        assert "you gain 500" in summary
        assert "+12%" in summary


class TestDeadConstantsAreGone:
    def test_removed_constants_are_not_re_exported(self):
        """``MAX_PACKAGE_SIZE`` and ``PARTIAL_MARKET_MAX_RANK`` were
        exported but never read — the code that consulted the latter was
        collapsed by WS-J F-7."""
        import src.trade.finder as finder

        for name in ("MAX_PACKAGE_SIZE", "PARTIAL_MARKET_MAX_RANK", "PARTIAL_KTC_MAX_RANK"):
            assert not hasattr(finder, name), (
                f"{name} is exported again but nothing reads it; an exported "
                "constant nothing consults is a promise the code does not keep"
            )
