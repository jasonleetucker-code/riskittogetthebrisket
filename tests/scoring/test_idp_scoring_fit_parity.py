"""Parity regression test: backend never mutates ``rankDerivedValue``.

The scoring-fit pass is *additive only* — it stamps new
``idpScoringFit*`` fields on each IDP row but MUST NOT touch the
existing consensus fields (``rankDerivedValue``,
``canonicalConsensusRank``, ``sourceRanks``, etc.).

This test asserts the invariant by:

1. Running ``apply_idp_scoring_fit_pass`` against a hand-built mini
   players_array
2. Snapshotting every key present BEFORE and AFTER
3. Asserting the symmetric difference is a STRICT SUBSET of the
   approved ``idpScoringFit*`` whitelist

If any future refactor adds a side-effect that mutates an existing
field, this test fails loud rather than silently shifting values in
production.
"""
from __future__ import annotations

import unittest
from copy import deepcopy
from unittest.mock import patch

from src.scoring.idp_scoring_fit_apply import apply_idp_scoring_fit_pass


# Approved field names the pass is allowed to add.  Any addition to
# this set requires a deliberate code review — that's the whole point.
_ALLOWED_NEW_FIELDS = frozenset({
    "idpScoringFitVorp",
    "idpScoringFitTier",
    "idpScoringFitDelta",
    "idpScoringFitConfidence",
    "idpScoringFitSynthetic",
    "idpScoringFitDraftRound",
    "idpScoringFitWeightedPpg",
    "idpScoringFitGamesUsed",
    "idpScoringFitAdjustedValue",
})


def _seed_players() -> list[dict]:
    """Hand-build a minimal IDP-heavy players_array for the test.

    All consensus fields populated.  After the pass, every existing
    field MUST equal its pre-pass value byte-for-byte.
    """
    return [
        {
            "displayName": "Micah Parsons",
            "position": "LB",
            "playerId": "11111",
            "rankDerivedValue": 8500,
            "canonicalConsensusRank": 12,
            "sourceRanks": {"ktc": 12, "dlf": 11, "idpTradeCalc": 8},
            "confidenceBucket": "high",
            "anomalyFlags": [],
        },
        {
            "displayName": "Will Anderson Jr.",
            "position": "DE",
            "playerId": "22222",
            "rankDerivedValue": 6700,
            "canonicalConsensusRank": 28,
            "sourceRanks": {"ktc": 28, "dlf": 30, "idpTradeCalc": 22},
            "confidenceBucket": "medium",
            "anomalyFlags": [],
        },
        {
            "displayName": "Josh Allen",
            "position": "QB",  # offense — should be skipped by the pass
            "playerId": "33333",
            "rankDerivedValue": 9999,
            "canonicalConsensusRank": 1,
        },
    ]


class TestIdpScoringFitParity(unittest.TestCase):
    """The backend pass MUST be additive-only on existing fields."""

    @patch("src.scoring.idp_scoring_fit_apply._fetch_sleeper_players_idmap")
    @patch("src.scoring.idp_scoring_fit_apply._fetch_nflverse_id_map")
    @patch("src.scoring.idp_scoring_fit_apply._fetch_trailing_3yr_defensive_corpus")
    @patch("src.scoring.idp_scoring_fit_apply._fetch_idp_league_context")
    @patch("src.api.feature_flags.is_enabled")
    def test_pass_does_not_mutate_existing_fields(
        self,
        mock_flag,
        mock_ctx,
        mock_corpus,
        mock_id_map,
        mock_sleeper,
    ):
        # Force the flag ON, return canned context so the pass executes
        # its full body.  The corpus is intentionally non-empty so the
        # pass produces some fit rows.
        mock_flag.side_effect = lambda name: name == "idp_scoring_fit"
        mock_ctx.return_value = {
            "scoring_settings": {
                "idp_tkl_solo": 1.5,
                "idp_sack": 4.0,
                "idp_qb_hits": 1.5,
                "idp_pd": 1.5,
            },
            "roster_positions": ["QB", "RB", "WR", "TE", "FLEX", "DL", "LB", "DB"],
            "num_teams": 12,
        }
        # Build a tiny defensive corpus so the pass produces output.
        mock_corpus.return_value = {
            2024: [
                {"player_id": "gsis_parsons", "player_name": "Micah Parsons",
                 "position": "LB", "season": 2024, "week": w,
                 "def_tackles_solo": 4, "def_sacks": 1}
                for w in range(1, 18)
            ] + [
                {"player_id": "gsis_anderson", "player_name": "Will Anderson",
                 "position": "DE", "season": 2024, "week": w,
                 "def_tackles_solo": 2, "def_sacks": 1, "def_qb_hits": 1}
                for w in range(1, 18)
            ],
        }
        mock_id_map.return_value = [
            {"gsis_id": "gsis_parsons", "display_name": "Micah Parsons",
             "position": "LB", "rookie_season": 2021, "draft_round": 1},
            {"gsis_id": "gsis_anderson", "display_name": "Will Anderson",
             "position": "DE", "rookie_season": 2023, "draft_round": 1},
        ]
        mock_sleeper.return_value = {
            "11111": "gsis_parsons",
            "22222": "gsis_anderson",
        }

        # Snapshot the pre-pass state.
        players = _seed_players()
        before = deepcopy(players)

        apply_idp_scoring_fit_pass(players, league_idp_enabled=True)

        # For every player, every key that existed BEFORE must still
        # equal its pre-pass value AFTER.  The only NEW keys allowed
        # are members of ``_ALLOWED_NEW_FIELDS``.
        for pre, post in zip(before, players):
            for k, v in pre.items():
                self.assertEqual(
                    post.get(k), v,
                    f"field {k!r} on {pre.get('displayName')!r} mutated: "
                    f"before={v!r}, after={post.get(k)!r}",
                )
            new_keys = set(post.keys()) - set(pre.keys())
            unauthorized = new_keys - _ALLOWED_NEW_FIELDS
            self.assertFalse(
                unauthorized,
                f"unauthorized new fields on {pre.get('displayName')!r}: "
                f"{unauthorized}",
            )

    @patch("src.api.feature_flags.is_enabled")
    def test_flag_off_is_complete_no_op(self, mock_flag):
        """With the flag OFF, players_array must be byte-identical."""
        mock_flag.return_value = False

        players = _seed_players()
        before = deepcopy(players)

        apply_idp_scoring_fit_pass(players, league_idp_enabled=True)

        self.assertEqual(players, before)

    @patch("src.api.feature_flags.is_enabled")
    def test_idp_disabled_league_is_no_op(self, mock_flag):
        """For offense-only leagues, players_array must be byte-identical
        even with the flag ON."""
        mock_flag.return_value = True

        players = _seed_players()
        before = deepcopy(players)

        apply_idp_scoring_fit_pass(players, league_idp_enabled=False)

        self.assertEqual(players, before)


if __name__ == "__main__":
    unittest.main()
