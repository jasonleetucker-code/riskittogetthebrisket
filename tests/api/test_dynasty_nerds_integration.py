"""Regression tests for Dynasty Nerds SF-TEP source integration.

These tests pin down the contract-level wiring for the 5th ranking
source so a future refactor cannot silently drop DN from the blend.

Specifically:

1. The source is registered in ``_RANKING_SOURCES`` with the expected
   scope, weight, and depth.
2. The CSV path is wired in ``_SOURCE_CSV_PATHS`` as a rank-signal
   source.
3. Name-based enrichment works for typical DN display names, including
   apostrophes and suffixes.
4. Synthetic rows that share a canonical match key with a DN CSV row
   receive a populated ``canonicalSiteValues["dynastyNerdsSfTep"]``.
5. Players listed in the DN CSV with rank 1 stamp ``sourceRanks``
   with a finite ordinal inside the blended board.
6. DN-only players are handled as semantic 1-src and resolved via
   ``SINGLE_SOURCE_ALLOWLIST`` where applicable.
7. Rows with ``value=0`` in the raw DR_DATA payload are skipped by
   the fetch script, so they never appear in the CSV at all.
"""
from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path

from src.api.data_contract import (
    SINGLE_SOURCE_ALLOWLIST,
    _OFFENSE_SIGNAL_KEYS,
    _RANKING_SOURCES,
    _SOURCE_CSV_PATHS,
    _canonical_match_key,
    build_api_data_contract,
)
from src.canonical.idp_backbone import SOURCE_SCOPE_OVERALL_OFFENSE

REPO_ROOT = Path(__file__).resolve().parents[2]
DN_CSV = REPO_ROOT / "CSVs" / "site_raw" / "dynastyNerdsSfTep.csv"


def _dn_csv_rows() -> list[dict[str, str]]:
    if not DN_CSV.exists():
        return []
    with DN_CSV.open("r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


class TestDynastyNerdsRegistry(unittest.TestCase):
    """Registry entries for the Dynasty Nerds source."""

    def test_source_registered_in_ranking_sources(self):
        keys = {s["key"] for s in _RANKING_SOURCES}
        self.assertIn("dynastyNerdsSfTep", keys)

    def test_source_scope_is_overall_offense(self):
        src = next(
            (s for s in _RANKING_SOURCES if s["key"] == "dynastyNerdsSfTep"),
            None,
        )
        self.assertIsNotNone(src)
        self.assertEqual(src["scope"], SOURCE_SCOPE_OVERALL_OFFENSE)

    def test_source_weight_and_depth(self):
        src = next(
            s for s in _RANKING_SOURCES if s["key"] == "dynastyNerdsSfTep"
        )
        # Every registered source is declared at weight 1.0 so the
        # blend is an honest equal-weight consensus.  See the
        # registry note in data_contract.py.
        self.assertEqual(src["weight"], 1.0)
        # Depth guardrail over the 294 non-zero rows in the snapshot.
        self.assertGreaterEqual(src["depth"], 290)

    def test_source_not_retail(self):
        src = next(
            s for s in _RANKING_SOURCES if s["key"] == "dynastyNerdsSfTep"
        )
        self.assertFalse(src.get("is_retail", False))

    def test_source_in_offense_signal_keys(self):
        self.assertIn("dynastyNerdsSfTep", _OFFENSE_SIGNAL_KEYS)

    def test_csv_path_registered_as_rank_signal(self):
        cfg = _SOURCE_CSV_PATHS.get("dynastyNerdsSfTep")
        self.assertIsInstance(cfg, dict)
        self.assertTrue(str(cfg.get("path", "")).endswith("dynastyNerdsSfTep.csv"))
        self.assertEqual(cfg.get("signal"), "rank")


class TestDynastyNerdsCsvShape(unittest.TestCase):
    """Shape of the scraped CSV file on disk."""

    def test_csv_exists(self):
        self.assertTrue(DN_CSV.exists(), f"{DN_CSV} missing")

    def test_csv_has_rank_column(self):
        rows = _dn_csv_rows()
        self.assertTrue(rows, "DN CSV had no data rows")
        first = rows[0]
        for col in ("Name", "Rank", "Value", "SleeperId"):
            self.assertIn(col, first, f"Missing column {col}")

    def test_csv_ranks_start_at_1_and_are_monotonic(self):
        rows = _dn_csv_rows()
        self.assertTrue(rows, "DN CSV had no data rows")
        ranks = [int(r["Rank"]) for r in rows if r["Rank"]]
        self.assertEqual(ranks[0], 1)
        for a, b in zip(ranks, ranks[1:]):
            self.assertLess(a, b, "Ranks should be strictly monotonic")

    def test_csv_skips_zero_value_rows(self):
        """Rows with value==0 in the raw payload must not appear."""
        rows = _dn_csv_rows()
        for r in rows:
            val = int(float(r["Value"]))
            self.assertGreater(val, 0)

    def test_csv_covers_offense_positions_only(self):
        rows = _dn_csv_rows()
        positions = {r.get("Pos", "").strip() for r in rows}
        positions.discard("")
        self.assertTrue(positions.issubset({"QB", "RB", "WR", "TE"}))

    def test_csv_all_rows_carry_sleeper_id(self):
        """Dynasty Nerds always provides sleeperId in the payload."""
        rows = _dn_csv_rows()
        with_sid = sum(1 for r in rows if (r.get("SleeperId") or "").strip())
        # The occasional Sleeper-less manual entry is tolerated, but we
        # expect at least 95% coverage given the payload shape.
        self.assertGreaterEqual(with_sid / max(1, len(rows)), 0.95)


class TestDynastyNerdsEnrichment(unittest.TestCase):
    """End-to-end: DN CSV rows surface on contract rows that match by name."""

    @classmethod
    def setUpClass(cls):
        # Build a minimal payload containing the DN top players so
        # enrichment has real rows to attach values to.
        rows = _dn_csv_rows()
        cls.dn_rows = rows
        if not rows:
            cls.contract = None
            return
        players: dict = {}
        positions: dict = {}
        top20 = rows[:20]
        mid = rows[min(150, len(rows) - 1)]
        picks = top20 + [mid]
        for r in picks:
            name = r["Name"]
            pos = (r.get("Pos") or "RB").strip() or "RB"
            players[name] = {
                "_composite": 5000,
                "_rawComposite": 5000,
                "_finalAdjusted": 5000,
                "_sites": 1,
                "position": pos,
                "team": r.get("Team") or "TST",
                "_canonicalSiteValues": {"ktcSfTep": 5000},
            }
            positions[name] = pos
        payload = {
            "players": players,
            "sites": [{"key": "ktcSfTep"}, {"key": "idpTradeCalc"}],
            "maxValues": {"ktcSfTep": 9999},
            "sleeper": {"positions": positions},
        }
        cls.contract = build_api_data_contract(payload)

    def test_contract_rows_receive_dn_values(self):
        if self.contract is None:
            self.skipTest("DN CSV missing")
        pa = self.contract.get("playersArray", [])
        dn_enriched = [
            p for p in pa
            if (p.get("canonicalSiteValues") or {}).get("dynastyNerdsSfTep")
        ]
        # Expect at least 15 of the 20-plus synthesized rows to have
        # received an enrichment value.  A handful of top-20 names may
        # canonicalize differently (suffix drift, apostrophe variants)
        # but the majority must join cleanly.
        self.assertGreaterEqual(len(dn_enriched), 15)

    def test_dn_source_rank_stamped(self):
        if self.contract is None:
            self.skipTest("DN CSV missing")
        pa = self.contract.get("playersArray", [])
        any_stamped = any(
            (p.get("sourceRanks") or {}).get("dynastyNerdsSfTep") is not None
            for p in pa
        )
        self.assertTrue(any_stamped)

    def test_dn_original_ranks_preserved(self):
        if self.contract is None:
            self.skipTest("DN CSV missing")
        pa = self.contract.get("playersArray", [])
        matched = [
            p for p in pa
            if (p.get("sourceOriginalRanks") or {}).get("dynastyNerdsSfTep")
        ]
        self.assertTrue(matched)
        # The preserved original rank must be a positive number inside
        # the DN board's depth.
        for row in matched:
            orr = row["sourceOriginalRanks"]["dynastyNerdsSfTep"]
            self.assertGreaterEqual(float(orr), 1.0)
            self.assertLessEqual(float(orr), 500.0)

    def test_top_dn_player_appears_at_top_of_contract(self):
        if self.contract is None or not self.dn_rows:
            self.skipTest("DN CSV missing")
        top_name = self.dn_rows[0]["Name"]
        key = _canonical_match_key(top_name)
        pa = self.contract.get("playersArray", [])
        match = next(
            (
                p for p in pa
                if _canonical_match_key(p.get("canonicalName") or "") == key
            ),
            None,
        )
        self.assertIsNotNone(match, f"{top_name} missing from contract")
        rank = match.get("canonicalConsensusRank")
        self.assertIsNotNone(rank)
        # A DN rank-1 player must land comfortably inside the top 50
        # of the unified board when enriched with both KTC and DN.
        self.assertLessEqual(rank, 50)


class TestDynastyNerdsAllowlist(unittest.TestCase):
    """DN-only players that are legitimately 1-src must be allowlisted."""

    def test_dn_only_entries_documented(self):
        # Each DN-only entry must reference DN in the reason string.
        dn_reasons = [
            reason for reason in SINGLE_SOURCE_ALLOWLIST.values()
            if "Dynasty Nerds" in reason or "dynastyNerds" in reason
        ]
        # We do not require a specific count — just sanity-check that
        # at least one DN-only reason is present (otherwise the
        # allowlist and the live board have drifted).
        self.assertTrue(
            dn_reasons,
            "No Dynasty Nerds-tagged entries in SINGLE_SOURCE_ALLOWLIST",
        )


if __name__ == "__main__":
    unittest.main()
