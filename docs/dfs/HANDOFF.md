# DFS — session handoff

Resumable state for the next session (any model). Update this file at the end of every DFS
session; it is the one place the branch/PR/evidence state lives. Authority: `docs/EXECUTION_PLAN.md`
§0 "DFS — owner directive, 2026-09-30" (+ same-day addendum). Scope + IDs: `TRACEABILITY.md`.
Order: `ROADMAP.md` (Phases A–H).

> **CURRENT STATUS (2026-10-07, CLEANUP-1 reconciliation):** every DFS PR below — #1534, #1535, #1546,
> #1547–#1560 and #1561 (`claude/dfs-auto`) — is **MERGED** (all 2026-09-30) and the code is in the
> deployed production build (ancestor of `1eec690fa`, 2026-10-07; flags `dfs_workspace` and
> `dfs_auto_slates` default ON). There is no live DFS branch or stacked chain. #1650 (2026-10-04,
> `5fdff0256`) fixed two time-bombed DFS as-of tests that had gone red on `main`. NOT verified: the
> production `/dfs` route, production screenshots, and installation of the `dynasty-dfs-auto-refresh`
> timer on the box. The sections below are the historical 2026-09-30 session state.

## Branches and PRs (2026-09-30) — all merged; historical

| Branch | PR | Contents | State |
|---|---|---|---|
| `claude/dfs-foundation` | #1534 → `main` | P0 registration, rules registry, owner CSV imports, MILP baseline, builds, export, `/dfs` page, source seeds, review fixes, HiGHS single-thread fix | **MERGED** 2026-09-30 (`1fdd9b8fe`) after a green release candidate |
| `claude/dfs-contests` | #1535 → `main` | Phase B contests; addendum reconciliation; Phase A canonical slate + detection + SportsDataIO adapter (flag OFF) + provider matrix + freshness + contest↔slate link | **MERGED** 2026-09-30 (`66026851f`). *Previously: retargeted to `main`; release candidate running* |
| `claude/dfs-multisport` | #1546, stacked on #1535 | See "multisport contents" below | **MERGED** 2026-09-30 (`7991cef3f`). *Previously: open; retarget to `main` after #1535 merges* |

Historical worktrees (branches merged): `C:\Users\jason\code\chaseupside-dfs` (#1534), `…\chaseupside-dfs-contests` (#1535),
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

## Contest-aware modelling phase (2026-09-30, second directive)

Stacked PR chain — **all merged 2026-09-30** (historical instruction was "merge in order once `main`
holds #1546"):

| PR | Branch | Slice | Tests at head | State |
|---|---|---|---|---|
| #1547 | `claude/dfs-pit` | A — point-in-time ledger, models, decisions, evaluations | 231 | MERGED `4f25d5a8a` |
| #1548 | `claude/dfs-ownership` | B — ownership baseline + ensemble + metrics (+ capped-surplus fix) | 243 | MERGED `e52c349ad` |
| #1549 | `claude/dfs-sim` | C — outcome distributions + copula + sport correlation priors | 249 | MERGED `86863389c` |
| #1550 | `claude/dfs-field` | D — field generator + field fit (+ implied-ownership challenger) | 256 | MERGED `63d6374fd` |
| #1551 | `claude/dfs-dup` | E — duplication baseline + zero-truncated challenger | 260 | MERGED `23c5c0162` |
| #1553 | `claude/dfs-contestsim` | F — contest Monte Carlo + pipeline + `/simulate` | 266 | MERGED `fdf384ff6` |
| #1554 | `claude/dfs-portfolio` | G — portfolio optimizer + `/portfolio` | 271 | MERGED `bc4c510a6` |
| #1556 | `claude/dfs-backtest` | H — chronological backtest + `/backtest` | 277 | MERGED `13cea60e0` |
| #1557 | `claude/dfs-ui` | I — contest-model + scorecard UI | 278 | MERGED `2f5bd931a` |
| #1558 | `claude/dfs-fanduel` | J — FanDuel parity + rule provenance | 284 | MERGED `d57254724` |
| #1559 | `claude/dfs-sources` | K — Daily Fantasy Fuel adapter (first connected source) | 288 | MERGED `336c3769e` |
| #1560 | `claude/dfs-jobs` | L — background jobs + pinned route surface | 295 | MERGED `13bf07a09` |
| #1561 *(was "(next)")* | `claude/dfs-auto` | M — zero-upload primary workflow: automatic NFL DK+FD slates (ADR-DFS-024, DFS-AUTO-01..24) | 318 | MERGED `519ee6159` |

Historical worktree (branches merged): `C:\Users\jason\code\chaseupside-dfs-model`.
Evidence classes, kept apart: every model here has UNIT / SYNTHETIC evidence only. No historical
contest has been replayed (none imported), no forward test exists, and nothing is shown to be
profitable. Negative findings recorded in ADR-DFS-016 (structural ownership targets are
salary-infeasible; fixed-order field sampling was badly biased).

## Proven (with evidence)

- `pytest tests/dfs` 202 passed on the multisport head (historical branch-time count; #1650 later
  fixed two time-bombed as-of tests on `main`). Includes:
  - brute-force MILP parity: DK + FD NFL, NBA, NHL, MMA, Showdown, team stacks (NHL 4-3 on both
    infeasible and binding seeds), late swap against a slot-aware brute force;
  - the $1,000/$100 → $550 tie fixture;
  - the §29 end-to-end fixture.
- Frontend: 995 component + lib tests green. `next build` + bundle budgets green (`/dfs` 32.5 KB of 34).
- Later test directories run locally on #1534: 6 failures, none DFS-caused (Windows-only on untouched
  code, or suite-order flakes that pass alone).

## Not proven / open

- **CURRENT (2026-10-07):** code is deployed (see the status block at the top); production `/dfs`
  observation, production screenshots and the auto-refresh timer install are NOT verified.
  *Previously (2026-09-30): "Nothing is deployed. No production screenshots."*
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

0. **Zero-upload workflow (DFS-AUTO):** automatic slates cannot produce UPLOAD files — DK/FD player
   ids have no permitted free source. Approve a licensed DFS slate feed (SportsDataIO DFS slates;
   price not verified, nothing purchased) or keep using the platform file under *Advanced* for the
   final upload. Say whether your RotoGrinders permission covers premium (paid) data you hold.
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
