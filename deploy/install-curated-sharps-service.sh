#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/home/dynasty/trade-calculator}"
VENV_DIR="${VENV_DIR:-/home/dynasty/.venvs/trade-calculator}"
SERVICE_USER="${SERVICE_USER:-dynasty}"
SERVICE_GROUP="${SERVICE_GROUP:-$SERVICE_USER}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
TEMPLATE_DIR="$APP_DIR/deploy/curated-sharps-systemd"

render() {
  local source="$1" target="$2"
  sed \
    -e "s|__APP_DIR__|$APP_DIR|g" \
    -e "s|__VENV_DIR__|$VENV_DIR|g" \
    -e "s|__SERVICE_USER__|$SERVICE_USER|g" \
    -e "s|__SERVICE_GROUP__|$SERVICE_GROUP|g" \
    "$source" | sudo -n tee "$target" >/dev/null
}

[[ -x "$VENV_DIR/bin/python" ]] || { echo "Missing Python venv: $VENV_DIR" >&2; exit 1; }
[[ -f "$APP_DIR/scripts/refresh_curated_sharps.py" ]] || { echo "Missing refresh script" >&2; exit 1; }

render "$TEMPLATE_DIR/chase-upside-curated-sharps.service.template" \
  "$SYSTEMD_DIR/chase-upside-curated-sharps.service"
render "$TEMPLATE_DIR/chase-upside-curated-sharps.timer.template" \
  "$SYSTEMD_DIR/chase-upside-curated-sharps.timer"

sudo -n systemctl daemon-reload
sudo -n systemctl enable --now chase-upside-curated-sharps.timer

echo "Installed chase-upside-curated-sharps.timer"
