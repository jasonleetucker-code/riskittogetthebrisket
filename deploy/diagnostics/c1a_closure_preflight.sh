#!/usr/bin/env bash
#
# C1A closure preflight — READ ONLY.
#
# Answers the two questions that decide whether the authorized closure actions
# can be performed from CI at all, before anything mutates production:
#
#   A. WHICH DEPLOY KEY DOES EACH PUSHER ACTUALLY USE?  All three pusher
#      scripts default to ${HOME}/.ssh/github_deploy_key and each supports its
#      own override (DLF_FETCH_SSH_KEY / IDPSHOW_FETCH_SSH_KEY /
#      PLAYERCTX_HISTORY_SSH_KEY).  Production shows the DEFAULT path absent
#      while DLF and IDP Show push successfully, so the siblings must be
#      overridden.  Measuring which, and whether those paths are readable by
#      the app user, is what turns "probably the key" into a repair.
#
#   B. CAN THE HARDENING INSTALLER RUN NON-INTERACTIVELY?  It requires full
#      root (`sudo bash …`).  The deploy pipeline only ever proves NOPASSWD
#      sudo for systemctl, journalctl and install — three specific binaries.
#      If arbitrary `sudo bash` is not permitted, no CI job can install the
#      nightly and it is a human-at-a-terminal action.  Reporting that is the
#      useful answer; discovering it halfway through a mutation is not.
#
# PRIVACY, and it is the reason this is a separate script rather than a flag on
# the inventory: it reads `.env`, which holds secrets.  It prints
#   * whether each of THREE named variables is set — never the file, never any
#     other variable, never a count of what else is in there;
#   * the three KEY PATHS, which are filenames and are needed to state which
#     key the repair should point at;
#   * whether those paths exist and are readable.
# It never prints key material, and `head -c 0`-style truncation is not relied
# on anywhere — nothing that could contain a private key is echoed at all.
#
# Usage:  APP_DIR=... bash -s < deploy/diagnostics/c1a_closure_preflight.sh
# Exit:   0 preflight completed (read the report) · 1 could not run

set -Eeuo pipefail

APP_DIR="${APP_DIR:-/home/dynasty/trade-calculator}"
ENV_FILE="${APP_DIR}/.env"

say() { printf '[c1a-preflight] %s\n' "$*"; }
hdr() { printf '\n[c1a-preflight] ══ %s ══\n' "$*"; }
kv() { printf '[c1a-preflight]   %-38s %s\n' "$1" "$2"; }

[[ -d "${APP_DIR}" ]] || { printf '[c1a-preflight][ERR] APP_DIR missing: %s\n' "${APP_DIR}" >&2; exit 1; }

say "host=$(hostname) user=$(id -un) date=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# ── A. deploy-key configuration ───────────────────────────────────────────
hdr "A. which key each pusher is configured to use"

if [[ ! -e "${ENV_FILE}" ]]; then
    kv ".env" "ABSENT at ${ENV_FILE}"
elif [[ ! -r "${ENV_FILE}" ]]; then
    kv ".env" "PRESENT but UNREADABLE by $(id -un)"
else
    kv ".env" "present and readable"
fi

# Reads ONE named variable and echoes only its value. Never iterates the file,
# so an unrelated secret cannot be printed by accident.
env_value() {
    local name="$1"
    [[ -r "${ENV_FILE}" ]] || return 1
    # last assignment wins, matching how a shell sourcing it would behave;
    # ignores commented-out lines.
    sed -n "s/^[[:space:]]*${name}=//p" "${ENV_FILE}" 2>/dev/null \
        | tail -n 1 \
        | sed -e 's/^["'\'']//' -e 's/["'\'']$//'
}

DEFAULT_KEY="${HOME}/.ssh/github_deploy_key"
kv "default path (all three scripts)" "${DEFAULT_KEY}"
if [[ -r "${DEFAULT_KEY}" ]]; then
    kv "  default path" "READABLE"
elif [[ -e "${DEFAULT_KEY}" || -L "${DEFAULT_KEY}" ]]; then
    kv "  default path" "PRESENT but UNREADABLE by $(id -un)"
else
    kv "  default path" "ABSENT"
fi

for var in DLF_FETCH_SSH_KEY IDPSHOW_FETCH_SSH_KEY PLAYERCTX_HISTORY_SSH_KEY; do
    val="$(env_value "${var}" || true)"
    if [[ -z "${val}" ]]; then
        kv "${var}" "NOT CONFIGURED — falls back to the default path"
        continue
    fi
    kv "${var}" "configured -> ${val}"
    # Readability as the APP USER. This script runs as that user, which is the
    # same User= the units run under, so `test -r` here answers the question
    # the unit will ask.
    if [[ -r "${val}" ]]; then
        kv "  readable by $(id -un)" "YES  mode=$(stat -c %a "${val}" 2>/dev/null || echo '?') owner=$(stat -c '%U:%G' "${val}" 2>/dev/null || echo '?')"
    elif [[ -e "${val}" || -L "${val}" ]]; then
        kv "  readable by $(id -un)" "NO — present but not readable"
    else
        kv "  readable by $(id -un)" "NO — ABSENT"
    fi
done

hdr "A2. do the siblings' keys authorize THIS repository?"
# A key that reads is not a key that can push. `ssh -T git@github.com` returns
# 1 on success for a deploy key, so the STATUS is not the signal — the message
# is, and it names the repository the key is attached to.
#
# Deliberately NOT a push: a preflight that mutates a remote is not a preflight.
for var in DLF_FETCH_SSH_KEY IDPSHOW_FETCH_SSH_KEY; do
    val="$(env_value "${var}" || true)"
    [[ -n "${val}" && -r "${val}" ]] || { kv "${var}" "skipped (not configured or unreadable)"; continue; }
    out="$(ssh -i "${val}" -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
             -o ConnectTimeout=10 -T git@github.com 2>&1 || true)"
    # GitHub's reply for a deploy key is a single line naming the repo.
    kv "${var} -> github identity" "$(printf '%s' "${out}" | head -n 1)"
done

# ── B. can the installer run non-interactively? ───────────────────────────
hdr "B. NOPASSWD sudo scope (decides whether CI can install the nightly)"

probe_sudo() {
    local label="$1"; shift
    if sudo -n "$@" >/dev/null 2>&1; then
        kv "${label}" "PERMITTED"
    else
        kv "${label}" "NOT PERMITTED without a password"
    fi
}
probe_sudo "sudo -n /bin/systemctl" /bin/systemctl --version
probe_sudo "sudo -n /usr/bin/install" /usr/bin/install --version
probe_sudo "sudo -n /bin/journalctl" /bin/journalctl --version
# The one apply_hardening.sh actually needs.
probe_sudo "sudo -n bash (arbitrary root shell)" bash -c 'true'

say "sudo -l (what this account may run as root):"
sudo -n -l 2>&1 | sed 's/^/[c1a-preflight]     /' | head -n 40 || \
    say "  sudo -l unavailable without a password"

hdr "B2. the installer as it exists on this host"
HARDEN="${APP_DIR}/deploy/apply_hardening.sh"
if [[ -r "${HARDEN}" ]]; then
    kv "apply_hardening.sh" "PRESENT sha256=$(sha256sum "${HARDEN}" | awk '{print $1}')"
    kv "  supports --dry-run" "$(grep -c -- '--dry-run' "${HARDEN}" | tr -d ' ') reference(s)"
    kv "  has a per-step selector" "$(grep -cE '^\s*--only|^\s*--skip' "${HARDEN}" | tr -d ' ') (0 means all-or-nothing)"
else
    kv "apply_hardening.sh" "ABSENT or unreadable at ${HARDEN}"
fi

hdr "DONE — nothing above was modified"
exit 0
