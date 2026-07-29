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


class TestUnpricedCountUsesTheCompositeScale:
    """2026-07-29 audit.  The unpriced-asset filter necessarily runs on
    COMPOSITE values (these rows have no board value — that is what makes
    them unpriced), but it was gating them with the BOARD-scale
    ``MIN_ASSET_VALUE`` (700).  Composite runs ~1.131x the board, so the
    board-scale gate admitted assets the composite-scale one would not:
    202 on the live payload where ``build_asset_pool``'s own docstring
    says 189.
    """

    def test_composite_threshold_is_the_inverted_k(self):
        from src.trade.finder import (
            _MIN_ASSET_VALUE_COMPOSITE_SCALE,
            BOARD_TO_COMPOSITE_K,
        )

        assert _MIN_ASSET_VALUE_COMPOSITE_SCALE == round(MIN_ASSET_VALUE / BOARD_TO_COMPOSITE_K)
        # The pre-migration composite gate, recovered exactly.
        assert _MIN_ASSET_VALUE_COMPOSITE_SCALE == 800

    def test_asset_between_the_two_thresholds_is_not_counted(self):
        """A composite value of 750 clears the board-scale 700 but not the
        composite-scale 800.  It is the case that separated the two
        numbers, so it is the case worth pinning."""
        from src.trade.finder import _MIN_ASSET_VALUE_COMPOSITE_SCALE

        straddler = (MIN_ASSET_VALUE + _MIN_ASSET_VALUE_COMPOSITE_SCALE) // 2
        assert MIN_ASSET_VALUE < straddler < _MIN_ASSET_VALUE_COMPOSITE_SCALE

        players = {"Priced": _player(5000), "Straddler": _player(straddler)}
        teams = [
            {"name": "Me", "players": ["Priced"]},
            {"name": "Them", "players": ["Straddler"]},
        ]
        res = find_trades(
            players=players,
            my_team="Me",
            opponent_teams=["Them"],
            sleeper_teams=teams,
            contract=_contract({"Priced": 4000}),
        )
        assert (res.get("metadata") or {}).get("assetsUnpricedByBoard") == 0

    def test_asset_above_the_composite_threshold_is_still_counted(self):
        from src.trade.finder import _MIN_ASSET_VALUE_COMPOSITE_SCALE

        players = {
            "Priced": _player(5000),
            "Real": _player(_MIN_ASSET_VALUE_COMPOSITE_SCALE + 50),
        }
        teams = [
            {"name": "Me", "players": ["Priced"]},
            {"name": "Them", "players": ["Real"]},
        ]
        res = find_trades(
            players=players,
            my_team="Me",
            opponent_teams=["Them"],
            sleeper_teams=teams,
            contract=_contract({"Priced": 4000}),
        )
        assert (res.get("metadata") or {}).get("assetsUnpricedByBoard") == 1


class TestOffenseOnlyValueIsBoardScale:
    """2026-07-29 audit.  ``_offenseOnlyFinalAdjusted`` is mirrored from
    ``offenseOnlyRankDerivedValue`` (data_contract.py) — the IDP-disabled
    run of the SAME pipeline — so it is BOARD-scale, measured at median
    0.994x ``rankDerivedValue`` over 522 live assets.  The two branches
    had their scales backwards: the board path discarded it as though the
    board had no offense-only variant, and the composite path consumed it
    alongside a 1.131x-scale model value.
    """

    def test_board_path_now_carries_the_offense_only_value(self):
        players = {"Star WR": _player(9000, ktc=9000)}
        players["Star WR"]["_offenseOnlyFinalAdjusted"] = 4100
        board = board_values_from_contract(_contract({"Star WR": 4321}))
        pool = build_asset_pool(players, market_top_n=0, board_values=board)
        assert [a.offense_only_model_value for a in pool] == [4100]

    def test_legacy_path_refuses_the_cross_scale_value(self):
        """On the composite path ``model_value`` is composite-scale, so
        consuming a board-scale offense-only value inside the same
        subtraction understated all-offense legs by ~12%.  Degrade to
        unavailable instead."""
        players = {"Star WR": _player(9000, ktc=9000)}
        players["Star WR"]["_offenseOnlyFinalAdjusted"] = 4100
        pool = build_asset_pool(players, market_top_n=0)
        assert [a.offense_only_model_value for a in pool] == [None]
        assert [a.model_value for a in pool] == [9000]

    def test_all_offense_trade_scores_off_the_offense_only_board(self):
        """End-to-end: with no IDP asset on either side, ``_score_trade``
        must consume the offense-only values, not the blended ones."""
        players = {
            "Mine": _player(6000, ktc=6000),
            "Theirs": _player(6000, ktc=6000),
        }
        players["Mine"]["_offenseOnlyFinalAdjusted"] = 5000
        players["Theirs"]["_offenseOnlyFinalAdjusted"] = 5900
        board = board_values_from_contract(_contract({"Mine": 5200, "Theirs": 5200}))
        pool = {a.name: a for a in build_asset_pool(players, market_top_n=0, board_values=board)}
        # Blended board values tie; the offense-only board does not.
        assert pool["Mine"].model_value == pool["Theirs"].model_value
        assert pool["Mine"].offense_only_model_value == 5000
        assert pool["Theirs"].offense_only_model_value == 5900


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
