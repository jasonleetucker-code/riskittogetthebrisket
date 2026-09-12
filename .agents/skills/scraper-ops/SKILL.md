---
name: scraper-ops
description: Diagnose or repair source acquisition, refresh failures and stale ingestion output. Use for ingestion reliability, not general Git merges or account login.
---

# Scraper Ops

## Objective
Stabilize and verify the data ingestion pipeline.

## Scope
Keep acquisition reliability separate from canonical value methodology. A blending/calibration change belongs to value-pipeline-auditor; source refresh does not authorize it.

## Evidence
- Identify the current scrape/source flow from trigger to stored output to frontend consumption.
- Verify polling, retries, stale-data behavior, snapshot handling, and error surfaces.
- Prefer removing brittle steps when a simpler reliable path exists.
- Do not assume a scrape succeeded because a process ran; verify output artifacts and downstream consumption.

For authorized repairs, implement and verify the fix; for audits, report findings. Scale the following evidence to the requested scope.

## Report
1. Current ingestion flow
2. Failure points and fragility points
3. Reliability fixes
4. Exact files to change
5. Verification checklist
