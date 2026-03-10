---
name: reality-check-review
description: Use when the task needs ruthless validation of claims, architecture, implementation status, edge cases, contradictions, dead code, or overstatement of completeness.
---

# Reality Check Review

## Objective
Challenge assumptions and kill false confidence.

## Mandatory Behavior
- Look for claims the code does not actually support.
- Look for dead code, bypassed code, stale comments, fake completion, hidden regressions, and untested edge cases.
- Be blunt and specific.
- Prefer verified negatives over optimistic guesses.

## Output Format
1. False assumptions
2. Unsupported claims
3. Hidden risks
4. What is actually true
