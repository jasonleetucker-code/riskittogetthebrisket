# League Page Discovery + Scaffold Package

## Purpose
This folder contains the League Page planning/spec package and now tracks the
implemented public League scaffold in the live repo.

## Current status snapshot (repo-grounded)
- `complete`: runtime architecture discovery and data-path tracing.
- `complete`: public League route scaffold is live (`/league` + top-level section routes).
- `complete`: landing-page League choice now routes to public League HQ.
- `complete`: route-level public/private split (League is public; Jason workspace stays auth-gated).
- `partial`: dedicated public-safe API exists (`/api/league/public`) but only includes
  baseline league context summaries, not full historical modules.
- `partial`: historical data coverage for standings/records/awards/history remains incomplete.

## Live execution path (verified)
1. `GET /` serves `Static/landing.html`.
2. Landing "League" action navigates to `GET /league`.
3. `server.py::serve_league_entry` serves `Static/league/index.html` (public, no auth).
4. `Static/league/league.js` client-routes top-level League tabs under `/league/*`.
5. UI fetches `GET /api/league/public` for public-safe summary data.

## Public League routes currently implemented
- `/league`
- `/league/standings`
- `/league/franchises`
- `/league/awards`
- `/league/draft`
- `/league/trades`
- `/league/records`
- `/league/money`
- `/league/constitution`
- `/league/history`
- `/league/league-media`

Note: deeper nested paths such as `/league/franchises/{id}` resolve via the same
public shell and currently render scaffold detail states.

## Auth boundary snapshot
- Public:
  - `/`
  - `/league`
  - `/league/{league_path:path}`
  - `/api/league/public`
- Auth-gated:
  - `/app`
  - `/rankings`
  - `/trade`
  - `/index.html`
  - `/Static/index.html`

## Public-safe API contract scope (`/api/league/public`)
- Included (public-safe summary only):
  - league identity summary
  - team directory summary (name, roster id, counts)
  - recent trade window summary (timestamp/week/side counts)
  - module status notes
- Excluded by design:
  - private valuation internals
  - trade-calculator logic/state
  - proprietary ranking diagnostics

## Core discovery/spec docs in this folder
- `repo-architecture-findings.md`
- `data-availability-matrix.md`
- `historical-gap-audit.md`
- `data-model.md`
- `feature-blueprint.md`
- `awards-methodology.md`
- `franchise-page-spec.md`
- `trades-methodology.md`
- `draft-methodology.md`
- `money-spec.md`
- `constitution-spec.md`
- `public-private-boundary.md`
- `league-media-spec.md`
- `phased-roadmap.md`

## Skills/tools used explicitly
- `blueprint-auditor`
- `reality-check-review`
- `scraper-ops`

## Maintenance rules
- Keep claims tied to live code paths.
- Use explicit status tags: `complete`, `partial`, `missing`, `blocked`, `manual-only`.
- Never treat inferred history as factual history.
- Keep League outputs public-safe; do not expose private calculator internals.
