# Production Bootstrap Runbook

This runbook is for first-time production setup and recovery on a fresh server.

Current production target:
- host: `178.156.148.92`
- user: `dynasty`
- app path: `/home/dynasty/trade-calculator`
- venv path: `/home/dynasty/.venvs/trade-calculator`
- service: `dynasty`
- domain: `riskittogetthebrisket.org`

## 1) Repo-managed bootstrap (safe to rerun)

Run as `dynasty` from the repo root:

```bash
cd /home/dynasty/trade-calculator
bash deploy/bootstrap-production.sh
```

What this script does:
1. Verifies command-scoped NOPASSWD sudo for `systemctl`, `journalctl`, and `install`.
2. Creates/repairs Python venv path if missing.
3. Installs Python dependencies from canonical `requirements.txt`.
4. Installs Playwright browser binaries (`chromium` by default).
5. Installs/updates systemd unit via `deploy/install-systemd-service.sh`.
6. Restarts `dynasty` and runs `deploy/verify-deploy.sh`.
7. Writes deploy state markers under `DEPLOY_STATE_DIR`.

Optional environment flags:
- `INSTALL_PLAYWRIGHT_BROWSER=true|false` (default `true`)
- `INSTALL_PLAYWRIGHT_DEPS=true|false` (default `false`; runs interactive `sudo ... playwright install-deps`)
- `FORCE_SERVICE_INSTALL=true|false` (default `false`)
- `STRICT_LOCAL_HEALTH=true|false` (default `false` for bootstrap)
- `RUN_VERIFY=true|false` (default `true`)

## 2) Required manual security/OS prerequisites (external)

These are intentionally not auto-managed by deploy automation.

### 2.1 Sudoers policy for deploy user

Deploy automation expects command-scoped sudo, not `NOPASSWD: ALL`.

Required entries for `dynasty`:
- `/bin/systemctl` or `/usr/bin/systemctl`
- `/bin/journalctl` or `/usr/bin/journalctl`
- `/usr/bin/install` or `/bin/install`

Optional but recommended for automatic venv ownership repair:
- `/bin/chown` or `/usr/bin/chown`

### 2.2 Base server packages

Server must have at least:
- `python3`
- `python3-venv`
- `git`
- `curl`
- `sudo`
- `systemd`

### 2.3 Playwright OS dependencies

If browser runtime checks fail, run:

```bash
cd /home/dynasty/trade-calculator
sudo /home/dynasty/.venvs/trade-calculator/bin/python -m playwright install-deps chromium
```

## 3) Reverse proxy and TLS assumptions

Repo deploy scripts do **not** manage live nginx/certbot state.

Expected production edge assumptions:
1. `riskittogetthebrisket.org` terminates TLS at nginx.
2. HTTP (`:80`) redirects to HTTPS (`:443`).
3. nginx proxies app traffic to `http://127.0.0.1:8000`.
4. `/api/health` remains reachable externally over HTTPS for smoke checks.

## 4) Post-bootstrap verification

From server:

```bash
sudo -n /bin/systemctl is-active dynasty
curl -fsS http://127.0.0.1:8000/api/status | head -c 400
curl -fsS https://riskittogetthebrisket.org/api/health | head -c 400
```

From GitHub:
1. Ensure production secrets/vars are set.
2. Run `.github/workflows/deploy.yml` on `main`.
