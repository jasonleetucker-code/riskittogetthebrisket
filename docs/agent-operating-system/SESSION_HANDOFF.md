# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-11-08 ~03:30Z.** Agent-OS-Receipt `741230de`.

## Mode
- Four owner directives of 2026-11-07 in force inside one program (CW-01 … CW-53,
  `docs/audits/remediation_2026-11-06/`); latest is the master correctness / CI directive
  (`docs/owner/MASTER_CORRECTNESS_CI_DIRECTIVE_2026-11-07.md`, MD-74 … 85). Authorization: `docs/EXECUTION_PLAN.md`.
- Standing permission to merge anything ready (green CI + independent review); owner gates stay binding.

## Production and main
- Production `de7b8dc9d` at 03:15Z (#2134 + #2136 live); the deploy for `7079e2689` (#2147) follows.
- Main green. **Open ours: none** (only owner-reserved #1938). Merged since 2026-11-07: #2129, #2131, #2133, #2128, #2123,
  #2135, #2137, #2138, #2139, #2141, #2140, #2130, #2142, #2143, #2144, #2145, #2146, #2134, #2136, #2147.

## CI — all three hard gates sharded and proven (directive Part 2, MD-76 DONE)
| gate | before | after (measured) |
|---|---|---|
| PR Validation | 78–120 min (serial step 74–106) | ~20 min (run 42411207802) |
| Deploy Production (execution) | ~105 min (validate 96.4) | 24.5–32.3 min over 6 runs |
| Release Candidate | ~100 min | 19.0 min (run 42436431533, tree `5eb4a3de…` agreed on every job) |
- One owner `scripts/ci_test_shards.py` + `config/ci/test_shards.json` (8 shards, floor 32,500, skip budget 290;
  durations refreshed from a complete run). Completeness proof in `Validate PR`, `Hard gate complete`,
  `Validate Release Candidate`. Deploy falls back to serial for targets without the owner or on
  `serial_hard_gate` dispatch; RC refuses a partial re-run ("re-run ALL jobs").
- Receipt check (#2130) runs on every PR; the State must be TESTED_IN_PR / MERGED / DEPLOYED /
  VERIFIED_IN_PRODUCTION and all twelve labels present. A body edit re-runs it.
- Runner contention: ~12 jobs per full PR vs GitHub Free's 20 — shards start staggered under load.

## Correctness / capture / performance landed
- Waivers: #2138, #2136, #2147 — id-first ownership with ONE holder owner (`src/draft/context.py::league_holder_index`),
  ONE balance field `faabBudget` (unknown withholds bids on /suggestions and the desk; lower of requested and
  observed wins; over-spent = known $0), position_not_started, desk refusals.
- Playoffs: #2134 refuses leagues with divisions (`league_divisions_unmodeled`), strict integral parse.
- Oracles: #2135, #2143 (playoff / title / draft slot / Game Day vs exact enumeration).
- False precision: #2137. Gameplan unavailable-not-zero #2128; alert cooldown #2123.
- Capture: #2140 deployed — late pregame snapshot, as-known injuries, board identity, atomic writes; box verified
  (run 42441936899: timer enabled, exit-code policy correct, 198 snapshots readable).
- Performance: baseline #2142; sitemap #2144 (2.7 MB → 77 KB per rebuild); `weeklyRecap.byKey` removed #2145 (~246 KB).

## Owner decisions pending
- #2137 wording left unchanged: "market overvalues", /arbitrage "Edge"/"STRONG BUY", Waiver Advisor "61% confidence",
  BDVM "Hit %", Monte Carlo "clear winner".
- #2134 owner question 1: the divisions refusal also withholds draft-slot odds that divisions cannot affect.
- Making `Receipt check` a required status check (repository setting).
- Unchanged: #1938 reserved; backup runbook / #1938 impact need box access; decision register + methodology proposals.

## Next dependency-ready units
- `src/waivers/advisor.py:~493` `max(0, int(balance or 0))` (inert today, flag off) → pass None.
- `/api/public/league` still 2.7 → ~2.47 MB: archives (816 KB) and activity feed (458 KB) dominate (#2144 analysis).
- P1 ledger: 56 / 15 / 10 / 4 of 85 (W24-F001 PARTIAL: union skip census missing).
- MD-78 (source independence / 0.30 haircut challengers), MD-83 (security / backups), CW-48 verification states.

## Machine / hazards
- Drive C: ~12–15 GB free (97–98%); ~25 older worktrees from earlier sessions remain (not removed — may hold unpushed
  work). The main checkout's `frontend\node_modules` is empty. One locked file under `rib-public-league-perf`.
- A dry run of `game-day-capture.yml` shares the `production-deploy` group: dispatch it only while no deploy is
  pending (a pending dispatch displaces / is displaced by a deploy).
- New workflow steps need entries in `config/ci/release_gate_classification.json`.
- Sharding exposes order-dependent tests: fix the test's isolation, never re-serialize.
- Never "fixes #<open PR>"; never `git stash`; never `git commit -a`; Ruff only via `bash scripts/format_python_changes.sh`;
  heredocs through the Bash tool unescape `\\n` (use the Edit tool for escaped literals).
