# Owner alert channel setup — 2026-11-19 (STAB-2)

**Why.** On 2026-11-18 the Signals health probe (run 44377419713) recorded **0** reconnect-notice sends on any
channel across ~400 h: the box has no working owner-notification channel. E-mail via Gmail is firewalled on port 465
and `ALERT_TO` is not set. Every production alert reached no one, except the GitHub-side issues (health check, SLO
#2258), which notify only through GitHub's own e-mail.

**What changed in code (PR "owner alert routing").**

- Every server-side alert now goes through `src/utils/owner_alerts.py`: the owner's ntfy webhook
  (`NOTIFY_WEBHOOK_URL`) first, e-mail as the fallback. This covers:
  - backup and uptime watchdogs, scrape failures and low disk (`server.send_alert`);
  - the ops-alert sweep (data freshness, failed units, backup coverage, contract health …);
  - per-source staleness alerts;
  - the Signals reconnect notice.

  Before, only the last of these could use ntfy.
- `health-check.yml` pushes to the same topic, read from the repo secret `NOTIFY_WEBHOOK_URL`. It pushes on a NEW
  health or SLO incident, a CHANGED breach set, and every recovery — never on every run.
- Ways to verify:
  - `POST /api/test-alert` (admin) reports per-channel delivery as booleans;
  - the Signals probe reports which channels the box has configured (`alertRouting.*`, booleans only);
  - `signals-health-probe.yml` mode `notify-test` sends one labelled TEST push per alert class from the box.

**What you need to do (about 10 minutes).** The topic name is a secret: anyone who knows it can read and post to it.
Never paste it in chat, an issue or a commit.

1. **Create the topic and subscribe.**
   - Install the free *ntfy* app on the iPhone.
   - Generate an unguessable topic name on your own computer:
     `python3 -c "import secrets; print('riskit-' + secrets.token_urlsafe(24))"`
   - In the app, subscribe to that topic on `ntfy.sh`.
   - The URL is `https://ntfy.sh/<topic>`.
   - ntfy.sh is free and needs no account. Alert text is operational (no secrets, no private league data), but it
     passes through ntfy.sh. If you would rather self-host, any HTTPS endpoint that accepts a plain-text POST works.
2. **Box — backend and alert sweep.**
   ```bash
   sudo -u dynasty bash -lc 'cd /home/dynasty/trade-calculator && cp -p .env .env.bak.$(date +%Y%m%d) && printf "\nNOTIFY_WEBHOOK_URL=%s\n" "https://ntfy.sh/<topic>" >> .env'
   sudo systemctl restart dynasty
   ```
3. **Box — the two units that push from their own environment.**
   - Run `sudo systemctl edit riskit-uptime.service`, then `sudo systemctl edit dynasty-signals-auth-renew.service`.
   - In each, add:
     ```
     [Service]
     Environment="NOTIFY_WEBHOOK_URL=https://ntfy.sh/<topic>"
     ```
   - Then run `sudo systemctl daemon-reload`.
4. **GitHub.** Go to repo Settings → Secrets and variables → Actions → New repository secret. Name it
   `NOTIFY_WEBHOOK_URL`, with the same URL as the value.
5. Reply "alerts configured". I then run the verification below. You only confirm what arrived on the phone.

**Verification (I run these; you confirm receipt).**

| Check | How | Expected |
|---|---|---|
| Box configuration | `signals-health-probe.yml` mode `health` | `alertRouting.ntfyConfigured`, `uptimeProbeNtfyConfigured` and `renewalNtfyConfigured` all `true` |
| Box → phone, every class | `signals-health-probe.yml` mode `notify-test` | 5 TEST pushes arrive: Signals reconnect, source freshness, deploy lag, backup, health. You confirm 5 |
| GitHub → phone | `health-check.yml` dispatch with `owner_push_test: true` | 1 TEST push arrives. You confirm 1 |
| A REAL alert | the next daily alert sweep (`dynasty-signal-alerts`) | The real "Signals reconnect required" notice arrives, because the episode has been open since the session failed. The probe then shows `reconnectNoticeDelivered: true` |

**Deduplication and recovery (unchanged, unit-tested).**

- Ops and source-staleness alerts keep their per-condition cooldown and send one recovery notice when a condition
  clears (`src/api/ops_alerts.py`, `src/api/source_health_alerts.py`).
- The Signals notice is sent once per failure episode.
- `send_alert` has a one-hour cooldown. An undelivered alert sets no cooldown, so it is retried.
- GitHub-side pushes fire only on create, change and recovery.

**Expect a short burst after setup.** Conditions that are already firing are pushed on the next sweep. The Signals
reconnect notice is certain. Any ops or source-staleness condition that is currently open may follow; the 4 stale
private Signals sources are the likely one until you reconnect Signals.

**Rollback.**
- Remove the `NOTIFY_WEBHOOK_URL` line from `.env` (or restore `.env.bak.<date>`) and restart `dynasty`.
- `sudo systemctl revert riskit-uptime.service dynasty-signals-auth-renew.service`.
- Delete the repo secret.
- With no channel configured, alerts return to their previous behaviour.

**If the topic leaks.** Create a new topic, repeat steps 2–4 with the new URL, and unsubscribe from the old topic in
the app.
