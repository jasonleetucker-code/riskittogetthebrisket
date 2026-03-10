---
name: performance-optimizer
description: Use when the task is to speed up the app, reduce load time, remove blocking work, optimize frontend/backend interactions, improve time-to-interactive, or reduce repeated calculations and fetches.
---

# Performance Optimizer

## Objective
Make the app materially faster without degrading correctness.

## Mandatory Behavior
- Trace the initial page-load path from first render to usable UI.
- Identify blocking operations, repeated work, oversized payloads, unnecessary DOM work, duplicated calculations, and avoidable waits.
- Separate findings by frontend, backend, network, caching, and data-shaping layers.
- Prefer the smallest set of changes with the biggest speed impact.
- Verify key ranking and value logic remains correct after changes.

## Output Format
1. Bottlenecks found
2. Why each bottleneck matters
3. Exact files and code paths to change
4. Implementation plan in priority order
5. Validation checklist
