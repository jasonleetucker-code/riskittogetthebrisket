from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENGINEERING_PRIORITIES = (
    "docs/engineering/"
    "ENGINEERING_RELIABILITY_PRIORITIES_2026-09-06.md"
)


def _read(path: str) -> str:
    return (REPO / path).read_text(encoding="utf-8")


def test_universal_entrypoint_routes_every_model_to_same_authorities():
    entry = _read("AI_INSTRUCTIONS.md")
    targets = (
        "docs/AGENT_OPERATING_SYSTEM.md",
        "docs/EXECUTION_PLAN.md",
        "docs/WORK_CLAIMS.md",
        "ASSISTANT_COORDINATION.md",
        "CLAUDE.md",
        ENGINEERING_PRIORITIES,
    )
    for target in targets:
        assert target in entry

    for model in ("Claude", "Codex", "Gemini", "ChatGPT", "Copilot"):
        assert model in entry


def test_provider_entrypoints_are_adapters_to_universal_instructions():
    assert "AI_INSTRUCTIONS.md" in _read("AGENTS.md")
    assert "@AI_INSTRUCTIONS.md" in _read("CLAUDE.md").splitlines()
    assert "AI_INSTRUCTIONS.md" in _read("GEMINI.md")
    assert "AI_INSTRUCTIONS.md" in _read(".github/copilot-instructions.md")

    claude = _read("CLAUDE.md")
    assert "LEGACY FILENAME, UNIVERSAL RUNBOOK" in claude
    assert "every LLM" in claude


def test_provider_specific_files_cannot_own_unique_semantics():
    os_doc = _read("docs/AGENT_OPERATING_SYSTEM.md")
    entry = _read("AI_INSTRUCTIONS.md")

    os_phrases = (
        "Cross-model parity rule",
        "adapters, not authorities",
        "No correctness, architecture, safety, verification, product, methodology, "
        "or engineering-process rule",
    )
    for phrase in os_phrases:
        assert phrase in os_doc

    entry_phrases = (
        "Provider-specific files are adapters only",
        "Do not make the human owner remember which model knows which rule.",
    )
    for phrase in entry_phrases:
        assert phrase in entry


def test_startup_preflight_is_shared_not_claude_owned():
    shared = _read("scripts/agent_session_start.sh")
    claude_hook = _read(".claude/health-check.sh")

    shared_phrases = (
        "Model-neutral session-start health check",
        "AI_INSTRUCTIONS.md",
        "Data Freshness",
        "Test Collection",
        "Git Status",
        "Scraper Syntax",
    )
    for phrase in shared_phrases:
        assert phrase in shared

    assert "exec bash scripts/agent_session_start.sh" in claude_hook

    receipt = _read("scripts/agent_os_receipt.py")
    assert ".agent-runtime/session-receipts" in receipt
    assert ".agent-runtime/" in _read(".gitignore")


def test_engineering_reliability_research_is_shared_and_actionable():
    doc = _read(ENGINEERING_PRIORITIES)
    required = (
        "External-source deterministic replay",
        "Typed API contract spine",
        "Reproducible dependency/build/artifact identity",
        "Property-based and mutation testing",
        "Progressive static-typing ratchet",
        "End-to-end observability and SLOs",
        "Repo-specific agent/harness evals",
        "Faster CI without weaker evidence",
        "Machine-enforced architecture boundaries",
        "Supply-chain security ratchet",
        "Versioned SQLite migration ownership",
    )
    for heading in required:
        assert heading in doc
    assert "not product authorization" in doc.lower()
