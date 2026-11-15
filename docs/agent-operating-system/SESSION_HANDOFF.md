# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-11-15 ~14:00Z.** Agent-OS-Receipt `aa55ed12`.

## Mode
- **Owner unified directive 2026-11-08 (third of the day):** `docs/owner/UNIFIED_ENGINEERING_FORECASTING_DIRECTIVE_2026-11-08.md`,
  intake MD-116, MD-117; priorities map onto MD-59 and MD-97 … MD-115. Forecasting is research only.
- Acceptance matrix and this checkpoint: `docs/audits/remediation_2026-11-06/BACKEND_CAMPAIGN_LEDGER_2026-11-08.md`.
- **Frontend excluded.** Frontend needs go to `docs/ui/BACKEND_API_HANDOFF.md`.
- At most 4 editing workers, including the coordinator. Standing permission to merge reviewed, exact-head-green PRs.
- Another session (`claude/website-audit-readiness-*`, memory and diagnostics work, #2188–#2198) also merges to `main`.

## Production
- Serving `e63d66298` (process started 2026-11-14 05:09Z); health ok, data about 1 h old.
- Deploys failed 2026-11-13 → 15 on three board- or runner-dependent tests. All three are fixed by #2199 (`91d0578f8`).
  **Next unit:** confirm the next Deploy Production run passes and production moves past `e63d66298`.

## Open campaign PRs (all independently approved; updated from main 2026-11-15)
| PR | What |
|---|---|
| #2183 | restore proof + irreplaceable ledgers in backup health (v4); systemd failure detection in the sweep |
| #2200 | TE basis and pick market evidence (research) |
| #2201 | property tests, pseudonymized real-roster fixture, skip budget 10 → 7 (merge after main is at 10 skips) |
| #2202 | package-model validation (insufficient data locally; box run proposed) |
Merge each once its exact head is green.

## Owner decisions (briefs in `docs/owner/DECISION_BRIEFS_2026-11-08.md`)
- Apply the required-check ruleset (brief 12); approve running study two (brief 1); #1938; division payout
  tiebreaker; median games in draft order; Hill validation target; TE basis; BDVM signal policy; source-vote holds;
  package model; public ids; credential rotation; off-box backup; one read-only box run for #2202.
- **Data licensing (from #2174):** several live inputs may conflict with published terms (Pro Football Reference via
  nflverse snap counts, Disney terms for ESPN feeds and the Clay PDF, Sleeper commercial use). Needs an owner or
  counsel decision.

## Next dependency-ready units
1. Verify the deploy after #2199 and production behaviour.
2. Merge #2183, #2200, #2201, #2202 when green; then verify `backup_health` v4 in production.
3. Remaining directive items: backend payload section contracts (MD-114), public-id consumer census (brief 11),
   documentation convergence (Priority 19), old PR disposition (Priority 20).

## Hazards
- Board-dependent tests in the hard gate keep recurring; pin inputs or use the `livedata` lane with a named
  deterministic replacement. `tests/archive_fixtures.newest_complete_contract` still builds with `csv_root=None`.
- Never `git stash`; never `git commit -a`; Ruff only via `bash scripts/format_python_changes.sh`.
- Long silent commands stalled several background agents; keep worker commands short or backgrounded.
