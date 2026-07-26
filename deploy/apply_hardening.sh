#!/usr/bin/env bash
#
# apply_hardening.sh — idempotent installer for the production-hardening
# set prepared in deploy/ (see docs/PROD-HARDENING.md).
#
#   1. nginx site config      (diff → backup → install → nginx -t → reload;
#                              auto-restores the backup if nginx -t fails)
#   2. dynasty / dynasty-frontend systemd units (re-rendered from the
#                              hardened templates via install-systemd-service.sh)
#   3. dynasty-healthcheck    service + timer   (backend watchdog, 1 min)
#   4. riskit-state-backup    service + timer   (nightly 02:30 UTC)
#   5. riskit-uptime          service + timer   (probe, 5 min)
#
# Safe to re-run: every step diffs current vs. desired and only touches
# what changed.  Nothing here edits .env, credentials, certificates, or
# application data.
#
# Usage (as root on the VPS):
#   sudo bash deploy/apply_hardening.sh            # apply
#   sudo bash deploy/apply_hardening.sh --dry-run  # show diffs only
#
# Env overrides:
#   APP_DIR       default /home/dynasty/trade-calculator
#   APP_USER      default dynasty
#   SERVICE_NAME  default dynasty
#   NGINX_SITE    default riskittogetthebrisket.org

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_DIR="${APP_DIR:-/home/dynasty/trade-calculator}"
[[ -d "${APP_DIR}" ]] || APP_DIR="${DEFAULT_APP_DIR}"
APP_USER="${APP_USER:-dynasty}"
SERVICE_NAME="${SERVICE_NAME:-dynasty}"
NGINX_SITE="${NGINX_SITE:-riskittogetthebrisket.org}"

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

log()  { printf '[apply-hardening] %s\n' "$*"; }
warn() { printf '[apply-hardening][WARN] %s\n' "$*" >&2; }
err()  { printf '[apply-hardening][ERROR] %s\n' "$*" >&2; }

if [[ "${EUID}" -ne 0 ]]; then
    err "must run as root (nginx config + /etc/systemd/system + reloads)."
    err "  sudo bash deploy/apply_hardening.sh"
    exit 1
fi

CHANGED_NGINX=false
CHANGED_UNITS=false
ENABLED_TIMERS=()

show_diff() {
    # diff current(new-arg-order: old new) — never fails the script.
    diff -u "$1" "$2" 2>/dev/null || true
}

# install_unit <src> <dest> [render]
# render=yes rewrites the canonical repo path inside the unit to APP_DIR
# so a non-default checkout location still points at real scripts.
install_unit() {
    local src="$1" dest="$2" render="${3:-no}"
    local staged
    staged="$(mktemp)"
    if [[ "${render}" == "yes" ]]; then
        sed "s|/home/dynasty/trade-calculator|${APP_DIR}|g" "${src}" > "${staged}"
    else
        cp "${src}" "${staged}"
    fi
    if [[ -f "${dest}" ]] && cmp -s "${staged}" "${dest}"; then
        log "up-to-date: ${dest}"
        rm -f "${staged}"
        return 0
    fi
    log "installing: ${dest}"
    show_diff "${dest}" "${staged}"
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "(dry-run) would install ${dest}"
    else
        install -m 0644 "${staged}" "${dest}"
        CHANGED_UNITS=true
    fi
    rm -f "${staged}"
}

enable_timer() {
    local timer="$1"
    ENABLED_TIMERS+=("${timer}")
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "(dry-run) would: systemctl enable --now ${timer}"
    else
        systemctl enable --now "${timer}"
    fi
}

# ── 1. nginx ─────────────────────────────────────────────────────────
apply_nginx() {
    local src="${APP_DIR}/deploy/nginx/${NGINX_SITE}.conf"
    local dest="/etc/nginx/sites-available/${NGINX_SITE}"
    local link="/etc/nginx/sites-enabled/${NGINX_SITE}"

    if ! command -v nginx >/dev/null 2>&1; then
        warn "nginx not installed — skipping nginx step"
        return 0
    fi
    [[ -f "${src}" ]] || { err "missing ${src}"; exit 1; }

    if [[ -f "${dest}" ]] && cmp -s "${src}" "${dest}"; then
        log "nginx config up-to-date: ${dest}"
    else
        log "nginx config differs:"
        show_diff "${dest}" "${src}"
        if [[ "${DRY_RUN}" == "true" ]]; then
            log "(dry-run) would install ${dest}, test, reload"
            return 0
        fi
        local backup=""
        if [[ -f "${dest}" ]]; then
            backup="${dest}.bak.$(date -u +%Y%m%d%H%M%S)"
            cp -p "${dest}" "${backup}"
            log "backed up current config to ${backup}"
        fi
        install -m 0644 "${src}" "${dest}"
        ln -sf "${dest}" "${link}"
        if ! nginx -t; then
            err "nginx -t FAILED with the new config"
            if [[ -n "${backup}" ]]; then
                err "restoring ${backup}"
                cp -p "${backup}" "${dest}"
                nginx -t || err "restored config ALSO fails nginx -t — manual intervention required"
            fi
            exit 1
        fi
        systemctl reload nginx
        CHANGED_NGINX=true
        log "nginx reloaded with hardened config"
    fi

    # Sanity even when unchanged: symlink + config still valid.
    [[ -L "${link}" ]] || { [[ "${DRY_RUN}" == "true" ]] || ln -sf "${dest}" "${link}"; }
    nginx -t >/dev/null 2>&1 || warn "current nginx config fails nginx -t — investigate before next reload"
}

# ── 2. dynasty + dynasty-frontend units from hardened templates ──────
apply_app_services() {
    log "re-rendering ${SERVICE_NAME}/${SERVICE_NAME}-frontend units from templates"
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "(dry-run) would run: FORCE_SERVICE_INSTALL=true deploy/install-systemd-service.sh"
        return 0
    fi
    # install-systemd-service.sh resolves the venv + npm paths itself and
    # writes both units; FORCE ensures the hardened templates land even
    # though the units already exist.  It does NOT restart anything.
    if ! APP_DIR="${APP_DIR}" APP_USER="${APP_USER}" SERVICE_NAME="${SERVICE_NAME}" \
         FORCE_SERVICE_INSTALL=true bash "${APP_DIR}/deploy/install-systemd-service.sh"; then
        err "install-systemd-service.sh failed — app units NOT updated"
        exit 1
    fi
    CHANGED_UNITS=true
}

# ── 3-5. hardening units ─────────────────────────────────────────────
apply_hardening_units() {
    install_unit "${APP_DIR}/deploy/systemd/dynasty-healthcheck.service" \
                 "/etc/systemd/system/dynasty-healthcheck.service" yes
    install_unit "${APP_DIR}/deploy/systemd/dynasty-healthcheck.timer" \
                 "/etc/systemd/system/dynasty-healthcheck.timer"
    install_unit "${APP_DIR}/deploy/backup/riskit-state-backup.service" \
                 "/etc/systemd/system/riskit-state-backup.service" yes
    install_unit "${APP_DIR}/deploy/backup/riskit-state-backup.timer" \
                 "/etc/systemd/system/riskit-state-backup.timer"
    install_unit "${APP_DIR}/deploy/monitoring/riskit-uptime.service" \
                 "/etc/systemd/system/riskit-uptime.service" yes
    install_unit "${APP_DIR}/deploy/monitoring/riskit-uptime.timer" \
                 "/etc/systemd/system/riskit-uptime.timer"

    if [[ "${DRY_RUN}" != "true" ]]; then
        chmod +x "${APP_DIR}/deploy/systemd/dynasty-healthcheck.sh" \
                 "${APP_DIR}/deploy/backup/riskit-state-backup.sh" \
                 "${APP_DIR}/deploy/monitoring/uptime_check.sh" 2>/dev/null || true
    fi
}

apply_nginx
apply_app_services
apply_hardening_units

if [[ "${DRY_RUN}" != "true" && "${CHANGED_UNITS}" == "true" ]]; then
    systemctl daemon-reload
    log "systemd daemon-reload done"
fi
enable_timer dynasty-healthcheck.timer
enable_timer riskit-state-backup.timer
enable_timer riskit-uptime.timer

# ── Verification checklist ───────────────────────────────────────────
cat <<CHECKLIST

════════════════════════════════════════════════════════════════════
 VERIFICATION CHECKLIST — run each step now
════════════════════════════════════════════════════════════════════
 nginx
   [ ] sudo nginx -t                          # syntax OK
   [ ] curl -sSI https://${NGINX_SITE}/ | grep -Ei 'HTTP/|strict-transport|x-content-type'
       → expect HTTP/2 200, HSTS + nosniff headers
   [ ] curl -sSI https://${NGINX_SITE}/api/health
       → 200; Cache-Control comes from the app, NOT nginx
   [ ] curl -sS -H 'Accept-Encoding: gzip' -o /dev/null -w '%{size_download}\n' \\
         https://${NGINX_SITE}/api/data
       → wire size ~100-400 KB (compressed), not ~4 MB
   [ ] curl -sSI https://${NGINX_SITE}/_next/static/<any-chunk>.js
       → Cache-Control: public, max-age=31536000, immutable (from Next)

 systemd services (hardened units land on NEXT restart; restart at a
 quiet moment):
   [ ] systemctl cat ${SERVICE_NAME} | grep -E 'MemoryMax|StartLimit|PrivateTmp'
   [ ] sudo systemctl restart ${SERVICE_NAME}-frontend ${SERVICE_NAME}   # optional now
   [ ] bash ${APP_DIR}/deploy/verify-deploy.sh

 watchdog / timers
   [ ] systemctl list-timers 'dynasty-*' 'riskit-*'   # all three scheduled
   [ ] sudo systemctl start dynasty-healthcheck.service && journalctl -u dynasty-healthcheck -n 5
   [ ] sudo systemctl start riskit-state-backup.service \\
         && sudo tail -n 20 /var/log/riskit-state-backup.log \\
         && sudo ls -la /var/backups/riskit-state/daily/\$(date -u +%F)/
   [ ] sudo systemctl start riskit-uptime.service && sudo tail -n 3 /var/log/riskit-uptime.log

 rollback (if anything misbehaves): docs/PROD-HARDENING.md § Rollback
════════════════════════════════════════════════════════════════════
CHECKLIST

log "done (dry-run=${DRY_RUN}, nginx-changed=${CHANGED_NGINX}, units-changed=${CHANGED_UNITS})"
