# Domain cutover — `chaseupside.com`

Puts production behind `https://chaseupside.com` with a Let's Encrypt
certificate. Today the site is served over plain HTTP with **no TLS**,
so login credentials cross the network in the clear; that is what this
fixes.

| Tag | Where |
|---|---|
| **[VPS]** | shell on the production box, as a user with `sudo` |
| **[GITHUB]** | github.com → repo → Settings, or the Actions tab |
| **[LOCAL]** | a shell that is **not** on the VPS — a laptop. Used wherever a check must come from a second vantage point; running it on the box can pass via loopback or NAT hairpin while the public path is broken |

Run the steps in order. Each states its precondition and a checkpoint
saying what "good" looks like. Paste output back before moving on.

---

## Starting state this runbook assumes

Confirm all four before starting. If any is false, stop — the steps
below are written against this exact state and not a fresh box.

1. `/etc/nginx/sites-enabled/dynasty` is a **symlink** into
   `/etc/nginx/sites-available/dynasty`.
2. That file's `server_name` has already been widened by hand to
   `169.58.50.224 chaseupside.com www.chaseupside.com`.
3. `http://chaseupside.com/` therefore already serves the app over
   plain HTTP.
4. There is no certificate for `chaseupside.com` yet.

```bash
ls -l /etc/nginx/sites-enabled/
grep -n 'server_name' /etc/nginx/sites-available/dynasty
curl -sS -o /dev/null -w '%{http_code}\n' http://chaseupside.com/api/health
sudo ls /etc/letsencrypt/live/ 2>/dev/null || echo "(no certs yet)"
```

> **Checkpoint.** `dynasty` is a symlink; `server_name` lists the IP and
> both hostnames; the curl returns `200`; no `chaseupside.com` directory
> under `/etc/letsencrypt/live/`.

### Two PRs, deliberately

`deploy.yml` triggers on **`push` to `main`** — merging *is* deploying.
That is why the work is split:

* **PR A** (nginx config, this runbook, docs) — safe to merge at any
  time. Merging it deploys, and that deploy is how the config files
  reach the box.
* **PR B** (repoints the uptime probe, alert-email links, Grafana URL,
  `robots.txt` origin at `https://chaseupside.com`) — **must not merge
  until the certificate exists**. Merging it early would deploy an
  uptime probe aimed at a host that cannot answer, and the watchdog
  would start firing false DOWN alerts during the cutover — exactly
  when a real alert must not be lost in noise.

---

## Step 0 — [VPS] Record the rollback baseline

**Precondition:** none. Do this first; it is what makes step 12 possible.

```bash
ls -l /etc/nginx/sites-enabled/
sudo tar czf "/root/nginx-backup-$(date -u +%Y%m%dT%H%M%SZ).tar.gz" /etc/nginx
ls -lh /root/nginx-backup-*.tar.gz
```

> **Checkpoint.** A timestamped tarball exists. Note which site files are
> enabled — `dynasty` plus possibly Debian's `default`.

---

## Step 0b — [GITHUB] Check `PROD_PUBLIC_URL` **now** (independent of this cutover)

Settings → Secrets and variables → Actions → **Variables** →
`PROD_PUBLIC_URL`. Just read it; do not change it yet.

This is urgent on its own schedule, not because of the cutover.
`.github/workflows/intel-refresh.yml` runs on a **cron** and sends
`Authorization: Bearer ${INTEL_REFRESH_TOKEN}` to whatever host this
variable names. If it currently holds the lapsed
`riskittogetthebrisket.org` — which now resolves to a third party — then
that token is being handed to them on every scheduled run, which is the
failure that already happened once today.

> **If it names any host we do not control, clear the variable right
> now.** The workflows fail loudly on an empty value by design; a red
> workflow is strictly better than a leaked token. Then continue — you
> will set the real value at step 9.

---

## Step 1 — [LOCAL] Verify DNS for apex **and** `www`

**Precondition:** none.

The domain already answers over HTTP, so the apex clearly resolves. The
one that has not been proven is `www`, and it matters: the certificate
requests `www` as a SAN, and Let's Encrypt fails the **whole** issuance
if any requested name fails validation.

```bash
dig +short chaseupside.com
dig +short www.chaseupside.com
dig +short @1.1.1.1 www.chaseupside.com
```

> **Checkpoint.** All three print `169.58.50.224`.
>
> If `www` prints nothing, either add the DNS record and wait, or drop
> `www` from the certificate — but decide now, because changing your
> mind later means re-issuing. To drop it, omit `-d www.chaseupside.com`
> at step 5 and delete `www.chaseupside.com` from the two `server_name`
> lines in `chaseupside.com.conf` before step 6.

---

## Step 2 — [GITHUB] Merge PR A

**Precondition:** none.

Merging pushes to `main`, which triggers **Deploy**. That deploy is how
`deploy/nginx/chaseupside.com.conf` and
`deploy/nginx/chaseupside-proxy.conf` get onto the box.

PR A touches only nginx config files, docs, and two comment lines in
`frontend/app/api/*/route.js`. Nothing the running app reads changes.
The comment change does cause a frontend rebuild, which `deploy.sh`
performs into a staging directory and swaps atomically — no meaningful
downtime, but do not be surprised by the rebuild.

> **Checkpoint.** The Deploy workflow is green, and the files are on the
> box:
> ```bash
> ls -l /home/dynasty/trade-calculator/deploy/nginx/chaseupside*.conf
> ```
>
> If Deploy's "Post-deploy smoke test" step is the only thing red, check
> what `PROD_PUBLIC_URL` points at (step 0b) — that step probes it, and
> a stale value fails there without affecting the deploy itself.

---

## Step 3 — [VPS] Serve the ACME challenge path

**Precondition:** step 2 green.

We issue with the **webroot** plugin, not `--nginx`. The `--nginx`
plugin rewrites the installed config in place, and this repo keeps nginx
config under version control — `deploy/apply_hardening.sh` diffs the
installed file against the checked-in copy and reinstalls the repo
version when they differ, which would revert certbot's edits. That
script is not wired into any workflow and `deploy.sh` does not touch
nginx, so the risk is **manual-only**: it bites if someone runs
`apply_hardening.sh` by hand. Webroot sidesteps it by never touching
nginx config at all.

Create the webroot and the cache directory the new config needs:

```bash
sudo mkdir -p /var/www/certbot/.well-known/acme-challenge
sudo mkdir -p /var/cache/nginx
sudo chown -R www-data:www-data /var/www/certbot
echo ok | sudo tee /var/www/certbot/.well-known/acme-challenge/ping >/dev/null
```

The live config proxies `/` to Next.js, so the challenge path would be
proxied and 404. Add the challenge location to the **live** file. Check
the anchor first:

```bash
grep -c 'client_max_body_size 25m;' /etc/nginx/sites-available/dynasty
```

> **Checkpoint.** Prints `1`. If it prints `0` or more than `1`, stop —
> insert the location block by hand instead of running the `sed` below.

```bash
sudo sed -i.bak-acme '/client_max_body_size 25m;/a\
\
    location ^~ /.well-known/acme-challenge/ {\
        root /var/www/certbot;\
        default_type "text/plain";\
    }' /etc/nginx/sites-available/dynasty

sed -n '/server_name/,/location \/api\//p' /etc/nginx/sites-available/dynasty
sudo nginx -t
```

> **Checkpoint.** The printed excerpt shows the new
> `location ^~ /.well-known/acme-challenge/` block sitting before
> `location /api/`, and `nginx -t` prints `test is successful`. A
> backup of the original is at
> `/etc/nginx/sites-available/dynasty.bak-acme`.
>
> **If `nginx -t` fails, restore and stop:**
> `sudo cp /etc/nginx/sites-available/dynasty.bak-acme /etc/nginx/sites-available/dynasty`

```bash
sudo systemctl reload nginx
```

---

## Step 4 — [LOCAL] Verify the challenge path from outside

**Precondition:** step 3 reloaded cleanly.

Run from a laptop. This is the exact request Let's Encrypt will make.

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://chaseupside.com/.well-known/acme-challenge/ping
curl -sS http://chaseupside.com/.well-known/acme-challenge/ping
```

> **Checkpoint.** `200` then `ok`.
>
> A `404` means the location did not take effect — re-check step 3. A
> connection timeout means something upstream of nginx is blocking :80
> from outside; check the provider's firewall as well as `ufw status`.

---

## Step 5 — [VPS] Issue the certificate

**Precondition:** step 4 checkpoint green.

Dry run first — it exercises the real validation flow without consuming
the production rate limit (5 failed validations per hostname per hour):

```bash
sudo certbot certonly --webroot -w /var/www/certbot \
  -d chaseupside.com -d www.chaseupside.com \
  --dry-run
```

> **Checkpoint.** `The dry run was successful.` If it fails, fix the
> cause and re-run the dry run — do not "try the real one and see".

Issue for real. Replace `you@example.com` with the operator's address
(it receives expiry warnings):

```bash
sudo certbot certonly --webroot -w /var/www/certbot \
  -d chaseupside.com -d www.chaseupside.com \
  --email you@example.com \
  --agree-tos --no-eff-email \
  --deploy-hook "systemctl reload nginx"
```

`--deploy-hook` matters: with webroot, certbot knows nothing about
nginx, so without it a renewed certificate would sit on disk unused and
the site would eventually serve an expired one. The hook is recorded in
the renewal config and runs on every future renewal.

```bash
sudo ls -l /etc/letsencrypt/live/chaseupside.com/
ls -l /etc/letsencrypt/options-ssl-nginx.conf /etc/letsencrypt/ssl-dhparams.pem
```

> **Checkpoint.** `fullchain.pem` and `privkey.pem` exist, **and** so do
> the two shared files on the second line — the new config `include`s
> the first and references the second, so a missing one fails `nginx -t`
> at step 6. They may be absent on a webroot-only box. Create them with:
> ```bash
> sudo curl -fsS -o /etc/letsencrypt/options-ssl-nginx.conf \
>   https://raw.githubusercontent.com/certbot/certbot/main/certbot-nginx/certbot_nginx/_internal/tls_configs/options-ssl-nginx.conf
> sudo openssl dhparam -out /etc/letsencrypt/ssl-dhparams.pem 2048
> ```
> (the dhparam generation takes a minute or two).

---

## Step 6 — [VPS] Swap in the new config

**Precondition:** step 5 checkpoint green — the certificate exists.

The new config **replaces** the `dynasty` site rather than joining it.
Both declare `upstream dynasty_backend` / `dynasty_frontend`, and both
now claim `chaseupside.com`, so having both enabled fails `nginx -t`
with a duplicate-upstream error. That is intentional: it fails loudly at
test time instead of silently letting two server blocks fight over a
hostname. Keep the swap atomic.

```bash
APPDIR=/home/dynasty/trade-calculator

sudo mkdir -p /etc/nginx/snippets
sudo install -m 0644 "$APPDIR/deploy/nginx/chaseupside-proxy.conf" \
     /etc/nginx/snippets/chaseupside-proxy.conf
sudo install -m 0644 "$APPDIR/deploy/nginx/chaseupside.com.conf" \
     /etc/nginx/sites-available/chaseupside.com

# Atomic swap: dynasty out, chaseupside.com in.
sudo rm -f /etc/nginx/sites-enabled/dynasty
sudo ln -sf /etc/nginx/sites-available/chaseupside.com /etc/nginx/sites-enabled/

ls -l /etc/nginx/sites-enabled/
sudo nginx -t
```

> **Checkpoint.** `sites-enabled/` lists `chaseupside.com` and **not**
> `dynasty`, and `nginx -t` prints `test is successful`.
>
> **If `nginx -t` fails, do not reload.** Put the old symlink straight
> back and paste the error:
> ```bash
> sudo rm -f /etc/nginx/sites-enabled/chaseupside.com
> sudo ln -sf /etc/nginx/sites-available/dynasty /etc/nginx/sites-enabled/
> sudo nginx -t && sudo systemctl reload nginx
> ```

```bash
sudo systemctl reload nginx
```

`/etc/nginx/sites-available/dynasty` stays on disk. Removing the symlink
disables it; deleting the file would remove the rollback target.

---

## Step 7 — [LOCAL] Verify TLS, the redirect, and the bare IP

**Precondition:** step 6 reloaded cleanly. Run all of this from a laptop.

Port 80 on the domain must redirect:

```bash
curl -sI http://chaseupside.com/ | head -5
curl -sI http://www.chaseupside.com/ | head -5
```

> **Checkpoint.** `301` with `Location: https://chaseupside.com/`
> (respectively `https://www.…`).

HTTPS must answer with a valid chain:

```bash
curl -sI https://chaseupside.com/ | head -8
curl -sS https://chaseupside.com/api/health | head -c 400; echo
```

> **Checkpoint.** `HTTP/2 200`, a
> `strict-transport-security: max-age=31536000` header, and a health
> body with `"status":"ok"`. `curl` validates the chain by default, so a
> cert error here is a hard failure, not a warning.

**The bare IP must still work over plain HTTP** — monitoring and the
alert-email links still point at it until PR B deploys:

```bash
curl -sI http://169.58.50.224/ | head -3
curl -sS -o /dev/null -w '%{http_code}\n' http://169.58.50.224/api/health
```

> **Checkpoint.** `200` on both, and **no `301`**. If the IP redirects to
> HTTPS, the transitional IP server block is missing or not matching —
> every monitoring probe would fail the TLS handshake against a
> certificate that cannot cover an IP address. Stop and fix before
> continuing.

Certificate contents:

```bash
echo | openssl s_client -connect chaseupside.com:443 -servername chaseupside.com 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
```

> **Checkpoint.** `notAfter` ~90 days out, issuer Let's Encrypt, and
> `subjectAltName` lists **both** names (unless you deliberately dropped
> `www` at step 1).

Spot-check the routes with special handling, so a dropped location block
surfaces now rather than in a user report:

```bash
for p in / /api/health /api/public/league /favicon.ico; do
  printf '%-24s %s\n' "$p" "$(curl -sS -o /dev/null -w '%{http_code}' --max-time 45 "https://chaseupside.com$p")"
done
```

> **Checkpoint.** All `200`. `/api/public/league` can be slow on a cold
> snapshot; the 45s timeout covers it.

Confirm a `/_next/static/` asset still serves (this location is new
relative to the live config, so it is worth one look):

```bash
ASSET=$(curl -sS https://chaseupside.com/ | grep -o '/_next/static/[^"]*\.js' | head -1)
echo "asset: $ASSET"
curl -sI "https://chaseupside.com${ASSET}" | head -6
```

> **Checkpoint.** `200` with `cache-control: public, max-age=31536000,
> immutable` passed through from Next.js.

---

## Step 8 — [VPS] Confirm auto-renewal is armed

**Precondition:** step 7 green.

```bash
systemctl list-timers | grep -i certbot
```

> **Checkpoint.** A `certbot.timer` line with a `NEXT` time. If nothing
> prints:
> ```bash
> sudo systemctl enable --now certbot.timer
> systemctl list-timers | grep -i certbot
> ```
> Some images use a cron entry instead — check `ls -l /etc/cron.d/certbot`.
> Either is fine, but one must exist.

```bash
sudo certbot renew --dry-run
sudo grep -nE 'renew_hook|webroot_path' /etc/letsencrypt/renewal/chaseupside.com.conf
```

> **Checkpoint.** `Congratulations, all simulated renewals succeeded`
> naming `chaseupside.com`, plus
> `renew_hook = systemctl reload nginx` and
> `webroot_path = /var/www/certbot`.
>
> This is the step that proves renewal works through the **new** config,
> not just the temporary ACME location the cert was issued under. If
> `renew_hook` is missing, add it under `[renewalparams]` and re-run the
> dry run.

---

## Step 9 — [GITHUB] Set `PROD_PUBLIC_URL`

**Precondition:** step 7 green — `https://chaseupside.com/api/health`
returns 200.

Settings → Secrets and variables → Actions → **Variables**. Set to
exactly:

```
https://chaseupside.com
```

No trailing slash. Six workflows read this — `deploy.yml`,
`health-check.yml`, `intel-refresh.yml`, `prod-e2e-smoke.yml`,
`public-league-warmup.yml`, `smoke-test.yml` — and `intel-refresh.yml`
sends a bearer token to it (see step 0b). Confirm the value resolves to
`169.58.50.224` before saving.

Verify with a read-only run: Actions → **Health Check** → *Run workflow*.

> **Checkpoint.** Green, and the log shows it probing
> `https://chaseupside.com`.

---

## Step 10 — [VPS] Update `.env`

**Precondition:** step 7 green — HTTPS actually works.

Edit `/home/dynasty/trade-calculator/.env`.

**10a. `JASON_AUTH_COOKIE_SECURE` — the one that closes the credential
exposure.**

```bash
sudo grep '^JASON_AUTH_COOKIE_SECURE=' /home/dynasty/trade-calculator/.env
```

(prints one non-secret boolean line, not the file). Set it to:

```
JASON_AUTH_COOKIE_SECURE=true
```

`server.py` sets the session cookie with `secure=JASON_AUTH_COOKIE_SECURE`.
A `Secure` cookie is not stored by browsers over plain HTTP, so while
the site was HTTP-only this had to be `false` for login to work at all —
which is exactly why credentials have been travelling in the clear.

> Set this **only after** step 7 passed. On plain HTTP it locks everyone
> out of login: the browser silently discards the cookie and every
> request comes back unauthenticated.

No `domain` attribute is set on the cookie, so it is host-only for
`chaseupside.com` — correct, nothing to change. `SameSite=lax` is
correct for a same-origin app; leave it.

**10b. `PUBLIC_SITE_URL`.**

```
PUBLIC_SITE_URL=https://chaseupside.com
```

Use `PUBLIC_SITE_URL`, **not** `NEXT_PUBLIC_SITE_URL`, even though
`robots.js` / `sitemap.js` check the `NEXT_PUBLIC_` name first.
`NEXT_PUBLIC_*` is inlined by Next.js at **build** time and
`deploy/deploy.sh` runs `npm run build` without sourcing `.env`, so a
value set here would inline as `undefined`. `PUBLIC_SITE_URL` is read
from the process environment at runtime, which the frontend systemd unit
supplies via `EnvironmentFile=-…/.env`.

**10c. `UPTIME_CHECK_URL`** — only if the line exists:

```bash
sudo grep '^UPTIME_CHECK_URL=' /home/dynasty/trade-calculator/.env
```

```
UPTIME_CHECK_URL=https://chaseupside.com/api/health
```

If absent, leave it — PR B updates the code default.

```bash
sudo systemctl restart dynasty dynasty-frontend
```

> **Checkpoint.** Log in through a browser at `https://chaseupside.com/`
> and confirm the session survives a page reload. That is the real test
> of 10a. If you are bounced back to the login screen, revert 10a to
> `false`, restart, and investigate before continuing.

---

## Step 11 — [GITHUB] Merge PR B

**Precondition:** steps 7, 9 and 10 all green.

PR B repoints the uptime probe, the alert-email links, the Grafana
dashboard JSON and the `robots.txt` / `sitemap.xml` origin at
`https://chaseupside.com`. Merging deploys it.

> **Checkpoint.** Deploy is green, including "Post-deploy smoke test"
> and "Validate live data contract" — both now exercising the new
> domain.

```bash
curl -sS https://chaseupside.com/robots.txt
```

> **Checkpoint.** The `Sitemap:` line reads
> `https://chaseupside.com/sitemap.xml`.

```bash
systemctl cat riskit-uptime.service | grep -i 'SITE_URL' || echo "(no SITE_URL override — code default applies)"
sudo systemctl start riskit-uptime.service
sudo tail -n 5 /var/log/riskit-uptime.log
```

> **Checkpoint.** The probe line shows `https://chaseupside.com` targets
> returning `200`. If a drop-in pins `SITE_URL` to the old value it wins
> over the code default — remove it with
> `sudo systemctl edit riskit-uptime.service`.

---

## Step 12 — Rollback

**12a. [VPS] nginx will not validate, or the site is down.**

```bash
sudo rm -f /etc/nginx/sites-enabled/chaseupside.com
sudo ln -sf /etc/nginx/sites-available/dynasty /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
curl -sS -o /dev/null -w '%{http_code}\n' http://169.58.50.224/api/health
```

> Expect `200`. The site is back exactly as it was, including
> `http://chaseupside.com` over plain HTTP, because the `dynasty` file
> still carries the widened `server_name`.

If the config tree itself is in a bad state, restore the tarball from
step 0:

```bash
sudo tar xzf /root/nginx-backup-<TIMESTAMP>.tar.gz -C /
sudo nginx -t && sudo systemctl reload nginx
```

`deploy/nginx/riskittogetthebrisket.org.conf` is **not** a rollback
target — we do not own that domain and its `ssl_certificate` paths do
not exist, so enabling it fails `nginx -t`. It is retained only as the
historical reference copy.

The issued certificate does no harm after a rollback; leave it and reuse
it on the next attempt. To remove it:
`sudo certbot delete --cert-name chaseupside.com`.

**If you already completed step 10a, undo it.** A rollback puts the site
on plain HTTP, and `JASON_AUTH_COOKIE_SECURE=true` there means browsers
discard the session cookie and nobody can log in — with a symptom
(bounced to login, no error) that looks nothing like an nginx rollback:

```bash
sudo sed -i 's/^JASON_AUTH_COOKIE_SECURE=true$/JASON_AUTH_COOKIE_SECURE=false/' \
     /home/dynasty/trade-calculator/.env
sudo grep '^JASON_AUTH_COOKIE_SECURE=' /home/dynasty/trade-calculator/.env
sudo systemctl restart dynasty
```

> Set it back to `true` the moment HTTPS works again — it is the setting
> that has been exposing credentials.

**12b. [GITHUB] A deploy is bad.**

Actions → **Deploy** → *Run workflow* with `deploy_ref` set to the last
known-good commit and `allow_non_fast_forward=true` (required — the
workflow blocks backwards deploys by default). Or run
`deploy/rollback.sh` on the box.

**12c. [GITHUB] Abandoning the cutover.**

Clear `PROD_PUBLIC_URL` rather than pointing it back at the old domain.
The workflows fail loudly on an empty value; that is intended, and far
safer than sending a bearer token to a host we do not control.

---

## After the cutover

- **Remove the transitional bare-IP server block** from
  `chaseupside.com.conf` once nothing calls the IP any more. Check with
  `grep -rn '169\.58\.50\.224'` on the repo and by looking for
  `Host: 169.58.50.224` in `/var/log/nginx/access.log`. Removing it
  earlier breaks monitoring; leaving it forever keeps an unencrypted
  entrance open.
- **Grafana**: the dashboard JSON is updated by PR B, but a dashboard
  already imported keeps its own saved `metrics_url`. Update it in
  Dashboard settings → Variables, or re-import.
- **Remove the temporary ACME location** from
  `/etc/nginx/sites-available/dynasty` if you ever re-enable that file —
  the new config has its own. The pre-edit backup is at
  `dynasty.bak-acme`.
- **HSTS `includeSubDomains` / preload**: deliberately not enabled. Add
  only after every subdomain of `chaseupside.com` serves valid TLS —
  mistakes lock browsers out for the full `max-age` (one year).
- **Product naming**: the app still says "Risk It To Get The Brisket" in
  titles, the PWA manifest, OG cards and alert copy. Inventoried in
  PR A's description; a separate change.
