# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-11-07 ~19:45Z.** Agent-OS-Receipt `741230de`. Session `session_01BGLcxPv9489uMYWnm3GbTF`.

## Mode
- Three owner directives of 2026-11-07 are in force, inside one program and inventory (CW-01 … CW-53,
  `docs/audits/remediation_2026-11-06/`):
  - session resumption: `docs/owner/SESSION_RESUMPTION_DIRECTIVE_2026-11-07.md` (MD-56 … MD-64);
  - **complete sitewide feature verification**: `docs/owner/SITEWIDE_FEATURE_VERIFICATION_DIRECTIVE_2026-11-07.md`
    (MD-65 … MD-73), which runs through CW-48 … CW-53;
  - authorization for both is in `docs/EXECUTION_PLAN.md`.
- Standing permission to merge anything ready (green CI + independent review); owner gates stay binding.

## Production and main (~19:40Z)
- `/api/status` build.commit `a1a443b7` (#2107). **Deploy Production has failed on every main push since**, including
  runs 3778 (#2127) and 3779 (19:09Z refresh).
  - Likely cause (not yet confirmed from the deploy logs): main is red on
    `tests/api/test_dlf_offense_only_vote.py::test_no_confidence_rise_from_the_held_familys_silence`, red since the
    13:37Z data refresh.
  - Nothing merged after #2107 is live. Re-check after #2129 merges.
- The **fix is PR #2129**: a test-only change, so 0 values move.
  - Root cause: the cured-rejection guard's replay rejects FantasyPros/Draft Sharks IDP because of DLF's vote. The
    test's helper read only `droppedSources`.
  - Independently reviewed: APPROVE. Full backend CI started 18:38Z, ETA ~20:10Z. **Merge on green.**
  - Optional follow-up from the review: in `_recovered_evidence`'s cured branch (test file ~:279), re-run
    `_lost_evidence_replay` on the held row instead of trusting a missing stamp, and subtract
    `freshnessExcludedSources` (~:270).

## Merged this session (2026-11-07)
#2106 · #2108 · #2107 · #2105 · #2124 · #2110 · #2109 · #2111 · #2115 · #2120 · #2121 · #2122 · #2113 · #2114 · #2117 ·
#2119 · #2118 · #2125 · #2126 (ledger + handoff) · **#2127** (unpriced rows show no invented `#`/tier/positional rank,
CLAUDE.md corrected; 43a0d5b7).

## Open (ours) — merge queue, in order
1. **#2129**: merge on green (above).
2. **#2128** W20-F010 (head b3b28af6): `/api/gameplan` market/consensus/leagueAdjusted publish null + unavailable,
   never 0.0.
   - Both review findings are addressed: baseline entries removed (f622d18d); tally / xfail count updated (b3b28af6).
   - Red only from the main-red test (commented on the PR). After #2129: merge main in, CI, merge.
3. **#2123** W12-F005 (approved at 7db46524): player-keyed alert cooldown + failed-send retry. After #2129: merge
   main in, CI, merge.
   - It shares `tests/api/test_audit_cw40_batch_t2_open.py` with #2128; a trial merge is clean.
4. After 2 and 3 merge: in `P1_LEDGER.md` set W20-F010 (#2128) and W12-F005 (#2123) to CLOSED_VERIFIED.
   - Expected counts: 56 CLOSED / 14 PARTIAL / 11 OPEN / 4 ROD of 85.
   - Today's file, which already has W07-F003 / W07-F004 / W25-F003 closed: 54 / 15 / 12 / 4.
- #1938 DRAFT (owner-reserved): promotion package reviewed ACCURATE at 678ffa66. Do not merge.

## Workers started this session (may not survive a session change — check GitHub for their branches / PRs)
- CW-53 CI parallelization (pytest-xdist on the hard gate):
  - branch `claude/cw53-ci-parallel`; local commit 68dc1865, not pushed at 19:40Z;
  - touches `pr-validation.yml` and the requirements / lock files;
  - the worktree is `.claude/worktrees/cw53` in the main checkout.
- CW-53 PR verification receipt CI check: **PR #2130** (head 73b712cf); needs an independent review and its first CI
  run.
  - branch `claude/cw53-pr-receipt-check`;
  - 31 new tests and L1 green;
  - offline run: #2127, #2128, #2123 and #2125 have no receipt section (would FAIL); #2129 is tests-only (advisory);
  - new `scripts/check_pr_verification_receipt.py`, `.github/workflows/pr-verification-receipt.yml`, template fields
    and a standard subsection;
  - not a branch-protection required check (owner setting).
- CW-49 probability oracles:
  - branch `claude/cw49-probability-oracles`;
  - exact-enumeration and analytic oracles for `src/ros/playoff_sim.py`, draft-slot distribution, `game_day_sim.py`;
  - write-up `docs/engineering/CW49_PROBABILITY_ORACLES_2026-11-07.md`.
- CW-50 waiver workflow verification:
  - branch `claude/cw50-waiver-workflow-verification`;
  - checks eligible players, FAAB ≤ balance, roster capacity, protections and the NO TRANSACTION alternative;
  - write-up `docs/engineering/CW50_WAIVER_WORKFLOW_VERIFICATION_2026-11-07.md`.
- If a branch has no PR, re-dispatch from the description above. Every worker PR needs an independent review before
  merge.

## Verification record (directive Part 9) — honest numbers
- Census recomputed on main 2b225e63 (`python scripts/feature_census.py --out-dir <tmp>`; the committed
  `FEATURE_CENSUS.md` is older):
  - 500 surfaces: 229 routes, 61 pages, 88 bridges, 68 flags, 54 jobs;
  - 9 have no test reference, all of them scheduled jobs;
  - 21 have weak references only.
- A reference is not verification. Independently oracle-verified so far:
  - FAAB engine and BDVM ROS blend (#2118, `docs/engineering/CW49_ORACLES.md`);
  - package model, confidence gate, blend median (existing `*_oracle.py` tests);
  - rookie-auction whole dollars (`tests/draft_valuation/`);
  - lineup solver (vs Sleeper awards).
  - Probability engines and waivers are in progress (workers above).
- No per-feature "verified against intent" state exists yet in the inventory (CW-48 / MD-55 / MD-73 open).

## Owner / box-operator items
- Box: `docs/ops/STATE_BACKUP_RESTORE_RUNBOOK_2026-11-07.md`. #1938 BDVM impact: read-only command in the package §11.
- Making `pr-verification-receipt` a required check is a repository-settings action for the owner.
- Pending owner decisions are unchanged: see the previous list in `docs/owner/OWNER_DECISION_REGISTER.md` and the four
  methodology proposals under `docs/valuation/methodology_proposals/`.

## Next dependency-ready units
- The merge queue above, then the deploy check (build.commit should move past a1a443b7).
- CW-48: add per-feature verification states to the existing inventory (no second ledger).
- CW-50: tests for the 9 unreferenced timers (census list).
- W24 test-integrity items; pin `tests/test_hampel_filter.py::TestLiveBoardIdpAnchorEjectionRate` to an archive.
- Terminal `newsScope` stamp. CW-37 patch bumps #1920 / #1688 / #1687.

## Hazards
- NEVER write "fix/fixes/closes/resolves #<open PR>" in a commit or PR body.
- The decision-coercion gate enforces on every touched file: fix unbaselined `x or 0`, delete stale baseline entries
  by hand (count = entries), never `--write-baseline`.
- Strict xfails / `it.fails` pin open defects: a repair PR flips them and merges AFTER the PR that adds them.
- Full Validate PR ~90–110 min. Python formatting ONLY via `bash scripts/format_python_changes.sh` (Ruff 0.6.9).
- Never `git stash`; remove finished worktrees; usage limits can stop workers mid-task.
