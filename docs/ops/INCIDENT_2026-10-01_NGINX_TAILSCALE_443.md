# Incident 2026-10-01 — chaseupside.com down: nginx could not bind :443

**Severity:** P0. The whole public service (website and iPhone PWA) was unreachable.
**Status:** RESTORED at 2026-10-01 11:44 UTC (13:44 CEST).

## Timeline (UTC)

| time | event |
|---|---|
| 02:22–~03:00 | Last verified healthy deploy: `71d5d9dcd` (run 36805504364, `PASS build.commit`). |
| 04:07:54 | `unattended-upgrade` upgrades `libssl3t64` / `openssl` (3.0.13-0ubuntu3.15 → .16). |
| 04:08:04 | systemd re-execs; libssl-linked services restart together: `dynasty`, `nginx`, `ssh`, `tailscaled`, `edgelab-dashboard`, journald. |
| 04:08:05 | `tailscaled: listening on 100.107.60.6:443` (Tailscale Serve, tailnet-only, proxying the Market Edge Lab dashboard on 127.0.0.1:8765). |
| 04:08:10–12 | `nginx: [emerg] bind() to 0.0.0.0:443 failed (98: Address already in use)` → `nginx.service: Failed`. |
| 04:36, 06:4x, 09:44, 11:03 | Every deploy ships to the box, then hangs in the post-deploy smoke test (public URL refused) until the job timeout ("cancelled"). Health check opens #1568 at 05:50. |
| ~11:30 | Detected and diagnosed (read-only, over the `dynasty` SSH account). Owner reports website and iPhone app down. |
| 11:44 | Fix applied; nginx `active`; external HTTPS 200. |

Outage: about **9 h 36 m** (04:08 → 11:44).

## Root cause

Both nginx sites on the box (`dynasty` = chaseupside.com, `housing`) used wildcard
`listen 443 ssl` / `listen [::]:443`. Tailscale Serve listens on `:443` of the box's
**tailnet** addresses (`100.107.60.6`, `fd7a:115c:a1e0::a938:3c08`).

- **The conflict.** A wildcard bind cannot coexist with another process LISTENING on a
  specific address on the same port.
- **Why it was dormant.** Before 04:08, nginx held the wildcard first, so the conflict
  never surfaced.
- **The trigger.** The unattended OpenSSL upgrade restarted both processes at once.
  tailscaled re-bound while nginx was still stopping, and nginx lost the race.

**Not caused by application code.** `71d5d9dcd..c9a939104` touches no deploy, workflow or
nginx file, and the Batch 2 changes (deploy SHA pinning, Signals, Lane 6, BDVM) were
not involved. The Calculator backend and frontend stayed healthy on localhost
throughout (deploy verify: `/api/status`, `/api/health` OK; 151/151 Next chunks).
No rollback was warranted: no release was at fault.

## Fix

**On the box** (2026-10-01 11:44 UTC, through the deploy account's existing
passwordless `install` + `systemctl` sudo rules):
- Both 443 listeners were rebound to the box's **public** addresses:
  `169.58.50.224:443` and `[2a02:c207:2345:4985::1]:443`.
- The originals are kept at `/etc/nginx/sites-available/{dynasty,housing}.bak-20261001-incident`.
- `systemctl start nginx` succeeded. nginx and Tailscale Serve now both listen on :443
  on different addresses, in any restart order.
- Tailscale and Market Edge Lab were not touched.

**In the repo** (this PR):
- `deploy/nginx/chaseupside.com.conf` binds `__PUBLIC_IPV4__:443` / `[__PUBLIC_IPV6__]:443`.
- The cutover runbook renders those placeholders from the box's own route source
  addresses before installing.
- `tests/deploy/test_nginx_no_wildcard_443.py` fails on any wildcard :443 listener. It
  fails against the previous template.

## Verification after restoration

- **External:** five consecutive `GET /` and `/api/health` → 200 (~0.6 s). `/api/status`
  `build.commit` = `149b5b2508368ecfd28e7ea7dbb2a698121532ef`. HTTP → 301 HTTPS. TLS cert
  `CN=chaseupside.com`, valid to 2026-12-23.
- **Auth gate intact:**
  - `/login` → 200;
  - `/rankings` and `/trade` → 307 `/login?next=…`;
  - anonymous `/api/data` → 401;
  - public `/league`, `/api/leagues`, `/api/draft-capital` → 200.
- **Real browser, desktop:** `/league` renders with data; the login page renders; no
  console errors; every `_next/static` asset → 200.
- **Real browser, mobile emulation (375×812):** `/league?tab=draft-capital` renders
  data. The only console error is the expected anonymous 401 on the private
  `/api/ros/pick-projections`.
- **iPhone path:** the "app" is the installed PWA (`manifest.webmanifest`,
  `display: standalone`, `sw.js`).
  - The service worker is network-first for HTML, falls back to an offline shell, and
    caches static assets by hash. `sw.js` is served `max-age=0`.
  - So an iPhone that showed the offline shell during the outage loads normally on
    next open.
  - Not run on a physical iPhone or simulator; emulation only.
- **Box:** `nginx`, `dynasty`, `dynasty-frontend` active; no warnings in the
  post-recovery window.

### First deploy after restoration (run 36849544325, `a1933e59`)

This was also the first live run of deploy SHA pinning (#1570). One commit carried through
every stage:
- resolve: `a1933e59…` (`kind=default`);
- validated tree: `a1933e59…`;
- deploy job target: `a1933e59…`;
- box `Resolved target revision`: `a1933e59…`;
- `[verify] Public URL reachable`;
- smoke `PASS build.commit == a1933e59676bb3cddaa53fdfaf78682ccbcfaf6b`.

`/api/status` then served `a1933e59…` on three consecutive reads. A 33-poll
`/api/health` watch over the deploy saw a single 502 at 12:21:21 UTC, during the
planned backend restart (12:20:46 → active 12:21:04). Every request since has
returned 200, and nginx has logged no warnings.

## Remaining / follow-ups

- **Owner-only check:** authenticated pages could not be exercised by the agent (no
  owner credentials, by policy). The owner confirms by signing in on web and iPhone.
- **Alerting gap.** The public site was dark for 9.6 h with no owner alert:
  - deploy verify treats the public check as a warning (`STRICT_PUBLIC_HEALTH=false`);
  - #1568 opened but notified nobody.
  - The owner's ntfy path (`NOTIFY_WEBHOOK_URL`, already used by the uptime probe) should
    cover public reachability.
- **`housing.chaseupside.com` → 502:** its upstream (`127.0.0.1:8090`) is not running.
  This is a separate app, unrelated to the listen change.
- **`dynasty-depth-charts-refresh.service` is in `failed` state** (pre-existing; not an
  availability issue). Investigate separately.
- **Hard-coded addresses.** The live configs now name the box's public addresses; an IP
  change or a future `certbot --nginx` install must keep explicit addresses.
