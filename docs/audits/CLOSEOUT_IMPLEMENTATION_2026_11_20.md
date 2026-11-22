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
| 1 | P0 DLF rookie boards | VERIFIED COMPLETE (fix); OWNER DECISION (stale vote, §1) | Vendor publishes no rookie rankings since 2026-11-17 22:27 UTC: same RankingEngine table, 0 rows, 0 expert columns (Superflex: 287 rows, 6 experts). Not a parser defect. | `vendor_empty` label (rookie boards only; run still exits 1); last-good kept; box-local per-board state file; fail-closed rookie class guard; dead shell guard fixed | #2275 → `39e6c1d3` | release candidate 44796069769 green; deploy 44803655798 green | production build `39e6c1d3`; box state file 2026-11-20 20:27 UTC: both rookie boards `vendor_empty`, last-good 61/31 rows kept, dlfSf/dlfIdp/values `written` (diagnostics 44815264693) | owner: what to do with the frozen `dlfRookieSf` vote (options A–D) | owner decision |
| 2 | P1 alert delivery | MERGED (code); OWNER ACTION REQUIRED (channel) | No owner channel; plus code gaps | alerts-box (#2280) and alerts-workflows (#2277) merged in train 1120; follow-ups #2287 (shell scripts, restart push), #2290 (stale-backup alert, producer test) | #2277 → `b44d5e43`, #2280 → `76f9e117`; PRs #2287, #2290 | train release candidate 44887684813 green on the exact merged tree | deploy of `76f9e117` running (2026-11-21 ~09:35 UTC) | owner: ntfy topic and secret | verify deploy; land #2287/#2290 |
| 3 | P1 branch protection | OWNER ACTION REQUIRED | Live ruleset 19976839 has no required checks | dry run re-verified 2026-11-20; apply attempted | — | `test_main_protection_ruleset.py` 6/6 | the API write was refused (§3) | owner runs the script | — |
| 4 | P1 Signals | OWNER ACTION REQUIRED | Session `reconnect_required` (probe 44532781512) | — | — | — | 4/4 private sources stale | owner reconnect on own computer, then provision | verify after reconnect |
| 5 | P1 Node 22 | OWNER ACTION REQUIRED | Box runs Node 20 (system install) | #2271 to be refreshed against main | #2271 (HOLD) | — | — | owner installs Node ≥22.12 | refresh #2271 |
| 6 | P1 off-box backups | OWNER ACTION REQUIRED | All generations on one disk | design + stale-copy alert (#2264, deployed) | — | — | `offbox_copy` row live, silent until configured | B2 approval and keys | backup-age alert work (wave 2) |
| 7 | P2 credentials | OWNER ACTION REQUIRED | rotation is owner-only | inventory + `check_login_status.py` (#2263); `startup_guards.startup_refusals` refuses empty or placeholder `JASON_LOGIN_PASSWORD` | — | — | — | owner rotation | — |
| 8 | P2 public-repo data | OWNER ACTION REQUIRED (decision) | policy | recommendation + guard gap closed (#2262) | — | — | — | owner decision | — |
| 9 | P2 mobile / browser | MERGED | gaps in touch-target coverage | frontend-hardening (#2285): CSV neutralization, retryable failure states, sub-24px ratchet; WebKit SW test race fixed (#2284) | #2285 → `3d5e5cbb`, #2284 → `eb41b1dd` | train E2E 44803981544 green (both browsers) | deploy running | physical iPhone checklist (owner) | owner device check |
| 10 | P2 Ubuntu apt | MERGED (CI-1c); PR OPEN (CI-1d) | archive 503 / stalled mirror on 2026-11-19 | CI-1c verified `.deb` cache for tesseract (#2283); CI-1d Playwright deps through the installer (#2288) | #2283 → `b3a8fa32`; PR #2288 | train release candidate green; #2288 targeted 709 passed | CI only | — | land #2288, dispatch E2E on main |
| 11 | P2 zombie run 43096180672 | EXTERNAL BLOCKER | GitHub-side zombie: queued since 2026-11-11, 0 jobs | rechecked 2026-11-20: cancel answers HTTP 409 "has not been queued yet"; delete answered 403 on 2026-11-19 | — | — | deploy-in-flight guard ignores it as "never started" | GitHub support or owner UI | — |
| 12 | P2 Sharp smoke token | MERGED (code); OWNER ACTION REQUIRED (token) | honest "not measured" since T15 | measure only after deploy commit; unverifiable is loud (#2277) | #2277 → `b44d5e43` | train release candidate green | — | owner provisions `SHARP_SMOKE_TOKEN` | — |
| 13 | P2 2030 pick policy | OWNER ACTION REQUIRED (decision) | league window vs board horizon | prototype `d5b8161d` | — | — | — | decision before 2027-01-01 | — |
| 14 | P2 data-only activation | EXTERNAL BLOCKER (time) | evidence bar not met | observer automatic since #2272 | — | — | 17 compared + live since | time; owner on counting rule | wave 2: aggregate dedup + live-only window |
| 15 | §17 audit leftovers | VERIFIED COMPLETE (train 1120; follow-ups #2287–#2291 as train 1121) | see §17 table | train 1120: #2277, #2278, #2279, #2281, #2282, #2283, #2284, #2285, #2286, #2280; follow-ups #2287–#2290, #2291 | `main` `76f9e117` | release candidate 44887684813 + E2E 44803981544 green | production `build.commit` `76f9e117` (deploy 44889347872, 2026-11-21 10:43 UTC); `/api/health` 200 and read-only; frontend lock hash = repo (Next 16.4.6). Train 1121: `build.commit` `cfc0179a` (deploy 44962933533, 2026-11-22); roster freshness and `alertDelivery` served, anonymous test-alert 401 | — | — |

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
- Records each board's state in the box-local `/var/lib/dlf-fetch/dlf_board_states.json` (never committed; read by
  `dlf-diagnostics.yml`).
- Refuses any page from another class until an owner-approved config change.

**Owner decision needed: the stale `dlfRookieSf` vote.** `dlfRookieIdp` is already vote-held. The v1 freshness curve
decays `dlfRookieSf` (expected interval 80 h): STALE about 2026-11-27, QUARANTINED (no vote) about 2026-12-18.

**Two separate red checks, measured 2026-11-21** (scheduled-refresh run 44861373134, health check 44878386225):
- `Assert DLF freshness` reads the aggregate `dlf_last_success`, which `deploy/dlf_fetch_and_push.sh` writes only on a
  fully clean run. `fetch_dlf.py` exits 1 while the rookie boards are empty (the #2275 review decision), so the stamp
  has stayed at 2026-11-17 22:27 (77 h on 2026-11-21).
- The staleness watchdog flags `dlfRookieSf` / `dlfRookieIdp` 77 h stale.
- Together they make every scheduled refresh since 2026-11-19 03:50 fail (7 runs), which is the `pipeline.refresh`
  BREACH on the production SLO. Data still flows: the refresh commits and pushes before these assertions run, and the
  box's own scrape keeps the served board fresh (board age 0.14 h on 2026-11-21).

| Option | Watchdog | `Assert DLF freshness` (refresh job) | Values change? |
|---|---|---|---|
| A. Wait | red | red until DLF republishes rookie rankings (the 12-18 quarantine ends the vote, not this assertion) | Gradually, by the existing curve |
| B. Hold the `dlfRookieSf` vote now, plus an `acknowledgedFetchOutages` entry | DEGRADED (the entry is honoured only while the source votes on no row, at most 14 days per entry) | still red until DLF republishes: the entry is read only by the watchdog | Yes: one frozen vote is removed from about 61 rookie rows now; the 2026 rookies keep `dlfSf` evidence (40 of 61 overlap) |
| C. When DLF publishes the 2027 class | — | — | A reviewed `rookie_class_year`/`stage` change plus a methodology decision on incoming-class votes |
| D. Declare a seasonal policy for the DLF rookie boards | verified, not stale | green once implemented: a declared empty board stops failing the run (the fetcher returns the seasonal state instead of 1), so the aggregate stamp advances | Yes: the frozen vote stops while DLF publishes nothing |

D needs a `config/sources/seasonal_policy_v1.json` entry, an HTML empty signature in `src/sources/seasonal_policy.py`
and the fetcher's seasonal exit path (`flockFantasySfRookies` is the existing example); it is code plus a
source-voting decision.

Recommendation (revised 2026-11-21): **D.** It is the only option that is accurate (the board is empty, not failing),
keeps CI honest (green only because a declared state is verified, not because a check was quieted), stops treating
frozen data as a vote, and recovers on its own when DLF publishes again (the signature no longer matches). B alone
removes the vote but leaves the refresh job red. Both are source-voting changes, so they are yours to approve. Until
you decide, `pipeline.refresh` stays BREACH on every scheduled health check.

**Update, 2026-11-21 11:45 UTC: DLF republished both rookie boards at 04:27 UTC, so option A happened on its own.**
From the committed state on `main` (`data/scrape_state/*` and `CSVs/site_raw/*`, written by the box timer):

| Board | Rows | Content last changed | Fetch state since 04:27 UTC |
|---|---|---|---|
| `dlfSf` | 286 | 2026-11-20 22:27 | written every run |
| `dlfIdp` | 181 | 2026-11-17 14:27 (vendor unchanged since) | written every run |
| `dlfRookieSf` | 62 | **2026-11-21 04:27** (49 rows changed, 1 added; still the 2026 class) | written every run |
| `dlfRookieIdp` | 31 | **2026-11-21 04:27** (12 rows changed; still the 2026 class) | written every run |
| `dlfValuesSfTep` | 328 | 2026-11-20 18:27 | written every run |

- The aggregate `dlf_last_success` advanced at 04:27, 06:27, 08:27 and 10:27 UTC (fully clean runs). The last failed
  scheduled refresh (44861373134, 03:29 UTC) ran before that. The next scheduled refresh should pass `Assert DLF
  freshness` and the staleness watchdog with no change, and `pipeline.refresh` should return to OK on the following
  health check. Neither has run yet at the time of writing.
- `dlfRookieSf`'s content clock restarted at 04:27, so the stale/quarantine dates above no longer apply.
- #2275 worked as designed through the outage: the empty boards were labelled `vendor_empty`, the last-good CSVs were
  kept, the stamps stayed honest, and the boards were written again as soon as the vendor published.
- Recommendation now: **no action needed for this episode.** D remains the recommended answer if the vendor empties
  the rookie boards again (for example between classes), so a declared seasonal state is verified rather than
  failing every refresh. It stays an owner decision (source voting) and is not implemented here.
- The diagnostics session-jar traceback (§1's last diagnostics runs) is fixed in #2291.

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
| T1 Hermetic hard gate, skip budget | VERIFIED COMPLETE | evidence-tooling agent pins the two remaining archive-reading tests and adds a retention early warning (X-HERMETIC) | MERGED (#2282) |
| T2 Freshness and deploy-lag SLO | VERIFIED COMPLETE | — | VERIFIED COMPLETE |
| T3 Data delivery decoupled from the full gate | OWNER / time | evidence-tooling (CI-4b dedup, live-only window, specific advisory gates); activation stays the owner's | MERGED (code, #2282); EXTERNAL BLOCKER (time) |
| T4 Owner admin-action pack | OWNER ACTION REQUIRED | ledger rows 3, 6, 7 | OWNER ACTION REQUIRED |
| T5 Year boundary 2026→2027 | VERIFIED COMPLETE | evidence-tooling adds future-clock instants and a failure tracker (X-YEAR-BOUNDARY) | MERGED (#2282) |
| T6 Five UI-fix PRs | VERIFIED COMPLETE | — | VERIFIED COMPLETE |
| T7 Trade and War Room smoke | VERIFIED COMPLETE | evidence-tooling: a stale `rostersState` becomes an explicit warning (X-SMOKE) | MERGED (#2282) |
| T8 Public-repo data exposure | OWNER ACTION REQUIRED (decision) | ledger row 8; #2275 deliberately adds no tracked vendor-named file | OWNER ACTION REQUIRED |
| T9 Trade-flow resilience | VERIFIED COMPLETE | wave-1 frontend-hardening (service-worker / API failure recovery) | MERGED (#2285) |
| T10 Mobile ergonomics, 390 px | PARTIAL | wave-1 frontend-hardening (touch-target coverage and ratchet); a physical-device check is the owner's | MERGED (#2285); physical device check is the owner's |
| T11 Signals restore | OWNER ACTION REQUIRED | ledger row 4, §4 | OWNER ACTION REQUIRED |
| T12 Live roster refresh | VERIFIED NOT NEEDED (measure first) | X-ROSTER-FRESHNESS adds the measurement (after wave 1) | PR OPEN (#2289) |
| T13 Security hardening | PARTIAL | `deploy.yml` top-level token grant plus a guard test for every workflow (#2278); `claude.yml` grant and SHA pin (wave-1 alerts-workflows #2277); CSV injection (frontend-hardening); health side effects (#2279) | MERGED (#2277, #2278, #2279, #2285) |
| T14 Next.js | VERIFIED COMPLETE (16.4.5) | superseded Dependabot #2233 closed 2026-11-20; 16.4.6 patch bump (after wave 1) | MERGED (16.4.6, #2281) |
| T15 Permanent-red / vacuous-green checks | VERIFIED COMPLETE | remaining X-CI items: refresh assertion text (#2277); production-auth suite skip floor (queued); `pipeline.refresh` basis (after alerts-box) | MERGED (#2277, #2286) |
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
| #2275 | P0 DLF rookie boards | me; two independent reviews addressed | MERGED `39e6c1d3` (head `d6342a3c`, release candidate 44796069769 green); deploy 44803655798 |
| #2276 | this record | me | merged last |
| #2277 | wave-1 alerts-workflows | workflow `wf_094793f6-175` | MERGED `b44d5e43` (train 1120, 2026-11-21 09:22 UTC) |
| #2278 | T13 `deploy.yml` token | me | MERGED `853a86c4` (train 1120, 2026-11-21 09:22 UTC) |
| #2279 | X-HEALTH | me | MERGED `c8c9020a` (train 1120, 2026-11-21 09:22 UTC) |
| #2280 | wave-1 alerts-box | workflow `wf_094793f6-175` | MERGED `76f9e117` (train 1120, 2026-11-21 09:22 UTC) |
| #2281 | T14 Next 16.4.6 | me | MERGED `fcd39c33` (train 1120, 2026-11-21 09:22 UTC) |
| #2282 | X-HERMETIC, X-YEAR-BOUNDARY, CI-4b, T3 advisory gates, X-SMOKE | evidence-tooling agent | MERGED `95d9b770` (train 1120, 2026-11-21 09:22 UTC) |
| #2283 | CI-1c verified apt cache | CI-1c agent | MERGED `b3a8fa32` (train 1120, 2026-11-21 09:22 UTC) |
| #2284 | WebKit service-worker E2E flake (root cause: the test left "/" before its `register()` reached WebKit's SW server; WebKit then drops the job and the registration never gets a worker) | SW agent | MERGED `eb41b1dd` (train 1120, 2026-11-21 09:22 UTC) |
| #2285 | wave-1 frontend hardening (CSV injection, retryable failure states, sub-24px ratchet) | wave-1 agent; PR opened by me after the workflow died (one `ds.css` discipline failure fixed) | MERGED `3d5e5cbb` (train 1120, 2026-11-21 09:22 UTC) |
| #2271 | Node 22 lanes (HOLD) | me | E2E re-run once (WebKit service-worker flake, not Node 22); owner installs Node ≥22.12 |
| #2286 | X-CI production-auth skip floor | me | MERGED `1e9dc3ac` (train 1120, 2026-11-21 09:22 UTC) |
| #2287 | alert shell scripts (COV-CRITICAL push, uptime retry queues, validator-exact URL check) | worker + my review fixes | PR CI; third review round running |
| #2288 | CI-1d Playwright deps through the installer | worker + my review fixes | PR CI; third review round running |
| #2289 | X-ROSTER-FRESHNESS status fields and SLO rule | me | PR CI; third review round running |
| #2290 | COV-BACKUP stale-state-backup alert, E2E-TEST producer test mode | worker + my review fix | PR CI; third review round running |

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

- **2026-11-20 19:35 UTC: #2275 merged** (squash `39e6c1d3`, `expectedHeadSha` `d6342a3c`). Release candidate
  44796069769 passed on that head after `main` had been merged in twice for HEAD-FREEZE. Deploy Production 44803655798
  started at 19:36 UTC.
- **#2280 re-review (after `29ad02ee4`).** It found a new permanent red: with no channel configured (production today)
  `consecutiveFailures` stays `null`, the delivery rule answered UNKNOWN, `check_production_slo.py` exited 3 on every
  scheduled run and the SLO tracker would never close. Fixed in `322685efb`: `delivery_health()` publishes
  `deliveryRecord` (`recorded` / `none` / `unreadable`). The rule is OK with no channel, OK with a channel and no
  attempt yet, and UNKNOWN only for an unreadable or unreported record. A second re-review approved it with one nit:
  when `user_kv` resets a corrupt store it destroys a prior failure streak, so the record reads `none` until the next
  attempt (follow-up; not recoverable in this module).
- **Train 1120.** Branch `claude/serene-shannon-7lsrm9-train-1120` at `8f072d58f`: `main` `39e6c1d3` plus, in order,
  #2284 `07932f09`, #2277 `86ec2268`, #2278 `57b247ab`, #2279 `4f1a2394`, #2281 `f1cc8373`, #2282 `7fad4fb7`,
  #2283 `7ac91d19`, #2285 `ee990bd4`, #2286 `bb5150a5`, #2280 `322685ef`. No conflicts. Only #2280 touches
  `config/coercion_baseline.json`. Release candidate 44803977318 and E2E 44803981544 (the E2E run carries #2284's
  service-worker fix, so it also re-tests #2281 and #2285, whose own E2E runs failed only on that flake) dispatched
  19:38 UTC.
- **Expected after the train deploys.** `alerting.alert_sweep_age` is UNKNOWN until the first daily sweep (15:00 UTC,
  2026-11-21), so the health check opens an "UNKNOWN-ONLY" SLO tracker that the next green run closes. Running the sweep
  by hand would send real user signal alerts, so it is left to its timer.
- **Follow-ups building on train 1120** (each in its own worktree and branch; PRs open after the train lands):
  - alert shell plumbing: COV-CRITICAL push from `dynasty-healthcheck.sh`, `uptime_check.sh` state after the push,
    `deploy.sh` copying `owner_notify.py`, `--check` usage (`claude/serene-shannon-7lsrm9-alert-shell`);
  - CI-1d: Playwright OS deps through the shared installer (`claude/serene-shannon-7lsrm9-ci-1d`);
  - COV-BACKUP stale-state-backup alert row and the E2E-TEST producer test mode
    (`claude/serene-shannon-7lsrm9-alert-producers`);
  - X-ROSTER-FRESHNESS: `freshness_slo` roster fields, the stale-roster refusal counter and
    `data_freshness.roster_age_hours` (`claude/serene-shannon-7lsrm9-roster-slo`, `4bc0b1e1`). The rule adds no
    threshold: it maps the box's own `rosterState` verdict (6 h, `SCORING_SNAPSHOT_MAX_AGE_HOURS`).
- **Process notes.**
  - A `git worktree add` failed (the branch name `train2` was taken by a 2026-11-18 train), and the merge loop that
    followed ran in the main checkout. It merged the ten heads into the local closeout branch. Nothing was pushed. The
    branch was reset to its pushed head `80785eb0e`, and the train was rebuilt in its own worktree.
  - A test written for #2280 pointed the store path at the test file. `user_kv` quarantined the file as a corrupt store.
    The file was restored before commit, and the test now uses the isolated per-test store.

- **2026-11-20 20:04 UTC: #2275 deployed** (production `build.commit` `39e6c1d3`). The box-side proof came from the
  20:27 UTC timer run (diagnostics 44815264693): `/var/lib/dlf-fetch/dlf_board_states.json` shows `dlfRookieSf` and
  `dlfRookieIdp` as `vendor_empty` ("rankings table(s) with 0 rows and 0 expert columns"), the last-good CSVs kept
  (61 and 31 rows), and `dlfSf` / `dlfIdp` / `dlfValuesSfTep` `written`. The traceback seen in both diagnostics logs
  comes from the inventory script's own session-jar section (stderr interleaved), not from the timer: a
  diagnostics-only follow-up.
- **Train 1120 validation.** Release candidate 44807243040 and E2E 44803981544 passed on the train. Two data
  refreshes then landed and were integrated once (`dbc1af5c`); release candidate 44815259917 passed. The session then
  paused for the usage limit (about 21:00 UTC to 09:00 UTC), during which `main` moved 19 automated data commits
  (data/, exports/, CSVs/, config/ only). They were integrated once more (`861f43dd`), and release candidate
  44887684813 passed at 09:20 UTC, its plan step reporting "the validated tree IS the tree that will merge".
- **2026-11-21 09:22 UTC: train 1120 merged**, in order #2284, #2277, #2278, #2279, #2281, #2282, #2283, #2285, #2286,
  #2280, each squash with `expectedHeadSha`. `main` `76f9e117` has tree `c7eeccd0`, identical to the validated
  candidate tree. Deploy 44889308459 (`b44d5e43`) is running and 44889347872 (`76f9e117`) is queued behind it; the
  intermediate deploys were cancelled as stale, by design.
- **#2280 late fix.** CI shard 2 on `322685ef` failed two status tests that pinned the old `alertDelivery` key set
  (the re-reviewer had said that file read the block by key). Fixed in `a07b7d28` before the train merged.
- **Follow-up PRs** (each reviewed adversarially, fixes applied, rebuilt on `main` by cherry-pick into `-v2` branches,
  octopus-merged together cleanly with 194 cross-cutting tests green):
  - #2287 alert shell scripts. Review round 1: a short outage whose push failed was lost entirely, and a failing
    second channel made the working one repeat; fixed with per-channel queues. Round 2: a prefix-glob URL check let
    `http://localhost.evil.example` through, and queue lines reached `curl -d` (an `@` value is read as a file); fixed
    with a validator-exact shell check (45,360-URL differential corpus) and stdin bodies.
  - #2288 CI-1d (Playwright deps through the installer); fixes: smoke step cap below the job's, V1 reads the installer
    from the workflow commit.
  - #2289 roster freshness SLO; fixes: refusal counter withheld from anonymous status, box error block named, rule
    pinned in `RULES`.
  - #2290 stale-state-backup alert and producer test mode; fix: the backup text no longer contradicts a failed-unit
    alert in the same message.
  A third review round over all four is running (`w4ioxktmw`).
- **Process notes (2026-11-21).** One parallel test command ran two subshells from the main checkout instead of the
  scratchpad, and its `git checkout` moved the main checkout to `roster-slo-v2`. Nothing was modified or pushed; the
  checkout was restored to the closeout branch at once. Disk reached ~92% during reviews; finished worktrees were
  removed after confirming each was clean and matched its pushed head.
- **2026-11-21 10:43 UTC: train 1120 verified in production.** Deploy 44889308459 (`b44d5e43`) succeeded at 10:03
  and 44889347872 (`76f9e117`) at 10:43; the intermediate deploys were cancelled as stale. On
  `https://chaseupside.com` at 10:48:
  - `/api/status` `build.commit` = `76f9e1174ab403be27bff1c22f4b345ef960ac8f` (process started 10:38:13);
  - `build.release.frontend_lock_sha256` = `04d44494…` = `sha256(frontend/package-lock.json @ 76f9e117)`, whose `next`
    is 16.4.6 (#2281);
  - `alertDelivery` = `{ntfyConfigured: false, emailConfigured: false, consecutiveFailures: null, deliveryRecord:
    "none"}` (#2280); `alertSweepAgeHours` = null until the first 15:00 UTC sweep;
  - `freshness_slo.privateSourceDetail` = `withheld` on the anonymous projection;
  - `/api/health` answered 200 twice with every scrape-state field of `/api/status` unchanged before and after
    (#2279, read-only); the startup scrape finished at 10:43:23 (`scrape_count` 1, success);
  - `/` and `/league` answer 200. A production browser smoke (`prod-e2e-smoke.yml`) was dispatched.
- **Production SLO, 2026-11-21 07:02 UTC (health check 44878386225):** two BREACHes, both explained.
  `pipeline.refresh`: the DLF rookie boards (§1; every scheduled refresh since 2026-11-19 03:50 fails `Assert DLF
  freshness` and the staleness watchdog, 7 runs). `data_freshness.private_sources`: 4 of 4 Signals sources stale
  (ledger row 4, owner reconnect). Every other rule OK (deploy lag 0, board age 0.14 h).
- **Owner alert delivery: highest verified level = none on a real channel.** Level 1 (generated) is proven only in
  tests with stub channels. Production has no channel: the box reports `ntfyConfigured: false` /
  `emailConfigured: false`, and the GitHub workflows' environment shows `NOTIFY_WEBHOOK_URL` empty (a set secret
  prints `***`). To reach Level 2 (accepted) and Level 4 (received): create the private ntfy topic; set it as the
  repository secret `NOTIFY_WEBHOOK_URL` and in the box drop-ins (`dynasty.service`, `riskit-uptime.service`,
  `dynasty-healthcheck.service`) per `docs/ops/OWNER_ALERT_CHANNEL_SETUP_2026-11-19.md`; restart; then an admin
  `POST /api/test-alert?producers=1` (after #2290) and the owner confirms the four `[TEST]` pushes arrived.
- **Follow-up review fixes on 2026-11-21** (beyond the reviews already recorded):
  - #2287 queue-storage audit (`5458ecc1`): status and queues move from the predictable, shared `/var/tmp` path to a
    private `StateDirectory=` (0700, `UMask=0077`); the script refuses a state directory it does not own or that
    others can write; atomic temp-and-rename writes; a symlinked queue file is never read; `flock` against concurrent
    runs; the queue is saved before sending and after each accepted message (at-least-once, at most one re-send after
    a kill); a 15 s delivery budget keeps a run inside `TimeoutStartSec=90`; `NOTIFY_CMD` under `timeout 10`. Eight
    new tests, all failing on the previous script, including a run killed on its second POST. CI then caught 33
    text-mode file calls without `encoding=` in the new tests (`tests/test_explicit_text_encoding.py`); fixed in
    `ce212151`.
  - #2288 (`278ab140`): the default `PLAYWRIGHT_CMD` was `npx playwright`, which downloads whatever npm serves when
    the local install is missing; it is now `npx --no playwright` (the pinned 1.64.1 or a failure). Both Playwright
    calls run under `timeout` with named errors (dry-run 120 s, browser install 420 s).
  - #2290 (`f7a31566`): authorized `/api/test-alert` calls were bounded only by the site-wide 60-per-minute limiter,
    and one producers request can send a push per producer per channel. Authorized requests now share one isolated
    budget (5 per 10 minutes, charged after auth); past it 429 and nothing is sent.
  - #2289: verified, no change needed. Shard 7 failed once on `test_run_scraper_nonblocking` (an event-loop timing
    assertion in the scraper path, which this PR does not reach: call graph and import diff checked); it reproduced
    1 time in 17 locally on the PR head and 0 in 12 on `main`, and passed on the one allowed re-run.
  - #2291 (new): the DLF diagnostics session-jar traceback. The jar `fetch_dlf.py` writes is an object
    (`{"_comment_", "cookies"}`), so section [4] iterated key strings. Fixed to read the cookie list, print names and
    domains only, never values.- **Production browser smoke** (`prod-e2e-smoke.yml` 44896117924, dispatched 10:49 UTC against build `76f9e117`): success.
- **Third review round and delta reviews, 2026-11-21 (all fixed with regression tests).**
  - Round 3 (`w4ioxktmw`: three lenses per PR, each finding put to refuters; 28 agents) confirmed seven findings, all NIT,
    and refuted five. Three of the refuted five were against the pre-audit #2287 head (`/var/tmp` queues, no total time
    bound) and are moot. The fourth, a 1-of-3 vote, said `/api/test-alert` requests are now also charged to the
    site-wide per-IP bucket that TestClient shares across tests, so a test could flip to 429 depending on what ran
    before it. It is a real latent order dependence (one refuter reproduced it), so it was fixed anyway.
  - Delta reviews of the post-audit commits: #2288 APPROVE; #2290 APPROVE; #2291 APPROVE; #2287 CHANGES_REQUESTED, with
    one IMPORTANT finding.
  - #2287 (IMPORTANT, delta review): the uptime script recorded the new status before the cmd channel had queued the
    transition, so a run killed during the webhook POST lost the cmd alert for good (reproduced with a stub curl that
    kills its parent). Now every configured channel queues first, then the status is recorded, then delivery runs.
    `test_uptime_a_run_killed_during_the_webhook_send_still_alerts_the_cmd_channel` fails if the order is reverted
    (`16711767`; 1,699 related tests pass).
  - #2287 NITs fixed:
    - `timeout -k 2` on `NOTIFY_CMD`;
    - no send inherits the lock descriptor (a child left behind used to hold every later run off; tested);
    - runtime formula corrected and `TimeoutStartSec` raised 90 → 120 (worst case 88 s);
    - `mv -T` (a symlink to a directory is replaced, not written into);
    - the run works inside the checked directory with relative names;
    - the old `/var/tmp` status is read once at upgrade when this user wrote it, so an outage in progress still gets its
      recovery message;
    - `NOTIFY_BUDGET` is validated;
    - the shell URL check now strips exactly what `str.strip()` strips (NBSP and the Unicode spaces), accepts
      zero-padded ports, and refuses a stray `[`, matching `validate()`, in both `dynasty-healthcheck.sh` and
      `notify_owner.sh`;
    - the queue test now fails if the newest messages are dropped instead of the oldest.
  - #2287 not fixed (pre-existing, out of scope): the webhook URL is in curl's argv during a POST, readable by local
    users through `/proc`, and `Environment=` drop-ins are readable through `systemctl show`. Follow-up: `curl
    --config` plus `EnvironmentFile=` with mode 0600, in all three scripts.
  - #2288: an unusable or timed-out final Playwright check no longer also prints "still missing" naming the packages
    just installed (`165c76f8`).
  - #2289 (`354ab408`): two tests could not fail. The public test now requires every roster field to be present and
    not withheld, and a current roster block travels through anonymous `/api/status` to `rule_roster_age` = OK. The
    admin test now pins the refusal counter the server reads itself. Both mutations fail.
  - #2290 (`c82c0b57`): notify-test reports HTTP 429 as `rate_limited` with an integer `retryAfterSeconds` (documented);
    the three test files that post the route start each test with the site bucket full; a wrong bearer (401) and a
    signed-in non-admin (403) are pinned as spending nothing; the budget comment now describes the token bucket
    accurately.
  - #2291 (`7fe43842`): the jar listing is capped at 40; a non-string name or domain prints `<not a string>`; an
    unreadable jar prints its error class only; odd expiries never raise.
- **Train 1121.** Branch `claude/serene-shannon-7lsrm9-train-1121` at `2d8c90f6` (tree `4fca394d`): `main` `110d1f54`
  (2 automated data commits past `76f9e117`, `data/` only, class C, integrated once) plus, in order, #2287 `16711767`,
  #2288 `165c76f8`, #2289 `354ab408`, #2290 `c82c0b57`, #2291 `7fe43842`. No conflicts (`server.py` auto-merged the
  #2289 and #2290 changes). None touches `config/coercion_baseline.json`. Release candidate 44899341283 and E2E
  44899343711 (the E2E job installs its browsers through #2288's installer) dispatched 11:29 UTC.
- **Train 1121 release-candidate history.**
  - **44900047845 (12:08 UTC): failed in shard 4.** Two `PublicLeagueRouteTests` section tests answered 429. The public routes share one per-client limiter budget (60/min, 1000/h) across the test process, and that file never reset it.
    - Pre-existing, not caused by the five PRs: the same 121-file shard sequence fails identically on `main` `110d1f54` (2 failed, 2,521 passed). The train's new test files only changed which files share the shard.
    - Fixed on #2290 (`d64bda29`): the file now resets the limiter per test, as its sibling memo tests already do. The same sequence then gives 2,542 passed on the train.
  - **44904289607 (12:30 UTC): all eight shards passed** (including shard 4). The strict freshness step failed because an idpShow refresh (4 `data/scrape_state` files) landed on `main` during the run.
  - **44961121478 (23:18 UTC): success.** Before it, `main` was integrated once more (16 class-C commits: data/exports/CSVs/config), giving train head `e16d6a41`, tree `b4d12c3a`. The run was timed after the 22:27/22:32 refreshes. E2E 44899343711 passed on the train earlier; it is the first real run of #2288's Playwright installer.
  - **Lesson:** the local `ruff` here is 0.16.9; the pinned 0.6.9 is `python -m ruff` / `scripts/format_python_changes.sh`. One #2287 commit was formatted with the wrong one and fixed in `567f758a`.
- **2026-11-21 23:40 UTC: train 1121 merged**, in order, each squash with `expectedHeadSha`:
  - #2287 `4485aaf1` (head `567f758a`);
  - #2288 `02ebd9aa` (`165c76f8`);
  - #2289 `1ba65ede` (`354ab408`);
  - #2290 `f6c16e38` (`d64bda29`);
  - #2291 `cfc0179a` (`7fe43842`).

  `main` `cfc0179a` has tree `b4d12c3a`, identical to the validated candidate tree. Deploy 44962907372 (`4485aaf1`) was running and 44962933533 (`cfc0179a`) queued; the three intermediate deploys were cancelled as stale, by design.
- **2026-11-22: train 1121 VERIFIED in production.**
  - Deploy 44962907372 (`4485aaf1`) succeeded at 00:10 UTC.
  - Deploy 44962933533 (`cfc0179a`) succeeded at about 00:53 UTC.
  - Read-only probe right after: `/api/status` `build.commit` = `cfc0179ab0e4…` (match).
  - `freshness_slo`: `state: measured`, board 0.04 h, rosters `current` / `live` at 0.12 h against the 6 h budget (#2289).
  - `rosterUnverifiableTrades` and `privateSourceDetail` are `withheld` for an anonymous caller (#2289 privacy).
  - `alerting.alertDelivery` is present and honest (#2290): `deliveryRecord: none`, ntfy and email not configured. No channel exists yet; this is an owner action, ledger row 4.
  - Anonymous `POST /api/test-alert` returns 401 `auth_required`.
  - `/api/health`, `/` and `/league` return 200.
  - #2287 (uptime and healthcheck shell) and #2288 (CI installer) have no HTTP surface. Their acceptance is the shell tests and E2E 44899343711.
- **DLF confirmed recovered without a code change:**
  - Scheduled refreshes 44906727928 (13:01) and 44947449357 (20:39) passed `Assert DLF freshness` and the staleness watchdog.
  - Health check 44939740223 (19:13) moved the SLO conditions from `data_freshness.private_sources,pipeline.refresh` to `data_freshness.private_sources` only.
  - The one remaining breach is the Signals reconnect (owner, ledger row 4).
