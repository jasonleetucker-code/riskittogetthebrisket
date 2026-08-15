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
#   NGINX_SITE    default dynasty  (nginx sites-available filename;
#                 was a domain until that domain was lost — the site is
#                 served on a bare IP until a new domain is registered)

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_DIR="${APP_DIR:-/home/dynasty/trade-calculator}"
[[ -d "${APP_DIR}" ]] || APP_DIR="${DEFAULT_APP_DIR}"
APP_USER="${APP_USER:-dynasty}"
SERVICE_NAME="${SERVICE_NAME:-dynasty}"
NGINX_SITE="${NGINX_SITE:-dynasty}"
# Root-owned install location for scripts that systemd runs AS ROOT.
# They must NOT execute from the deploy-user-writable checkout — that
# would let a compromised deploy account swap a script and get root on
# the next timer fire.  Overridable for testing (RISKIT_LIB_DIR=...).
RISKIT_LIB_DIR="${RISKIT_LIB_DIR:-/usr/local/lib/riskit}"

# VENV_DIR must be derived from the APP_USER's home, NOT from $HOME:
# under the documented `sudo bash` invocation HOME=/root, and
# install-systemd-service.sh's own default (${HOME}/.venvs/<slug>)
# would render dynasty.service against /root/.venvs/... — a
# nonexistent interpreter that takes the backend down on the next
# restart.  getent keeps this correct for any APP_USER override.
if [[ -z "${VENV_DIR:-}" ]]; then
    APP_USER_HOME="$(getent passwd "${APP_USER}" | cut -d: -f6)"
    if [[ -z "${APP_USER_HOME}" ]]; then
        printf '[apply-hardening][ERROR] cannot resolve home directory for APP_USER=%s\n' "${APP_USER}" >&2
        exit 1
    fi
    VENV_DIR="${APP_USER_HOME}/.venvs/$(basename "${APP_DIR}")"
fi

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
# render=yes rewrites the canonical paths/names inside the unit for
# non-default installs: checkout path → APP_DIR, root-script dir →
# RISKIT_LIB_DIR, the watchdog's HEALTH_SERVICE → SERVICE_NAME, and
# User/Group=dynasty → APP_USER (each pattern is a no-op in units that
# don't contain it).
install_unit() {
    local src="$1" dest="$2" render="${3:-no}"
    local staged
    staged="$(mktemp)"
    if [[ "${render}" == "yes" ]]; then
        sed -e "s|/home/dynasty/trade-calculator|${APP_DIR}|g" \
            -e "s|/usr/local/lib/riskit|${RISKIT_LIB_DIR}|g" \
            -e "s|HEALTH_SERVICE=dynasty|HEALTH_SERVICE=${SERVICE_NAME}|g" \
            -e "s|^User=dynasty$|User=${APP_USER}|" \
            -e "s|^Group=dynasty$|Group=${APP_USER}|" \
            "${src}" > "${staged}"
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
            else
                # First install: there is no known-good config to fall
                # back to.  Leaving the invalid file + enabled symlink
                # armed would fail the NEXT nginx restart/reboot, so
                # remove both — nginx keeps running on whatever it had.
                err "first install (no backup) — removing invalid ${dest} and ${link} so a later nginx restart cannot pick them up"
                rm -f "${dest}" "${link}"
            fi
            exit 1
        fi
        systemctl reload nginx
        CHANGED_NGINX=true
        log "nginx reloaded with hardened config"
    fi

    # Sanity even when unchanged: the enabled symlink must exist AND
    # resolve to our destination — a stale/renamed/broken link would
    # keep nginx serving the wrong config while this script reports
    # up-to-date.  Fixing the link changes what nginx WILL serve, so it
    # gets the same validate-then-reload as the main install path;
    # without the reload the running nginx would keep serving its
    # previously loaded config while the installer reports completion.
    local link_target prev_raw
    link_target="$(readlink -f "${link}" 2>/dev/null || true)"
    if [[ "${link_target}" != "${dest}" ]]; then
        warn "sites-enabled symlink wrong (resolves to '${link_target:-<missing>}', want '${dest}') — fixing"
        if [[ "${DRY_RUN}" == "true" ]]; then
            log "(dry-run) would recreate ${link}, then nginx -t + reload nginx"
        else
            # Remember the exact previous link state (raw target, not
            # resolved) so a failed validation restores it verbatim.
            prev_raw="$(readlink "${link}" 2>/dev/null || true)"
            ln -sf "${dest}" "${link}"
            if ! nginx -t; then
                err "nginx -t FAILED after repairing the sites-enabled symlink"
                if [[ -n "${prev_raw}" ]]; then
                    err "restoring previous link state: ${link} -> ${prev_raw}"
                    ln -sf "${prev_raw}" "${link}"
                else
                    err "removing ${link} (no link existed before the repair)"
                    rm -f "${link}"
                fi
                exit 1
            fi
            systemctl reload nginx
            CHANGED_NGINX=true
            log "nginx reloaded after sites-enabled symlink repair"
        fi
    fi
    nginx -t >/dev/null 2>&1 || warn "current nginx config fails nginx -t — investigate before next reload"
}

# ── 2. dynasty + dynasty-frontend units from hardened templates ──────
apply_app_services() {
    # Pre-flight: never rewrite the backend unit to point at an
    # interpreter that does not exist (that is a guaranteed outage on
    # the next restart).
    if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
        err "pre-flight FAILED: ${VENV_DIR}/bin/python does not exist or is not executable."
        err "Refusing to rewrite ${SERVICE_NAME}.service against a missing interpreter."
        err "Set VENV_DIR explicitly if the venv lives elsewhere."
        exit 1
    fi
    log "pre-flight OK: ${VENV_DIR}/bin/python exists"
    log "re-rendering ${SERVICE_NAME}/${SERVICE_NAME}-frontend units from templates"
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "(dry-run) would run: FORCE_SERVICE_INSTALL=true VENV_DIR=${VENV_DIR} deploy/install-systemd-service.sh"
        return 0
    fi
    # install-systemd-service.sh resolves the npm path itself and writes
    # both units; FORCE ensures the hardened templates land even though
    # the units already exist.  It does NOT restart anything.  VENV_DIR
    # is passed explicitly — see the derivation note at the top.
    if ! APP_DIR="${APP_DIR}" APP_USER="${APP_USER}" SERVICE_NAME="${SERVICE_NAME}" \
         VENV_DIR="${VENV_DIR}" \
         FORCE_SERVICE_INSTALL=true bash "${APP_DIR}/deploy/install-systemd-service.sh"; then
        err "install-systemd-service.sh failed — app units NOT updated"
        exit 1
    fi
    CHANGED_UNITS=true
}

# ── 3a. root-owned copies of root-run scripts ────────────────────────
# dynasty-healthcheck.sh and riskit-state-backup.sh execute as root
# (systemctl restart / /var/backups + /var/lib reads), so their units
# point at ${RISKIT_LIB_DIR} — root:root 0755, outside the checkout.
# Updates flow through re-running this installer; editing the checkout
# copy alone changes nothing at runtime.  The uptime probe is NOT
# installed here: it runs unprivileged (User=dynasty) from the
# checkout, which is fine because it has no more privilege than the
# user who can already edit it.
# THE canonical state-backup installation lives in its own file so that the
# deploy account can run it WITHOUT a root shell — measured 2026-08-15, this
# host's NOPASSWD sudo covers systemctl/journalctl/install/chown and not bash,
# so `sudo bash apply_hardening.sh` cannot run here at all. Sourced rather than
# re-implemented: two copies of "which files, in which order, with which modes"
# drift, and drift here means a writer installed without its library.
# shellcheck source=deploy/backup/install_state_backup.sh
source "${APP_DIR}/deploy/backup/install_state_backup.sh"

install_priv_script() {
    local src="$1"
    local mode="${2:-0755}"
    local dest="${RISKIT_LIB_DIR}/$(basename "$1")"
    if [[ -f "${dest}" ]] && cmp -s "${src}" "${dest}"; then
        log "up-to-date: ${dest}"
        return 0
    fi
    log "installing root-owned script: ${dest}"
    show_diff "${dest}" "${src}"
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "(dry-run) would install ${dest} (root:root ${mode})"
    else
        install -o root -g root -m "${mode}" -D "${src}" "${dest}"
    fi
}

apply_privileged_scripts() {
    install_priv_script "${APP_DIR}/deploy/systemd/dynasty-healthcheck.sh"
    # The state-backup pair — library first, modes, destinations — is owned by
    # deploy/backup/install_state_backup.sh and called, not copied. That file
    # documents why the ordering is load-bearing.
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "(dry-run) would install the state-backup library + writer into ${RISKIT_LIB_DIR}"
    else
        state_backup_install_scripts "${APP_DIR}" "${RISKIT_LIB_DIR}"
    fi
}

# ── 3-5. hardening units ─────────────────────────────────────────────
apply_hardening_units() {
    install_unit "${APP_DIR}/deploy/systemd/dynasty-healthcheck.service" \
                 "/etc/systemd/system/dynasty-healthcheck.service" yes
    install_unit "${APP_DIR}/deploy/systemd/dynasty-healthcheck.timer" \
                 "/etc/systemd/system/dynasty-healthcheck.timer"
    # Same owner as above — see deploy/backup/install_state_backup.sh.
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "(dry-run) would install ${STATE_BACKUP_SERVICE} + ${STATE_BACKUP_TIMER}"
    else
        state_backup_install_units "${APP_DIR}" "${RISKIT_LIB_DIR}"
        CHANGED_UNITS=true
    fi
    install_unit "${APP_DIR}/deploy/monitoring/riskit-uptime.service" \
                 "/etc/systemd/system/riskit-uptime.service" yes
    install_unit "${APP_DIR}/deploy/monitoring/riskit-uptime.timer" \
                 "/etc/systemd/system/riskit-uptime.timer"

    if [[ "${DRY_RUN}" != "true" ]]; then
        # Only the unprivileged probe runs from the checkout; the two
        # root-run scripts execute from ${RISKIT_LIB_DIR} (see above).
        chmod +x "${APP_DIR}/deploy/monitoring/uptime_check.sh" 2>/dev/null || true
    fi
}

apply_nginx
apply_app_services
apply_privileged_scripts
apply_hardening_units

if [[ "${DRY_RUN}" != "true" && "${CHANGED_UNITS}" == "true" ]]; then
    systemctl daemon-reload
    log "systemd daemon-reload done"
fi
enable_timer dynasty-healthcheck.timer
enable_timer "${STATE_BACKUP_TIMER}"
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
   [ ] ls -la ${RISKIT_LIB_DIR}/   # root:root 0755 healthcheck + backup scripts
   [ ] systemctl cat dynasty-healthcheck riskit-state-backup | grep ExecStart
       → both point at ${RISKIT_LIB_DIR}, NOT the checkout
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
