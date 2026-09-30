# DFS — session handoff

Resumable state for the next session (any model). Update this file at the end of every DFS
session; it is the one place the branch/PR/evidence state lives. Authority: `docs/EXECUTION_PLAN.md`
§0 "DFS — owner directive, 2026-09-30" (+ same-day addendum). Scope + IDs: `TRACEABILITY.md`.
Order: `ROADMAP.md` (Phases A–H).

## Branches and PRs (2026-09-30)

| Branch | PR | Contents | State |
|---|---|---|---|
| `claude/dfs-foundation` | #1534 → `main` | P0 registration, rules registry, owner CSV imports, MILP baseline, builds, export, `/dfs` page, source seeds, review fixes, HiGHS single-thread fix | **MERGED** 2026-09-30 (`1fdd9b8fe`) after a green release candidate |
| `claude/dfs-contests` | #1535 → `main` | Phase B contests; addendum reconciliation; Phase A canonical slate + detection + SportsDataIO adapter (flag OFF) + provider matrix + freshness + contest↔slate link | Retargeted to `main`; release candidate running |
| `claude/dfs-multisport` | #1546, stacked on #1535 | See "multisport contents" below | Open; retarget to `main` after #1535 merges |

Worktrees: `C:\Users\jason\code\chaseupside-dfs` (#1534), `…\chaseupside-dfs-contests` (#1535),
`…\chaseupside-dfs-next` (multisport); each with `frontend/node_modules` as a junction to the main
checkout's.

### multisport contents

- Rule sets (all UNVERIFIED, research mode): NBA + NHL classic (DK + FD), DK NFL Showdown Captain,
  DK MMA Classic.
- Phase B: Quick / Exact / Import contest modes, top-1% concentration, payout curve, contest/preset
  on builds + disclosures.
- Phase C: conditional rules + rule builder; projection overrides vs selection boosts; salary range;
  per-player min/max exposure (ADR-DFS-011); sport-neutral team/game stacks (`teamStacks`).
- Phase D: owner-imported projected ownership; owner-imported outcome distributions (StDev,
  P10…P90; Floor/Ceiling only with stated percentiles); evidence-claim policy core; all 109 source
  seeds resolved (podcasts, websites, sportsbooks — `SOURCES.md` §5–7).
- Phase G foundation: DK entry-file import/export; late swap (`src/dfs/lateswap.py`,
  `/api/dfs/late-swap[/export]`, locked + unknown-start slots pinned, only proven-open players in).
- UI: Playwright a11y spec for `/dfs`; code-split pool / rule builder / team stacks / late swap.

## Proven (with evidence)

- `pytest tests/dfs` 202 passed on multisport. Includes:
  - brute-force MILP parity: DK + FD NFL, NBA, NHL, MMA, Showdown, team stacks (NHL 4-3 on both
    infeasible and binding seeds), late swap against a slot-aware brute force;
  - the $1,000/$100 → $550 tie fixture;
  - the §29 end-to-end fixture.
- Frontend: 995 component + lib tests green. `next build` + bundle budgets green (`/dfs` 32.5 KB of 34).
- Later test directories run locally on #1534: 6 failures, none DFS-caused (Windows-only on untouched
  code, or suite-order flakes that pass alone).

## Not proven / open

- Nothing is deployed. No production screenshots.
- Rule sets and upload / entry-file formats are unverified (official pages refuse automated access).
- SportsDataIO coverage is documented, not verified (no key; paid; owner approval).
- Windows-only failures on untouched `main` are listed in memory; Linux CI is authoritative.
- TEST ISOLATION debt stays open at low priority (`docs/OWNER_REQUESTED_TODO.md`). The #1534
  mount-test failures were a FastAPI 0.135 vs 0.141 introspection difference, not contamination.
- One unexplained single failure of `test_full_flow_research_build_and_export`, seen under heavy
  local CPU load (a concurrent full-suite run). It could not be reproduced in 3 clean runs.
- FIXED (#1534, `bb7046b9d`): the intermittent native crash of `pytest tests/dfs` was HiGHS
  (scipy.optimize.milp) being called from different threads — a Windows access violation in a
  frameless native thread, ~1 run in 5. Every solve now runs on one long-lived `dfs-highs`
  thread; 20/20 clean runs after, and a test pins solves to that thread.

## Owner actions that unblock the most

1. Confirm DK/FD rules, or drop real salary files + blank upload/entry templates into
   `tests/dfs/fixtures/templates/`.
2. Decide on a SportsDataIO DFS plan and/or a licensed odds aggregator (price/licence unknown). If
   approved, set keys on the box (never committed).
3. Name any projection sources you are licensed to use, and which percentiles their floor/ceiling are.
4. Clarify 6 unresolved website seeds: LineupIQ, Bet The Line, Sharp AI Proptimizer, NFL Data Edge,
   SportsPredict, Prediktor.

## Next dependency-ready batch

- **G:** FanDuel entry files; live scoring + rooting view; cross-entry-coordinated late swap.
- **E:** field / duplication models from imported ownership + distributions, with calibration reports
  before any contest-EV claim.
- **C:** NHL line stacks (needs line data).
- **UI (Lane 6):** strategy / lineup-count chips on the home flow; E2E coverage of late swap.

## Commands

```bash
python -m pytest tests/dfs -q
```

```bash
cd frontend && npx vitest run __tests__/dfs-lib.test.js __tests__/components
```

```bash
cd frontend && npx next build --webpack && node scripts/check-bundle-sizes.mjs
```
