#!/usr/bin/env bash
# Read-only Node runtime check for the production box (STAB-6, 2026-11-19).
#
# Run on the box BEFORE and AFTER installing Node 22:
#   bash deploy/node22_box_check.sh            # report only
#   bash deploy/node22_box_check.sh --require 22.12   # exit 1 unless every node the
#                                                      # app can resolve is >= 22.12
# It changes nothing: no install, no restart. Prints versions and paths only.
set -Eeuo pipefail

REQUIRE=""
if [[ "${1:-}" == "--require" ]]; then
  REQUIRE="${2:?--require needs a version like 22.12}"
fi
APP_USER="${APP_USER:-dynasty}"

ver_ge() {  # ver_ge 22.23.4 22.12 -> 0 when $1 >= $2
  local a b
  IFS=. read -r -a a <<<"${1#v}"
  IFS=. read -r -a b <<<"${2#v}"
  for i in 0 1 2; do
    local x="${a[$i]:-0}" y="${b[$i]:-0}"
    (( x > y )) && return 0
    (( x < y )) && return 1
  done
  return 0
}

echo "== OS"; (. /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-unknown}") || echo unknown
echo "== node on PATH (current shell)"
command -v node && node --version || echo "node: not on PATH"
command -v npm && npm --version || echo "npm: not on PATH"
echo "== as ${APP_USER} (what the services resolve)"
APP_NODE="$(sudo -n -u "${APP_USER}" bash -lc 'node --version' 2>/dev/null || true)"
echo "${APP_USER} node: ${APP_NODE:-unknown (sudo -n not permitted or node missing)}"
echo "== /usr/bin/node (the frontend unit runs /usr/bin/npm)"
[[ -x /usr/bin/node ]] && /usr/bin/node --version || echo "/usr/bin/node: absent"
echo "== apt"
apt-cache policy nodejs 2>/dev/null | sed -n '1,4p' || true
ls /etc/apt/sources.list.d/ 2>/dev/null | grep -i node || echo "no nodesource list file"

if [[ -n "${REQUIRE}" ]]; then
  fail=0
  for v in "$(/usr/bin/node --version 2>/dev/null || true)" "${APP_NODE}"; do
    [[ -z "$v" ]] && continue
    if ! ver_ge "$v" "${REQUIRE}"; then
      echo "FAIL: node $v < required ${REQUIRE}"; fail=1
    fi
  done
  [[ -x /usr/bin/node ]] || { echo "FAIL: /usr/bin/node missing"; fail=1; }
  (( fail == 0 )) && echo "OK: node >= ${REQUIRE}" || exit 1
fi
