# League Media Spec

## Scope
Public League Page `League Media` tab only.

This spec defines content-system architecture, data dependencies, and governance.

## Repo-grounded facts (current state)
- Current live data ingestion (`Dynasty Scraper.py`) includes Sleeper teams and rolling trade history.
- Current live payload does not include weekly matchup history, weekly team scores, or historical season outcomes required for robust weekly editorial modules.
- No existing media article store exists in repo runtime paths.
- Blueprint identifies media as a manual-first public domain that needs commissioner-managed storage.

## Purpose
League Media should increase league identity, entertainment, and historical continuity.
It must never become a private optimization tool.

## Core submodules
- Thursday Weekly Preview
- Tuesday Weekly Review
- Matchup of the Week
- Weekly Story Archive
- Optional later modules:
- Power Rankings
- Rivalry of the Week
- Player Spotlight
- Commissioner Notes

## Module specs

### Thursday Weekly Preview
- Purpose: set context for upcoming week.
- Minimum data needed: current standings, upcoming matchups, recent form, roster availability notes.
- Feasibility now: **Partially feasible** (manual write-ups possible; automated matchup context is blocked by missing weekly matchup ingestion in current payload).

### Tuesday Weekly Review
- Purpose: summarize completed week results and narrative outcomes.
- Minimum data needed: completed matchups, weekly team scores, top performances.
- Feasibility now: **Requires manual historical entry** for reliable output.

### Matchup of the Week
- Purpose: spotlight one high-stakes or high-drama matchup.
- Minimum data needed: schedule, standings impact, rivalry context, result outcome.
- Feasibility now: **Partially feasible** (manual selection possible; automated scoring narrative requires missing weekly results data).

### Weekly Story Archive
- Purpose: permanent public index of published stories by season/week.
- Minimum data needed: article metadata + approved content body.
- Feasibility now: **Fully feasible** with a manual file-based store.

### Optional modules (later)
- Power Rankings: requires stable multi-week performance dataset and ranking policy.
- Rivalry of the Week: requires historical head-to-head records.
- Player Spotlight: requires weekly player performance ingestion and editorial context.
- Commissioner Notes: fully manual, immediately feasible.

## Data requirements summary
- Internal league data needed (not fully present today):
- Weekly matchups, weekly team scores, season standings history, playoff outcomes.
- External enrichment inputs (optional):
- NFL injury/news feed, player transaction feed, weather context for featured games.

No external news integration is currently implemented in repo.

## Automation vs commissioner approval
- Draft generation can be automated only for low-risk factual summaries once data is available.
- All public publishing should require commissioner approval/editing before release.
- Final publication should store:
- `approved_by`
- `approved_at_utc`
- `source_refs`

## Recommended content-generation pipeline
- Step 1: ingest and validate weekly league facts.
- Step 2: generate structured draft outline from validated facts.
- Step 3: apply guardrail checks (no private strategy language, no exposed private metrics).
- Step 4: commissioner edits and approves.
- Step 5: publish immutable version to archive.

## Caching/storage/reference strategy

Use repo-local file artifacts first:
- `data/league/manual/media/posts/{season}/week-{week}/{slug}.md`
- `data/league/manual/media/posts/{season}/week-{week}/{slug}.json` (metadata)
- `data/league/manual/media/index.json` (archive index)

Cache published media as static-safe payloads for public endpoint responses.

## Public-safe guardrails
- Prohibited content:
- Trade exploitation advice, opponent weakness targeting, private valuation math, private recommendation logic.
- Allowed content:
- Factual outcomes, neutral narrative analysis, approved commissioner commentary, public records.

## Phase recommendation
- Phase 0: Manual publishing only (Commissioner Notes + Story Archive).
- Phase 1: Semi-structured Preview/Review drafts with manual fact entry.
- Phase 2: Automated factual draft assistance after weekly results ingestion is reliable.
- Phase 3: Optional modules (Power Rankings, Rivalry, Spotlight) after historical backfill and QA gates.

