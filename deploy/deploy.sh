#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# Deploy latest code to production
# Run this on the Hetzner server after pushing changes to main.
#
# Usage:
#   bash deploy/deploy.sh              # pull + restart backend
#   bash deploy/deploy.sh --full       # pull + rebuild frontend + restart
# ──────────────────────────────────────────────────────────────
set -euo pipefail

APP_DIR="/opt/riskittogetthebrisket"
SERVICE="dynasty-backend"
FULL_BUILD=false

if [ "${1:-}" = "--full" ]; then
    FULL_BUILD=true
fi

cd "$APP_DIR"

echo "=== Pulling latest from origin/main ==="
git fetch origin main
git reset --hard origin/main

echo "=== Running pipeline scripts ==="
for script in source_pull validate_ingest identity_resolve canonical_build league_refresh reporting; do
    SCRIPT_PATH="scripts/${script}.py"
    if [ -f "$SCRIPT_PATH" ]; then
        echo "  Running $SCRIPT_PATH..."
        python3 "$SCRIPT_PATH" --repo . || echo "  WARNING: $SCRIPT_PATH failed (non-fatal)"
    fi
done

if [ "$FULL_BUILD" = true ]; then
    echo "=== Rebuilding frontend ==="
    cd frontend
    npm ci
    npm run build
    cd ..
fi

echo "=== Restarting backend service ==="
systemctl restart "$SERVICE"
sleep 2

if systemctl is-active --quiet "$SERVICE"; then
    echo "=== Deploy complete — $SERVICE is running ==="
else
    echo "=== WARNING: $SERVICE failed to start ==="
    journalctl -u "$SERVICE" --no-pager -n 20
    exit 1
fi

echo "=== Health check ==="
sleep 3
curl -sf http://127.0.0.1:8000/api/health && echo " OK" || echo " FAILED"
