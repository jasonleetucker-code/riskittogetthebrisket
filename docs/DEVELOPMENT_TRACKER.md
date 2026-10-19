# Development Tracker — live implementation state

**Owner directive:** "MAXIMUM VELOCITY DEVELOPMENT DIRECTIVE" (2026-10-19), Directive 8.
**Purpose:** one live board for what is being built, by which worker, on which branch, in which state. Product authority stays with `docs/EXECUTION_PLAN.md`. Scope rows and acceptance criteria live in `docs/COMPLETION_QUEUE.md` (CQ ids, arriving on `main` with release train 12). This file records *state* only, so the two cannot disagree about scope.

**States:** QUEUED · IMPLEMENTING · IMPLEMENTED / UNVALIDATED · VALIDATING · CI FAILING · READY FOR REVIEW · BLOCKED · MERGED · DEPLOYED / VERIFIED.

**Rules in force (owner, 2026-10-19).**
- Independent features build in parallel, in isolated worktrees and branches, with focused tests during development. Full validation runs at integration: release train, release check, Validate PR, E2E.
- **No merge to `main` without the owner's explicit approval** (Rule E). `main` deploys automatically, so merging is releasing.
- A partially built feature must not change production behaviour; use flags or isolation.
- Valuation formulas, voting eligibility and Value Adjustment change only under their documented invariants and acceptance tests.
- Source ingestion and voting activation are separate milestones.
- No CI shortcut: no deleted tests, no suppressed errors, no weakened acceptance.
- League Tycoon and DFS stay shelved.

Committed is not merged; merged is not deployed; deployed is not verified.

Last updated: 2026-10-19 10:20 UTC (coordinator).

## Release vehicles

| Vehicle | Members | State | Next action |
|---|---|---|---|
| Train 11 (#1829) | #1822 playoff odds follow the roster; #1823 mobile Trade Tendencies partner | DEPLOYED (`a9f3918808`, 10:04 UTC). Playoff sections still serve a pre-deploy cached forecast (05:27) | Re-probe after the next ROS refresh; check `/trades` on mobile |
| Train 12 (#1836) | #1826, #1827, #1830, #1828, #1834, #1837 + integration commit; main merged once (#1832) | VALIDATING: release check dispatched on `e25b226724` (120-min budget) | When green: **owner approval to merge**, then deploy before the week-6 Power publication (after Monday night) |
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
| Source voting rework per 2026-10-19 directives (CQ-01, CQ-10, CQ-18) | Source-voting lane | `claude/idp-source-independence` | #1817 | Coordinate with #1831 (flag lines) | IMPLEMENTING (rework pushed `7f4153c089`) | Earlier head was red on the hard gate | Green CI, scenario evidence, all-flags-off parity |
| Universal freshness schedule + voting status (CQ-64) | Freshness lane | `claude/universal-freshness-schedule` | #1831 | — | CI FAILING (`f24c09aff8`: Signals stale-vote test KeyError; IDP anchor-chain test) | Root-cause pending | Full local suite, then push |
| IDP outlier filter (CQ-65) | Outlier lane | `claude/outlier-filter-disagreement` | — | — | IMPLEMENTING | — | Preregistered challenger behind a flag, default OFF |
| Source voting transparency UI (CQ-66) | W1 | `claude/source-voting-transparency-ui` | — | #1831 payload (renders an honest "not available" state until then) | IMPLEMENTING | — | PR |
| Screenshot import remainder (CQ-11) | W2 | `claude/screenshot-import-cq11` | — | — | IMPLEMENTING | Production proof needs a member session (CQ-12) | PR |
| Production wedge diagnostics (ops) | W3 | `claude/prod-wedge-diagnostics` | — | — | IMPLEMENTING | Needs the box journal | PR; coordinator runs read-only diagnostics once |
| Default-league workbook pick ownership fail-closed | W4 | `claude/workbook-pick-ownership-fail-closed` | — | — | IMPLEMENTING | `/trade` `team.picks \|\| []` is a separate follow-up | PR |
| Brisket Trade Advisor (public League Hub) | Audit workflow → build workers | — | — | Audit and design | IMPLEMENTING (Phase 1 audit) | — | Launch backend + frontend workers from the final design |
| Signals Fantasy IDP voting, DL/LB/DB per family | Audit workflow → build workers | — | — | On-box evaluation; #1817 / #1831 / outlier lane overlap | IMPLEMENTING (audit / root cause) | Private data is box-local | Preregister candidates; on-box diagnostics |
| Chase Upside Trade Market (`chaseTradeMarket`) | Audit workflow → build workers | — | — | On-box data census | IMPLEMENTING (Milestone 1 audit) | Trade data is box-local | On-box census; maturity lineage; shadow model |
| War Room server phases (CQ-20) | — | — | — | Train 12 (#1828 status endpoint) | QUEUED | — | Start after train 12 merges (touches `/trade`) |
| `/trade` pick-ownership unknown state | — | — | — | Train 12 (`/trade` files) | QUEUED | — | Start after train 12 merges |
| Calculator correctness parity tests (CQ-21) | — | — | — | — | QUEUED | — | Next wave |
| Accessibility defects (CQ-30) | — | — | — | — | QUEUED | Exclude `/trade` until train 12 merges | Next wave |
| Scheduled workflow health (CQ-29) | — | — | — | — | QUEUED | — | Next wave |
| 2030 pick horizon | — | — | — | **Owner decision** | BLOCKED | Board shows 2030 rows after the vendor slot roll; the 2026-09-25 decision requires owner approval | Owner: keep 2029 or allow 2030 |

## Shelved / not to revive
League Tycoon (#1755 parks ideas only), DFS implementation, the premature 2027 rookie auction, paid data and paid inference, and Sleeper writes.
