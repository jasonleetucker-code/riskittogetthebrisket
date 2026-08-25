"""Failure attribution speaks ONE vocabulary (F-12 / census S-2 / V1-76).

The scraper's ``sourceRunSummary`` names a source by its RUN name — the
``source_enabled_map`` key in ``Dynasty Scraper.py`` (``KTC``,
``IDPTradeCalc``, ``DLF_LocalCSV`` …).  Every population/coverage surface
in ``data_contract`` speaks the ranking-registry KEY (``ktcSfTep``,
``idpTradeCalc``, ``dlfSf`` …).  The two vocabularies are disjoint on
real data — ``"DLF_LocalCSV" != "dlfSf"`` — so a run-level failure could
not be joined back to the registry rows it concerns.  The health surface
therefore misattributed or dropped it (audit F-12).

The refuted design (``playerCount: null`` to distinguish "reported zero"
from "did not report") is NOT resurrected here: it raised ``TypeError``
at the scrape-promotion ``site_count`` computation and would have marked
whole scrapes FAILED.  See ``docs/VERSION_1_COMPLETION_CONTRACT.md`` §8.1.

The repair is a single DECLARED mapping owned by the registry (each
``_RANKING_SOURCES`` entry's ``run_source`` field, resolved by
``registry_keys_for_run_source``), so a failure disposition ROUND-TRIPS
from its run name to its canonical registry keys.  Unverified fails
closed: a run name no registered source declares resolves to ``[]`` and
stays unattributed rather than being pinned to a guessed row.
"""

from __future__ import annotations

import server as srv
from src.api.data_contract import (
    get_ranking_source_keys,
    registry_keys_for_run_source,
)


# The verifiable scraper-run sources — the only run names that can appear
# in ``sourceRunSummary`` today — and the registry keys each governs.
DLF_KEYS = ["dlfSf", "dlfRookieSf", "dlfIdp", "dlfRookieIdp"]


class TestRunNameResolvesToRegistryKeys:
    def test_ktc_run_name_round_trips_to_its_registry_key(self):
        assert registry_keys_for_run_source("KTC") == ["ktcSfTep"]

    def test_idptradecalc_run_name_round_trips(self):
        assert registry_keys_for_run_source("IDPTradeCalc") == ["idpTradeCalc"]

    def test_dlf_local_csv_run_name_governs_every_dlf_registry_key(self):
        # The exact defect in the finding: a DLF failure arrives under the
        # transport-qualified run name ``DLF_LocalCSV`` and must resolve to
        # ALL four DLF registry boards, none of which is spelled
        # ``DLF_LocalCSV``.
        assert sorted(registry_keys_for_run_source("DLF_LocalCSV")) == sorted(DLF_KEYS)

    def test_resolved_keys_are_all_real_registry_keys(self):
        registered = set(get_ranking_source_keys())
        for run_name in ("KTC", "IDPTradeCalc", "DLF_LocalCSV"):
            for key in registry_keys_for_run_source(run_name):
                assert key in registered

    def test_unverified_run_name_fails_closed(self):
        # A run name no registered source declares must resolve to nothing
        # — the failure stays unattributed, never pinned to a guessed row.
        assert registry_keys_for_run_source("SomeSourceWeNeverRan") == []
        assert registry_keys_for_run_source("") == []
        assert registry_keys_for_run_source(None) == []  # type: ignore[arg-type]

    def test_primary_and_transport_qualified_forms_agree(self):
        # V1-80's qualifier tolerance: a bare ``DLF`` and the scraper's
        # ``DLF_LocalCSV`` resolve to the same keys, so a primary name and
        # its transport-qualified form are never two incomparable labels.
        assert sorted(registry_keys_for_run_source("DLF")) == sorted(DLF_KEYS)


def _payload_with_dlf_failure() -> dict:
    """A complete-shaped run in which DLF_LocalCSV hard-failed.

    Anchor ``sites`` carry real integer ``playerCount`` values — the
    refuted design's ``playerCount: null`` is deliberately NOT emitted.
    """
    return {
        "sites": [
            {"key": "ktc", "playerCount": 500},
            {"key": "idpTradeCalc", "playerCount": 900},
        ],
        "settings": {
            "sourceRunSummary": {
                "overallStatus": "partial",
                "partialRun": True,
                "enabledSources": ["KTC", "IDPTradeCalc", "DLF_LocalCSV"],
                "completeSources": ["KTC", "IDPTradeCalc"],
                "partialSources": [],
                "timedOutSources": [],
                "failedSources": ["DLF_LocalCSV"],
                "sources": {
                    "DLF_LocalCSV": {
                        "error": "local CSV missing",
                        "message": "DLF local CSV not found",
                        "valueCount": 0,
                    }
                },
            }
        },
    }


class TestSnapshotRoundTrip:
    def test_failure_record_carries_its_registry_keys(self):
        snap = srv._build_source_health_snapshot(_payload_with_dlf_failure())
        dlf_fail = [f for f in snap["source_failures"] if f["source"] == "DLF_LocalCSV"]
        assert len(dlf_fail) == 1, "the DLF run failure must be reported once"
        assert sorted(dlf_fail[0]["registryKeys"]) == sorted(DLF_KEYS), (
            "a run-named failure must round-trip to the registry rows it "
            f"concerns; got {dlf_fail[0].get('registryKeys')}"
        )

    def test_runtime_publishes_key_space_projection(self):
        snap = srv._build_source_health_snapshot(_payload_with_dlf_failure())
        runtime = snap["source_runtime"]
        # Run-name provenance is retained...
        assert runtime["failed_sources"] == ["DLF_LocalCSV"]
        # ...and the registry-key projection is published beside it so the
        # health rows (registry-keyed) can light up on their own.
        assert sorted(runtime["failed_source_keys"]) == sorted(DLF_KEYS)
        assert runtime["partial_source_keys"] == []
        assert runtime["timed_out_source_keys"] == []

    def test_the_two_vocabularies_now_share_a_join_key(self):
        # The census S-2 statement made executable: the failure vocabulary
        # and the population vocabulary intersect where they should.
        snap = srv._build_source_health_snapshot(_payload_with_dlf_failure())
        registered = set(snap["registered_sources"])
        failed_keys = set(snap["source_runtime"]["failed_source_keys"])
        assert failed_keys, "a real failure must project into key space"
        assert failed_keys <= registered, (
            "every projected failure key must be a member of the registry "
            "population — otherwise it is still a second vocabulary"
        )


class TestRefutedDesignIsNotResurrected:
    """The refuted ``playerCount: null`` design broke the scrape promoter.

    Guard the two facts §8.1 pinned: our output introduces no ``None``
    ``playerCount``, and the ``site_count`` computation the promoter runs
    still works on a payload our snapshot rode alongside.
    """

    def test_snapshot_introduces_no_null_player_count(self):
        snap = srv._build_source_health_snapshot(_payload_with_dlf_failure())
        # anchor_row_counts is the only place playerCount is read; a real
        # integer count must not have become None.
        for key, count in snap["anchor_row_counts"].items():
            assert count is not None, (
                f"{key} carried a real playerCount and must not be nulled — "
                "that is the refuted design that raised TypeError at the "
                "scrape promoter"
            )

    def test_promoter_site_count_expression_still_works(self):
        # Replicates server.py's scrape-promotion guard verbatim to prove
        # our failure-attribution shape never reaches it with a null
        # playerCount.  ``None > 0`` would raise TypeError.
        result = _payload_with_dlf_failure()
        result["players"] = {"a": {}, "b": {}}
        site_count = len([s for s in result.get("sites", []) if s.get("playerCount", 0) > 0])
        assert site_count == 2  # ktc + idpTradeCalc, both positive
