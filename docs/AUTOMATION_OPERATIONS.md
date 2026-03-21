# Automation and Operations Guide

This document is the current production automation truth for this repo.

## What Is Automatic Today

### 1) Data refresh / scraping
- Runtime authority: `server.py`
- Mechanism: in-process scheduler loop
- Default cadence: every 4 hours (`SCRAPE_INTERVAL_HOURS=4`)
- Jitter: up to 10 minutes (`SCRAPE_INTERVAL_JITTER_MINUTES=10`)
- Failure backoff: +60 minutes per consecutive failed run, capped at 12 hours

The scheduler runs a full scrape and then promotion gate validation before publishing.

### 2) Promotion safety + fallback
- Runtime promotion gate: `src/api/promotion_gate.py` (called by `server.py`)
- If gate fails, new payload is rejected.
- Live runtime keeps last-known-good payload:
  - `data/runtime_last_good.json`
  - `data/runtime_last_good_meta.json`

### 3) Deploy automation
- Runtime deploy workflow: `.github/workflows/deploy.yml`
- Trigger: `push` to `main` and manual dispatch
- Model: event-driven deploy (no GitHub polling loop)
- Post-deploy checks:
  - `deploy/verify-deploy.sh`
  - `scripts/runtime_probe.py --mode smoke`

### 4) Recurring runtime checks
- Hourly lightweight check: `.github/workflows/runtime-health.yml`
- 12-hour smoke check: `.github/workflows/runtime-smoke.yml`
- Weekly deeper audit: `.github/workflows/weekly-deep-audit.yml`
  - includes semantic ratchet gate: `scripts/semantic_ratchet_gate.py`
  - includes critical value/trade tests: `scripts/run_critical_api_tests.py`

## Schedule Summary

| Job | Cadence | Purpose | Load profile |
|---|---|---|---|
| Runtime scrape scheduler | Every 4h (+ jitter/backoff) | Refresh source data and publish if valid | Heavy |
| Uptime watchdog loop | Every 300s (default) | Detect external health failures | Light |
| Runtime health monitor workflow | Hourly | Validate health + freshness + operator report | Light |
| Runtime smoke monitor workflow | Every 12h | Validate public/private routing and auth boundary | Medium |
| Weekly deep audit workflow | Weekly (Monday 05:15 UTC) | Run deeper regression-focused API unit tests | Medium |
| Deploy validate job (main pushes) | Event-driven | Contract validation + semantic ratchet + critical value/trade tests + parity gate | Medium/Heavy |

## Operator Checks (Non-Technical)

If you want to know whether the system is healthy:

1. Open GitHub Actions and check latest runs for:
   - `Deploy Production`
   - `Runtime Health Monitor`
   - `Runtime Smoke Monitor`
2. Open `https://riskittogetthebrisket.org/api/health`
   - Look for `"status":"ok"`
3. Open `https://riskittogetthebrisket.org/api/status`
   - Check `automation.scrape_scheduler`
   - Check `automation.deploy_status`
   - Check `frontend_runtime.raw_fallback_health`
4. Open `https://riskittogetthebrisket.org/api/validation/operator-report`
   - `status` should not be `critical`

## What Happens On Failure

### Scrape or formula validation failure
- New payload is not promoted.
- Existing live payload remains active.
- Failure report written to `data/validation/promotion_gate_*.json`.

### Deploy failure
- Deploy pipeline fails.
- Remote deploy script supports rollback path (`deploy/rollback.sh`).
- Post-deploy probe failure fails the workflow.

### Runtime health / smoke failure
- Scheduled workflow fails and stores probe JSON artifact.
- Probe issue list shows exact failed endpoint/route and reason.
- Probe also warns when frontend raw fallback skips corrupt local payload files.

### Frontend raw fallback warning
- `GET /api/status` exposes `frontend_runtime.raw_fallback_health`
- `GET /api/health` exposes `frontend_raw_fallback` and warning code `frontend_raw_fallback_skipped_files`
- Dry-run cleanup:
  - `python scripts/quarantine_invalid_raw_fallback.py`
- Quarantine invalid files into `data/quarantine/raw_fallback/`:
  - `python scripts/quarantine_invalid_raw_fallback.py --apply`

## Key Configuration Variables

### Scrape scheduler
- `SCRAPE_SCHEDULER_ENABLED`
- `SCRAPE_INTERVAL_HOURS`
- `SCRAPE_INTERVAL_JITTER_MINUTES`
- `SCRAPE_FAILURE_BACKOFF_MINUTES`
- `SCRAPE_MAX_BACKOFF_HOURS`

### Health policy
- `MAX_HEALTHY_SCRAPE_AGE_HOURS`
- `UPTIME_CHECK_ENABLED`
- `UPTIME_CHECK_URL`
- `UPTIME_CHECK_INTERVAL_SEC`
- `UPTIME_CHECK_TIMEOUT_SEC`
- `UPTIME_ALERT_FAIL_THRESHOLD`

### Deploy/runtime checks
- `PROD_PUBLIC_URL` (GitHub variable)
- `PROD_MAX_HEALTHY_SCRAPE_AGE_HOURS` (GitHub variable used by probe workflows)

## Source of Truth Files
- Runtime scheduler/health/status: `server.py`
- Promotion gate: `src/api/promotion_gate.py`
- Deploy execution: `deploy/deploy.sh`
- Deploy verification: `deploy/verify-deploy.sh`
- Runtime probe utility: `scripts/runtime_probe.py`
- Automation workflows: `.github/workflows/*.yml`
