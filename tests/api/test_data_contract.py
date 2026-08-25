import unittest

from src.api.data_contract import (
    OVERALL_RANK_LIMIT,
    _SINGLE_SOURCE_VALUE_RETENTION,
    _compute_unified_rankings,
    build_api_data_contract,
    validate_api_data_contract,
)
from src.canonical.player_valuation import percentile_to_value, rank_to_value  # noqa: F401


def _minimal_raw_payload():
    """Minimal raw scraper-shaped payload for contract builder tests."""
    return {
        "players": {
            "Josh Allen": {
                "_composite": 8500,
                "_rawComposite": 8500,
                "_finalAdjusted": 8400,
                "_sites": 6,
                "position": "QB",
                "team": "BUF",
            },
            "Ja'Marr Chase": {
                "_composite": 9200,
                "_rawComposite": 9200,
                "_finalAdjusted": 9100,
                "_sites": 7,
                "position": "WR",
                "team": "CIN",
            },
        },
        "sites": [{"key": "ktcSfTep"}, {"key": "idpTradeCalc"}],
        "maxValues": {"ktcSfTep": 9999},
        "sleeper": {"positions": {"Josh Allen": "QB", "Ja'Marr Chase": "WR"}},
    }


class TestComputeKtcRankings(unittest.TestCase):
    """Tests for _compute_unified_rankings — the backend single source of truth.

    This function stamps ktcRank + rankDerivedValue onto playersArray entries
    and mirrors them back to the legacy players dict.  Both JS frontends then
    consume these pre-computed values instead of recomputing independently.
    """

    def _make_player_row(self, name: str, pos: str, ktc: int) -> dict:
        """Minimal playersArray-shaped row with a KTC site value."""
        return {
            "canonicalName": name,
            "displayName": name,
            "legacyRef": name,
            "position": pos,
            "assetClass": "offense",
            "values": {
                "overall": ktc,
                "rawComposite": ktc,
                "finalAdjusted": ktc,
                "displayValue": None,
            },
            "canonicalSiteValues": {"ktcSfTep": ktc},
            "sourceCount": 1,
        }

    def test_top_player_gets_rank_1(self):
        rows = [
            self._make_player_row("Alpha", "QB", 9000),
            self._make_player_row("Beta", "WR", 7000),
        ]
        _compute_unified_rankings(rows, {})
        alpha = next(r for r in rows if r["canonicalName"] == "Alpha")
        self.assertEqual(alpha["ktcRank"], 1)

    def test_rank_order_follows_ktc_value_descending(self):
        rows = [
            self._make_player_row("Low", "RB", 3000),
            self._make_player_row("High", "QB", 9000),
            self._make_player_row("Mid", "WR", 6000),
        ]
        _compute_unified_rankings(rows, {})
        by_rank = sorted(
            (r for r in rows if "ktcRank" in r),
            key=lambda r: r["ktcRank"],
        )
        self.assertEqual([r["canonicalName"] for r in by_rank], ["High", "Mid", "Low"])

    def test_rank_derived_value_for_solo_top_player(self):
        rows = [self._make_player_row("Solo", "QB", 9999)]
        _compute_unified_rankings(rows, {})
        self.assertEqual(rows[0]["ktcRank"], 1)
        # KTC is a value-based source under the Final Framework
        # override — its raw 0-9999 value is fed directly into the
        # blend.  The top player's KTC value (9999) is also the site's
        # max, so the normalized vote is 9999/9999 × 9999 = 9999.  This
        # fixture is single-source (KTC only), so the single-source
        # confidence haircut applies to BOTH the displayed value and
        # the rookie-tether fallback stamp (round vs truncate is the
        # only difference between the two).
        self.assertEqual(
            rows[0]["_blendedValueUncapped"],
            int(round(9999 * _SINGLE_SOURCE_VALUE_RETENTION)),
        )
        self.assertEqual(
            rows[0]["rankDerivedValue"],
            int(9999 * _SINGLE_SOURCE_VALUE_RETENTION),
        )

    def test_value_based_source_uses_raw_value_directly(self):
        """KTC is on the ``_VALUE_BASED_SOURCES`` allowlist, so its
        per-player contribution to ``rankDerivedValue`` is the raw
        ``canonicalSiteValues[ktc]`` normalized to 0-9999, NOT the
        Hill-converted value for the player's rank.

        This test constructs a single-source KTC pool where the raw
        values descend linearly and asserts the blended value tracks
        the raw value (scaled by the pool's max) rather than the
        Hill curve's output at the percentile of the player's rank.
        """
        rows = [self._make_player_row(f"P{i}", "WR", 9999 - i * 10) for i in range(60)]
        _compute_unified_rankings(rows, {})
        rank_50_row = next(r for r in rows if r.get("ktcRank") == 50)
        raw_v = rank_50_row["canonicalSiteValues"]["ktcSfTep"]
        # site_max comes from the same pool → P0's value 9999.
        site_max = 9999
        # This pool is KTC-only (single source), so the single-source
        # haircut applies to both the displayed ``rankDerivedValue``
        # and the rookie-tether ``_blendedValueUncapped`` fallback.
        # The value-direct mechanic still shows through: the haircut is
        # a flat scalar on the raw-normalized site value, NOT the Hill
        # output (asserted below).
        value_direct = raw_v / site_max * 9999.0
        self.assertEqual(
            rank_50_row["_blendedValueUncapped"],
            int(round(value_direct * _SINGLE_SOURCE_VALUE_RETENTION)),
        )
        self.assertEqual(
            rank_50_row["rankDerivedValue"],
            int(value_direct * _SINGLE_SOURCE_VALUE_RETENTION),
        )
        # And the value is NOT the Hill output at p=49/499 ≈ 0.098,
        # which would yield a much lower value under HILL_PERCENTILE_*.
        from src.api.data_contract import _PERCENTILE_REFERENCE_N  # noqa: PLC0415

        hill_p = (50 - 1) / (_PERCENTILE_REFERENCE_N - 1)
        hill_value = int(percentile_to_value(hill_p))
        self.assertNotEqual(
            rank_50_row["rankDerivedValue"],
            hill_value,
            "Value-based source should NOT be routed through the Hill "
            "curve — ``rankDerivedValue`` must reflect the raw normalized "
            "site value.",
        )

    def test_picks_included(self):
        """Picks with source values participate in the unified ranking."""
        rows = [
            self._make_player_row("2026 Early 1st", "PICK", 8000),
            self._make_player_row("Real Player", "QB", 7000),
        ]
        rows[0]["assetClass"] = "pick"
        _compute_unified_rankings(rows, {})
        pick = next(r for r in rows if r["canonicalName"] == "2026 Early 1st")
        self.assertEqual(pick["ktcRank"], 1)
        real = next(r for r in rows if r["canonicalName"] == "Real Player")
        self.assertEqual(real["ktcRank"], 2)

    def test_unresolved_position_excluded(self):
        rows = [
            self._make_player_row("UnknownGuy", "?", 8000),
            self._make_player_row("KnownGuy", "QB", 7000),
        ]
        _compute_unified_rankings(rows, {})
        unknown = next(r for r in rows if r["canonicalName"] == "UnknownGuy")
        self.assertNotIn("ktcRank", unknown)

    def test_zero_ktc_excluded(self):
        rows = [
            self._make_player_row("NoKtc", "WR", 0),
            self._make_player_row("HasKtc", "WR", 5000),
        ]
        _compute_unified_rankings(rows, {})
        no_ktc = next(r for r in rows if r["canonicalName"] == "NoKtc")
        self.assertNotIn("ktcRank", no_ktc)

    def test_respects_rank_limit(self):
        rows = [self._make_player_row(f"P{i}", "RB", 9000 - i) for i in range(900)]
        _compute_unified_rankings(rows, {})
        ranked = [r for r in rows if "canonicalConsensusRank" in r]
        self.assertEqual(len(ranked), OVERALL_RANK_LIMIT)

    def test_mirrors_to_legacy_players_dict(self):
        rows = [self._make_player_row("Josh Allen", "QB", 9000)]
        legacy = {"Josh Allen": {"ktcSfTep": 9000, "_finalAdjusted": 9000}}
        _compute_unified_rankings(rows, legacy)
        self.assertEqual(legacy["Josh Allen"]["ktcRank"], 1)
        # The legacy dict must mirror whatever the array row computed,
        # including the single-source haircut applied to this KTC-only
        # fixture — the assertion tracks the row, not a fixed constant.
        self.assertEqual(
            legacy["Josh Allen"]["rankDerivedValue"],
            rows[0]["rankDerivedValue"],
        )

    def test_build_api_data_contract_stamps_ktc_rank(self):
        """The full contract builder must include ktcRank in playersArray."""
        raw = {
            "players": {
                "Josh Allen": {
                    "_composite": 9000,
                    "_rawComposite": 9000,
                    "_finalAdjusted": 9000,
                    "_canonicalSiteValues": {"ktcSfTep": 9000},
                    "position": "QB",
                },
                "Ja'Marr Chase": {
                    "_composite": 8500,
                    "_rawComposite": 8500,
                    "_finalAdjusted": 8500,
                    "_canonicalSiteValues": {"ktcSfTep": 8500},
                    "position": "WR",
                },
            },
            "sites": [{"key": "ktcSfTep"}],
            "maxValues": {"ktcSfTep": 9999},
            "sleeper": {"positions": {}},
        }
        contract = build_api_data_contract(raw)
        ranked_rows = [r for r in contract["playersArray"] if "ktcRank" in r]
        self.assertEqual(len(ranked_rows), 2)
        names_by_rank = {r["ktcRank"]: r["canonicalName"] for r in ranked_rows}
        self.assertEqual(names_by_rank[1], "Josh Allen")
        self.assertEqual(names_by_rank[2], "Ja'Marr Chase")

    def test_build_api_data_contract_stamps_legacy_players_dict(self):
        """Contract builder must also write ktcRank into legacy players dict."""
        raw = {
            "players": {
                "Josh Allen": {
                    "_composite": 9000,
                    "_rawComposite": 9000,
                    "_finalAdjusted": 9000,
                    "_canonicalSiteValues": {"ktcSfTep": 9000},
                    "position": "QB",
                },
            },
            "sites": [{"key": "ktcSfTep"}],
            "maxValues": {},
            "sleeper": {"positions": {}},
        }
        contract = build_api_data_contract(raw)
        # The legacy players dict in the contract payload must have ktcRank
        self.assertIn("ktcRank", contract["players"]["Josh Allen"])
        self.assertEqual(contract["players"]["Josh Allen"]["ktcRank"], 1)

    def test_build_api_data_contract_does_not_mutate_raw_payload(self):
        """Two-level copy guards against mutations leaking back into the
        caller's raw_payload. Scalar fields added to player dicts by the
        ranker (rankDerivedValue, ktcRank, etc.) must NOT appear on the
        source payload after the build.
        """
        raw = {
            "players": {
                "Josh Allen": {
                    "_composite": 9000,
                    "_rawComposite": 9000,
                    "_finalAdjusted": 9000,
                    "_canonicalSiteValues": {"ktcSfTep": 9000},
                    "position": "QB",
                },
            },
            "sites": [{"key": "ktcSfTep"}],
            "maxValues": {},
            "sleeper": {"positions": {}},
        }
        orig_player_keys = set(raw["players"]["Josh Allen"].keys())
        orig_csv_keys = set(raw["players"]["Josh Allen"]["_canonicalSiteValues"].keys())
        build_api_data_contract(raw)
        # Top-level keys of the source player dict must not have grown.
        self.assertEqual(set(raw["players"]["Josh Allen"].keys()), orig_player_keys)
        # Nested _canonicalSiteValues keys must not have grown either.
        self.assertEqual(
            set(raw["players"]["Josh Allen"]["_canonicalSiteValues"].keys()),
            orig_csv_keys,
        )
        # Critical: the build must not stamp rankDerivedValue onto the caller's dict.
        self.assertNotIn("rankDerivedValue", raw["players"]["Josh Allen"])
        self.assertNotIn("ktcRank", raw["players"]["Josh Allen"])


class TestCanonicalConsensusRank(unittest.TestCase):
    """Backend must stamp canonicalConsensusRank — the authoritative rank
    that frontends use directly instead of recomputing their own sort order."""

    def _make_player_row(self, name: str, pos: str, ktc: int) -> dict:
        return {
            "canonicalName": name,
            "displayName": name,
            "legacyRef": name,
            "position": pos,
            "assetClass": "offense",
            "values": {
                "overall": ktc,
                "rawComposite": ktc,
                "finalAdjusted": ktc,
                "displayValue": None,
            },
            "canonicalSiteValues": {"ktcSfTep": ktc},
            "sourceCount": 1,
        }

    def test_canonical_consensus_rank_stamped_on_ranked_players(self):
        rows = [
            self._make_player_row("Alpha", "QB", 9000),
            self._make_player_row("Beta", "WR", 7000),
        ]
        _compute_unified_rankings(rows, {})
        alpha = next(r for r in rows if r["canonicalName"] == "Alpha")
        beta = next(r for r in rows if r["canonicalName"] == "Beta")
        self.assertEqual(alpha["canonicalConsensusRank"], 1)
        self.assertEqual(beta["canonicalConsensusRank"], 2)

    def test_canonical_consensus_rank_equals_ktc_rank(self):
        rows = [self._make_player_row(f"P{i}", "WR", 9000 - i * 10) for i in range(10)]
        _compute_unified_rankings(rows, {})
        for r in rows:
            self.assertEqual(r["canonicalConsensusRank"], r["ktcRank"])

    def test_canonical_consensus_rank_not_on_excluded_players(self):
        """Only rows without any source value or with unsupported positions
        are excluded from canonicalConsensusRank.  Picks ARE now included."""
        rows = [
            self._make_player_row("Unknown", "?", 8000),
            self._make_player_row("NoKtc", "WR", 0),
        ]
        _compute_unified_rankings(rows, {})
        for r in rows:
            self.assertNotIn("canonicalConsensusRank", r)

    def test_canonical_consensus_rank_mirrored_to_legacy_dict(self):
        rows = [self._make_player_row("Josh Allen", "QB", 9000)]
        legacy = {"Josh Allen": {"ktcSfTep": 9000}}
        _compute_unified_rankings(rows, legacy)
        self.assertEqual(legacy["Josh Allen"]["_canonicalConsensusRank"], 1)

    def test_canonical_consensus_rank_respects_limit(self):
        rows = [self._make_player_row(f"P{i}", "RB", 9000 - i) for i in range(900)]
        _compute_unified_rankings(rows, {})
        ranked = [r for r in rows if "canonicalConsensusRank" in r]
        self.assertEqual(len(ranked), OVERALL_RANK_LIMIT)


class TestRankChangeMirror(unittest.TestCase):
    """``rankChange`` stamped by ``_stamp_rank_changes`` onto playersArray
    must survive the runtime view that strips playersArray — i.e. it
    must mirror into the legacy ``players`` dict via
    ``_TRUST_MIRROR_FIELDS``.  Regression for the 2026-04-22 audit
    which found rankChange missing from every legacy-dict row.
    """

    def test_rank_change_mirrors_to_legacy_dict(self):
        from src.api.data_contract import _mirror_trust_to_legacy

        players_array = [
            {"legacyRef": "Josh Allen", "rankChange": 3, "confidenceBucket": "high"},
            {"legacyRef": "Puka Nacua", "rankChange": None, "confidenceBucket": "high"},
        ]
        legacy = {
            "Josh Allen": {"ktcSfTep": 9000},
            "Puka Nacua": {"ktcSfTep": 8800},
        }
        _mirror_trust_to_legacy(players_array, legacy)
        self.assertEqual(legacy["Josh Allen"]["rankChange"], 3)
        self.assertIsNone(legacy["Puka Nacua"]["rankChange"])


class TestIdpIntegrityGuardrails(unittest.TestCase):
    def test_prefers_explicit_player_offense_position_over_conflicting_sleeper_idp_map(self):
        raw = {
            "players": {
                "DJ Moore": {
                    "_composite": 8000,
                    "_rawComposite": 8000,
                    "_finalAdjusted": 7900,
                    "_canonicalSiteValues": {"ktcSfTep": 7700},
                    "position": "WR",
                },
            },
            "sites": [{"key": "ktcSfTep"}, {"key": "idpTradeCalc"}],
            "maxValues": {"ktcSfTep": 9999},
            "sleeper": {"positions": {"DJ Moore": "DB"}},
        }
        contract = build_api_data_contract(raw)
        row = contract["playersArray"][0]
        self.assertEqual(row["position"], "WR")
        self.assertEqual(row["assetClass"], "offense")

    def test_validation_flags_offense_signal_player_tagged_as_idp(self):
        payload = _minimal_raw_payload()
        payload["players"] = {
            "Test Offense Player X": {
                "_composite": 5000,
                "_rawComposite": 5000,
                "_finalAdjusted": 5000,
                "_canonicalSiteValues": {"ktcSfTep": 5000},
                "position": "DB",
            },
        }
        payload["sites"] = [{"key": "ktcSfTep"}]
        contract = build_api_data_contract(payload)
        report = validate_api_data_contract(contract)
        self.assertFalse(report["ok"])
        self.assertTrue(any("offense→IDP mismatch" in e for e in report["errors"]))

    def test_validation_flags_implausibly_tiny_idp_pool(self):
        players = {}
        for i in range(300):
            players[f"Player {i}"] = {
                "_composite": 4000 - i,
                "_rawComposite": 4000 - i,
                "_finalAdjusted": 4000 - i,
                "_canonicalSiteValues": {"ktcSfTep": 3000},
                "position": "WR",
            }
        players["Bobby Brown"] = {
            "_composite": 2500,
            "_rawComposite": 2500,
            "_finalAdjusted": 2500,
            "_canonicalSiteValues": {"idpTradeCalc": 8000},
            "position": "DL",
        }
        raw = {
            "players": players,
            "sites": [{"key": "ktcSfTep"}, {"key": "idpTradeCalc"}],
            "maxValues": {"ktcSfTep": 9999},
            "sleeper": {"positions": {}},
        }
        contract = build_api_data_contract(raw)
        report = validate_api_data_contract(contract)
        self.assertFalse(report["ok"])
        self.assertTrue(any("implausibly small IDP pool" in e for e in report["errors"]))

    def test_validation_flags_offense_idp_duplicate_name_collision(self):
        payload = build_api_data_contract(_minimal_raw_payload())
        payload["playersArray"].append(
            {
                "playerId": None,
                "canonicalName": "DJ Moore",
                "displayName": "DJ Moore",
                "position": "WR",
                "team": "CHI",
                "rookie": False,
                "values": {
                    "overall": 100,
                    "rawComposite": 100,
                    "finalAdjusted": 100,
                    "displayValue": 100,
                },
                "canonicalSiteValues": {"ktcSfTep": 100},
                "sourceCount": 1,
            }
        )
        payload["playersArray"].append(
            {
                "playerId": None,
                "canonicalName": "D.J. Moore",
                "displayName": "D.J. Moore",
                "position": "DB",
                "team": "CHI",
                "rookie": False,
                "values": {
                    "overall": 1,
                    "rawComposite": 1,
                    "finalAdjusted": 1,
                    "displayValue": 1,
                },
                "canonicalSiteValues": {"idpTradeCalc": 1},
                "sourceCount": 1,
            }
        )
        report = validate_api_data_contract(payload)
        self.assertFalse(report["ok"])
        self.assertTrue(any("name collision" in e for e in report["errors"]))


class TestStripNameSuffix(unittest.TestCase):
    """Ensure _strip_name_suffix handles all generational suffix variants."""

    def test_jr_with_period(self):
        from src.api.data_contract import _strip_name_suffix

        self.assertEqual(_strip_name_suffix("Marvin Harrison Jr."), "Marvin Harrison")

    def test_jr_without_period(self):
        from src.api.data_contract import _strip_name_suffix

        self.assertEqual(_strip_name_suffix("Brian Thomas Jr"), "Brian Thomas")
        self.assertEqual(_strip_name_suffix("Omar Cooper Jr"), "Omar Cooper")
        self.assertEqual(_strip_name_suffix("Michael Penix Jr"), "Michael Penix")

    def test_iii_suffix(self):
        from src.api.data_contract import _strip_name_suffix

        self.assertEqual(_strip_name_suffix("Kenneth Walker III"), "Kenneth Walker")

    def test_suffix_variants_match_base(self):
        from src.api.data_contract import _strip_name_suffix

        self.assertEqual(
            _strip_name_suffix("Kenneth Walker III"), _strip_name_suffix("Kenneth Walker")
        )
        self.assertEqual(
            _strip_name_suffix("Marvin Harrison Jr."), _strip_name_suffix("Marvin Harrison")
        )
        self.assertEqual(_strip_name_suffix("Brian Thomas Jr"), _strip_name_suffix("Brian Thomas"))
        self.assertEqual(_strip_name_suffix("Omar Cooper Jr"), _strip_name_suffix("Omar Cooper"))
        self.assertEqual(
            _strip_name_suffix("Michael Penix Jr"), _strip_name_suffix("Michael Penix")
        )

    def test_no_suffix_unchanged(self):
        from src.api.data_contract import _strip_name_suffix

        self.assertEqual(_strip_name_suffix("Patrick Mahomes"), "Patrick Mahomes")


class TestHillCurvesStamp(unittest.TestCase):
    """Contract carries all four scope-level master Hill curves.

    The refit workflow (``.github/workflows/refit-hill-curves.yml``)
    fits four scope masters — GLOBAL / OFFENSE / IDP / ROOKIE — via
    ``scripts/auto_refit_hill_curves.py``, and the routing in
    ``_curve_for_source`` consumes three of them live.  The frontend
    HillCurveExplorer renders the set directly; this test pins the
    stamp shape so a rename or drop doesn't silently leave the chart
    with no curves.
    """

    def test_contract_root_has_all_four_scope_curves(self):
        contract = build_api_data_contract(_minimal_raw_payload())
        curves = contract.get("hillCurves")
        self.assertIsInstance(curves, dict)
        self.assertEqual(
            set(curves.keys()),
            {"global", "offense", "idp", "rookie", "provenance"},
        )

    def test_each_curve_has_renderable_rank_form(self):
        contract = build_api_data_contract(_minimal_raw_payload())
        curves = contract["hillCurves"]
        for scope in ("global", "offense", "idp", "rookie"):
            entry = curves[scope]
            for field in ("midpoint", "slope", "c", "s", "referenceN", "label", "routed"):
                self.assertIn(field, entry, f"{scope}.{field} missing")
            self.assertGreater(entry["midpoint"], 0.0, f"{scope} midpoint must be positive")
            self.assertGreater(entry["slope"], 0.0, f"{scope} slope must be positive")
            self.assertEqual(entry["slope"], round(entry["s"], 4))
            # midpoint ≈ c * (referenceN − 1); allow small rounding.
            expected_midpoint = entry["c"] * (entry["referenceN"] - 1)
            self.assertAlmostEqual(entry["midpoint"], round(expected_midpoint, 4), places=3)

    def test_curves_match_committed_constants(self):
        from src.canonical.player_valuation import (
            HILL_GLOBAL_PERCENTILE_C,
            HILL_GLOBAL_PERCENTILE_S,
            HILL_PERCENTILE_C,
            HILL_PERCENTILE_S,
            HILL_ROOKIE_PERCENTILE_C,
            HILL_ROOKIE_PERCENTILE_S,
            IDP_HILL_PERCENTILE_C,
            IDP_HILL_PERCENTILE_S,
        )

        curves = build_api_data_contract(_minimal_raw_payload())["hillCurves"]
        self.assertAlmostEqual(curves["global"]["c"], HILL_GLOBAL_PERCENTILE_C)
        self.assertAlmostEqual(curves["global"]["s"], HILL_GLOBAL_PERCENTILE_S)
        self.assertAlmostEqual(curves["offense"]["c"], HILL_PERCENTILE_C)
        self.assertAlmostEqual(curves["offense"]["s"], HILL_PERCENTILE_S)
        self.assertAlmostEqual(curves["idp"]["c"], IDP_HILL_PERCENTILE_C)
        self.assertAlmostEqual(curves["idp"]["s"], IDP_HILL_PERCENTILE_S)
        self.assertAlmostEqual(curves["rookie"]["c"], HILL_ROOKIE_PERCENTILE_C)
        self.assertAlmostEqual(curves["rookie"]["s"], HILL_ROOKIE_PERCENTILE_S)


class TestHillMasterProvenanceStamp(unittest.TestCase):
    """V1-21 / W04-F011: the served board must record WHICH model version

    produced ``hillCurves``' constants — a real ``modelVersion`` /
    ``paramSetId`` / ``asOf`` stamp, the same vocabulary
    ``src/bdvm``/``src/consensus_edge`` already use, sourced from the
    PRE-EXISTING ``src/model_registry`` package (which previously had
    zero live-endpoint consumers) rather than a fourth invented scheme.

    The property under test is narrower than "a stamp exists": a stamp
    must be TRUTHFUL. It is one of three honest states — a verified
    champion match, an explicit "unverified" (constants drifted from the
    registry), or an explicit "unavailable" (registry unreadable / no
    champion) — and never lets state 2 or 3 wear state 1's clothing.
    """

    def test_the_live_board_stamps_a_real_verified_champion(self):
        """Positive control: today's committed constants DO match the
        registry's recorded champion, so the contract must say so with
        real values, not a placeholder."""
        contract = build_api_data_contract(_minimal_raw_payload())
        prov = contract["hillCurves"]["provenance"]
        self.assertEqual(prov["status"], "verified_champion")
        self.assertIsInstance(prov["modelVersion"], int)
        self.assertGreaterEqual(prov["modelVersion"], 1)
        self.assertIsInstance(prov["paramSetId"], str)
        self.assertTrue(prov["paramSetId"].startswith("hill_scope_masters:"))
        self.assertIsNotNone(prov["asOf"])
        self.assertIn(prov["confidence"], ("unvalidated", "provisional", "measured"))

    def test_paramSetId_is_stable_across_two_builds(self):
        """The same champion must yield the same id — it identifies the
        parameter CONTENT, not the moment it was read."""
        a = build_api_data_contract(_minimal_raw_payload())["hillCurves"]["provenance"]
        b = build_api_data_contract(_minimal_raw_payload())["hillCurves"]["provenance"]
        self.assertEqual(a["paramSetId"], b["paramSetId"])
        self.assertEqual(a["modelVersion"], b["modelVersion"])

    def test_a_missing_registry_reports_unavailable_not_a_guessed_version(self):
        """Negative control: if the model registry cannot be loaded at
        all, the stamp must say UNAVAILABLE with a reason -- never fall
        back to a fabricated or nearest-looking version number."""
        from unittest import mock

        from src.model_registry import ModelRegistry, RegistryError

        def _raise(model_id, registry_dir=None):
            raise RegistryError("simulated: registry file missing")

        with mock.patch.object(ModelRegistry, "load", staticmethod(_raise)):
            contract = build_api_data_contract(_minimal_raw_payload())
        prov = contract["hillCurves"]["provenance"]
        self.assertEqual(prov["status"], "unavailable")
        self.assertIsNone(prov["modelVersion"])
        self.assertIsNone(prov["paramSetId"])
        self.assertIn("reason", prov)
        self.assertTrue(prov["reason"])

    def test_drifted_constants_report_unverified_not_the_stale_champion(self):
        """Negative control: if the live constants no longer match the
        registry's recorded champion (e.g. an edit that skipped
        promote()+apply()), the stamp must say UNVERIFIED -- it must
        NOT keep claiming the old champion's version, which would
        misattribute a value nobody validated to a version that was."""
        import src.canonical.player_valuation as pv
        from unittest import mock

        with mock.patch.object(pv, "HILL_GLOBAL_PERCENTILE_C", 0.999):
            contract = build_api_data_contract(_minimal_raw_payload())
        prov = contract["hillCurves"]["provenance"]
        self.assertEqual(prov["status"], "unverified")
        self.assertIsNone(prov["modelVersion"])
        self.assertIsNone(prov["paramSetId"])
        self.assertIn("reason", prov)

    def test_a_corrupt_registry_file_degrades_to_unavailable_not_a_crash(self):
        """A malformed registry file (bad JSON) must not take down the
        whole /api/data build over a diagnostic field -- it degrades to
        the same UNAVAILABLE state as a missing file."""
        from unittest import mock

        from src.model_registry import ModelRegistry

        def _raise_json_error(model_id, registry_dir=None):
            raise ValueError("simulated: not valid JSON")

        with mock.patch.object(ModelRegistry, "load", staticmethod(_raise_json_error)):
            contract = build_api_data_contract(_minimal_raw_payload())
        prov = contract["hillCurves"]["provenance"]
        self.assertEqual(prov["status"], "unavailable")
        self.assertIsNone(prov["modelVersion"])

    def test_no_champion_reports_unavailable(self):
        """Negative control: a registry that loads but has never had a
        champion promoted must not be read as version 0 or version
        None-meaning-verified -- it is UNAVAILABLE, the same as an
        unreadable file, because neither case has a validated answer."""
        from src.model_registry.versioning import ModelRegistry as RealModelRegistry

        empty_registry = RealModelRegistry("hill_scope_masters", versions=())
        from unittest import mock
        from src.model_registry import ModelRegistry

        with mock.patch.object(ModelRegistry, "load", staticmethod(lambda *a, **k: empty_registry)):
            contract = build_api_data_contract(_minimal_raw_payload())
        prov = contract["hillCurves"]["provenance"]
        self.assertEqual(prov["status"], "unavailable")
        self.assertIsNone(prov["modelVersion"])


class TestRawSourceValues(unittest.TestCase):
    """``rawSourceValues`` carries raw 0-9999 scrape values for sources
    whose published board is the user-meaningful display number (e.g.
    KTC TE++).  The PlayerPopup chip render and the trade-page V13
    Value Adjustment formula read from this map so the displayed
    value matches the source's website (keeptradecut.com).

    Post PR #406 (the 2026-05 TEP split), ``ktcSfTep`` is exempt from
    blend-time TE multipliers and the scraper-side ×1.15 has been
    removed, so ``canonicalSiteValues.ktcSfTep`` equals the raw
    scrape in production.  These tests still feed divergent values
    to prove the contract layer's pass-through is faithful in BOTH
    fields independently — that resilience is what protects the
    display layer if a future correction is reintroduced upstream.
    ``rawSourceValues.ktcSfTep`` mirrors
    ``CSVs/site_raw/ktcSfTep.csv``.
    """

    def test_raw_source_values_carries_ktc_sf_tep_for_te_row(self):
        """A TE with a top-level ``ktcSfTep`` raw scrape must surface
        that value at ``rawSourceValues.ktcSfTep`` on the playersArray
        row.  ``canonicalSiteValues.ktcSfTep`` is passed through
        verbatim from the upstream canonical pipeline — the test
        deliberately uses divergent inputs to assert independent
        pass-through of both fields.
        """
        raw = {
            "players": {
                "Trey McBride": {
                    "_composite": 9000,
                    "_rawComposite": 9000,
                    "_finalAdjusted": 9000,
                    "_canonicalSiteValues": {
                        "ktc": 7560,
                        "ktcSfTep": 10527,  # synthetic divergent value (production: equals raw)
                    },
                    "ktc": 7560,
                    "ktcSfTep": 9154,  # raw scrape — matches keeptradecut.com
                    "position": "TE",
                },
            },
            "sites": [{"key": "ktcSfTep"}],
            "maxValues": {"ktcSfTep": 9999},
            "sleeper": {"positions": {"Trey McBride": "TE"}},
        }
        contract = build_api_data_contract(raw)
        row = next(r for r in contract["playersArray"] if r["canonicalName"] == "Trey McBride")
        # rawSourceValues carries the raw scrape from the top-level
        # ``ktcSfTep`` field (the synthetic input mimics the legacy
        # divergence between raw and canonicalSites).
        self.assertIn("rawSourceValues", row)
        self.assertEqual(row["rawSourceValues"]["ktcSfTep"], 9154)
        # canonicalSiteValues passes through whatever the upstream
        # canonical pipeline emitted (post PR #406 these match in
        # production; the test asserts the contract layer doesn't
        # collapse the two fields).
        self.assertEqual(row["canonicalSiteValues"]["ktcSfTep"], 10527)

    def test_raw_source_values_omits_missing_keys(self):
        """When a player has no ``ktcSfTep`` raw scrape (e.g. KTC
        coverage gap), ``rawSourceValues`` is an empty dict — the
        frontend can branch on key presence cleanly without coercing
        a zero / null into the display.
        """
        raw = {
            "players": {
                "Player Without Ktc": {
                    "_composite": 5000,
                    "_rawComposite": 5000,
                    "_finalAdjusted": 5000,
                    "_canonicalSiteValues": {"idpTradeCalc": 4500},
                    "position": "WR",
                },
            },
            "sites": [{"key": "idpTradeCalc"}],
            "maxValues": {},
            "sleeper": {"positions": {"Player Without Ktc": "WR"}},
        }
        contract = build_api_data_contract(raw)
        row = next(
            r for r in contract["playersArray"] if r["canonicalName"] == "Player Without Ktc"
        )
        self.assertEqual(row["rawSourceValues"], {})

    def test_raw_source_values_skips_zero_and_negative_values(self):
        """Sentinel zeros / negatives don't make it into
        ``rawSourceValues`` so consumers can treat presence as
        "raw value available".
        """
        raw = {
            "players": {
                "Zeroed Player": {
                    "_composite": 100,
                    "_rawComposite": 100,
                    "_finalAdjusted": 100,
                    "_canonicalSiteValues": {"ktcSfTep": 0},
                    "ktcSfTep": 0,  # sentinel
                    "position": "WR",
                },
            },
            "sites": [{"key": "ktcSfTep"}],
            "maxValues": {},
            "sleeper": {"positions": {"Zeroed Player": "WR"}},
        }
        contract = build_api_data_contract(raw)
        row = next(r for r in contract["playersArray"] if r["canonicalName"] == "Zeroed Player")
        self.assertNotIn("ktcSfTep", row["rawSourceValues"])


if __name__ == "__main__":
    unittest.main()
