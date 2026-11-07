# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-11-07 ~05:15Z.** Agent-OS-Receipt `741230de`. Session `session_01BGLcxPv9489uMYWnm3GbTF`.

## Mode
- Two owner directives of 2026-11-06, one program:
  - Sitewide remediation: `docs/owner/SITEWIDE_REMEDIATION_DIRECTIVE_2026-11-06.md`; intake MD-38 … MD-46.
  - Continuous QA / feature-intent verification: `docs/owner/CONTINUOUS_QA_DIRECTIVE_2026-11-06.md`; intake
    MD-47 … MD-55; permanent process `docs/engineering/CONTINUOUS_VERIFICATION_STANDARD_2026-11-06.md`.
- Inventory CW-01 … CW-53 (`docs/audits/remediation_2026-11-06/`; `build_inventory.py` then `--check`); delegated
  decisions DD-01 … DD-16. Owner granted standing permission to merge anything ready (green CI + independent review).

## Production (verified 2026-11-07 ~05:12Z, public endpoints)
- `/api/status` build.commit `405bc35a` (main through #2102; includes #2096 W06 fix, #2094 W20-F005, #2097, #2087
  security fix, #2055 next 16.4.3). `/api/health` 200. Scrape success 03:39:57Z. `box_resources` live (#2062):
  0 Chromium processes; cgroup memory 743–2,531 MiB of 3,072 across the night (peaked right after a deploy+scrape,
  then fell back — reclaimable, not a leak trend).
- Box memory figures are from `/api/status` `box_resources` reads at ~00:09Z, ~01:15Z, ~03:14Z and ~05:12Z.
- Not verifiable without a signed-in session: W06 ghost rows gone from the served board (`/api/data` is 401),
  "Market Disagreement" copy, Monte Carlo framing, Terminal pick values, /phases sentence. #2103 (CLAUDE.md +
  /phases) merged 05:09Z and deploys next.
- `backup_health.stateBackup` still unverifiable / permission_denied: needs the box operator (below).

## Merged this session (since the 2026-11-06 ~21:10Z handoff)
#2099 #2055 #2093 #2095 #2092 #2096 (accidentally auto-closed by a "fix #2096" commit keyword, reopened) #2101
#2102 (CI wall 120→180) #2100 #2103.

## Open
- None of ours. Dependabot: #2056 (jsdom major), #2034 (actions), #2033 (e2e harness) — CW-37, unreviewed.
- #1938 owner-reserved (DD-11).

## Owner / box-operator items
- Box: `bash deploy/backup/install_state_backup.sh` then `scripts/verify_state_backup_restore.py` (#2064 body); check
  `systemctl list-timers '*weekly-projection-capture*' '*pre-auction-snapshot*' '*forecast-calibration-ledger*'`;
  confirm `:8000` is closed.
- Owner decisions: W12-F006 which alert wins when terminal + BDVM detectors fire for one player in one sweep;
  W20-F001 which UI consumes `/api/gameplan`; gated methodology repairs W13-F003 (BDVM saturation), W27-F001 (one IDP
  edge), W27-F005 (TE skew), W10-F003 (retire/reseed old panel), W30-F008 (Hill denominator); DD-11 #1938; DD-14 DFS
  timer. Dependabot alert #149 (low).

## Next dependency-ready units
CW-40: 59 P1 findings still unadjudicated per the 2026-11-06 recount (41 rotted repros, 18 unsafe; not re-measured since), separate from the adjudicated open/partial items; W26-F003 `/draft` no-store needs a live-draft
freshness check first; W25-F003 display half (doc half closed by #2103; unpriced rows still get a `#` ordinal, `it.fails` pinned). CW-49: FAAB anchor
derivation + market layer, ROS/BDVM oracles. CW-53: suite duration (shared-state audit of slowest files →
`pytest-xdist --dist loadfile`). CW-37: dependency batches. CW-48: requirement joins. CW-52: dead-code census.

## Hazards
- NEVER write "fix/fixes/closes/resolves #<open PR>" in a commit message or PR body: GitHub closes that PR on merge
  (it closed #2096 on 2026-11-06).
- Full Validate PR now takes ~105–114 min (wall 180 since #2102). `pytest -x`: one failure hides the rest.
- Python formatting ONLY via `bash scripts/format_python_changes.sh` (pinned Ruff 0.6.9). Every Python text IO passes
  `encoding="utf-8"` (the guard failed #2092 at 67%).
- Local Node 22 vs CI Node 20 (getter-only `navigator`, #2098). jsx vitest files must live under
  `frontend/__tests__/components/` (jsdom project).
- Squash-merged stacked branches conflict add/add on merge-back: keep the branch side for files it changed.
- `config/coercion_baseline.json`: edit by hand, never `--write-baseline`. Receipted blob
  `scripts/idp_opportunity_prospective.py` = `beb7640f`. Never `git stash`. Remove finished worktrees.
