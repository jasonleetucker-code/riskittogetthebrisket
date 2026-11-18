# Audit implementation tracker — 2026-11-18

**What this is.** The live record of implementing the 16 priorities from the 2026-11-18 comprehensive audit
(audited `origin/main` `de63c768`, production build `71cc45b7`). A future session resumes from this file plus
`docs/WORK_CLAIMS.md`, not from chat history.

**Authority.** Owner directive 2026-11-18 ("MASTER DIRECTIVE — IMPLEMENT ALL 16 AUDIT PRIORITIES"), recorded as
intake AUD-1 … AUD-16 in `docs/OWNER_REQUESTED_TODO.md` and authorized in `docs/EXECUTION_PLAN.md` (same date).
Priority sets order, not whether an item is done. Owner-only gates still bind; they are listed per task below.

**Process.** One coordinator plus at most four concurrent editing workers in total (the coordinator's own editing
counts), each on its own `claude/serene-shannon-7lsrm9-tNN-*` branch with a disjoint file claim. PRs are small and
focused, merged by the Integration Authority only after green required checks, an independent review and a
release-candidate run on the exact tree; then deploy and production verification.

**Statuses.** NOT STARTED · IN PROGRESS · PR OPEN · MERGED · DEPLOYED · VERIFIED COMPLETE ·
BLOCKED — OWNER ACTION · BLOCKED — EXTERNAL DEPENDENCY · VERIFIED NO LONGER NEEDED. A status is set only from evidence
(a commit, a CI run, a production probe), never from intent.

## Summary table

| # | Task | Pri | Status | Branch / PR | Production evidence | Open issue |
|---|---|---|---|---|---|---|
| 1 | Hermetic hard gate and skip-budget repair | P0 | IN PROGRESS | `claude/serene-shannon-7lsrm9-t01-hermetic-gate` | — | archive `…20261107_063955.zip` expected pruned ~2026-11-21 |
| 2 | Freshness and deploy-lag SLO with alerts | P0 | IN PROGRESS | `claude/serene-shannon-7lsrm9-t02-freshness-slo` | — | — |
| 3 | Decouple data delivery from the full code gate | P1 | NOT STARTED | — | — | activation needs an owner policy amendment (Agent OS §3 L3 "no skip logic") |
| 4 | Owner admin-action pack | P1 | NOT STARTED | — | — | ruleset apply, credential rotation, off-box backup destination, deploy-key review are owner-only |
| 5 | Year-boundary hardening (2026→2027) | P1 | NOT STARTED | — | — | — |
| 6 | Land five UI-fix PRs #2223/#2224/#2226/#2227/#2228 | P1 | IN PROGRESS (independent review + train validation) | train `claude/serene-shannon-7lsrm9-t06-ui-train` | — | real-device touch check for #2223 |
| 7 | Post-deploy trade and War Room smoke | P1 | NOT STARTED | — | — | — |
| 8 | Public-repo data-exposure remediation | P2 | NOT STARTED | — | — | publication policy is an owner decision |
| 9 | Trade-flow resilience (frontend) | P2 | NOT STARTED | — | — | — |
| 10 | Mobile ergonomics and 390 px coverage | P2 | NOT STARTED | — | — | — |
| 11 | Restore Signals; loud private-source failure | P2 | NOT STARTED | — | — | box journal access needed for root cause |
| 12 | Live roster refresh — measure first | P2 | NOT STARTED | — | — | — |
| 13 | Security hardening batch | P2 | NOT STARTED | — | — | — |
| 14 | Next.js 16.4.5+ (#2233) | P2 | NOT STARTED | — | — | — |
| 15 | Make permanent-red / vacuous-green checks meaningful | P3 | NOT STARTED | — | — | — |
| 16 | Node 20 → 22 | P3 | NOT STARTED | — | — | production runtime cutover is box work |

## Baseline (2026-11-18, before any change)

All values measured this session unless marked otherwise.

- `origin/main` `de63c768`; production build `71cc45b7`; last 3 box scrapes OK; backend 1.5 / 3 GiB, 0 `memory.high`
  events; contract OK.
- Deploy Production, last 100 runs: 50 success, 38 failure, 11 cancelled; no successful deploy on 2026-11-13 or 11-14.
  Deploy gaps: 63 h (11-12 23:42 → 11-15 14:49 UTC) and 31 h (11-16 12:58 → 11-17 20:02 UTC).
- Hard gate on the latest green deploy: "7 tests + 0 modules skipped (budget 7)".
- `signalsSf` last fetched 2026-11-02 (age 391.9 h on 11-18; alert threshold 24 h).
- Five UI-fix PRs: all `mergeable_state: clean`, required checks green, no reviews.
- #2233 (Next 16.4.5): red on backend shard 4 (the BDVM study test fixed on main by #2234) and an E2E journey.

## Per-task record

Each section: summary of the problem (from the audit), what was done, files, PRs/commits, tests, CI, deploy,
production evidence, remaining risk. Updated as work lands.

### 1. Hermetic hard gate and skip-budget repair — P0
Problem: blocking tests read rolling `exports/archive/` zips and refresh-rewritten inputs; skip budget has zero
headroom; retention will delete `dynasty_export_20261107_063955.zip` (not the newest of its day) about 2026-11-21,
turning every gate red. Precedent: `c9a3d02f` (#2234).
Record: in progress.

### 2. Freshness and deploy-lag SLO — P0
Problem: no alert on "production N hours behind validated main" or "decision surface mostly withheld".
Record: in progress.

### 3. Data delivery decoupled from the full code gate — P1
Problem: each data commit runs the 8-shard gate (~115 runner-minutes) and restarts the backend; 62% of data-triggered
deploys failed in the audit window versus 7% of code pushes. Activation changes an Agent OS rule, so the path ships in
shadow mode and production cutover waits for the owner.
Record: not started.

### 4. Owner admin-action pack — P1
Problem: prepared required-checks ruleset never applied (live ruleset: deletion + non_fast_forward only); credential
rotation, off-box backup and deploy-key inventory pending since owner decision briefs #12–#14 (2026-11-08).
Record: not started.

### 5. Year boundary — P1
Problem: calendar-derived draft years and pick horizons (`draft_class_evidence.py:248`, `sleeper_overlay.py`,
`intel/service.py:140`) are untested across 2026-12-31 → 2027-01-02.
Record: not started.

### 6. Five UI-fix PRs — P1
Record: independent review and release-train validation in progress.

### 7. Post-deploy trade / War Room smoke — P1
Problem: authenticated post-deploy verification never calls `/api/trade/analyze` or `/api/trade/analyze-multi`.
Record: not started.

### 8. Public-repo data exposure — P2
Problem: public repo tracks ~30 vendor CSVs and ~158 full-board export zips (with Sleeper owner IDs) while
`SECURITY.md` calls valuations private. No history rewrite, visibility change or purge without the owner.
Record: not started.

### 9. Trade-flow resilience — P2
Problem: plain errors without Retry on several trade routes; no client timeout on the contract fetch; the service
worker can answer API calls with HTML.
Record: not started.

### 10. Mobile ergonomics — P2
Problem: 32 px controls without coarse-pointer sizing; 390 px axe scans cover 12 route families.
Record: not started.

### 11. Signals and private-source alerting — P2
Problem: `signalsSf` stale ~16 days, votes withheld, no loud alert.
Record: not started.

### 12. Roster freshness — P2 (measure first)
Problem: `dynasty_main` rosters refresh only with the ~2 h scrape; the N-team engine needs rosters ≤ 6 h old. Whether
this causes real ownership refusals is unmeasured; no new polling without evidence.
Record: not started.

### 13. Security hardening — P2
Problem: placeholder password passes the startup guard; non-ASCII bearer token → 500; CSV formula injection;
anonymous `GET /api/health` can send the backup-alert email; workflows without `permissions:`.
Record: not started.

### 14. Next.js upgrade — P2
Record: not started.

### 15. Meaningful CI checks — P3
Problem: Rank-Form Curve Drift red 13 weeks running (#898); Sharp population check passes without measuring (#1727);
dead `_tmp_*` workflow registrations.
Record: not started.

### 16. Node 22 — P3
Problem: Node 20 (`engines >=20 <21`, every workflow) is past end of life; blocks jsdom/jest-dom/axe upgrades.
Record: not started.

## Owner actions (consolidated, kept current)

1. Task 4 — apply `deploy/github/main-protection-ruleset.json`; rotate the production login credential; choose an
   off-box backup destination; confirm the deploy-key inventory.
2. Task 3 — approve or decline the Agent OS amendment that lets a byte-identical code tree reuse its validation.
3. Task 8 — choose a publication policy for vendor CSVs and board exports.
4. Task 11 — if Signals' session expired, re-authenticate on the box.
5. Task 16 — authorize the production Node runtime cutover.
