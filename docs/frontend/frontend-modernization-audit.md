# Frontend Modernization Audit (Repo-Grounded)

Last updated: 2026-03-19

## Scope
This audit evaluates the **real frontend implementation path** for speed, UX quality, consistency, maintainability, and migration readiness.

## Runtime Truth (Verified)
- `/` is served by backend static landing shell in `server.py` (`serve_landing`).
- `/league` and `/league/*` are served by backend static League shell in `server.py` (`serve_league_entry`).
- `/app`, `/rankings`, `/trade` are auth-gated and served via backend app-shell resolver in `server.py` (`_serve_app_shell`).
- Next exists as a migration runtime option, but is not currently the authoritative path by default.

Evidence:
- `server.py` (`_resolve_frontend_path`, `serve_landing`, `serve_league_entry`, `_serve_app_shell`, auth-gated route handlers)
- `docs/RUNTIME_ROUTE_AUTHORITY.md`

## Current Frontend Stack

### 1) Live private app shell (authoritative today)
- Static HTML shell: `Static/index.html`
- Runtime JS modules:
  - `Static/js/runtime/00-core-shell.js`
  - `Static/js/runtime/10-rankings-and-picks.js`
  - `Static/js/runtime/20-data-and-calculator.js`
  - `Static/js/runtime/30-more-surfaces.js`
  - `Static/js/runtime/40-runtime-features.js`
  - `Static/js/runtime/50-bootstrap.js`
- Large in-browser state and DOM mutation model.

### 2) Live public surfaces (authoritative today)
- Landing: `Static/landing.html`
- League shell: `Static/league/index.html`, `Static/league/league.css`, `Static/league/league.js`

### 3) Next migration shell (non-authoritative by default)
- `frontend/app/layout.jsx`
- `frontend/app/page.jsx`
- `frontend/app/rankings/page.jsx`
- `frontend/app/trade/page.jsx`
- `frontend/app/api/dynasty-data/route.js`
- `frontend/lib/dynasty-source.js`, `frontend/lib/dynasty-data-server.js`, `frontend/lib/dynasty-data.js`

## Surface-by-Surface Implementation State

| Surface | Status | Notes |
| --- | --- | --- |
| Landing page | `implemented` | Public static shell with League/Jason entry split. |
| League public routes | `implemented` | Public static league shell + route aliases; JS-driven per-route page modules are still content-stub heavy. |
| Private app shell | `implemented` | Feature-rich but monolithic static runtime with heavy inline style/markup and broad global JS. |
| Rankings UX | `implemented` | Deep functionality and parity checks exist; architecture remains tightly coupled to global runtime state. |
| Trade calculator UX | `implemented` | Strong feature depth including multi-side flow; still DOM-heavy and hard to maintain. |
| Suggestions workflows | `partial` | Present with heuristics and controls; quality depends on evolving model assumptions. |
| Next rankings/trade pages | `partial` | Data-backed, but reduced functionality versus live static runtime. |
| Next login | `scaffolded` | Client-only demo auth behavior; not runtime auth authority. |

## Biggest Frontend Weaknesses

1. Mixed runtime ownership and migration overlap
- Live authority is static + backend routes while Next contains parallel UI surfaces.
- This increases cognitive load, implementation drift risk, and duplicated styling/behavior.

2. Monolithic private shell architecture
- `Static/index.html` is very large and carries high coupling between layout, style, and runtime logic.
- Runtime modules are sizeable and global-state-centric, making targeted change riskier.

3. Information architecture inconsistency
- Public landing/League has a separate visual language from private app runtime.
- Navigation, microcopy, and state feedback are not yet systematized across all surfaces.

4. Mobile complexity burden
- Mobile support exists and is substantial, but implemented via many overrides, mode branches, and duplicated control pathways.
- Harder to evolve without regressions.

5. Perceived-performance pressure points
- Initial private app shell ships very large HTML/CSS + heavy runtime JS execution.
- Many rich tables/panels and broad DOM updates can create expensive render paths.

## Performance Findings

### Observed Bottlenecks
- Heavy static shell payload + large runtime script set on private app surface.
- Global listeners and frequent rebuild logic in key workflows.
- Multiple rich tables/cards that rely on large in-page DOM operations.

### Foundational Improvements Implemented in this pass
1. Runtime boot event optimization (`Static/js/runtime/50-bootstrap.js`)
- Added debounced global search rendering.
- Added debounced resize handling with `requestAnimationFrame` handoff.
- Replaced unconditional status polling with visibility-aware polling.

2. Static shell loading polish (`Static/index.html`)
- Added `fonts.gstatic.com` preconnect.
- Marked runtime scripts as `defer` while preserving order.

These changes are low-risk and reduce background churn and avoidable UI work without changing value logic.

## UX/Design Quality Assessment

### What is strong
- Dense, power-user-focused workflows exist.
- Data depth and controls are already meaningful (not toy-level UI).
- League/public boundary and route authority are explicit in backend routing.

### What feels dated or inconsistent
- Private shell: high density + broad inline style usage creates a patched-together feel.
- Next shell: cleaner but currently less feature-complete and visually not yet matching premium production expectations.
- Typography and hierarchy are inconsistent across surfaces.

## Keep / Refactor / Rebuild / Remove

### Keep
- Backend route authority and auth gating model.
- Current static runtime behavior as production-safe baseline during migration.
- Existing E2E parity/smoke strategy and route authority checks.

### Refactor
- Private shell runtime modules toward clearer feature boundaries and shared formatting/helpers.
- Mobile control pathways to reduce duplicate logic branches.
- Shared tokens/interaction primitives to tighten visual consistency.

### Rebuild (progressively)
- Next private surfaces (`/rankings`, `/trade`) to reach feature parity with static runtime.
- Unified layout/navigation/state-feedback components with explicit design system rules.

### Remove (when parity gates pass)
- Static private-shell ownership for `/app`, `/rankings`, `/trade` only after Next parity + regression guardrails are proven.

## Modernization Readiness Summary

- Runtime authority clarity: `good`
- Product functionality depth: `good`
- Architectural maintainability: `needs improvement`
- Design-system maturity: `needs improvement`
- Migration risk posture: `manageable with strict parity gates`

Bottom line: the right move is **progressive modernization**, not a hard rewrite.
