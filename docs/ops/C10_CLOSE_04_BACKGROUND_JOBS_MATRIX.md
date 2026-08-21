# C10-CLOSE-04 — Background jobs / data production (V1-124)

**Status: CHECKLIST/INSTRUMENT ONLY.** No row in this document has been executed against
production or SSH. This session had no deployed-production access. Building the instrument is
this document's whole job; filling in `Result` / `Evidence` / `Date` on each row is Claude 5's (or
whoever has deployed production access).

**Target level: L3** — "L1 plus the named checklist executed against the deployed SHA, evidence
recorded," per `docs/VERSION_1_COMPLETION_CONTRACT.md` §2.

## Canonical definition (§13.4, `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md`)

> Verify all required scrapers, imports, history writers, snapshotters, materializers,
> queues/timers/workflows, retention, last-known-good behavior, and freshness alerts are live and
> observable.

## How to execute a row

1. Deployed-SHA preamble: record the exact production commit SHA and the wall-clock time of the
   check, same convention as `docs/lane4/L2_L3_VERIFICATION_PROCEDURES.md:82-117`.
2. For every systemd row, run `deploy/diagnostics/c1a_closure_inventory.sh` on the box (read-only,
   modifies nothing) — its Section C now covers all 27 systemd units listed below, using the same
   `unit_state()`/`journal_tail()` probes Sections A/B already used for the 3 units this script
   started with.
3. **Do not use `systemctl is-active` as a liveness check on a timer-activated `Type=oneshot`
   service.** Its correct steady state between runs is `inactive`/`disabled` — documented at
   `docs/master-site-audit/B_SERIES_EXECUTION_LEDGER.md:176-178`. Use `LastTriggerUSec` +
   `Result` + `ExecMainStatus` (all reported by `unit_state()`) plus an artifact stat instead.
4. Rows pre-marked `UNVERIFIABLE-WITHOUT-JOURNAL` below have no artifact or `/api/status` field to
   check — `journalctl -u <unit> -n 120` is the ONLY evidence a run happened. Record what the
   journal shows; do not mark these `PASS` on the strength of `LastTriggerUSec` alone (that proves
   the timer *fired*, not that the job *succeeded*).
5. An unavailable job (timer not installed, installer never wired, journal shows only failures)
   must not read as healthy. Leaving a row blank is not the same as recording it healthy — every
   row gets an explicit result.

## A. GitHub Actions cron workflows (14)

| # | Workflow | Cron (UTC) | Expected artifact | Health mechanism | Result | Evidence | Date |
|---|---|---|---|---|---|---|---|
| A1 | `scheduled-refresh.yml` | `42 */2 * * *` | `CSVs/site_raw/*.csv`, `exports/latest/**`, `data/scrape_state/*_last_success` | Strongest in repo: per-source stamps → `watchdog_freshness.py`; `watchdog_contract_coverage.py`; issue open+close | | | |
| A2 | `health-check.yml` | `17 */6 * * *` | none (assertion only) | issue open+close; `MIN_SOURCES=8`, `MIN_PER_SOURCE=5`; backup-freshness assert | | | |
| A3 | `retention-health.yml` | `40 6 * * *` | none (probe) | **No issue open/close** — red X only | | | |
| A4 | `prod-e2e-smoke.yml` | `17 */4 * * *` | none | **No issue open/close** | | | |
| A5 | `public-league-warmup.yml` | `*/20 * * * *` | warms `data/public_league/` snapshot | **No issue open/close** — highest-frequency job on the platform with zero alerting | | | |
| A6 | `e2e.yml` | `23 6 * * *` | none | issue open+close | | | |
| A7 | `smoke-test.yml` | `15 6 * * *` | none | **No issue open/close** | | | |
| A8 | `intel-refresh.yml` | `10 9 * * *` | `data/intel/**` | issue open+close | | | |
| A9 | `audit-identity-matches.yml` | `17 8 * * *` (+push) | identity report | issue open+close | | | |
| A10 | `audit-dropped-sources.yml` | `23 7 * * 1` | report | **No issue open/close** | | | |
| A11 | `refit-hill-curves.yml` | `17 6 * * 2` | `config/model_registry/**` challenger row | **Creates an issue 3x, closes 0x — mints a duplicate every week. Check open-issue count first** | | | |
| A12 | `audit-rank-form-drift.yml` | `41 7 * * 2` | report | 3 create / 1 close | | | |
| A13 | `consensus-edge-revalidate.yml` | `40 5 * * 3` | validation JSON, discarded | **No issue open/close** | | | |
| A14 | `weekly-narratives.yml` | `0 14 * * 2` + `0 13 * * 3` | narrative artifacts | **No issue open/close** | | | |

**Also verify**: none of these 14 has silently hit GitHub's 60-day repo-inactivity auto-disable —
nothing in this repo detects that condition, so it must be checked manually
(`gh workflow list` state, or the Actions UI).

## B. systemd units on the VPS (27)

### B1. Sharp-intel lane — 8 recurring crawls, **the entire lane has zero health signal**

`/api/sharp/*` reads `data/intel/ledger.sqlite3` on every request and reports `cohort_building` on
an empty ledger — indistinguishable from "the crawls stopped four weeks ago" without checking these
directly.

| # | Unit | OnCalendar (UTC) | Expected output | Health mechanism | Result | Evidence | Date |
|---|---|---|---|---|---|---|---|
| B1 | `dynasty-sharp-discovery` | `04:20` +900s | Sleeper manager graph → `data/intel/ledger.sqlite3` | **NONE — UNVERIFIABLE-WITHOUT-JOURNAL** | | | |
| B2 | `dynasty-sharp-records` | `04:50` +900s | season records rows | **NONE — UNVERIFIABLE-WITHOUT-JOURNAL** | | | |
| B3 | `dynasty-sharp-cohort-snapshot` | `05:10` | `data/sharp/cohort/snapshot_<date>.json` | **NONE — UNVERIFIABLE-WITHOUT-JOURNAL** | | | |
| B4 | `dynasty-ffpc-sharp` | `05:20` +900s | FFPC managers → platform ledger | **NONE — UNVERIFIABLE-WITHOUT-JOURNAL** | | | |
| B6 | `dynasty-sharp-rosters` | `05:50` +900s | current holdings for `/market/sharp-roster-percentage` | **NONE — UNVERIFIABLE-WITHOUT-JOURNAL** | | | |
| B9 | `dynasty-sharp-activity` | `06:30` +900s | Sleeper trades → ledger | **NONE — UNVERIFIABLE-WITHOUT-JOURNAL** | | | |
| B20 | `dynasty-sharp-transactions` | `02,08,14,20:20` +600s | trade movements → ledger | **NONE — UNVERIFIABLE-WITHOUT-JOURNAL** | | | |
| B26 | `chase-upside-ffpc-sharp` | `05:20` +900s | same as B4, different installer (`deploy/install-ffpc-sharp-service.sh`, called from `bootstrap-sharp-records.sh`) | **NONE — UNVERIFIABLE-WITHOUT-JOURNAL** | | | |
| B27 | `chase-upside-curated-sharps` | `06:20` +20m | `data/intel/sharp_curated` | **NONE — UNVERIFIABLE-WITHOUT-JOURNAL.** Was completely unwired until this batch (see "Fixed this batch" below) | | | |

### B2. Other `dynasty-*` template units

| # | Unit | OnCalendar (UTC) | Expected output | Health mechanism | Result | Evidence | Date |
|---|---|---|---|---|---|---|---|
| B5 | `dynasty-playerctx-refresh` | `Tue 05:40` +600s | `data/playerctx/snapshot.json` + history | `/api/status.playerctxHistoryCoverage` + retention `C1-RET-08` | | | |
| B7 | `dynasty-bdvm-refresh` | `Tue 06:10` +600s | `data/bdvm/projections/<season>/` | **NONE machine-readable** — age only in `meta.auxiliaryInputs`, behind the `bdvm_engine` flag (default off) | | | |
| B8 | `dynasty-crowd-faab` | 3-hourly +300s | `data/faab/crowd_history_<leagueKey>.json` | `retention_health` `C1-RET-01` | | | |
| B10 | `dynasty-playerctx-history` | `Tue 06:45` | pushes dated snapshots to `main` | `/api/status.playerctxHistoryCoverage.pendingPush` | | | |
| B11 | `dynasty-board-snapshot` | `07:10` +300s | `data/board_history.sqlite` | `retention_health` `C1-RET-02` | | | |
| B12 | `dynasty-reception-depth` | `Wed 07:20` +900s | `data/nfl_data/.../reception_depth_<season>.jsonl` | **NONE — UNVERIFIABLE-WITHOUT-JOURNAL** | | | |
| B13 | `dynasty-consensus-edge-snapshot` | `07:30` +300s | `data/consensus_edge.sqlite` | **NONE — UNVERIFIABLE-WITHOUT-JOURNAL** | | | |
| B14 | `dynasty-faab-history` | `07:40` +600s | `data/faab/bid_history_<leagueKey>.json` | **NONE automated** — worked L3 procedure exists at `docs/lane4/L2_L3_VERIFICATION_PROCEDURES.md:118-161`, use it | | | |
| B15 | `dynasty-pbp-weekly` | `Wed 08:20` +900s | `data/nfl_data/actuals/pbp_weekly_<season>.jsonl` | **NONE — UNVERIFIABLE-WITHOUT-JOURNAL** | | | |
| B16 | `dynasty-custom-alerts` | 2-hourly +180s | alert emails | **NONE.** `curl --fail` reds systemd on non-2xx but nothing records the last successful sweep | | | |
| B17 | `dynasty-signal-alerts` | `15:00` +300s | alert digest emails | **NONE — UNVERIFIABLE-WITHOUT-JOURNAL** | | | |
| B18 | `dynasty-dlf-fetch` | 2-hourly | 4 CSVs + 5 stamps | `*_last_success` stamps → `watchdog_freshness` + dedicated DLF assertion in A1 | | | |
| B19 | `dynasty-idpshow-fetch` | 2-hourly | 2 CSVs + `idpShow_last_success`, `idpShowCombined_last_success` | stamps → `watchdog_freshness`; `idpShow` soft-flagged, 72h escalation | | | |

### B3. Fixed non-template units

| # | Unit | Schedule | Expected output | Health mechanism | Result | Evidence | Date |
|---|---|---|---|---|---|---|---|
| B21 | `riskit-backup` | daily `02:00`, `Persistent=true` | `/var/backups/riskit/daily/*.sqlite.gz` | `/api/status.backup_health.newestBackupAgeHours`, asserted by A2 | | | |
| B22 | `riskit-backup-restore-test` | `Mon 03:30` | none (integrity assert) | **NONE** — log line only | | | |
| B23 | `riskit-state-backup` | daily `02:30` | `/var/backups/riskit-state` | **NONE — invisible to `backup_health`, which globs a different path (`/var/backups/riskit/daily`)** | | | |
| B24 | `dynasty-healthcheck` | every 1 min | restarts `dynasty` after 3 failed probes | **NONE** — journal only | | | |
| B25 | `riskit-uptime` | every 5 min | `/var/log/riskit-uptime.log` | **NONE in-repo.** `SuccessExitStatus=0 1` means a DOWN site does not mark the unit failed | | | |

**B21/B23/B24/B25 are installed by `deploy/apply_hardening.sh`, which has zero automated callers**
anywhere in `.github/workflows/`, `deploy/deploy.sh`, or `bootstrap-production.sh` (verified this
session, grep found nothing). **Verify these units exist on the box at all before trusting anything
else about them** — if `apply_hardening.sh` was ever skipped or the host rebuilt, the 1-minute
liveness watchdog, 5-minute uptime probe, and 02:30 state backup may not exist, and every deploy
still reports success.

### B4. Always-on application services

| # | Unit | Health mechanism | Result | Evidence | Date |
|---|---|---|---|---|---|
| — | `dynasty.service` | Normal `is-active`/`is-failed` liveness check applies (NOT a oneshot timer target) | | | |
| — | `dynasty-frontend.service` | Same | | | |

## C. In-process loops inside `server.py`

| # | Loop | Interval | Health mechanism | Result | Evidence | Date |
|---|---|---|---|---|---|---|
| C1 | `schedule_loop()` → scheduled scrape | 2h | `/api/status` `scrape_status`, `scrape_success_rate_24h` | | | |
| C2 | `initial_scrape()` | once, +3s after boot | same as C1 | | | |
| C3 | `uptime_watchdog_loop()` | configurable | `/api/status.uptime`, `/api/health.uptime_watchdog.enabled` | | | |
| C4 | public-league warmup thread | boot + stale-while-revalidate | `_public_league_cache["last_failure_at"]` — **tracked in-memory only, never reaches `/api/status`** despite being the highest-frequency job on the platform (every 20 min via A5) | | | |
| C5 | sleeper-overlay-warm thread | post-scrape | **NONE** | | | |
| C6 | intel-refresh thread | on `POST /api/intel/refresh` | `/api/intel/refresh/status` | | | |
| C7 | overlay-refresh-`<leagueId>` thread | on demand | **NONE** | | | |
| C8 | source-history backfill | once at boot | **NONE** — `rank_history.jsonl` stall is silent by the code's own admission (`server.py:5007-5012`) | | | |

## D. Fixed this batch (not just documented)

- **`chase-upside-curated-sharps` (B27) was completely unwired** — `deploy/install-curated-sharps-service.sh`
  had zero callers anywhere in the repo, the exact "template committed, reviewed, merged, and never
  once rendered onto a box" failure class `tests/deploy/test_all_timers_are_wired.py`'s own docstring
  describes, in a directory that guard structurally could not see. Wired into
  `deploy/bootstrap-sharp-records.sh` (a new `run_curated_sharps_now()`, mirroring the existing
  `run_ffpc_now()` shape exactly, called from the same place). A new test,
  `tests/deploy/test_all_timers_are_wired.py::test_every_dedicated_installer_directory_has_a_reachable_installer`,
  mutation-proved RED (installer missing) then GREEN, closes the blind spot for both
  `curated-sharps-systemd/` and `ffpc-systemd/` going forward.
- **`deploy/diagnostics/c1a_closure_inventory.sh` extended from 3 units to all 27** — new Section C
  reuses the script's own existing `unit_state()`/`journal_tail()` probes rather than inventing a
  second inspection mechanism, so running it now produces this entire matrix's B section in one
  read-only pass.

## E. Not fixed this batch — real, out-of-scope work

- Wiring an actual health signal (retention stream, `/api/status` field, or CI assertion) for any
  of the 14 `UNVERIFIABLE-WITHOUT-JOURNAL` rows above. That is instrumentation work with production
  design decisions (what budget, what alerting channel), not a census.
- Fixing `riskit-uptime.service`'s `SuccessExitStatus=0 1` masking real outages, or pointing
  `backup_health`'s glob at `/var/backups/riskit-state` too. Both are real, named defects; both need
  an owner decision on the right fix, not a silent edit here.
- Verifying `apply_hardening.sh` was ever actually run on the current production box. This document
  can only say the automated-caller path doesn't exist — whether a human ran it by hand is a
  production fact only Claude 5 can check.

## Result summary (fill in after execution)

| Metric | Count |
|---|---|
| Rows executed | 0 of 49 |
| Healthy (real evidence, not just LastTriggerUSec) | — |
| UNVERIFIABLE-WITHOUT-JOURNAL, journal checked | — |
| Genuinely broken / not installed | — |
| Not yet run | all |
