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
    assert "scripts/agent_os_receipt.py" in hook
    assert "@docs/AGENT_OPERATING_SYSTEM.md" in _read("CLAUDE.md").splitlines()
    assert "Agent OS session receipt" in _read("docs/AGENT_OPERATING_SYSTEM.md")
    assert "Agent-OS-Receipt: <AGENT_OS_LOADED_BLOB_SHA>" in _read("docs/AGENT_OPERATING_SYSTEM.md")


def test_new_skills_have_narrow_non_product_scope():
    traffic = _read(".agents/skills/season-launch-traffic-control/SKILL.md")
    harness = _read(".agents/skills/repo-harness-auditor/SKILL.md")

    assert "Do not use for broad product implementation" in traffic
    assert "Fixed denominator: **30**" in traffic
    assert "Do not use for product feature implementation" in harness
    assert "Never change product methodology" in harness


def test_agent_os_has_bounded_debugging_and_routing_rules():
    doc = _read("docs/AGENT_OPERATING_SYSTEM.md")
    assert "Retry budgets and exit conditions" in doc
    assert "Root-cause debugging" in doc
    assert "Model/effort routing and tool batching" in doc
    assert "Targeted edits over gratuitous rewrites" in doc
    assert "Progress visibility on long runs" in doc


def test_harness_migration_audit_is_evidence_not_authority():
    harness = _read(".agents/skills/repo-harness-auditor/SKILL.md")
    rationale = _read("docs/agent-operating-system/DESIGN_RATIONALE_2026-09-05.md")
    assert "/claude-api prompt-audit" in harness
    assert "evidence, not authority" in harness
    assert "representative baseline task set" in harness
    assert "append-only" in harness
    assert "zodchiii" in rationale


def test_agent_os_graphs_require_real_edges_complete_fanin_and_anchors():
    doc = _read("docs/AGENT_OPERATING_SYSTEM.md")
    assert "Graph construction rules" in doc
    assert "Fake-edge test" in doc
    assert "fan out -> reduce -> verify -> synthesize" in doc
    assert "Hidden edges" in doc
    assert "Fan-in completeness and context safety" in doc
    assert "Anchors" in doc
    assert "When not to graph" in doc


def test_harness_auditor_checks_graph_topology_not_just_prompts():
    harness = _read(".agents/skills/repo-harness-auditor/SKILL.md")
    rationale = _read("docs/agent-operating-system/DESIGN_RATIONALE_2026-09-05.md")
    assert "Graph-orchestration hygiene" in harness
    assert "fan-in counts expected vs received inputs" in harness
    assert "fresh context" in harness
    assert "Anatoli Kopadze" in rationale


def test_agent_os_governs_unattended_loops_without_activating_them():
    doc = _read("docs/AGENT_OPERATING_SYSTEM.md")
    assert "Autonomous-loop safety envelope" in doc
    assert "committed contract" in doc
    assert "local operator overrides" in doc
    assert "Hard runtime limits" in doc
    assert "One execution gateway" in doc
    assert "append-only run receipt" in doc
    assert "preflight -> act -> verify -> guard -> grade -> receipt" in doc
    assert "Emergency halt" in doc
    assert "report-only" in doc
    assert "Activation gate" in doc
    assert "design policy, not activation" in doc


def test_harness_auditor_checks_autonomous_runner_controls():
    harness = _read(".agents/skills/repo-harness-auditor/SKILL.md")
    rationale = _read("docs/agent-operating-system/DESIGN_RATIONALE_2026-09-05.md")
    assert "Autonomous-runner hygiene" in harness
    assert "fail-closed external halt sentinel" in harness
    assert "report-only, assisted, and autonomous modes" in harness
    assert "PolyDAO" in rationale
    assert "2096128417108287566" in rationale
