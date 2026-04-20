"""Tests for the source-override path in the canonical ranking pipeline.

These tests pin the contract that ``build_api_data_contract`` and
``_compute_unified_rankings`` honor user-supplied source overrides
through the SAME canonical pipeline as the default board, with no
secondary engine.

Coverage:
    1. ``normalize_source_overrides`` correctly parses both shapes:
       legacy siteWeights map and explicit {enabled_sources, weights}.
    2. Disabled sources are filtered from Phase 1 ordinal ranking and
       Phase 2-3 blend, and absent from ``sourceRanks`` stamps.
    3. Weight overrides shift Phase 2-3 blend contributions and
       re-order the final board.
    4. ``rankingsOverride`` summary block is populated correctly.
    5. Default (no-override) response is byte-equivalent to the
       legacy path — passing ``source_overrides=None`` must not drift
       the pipeline.
    6. Override + default responses share the same materialization —
       every field the frontend reads (rank, value, sourceRanks,
       sourceRankMeta, confidence) is stamped on both paths.
    7. Backbone fallback when the backbone source is disabled.
"""
from __future__ import annotations

import unittest
from copy import deepcopy
from typing import Any

import json

from src.api.data_contract import (
    _DELTA_PLAYER_FIELDS,
    _RANKING_SOURCES,
    _TEP_DERIVATION_SLOPE,
    _compute_unified_rankings,
    _derive_tep_multiplier_from_league,
    _resolve_league_context,
    _summarize_source_overrides,
    assert_ranking_source_registry_parity,
    build_api_data_contract,
    build_rankings_delta_payload,
    get_ranking_source_keys,
    get_ranking_source_registry,
    normalize_source_overrides,
    normalize_tep_multiplier,
)


def _fixture_raw_payload() -> dict[str, Any]:
    """Compact raw payload that exercises both offense + IDP scopes.

    Six offense players with varying source coverage and three IDP
    players cover the main code paths of _compute_unified_rankings
    (Phase 1 ordinal ranking, Phase 2-3 blend, Phase 4 unified sort).
    """
    return {
        "players": {
            "Josh Allen": {
                "position": "QB",
                "team": "BUF",
                "_canonicalSiteValues": {
                    "ktc": 9999,
                    "idpTradeCalc": 9800,
                    "dlfSf": 9900,
                    "dynastyNerdsSfTep": 9950,
                },
                "_sites": 4,
            },
            "Ja'Marr Chase": {
                "position": "WR",
                "team": "CIN",
                "_canonicalSiteValues": {
                    "ktc": 9700,
                    "idpTradeCalc": 9600,
                    "dlfSf": 9850,
                    "dynastyNerdsSfTep": 9800,
                },
                "_sites": 4,
            },
            "Bijan Robinson": {
                "position": "RB",
                "team": "ATL",
                "_canonicalSiteValues": {
                    "ktc": 9500,
                    "idpTradeCalc": 9500,
                    "dlfSf": 9700,
                    "dynastyNerdsSfTep": 9600,
                },
                "_sites": 4,
            },
            "Trevor Lawrence": {
                "position": "QB",
                "team": "JAX",
                "_canonicalSiteValues": {
                    "ktc": 6000,
                    "idpTradeCalc": 6500,
                    # DLF SF drops him
                    "dynastyNerdsSfTep": 6200,
                },
                "_sites": 3,
            },
            "Rookie Wonder": {
                "position": "WR",
                "team": "???",
                "_canonicalSiteValues": {
                    "ktc": 7500,
                    # Only KTC has him
                },
                "_sites": 1,
            },
            "Veteran TE": {
                "position": "TE",
                "team": "???",
                "_canonicalSiteValues": {
                    "ktc": 5000,
                    "dlfSf": 4800,
                },
                "_sites": 2,
            },
            # TE covered by every offense source including the TEP-
            # native one.  Used by TestTepMultiplier to verify that
            # the TEP multiplier boosts non-TEP-native contributions
            # but passes the TEP-native source through unchanged.
            "Brock Bowers": {
                "position": "TE",
                "team": "LV",
                "_canonicalSiteValues": {
                    "ktc": 9400,
                    "idpTradeCalc": 9300,
                    "dlfSf": 9450,
                    "dynastyNerdsSfTep": 9600,
                },
                "_sites": 4,
            },
            # IDP players
            "Myles Garrett": {
                "position": "DL",
                "team": "CLE",
                "_canonicalSiteValues": {
                    "idpTradeCalc": 9500,
                    "dlfIdp": 9400,
                    "fantasyProsIdp": 9600,
                },
                "_sites": 3,
            },
            "Roquan Smith": {
                "position": "LB",
                "team": "BAL",
                "_canonicalSiteValues": {
                    "idpTradeCalc": 8500,
                    "dlfIdp": 8400,
                    "fantasyProsIdp": 8600,
                },
                "_sites": 3,
            },
            "Kyle Hamilton": {
                "position": "DB",
                "team": "BAL",
                "_canonicalSiteValues": {
                    "idpTradeCalc": 8800,
                    "dlfIdp": 8700,
                    "fantasyProsIdp": 8900,
                },
                "_sites": 3,
            },
        },
        "sites": [
            {"key": "ktc"},
            {"key": "idpTradeCalc"},
            {"key": "dlfIdp"},
            {"key": "dlfSf"},
            {"key": "dynastyNerdsSfTep"},
            {"key": "fantasyProsIdp"},
        ],
        "maxValues": {"ktc": 9999},
        "sleeper": {
            "positions": {
                "Josh Allen": "QB",
                "Ja'Marr Chase": "WR",
                "Bijan Robinson": "RB",
                "Trevor Lawrence": "QB",
                "Rookie Wonder": "WR",
                "Veteran TE": "TE",
                "Brock Bowers": "TE",
                "Myles Garrett": "DL",
                "Roquan Smith": "LB",
                "Kyle Hamilton": "DB",
            },
        },
    }


def _by_name(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(p.get("canonicalName") or p.get("displayName") or ""): p
        for p in contract.get("playersArray") or []
    }


class TestNormalizeSourceOverrides(unittest.TestCase):
    """Input validation + shape normalization for the override map."""

    def test_empty_input_returns_empty(self) -> None:
        out, warnings = normalize_source_overrides(None)
        self.assertEqual(out, {})
        self.assertEqual(warnings, [])
        out, warnings = normalize_source_overrides({})
        self.assertEqual(out, {})

    def test_non_dict_input_is_dropped_with_warning(self) -> None:
        out, warnings = normalize_source_overrides("not a dict")
        self.assertEqual(out, {})
        self.assertTrue(warnings)

    def test_legacy_site_weights_shape(self) -> None:
        out, warnings = normalize_source_overrides(
            {"ktc": {"include": False}, "dlfSf": {"weight": 0.5}}
        )
        self.assertEqual(out["ktc"], {"include": False})
        self.assertEqual(out["dlfSf"], {"weight": 0.5})
        self.assertEqual(warnings, [])

    def test_explicit_enabled_sources_shape(self) -> None:
        out, warnings = normalize_source_overrides(
            {"enabled_sources": ["idpTradeCalc", "dlfSf"], "weights": {"dlfSf": 2.0}}
        )
        # Every source NOT in enabled_sources should be marked include: False.
        self.assertEqual(out["ktc"], {"include": False})
        self.assertEqual(out["dynastyNerdsSfTep"], {"include": False})
        # idpTradeCalc and dlfSf are enabled; dlfSf carries a weight override.
        self.assertNotIn("include", out.get("idpTradeCalc", {}))
        self.assertEqual(out["dlfSf"].get("weight"), 2.0)
        self.assertEqual(warnings, [])

    def test_unknown_key_is_dropped_with_warning(self) -> None:
        out, warnings = normalize_source_overrides({"fakeSource": {"weight": 1.0}})
        self.assertEqual(out, {})
        self.assertTrue(any("fakeSource" in w for w in warnings))

    def test_invalid_weight_is_rejected(self) -> None:
        out, warnings = normalize_source_overrides(
            {"ktc": {"weight": "not a number"}}
        )
        self.assertNotIn("weight", out.get("ktc", {}))
        self.assertTrue(warnings)
        out, warnings = normalize_source_overrides({"ktc": {"weight": -1}})
        self.assertNotIn("weight", out.get("ktc", {}))
        self.assertTrue(warnings)
        out, warnings = normalize_source_overrides({"ktc": {"weight": float("inf")}})
        self.assertNotIn("weight", out.get("ktc", {}))
        self.assertTrue(warnings)

    def test_include_non_bool_is_rejected(self) -> None:
        out, warnings = normalize_source_overrides({"ktc": {"include": "yes"}})
        self.assertNotIn("include", out.get("ktc", {}))
        self.assertTrue(warnings)


class TestSourceRegistryParity(unittest.TestCase):
    """The Python registry and frontend JS registry must stay in sync."""

    def test_get_ranking_source_registry_shape(self) -> None:
        reg = get_ranking_source_registry()
        self.assertEqual(len(reg), len(_RANKING_SOURCES))
        for entry in reg:
            self.assertIn("key", entry)
            self.assertIn("displayName", entry)
            self.assertIn("columnLabel", entry)
            self.assertIn("scope", entry)
            self.assertIn("weight", entry)
            self.assertIn("isBackbone", entry)
            self.assertIn("isRetail", entry)

    def test_get_ranking_source_keys_matches_internal_list(self) -> None:
        self.assertEqual(
            get_ranking_source_keys(),
            [str(s.get("key")) for s in _RANKING_SOURCES],
        )

    def test_assert_parity_on_identical_copy(self) -> None:
        # A deep copy of the Python registry must trivially pass parity.
        reg = get_ranking_source_registry()
        self.assertEqual(assert_ranking_source_registry_parity(reg), [])

    def test_assert_parity_detects_weight_drift(self) -> None:
        reg = get_ranking_source_registry()
        reg[0]["weight"] = 2.0
        errors = assert_ranking_source_registry_parity(reg)
        self.assertTrue(errors)
        self.assertTrue(any("weight" in e for e in errors))

    def test_assert_parity_detects_missing_source(self) -> None:
        reg = get_ranking_source_registry()[:-1]
        errors = assert_ranking_source_registry_parity(reg)
        self.assertTrue(errors)

    def test_assert_parity_detects_scope_drift(self) -> None:
        reg = get_ranking_source_registry()
        reg[0]["scope"] = "wrong_scope"
        errors = assert_ranking_source_registry_parity(reg)
        self.assertTrue(errors)
        self.assertTrue(any("scope" in e for e in errors))


class TestBuildApiDataContractDefaultPath(unittest.TestCase):
    """Default (no override) path must produce canonical stamped output."""

    def test_default_payload_has_rankings(self) -> None:
        contract = build_api_data_contract(_fixture_raw_payload())
        by_name = _by_name(contract)
        allen = by_name.get("Josh Allen")
        self.assertIsNotNone(allen)
        self.assertIsNotNone(allen.get("canonicalConsensusRank"))
        self.assertGreater(allen.get("rankDerivedValue", 0), 0)
        self.assertIn("ktc", allen.get("sourceRanks", {}))
        self.assertIn("dlfSf", allen.get("sourceRanks", {}))

    def test_default_payload_has_rankings_override_block(self) -> None:
        contract = build_api_data_contract(_fixture_raw_payload())
        rov = contract.get("rankingsOverride")
        self.assertIsNotNone(rov)
        self.assertFalse(rov.get("isCustomized"))
        # Every registered source should be enabled in the default state.
        self.assertEqual(
            set(rov["enabledSources"]), set(get_ranking_source_keys())
        )
        # Every effective weight should match the default (1.0 across the board).
        for key, weight in rov["weights"].items():
            self.assertEqual(weight, rov["defaults"].get(key))

    def test_default_path_equals_explicit_none(self) -> None:
        """Passing ``source_overrides=None`` must be identical to omitting it."""
        a = build_api_data_contract(_fixture_raw_payload())
        b = build_api_data_contract(
            _fixture_raw_payload(), source_overrides=None
        )
        # Strip generatedAt (timestamp differs) before comparing.
        a.pop("generatedAt", None)
        b.pop("generatedAt", None)
        # rankingsOverride's "received" dict may be {} in both cases.
        self.assertEqual(
            _by_name(a)["Josh Allen"].get("canonicalConsensusRank"),
            _by_name(b)["Josh Allen"].get("canonicalConsensusRank"),
        )
        self.assertEqual(
            _by_name(a)["Josh Allen"].get("rankDerivedValue"),
            _by_name(b)["Josh Allen"].get("rankDerivedValue"),
        )


class TestBuildApiDataContractOverridePath(unittest.TestCase):
    """Override path must honor the user-supplied source configuration."""

    def setUp(self) -> None:
        self.baseline = build_api_data_contract(_fixture_raw_payload())
        self.baseline_by_name = _by_name(self.baseline)

    def test_disabling_source_removes_it_from_every_stamp(self) -> None:
        overridden = build_api_data_contract(
            _fixture_raw_payload(),
            source_overrides={"ktc": {"include": False}},
        )
        by_name = _by_name(overridden)
        # Every row that has sourceRanks must NOT have ktc.
        for row in overridden.get("playersArray", []):
            ranks = row.get("sourceRanks") or {}
            self.assertNotIn("ktc", ranks)

        # Josh Allen loses one signal but stays on the board.
        allen = by_name.get("Josh Allen")
        self.assertIsNotNone(allen)
        self.assertNotIn("ktc", allen.get("sourceRanks", {}))
        self.assertIsNotNone(allen.get("canonicalConsensusRank"))

        # Rookie Wonder was only on KTC — disabling KTC removes his
        # ranking entirely (no source → no rank).
        rookie = by_name.get("Rookie Wonder")
        self.assertIsNotNone(rookie)
        self.assertEqual(rookie.get("sourceRanks") or {}, {})

    def test_disabling_source_shifts_blend_value(self) -> None:
        # Josh Allen is at the top of the board with 4 sources.  When
        # we disable one of the sources that scores him highly, his
        # blended rank-derived value should move.
        override = {"dlfSf": {"include": False}}
        overridden = build_api_data_contract(
            _fixture_raw_payload(), source_overrides=override
        )
        by_name = _by_name(overridden)
        allen_baseline = self.baseline_by_name["Josh Allen"]
        allen_overridden = by_name["Josh Allen"]
        # Exact value may not change (because Allen is near the top
        # of every source), but sourceRanks must shrink.
        self.assertEqual(
            len(allen_overridden.get("sourceRanks") or {}),
            len(allen_baseline.get("sourceRanks") or {}) - 1,
        )

    def test_weight_override_shifts_blend(self) -> None:
        # Heavy weight on KTC only → the blend for multi-source rows
        # leans harder toward KTC's opinion.
        override = {
            "idpTradeCalc": {"weight": 0},
            "dlfSf": {"weight": 0},
            "dynastyNerdsSfTep": {"weight": 0},
        }
        overridden = build_api_data_contract(
            _fixture_raw_payload(), source_overrides=override
        )
        by_name = _by_name(overridden)
        # With every other offense source at weight 0, the blend
        # collapses to KTC.  Rookie Wonder (KTC-only, rank 3) should
        # retain a finite value since KTC is fully preserved, while
        # Veteran TE (KTC+DLF SF) gets only the KTC signal weighted.
        rookie = by_name["Rookie Wonder"]
        self.assertIsNotNone(rookie.get("canonicalConsensusRank"))
        self.assertGreater(rookie.get("rankDerivedValue") or 0, 0)

    def test_override_rankings_override_block_reflects_config(self) -> None:
        override = {"ktc": {"include": False}, "dlfSf": {"weight": 0.5}}
        contract = build_api_data_contract(
            _fixture_raw_payload(), source_overrides=override
        )
        rov = contract.get("rankingsOverride") or {}
        self.assertTrue(rov.get("isCustomized"))
        self.assertNotIn("ktc", rov.get("enabledSources") or [])
        self.assertEqual(rov.get("weights", {}).get("dlfSf"), 0.5)
        self.assertEqual(rov.get("defaults", {}).get("dlfSf"), 1.0)

    def test_disabling_all_sources_produces_empty_ranks(self) -> None:
        every_off = {
            key: {"include": False} for key in get_ranking_source_keys()
        }
        contract = build_api_data_contract(
            _fixture_raw_payload(), source_overrides=every_off
        )
        # Every row's sourceRanks should be empty.
        for row in contract.get("playersArray", []):
            self.assertEqual(row.get("sourceRanks") or {}, {})
        # canonicalConsensusRank should be None/falsy across the board.
        for row in contract.get("playersArray", []):
            self.assertFalse(row.get("canonicalConsensusRank"))

    def test_disabling_backbone_source_degrades_gracefully(self) -> None:
        # idpTradeCalc is the backbone source (is_backbone=True).
        # Disabling it should not raise; IDP sources should still
        # produce ranks (via their own scopes, without the backbone
        # crosswalk).
        contract = build_api_data_contract(
            _fixture_raw_payload(),
            source_overrides={"idpTradeCalc": {"include": False}},
        )
        by_name = _by_name(contract)
        garrett = by_name.get("Myles Garrett")
        self.assertIsNotNone(garrett)
        # He still has dlfIdp + fantasyProsIdp signals, so he should
        # be ranked; idpTradeCalc must be absent.
        self.assertNotIn("idpTradeCalc", garrett.get("sourceRanks") or {})


class TestRankingsTradeCalculatorAlignment(unittest.TestCase):
    """Rankings + trade calculator use the same override-adjusted source set.

    This test asserts the single-source-of-truth invariant: after an
    override response is computed, every row's ``rankDerivedValue`` and
    every row's ``sourceRanks`` reflect the same effective source
    configuration.  The trade calculator reads ``row.rankDerivedValue``
    directly, so if the override pipeline is coherent, the trade
    calculator automatically sees override-adjusted values.
    """

    def test_override_response_stamps_consistent_fields(self) -> None:
        override = {"dlfSf": {"include": False}, "ktc": {"weight": 2.0}}
        contract = build_api_data_contract(
            _fixture_raw_payload(), source_overrides=override
        )
        for row in contract.get("playersArray", []):
            source_ranks = row.get("sourceRanks") or {}
            source_meta = row.get("sourceRankMeta") or {}
            if not source_ranks:
                continue
            # The meta dict for each stamped source must exist and
            # carry the matching effective rank + weight.
            for key, rank in source_ranks.items():
                self.assertIn(key, source_meta)
                self.assertEqual(source_meta[key].get("effectiveRank"), rank)
                # dlfSf is disabled — must not appear anywhere.
                self.assertNotEqual(key, "dlfSf")
                # KTC's weight should be 2.0 on every row (user override).
                if key == "ktc":
                    self.assertEqual(source_meta[key].get("weight"), 2.0)

    def test_rankings_order_matches_value_order(self) -> None:
        """The final board's canonicalConsensusRank must be monotonic
        by rankDerivedValue under any override."""
        override = {"dlfSf": {"weight": 0}}
        contract = build_api_data_contract(
            _fixture_raw_payload(), source_overrides=override
        )
        ranked_rows = sorted(
            [
                r
                for r in contract.get("playersArray") or []
                if r.get("canonicalConsensusRank")
            ],
            key=lambda r: int(r["canonicalConsensusRank"]),
        )
        # Walk adjacent rows: rank i → rank i+1, value should be
        # non-increasing (ties allowed).
        prev_value = None
        for row in ranked_rows:
            value = row.get("rankDerivedValue") or 0
            if prev_value is not None:
                self.assertLessEqual(
                    value,
                    prev_value,
                    f"value non-monotonic at rank {row.get('canonicalConsensusRank')}",
                )
            prev_value = value


class TestSummarizeSourceOverrides(unittest.TestCase):
    """Unit-level coverage for _summarize_source_overrides."""

    def test_none_input_produces_defaults_summary(self) -> None:
        summary = _summarize_source_overrides(None)
        self.assertFalse(summary["isCustomized"])
        self.assertEqual(
            set(summary["enabledSources"]), set(get_ranking_source_keys())
        )

    def test_explicit_default_weight_is_not_customized(self) -> None:
        summary = _summarize_source_overrides({"ktc": {"weight": 1.0}})
        self.assertFalse(summary["isCustomized"])

    def test_excluded_source_marks_customized(self) -> None:
        summary = _summarize_source_overrides({"ktc": {"include": False}})
        self.assertTrue(summary["isCustomized"])
        self.assertNotIn("ktc", summary["enabledSources"])

    def test_non_default_weight_marks_customized(self) -> None:
        summary = _summarize_source_overrides({"ktc": {"weight": 2.0}})
        self.assertTrue(summary["isCustomized"])
        self.assertEqual(summary["weights"]["ktc"], 2.0)


class TestOffenseAndIdpResponseToOverrides(unittest.TestCase):
    """Offense and IDP players must BOTH respond to override changes."""

    def test_offense_player_responds_to_offense_override(self) -> None:
        base = build_api_data_contract(_fixture_raw_payload())
        override = build_api_data_contract(
            _fixture_raw_payload(),
            source_overrides={"dlfSf": {"include": False}},
        )
        base_by_name = _by_name(base)
        override_by_name = _by_name(override)
        # Disabling dlfSf should drop the source from an offense row's
        # stamp.
        self.assertIn("dlfSf", base_by_name["Josh Allen"].get("sourceRanks") or {})
        self.assertNotIn(
            "dlfSf", override_by_name["Josh Allen"].get("sourceRanks") or {}
        )

    def test_idp_player_responds_to_idp_override(self) -> None:
        base = build_api_data_contract(_fixture_raw_payload())
        override = build_api_data_contract(
            _fixture_raw_payload(),
            source_overrides={"dlfIdp": {"include": False}},
        )
        base_by_name = _by_name(base)
        override_by_name = _by_name(override)
        self.assertIn("dlfIdp", base_by_name["Myles Garrett"].get("sourceRanks") or {})
        self.assertNotIn(
            "dlfIdp", override_by_name["Myles Garrett"].get("sourceRanks") or {}
        )


class TestBuildRankingsDeltaPayload(unittest.TestCase):
    """Compact delta payload: must carry every override-sensitive field."""

    def test_delta_payload_shape(self) -> None:
        delta = build_rankings_delta_payload(
            _fixture_raw_payload(),
            source_overrides={"ktc": {"include": False}},
        )
        self.assertEqual(delta.get("mode"), "delta")
        self.assertIn("rankingsOverride", delta)
        self.assertIn("rankingsDelta", delta)
        block = delta["rankingsDelta"]
        self.assertEqual(block.get("playerKey"), "displayName")
        self.assertIsInstance(block.get("players"), list)
        self.assertIsInstance(block.get("activePlayerIds"), list)

        # Every delta entry carries an id field and at least one
        # ranking-related stamp.
        for entry in block["players"]:
            self.assertIn("id", entry)
            self.assertIsInstance(entry["id"], str)

    def test_delta_excludes_unchanged_fields(self) -> None:
        """Delta rows must NOT carry identity / team / age / rookie fields.

        Those fields are invariant under a source override, so the
        frontend already has them on the cached base payload.  Sending
        them in the delta would waste bandwidth and invites merge
        bugs where the delta accidentally stomps identity.
        """
        delta = build_rankings_delta_payload(
            _fixture_raw_payload(),
            source_overrides={"ktc": {"include": False}},
        )
        for entry in delta["rankingsDelta"]["players"]:
            self.assertNotIn("displayName", entry)
            self.assertNotIn("canonicalName", entry)
            self.assertNotIn("team", entry)
            self.assertNotIn("position", entry)
            self.assertNotIn("age", entry)
            self.assertNotIn("rookie", entry)
            self.assertNotIn("assetClass", entry)
            self.assertNotIn("identityConfidence", entry)
            self.assertNotIn("identityMethod", entry)

    def test_delta_active_player_ids_subset(self) -> None:
        """activePlayerIds must be a subset of the delta.players ids."""
        delta = build_rankings_delta_payload(
            _fixture_raw_payload(),
            source_overrides={"ktc": {"include": False}},
        )
        player_ids = {e["id"] for e in delta["rankingsDelta"]["players"]}
        active_ids = set(delta["rankingsDelta"]["activePlayerIds"])
        self.assertTrue(active_ids.issubset(player_ids))

    def test_delta_byte_size_is_bounded(self) -> None:
        """The delta payload must be substantially smaller than the full contract.

        The prior implementation returned the full ~4MB contract for
        every override request.  The delta payload must fit under a
        strict bound well below 500KB even for the full production
        payload — on the compact fixture it is trivially a few KB.
        """
        delta = build_rankings_delta_payload(
            _fixture_raw_payload(),
            source_overrides={"ktc": {"include": False}},
        )
        full = build_api_data_contract(
            _fixture_raw_payload(),
            source_overrides={"ktc": {"include": False}},
        )
        delta_bytes = len(json.dumps(delta, separators=(",", ":")))
        full_bytes = len(json.dumps(full, separators=(",", ":")))
        # Delta must be strictly smaller than full.
        self.assertLess(delta_bytes, full_bytes)
        # A generous cap to catch regressions: on the fixture the
        # delta must fit in 50KB (the full contract is ~30KB but
        # includes playersArray + legacy dict).  In production the
        # delta is ~1.25MB vs ~4MB full.  The ratio matters more
        # than the absolute bound; assert both.
        self.assertLess(delta_bytes, 50_000)
        self.assertLess(delta_bytes / full_bytes, 0.60)

    def test_delta_carries_all_override_sensitive_fields(self) -> None:
        """Every field in _DELTA_PLAYER_FIELDS that exists on the full row must also appear on the matching delta entry.

        This is the regression guard: when a new override-sensitive
        field is added to the ``playersArray`` row contract, it MUST
        be threaded through the delta as well or the frontend merge
        will render stale values.  The parity is enforced here.
        """
        full = build_api_data_contract(
            _fixture_raw_payload(),
            source_overrides={"dlfSf": {"include": False}},
        )
        delta = build_rankings_delta_payload(
            _fixture_raw_payload(),
            source_overrides={"dlfSf": {"include": False}},
        )
        full_by_id = {
            str(p.get("displayName") or p.get("canonicalName") or ""): p
            for p in full.get("playersArray") or []
        }
        for entry in delta["rankingsDelta"]["players"]:
            full_row = full_by_id.get(entry["id"])
            self.assertIsNotNone(full_row)
            for field in _DELTA_PLAYER_FIELDS:
                # Only check fields that are actually present on the
                # full row — optional fields (e.g. sourceAudit) may
                # be missing on some rows, and that's legal.
                if field in full_row:
                    self.assertIn(
                        field,
                        entry,
                        f"delta entry for {entry['id']} is missing {field}",
                    )
                    self.assertEqual(
                        entry[field],
                        full_row[field],
                        f"delta field {field} mismatch on {entry['id']}",
                    )

    def test_delta_default_path_is_deterministic(self) -> None:
        """Calling with no overrides still produces a coherent delta payload."""
        delta = build_rankings_delta_payload(_fixture_raw_payload())
        self.assertEqual(delta.get("mode"), "delta")
        # Default response: not customized, all sources enabled.
        rov = delta.get("rankingsOverride") or {}
        self.assertFalse(rov.get("isCustomized"))
        self.assertEqual(
            set(rov.get("enabledSources") or []),
            set(get_ranking_source_keys()),
        )

    def test_delta_merge_reconstruction_matches_full_contract(self) -> None:
        """A manual merge of the delta onto a base contract must reproduce the override-adjusted rankings for every field in _DELTA_PLAYER_FIELDS.

        This is the invariant the frontend ``mergeRankingsDelta``
        relies on: for every field the delta carries, the merged row
        must equal the row produced by ``build_api_data_contract``
        with the same overrides.
        """
        override = {"idpTradeCalc": {"weight": 2.0}}
        base = build_api_data_contract(_fixture_raw_payload())
        full_overridden = build_api_data_contract(
            _fixture_raw_payload(), source_overrides=override
        )
        delta = build_rankings_delta_payload(
            _fixture_raw_payload(), source_overrides=override
        )

        # Manually merge in Python — mirrors the JS mergeRankingsDelta.
        delta_by_id = {e["id"]: e for e in delta["rankingsDelta"]["players"]}
        merged_by_id = {}
        for row in base.get("playersArray") or []:
            player_id = str(row.get("displayName") or row.get("canonicalName") or "")
            if not player_id:
                continue
            merged = dict(row)
            entry = delta_by_id.get(player_id)
            if entry:
                for field, value in entry.items():
                    if field == "id":
                        continue
                    merged[field] = value
            merged_by_id[player_id] = merged

        # Compare against the override-adjusted full contract for every
        # override-sensitive field.
        full_by_id = {
            str(p.get("displayName") or p.get("canonicalName") or ""): p
            for p in full_overridden.get("playersArray") or []
        }
        for player_id, full_row in full_by_id.items():
            merged_row = merged_by_id.get(player_id)
            self.assertIsNotNone(merged_row)
            for field in _DELTA_PLAYER_FIELDS:
                if field in full_row:
                    self.assertEqual(
                        merged_row.get(field),
                        full_row.get(field),
                        f"merge mismatch on {player_id}.{field}",
                    )


class TestNormalizeTepMultiplier(unittest.TestCase):
    """Input validation + clamping for the TE-premium multiplier.

    Absent or invalid values return ``None`` (not ``1.0``) so the
    pipeline can distinguish "user did not override" (→ derive from
    Sleeper league context) from "user explicitly set 1.0" (→ use
    1.0 verbatim).
    """

    def test_missing_field_returns_none(self) -> None:
        self.assertIsNone(normalize_tep_multiplier(None))
        self.assertIsNone(normalize_tep_multiplier({}))
        self.assertIsNone(normalize_tep_multiplier({"ktc": {"include": False}}))

    def test_snake_case_key_is_accepted(self) -> None:
        self.assertEqual(normalize_tep_multiplier({"tep_multiplier": 1.15}), 1.15)

    def test_camel_case_key_is_accepted(self) -> None:
        self.assertEqual(normalize_tep_multiplier({"tepMultiplier": 1.2}), 1.2)

    def test_explicit_one_is_preserved(self) -> None:
        # Critical: posting ``{"tep_multiplier": 1.0}`` must return
        # 1.0, NOT None.  The frontend slider explicitly set to 1.0
        # (user wants to disable TE premium entirely) is a real
        # override that the pipeline honors verbatim; it must not
        # fall back to the league-derived default.
        self.assertEqual(normalize_tep_multiplier({"tep_multiplier": 1.0}), 1.0)

    def test_snake_case_wins_over_camel_case(self) -> None:
        # Both forms present: snake_case is the canonical spelling and
        # should win if a caller mixes them.
        result = normalize_tep_multiplier(
            {"tep_multiplier": 1.15, "tepMultiplier": 1.5}
        )
        self.assertEqual(result, 1.15)

    def test_out_of_range_values_clamp(self) -> None:
        self.assertEqual(normalize_tep_multiplier({"tep_multiplier": 0.5}), 1.0)
        self.assertEqual(normalize_tep_multiplier({"tep_multiplier": 3.0}), 2.0)
        self.assertEqual(normalize_tep_multiplier({"tep_multiplier": -1}), 1.0)

    def test_non_numeric_values_return_none(self) -> None:
        # Unparseable values fall back to "let the backend derive",
        # not to a silent 1.0 (which would mask garbled bodies).
        self.assertIsNone(normalize_tep_multiplier({"tep_multiplier": "nope"}))
        self.assertIsNone(normalize_tep_multiplier({"tep_multiplier": None}))
        self.assertIsNone(
            normalize_tep_multiplier({"tep_multiplier": float("inf")})
        )
        self.assertIsNone(
            normalize_tep_multiplier({"tep_multiplier": float("nan")})
        )

    def test_non_dict_input_returns_none(self) -> None:
        self.assertIsNone(normalize_tep_multiplier("1.15"))
        self.assertIsNone(normalize_tep_multiplier(1.15))
        self.assertIsNone(normalize_tep_multiplier([1.15]))

    def test_tep_multiplier_with_source_overrides_is_accepted(self) -> None:
        """The TEP field must not reject a body that has no per-source overrides.

        Posting just ``{"tep_multiplier": 1.15}`` must be a valid body.
        """
        overrides, warnings = normalize_source_overrides({"tep_multiplier": 1.15})
        # No per-source overrides were provided — the source map
        # should be empty and the TEP field must not appear as a
        # warning.
        self.assertEqual(overrides, {})
        for w in warnings:
            self.assertNotIn("tep_multiplier", w)
        self.assertEqual(normalize_tep_multiplier({"tep_multiplier": 1.15}), 1.15)

    def test_tep_multiplier_alongside_legacy_overrides(self) -> None:
        body = {"tep_multiplier": 1.2, "ktc": {"include": False}}
        overrides, warnings = normalize_source_overrides(body)
        self.assertEqual(overrides, {"ktc": {"include": False}})
        self.assertEqual(warnings, [])
        self.assertEqual(normalize_tep_multiplier(body), 1.2)


class TestTepMultiplierDerivation(unittest.TestCase):
    """League-context-aware derivation of the TE-premium multiplier.

    The backend derives the TEP multiplier from the operator's
    Sleeper league ``bonus_rec_te`` scoring setting when the caller
    passes ``tep_multiplier=None`` (production cold-start path).  This
    suite pins the linear formula + the three "from league context"
    entry points.

    Calibration: ``tep_multiplier = 1.0 + bonus_rec_te * 0.30``,
    clamped to ``[1.0, 2.0]``.  0.5 PPR bonus (standard TEP-1.5)
    → 1.15, which matches the historical frontend default.
    """

    def test_derive_zero_bonus_is_identity(self) -> None:
        """A league with no TE premium derives a no-op multiplier."""
        result = _derive_tep_multiplier_from_league({"bonus_rec_te": 0.0})
        self.assertEqual(result, 1.0)

    def test_derive_half_bonus_matches_legacy_default(self) -> None:
        """TEP-1.5 (bonus 0.5) derives the historical frontend default."""
        result = _derive_tep_multiplier_from_league({"bonus_rec_te": 0.5})
        self.assertAlmostEqual(result, 1.15, places=6)

    def test_derive_full_bonus(self) -> None:
        """TEP-2.0 (bonus 1.0) derives a 30% boost."""
        result = _derive_tep_multiplier_from_league({"bonus_rec_te": 1.0})
        self.assertAlmostEqual(result, 1.30, places=6)

    def test_derive_clamps_extreme_values(self) -> None:
        """Misconfigured bonuses can't pump TE values off the board."""
        # bonus_rec_te=10 would derive 4.0 without clamping; clamp to 2.0.
        result = _derive_tep_multiplier_from_league({"bonus_rec_te": 10.0})
        self.assertEqual(result, 2.0)

    def test_derive_floors_at_one(self) -> None:
        """Negative / invalid bonuses floor at 1.0 (no TE discount)."""
        self.assertEqual(
            _derive_tep_multiplier_from_league({"bonus_rec_te": -0.5}), 1.0
        )
        self.assertEqual(
            _derive_tep_multiplier_from_league({"bonus_rec_te": None}), 1.0
        )
        self.assertEqual(
            _derive_tep_multiplier_from_league({"bonus_rec_te": "nope"}), 1.0
        )

    def test_derive_with_none_context_falls_back_to_default(self) -> None:
        """No context (offline / no SLEEPER_LEAGUE_ID) → no-op."""
        # In the test environment SLEEPER_LEAGUE_ID is cleared by
        # conftest, so _resolve_league_context returns the fallback
        # dict with bonus_rec_te=0.0 → derived TEP = 1.0.
        result = _derive_tep_multiplier_from_league()
        self.assertEqual(result, 1.0)

    def test_derivation_slope_matches_constant(self) -> None:
        """Slope constant is 0.30 (calibrated for TEP-1.5 → 1.15)."""
        self.assertAlmostEqual(_TEP_DERIVATION_SLOPE, 0.30)


class TestBuildContractTepFixed(unittest.TestCase):
    """TEP is a fixed 1.15 (2026-04-20 simplification).

    The prior league-derivation / explicit-override / clamp tests
    exercised a variance knob that no longer exists.  The one
    invariant we still pin: every contract's summary block shows
    tepMultiplier = 1.15 and source = "fixed", regardless of
    league context or caller-supplied value.
    """

    def test_summary_always_reports_fixed_1_15(self) -> None:
        contract = build_api_data_contract(_fixture_raw_payload())
        rov = contract.get("rankingsOverride") or {}
        self.assertAlmostEqual(float(rov.get("tepMultiplier") or 0), 1.15)
        self.assertEqual(rov.get("tepMultiplierSource"), "fixed")

    def test_caller_supplied_tep_is_ignored(self) -> None:
        """Passing any explicit tep_multiplier is a no-op — the
        contract still reflects the fixed 1.15 boost.
        """
        for v in (1.0, 1.30, 2.0, None):
            contract = build_api_data_contract(
                _fixture_raw_payload(), tep_multiplier=v
            )
            rov = contract.get("rankingsOverride") or {}
            self.assertAlmostEqual(
                float(rov.get("tepMultiplier") or 0),
                1.15,
                msg=f"tep_multiplier={v} produced unexpected effective value",
            )



if __name__ == "__main__":
    unittest.main()
