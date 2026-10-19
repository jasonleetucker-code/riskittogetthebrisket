# Development Tracker — live implementation state

**Owner directive:** "MAXIMUM VELOCITY DEVELOPMENT DIRECTIVE" (2026-10-19), Directive 8.
**Purpose:** one live board for what is being built, by which worker, on which branch, in which state. Product authority stays with `docs/EXECUTION_PLAN.md`. Scope rows and acceptance criteria live in `docs/COMPLETION_QUEUE.md` (CQ ids, arriving on `main` with release train 12). This file records *state* only, so the two cannot disagree about scope.

**States:** QUEUED · IMPLEMENTING · IMPLEMENTED / UNVALIDATED · VALIDATING · CI FAILING · READY FOR REVIEW · BLOCKED · MERGED · DEPLOYED / VERIFIED.

**Rules in force (owner, 2026-10-19).**
- Independent features build in parallel, in isolated worktrees and branches, with focused tests during development. Full validation runs at integration: release train, release check, Validate PR, E2E.
- **Standing merge authorization (owner, 2026-10-19, superseding Rule E's per-merge approval).** The Integration Authority merges any PR whose required checks are green on the exact head, whose implementation is complete, whose reviews are satisfied and which has no unresolved dependency or conflict, without asking. Merging to `main` runs the existing automated deploy pipeline. Still owner-only: production model or source activation, security, spending, and other consequential changes. Canonical text: PR #1839, landing in `docs/AGENT_OPERATING_SYSTEM.md` §3 and `ASSISTANT_COORDINATION.md`.
- A partially built feature must not change production behaviour; use flags or isolation.
- Valuation formulas, voting eligibility and Value Adjustment change only under their documented invariants and acceptance tests.
- Source ingestion and voting activation are separate milestones.
- No CI shortcut: no deleted tests, no suppressed errors, no weakened acceptance.
- League Tycoon and DFS stay shelved.

Committed is not merged; merged is not deployed; deployed is not verified.

Last updated: 2026-10-19 22:55 UTC (coordinator).

## Release vehicles

| Vehicle | Members | State | Next action |
|---|---|---|---|
| Train 11 (#1829) | #1822 playoff odds follow the roster; #1823 mobile Trade Tendencies partner | DEPLOYED (`a9f3918808`, 10:04 UTC). Playoff sections still serve a pre-deploy cached forecast (05:27) | Re-probe after the next ROS refresh; check `/trades` on mobile |
| Train 12 (#1836) | #1826, #1827, #1830, #1828, #1834, #1837 + integration commit + the side-search race fix | **MERGED** `f3e24b3470` (22:38). Release check, Validate PR and E2E were all green on `bc976ce80b`; `main` had moved by data only. Deploy Production 39336343547 is running. The 20:19 deploy had failed on that same race, so production still runs the earlier build until this one lands | Verify production; record the automatic V1 run |
| Train 13 (#1857) | #1839 (with integration fixes), #1838, #1840, #1845, #1841, #1846, #1844, #1848, directive records | VALIDATING: head `00ef6631e3`, release check dispatched 22:45 | Merge when green |
| #1832 CI budget 80→120 min | — | MERGED (`2d854f7523`) | Rides the next deploy |

## Features

| Feature (CQ) | Worker | Branch | PR | Dependencies | State | Known issues | Next action |
|---|---|---|---|---|---|---|---|
| War Room plain English (CQ-05) | War Room lane (done) | `claude/trade-war-room-clarity` | #1827 (in train 12) | — | VALIDATING (train 12) | — | Production checks after deploy |
| VA comparison + Second Opinions (CQ-06) | VA lane (done) | `claude/trade-dual-va-comparison` | #1826 (in train 12) | — | VALIDATING (train 12) | — | Production checks after deploy |
| Analyze speed + timing (CQ-03) | Perf lane (done) | `claude/trade-analyze-speed` | #1828 (in train 12) | — | VALIDATING (train 12) | Production latency unmeasured | Measure `Server-Timing` on prod |
| Power Rankings roster-11 hand-off (CQ-09) | CQ-09 lane (done) | `claude/power-rankings-current-franchise` | #1834 (in train 12) | #1822 | VALIDATING (train 12) | Time-sensitive: week-6 publication | Deploy before Monday-night final |
| V1 authenticated verification (Priority #1, CQ-16) | V1 lane (done) | `claude/v1-verification-session-survival` | #1837 (in train 12) | — | VALIDATING (train 12) | Why prod wedged at 08:42Z; 2030 horizon (owner); sharp-tracker timeout; W1-28 field | Next automatic V1 run after deploy |
| Records + completion queue (CQ-17) | Coordinator | `claude/completion-queue-records-2026-10-19` | #1830 (in train 12) | — | VALIDATING (train 12) | — | — |
| Source voting rework per 2026-10-19 directives (CQ-01, CQ-10, CQ-18) | Source-voting lane (done) | `claude/idp-source-independence` | #1817 | DLF IDP restore held at release until the outlier interaction is fixed | IMPLEMENTING (W9): re-applying the DLF IDP hold as a temporary, labelled hold; merging `main`; fresh board evidence. All other #1817 changes stay (D2/D3 deleted, D4 and D5 ON, two-way fix) | Under the current outlier filter, the DLF IDP restore drops 31 valid Draft Sharks / FantasyPros / IDP Trade Calculator votes on 30 rows (7 moves of 34–54%) | Train 13 after W9 reports |
| Universal freshness schedule + voting status (CQ-64) | Freshness lane | `claude/universal-freshness-schedule` | #1831 | — | CI FAILING (`f24c09aff8`: Signals stale-vote test KeyError; IDP anchor-chain test) | Root-cause pending | Full local suite, then push |
| IDP outlier filter (CQ-65) | Outlier lane | `claude/outlier-filter-disagreement` | — (PR soon) | — | IMPLEMENTED / UNVALIDATED: flag `outlier_disagreement_policy`, default OFF. Keeps all 31 dropped votes, but **fails its preregistered adversarial gates** (AD1b 58% vs 90%, AD1d 92.6% vs 95%, AD2 15% vs 90%), so the verdict is NOT ELIGIBLE | Owner decision needed: activate anyway, preregister a v2, or accept the explained moves | PR with flag OFF plus the evidence |
| Source voting transparency UI (CQ-66) | W1 (done) | `claude/source-voting-transparency-ui` | #1846 | #1831 payload (renders an honest "not available" state until then) | READY FOR REVIEW (`e3b0ed6f5c`). `/trades` bundle budget 26→32 KB, a chunk relocation measured by the worker | Live data waits on #1831 | Train 13 |
| Screenshot import remainder (CQ-11) | W2 (done) | `claude/screenshot-import-cq11` | #1841 | — | READY FOR REVIEW: 242 screenshot tests and 69 vitest passing locally; side alignment by label; mobile/dark fixtures; the owner's Dart/Achane case pinned three ways; prod-auth status spec | CQ-12 needs a member session; privacy check on the `ktc_fullpage_browser` fixture (owner) | Train 13 |
| Production restart root cause (ops) | W3 (done) | `claude/prod-wedge-diagnostics` | #1845 | — | READY FOR REVIEW. Diagnostics ran once (run 39241251979): the liveness watchdog's 3-strike restart; the event loop was silent 08:40–08:41; SIGTERM timed out, then SIGKILL; no OOM; peak 2.6G against MemoryHigh 2.5GiB. The PR also takes `send_alert` off the event loop (a defensive fix: SMTP with no timeout) | Memory pressure → W8 | Train 13 |
| Default-league workbook pick ownership fail-closed | W4 (done) | `claude/workbook-pick-ownership-fail-closed` | #1840 | — | READY FOR REVIEW: the fix already shipped in #1785 (train 6); this PR adds 13 contract tests plus doc fixes, and changes no behaviour | Follow-ups below | Train 13 |
| Brisket Trade Advisor (public League Hub) | Audit workflow → build workers | — | — | Audit and design | IMPLEMENTING (Phase 1 audit) | — | Launch backend + frontend workers from the final design |
| Signals Fantasy IDP voting, DL/LB/DB per family | Audit workflow → build workers | — | — | On-box evaluation; #1817 / #1831 / outlier lane overlap | IMPLEMENTING (audit / root cause) | Private data is box-local | Preregister candidates; on-box diagnostics |
| Chase Upside Trade Market (`chaseTradeMarket`) | Audit workflow → build workers | — | — | On-box data census | IMPLEMENTING (Milestone 1 audit) | Trade data is box-local | On-box census; maturity lineage; shadow model |
| League intelligence & trade decision engine (owner directive 2026-10-19, evening) | Workflow: 8 readers → design → 2 critics → 5 implementers → 5 reviewers | `claude/li-scoring`, `claude/li-valuation`, `claude/li-bestball`, `claude/li-decision`, `claude/li-integration` | — | Records in train 13 | IMPLEMENTING | A league-aware canonical value needs preregistered gates plus owner approval; everything else is behind flags or in shadow | Batch-1 PRs |
| League audit PR #1843 (owner / codex) | — | `audit/league-intelligence-evidence-2026-10-19` | #1843 | — | CI FAILING (Validate PR) | Root cause being read by the league workflow | Fix, then train |
| Train 14 (planned) | #1817 (DLF IDP held; CI running), #1849 a11y, #1850 CI health, #1847 outlier (flag OFF), #1851 and #1852 Trade Market, #1853 Advisor engine repairs (fixing a CI regression; reconcile with train 12's analyze rewrite), #1854 Signals pre-registration and verifier | — | — | Train 13 merged | QUEUED | — | Build after train 13 |
| Follow-ups found tonight | Rookie-board fallback should refuse rather than vote untranslated ranks (outlier lane); `test_overview_memo` depends on local data age; the third Sleeper player-dump parse; overlay cache holds raw and gzip copies; `timeout_graceful_shutdown`; production restart diagnostics should also list `dynasty-*` units; a parallel hard-gate trial; 3 screens use unstyled `btn btn-secondary` | — | — | — | — | QUEUED | — | Next waves |
| War Room server phases (CQ-20) | — | — | — | Train 12 (#1828 status endpoint) | QUEUED | — | Start after train 12 merges (touches `/trade`) |
| `/trade` pick-ownership unknown state | — | — | — | Train 12 (`/trade` files) | QUEUED | — | Start after train 12 merges |
| Calculator correctness parity tests (CQ-21) | — | — | — | — | QUEUED | — | Next wave |
| Production memory pressure (peak above MemoryHigh under verification load) | W8 | `claude/prod-memory-pressure` | — | — | IMPLEMENTING | — | PR: bounded caches, no output change; evidence-based unit limits |
| Accessibility defects (CQ-30) | W6 | `claude/a11y-cq30` | — | `/trade` hover tint deferred until train 12 lands | IMPLEMENTING | — | PR |
| Scheduled workflow health (CQ-29) | W7 | `claude/scheduled-ci-health-cq29` | — | — | IMPLEMENTING | No box SSH; unit checks go to W3's diagnostics | PR |
| Workbook refusal reason precision (`sleeper_unreachable` vs `traded_picks_fetch_failed` when Sleeper fails before `/traded_picks`) | — | — | — | — | QUEUED | Shipped wording; the change is small | Next wave |
| Workbook keeps hand-entered reassignments Sleeper does not report (an observed `[]` overrides nothing) | — | — | — | — | QUEUED (investigate) | Sleeper should be the system of record | Verify, then fix |
| League pick window follows the same rule (`league_draft_years` uses calendar year + 3 classes, so it would show 2030 from 2027-01-01, before the 2027 draft) | — | — | — | #1844 merged | QUEUED (must land before 2027-01-01) | Found by W5 | Switch the league window to its last completed draft + 3 |
| Derived pick rows must not publish `ktcMarket.available` or high confidence (latent until 2030 is added) | — | — | — | #1844 merged | QUEUED (before the 2027 draft completes) | Found by W5; fix sketched in #1844 | Implement and test |
| Stale WORK_CLAIMS rows: Draft Valuation Batch E/F/G still read "active — PR open" | — | — | — | — | QUEUED | Records only | Fold into the next records pass |
| Pick horizon = last completed rookie draft + 3 (owner decision 2026-10-19: no 2030 until the 2027 draft completes) | W5 (done) | `claude/pick-horizon-completed-draft-plus-3` | #1844 | — | VALIDATING (`3d1be615c6`; CI running; in train 13). One owner, `board_pick_horizon`. Board diff: the 24 rows for 2030 go; 57 values rise (median +0.1%, max +1.4%); 0 fall. The rises come from removing the 2030 rows, which had been leaking into the rookie ladder; the leak is fixed in its own commit | Latent: derived rows will claim market/high confidence once 2030 is added (around May 2027) | Train 13 |

## Shelved / not to revive
League Tycoon (#1755 parks ideas only), DFS implementation, the premature 2027 rookie auction, paid data and paid inference, and Sleeper writes.
