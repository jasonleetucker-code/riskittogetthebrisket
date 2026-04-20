import unittest

from src.api.data_contract import (
    OVERALL_RANK_LIMIT,
    KTC_RANK_LIMIT,
    _compute_unified_rankings,
    build_api_data_contract,
    build_api_startup_payload,
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
        "sites": [{"key": "ktc"}, {"key": "idpTradeCalc"}],
        "maxValues": {"ktc": 9999},
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
            "values": {"overall": ktc, "rawComposite": ktc,
                       "finalAdjusted": ktc, "displayValue": None},
            "canonicalSiteValues": {"ktc": ktc},
            "sourceCount": 1,
        }

    def test_top_player_gets_rank_1(self):
        rows = [
            self._make_player_row("Alpha", "QB", 9000),
            self._make_player_row("Beta",  "WR", 7000),
        ]
        _compute_unified_rankings(rows, {})
        alpha = next(r for r in rows if r["canonicalName"] == "Alpha")
        self.assertEqual(alpha["ktcRank"], 1)

    def test_rank_order_follows_ktc_value_descending(self):
        rows = [
            self._make_player_row("Low",  "RB", 3000),
            self._make_player_row("High", "QB", 9000),
            self._make_player_row("Mid",  "WR", 6000),
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
        # max, so the normalized vote is 9999/9999 × 9999 = 9999.
        self.assertEqual(rows[0]["rankDerivedValue"], 9999)

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
        raw_v = rank_50_row["canonicalSiteValues"]["ktc"]
        # site_max comes from the same pool → P0's value 9999.
        site_max = 9999
        expected_direct = int(round(raw_v / site_max * 9999.0))
        self.assertEqual(rank_50_row["rankDerivedValue"], expected_direct)
        # And the value is NOT the Hill output at p=49/499 ≈ 0.098,
        # which would yield a much lower value under HILL_PERCENTILE_*.
        from src.api.data_contract import _PERCENTILE_REFERENCE_N  # noqa: PLC0415
        hill_p = (50 - 1) / (_PERCENTILE_REFERENCE_N - 1)
        hill_value = int(percentile_to_value(hill_p))
        self.assertNotEqual(
            rank_50_row["rankDerivedValue"], hill_value,
            "Value-based source should NOT be routed through the Hill "
            "curve — ``rankDerivedValue`` must reflect the raw normalized "
            "site value."
        )

    def test_picks_included(self):
        """Picks with source values participate in the unified ranking."""
        rows = [
            self._make_player_row("2026 Early 1st", "PICK", 8000),
            self._make_player_row("Real Player",    "QB",   7000),
        ]
        rows[0]["assetClass"] = "pick"
        _compute_unified_rankings(rows, {})
        pick = next(r for r in rows if r["canonicalName"] == "2026 Early 1st")
        self.assertEqual(pick["ktcRank"], 1)
        real = next(r for r in rows if r["canonicalName"] == "Real Player")
        self.assertEqual(real["ktcRank"], 2)

    def test_unresolved_position_excluded(self):
        rows = [
            self._make_player_row("UnknownGuy", "?",  8000),
            self._make_player_row("KnownGuy",   "QB", 7000),
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
        legacy = {"Josh Allen": {"ktc": 9000, "_finalAdjusted": 9000}}
        _compute_unified_rankings(rows, legacy)
        self.assertEqual(legacy["Josh Allen"]["ktcRank"], 1)
        self.assertEqual(legacy["Josh Allen"]["rankDerivedValue"], int(rank_to_value(1)))

    def test_build_api_data_contract_stamps_ktc_rank(self):
        """The full contract builder must include ktcRank in playersArray."""
        raw = {
            "players": {
                "Josh Allen": {
                    "_composite": 9000, "_rawComposite": 9000, "_finalAdjusted": 9000,
                    "_canonicalSiteValues": {"ktc": 9000}, "position": "QB",
                },
                "Ja'Marr Chase": {
                    "_composite": 8500, "_rawComposite": 8500, "_finalAdjusted": 8500,
                    "_canonicalSiteValues": {"ktc": 8500}, "position": "WR",
                },
            },
            "sites": [{"key": "ktc"}],
            "maxValues": {"ktc": 9999},
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
                    "_composite": 9000, "_rawComposite": 9000, "_finalAdjusted": 9000,
                    "_canonicalSiteValues": {"ktc": 9000}, "position": "QB",
                },
            },
            "sites": [{"key": "ktc"}],
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
                    "_composite": 9000, "_rawComposite": 9000, "_finalAdjusted": 9000,
                    "_canonicalSiteValues": {"ktc": 9000}, "position": "QB",
                },
            },
            "sites": [{"key": "ktc"}],
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
            "values": {"overall": ktc, "rawComposite": ktc,
                       "finalAdjusted": ktc, "displayValue": None},
            "canonicalSiteValues": {"ktc": ktc},
            "sourceCount": 1,
        }

    def test_canonical_consensus_rank_stamped_on_ranked_players(self):
        rows = [
            self._make_player_row("Alpha", "QB", 9000),
            self._make_player_row("Beta",  "WR", 7000),
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
        legacy = {"Josh Allen": {"ktc": 9000}}
        _compute_unified_rankings(rows, legacy)
        self.assertEqual(legacy["Josh Allen"]["_canonicalConsensusRank"], 1)

    def test_canonical_consensus_rank_respects_limit(self):
        rows = [self._make_player_row(f"P{i}", "RB", 9000 - i) for i in range(900)]
        _compute_unified_rankings(rows, {})
        ranked = [r for r in rows if "canonicalConsensusRank" in r]
        self.assertEqual(len(ranked), OVERALL_RANK_LIMIT)


class TestIdpIntegrityGuardrails(unittest.TestCase):
    def test_prefers_explicit_player_offense_position_over_conflicting_sleeper_idp_map(self):
        raw = {
            "players": {
                "DJ Moore": {
                    "_composite": 8000,
                    "_rawComposite": 8000,
                    "_finalAdjusted": 7900,
                    "_canonicalSiteValues": {"ktc": 7700},
                    "position": "WR",
                },
            },
            "sites": [{"key": "ktc"}, {"key": "idpTradeCalc"}],
            "maxValues": {"ktc": 9999},
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
                "_canonicalSiteValues": {"ktc": 5000},
                "position": "DB",
            },
        }
        payload["sites"] = [{"key": "ktc"}]
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
                "_canonicalSiteValues": {"ktc": 3000},
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
            "sites": [{"key": "ktc"}, {"key": "idpTradeCalc"}],
            "maxValues": {"ktc": 9999},
            "sleeper": {"positions": {}},
        }
        contract = build_api_data_contract(raw)
        report = validate_api_data_contract(contract)
        self.assertFalse(report["ok"])
        self.assertTrue(any("implausibly small IDP pool" in e for e in report["errors"]))

    def test_validation_flags_offense_idp_duplicate_name_collision(self):
        payload = build_api_data_contract(_minimal_raw_payload())
        payload["playersArray"].append({
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
            "canonicalSiteValues": {"ktc": 100},
            "sourceCount": 1,
        })
        payload["playersArray"].append({
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
        })
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
        self.assertEqual(_strip_name_suffix("Kenneth Walker III"), _strip_name_suffix("Kenneth Walker"))
        self.assertEqual(_strip_name_suffix("Marvin Harrison Jr."), _strip_name_suffix("Marvin Harrison"))
        self.assertEqual(_strip_name_suffix("Brian Thomas Jr"), _strip_name_suffix("Brian Thomas"))
        self.assertEqual(_strip_name_suffix("Omar Cooper Jr"), _strip_name_suffix("Omar Cooper"))
        self.assertEqual(_strip_name_suffix("Michael Penix Jr"), _strip_name_suffix("Michael Penix"))

    def test_no_suffix_unchanged(self):
        from src.api.data_contract import _strip_name_suffix
        self.assertEqual(_strip_name_suffix("Patrick Mahomes"), "Patrick Mahomes")


if __name__ == "__main__":
    unittest.main()
