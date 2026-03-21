# Frontend Target Architecture (Modernization Path)

Last updated: 2026-03-19

## 1) Architecture Decision
Use a **progressive consolidation model**:
- Keep current backend route authority stable.
- Modernize private product surfaces through Next as the target UI runtime.
- Preserve static public League shell until League migration is intentionally executed.

This avoids a risky rewrite while still moving toward a cleaner, faster, maintainable frontend.

## 2) Target Runtime Ownership

### Current authoritative model (must remain true during transition)
- Public routes: backend static
  - `/`
  - `/league/*`
- Private routes: backend auth-gated shell
  - `/app`
  - `/rankings`
  - `/trade`

### Target private UI authority (phase-gated)
- Next should become primary renderer for private surfaces **only when parity is proven**.
- Backend remains authentication and API authority.

## 3) Frontend Technology Direction

### Keep
- Next App Router for migration UI
- Existing backend APIs and data contract
- Playwright smoke/parity verification approach

### Introduce/standardize (incrementally)
- Shared design-token layer (colors/typography/spacing/state)
- Shared table primitives for rankings/trade lists
- Shared data formatting helpers (numbers, badges, source chips, stale/fresh markers)
- Shared loading/empty/error state primitives

### Avoid
- Full rewrite of all surfaces at once
- Parallel competing formulas in UI
- New heavy libraries before clear need

## 4) Data + Rendering Authority

Single truth model for private surfaces:
- Backend computes authoritative values and source coverage.
- UI renders backend-provided values; no alternative ranking formula path in client.
- UI parity checks remain mandatory for rankings/trade display integrity.

## 5) Migration Contract for Private Surfaces

A route can migrate from static private shell to Next only after all are true:
1. Functional parity with live static flow
2. Mobile parity at phone + tablet breakpoints
3. No auth boundary regressions
4. Parity tests show zero critical value/render mismatches
5. Smoke suite passes for desktop + mobile + tablet

## 6) Component-System Direction

Build toward reusable sections:
- `AppShell`: header/nav/runtime markers
- `MetricTiles`: KPI summaries
- `SourceCoverageStrip`: source health + freshness chips
- `RankingsTable` + `RankingsCards`
- `TradeWorkspace` + side asset lists + summary rail
- Shared `LoadingState`, `EmptyState`, `ErrorState`

## 7) Performance Direction

### Baseline strategy
- Keep expensive operations off critical first paint.
- Debounce high-frequency UI handlers.
- Defer non-critical hydration/rendering.
- Prefer server-shaped payloads over client recompute.

### Budget intent (private surfaces)
- Keep first meaningful render fast on mobile.
- Control large list rendering with batching/windowing patterns when needed.
- Avoid duplicate fetches and duplicate transforms.

## 8) Why this path is best-fit for this repo
- Matches current route authority and deployment reality.
- Preserves existing functionality while reducing architectural debt.
- Enables visible modernization quickly without destabilizing value correctness.
- Supports long-term maintainability and future feature scale.
