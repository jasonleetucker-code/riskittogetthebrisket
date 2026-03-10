---
name: blueprint-auditor
description: Use when the task is to compare the actual repo against blueprint, roadmap, spec, or implementation-plan documents. Trigger for implementation audits, progress reports, milestone verification, missing features, half-built systems, dead code, and wiring checks.
---

# Blueprint Auditor

## Objective
Determine where the repo truly stands against its blueprint/spec/roadmap based on the live codebase.

## Mandatory Behavior
- Locate blueprint, spec, roadmap, and strategy documents in the repo first.
- If multiple documents exist, identify the current primary blueprint and explain why.
- Summarize the blueprint's main goals, modules, and milestones.
- Compare blueprint expectations against real live implementation paths.
- Do not credit any feature as complete unless the live path is wired and used.
- Explicitly label each item as complete, partial, mocked, bypassed, dead/stale, or missing.

## Output Format
1. Source-of-truth docs found
2. Blueprint summary
3. Verified implementation status by module
4. Gaps and contradictions
5. Highest-priority next steps
