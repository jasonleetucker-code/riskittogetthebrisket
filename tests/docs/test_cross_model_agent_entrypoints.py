from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO / path).read_text(encoding="utf-8")


def test_universal_entrypoint_routes_every_model_to_same_authorities():
    entry = _read("AI_INSTRUCTIONS.md")
    for target in (
        "docs/AGENT_OPERATING_SYSTEM.md",
        "docs/EXECUTION_PLAN.md",
        "docs/WORK_CLAIMS.md",
        "ASSISTANT_COORDINATION.md",
        "CLAUDE.md",
        "docs/engineering/ENGINEERING_RELIABILITY_PRIORITIES_2026-09-06.md",
    ):
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
    assert "Cross-model parity rule" in os_doc
    assert "adapters, not authorities" in os_doc
    assert (
        "No correctness, architecture, safety, verification, product, methodology, "
        "or engineering-process rule" in os_doc
    )
    assert "Provider-specific files are adapters only" in entry
    assert "Do not make the human owner remember which model knows which rule." in entry


def test_startup_preflight_is_shared_not_claude_owned():
    shared = _read("scripts/agent_session_start.sh")
    claude_hook = _read(".claude/health-check.sh")

    assert "Model-neutral session-start health check" in shared
    assert "AI_INSTRUCTIONS.md" in shared
    assert "Data Freshness" in shared
    assert "Test Collection" in shared
    assert "Git Status" in shared
    assert "Scraper Syntax" in shared
    assert "exec bash scripts/agent_session_start.sh" in claude_hook

    assert ".agent-runtime/session-receipts" in _read("scripts/agent_os_receipt.py")
    assert ".agent-runtime/" in _read(".gitignore")


def test_engineering_reliability_research_is_shared_and_actionable():
    doc = _read(
        "docs/engineering/ENGINEERING_RELIABILITY_PRIORITIES_2026-09-06.md"
    )
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
