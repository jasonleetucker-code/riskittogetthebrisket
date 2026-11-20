# Closeout implementation record — 2026-11-20

Follow-up to `docs/audits/PRODUCTION_STABILIZATION_2026_11_19.md`. That record stays as written; this one tracks
the 2026-11-20 owner directive "Master implementation directive — complete all remaining work".

**Authority.** Intake: `docs/OWNER_REQUESTED_TODO.md` (2026-11-20). Authorization: `docs/EXECUTION_PLAN.md` (top
section). Owner-only gates, unchanged:
- credentials;
- backup destination and spend;
- repository visibility and history;
- data-publication policy;
- the production Node cutover;
- data-only deploy activation;
- the 2030 pick policy;
- valuation, source-voting and flag changes.

**Process.**
- Up to four concurrent agents, as the directive says.
- Wave 1 ran as an isolated-worktree workflow: implement → independent review → fix.
- The workflow engine caps concurrency at 2 on this 4-CPU host.

**Statuses:** NOT STARTED · IN PROGRESS · PR OPEN · MERGED · DEPLOYED · VERIFIED COMPLETE · OWNER ACTION REQUIRED ·
EXTERNAL BLOCKER · VERIFIED NOT NEEDED. A status is set only from evidence.

## Starting state (measured 2026-11-20 ~12:30 UTC)

- `origin/main` `5ae4299c`; production `build.commit` `b90a88c0` (data deploys since `58424f58`).
- `freshness_slo`: private sources stale 4 of 4.
- Scheduled refresh red since 2026-11-19 03:50 UTC on "Assert DLF freshness".
- Open PRs from the previous program: #2274 (worker cap, merged 12:42 UTC) and #2271 (Node 22, HOLD).
- Read-only understand pass (workflow `wf_285342a1-685`, 4 agents) reconciled the 16-task audit and mapped:
  - DLF rookie semantics;
  - alert coverage;
  - CI reliability.

  Its per-item findings drive the ledger below.

## Task ledger

| # | Priority / task | Status | Root cause | Implementation | PR → commit | Tests / CI | Production verification | Blocker | Next action |
|---|---|---|---|---|---|---|---|---|---|
| 1 | P0 DLF rookie boards | PR OPEN | Vendor publishes no rookie rankings since 2026-11-17 22:27 UTC: same RankingEngine table, 0 rows, 0 expert columns (Superflex: 287 rows, 6 experts). Not a parser defect. | `vendor_empty` label (rookie boards only; run still exits 1); last-good kept; per-board state file; fail-closed rookie class guard; dead shell guard fixed; probe trimmed | #2275 | 223 targeted tests; first review's B1, B2 and I1–I4 addressed, re-review running | pending deploy: box journal + `dlf_board_states.json` | owner decision on the stale `dlfRookieSf` vote (§1) | re-review → release candidate → merge → deploy → verify |
| 2 | P1 alert delivery | IN PROGRESS | No owner channel; plus code gaps (wave 1) | wave 1 alerts-box + alerts-workflows | — | — | — | owner: ntfy topic and secret | integrate wave 1 |
| 3 | P1 branch protection | OWNER ACTION REQUIRED | Live ruleset 19976839 has no required checks | dry run re-verified 2026-11-20; apply attempted | — | `test_main_protection_ruleset.py` 6/6 | the API write was refused (§3) | owner runs the script | — |
| 4 | P1 Signals | OWNER ACTION REQUIRED | Session `reconnect_required` (probe 44532781512) | — | — | — | 4/4 private sources stale | owner reconnect on own computer, then provision | verify after reconnect |
| 5 | P1 Node 22 | OWNER ACTION REQUIRED | Box runs Node 20 (system install) | #2271 to be refreshed against main | #2271 (HOLD) | — | — | owner installs Node ≥22.12 | refresh #2271 |
| 6 | P1 off-box backups | OWNER ACTION REQUIRED | All generations on one disk | design + stale-copy alert (#2264, deployed) | — | — | `offbox_copy` row live, silent until configured | B2 approval and keys | backup-age alert work (wave 2) |
| 7 | P2 credentials | OWNER ACTION REQUIRED | rotation is owner-only | inventory + `check_login_status.py` (#2263); `startup_guards.startup_refusals` refuses empty or placeholder `JASON_LOGIN_PASSWORD` | — | — | — | owner rotation | — |
| 8 | P2 public-repo data | OWNER ACTION REQUIRED (decision) | policy | recommendation + guard gap closed (#2262) | — | — | — | owner decision | — |
| 9 | P2 mobile / browser | IN PROGRESS | gaps in touch-target coverage | wave 1 frontend-hardening | — | — | — | physical iPhone checklist | — |
| 10 | P2 Ubuntu apt | NOT STARTED | archive 503 / stalled mirror on 2026-11-19 | wave 2: verified `.deb` cache + Playwright deps through the installer | — | — | — | — | — |
| 11 | P2 zombie run 43096180672 | EXTERNAL BLOCKER | GitHub-side zombie: queued since 2026-11-11, 0 jobs | rechecked 2026-11-20: cancel answers HTTP 409 "has not been queued yet"; delete answered 403 on 2026-11-19 | — | — | deploy-in-flight guard ignores it as "never started" | GitHub support or owner UI | — |
| 12 | P2 Sharp smoke token | IN PROGRESS / OWNER | honest "not measured" since T15 | wave 1: measure only after deploy commit | — | — | — | owner provisions `SHARP_SMOKE_TOKEN` | — |
| 13 | P2 2030 pick policy | OWNER ACTION REQUIRED (decision) | league window vs board horizon | prototype `d5b8161d` | — | — | — | decision before 2027-01-01 | — |
| 14 | P2 data-only activation | EXTERNAL BLOCKER (time) | evidence bar not met | observer automatic since #2272 | — | — | 17 compared + live since | time; owner on counting rule | wave 2: aggregate dedup + live-only window |
| 15 | §17 audit leftovers | IN PROGRESS | see §17 table | waves 1–2; #2278 (T13 deploy token); #2279 (X-HEALTH); CI-1c apt cache; #2233 closed as superseded | #2278, #2279 | targeted suites green (see PRs) | — | — | review → release candidate → merge |

## §1 DLF rookie boards — evidence and decision

**Read-only on-box probes:** DLF diagnostics 44737613322, 44740383578 and 44742643782, dispatched from the PR branch.

**What the pages show:**
- Both rookie pages answer 200 at their own path with no redirect.
- Titles: "2026 Rookie Superflex/IDP Rankings For Dynasty Fantasy Football - DLF". The class is unchanged.
- Each renders `table#avgTable` (class `display dlf_rankings-table avgtable startup-table`) with headers
  `Rank, Avg, Pos, Name, Team, Age, Value, Follow`: no expert columns, 0 body rows, a "Load More" button.
- There are no per-expert tables, and `dlfajax.js` is absent.
- The inline scripts are only follow/unfollow handlers and a position filter over existing rows.

**The working Superflex page, same plugin, for comparison:**
- 3.1 MB of HTML;
- `avgTable` with 287 rows and 6 expert columns;
- six `rankerNTable` per-expert tables.

**Conclusion:** the vendor has no rookie rankings published. There is nothing to parse, and rows must never be
fabricated.

**What the system does after #2275:**
- Labels the state (`vendor_empty`) in the per-board state file and the journal. It is a label only: the run
  still exits 1. Deciding that an empty board is an expected seasonal state belongs to
  `src/sources/seasonal_policy.py`, which today declares only `flockFantasySfRookies`. Under the owner decision of
  2026-10-03, any other empty board fails closed. The first version of #2275 exited 4 and treated the empty board as
  "not a failure". Review rejected that as a second owner of the same question.
- Keeps the last-good 2026-class CSVs. Understand pass: 91 of 92 rows join to first-year players, so the CSVs are the
  drafted 2026 class.
- Leaves the stamps alone, so the data age stays honest.
- Records each board's state in `data/scrape_state/dlf_board_states.json`.
- Refuses any page from another class until an owner-approved config change.

**Owner decision needed: the stale `dlfRookieSf` vote.** `dlfRookieIdp` is already vote-held. The v1 freshness curve
decays `dlfRookieSf` (expected interval 80 h): STALE about 2026-11-27, QUARANTINED (no vote) about 2026-12-18. Until
then, scheduled-refresh's DLF assertion and the staleness watchdog stay red. That is the deliberate rule: a stale
source that still votes stays red.

| Option | Effect | Values change? |
|---|---|---|
| A. Wait | Vote decays automatically; CI red until about 12-18 or until DLF republishes | Gradually, by the existing curve |
| B. Hold the `dlfRookieSf` vote now, plus an `acknowledgedFetchOutages` entry | The watchdog reports DEGRADED instead of red; the 2026 rookies keep `dlfSf` evidence (40 of 61 overlap) | Yes: one frozen vote is removed from about 61 rookie rows now |
| C. When DLF publishes the 2027 class | A reviewed `rookie_class_year`/`stage` change plus a methodology decision on incoming-class votes | Yes, by decision |
| D. Declare a seasonal policy for the DLF rookie boards | A `config/sources/seasonal_policy_v1.json` entry plus an HTML empty signature in `src/sources/seasonal_policy.py`: an empty board becomes `seasonally_inactive`, casts no vote, and the watchdog reports it verified rather than stale | Yes: the frozen vote stops while DLF publishes nothing |

Recommendation: **B now, D if this recurs every off-season.** The board is frozen, not merely slow, and a frozen
vote at decaying weight is noise. Both are source-voting changes, so they are yours to approve.

**Public diagnostics logs checked.** Runs 44740383578 and 44742643782 printed sanitized script excerpts. Their public
logs hold only generic page JavaScript (follow/unfollow handlers, a position filter) and column headers: no nonce,
cookie, member name or token. #2275 removes that printing anyway.

## §3 Branch protection — what happened

- This session's token reports `admin: true` on the repository.
- The dry run (`bash deploy/github/apply-branch-protection.sh --dry-run`) against live ruleset 19976839 matches the
  2026-11-19 review:
  - adds `pull_request` (0 approvals);
  - adds `required_status_checks`: `Validate PR` and `Receipt check` (integration 15368);
  - bypass: deploy key always, GitHub Actions 15368 always, admin pull-request-only; write role 4 removed.
- Direct pushers to `main` since 2026-11-13: github-actions[bot] 96, the box timers (IDP Show 83, DLF 81,
  playerctx 1), and squash-merged PRs only (25 owner-attributed and 3 Dependabot, all with committer GitHub and a
  `(#NNNN)` suffix). Every one is covered by a bypass or goes through a PR.
- Applying failed. `PUT /repos/…/rulesets/19976839` answered **HTTP 403 "Write access to this GitHub API path is
  not permitted through this proxy"**. This session's network proxy forbids ruleset writes; the token itself has
  admin. Not bypassed.
- Owner command, from a machine with an admin token:
  `GH_TOKEN=<admin token> bash deploy/github/apply-branch-protection.sh`
- I verify afterwards:
  - the live ruleset matches the payload;
  - PR #2231 (red `Validate PR`) shows `mergeable_state: blocked`;
  - the next refresh push lands.
- Live ruleset saved before the attempt, for rollback: session scratchpad `ruleset_19976839_before_20261120T124122Z.json`.

## §4 Signals — corrected procedure

The 2026-11-19 owner action said to reconnect "on the box". **That was wrong.** `scripts/signals_connect.py`
`reconnect` opens a dedicated browser for sign-in and one emailed code, so it runs on the owner's own computer
(`docs/sources/SIGNALS_ACCOUNT_CONNECTION.md` lines 156–163):

```bash
python scripts/signals_connect.py reconnect                    # your computer; sign in, enter the emailed code
python scripts/signals_connect.py provision --host chaseupside  # moves the session to the box over SSH stdin
# add --sudo-user dynasty if that SSH alias logs in as root
```

Then I verify:
- the Signals probe reports the session healthy;
- the next collection succeeds;
- `freshness_slo.privateSourcesStale` drops;
- `sourceVotingStatus` shows the votes resumed.

## §17 The 16 audit tasks (2026-11-18 audit), reconciled

The reconciliation comes from the read-only understand pass (`wf_285342a1-685`), checked against `main` at
`5ae4299c`. Any status other than VERIFIED COMPLETE is routed to the unit named in the "Route" column.

| Task | Status at intake | Route | Current |
|---|---|---|---|
| T1 Hermetic hard gate, skip budget | VERIFIED COMPLETE | evidence-tooling agent pins the two remaining archive-reading tests and adds a retention early warning (X-HERMETIC) | IN PROGRESS |
| T2 Freshness and deploy-lag SLO | VERIFIED COMPLETE | — | VERIFIED COMPLETE |
| T3 Data delivery decoupled from the full gate | OWNER / time | evidence-tooling (CI-4b dedup, live-only window, specific advisory gates); activation stays the owner's | IN PROGRESS (code); EXTERNAL BLOCKER (time) |
| T4 Owner admin-action pack | OWNER ACTION REQUIRED | ledger rows 3, 6, 7 | OWNER ACTION REQUIRED |
| T5 Year boundary 2026→2027 | VERIFIED COMPLETE | evidence-tooling adds future-clock instants and a failure tracker (X-YEAR-BOUNDARY) | IN PROGRESS |
| T6 Five UI-fix PRs | VERIFIED COMPLETE | — | VERIFIED COMPLETE |
| T7 Trade and War Room smoke | VERIFIED COMPLETE | evidence-tooling: a stale `rostersState` becomes an explicit warning (X-SMOKE) | IN PROGRESS |
| T8 Public-repo data exposure | OWNER ACTION REQUIRED (decision) | ledger row 8; #2275 deliberately adds no tracked vendor-named file | OWNER ACTION REQUIRED |
| T9 Trade-flow resilience | VERIFIED COMPLETE | wave-1 frontend-hardening (service-worker / API failure recovery) | IN PROGRESS |
| T10 Mobile ergonomics, 390 px | PARTIAL | wave-1 frontend-hardening (touch-target coverage and ratchet); a physical-device check is the owner's | IN PROGRESS |
| T11 Signals restore | OWNER ACTION REQUIRED | ledger row 4, §4 | OWNER ACTION REQUIRED |
| T12 Live roster refresh | VERIFIED NOT NEEDED (measure first) | X-ROSTER-FRESHNESS adds the measurement (after wave 1) | NOT STARTED |
| T13 Security hardening | PARTIAL | `deploy.yml` top-level token grant plus a guard test for every workflow (#2278); `claude.yml` grant and SHA pin (wave-1 alerts-workflows #2277); CSV injection (frontend-hardening); health side effects (#2279) | PR OPEN |
| T14 Next.js | VERIFIED COMPLETE (16.4.5) | superseded Dependabot #2233 closed 2026-11-20; 16.4.6 patch bump (after wave 1) | MERGED (16.4.5); 16.4.6 NOT STARTED |
| T15 Permanent-red / vacuous-green checks | VERIFIED COMPLETE | remaining X-CI items: refresh assertion text (#2277); production-auth suite skip floor (queued); `pipeline.refresh` basis (after alerts-box) | IN PROGRESS |
| T16 Node 20 → 22 | OWNER ACTION REQUIRED | #2271 refreshed against main (`b9adf5dd`); held until Node ≥22.12 is on the box | OWNER ACTION REQUIRED |

**Understand-pass items routed to units:**
- wave-1 alerts-box: URL-HANDLING, STARTUP-VALIDATION, SRC-COOLDOWN, SENDALERT-COOLDOWN, ALL-FAIL, DEADMAN,
  DOC-DRIFT, COV-STALENESS.
- wave-1 alerts-workflows (#2277): COV-REFRESH, CI-3c, COV-DEPLOYLAG, COV-DECISION, CI-5b, CI-2c, T13 (`claude.yml`).
- wave-1 frontend-hardening: X-CSV-INJECTION, X-FRONTEND-FAILURE-SW, X-MOBILE-TOUCH, T10, T9.
- evidence-tooling agent: X-HERMETIC, X-YEAR-BOUNDARY, CI-4b, T3 (advisory gates), X-SMOKE.
- #2279: X-HEALTH.
- #2278: T13 (`deploy.yml`).
- CI-1c worker: verified apt cache.
- After wave 1: X-ROSTER-FRESHNESS, COV-BACKUP, COV-CRITICAL, E2E-TEST, CI-1d, X-CI (production-auth skip floor and
  the `pipeline.refresh` basis), Next 16.4.6.
- Watch only: CI-5c (`audit-rank-form-drift` must be green on its next scheduled run, week of 2026-11-24).

## Open PRs from this directive (2026-11-20 ~14:20 UTC)

| PR | Unit | Owner of the work | State |
|---|---|---|---|
| #2275 | P0 DLF rookie boards | me; two independent reviews addressed | PR CI on `eb034460e` |
| #2276 | this record | me | merged last |
| #2277 | wave-1 alerts-workflows | workflow `wf_094793f6-175` | in that workflow's review/fix |
| #2278 | T13 `deploy.yml` token | me | independent review (workflow `wf_f548c007-001`) |
| #2279 | X-HEALTH | me | independent review (same) |
| #2280 | wave-1 alerts-box | workflow `wf_094793f6-175` | in that workflow's review/fix; coercion-baseline entry regenerated by its author |
| #2281 | T14 Next 16.4.6 | me | independent review (same) |
| #2282 | X-HERMETIC, X-YEAR-BOUNDARY, CI-4b, T3 advisory gates, X-SMOKE | evidence-tooling agent | independent review (same) |
| #2283 | CI-1c verified apt cache | CI-1c agent | review queued |
| #2284 | WebKit service-worker E2E flake (root cause: the test left "/" before its `register()` reached WebKit's SW server; WebKit then drops the job and the registration never gets a worker) | SW agent | review queued |
| #2285 | wave-1 frontend hardening (CSV injection, retryable failure states, sub-24px ratchet) | wave-1 agent; PR opened by me after the workflow died (one `ds.css` discipline failure fixed) | review in workflow `wf_5eaf751c-c6c` |
| #2271 | Node 22 lanes (HOLD) | me | E2E re-run once (WebKit service-worker flake, not Node 22); owner installs Node ≥22.12 |
| (branch) | X-ROSTER-FRESHNESS measurement | me | committed `2e2188d22`; SLO rule added after #2280, then PR |

**Findings made while integrating:**
- COV-BACKUP's premise is stale. Production's public `/api/status` shows `stateBackup` healthy, evidence
  `directory_listing`, 14 generations (2026-11-20 ~14:15 UTC); `BACKUP_READ_GROUP=dynasty` already lets the backend
  list the root. The remaining gap is an alert-sweep row for a stale state backup; it goes in `ops_alerts.py` after
  #2280.
- The WebKit service-worker E2E test (`mobile-device-flows.spec.js`, "with the worker in control") still fails on a
  first attempt with a registration that has no worker (E2E run 44744152284, as in 2026-11-19's STAB-9 runs). A
  worker is root-causing it on branch `claude/serene-shannon-7lsrm9-sw-flake`; skipping or retrying it is not
  acceptable.

**2026-11-20 14:20–18:20 UTC: session paused.** The usage limit was hit, and the container restarted several times.
That stopped the wave-1 workflow and the first review workflow. On resume:
- #2275 was fully green, but its release candidate refused because 96 build-consumed data changes on `main` were
  missing from its head (HEAD-FREEZE). `main` was merged in once (`455d50159`) and the release candidate re-dispatched.
- #2282 had a real blocker: its new TE-skew fixture carried 22 paid-vendor files and 204 owner-id-like fields into
  this public repository, and the exposure guard refused it. That fixture was removed (`7fad4fb79`). The test reads
  its allowlisted archive again; pinning it needs the owner's exposure decision or a vendor-free fixture.
- **Possible real-Safari issue (found by #2284, not fixed):** a page that does a full navigation right after mount
  can strand its service-worker registration for the session. HomeClient's standalone-PWA redirect to `/auction` is
  one such path. Recorded as a follow-up for a WebKit device check.

**Independent review, workflow `wf_5eaf751c-c6c` (10 agents, 2026-11-20 ~19:00 UTC):**
- Approved with nits only: #2277, #2278, #2279, #2281, #2282, #2283 and #2285. #2281's integrity hashes all match the
  npm registry. #2279 had a 96-state parity matrix between the view and the reconciler: 0 mismatches.
- #2280 changes requested. Adversarial verification confirmed two important findings:
  - a flapping uptime check sends about 8 pushes an hour (80 at the 30 s floor) against about 1 on `main`;
  - the delivery-health record is in memory only, so a restart reads 0 failures and the SLO rule says OK.

  It also confirmed one nit: an SMTP failure logs the recipient. A fix agent is working on all three.
- #2284 and #2286 are under a separate review.
- A merge-tree simulation of #2275, #2278, #2279, #2282, #2283, #2277, #2285, #2281, #2284 and #2286 on `main`
  found no conflicts.

## Integration log

(Appended as trains land.)
