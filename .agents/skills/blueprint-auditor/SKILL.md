---
name: blueprint-auditor
description: Compare a named blueprint, roadmap or completion contract with live implementation. Use for scope-to-code audits and milestone verification.
---

# Blueprint Auditor

## Objective
Determine where the repo truly stands against its blueprint/spec/roadmap based on the live codebase.

## Scope
Compare the requested scope only. Use reality-check-review for a concrete implementation claim without a blueprint comparison.

## Evidence
- Locate blueprint, spec, roadmap, and strategy documents in the repo first.
- If multiple documents exist, identify the current primary blueprint and explain why.
- Summarize the blueprint's main goals, modules, and milestones.
- Compare blueprint expectations against real live implementation paths.
- Do not credit any feature as complete unless the live path is wired and used.
- Explicitly label each item as complete, partial, mocked, bypassed, dead/stale, or missing.

For authorized repairs, implement and verify the fix; for audits, report findings. Scale the following evidence to the requested scope.

## Report
1. Source-of-truth docs found
2. Blueprint summary
3. Verified implementation status by module
4. Gaps and contradictions
5. Highest-priority next steps
