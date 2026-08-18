"""The source-health population is the REGISTRY, not what a run emitted.

F-7 / census S-1.  ``/api/status``'s ``source_health`` block answers
"how are our sources doing".  Its denominator was ``payload["sites"]``,
which the scraper emits with exactly the two ANCHOR markets — measured
on the live 2026-08-18 export, ``sites`` is ``[ktc, idpTradeCalc]``.  So
the headline read **2 of 2 healthy, 0 missing** for a board carried by
**21 registered production voters**.

The defect is the denominator, not the arithmetic.  Twenty voters were
outside the population, so a source that stopped contributing entirely
could not appear in ``missing_sources`` — it was never counted.  That is
``MISSING IS NEVER ZERO`` at the health layer, and it is the rule
``src/api/confidence.py`` already gets right: a family that stops
covering a row stays *eligible*, so its silence is permanent missing
evidence rather than a smaller denominator.

Deliberately NOT ``coverageAudit.expectedSites``.  That block is an
anchor-loss detector and **2 is correct for it**; widening it would
break the thing it does well.  The population is a separate question
with a separate owner — ``data_contract.get_ranking_source_keys()``.
"""

from __future__ import annotations

import server as srv
from src.api.data_contract import get_ranking_source_keys


def _payload_with_anchor_only_sites() -> dict:
    """The real shape: two anchor rows, a complete run, nothing wrong."""
    return {
        "sites": [
            {"key": "ktc", "playerCount": 500},
            {"key": "idpTradeCalc", "playerCount": 900},
        ],
        "settings": {
            "sourceRunSummary": {
                "overallStatus": "complete",
                "partialRun": False,
                "enabledSources": ["KTC", "IDPTradeCalc"],
                "completeSources": ["KTC", "IDPTradeCalc"],
                "partialSources": [],
                "timedOutSources": [],
                "failedSources": [],
                "sources": {},
            }
        },
    }


class TestPopulationIsTheRegistry:
    def test_total_sources_counts_every_registered_voter(self):
        registered = get_ranking_source_keys()
        assert len(registered) > 2, "precondition: the registry is bigger than the anchors"

        snap = srv._build_source_health_snapshot(_payload_with_anchor_only_sites())

        assert snap["total_sources"] == len(registered), (
            "the health headline must count the sources we are ENTITLED TO EXPECT. "
            f"Got {snap['total_sources']} for a registry of {len(registered)} — that is the "
            "2-row `sites` list being used as a denominator."
        )

    def test_every_registered_key_is_present_in_source_counts(self):
        snap = srv._build_source_health_snapshot(_payload_with_anchor_only_sites())
        counts = snap["source_counts"]
        missing_from_population = sorted(set(get_ranking_source_keys()) - set(counts))
        assert not missing_from_population, (
            "a registered source absent from `source_counts` is invisible to every consumer "
            f"that iterates it: {missing_from_population}"
        )

    def test_a_source_that_contributed_nothing_is_reported_missing(self):
        """The whole point.  Silence must be legible, not absent."""
        registered = get_ranking_source_keys()
        # Everything voted except one — the shape of a single fetcher outage.
        silent = registered[-1]
        coverage = {k: 100 for k in registered if k != silent}

        snap = srv._build_source_health_snapshot(
            _payload_with_anchor_only_sites(), coverage=coverage
        )

        assert silent in snap["missing_sources"], (
            f"{silent!r} contributed to zero rows and must be named in `missing_sources`; "
            f"got {snap['missing_sources']}"
        )
        assert snap["sources_with_data"] == len(registered) - 1
        assert snap["source_counts"][silent] == 0

    def test_registered_sources_is_published_so_a_consumer_can_list_rows(self):
        """`/tools/source-health` lists rows from `source_runtime.enabled_sources`,
        which is the SCRAPER RUN's list in the scraper's own naming
        (``["KTC", "IDPTradeCalc"]``) — 2 entries, and not registry keys.
        The population has to be published separately for the page to be
        able to render the pipeline it claims to render."""
        snap = srv._build_source_health_snapshot(_payload_with_anchor_only_sites())
        assert snap.get("registered_sources") == sorted(get_ranking_source_keys())


class TestAnchorDetectorIsUntouched:
    def test_snapshot_does_not_redefine_the_anchor_set(self):
        """`coverageAudit.expectedSites` is a different question and stays a
        2-entry anchor-loss detector.  This asserts the repair did not
        smuggle the population into it."""
        from src.api.data_contract import build_api_data_contract
        import gzip
        import json
        from pathlib import Path

        fixture = Path("tests/fixtures/golden/input_export.json.gz")
        raw = json.loads(gzip.decompress(fixture.read_bytes()).decode("utf-8"))
        expected = (build_api_data_contract(raw).get("coverageAudit") or {}).get(
            "expectedSites"
        ) or {}
        assert expected.get("offense") == ["ktc"]
        assert expected.get("idp") == ["idpTradeCalc"]


class TestUnknownIsNotZero:
    def test_an_empty_coverage_map_is_unmeasured_not_universal_silence(self):
        """``served_source_coverage`` is a module global that starts ``{}``
        and is filled at contract promotion.  Treating empty as
        measured-zero would report every registered source as silent on
        every cold boot — the same missing-vs-zero mistake one level
        down."""
        snap = srv._build_source_health_snapshot(_payload_with_anchor_only_sites(), coverage={})
        registered = sorted(get_ranking_source_keys())
        assert snap["missing_sources"] == [], (
            "an unprimed server must not accuse every source of going silent; "
            f"got {len(snap['missing_sources'])} 'missing'"
        )
        assert snap["unmeasured_sources"] == registered
        assert snap["sources_with_data"] == 0
        assert all(v is None for v in snap["source_counts"].values())

    def test_the_anchor_row_counts_survive_under_their_own_name(self):
        """The scraper's row counts are a different quantity from board
        contribution; merging them into one map was the defect.  They are
        kept, named for what they are."""
        snap = srv._build_source_health_snapshot(_payload_with_anchor_only_sites())
        assert snap["anchor_row_counts"] == {"ktc": 500, "idpTradeCalc": 900}
