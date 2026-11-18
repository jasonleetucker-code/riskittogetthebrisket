"""``/api/status`` carries aggregate board-freshness numbers (audit 2026-11-18).

On 2026-11-17 190 of the top-200 players were ``freshness == "low"`` and
nothing alerted.  ``src/api/freshness_slo.py`` is the one owner of those
measurements; these tests pin the arithmetic, the withheld rule's parity with
the frontend, missing-is-never-zero, and the public/admin split.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

import server
from src.api import freshness_slo as fs

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
_REPO = Path(__file__).resolve().parents[2]


def _row(rank, *, fresh="high", quarantined=False, value=5000.0):
    return {
        "canonicalConsensusRank": rank,
        "rankDerivedValue": value,
        "quarantined": quarantined,
        "confidenceAxes": {"freshness": fresh},
    }


def _contract(rows, *, scraped="2026-11-18T06:00:00+00:00", stamps=None):
    return {
        "playersArray": rows,
        "scrapeTimestamp": scraped,
        "dataFreshness": {"sourceTimestamps": stamps or {}},
    }


def test_withheld_rule_matches_the_frontend_rule_exactly():
    """One Python owner mirroring ``trade-logic.js::withheldValueState``."""
    js = (_REPO / "frontend/lib/trade-logic.js").read_text(encoding="utf-8")
    body = js.split("export function withheldValueState(row) {", 1)[1].split("\n}\n", 1)[0]
    assert "quarantined === true" in body and '"quarantined"' in body
    assert re.search(r'freshness === "low"\)\s*return "stale"', body)
    assert fs.withheld_value_state(_row(1, quarantined=True)) == "quarantined"
    assert fs.withheld_value_state(_row(1, fresh="low")) == "stale"
    # quarantine wins over stale, as in the JS
    assert fs.withheld_value_state(_row(1, fresh="low", quarantined=True)) == "quarantined"
    assert fs.withheld_value_state(_row(1)) is None
    assert fs.withheld_value_state(None) is None
    assert fs.withheld_value_state({"confidenceAxes": None}) is None


def test_stale_board_measures_the_incident_shape():
    rows = [_row(i, fresh="low" if i <= 190 else "high") for i in range(1, 201)]
    m = fs.board_freshness_metrics(_contract(rows), now=NOW)
    assert m["state"] == "measured"
    assert m["top200Count"] == 200 and m["top200StaleCount"] == 190
    assert m["top200StaleShare"] == 0.95
    assert m["pricedWithheldShare"] == 0.95
    assert m["boardAgeHours"] == 6.0


def test_healthy_board_measures_zero_not_unknown():
    m = fs.board_freshness_metrics(_contract([_row(i) for i in range(1, 201)]), now=NOW)
    assert m["top200StaleShare"] == 0.0 and m["pricedWithheldShare"] == 0.0


def test_withheld_counts_quarantined_and_ignores_unpriced_rows():
    rows = [_row(1, quarantined=True), _row(2), _row(3, fresh="low"), _row(4, value=None)]
    m = fs.board_freshness_metrics(_contract(rows), now=NOW)
    assert m["pricedCount"] == 3 and m["pricedWithheldCount"] == 2
    assert m["top200WithheldShare"] == 0.5  # 2 of the 4 ranked rows
    assert m["top200StaleShare"] == 0.25  # only freshness-low counts as stale


@pytest.mark.parametrize("contract", [None, {}, {"playersArray": []}, {"playersArray": "x"}])
def test_missing_contract_is_unknown_never_zero(contract):
    m = fs.board_freshness_metrics(contract, now=NOW)
    assert m["state"] == "unknown"
    for key in ("top200StaleShare", "pricedWithheldShare", "boardAgeHours", "top200Count"):
        assert m[key] is None, key


def test_unparseable_scrape_timestamp_is_unknown_age():
    m = fs.board_freshness_metrics(_contract([_row(1)], scraped="not-a-date"), now=NOW)
    assert m["boardAgeHours"] is None and m["boardScrapedAt"] is None


def test_private_source_staleness_counts_only_provisioned_sources():
    avail = {
        "signalsSf": {"state": "present", "provisioned": True, "csvPresent": True},
        "otherPrivate": {"state": "not_provisioned", "provisioned": False, "csvPresent": False},
        "freshPrivate": {"state": "present", "provisioned": True, "csvPresent": True},
        "noStamp": {"state": "present", "provisioned": True, "csvPresent": True},
    }
    stamps = {
        "signalsSf": {"staleness": "stale", "ageHours": 380.0, "maxAgeHours": 24},
        "otherPrivate": {"staleness": "stale"},
        "freshPrivate": {"staleness": "fresh", "ageHours": 1.0, "maxAgeHours": 24},
    }
    m = fs.board_freshness_metrics(
        _contract([_row(1)], stamps=stamps), now=NOW, private_availability=avail
    )
    assert (
        m["privateSourcesProvisioned"],
        m["privateSourcesStale"],
        m["privateSourcesUnknown"],
    ) == (3, 1, 1)
    assert [d["source"] for d in m["privateSourceDetail"]] == ["noStamp", "signalsSf"]


def test_unreadable_private_availability_is_unknown_not_zero():
    m = fs.board_freshness_metrics(_contract([_row(1)]), now=NOW, private_availability=None)
    assert m["privateSourcesStale"] is None and m["privateSourcesProvisioned"] is None


def test_measuring_never_mutates_the_contract():
    contract = _contract([_row(i, fresh="low") for i in range(1, 6)])
    before = json.dumps(contract, sort_keys=True)
    fs.board_freshness_metrics(contract, now=NOW, private_availability={})
    assert json.dumps(contract, sort_keys=True) == before


# -- the served endpoint: public numbers vs admin detail -----------------------
@pytest.fixture
def planted(monkeypatch):
    rows = [_row(i, fresh="low" if i <= 30 else "high") for i in range(1, 201)]
    stamps = {"signalsSf": {"staleness": "stale", "ageHours": 380.0, "maxAgeHours": 24}}
    monkeypatch.setattr(server, "latest_contract_data", _contract(rows, stamps=stamps))
    monkeypatch.setattr(
        "src.api.data_contract.private_source_availability",
        lambda *a, **k: {
            "signalsSf": {"state": "present", "provisioned": True, "csvPresent": True}
        },
    )
    monkeypatch.setattr(server, "send_alert", lambda *a, **k: None)
    return monkeypatch


def test_public_status_serves_numbers_and_withholds_source_names(planted):
    body = json.loads(asyncio.run(server.get_status()).body)
    slo = body["freshness_slo"]
    assert slo["top200StaleShare"] == 0.15
    assert slo["privateSourcesStale"] == 1
    assert slo["privateSourceDetail"] == "withheld"
    assert "signalsSf" not in json.dumps(slo)


def test_admin_content_carries_the_per_source_detail(planted):
    """``/api/admin/diagnostics`` serves ``_status_content`` unredacted."""
    slo = server._status_content()["freshness_slo"]
    assert slo["privateSourceDetail"][0]["source"] == "signalsSf"
    assert slo["privateSourceDetail"][0]["ageHours"] == 380.0


def test_status_without_a_contract_says_unknown_not_healthy(monkeypatch):
    monkeypatch.setattr(server, "latest_contract_data", None)
    monkeypatch.setattr(server, "send_alert", lambda *a, **k: None)
    slo = json.loads(asyncio.run(server.get_status()).body)["freshness_slo"]
    assert slo["state"] == "unknown" and slo["top200StaleShare"] is None
