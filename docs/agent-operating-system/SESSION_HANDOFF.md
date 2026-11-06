# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-11-06 ~19:05Z.** Agent-OS-Receipt `741230de` (Agent OS changed with #2080). Session
`session_01BGLcxPv9489uMYWnm3GbTF`.

## Mode
- Two owner directives of 2026-11-06, one program:
  - Sitewide remediation: `docs/owner/SITEWIDE_REMEDIATION_DIRECTIVE_2026-11-06.md`; intake MD-38 … MD-46.
  - Continuous QA / feature-intent verification: `docs/owner/CONTINUOUS_QA_DIRECTIVE_2026-11-06.md`; intake
    MD-47 … MD-55; permanent process `docs/engineering/CONTINUOUS_VERIFICATION_STANDARD_2026-11-06.md` (#2080).
- Inventory CW-01 … CW-53 (`docs/audits/remediation_2026-11-06/`; `build_inventory.py` then `--check`); delegated
  decisions DD-01 … DD-16 (`DECISIONS.md`). Owner granted standing permission to merge anything ready (green CI +
  independent review).

## Production (verified 2026-11-06 ~18:55Z, public endpoints)
- Deploy run 3734 SUCCEEDED 18:48Z: `/api/status` build.commit `91b0965c` (release train #2072). First deploy since
  2026-11-04. `/api/health` 200 (was 503). Scrape success 18:48:38Z (263 s), next 20:44Z. Flag
  `confidence_cured_rejection_guard` LIVE.
- Deploys 3747 / 3748 (main through #2079 / #2084) were in flight; later merges queue more (concurrency group never
  cancels an in-progress deploy). Re-read build.commit and `box_resources` (#2062 adds it) after they land.
- `backup_health.stateBackup` still unverifiable / permission_denied: needs the box operator (below).

## Merged today
#2065 #2066 #2073 #2078 #2080 #2081 #2083 · #2072 (train, incl. #2061) · #2070 #2069 #2086 #2064 #2075 #2077 #2085
#2068 #2063 #2087 #2082 #2074 #2079 #2084 #2071.

## Open, all independently reviewed — merge each on green
- #2062 scraper reaper + box diagnostics: CI re-run once (load-sensitive loop-timing test; DD-16).
- #2067 trade honesty / "Market Disagreement": nav-invariant test updated (ce2e969d, DD-15); journeys re-run once.
- #2076 forecast calibration ledger timer: installer conflict with #2063 resolved (f9049d11).
- #2089 CW-49 math oracles (package model, blend median).
- In flight: CW-10 follow-up worker (FAAB config refusal on `/api/waiver/advisor` + `/api/waiver/streaming`).

## Owner / box-operator items
- Box: `bash deploy/backup/install_state_backup.sh` then `scripts/verify_state_backup_restore.py` (#2064 body); check
  `systemctl list-timers '*weekly-projection-capture*' '*pre-auction-snapshot*'` and w9/w10 archive timestamps;
  confirm `:8000` is closed.
- Owner: DD-11 recommends promoting #1938 (owner-reserved). DD-14: the DFS auto-refresh timer keeps running under
  ODR-DFS-PAUSE ("deployed DFS preserved") — say so if the pause should cover it. Sharp audit routes are
  any-signed-in, not admin-only (consistent with siblings) — policy question only.

## Next dependency-ready units
QA: CW-48 requirement joins for the census's surfaces; CW-49 batch 2 (confidence gate axes, FAAB curve, lineup vs host
truth); CW-50 critical journeys + census weak-only items; CW-52 dead-code census. Remediation: Week 9 evaluation once
final (#2077 merged); CW-40 P1 batch (71 unresolved); CW-29 follow-up (`infer_scoring_tags` /
`compute_profile_features` missing → 0); CW-26 post-deploy `/overview` curl baseline; snapshot-layer staleness bound
(CW-11 note); residuals routed by #2082: W12-F002 → CW-36, W17-F001 → CW-17, W17-F002 → CW-33.

## Hazards
- Run Python formatting ONLY via `bash scripts/format_python_changes.sh` (pinned Ruff 0.6.9); a newer local `ruff`
  formats differently and fails CI.
- Disk: worker worktrees are full checkouts; `git worktree remove -f -f` finished ones.
- Usage: the 5-hour model limit was hit once (≈14:45–16:40Z) with four opus agents running; prefer sonnet workers.
- Deploy/Validate run `pytest -x`: one data-coupled failure hides the next. Validate job timeout is 120 min.
- `config/coercion_baseline.json`: edit by hand, never `--write-baseline`; one open PR at a time.
- Receipted blobs never change: `scripts/idp_opportunity_prospective.py` = `beb7640f`.
- Encoding guard: new Python text IO passes `encoding="utf-8"`. Never `git stash`.
