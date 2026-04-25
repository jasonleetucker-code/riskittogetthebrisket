"""Regression tests for the DraftSharks negative-value carve-out.

DraftSharks publishes a cross-market ``3D Value +`` column that goes
negative past ~rank 200 — the CSV rows below that threshold carry
legitimate negative values (e.g. Emmanuel McNeil-Warren at IDP rank
362 → ``-25``).  Before the 2026-04-22 fix, three separate ``> 0``
gates silently dropped every negatively-valued DS row:

    1. ``_enrich_from_source_csvs`` wouldn't write the value into
       ``canonicalSiteValues``.
    2. ``_compute_unified_rankings`` Phase 1 ordinal pass wouldn't
       add the row to the source's eligible pool, so
       ``row_source_ranks`` had no DS stamp.
    3. ``sourcePresence[draftSharks*]`` was computed as
       ``v > 0``, so it read False even for stamped rows.

The net effect was ~360 players (185 SF + 174 IDP) showing up as
"not covered by DraftSharks" when they were actually ranked by DS.
These tests guard all three gates simultaneously by building the
live contract and asserting that a known tail-player (McNeil-Warren)
receives credit for DS coverage end to end.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.api.data_contract import (
    _DS_COMBINED_RANK_KEYS,
    _RANKING_SOURCES,
    build_api_data_contract,
)

REPO = Path(__file__).resolve().parents[2]
DS_IDP_CSV = REPO / "CSVs" / "site_raw" / "draftSharksIdp.csv"
DS_SF_CSV = REPO / "CSVs" / "site_raw" / "draftSharksSf.csv"


def _load_live_contract() -> dict | None:
    """Build the live contract from the latest exported raw payload.

    Returns ``None`` when no export exists — tests that depend on the
    live contract self-skip in that case so CI still runs against the
    registry-shape assertions.
    """
    export_dir = REPO / "exports" / "latest"
    files = sorted(export_dir.glob("dynasty_data_*.json"), reverse=True)
    if not files:
        return None
    with files[0].open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return build_api_data_contract(raw)


class DraftSharksNegativeValueTests(unittest.TestCase):
    """End-to-end coverage for DS rows with negative ``3D Value +``."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = _load_live_contract()

    def test_ds_combined_rank_keys_matches_registry(self) -> None:
        """The module-level set must mirror every registry entry that
        declares ``ds_combined_rank_partner``.  If someone adds a new
        negative-scale source to the registry and forgets to bump
        the set, this test fires."""
        expected = {
            str(src.get("key") or "")
            for src in _RANKING_SOURCES
            if src.get("ds_combined_rank_partner")
        }
        self.assertEqual(set(_DS_COMBINED_RANK_KEYS), expected)
        # Sanity: at minimum both DS sources must be in the set.
        self.assertIn("draftSharks", _DS_COMBINED_RANK_KEYS)
        self.assertIn("draftSharksIdp", _DS_COMBINED_RANK_KEYS)

    def test_ds_csvs_have_negative_rows(self) -> None:
        """Guard against CSV-format regressions that would make these
        tests vacuous — DS SHOULD carry negative-valued rows past the
        rank-200 crossover."""
        for csv_path in (DS_IDP_CSV, DS_SF_CSV):
            if not csv_path.exists():
                self.skipTest(f"CSV missing: {csv_path}")
            text = csv_path.read_text(encoding="utf-8")
            # Cheap substring probe — avoids pulling pandas just to
            # confirm there's a negative number in the value column.
            self.assertTrue(
                any(
                    line.rstrip().endswith(f",{sign}")
                    or f",{sign}\n" in line
                    or f",-{digit}" in line
                    for line in text.splitlines()
                    for sign in ("-1", "-5", "-10")
                    for digit in ("1", "2", "3", "4", "5", "6", "7", "8", "9")
                ),
                f"{csv_path.name} has no negative ``3D Value +`` rows — "
                "has the CSV format changed, or have the tail rows been "
                "trimmed upstream?",
            )

    def test_negative_ds_row_gets_full_coverage(self) -> None:
        """Emmanuel McNeil-Warren is DraftSharks IDP rank 362 with
        ``3D Value +`` == -25.  Every gate — canonicalSiteValues,
        sourceRanks, sourcePresence — must show DS as covering him."""
        if not DS_IDP_CSV.exists():
            self.skipTest("DraftSharks IDP CSV missing")
        if self.contract is None:
            self.skipTest("No exported raw payload to build contract from")

        players = self.contract.get("playersArray") or []
        target = next(
            (p for p in players if p.get("displayName") == "Emmanuel McNeil-Warren"),
            None,
        )
        if target is None:
            self.skipTest(
                "Emmanuel McNeil-Warren not in live contract — CSV may "
                "have been regenerated without him; drop this test or "
                "swap for another known tail player."
            )

        csv_vals = target.get("canonicalSiteValues") or {}
        self.assertIn(
            "draftSharksIdp",
            csv_vals,
            "canonicalSiteValues missing draftSharksIdp — the CSV "
            "enrichment ``> 0`` gate still drops negative DS values.",
        )
        self.assertIsNotNone(csv_vals["draftSharksIdp"])
        self.assertLess(
            float(csv_vals["draftSharksIdp"]),
            0,
            "McNeil-Warren's DS IDP value should be negative; if it's "
            "now positive, either DS changed his ranking or a prior "
            "stage is clobbering the stamp.",
        )

        source_ranks = target.get("sourceRanks") or {}
        self.assertIn(
            "draftSharksIdp",
            source_ranks,
            "sourceRanks missing draftSharksIdp — Phase 1 ordinal "
            "pass still filters ``val <= 0``.",
        )
        self.assertGreater(source_ranks["draftSharksIdp"], 0)

        presence = target.get("sourcePresence") or {}
        self.assertTrue(
            presence.get("draftSharksIdp"),
            "sourcePresence[draftSharksIdp] is False even though DS "
            "ranked the player — the presence computation still "
            "requires ``v > 0`` for DS sources.",
        )

    def test_ds_coverage_counts_include_negative_tail(self) -> None:
        """Aggregate check: the fix should expand DS coverage by
        hundreds of players (the negative-value tail).  Floor the
        totals so a regression that silently re-introduces the
        ``> 0`` gate would drop coverage below expected and fail."""
        if not DS_IDP_CSV.exists() or not DS_SF_CSV.exists():
            self.skipTest("DraftSharks CSVs missing")
        if self.contract is None:
            self.skipTest("No exported raw payload to build contract from")

        players = self.contract.get("playersArray") or []

        ds_idp_covered = sum(
            1
            for p in players
            if (p.get("sourcePresence") or {}).get("draftSharksIdp")
        )
        ds_sf_covered = sum(
            1
            for p in players
            if (p.get("sourcePresence") or {}).get("draftSharks")
        )

        # Regression floor: a real regression of the carve-out drops
        # ~170 IDP rows / ~185 SF rows (the negative-tail population).
        # Floors are set well above the resulting trip points so day-
        # to-day scraper churn (DS rotating tail players in/out of the
        # rank-200+ band) doesn't false-fail, while a true regression
        # still fails immediately.
        #
        # Empirical baselines (2026-04):
        #   - DS IDP coverage drifted from 270 (test author's
        #     as-found) to 213 over a few weeks of routine scraper
        #     refreshes — DS publishes fewer IDP entries than they
        #     used to.  Floor at 180 leaves ~33 rows of churn buffer
        #     and still catches a regression that would drop coverage
        #     to ~43.
        #   - DS SF coverage has been stable at 406-407.  Floor at
        #     326 (80% of original 407) is unchanged.
        self.assertGreaterEqual(
            ds_idp_covered,
            180,
            f"DS IDP coverage collapsed to {ds_idp_covered}; the "
            "negative-value carve-out may have regressed.",
        )
        self.assertGreaterEqual(
            ds_sf_covered,
            326,
            f"DS SF coverage collapsed to {ds_sf_covered}; the "
            "negative-value carve-out may have regressed.",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
