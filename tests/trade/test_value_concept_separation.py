"""One field name carries one value concept, on every trade surface.

The defect this pins (R28 — W29-F001, W29-F002, W09-F006)
─────────────────────────────────────────────────────────
The contract carries TWO boards on the same 0-9999 scale:
``rankDerivedValue`` (the consensus board every page renders) and
``offenseOnlyRankDerivedValue`` (an IDP-disabled re-run of the same
pipeline).  Both are legitimate concepts.  Three engines used to
substitute the second for the first whenever a trade happened to
contain no DL/LB/DB — which is every all-offense trade — and shipped
the result under the FIRST one's field name:

* ``suggestions.py::_serialize_player`` wrote the offense-only value
  into ``displayValue``.  Measured on the live payload: 19 of 51 asset
  legs disagreed with the board, worst case Travis Hunter at 5,637 on
  ``/trade`` against 4,401 on ``/rankings`` (+28.08%), because the
  offense-only board never saw the two-way-player boost.  The same
  player could carry two different ``displayValue``s inside ONE
  response, since ``rosterAnalysis.byPosition`` always serialized the
  board.
* ``trade_simulator.py::_resolve_asset`` did the same to ``value``.
* ``finder.py`` did the same to ``modelValue`` — the field
  ``/arbitrage`` renders under the literal label "board".

And because ``src/league_intel/overlay.py`` scaled ``rankDerivedValue``
alone, the league-adjusted lens could not reach the substituted field:
an all-offense trade came back byte-identical under
``valuationMode=leagueAdjusted``, with the adjusted label stamped on
it and ``valuationNote: null``.

The rule these tests enforce
────────────────────────────
One field name means one concept.  ``displayValue`` / ``value`` /
``modelValue`` are ALWAYS the canonical board.  The offense-only board
is still published — as ``offenseOnlyValue`` / ``offenseOnlyModelValue``
— and it moves with the lens like every other board-scale field, so
nothing is lost and nothing is confusable.
"""

from __future__ import annotations

import copy

from src.api import trade_simulator
from src.league_intel import overlay as _overlay
from src.trade import finder as _finder
from src.trade import suggestions as _suggestions


# ── the overlay: every board-scale field moves, and only those ──────────


def _row(name, pos, rdv, oo=None, composite=None):
    row: dict = {
        "displayName": name,
        "canonicalName": name,
        "legacyRef": name,
        "position": pos,
        "pos": pos,
        "rankDerivedValue": rdv,
        "canonicalConsensusRank": None,
        "values": {"overall": rdv, "finalAdjusted": rdv, "displayValue": rdv},
    }
    if oo is not None:
        row["offenseOnlyRankDerivedValue"] = oo
    if composite is not None:
        row["values"]["rawComposite"] = composite
    return row


def _board():
    return [
        _row("A", "WR", 5000, oo=4800, composite=5500),
        _row("B", "RB", 4000, oo=4200, composite=4400),
        _row("C", "LB", 3000, composite=3300),
    ]


class TestTheLensReachesEveryBoardScaleField:
    def test_the_offense_only_board_is_scaled_too(self):
        """THE W09-F006 REGRESSION.

        ``offenseOnlyRankDerivedValue`` is a second board on the same
        scale, read by the simulator, the finder and the suggestion
        engine.  Leaving it at its market value while the response
        stamps ``leagueAdjusted`` is an active misstatement, not a
        missing feature.
        """
        out = _overlay.adjusted_rows(_board(), {"A": 1.5, "B": 0.5})
        by_name = {r["displayName"]: r for r in out}
        assert by_name["A"]["rankDerivedValue"] == 7500
        assert by_name["A"]["offenseOnlyRankDerivedValue"] == 7200
        assert by_name["B"]["rankDerivedValue"] == 2000
        assert by_name["B"]["offenseOnlyRankDerivedValue"] == 2100

    def test_the_values_bundle_aliases_move_with_the_value(self):
        """``data_contract.py`` writes ``overall`` / ``finalAdjusted`` /
        ``displayValue`` in one branch from ``rankDerivedValue``.  A row
        carrying an adjusted value beside an unadjusted alias is the
        same collision one level down."""
        out = _overlay.adjusted_rows(_board(), {"A": 1.5})
        vals = {r["displayName"]: r["values"] for r in out}["A"]
        assert vals["overall"] == 7500
        assert vals["finalAdjusted"] == 7500
        assert vals["displayValue"] == 7500

    def test_the_scraper_composite_is_never_scaled(self):
        """``rawComposite`` runs on the pre-canonical composite scale
        (median 1.0855x the board).  Multiplying it by a board-derived
        factor produces a number on neither scale."""
        out = _overlay.adjusted_rows(_board(), {"A": 1.5, "B": 0.5, "C": 1.2})
        raw = {r["displayName"]: r["values"].get("rawComposite") for r in out}
        assert raw == {"A": 5500, "B": 4400, "C": 3300}

    def test_the_callers_rows_and_values_bundles_are_never_mutated(self):
        """``latest_contract_data`` is a shared module global, and the
        ``values`` dict is nested inside it — a shallow row copy alone
        would still write through."""
        rows = _board()
        before = copy.deepcopy(rows)
        _overlay.adjusted_rows(rows, {"A": 1.5, "B": 0.5})
        assert rows == before


# ── suggestions: displayValue is the board, always ──────────────────────


def _asset(name, pos, value, oo=None):
    return _suggestions.PlayerAsset(
        name=name,
        position=pos,
        display_value=value,
        calibrated_value=value,
        source_count=4,
        team="KC",
        offense_only_value=oo,
    )


def _all_offense_pool():
    """A roster deep at RB/WR and thin at QB/TE, plus market targets.

    Every asset is offense, so ``_trade_is_idp_free`` was true for every
    package the engine could build — the branch under test fired on all
    of them.  Every offense-only value is deliberately unequal to its
    board value, Travis Hunter's pair (board 4401 / offense-only 5637)
    taken from the live payload.
    """
    pool = [_asset("Travis Hunter", "WR", 4401, oo=5637)]
    for i, v in enumerate([7800, 7600, 7400, 6000, 5500]):
        pool.append(_asset(f"My RB{i}", "RB", v, oo=int(v * 0.85)))
    for i, v in enumerate([7500, 7300, 7100, 6800, 6000, 5200]):
        pool.append(_asset(f"My WR{i}", "WR", v, oo=int(v * 0.85)))
    pool.append(_asset("My QB0", "QB", 5000, oo=4200))
    pool.append(_asset("My TE0", "TE", 3000, oo=2500))
    for i, v in enumerate([7900, 7000, 6300, 5800]):
        pool.append(_asset(f"Free QB{i}", "QB", v, oo=int(v * 0.70)))
    for i, v in enumerate([7700, 6900, 5900]):
        pool.append(_asset(f"Free TE{i}", "TE", v, oo=int(v * 0.70)))
    for i, v in enumerate([9000, 8200, 7000]):
        pool.append(_asset(f"Free WR{i}", "WR", v, oo=int(v * 0.70)))
    return pool


def _all_offense_payload():
    pool = _all_offense_pool()
    roster = [a.name for a in pool if a.name.startswith("My ") or a.name == "Travis Hunter"]
    return _suggestions.generate_suggestions_from_pool(
        roster_names=roster,
        pool=pool,
        board_top_n=0,
    )


class TestSuggestionsPublishOneConceptPerName:
    def test_display_value_is_the_board_even_for_an_all_offense_trade(self):
        """THE W29-F001 REGRESSION, at its narrowest point.  Travis
        Hunter's shape: board 4401, offense-only 5637."""
        hunter = _asset("Travis Hunter", "WR", 4401, oo=5637)
        out = _suggestions._serialize_player(hunter)
        assert out["displayValue"] == 4401
        assert out["offenseOnlyValue"] == 5637

    def test_a_player_without_an_offense_only_value_omits_the_key(self):
        out = _suggestions._serialize_player(_asset("Nobody", "LB", 3000))
        assert out["displayValue"] == 3000
        assert "offenseOnlyValue" not in out

    def test_one_player_carries_one_number_across_the_whole_payload(self):
        """``rosterAnalysis.byPosition`` always serialized the board
        while suggestion legs served the offense-only board, so one
        response could show a player at two values (live: Brian Thomas
        at 4,436 in a leg and 4,466 in the roster block)."""
        payload = _all_offense_payload()
        legs = 0
        seen: dict[str, set[int]] = {}
        for bucket in ("sellHigh", "buyLow", "consolidation", "positionalUpgrades"):
            for suggestion in payload[bucket]:
                for side in ("give", "receive"):
                    for leg in suggestion[side]:
                        legs += 1
                        seen.setdefault(leg["name"], set()).add(leg["displayValue"])
        assert legs >= 4, "fixture produced no suggestion legs; the assertion would be vacuous"
        for players in payload["rosterAnalysis"]["byPosition"].values():
            for leg in players:
                seen.setdefault(leg["name"], set()).add(leg["displayValue"])
        board = {a.name: a.display_value for a in _all_offense_pool()}
        for name, values in seen.items():
            assert values == {board[name]}, f"{name} served {values}, board says {board[name]}"

    def test_the_totals_sum_the_numbers_the_legs_show(self):
        """The invariant that makes a card readable: if the value shown
        beside a player is not the value the gap was computed from, the
        arithmetic on screen cannot be checked by the person reading
        it."""
        payload = _all_offense_payload()
        checked = 0
        for bucket in ("sellHigh", "buyLow", "consolidation", "positionalUpgrades"):
            for suggestion in payload[bucket]:
                assert suggestion["giveTotal"] == sum(p["displayValue"] for p in suggestion["give"])
                assert suggestion["receiveTotal"] == sum(
                    p["displayValue"] for p in suggestion["receive"]
                )
                checked += 1
        assert checked >= 2

    def test_the_payload_names_the_board_it_priced_from(self):
        payload = _all_offense_payload()
        assert payload["metadata"]["valueBasis"] == "rankDerivedValue"


# ── the simulator: value is the board, always ───────────────────────────


def _sim_contract():
    return {
        "playersArray": [
            _row("Star WR", "WR", 9950, oo=8000),
            _row("Star RB", "RB", 6472, oo=5000),
            _row("Star QB", "QB", 7482, oo=6000),
            _row("Star LB", "LB", 4000),
        ]
    }


class TestTheSimulatorPublishesOneConceptPerName:
    def test_an_all_offense_trade_is_priced_on_the_board(self):
        """THE W09-F006 REPRODUCTION, in a unit test.  A trade with no
        IDP leg used to silently switch the whole simulation onto the
        offense-only board."""
        out = trade_simulator.simulate_trade(
            _sim_contract(),
            resolved_team={"name": "Me", "players": ["Star WR"]},
            players_out=["Star WR"],
            players_in=["Star RB", "Star QB"],
        )
        sent = {a["name"]: a["value"] for a in out["sending"]}
        recv = {a["name"]: a["value"] for a in out["receiving"]}
        assert sent == {"Star WR": 9950}
        assert recv == {"Star RB": 6472, "Star QB": 7482}
        assert out["equity"] == 6472 + 7482 - 9950
        assert out["valueBasis"] == "rankDerivedValue"

    def test_the_offense_only_board_rides_along_under_its_own_name(self):
        out = trade_simulator.simulate_trade(
            _sim_contract(),
            resolved_team={"name": "Me", "players": ["Star WR"]},
            players_out=["Star WR"],
            players_in=["Star RB"],
        )
        assert out["sending"][0]["offenseOnlyValue"] == 8000
        assert out["receiving"][0]["offenseOnlyValue"] == 5000

    def test_the_lens_moves_an_all_offense_simulation(self):
        """End to end: apply the lens the way ``_valuation_scoped_contract``
        does, then simulate.  Byte-identical output under both modes is
        exactly what the finding measured (equity 4004 either way)."""
        market = _sim_contract()
        factors = {"Star WR": 1.10, "Star RB": 1.05, "Star QB": 0.95, "Star LB": 1.0}
        adjusted = _overlay.adjusted_contract(market, factors)
        assert adjusted is not None

        def _sim(contract):
            return trade_simulator.simulate_trade(
                contract,
                resolved_team={"name": "Me", "players": ["Star WR"]},
                players_out=["Star WR"],
                players_in=["Star RB", "Star QB"],
            )

        assert _sim(market)["equity"] != _sim(adjusted)["equity"]


# ── the finder: modelValue is the board, always ─────────────────────────


class TestTheFinderPublishesOneConceptPerName:
    def test_model_value_is_the_board_on_an_all_offense_trade(self):
        """``/arbitrage`` renders this field under the label "board"."""
        give = _finder.Asset(
            name="Star WR",
            position="WR",
            team="KC",
            model_value=9950,
            market_value=9000,
            offense_only_model_value=8000,
        )
        receive = _finder.Asset(
            name="Star RB",
            position="RB",
            team="KC",
            model_value=6472,
            market_value=6000,
            offense_only_model_value=5000,
        )
        payload = _finder.TradeCandidate(give=[give], receive=[receive]).to_dict()
        assert payload["give"][0]["modelValue"] == 9950
        assert payload["give"][0]["offenseOnlyModelValue"] == 8000
        assert payload["receive"][0]["modelValue"] == 6472
        assert payload["receive"][0]["offenseOnlyModelValue"] == 5000

    def test_the_offense_only_value_comes_from_the_contract_not_the_legacy_mirror(self):
        """``overlay.adjusted_rows`` rewrites ``playersArray`` rows only
        and deliberately leaves the legacy ``players`` dict alone, so a
        value read from ``_offenseOnlyFinalAdjusted`` is always the
        UNADJUSTED market number under an adjusted label (W29-F002)."""
        players = {
            "Star WR": {
                "position": "WR",
                "team": "KC",
                "_finalAdjusted": 9000,
                "_offenseOnlyFinalAdjusted": 8000,
                "_sites": 4,
                "_canonicalSiteValues": {"ktcSfTep": 9000},
            }
        }
        contract = {
            "playersArray": [_row("Star WR", "WR", 10945, oo=8800)],
        }
        pool = _finder.build_asset_pool(
            players,
            market_top_n=0,
            board_values=_finder.board_values_from_contract(contract),
            offense_only_values=_finder.offense_only_values_from_contract(contract),
        )
        assert [a.model_value for a in pool] == [10945]
        assert [a.offense_only_model_value for a in pool] == [8800]

    def test_the_mirror_is_still_the_fallback_when_no_map_is_passed(self):
        """A caller holding a board but no offense-only map — fixtures,
        and any call site not yet threaded — keeps the old source."""
        players = {
            "Star WR": {
                "position": "WR",
                "team": "KC",
                "_finalAdjusted": 9000,
                "_offenseOnlyFinalAdjusted": 8000,
                "_sites": 4,
                "_canonicalSiteValues": {"ktcSfTep": 9000},
            }
        }
        contract = {"playersArray": [_row("Star WR", "WR", 10945, oo=8800)]}
        pool = _finder.build_asset_pool(
            players,
            market_top_n=0,
            board_values=_finder.board_values_from_contract(contract),
        )
        assert [a.offense_only_model_value for a in pool] == [8000]
