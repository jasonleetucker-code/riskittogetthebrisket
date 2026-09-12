# Harness progressive-disclosure audit — 2026-09-11

Owner authorization: “Do it” in response to the proposed audit and simplification
of this repository's agent instructions. Scope is instructions, skills, startup
diagnostics and their checks; product methodology and production behavior are excluded.

Source read on 2026-09-11 (America/New_York):
https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra
Shared post: https://x.com/openaidevs/status/2098480213244117065
Adopted: narrow triggers, conditional references, proportional validation and
explicit completion. Rejected: treating vendor claims as proof of better local
outcomes, deleting domain safeguards, or granting new execution permissions.

## Findings and changes

| Classification | Finding | Disposition |
|---|---|---|
| Duplicate | Entry adapters repeat shared policy and mandatory reading lists. | Shared entry router; provider adapters point to it. |
| Partial | Agent OS describes progressive disclosure but embeds graph, runtime and unattended-runner manuals. | Move those policies verbatim to linked conditional references; retain their entry anchors. |
| Partial | Harness auditor loads all specialist review modes on every invocation. | Keep common audit guidance; link four mode-specific references. |
| Stale | Coordination repeats an August campaign assignment as current routing. | Use the execution plan's current assignments. |
| Historical workaround | Design skill claims default output is “60% done” and mandates an eight-part report. | Remove unsupported estimate and fixed ceremony; retain concrete design and rendered-UI criteria. |
| Overbroad | Scraper trigger includes all merge issues/login removal; review and blueprint triggers overlap. | Narrow acquisition, claim-review and scope-comparison boundaries; sharpen all eight descriptions. |
| Partial | Startup always collects all tests and inspects scraper syntax/data. | Default receipt/router/Git state; opt-in diagnostics preserve the existing checks. |
| Complete (preserved) | Domain truth, source separation, privacy, provenance and protected integration rules. | Technical runbook and consequence boundaries retained. |

## Harness map and limits

Provider adapter -> AI_INSTRUCTIONS.md -> core Agent OS + execution authority.
Coordination owns branches/integration; CLAUDE.md remains the universal technical
reference. Skills route by task; hooks invoke the shared startup script.

The full CLAUDE.md is still automatically loaded by Claude Code. Its 2,500-line
technical body has many semantic references; this pass changes its startup
wording but does not relocate domain sections. On other providers the entrypoint
now explicitly requests relevant sections. Exact loaded tokens depend on runtime.
No skill was proved dead; all eight retain distinct workflows. No new scheduler,
paid inference, hook lifecycle or product engine was introduced.

Stop causality: the old AI_INSTRUCTIONS.md “Read order for material work,” Agent
OS session-start list and harness skill “Read first” duplicate reading demands.
The design skill's “Mandatory Sequence (Always Follow)” can turn a small visual
repair into a large report. These are instruction findings, not measured model
behavior. The permission needed in this session was the filesystem sandbox for
an isolated worktree, not a skill-imposed review stop.

## Verification

Verified 2026-09-12:

- `python -m pytest tests/docs tests/deploy/test_health_check_stale_ref_guard.py -q`: 91 passed.
- `bash scripts/format_python_changes.sh`: Ruff 0.6.9, 1,426 files formatted/checked; lint passed.
- `python scripts/check_planning_integrity.py`: OK.
- Skill Creator `quick_validate.py`: all eight repo skills valid.
- Real default startup: receipt, literal launch tally and Git state completed; no product diagnostics invoked.
- Executable disposable-repository tests: default mode, diagnostic mode, collection failure continuation and invalid arguments.
- All three extracted Agent OS policy sections match the base verbatim.
- `git diff --check`: passed.

The first new-fixture run had three failures because it lacked a Git repository;
the fixture now initializes a disposable repo. Existing docs/freshness checks passed.
No model behavior or production performance benchmark was run.

| Entry | Before words | After words | Reduction |
|---|---:|---:|---:|
| AI_INSTRUCTIONS.md | 977 | 711 | 27% |
| Agent OS core | 6516 | 4794 | 26% |
| Harness auditor SKILL.md | 2008 | 869 | 57% |
| Design director SKILL.md | 670 | 187 | 72% |

Conditional references remain available and consume context when loaded. These
counts exclude the unchanged technical runbook and runtime-injected instructions.
The OneDrive backup and active checkout's pre-existing scraper data were not edited.

Implementation: FEATURE_GREEN / READY_FOR_INTEGRATION. Protected integration is
separate from local verification. Agent-OS-Receipt: 2289274e7c5750c9bc87bb25fc2dd789d4d23843.
Measure text footprint against base 7631e233a; this is a context proxy, not a
claim of measured model speed, cost or success-rate improvement.

## Exact files touched

- `.agents/skills/blueprint-auditor/SKILL.md`
- `.agents/skills/design-taste-director/SKILL.md`
- `.agents/skills/performance-optimizer/SKILL.md`
- `.agents/skills/reality-check-review/SKILL.md`
- `.agents/skills/repo-harness-auditor/SKILL.md`
- `.agents/skills/repo-harness-auditor/references/external-guidance.md`
- `.agents/skills/repo-harness-auditor/references/graphs.md`
- `.agents/skills/repo-harness-auditor/references/model-migration.md`
- `.agents/skills/repo-harness-auditor/references/runtime-and-runners.md`
- `.agents/skills/scraper-ops/SKILL.md`
- `.agents/skills/season-launch-traffic-control/SKILL.md`
- `.agents/skills/value-pipeline-auditor/SKILL.md`
- `.github/copilot-instructions.md`
- `AGENTS.md`
- `AI_INSTRUCTIONS.md`
- `ASSISTANT_COORDINATION.md`
- `CLAUDE.md`
- `GEMINI.md`
- `docs/AGENT_OPERATING_SYSTEM.md`
- `docs/EXECUTION_PLAN.md`
- `docs/OWNER_REQUESTED_TODO.md`
- `docs/WORK_CLAIMS.md`
- `docs/agent-operating-system/AUTONOMOUS_RUNNERS.md`
- `docs/agent-operating-system/GRAPH_WORKFLOWS.md`
- `docs/agent-operating-system/HARNESS_DISCLOSURE_AUDIT_2026-09-11.md`
- `docs/agent-operating-system/RUNTIME_CONTROLS.md`
- `scripts/agent_session_start.sh`
- `tests/docs/test_agent_operating_system.py`
- `tests/docs/test_harness_disclosure.py`
