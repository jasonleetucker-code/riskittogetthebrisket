from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO / path).read_text(encoding="utf-8")


def test_agent_operating_system_is_reachable_from_both_front_doors():
    target = "docs/AGENT_OPERATING_SYSTEM.md"
    assert target in _read("CLAUDE.md")
    assert target in _read("AGENTS.md")
    assert target in _read("ASSISTANT_COORDINATION.md")


def test_operating_system_cannot_authorize_product_scope():
    doc = _read("docs/AGENT_OPERATING_SYSTEM.md")
    assert "**Product authority:** **none.**" in doc
    assert "docs/EXECUTION_PLAN.md" in doc
    assert "ONE CONCEPT / ONE CANONICAL OWNER" in doc
    assert "missing != zero" in doc
    assert "stale != current" in doc


def test_session_start_router_mechanically_counts_launch_rows():
    hook = _read(".claude/health-check.sh")
    assert "=== AGENT ROUTER ===" in hook
    assert "WEEK_1_LAUNCH_CONTRACT.md" in hook
    assert "LAUNCH_VERIFIED" in hook
    assert "literal VERIFIED" in hook
    assert "Keep V1 closed" in hook


def test_new_skills_have_narrow_non_product_scope():
    traffic = _read(".agents/skills/season-launch-traffic-control/SKILL.md")
    harness = _read(".agents/skills/repo-harness-auditor/SKILL.md")

    assert "Do not use for broad product implementation" in traffic
    assert "Fixed denominator: **30**" in traffic
    assert "Do not use for product feature implementation" in harness
    assert "Never change product methodology" in harness
