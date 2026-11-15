# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-11-15 ~22:30Z.** Agent-OS-Receipt `aa55ed12`.

## Mode
- **Owner execution directive 2026-11-15 (MD-118)** restates the 2026-11-08 unified directive
  (`docs/owner/UNIFIED_ENGINEERING_FORECASTING_DIRECTIVE_2026-11-08.md`, MD-116, MD-117): deployment reliability first,
  then backend correctness, mathematics, data integrity, operations, documentation; forecasting stays research only.
- Acceptance matrix and checkpoints: `docs/audits/remediation_2026-11-06/BACKEND_CAMPAIGN_LEDGER_2026-11-08.md`.
- **Frontend excluded** (#2112, #2132, #2171 owned elsewhere). Frontend needs go to `docs/ui/BACKEND_API_HANDOFF.md`.
- At most 4 editing workers, including the coordinator. Standing permission to merge reviewed, exact-head-green PRs.

## Production
- Serving `4b93f334c` (deployed 2026-11-15 22:16Z, run 43765683235): health ok. Carries every campaign PR through
  #2216. No campaign PR is open. Older `claude/*` PRs still open are owner-gated or parked: #1938 (owner
  decision), #1884 (more research required), #1873 (tied to #2202), #1852, #1513 (validation track).
- Trade routes (`statusQuo`, `valueUncertainty`) need sign-in; their production output has not been observed.

## Owner decisions (briefs: `docs/owner/DECISION_BRIEFS_2026-11-08.md`)
- Apply the required-check ruleset; approve running team-points study two (first possible run about 2026-12-22);
  #1938; division payout tiebreaker; median games in draft order; Hill validation target; TE basis; BDVM signal
  policy; source-vote holds; package model and one read-only box run (#2202); owner-id pseudonymization (#2207, D1–D6);
  best-alternative ranking rule for trade opportunity cost (#2211); credential rotation; off-box backup; operator
  re-run of the backup installer (`irreplaceableLedgers.coverage: unverifiable`).
- Data licensing (#2174): several live inputs may conflict with published terms; needs owner or counsel.
- Dependency bumps need a lock refresh with `uv` 0.9.26, which this machine lacks; Dependabot PRs cannot merge as-is.

## Next dependency-ready units
1. `records` / `franchise` first-hit cost is not explained by cache keys (#2216 receipt); measure on the box.
2. `/api/draft-capital` is not warmed (separate 300 s cache with Sleeper calls).
3. Everything else in the matrix waits on an owner decision above or on data that does not exist yet.

## Hazards
- Board-dependent tests are the recurring deploy-freeze cause. Use `tests/archive_fixtures` pinned helpers;
  the guards in `tests/test_pinned_board.py` enforce it.
- Generated UI fixtures (`frontend/__tests__/fixtures/trade-war-room`, `trade-multi-withheld`) and
  `tests/fixtures/forced_drop_flag_off_reference.json` must be regenerated under the pytest harness (a throwaway
  parametrized test), never by running the generator module directly; `trade-multi/*` comes from the live archive.
- Never `git stash`; never `git commit -a`; Ruff only via `bash scripts/format_python_changes.sh`.
- Long silent commands stall background agents; keep worker commands short or backgrounded.
