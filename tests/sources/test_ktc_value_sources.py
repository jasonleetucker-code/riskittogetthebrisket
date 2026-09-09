from __future__ import annotations

import asyncio

import pytest

from src.sources.ktc_value_sources import (
    KTC_CANONICAL_MARKET_SOURCE,
    KTC_CROWD,
    KTC_CROWD_TRADES,
    KTC_TRADES,
    KtcValueSourceCapture,
    KtcValueSourceError,
    crowd_trade_divergence,
    classify_control_label,
    observations_from_players_array,
    select_value_source,
    validate_capture_set,
)


def test_crowd_trades_is_the_single_declared_market_source():
    assert KTC_CANONICAL_MARKET_SOURCE == KTC_CROWD_TRADES


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Crowdsourced", KTC_CROWD),
        ("Tradesourced", KTC_TRADES),
        ("Crowd+Trades", KTC_CROWD_TRADES),
        ("Crowd + Trades", KTC_CROWD_TRADES),
        ("Crowdsourced Values", KTC_CROWD),
        ("Tradesourced Values", KTC_TRADES),
        ("Crowd + Trade Values", KTC_CROWD_TRADES),
    ],
)
def test_visible_labels_map_to_stable_source_types(label, expected):
    assert classify_control_label(label) == expected


def test_selected_board_preserves_base_tepp_rank_value_and_identity():
    rows = observations_from_players_array(
        [
            {
                "playerID": 101,
                "playerName": "Brock Bowers",
                "position": "TE",
                "superflexValues": {
                    "value": 8200,
                    "rank": 8,
                    "tepp": {"value": 9900, "rank": 4},
                },
            },
            {
                "playerID": 1709,
                "playerName": "2027 Mid 3rd",
                "position": "RDP",
                "superflexValues": {
                    "value": 1800,
                    "rank": 220,
                    "tepp": {"value": 1800, "rank": 220},
                },
            },
        ]
    )
    assert rows[0].name == "Brock Bowers"
    assert rows[0].player_id == 101
    assert rows[0].base_value == 8200
    assert rows[0].base_rank == 8
    assert rows[0].tepp_value == 9900
    assert rows[0].tepp_rank == 4
    assert rows[1].position == "RDP"


def test_explicit_fields_keep_crowd_trades_and_combined_distinct():
    rows = [
        {
            "playerID": 1743,
            "playerName": "TreVeyon Henderson",
            "position": "RB",
            "superflexValues": {
                "value": 4839,
                "rank": 64,
                "blendValue": 4926,
                "blendRank": 62,
                "vftValue": 5014,
                "vftRank": 57,
                "tepp": {
                    "value": 4839,
                    "rank": 67,
                    "blendValue": 4926,
                    "blendRank": 65,
                    "vftValue": 5014,
                    "vftRank": 61,
                },
            },
        }
    ]
    crowd = observations_from_players_array(rows, KTC_CROWD)[0]
    combined = observations_from_players_array(rows, KTC_CROWD_TRADES)[0]
    trades = observations_from_players_array(rows, KTC_TRADES)[0]
    assert crowd.tepp_value == 4839
    assert combined.tepp_value == 4926
    assert trades.tepp_value == 5014
    assert (crowd.tepp_rank, combined.tepp_rank, trades.tepp_rank) == (67, 65, 61)


def test_missing_tradesourced_value_is_missing_never_zero():
    rows = observations_from_players_array(
        [
            {
                "playerID": 202,
                "playerName": "Low-volume Rookie",
                "position": "WR",
                "superflexValues": {
                    "value": None,
                    "rank": None,
                    "tepp": {"value": 0, "rank": None},
                },
            }
        ]
    )
    assert rows[0].base_value is None
    assert rows[0].tepp_value is None


def _capture(source, rows, *, control_value):
    observations = observations_from_players_array(rows, source)
    return KtcValueSourceCapture(
        value_source=source,
        selected_label={
            KTC_CROWD: "Crowdsourced",
            KTC_TRADES: "Tradesourced",
            KTC_CROWD_TRADES: "Crowd+Trades",
        }[source],
        selected_value=control_value,
        page_url="https://keeptradecut.com/dynasty-rankings",
        captured_at="2026-09-08T22:00:00+00:00",
        superflex=True,
        te_premium="TE++",
        te_premium_level=2,
        row_count=len(observations),
        priced_count=sum(1 for row in observations if row.tepp_value is not None),
        content_hash=f"hash-{source}",
        rows=observations,
    )


def test_capture_set_rejects_selector_that_only_changes_the_label():
    row = {
        "playerID": 1,
        "playerName": "Same",
        "position": "RB",
        "superflexValues": {"value": 100, "tepp": {"value": 100, "rank": 1}},
    }
    captures = {
        KTC_CROWD: _capture(KTC_CROWD, [row], control_value="crowd"),
        KTC_TRADES: _capture(KTC_TRADES, [row], control_value="trades"),
        KTC_CROWD_TRADES: _capture(KTC_CROWD_TRADES, [row], control_value="both"),
    }
    captures = {
        key: KtcValueSourceCapture(**{**capture.__dict__, "content_hash": "identical"})
        for key, capture in captures.items()
    }
    with pytest.raises(KtcValueSourceError, match="byte-equivalent"):
        validate_capture_set(captures)


def test_crowd_trade_divergence_is_numeric_without_an_invented_threshold():
    crowd = _capture(
        KTC_CROWD,
        [
            {
                "playerID": 10,
                "playerName": "Trade Premium",
                "position": "RB",
                "superflexValues": {"value": 4500, "tepp": {"value": 5000, "rank": 50}},
            },
            {
                "playerID": 11,
                "playerName": "Missing Trades",
                "position": "WR",
                "superflexValues": {"value": 3000, "tepp": {"value": 3000, "rank": 100}},
            },
        ],
        control_value="crowd",
    )
    trades = _capture(
        KTC_TRADES,
        [
            {
                "playerID": 10,
                "playerName": "Trade Premium",
                "position": "RB",
                # Tradesourced carries its native value under vftValue/vftRank,
                # not value/rank -- KTC ships all three source-native fields
                # on the same player object (see observations_from_players_array).
                "superflexValues": {
                    "vftValue": 5000,
                    "tepp": {"vftValue": 5500, "vftRank": 45},
                },
            }
        ],
        control_value="trades",
    )

    by_name = {row.name: row for row in crowd_trade_divergence(crowd, trades)}
    premium = by_name["Trade Premium"]
    assert premium.delta == 500
    assert premium.percent_delta == pytest.approx(10.0)
    assert premium.direction == "trade_premium"

    missing = by_name["Missing Trades"]
    assert missing.trades_value is None
    assert missing.delta is None
    assert missing.percent_delta is None
    assert missing.direction is None


class _OptionLocator:
    def __init__(self, select):
        self.select = select

    async def text_content(self):
        return self.select["options"][self.select["selected"]]["text"]


class _SelectLocator:
    def __init__(self, page, index):
        self.page = page
        self.index = index

    async def select_option(self, *, index):
        self.page.controls[self.index]["selected"] = index

    async def input_value(self):
        control = self.page.controls[self.index]
        return control["options"][control["selected"]]["value"]

    def locator(self, selector):
        assert selector == "option:checked"
        return _OptionLocator(self.page.controls[self.index])


class _SelectCollection:
    def __init__(self, page):
        self.page = page

    def nth(self, index):
        return _SelectLocator(self.page, index)


class _FakePage:
    def __init__(self, controls):
        self.controls = controls

    async def evaluate(self, _script):
        return [
            {
                "index": i,
                "value": control["options"][control["selected"]]["value"],
                "options": [
                    {
                        "optionIndex": j,
                        "text": option["text"],
                        "value": option["value"],
                    }
                    for j, option in enumerate(control["options"])
                ],
            }
            for i, control in enumerate(self.controls)
        ]

    def locator(self, selector):
        assert selector == "select"
        return _SelectCollection(self)

    async def wait_for_timeout(self, _ms):
        return None


def test_selector_drives_visible_three_mode_control_not_a_guessed_parameter():
    page = _FakePage(
        [
            {
                "selected": 0,
                "options": [
                    {"text": "50", "value": "50"},
                    {"text": "100", "value": "100"},
                ],
            },
            {
                "selected": 0,
                "options": [
                    {"text": "Crowdsourced", "value": "crowd"},
                    {"text": "Tradesourced", "value": "trades"},
                    {"text": "Crowd+Trades", "value": "both"},
                ],
            },
        ]
    )
    selected = asyncio.run(select_value_source(page, KTC_CROWD_TRADES))
    assert selected == {"label": "Crowd+Trades", "value": "both"}
    assert page.controls[1]["selected"] == 2


def test_selector_fails_closed_when_three_mode_control_disappears():
    page = _FakePage(
        [
            {
                "selected": 0,
                "options": [
                    {"text": "Crowdsourced", "value": "crowd"},
                    {"text": "Tradesourced", "value": "trades"},
                ],
            }
        ]
    )
    with pytest.raises(KtcValueSourceError, match="three-mode Value Source control not found"):
        asyncio.run(select_value_source(page, KTC_CROWD_TRADES))
