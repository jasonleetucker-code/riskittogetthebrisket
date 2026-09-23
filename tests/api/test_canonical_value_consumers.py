"""One canonical model value, one canonical KTC Market — everywhere.

Owner directive 2026-09-23: rankings, trade calculator, APIs and player pages
consume ONE model value (``rankDerivedValue``) and every market comparison
uses ONE KTC Market (``src/sources/ktc_market.py``).  Built from a synthetic
payload (no live board) so it holds in the hard gate.
"""

from __future__ import annotations

from src.api.data_contract import build_api_data_contract
from src.league_intel.values import build_player_values
from src.sources.ktc_market import KTC_MARKET_KEY, ktc_market_for_row, market_raw_value
from src.trade.finder import board_values_from_contract


def _payload() -> dict:
    players = {}
    specs = [
        ("Alpha QB", "QB", 9999, 9500, 9800, 9990),
        ("Beta WR", "WR", 7000, 6200, 6700, 6900),
        ("Gamma RB", "RB", 5000, 4400, 4800, 5100),
        ("Delta TE", "TE", 3000, None, 2900, 3100),
    ]
    for name, pos, crowd, trades, market, idptc in specs:
        sites = {"ktcCrowdSfTep": crowd, "ktcCrowdTradesSfTep": market, "idpTradeCalc": idptc}
        if trades is not None:
            sites["ktcTradesSfTep"] = trades
        players[name] = {
            "_composite": crowd,
            "_rawComposite": crowd,
            "_finalAdjusted": crowd,
            "_sites": len(sites),
            "position": pos,
            "team": "FA",
            "_canonicalSiteValues": sites,
        }
    players["Linebacker"] = {
        "_composite": 4000,
        "position": "LB",
        "team": "FA",
        "_canonicalSiteValues": {"idpTradeCalc": 4000},
    }
    return {
        "players": players,
        "sites": [{"key": "ktcCrowdSfTep"}, {"key": "idpTradeCalc"}],
        "maxValues": {"ktcCrowdSfTep": 9999, "idpTradeCalc": 9999},
        "sleeper": {"positions": {n: p["position"] for n, p in players.items()}},
    }


def _contract() -> dict:
    return build_api_data_contract(_payload(), csv_root=None)


def test_rankings_api_and_legacy_view_carry_the_same_model_value():
    contract = _contract()
    for row in contract["playersArray"]:
        rdv = row.get("rankDerivedValue")
        legacy = contract["players"].get(row.get("legacyRef") or row["displayName"]) or {}
        if rdv is None:
            continue
        assert row["values"]["overall"] == rdv
        assert row["values"]["displayValue"] == rdv
        assert legacy.get("rankDerivedValue") == rdv


def test_trade_calculator_reads_the_canonical_model_value():
    contract = _contract()
    board = board_values_from_contract(contract)
    for row in contract["playersArray"]:
        rdv = row.get("rankDerivedValue")
        name = row.get("canonicalName") or row.get("displayName")
        if rdv is None or name not in board:
            continue
        assert board[name] == int(rdv)


def test_market_everywhere_is_the_canonical_ktc_market():
    contract = _contract()
    checked = 0
    for row in contract["playersArray"]:
        block = ktc_market_for_row(row)
        sites = row.get("canonicalSiteValues") or {}
        # The block IS KTC's published Crowd+Trades — nothing blended in.
        assert block.get("value") == market_raw_value(sites)
        pv = build_player_values(row)
        if row.get("assetClass") == "offense":
            # league_intel's "market value" is the same canonical KTC Market.
            assert pv.market_value == block.get("value")
            checked += 1
        if str(row.get("position")).upper() in {"DL", "LB", "DB"}:
            assert block.get("value") is None
            assert row.get("marketGapValueRatio") is None
        if row.get("rankDerivedValue") is not None:
            assert pv.consensus_value == row["rankDerivedValue"]
    assert checked >= 3
    assert KTC_MARKET_KEY == "ktcCrowdTradesSfTep"
