# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-11-06 ~14:00Z.** Agent-OS-Receipt `47a8b19f`. Session `session_01BGLcxPv9489uMYWnm3GbTF`.

## Mode
- Owner directive 2026-11-06 (sitewide remediation): record `docs/owner/SITEWIDE_REMEDIATION_DIRECTIVE_2026-11-06.md`;
  intake MD-38 … MD-46; execution-plan top section; register section "Sitewide remediation directive (2026-11-06)";
  agent decisions `docs/audits/remediation_2026-11-06/DECISIONS.md` (DD-01 … DD-13).
- Inventory `docs/audits/remediation_2026-11-06/` (CW-01 … CW-47): `python docs/audits/remediation_2026-11-06/build_inventory.py`
  then `--check`. Production performance baseline: `perf_baseline_2026-11-06.json` (same folder).

## Production (live, 2026-11-06)
- Build `80c52dbf` (2026-11-04). **No deploy since 2026-11-05**: the hard gate fails on Sonny Styles (fixed by #2061) and,
  hidden behind it by `pytest -x`, Patrick Mahomes (CW-47 confidence gap). Both are in **release train #2072**.
- `/api/health` 503; scraper 0/9, stuck at `browser/launch`; a deploy restarts `dynasty.service`.

## Merged this session
#2065 (Week 10 freeze receipts, pushed 12:46:58Z — before the 2026-11-12 kickoff), #2066 (directive record + inventory),
#2073 (inventory states, DD-11 … DD-13).

## Merge order (every PR below is independently reviewed APPROVE)
1. **#2072** release train (CW-47 seated confidence guard + #2061). Validate PR running the full hard gate (first time
   in two days that `-x` does not stop early — watch for a THIRD hidden failure). On green: merge, close #2061 as
   included, watch Deploy Production, confirm `/api/status` `build.commit` advances, read `box_resources` /
   `backup_health` / scraper state.
2. Then bring each up to date with `main` and merge on green: #2062 (scraper reaper + box diagnostics), #2063 (2027
   pre-auction snapshot; nit: import the 6 h budget from its owner), #2064 (backup group-list, analyst ledger, restore
   verifier), #2067 (hide synthetic MC win rate; "Market Disagreement"), #2068 (archetype missing ≠ 0), #2069 (scoring
   parity census), #2070 (rehab reviews), #2071 (FAAB integrity + fail-closed config; follow-up: add the config refusal
   to `/api/waiver/advisor` and `/api/waiver/streaming`), #2074 (W10-F001 bid ≤ remaining budget; C01 closed), #2075
   (login next sanitizer + missing budget ≠ $0), #2076 (forecast calibration ledger timer + size-controlled gates),
   #2077 (prospective IDP evaluation runner).
3. In flight (workers): public-league stale-while-revalidate; `/draft` contract-view audit; Team Strength auth state.

## Owner / box-operator items
- Box: `bash deploy/backup/install_state_backup.sh` + `scripts/verify_state_backup_restore.py` (#2064 body); check
  `systemctl list-timers '*weekly-projection-capture*'` and w9/w10 archive timestamps; confirm `:8000` is closed.
- Owner: DD-11 recommends promoting #1938 (IDP scorer fixes; host-truth census 91.8 % → 96.4 %) — still owner-reserved.
- Canonical-owner question: board-level class retirement waits for EVERY served league to prove completion (#1414).

## Next dependency-ready units
Week 9 evaluation once final (needs #2077); CW-08 follow-ups (#802 return TDs untested); CW-12 source lineage
(MD-21) as a measured shadow only; CW-29 follow-up (`infer_scoring_tags` / `compute_profile_features` missing→0);
CW-40 adjudicate the 78 unresolved P0/P1 master-audit findings; CW-37 dependency batches after the train.

## Hazards
- Disk: each worker worktree is a full checkout; `git worktree remove -f -f` finished ones (disk filled once).
- Deploy/Validate run `pytest -x`: one data-coupled failure hides the next.
- `config/coercion_baseline.json`: edit entries by hand, never `--write-baseline`; only one open PR may touch it.
- Receipted blobs (freeze receipts) must never change: `scripts/idp_opportunity_prospective.py` = `beb7640f`.
- `pip install http-ece` needs `pip install --ignore-installed --upgrade setuptools` first in this container.
- Encoding guard: new Python text IO passes `encoding="utf-8"`. Never `git stash`. GitHub API quota is shared.
