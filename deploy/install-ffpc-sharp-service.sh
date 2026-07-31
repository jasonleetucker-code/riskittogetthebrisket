#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
APP_USER="${APP_USER:-$(id -un)}"
VENV_DIR="${VENV_DIR:-${HOME}/.venvs/$(basename "${APP_DIR}")}"
SERVICE_NAME="${SERVICE_NAME:-dynasty}"
CONFIG="${APP_DIR}/config/sharp/ffpc_sources.json"

if [[ ! -f "${CONFIG}" ]]; then
  echo "[ffpc-install] config missing: ${CONFIG}" >&2
  exit 1
fi
if python3 - "${CONFIG}" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    cfg = json.load(fh)
raise SystemExit(
    0
    if (
        cfg.get("enabled")
        and cfg.get("mode", "public_only") == "public_only"
        and not (cfg.get("authenticatedApi") or {}).get("enabled")
    )
    else 2
)
PY
then
  :
else
  code=$?
  if [[ "${code}" == "2" ]]; then
    echo "[ffpc-install] FFPC is disabled, authenticated access is enabled, or mode is not public_only; no units installed."
    exit 0
  fi
  exit "${code}"
fi

service_template="${APP_DIR}/deploy/ffpc-systemd/chase-upside-ffpc-sharp.service.template"
timer_template="${APP_DIR}/deploy/ffpc-systemd/chase-upside-ffpc-sharp.timer.template"
service_path="/etc/systemd/system/${SERVICE_NAME}-ffpc-sharp.service"
timer_path="/etc/systemd/system/${SERVICE_NAME}-ffpc-sharp.timer"
for file in "${service_template}" "${timer_template}"; do
  [[ -f "${file}" ]] || { echo "[ffpc-install] missing template: ${file}" >&2; exit 1; }
done

escape() { printf '%s' "$1" | sed -e 's/[\\/&]/\\&/g'; }
tmp_service="$(mktemp)"; tmp_timer="$(mktemp)"
trap 'rm -f "${tmp_service}" "${tmp_timer}"' EXIT
sed \
  -e "s/__SERVICE_NAME__/$(escape "${SERVICE_NAME}")/g" \
  -e "s/__APP_USER__/$(escape "${APP_USER}")/g" \
  -e "s#__APP_DIR__#$(escape "${APP_DIR}")#g" \
  -e "s#__VENV_DIR__#$(escape "${VENV_DIR}")#g" \
  "${service_template}" > "${tmp_service}"
sed -e "s/__SERVICE_NAME__/$(escape "${SERVICE_NAME}")/g" \
  "${timer_template}" > "${tmp_timer}"
sudo -n install -m 0644 "${tmp_service}" "${service_path}"
sudo -n install -m 0644 "${tmp_timer}" "${timer_path}"
sudo -n systemctl daemon-reload
sudo -n systemctl enable --now "${SERVICE_NAME}-ffpc-sharp.timer"
echo "[ffpc-install] enabled ${SERVICE_NAME}-ffpc-sharp.timer"
