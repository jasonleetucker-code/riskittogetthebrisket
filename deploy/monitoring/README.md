# deploy/monitoring — lightweight uptime monitoring

A single probe script + systemd timer.  No third-party services; the
probe is log-only until the operator opts in to a notification channel.

## What it checks (every 5 minutes)

1. `https://riskittogetthebrisket.org/api/health` — full external path:
   DNS → TLS → nginx → FastAPI backend.
2. `https://riskittogetthebrisket.org/` — nginx → Next.js frontend.
3. `http://127.0.0.1:8000/api/health` — backend direct (distinguishes
   "backend down" from "nginx/TLS broken"); disable with
   `CHECK_LOCAL=false`.

One line per run appended to `/var/log/riskit-uptime.log`:

```
2026-07-26T02:35:00Z UP public-health=ok(200,0.142s) public-frontend=ok(200,0.375s) local-backend=ok(200,0.009s)
2026-07-26T02:40:01Z DOWN public-health=FAIL(502) public-frontend=ok(200,0.298s) local-backend=FAIL(000)
```

Add the log to rotation by appending `/var/log/riskit-uptime.log` to
the file list in `deploy/logrotate.conf` if it grows past comfort
(~30 KB/month at 5-minute cadence — rotation is optional).

## Install

```bash
sudo cp deploy/monitoring/riskit-uptime.service deploy/monitoring/riskit-uptime.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now riskit-uptime.timer
systemctl list-timers riskit-uptime.timer
```

(`deploy/apply_hardening.sh` does this idempotently.)  Cron works too:

```
*/5 * * * * /home/dynasty/trade-calculator/deploy/monitoring/uptime_check.sh
```

## Notifications (optional, operator's choice)

The probe notifies only on **state changes** (UP→DOWN, DOWN→UP), so a
3-hour outage is one alert, not 36.  Nothing external is contacted
until you set one of these via `sudo systemctl edit riskit-uptime.service`:

```ini
[Service]
# Any URL that accepts a plain-text POST — a private ntfy.sh topic,
# a Slack/Discord incoming-webhook wrapper, a self-hosted gotify, ...
Environment="NOTIFY_WEBHOOK_URL=https://ntfy.sh/<your-private-topic>"
# ...or any command that reads the message on stdin:
#Environment="NOTIFY_CMD=mail -s riskit-alert you@example.com"
```

## Known limitation

The probe runs **on the VPS itself**.  It catches nginx, TLS, backend,
and frontend failures, but a full network partition or a dead box also
kills the prober.  If that matters, run the same script from any second
machine (`SITE_URL=... CHECK_LOCAL=false LOG_FILE=... uptime_check.sh`
from cron) — it has no dependencies beyond bash + curl.

## Relationship to other health tooling

- `deploy/systemd/dynasty-healthcheck.*` (every 1 min) is the
  **actuator**: it restarts the backend after 3 consecutive local
  failures.  This probe is the **observer** and never restarts anything.
- `deploy/verify-deploy.sh` is deploy-time verification only.
- `deploy/grafana/` visualizes public-league metrics, not uptime.
