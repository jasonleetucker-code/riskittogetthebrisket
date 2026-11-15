# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-11-15 ~21:00Z.** Agent-OS-Receipt `aa55ed12`.

## Mode
- **Owner execution directive 2026-11-15 (MD-118)** restates the 2026-11-08 unified directive
  (`docs/owner/UNIFIED_ENGINEERING_FORECASTING_DIRECTIVE_2026-11-08.md`, MD-116, MD-117): deployment reliability first,
  then backend correctness, mathematics, data integrity, operations, documentation; forecasting stays research only.
- Acceptance matrix and checkpoints: `docs/audits/remediation_2026-11-06/BACKEND_CAMPAIGN_LEDGER_2026-11-08.md`.
- **Frontend excluded** (#2112, #2132, #2171 owned elsewhere). Frontend needs go to `docs/ui/BACKEND_API_HANDOFF.md`.
- At most 4 editing workers, including the coordinator. Standing permission to merge reviewed, exact-head-green PRs.

## Production
- Serving `4fc4b2ac5` (deployed 2026-11-15 17:38Z): health ok; backup health v4 live with `restoreProof: proven`.
- `main` is `b547e4b7b`. The deploys of `f51d7ea2f` and `bfdc3c0b1` failed only on
  `tests/api/test_hill_alignment_audit.py` (live CSVs read inside a pinned module), fixed by #2213. #2213 is
  test-only, so the next data refresh triggers the deploy that carries #2211 (status quo) and #2212.
  **Next unit:** confirm that deploy passes and production moves past `4fc4b2ac5`.

## Open campaign PRs
| PR | What | State |
|---|---|---|
| #2214 | guard: no hard-gate test reads today's inputs by path; 17 modules repointed | TESTED_IN_PR; remove the #2213 allow-list entry after merging main, then review |
| (pending) | public sections warmed after publish (playoffOdds cold 7.7–18.5 s) | worker in progress |

## Owner decisions (briefs: `docs/owner/DECISION_BRIEFS_2026-11-08.md`)
- Apply the required-check ruleset; approve running team-points study two (first possible run about 2026-12-22);
  #1938; division payout tiebreaker; median games in draft order; Hill validation target; TE basis; BDVM signal
  policy; source-vote holds; package model and one read-only box run (#2202); owner-id pseudonymization (#2207, D1–D6);
  best-alternative ranking rule for trade opportunity cost (#2211); credential rotation; off-box backup.
- Data licensing (#2174): several live inputs may conflict with published terms; needs owner or counsel.
- Dependency bumps need a lock refresh with `uv` 0.9.26, which this machine lacks; Dependabot PRs cannot merge as-is.

## Hazards
- Board-dependent tests are the recurring deploy-freeze cause. Use `tests/archive_fixtures` pinned helpers;
  the guards in `tests/test_pinned_board.py` enforce it.
- Generated UI fixtures (`frontend/__tests__/fixtures/trade-war-room`, `trade-multi-withheld`) and
  `tests/fixtures/forced_drop_flag_off_reference.json` must be regenerated under the pytest harness (a throwaway
  parametrized test), never by running the generator module directly; `trade-multi/*` comes from the live archive.
- Never `git stash`; never `git commit -a`; Ruff only via `bash scripts/format_python_changes.sh`.
- Long silent commands stall background agents; keep worker commands short or backgrounded.
