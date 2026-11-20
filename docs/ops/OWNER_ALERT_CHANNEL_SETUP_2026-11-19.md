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
  - `POST /api/test-alert` (admin) reports per-channel delivery as booleans, plus `ntfyState`;
  - the Signals probe reports which channels the box has configured (`alertRouting.*`, booleans only, plus
    `ntfyState`);
  - `signals-health-probe.yml` mode `notify-test` sends one labelled TEST push per alert class from the box.
- Added 2026-11-20 (alert delivery hardening):
  - **One validator.** `src/utils/owner_notify.py::validate` decides whether a `NOTIFY_WEBHOOK_URL` value is
    usable: lower-case `https://` with a host, or `http://` to loopback; no spaces, no `user:pass@`, no quotes.
    It answers `ok`, `unset` or `rejected:<reason>` and never repeats the value. Shell callers can ask it with
    `python -m src.utils.owner_notify --check` (exit 0 ok, 1 rejected, 3 unset).
  - **A rejected value is reported, not silently dropped.** The backend logs one startup warning naming the
    variable and the reason. The deploy pre-flight prints the same line when it can load the validator; it
    never refuses a deploy over it. `/api/test-alert` and the probe report it as `ntfyState`
    (`rejected:scheme`, or `rejected_scheme` in the probe).
  - **Delivery health is visible from outside.** `/api/status` publishes `alertDelivery` (`ntfyConfigured`,
    `emailConfigured`, `lastDeliveredAt`, `lastFailedAt`, `consecutiveFailures`; booleans, timestamps and a
    count). It also publishes `alertSweepAgeHours`, the hours since the daily alert sweep last finished
    (`null` = none recorded yet). The 6-hourly SLO check breaches on 3 failed deliveries in a row
    (`alerting.alert_delivery_failing`) and on a sweep older than 30 h (`alerting.alert_sweep_age`). A missing
    value is UNKNOWN, never OK. Expect `alert_sweep_age` to be UNKNOWN until the first sweep (15:00 UTC) after
    the deploy that ships it.
  - **The delivery record survives restarts.** Each sweep attempts at most a couple of deliveries, so three
    failures in a row take several sweeps, and a deploy in between used to reset the count to 0. The record now
    persists in the server's user store, beside the sweep stamp. Failures add up across sweeps and restarts
    until a delivery succeeds. Writing the record is best-effort: if the store fails, the alert is still sent,
    the server logs the error class, and it reports its own in-process count.
  - **No record is never published as 0.** Until the box records a delivery attempt, `consecutiveFailures` is
    `null`, and `deliveryRecord` says why: `none` (no delivery has ever been attempted; every attempt is
    persisted, so none has failed) or `unreadable`. The SLO rule `alert_delivery_failing` is OK with no channel
    configured ("nothing can fail here"), OK with a channel and `none` ("no delivery has been attempted yet"),
    and UNKNOWN only when the record is unreadable or not reported. To record an attempt at once, send `POST
    /api/test-alert` (admin). The `notify-test` probe mode does not record anything: it runs outside the server
    and never writes the server's store.

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
3. **Box — the units that push from their own environment.**
   - Run `sudo systemctl edit dynasty-signals-auth-renew.service` and add:
     ```
     [Service]
     Environment="NOTIFY_WEBHOOK_URL=https://ntfy.sh/<topic>"
     ```
   - **The on-box uptime probe is not installed today.** The probe run on 2026-11-19 (44532781512, after this change
     deployed) reported `uptimeProbeNtfyConfigured: null`: systemd does not have `riskit-uptime.service` loaded.
     Outside-in uptime is still covered by `health-check.yml` (step 4). If you want the 5-minute on-box probe too,
     first install it:
     ```bash
     cd /home/dynasty/trade-calculator
     sudo cp deploy/monitoring/riskit-uptime.service deploy/monitoring/riskit-uptime.timer /etc/systemd/system/
     sudo systemctl daemon-reload && sudo systemctl enable --now riskit-uptime.timer
     ```
     Then run `sudo systemctl edit riskit-uptime.service` with the same two lines.
   - Then run `sudo systemctl daemon-reload`.
4. **GitHub.** Go to repo Settings → Secrets and variables → Actions → New repository secret. Name it
   `NOTIFY_WEBHOOK_URL`, with the same URL as the value.
5. Reply "alerts configured". I then run the verification below. You only confirm what arrived on the phone.

**Verification (I run these; you confirm receipt).**

| Check | How | Expected |
|---|---|---|
| Box configuration | `signals-health-probe.yml` mode `health` | `alertRouting.ntfyConfigured` and `renewalNtfyConfigured` `true`, `alertRouting.ntfyState` `ok`; `uptimeProbeNtfyConfigured` `true` only if you installed the uptime probe (otherwise `null`) |
| Box → phone path | `signals-health-probe.yml` mode `notify-test` | 5 labelled TEST pushes arrive. You confirm 5 |
| GitHub → phone | `health-check.yml` dispatch with `owner_push_test: true` | 1 TEST push arrives. You confirm 1 |
| A REAL alert | the next daily alert sweep (`dynasty-signal-alerts`) | The real "Signals reconnect required" notice arrives, because the episode has been open since the session failed. The probe then shows `reconnectNoticeDelivered: true` |
| Delivery health | `/api/status` after that sweep | `alertDelivery.lastDeliveredAt` set, `consecutiveFailures` `0`, `alertSweepAgeHours` below 30 |

What the TEST pushes prove, and what they do not. The 5 box pushes are title-only messages sent with the `.env`
URL by `scripts/send_owner_test_alert.py`. They prove that the box can reach your phone with that URL. They do not
prove that each alert class is produced. Two of the five classes are not box alerts at all: deploy lag and the
health/SLO alerts come from `health-check.yml` with the repo secret, and the GitHub row proves that path. The
production paths that build the real box alerts (`send_alert`, the ops and staleness sweeps) are covered by unit
tests and by the "A REAL alert" row.

**Deduplication and recovery (unit-tested).**

- **Ops alerts:** each condition has a 4-hour cooldown. Only a DELIVERED alert starts it. A sweep with no channel,
  or one whose delivery failed, spends nothing, so the next sweep tries again. When the condition clears you get
  one recovery notice (`src/api/ops_alerts.py`).
- **Source-staleness alerts:** the same rule since 2026-11-20, with a 72-hour cooldown per source
  (`src/api/source_health_alerts.py`).
  - Before that change the 72 h window was stamped even when nothing was delivered, and an undelivered recovery
    was lost.
  - A recovery notice is now retried every sweep until it is delivered.
  - A stale episode you were never told about ends without a recovery notice.
- **Signals notice:** sent once per failure episode.
- **`send_alert`** (uptime, scrape failure, partial scrape, low disk, stale backups): a one-hour cooldown PER
  ALERT CLASS since 2026-11-20. One class no longer silences another.
  - Each uptime outage you were told about gets exactly one "Uptime recovered", even inside the hour. A
    recovery is never held back by a cooldown.
  - You get no recovery for an outage you were never told about.
  - Which outages you were told about is kept in the server's memory. After a restart or deploy, an outage
    announced before it gets no "Uptime recovered", and its next failure may be announced again.
  - A recovery does not reset the uptime cooldown. If the check flaps, you get at most one failure and one
    recovery per hour (2026-11-20 review: resetting it sent 8 pushes an hour at the default 5-minute check
    interval and 80 at the 30-second minimum).
  - A recovery that arrives while its failure alert is still being sent waits for that send. It goes out only
    if the failure alert was delivered.
  - An undelivered alert sets no cooldown, so it is retried on the next trigger.
  - The e-mail fallback uses the same 587-then-465 sender as the sweeps. On failure it logs the error class
    only, never the address or the server's reply.
- **GitHub-side pushes:** only on create, change and recovery.

**Expect a short burst after setup.** Conditions that are already firing are pushed on the next sweep. The Signals
reconnect notice is certain. Any open ops condition may follow.

Source-staleness conditions recorded before 2026-11-20 keep their old timestamp. Each one stays quiet until that
timestamp is 72 h old, then it is pushed. This avoids a burst on upgrade. The 4 stale private Signals sources are
the likely candidates until you reconnect Signals.

**Rollback.**
- Remove the `NOTIFY_WEBHOOK_URL` line from `.env` (or restore `.env.bak.<date>`) and restart `dynasty`.
- `sudo systemctl revert riskit-uptime.service dynasty-signals-auth-renew.service`.
- Delete the repo secret.
- With no channel configured, alerts return to their previous behaviour.

**If the topic leaks.** Create a new topic, repeat steps 2–4 with the new URL, and unsubscribe from the old topic in
the app.
