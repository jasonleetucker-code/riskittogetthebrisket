#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# scripts/setup.sh — one-command environment bootstrap.
#
# Reproduces the CI install path locally so a brand-new machine can
# run the tests identically to GitHub Actions:
#
#     ./scripts/setup.sh
#     make test          # (or: .venv/bin/python -m pytest tests/ -q)
#
# Behaviour:
#   * Creates ``.venv/`` if it does not exist (virtualenv isolation so
#     nothing leaks into / relies on a globally-installed package).
#   * Upgrades pip inside the venv.
#   * Installs ``requirements-dev.txt`` — which chains ``requirements.txt``
#     via ``-r`` — so runtime AND test deps always install together.
#   * Runs ``pip check`` to fail fast on conflicting pins.
#   * Runs ``scripts/check_env.py`` to confirm every expected module
#     imports.  This is the same preflight CI uses, so a green local
#     setup guarantees CI will not fall over on missing deps.
#
# Options (via env vars):
#   VENV_DIR         defaults to "${REPO_ROOT}/.venv"
#   PYTHON           python executable used to create the venv
#                    (default: python3)
#   SKIP_PLAYWRIGHT  set to 1 to skip the ``playwright install`` step
#                    (downloads Chromium ~170MB; irrelevant for unit
#                    tests but needed for the scraper runtime)
# ──────────────────────────────────────────────────────────────────────

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${VENV_DIR:-${REPO_ROOT}/.venv}"
PYTHON_BIN="${PYTHON:-python3}"

log() { printf '[setup] %s\n' "$*"; }
err() { printf '[setup][ERROR] %s\n' "$*" >&2; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    err "Required command not found: $1"
    exit 1
  }
}

require_cmd "${PYTHON_BIN}"

cd "${REPO_ROOT}"

if [[ ! -f requirements.txt ]]; then
  err "requirements.txt missing — are you running from the repo root?"
  exit 1
fi
if [[ ! -f requirements-dev.txt ]]; then
  err "requirements-dev.txt missing — aborting setup to avoid partial install."
  exit 1
fi

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  log "Creating virtualenv at ${VENV_DIR} (python=${PYTHON_BIN})"
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
else
  log "Reusing existing virtualenv at ${VENV_DIR}"
fi

VENV_PY="${VENV_DIR}/bin/python"
VENV_PIP="${VENV_DIR}/bin/pip"

log "Upgrading pip inside venv"
"${VENV_PY}" -m pip install --upgrade pip

log "Installing runtime + dev deps from requirements-dev.txt"
"${VENV_PIP}" install -r requirements-dev.txt

log "Running ``pip check`` to detect conflicting dependency pins"
"${VENV_PIP}" check

if [[ "${SKIP_PLAYWRIGHT:-0}" != "1" ]]; then
  log "Installing Playwright Chromium browser (set SKIP_PLAYWRIGHT=1 to skip)"
  "${VENV_PY}" -m playwright install chromium || {
    err "Playwright browser install failed — scraper paths may not work."
    err "Unit tests do not require a browser; continuing anyway."
  }
fi

log "Running preflight import check"
"${VENV_PY}" "${REPO_ROOT}/scripts/check_env.py"

log "Done.  Activate the venv with:  source ${VENV_DIR}/bin/activate"
log "Then run tests with:             python -m pytest tests/ -q"
