#!/usr/bin/env bash
#
# nginx_live_harden.sh — add the Chase Upside security headers to the LIVE
# nginx site WITHOUT replacing it.
#
# Why this exists: the live site (/etc/nginx/sites-available/dynasty) is
# certbot-managed and pins its :443 listeners to specific public addresses
# (a wildcard :443 cannot coexist with Tailscale Serve on the tailnet
# address).  deploy/nginx/chaseupside.com.conf is a TEMPLATE with address
# placeholders and its own upstreams, so installing it over the live file
# would revert certbot's edits or collide with the live upstreams.
#
# This script instead:
#   1. installs deploy/nginx/snippets/chaseupside-security-headers.conf to
#      /etc/nginx/snippets/ (server-context: headers + banner hiding only);
#   2. inserts ONE line, `include <snippet>;`, after the server_name line of
#      every server block whose server_name names chaseupside.com;
#   3. proves the candidate differs from the live file by exactly those
#      inserted lines — every listen, ssl_certificate, certbot include,
#      server_name, location and return line is byte-identical;
#   4. on --apply: backs up, installs, `nginx -t` (auto-restore on failure),
#      reloads, and probes the public site.
# It never touches other sites (e.g. housing), listeners, certificates,
# upstreams or Tailscale.
#
# Usage:
#   bash deploy/nginx_live_harden.sh                 # dry-run (default; no root)
#   sudo bash deploy/nginx_live_harden.sh --apply --expect-sha256 <sha from dry-run>
#   bash deploy/nginx_live_harden.sh --verify        # read-only live check (no root)
#
# Env overrides (tests): LIVE_SITE, SNIPPET_DEST, SNIPPET_SRC, NGINX_BIN,
# SYSTEMCTL_BIN, SKIP_PROBE=1, ALLOW_NON_ROOT_APPLY=1.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIVE_SITE="${LIVE_SITE:-/etc/nginx/sites-available/dynasty}"
SNIPPET_SRC="${SNIPPET_SRC:-${SCRIPT_DIR}/nginx/snippets/chaseupside-security-headers.conf}"
SNIPPET_DEST="${SNIPPET_DEST:-/etc/nginx/snippets/chaseupside-security-headers.conf}"
NGINX_BIN="${NGINX_BIN:-nginx}"
SYSTEMCTL_BIN="${SYSTEMCTL_BIN:-systemctl}"
DOMAIN="chaseupside.com"
INCLUDE_LINE="    include ${SNIPPET_DEST}; # chaseupside hardening (deploy/nginx_live_harden.sh)"

MODE="dry-run"
EXPECT_SHA=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --apply) MODE="apply"; shift ;;
        --dry-run) MODE="dry-run"; shift ;;
        --verify) MODE="verify"; shift ;;
        --expect-sha256) EXPECT_SHA="${2:-}"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

log() { printf '[nginx-live-harden] %s\n' "$*"; }
die() { printf '[nginx-live-harden][ERROR] %s\n' "$*" >&2; exit 1; }

EXPECTED_HEADERS=(
    strict-transport-security x-content-type-options content-security-policy
    x-frame-options referrer-policy permissions-policy
)

# probe_live <attempts> — fetch https://DOMAIN/ through the live file's own
# pinned :443 IPv4 listener, bypassing any proxy, and check the hardening.
# `systemctl reload nginx` is asynchronous: old workers keep answering for a
# moment, so a single immediate request can report the PRE-reload headers.
# Retries (1 s apart) until every expected header is present and the version
# banner is gone.  Sets PROBE_STATUS to ok / incomplete / unreachable.
probe_live() {
    local attempts="${1:-15}" i hdrs status v4 missing h
    local resolve=()
    v4="$(grep -oE 'listen[[:space:]]+([0-9]{1,3}\.){3}[0-9]{1,3}:443' "${LIVE_SITE}" | head -1 | awk '{print $2}' | cut -d: -f1 || true)"
    [[ -n "${v4}" ]] && resolve=(--resolve "${DOMAIN}:443:${v4}")
    PROBE_STATUS="unreachable"
    for ((i = 1; i <= attempts; i++)); do
        hdrs="$(curl --noproxy '*' -sS -o /dev/null -D - -m 10 "${resolve[@]}" "https://${DOMAIN}/" 2>/dev/null | tr -d '\r' || true)"
        status="$(printf '%s\n' "${hdrs}" | awk 'NR==1{print $2}')"
        if [[ -z "${hdrs}" || "${status}" =~ ^5 ]]; then
            PROBE_STATUS="unreachable"
        else
            missing=()
            for h in "${EXPECTED_HEADERS[@]}"; do
                printf '%s\n' "${hdrs}" | grep -qi "^${h}:" || missing+=("${h}")
            done
            printf '%s\n' "${hdrs}" | grep -qiE '^server: nginx/[0-9]' && missing+=("server-version-banner")
            printf '%s\n' "${hdrs}" | grep -qi '^x-powered-by:' && missing+=("x-powered-by")
            if [[ "${#missing[@]}" -eq 0 ]]; then
                PROBE_STATUS="ok"
                log "probe: HTTP ${status}; all ${#EXPECTED_HEADERS[@]} headers present; no version banner; no X-Powered-By (attempt ${i})"
                return 0
            fi
            PROBE_STATUS="incomplete"
        fi
        sleep "${PROBE_SLEEP:-1}"
    done
    if [[ "${PROBE_STATUS}" == "incomplete" ]]; then
        log "probe: HTTP ${status}; still missing / present-when-it-should-not: ${missing[*]}"
    else
        log "probe: no healthy answer after ${attempts} attempts (status '${status:-none}')"
    fi
    return 1
}

if [[ "${MODE}" == "verify" ]]; then
    # Read-only check of the LIVE server; needs no root and changes nothing.
    [[ -r "${LIVE_SITE}" ]] || die "cannot read live site ${LIVE_SITE}"
    probe_live "${PROBE_ATTEMPTS:-3}" && exit 0
    exit 1
fi

[[ -r "${LIVE_SITE}" ]] || die "cannot read live site ${LIVE_SITE}"
[[ -r "${SNIPPET_SRC}" ]] || die "missing snippet source ${SNIPPET_SRC}"

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
CANDIDATE="${WORK}/candidate.conf"
# One read of the live file: everything below hashes and patches this copy.
SNAPSHOT="${WORK}/live.snapshot"
cp "${LIVE_SITE}" "${SNAPSHOT}"
LIVE_SHA="$(sha256sum "${SNAPSHOT}" | cut -d' ' -f1)"

# --- preflight: refuse configs this patcher cannot reason about --------
# Depth-aware scan.  Comments are stripped before counting braces.
awk -v domain="${DOMAIN}" '
    function strip(s) { sub(/#.*/, "", s); return s }
    {
        line = strip($0)
        # A nested add_header / proxy_hide_header (including on a one-line
        # `location ... { ... }`) replaces the inherited server-level set.
        if ((depth >= 2 && line ~ /^[ \t]*(add_header|proxy_hide_header)[ \t]/) ||
            (line ~ /^[ \t]*(location|if)[ \t].*\{.*(add_header|proxy_hide_header)[ \t]/)) {
            printf "nested add_header/proxy_hide_header at line %d would mask server-level headers\n", NR > "/dev/stderr"; bad = 1
        }
        if (depth == 1 && line ~ /^[ \t]*add_header[ \t]/ && inchase) {
            printf "server-level add_header already present at line %d (would duplicate)\n", NR > "/dev/stderr"; bad = 1
        }
        if (depth == 1 && line ~ /^[ \t]*server_name[ \t]/ && index(line, domain)) { inchase = 1; chase++ }
        o = gsub(/\{/, "{", line); c = gsub(/\}/, "}", line)
        depth += o - c
        if (depth == 0) inchase = 0
    }
    END {
        if (depth != 0) { print "unbalanced braces" > "/dev/stderr"; bad = 1 }
        if (chase == 0) { print "no server block names " domain > "/dev/stderr"; bad = 1 }
        exit bad
    }
' "${SNAPSHOT}" || die "preflight refused ${LIVE_SITE}; nothing changed"

# --- candidate: insert the include after each chaseupside server_name ---
if grep -qF "include ${SNIPPET_DEST};" "${SNAPSHOT}"; then
    cp "${SNAPSHOT}" "${CANDIDATE}"
    ALREADY=1
else
    # Line numbers (in the live file) of each chaseupside server_name.  The
    # candidate is then built by sed `a` (append-after-line), which copies
    # every original byte — including a missing final newline — untouched.
    mapfile -t INSERT_AFTER < <(awk -v domain="${DOMAIN}" '
        function strip(s) { sub(/#.*/, "", s); return s }
        {
            line = strip($0)
            if (depth == 1 && line ~ /^[ \t]*server_name[ \t]/ && index(line, domain)) print NR
            o = gsub(/\{/, "{", line); c = gsub(/\}/, "}", line)
            depth += o - c
        }
    ' "${SNAPSHOT}")
    [[ "${#INSERT_AFTER[@]}" -gt 0 ]] || die "no insertion point found"
    SED_SCRIPT="${WORK}/insert.sed"
    : > "${SED_SCRIPT}"
    for n in "${INSERT_AFTER[@]}"; do
        printf '%sa\\\n%s\n' "${n}" "${INCLUDE_LINE}" >> "${SED_SCRIPT}"
    done
    sed -f "${SED_SCRIPT}" "${SNAPSHOT}" > "${CANDIDATE}"
    ALREADY=0
fi

# --- proof: byte-exact — the candidate minus the inserted lines IS the live file
if [[ "${ALREADY}" == 0 ]]; then
    # Inserted line k (0-based) lands at candidate line INSERT_AFTER[k] + k + 1.
    DEL_SCRIPT="${WORK}/delete.sed"
    : > "${DEL_SCRIPT}"
    k=0
    for n in "${INSERT_AFTER[@]}"; do
        printf '%sd\n' "$((n + k + 1))" >> "${DEL_SCRIPT}"
        k=$((k + 1))
    done
    sed -f "${DEL_SCRIPT}" "${CANDIDATE}" > "${WORK}/candidate.minus"
    cmp -s "${WORK}/candidate.minus" "${SNAPSHOT}" \
        || die "candidate is not byte-identical to the live file apart from the inserted lines; refusing"
    if [[ "$(grep -cF "include ${SNIPPET_DEST};" "${CANDIDATE}")" != "${#INSERT_AFTER[@]}" ]]; then
        die "inserted-line count mismatch; refusing"
    fi
fi
for pat in 'listen ' 'ssl_certificate' 'letsencrypt' 'server_name ' 'location ' 'return ' 'proxy_pass '; do
    if [[ "$(grep -cF "${pat}" "${CANDIDATE}")" != "$(grep -cF "${pat}" "${SNAPSHOT}")" ]]; then
        die "line count for '${pat}' changed; refusing"
    fi
done
ADDED=0
[[ "${ALREADY}" == 0 ]] && ADDED="${#INSERT_AFTER[@]}"

log "mode: ${MODE}"
log "live site: ${LIVE_SITE}"
log "live sha256: ${LIVE_SHA}"
if [[ "${ALREADY}" == 1 ]]; then
    log "include already present — site file unchanged"
else
    log "lines to insert: ${ADDED} (one per ${DOMAIN} server block); listeners, certificates, locations: unchanged"
    diff -u --label "${LIVE_SITE}" --label "${LIVE_SITE} (candidate)" "${SNAPSHOT}" "${CANDIDATE}" || true
fi
if [[ -f "${SNIPPET_DEST}" ]] && cmp -s "${SNIPPET_SRC}" "${SNIPPET_DEST}"; then
    log "snippet up to date: ${SNIPPET_DEST}"
else
    log "snippet to install at ${SNIPPET_DEST}:"
    sed 's/^/    | /' "${SNIPPET_SRC}"
fi

if [[ "${MODE}" == "dry-run" ]]; then
    log "dry-run: nothing changed.  nginx -t is not run here (it needs root)."
    log "to apply after review:  sudo bash $0 --apply --expect-sha256 ${LIVE_SHA}"
    exit 0
fi

# --- apply -------------------------------------------------------------
if [[ "${EUID}" -ne 0 && "${ALLOW_NON_ROOT_APPLY:-0}" != 1 ]]; then
    die "--apply must run as root"
fi
[[ -n "${EXPECT_SHA}" ]] || die "--apply requires --expect-sha256 (the sha the dry-run printed)"
[[ "${EXPECT_SHA}" == "${LIVE_SHA}" ]] || die "live file changed since the dry-run (sha ${LIVE_SHA}); re-run the dry-run"

STAMP="$(date -u +%Y%m%d%H%M%S)"
BACKUP="${LIVE_SITE}.bak.${STAMP}"
SNIPPET_EXISTED=0; [[ -f "${SNIPPET_DEST}" ]] && SNIPPET_EXISTED=1
SNIPPET_BACKUP="${WORK}/snippet.prev"
[[ "${SNIPPET_EXISTED}" == 1 ]] && cp -p "${SNIPPET_DEST}" "${SNIPPET_BACKUP}"

restore() {
    log "restoring ${BACKUP}"
    cp -p "${BACKUP}" "${LIVE_SITE}"
    if [[ "${SNIPPET_EXISTED}" == 1 ]]; then cp -p "${SNIPPET_BACKUP}" "${SNIPPET_DEST}"; else rm -f "${SNIPPET_DEST}"; fi
    "${NGINX_BIN}" -t && "${SYSTEMCTL_BIN}" reload nginx || log "restore: nginx -t failed — manual attention required"
}

[[ "$(sha256sum "${LIVE_SITE}" | cut -d' ' -f1)" == "${LIVE_SHA}" ]] || die "live file changed during this run; nothing installed"
cp -p "${LIVE_SITE}" "${BACKUP}"
log "backed up live site to ${BACKUP}"
install -m 0644 "${SNIPPET_SRC}" "${SNIPPET_DEST}"
install -m 0644 "${CANDIDATE}" "${LIVE_SITE}"
if ! "${NGINX_BIN}" -t; then
    log "nginx -t FAILED"
    cp -p "${BACKUP}" "${LIVE_SITE}"
    if [[ "${SNIPPET_EXISTED}" == 1 ]]; then cp -p "${SNIPPET_BACKUP}" "${SNIPPET_DEST}"; else rm -f "${SNIPPET_DEST}"; fi
    "${NGINX_BIN}" -t || true
    die "restored the previous config; nginx was NOT reloaded"
fi
"${SYSTEMCTL_BIN}" reload nginx
log "nginx reloaded"

if [[ "${SKIP_PROBE:-0}" == 1 ]]; then exit 0; fi
if ! probe_live 15; then
    if [[ "${PROBE_STATUS}" == "unreachable" ]]; then
        log "probe: site did not answer correctly after reload — rolling back"
        restore
        die "rolled back"
    fi
    log "probe WARNING: headers incomplete after retries; verify by hand: bash $0 --verify"
fi
log "done.  rollback: sudo cp -p ${BACKUP} ${LIVE_SITE} && sudo rm -f ${SNIPPET_DEST} && sudo nginx -t && sudo systemctl reload nginx"
