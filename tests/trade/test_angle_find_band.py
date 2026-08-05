"""/api/angle/find prices its cross-market subtraction with a band.

Audit finding W27-F004 (root cause R7).

The cross-market rewiring covered `/api/angle/packages` and explicitly
exempted the 1-for-1 path on the grounds that only SUMS are dangerous.
There is no sum here, but there is still a cross-market SUBTRACTION and
the visibility gate is applied to it: selecting an IDP player returns a
candidate list that is almost entirely `idpTradeCalc` minus `ktcSfTep`,
against a default +/-5% gate that is narrower than the two boards' own
measured p10-p90 disagreement (0.886-1.083 over 475 shared players).
The response carried no band, no market stamp and no diagnostics —
unlike `/api/angle/packages`, which returns all three on the same data.

Same machinery, single-asset packages.  A single-asset `value_package`
total equals `_value_pair`'s market value exactly for every rankable row
on the live board, so the point estimates the gates use are unchanged;
what is added is the uncertainty around them.
"""

from __future__ import annotations

from src.trade.angle import find_angles

_TEAMS = [
    {"name": "Mine", "ownerId": "me", "rosterId": 1, "players": ["MyWr", "MyLb"]},
    {
        "name": "Theirs",
        "ownerId": "them",
        "rosterId": 2,
        "players": ["TheirWr", "TheirLb"],
    },
]


def _row(name: str, position: str, my_value: int, market_key: str, market: int) -> dict:
    return {
        "canonicalName": name,
        "displayName": name,
        "position": position,
        "rankDerivedValue": my_value,
        "canonicalSiteValues": {market_key: market},
    }


def _board() -> list[dict]:
    return [
        _row("MyWr", "WR", 5000, "ktcSfTep", 5000),
        _row("TheirWr", "WR", 5400, "ktcSfTep", 5100),
        _row("MyLb", "LB", 5000, "idpTradeCalc", 5000),
        _row("TheirLb", "LB", 5400, "idpTradeCalc", 3000),
    ]


def _find(selected: str) -> dict:
    return find_angles(_board(), selected, "me", _TEAMS, limit=50)


class TestSameMarketIsUnchanged:
    def test_offense_versus_offense_is_certain_and_carries_no_band(self):
        """An assumption-free comparison must not be suppressed."""
        res = _find("MyWr")
        names = [c["name"] for c in res["candidates"]]
        assert "TheirWr" in names
        got = next(c for c in res["candidates"] if c["name"] == "TheirWr")
        assert got["market_uncertainty_band"] == 0
        assert got["market_gain_low_pct"] == got["market_gain_high_pct"]

    def test_the_point_estimate_is_the_one_the_gates_always_used(self):
        res = _find("MyWr")
        got = next(c for c in res["candidates"] if c["name"] == "TheirWr")
        assert got["market_value"] == 5100
        assert got["market_gain_pct"] == 2.0


class TestCrossMarketCarriesItsUncertainty:
    def test_a_gain_inside_the_band_is_withheld_not_returned(self):
        """IDP-vs-offense at a 2% gain cannot be called against a 5% gate."""
        res = _find("MyLb")
        names = [c["name"] for c in res["candidates"]]
        assert "TheirWr" not in names, "cross-market verdict served as certain"
        assert res["market_diagnostics"]["withheld_uncertain"] >= 1

    def test_the_reason_is_named_rather_than_the_row_vanishing(self):
        res = _find("MyLb")
        reasons = res["market_diagnostics"]["reasons"]
        assert reasons, "a withheld candidate left no trace"
        assert any("uncertainty band" in r for r in reasons)
        assert any("withheld" in w for w in res["warnings"])

    def test_a_same_market_comparison_is_assumption_free(self):
        """Both sides on IDPTC: the exchange rate cancels in the ratio.

        (a·k - b·k)/(b·k) = (a - b)/b, so `market_gain_pct` is
        scale-invariant and no exchange-rate assumption can flip the
        verdict — however wide each package's own band is.  Suppressing
        these would withhold a decision nothing could change.
        """
        res = _find("MyLb")
        got = next(c for c in res["candidates"] if c["name"] == "TheirLb")
        assert got["market_verdict_basis"] == "same_market"
        assert got["market_gain_low_pct"] == got["market_gain_high_pct"]

    def test_a_near_gate_same_market_comparison_is_not_withheld(self):
        """The case the band was wrongly eating: +2% IDPTC vs a 5% gate."""
        board = [
            _row("MyLb", "LB", 5000, "idpTradeCalc", 5000),
            _row("NearLb", "LB", 5400, "idpTradeCalc", 5100),
        ]
        teams = [
            {"name": "Mine", "ownerId": "me", "rosterId": 1, "players": ["MyLb"]},
            {"name": "Theirs", "ownerId": "them", "rosterId": 2, "players": ["NearLb"]},
        ]
        res = find_angles(board, "MyLb", "me", teams, limit=50)
        assert "NearLb" in [c["name"] for c in res["candidates"]]

    def test_the_cross_market_case_still_carries_a_range(self):
        res = _find("MyLb")
        assert res["market_diagnostics"]["withheld_uncertain"] >= 1


class TestProvenanceIsStamped:
    def test_the_selected_side_names_its_market(self):
        res = _find("MyLb")
        assert res["selected"]["market"] == "idpTradeCalc"
        assert "market_normalization_version" in res["selected"]

    def test_every_candidate_carries_its_gain_range(self):
        res = _find("MyWr")
        assert res["candidates"]
        for c in res["candidates"]:
            assert "market_gain_low_pct" in c
            assert "market_gain_high_pct" in c
            assert "market_uncertainty_band" in c
