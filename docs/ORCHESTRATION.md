# Autonomous Engineering Org — Canonical Execution Plan

Maintained by the main orchestrator session. This file IS the unified plan,
ownership model, git/integration policy, and dashboard. Update on every
material change. Supersedes ad-hoc per-track instructions.

Target: **comprehensively functional, integrated, polished product in ~1
week** (by ~2026-08-02). Optimize for the final integrated system, not
constant main-branch stability.

## 1. Workstreams & ownership (one owner each)

| WS | Workstream | Owner (agent) | Branch | Scope (exclusive) | Status |
|---|---|---|---|---|---|
| A | Redesign R2 — rankings + profiles | design custodian | claude/redesign-r2-rankings | frontend/app/rankings/, PlayerPopup, ds/ additions | Testing (PR imminent) |
| B | Redesign R3 — dashboard, news, market surfaces | news-domain agent (launch after R2 merges) | claude/redesign-r3-surfaces | frontend/app/{page,news,edge,finder}/ | Ready (awaiting R2) |
| C | Redesign R4 — draft war room + trade surfaces | trade-domain agent (launch after R2 merges) | claude/redesign-r4-warroom | frontend/app/{draft,trade,trades,angle,waivers}/ | Ready (awaiting R2) |
| D | Redesign R5 — perf/a11y/mobile sweep + dead-CSS purge | design custodian | claude/redesign-r5-polish | global CSS, cross-page | Blocked by B+C |
| E | League Intelligence LI-1..LI-8 | league-intel agent | claude/league-intel-foundation (continuous) | src/league_intel/, config/league_intel/, tests/league_intel/, coordinated: registry.json, src/ros/lineup.py | In progress (LI-1/2 at suite gate) |
| F | LI-9 UI (valuation-mode toggle) | design custodian | (into R5 or own) | R1 shell TopBar + getActiveValue adoption | Blocked by E(LI-4)+A |
| G | E2E safety net upkeep | e2e agent | claude/e2e-r1-reconcile | tests/e2e/ | In progress |
| H | Identity sweep close-out | identity agent | claude/identity-sweep | identity joins (re-scoped post-merges) | Converging (status poked) |
| I | Ops: refresh/deploy/intel cron, VPS | orchestrator | main (dispatch only) | workflows, monitoring | Steady; intel 401 user-blocked (issue #545) |
| R | Fresh-eyes review | reviewer agent | read-only | PR comments | At integration checkpoints only |

Idle agents with retained domain context (resume, never cold-spawn):
intel, FAAB, playerctx, news, prod-hardening — reassigned as B/C owners or
LI contributors as checkpoints arrive.

## 2. Git & integration policy (REVISED — effective now)

Old mode (per-task PR, merge-on-green, ~13 merges/day) is retired. New:

1. **One branch per WORKSTREAM**, not per task. Batch logical commits;
   checkpoint-commit at least at each completed sub-milestone. Push
   regularly (container loss protection) — pushing ≠ PR.
2. **PR only at integration checkpoints** or when: cross-workstream
   contract must become canonical (e.g. LI registry fix), risk warrants a
   rollback boundary, or a workstream is complete.
3. **Two scheduled integration windows**: mid-week (~2026-07-29: R2+R3+R4
   merged in dependency order; LI-1..LI-4 merged; E2E reconciled) and
   final (~2026-08-01: everything; full-system validation).
4. Reviewer runs at integration windows (and on high-risk diffs), not per
   push. CI runs on PRs as before — fewer PRs = fewer runs.
5. Data-refresh/deploy automation on main is unaffected.
6. Safety: no destructive resets, no force-push on shared branches, no
   cross-agent file edits without registry entry, secrets untouched.

## 3. Shared contracts (frozen unless custodian approves)

- **ds/ component APIs + tokens** (design custodian) — R3/R4 consume, may
  ADD primitives, must not mutate existing APIs.
- **nav-model.js** (design custodian) — single IA source; R3/R4 register
  routes only.
- **Data contract /api/data + buildRows purity** (orchestrator) — frozen;
  no client-side value math ever.
- **league_registry rosterSettings** (league-intel agent, LI-1) — being
  corrected; consumers verified in that PR; afterwards frozen.
- **Sleeper stat-key vocabulary** (ADR-005) — LI event schema.
- **getActiveValue() selector** (LI-4) — defined early so R-phase pages
  can adopt without waiting for the adjustment engine (no-op = consensus).
- High-conflict files: server.py (append-only sections per workstream),
  package.json/lockfile (single-owner edits, coordinate via registry),
  globals.css (R5 owns the purge; others additive only).

## 4. Dependency graph (critical path bold)

**R2 → (R3 ∥ R4) → R5 → final integration**
**LI-1/2 → LI-3 (lineup exactness) → LI-5 (replacement) → LI-7 (adjusted values)**
LI-4 (value schema/selector) → independent after LI-1; unlocks F.
LI-6 (projection re-scoring) after LI-2; feeds LI-7.
LI-8 (sim/League Twin ext) after LI-3; enhances trade UI (R4 seam: display-only).
G tracks A-D (SEL registry). H independent. I independent (user unblocks intel).

## 5. One-week backward plan

- **Now–Sun**: R2 lands; R3+R4 launch in parallel; LI-1/2 PR + review;
  LI agent continues LI-3+4+5 on the same branch (one batched PR).
- **Mon–Tue**: mid-week integration window #1 (R3, R4, LI batch, E2E).
  LI-6/7 build; F (toggle) starts once LI-4 + R-pages merged.
- **Wed–Thu**: LI-7 guardrailed values live behind toggle (default
  consensus); R5 sweep; LI-8 sim extension; golden backtests.
- **Fri–Sat**: final integration window — full-suite + E2E + visual pass,
  perf, docs, release checklist, deploy, VPS apply notes for user.

Risks: credit outages (mitigated: liveness tick auto-resumes agents);
LI golden validation may hit Sleeper stats-API gaps (fallback documented
in LI-2 instructions); intel cron stays red until user runs the
journalctl step (issue #545) — not on the critical path.
