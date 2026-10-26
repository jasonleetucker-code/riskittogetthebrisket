# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-10-26 ~14:30Z.** Agent-OS-Receipt `cb64f74c`. Concurrency limit: four workers (owner 2026-10-26).
No subagents are running.

## Merged + live
- **#1939** (squash `6eddc569f`, merged 11:33Z): the scheduled refresh is pinned to ubuntu-24.04.
  - **Production:** `/api/status .build.commit` = `6eddc569f`, process started 13:07:59Z.
  - **Verified:** refresh run 40325142841 (dispatched 12:46Z) ran on 24.04.
    - The `_last_success` stamps for `ktc*` and `idpTradeCalc` moved to 12:50:16Z, and `draftSharks*` to 12:52:55Z.
    - Content changed for KTC and DraftSharks IDP (12:53:33Z).
    - IDPTC content stays at 2026-10-10. That is vendor staleness, not a fetch failure.
    - The evidence is posted on #1939.
- **Nightly E2E:** run 40329220180 (13:16Z) was green. Issue #1918 is closed.

## Draft PRs from this session (none merged)
Every PR in this table had an independent review, with findings fixed afterwards unless noted.

| PR | head | review | what |
|---|---|---|---|
| #1950 | `1e99a02c0` | APPROVE_WITH_NITS; 6 findings fixed | Auction Phase 2 + security follow-ups; supersedes #1533 |
| #1951 | `7e6b0ef9f` (on #1948) | APPROVE_WITH_NITS; nits fixed | LI1842 defects 01/03/04/06/09/10/11 |
| #1948 | `155f6d505` | APPROVE_WITH_NITS; nits fixed | config propagation matrix + metamorphic tests |
| #1952 | `52f373b94` | APPROVE_WITH_NITS; hardened | ESPN injuries parse 274 of 800 (was 0); shadow events only |
| #1953 | `8bd2cbbc5` | APPROVE_WITH_NITS | refresh browser-source signals; release-gate entry fixed |
| #1954 | `1fd4a5770` | APPROVE_WITH_NITS | Settings value-basis truthful; waiver-compare charset |
| #1955 | `2dbf1fd49` | APPROVE_WITH_NITS | aiohttp/certifi/pillow with lock refresh; prove-* green; supersedes #1855/#1895/#1896 |
| #1956 | `f606ba310` | APPROVE_WITH_NITS | `/api/health` reads the real DLF session jar |
| #1957 | `c0e535e2e` | APPROVE_WITH_NITS; hardened | Sharp 404s no longer trip the breaker |
| #1958 | `c741ae050` | APPROVE_WITH_NITS | ROS kept-previous status + content clock; coercion fixed |
| #1959 | `667274f26` | APPROVE_WITH_NITS; nits fixed | BDVM refresh honest status; IDP Show parser to shadow |
| #1960 | `748d20a0a` | — | audit report + inventory (125 items, 39 defects) |

Reviews of pre-existing PRs, all posted on the PRs:
- **APPROVE:** #1935, #1941, #1949.
- **APPROVE_WITH_NITS:**
  - #1936, #1940, #1942 (now merged with #1940's head), #1943, #1945 (X2/Q3 relabelled)
  - #1944, #1946, #1947, #1843
  - #1938, with an owner decision brief
- **#1937:** REQUEST_CHANGES, then all five findings fixed at `7c418c4dd`. Replay: only roster 2 (Byron Murphy) differs, and 216 of 216 picks are identical.

## Merge order (when authorized)
1. #1933 (CI unblock), #1934 (Agent OS + handoff)
2. #1955, #1956, #1953, #1954, #1958, #1952, #1957, #1959, #1950, #1960
3. #1931, then #1938 (owner decision)
4. #1935, then #1937 / #1946 / #1949
5. #1940, then #1942; #1936 / #1941 / #1943 / #1945
6. #1948, then #1951; #1944, #1947, #1843, #1929

Close #1533 after #1950 merges, and #1855 / #1895 / #1896 after #1955 merges.

## Owner decisions pending
- **#1938 nflverse scorer fixes.** Recommended: ship WITH the special-teams de-dup, after a box before/after of
  `run_valuation` plus the alert sweep. There is no flag; rollback is a revert.
- **Activations into BDVM:**
  - injury events (#1952);
  - IDP Show projections (#1959 switch);
  - a ROS content-clock freshness multiplier (#1958).
- **LI1842 open defects:** 02 TE multiplier, 05, 07 roster cap, 08 POST leagueKey, 12 trade_deadline,
  13 auction provenance.
  - Defect 07 may be taxi accounting: 24 roster positions + 3 taxi = 27.
  - Should `/api/intel/leads` return 503 for a league whose data isn't loaded, or just leave out the fit/value terms?
- **Credentials and signals:**
  - provide `SHARP_SMOKE_TOKEN` (the smoke check has never measured anything);
  - run red after a browser source is preserved for N runs (#1953);
  - Sharp crawl exit-code semantics (#1957).
- **Housekeeping:** #804 capture cadence; DFS tick while DFS is paused; retire the Codex OneDrive orchestrator.
- **Earlier, still open:**
  - cut-ladder tie-break (#1945 X2) and forced-drop activation (recommended: not yet)
  - Public Waiver Wire scope
  - IDP Show board swap
  - 2026 holdout; 17-game re-run
  - lineage census box run
  - backend memory canary

## Hazards
- **Disk:** about 121 GB free after removing 48 clean, pushed worktrees and the regenerable folders. 44 dirty or
  unpushed worktrees remain (some are Codex's). Inspect before deleting.
- **Git:** never `git stash`; commit explicit paths only; never junction `node_modules`.
- **Deploys:** only the newest pending run in the `production-deploy` group survives, so confirm what is live from
  `/api/status .build`.
