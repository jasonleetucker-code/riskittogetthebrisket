"""One canonical dynasty value per asset — W29-F001 / W29-F002.

THE INVARIANT
─────────────
An asset's canonical value is a property of the ASSET, not of the
question being asked about it.  Context may change which assets are
relevant, how they are filtered, ranked, recommended or explained.  It
may not change what the asset is worth on the canonical board.

WHAT WAS MEASURED (2026-08-14, live contract, 1,093 rows)
──────────────────────────────────────────────────────────
``build_api_data_contract`` runs ``_compute_unified_rankings`` a SECOND
time with every IDP-scoped source disabled, and stamps the result on
each row as ``offenseOnlyRankDerivedValue``.  That is a second canonical
board, produced by the canonical function, on the canonical scale:

* 605 rows carry it; 507 are comparable with a priced canonical value;
* **491 of those 507 disagree** — up to 21.87%;
* the disagreement is not confined to defenders.  **Picks move most**
  (2026 Pick 2.06: 3,224 → 2,519).  A draft pick is neither an offensive
  player nor an IDP player, and its dynasty value cannot depend on
  which sources a *different* asset class was scored against;
* Travis Hunter measured 4,758 canonical vs 5,637 offense-only — the
  spread W29-F001 recorded from the other direction.

The switch is **per trade, not per league**::

    trade_simulator.py:209   offense_only = trade_has_resolved and not trade_has_idp
    suggestions.py:1789      _serialize_player(p, offense_only=_trade_is_idp_free(...))
    finder.py:689            if not trade_has_idp and a.offense_only_model_value is not None

So in ONE league, on ONE day, from ONE board, a player is worth one
number in a trade that happens to contain a defender and a different
number in a trade that does not — and in the simulator the substitution
is applied to the team's ENTIRE existing roster, not merely to the legs
being traded.  Neither number is labelled; both are served under the
canonical field names ``displayValue`` and ``modelValue``.

That is the definition of a second competing canonical truth, and the
owner ruling for B9 is that it may not survive.

WHY THESE TESTS ARE SHAPED THIS WAY
────────────────────────────────────
They assert the INVARIANT ("the same asset values the same regardless of
what else is in the trade"), never the absence of a particular field
name.  A test that merely banned ``offenseOnlyRankDerivedValue`` would
pass the day someone reintroduced the same second board under another
name, which is the failure mode this whole finding is an instance of.
"""

from __future__ import annotations

from src.api import terminal, trade_simulator
from src.canonical.player_valuation import rank_to_value
from src.trade import finder, suggestions


# ── Fixtures ─────────────────────────────────────────────────────────
#
# The offense-only value is deliberately set FAR from the canonical one
# (2,500 vs 4,000).  The live spread is up to 21.87%; an exaggerated
# fixture spread makes a substitution impossible to mistake for rounding
# and keeps the assertion readable.


def _row(name, rank, pos="WR", asset="offense", offense_only=None):
    row = {
        "displayName": name,
        "canonicalName": name,
        "legacyRef": name,
        "assetClass": asset,
        "position": pos,
        "pos": pos,
        "canonicalConsensusRank": rank,
        "rankChange": 0,
        "rankDerivedValue": int(rank_to_value(rank)),
        "values": {"full": int(rank_to_value(rank))},
    }
    if offense_only is not None:
        row["offenseOnlyRankDerivedValue"] = int(offense_only)
    return row


def _contract() -> dict:
    """Two offensive players, one pick, one defender.

    ``Wideout`` and ``Rookie Pick`` both carry an offense-only value that
    disagrees with canonical.  ``Linebacker`` exists purely so a caller
    can put an IDP asset into a trade and flip the engines' switch.
    """
    wr = _row("Wideout", 20, "WR", offense_only=2500)
    wr["rankDerivedValue"] = 4000
    wr["values"]["full"] = 4000

    pick = _row("2026 Pick 2.06", 40, "PICK", asset="pick", offense_only=2519)
    pick["rankDerivedValue"] = 3224
    pick["values"]["full"] = 3224

    return {
        "playersArray": [
            wr,
            pick,
            _row("Quarterback", 5, "QB"),
            _row("Linebacker", 60, "LB", asset="idp"),
        ],
        "sleeper": {
            "teams": [
                {
                    "ownerId": "o1",
                    "name": "Team Alpha",
                    "roster_id": 1,
                    "players": ["Wideout", "Quarterback"],
                    "picks": [],
                },
                {
                    "ownerId": "o2",
                    "name": "Team Bravo",
                    "roster_id": 2,
                    "players": ["Linebacker"],
                    "picks": [],
                },
            ],
        },
    }


def _value_of(result: dict, side: str, name: str) -> int:
    for asset in result[side]:
        if asset["name"] == name:
            return asset["value"]
    raise AssertionError(f"{name!r} not found in {side}: {result[side]}")


class TestTheSimulatorValuesAnAssetTheSameWay:
    """``/api/trade/simulate`` — the per-trade switch, at the boundary."""

    def test_a_player_is_worth_the_same_with_and_without_a_defender_in_the_trade(self):
        contract = _contract()
        team = terminal.resolve_team(contract, owner_id="o1", name=None)

        idp_free = trade_simulator.simulate_trade(
            contract,
            resolved_team=team,
            players_in=["Quarterback"],
            players_out=["Wideout"],
        )
        with_idp = trade_simulator.simulate_trade(
            contract,
            resolved_team=team,
            players_in=["Quarterback", "Linebacker"],
            players_out=["Wideout"],
        )

        assert _value_of(idp_free, "sending", "Wideout") == _value_of(
            with_idp, "sending", "Wideout"
        ), (
            "Wideout is worth a different number depending on whether an unrelated "
            "defender is also in the trade — two canonical values for one asset."
        )

    def test_a_pick_is_worth_the_same_with_and_without_a_defender_in_the_trade(self):
        """A pick is neither an offensive nor an IDP asset.

        It moved most of all on the live board (2026 Pick 2.06:
        3,224 → 2,519, −21.87%), which is what shows the mechanism is not
        "exclude IDP calibration from IDP-free trades" but a wholesale
        second board.
        """
        contract = _contract()
        team = terminal.resolve_team(contract, owner_id="o1", name=None)

        idp_free = trade_simulator.simulate_trade(
            contract,
            resolved_team=team,
            players_in=["2026 Pick 2.06"],
            players_out=["Wideout"],
        )
        with_idp = trade_simulator.simulate_trade(
            contract,
            resolved_team=team,
            players_in=["2026 Pick 2.06", "Linebacker"],
            players_out=["Wideout"],
        )

        assert _value_of(idp_free, "receiving", "2026 Pick 2.06") == _value_of(
            with_idp, "receiving", "2026 Pick 2.06"
        )

    def test_the_untraded_roster_is_not_repriced_by_the_trade_being_evaluated(self):
        """The substitution reached ``before_assets`` — the whole roster.

        Evaluating a trade is a read-only question about a hypothetical.
        It cannot change what the manager's existing roster is worth.
        """
        contract = _contract()
        team = terminal.resolve_team(contract, owner_id="o1", name=None)

        idp_free = trade_simulator.simulate_trade(
            contract,
            resolved_team=team,
            players_in=["Quarterback"],
            players_out=[],
        )
        with_idp = trade_simulator.simulate_trade(
            contract,
            resolved_team=team,
            players_in=["Linebacker"],
            players_out=[],
        )

        assert idp_free["before"]["totalValue"] == with_idp["before"]["totalValue"], (
            "The team's CURRENT roster is worth a different total depending on "
            "what is in the hypothetical trade being evaluated."
        )


class TestSuggestionsServeTheCanonicalValue:
    """``displayValue`` is a canonical field name (W29-F001)."""

    def test_display_value_is_the_board_value_in_an_idp_free_trade(self):
        player = suggestions.PlayerAsset(
            name="Wideout",
            position="WR",
            display_value=4000,
            calibrated_value=4000,
            source_count=4,
            team="KC",
            offense_only_value=2500,
        )

        serialized = suggestions._serialize_player(player, offense_only=True)

        assert serialized["displayValue"] == 4000, (
            "displayValue carried the offense-only board. Two different value "
            "concepts under one canonical field name."
        )


class TestTheFinderServesTheCanonicalValue:
    """``modelValue`` is the finder's canonical field."""

    def test_model_value_is_the_board_value_in_an_idp_free_trade(self):
        asset = finder.Asset(
            name="Wideout",
            position="WR",
            team="KC",
            model_value=4000,
            market_value=4100,
            offense_only_model_value=2500,
        )
        result = finder.TradeCandidate(
            give=[asset],
            receive=[],
            give_model_total=4000,
            receive_model_total=0,
            give_ktc_total=4100,
            receive_ktc_total=0,
        ).to_dict()

        assert result["give"][0]["modelValue"] == 4000, (
            "modelValue carried the offense-only board when the trade had no IDP asset."
        )


class TestTheContractPublishesOneCanonicalBoard:
    """The producer, not just the consumers.

    Leaving the second board on the contract while un-wiring its readers
    would keep a loaded gun on every row: the next engine to want an
    "IDP-free view" would find a ready-made second canonical board and
    wire it straight back in.
    """

    def test_no_row_carries_a_second_disagreeing_board_value(self):
        from src.api.data_contract import build_api_data_contract

        import json
        import pathlib

        export = pathlib.Path("exports/latest")
        candidates = sorted(export.glob("dynasty_data*.json"), reverse=True)
        if not candidates:
            import pytest

            pytest.skip("no export available in this environment")

        raw = json.loads(candidates[0].read_text(encoding="utf-8"))
        contract = build_api_data_contract(raw)

        disagreeing = []
        for row in contract["playersArray"]:
            canonical = row.get("rankDerivedValue")
            second = row.get("offenseOnlyRankDerivedValue")
            if not isinstance(canonical, (int, float)) or canonical <= 0:
                continue
            if not isinstance(second, (int, float)) or second <= 0:
                continue
            if int(second) != int(canonical):
                disagreeing.append((row.get("displayName"), int(canonical), int(second)))

        assert not disagreeing, (
            f"{len(disagreeing)} rows carry a second canonical-scale value that "
            f"disagrees with the canonical board, e.g. {disagreeing[:3]}"
        )
