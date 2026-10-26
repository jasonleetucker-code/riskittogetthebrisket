# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-10-26 ~12:50Z.** Agent-OS-Receipt `cb64f74c`. Concurrency limit: four workers (owner 2026-10-26).

## P0 status: #1939 merged, verification in progress
- **#1939 is MERGED** (squash `6eddc569f`, 11:33Z). An independent review returned APPROVE_WITH_NITS. Checks were green
  on the exact head. Main had moved only through automated data commits (BENIGN_AUTOMATION_MOVE).
- **Deploys:** Deploy Production run 40315867455 is still validating. A newer push deploy, 40322694960, is queued.
- **Verification refresh:** GitHub throttled the 12:42Z cron slot, so I started refresh run 40325142841 by hand at
  12:46Z.
- **Pass criteria for that run:**
  - the job runs on the 24.04 image, with no Chromium warning;
  - the `_last_success` stamps for `ktc*`, `idpTradeCalc` and `draftSharks*` move past 2026-10-25T12:06Z;
  - separately, `lastContentChange` advances for KTC and DraftSharks. It should NOT advance for IDPTC, whose vendor page
    still says 10/10.

## Draft PRs opened this session
None of these is merged. L0 Fast Checks is green on all of them; Validate PR is still pending.

| PR | branch / head | what | tests (local) |
|---|---|---|---|
| #1950 | `claude/auction-rehearsal-rebase` `1e99a02c0` | Auction Phase 2 merged with main + 6 security-review follow-ups (reports mock-only, …) | 390 auction, 27 api, 55 vitest |
| #1951 | `claude/li1842-defect-fixes` `24052113b` (on #1948) | LI1842 defects 01/03/04/06/09/10/11 | 607+6xf, 209, 120 vitest |
| #1952 | `claude/injury-feed-parser-fix` `1157499be` | ESPN injuries parse 274 of 800 (was 0); events to a shadow file only | 120 + 43 |
| #1953 | `claude/refresh-silent-failure-signals` `1669a49e0` | refresh warns on unstamped/preserved browser sources; diagnostic pin | 34 + 70 |
| #1954 | `claude/fix-misleading-ui-strings` `1fd4a5770` | Settings value-basis truthful; waiver-compare charset | 39 py, 55 vitest |
| #1955 | `claude/py-security-bumps-locked` `2dbf1fd49` | aiohttp/certifi/pillow with lock refresh; 100 of 111 alerts; prove-* GREEN in CI | 223 OCR, 84 deps |
| #1956 | `claude/health-dlf-session-path` `f606ba310` | `/api/health` reads the real DLF session jar | 116 |
| #1957 | `claude/sharp-crawl-404-breaker` `5b544d91a` | 404 leagues no longer trip the `sleeper_api` breaker; gone leagues skipped | 464 + 173 |
| #1958 | `claude/ros-collector-honest-status` `29de5cdf3` | ROS `kept_previous` status + content clock (reporting only) | 21 new, 989 ros |

#1934 (Agent OS four-worker policy + this handoff) is ready for review.

**Reviews:**
- #1939: APPROVE_WITH_NITS (merged).
- #1950: APPROVE_WITH_NITS. All six of its findings are fixed at `1e99a02c0`.
- #1952 and #1957: independent review running.

## Running (subagents)
- Final audit report writer: `docs/audits/RESEARCH_PROMOTION_READINESS_AUDIT_2026-10-25.md` + `.json`, as a draft PR.
  All 125 items are assessed in `.claude/worktrees/_audit_inputs/` (local, untracked).
- BDVM projection refresh. It reports failed sources honestly, and moves the IDP Show parser output to a shadow file
  (`claude/bdvm-idpshow-projection-honesty`).
- Independent review of #1952 and #1957.

## Integration queue (pre-existing; checks green; none reviewed this session)
- **Base main:** #1933, #1929, #1931, #1936, #1940, #1941, #1943, #1945, #1944, #1947, #1843.
- **Stacked:** #1942 on #1940; #1937 / #1946 / #1949 on #1935; #1938 on #1931 (owner decision, changes BDVM);
  #1951 on #1948.
- **Superseded once its replacement is reviewed/green:** #1533 by #1950; #1855 / #1895 / #1896 by #1955.
- **Codex-owned:** #1921.

## Owner decisions pending
- **Data and valuation:**
  - #1938: BDVM nflverse scorer fixes.
  - Injury events into BDVM (after #1952).
  - IDP Show projections into BDVM (after the BDVM honesty PR).
  - ROS freshness multiplier on the content clock (#1958).
- **League config:** LI1842 open defects 02 (TE multiplier), 05, 07 (roster cap), 08 (POST leagueKey),
  12 (trade_deadline), 13 (auction provenance).
- **Ops and monitoring:**
  - `SHARP_SMOKE_TOKEN`: the Sharp production smoke check has never measured anything.
  - #804 rank-digest capture cadence.
  - Whether the DFS tick should keep running while DFS is paused.
  - Retire the Codex OneDrive orchestrator.
  - Turning the run red when a browser source is preserved for N runs (#1953, proposed N=3).
  - Sharp crawl exit-code semantics (#1957).
- **Earlier, still open:**
  - cut-ladder tie-break;
  - forced-drop activation (recommendation: not yet);
  - Public Waiver Wire scope;
  - IDP Show board swap;
  - 2026 holdout;
  - 17-game re-run;
  - lineage census box run;
  - backend memory canary.

## Hazards
- **Disk:** freed from 1.9 GB to 121 GB free by removing 48 clean, pushed worktrees and the regenerable folders. 44
  dirty or unpushed worktrees remain, including Codex ones. Inspect before deleting any of them.
  `~/.codex/visualizations/2026/09/10/...` holds about 33 GB.
- **Never use `git stash`.** Commit explicit paths only.
- **Deploy concurrency:** GitHub keeps only the newest pending run in the `production-deploy` group, so a new push can
  cancel a queued deploy. Confirm a commit is live from the first FINISHED deploy whose SHA contains it
  (`/api/status .build`).
