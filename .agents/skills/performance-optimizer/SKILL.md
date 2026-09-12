---
name: performance-optimizer
description: Diagnose and fix measured load-time or responsiveness bottlenecks. Use for performance work, not every fetch or frontend edit.
---

# Performance Optimizer

## Objective
Make the app materially faster without degrading correctness.

## Scope
Measure the affected route or operation; trace initial page load only when that is the bottleneck. Preserve value correctness on affected paths.

## Evidence
- Trace and measure the affected operation from input to usable result.
- Identify blocking operations, repeated work, oversized payloads, unnecessary DOM work, duplicated calculations, and avoidable waits.
- Separate findings by frontend, backend, network, caching, and data-shaping layers.
- Prefer the smallest set of changes with the biggest speed impact.
- Verify key ranking and value logic remains correct after changes.

For authorized repairs, implement and verify the fix; for audits, report findings. Scale the following evidence to the requested scope.

## Report
1. Bottlenecks found
2. Why each bottleneck matters
3. Exact files and code paths to change
4. Implementation plan in priority order
5. Validation checklist
