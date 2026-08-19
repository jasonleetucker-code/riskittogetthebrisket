"""The arbitrage finder must reach IDP, and must say so when it cannot.

WHY THIS EXISTS
===============
``build_asset_pool`` routes every asset to the retail board its
counterparty would actually consult — ``idpTradeCalc`` for IDP,
``ktcSfTep`` for offense and picks (WS-J F-3).  It picked the branch by
reading ``pdata["position"]`` off the legacy ``players`` dict.

That dict has **no ``position`` key**.  Measured on the pinned
2026-07-30 contract: **0 of 1093** entries carry one.  So
``_norm_pos("")`` was falsy for every asset, the IDP branch was
unreachable, and every defender was priced against KTC — which
publishes no IDP.  They scored ``market_value = None`` and were dropped
before scoring.  In an IDP league the finder silently returned
offense-only results.

Measured effect of the fix on the same payload:

    pool 150 -> 300 assets
    IDP in pool 0 -> 150
    market sources {ktcSfTep: 132, ktc: 18}
                -> {ktcSfTep: 132, ktc: 18, idpTradeCalc: 150}

WHAT MAKES THIS CLASS 7 RATHER THAN A PLAIN BUG
===============================================
A join that returns nothing looks exactly like a join with nothing to
return.  The pool was not empty — it was full of offense — so every
surface downstream looked healthy.  ``marketCoveragePercent`` reported
**100%**, because the unpriced defenders had already been filtered out
before coverage was computed.

And the detector written to catch precisely this failure read the SAME
absent key::

    league_has_idp = any(is_idp_position(p.get("position", "")) ...)

so it was permanently ``False`` and could never fire.  That is the part
worth keeping a test on: a detector fed the broken input is not a
detector, and both halves are pinned below.

NOT ``livedata``-marked: synthetic rows, pure logic, must block.
"""

from __future__ import annotations

import unittest
from typing import Any

from src.trade.finder import (
    is_idp_position,
    build_asset_pool,
    board_values_from_contract,
    find_trades,
    positions_from_contract,
)
from src.utils.name_clean import normalize_position as _norm_pos


def _contract() -> dict[str, Any]:
    """A contract with offense and IDP rows, shaped like the live one.

    Crucially the legacy ``players`` dict carries NO ``position`` key —
    that is the live shape, and a fixture that supplied one would make
    this whole test vacuous.
    """
    rows: list[dict[str, Any]] = []
    players: dict[str, Any] = {}
    for i in range(1, 21):
        name = f"Receiver {i:02d}"
        rows.append(
            {
                "canonicalName": name,
                "displayName": name,
                "legacyRef": name,
                "position": "WR",
                "assetClass": "offense",
                "rankDerivedValue": 8000 - i * 100,
            }
        )
        players[name] = {
            "_sites": 5,
            "_canonicalSiteValues": {"ktcSfTep": 7900 - i * 100},
        }
    for i in range(1, 21):
        name = f"Defender {i:02d}"
        rows.append(
            {
                "canonicalName": name,
                "displayName": name,
                "legacyRef": name,
                "position": "LB",
                "assetClass": "idp",
                "rankDerivedValue": 6000 - i * 100,
            }
        )
        players[name] = {
            "_sites": 4,
            "_canonicalSiteValues": {"idpTradeCalc": 5900 - i * 100},
        }
    return {"playersArray": rows, "players": players}


class TestPositionsFromContract(unittest.TestCase):
    def test_the_legacy_players_dict_really_has_no_position(self) -> None:
        """Pins the premise. If this ever stops being true the fix is
        redundant — but so is the bug, and we should find out here.
        """
        contract = _contract()
        with_position = [
            name
            for name, p in contract["players"].items()
            if isinstance(p, dict) and p.get("position")
        ]
        self.assertEqual(
            with_position,
            [],
            msg="fixture drifted: the live players dict carries no position key",
        )

    def test_positions_resolve_from_the_contract(self) -> None:
        pos = positions_from_contract(_contract())
        self.assertEqual(pos["Defender 01"], "LB")
        self.assertEqual(pos["Receiver 01"], "WR")

    def test_keyed_the_same_way_as_board_values(self) -> None:
        """The two lookups must agree about which player they mean.

        ``build_asset_pool`` resolves a board value and a position for
        the same asset from two different maps; if they keyed
        differently, an asset could get one and not the other.
        """
        contract = _contract()
        self.assertEqual(
            set(positions_from_contract(contract)),
            set(board_values_from_contract(contract)),
        )


class TestIdpReachesThePool(unittest.TestCase):
    def test_idp_assets_are_priced_and_kept(self) -> None:
        contract = _contract()
        pool = build_asset_pool(
            contract["players"],
            market_top_n=0,
            board_values=board_values_from_contract(contract),
            positions=positions_from_contract(contract),
        )
        idp = [a for a in pool if is_idp_position(a.position)]
        self.assertTrue(idp, "no IDP asset survived into the pool")
        self.assertTrue(
            all(a.has_market for a in idp),
            msg=(
                "an IDP asset has no market value — it was routed to KTC, which "
                "publishes no IDP, instead of to idpTradeCalc"
            ),
        )
        self.assertEqual(
            {a.market_source for a in idp},
            {"idpTradeCalc"},
            msg="IDP assets must anchor on the IDP market, not the offense board",
        )

    def test_offense_still_anchors_on_ktc(self) -> None:
        """The routing must stay per-market, not flip wholesale."""
        contract = _contract()
        pool = build_asset_pool(
            contract["players"],
            market_top_n=0,
            board_values=board_values_from_contract(contract),
            positions=positions_from_contract(contract),
        )
        off = [a for a in pool if not is_idp_position(a.position)]
        self.assertTrue(off)
        self.assertEqual({a.market_source for a in off}, {"ktcSfTep"})


class TestIdpWarningCanActuallyFire(unittest.TestCase):
    """The detector must not read the same broken input it detects."""

    def test_warning_fires_when_an_idp_league_has_no_idp_market_data(self) -> None:
        contract = _contract()
        # Strip every IDP market value: the league still has defenders,
        # but none of them can be priced. That is exactly the state the
        # warning exists to announce.
        for name, p in contract["players"].items():
            if name.startswith("Defender"):
                p["_canonicalSiteValues"] = {}

        result = find_trades(
            players=contract["players"],
            my_team="A",
            opponent_teams=["B"],
            sleeper_teams=[
                {"name": "A", "players": ["Receiver 01"]},
                {"name": "B", "players": ["Defender 01"]},
            ],
            contract=contract,
        )
        warnings = " ".join(result.get("warnings") or [])
        self.assertIn(
            "IDP",
            warnings,
            msg=(
                "an IDP league with zero priced IDP assets produced no warning. "
                "league_has_idp reads positions — if it reads pdata['position'] "
                "again it is permanently False and this failure goes silent, "
                "which is the state this test exists to prevent."
            ),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
