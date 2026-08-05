# Runbook — rotate `INTEL_REFRESH_TOKEN`

**Status:** open operator action (`UNIMPLEMENTED_BACKLOG.md` §10,
`docs/ORCHESTRATION.md` §6.5, `OWNER_ACTION_AUDIT_2026-07-29.md` OA-09).
The token "sat unencrypted for months" and has never been confirmed rotated.

**Who can run this:** you only. Writing the Actions secret needs
`administration: write` plus libsodium sealing against the repo public key;
writing the prod `.env` needs SSH + `sudo` on the VPS. Neither is available
to an agent session, which is why this is a runbook and not a script.

---

## Read this first — you may not be rotating the variable you think

`server.py:12529`:

```python
INTEL_REFRESH_TOKEN = os.getenv("INTEL_REFRESH_TOKEN", "").strip() or SIGNAL_ALERT_CRON_TOKEN
```

There is a **fallback**, and `.env.example:105` ships `INTEL_REFRESH_TOKEN=`
**commented out**. So production may today be authenticating the intel
refresh with `SIGNAL_ALERT_CRON_TOKEN` and have no `INTEL_REFRESH_TOKEN`
line at all.

That changes what this task even is:

| what prod actually has | what "rotation" means |
|---|---|
| a real `INTEL_REFRESH_TOKEN=` line | rotate it — Step 2 onward, blast radius is the intel refresh only |
| no such line (falling back) | you are **adding** a variable, not rotating one. Do that (it is strictly better — it stops the two secrets being one secret), and leave `SIGNAL_ALERT_CRON_TOKEN` alone |

**Which one is true cannot be determined from the repository.** Step 1
determines it. Do not skip it.

Rotating `SIGNAL_ALERT_CRON_TOKEN` instead has a much wider blast radius —
see the trap table at the bottom.

---

## Step 1 — [VPS] Find out which variable is live

**Precondition:** SSH access to the deploy host as a user who can read the
app's `.env`.

```bash
ssh <deploy-user>@<deploy-host>
sudo grep -nE '^[[:space:]]*(INTEL_REFRESH_TOKEN|SIGNAL_ALERT_CRON_TOKEN)=' \
  /home/dynasty/trade-calculator/.env
```

> **Checkpoint.** Read the output carefully:
>
> * **Both lines present** → you are rotating `INTEL_REFRESH_TOKEN`. Continue at Step 2.
> * **Only `SIGNAL_ALERT_CRON_TOKEN=`** → the intel refresh is running on the
>   fallback. Continue at Step 2 anyway; you are adding the dedicated
>   variable, which also decouples the two.
> * **Neither** → stop. The refresh cannot be authenticating at all and the
>   daily workflow should be failing; investigate that first.
> * **A line starting `export `** → that is the trap in row 4 below. systemd's
>   `EnvironmentFile` ignores it silently. Fix the format as part of Step 3.

The host/user vary between docs (`root@chaseupside.com`,
`root@<deploy-host>`, `dynasty@<deploy-host>` all appear). The
authoritative pair is the `DEPLOY_HOST` / `DEPLOY_USER` repo secrets that
`deploy.yml:240-243` uses; `sudo` is needed either way.

## Step 2 — [local] Generate the new value

```bash
openssl rand -hex 32
```

> **Checkpoint.** 64 hex characters. Keep the terminal open — you need to
> paste the *identical* string into two places, and they must match
> **byte for byte**. Do not let an editor add a trailing newline.

## Step 3 — [VPS] Update the prod `.env`, then restart

```bash
sudo cp /home/dynasty/trade-calculator/.env \
        /home/dynasty/trade-calculator/.env.bak-$(date +%F)
sudo nano /home/dynasty/trade-calculator/.env
#   set (or add):   INTEL_REFRESH_TOKEN=<the value from Step 2>
#   plain KEY=value — NO `export`, no quotes, no trailing spaces
sudo systemctl restart dynasty
sudo systemctl is-active dynasty
```

> **Checkpoint.** `active`. The restart is not optional: `server.py:12529`
> runs at import, so the value is read once at process start. Editing
> `.env` without restarting changes nothing and the next run still 401s.

## Step 4 — [GitHub] Update the Actions secret

Settings → Secrets and variables → Actions → `INTEL_REFRESH_TOKEN` → Update.

> **Checkpoint.** Paste with no trailing newline. The server `.strip()`s its
> side (`:12529`); the workflow does **not** strip the secret
> (`intel-refresh.yml:65`), so a stray newline is a mismatch that the
> backend logs only as `lengths match: False`.

## Step 5 — Verify, and do not wait for the cron to tell you

Actions → **Intel Refresh** → Run workflow.

> **Checkpoint.** Green. A 401 means the two halves disagree — the
> workflow's own checklist (`intel-refresh.yml:113-128`) lists the four
> causes in order. Without this step a mismatch surfaces at 09:10 UTC the
> next day, as a failed run and an `intel-stale` issue.

The workflow's sidebar name is **Intel Refresh** (`intel-refresh.yml:1`).
OA-09 calls it "Sharp Tracker intel refresh", which is not a string that
appears in the UI.

## Rollback

```bash
sudo cp /home/dynasty/trade-calculator/.env.bak-<date> \
        /home/dynasty/trade-calculator/.env
sudo systemctl restart dynasty
```
…then restore the previous secret value in GitHub. Both halves, or they
disagree again.

---

## Traps — each of these has a silent failure mode

| # | Trap | Why it bites |
|---|---|---|
| 1 | Editing `.env` without restarting `dynasty` | Token is read at import (`server.py:12529`). No error, just 401s. |
| 2 | Trailing newline in the Actions secret | Server strips, workflow does not. Logged only as a length mismatch. |
| 3 | Updating only one of the two stores | The other keeps the old value; the daily run 401s and opens an `intel-stale` issue. |
| 4 | `export INTEL_REFRESH_TOKEN=…` in `.env` | systemd `EnvironmentFile` ignores `export` **silently**. The var never reaches the process, so it falls through to `SIGNAL_ALERT_CRON_TOKEN` — and appears to work, on the wrong secret. |
| 5 | Rotating `SIGNAL_ALERT_CRON_TOKEN` instead | It also authenticates the daily signal-alert digest and the 2-hourly custom-alert sweep (`dynasty-signal-alerts` / `dynasty-custom-alerts` unit templates). Wider blast radius, same restart requirement. |
| 6 | Blanking `SIGNAL_ALERT_CRON_TOKEN` | `deploy/deploy.sh` gates timer installation on `^\s*SIGNAL_ALERT_CRON_TOKEN=.+$`. An empty or malformed line makes the next deploy **silently stop installing** both alert timers, with no error. |

## Places that do NOT need changing

Verified, so nobody goes hunting: no file under `deploy/**` references
`INTEL_REFRESH_TOKEN`; no systemd unit passes it as `Environment=`; nothing
in `src/` reads it; the frontend never sees it. It lives in exactly two
stores — the Actions secret and the prod `.env`.
