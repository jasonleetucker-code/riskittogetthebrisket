# Phased Frontend Modernization Roadmap

Last updated: 2026-03-19

## Phase 1 — Stabilize + Foundation (Immediate)

### Goals
- Improve perceived speed and UX coherence without changing route authority.
- Reduce avoidable runtime work in live static shell.
- Establish consistent design-system baseline in migration shell.

### Work
1. Apply low-risk runtime boot optimizations in static private shell.
2. Standardize typography/tokens/layout scaffolding in Next shell.
3. Keep public/private route truth explicit in docs.
4. Continue cross-device smoke + parity checks.

### Done When
- No functional regression in calculator/rankings flows.
- Mobile/tablet smoke remains green.
- Runtime authority unchanged and documented.

## Phase 2 — Private Surface Parity Buildout

### Goals
- Bring Next `/rankings` and `/trade` to feature parity with static private shell.
- Consolidate duplicated UI logic into reusable components.

### Work
1. Build Next rankings workflow parity:
   - filters/sort/source columns
   - mobile cards + desktop table parity
   - backend parity checks integrated
2. Build Next trade workspace parity:
   - asset add/remove/swap/clear
   - 2/3-team flows
   - impact/analyze + saved drafts
3. Introduce shared formatting and state components.

### Dependencies
- Stable backend API contract and parity diagnostics.
- Existing Playwright route/value tests.

### Done When
- Feature parity confirmed with automated tests.
- No critical mismatches between rendered values and backend values.
- Mobile parity comparable to current static shell.

## Phase 3 — Authority Consolidation + Legacy Reduction

### Goals
- Move private route rendering authority to Next (if parity proven).
- Reduce monolithic static private runtime burden.

### Work
1. Flip private route rendering with config-guarded rollout.
2. Keep rollback path to static shell until multiple clean releases.
3. Remove or archive proven-dead private static runtime sections.
4. Preserve public League static route ownership unless League migration is deliberately scheduled.

### Done When
- `/app`, `/rankings`, `/trade` stable under Next authority.
- Auth boundary and public League behavior unchanged.
- Regression suite catches route/value drift before release.

## Priority Queue (Dependency-Aware)
1. Performance hot-spot cleanup in static shell boot/render path.
2. Next rankings parity (highest user trust impact).
3. Next trade workspace parity (highest flagship feature impact).
4. Shared design-system components + state surfaces.
5. Controlled private-route authority migration.

## Risk Controls
- Do not migrate route authority by appearance alone.
- Require parity checks before each authority flip.
- Keep last-known-good behavior and rollback path documented.
- Maintain mobile smoke as a release gate.

## What Stays for Now
- Backend routing and auth gates.
- Static public League shell.
- Existing production value computation authority in backend/data pipeline.
