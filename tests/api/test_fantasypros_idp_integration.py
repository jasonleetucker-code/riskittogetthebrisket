"""Regression tests for FantasyPros Dynasty IDP source integration.

These tests pin down the contract-level wiring for the 6th ranking
source so a future refactor cannot silently drop FP from the blend
and cannot break the combined-authority + anchored-extension rules.
"""
from __future__ import annotations

import csv
import json
import os
import unittest
from pathlib import Path

from src.api.data_contract import (
    _IDP_SIGNAL_KEYS,
    _RANKING_SOURCES,
    _SOURCE_CSV_PATHS,
    _canonical_match_key,
    build_api_data_contract,
)
from src.canonical.idp_backbone import SOURCE_SCOPE_OVERALL_IDP

REPO_ROOT = Path(__file__).resolve().parents[2]
FP_CSV = REPO_ROOT / "CSVs" / "site_raw" / "fantasyProsIdp.csv"
LIVE_API_JSON = REPO_ROOT / "tests" / "api" / "_live_api_fixture.json"


def _fp_csv_rows() -> list[dict[str, str]]:
    if not FP_CSV.exists():
        return []
    with FP_CSV.open("r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _load_live_api() -> dict | None:
    """Return the live API payload snapshot if present.

    Tests that need the full live payload (methodology / freshness
    wiring) are skipped when the fixture is absent, so local test
    runs without a live snapshot still pass.
    """
    env_path = os.environ.get("LIVE_API_FIXTURE")
    if env_path:
        p = Path(env_path)
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return None
    if LIVE_API_JSON.exists():
        try:
            return json.loads(LIVE_API_JSON.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _hill(rank: float) -> int:
    if rank <= 0:
        return 9999
    return max(1, min(9999, round(1 + 9998 / (1 + ((rank - 1) / 45.0) ** 1.10))))


class TestFantasyProsIdpRegistry(unittest.TestCase):
    """Registry entries for the FantasyPros IDP source."""

    def test_source_registered_in_ranking_sources(self):
        keys = {s["key"] for s in _RANKING_SOURCES}
        self.assertIn("fantasyProsIdp", keys)

    def test_source_scope_is_overall_idp(self):
        src = next(
            (s for s in _RANKING_SOURCES if s["key"] == "fantasyProsIdp"), None
        )
        self.assertIsNotNone(src)
        self.assertEqual(src["scope"], SOURCE_SCOPE_OVERALL_IDP)

    def test_source_weight_and_depth(self):
        src = next(s for s in _RANKING_SOURCES if s["key"] == "fantasyProsIdp")
        # Every registered source is declared at weight 1.0 so the
        # blend is an honest equal-weight consensus.  See the
        # registry note in data_contract.py.
        self.assertEqual(src["weight"], 1.0)
        self.assertGreaterEqual(src["depth"], 75)

    def test_source_in_idp_signal_keys(self):
        self.assertIn("fantasyProsIdp", _IDP_SIGNAL_KEYS)

    def test_csv_path_registered_as_rank_signal(self):
        cfg = _SOURCE_CSV_PATHS.get("fantasyProsIdp")
        self.assertIsInstance(cfg, dict)
        self.assertTrue(
            str(cfg.get("path", "")).endswith("fantasyProsIdp.csv")
        )
        self.assertEqual(cfg.get("signal"), "rank")

    def test_needs_shared_market_translation(self):
        src = next(s for s in _RANKING_SOURCES if s["key"] == "fantasyProsIdp")
        self.assertTrue(src.get("needs_shared_market_translation", False))


class TestFantasyProsIdpCsvShape(unittest.TestCase):
    """Shape + algorithmic invariants of the scraped CSV file on disk."""

    def test_csv_exists(self):
        self.assertTrue(FP_CSV.exists(), f"{FP_CSV} missing")

    def test_csv_has_required_columns(self):
        rows = _fp_csv_rows()
        self.assertTrue(rows, "FP CSV had no data rows")
        required = {
            "name",
            "originalRank",
            "effectiveRank",
            "derivationMethod",
            "family",
            "normalizedValue",
            "matchedSourceName",
            "position",
            "team",
        }
        self.assertTrue(required.issubset(set(rows[0].keys())))

    def test_all_families_valid(self):
        rows = _fp_csv_rows()
        self.assertTrue(rows)
        fams = {r["family"] for r in rows}
        self.assertTrue(fams.issubset({"DL", "LB", "DB"}))

    def test_all_derivation_methods_valid(self):
        rows = _fp_csv_rows()
        self.assertTrue(rows)
        methods = {r["derivationMethod"] for r in rows}
        self.assertTrue(
            methods.issubset({"direct_combined", "anchored_from_individual"})
        )

    # ── 1. Combined board players use direct rank ─────────────────
    def test_combined_board_players_use_direct_rank(self):
        """Pick several top IDP players — all must be direct_combined
        and effectiveRank must equal originalRank.
        """
        rows = _fp_csv_rows()
        self.assertTrue(rows)
        by_name = {r["name"]: r for r in rows}
        # Top IDPs on FantasyPros combined IDP board.
        top_names = [
            "Will Anderson Jr.",
            "Aidan Hutchinson",
            "Brian Burns",
            "Micah Parsons",
            "Maxx Crosby",
        ]
        found = 0
        for nm in top_names:
            r = by_name.get(nm)
            if r is None:
                continue
            found += 1
            self.assertEqual(
                r["derivationMethod"],
                "direct_combined",
                f"{nm} should be direct_combined",
            )
            self.assertEqual(
                int(r["originalRank"]),
                int(r["effectiveRank"]),
                f"{nm}: direct combined players must have originalRank == effectiveRank",
            )
        self.assertGreaterEqual(found, 3)

    # ── 2. Individual-only players anchored ───────────────────────
    def test_individual_only_players_anchored(self):
        rows = _fp_csv_rows()
        self.assertTrue(rows)
        ext = [r for r in rows if r["derivationMethod"] == "anchored_from_individual"]
        self.assertTrue(ext, "No anchored_from_individual rows found")
        for r in ext:
            # Extension players' effectiveRank must be strictly
            # deeper than the individual-page originalRank, since
            # the combined board always carries some players that
            # shift the individual row's true overall position.
            self.assertGreater(
                int(r["effectiveRank"]),
                int(r["originalRank"]),
                f"{r['name']}: anchored effRank must be deeper than ind rank",
            )

    # ── 3-5. Per-family anchor curve monotone ────────────────────
    def _assert_family_monotone(self, family: str) -> None:
        rows = _fp_csv_rows()
        self.assertTrue(rows)
        ext = [
            r for r in rows
            if r["derivationMethod"] == "anchored_from_individual"
            and r["family"] == family
        ]
        # Sort by individual rank (originalRank), then assert
        # effectiveRank is strictly monotone increasing.
        ext.sort(key=lambda r: int(r["originalRank"]))
        effs = [int(r["effectiveRank"]) for r in ext]
        for a, b in zip(effs, effs[1:]):
            self.assertLess(
                a,
                b,
                f"{family} extension curve not monotone: {a} -> {b}",
            )

    def test_dl_curve_monotone(self):
        self._assert_family_monotone("DL")

    def test_lb_curve_monotone(self):
        self._assert_family_monotone("LB")

    def test_db_curve_monotone(self):
        self._assert_family_monotone("DB")

    # ── 6. Combined-family authority ─────────────────────────────
    def test_combined_family_authority(self):
        """A player who appears on both combined and an individual
        page must keep the combined page's family decision.
        The CSV never emits a second row for such players, so
        combined-family authority is enforced by construction — we
        assert no extension row exists for any direct_combined name.
        """
        rows = _fp_csv_rows()
        self.assertTrue(rows)
        direct_names = {
            r["name"] for r in rows if r["derivationMethod"] == "direct_combined"
        }
        ext_names = {
            r["name"] for r in rows if r["derivationMethod"] == "anchored_from_individual"
        }
        self.assertFalse(
            direct_names & ext_names,
            "Same player appears as both direct_combined and anchored_from_individual",
        )

    # ── 7. Normalized value uses exact Hill formula ──────────────
    def test_normalized_value_uses_exact_hill_formula(self):
        rows = _fp_csv_rows()
        self.assertTrue(rows)
        for r in rows[:30]:
            eff = int(r["effectiveRank"])
            expected = _hill(eff)
            actual = int(r["normalizedValue"])
            self.assertEqual(
                actual,
                expected,
                f"{r['name']} at rank {eff}: normalizedValue {actual} != Hill({eff}) {expected}",
            )

    # ── 10. Anchor curve extrapolation monotone ──────────────────
    def test_anchor_curve_extrapolation_monotone(self):
        """No extrapolated value may decrease as individual rank
        increases.  Combined with the per-family monotone tests
        this pins every extension row's effectiveRank to strict
        monotonicity with respect to its individual-page rank.
        """
        rows = _fp_csv_rows()
        self.assertTrue(rows)
        for fam in ("DL", "LB", "DB"):
            ext = sorted(
                (
                    r for r in rows
                    if r["derivationMethod"] == "anchored_from_individual"
                    and r["family"] == fam
                ),
                key=lambda r: int(r["originalRank"]),
            )
            last_eff = -1
            for r in ext:
                eff = int(r["effectiveRank"])
                self.assertGreater(
                    eff,
                    last_eff,
                    f"{fam}: non-monotone extrapolation at {r['name']}",
                )
                last_eff = eff


class TestFantasyProsIdpEnrichment(unittest.TestCase):
    """End-to-end: FP CSV rows surface on contract rows that match by name."""

    @classmethod
    def setUpClass(cls):
        rows = _fp_csv_rows()
        cls.fp_rows = rows
        if not rows:
            cls.contract = None
            return
        players: dict = {}
        positions: dict = {}
        # Synthesize contract rows for every FP player so enrichment
        # has a target for each one.
        for r in rows:
            name = r["name"]
            fam = r["family"]
            pos = {"DL": "DL", "LB": "LB", "DB": "DB"}[fam]
            players[name] = {
                "_composite": 5000,
                "_rawComposite": 5000,
                "_finalAdjusted": 5000,
                "_sites": 1,
                "position": pos,
                "team": r.get("team") or "TST",
                "_canonicalSiteValues": {"idpTradeCalc": 5000},
            }
            positions[name] = pos
        payload = {
            "players": players,
            "sites": [{"key": "ktcSfTep"}, {"key": "idpTradeCalc"}],
            "maxValues": {"idpTradeCalc": 9999},
            "sleeper": {"positions": positions},
        }
        cls.contract = build_api_data_contract(payload)

    def test_contract_rows_receive_fp_values(self):
        if self.contract is None:
            self.skipTest("FP CSV missing")
        pa = self.contract.get("playersArray", [])
        enriched = [
            p for p in pa
            if (p.get("canonicalSiteValues") or {}).get("fantasyProsIdp")
        ]
        self.assertGreaterEqual(len(enriched), 80)

    # ── 8. Source metadata present in payload ──────────────────
    def test_source_metadata_present_in_payload(self):
        if self.contract is None:
            self.skipTest("FP CSV missing")
        pa = self.contract.get("playersArray", [])
        have_meta = [
            p for p in pa
            if p.get("fantasyProsIdpEffectiveRank") is not None
            and p.get("fantasyProsIdpDerivationMethod") in (
                "direct_combined", "anchored_from_individual"
            )
            and p.get("fantasyProsIdpFamily") in ("DL", "LB", "DB")
        ]
        self.assertGreaterEqual(
            len(have_meta),
            80,
            "FP metadata should be stamped on at least 80 IDP rows",
        )

    # ── 9. Combined-board player keeps direct rank in payload ──
    def test_no_combined_player_loses_direct_rank(self):
        if self.contract is None:
            self.skipTest("FP CSV missing")
        pa = self.contract.get("playersArray", [])
        by_name = {
            p.get("displayName") or p.get("canonicalName") or "": p
            for p in pa
        }
        for r in self.fp_rows:
            if r["derivationMethod"] != "direct_combined":
                continue
            row = by_name.get(r["name"])
            if row is None:
                continue
            eff = row.get("fantasyProsIdpEffectiveRank")
            orig = row.get("fantasyProsIdpOriginalRank")
            if eff is None or orig is None:
                continue
            self.assertEqual(
                eff,
                orig,
                f"{r['name']}: combined-board player lost direct rank",
            )
            self.assertEqual(row.get("fantasyProsIdpDerivationMethod"), "direct_combined")

    def test_fp_appears_in_methodology_sources(self):
        if self.contract is None:
            self.skipTest("FP CSV missing")
        methodology = self.contract.get("methodology") or {}
        sources = methodology.get("sources") or []
        src_keys = {s.get("key") for s in sources}
        self.assertIn("fantasyProsIdp", src_keys)

    def test_fp_in_source_timestamps(self):
        if self.contract is None:
            self.skipTest("FP CSV missing")
        df = self.contract.get("dataFreshness") or {}
        ts = df.get("sourceTimestamps") or {}
        self.assertIn("fantasyProsIdp", ts)


class TestFantasyProsIdpLivePayload(unittest.TestCase):
    """Live payload assertions — skipped if snapshot not present."""

    def test_fp_source_appears_in_live_methodology(self):
        live = _load_live_api()
        if live is None:
            self.skipTest("No live API fixture present")
        sources = (live.get("methodology") or {}).get("sources") or []
        self.assertIn("fantasyProsIdp", {s.get("key") for s in sources})

    def test_fp_in_live_source_timestamps(self):
        live = _load_live_api()
        if live is None:
            self.skipTest("No live API fixture present")
        ts = (
            (live.get("dataFreshness") or {}).get("sourceTimestamps") or {}
        )
        self.assertIn("fantasyProsIdp", ts)

    def test_fp_metadata_on_live_players(self):
        live = _load_live_api()
        if live is None:
            self.skipTest("No live API fixture present")
        pa = live.get("playersArray") or []
        have = [
            p for p in pa
            if p.get("fantasyProsIdpEffectiveRank") is not None
        ]
        self.assertGreaterEqual(len(have), 80)


if __name__ == "__main__":
    unittest.main()
