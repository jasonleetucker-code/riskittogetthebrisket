# Runtime Route Authority (Verified)

Last verified: 2026-03-20

This file maps route authority to live `server.py` handlers.
It is based on runtime code paths, not folder presence assumptions.

## Critical Route Map

| Route | Access | Runtime authority | Status |
| --- | --- | --- | --- |
| `/` | public | `serve_landing` -> `Static/landing.html` (or `static/landing.html`) | complete |
| `/league` | public | `serve_league_entry` -> `Static/league/index.html` when available | complete |
| `/league/{league_path:path}` | public | same handler as `/league`; never proxied to Next | complete |
| `/league/standings` | public | concrete top-level alias of `/league/{league_path:path}` | complete |
| `/league/franchises` | public | concrete top-level alias of `/league/{league_path:path}` | complete |
| `/league/awards` | public | concrete top-level alias of `/league/{league_path:path}` | complete |
| `/league/draft` | public | concrete top-level alias of `/league/{league_path:path}` | complete |
| `/league/trades` | public | concrete top-level alias of `/league/{league_path:path}` | complete |
| `/league/records` | public | concrete top-level alias of `/league/{league_path:path}` | complete |
| `/league/money` | public | concrete top-level alias of `/league/{league_path:path}` | complete |
| `/league/constitution` | public | concrete top-level alias of `/league/{league_path:path}` | complete |
| `/league/history` | public | concrete top-level alias of `/league/{league_path:path}` | complete |
| `/league/league-media` | public | concrete top-level alias of `/league/{league_path:path}` | complete |
| `/app` | auth-gated | `serve_dashboard` -> `_serve_app_shell("/")` | complete |
| `/rankings` | auth-gated | `serve_rankings` -> `_serve_app_shell("/rankings")` | complete |
| `/trade` | auth-gated | `serve_trade` -> `_serve_app_shell("/trade")` | complete |
| `/calculator` | auth-gated alias | `serve_calculator` -> redirect to `/trade` | complete |

## League Shell Rules

- Full League shell experience depends on tracked static artifacts:
  - `Static/league/index.html`
  - `Static/league/league.css`
  - `Static/league/league.js`
- If those files are missing at runtime, `/league` and `/league/*` do **not** return raw `500`.
- Missing-artifact behavior is explicit fallback authority:
  - `public-league-inline-fallback-shell`
- League routes remain public in fallback mode (no Jason auth wall, no Next proxy).

## Runtime Introspection

- Route map endpoint: `GET /api/runtime/route-authority`
- Response headers on route responses:
  - `X-Route-Id`
  - `X-Route-Authority`
  - `X-Frontend-Runtime-Configured`
  - `X-Frontend-Runtime-Active`
- Deploy readiness block:
  - `deployReadiness.leagueShell.ok`
  - `deployReadiness.leagueShell.entryExists`
  - `deployReadiness.leagueShell.cssExists`
  - `deployReadiness.leagueShell.jsExists`

## Private Auth Guardrail

- Private route login requires either:
  - `JASON_LOGIN_PASSWORD`, or
  - `JASON_LOGIN_PASSWORD_FILE` (file-based secret fallback).
- When both are missing, `/api/auth/login` returns `503` with a configuration error.
- `/app`, `/rankings`, `/trade`, and `/calculator` remain auth-gated and will continue redirecting unauthenticated users.
- `/calculator` is a compatibility alias only and redirects authenticated users to `/trade`.

## FRONTEND_RUNTIME Behavior (Operator Truth)

- `FRONTEND_RUNTIME` affects private shell resolution for:
  - `/app`
  - `/rankings`
  - `/trade`
- `FRONTEND_RUNTIME` does **not** transfer authority for:
  - `/`
  - `/league`
  - `/league/{league_path:path}`
  - `/league` top-level aliases (`/league/standings`, `/league/franchises`, etc.)

Mode details from runtime payload (`privateShellResolutionOrder`):
- `static`: private shell resolves from static `index.html` candidates only.
- `auto`: tries Next proxy first, then explicit static fallback.
- `next`: Next proxy only, no static fallback when unreachable (returns 503 for private shell routes).

## Deploy/Release Guardrail

- `deploy/verify-deploy.sh` now checks `/api/runtime/route-authority`.
- By default (`STRICT_LEAGUE_SHELL_READINESS=true`), deploy verification fails if League shell assets are not fully ready.
- In strict mode, deploy verification also fails if required League shell artifacts exist locally but are not tracked in git:
  - `Static/league/index.html`
  - `Static/league/league.css`
  - `Static/league/league.js`
- CI deploy validation (`.github/workflows/deploy.yml`) enforces the same tracked-artifact rule before remote deploy starts.
- This prevents silently promoting a deployment that would run the League fallback unexpectedly.

## Non-authoritative Artifacts

- `frontend/.next` alone is not route authority.
- `frontend/tsconfig.tsbuildinfo` is generated cache output and never route authority.
- `frontend/app/league/*` pages are not live authority unless backend routing is explicitly switched to Next.
- Current repo intentionally keeps `frontend/app/league/*` route files absent to avoid false ownership assumptions while League is FastAPI static-owned.
- League routes are intentionally owned by FastAPI static/fallback handling.
