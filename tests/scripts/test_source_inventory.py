"""``scripts/source_inventory.py`` — every ingested source is accounted for.

B17 guard (owner directive 2026-09-24): a CSV that lands in ``CSVs/site_raw``
must either be a registered voter or carry a stated reason for not voting.
"Ingested but nobody decided" is the state that let a source sit on the
sidelines unnoticed, so it fails here instead.
"""

from __future__ import annotations

from scripts import source_inventory as inv
from src.api import data_contract as dc
from src.sources.ktc_market import KTC_MARKET_KEY


def _inventory() -> dict:
    return inv.build_inventory({"playersArray": []})


def test_no_ingested_source_is_unclassified():
    rows = _inventory()["sources"]
    unclassified = [r["key"] for r in rows if r["role"] == "UNCLASSIFIED"]
    assert not unclassified, f"ingested with no decision: {unclassified}"


def test_every_registered_voter_is_a_model_input():
    roles = {r["key"]: r["role"] for r in _inventory()["sources"]}
    for src in dc._RANKING_SOURCES:
        assert roles[src["key"]] == "model_input"


def test_ktc_market_is_the_benchmark_and_mirrors_do_not_vote():
    roles = {r["key"]: r["role"] for r in _inventory()["sources"]}
    assert roles[KTC_MARKET_KEY] == "benchmark"
    for mirror in ("ktc", "ktcSfTep"):
        assert roles[mirror] == "non_voting"


def test_markdown_lists_every_source_once():
    data = _inventory()
    md = inv.to_markdown(data)
    for r in data["sources"]:
        assert md.count(f"| `{r['key']}` |") == 1
