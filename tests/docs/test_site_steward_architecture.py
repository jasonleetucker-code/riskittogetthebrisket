import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO / path).read_text(encoding="utf-8")


def test_steward_architecture_is_not_runtime_activation():
    doc = _read("docs/autonomy/SITE_STEWARD_ARCHITECTURE_2026-09-08.md")
    assert "Not runtime activation" in doc
    assert "Week 1 remains an active fixed-denominator launch contract at 25/30 VERIFIED" in doc
    assert "DEFERRED_BY_AUTHORITY" in doc
    assert "zero production mutation" in doc


def test_architecture_chooses_existing_infrastructure_first():
    doc = _read("docs/autonomy/SITE_STEWARD_ARCHITECTURE_2026-09-08.md")
    assert "hybrid existing infrastructure + repo-owned Steward controller" in doc
    assert "Do not replace these systems with an “agent platform.”" in doc
    assert "Temporal/LangGraph as immediate dependency" in doc
    assert "REJECT FOR NOW" in doc


def test_architecture_separates_source_discovery_from_activation():
    doc = _read("docs/autonomy/SITE_STEWARD_ARCHITECTURE_2026-09-08.md")
    assert "No discovered source may vote in canonical production" in doc
    assert "CHALLENGER -> APPROVED/ACTIVE" in doc
    assert "changed source weighting" in doc


def test_architecture_rejects_generic_youtube_scraping():
    doc = _read("docs/autonomy/SITE_STEWARD_ARCHITECTURE_2026-09-08.md")
    assert "Do not build a generic YouTube transcript scraper" in doc
    assert "Current YouTube API policy prohibits scraping" in doc
    assert "publisher-provided transcript" in doc


def test_steward_contract_schema_contains_all_required_defs():
    payload = json.loads(_read("config/steward/contracts.schema.json"))
    assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    defs = payload["$defs"]
    assert {
        "autonomousRunContract",
        "checkpoint",
        "runReceipt",
        "sourceCandidate",
        "featureConcept",
        "mediaEvidence",
    } <= set(defs)
    assert defs["autonomousRunContract"]["properties"]["mode"]["$ref"] == "#/$defs/runMode"
    assert "A_REPORT_ONLY" in defs["autonomyClass"]["enum"]
    assert "D_CONSEQUENTIAL" in defs["autonomyClass"]["enum"]


def test_source_and_media_contracts_pin_semantics_and_provenance():
    payload = json.loads(_read("config/steward/contracts.schema.json"))
    source = payload["$defs"]["sourceCandidate"]
    assert "signal_type" in source["properties"]["semantics"]["required"]
    assert source["properties"]["semantics"]["properties"]["signal_type"]["enum"] == [
        "ordinal",
        "cardinal",
        "mixed",
        "unknown",
    ]
    assert "eligible_to_vote" in source["properties"]["evaluation"]["required"]

    media = payload["$defs"]["mediaEvidence"]
    claim_types = media["properties"]["claim_type"]["enum"]
    assert {"FACT", "REPORT", "ANALYST_OPINION", "PROJECTION", "RANKING", "RUMOR"} <= set(
        claim_types
    )
    assert "rights_or_access_note" in media["properties"]["provenance"]["required"]


def test_phase_one_requires_report_only_security_controls():
    doc = _read("docs/autonomy/SITE_STEWARD_ARCHITECTURE_2026-09-08.md")
    assert "report-only Steward" in doc
    assert "no write-capable token in model research process" in doc
    assert "HALT/budget/retry tests" in doc
    assert "resume after forced interruption without duplicate work" in doc
