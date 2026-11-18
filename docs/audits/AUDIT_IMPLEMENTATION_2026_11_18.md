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
| 1 | Hermetic hard gate and skip-budget repair | P0 | DEPLOYED | #2239 → `cb5648ff` | production build `bd17e684`; deploy hard gates since have passed with the guard in place | follow-ups: two archive readers kept (their day's newest export) |
| 2 | Freshness and deploy-lag SLO with alerts | P0 | VERIFIED COMPLETE | #2238 → `4a80cca8` | production build `bd17e684` (~14:06 UTC): `freshness_slo.state=measured`, top-200 stale 0/200, priced withheld 15/1016 (1.48 %), board age 0.01 h, private sources 4 provisioned / 4 stale | alerting verified 16:05 UTC: Scheduled Health Check run 44341452236 (dispatched) measured deploy lag 1.12 h, 1 consecutive deploy failure, top-200 stale 0.0, withheld 0.003, board age 0.26 h — all OK — and BREACHED `data_freshness.private_sources` 4/4 (names withheld), auto-opening issue #2258 "Production SLO alert". The breach is the Signals stall (Task 11) |
| 3 | Decouple data delivery from the full code gate | P1 | DEPLOYED (shadow observer running in CI) | #2251 → `ecd2bc91` | production `eb604ee2`; shadow run 44339329955 classified train 4 CODE (correct) | activation BLOCKED — OWNER DECISION; backtest: 9 of 23 data-only runs failed the full gate on data-coupled tests, so the fast path is not yet safe |
| 4 | Owner admin-action pack | P1 | DEPLOYED (tooling) — BLOCKED — OWNER ACTION | #2244 → `ca698b11` | production `eb604ee2` (scripts/runbook only; nothing applied) | ruleset apply, credential rotation, off-box backup destination, deploy-key review are owner-only |
| 5 | Year-boundary hardening (2026→2027) | P1 | DEPLOYED | #2248 → `ae310e03` | production `eb604ee2`; no served value changed by design | owner: league vs board horizon divergence at New Year (2030 picks unpriced until the 2027 draft is proven) |
| 6 | Land five UI-fix PRs #2223/#2224/#2226/#2227/#2228 | P1 | DEPLOYED (+ #2250 merged `58278641`) | #2227 `3945d0a2`, #2224 `0d8bca1f`, #2226 `42bd796c`, #2223 `9a4ad5ca`, #2228 `5f35bf8c`; follow-up #2250 | production `/api/status` build `5f35bf8c` (2026-11-18 ~12:20 UTC) | real-device iOS tap / VoiceOver check for #2223; post-deploy signed-in verification pending |
| 7 | Post-deploy trade and War Room smoke | P1 | DEPLOYED — smoke VERIFIED on production | #2242 → `c59c0a52` | V1 run 44331428925 against production `f5e06111`: trade smoke exit 0 — `analyze_2team` HTTP 200 (2 priced rows), `analyze_multi_3team` HTTP 200 (6 priced rows, rosters current); security acceptance pass | the same run's browser suite failed once: desktop War Room spec timeout (125 s) on a backend restarted 6 min earlier by the train-4 rollback; the mobile War Room spec passed in 41 s on the same build. Re-test on the next V1 run |
| 8 | Public-repo data-exposure remediation | P2 | DEPLOYED (guard) — BLOCKED — OWNER DECISION | #2249 → `522c0efc` | production `eb604ee2`; growth guard active as a blocking PR step | publication policy is an owner decision |
| 9 | Trade-flow resilience (frontend) | P2 | DEPLOYED | #2243 → `bd17e684` | production build `bd17e684` | service-worker update on real devices (iOS PWA) |
| 10 | Mobile ergonomics and 390 px coverage | P2 | DEPLOYED | #2245 → `eb604ee2` (train 5: RC 44330233614 + E2E 44330240357 green) | production `eb604ee2` (16:47 UTC) | 4-team tray clearance and info-tip tap accuracy need a real device |
| 11 | Restore Signals; loud private-source failure | P2 | IN PROGRESS (units 1–2 merged; diagnosis next) | #2237 → `3f647d16`; #2257 → `bb95f1e6` (RC 44347627363) | — | next: run the health probe once no deploy is in flight; two orphaned deploy runs still need a force-cancel |
| 12 | Live roster refresh — measure first | P2 | VERIFIED NO LONGER NEEDED (measured; owner may override) | #2246 → `6b0546a7` | measurement doc only; no runtime change | owner may override (median post-trade misattribution 1.1 h) |
| 13 | Security hardening batch | P2 | DEPLOYED | #2240 → `5f7e6080` | production `eb604ee2`; the box `.env` pre-flight ran and passed on deploys 44330192334 and 44345462077 | box `.env` is pre-checked against the target revision before the deploy moves anything |
| 14 | Next.js 16.4.5+ (#2233) | P2 | DEPLOYED | #2241 → `0dc1c6cd` | production build `bd17e684` | dependabot #2233 superseded |
| 15 | Make permanent-red / vacuous-green checks meaningful | P3 | DEPLOYED | #2247 → `123c08df`; #2253 → `83cc4061` (train 5) | production `eb604ee2`; CI-only change | 57 stale workflow registrations need an owner disable; #898 owner decision; E2E skip ceiling sits at exactly 70/70 on main |
| 16 | Node 20 → 22 | P3 | MERGED, then PARTIALLY REVERTED by hotfix #2256 (production lanes back on 20 until the box cutover) | #2252 → `79c60f26`; #2256 → `6f87d9d0` (RC 44340812140 green) | — | production runtime cutover BLOCKED — OWNER ACTION; engines `>=20 <23` until then |

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
Record (PR #2239, head `9f764920`):
- W30 rebuild-structure test reads the committed pinned board (`tests/fixtures/pinned_board`); W27 provenance test
  checks the committed fixture's recorded provenance; W06 identity regression reads a 22 KB extraction
  (`tests/fixtures/w06_f001_identity_rows.json`: names + has-id flag, source zip sha256 recorded). All pass with
  `…20261107_063955.zip` and `…20261106_194518.zip` moved out of `exports/archive`.
- Four checks in `tests/api/test_tracked_artifacts_privacy.py` that read a gitignored live ROS artifact (so could only
  skip in a checkout) are now `livedata`.
- Guard `tests/test_hermetic_gate_inputs.py` + `tests/hermetic_gate_scan.py` + `tests/hermetic_gate_allowlist.json`:
  static AST scan of blocking tests; fails on a new `exports/archive/<file>.zip` literal or a missing-data skip;
  90 existing files allowlisted with reasons; seeded-violation self-tests.
- apt-get (tesseract) wrapped in a 4-attempt retry in `deploy.yml`, `release-candidate.yml`, `pr-validation.yml`;
  still exits 1 after the last attempt.
- Skip inventory from deploy run 44234235112's shard manifests: 7 before → 3 after (4 ROS-artifact checks moved to
  livedata; remaining: a POSIX read-only-file case, one declared-exempt pbp call site, one unreachable Signals
  refusal path). Headroom 0 → 4.
- Failure census, last 40 failed deploys / 65 failed jobs: MCP roster test 16 (fixed #2199/#2208), heap-report loop
  11 (RSS, not data; none since 11-15), BDVM study 7 (fixed #2234), IDP Hampel challenger 5, CW40 batch 5,
  IDPTC cutoff 6 (all fixed #2208), FAAB calibration 2 and DLF offense-only 2 (none since 11-07), Hill alignment 2
  (fixed #2213), W30 1 (fixed here). No refresh-driven offender left unpinned.
- Tests: targeted 140 passed / 1 skipped (shallow-clone git-history check) / 1 xfailed; L1 not completed locally.
- Independent review blocker (fixed in `b23dc419`): the guard itself flagged bare archive names only when the file
  existed, so the ~11-21 prune would have turned it red; now data-independent, with `+`/`/` constant folding,
  archive-listing detection and broader skip-reason phrases (106 allowlisted files). Verified by the coordinator with
  both pinned zips deleted: 39 passed / 1 skipped (shallow-clone history check) / 1 xfailed.
- Train 2 (`claude/serene-shannon-7lsrm9-train2` = main `5f35bf8c` + #2239 + #2237): Release Candidate run
  44292795458 success (static/contract/frontend + 8 hard-gate shards). Merged 2026-11-18 ~11:58 UTC: #2239 →
  `cb5648ff`, #2237 → `3f647d16`.
- Follow-ups: `tests/scripts/test_w27_f005_te_skew_research.py` (export 20261106_194518) and
  `tests/idp_accuracy/test_backtest.py` (export 20260909_211525) still read real archive exports; both are their day's
  newest export, so retention keeps them 365 days.

### 2. Freshness and deploy-lag SLO — P0
Problem: no alert on "production N hours behind validated main" or "decision surface mostly withheld".
Record (PR #2238, head `e2bc2309`):
- `/api/status` gains `freshness_slo`: public numbers (top-200 stale / withheld shares, priced-withheld share, board
  age, private sources provisioned / stale / unknown) and an admin-only `privateSourceDetail` (anonymous projection:
  `"withheld"`). Missing inputs → `null` + `state: "unknown"`. Owner: `src/api/freshness_slo.py`.
- `scripts/check_production_slo.py` + `config/ops/production_slo.json`: deploy lag 12 h (only commits `deploy.yml`
  does not path-ignore), deploy failures (≥3 consecutive AND >12 h since a success), refresh 14 h, top-200 stale 10 %,
  priced-withheld 10 %, board age 18 h, stale private sources 0. OK / BREACH / UNKNOWN per rule; exit 0 / 1 / 3.
- `health-check.yml`: workflow `permissions: contents read, actions read`; new `slo` job; one rolling issue
  "Production SLO breach" (label `production-health`), body rewritten in place, a comment only when the breached set
  changes, closed on green.
- Backtest, 14 days hourly (337 samples): deploy_lag 132 alert-hours in 5 real episodes incl. 11-13 → 11-15 and
  11-17; deploy_failures 136; refresh 0 (median refresh gap 7.1 h, max 11.6 h). At 24 h lag the 11-17 incident would
  fire only in its last hour, so 12 h kept.
- Tests: 50 new passed; related deploy/diagnostics guards 112 passed; tests/ops + status/diagnostics/backup 530 passed.

### 3. Data delivery decoupled from the full code gate — P1
Problem: each data commit runs the 8-shard gate (~115 runner-minutes) and restarts the backend; 62% of data-triggered
deploys failed in the audit window versus 7% of code pushes. Activation changes an Agent OS rule, so the path ships in
shadow mode and production cutover waits for the owner.
Record (PR #2251 → `ecd2bc91`, merged in train 4):
- `scripts/classify_deploy_delta.py`: DATA_ONLY only if the last fully validated deployed commit is an ancestor and
  the code tree is byte-identical (mode + object id per path; data = regular files under `CSVs/`, `data/`,
  `exports/`; pickle-type files and anything else classify as CODE). Fail closed.
- `scripts/data_delivery_gate.py`: the data gate set (blocking: runtime import, contract FULL lane, tracked-data
  privacy; advisory: source health, live-data tests), with a 45 min set budget.
- `scripts/data_delivery_shadow.py` + `.github/workflows/data-delivery-shadow.yml`: read-only `workflow_run`
  observer on every completed Deploy Production run; records whether the data gate set agrees with the full gate.
  Contents/actions read only, no environment, no box contact, own concurrency group.
- Design and the exact Agent OS §3 amendment text: `docs/ops/DATA_ONLY_DELIVERY_DESIGN_2026-11-18.md`.
- Backtest (200 deploy runs, 138 classified): 23 DATA_ONLY; 14 passed the full gate, 9 failed it (7 data-coupled
  unit tests — the class #2239 pins — and 2 tesseract apt failures); none failed the contract lane.
- `deploy.yml`, `deploy.sh`, `scheduled-refresh.yml`, the server and the box are unchanged.
- Activation: BLOCKED — OWNER DECISION, after ≥30 compared DATA_ONLY deliveries over ≥14 days with zero unsafe
  disagreements.

### 4. Owner admin-action pack — P1
Problem: prepared required-checks ruleset never applied (live ruleset: deletion + non_fast_forward only); credential
rotation, off-box backup and deploy-key inventory pending since owner decision briefs #12–#14 (2026-11-08).
Record (PR #2244 → `ca698b11`, merged in train 4). Prepared, nothing applied:
- Branch protection: `deploy/github/main-protection-ruleset.json` pinned to required check names that exist (live
  host truth: `Validate PR`, `Receipt check`), refresh pushers keep bypass; `apply-branch-protection.sh --dry-run`
  diff; guard test `tests/deploy/test_ruleset_required_checks_pinned.py`.
- Credential rotation: runbook section in `docs/ops/ADMIN_ONLY_ACTIONS_RUNBOOK.md` (backup `.env`, set, restart,
  verify, rollback). Works with Task 13's startup guard.
- Off-box backup: `scripts/offbox_backup.py` (disabled unless configured; copies only a locally restore-verified
  generation; SHA-256 read-back; refuses unencrypted targets without an explicit ack and any target overlapping a
  source; restore drill) plus `deploy/backup/offbox/*.example` units. No provider chosen, nothing installed.
- Access inventory: what the agent could read (live ruleset 19976839 = deletion + non_fast_forward only, bypass for
  roles 4/5 and the deploy key); deploy keys, collaborators and secret presence are owner-readable only.
- Tests: 25 passed. Status: BLOCKED — OWNER ACTION for every privileged step.

### 5. Year boundary — P1
Problem: calendar-derived draft years and pick horizons (`draft_class_evidence.py:248`, `sleeper_overlay.py`,
`intel/service.py:140`) are untested across 2026-12-31 → 2027-01-02.
Record (PR #2248 → `ae310e03`, merged in train 4):
- Fake-clock harness `tests/fake_clock.py` (`--fake-now` / `RISKIT_FAKE_NOW`, off by default; no new dependency).
- `tests/identity/test_year_boundary_rules.py`: 25 cases at 2026-12-31T23:30Z, 2027-01-01T00:30Z,
  2027-01-02T12:00Z and 2027-01-01T03:00Z with `TZ=America/Los_Angeles`, board and league scope, expectations
  derived from the written rules.
- Sweep (134 clock-reading files): 28-29 failures per instant before → 0 after. One real test defect (a 2027-only
  draft-capital expectation) and fixture fixes in `test_metrics_engines.py` / `test_pick_projection.py`; 28 harness
  artifacts (subprocess / file mtime) listed with reasons in `config/ci/future_clock_exclusions.txt`.
- Production code: no year mis-statement found; no served value changes. `validate_api_contract.py --lane structural`
  rc=0 at every instant.
- Advisory workflow `.github/workflows/future-clock.yml` (weekly + dispatch, contents read, tests only).
- Owner decision (documented and pinned, not changed): the league draft window and the board pick horizon diverge at
  New Year — 2030 picks stay unpriced on the board until the 2027 draft is proven complete.

### 6. Five UI-fix PRs — P1
Record:
- Independent review (2026-11-18): MERGE for #2227, #2224, #2226, #2228; MERGE with a real-device check for #2223.
  Each defect re-confirmed on main (e.g. `ManualAddDrop.jsx:254` 120 ms blur timer and mouse/touch-only picks;
  `ros-trade-deadline.jsx:94` raw status; `angle/page.jsx` never reads `rosterCapacity`; `movers.js:70` coercion).
- Train `claude/serene-shannon-7lsrm9-t06-ui-train` `a27c176c` = `de63c768` + the five heads (order #2227, #2224,
  #2226, #2223, #2228), no conflicts. On it: decision-coercion gate 616/616 clean (main baseline 617 → 616 as
  intended); `npx vitest run` 446 files / 5795 passed / 3 expected-fail; `npm run build` exit 0 (first attempt hit Next
  16.4.3's build-time advisory `SecurityFatalError`, which is Task 14's); bundle, public-privacy and advisor-bundle
  checks pass (tightest headroom `/trade` 0.9 KB, `/league` 1.0 KB).
- Release Candidate run 44284022341: success. E2E Safety Net run 44284026751 ("Boot stack + run journeys"): success.
- Merged 2026-11-18 ~10:50 UTC in train order, each pinned to the exact head validated in the train (train parents
  checked equal to the PR heads): #2227 → `3945d0a2`, #2224 → `0d8bca1f`, #2226 → `42bd796c`, #2223 → `9a4ad5ca`,
  #2228 → `5f35bf8c`. Deploy runs: 44289141366 (`3945d0a2`) then 44289183586 (`5f35bf8c`); the three in between were
  superseded by the deploy concurrency group.
- Not verified here (need a real device): iOS Safari tap-to-pick and VoiceOver on the waivers pickers (#2223 drops
  `onTouchStart`; a tap now picks through compatibility click); phone test-push; a live auction room (#2228).
- Out of the train's scope: `/rankings` still has an operable "Sources in blend" popover saying "Unchecking a source
  removes it from the blended average" (`frontend/app/rankings/page.jsx:1528-1575`, `:254-292`, `:1776-1779`) and
  `frontend/lib/value-explainers.js:68`, although `_SOURCE_OVERRIDES_DISABLED = True`. `rankings/page.jsx` is touched
  by draft #2171 (Sports Network, owner-held); the fix is sequenced as a separate small PR.

### 7. Post-deploy trade / War Room smoke — P1
Problem: authenticated post-deploy verification never calls `/api/trade/analyze` or `/api/trade/analyze-multi`.
Record (PR #2242, head `1dfb1daf`):
- Finding while building it: both routes append a receipt to the box-local AL-P5 decision ledger
  (`data/trade/decisions/runs-YYYY-MM.jsonl`, via `src/trade/trade_decision_log.py::record_decision`) on every call, so
  a per-deploy smoke would have injected synthetic decisions into learning data. Fix: `X-Chase-Smoke: 1` is honoured
  only for guest-pass sessions and skips the receipt (per team on analyze-multi); any other session records as before.
- `scripts/smoke_trade_analysis.py`: builds a 2-team trade and a 3-team ring from each team's top priced player on the
  live board, asset-only mode; passes only on HTTP 200, a complete per-team schema, at least one priced asset, not
  every team UNAVAILABLE / NOT_ENOUGH_EVIDENCE, and the receipt skipped; named failure codes (`flag_off`,
  `all_withheld`, `data_not_ready`, `schema_drift:*`, `ownership_refused:*`, …).
- Wired into `v1-authenticated-verification.yml` on both triggers; blocking verdict; artifact `trade-smoke.json`.
- Tests: 241 passed in the targeted set, incl. an end-to-end run on the archived board through the real routes.
- Only a real post-deploy run can confirm the guest `/api/data?view=app` shape, header handling and latency.

### 8. Public-repo data exposure — P2
Problem: public repo tracks ~30 vendor CSVs and ~158 full-board export zips (with Sleeper owner IDs) while
`SECURITY.md` calls valuations private. No history rewrite, visibility change or purge without the owner.
Record (PR #2249 → `522c0efc`, merged in train 4):
- `scripts/audit_tracked_data_exposure.py`: read-only inventory over 12,554 in-scope tracked files (2.28 GB);
  aggregate committed as counts, field names, paths and vendors only
  (`docs/security/DATA_EXPOSURE_INVENTORY_2026-11-18.md` + `.json`).
- `docs/security/DATA_EXPOSURE_DECISION_BRIEF_2026-11-18.md`: owner decisions in its section 4 (vendor policy,
  owner-id policy, history rewrite, private repository, with an order-of-magnitude Actions-minutes estimate for a
  private repo). Only FantasyPros terms were located; other vendors are labelled "not verified".
- Growth guard: a blocking, diff-scoped PR step (`--changed-since origin/main`) fails on a NEW owner-id-bearing or
  paid-vendor tracked file; existing files are in `config/security/tracked_data_exposure_baseline.txt`. The
  real-tree scan is `livedata` (advisory); review fix made the hard-gate tests hermetic.
- Nothing deleted, untracked, moved or rewritten; visibility and refresh/deploy publishing unchanged.
- Status: BLOCKED — OWNER DECISION on the publication policy.

### 9. Trade-flow resilience — P2
Problem: plain errors without Retry on several trade routes; no client timeout on the contract fetch; the service
worker can answer API calls with HTML.
Record (PR #2243 → `bd17e684`, merged in train 3; deployed):
- `/trade`, `/arbitrage`, `/angle`, `/edge` render the shared `FailureState` with a working Retry (was a retry-less
  raw-error banner).
- Contract fetch: 25 s client deadline (`AbortController`) → retryable `timeout` failure; failed requests never cached.
- Service worker v11: `/api/*` cached by allow-list only (public league API); offline API answers are JSON 503, never
  the HTML shell; old caches evicted.
- `app/error.jsx` no longer prints `error.message`; new `not-found.jsx` and `global-error.jsx`.
- `/` no longer fires the private data pipeline (a guaranteed 401) for anonymous visitors.
- Production: deployed in `bd17e684`; on build `f5e06111` the prod-mobile War Room spec passed (41 s) — see Task 7 for
  the one desktop timeout. Not verified: service-worker update on a real iOS PWA.

### 10. Mobile ergonomics — P2
Problem: 32 px controls without coarse-pointer sizing; 390 px axe scans cover 12 route families.
Record (PR #2245 → `eb604ee2`, merged in train 5 with E2E fix #2253 → `83cc4061`):
- `ds.css` coarse-pointer / ≤480 px block: buttons, inputs, selects, tabs, segmented options, sort headers,
  disclosures, dialog close and info-tip triggers ≥44 px.
- 390 px axe coverage +11 route families on the phone projects.
- `mobile-target-size.spec.js` (tagged `@mobile-only`, filtered from desktop with `grepInvert`, so the E2E skip
  ceiling of 70 is not consumed).
- FAB clearance raised to 136 px when the N-team summary bar is present; nav / tray / FAB no-overlap test.
- #2253 fixed the two product bugs behind the E2E flakes (sheet focus stolen by a later animation frame; a team picked
  before `/api/leagues` answered was dropped).
- Validation: train 5 RC 44330233614 + E2E 44330240357 green. Not verified: real-device tap accuracy.

### 11. Signals and private-source alerting — P2
Problem: `signalsSf` stale ~16 days, votes withheld, no loud alert.
Record:
- 2026-11-18 10:12 UTC: dispatched the read-only `signals-health-probe.yml` (mode `health`); run 44283253164 refused
  "a deploy.yml run is in progress or queued" with nothing running. Cause: two `deploy.yml` runs GitHub created but
  never started — 32212914036 (queued since 2026-08-19, `workflow_dispatch` of `1d9a001c`) and 43096180672 (queued
  since 2026-11-11, push of `44a0d573`). The ordinary cancel API answers 409 for both; force-cancel is an owner action.
  Every on-box Signals run has been blocked the same way, which is why the stall could not be diagnosed.
- Unit 1, #2237: `scripts/deploy_in_flight.py` — one guard for both on-box workflows; never-started runs older than
  6 h are warned about instead of blocking; unreadable state fails closed. Tests: 78 passed, 1 skipped.
- Next: after #2237 merges, run the health probe and fix the actual cause.

### 12. Roster freshness — P2 (measure first)
Problem: `dynasty_main` rosters refresh only with the ~2 h scrape; the N-team engine needs rosters ≤ 6 h old. Whether
this causes real ownership refusals is unmeasured; no new polling without evidence.
Record (PR #2246, docs only, `docs/ops/ROSTER_FRESHNESS_MEASUREMENT_2026-11-18.md`):
- `dynasty_main` roster age at a random moment: p50 1.11 h, p95 2.04 h, max 2.14 h (four consecutive successful box
  scrapes 04:27–10:38 UTC, gaps 2.006 / 2.094 / 2.088 h, ~0.08 h publish lag; 200k-draw simulation). Engine refusal
  threshold 6 h → never stale in a healthy cycle. `dynasty_new`: request-driven overlay, 15 min TTL.
- 84 completed `dynasty_main` trades 2026-08-13 → 11-17 (7 in the last 30 days): pre-trade ownership is served for a
  mean 1.11 h after each; ≈1.1 % of wall-clock time has a pending trade.
- A 10–15 min light refresh would add ≈0.3 Sleeper req/min (≈0.03 % of the ~1000/min guidance); the real cost is a
  second writer of the contract `sleeper` block.
- Decision: not justified now. Revisit triggers: a refusal counter showing a material rate, scrape cadence relaxed
  beyond ~4 h, or owner reports of acting on stale post-trade ownership. Owner may override (the median exceeds the
  task's 30–60 min bar).

### 13. Security hardening — P2
Problem: placeholder password passes the startup guard; non-ASCII bearer token → 500; CSV formula injection;
anonymous `GET /api/health` can send the backup-alert email; workflows without `permissions:`.
Record (PR #2240, head `02e3a8f2`):
- One owner `src/api/startup_guards.py::startup_refusals`: placeholder / empty `JASON_LOGIN_PASSWORD` refused unless
  `ALLOW_DEFAULT_LOGIN_DEV`; with `RISKIT_ENV=production` (now set by `dynasty.service.template`) `E2E_TEST_MODE` /
  `ALLOW_DEFAULT_LOGIN_DEV` refused. `server.py` calls it at startup.
- Review blocker (fixed): the deploy must not restart into a refusing server. `deploy.sh::check_box_env_guards` now
  runs the TARGET revision's `startup_guards.py` (materialised with `git show`, stdlib-only) against the box `.env`
  (systemd-style parsing, last assignment wins) BEFORE the checkout moves, the frontend swaps or the backend restarts;
  it prints variable names only. (`python3 -I -m` would have refused every deploy — caught by a test.)
- Bearer routes compare bytes (`constant_time_equals`, `surrogateescape`); an empty configured token never matches.
- CSV: `neutralize_csv_text` prefixes `'` to text starting with `= + - @` (after leading whitespace/control) or a
  leading tab/CR; numbers stay numbers; the auction export uses the same owner. DFS DraftKings uploads unchanged.
- `/api/health` has no side effects; a `backup_watchdog_loop` (6 h tick, existing `send_alert` cooldown) sends the
  stale-backup email.
- Workflows: `contents: read` on `pr-validation.yml`, `smoke-test.yml`, `prod-e2e-smoke.yml`; `permissions: {}` on
  `public-league-warmup.yml`; `E2E_TEST_SECRET` masked in `e2e.yml`.
- Tests: 22 new tests fail on main and pass on the PR; box-env guard 16 tests; deploy suites pass.
- Follow-ups: pin `anthropics/claude-code-action` to a verified SHA (repo not readable from this session);
  `permissions:` for `health-check.yml` (done in #2238) and `deploy.yml`.

### 14. Next.js upgrade — P2
Record (PR #2241 → `0dc1c6cd`, merged in train 3; deployed): `next` 16.4.3 → 16.4.5 (fixes
GHSA-mfr8-8qww-v76h and GHSA-vc7v-qv4w-wrv8, both moderate; 16.4.5 published 2026-11-03). Supersedes Dependabot
#2233. Build, bundle budgets and E2E green in train 3; production build `bd17e684` serves it.

### 15. Meaningful CI checks — P3
Problem: Rank-Form Curve Drift red 13 weeks running (#898); Sharp population check passes without measuring (#1727);
dead `_tmp_*` workflow registrations.
Record (PR #2247 → `123c08df`, merged in train 4; plus #2253):
- Audit Rank-Form Curve Drift: the accepted drift state is recorded (`config/ci/rank_form_drift_accepted.json`,
  margin 25), so the check is green at the accepted level and red only if drift grows past it — a tripwire instead of
  a permanent red. #898 stays an owner decision.
- Verify Sharp Production Population: a separate "measured" job runs only when the smoke actually measured and
  passed; an unmeasured run shows SKIPPED rather than green.
- `docs/ops/STALE_WORKFLOW_REGISTRATIONS_2026-11-18.md`: 57 registered workflows with no file on `main`, with the
  exact owner disable command (needs `actions:write`; not run).
- 13 scheduled workflows swept; no further vacuous-green case found.

### 16. Node 22 — P3
Problem: Node 20 (`engines >=20 <21`, every workflow) is past end of life; blocks jsdom/jest-dom/axe upgrades.
Record (PR #2252 → `79c60f26`, train 4; hotfix #2256 → `6f87d9d0`):
- #2252 moved every workflow and `.nvmrc` to Node 22 and widened `engines.node` to `>=20 <23`.
- Deploy 44330192334 then failed at box staging: `stage_release_artifact.py` requires the artifact's Node major to
  equal production's (20). Auto-rollback kept production serving.
- #2256 puts the production-runtime lanes (deploy, release candidate, PR validation, E2E) back on Node 20, pinned by
  `tests/deploy/test_deploy_node_matches_production.py`; other workflows stay on 22. The cutover doc now describes
  one coordinated change (box runtime + those lanes in the same window).
- Status: CI partially on 22; production runtime cutover BLOCKED — OWNER ACTION.

## Integration log

- Train 1 (UI): RC 44284022341 + E2E 44284026751 green → #2227/#2224/#2226/#2223/#2228 merged ~10:50 UTC; deployed
  (`5f35bf8c`, deploy 44289183586 success).
- Train 2: `main 5f35bf8c + #2239 + #2237`, RC 44292795458 green → merged ~11:58 UTC (`cb5648ff`, `3f647d16`).
- Train 3: `main 3f647d16 + #2238 + #2241 + #2242 + #2243` (`64fda809`), RC 44299420115 + E2E 44299425175 green;
  main moved only by two class-C refresh commits (`0e330a59`, `28092bf6`: `data/scrape_state/*`) → merged ~12:42 UTC
  (`4a80cca8`, `0dc1c6cd`, `c59c0a52`, `bd17e684`).

- Train 4a (`main bd17e684 + #2240 + #2246 + #2248 + #2250`): E2E 44313606560 green; RC 44313601524 REFUSED by the
  HEAD-FREEZE gate — 88 class-C changes landed on main mid-validation (refresh `3922bc9f`, stamps `0c63b29d`, Hill
  evidence `8f12ffb3`). Per the release rule the base was integrated once: combined train 4 (`ed388854` = main
  `8f12ffb3` + #2240, #2246, #2248, #2250, #2244, #2247, #2249, #2251, #2252; all merge cleanly; locally 1,922
  passed / 4 skipped across tests/deploy, tests/governance, the hermetic guard and the security / year tests).
- Combined train 4 RC 44323437798 + E2E 44323443564 green; main moved afterwards only by box-pushed class-C data
  (`f5e06111` CSVs/site_raw + scrape_state, `a4ae4377` scrape_state). Merged ~14:55 UTC in order: #2240 `5f7e6080`,
  #2246 `6b0546a7`, #2248 `ae310e03`, #2250 `58278641`, #2244 `ca698b11`, #2247 `123c08df`, #2249 `522c0efc`,
  #2251 `ecd2bc91`, #2252 `79c60f26`. This deploy is the first to run the box `.env` pre-flight (#2240).
- Train 5 (`main 79c60f26 + #2253 + #2245`, `fc94e30a`): RC + E2E dispatched.
- Deploy `bd17e684` succeeded (~14:06 UTC); the superseded `3f647d16` deploy was cancelled before its production step.

- **Incident 2026-11-18 ~15:20 UTC — deploy blocked by the Node 22 CI move (#2252).** Deploy Production 44330192334
  (`79c60f26`, train 4) failed at box staging: `scripts/stage_release_artifact.py` refuses an artifact built on a
  different Node major than production ("release Node major version differs from production"); CI built on 22, the
  box runs 20. Auto-rollback restored `f5e06111` (production kept serving; services restarted once). The box `.env`
  pre-flight from #2240 ran first and PASSED (no placeholder password, no test switches on the box). Fix: #2256
  restores Node 20 on deploy / release-candidate / PR-validation / E2E, pins it in
  `tests/deploy/test_deploy_node_matches_production.py`, and makes the cutover one coordinated change (box + lanes).
  Train 5 (#2245 + #2253; RC 44330233614 + E2E 44330240357 green) is held until #2256 merges so they ship in one
  deploy.
- Signals probe (Task 11): the deploy-in-flight guard now passes ("no deploy in flight (2 orphaned run(s)
  ignored)"); the probe ran on the box (run 44339687295) but its fail-closed public projection withheld the whole
  report (`{"error": "PublicLeak"}`) because a free-text leaf (likely the source's error text) is not public-safe.
  Fix: PR #2257 (unsafe leaves replaced by `withheld_unsafe_value`, path recorded under `redacted`; `errorClass` vocabulary; systemd `Result` normalised, e.g. `exit-code` -> `exit_code`, the most likely tripped leaf). Takes effect after merge + deploy; then re-run the probe to diagnose `signalsSf`.

- 16:16 UTC: merged #2256 (`6f87d9d0`, RC 44340812140 on base `4790727e` = main at merge), then train 5 #2253
  (`83cc4061`) and #2245 (`eb604ee2`). Main drift since train 5's validated base `79c60f26` was #2256 only (CI Node
  version; no shared files). Superseded deploy 44345387765 (`6f87d9d0`) cancelled at "Resolve Deploy Target", before
  any production step; deploy 44345462077 (`eb604ee2`) carries all three.

- 16:47 UTC: Deploy Production 44345462077 succeeded; production `/api/status` `build.commit` = `eb604ee2`
  (all of trains 1–5 plus hotfix #2256). `freshness_slo`: top-200 stale 0/200, priced withheld 3/1016, board scraped
  16:46 UTC. The box `.env` pre-flight (Task 13) passed again. Task 3's shadow observer ran for real on the previous
  deploy (run 44339329955): resolved target `79c60f26` / base `f5e06111` from the deploy logs and classified the delta
  CODE (78 paths, 74 code) — correct, fail-closed; it is running again for this deploy.

## Operational notes

- 2026-11-18 ~11:40 UTC — CI runner saturation: ~10 concurrent PR CI runs (8 shards + E2E each) left Deploy Production
  and the train-2 Release Candidate queued. Nine queued PR Validation / E2E runs were cancelled (re-run later, two or
  three at a time): #2244, #2245, #2246, #2247, #2248, #2250 (#2240 / #2249 get fresh runs on their next push).
- E2E Safety Net on main sits at exactly its skip ceiling (70 skipped, ceiling 70): any new deliberately gated test
  breaks it. #2245 filters its phone-only suite with `grepInvert` instead of skipping it.
- E2E flakes root-caused (#2253): the TC-E sheet re-focused its search field on a later animation frame, stealing
  focus from Done (WebKit, ~8 % of mobile-390 attempts); `useTeam.setSelectedTeam` silently dropped a team picked
  before `/api/leagues` answered (the War Room then read "Pick your team"). Both are product bugs, fixed in the
  components with unit tests.
- `tests/api/test_run_scraper_nonblocking.py::test_event_loop_stays_responsive_during_each_fetch_main[scripts.fetch_fantasypros_idp]`
  failed once on #2238 (0.44 s vs 0.35 s bound) and passed on the single permitted re-run — an intermittent timing test
  under runner load; candidate for Task 15's follow-up list.

## Owner actions (consolidated, kept current)

1. Task 4 — apply `deploy/github/main-protection-ruleset.json`; rotate the production login credential; choose an
   off-box backup destination; confirm the deploy-key inventory.
2. Task 3 — approve or decline the Agent OS amendment that lets a byte-identical code tree reuse its validation.
3. Task 8 — choose a publication policy for vendor CSVs and board exports.
4. Task 11 — if Signals' session expired, re-authenticate on the box.
5. Task 16 — authorize the production Node runtime cutover.
6. Task 11/15 — force-cancel the two orphaned Deploy Production runs 32212914036 and 43096180672 in the Actions UI
   (the API's ordinary cancel refuses them; the force-cancel call was not permitted from this session). The August run
   would deploy a three-month-old SHA if GitHub ever started it.
