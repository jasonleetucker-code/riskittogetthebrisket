#!/usr/bin/env bash
# Prove that TLS renewal actually works, before it matters.
#
# Usage (as root ON THE VPS):
#   sudo bash deploy/verify-cert-renewal.sh
#   sudo bash deploy/verify-cert-renewal.sh --no-dry-run-only   # same, explicit
#
# Env overrides:
#   CERT_DOMAIN     primary certificate name.  Default: chaseupside.com
#   WEBROOT         expected ACME webroot.     Default: /var/www/certbot
#   RENEWAL_CONF    renewal config path.
#                   Default: /etc/letsencrypt/renewal/${CERT_DOMAIN}.conf
#
# Why this exists: ORCHESTRATION.md §6.5 has carried "certificate renewal
# has never been tested" as an open operator item.  The failure mode is
# the site going dark roughly 85 days after issue with no prior warning,
# and the certbot timer merely EXISTING is not evidence that renewal
# works — the cert was issued through a temporary ACME location, and the
# live nginx config has changed since.
#
# Three things have to hold, and the timer proves none of them:
#   1. a renewal timer (or cron) is armed at all;
#   2. `certbot renew --dry-run` succeeds against the CURRENT nginx
#      config, not the one in place at issuance;
#   3. the renewal config carries `renew_hook = systemctl reload nginx`.
#      Certificates are issued with the WEBROOT plugin (see the note in
#      deploy/nginx/chaseupside.com.conf), so certbot knows nothing about
#      nginx.  Without the hook a renewed certificate lands on disk
#      unused and the site serves the expired one until someone reloads
#      by hand — a renewal that "succeeds" and still takes the site down.
#
# THIS CANNOT BE RUN FROM AN AGENT SESSION, and that is not a limitation
# worth working around: ORCHESTRATION.md §6.5 records that there is no ssh
# client in the container, and outbound HTTPS goes through a re-signing
# egress proxy, so reading chaseupside.com:443 returns the proxy's
# certificate rather than Let's Encrypt's.  Any expiry checked that way is
# the wrong certificate's.
#
# Exit code: 0 all checks passed, 1 otherwise.

set -Eeuo pipefail

CERT_DOMAIN="${CERT_DOMAIN:-chaseupside.com}"
WEBROOT="${WEBROOT:-/var/www/certbot}"
RENEWAL_CONF="${RENEWAL_CONF:-/etc/letsencrypt/renewal/${CERT_DOMAIN}.conf}"

FAILURES=0

log() { printf '[cert] %s\n' "$*"; }
warn() { printf '[cert][WARN] %s\n' "$*" >&2; }
error() {
  printf '[cert][ERROR] %s\n' "$*" >&2
  FAILURES=$((FAILURES + 1))
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    printf '[cert][ERROR] must run as root (certbot reads /etc/letsencrypt).\n' >&2
    printf '[cert][ERROR] try: sudo bash deploy/verify-cert-renewal.sh\n' >&2
    exit 1
  fi
}

check_timer() {
  log "--- renewal timer ---"
  local found=""
  if command -v systemctl >/dev/null 2>&1; then
    # Package installs use certbot.timer; snap installs use
    # snap.certbot.renew.timer.  Either is fine, one must exist.
    if systemctl list-timers --all 2>/dev/null | grep -qiE 'certbot|snap\.certbot\.renew'; then
      found="systemd"
      systemctl list-timers --all 2>/dev/null | grep -iE 'certbot|snap\.certbot\.renew' | sed 's/^/[cert]   /'
    fi
  fi
  if [[ -z "${found}" && -f /etc/cron.d/certbot ]]; then
    found="cron"
    log "  /etc/cron.d/certbot present"
  fi
  if [[ -z "${found}" ]]; then
    error "no certbot timer and no /etc/cron.d/certbot — renewal is NOT automated."
    error "  fix: sudo systemctl enable --now certbot.timer"
  else
    log "  armed via ${found}"
  fi
}

check_renew_hook() {
  log "--- renewal config ---"
  if [[ ! -f "${RENEWAL_CONF}" ]]; then
    error "no renewal config at ${RENEWAL_CONF} — was the cert issued for ${CERT_DOMAIN}?"
    return
  fi
  if grep -qE '^\s*renew_hook\s*=.*(systemctl|service).*nginx' "${RENEWAL_CONF}"; then
    log "  renew_hook reloads nginx: $(grep -E '^\s*renew_hook' "${RENEWAL_CONF}" | head -1 | sed 's/^\s*//')"
  else
    error "renew_hook does NOT reload nginx in ${RENEWAL_CONF}."
    error "  Certs are issued with the WEBROOT plugin, so certbot never touches"
    error "  nginx. Without this hook a renewed cert sits unused on disk and the"
    error "  site keeps serving the expired one."
    error "  fix: add under [renewalparams]:  renew_hook = systemctl reload nginx"
  fi
  if grep -qE "^\s*webroot_path\s*=.*${WEBROOT//\//\\/}" "${RENEWAL_CONF}"; then
    log "  webroot_path is ${WEBROOT}"
  else
    warn "webroot_path is not ${WEBROOT} in ${RENEWAL_CONF}:"
    grep -E '^\s*webroot_path' "${RENEWAL_CONF}" | sed 's/^/[cert]   /' || true
    warn "  The dry run below is the real test; this is only a hint if it fails."
  fi
}

check_dry_run() {
  log "--- certbot renew --dry-run ---"
  if ! command -v certbot >/dev/null 2>&1; then
    error "certbot is not installed or not on PATH."
    return
  fi
  # This is the check that matters: it renews against the CURRENT nginx
  # config through the real ACME challenge path, without burning a rate
  # limit.
  if certbot renew --dry-run 2>&1 | tee /tmp/certbot-dry-run.log | sed 's/^/[cert]   /'; then
    if grep -qi "simulated renewal" /tmp/certbot-dry-run.log; then
      log "  dry run succeeded"
    else
      error "certbot exited 0 but printed no 'simulated renewal' line — read /tmp/certbot-dry-run.log"
    fi
  else
    error "certbot renew --dry-run FAILED — renewal would fail for real in ~85 days."
    error "  full output: /tmp/certbot-dry-run.log"
  fi
}

main() {
  require_root
  log "domain ${CERT_DOMAIN}"
  check_timer
  check_renew_hook
  check_dry_run
  echo
  if (( FAILURES > 0 )); then
    error "${FAILURES} check(s) failed — renewal is NOT proven."
    exit 1
  fi
  log "All checks passed. Renewal is armed, hooked, and verified end to end."
  log "Re-run after any nginx or certbot change; it is cheap and rate-limit free."
}

main "$@"
