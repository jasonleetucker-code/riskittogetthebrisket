#!/usr/bin/env bash
# Package-model market-ledger evaluation — read-only, on the production host.
#
# WHY THIS EXISTS
# ---------------
# PR #1833 (package Value Adjustment research, Phases 1-2) graded every
# package-model candidate against 1,121 public trades rebuilt inside a research
# container.  The production market-trade ledger
# (``data/market_trades/underlying_trades.sqlite``) holds the longer history,
# but it is box-local and gitignored, so the only place the candidates can be
# graded on the real archive is the production host.  The owner chose a
# controlled read-only server-side run without a deploy ("Option 2", master
# directive 2026-10-19 §11).  This is the host half of that run;
# ``.github/workflows/package-model-market-ledger.yml`` is the runner half.
#
# CONTRACT — READ-ONLY, PINNED, AGGREGATE-ONLY
# --------------------------------------------
# * Pinned code.  The workflow sends three research scripts as one base64 tar
#   in ``PAYLOAD_B64`` and their expected sha256 lines in ``PINS``, both from
#   the reviewed commit on ``main``.  Nothing runs unless every file matches.
#   Nothing is read from, or executed out of, the app tree except the app's own
#   Python interpreter and the deployed ``src/`` it imports.
# * One private temp dir.  The ONLY place this script writes is a fresh
#   ``mktemp -d`` directory, removed by the EXIT trap whatever happens.  It
#   never ``cd``s into the app dir, never touches a service, timer, store,
#   config, checkout or git state, and never restarts or reloads anything.
# * Python-level enforcement.  ``--market-ledger-only`` installs
#   ``scripts/research_readonly_guard.py`` (an irremovable CPython audit hook)
#   BEFORE any app import: no file write outside the guard's scratch dir, SQLite
#   read-only (``mode=ro``) only, no network, no subprocess, no bytecode.  Any
#   refused write or process start exits 3.
# * Bounded.  ``nice 19``, idle I/O class, a 30-minute wall clock and a 4 GiB
#   address-space cap, so the run cannot starve the live service.
# * Public output.  The repository is PUBLIC.  stdout is the script's
#   aggregate-only JSON (``assert_aggregate_only`` refuses identifier-like
#   content).  stderr is NEVER forwarded raw: it is captured inside the temp dir
#   and only its line count is reported, plus — on failure — code locations
#   and exception TYPES (never exception messages).
#
# Exit status is the evaluation's exit status (0 ok, 2 no ledger on this host,
# 3 the guard refused a write / process, 124 timeout, anything else = failure).
# The evaluation's status is never masked; the only ``|| true`` is on printing
# the failure diagnostics, after the status has been captured.

set -Eeuo pipefail
umask 077

APP_DIR="${APP_DIR:-/home/dynasty/trade-calculator}"
MAX_LAG_DAYS="${MAX_LAG_DAYS:-7}"
PAYLOAD_B64="${PAYLOAD_B64:-}"
PINS="${PINS:-}"

[[ "$MAX_LAG_DAYS" =~ ^[0-9]{1,2}$ ]] || { echo "MAX_LAG_DAYS must be an integer 0-99" >&2; exit 64; }
[[ -n "$PAYLOAD_B64" ]] || { echo "PAYLOAD_B64 is empty" >&2; exit 64; }
[[ -n "$PINS" ]] || { echo "PINS is empty" >&2; exit 64; }
[[ -d "$APP_DIR/src" ]] || { echo "APP_DIR has no src/" >&2; exit 64; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/package-model-ledger.XXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT
cd "$WORK"

# ── 1. unpack and verify the pinned research scripts ─────────────────────────
printf '%s' "$PAYLOAD_B64" | base64 -d | tar -xzf - -C "$WORK" --no-same-owner --no-same-permissions
printf '%s\n' "$PINS" > "$WORK/pins.sha256"
EXPECTED=(package_model_phase2_research.py package_model_hybrid_research.py research_readonly_guard.py)
for f in "${EXPECTED[@]}"; do
  grep -Eq "^[0-9a-f]{64}  ${f}\$" "$WORK/pins.sha256" || { echo "no pin for $f" >&2; exit 65; }
done
UNPACKED="$(find "$WORK" -mindepth 1 -maxdepth 1 -type f -name '*.py' | wc -l)"
[[ "$UNPACKED" -eq "${#EXPECTED[@]}" ]] || { echo "unexpected payload contents" >&2; exit 65; }
(cd "$WORK" && sha256sum --check --strict --quiet pins.sha256) >&2 || { echo "pinned sha256 mismatch" >&2; exit 65; }

# ── 2. the app's own interpreter, read-only ──────────────────────────────────
PY=/home/dynasty/.venvs/trade-calculator/bin/python
[[ -x "$PY" ]] || PY="$APP_DIR/.venv/bin/python"
[[ -x "$PY" ]] || { echo "no app interpreter found" >&2; exit 66; }

echo "host-utc   : $(date -u +%Y-%m-%dT%H:%M:%SZ)" >&2
echo "max-lag    : ${MAX_LAG_DAYS}d" >&2

# ── 3. run the evaluation (stdout = aggregate JSON; stderr captured) ─────────
set +e
(
  ulimit -v 4194304
  TMPDIR="$WORK" RISKIT_APP_DIR="$APP_DIR" PYTHONDONTWRITEBYTECODE=1 \
    timeout --signal=TERM --kill-after=30 1800 \
    nice -n 19 ionice -c3 \
    "$PY" -B "$WORK/package_model_phase2_research.py" \
    --market-ledger-only --max-lag-days "$MAX_LAG_DAYS"
) 2> "$WORK/stderr.log"
STATUS=$?
set -e

LINES="$(wc -l < "$WORK/stderr.log")"
echo "evaluation exit=${STATUS} stderr-lines=${LINES}" >&2
if [[ "$STATUS" -ne 0 ]]; then
  # Code locations and exception TYPES only — never a message, which could
  # carry a league / manager / asset identifier into a public log.
  echo "--- stderr structure (code locations + exception types only) ---" >&2
  grep -E '^\s*File "[^"]*", line [0-9]+|^[A-Za-z_][A-Za-z0-9_.]*(Error|Exception|Exit|Interrupt|Warning)\b' "$WORK/stderr.log" \
    | tail -n 25 \
    | sed -E 's#File "[^"]*/([^/"]+)"#File "\1"#; s/^([A-Za-z_][A-Za-z0-9_.]*)(:.*)?$/\1/; s/[0-9]{6,}/<n>/g' >&2 || true
fi
exit "$STATUS"
