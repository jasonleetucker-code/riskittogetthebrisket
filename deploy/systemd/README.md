# systemd units — Risk It platform

## Install (on the VPS)

```bash
# Copy units into /etc/systemd/system/
sudo cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload

# Enable + start the timers (the .service units are triggered by them).
sudo systemctl enable --now riskit-backup.timer
sudo systemctl enable --now riskit-backup-restore-test.timer
sudo systemctl enable --now dynasty-healthcheck.timer

# Optional: logrotate (uses Linux's own logrotate cron, NOT a timer here).
sudo cp deploy/logrotate.conf /etc/logrotate.d/riskit
sudo chmod 644 /etc/logrotate.d/riskit

# Verify next-fire times:
systemctl list-timers riskit-*
```

## Units

| Unit | Purpose | Cadence |
|---|---|---|
| `riskit-backup.service`+ `.timer` | Nightly online SQLite backup of user_kv + session_store | Daily 02:00 UTC |
| `riskit-backup-restore-test.service` + `.timer` | Integrity check of the latest backup | Weekly Mon 03:30 UTC |
| `dynasty-healthcheck.service` + `.timer` + `.sh` | Backend LIVENESS watchdog: probes `/api/health`, restarts `dynasty` after 3 consecutive no-response probes; app-degraded 503s (stale data / failed scrape) are log-only and never restart | Every 1 min |

Related units living elsewhere in deploy/:

- `deploy/backup/riskit-state-backup.*` — nightly full-state backup
  (sqlite + public_league/ + intel/ + scraper session secrets), 02:30 UTC.
- `deploy/monitoring/riskit-uptime.*` — public-URL uptime probe, 5 min.

`deploy/apply_hardening.sh` installs/refreshes all of the above
idempotently (see docs/PROD-HARDENING.md).

**Root-run scripts execute from `/usr/local/lib/riskit/`, not the
checkout.**  `dynasty-healthcheck.sh` and
`deploy/backup/riskit-state-backup.sh` run as root, so the apply
script installs root:root 0755 copies outside the deploy-user-writable
repo and the units point there — a root unit executing a
checkout-writable file would let a compromised deploy account escalate
to root.  Re-run the apply script to roll out script changes; the
repo copies are the source of truth but are inert at runtime.

Timers rendered + enabled by `deploy/install-systemd-service.sh`
(placeholder substitution — do **not** copy the `*.template` files into
/etc/systemd/system verbatim):

| Unit | Purpose | Cadence | Installed when |
|---|---|---|---|
| `dynasty.service` / `dynasty-frontend.service` | Backend + Next.js | — | always |
| `dynasty-signal-alerts.*` | Signal-alert digest sweep | Daily 15:00 | `SIGNAL_ALERT_CRON_TOKEN` in `.env` |
| `dynasty-custom-alerts.*` | Custom-rule alert sweep | Every 2h | `SIGNAL_ALERT_CRON_TOKEN` in `.env` |
| `dynasty-dlf-fetch.*` | DLF CSV fetch + push (CI is Cloudflare-blocked) | Every 2h | DLF creds in `.env` |
| `dynasty-idpshow-fetch.*` | IDP Show rankings fetch + push | Every 2h | always |
| `dynasty-playerctx-refresh.*` | Player context (contracts / snap share / depth chart) → `data/playerctx/snapshot.json`, served by `/api/playerctx/player` | Weekly Tue 05:40 UTC | always (public data, no creds) |
| `dynasty-depth-charts-refresh.*` | Live Waiver Opportunity layer: all-32-team ESPN depth-chart diff → `DEPTH_CHART_PROMOTION`/`DEMOTION` events in `data/bdvm/events/<season>.json`, read by `src/trade/faab_opportunity.py`. Sets `RISKIT_FEATURE_DEPTH_CHART_VALIDATION=1` for its own process only (global default stays off — the gate is SCRIPT_ONLY, not LIVE) | Daily 04:20 UTC | always (public ESPN data, no creds) |
| `dynasty-injury-feed-refresh.*` | Live Waiver Opportunity layer: league-wide ESPN injury-status diff → `INJURY`/`ACTIVATED_RETURN` events in the same events ledger, damping a player's short-term surplus when he is unlikely to play soon. Sets `RISKIT_FEATURE_ESPN_INJURY_FEED=1` for its own process only | Every 4h | always (public ESPN data, no creds) |
| `dynasty-trending-history-refresh.*` | Live Waiver Opportunity layer: appends a Sleeper trending adds+drops snapshot to `data/waiver/trending_history.json`, making 6h/12h/24h/48h velocity computable (`src/adapters/sleeper_trending_history.py`) | Hourly | always (public Sleeper data, no creds) |
| `dynasty-bdvm-refresh.*` | BDVM request-path input warm (`scripts/refresh_bdvm_inputs.py` — nflverse id map / weekly stats / snap counts / schedules, the caches `/api/bdvm/*` may only READ) **then** BDVM projection snapshots (reconstructed baseline + Mike Clay ESPN guide + IDP Show real projections) → `data/bdvm/projections/<season>/`, served by `/api/bdvm/*` (flag `bdvm_engine`) | Weekly Tue 06:10 UTC | always (baseline + Clay need no creds; Clay self-skips without poppler-utils; IDP Show stage self-skips without the session jar) |

`dynasty-playerctx-refresh` and `dynasty-bdvm-refresh` must run **on
prod**, not in CI: their endpoints read local files and `data/` is
gitignored, so a CI-built snapshot would never reach the VPS.  See
`docs/playerctx.md`; for BDVM, `scripts/refresh_bdvm_projections.py`
documents the stage/exit-code contract, and the IDP Show session jar
is shared with the rankings timer at
`/var/lib/idpshow-fetch/idpshow_session.json`.

The BDVM unit's FIRST `ExecStart=` is the input warm, `-`-prefixed so a
warm failure cannot abort the projection refresh; the unit's own
success/failure therefore still reports the projections outcome, and
the warm's result is in its journal lines and exit code.  It runs on
prod for the same reason the projections do — the request path reads a
local cache under gitignored `data/`.  Without it BDVM does not serve
wrong numbers: it degrades to the states it has always used when a
fetch failed and stamps them in `meta.auxiliaryInputs`.

## Manual runs

```bash
# Force a backup now.
sudo systemctl start riskit-backup.service

# Verify latest backup manually.
sudo -u dynasty /home/dynasty/trade-calculator/deploy/backup_user_kv.sh --restore-test
```

## Observability

Backups write to `/var/log/riskit-backup.log`.  Successful run ends
with `nightly backup complete: <ISO timestamp>`.  Failed restore-
test exits non-zero and logs `ERROR`.

Logrotate config (`deploy/logrotate.conf`) keeps 14 days of
backup logs + application logs (`/var/log/dynasty.log`,
`/var/log/dynasty-frontend.log`).
