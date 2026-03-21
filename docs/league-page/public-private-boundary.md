# Public vs Private Boundary Spec

## Scope
Defines hard boundaries for a public League Page.

## Repo-grounded facts (current state)
- `/league` is publicly reachable in `server.py` and explicitly described as available without private workspace login.
- `/app`, `/rankings`, and `/trade` are auth-gated in `server.py`.
- `/api/data` is currently not auth-gated and returns broad runtime payloads (full/runtime/startup views).
- Live payload includes private valuation internals and diagnostics (for example: `valueResolverDiagnostics`, `empiricalLAM`, `rawMarketDiagnostics`, many `_formatFit*` and `_leagueAdjusted` style fields under players).
- Next `frontend/app/login/page.jsx` is a localStorage demo flow, not a backend security boundary.

## Public boundary principle
Public League Page must be allowlist-driven, not sanitize-after-the-fact from private payloads.

## Must remain private (never public)
- Proprietary valuation internals and formulas:
- Per-player internal adjustment fields (`_formatFit*`, `_lam*`, `_rawComposite`, `_leagueAdjusted`, etc.).
- `valueResolverDiagnostics`, `valueAuthority` internals beyond high-level non-sensitive summaries.
- Source blending, calibration, and weighting internals used for private edge.
- Trade optimization internals:
- Trade package multipliers, sensitivity knobs, counter-trade logic, and recommendation logic.
- Any opponent-facing optimization output (targets, exploit lists, sendability scoring).
- Operational and sensitive fields:
- Auth/session internals, admin-only settings, scrape diagnostic internals not intended for public audiences.

## Allowed public domains
- League identity: name, season, franchise identities.
- Historical outcomes intended for public view: standings, championships, awards, records, draft history, completed trades.
- Constitution text and amendment history.
- Money tab outputs intended for transparency (dues/winnings/net/ROI), once manually curated and verified.
- League Media articles after commissioner approval.

## Required contract separation

Create a dedicated public contract endpoint (example shape):
- `GET /api/public/league/{league_id}`
- `GET /api/public/league/{league_id}/standings`
- `GET /api/public/league/{league_id}/franchises`
- `GET /api/public/league/{league_id}/awards`
- `GET /api/public/league/{league_id}/money`
- `GET /api/public/league/{league_id}/constitution`
- `GET /api/public/league/{league_id}/media`

Do not power public League Page from `/api/data` directly.

## Data filtering rules
- Positive allowlist for public fields only.
- Explicit denylist guardrails for known private families:
- Top-level: `settings`, `empiricalLAM`, `rawMarketDiagnostics`, `coverageAudit`, private diagnostics blocks.
- Player-level: any key prefixed with `_`, plus private valuation/strategy keys.
- Reject payloads that accidentally include denied fields.

## Governance and QA
- Add contract tests that fail if private keys appear in public endpoints.
- Add snapshot tests for each public module payload.
- Require commissioner/content-owner signoff for first publication of each module.

## Status labels (today)
- Public league route availability: **Complete (shell + baseline public data contract)**.
- Public/private separation by contract: **Partial** (dedicated `/api/league/public` exists, but `/api/data` remains broad/public).
- Private route auth gate for main workspace: **Complete**.
