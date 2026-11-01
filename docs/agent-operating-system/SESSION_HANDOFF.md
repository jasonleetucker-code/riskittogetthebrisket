# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-11-01 ~15:30Z.** Agent-OS-Receipt `cb64f74c`. Workers: four plus the coordinator.

## Mode
- Owner directive 2026-11-01 ("MASTER DEVELOPMENT DIRECTIVE"), decisions 1–10 verbatim in
  `docs/owner/CHASE_UPSIDE_MASTER_DIRECTIVE_DECISIONS_2026-11-01.md`; intake MD-1 … MD-16; execution-plan section at
  the top of `docs/EXECUTION_PLAN.md`; register section "Master development directive (2026-11-01)".
- Standing merge authorization applies: exact-head green, independent review (delta re-review after any later
  commit), stacked dependencies first.

## Settled by the 2026-11-01 decisions (were pending)
- NC-A: ROS diagnosis accepted; G3 stays FAILED; CR research + optional `rosPointsPerWeek` shadow; no promotion.
- NC-B D-A / D-B: not promoted; read-only comparison authorized.
- NC-D: `responseFloorMs` 300 (provisional); admission and limiters unchanged; public launch still blocked; odds
  wording decided (decision 9).
- #2006: restore the deep-tail rookie rule (decision 3 gates).
- RCV-7: Roster Construction conditional private activation (decision 1 conditions); 2025 slots never inferred
  (decision 2).
- FAAB list-bid season phase: already fixed by IST-7 (#2018, `29216a529`); the old "unassigned" note was stale.

## Lanes (see `docs/WORK_CLAIMS.md`)
- **Worker 1:** #2031 review; #2032 naming-canon parity fix + rebase; decision 9 wording PR.
- **Worker 2:** Roster Construction parity census, integrity tests, 2025 unavailable state, timing / mobile; activation
  PR only if every gate passes (lands after #2032 — both touch `nav-model.js` / `server.py` capabilities).
- **Worker 3:** #2006 rebase + re-measure; #2035 format fix, review, Week 8 run; ROS prereg.
- **Worker 4:** streaming gap decomposition + weekly IDP source census + scenarios; outlier V2 / IDP Show
  comparison (read-only); advisor floor 300 ms; read-only production security audit.

## Production
- Prod flags at 15:00Z: `waiver_advisor` ON, `idp_streaming` ON, `roster_construction` OFF,
  `brisket_trade_advisor` OFF, `source_freshness_schedule_v2` OFF. Verify with `/api/status` (`featureFlags`,
  `build.commit`).
- **P-1:** live nginx sends none of the declared security headers; `deploy/apply_hardening.sh` is box-operator only.

## Still owner-reserved
- Public Trade Advisor launch and per-source permissions (OD-3); box-operator hardening; CR promotion; DLF IDP release;
  freshness v2; IDP Show board swap; #1884 / #1938 / #1873 / #1852; Sim V3; `dynasty_new` taxi cap; #1985 GitHub
  Support filing (owner account); League Tycoon.

## Hazards
- Encoding guard is in the hard gate: new Python passes `encoding="utf-8"` to text-mode IO.
- Never `git stash`; commit explicit paths; `npm ci` per worktree; only the newest pending deploy run survives.
- GitHub API quota is shared across sessions: no polling loops.
