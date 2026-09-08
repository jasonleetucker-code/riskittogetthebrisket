from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO / path).read_text(encoding="utf-8")


def test_steward_vision_is_owner_goal_not_runner_activation():
    doc = _read("docs/AUTONOMOUS_SITE_STEWARD_VISION.md")
    assert "owner-approved long-term direction" in doc
    assert "design/governance only" in doc
    assert "does **not** activate an unattended runner" in doc
    assert "near-full automation with narrow, explicit human gates" in doc
    assert "The model is the brain, not the scheduler" in doc
    assert "scheduler/event -> preflight" in doc


def test_source_discovery_is_separate_from_canonical_activation():
    doc = _read("docs/AUTONOMOUS_SITE_STEWARD_VISION.md")
    lifecycle = (
        "DISCOVERED -> QUARANTINED -> CLASSIFIED -> REPLAYABLE -> EVALUATED -> "
        "CHALLENGER -> APPROVED -> ACTIVE"
    )
    assert lifecycle in doc
    assert "Source discovery and source activation are separate transitions" in doc
    assert "must not influence canonical values merely because the agent found it" in doc
    assert "ordinal vs cardinal meaning" in doc
    assert "correlation with existing sources" in doc
    assert "fail closed" in doc


def test_feature_discovery_requires_independent_repo_native_implementation():
    doc = _read("docs/AUTONOMOUS_SITE_STEWARD_VISION.md")
    lifecycle = (
        "OBSERVED -> CONCEPT_NOTE -> FIT_ASSESSMENT -> INTERNAL_SPEC -> PROTOTYPE_BRANCH -> "
        "REVIEW -> OWNER/PRODUCT_GATE -> MERGED -> VERIFIED"
    )
    assert "Feature / competitor intelligence" in doc
    assert lifecycle in doc
    assert "Independent implementation rule" in doc
    assert "Do **not** copy proprietary source code" in doc
    assert "Personal/noncommercial use does not erase copyright" in doc
    assert "extend it instead of creating a competitor clone" in doc


def test_media_lane_preserves_provenance_freshness_and_correlation():
    doc = _read("docs/AUTONOMOUS_SITE_STEWARD_VISION.md")
    assert "public YouTube transcripts/captions" in doc
    assert "podcast transcripts or feeds" in doc
    assert "exact timestamp/range" in doc
    assert "freshness/expiry" in doc
    assert "correlation/source-family information" in doc
    assert "Commentary is evidence, not canonical fact" in doc


def test_math_lane_can_challenge_but_not_self_promote():
    doc = _read("docs/AUTONOMOUS_SITE_STEWARD_VISION.md")
    lifecycle = (
        "fit -> backtest -> validate -> compare -> approval -> promote -> monitor -> rollback"
    )
    assert "Math / model / rankings steward" in doc
    assert lifecycle in doc
    assert "may **not** silently self-promote" in doc
    assert "Automation should make everything before the approval gate" in doc


def test_autonomy_classes_keep_consequential_transitions_guarded():
    doc = _read("docs/AUTONOMOUS_SITE_STEWARD_VISION.md")
    classes = (
        "Class A — observe/report",
        "Class B — reversible workspace/branch work",
        "Class C — routine integration under pre-approved policy",
        "Class D — consequential methodology/product/authority change",
    )
    for name in classes:
        assert name in doc
    assert "The model cannot grant itself broader permissions" in doc
    assert "external halt sentinel / kill switch" in doc


def test_lifetime_prompt_is_versioned_contract_not_monolith():
    doc = _read("docs/AUTONOMOUS_SITE_STEWARD_VISION.md")
    assert "“One lifetime prompt” means a versioned contract" in doc
    assert "machine-readable autonomous-run contract" in doc
    assert "persistent state/checkpoints" in doc
    assert "append-only receipts" in doc
