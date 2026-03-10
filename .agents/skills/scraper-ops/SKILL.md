---
name: scraper-ops
description: Use when the task involves scraping failures, source ingestion, polling, stale snapshots, merge issues, login removal, source refresh, or data update reliability.
---

# Scraper Ops

## Objective
Stabilize and verify the data ingestion pipeline.

## Mandatory Behavior
- Identify the current scrape/source flow from trigger to stored output to frontend consumption.
- Verify polling, retries, stale-data behavior, snapshot handling, and error surfaces.
- Prefer removing brittle steps when a simpler reliable path exists.
- Do not assume a scrape succeeded because a process ran; verify output artifacts and downstream consumption.

## Output Format
1. Current ingestion flow
2. Failure points and fragility points
3. Reliability fixes
4. Exact files to change
5. Verification checklist
