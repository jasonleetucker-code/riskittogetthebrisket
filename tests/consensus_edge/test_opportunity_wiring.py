"""The opportunity component, pinned against the way it actually failed.

Two bugs made this component return `no_opportunity_evidence_available`
for **every player, in every environment, including production with a
fully populated `data/rank_history.jsonl`** — and the unit suite was
green throughout:

1. The service looked up rank history by bare `displayName`. The log is
   keyed `{canonicalName}::{assetClass}`, so the lookup could not match
   a single entry.
2. The axis read `rankDerivedValue` off each history point. The producer
   writes `val`.

Neither is a logic error. Both are *shape* errors, and the existing test
built its fixture by hand in a shape the producer never emits — so the
test agreed with the code and both were wrong together. Every test here
therefore derives its shape from the real producer or asserts against a
real artifact, never from a hand-written guess.

The third thing pinned here is direction. The previous axis scored a
RISING board value positively: "the price went up" was evidence the
price should go up, worth up to 20% of the composite pushed toward Buy.
Its own docstring said it did the opposite. A test now fails if a rising
value ever produces a buy-ward contribution again.
"""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path

from src.api import rank_history as rh
from src.consensus_edge import identity_join, opportunity, service

REPO = Path(__file__).resolve().parents[2]


def _history_points(*values: float) -> list[dict]:
    """History points in the shape ``rank_history.load_history`` emits.

    Field names are asserted against the producer below rather than
    trusted here, so this helper cannot drift away from reality the way
    the original fixture did.
    """
    return [{"date": f"2026-07-{i + 1:02d}", "rank": i + 1, "val": v} for i, v in enumerate(values)]


class TestHistoryShapeMatchesTheProducer(unittest.TestCase):
    """The fixture shape must be the producer's shape, not a guess."""

    def test_producer_emits_val_not_rank_derived_value(self):
        source = inspect.getsource(rh.load_history)
        self.assertIn(
            '"val": val',
            source,
            "rank_history no longer emits 'val'; opportunity.py reads that key",
        )
        self.assertNotIn(
            '"rankDerivedValue"',
            source,
            "rank_history now emits rankDerivedValue; opportunity.py reads 'val'",
        )

    def test_the_consumer_reads_the_key_the_producer_writes(self):
        source = inspect.getsource(opportunity.board_momentum_risk_axis)
        self.assertIn('point["val"]', source)

    def test_history_keys_are_name_scoped_by_asset_class(self):
        # The exact defect: the service indexed this dict by bare name.
        key = rh._player_key({"canonicalName": "Ja'Marr Chase", "assetClass": "offense"})
        self.assertEqual(key, "Ja'Marr Chase::offense")

    def test_service_composes_the_same_key_the_producer_files_under(self):
        # Pinned rather than imported: `_player_key` is private to
        # another package, and a cross-package private import is its own
        # kind of fragility. This asserts the two agree.
        for name, asset in (
            ("Ja'Marr Chase", "offense"),
            ("Micah Parsons", "idp"),
            ("2027 Early 1st", "pick"),
        ):
            self.assertEqual(
                service.rank_history_key(name, asset),
                rh._player_key({"canonicalName": name, "assetClass": asset}),
                f"service and rank_history disagree about {name}'s key",
            )

    def test_unknown_asset_class_still_produces_the_producer_s_key(self):
        self.assertEqual(
            service.rank_history_key("Someone", None),
            rh._player_key({"canonicalName": "Someone"}),
        )


class TestMomentumIsRiskOnly(unittest.TestCase):
    """A rising price must never read as a reason to buy."""

    def test_rising_value_is_never_a_positive_contribution(self):
        axis = opportunity.board_momentum_risk_axis(_history_points(4000, 5000, 6000))
        self.assertIsNotNone(axis["score"])
        self.assertLess(
            axis["score"],
            0,
            "a rising board value produced a buy-ward contribution — this is "
            "momentum-chasing, and it is the exact bug this axis was rewritten for",
        )

    def test_a_large_rise_saturates_rather_than_running_away(self):
        axis = opportunity.board_momentum_risk_axis(_history_points(1000, 5000, 9000))
        self.assertGreaterEqual(axis["score"], -1.0)

    def test_falling_value_is_neutral_not_a_second_buy_signal(self):
        # The fall is what CREATED the mispricing gap. Counting it here
        # too would double-count the same evidence.
        axis = opportunity.board_momentum_risk_axis(_history_points(6000, 5000, 4000))
        self.assertEqual(axis["score"], 0.0)

    def test_the_whole_component_cannot_be_pushed_positive_by_price_alone(self):
        result = opportunity.assess(rank_history=_history_points(4000, 5000, 6000))
        self.assertIsNotNone(result["score"])
        self.assertLessEqual(result["score"], 0.0)


class TestOpportunityRefusesWithoutEvidence(unittest.TestCase):
    """Absent evidence is None with a reason, never a neutral zero."""

    def test_no_inputs_at_all(self):
        result = opportunity.assess()
        self.assertIsNone(result["score"])
        self.assertEqual(result["reason"], opportunity.UNSCORED_NO_EVIDENCE)
        self.assertIn("snapTrend", result["absentAxes"])
        self.assertIn("boardMomentumRisk", result["absentAxes"])

    def test_too_few_history_points(self):
        result = opportunity.assess(rank_history=_history_points(4000, 5000))
        self.assertIsNone(result["score"])

    def test_history_carrying_the_wrong_key_refuses_rather_than_scoring(self):
        # This is the bug shape itself: had the axis silently returned
        # 0.0 here, the component would have looked live while measuring
        # nothing.
        wrong = [{"date": "2026-07-01", "rank": 1, "rankDerivedValue": v} for v in (1, 2, 3)]
        axis = opportunity.board_momentum_risk_axis(wrong)
        self.assertIsNone(axis["score"])
        self.assertEqual(axis["tier"], opportunity.TIER_ABSENT)


class TestSnapTrendAxis(unittest.TestCase):
    """Role growth, from the one usage feed that exists on disk."""

    def _ctx(self, **snaps):
        base = {"season": 2025, "games": 10, "side": "offense", "pct": 60.0, "recentPct": 60.0}
        base.update(snaps)
        return {"snaps": base}

    def test_growing_role_scores_positive(self):
        axis = opportunity.snap_trend_axis(self._ctx(trend=7.5))
        self.assertGreater(axis["score"], 0)
        self.assertEqual(axis["tier"], opportunity.TIER_OBSERVED)

    def test_shrinking_role_scores_negative(self):
        axis = opportunity.snap_trend_axis(self._ctx(trend=-7.5))
        self.assertLess(axis["score"], 0)

    def test_extreme_swings_saturate(self):
        self.assertEqual(opportunity.snap_trend_axis(self._ctx(trend=90.0))["score"], 1.0)
        self.assertEqual(opportunity.snap_trend_axis(self._ctx(trend=-90.0))["score"], -1.0)

    def test_under_three_games_the_trend_is_a_window_artifact(self):
        # recentPct is a last-three-games mean; with fewer than three
        # games it equals the season mean by construction.
        axis = opportunity.snap_trend_axis(self._ctx(trend=5.0, games=2))
        self.assertIsNone(axis["score"])
        self.assertEqual(axis["tier"], opportunity.TIER_ABSENT)

    def test_no_context_is_absent_not_neutral(self):
        self.assertIsNone(opportunity.snap_trend_axis(None)["score"])
        self.assertIsNone(opportunity.snap_trend_axis({})["score"])

    def test_usage_data_alone_produces_a_score(self):
        result = opportunity.assess(player_context=self._ctx(trend=6.0))
        self.assertIsNotNone(result["score"])
        self.assertEqual(result["observedAxes"], ["snapTrend"])

    def test_snap_field_names_match_the_playerctx_producer(self):
        # Same discipline as the history-shape test: assert against the
        # module that writes the record, not against a hand-written idea
        # of what it writes.
        from src.playerctx import normalize

        source = inspect.getsource(normalize)
        self.assertIn('"trend": s["trend"]', source)
        self.assertIn('"games": s["games"]', source)


class TestPlayerContextJoin(unittest.TestCase):
    """Board key ↔ playerctx record, joined on Sleeper id only."""

    CONTRACT = {
        "playersArray": [
            {"playerId": "4046", "displayName": "Patrick Mahomes", "assetClass": "offense"},
            {"playerId": "9999", "displayName": "Nobody Indexed", "assetClass": "offense"},
            {"displayName": "No Sleeper Id", "assetClass": "offense"},
        ]
    }
    SNAPSHOT = {
        "sleeperIndex": {"4046": "00-0033873"},
        "players": {"00-0033873": {"snaps": {"trend": 4.0, "games": 12}}},
    }

    def test_a_matching_row_receives_its_record(self):
        joined = identity_join.player_context_index(self.CONTRACT, self.SNAPSHOT)
        self.assertIn("Patrick Mahomes", joined)
        self.assertEqual(joined["Patrick Mahomes"]["snaps"]["trend"], 4.0)

    def test_unmatched_rows_are_simply_absent(self):
        joined = identity_join.player_context_index(self.CONTRACT, self.SNAPSHOT)
        self.assertNotIn("Nobody Indexed", joined)
        self.assertNotIn("No Sleeper Id", joined)

    def test_no_snapshot_is_an_empty_join_not_a_crash(self):
        self.assertEqual(identity_join.player_context_index(self.CONTRACT, None), {})
        self.assertEqual(identity_join.player_context_index(self.CONTRACT, {}), {})

    def test_the_sleeper_id_field_matches_what_the_contract_stamps(self):
        # `playersArray` rows call it `playerId`; the legacy `players`
        # dict calls it `_sleeperId`. A join that knew only one spelling
        # matched every fixture and zero production rows.
        source = (REPO / "src" / "api" / "data_contract.py").read_text()
        self.assertIn(
            '"playerId": str(p_data.get("_sleeperId")',
            source,
            "the contract no longer stamps playerId from _sleeperId; "
            "identity_join.row_sleeper_id assumes it does",
        )
        self.assertEqual(identity_join.row_sleeper_id({"playerId": "1"}), "1")
        self.assertEqual(identity_join.row_sleeper_id({"_sleeperId": "2"}), "2")
        self.assertEqual(identity_join.row_sleeper_id({}), "")


class TestGsisJoinRefusesRatherThanGuessing(unittest.TestCase):
    """A wrong multiplier on the right-looking player is worse than none."""

    def test_directory_without_gsis_ids_yields_nothing(self):
        contract = {"playersArray": [{"playerId": "4046", "displayName": "Patrick Mahomes"}]}
        directory = {"4046": {"full_name": "Patrick Mahomes"}}  # no gsis_id
        self.assertEqual(identity_join.build_gsis_to_player_key(contract, directory), {})

    def test_a_present_gsis_id_joins(self):
        contract = {"playersArray": [{"playerId": "4046", "displayName": "Patrick Mahomes"}]}
        directory = {"4046": {"gsis_id": "00-0033873"}}
        self.assertEqual(
            identity_join.build_gsis_to_player_key(contract, directory),
            {"00-0033873": "Patrick Mahomes"},
        )

    def test_names_are_never_matched_as_a_fallback(self):
        contract = {"playersArray": [{"displayName": "Patrick Mahomes"}]}  # no sleeper id
        directory = {"4046": {"gsis_id": "00-0033873", "full_name": "Patrick Mahomes"}}
        self.assertEqual(identity_join.build_gsis_to_player_key(contract, directory), {})


class TestInputsAreResolvedOnce(unittest.TestCase):
    """The served board and the recorded board must be the same board."""

    def test_both_callers_go_through_the_shared_resolver(self):
        for path in (
            REPO / "src" / "consensus_edge" / "api.py",
            REPO / "scripts" / "snapshot_consensus_edge.py",
        ):
            source = path.read_text()
            self.assertIn(
                "inputs_mod.resolve(contract)",
                source,
                f"{path.name} builds a board without the shared input resolver; "
                "the recorded history would then describe a board no user saw",
            )

    # Parameters that are NOT data inputs and must not be resolved from
    # the environment. `params` and `hours_stale` are caller policy;
    # `csv_root` and `scoring_fit_board` exist for historical replay —
    # resolving those from the environment is precisely the leak the
    # replay guards against, since "whatever is on disk right now" is
    # today's data.
    _NOT_DATA_INPUTS = frozenset(
        {"contract", "params", "hours_stale", "csv_root", "scoring_fit_board"}
    )

    def test_the_resolver_covers_every_optional_input(self):
        from src.consensus_edge import inputs as inputs_mod

        optional = {
            name
            for name, param in inspect.signature(service.build_board).parameters.items()
            if param.default is None and name not in self._NOT_DATA_INPUTS
        }
        self.assertEqual(
            optional,
            set(inputs_mod.resolve(None)),
            "build_board grew an optional data input the shared resolver does not "
            "supply. If the new parameter is replay-only rather than a data input, "
            "add it to _NOT_DATA_INPUTS and say why.",
        )

    def test_the_exclusion_list_only_names_real_parameters(self):
        # Otherwise the exclusion list becomes a place stale names hide,
        # and a genuinely unresolved input could be masked by a typo.
        actual = set(inspect.signature(service.build_board).parameters)
        self.assertTrue(
            self._NOT_DATA_INPUTS <= actual,
            f"exclusion list names parameters that no longer exist: "
            f"{sorted(self._NOT_DATA_INPUTS - actual)}",
        )

    def test_resolution_never_raises_on_a_bare_environment(self):
        from src.consensus_edge import inputs as inputs_mod

        resolved = inputs_mod.resolve({"playersArray": []})
        self.assertEqual(
            set(resolved),
            {
                "movements_by_asset",
                "rank_history_by_player",
                "player_context_by_player",
            },
        )


if __name__ == "__main__":
    unittest.main()
