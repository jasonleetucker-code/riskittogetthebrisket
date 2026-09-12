---
name: reality-check-review
description: Independently review a concrete implementation or completion claim for unsupported evidence and regressions. Use for review, not routine implementation.
---

# Reality Check Review

## Objective
Challenge assumptions and kill false confidence.

## Scope
Review the supplied claim or change. Use blueprint-auditor for a roadmap-wide comparison; do not expand a bounded review into a whole-repo audit.

## Evidence
- Look for claims the code does not actually support.
- Look for dead code, bypassed code, stale comments, fake completion, hidden regressions, and untested edge cases.
- Be blunt and specific.
- Prefer verified negatives over optimistic guesses.

For authorized repairs, implement and verify the fix; for audits, report findings. Scale the following evidence to the requested scope.

## Report
1. False assumptions
2. Unsupported claims
3. Hidden risks
4. What is actually true
