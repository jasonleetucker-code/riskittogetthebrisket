# Deployment Guide — riskittogetthebrisket.org

## Overview

The site runs on a **Hetzner VPS** with:
- **Backend**: Python FastAPI (systemd service on port 8000)
- **Reverse proxy**: Nginx (ports 80/443 → 8000)
- **SSL**: Let's Encrypt via Certbot (auto-renewing)
- **CI**: GitHub Actions (runs on every push to `main`)
- **CD**: GitHub Actions deploy workflow (manual trigger) or SSH + `deploy.sh`

## Repository

- `origin`: `git@github.com:jasonleetucker-code/riskittogetthebrisket.git`
- Branch: `main`

## First-Time Server Setup

### Prerequisites
- A Hetzner VPS (or any Ubuntu/Debian server) with root SSH access
- DNS A record: `riskittogetthebrisket.org` → your server IP
- DNS A record: `www.riskittogetthebrisket.org` → your server IP

### Automated setup

Run the setup script as root on the server:

```bash
git clone git@github.com:jasonleetucker-code/riskittogetthebrisket.git /opt/riskittogetthebrisket
cd /opt/riskittogetthebrisket
bash deploy/setup-server.sh
```

This installs nginx, Python, creates the `codexops` user, configures the systemd service, and sets up the reverse proxy.

### SSL certificate

After DNS is pointed:

```bash
bash deploy/setup-ssl.sh you@email.com
```

### Environment

Edit `/opt/riskittogetthebrisket/.env` with production values:

```bash
nano /opt/riskittogetthebrisket/.env
```

Key variables — see `.env.example` for the full list.

## Deploying Updates

### Option A: SSH deploy script (quick)

```bash
ssh your-server
bash /opt/riskittogetthebrisket/deploy/deploy.sh          # pull + restart
bash /opt/riskittogetthebrisket/deploy/deploy.sh --full    # + rebuild frontend
```

### Option B: GitHub Actions (from GitHub UI)

1. Go to **Actions** → **Deploy to Production**
2. Click **Run workflow**
3. Optionally check "Rebuild frontend"

Requires these repository secrets:
- `HETZNER_HOST` — server IP or hostname
- `HETZNER_USER` — SSH username (e.g., `codexops`)
- `HETZNER_SSH_KEY` — private SSH key for that user

### Option C: Local push + manual restart

```powershell
.\sync.bat "Your commit message"
# Then SSH in and restart:
ssh your-server "cd /opt/riskittogetthebrisket && git pull origin main && sudo systemctl restart dynasty-backend"
```

## CI Pipeline (GitHub Actions)

Every push to `main` and every PR runs `.github/workflows/ci.yml`:

1. Checkout
2. Python pipeline scripts (ingest → validate → identity → canonical → league → report)
3. Backend smoke test (compile check)
4. API contract validation
5. Frontend build (`npm ci && npm run build`)
6. Playwright regression tests

## Useful Commands (on the server)

```bash
# Service management
sudo systemctl status dynasty-backend
sudo systemctl restart dynasty-backend
sudo journalctl -u dynasty-backend -f    # live logs

# Nginx
sudo nginx -t                            # test config
sudo systemctl reload nginx

# SSL
sudo certbot renew --dry-run             # test renewal
sudo certbot certificates                # check expiry

# Health check
curl https://riskittogetthebrisket.org/api/health
```

## Verification Checklist

You're fully deployed when:
- [ ] DNS A records point to server IP
- [ ] `curl https://riskittogetthebrisket.org/api/health` returns OK
- [ ] `systemctl is-active dynasty-backend` returns `active`
- [ ] GitHub Actions CI passes on `main`
- [ ] SSL certificate is valid (`certbot certificates`)
