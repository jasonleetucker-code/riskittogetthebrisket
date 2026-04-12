"""Tests for the DLF (Dynasty League Football) IDP source wiring.

Covers every link in the DLF pipeline end-to-end:

    * scripts/convert_dlf_csv.convert — reads the raw DLF export and
      writes a ``name,rank`` CSV that the contract loader understands.
    * src.api.data_contract._enrich_from_source_csvs — new ``signal=rank``
      branch that stamps a monotonic synthetic value onto
      canonicalSiteValues[\"dlfIdp\"] so the downstream descending sort
      still produces the correct ordinal.
    * src.api.data_contract._compute_unified_rankings — verifies that
      DLF participates as a second overall_idp source alongside
      IDPTradeCalc without becoming the backbone.
    * tests/adapters/test_source_config_completeness — pins the source
      config / weights shape (those assertions live in the adapters
      test file; this module covers the data-flow contract).
"""
from __future__ import annotations

import csv
import unittest
from pathlib import Path
from unittest import mock

from scripts.convert_dlf_csv import convert as convert_dlf_csv
from src.api.data_contract import (
    _RANKING_SOURCES,
    _RANK_TO_SYNTHETIC_VALUE_OFFSET,
    _compute_unified_rankings,
    _enrich_from_source_csvs,
)
from src.canonical.idp_backbone import (
    SOURCE_SCOPE_OVERALL_IDP,
    TRANSLATION_DIRECT,
)


def _row(name: str, pos: str, *, idp=None, dlf=None, ktc=None) -> dict:
    sites: dict = {}
    if idp is not None:
        sites["idpTradeCalc"] = idp
    if dlf is not None:
        sites["dlfIdp"] = dlf
    if ktc is not None:
        sites["ktc"] = ktc
    return {
        "canonicalName": name,
        "displayName": name,
        "legacyRef": name,
        "position": pos,
        "assetClass": "offense" if pos in {"QB", "RB", "WR", "TE"} else "idp",
        "values": {"overall": 0, "rawComposite": 0,
                   "finalAdjusted": 0, "displayValue": None},
        "canonicalSiteValues": sites,
        "sourceCount": 1,
    }


# ── Preprocessor: raw DLF export → exports/latest/site_raw/dlfIdp.csv ──


class TestDlfCsvPreprocessor(unittest.TestCase):
    """``scripts/convert_dlf_csv.convert`` must normalize the published
    DLF format (capitalized headers, expert columns, etc.) into the
    single ``name,rank`` shape the scraper bridge + contract loader
    consume.
    """

    def test_converts_raw_dlf_export_to_name_rank(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "dlf_idp.csv"
            src.write_text(
                "Rank,Avg,Pos,Name,Team,Age,FrankG,Jason K,Justin T,Value,Follow\n"
                "1,1.00,DE (DL1),Aidan Hutchinson,DET,25,1,1,1,,\n"
                "2,2.00,DE (DL2),Will Anderson Jr,HOU,24,2,2,2,,\n"
                "3,3.67,DE (DL3),Micah Parsons,GB,26,3,5,3,,\n"
                "4,4.67,DE (DL4),Jared Verse,LAR,25,4,6,4,,\n",
                encoding="utf-8",
            )
            dst = Path(td) / "out" / "dlfIdp.csv"
            count = convert_dlf_csv(src, dst)
            self.assertEqual(count, 4)

            rows = list(csv.DictReader(dst.open("r", encoding="utf-8")))
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["name"], "Aidan Hutchinson")
        self.assertEqual(rows[0]["rank"], "1")
        self.assertEqual(rows[1]["name"], "Will Anderson Jr")
        self.assertEqual(rows[1]["rank"], "2")
        # Fractional expert averages are preserved to two decimals so the
        # downstream tie-break is driven by the true consensus average.
        self.assertEqual(rows[2]["rank"], "3.67")
        self.assertEqual(rows[3]["rank"], "4.67")

    def test_skips_blank_names_and_nonpositive_ranks(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "dlf_idp.csv"
            src.write_text(
                "Rank,Avg,Pos,Name,Team\n"
                "1,1.00,DE (DL1),Hutch,DET\n"
                ",,,,\n"             # entirely blank row
                "2,0,LB1,,KC\n"      # blank name
                "3,-1,LB2,NegRank,KC\n"  # non-positive rank
                "4,4.00,LB3,Jack Campbell,DET\n",
                encoding="utf-8",
            )
            dst = Path(td) / "out.csv"
            count = convert_dlf_csv(src, dst)
            self.assertEqual(count, 2)
            rows = list(csv.DictReader(dst.open("r", encoding="utf-8")))
        self.assertEqual([r["name"] for r in rows], ["Hutch", "Jack Campbell"])

    def test_missing_source_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            convert_dlf_csv(Path("/definitely/not/here.csv"), Path("/tmp/out.csv"))


# ── Enrichment: _enrich_from_source_csvs with signal=rank ──


class TestDlfCsvEnrichment(unittest.TestCase):
    """``_enrich_from_source_csvs`` must stamp the DLF rank CSV onto
    players' canonicalSiteValues[\"dlfIdp\"] as a monotonic synthetic
    value so the downstream sort reproduces the DLF order.
    """

    def _run_with_temp_dlf_csv(
        self,
        players: list[dict],
        dlf_rows: list[tuple[str, float]],
    ) -> None:
        """Rewrite _SOURCE_CSV_PATHS for the duration of the test so we
        can point dlfIdp at a temporary file without touching the real
        exports/latest/site_raw tree.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            csv_path = Path(td) / "dlfIdp.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["name", "rank"])
                for name, rank in dlf_rows:
                    w.writerow([name, rank])

            # The loader computes absolute paths as repo_root / rel_path.
            # Patch _SOURCE_CSV_PATHS so dlfIdp resolves to our temp file
            # (expressed as an absolute path relative to repo root by using
            # the ".." chain; simpler: patch Path.exists + Path.__truediv__
            # by replacing the relative entry with the absolute temp path).
            from src.api import data_contract as dc

            patched = dict(dc._SOURCE_CSV_PATHS)
            # We want the loader to read OUR file.  The loader does
            #     csv_path = repo / csv_rel
            # where repo is the module-level repo root.  Passing an
            # already-absolute path through ``/`` in pathlib returns the
            # absolute path unchanged, so we just store the absolute path.
            patched["dlfIdp"] = {
                "path": str(csv_path),
                "signal": "rank",
            }
            # Drop unrelated sources so their absent CSVs don't interfere.
            for k in list(patched.keys()):
                if k != "dlfIdp":
                    patched.pop(k)

            with mock.patch.object(dc, "_SOURCE_CSV_PATHS", patched):
                _enrich_from_source_csvs(players)

    def test_rank_csv_stamps_monotonic_synthetic_value(self):
        players = [
            _row("Aidan Hutchinson", "DL"),
            _row("Will Anderson Jr", "DL"),
            _row("Micah Parsons", "DL"),
        ]
        self._run_with_temp_dlf_csv(
            players,
            [("Aidan Hutchinson", 1), ("Will Anderson Jr", 2), ("Micah Parsons", 3.67)],
        )

        hutch = players[0]["canonicalSiteValues"]["dlfIdp"]
        anderson = players[1]["canonicalSiteValues"]["dlfIdp"]
        parsons = players[2]["canonicalSiteValues"]["dlfIdp"]

        # Monotonically descending: rank 1 > rank 2 > rank 3.67.
        self.assertGreater(hutch, anderson)
        self.assertGreater(anderson, parsons)
        # And the offset constant determines the absolute numbers: each
        # stamped value must sit in the band just below the offset.
        self.assertLess(hutch, _RANK_TO_SYNTHETIC_VALUE_OFFSET * 100)
        self.assertGreater(parsons, 0)

    def test_rank_csv_handles_suffix_names(self):
        # The loader lowercases + strips the generational suffix on both
        # the CSV key and the player row.  A row carrying the suffix in
        # its canonicalName still gets enriched from a CSV entry that
        # omits it (and vice versa).
        players = [
            _row("Will Anderson", "DL"),  # suffix stripped on both sides
        ]
        self._run_with_temp_dlf_csv(
            players,
            [("Will Anderson Jr", 2.0)],
        )
        self.assertIn("dlfIdp", players[0]["canonicalSiteValues"])

    def test_existing_value_is_not_overwritten(self):
        players = [
            _row("Aidan Hutchinson", "DL", dlf=12345),
        ]
        self._run_with_temp_dlf_csv(
            players,
            [("Aidan Hutchinson", 1)],
        )
        self.assertEqual(
            players[0]["canonicalSiteValues"]["dlfIdp"], 12345
        )

    def test_missing_rank_column_skips_row(self):
        players = [_row("Ghost Player", "DL")]
        # CSV with only a 'name' column — no rank
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            csv_path = Path(td) / "dlfIdp.csv"
            csv_path.write_text("name\nGhost Player\n", encoding="utf-8")

            from src.api import data_contract as dc

            patched = {"dlfIdp": {"path": str(csv_path), "signal": "rank"}}
            with mock.patch.object(dc, "_SOURCE_CSV_PATHS", patched):
                _enrich_from_source_csvs(players)

        self.assertNotIn("dlfIdp", players[0]["canonicalSiteValues"])


# ── Ranking: DLF as an overall_idp source alongside IDPTradeCalc ──


class TestDlfParticipatesInUnifiedRankings(unittest.TestCase):
    """DLF is registered as a non-backbone overall_idp source with equal
    weight.  When both IDPTradeCalc and DLF rank a player, the coverage-
    weighted Hill-curve blend must consider both; IDPTradeCalc remains
    the backbone for ladder translation.
    """

    def test_dlf_is_registered_as_overall_idp_non_backbone(self):
        dlf = next(s for s in _RANKING_SOURCES if s["key"] == "dlfIdp")
        self.assertEqual(dlf["scope"], SOURCE_SCOPE_OVERALL_IDP)
        self.assertFalse(dlf["is_backbone"])
        self.assertIsNone(dlf["position_group"])
        # Full board — no declared depth — so coverage weight is 1.0.
        self.assertIsNone(dlf["depth"])
        self.assertEqual(dlf["weight"], 1.0)

    def test_idptradecalc_remains_the_only_backbone(self):
        backbones = [s for s in _RANKING_SOURCES if s.get("is_backbone")]
        self.assertEqual(len(backbones), 1)
        self.assertEqual(backbones[0]["key"], "idpTradeCalc")

    def test_dlf_ranks_alongside_idptradecalc(self):
        rows = [
            # Both sources agree: dl1 > lb1 > db1.
            _row("dl1", "DL", idp=900, dlf=9995),
            _row("lb1", "LB", idp=800, dlf=9990),
            _row("db1", "DB", idp=700, dlf=9985),
        ]
        _compute_unified_rankings(rows, {})

        for r in rows:
            meta = r["sourceRankMeta"]
            self.assertIn("dlfIdp", meta)
            self.assertIn("idpTradeCalc", meta)
            self.assertEqual(meta["dlfIdp"]["scope"], SOURCE_SCOPE_OVERALL_IDP)
            self.assertEqual(meta["dlfIdp"]["method"], TRANSLATION_DIRECT)

        # dl1 is rank 1 in both sources
        dl1 = rows[0]
        self.assertEqual(dl1["sourceRanks"]["idpTradeCalc"], 1)
        self.assertEqual(dl1["sourceRanks"]["dlfIdp"], 1)
        # db1 is rank 3 in both
        db1 = rows[2]
        self.assertEqual(db1["sourceRanks"]["idpTradeCalc"], 3)
        self.assertEqual(db1["sourceRanks"]["dlfIdp"], 3)

    def test_dlf_disagreement_with_idptradecalc_blends_not_overrides(self):
        # IDPTradeCalc says dl1 > dl2; DLF disagrees and puts dl2 first.
        # Both sources carry equal weight so the blended effective rank
        # should be the average of the two, which still produces a
        # deterministic ordinal on the unified board.
        rows = [
            _row("dl1", "DL", idp=900, dlf=9990),
            _row("dl2", "DL", idp=800, dlf=9995),
        ]
        _compute_unified_rankings(rows, {})

        dl1 = rows[0]
        dl2 = rows[1]
        # Sanity: each source stamps its own ordinal under the same scope.
        self.assertEqual(dl1["sourceRanks"]["idpTradeCalc"], 1)
        self.assertEqual(dl2["sourceRanks"]["idpTradeCalc"], 2)
        self.assertEqual(dl1["sourceRanks"]["dlfIdp"], 2)
        self.assertEqual(dl2["sourceRanks"]["dlfIdp"], 1)
        # Rank spread across sources is captured for transparency.  A
        # one-rank disagreement is below the hasSourceDisagreement
        # threshold (80) but still surfaces on sourceRankSpread.
        self.assertEqual(dl1["sourceRankSpread"], 1.0)
        self.assertEqual(dl2["sourceRankSpread"], 1.0)
        self.assertFalse(dl1["isSingleSource"])
        self.assertFalse(dl2["isSingleSource"])

    def test_dlf_only_player_still_gets_ranked_via_overall_idp_scope(self):
        rows = [
            _row("idp_anchor", "DL", idp=900),  # IDPTradeCalc-only
            _row("dlf_only", "DL", dlf=9950),   # DLF-only
        ]
        _compute_unified_rankings(rows, {})
        dlf_only = next(r for r in rows if r["canonicalName"] == "dlf_only")
        # dlf_only has no IDPTradeCalc value, so its sourceRanks only
        # contains dlfIdp — but it STILL gets a unified rank because DLF
        # is an overall_idp source.
        self.assertIn("dlfIdp", dlf_only["sourceRanks"])
        self.assertNotIn("idpTradeCalc", dlf_only["sourceRanks"])
        self.assertGreater(dlf_only["canonicalConsensusRank"], 0)
        # Single-source flag is set because only one source ranked him.
        self.assertTrue(dlf_only["isSingleSource"])


if __name__ == "__main__":
    unittest.main()
