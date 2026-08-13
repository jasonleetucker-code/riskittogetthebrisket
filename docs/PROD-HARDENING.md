# Production Hardening — nginx, systemd resilience, backups, monitoring

**Status: PREPARED, NOT APPLIED.**  Everything in this change set is
files in the repo.  Nothing has touched the production server; no
credentials, `.env` files, or certificates were read or modified.  The
operator applies it with `deploy/apply_hardening.sh` (which is
idempotent and prints a verification checklist), or by following the
per-file install notes.

Production context (from `deploy/PRODUCTION_BOOTSTRAP.md`): a
VPS, app at `/home/dynasty/trade-calculator`, user `dynasty`, nginx +
Let's Encrypt in front of `dynasty.service` (FastAPI :8000) and
`dynasty-frontend.service` (Next.js :3000).

---

## 1. nginx — `deploy/nginx/chaseupside.com.conf`

| Change | Rationale |
|---|---|
| `listen 443 ssl http2` (+ IPv6 listeners) | HTTP/2 multiplexing removes head-of-line blocking for the asset-heavy Next.js pages.  The combined `listen ... http2` spelling works on the nginx 1.24.x that Ubuntu LTS ships; on nginx ≥ 1.25.1 it still works but logs a deprecation warning — switch to `http2 on;` there. |
| `gzip on` + JSON-centric `gzip_types`, `gzip_min_length 1024`, `gzip_vary on`, `gzip_proxied any` | Fallback compression layer.  The backend already gzips responses ≥ 1 KB (FastAPI `GZipMiddleware`) and pre-gzips `/api/data`; nginx never re-compresses responses that arrive with `Content-Encoding`, so this only catches what upstreams leave uncompressed. |
| Brotli block **commented** | `brotli` directives fail `nginx -t` unless the `ngx_brotli` modules are installed.  Install `libnginx-mod-http-brotli-{filter,static}` first, then uncomment. |
| `location /_next/static/` with `proxy_cache` (new 50 MB `riskit_static` zone) | Next.js build assets are content-hashed and served with `public, max-age=31536000, immutable`; nginx caches them so repeated hits never touch the node process.  Entry lifetime is governed by the upstream Cache-Control, which nginx passes through **unmodified**.  Privacy scope: this is the only shared cache in the config and it is attached only to `/_next/static/` — `/api/*` stays uncached, preserving the invariant documented in `tests/api/test_cache_control_privacy.py` (auth-gated endpoints must never meet a shared cache).  nginx also refuses by default to cache responses carrying `Set-Cookie` or `Cache-Control: private/no-store`. |
| `/api/` timeouts: `proxy_read_timeout 120s` (kept), `proxy_connect_timeout 5s`, `proxy_send_timeout 30s` | 120s survives scrape-cycle cache rebuilds (~3 min hold documented in the old config) and cold `/api/news` (~10s).  The 5s connect timeout makes a dead backend fail fast instead of hanging browsers for 60s. |
| `/api/` `proxy_buffers 32 16k` | The `/api/data` contract is MB-scale; bigger in-memory buffers avoid nginx spilling responses to disk temp files. |
| Security headers (server-level, `always`): HSTS `max-age=31536000`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: frame-ancestors 'self'` (enforced), `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy`, `Permissions-Policy` | `frame-ancestors` is safe to enforce — it only controls embedding and cannot break the app's own scripts.  HSTS deliberately ships **without** `includeSubDomains`/`preload`; add those only after confirming every subdomain serves TLS (HSTS mistakes lock browsers out for a year). |
| Full CSP: **report-only, commented out** | Next.js 15 App Router emits inline hydration `<script>` chunks without nonces and the app has no nonce plumbing, so an enforced `script-src` would need `'unsafe-inline'` (near-worthless) or app-code changes (out of scope for a deploy-only change).  A complete Report-Only policy is included, commented, with the known externals mapped (`sleepercdn.com` images, `sw.js` worker).  Uncomment it to gather violation data before ever enforcing. |
| **Cache-Control pass-through preserved** | The backend stamps privacy-sensitive caching per endpoint (`private, max-age=…`, `no-store`).  No location adds/hides/overrides `Cache-Control` or `expires`.  Also: no `add_header` inside location blocks at all — nginx's all-or-nothing `add_header` inheritance would otherwise silently drop the server-level security headers there. |
| `client_max_body_size 10m`, upstream `keepalive` 8/16 | Sane request-size cap (POST bodies are small trade/override payloads); deeper idle-connection pool to the node process for HTTP/2 fan-out. |

Unchanged: routing structure, upstream addresses, certbot TLS include
lines, the 80→443 redirect, and the WebSocket upgrade path on `/`.

## 2. systemd — service templates

Both `deploy/systemd/dynasty.service.template` and
`dynasty-frontend.service.template` (rendered by
`deploy/install-systemd-service.sh`, placeholders intact):

| Change | Rationale |
|---|---|
| `Restart=always` **kept** (not switched to `on-failure`) | Existing behavior, and strictly stronger: it also revives the service after a clean-but-unexpected exit.  RestartSec=5 kept. |
| `StartLimitIntervalSec=300` + `StartLimitBurst=30` | Crash-loop brake: ~30 restarts per 5 min allowed, then systemd stops retrying a genuinely broken build.  The healthcheck watchdog runs `systemctl reset-failed` before its restart, so a tripped brake is recoverable automatically once the underlying cause clears. |
| `TimeoutStartSec=180` (backend) | Boot parses the multi-MB cached contract before binding the port (`verify-deploy.sh` budgets ~90s); don't let systemd kill a slow-but-healthy cold start. |
| `TimeoutStopSec=30` | Bounded shutdown before SIGKILL. |
| `MemoryHigh=2560M` / `MemoryMax=3G` (backend), `1536M`/`2G` (frontend) | **Assumption: a ≥ 4 GB box** — verify with `free -m` before applying; comment the lines out on smaller boxes.  Backend RSS is dominated by the in-memory contract + payload views and spikes during Playwright scrapes; MemoryHigh throttles first, MemoryMax is the OOM line and `Restart=always` recovers. |
| `PrivateTmp=true` | Isolated /tmp (incl. Playwright browser profiles). |
| Deliberately **not** added: `NoNewPrivileges`, `ProtectSystem`, `ProtectHome` | The backend launches Chromium for scrapes; these knobs can break the browser sandbox/profile handling.  Documented in the unit as "test a full scrape cycle before adding". |
| `After/Wants=network-online.target` | Don't race the network at boot. |

Note: the new settings land on the **next service restart** after
`install-systemd-service.sh` + `daemon-reload`.  The apply script does
not restart the services for you — do it at a quiet moment and follow
with `deploy/verify-deploy.sh`.

## 3. Backend watchdog — `deploy/systemd/dynasty-healthcheck.*`

New: `dynasty-healthcheck.sh` + `.service` + `.timer`.

**Liveness and application health are deliberately separate.**
`/api/health` returns HTTP 503 with `status: "degraded"` for stale
data, a failed/stalled scrape, or contract validation failure while
the process is **up and serving cached data**
(`server.py::get_health` — `status_code=200 if is_ok else 503`).
Restarting on a degraded 503 would bounce a healthy process, and
worse: the restart clears the in-memory scrape error and reloads the
disk cache with a fresh `loadedAt`, flipping health green **without a
successful scrape** — the watchdog would actively conceal ingestion
faults.  So:

- **Liveness probe** (every minute, curls
  `http://127.0.0.1:8000/api/health` *without* `-f`, 25s budget):
  **any** HTTP response — 200, 401, 404, 503 — is proof of life; the
  probe hits 127.0.0.1 directly, so no proxy can answer on a dead
  backend's behalf.  Only a connection-level failure (refused,
  timeout, empty reply — a non-zero curl exit) counts toward the
  restart threshold.
- After **3 consecutive** liveness failures: `systemctl reset-failed
  dynasty` (clears a tripped StartLimit brake) then `systemctl
  restart dynasty`, and the counter resets so an unhelpful restart
  re-triggers only after another full threshold.
- **Degraded 503s are log-only**, reported on state transitions (one
  journal line entering degraded, one on clearing) with a pointer to
  `/api/status` and the service journal.  The watchdog never restarts
  a process that is answering HTTP.
- Counter and degraded flag live in `/run/dynasty-healthcheck`
  (RuntimeDirectory — clean slate on reboot).  Logs to the journal.
- Tunables (`HEALTH_FAIL_THRESHOLD`, `HEALTH_URL`, …) via
  `systemctl edit dynasty-healthcheck.service`.
- Runs as root because it must drive systemctl; the frontend is left to
  its own `Restart=always` (a wedged-but-listening Next process is far
  rarer, and the uptime probe surfaces it).
- **Root/checkout separation**: because the unit runs as root, its
  `ExecStart` points at a root-owned copy in `/usr/local/lib/riskit/`
  (root:root 0755) installed by `apply_hardening.sh` — executing the
  deploy-user-writable checkout copy as root would let a compromised
  `dynasty` account swap the script and get root within a minute.
  Script updates flow through re-running the apply script; editing the
  checkout copy alone changes nothing at runtime.

## 4. Backups — `deploy/backup/` (new)

`riskit-state-backup.sh` + `.service` + `.timer` (+ README): nightly
02:30 UTC, keep **14** daily generations, umask 077.

- SQLite (`user_kv`, `session_store`, `guest_passes`) via the same
  WAL-safe `sqlite3.Connection.backup()` primitive the existing
  `backup_user_kv.sh` uses.
- `data/public_league/` and `data/intel/` as tar.gz — both guarded
  (`intel/` does not exist yet).
- Scraper session cookies (`dlf`/`draftsharks`/`idpshow`
  `*_session.json`, repo root **and** `/var/lib/{dlf,idpshow}-fetch/`)
  — gitignored secrets, backed up **on-box only**, mode 0600.  The IDP
  Show session is manually provisioned (captcha-gated login), which is
  exactly why losing it hurts.
- Every artifact integrity-checked: SQLite copies get
  `PRAGMA integrity_check` against the *copied* database (structural
  corruption copies page-for-page through `Connection.backup()` and
  passes `gzip -t`, which only validates the compressed stream) plus
  `gzip -t`; tarballs get `tar -tzf`.  The run fails loudly if zero
  artifacts were written.
- Destructive steps run strictly last: artifacts stage into a hidden
  dir and only a fully validated snapshot is promoted into `daily/`,
  mirrored off-box, or allowed to trigger pruning.  A failed run
  discards its own staging dir — it can never displace a good
  generation from the keep-window or publish a partial snapshot to the
  rsync mirror.
- **Required-artifact manifest**: an artifact *count* alone is not
  enough — with `DATA_DIR` unmounted or mistyped, a stray session JSON
  still produces one artifact, and that partial snapshot must never be
  promoted over a complete generation.  `BACKUP_REQUIRED` (default
  `user_kv.sqlite session_store.sqlite`) names the core items that
  must be written **and** integrity-verified before promotion; a
  missing required item discards staging and exits 1 with `daily/`
  untouched.
- **Root/checkout separation**: the unit runs as root, so `ExecStart`
  points at the root-owned copy in `/usr/local/lib/riskit/` installed
  by `apply_hardening.sh` — same rationale as the watchdog above.
- Optional off-box mirror: set `OFFBOX_RSYNC_DEST` via a service
  drop-in (operator fills in destination + SSH key).  Unset = local
  only, nothing leaves the box.
- The existing `riskit-backup.timer` (02:00, sqlite-only, 30 daily +
  12 monthly + weekly restore test) **stays enabled** — the overlap is
  a few MB per night and preserves the long sqlite history and the
  exercised restore path.

## 5. Uptime monitoring — `deploy/monitoring/` (new)

`uptime_check.sh` + `riskit-uptime.service`/`.timer` (+ README):
every 5 minutes probes `https://chaseupside.com/api/health`,
the frontend root, and the local backend port; appends one line per run
to `/var/log/riskit-uptime.log`.

- **No third-party service.**  Notification is opt-in via
  `NOTIFY_WEBHOOK_URL` (any plain-text-POST endpoint the operator
  chooses) or `NOTIFY_CMD` (message on stdin, e.g. `mail`), configured
  through a drop-in.  Fires only on UP↔DOWN **state changes**.
- Honest limitation, documented: it runs on the VPS, so it cannot see a
  full network partition/dead box.  The script is dependency-free
  (bash + curl) and can be run unchanged from any second machine.
- **Least privilege**: the probe only curls and logs, so the unit runs
  as `User=dynasty`, not root.  It may safely execute from the
  checkout because the process has no more privilege than the user who
  can already edit that file.  The log still lands in
  `/var/log/riskit-uptime.log` because systemd (pid 1) opens the
  `StandardOutput=append:` target before dropping privileges; state
  moves to `/var/tmp` (deploy-user writable).

## 6. Apply script — `deploy/apply_hardening.sh` (new)

Root-only, idempotent, `--dry-run` supported.  Order of operations:

1. nginx: diff repo config vs `/etc/nginx/sites-available/…`; if
   different → timestamped backup → install → `nginx -t` →
   `systemctl reload nginx`.  On `nginx -t` failure it restores the
   backup automatically; on a **first install** (no backup exists) it
   removes the invalid file *and* the enabled symlink so a later nginx
   restart/reboot cannot pick them up.  The sites-enabled symlink is
   validated by resolved target (`readlink -f`), not mere existence —
   a stale or broken link is recreated to point at the intended
   config, and because that changes what nginx will serve, the repair
   runs the same `nginx -t` + `systemctl reload nginx` sequence as a
   config install (restoring the previous link state verbatim if
   validation fails there).
2. Re-renders `dynasty`/`dynasty-frontend` units from the hardened
   templates via the existing `install-systemd-service.sh`
   (`FORCE_SERVICE_INSTALL=true`; no restart performed).  `VENV_DIR`
   is derived from the **APP_USER's** home via `getent` — never from
   `$HOME`, which is `/root` under `sudo` and would have rendered the
   backend unit against a nonexistent `/root/.venvs/...` interpreter —
   and a pre-flight assertion refuses to rewrite the units unless
   `$VENV_DIR/bin/python` actually exists.
3. Installs root-owned copies (root:root 0755) of the two root-run
   scripts — `dynasty-healthcheck.sh`, `riskit-state-backup.sh` — into
   `/usr/local/lib/riskit/` (override: `RISKIT_LIB_DIR`), diff-aware.
   The units execute those copies, never the checkout; re-run the
   apply script to roll out script changes.
4. Installs the healthcheck / state-backup / uptime units (diff-aware;
   rewrites the canonical `/home/dynasty/trade-calculator` path to
   `APP_DIR`, `/usr/local/lib/riskit` to `RISKIT_LIB_DIR`, the
   watchdog's `HEALTH_SERVICE` to `SERVICE_NAME`, and the uptime
   probe's `User=/Group=` to `APP_USER`, when overridden).
5. `daemon-reload`, `enable --now` on the three timers.
6. Prints the full verification checklist.

## Operator runbook

```bash
# on the VPS, as the deploy user, repo up to date on main
cd /home/dynasty/trade-calculator
sudo bash deploy/apply_hardening.sh --dry-run   # review every diff
sudo bash deploy/apply_hardening.sh             # apply
# then walk the printed checklist; at a quiet moment:
sudo systemctl restart dynasty-frontend dynasty
bash deploy/verify-deploy.sh
```

## Rollback

Every step is independently reversible:

- **nginx**: the apply script leaves
  `/etc/nginx/sites-available/chaseupside.com.bak.<timestamp>`.
  `sudo cp <backup> /etc/nginx/sites-available/chaseupside.com
  && sudo nginx -t && sudo systemctl reload nginx`.
- **Service units**: `git checkout <previous-commit> --
  deploy/systemd/dynasty.service.template
  deploy/systemd/dynasty-frontend.service.template`, then
  `FORCE_SERVICE_INSTALL=true bash deploy/install-systemd-service.sh`,
  `sudo systemctl daemon-reload`, restart at a quiet moment.
- **Watchdog**: `sudo systemctl disable --now dynasty-healthcheck.timer`
  (the backend keeps its own `Restart=always`).
- **State backup**: `sudo systemctl disable --now riskit-state-backup.timer`
  (the older `riskit-backup.timer` still covers sqlite).
- **Uptime probe**: `sudo systemctl disable --now riskit-uptime.timer`.

## Validation performed in the sandbox (and its limits)

- `bash -n` on all four shell scripts: **pass**.
- `systemd-analyze verify` (systemd 255) run against the concrete new
  units: warnings limited to units referencing paths that only exist on
  the production box — expected; no syntax errors.
- **nginx is not installed in the sandbox**, so `nginx -t` could NOT be
  run here.  The config was upgraded by careful review against the
  previous known-good file; the apply script runs `nginx -t` before any
  reload and auto-restores the backup on failure, so a syntax mistake
  cannot take the site down.
- `shellcheck` not available in the sandbox; scripts follow the
  existing deploy/ conventions (`set -Eeuo pipefail`, quoted
  expansions).
- Full Python test suite run once to prove no app code changed.

## Backlog: tighten the production deploy sudo scope

Filed 2026-08-13 out of the #813 review, and deliberately NOT done in
that PR — it is a sudoers redesign, not an incident repair.

The deploy identity holds NOPASSWD sudo for `systemctl`, `journalctl`,
`install` and `chown`, unrestricted in their arguments.  That is what
makes automatic runtime reconciliation possible without new privilege,
and it is also the limit of what the arrangement proves:

- keeping the root-EXECUTED watchdog as a `root:root 0755` copy under
  `/usr/local/lib/riskit/`, outside the deploy-user-writable checkout,
  stops an ordinary edit to the checkout from becoming the script root
  runs, and preserves the intended ownership/execution layout;
- it is **not** an OS security boundary around the deploy identity.
  Anything already running as that identity can call
  `sudo install`/`sudo systemctl` directly.
  `deploy/reconcile-runtime-controls.sh::_rc_sudo` constrains what *that
  script* will do; it constrains nothing else.

Do not describe the current design as containment of a compromised
deploy account.  Narrowing the sudoers rules — argument-constrained
`install` destinations, a fixed unit allowlist for `systemctl` — is the
work that would change that, and it belongs in its own change with its
own rollback plan.
