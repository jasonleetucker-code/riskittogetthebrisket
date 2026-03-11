#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# Hetzner Server Initial Setup Script
# Run once on a fresh server to configure everything.
#
# Usage (as root on Hetzner):
#   curl -sL <raw-github-url>/deploy/setup-server.sh | bash
#   — or —
#   bash deploy/setup-server.sh
# ──────────────────────────────────────────────────────────────
set -euo pipefail

REPO_URL="git@github.com:jasonleetucker-code/riskittogetthebrisket.git"
APP_DIR="/opt/riskittogetthebrisket"
APP_USER="codexops"
DOMAIN="riskittogetthebrisket.org"

echo "=== [1/7] System packages ==="
apt-get update -qq
apt-get install -y -qq nginx certbot python3-certbot-nginx python3 python3-pip python3-venv git curl

echo "=== [2/7] Create app user ==="
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --create-home --shell /bin/bash "$APP_USER"
    echo "Created user: $APP_USER"
else
    echo "User $APP_USER already exists"
fi

echo "=== [3/7] Clone / update repo ==="
if [ -d "$APP_DIR/.git" ]; then
    echo "Repo exists, pulling latest..."
    cd "$APP_DIR"
    git pull origin main
else
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "=== [4/7] Python dependencies ==="
sudo -u "$APP_USER" pip3 install --user fastapi uvicorn playwright 2>/dev/null || \
    pip3 install fastapi uvicorn playwright --break-system-packages

echo "=== [5/7] Environment file ==="
if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    echo "Created .env from .env.example — edit it with your production values."
    echo "  nano $APP_DIR/.env"
else
    echo ".env already exists, skipping."
fi

echo "=== [6/7] Systemd service ==="
cp "$APP_DIR/deploy/systemd/dynasty-backend.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable dynasty-backend
systemctl restart dynasty-backend
echo "Backend service started. Check: systemctl status dynasty-backend"

echo "=== [7/7] Nginx + SSL ==="
cp "$APP_DIR/deploy/nginx/riskittogetthebrisket.conf" /etc/nginx/sites-available/
ln -sf /etc/nginx/sites-available/riskittogetthebrisket.conf /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
echo "Nginx configured. Now run SSL setup:"
echo "  bash $APP_DIR/deploy/setup-ssl.sh"

echo ""
echo "=== Setup complete ==="
echo "Remaining steps:"
echo "  1. Point DNS A record for $DOMAIN → $(curl -s ifconfig.me)"
echo "  2. Edit $APP_DIR/.env with production values"
echo "  3. Run: bash $APP_DIR/deploy/setup-ssl.sh"
echo "  4. Verify: curl https://$DOMAIN/api/health"
