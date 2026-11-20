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
| 1 | P0 DLF rookie boards | PR OPEN | Vendor publishes no rookie rankings since 2026-11-17 22:27 UTC: same RankingEngine table, 0 rows, 0 expert columns (Superflex: 287 rows, 6 experts). Not a parser defect. | `vendor_empty` state + exit 4; last-good kept; per-board state file; fail-closed rookie class guard; better probe | #2275 | 261 targeted tests | pending deploy: box journal + `dlf_board_states.json` | owner decision on the stale `dlfRookieSf` vote (§1) | review → release candidate → merge → deploy → verify |
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
| 15 | §17 audit leftovers | IN PROGRESS | see §17 table | waves 1–2 | — | — | — | — | — |

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
- Names the state (`vendor_empty`).
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

Recommendation: **B**. The board is frozen, not merely slow, and a frozen vote at decaying weight is noise. This is
a source-voting change, so it is yours to approve.

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

## Integration log

(Appended as trains land.)
