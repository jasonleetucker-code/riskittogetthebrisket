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
/etc/systemd/system verbatim).

**A template edit reaches the box on the next deploy.** `deploy.sh` runs
the installer on every deploy, and every timer — the
`install_simple_timer` ones and the dedicated blocks with gates or
post-install steps alike — goes through one renderer,
`reconcile_timer_units`: render both templates, `cmp` them against the
installed files, and rewrite + `daemon-reload` only on a difference
(logged as `<unit> differs from its template; updating.`; an unchanged
unit logs `already installed and current.`). Until 2026-10-01 the
dedicated blocks only asked whether the timer existed, so production was
still running a `dynasty-bdvm-refresh.service` without its 2026-08-20
stage-0 input warm and a `dynasty-consensus-edge-snapshot.service` without
`User=`. A block's gate (cron token, DLF credentials, IDP Show session
jar, FFPC enablement) still decides whether the installer touches that
unit at all — a closed gate leaves an installed unit exactly as it is.
`FORCE_SERVICE_INSTALL=true` still rewrites unconditionally.

The Consensus Edge block also hands `data/consensus_edge.sqlite` and its
`-wal`/`-shm` sidecars to `APP_USER` (`sudo -n chown`) when they exist and
are owned by anyone else — they are root-owned on any box that ran the
pre-`User=` unit. Idempotent, never deletes, never follows a symlink, and
loud-but-non-fatal if the chown is refused.

| Unit | Purpose | Cadence | Installed when |
|---|---|---|---|
| `dynasty.service` / `dynasty-frontend.service` | Backend + Next.js | — | always |
| `dynasty-signal-alerts.*` | Signal-alert digest sweep | Daily 15:00 | `SIGNAL_ALERT_CRON_TOKEN` in `.env` |
| `dynasty-custom-alerts.*` | Custom-rule alert sweep | Every 2h | `SIGNAL_ALERT_CRON_TOKEN` in `.env` |
| `dynasty-dlf-fetch.*` | DLF CSV fetch + push (CI is Cloudflare-blocked) | Every 2h | DLF creds in `.env` |
| `dynasty-idpshow-fetch.*` | IDP Show rankings fetch + push | Every 2h | operator-minted `idpshow_session.json` present in the checkout |
| `dynasty-signals-auth-renew.*` | Renews the owner-connected Signals Cognito session stored outside the checkout at `/var/lib/signals-auth` (`docs/sources/SIGNALS_ACCOUNT_CONNECTION.md`); exit 0 no-op until a session is provisioned | Every 6h at :47 | always (no-op without a session) |
| `dynasty-playerctx-refresh.*` | Player context (contracts / snap share / depth chart) → `data/playerctx/snapshot.json`, served by `/api/playerctx/player` | Weekly Tue 05:40 UTC | always (public data, no creds) |
| `dynasty-depth-charts-refresh.*` | Live Waiver Opportunity layer: all-32-team ESPN depth-chart diff → `DEPTH_CHART_PROMOTION`/`DEMOTION` events in `data/bdvm/events/<season>.json`, read by `src/trade/faab_opportunity.py`. Sets `RISKIT_FEATURE_DEPTH_CHART_VALIDATION=1` for its own process only (global default stays off — the gate is SCRIPT_ONLY, not LIVE) | Daily 04:20 UTC | always (public ESPN data, no creds) |
| `dynasty-injury-feed-refresh.*` | Live Waiver Opportunity layer: league-wide ESPN injury-status diff → `INJURY`/`ACTIVATED_RETURN` events in the same events ledger, damping a player's short-term surplus when he is unlikely to play soon. Sets `RISKIT_FEATURE_ESPN_INJURY_FEED=1` for its own process only | Every 4h | always (public ESPN data, no creds) |
| `dynasty-trending-history-refresh.*` | Live Waiver Opportunity layer: appends a Sleeper trending adds+drops snapshot to `data/waiver/trending_history.json`, making 6h/12h/24h/48h velocity computable (`src/adapters/sleeper_trending_history.py`) | Hourly | always (public Sleeper data, no creds) |
| `dynasty-signals-fetch.*` | Signals Fantasy public dynasty + IDP dynasty boards → box-local private store `data/sources/signals/` (never committed), served only by the authenticated `/api/second-opinion/signals` as a non-voting rank-only second opinion (`src/sources/signals.py`). Conditional GET, 429-aware, 401/403 persists a stop | Every 6h | always (public pages, no creds) |
| `dynasty-signals-values.*` | Signals Fantasy AUTHENTICATED native dynasty values (offense Superflex snapshots + IDP season board) → box-local private store `data/sources/signals/values/` and the board CSVs `data/sources/signals/board/signalsSf.csv` / `signalsIdp.csv` the canonical contract build reads — an ACTIVE source since 2026-10-03 (`src/sources/signals.py`, `docs/sources/SIGNALS_FANTASY_INTEGRATION.md` §9). ≤60 GraphQL requests/run (~23), 429-aware, one renewal on 401/403 then a recorded stop | Every 6h at :17 | always (records `auth_unavailable` until a session is provisioned) |
| `dynasty-ktc-trades.*` | KTC Trade Database (most recent 200 completed dynasty trades, all formats) → box-local APPEND-ONLY raw archive `data/market_trades/archive.sqlite` (never committed) for the Market Trade Ledger (`src/sources/ktc_trades.py`, `src/trade/market_trade_*`). Evidence only — never moves a canonical value. One GET per run, conditional, no redirects, 429-aware, 401/403/challenge persists a stop; `turnoverSuspected` flags a window that turned over between runs | Every 30 min (:07/:37) | always (public page, no creds) |
| `dynasty-market-trade-ledger.*` | Rebuilds the DERIVED Market Trade Ledger (`data/market_trades/underlying_trades.sqlite`) + its daily coverage report from the box-local raw archive, the read-only Sharp intel ledger and the acquisition store (`scripts/market_trade_ledger.py --no-board`). Own unit (formerly the KTC fetch's ExecStartPost) so a rebuild cannot eat the fetch's timeout/memory; `MemoryMax=1G`; a killed run's temp file is removed by the next run | Daily 08:52 UTC | always (box-local files, no creds) |
| `dynasty-joint-filter-shadow.*` | Batch 3 Unit F shadow: builds the newest production board with the incumbent Hampel filter and with the #1571 joint robust filter (`joint_outlier_sparse_challenger`; sparse half OFF) and appends one record per board to the append-only `data/robust_filter_shadow/ledger.jsonl` (+ write-once panels), then refreshes the preregistered evaluation (`scripts/joint_filter_shadow.py`, `docs/valuation/evidence/joint-filter-shadow-2026-10-01/`). Writes no served value, flips no flag, never promotes | Twice daily, 07:55 + 19:55 UTC | always (no creds) |
| `dynasty-sparse-evidence-shadow.*` | Sparse-evidence estimator SHADOW ledger (Batch 3 Unit E): builds the newest served board twice in memory -- incumbent (flag `sparse_evidence_estimator` OFF, served) and candidate C (ON, never served) -- and appends each scoped row's `evidenceState`, C's estimate / interval / bounds and the incumbent value to gitignored monthly `data/sparse_evidence_shadow/ledger-YYYY-MM.jsonl` (`scripts/sparse_evidence_shadow.py`; exit 3 when the freshest payload is past the 6 h staleness budget). Never writes a served field, flips a flag or promotes | Twice daily 08:05 / 20:05 UTC | always (local files, no creds) |
| `dynasty-pick-forecast-snapshot.*` | AL-P4 capture: per active league and per capture window (Sleeper NFL week in season, UTC ISO week otherwise), records each team's ROS strength / depth / injuries / roster, record / points / all-play, remaining schedule, roster quality + age (contract league only, and only from a board inside the 6 h staleness budget), current pick ownership by canonical pick id, the Pick Projector's served forecast with its model identity, and the league's playoff/draft rules -- all from the existing canonical owners -- to gitignored monthly `data/pick_forecast_snapshots/ledger-YYYY-MM.jsonl` (`scripts/snapshot_pick_forecast.py`). Append-only and tiered: a run writes only when it beats the window's tier (settled > unsettled, then complete > partial > degraded), naming what it supersedes; a core field missing for a transient reason is refused (exit 3) and retried (`Restart=on-failure`, 20 min, `MemoryMax=1536M`). Missing inputs are null with a reason, never zero. Capture only: nothing reads it, nothing served changes. Not in the nightly backup yet (follow-up, AL-P2 owns `deploy/backup/`) | Weekly Tue 12:20 UTC + Wed/Thu 12:20 catch-ups | always (Sleeper public API + local files, no creds) |
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
