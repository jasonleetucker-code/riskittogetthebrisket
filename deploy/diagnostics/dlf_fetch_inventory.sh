#!/usr/bin/env bash
# DLF acquisition evidence, read from the production host.
#
# WHY THIS EXISTS
# ---------------
# Every DLF board (dlfSf / dlfIdp / dlfRookieSf / dlfRookieIdp) last fetched
# on 2026-09-09.  DLF sits behind a Cloudflare ruleset that 403s GitHub and
# agent IP ranges, so the fetch runs only on the production host
# (``deploy/dlf_fetch_and_push.sh`` via ``dynasty-dlf-fetch.timer``) and the
# cause is unobservable from anywhere else.  This collects the evidence needed
# to classify it — service result, journal, credential PRESENCE, session age,
# and a per-board dry run that reports the exact write/refuse verdict the real
# run makes (``fetch_dlf._board_verdict``) plus the table headers it parsed,
# and a structure probe of the Trade Analyzer Values page (``--probe``).
#
# CONTRACT
# --------
# READ-ONLY with respect to production state.  It does not start, restart or
# reload any unit, does not touch the app tree, the dedicated fetch clone, or
# the persisted session jar, and writes only inside DIAG_DIR (a mktemp dir the
# workflow created and uploaded the runner's ``fetch_dlf.py`` into), which it
# removes on exit.  The dry run logs in to DLF exactly as the timer does; it
# writes no CSV.
#
# NEVER prints a credential: only whether DLF_USERNAME / DLF_PASSWORD are set,
# and every line of fetcher output is scrubbed of both values before printing.
#
# A failing dry run is the FINDING, not a diagnostic failure: its exit code is
# printed and the script still exits 0.  Missing infrastructure (no app dir,
# no interpreter, no uploaded fetcher) exits non-zero.

set -Eeuo pipefail

APP_DIR="${APP_DIR:-/home/dynasty/trade-calculator}"
WORK_DIR="${DLF_FETCH_WORK_DIR:-/var/lib/dlf-fetch}"
DIAG_DIR="${DIAG_DIR:?DIAG_DIR (uploaded fetcher dir) is required}"
UNIT="dynasty-dlf-fetch"
JOURNAL_LINES="${JOURNAL_LINES:-200}"

trap 'rm -rf -- "${DIAG_DIR}"' EXIT

hdr() { printf '\n--- %s ---\n' "$*"; }

echo "=== DLF fetch inventory ==="
echo "host     : $(hostname)"
echo "user     : $(id -un)"
echo "utc      : $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "app_dir  : ${APP_DIR}"
echo "work_dir : ${WORK_DIR}"

[[ -d "${APP_DIR}" ]] || { echo "FATAL: APP_DIR missing" >&2; exit 2; }
[[ -f "${DIAG_DIR}/scripts/fetch_dlf.py" ]] || { echo "FATAL: uploaded fetcher missing" >&2; exit 2; }

# ------------------------------------------------------------------ 1 --
hdr "[1] systemd unit + timer"
systemctl show "${UNIT}.service" \
  -p ActiveState -p SubState -p Result -p ExecMainStatus \
  -p ExecMainStartTimestamp -p ExecMainExitTimestamp --no-pager 2>&1 || echo "systemctl show failed"
systemctl list-timers "${UNIT}.timer" --all --no-pager 2>&1 || echo "list-timers failed"

# ------------------------------------------------------------------ 2 --
hdr "[2] journal (last ${JOURNAL_LINES} lines)"
if journalctl -u "${UNIT}.service" -n 1 --no-pager >/dev/null 2>&1; then
  journalctl -u "${UNIT}.service" -n "${JOURNAL_LINES}" --no-pager 2>&1 | sed 's/^/[journal] /'
elif sudo -n journalctl -u "${UNIT}.service" -n 1 --no-pager >/dev/null 2>&1; then
  sudo -n journalctl -u "${UNIT}.service" -n "${JOURNAL_LINES}" --no-pager 2>&1 | sed 's/^/[journal] /'
else
  echo "journal not readable by $(id -un) (and no NOPASSWD journalctl)"
fi

# ------------------------------------------------------------------ 3 --
hdr "[3] credential presence (values never printed)"
ENV_FILE="${APP_DIR}/.env"
DLF_USERNAME=""
DLF_PASSWORD=""
if [[ -r "${ENV_FILE}" ]]; then
  # Read the two keys without sourcing the whole file (and without echoing).
  DLF_USERNAME="$(grep -E '^DLF_USERNAME=' "${ENV_FILE}" | tail -n1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//' || true)"
  DLF_PASSWORD="$(grep -E '^DLF_PASSWORD=' "${ENV_FILE}" | tail -n1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//' || true)"
  echo "env_file readable : yes"
else
  echo "env_file readable : NO (${ENV_FILE})"
fi
echo "DLF_USERNAME set  : $([[ -n "${DLF_USERNAME}" ]] && echo yes || echo NO)"
echo "DLF_PASSWORD set  : $([[ -n "${DLF_PASSWORD}" ]] && echo yes || echo NO)"

scrub() {
  local line
  while IFS= read -r line; do
    [[ -n "${DLF_USERNAME}" ]] && line="${line//"${DLF_USERNAME}"/<DLF_USERNAME>}"
    [[ -n "${DLF_PASSWORD}" ]] && line="${line//"${DLF_PASSWORD}"/<DLF_PASSWORD>}"
    printf '%s\n' "${line}"
  done
}

# ------------------------------------------------------------------ 4 --
hdr "[4] persisted session jar (names + expiry only)"
SESSION_FILE="${WORK_DIR}/dlf_session.json"
PY="${DLF_FETCH_PYTHON:-/home/dynasty/.venvs/trade-calculator/bin/python}"
[[ -x "${PY}" ]] || PY="${APP_DIR}/.venv/bin/python"
[[ -x "${PY}" ]] || PY="$(command -v python3 || true)"
[[ -n "${PY}" ]] || { echo "FATAL: no python interpreter" >&2; exit 2; }
echo "python : ${PY} ($("${PY}" -V 2>&1))"
if [[ -r "${SESSION_FILE}" ]]; then
  echo "session mtime : $(date -u -r "${SESSION_FILE}" +%Y-%m-%dT%H:%M:%SZ)"
  "${PY}" - "${SESSION_FILE}" <<'PY' || echo "session jar unreadable as JSON"
import json, sys, time
cookies = json.load(open(sys.argv[1]))
print(f"cookies : {len(cookies)}")
for c in cookies:
    exp = c.get("expires")
    when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(exp)) if isinstance(exp, (int, float)) else exp
    print(f"  {str(c.get('name'))[:48]:48s} expires={when}")
PY
  cp -f "${SESSION_FILE}" "${DIAG_DIR}/dlf_session.json"
else
  echo "session jar : absent (${SESSION_FILE}) — a run performs a full WP login"
fi

# ------------------------------------------------------------------ 5 --
hdr "[5] dedicated fetch clone + committed CSV headers"
if [[ -d "${WORK_DIR}/repo/.git" ]]; then
  git -C "${WORK_DIR}/repo" log -1 --format='clone HEAD : %h %cI %s' 2>&1 || true
  for key in dlfSf dlfIdp dlfRookieSf dlfRookieIdp; do
    f="${WORK_DIR}/repo/CSVs/site_raw/${key}.csv"
    [[ -f "${f}" ]] && echo "${key}: $(head -n1 "${f}") rows=$(($(wc -l <"${f}") - 1))"
  done
  for key in dlf dlfSf dlfIdp dlfRookieSf dlfRookieIdp; do
    s="${WORK_DIR}/repo/data/scrape_state/${key}_last_success"
    [[ -f "${s}" ]] && echo "stamp ${key}_last_success = $(date -u -d "@$(tr -d '[:space:]' <"${s}")" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || cat "${s}")"
  done
else
  echo "no dedicated clone at ${WORK_DIR}/repo"
fi
"${PY}" -c 'import bs4, curl_cffi; print("deps : bs4", bs4.__version__, "curl_cffi", curl_cffi.__version__)' 2>&1 || echo "deps : import FAILED"

# ------------------------------------------------------------------ 6 --
hdr "[6] per-board dry run (runner's fetch_dlf.py, no CSV written)"
set +e
(
  cd "${DIAG_DIR}"
  export DLF_USERNAME DLF_PASSWORD
  timeout 420 "${PY}" scripts/fetch_dlf.py --dry-run 2>&1
) | scrub
rc=${PIPESTATUS[0]}
set -e
echo "dry_run_exit=${rc}"

# DLF moved its native offensive Value off the rankings boards to the Trade
# Analyzer Values page.  Page structure is evidence the parser is designed
# from; the probe prints table shapes, first rows and embedded-data markers,
# never cookies or script bodies, and writes nothing.
hdr "[7] probe trade-analyzer-values"
DLF_VALUES_URL="${DLF_VALUES_URL:-https://dynastyleaguefootball.com/trade-analyzer-values/?l=sf_te_prem}"
set +e
(
  cd "${DIAG_DIR}"
  export DLF_USERNAME DLF_PASSWORD
  timeout 180 "${PY}" scripts/fetch_dlf.py --probe "${DLF_VALUES_URL}" 2>&1
) | scrub
rc=${PIPESTATUS[0]}
set -e
echo "probe_exit=${rc}"
echo
echo "=== done ==="
