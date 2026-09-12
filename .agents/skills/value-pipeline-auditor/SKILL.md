---
name: value-pipeline-auditor
description: Audit or change canonical dynasty normalization, blending, calibration and value correctness. Use for value-pipeline work, not presentation-only ranking edits.
---

# Value Pipeline Auditor

## Objective
Verify and improve the real live player value pipeline.

## Scope
Preserve the existing end-to-end checks for value/ranking changes. Acquisition incidents without a valuation change belong to scraper-ops.

## Evidence
- Trace the active value pipeline end to end.
- Verify source ingestion, normalization, canonical transforms, weighting, blending, calibration, and final UI rendering.
- Check that displayed site/source values match canonical transformed values where intended.
- Check that top-ranked assets calibrate correctly if the architecture requires it.
- Check that rookie-only ranks are not incorrectly treated as full-universe ranks.
- Check IDP paths separately from offensive paths.
- Flag dead helpers, stale transforms, parallel pipelines, and mismatches between comments and live behavior.

For authorized repairs, implement and verify the fix; for audits, report findings. Scale the following evidence to the requested scope.

## Report
1. Active pipeline map
2. Verified flaws
3. Rookie and IDP-specific findings
4. Exact code changes needed
5. Validation steps after change
