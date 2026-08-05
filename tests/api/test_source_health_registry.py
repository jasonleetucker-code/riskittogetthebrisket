"""``/api/status.source_health`` must describe the board, not the scraper.

R13 / W05-F001 / W05-F002 / W23-F007 / W23-F008.  Every source-health
surface used to be built from the legacy browser scraper's own
four-name run plan (``source_runtime.enabled_sources`` =
``['IDPTradeCalc','KTC','KTC_TradeDB','KTC_WaiverDB']``) and from
``payload['sites']``, which carries two entries.  Measured on the live
payload before the fix:

    total_sources 2 · sources_with_data 2 · missing_sources []
    source_counts {'ktc': 500, 'idpTradeCalc': 900}

for a board blending 21 registered sources — a 19-source outage could
not move any of those numbers, and ``missing_sources`` was empty by
construction because the denominator was whatever ran.

These tests pin the registry as the denominator.
"""

from __future__ import annotations

import server as srv
from src.api.data_contract import _RANKING_SOURCES, _SOURCE_CSV_PATHS


def _contract(counts: dict[str, int], *, blend: dict[str, int] | None = None) -> dict:
    """Synthesize a contract whose per-source ingest counts are exactly
    ``counts`` (and blend counts ``blend``, defaulting to the same)."""
    blend = counts if blend is None else blend
    rows: list[dict] = []
    total = max([*counts.values(), *blend.values(), 0])
    for i in range(total):
        vals = {k: 1000 for k, n in counts.items() if i < n}
        meta = {k: {"rank": i + 1} for k, n in blend.items() if i < n}
        rows.append({"canonicalSiteValues": vals, "sourceRankMeta": meta})
    return {"playersArray": rows}


def _snapshot(counts: dict[str, int], *, blend: dict[str, int] | None = None, **kw) -> dict:
    contract = _contract(counts, blend=blend)
    # Set the prime-time globals directly (rather than through the
    # compute helpers) so this red-check exercises the SNAPSHOT, not
    # the presence of a new helper.
    srv.served_source_ingest_counts = dict(counts)
    srv.served_source_coverage = dict(counts if blend is None else blend)
    srv.latest_contract_data = contract
    payload = {
        "sites": [
            {"key": "ktc", "playerCount": 500},
            {"key": "idpTradeCalc", "playerCount": 900},
        ],
        "settings": {},
        **kw,
    }
    return srv._build_source_health_snapshot(payload)


def _registry_keys() -> set[str]:
    return {str(s["key"]) for s in _RANKING_SOURCES if s.get("key")}


def test_source_health_enumerates_every_registered_source():
    counts = {k: 300 for k in _SOURCE_CSV_PATHS}
    snap = _snapshot(counts)
    keys = {r["key"] for r in snap["sources_detail"] if r["inRegistry"]}
    assert _registry_keys() <= keys, sorted(_registry_keys() - keys)
    assert set(snap["source_counts"]) >= _registry_keys()
    assert snap["total_sources"] == len(_SOURCE_CSV_PATHS)
    assert snap["sources_with_data"] == len(_SOURCE_CSV_PATHS)


def test_a_dead_source_is_named_in_missing_sources():
    """The whole point: deleting a source from the board has to move a
    number.  ``ktcSfTep`` is the retail anchor."""
    counts = {k: 300 for k in _SOURCE_CSV_PATHS if k != "ktcSfTep"}
    snap = _snapshot(counts)
    assert "ktcSfTep" in snap["missing_sources"]
    assert snap["sources_with_data"] == len(_SOURCE_CSV_PATHS) - 1
    row = next(r for r in snap["sources_detail"] if r["key"] == "ktcSfTep")
    assert row["status"] == "empty"
    assert row["rows"] == 0
    assert any(f["source"] == "ktcSfTep" for f in snap["source_failures"])


def test_counts_are_registry_keyed_not_case_folded():
    """``source_counts`` used to be keyed by whatever the scraper called
    the source, so the page's ``counts[src] || counts[src.toLowerCase()]``
    lookup resolved 'KTC'→'ktc' but missed 'IDPTradeCalc'→'idptradecalc'
    and rendered a 900-row source as 0."""
    snap = _snapshot({k: 300 for k in _SOURCE_CSV_PATHS} | {"idpTradeCalc": 911})
    assert snap["source_counts"]["idpTradeCalc"] == 911
    assert "IDPTradeCalc" not in snap["source_counts"]
    assert "idptradecalc" not in snap["source_counts"]


def test_unknown_counts_are_none_not_zero():
    """With no contract primed the row count is UNKNOWN.  Reporting 0
    would make a cold server indistinguishable from a dead pipeline."""
    srv.served_source_ingest_counts = {}
    srv.served_source_coverage = {}
    srv.latest_contract_data = None
    snap = srv._build_source_health_snapshot({"sites": [], "settings": {}})
    rows = [r for r in snap["sources_detail"] if r["inRegistry"]]
    assert rows, "registry rows must be listed even with no contract"
    assert all(r["rows"] is None and r["status"] == "unknown" for r in rows)
    assert snap["missing_sources"] == []


def test_ingest_only_source_reports_unknown_blend_rows():
    """``ktc`` is ingested but is not a blend member (``ktcSfTep``
    supersedes it), so its blend contribution is unknown — not zero."""
    snap = _snapshot({k: 300 for k in _SOURCE_CSV_PATHS})
    row = next(r for r in snap["sources_detail"] if r["key"] == "ktc")
    assert row["inBlend"] is False
    assert row["blendRows"] is None
    assert row["rows"] == 300


def test_runtime_failures_map_onto_registry_keys():
    """A failed 'KTC' scrape run is a failure of BOTH registry sources
    that run produces.  Previously the runtime name never joined to a
    registry key at all."""
    snap = _snapshot(
        {k: 300 for k in _SOURCE_CSV_PATHS},
        settings={
            "sourceRunSummary": {
                "enabledSources": ["KTC", "IDPTradeCalc", "KTC_TradeDB"],
                "failedSources": ["KTC"],
                "sources": {},
            }
        },
    )
    by_key = {r["key"]: r for r in snap["sources_detail"]}
    assert by_key["ktc"]["status"] == "failed"
    assert by_key["ktcSfTep"]["status"] == "failed"
    # A runtime name with no registry counterpart stays visible as
    # itself rather than being dropped or mis-joined.
    assert by_key["KTC_TradeDB"]["inRegistry"] is False


def test_ingest_counts_are_counted_off_the_served_contract():
    """The prime-time counter must agree with the row-count floors:
    non-zero ``canonicalSiteValues`` per source."""
    contract = _contract({"ktcSfTep": 3, "dlfSf": 1})
    contract["playersArray"].append({"canonicalSiteValues": {"ktcSfTep": 0}})
    assert srv._compute_source_ingest_counts(contract) == {"ktcSfTep": 3, "dlfSf": 1}
    assert srv._compute_source_ingest_counts(None) == {}


def test_parse_errors_join_onto_the_source_row():
    contract = _contract({k: 300 for k in _SOURCE_CSV_PATHS})
    contract["sourceParseErrors"] = [{"source": "otcffbSf", "error": "schema_mismatch"}]
    srv.served_source_ingest_counts = {k: 300 for k in _SOURCE_CSV_PATHS}
    srv.served_source_coverage = {k: 300 for k in _SOURCE_CSV_PATHS}
    srv.latest_contract_data = contract
    snap = srv._build_source_health_snapshot({"sites": [], "settings": {}})
    row = next(r for r in snap["sources_detail"] if r["key"] == "otcffbSf")
    assert row["status"] == "failed"
    assert row["reason"] == "schema_mismatch"
