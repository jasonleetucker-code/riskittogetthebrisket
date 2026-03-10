---
name: value-pipeline-auditor
description: Use when the task involves dynasty values, ranking normalization, 0-9999 calibration, source blending, rookie handling, IDP handling, canonical site values, or final value correctness.
---

# Value Pipeline Auditor

## Objective
Verify and improve the real live player value pipeline.

## Mandatory Behavior
- Trace the active value pipeline end to end.
- Verify source ingestion, normalization, canonical transforms, weighting, blending, calibration, and final UI rendering.
- Check that displayed site/source values match canonical transformed values where intended.
- Check that top-ranked assets calibrate correctly if the architecture requires it.
- Check that rookie-only ranks are not incorrectly treated as full-universe ranks.
- Check IDP paths separately from offensive paths.
- Flag dead helpers, stale transforms, parallel pipelines, and mismatches between comments and live behavior.

## Output Format
1. Active pipeline map
2. Verified flaws
3. Rookie and IDP-specific findings
4. Exact code changes needed
5. Validation steps after change
