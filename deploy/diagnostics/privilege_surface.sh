#!/usr/bin/env bash
# READ-ONLY: what may the deploy user actually do on production?
#
# The 2026-08-12 follow-up found that a fully green deploy left the live
# process on soft LimitNOFILE 1024 and dynasty-healthcheck.timer
# inactive, because deploy.sh never reconciles the installed systemd unit
# or the root-owned healthcheck copy.  Before choosing between
# "reconcile automatically" and "refuse and tell the operator", we need
# the privilege boundary as FACT, not assumption: automatic convergence
# is only on the table if the deploy user can already do it without
# widening sudo.
#
# Reads nothing but sudo policy and unit state.  Changes nothing.
# Prints no environment variables.

set -uo pipefail
SERVICE_NAME="${1:-dynasty}"
section() { printf '\n===== %s =====\n' "$*"; }

section "identity"
echo "user: $(id -un)  groups: $(id -Gn)"

section "permitted sudo surface (sudo -l)"
# -n so it can never prompt.  This is the decisive evidence.
sudo -n -l 2>&1 || echo "(sudo -l refused — the policy itself is not readable)"

section "can the deploy user write the install targets?"
for p in /etc/systemd/system /usr/local/lib/riskit; do
  if [[ -d "$p" ]]; then
    printf '%-28s exists  owner=%s mode=%s writable_by_me=%s\n' \
      "$p" "$(stat -c '%U' "$p")" "$(stat -c '%a' "$p")" \
      "$([[ -w "$p" ]] && echo yes || echo no)"
  else
    printf '%-28s MISSING\n' "$p"
  fi
done

section "installed unit vs repo template"
for u in "${SERVICE_NAME}.service" "${SERVICE_NAME}-healthcheck.service" "${SERVICE_NAME}-healthcheck.timer"; do
  f="/etc/systemd/system/${u}"
  if [[ -f "$f" ]]; then
    printf '%-40s present  owner=%s mode=%s mtime=%s\n' "$u" \
      "$(stat -c '%U' "$f")" "$(stat -c '%a' "$f")" "$(stat -c '%y' "$f" | cut -d. -f1)"
    grep -H '^LimitNOFILE' "$f" 2>/dev/null || echo "    (no LimitNOFILE line)"
  else
    printf '%-40s ABSENT\n' "$u"
  fi
done

section "healthcheck timer/service state"
SC=/bin/systemctl; [[ -x "$SC" ]] || SC=/usr/bin/systemctl
sudo -n "$SC" show "${SERVICE_NAME}-healthcheck.timer" \
  -p LoadState -p ActiveState -p UnitFileState -p NextElapseUSecRealtime 2>/dev/null
sudo -n "$SC" show "${SERVICE_NAME}-healthcheck.service" \
  -p LoadState -p UnitFileState -p ExecStart 2>/dev/null | head -4

section "root-owned healthcheck copy"
p=/usr/local/lib/riskit/${SERVICE_NAME}-healthcheck.sh
if [[ -e "$p" ]]; then
  echo "present: $(stat -c 'owner=%U mode=%a mtime=%y' "$p" | cut -d. -f1)"
  echo "readable by me: $([[ -r "$p" ]] && echo yes || echo no)"
else
  echo "ABSENT at $p"
fi
ls -la /usr/local/lib/riskit/ 2>/dev/null | head -8 || echo "(dir not listable)"

echo
echo "privilege_surface complete (read-only)."
