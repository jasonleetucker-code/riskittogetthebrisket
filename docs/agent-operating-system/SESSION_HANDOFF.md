# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-11-06 ~21:10Z.** Agent-OS-Receipt `741230de`. Session `session_01BGLcxPv9489uMYWnm3GbTF`.

## Mode
- Two owner directives of 2026-11-06, one program:
  - Sitewide remediation: `docs/owner/SITEWIDE_REMEDIATION_DIRECTIVE_2026-11-06.md`; intake MD-38 … MD-46.
  - Continuous QA / feature-intent verification: `docs/owner/CONTINUOUS_QA_DIRECTIVE_2026-11-06.md`; intake
    MD-47 … MD-55; permanent process `docs/engineering/CONTINUOUS_VERIFICATION_STANDARD_2026-11-06.md` (#2080).
- Inventory CW-01 … CW-53 (`docs/audits/remediation_2026-11-06/`; `build_inventory.py` then `--check`); delegated
  decisions DD-01 … DD-16 (`DECISIONS.md`). Owner granted standing permission to merge anything ready (green CI +
  independent review). Recount-open P1 master-audit findings are now routed (`MASTER-AUDIT-P1-OPEN` rows).

## Production (verified 2026-11-06 ~20:43Z, public endpoints)
- Deploy 3747 SUCCEEDED: `/api/status` build.commit `3b3b0eee` (main through #2079, incl. #2087 security fix,
  #2084 public-league SWR). `/api/health` 200. Scrape success 20:28:52Z, next 22:23Z.
- Deploy 3755 (`107452ef`: + #2062 #2094 #2067 #2076 and data refresh) was in progress; later merges (#2091 #2097
  #2098) queue another. After it lands: re-read build.commit, `box_resources` (#2062), forecast-ledger timer.
- `/api/public/league/overview` post-deploy: 8.32 s first, then 0.53–1.28 s (5 anonymous GETs). Anonymous
  `POST /api/ros/refresh` → 401 (non-admin signed-in 403 path unverifiable from here).
- `backup_health.stateBackup` still unverifiable / permission_denied: needs the box operator (below).

## Merged today (since the previous handoff)
#2089 #2090 #2094 (W20-F005) #2067 #2076 #2091 #2097 (W27/W10 disclosures) #2098 (flaky test).

## Open, all independently reviewed — merge each on green
- #2092 confidence-gate oracle (encoding fix 89a2d3fb pushed; previous run stopped at 67% on that failure).
- #2093 CW-29 profile features / scoring tags missing → unknown (no served caller).
- #2095 CW-40 adjudication of W06/W10/W13/W27/W30-F002 (doc + strict-xfail tests).
- #2096 W06-F001 must-have ghost rows (verified-rookie gate; delta review APPROVE on beb1bc25).
- #2055 next 16.4.3 patch (review APPROVE conditional on CI incl. production-start journeys).
- Coordinator records: branch `claude/coord-route-open-p1` (routing + states), push with the next batch.

## Owner / box-operator items
- Box: `bash deploy/backup/install_state_backup.sh` then `scripts/verify_state_backup_restore.py` (#2064 body); check
  `systemctl list-timers '*weekly-projection-capture*' '*pre-auction-snapshot*' '*forecast-calibration-ledger*'` and
  w9/w10 archive timestamps; confirm `:8000` is closed.
- Owner: DD-11 recommends promoting #1938 (owner-reserved). DD-14 DFS timer under ODR-DFS-PAUSE. Gated repairs:
  W13-F003 BDVM signal saturation, W27-F001 one IDP edge, W10-F003 retire/reseed old panel, W30-F008 Hill denominator.
- Dependabot alert #149 (low) on main — CW-37.

## Next dependency-ready units
CW-40: the 71 unresolved P1 findings (41 rotted repros, 18 unsafe, 12 unadjudicated). CW-49: FAAB ceiling-curve
oracle. CW-48: requirement joins for the census surfaces. CW-52: dead-code census. W30-F002: converged=false guard
on all-0/1 odds (unreachable today). CW-37: dependency batches (#2056 jsdom major, #2034 actions, #2033 e2e).

## Hazards
- Run Python formatting ONLY via `bash scripts/format_python_changes.sh` (pinned Ruff 0.6.9).
- Encoding guard: every new Python text read/write passes `encoding="utf-8"` (it failed #2092 at 67%).
- Local Node is 22, CI Node 20: a frontend test can pass in CI and fail locally (navigator getter, #2098).
- Disk: worker worktrees are full checkouts; `git worktree remove -f -f` finished ones.
- Deploy/Validate run `pytest -x`: one failure hides the rest. Validate job timeout is 120 min.
- `config/coercion_baseline.json`: edit by hand, never `--write-baseline`; one open PR at a time.
- Receipted blobs never change: `scripts/idp_opportunity_prospective.py` = `beb7640f`. Never `git stash`.
