"""Integration tests for the two-source adapter layer (KTC + IDPTradeCalc).

The legacy ``src.canonical.transform`` + ``blend_source_values`` tests
have been retired as part of the canonical-pipeline purge.  What
remains is the adapter-loading smoke — if these CSVs don't parse, the
live contract pipeline can't blend them either.
"""

from __future__ import annotations

import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _pinned_csv(name: str) -> Path:
    """The PINNED board's CSV, never today's refresh (tests/test_pinned_board.py)."""
    from tests.archive_fixtures import pinned_board_root

    path = pinned_board_root() / "CSVs" / "site_raw" / name
    assert path.is_file(), f"the pinned board carries {name}"
    return path


class TestAdapterLoads:
    def test_scraper_bridge_loads_ktc(self):
        from src.adapters.scraper_bridge_adapter import ScraperBridgeAdapter

        ktc_path = _pinned_csv("ktc.csv")
        adapter = ScraperBridgeAdapter(
            source_id="KTC", source_bucket="offense_vet", signal_type="value"
        )
        result = adapter.load(ktc_path)
        assert len(result.records) >= 100
        assert len(result.warnings) == 0

    def test_scraper_bridge_loads_idptradecalc(self):
        from src.adapters.scraper_bridge_adapter import ScraperBridgeAdapter

        idp_path = _pinned_csv("idpTradeCalc.csv")
        adapter = ScraperBridgeAdapter(
            source_id="IDPTRADECALC", source_bucket="idp_vet", signal_type="value"
        )
        result = adapter.load(idp_path)
        assert len(result.records) >= 100
        assert len(result.warnings) == 0
