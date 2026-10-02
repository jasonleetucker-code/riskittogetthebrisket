# DFS — documentation index

**Owner directive:** 2026-09-30 — "ChaseUpside DFS master product, engineering, research and
delivery prompt" (NFL / NBA / NHL / MMA × DraftKings / FanDuel).
**Authorization:** `docs/EXECUTION_PLAN.md` §0 "DFS — owner directive, 2026-09-30".
**Intake:** `docs/OWNER_REQUESTED_TODO.md` → "Added 2026-09-30 — DFS".
**Front door:** Calculator Ideas (`docs/BRISKET_IDEAS.md`). This folder is supporting detail,
not a second backlog.

## What exists today (Phase 1 slice, branch `claude/dfs-foundation`)

| Capability | State | Where |
|---|---|---|
| `/dfs` route, DFS nav group, private auth | implemented + tested | `frontend/app/dfs/`, `frontend/lib/nav-model.js` |
| Platform × sport × format capability matrix with honest readiness | implemented + tested | `config/dfs/rulesets.json`, `src/dfs/rules.py` |
| DraftKings NFL Classic + FanDuel NFL Full Roster rule sets | encoded, **unverified** (research only) | same |
| NBA + NHL classic (DK + FD) | encoded, **unverified** (research only; branch `claude/dfs-multisport`) | same |
| DraftKings NFL Showdown Captain | encoded, **unverified** (research only; CPT/FLEX rows as one athlete, 1.5× once) | same |
| MMA, FanDuel single-game, other showdowns | registered as `not_implemented` with reasons; files recognised | same |
| Owner-imported salary files (DK, FD) + projection CSV, identity quarantine | implemented + tested | `src/dfs/imports.py` |
| Immutable per-owner slate snapshots + builds | implemented + tested | `src/dfs/store.py` (`data/dfs/`) |
| Deterministic MILP optimizer (projection baseline), locks/excludes/salary/team/groups/QB stacks/bring-back, exactly-N with uniqueness + exposure caps, conflict isolation | implemented + tested (brute-force agreement) | `src/dfs/optimizer.py` |
| Upload-CSV export, re-validated at export time | implemented; **format unverified** | `src/dfs/export.py` |
| Contests: editor, payout-ladder validation, exact tie payouts, rake/overlay states, hard entry cap, versioned saves (branch `claude/dfs-contests`) | implemented + tested | `src/dfs/contests.py`, `frontend/components/dfs/ContestPanel.jsx` |
| Strategy presets (H2H … 150-max, single-game) — objectives + required models, all `unsupported` until P4 | registered | `config/dfs/presets.json` |
| Canonical slate model + platform-file auto-detection (platform · sport · format), wrong-platform refusal, eligibility + salary-cap cross-checks, per-class freshness (branch `claude/dfs-contests`) | implemented + tested | `src/dfs/slate.py` |
| Licensed slate feed: SportsDataIO `DfsSlatesByDate` adapter (flag `dfs_sportsdataio_slates`, OFF; no key) + provider capability / cost matrix | documented, **not verified** | `src/dfs/providers.py`, `config/dfs/providers.json` |
| Source seed registry — all 74 + 6 + 29 supplied names | registered, all `unverified` | `config/dfs/source_seeds.json` |

Nothing here is contest-aware yet. Every build says `capabilityLevel: "projection_only"`,
`contestEvaluated: false`, and carries no ROI/EV number.

## Documents

| Document | Purpose |
|---|---|
| [`TRACEABILITY.md`](TRACEABILITY.md) | Every mandate requirement with a stable ID, phase, status and next action (zero-loss map) |
| [`ROADMAP.md`](ROADMAP.md) | Dependency-aware phases 0–8 with NOW / NEXT / LATER / BLOCKED |
| [`DECISIONS.md`](DECISIONS.md) | ADR-DFS-001… (solver, readiness gating, sequential N, platform average, nav, isolation) |
| [`SOURCES.md`](SOURCES.md) | Source registry schema, independence policy, acquisition rules, competitor-research protocol |
| [`USER_GUIDE.md`](USER_GUIDE.md) | How to use the workspace today, CSV formats, what the statuses mean |
| [`HANDOFF.md`](HANDOFF.md) | Resumable session handoff: branches, PRs, what is proven, exact next commands |

## Owner actions that unblock the most

1. **Verify the two NFL rule sets.** Both official rules pages refused automated access on
   2026-09-30 (DraftKings 403 + the in-app browser blocks the domain; FanDuel 403). Confirm
   roster slots, cap and team/game rules, or drop a real salary file + blank upload template into
   `tests/dfs/fixtures/templates/`. Until then everything is research-only.
2. **Say which projection sources you are licensed to use** (none is assumed; see `SOURCES.md`).
3. **Budget / risk limits** are required before any entry-count recommendation (DFS-§7-03) —
   none is inferred.
