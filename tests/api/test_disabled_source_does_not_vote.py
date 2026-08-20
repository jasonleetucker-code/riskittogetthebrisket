"""Adversarial proof: a disabled or zero-weight ranking source cannot
influence canonical valuation, whatever its own numbers say.

Why this file exists now
-------------------------
The cross-position bridge program (``src/bridges/``, Lane 8) is landing
"PENDING does not vote" as a NEW vocabulary for cross-position evidence, but
it has zero production consumers today (see
``test_bridge_consumer_boundary.py``) -- nothing in ``data_contract.py``,
``canonical/``, ``league_intel/`` or ``trade/`` imports it yet.  The place
that invariant ALREADY lives, live, in production, is the ordinary
source-override gate: ``_source_is_enabled`` / ``_active_sources`` in
``src/api/data_contract.py``, which decides whether a REGISTERED ranking
source may vote in the blend.  Whatever gate a future bridge-translation
consumer (PR B) eventually builds, it has to compose with this one without
either leaking into the other -- so this file hardens the existing gate
first, with the adversarial rigor the bridge program's own charter asks for
(extreme-value injection, not just "does the flag get read").

``tests/api/test_source_overrides.py`` already proves disabling a source
REMOVES it from stamps and CHANGES the blend relative to including it.  It
does not prove the stronger claim this file adds: that a disabled source's
OWN MAGNITUDE is invisible to literally every field the contract publishes,
however extreme that magnitude is.  A source could in principle be excluded
from the blend's numerator/count while still leaking into a diagnostic
field (spread, coverage, confidence) that reads the raw payload directly
instead of through ``_active_sources``.  That is exactly the shape of bug
this file is built to catch and could not otherwise be told apart from
"working as intended" by eye.
"""

from __future__ import annotations

import copy
import json
import unittest
from typing import Any

from src.api import data_contract as _data_contract
from src.api.data_contract import build_api_data_contract, get_ranking_source_keys
from tests.api.test_source_overrides import _by_name, _fixture_raw_payload

#: Deliberately outside the board's normal 0-9999 scale on the high end --
#: these are impossible values for a real source to publish, chosen so a
#: leak cannot hide inside "plausible-looking noise".
_EXTREME_LOW = 1
_EXTREME_HIGH = 9999
_ABSURDLY_HIGH = 999_999


#: Row-level fields that are DELIBERATELY not part of the "does this source
#: vote" invariant.  All are the same raw per-source evidence, repeated
#: across the contract's parallel player representations -- ``playersArray``
#: (materialized, camelCase ``canonicalSiteValues``) and the legacy
#: ``players`` dict, which carries it TWICE more: once as
#: ``_canonicalSiteValues`` (underscore-prefixed) and once FLATTENED, one key
#: per registered source (``row["dlfSf"]``, ``row["ktc"]``, ...) for legacy
#: frontend consumption.  Every registered source's own reported number is
#: shown regardless of enabled state, precisely because "we
#: acquired/observed this" and "this voted" are different facts (dispatch
#: Phase 2: "A source can be visible as metadata/evidence without
#: influencing production value").  Verified empirically before being
#: written here, not assumed: a deep structural diff of two builds that
#: differ ONLY in a disabled source's own value finds exactly these fields
#: and nothing else (see ``TestMetadataVisibilityIsSeparateFromVoting``
#: below, which proves the two halves of that sentence together rather than
#: trusting one without the other).  The flattened legacy columns are
#: derived from the live source registry rather than hard-coded, so this
#: stays correct if a source is added or renamed.
_METADATA_ONLY_ROW_FIELDS = ("canonicalSiteValues",)
_METADATA_ONLY_LEGACY_FIELDS = ("_canonicalSiteValues", *get_ranking_source_keys())


def _stable(contract: dict[str, Any]) -> str:
    """A byte-comparable view of the contract's VOTING surface.

    Strips exactly two classes of field, both independently verified rather
    than assumed:

    * top-level ``dataFreshness`` / ``generatedAt`` -- non-deterministic BY
      DESIGN, reading live wall-clock time / on-disk CSV mtimes rather than
      the payload argument (two calls on an identical payload differ ONLY on
      these two keys; verified empirically, not by inspection);
    * the raw per-source evidence dict, in BOTH of the contract's parallel
      player representations -- not a vote.

    Every other field, at every level, in both ``playersArray`` and the
    legacy ``players`` dict, must be byte-identical for this function to
    consider two contracts the same.
    """
    c = dict(contract)
    c.pop("dataFreshness", None)
    c.pop("generatedAt", None)
    players_array = c.get("playersArray")
    if isinstance(players_array, list):
        scrubbed = []
        for row in players_array:
            row = dict(row)
            for field in _METADATA_ONLY_ROW_FIELDS:
                row.pop(field, None)
            scrubbed.append(row)
        c["playersArray"] = scrubbed
    legacy_players = c.get("players")
    if isinstance(legacy_players, dict):
        scrubbed_legacy = {}
        for name, row in legacy_players.items():
            if isinstance(row, dict):
                row = dict(row)
                for field in _METADATA_ONLY_LEGACY_FIELDS:
                    row.pop(field, None)
            scrubbed_legacy[name] = row
        c["players"] = scrubbed_legacy
    return json.dumps(c, sort_keys=True, default=str)


def _swap_source_values(
    payload: dict[str, Any], source_key: str, new_values_by_name: dict[str, float]
) -> dict[str, Any]:
    """Deep-copy ``payload`` and overwrite ONE source's values for named
    players.  Every other source's values, every other player, and the
    payload's structure are untouched."""
    mutated = copy.deepcopy(payload)
    for name, value in new_values_by_name.items():
        row = mutated["players"].get(name)
        if row is None:
            raise AssertionError(f"fixture no longer has a player named {name!r}")
        csv = row.setdefault("_canonicalSiteValues", {})
        if source_key not in csv:
            raise AssertionError(
                f"{name!r} does not carry {source_key!r} in the fixture -- "
                "the mutation would be a no-op and prove nothing"
            )
        csv[source_key] = value
    return mutated


class TestDisabledSourceMagnitudeIsInvisible(unittest.TestCase):
    """A disabled source's numeric content must never move the contract."""

    def setUp(self) -> None:
        self.override = {"dlfSf": {"include": False}}
        self.baseline_payload = _fixture_raw_payload()
        self.baseline = build_api_data_contract(
            self.baseline_payload, source_overrides=self.override
        )

    def test_extreme_low_value_injected_into_disabled_source(self) -> None:
        mutated_payload = _swap_source_values(
            self.baseline_payload,
            "dlfSf",
            {
                "Josh Allen": _EXTREME_LOW,
                "Ja'Marr Chase": _EXTREME_LOW,
                "Bijan Robinson": _EXTREME_LOW,
                "Veteran TE": _EXTREME_LOW,
            },
        )
        mutated = build_api_data_contract(mutated_payload, source_overrides=self.override)
        self.assertEqual(_stable(self.baseline), _stable(mutated))

    def test_disabled_source_pushed_to_rank_one_does_not_move_the_board(self) -> None:
        """Veteran TE sits near the bottom of the board.  Give his disabled
        ``dlfSf`` value the kind of number that would make him #1 overall if
        that source voted, while every rival's disabled value collapses to
        the floor.  The board must not move by a single rank."""
        mutated_payload = _swap_source_values(
            self.baseline_payload,
            "dlfSf",
            {
                "Josh Allen": _EXTREME_LOW,
                "Ja'Marr Chase": _EXTREME_LOW,
                "Bijan Robinson": _EXTREME_LOW,
                "Veteran TE": _EXTREME_HIGH,
            },
        )
        mutated = build_api_data_contract(mutated_payload, source_overrides=self.override)
        self.assertEqual(_stable(self.baseline), _stable(mutated))

    def test_absurd_out_of_scale_value_on_a_disabled_source(self) -> None:
        """A value the board's own scale cannot produce (999,999) is still
        invisible once the source is disabled -- the gate must not depend
        on the value ever being plausible."""
        mutated_payload = _swap_source_values(
            self.baseline_payload, "dlfSf", {"Veteran TE": _ABSURDLY_HIGH}
        )
        mutated = build_api_data_contract(mutated_payload, source_overrides=self.override)
        self.assertEqual(_stable(self.baseline), _stable(mutated))

    def test_several_disabled_sources_simultaneously_extreme(self) -> None:
        """Offense AND IDP disabled sources, both injected with extreme
        values, at once."""
        override = {"dlfSf": {"include": False}, "idpTradeCalc": {"include": False}}
        baseline = build_api_data_contract(self.baseline_payload, source_overrides=override)

        mutated_payload = _swap_source_values(
            self.baseline_payload,
            "dlfSf",
            {"Josh Allen": _EXTREME_LOW, "Veteran TE": _EXTREME_HIGH},
        )
        mutated_payload = _swap_source_values(
            mutated_payload,
            "idpTradeCalc",
            {"Myles Garrett": _EXTREME_LOW, "Kyle Hamilton": _EXTREME_HIGH},
        )
        mutated = build_api_data_contract(mutated_payload, source_overrides=override)
        self.assertEqual(_stable(baseline), _stable(mutated))

    def test_zero_weight_source_magnitude_is_also_invisible(self) -> None:
        """ "Enabled with weight 0" has exactly one coherent meaning -- no
        vote (``_active_sources``'s own docstring) -- so it must give the
        SAME invisibility guarantee as ``include: False``, not a weaker
        one."""
        override = {"dlfSf": {"weight": 0}}
        baseline = build_api_data_contract(self.baseline_payload, source_overrides=override)

        mutated_payload = _swap_source_values(
            self.baseline_payload,
            "dlfSf",
            {"Josh Allen": _EXTREME_LOW, "Veteran TE": _EXTREME_HIGH},
        )
        mutated = build_api_data_contract(mutated_payload, source_overrides=override)
        self.assertEqual(_stable(baseline), _stable(mutated))

    def test_a_disabled_sources_presence_is_absent_from_health_metadata(self) -> None:
        """Not just the VALUE -- the source's PRESENCE must be absent from
        every count-bearing field a caller could use to infer it voted."""
        rov = self.baseline.get("rankingsOverride") or {}
        self.assertNotIn("dlfSf", rov.get("enabledSources") or [])
        for row in self.baseline.get("playersArray") or []:
            self.assertNotIn("dlfSf", row.get("sourceRanks") or {})


class TestMetadataVisibilityIsSeparateFromVoting(unittest.TestCase):
    """Prove Phase 2's exact distinction, both halves at once: a disabled
    source's raw value stays VISIBLE as evidence while every voting field
    stays BLIND to it.  Proving only the second half (as the class above
    does, having scrubbed ``canonicalSiteValues`` out of the comparison)
    risks the scrub silently hiding a real leak inside a field it was never
    meant to cover.  This class checks the scrubbed field directly, in both
    directions."""

    def test_the_disabled_sources_raw_value_is_visible_as_evidence(self) -> None:
        override = {"dlfSf": {"include": False}}
        payload = _fixture_raw_payload()
        mutated_payload = _swap_source_values(payload, "dlfSf", {"Josh Allen": _EXTREME_HIGH})
        contract = _by_name(build_api_data_contract(mutated_payload, source_overrides=override))
        self.assertEqual(
            contract["Josh Allen"]["canonicalSiteValues"]["dlfSf"],
            _EXTREME_HIGH,
            "a disabled source's own value must still be visible as raw "
            "evidence -- 'excluded from the vote' is not 'erased'",
        )

    def test_but_the_same_change_moves_no_voting_field(self) -> None:
        override = {"dlfSf": {"include": False}}
        payload = _fixture_raw_payload()
        baseline = _by_name(build_api_data_contract(payload, source_overrides=override))
        mutated_payload = _swap_source_values(payload, "dlfSf", {"Josh Allen": _EXTREME_HIGH})
        mutated = _by_name(build_api_data_contract(mutated_payload, source_overrides=override))

        voting_fields = (
            "rankDerivedValue",
            "canonicalConsensusRank",
            "sourceRanks",
            "confidenceBucket",
            "confidenceAxes",
            "sourceRankPercentileSpread",
        )
        for field in voting_fields:
            self.assertEqual(
                baseline["Josh Allen"].get(field),
                mutated["Josh Allen"].get(field),
                f"{field} moved when only a DISABLED source's own value changed",
            )


class TestMutationProofOfTheEnableGate(unittest.TestCase):
    """Prove the tests above would actually catch the defect they exist to
    catch, by deliberately reintroducing it and requiring RED, then
    restoring and requiring GREEN.  A guard that stays green when the gate
    it guards is broken proves nothing -- this is that check."""

    def test_forcing_every_source_enabled_breaks_the_invariant_then_restores(self) -> None:
        override = {"dlfSf": {"include": False}}
        payload = _fixture_raw_payload()
        baseline = build_api_data_contract(payload, source_overrides=override)
        mutated_payload = _swap_source_values(
            payload, "dlfSf", {"Josh Allen": _EXTREME_LOW, "Veteran TE": _EXTREME_HIGH}
        )

        original = _data_contract._source_is_enabled

        def _always_enabled(src: dict[str, Any], source_overrides: dict | None) -> bool:
            # The mutation: pretend nothing was ever disabled.  If the
            # invariant test above is real, this must turn it red.
            return True

        _data_contract._source_is_enabled = _always_enabled
        try:
            broken = build_api_data_contract(mutated_payload, source_overrides=override)
            mutation_was_caught = _stable(baseline) != _stable(broken)
        finally:
            _data_contract._source_is_enabled = original

        self.assertTrue(
            mutation_was_caught,
            "mutating _source_is_enabled to ignore overrides did not change the "
            "contract at all -- the invariant tests in this file would not have "
            "caught the exact defect (a disabled source silently voting) they "
            "exist to catch",
        )

        restored = build_api_data_contract(mutated_payload, source_overrides=override)
        self.assertEqual(_stable(baseline), _stable(restored))

    def test_forcing_zero_weight_to_a_positive_floor_breaks_the_invariant_then_restores(
        self,
    ) -> None:
        """A second, independent mutation of the same gate: make
        ``_effective_source_weight`` refuse to return a non-positive weight,
        the way the PRE-fix code (PR #530) behaved."""
        override = {"dlfSf": {"weight": 0}}
        payload = _fixture_raw_payload()
        baseline = build_api_data_contract(payload, source_overrides=override)
        mutated_payload = _swap_source_values(
            payload, "dlfSf", {"Josh Allen": _EXTREME_LOW, "Veteran TE": _EXTREME_HIGH}
        )

        original = _data_contract._effective_source_weight

        def _floor_at_one(src: dict[str, Any], source_overrides: dict | None) -> float:
            w = original(src, source_overrides)
            return w if w > 0 else 1.0  # the pre-#530 defect, reintroduced

        _data_contract._effective_source_weight = _floor_at_one
        try:
            broken = build_api_data_contract(mutated_payload, source_overrides=override)
            mutation_was_caught = _stable(baseline) != _stable(broken)
        finally:
            _data_contract._effective_source_weight = original

        self.assertTrue(
            mutation_was_caught,
            "mutating _effective_source_weight to floor a zero weight at 1.0 did "
            "not change the contract -- this is the exact historical defect PR "
            "#530 fixed, and the invariant test above would not have caught its "
            "return",
        )

        restored = build_api_data_contract(mutated_payload, source_overrides=override)
        self.assertEqual(_stable(baseline), _stable(restored))


class TestDownstreamTradeSurfaceIsUnaffected(unittest.TestCase):
    """The trade engines never read the raw payload -- they read
    ``rankDerivedValue`` off the built contract (CLAUDE.md ``valuation_mode``
    section; pinned separately by ``tests/api/test_one_canonical_value_per_asset.py``
    and the whole C3-CON-01/C3-CAP-01 Trade lane).  So proving the contract's
    ``rankDerivedValue`` is invariant to a disabled source's magnitude IS the
    trade-level proof: nothing downstream can see a difference the contract
    itself does not carry.  This test names that value explicitly rather
    than leaving it implicit in the whole-contract comparisons above."""

    def test_rank_derived_value_is_the_field_trade_reads_and_it_does_not_move(self) -> None:
        override = {"dlfSf": {"include": False}}
        payload = _fixture_raw_payload()
        baseline = _by_name(build_api_data_contract(payload, source_overrides=override))

        mutated_payload = _swap_source_values(
            payload, "dlfSf", {"Josh Allen": _EXTREME_LOW, "Veteran TE": _EXTREME_HIGH}
        )
        mutated = _by_name(build_api_data_contract(mutated_payload, source_overrides=override))

        for name in baseline:
            self.assertEqual(
                baseline[name].get("rankDerivedValue"),
                mutated[name].get("rankDerivedValue"),
                f"{name}: rankDerivedValue moved despite the only change being a "
                "DISABLED source's own value -- src/trade/* would see this",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
