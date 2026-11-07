# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-11-07 ~23:40Z.** Agent-OS-Receipt `741230de` (session start `47a8b19f`; Agent OS changed mid-session
via #2133's one-sentence §3 L2 note).

## Mode
- Four owner directives of 2026-11-07 are in force inside one program and inventory (CW-01 … CW-53,
  `docs/audits/remediation_2026-11-06/`): session resumption (MD-56 … 64), sitewide feature verification
  (MD-65 … 73), and **master correctness, reliability, performance & CI acceleration**
  (`docs/owner/MASTER_CORRECTNESS_CI_DIRECTIVE_2026-11-07.md`, MD-74 … 85). Authorization: `docs/EXECUTION_PLAN.md`.
- Standing permission to merge anything ready (green CI + independent review); owner gates stay binding.

## Production and main
- Production `build.commit` **a9477b84** (#2133) as of 23:12Z — past the stuck a1a443b7. Deploy 42417916628 (cf01caaa,
  carrying #2128/#2123/#2135/#2137) was validating serially. `deploy.yml` ignores `tests/**`-only pushes (#2129 and
  #2138 deploy with the next code merge).
- Main is green. Merged this session: #2131, #2129, **#2133** (sharded PR gate), #2128, #2123, #2135, #2137, #2138.

## CI — measured (directive Part 2)
- Before: serial hard gate 74.0–105.7 min on 8 green full runs (~93% of Validate PR); full runs 78–120 min.
- After (#2133, run 42411207802): **Validate PR 20.3 min**; 8 shards 10.8–17.7 min of tests; 34,567 collected,
  34,273 passed, **261 skipped (identical to serial)**, 33 xfailed; completeness verified (partition, verdicts,
  floor 32,500, skip budget 290). First actionable failure surfaced at ~3.5 min (run 42408987900).
- Owner: `scripts/ci_test_shards.py` + `config/ci/test_shards.json`; `Validate PR` = aggregator (`always()`).
- Five PRs at once queue on GitHub Free's 20 concurrent jobs (≈12 jobs per full PR) — wall time grows, nothing skipped.

## Open (ours) — in order
1. **#2139** deploy-gate shards (approved conditional on green). Head d4b8a352 adds the fix for an order-dependent
   test the split exposed (`test_in_memory_run_events_still_populated`, 50-cap buffer). Merge on green; the next
   deploy then validates in ~15 min instead of ~95. Also carries refreshed durations (1,382 files, 5,795 s).
2. **#2130** receipt check (approved after fixes). Head 7a9c8e2e classifies its workflow steps in
   `config/ci/release_gate_classification.json` (its earlier red). Merge on green. Making it required = owner setting.
3. **#2140** Week 10 capture (REQUEST_CHANGES → worker fixing: atomic temp+link writes, per-kind isolation, `--verify`
   exit codes before the window, Sunday TBD = unknown, `espn_injury_feed` gate status). **Deploy before Wed
   2026-11-11 20:00 UTC** for Week 10's early capture context; the Sunday late snapshot needs it before Sun 08:00 UTC.
   Rollback hazard: pre-PR code rejects weeks containing `*_pregame_late.json`.
4. This records PR (ledger + directive + handoff).

## Verification record (directive Part 9)
- P1 ledger: **56 CLOSED / 15 PARTIAL / 10 OPEN / 4 ROD of 85** (W20-F010 #2128, W12-F005 #2123 closed; W24-F001
  PARTIAL — floor gate done, union skip census missing).
- Independently verified this session: probability engines (#2135: playoff/title odds, draft slots, Game Day vs exact
  enumeration; mutation-checked), waiver workflow properties (#2138: 30 tests; two defects found and repaired).
- Week 9 pregame captured before kickoff for every league (198 snapshots; timer armed) — read-only box run 42411491760.

## Owner decisions pending (new this session)
- Wording left unchanged by #2137: "market overvalues", /arbitrage "Edge"/"STRONG BUY", Waiver Advisor "61%
  confidence", BDVM "Hit %", Monte Carlo "clear winner".
- Unchanged: #1938 reserved; backup runbook and #1938 impact need box access; decision register + four methodology
  proposals.

## Next dependency-ready units
- Shard `release-candidate.yml` (each shard must rebuild the same merge-candidate tree).
- #2135 follow-ups: one unmocked playoff-sim smoke test on a real snapshot; byes / median-game coverage.
- MD-77 source-health drift fixtures; MD-82 measured performance baseline (perf_baseline_2026-11-06.json exists).
- CW-48 per-feature verification states in the inventory.

## Hazards
- NEVER write "fix/fixes/closes/resolves #<open PR>" in a commit or PR body.
- New workflow steps need entries in `config/ci/release_gate_classification.json` (regenerate from
  `scripts/ci_gate_classification.enumerate_workflow_steps`, preserve order and ASCII escaping).
- Sharding changes which modules share a process: an order-dependent test can surface in any shard — fix the test's
  isolation, never re-serialize.
- Decision-coercion gate: no new `x or <default>`; never `--write-baseline`.
- Python formatting ONLY via `bash scripts/format_python_changes.sh`. Never `git stash`; never `git commit -a`.
- Heredocs through the Bash tool unescape `\\n` — use the Edit tool for string literals containing escapes.
