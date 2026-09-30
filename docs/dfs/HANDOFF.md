# DFS — session handoff

Resumable state for the next session (any model). Update this file at the end of every DFS
session; it is the one place the branch/PR/evidence state lives. Authority: `docs/EXECUTION_PLAN.md`
§0 "DFS — owner directive, 2026-09-30" (+ same-day addendum). Scope + IDs: `TRACEABILITY.md`.
Order: `ROADMAP.md` (Phases A–H).

## Branches and PRs (2026-09-30)

| Branch | PR | Contents | State |
|---|---|---|---|
| `claude/dfs-foundation` | #1534 → `main` | P0 registration, rules registry, owner CSV imports, MILP baseline, builds, export, `/dfs` page, source seeds, review fixes | Open; Auto-fix on; CI was re-running after the coercion-gate fix |
| `claude/dfs-contests` | stacked on #1534 | Phase B contests (ladders, exact ties, rake/overlay, entry cap, presets, Contest panel); addendum reconciliation; Phase A canonical slate + platform-file detection + SportsDataIO adapter (flag OFF) + provider matrix + freshness + contest↔slate link | Open as a stacked PR; retarget to `main` after #1534 merges |

Worktrees used: `C:\Users\jason\code\chaseupside-dfs` (#1534) and
`C:\Users\jason\code\chaseupside-dfs-contests` (stacked), each with `frontend/node_modules` as a
junction to the main checkout's.

## Proven (with evidence)

- `pytest tests/dfs` 108 passed (incl. brute-force MILP parity on DK + FD rules, $1,000/$100 → $550
  tie fixture, rake-vs-overlay states, provider failure states, key-never-in-URL, the §29
  end-to-end fixture: slate → contest → projections → constraints → 5 lineups → export →
  re-import + independent validation).
- Frontend DFS tests 32 passed; full vitest 197 files green on #1534; `next build` + all bundle
  budgets green (`/dfs` 29.6 KB / 34).
- Real-browser runs on `next start` + the worktree backend (local E2E test session, synthetic
  slates): #1534 build/export flow; stacked branch: detection chip, platform switch, import,
  eligibility-disagreement banner, freshness table, provider "not connected" + CSV fallback.

## Not proven / open

- Nothing is deployed. No production screenshots; no axe/E2E spec for `/dfs` yet.
- Rule sets and upload formats unverified (official pages refuse automated access).
- SportsDataIO coverage is documented, not verified (no key; paid; owner approval).
- Windows-only: `tests/api/test_feature_flag_reachability.py` fails on untouched `main` too
  (path separators); Linux CI is authoritative.
- Test-isolation debt (non-blocking): the shared-`server.app` contaminator seen in #1534's CI is
  unidentified, not disproven — tracked in `docs/OWNER_REQUESTED_TODO.md` ("TEST ISOLATION").

## Owner actions that unblock the most

1. Confirm DK/FD NFL rules, or drop real salary files + blank upload templates into
   `tests/dfs/fixtures/templates/`.
2. Decide on a SportsDataIO DFS plan (price/licence unknown); if approved, set
   `SPORTSDATAIO_API_KEY` on the box and `RISKIT_FEATURE_DFS_SPORTSDATAIO_SLATES=1`.
3. Name any projection sources you are licensed to use.

## Next dependency-ready batch

- **A:** NHL + NBA classic rule sets (unverified until evidence) so their files build; Showdown
  / MVP captain rules; entry-file import (entry IDs) for export and late swap.
- **B:** quick-contest mode UI (preset picker), top-1% concentration + payout-curve chart,
  record the contest version on each build.
- **C:** min exposure, if-then groups, salary-left range, NHL/NBA/MMA stack controls.
- **UI (Lane 6):** strategy / lineup-count chips on the home flow, mobile pass, axe + E2E spec.

## Commands

```bash
python -m pytest tests/dfs -q
```

```bash
cd frontend && npx vitest run __tests__/dfs-lib.test.js __tests__/dfs-bridge-route.test.js __tests__/components/dfs-workspace.test.jsx __tests__/components/dfs-contest-panel.test.jsx __tests__/components/dfs-slate-sources.test.jsx
```

```bash
cd frontend && npx next build --webpack && node scripts/check-bundle-sizes.mjs
```
