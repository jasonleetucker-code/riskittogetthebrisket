import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO / path).read_text(encoding="utf-8")


def test_steward_architecture_is_not_runtime_activation():
    doc = _read("docs/autonomy/SITE_STEWARD_ARCHITECTURE_2026-09-08.md")
    assert "Not runtime activation" in doc
    assert "Read the live Week 1 contract for its literal count" in doc
    from src.steward.repository import launch_state

    contract = launch_state(_read("docs/season-launch/WEEK_1_LAUNCH_CONTRACT.md"))
    assert contract["total"] == 30
    assert contract["verified"] == sum(
        row["state"] == "VERIFIED" for row in contract["rows"].values()
    )
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


def test_schema_root_validates_each_record_kind_directly():
    payload = json.loads(_read("config/steward/contracts.schema.json"))
    refs = {entry["$ref"] for entry in payload["oneOf"]}
    assert refs == {
        "#/$defs/autonomousRunContract",
        "#/$defs/checkpoint",
        "#/$defs/runReceipt",
        "#/$defs/sourceCandidate",
        "#/$defs/featureConcept",
        "#/$defs/mediaEvidence",
    }


def test_authority_and_mode_composition_is_structurally_pinned():
    payload = json.loads(_read("config/steward/contracts.schema.json"))
    run = payload["$defs"]["autonomousRunContract"]
    encoded = json.dumps(run["allOf"], sort_keys=True)
    assert "A_REPORT_ONLY" in encoded
    assert "C_PREAUTHORIZED_INTEGRATION" in encoded
    assert "D_CONSEQUENTIAL" in encoded
    assert "owner_authorization_ref" in encoded
    assert "report_only" in encoded
    assert "assisted" in encoded

    doc = _read("docs/autonomy/SITE_STEWARD_ARCHITECTURE_2026-09-08.md")
    assert "Mode × autonomy-class composition" in doc
    assert "`autonomous` mode never upgrades the authority class" in doc


def test_pending_and_executed_actions_require_idempotency_keys():
    payload = json.loads(_read("config/steward/contracts.schema.json"))
    pending = payload["$defs"]["pendingAction"]
    executed = payload["$defs"]["executedAction"]
    assert "idempotency_key" in pending["required"]
    assert "idempotency_key" in executed["required"]
    assert (
        payload["$defs"]["checkpoint"]["properties"]["pending"]["items"]["$ref"]
        == "#/$defs/pendingAction"
    )
    assert (
        payload["$defs"]["runReceipt"]["properties"]["actions"]["items"]["$ref"]
        == "#/$defs/executedAction"
    )


def test_owner_zero_incremental_spend_policy_is_durable():
    architecture = _read("docs/autonomy/SITE_STEWARD_ARCHITECTURE_2026-09-08.md")
    vision = _read("docs/AUTONOMOUS_SITE_STEWARD_VISION.md")
    assert "Owner cost policy — zero incremental spend by default" in architecture
    assert "max_usd: 0" in architecture
    assert "usage-billed OpenAI API models" in architecture
    assert "Paid escalation requires a separate explicit owner authorization" in architecture
    assert "Cost boundary" in vision
    assert "incremental Steward usage budget is `$0`" in vision
    assert "remains deferred rather than silently spending money" in vision
