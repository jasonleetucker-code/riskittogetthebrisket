"""Regression tests for the name-join hygiene layer in the contract.

These tests pin the behaviour that drove the IDP data-hygiene fix: the
backend join path between scraper payload rows and source CSV lookup
tables was matching by a suffix-strip-only key, which silently lost
every player whose spelling differed in punctuation between the two
sides — most famously T.J. Watt (``TJ Watt`` in the CSVs vs
``T.J. Watt`` in the scraper dict).

After the fix, all joins go through ``_canonical_match_key`` which is a
thin wrapper around ``normalize_player_name`` in
``src/utils/name_clean.py``.  The normalizer already handles the
punctuation/diacritic/suffix/initial-collapse rules consistently with
the identity pipeline and the adapters.

Test coverage:

* ``_canonical_match_key`` parity with ``normalize_player_name``.
* ``_enrich_from_source_csvs`` joins across:
    - periods in initials (T.J. Watt ↔ TJ Watt)
    - periods in three-part initials (C.J. Stroud ↔ CJ Stroud)
    - periods + disambiguation (D.J. Moore ↔ DJ Moore)
    - generational suffix drift (Will Anderson Jr ↔ Will Anderson)
    - diacritics (Juanyeh Thomas ↔ Juanyéh Thomas)
* Downstream effect: a pair of rows that used to produce a single-source
  artefact now carries both sources on the canonical site map.
"""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.api.data_contract import (
    _canonical_match_key,
    _compute_unified_rankings,
    _enrich_from_source_csvs,
)
from src.utils.name_clean import normalize_player_name


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


class TestCanonicalMatchKey(unittest.TestCase):
    """``_canonical_match_key`` must be a pure alias for the shared
    ``normalize_player_name`` helper.  Any drift here re-introduces the
    class of bugs this entire fix was designed to eliminate.
    """

    def test_mirrors_normalize_player_name(self):
        for raw in [
            "T.J. Watt",
            "C.J. Stroud",
            "D.J. Moore",
            "Ja'Marr Chase",
            "Marvin Harrison Jr.",
            "Kenneth Walker III",
            "Juanyéh Thomas",
            "  t.j.  WATT  ",
        ]:
            self.assertEqual(
                _canonical_match_key(raw),
                normalize_player_name(raw),
            )

    def test_period_initials_collide_on_a_single_key(self):
        # The T.J. Watt regression: both spellings must yield the same key.
        self.assertEqual(
            _canonical_match_key("T.J. Watt"),
            _canonical_match_key("TJ Watt"),
        )
        self.assertEqual(
            _canonical_match_key("C.J. Stroud"),
            _canonical_match_key("CJ Stroud"),
        )
        self.assertEqual(
            _canonical_match_key("D.J. Moore"),
            _canonical_match_key("DJ Moore"),
        )
        self.assertEqual(
            _canonical_match_key("A.J. Brown"),
            _canonical_match_key("AJ Brown"),
        )

    def test_generational_suffix_drift_collides(self):
        # Marvin Harrison Jr. ↔ Marvin Harrison, Kenneth Walker III ↔
        # Kenneth Walker, Brian Thomas Jr ↔ Brian Thomas — all three
        # must join on the suffix-free base.
        self.assertEqual(
            _canonical_match_key("Marvin Harrison Jr."),
            _canonical_match_key("Marvin Harrison"),
        )
        self.assertEqual(
            _canonical_match_key("Kenneth Walker III"),
            _canonical_match_key("Kenneth Walker"),
        )
        self.assertEqual(
            _canonical_match_key("Brian Thomas Jr"),
            _canonical_match_key("Brian Thomas"),
        )

    def test_diacritics_fold_to_ascii(self):
        self.assertEqual(
            _canonical_match_key("Juanyéh Thomas"),
            _canonical_match_key("Juanyeh Thomas"),
        )

    def test_empty_input_returns_empty(self):
        self.assertEqual(_canonical_match_key(""), "")
        self.assertEqual(_canonical_match_key(None), "")


class TestEnrichFromSourceCsvsJoinHygiene(unittest.TestCase):
    """``_enrich_from_source_csvs`` must honour the canonical match key
    on both the CSV side (when building ``csv_lookup``) and the player-
    row side (when resolving a player to a CSV value).
    """

    def _run_with_csvs(
        self,
        players: list[dict],
        csvs: dict[str, list[tuple[str, float]]],
    ) -> None:
        """Rewrite ``_SOURCE_CSV_PATHS`` so each source in ``csvs``
        resolves to a temporary file inside a tempdir.

        Each value in ``csvs`` is a list of ``(name, rank)`` pairs;
        dlfIdp is loaded with signal=rank, everything else with
        signal=value (using the rank number as the raw value).
        """
        with tempfile.TemporaryDirectory() as td:
            from src.api import data_contract as dc

            patched = {}
            for source_key, rows in csvs.items():
                p = Path(td) / f"{source_key}.csv"
                with p.open("w", encoding="utf-8", newline="") as f:
                    w = csv.writer(f)
                    header = ("name", "rank") if source_key == "dlfIdp" else ("name", "value")
                    w.writerow(header)
                    for name, n in rows:
                        w.writerow([name, n])
                if source_key == "dlfIdp":
                    patched[source_key] = {
                        "path": str(p),
                        "signal": "rank",
                    }
                else:
                    patched[source_key] = str(p)
            with mock.patch.object(dc, "_SOURCE_CSV_PATHS", patched):
                _enrich_from_source_csvs(players)

    def test_tj_watt_joins_across_punctuation_drift(self):
        """The regression hero: T.J. Watt in the players dict joins to
        TJ Watt in both the DLF and IDPTradeCalc CSVs.
        """
        players = [_row("T.J. Watt", "DL")]
        self._run_with_csvs(
            players,
            {
                "idpTradeCalc": [("TJ Watt", 3288)],
                "dlfIdp": [("TJ Watt", 13)],
            },
        )
        sites = players[0]["canonicalSiteValues"]
        self.assertIn("idpTradeCalc", sites)
        self.assertIn("dlfIdp", sites)
        self.assertGreater(sites["idpTradeCalc"], 0)
        self.assertGreater(sites["dlfIdp"], 0)

    def test_cj_stroud_joins_across_punctuation_drift(self):
        players = [_row("C.J. Stroud", "QB", ktc=4851)]
        self._run_with_csvs(
            players,
            {
                "idpTradeCalc": [("CJ Stroud", 4794)],
            },
        )
        sites = players[0]["canonicalSiteValues"]
        self.assertIn("idpTradeCalc", sites)
        self.assertEqual(sites["idpTradeCalc"], 4794)

    def test_dj_moore_joins_across_punctuation_drift(self):
        players = [_row("D.J. Moore", "WR", ktc=3868)]
        self._run_with_csvs(
            players,
            {
                "idpTradeCalc": [("DJ Moore", 3909)],
            },
        )
        sites = players[0]["canonicalSiteValues"]
        self.assertIn("idpTradeCalc", sites)
        self.assertEqual(sites["idpTradeCalc"], 3909)

    def test_suffix_drift_joins_correctly(self):
        # DLF CSV emits "Will Anderson Jr"; scraper dict has the suffix-
        # free form.  The canonical key drops the suffix on both sides.
        players = [_row("Will Anderson", "DL")]
        self._run_with_csvs(
            players,
            {
                "dlfIdp": [("Will Anderson Jr", 2)],
            },
        )
        self.assertIn("dlfIdp", players[0]["canonicalSiteValues"])
        self.assertGreater(
            players[0]["canonicalSiteValues"]["dlfIdp"], 0
        )

    def test_reverse_suffix_drift_joins_correctly(self):
        # And in reverse: scraper has the suffix, CSV does not.
        players = [_row("Marvin Harrison Jr.", "WR")]
        self._run_with_csvs(
            players,
            {
                "idpTradeCalc": [("Marvin Harrison", 7200)],
            },
        )
        self.assertIn("idpTradeCalc", players[0]["canonicalSiteValues"])
        self.assertEqual(
            players[0]["canonicalSiteValues"]["idpTradeCalc"], 7200
        )

    def test_diacritics_drift_joins_correctly(self):
        players = [_row("Juanyéh Thomas", "DB")]
        self._run_with_csvs(
            players,
            {
                "idpTradeCalc": [("Juanyeh Thomas", 1100)],
            },
        )
        self.assertIn("idpTradeCalc", players[0]["canonicalSiteValues"])

    def test_existing_source_value_still_wins(self):
        # When the scraper already produced an idpTradeCalc value for
        # this player, the CSV enrichment must NOT overwrite it — even
        # if the CSV provides a different value under a punctuation
        # variant.
        players = [_row("T.J. Watt", "DL", idp=4000)]
        self._run_with_csvs(
            players,
            {"idpTradeCalc": [("TJ Watt", 5000)]},
        )
        self.assertEqual(
            players[0]["canonicalSiteValues"]["idpTradeCalc"], 4000
        )

    def test_row_becomes_multi_source_after_hygiene_fix(self):
        # End-to-end: a T.J. Watt row that starts with zero canonical
        # site values gets enriched from two independent CSVs, then
        # feeds _compute_unified_rankings with both sources present.
        # Before the fix this row was a 1-src ghost.
        players = [_row("T.J. Watt", "DL")]
        # Need a backbone anchor so the shared-market ladder exists and
        # DLF's raw rank has something to translate against.
        players.append(_row("Myles Garrett", "DL", idp=9000))
        self._run_with_csvs(
            players,
            {
                "idpTradeCalc": [
                    ("Myles Garrett", 9000),
                    ("TJ Watt", 3288),
                ],
                "dlfIdp": [
                    ("Aidan Hutchinson", 1),
                    ("TJ Watt", 13),
                ],
            },
        )
        _compute_unified_rankings(players, {})
        watt = next(
            r for r in players if r["canonicalName"] == "T.J. Watt"
        )
        # Both sources show up on canonicalSiteValues
        self.assertIn("idpTradeCalc", watt["canonicalSiteValues"])
        self.assertIn("dlfIdp", watt["canonicalSiteValues"])
        # And both appear on sourceRanks, so the player is NOT single-source.
        self.assertIn("idpTradeCalc", watt["sourceRanks"])
        self.assertIn("dlfIdp", watt["sourceRanks"])
        self.assertFalse(watt["isSingleSource"])
        self.assertEqual(watt["sourceCount"], 2)


if __name__ == "__main__":
    unittest.main()
