"""The export leg is the RAW-EVIDENCE lane, and that is a contract.

C1-U6 follow-up 11, established 2026-08-16.

The C1-U6 acceptance chain reads "rankings == trade == API == export ==
ownership == mobile == desktop", and the export-parity test self-skips
with a note that the export surface is not a canonical-value surface.
A self-skipping test and a missing test read identically, so this file
turns the note into something checkable.

**Measured truth.** Every artifact under ``exports/latest`` is produced
by ``Dynasty Scraper.py`` and carries the scraper's own quantities:

    dynasty_full.csv    Player,Composite,Sites,<per-site raw values>
    dynasty_values.csv  Player,KTC,IDPTradeCalc
    dynasty_data_*.json the raw scrape payload
    site_raw/*.csv      per-source vendor CSVs

In C1-U4's vocabulary those are the ``scraper_blend`` and
``source_value`` lanes — deliberately different NAMED quantities from
the canonical board. No export carries ``rankDerivedValue``, so there is
no second canonical value surface to keep in parity with, and the
completeness census correctly covers the contract alone.

**Why pin it.** The boundary is only sound while it is true. The day an
export starts carrying a canonical value, "the export is raw evidence"
silently becomes false and the census silently becomes incomplete —
with nothing failing. This test fails instead, and its message says what
to do.
"""

from __future__ import annotations

import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
EXPORT_DIR = REPO / "exports" / "latest"

#: Field names that mean "a canonical board value". If one of these
#: appears in an export, the export has become a canonical surface.
_CANONICAL_VALUE_FIELDS = {
    "rankDerivedValue",
    "canonicalConsensusRank",
    "displayValue",
    "finalAdjusted",
}


def _csvs() -> list[pathlib.Path]:
    if not EXPORT_DIR.is_dir():
        return []
    return sorted(p for p in EXPORT_DIR.glob("*.csv"))


class TestTheExportLegCarriesNoCanonicalValue:
    def test_the_export_csv_headers_are_scraper_quantities(self):
        csvs = _csvs()
        if not csvs:
            pytest.skip("no export directory in this environment")
        for path in csvs:
            header = path.read_text(encoding="utf-8").splitlines()[0]
            columns = {c.strip() for c in header.split(",")}
            leaked = columns & _CANONICAL_VALUE_FIELDS
            assert not leaked, (
                f"{path.name} now publishes canonical field(s) {sorted(leaked)}. "
                "The export leg has become a canonical-value surface, so it must be "
                "wired into the pick-completeness census and the parity chain "
                "(C1-U6 follow-up 11) rather than skipped as raw evidence."
            )

    def test_the_raw_payload_is_the_scrape_not_the_contract(self):
        """``dynasty_data_*.json`` is the scraper's payload.

        The contract is BUILT from it at request time; if the exported
        JSON ever contained ``playersArray`` rows with canonical values,
        the archive would be a second published board.
        """
        payloads = sorted(EXPORT_DIR.glob("dynasty_data_*.json")) if EXPORT_DIR.is_dir() else []
        if not payloads:
            pytest.skip("no exported payload in this environment")
        payload = json.loads(payloads[-1].read_text(encoding="utf-8"))
        assert "playersArray" not in payload, (
            "the exported payload now carries playersArray — it is a built contract, "
            "not a raw scrape, and the census/parity chain must cover it"
        )
        players = payload.get("players")
        assert isinstance(players, dict), "raw payload shape changed"
        for name, row in list(players.items())[:200]:
            if not isinstance(row, dict):
                continue
            leaked = set(row) & _CANONICAL_VALUE_FIELDS
            assert not leaked, f"{name} carries canonical field(s) {sorted(leaked)} in the export"
