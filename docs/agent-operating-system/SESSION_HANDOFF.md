# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-11-07 ~18:35Z.** Agent-OS-Receipt `741230de`. Session `session_01BGLcxPv9489uMYWnm3GbTF`.

## Mode
- Owner directive 2026-11-07 "session resumption, remediation and continuous verification":
  `docs/owner/SESSION_RESUMPTION_DIRECTIVE_2026-11-07.md`; intake MD-56 … MD-64; decisions in
  `docs/owner/OWNER_DECISION_REGISTER.md` (section "Session resumption directive (2026-11-07)"). It continues the two
  2026-11-06 directives inside inventory CW-01 … CW-53 (`docs/audits/remediation_2026-11-06/`).
- Standing permission to merge anything ready (green CI + independent review); owner gates stay binding.

## Production (public endpoints, ~18:30Z)
- `/api/status` build.commit `a1a443b7` (main through #2107). Later merges deploy through the normal pipeline —
  re-check build.commit before claiming any of them is live. `/api/health` 200. `backup_health.stateBackup` healthy.

## Merged this session (2026-11-07)
#2106 records · #2108 batch S · #2107 Decision C (retire Next Best Targets) · #2105 Decision A (Terminal precedence
over BDVM) · #2124 Dependabot assessment · #2110 batch M1 · #2109 Decision B (/rosters Team Gameplan) · #2111 batch t2 ·
#2115 batch t1 · #2120 W09-F007 + W21-F003 (+ scrape bridge cookie) · #2121 W26-F003 no-cache · #2122 Hill docstring ·
#2113 W13-F003 proposal · #2114 W27-F005 proposal · #2117 W27-F001 proposal · #2119 W30-F008 proposal · #2118 CW-49
oracles · #2125 CW-52 dead-code census.

## Open (ours)
- #2123 W12-F005 player-keyed alert cooldown + failed-send retry: APPROVED at 7db46524; awaiting CI, then merge.
- P1 ledger update (this records branch): all 59 PENDING rows adjudicated; counts 51 CLOSED_VERIFIED / 17 PARTIAL /
  13 OPEN / 4 REQUIRES_OWNER_DECISION / 0 PENDING.
- CW-53 CI-parallelization study: worker resumed after a usage-limit stop; branch `claude/cw53-ci-parallel`.
- #1938 DRAFT (owner-reserved): promotion package `docs/valuation/idp_accuracy/PR1938_PROMOTION_PACKAGE.md`, reviewed
  ACCURATE at 678ffa66. Do not merge.

## Owner / box-operator items
- Box: `docs/ops/STATE_BACKUP_RESTORE_RUNBOOK_2026-11-07.md` (restore verification, store coverage, timers, :8000
  external probe). #1938 BDVM impact: read-only command in the package §11 (paste back the JSON).
- Owner decisions now pending: #1938 activation (+ ship the special-teams rule; fold F1 double-TD fix); W13-F003
  shadow evaluation + interim labels/alerts; W27-F005 offline shadow of the scale-neutral label; W27-F001 D1 (C2 gates),
  D1b (exclude The IDP Show — default include), D2 shadow, D3 /edge interim; W30-F008 target scale A/B/C + shadow +
  Autopilot-gate risk; W12-F005 confirm direction flips within 12h stay held; W12-F007 low-confidence BUY/SELL;
  W20-F003/F004 Terminal totals include picks; W09-F003 suggestions send picks?; W10-F004 partial-vendor pricing A/B/C;
  W13-F002 picks in BDVM capitals; W27-F003 /angle IDP; W20-F006 canonical team-direction classifier; W21-F001 injury
  news → value; Node 22 move (blocks jsdom 30 / vitest 5 / axe 4.14).

## Next dependency-ready units
- W07-F003/W07-F004/W25-F003 display: unpriced rows get a client `#`, tier and positional rank (it.fails pinned in
  batch t2 and W25-F003 tests — flip them in the same PR).
- W20-F010: `/api/gameplan` market/consensus/leagueAdjusted publish 0.0 → explicit unavailable (pinned in batch t2).
- Terminal news `newsScope` stamp ("roster" vs "league_unfiltered") — follow-up from the #2120 review.
- W24-F001/F002/F004 test-integrity items; nondeterministic `tests/test_hampel_filter.py::TestLiveBoardIdpAnchorEjectionRate`
  reads exports/latest (M1 note) — pin to an archive.
- CW-37: rebase-and-merge patch bumps #1920/#1688/#1687; grouped Python lock regeneration; CW-48 requirement joins.

## Hazards
- NEVER write "fix/fixes/closes/resolves #<open PR>" in a commit or PR body.
- The decision-coercion gate enforces on every file a PR touches: pre-existing unbaselined `x or 0` in a touched file
  fails the PR — fix them, never `--write-baseline`.
- Strict xfails/`it.fails` pin open defects: a repair PR must flip them, and must merge AFTER the PR that adds them.
- Full Validate PR ~90–110 min; many PRs in parallel queue on runners. Python formatting ONLY via
  `bash scripts/format_python_changes.sh` (Ruff 0.6.9; reviewers' local Ruff 0.16.9 gives false format diffs).
- Local Node 22 vs CI Node 20; `main` has one Node-22-only vitest failure (RankingsBoard) — not on CI.
- Never `git stash`; remove finished worktrees; usage limits can stop workers mid-task (resume them with SendMessage).
