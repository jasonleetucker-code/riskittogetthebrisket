# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-10-27 ~14:30Z.** Agent-OS-Receipt `cb64f74c`. Concurrency limit: four workers. The coordinator's own coding
counts toward the four.

## Mode in force: BUILD_ONLY_MAX_THROUGHPUT (owner directive, 2026-10-27)
- **Paused:** merges and production deploys. **Prohibited:** turning any flag ON, publishing the private MCP, and
  changing production env, config or permissions.
- **Allowed:** isolated branches, worktrees, draft PRs, tests and reviews.
- **Unaffected:** the standing merge authorization. It resumes when the owner ends build mode, under the usual gates:
  - exact-head green checks;
  - an independent review (delta re-review after any later commit);
  - stacked dependencies merged first;
  - L2 on the merged tree.
- **Holds:** #1938 is still ON HOLD. Owner-held flags and methodology need an explicit owner decision.

## Production
- **Live:** `44695ab61` (#1985); `/api/health` 200.
- **Data deploys BLOCKED since 2026-10-27T08:29Z.** Deploy run 40473808525 failed only on the census SHA flake,
  `tests/market_trades/test_own_league_census.py::test_committed_outputs_carry_no_ids_or_names`.
  - **Fix:** #1988 (tests only, green, independently approved), held by the merge pause.
  - **Until it merges**, data refreshes don't reach production, and about half of all PR CI runs fail on the same flake.
  - **Owner decision** requested as a build-mode exception.
- `test_pick_refinement` (Garrett / Hamilton rank bands) runs in the deploy run's ADVISORY lane; it did not block.
  #2002 fixes it. The cause is IDP source authority, not a code defect: IDP anchors are SEVERELY_DEGRADED (~37% weight
  retained):
  - IDP Show content is from 2026-08-19 (weight 0);
  - FantasyPros IDP's label reads 9/04;
  - DLF IDP is held from voting.

## O7 and #1985 (owner-authorized 2026-10-27)
- **O7 COMPLETE** in #1989 (approved at `59e114a49`): one read-only, aggregate-only production run.
  - Canonical lane from 2026-07-20 (live from 2026-08-16).
  - Under the strict knowledge cutoff, 11 of 80 2026 trades are fully canonical-priced, all of them already
    IDPTC-priced.
  - **H2 → H7** (<5 of 55 under the full §2.4 rule). H6d stays unavailable.
- **#1985 privacy: investigation complete; no action taken.**
  - Only `refs/pull/1985/head` (plus GitHub's orphan test-merge commits) reaches `c95390a98`. Main, every branch and
    tag, and the other PRs are clean; there are no forks.
  - **Recommended:** GitHub Support dereferences PR #1985, garbage-collects and clears cached views. No main rewrite.
  - The plan is kept outside the repo (pointing at the commit would increase exposure).
  - Needs the owner's explicit approval to file a Support ticket from the owning account.

## Build-sprint draft PRs (all unmerged; reviewed at the head shown)
| PR | head | content | review | CI | owner gate |
|---|---|---|---|---|---|
| #1988 | 4cac09d7f | census SHA-flake test fix | APPROVE | green | merge exception (unblocks deploys) |
| #1989 | 59e114a49 | O7 evidence + scripts | APPROVE + delta | green | — |
| #1990 | 44c4a7c49 | Trade Advisor launch-gate engineering, browser timeout, permission checklist, 59-test multi-team matrix | APPROVE + delta | flake | responseFloorMs (250 recommended), permission record, admission sizes, launch |
| #1991 | d1bae4e28 | DEFECT-07 (report-only) / 08 / 12 / 13 league propagation | APPROVE + delta | pending | DEFECT-07 cap source; 02 and 05 decisions |
| #1992 | 2f33fabd7 | sim V3 challenger (preregistered): V3_DOES_NOT_BEAT_FALLBACK | APPROVE | flake | C3 caveat design; whether to preregister v4 |
| #1993 | fde8f1ce0 | dependency advisories, 10 of 11 (#1920 covers setuptools) | APPROVE | green | — |
| #1994 | 3c5c52ee0 | Waiver Advisor (flag `waiver_advisor` default OFF, route private) | APPROVE + delta x2 | pending | activation; FAAB season-phase fix |
| #1995 | c04adfff5 | private MCP remediation on top of #1921 (single composer, allowlist, redaction pinned) | APPROVE + delta x2 | flake | merge, publish, token, plugin install |
| #1996 | 86a9d0078 | public diagnostics boundary (/api/status, /health, /uptime) + truthful monitoring | APPROVE + delta | flake | backup readability option (status file recommended) |
| #1997 | 04185392d | DraftSharks ROS IDP rank-basis split + report-only guard | APPROVE + delta | pending | new `draftSharksRosIdp` voter (ROS lane) |
| #1998 | 4e85c5cb2 | G2 IDP source-integrity shadow evaluation (6 of 8 B-gates pass, 7 defects) | APPROVE + delta | pending | FP freshness rule, IDP universe rule, V2.1-sealed boards |
| #1999 | f0b5be7d8 | perf: presim eligibility reuse (~5x, byte-identical) + /league tab preload | APPROVE | pending | — |
| #2001 | c720bf5b0 | G2-D2 Tuimoloau alias + G2-D3 excludes_rookies flags (served-value change) | APPROVE | pending | release of value changes |
| #2002 | a353327af | pick-refinement live-rank gate (IDP-degraded rows, catastrophic floor) | APPROVE + delta | pending | — |
| #2003 | 6f4ede95b | [HOLD] DEFECT-02 manual TEP override withdrawal | APPROVE | pending | withdraw the override (yes/no) |

## Integration order (when merge mode resumes; do not run it before)
1. **#1988:** census flake, which unblocks every other PR's CI and production deploys.
2. **Independent, low-risk:** #1989, #2002, #1993 (high-risk class: both L2 suites run), #1999.
3. **#1996, then #1994.** Both touch `server.py` in disjoint hunks; #1994 also edits `src/api/feature_flags.py`. Rebuild
   #1994's merge base after #1996 lands and re-run its flag-count / reachability tests.
4. **#1991, then #1990** (independent; both touch the trade surface lightly).
5. **#1997** (ROS lane; owner approval for the new voter key).
6. **#1995** (MCP; needs #1921 reconciliation first: decide whether #1995 supersedes it).
7. **#1992, #1998:** research only, any time after #1988.
8. **Owner-gated value changes:** #2001 and #2003, only after their owner decisions.
- **Expected checks:** L0, Validate PR (path-aware L2; #1993 and anything high-risk runs both suites), and the release
  candidate at L3.
- **Rollback:** each PR is self-contained. Flags default OFF. #2003 rolls back with `_TEP_OVERRIDES_DISABLED = False`.

## Owner decisions pending (complete list)
- **Build-mode merge exception for #1988** (production data deploys blocked).
- **#1985:** approve filing the GitHub Support request.
- **Survey D1–D6; preregistration O1–O6 and O8.** O7 is done.
- **Advisor launch gates (#1990):** response floor, permission record, admission and rate-limit sizes.
- **Waiver Advisor (#1994):** activation; list bids ignore season phase (FAAB lane).
- **Values:**
  - DEFECT-02 (#2003);
  - DEFECT-07 cap source;
  - DEFECT-05 Consensus Edge card;
  - #2001 release;
  - #1997 new ROS voter.
- **IDP source authority:**
  - IDP Show stale since 08-19 (has its chart moved?);
  - FantasyPros IDP clock rule;
  - DLF IDP hold;
  - IDP universe gated on IDPTC (G2-D1).
- **Backups:** status-file option (#1996 / #1970). `SHARP_SMOKE_TOKEN`.
- **Sim:** C3 calibration caveat design; whether to preregister v4. Championship probability stays uncalibrated
  (IDPM-10).
- **Still open from before:**
  - CI duration (120 min limit);
  - #1938;
  - BDVM activations;
  - Consensus Edge artifacts (run 36708000268 expires 2026-10-30T11:23Z);
  - LI1842 defects (02 and 05 above);
  - the rest of W22-F005, now addressed by #1996.

## Hazards
- **GitHub API quota is shared.** Poll at most every 5 minutes with batched calls.
- **Census SHA flake** hits any run whose merge SHA has a 9+ digit decimal run, until #1988 lands. Read the failing test
  name before "fixing" a PR.
- **Never pipe a PR body through a process that can fail mid-write.** `gh pr edit --body-file` with a truncated file
  blanks the body. Recover from GraphQL `userContentEdits`.
- **Agents sharing one scratchpad can overwrite each other's files.** Use unique file names per agent.
- **Windows-only local failures** (not regressions; Linux CI decides):
  - the `resource` module;
  - symlinks and chmod;
  - CRLF hashes and line-ending regexes;
  - backslash paths, including `test_feature_flag_reachability` and `test_ui_parallel_governance`;
  - timezone labels.
- **Git:** never `git stash`; commit explicit paths only; never junction `node_modules`; reviewers use their own
  detached worktrees and remove them afterwards.
- **Deploys:** only the newest pending run in `production-deploy` survives. Confirm the live build with
  `/api/status .build.commit`.
