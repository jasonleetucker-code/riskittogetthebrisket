#!/usr/bin/env bash
# B7.0 preflight evidence — scoring-snapshot authority and canonical
# board-history recorder state, read from the production host.
#
# WHY THIS EXISTS
# ---------------
# B6 (#810, W18-F001) made cross-league ranking reuse a FACT decided by
# ``scoring_fingerprint`` over each league's actual Sleeper scoring card.
# The card is stored per league at ``data/leagues/scoring_<id>.json``,
# refreshed OFF the request path by the post-scrape warm pass.
# ``docs/EXECUTION_PLAN.md`` records that snapshot as an operational
# requirement — and nothing verifies it.  From outside the host the
# state is genuinely unobservable: ``data/leagues/`` is gitignored and
# is not among the paths ``scheduled-refresh.yml`` force-adds, and both
# fail-closed branches ("proven different" and "no verified snapshot")
# produce the identical public response.
#
# It also answers a second question with the same SSH round-trip: is the
# canonical board-history recorder actually running?  ``board_store.py``
# states that every day it is not running is evidence that cannot be
# recovered later, and its own docstring names the failure mode this
# checks for — "nine timer pairs shipped, two installed, and a deploy
# that reported success the whole time".
#
# CONTRACT
# --------
# Stages 1-3 are READ-ONLY.  They stat files, parse JSON with the
# standard library, ask systemd for unit properties, and open the
# history DB read-only.  They do not restart or reload anything, do not
# deploy or checkout, do not write to the app tree, do not import the
# application, and never print a credential.
#
# Stage 4 is DIFFERENT and is opt-in.  ``b6_validate.py`` REFRESHES the
# scoring snapshots as a side effect, so it would destroy the very
# mtimes stage 1 exists to record.  It therefore runs LAST, only when
# RUN_VALIDATOR=1, and stage 1's output is the authoritative "before"
# evidence regardless.
#
# Exit status is the step's exit status; no stage is allowed to mask a
# failure with ``|| true``.

set -Eeuo pipefail

APP_DIR="${APP_DIR:-/home/dynasty/trade-calculator}"
SERVICE_NAME="${SERVICE_NAME:-dynasty}"
RUN_VALIDATOR="${RUN_VALIDATOR:-0}"

echo "=== B7.0 scoring-snapshot + board-history inventory ==="
echo "host      : $(hostname)"
echo "utc       : $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "app_dir   : ${APP_DIR}"
echo "service   : ${SERVICE_NAME}"
echo "validator : ${RUN_VALIDATOR}"
echo

if [[ ! -d "${APP_DIR}" ]]; then
  echo "FATAL: APP_DIR does not exist: ${APP_DIR}" >&2
  exit 2
fi
cd "${APP_DIR}"

# Prefer the app's own interpreter; fall back to the system one.  Only
# the standard library is used, so either works.
PY=""
for candidate in "${APP_DIR}/.venv/bin/python" "${APP_DIR}/venv/bin/python" python3; do
  if command -v "${candidate}" >/dev/null 2>&1 || [[ -x "${candidate}" ]]; then
    PY="${candidate}"
    break
  fi
done
if [[ -z "${PY}" ]]; then
  echo "FATAL: no python interpreter found" >&2
  exit 2
fi
echo "python    : ${PY} ($("${PY}" -V 2>&1))"
echo

# ---------------------------------------------------------------- 1 --
# Scoring snapshots, read BEFORE anything can refresh them.
echo "--- [1] scoring snapshots (pre-read, no refresh) ---"
"${PY}" - <<'PYEOF'
import json, os, time
from pathlib import Path

ROOT = Path.cwd()
reg_path = ROOT / "config" / "leagues" / "registry.json"
snap_dir = ROOT / "data" / "leagues"

# The budget B6 derived (SCRAPE_INTERVAL_HOURS * 3, and the existing
# _SOURCE_MAX_AGE_HOURS default).  Hard-coded here rather than imported
# so this stage never touches application code.
MAX_AGE_HOURS = 6.0

print(f"snapshot dir      : {snap_dir}  exists={snap_dir.is_dir()}")
if snap_dir.is_dir():
    files = sorted(p.name for p in snap_dir.iterdir() if p.is_file())
    print(f"files present     : {files or '(none)'}")
print()

if not reg_path.is_file():
    print("FATAL: registry not found")
    raise SystemExit(2)

reg = json.loads(reg_path.read_text(encoding="utf-8"))
now = time.time()

for lg in reg.get("leagues", []):
    if not lg.get("active", True):
        continue
    key = lg.get("key")
    lid = str(lg.get("sleeperLeagueId") or "")
    path = snap_dir / f"scoring_{lid}.json"
    print(f"league            : {key}")
    print(f"  scoringProfile  : {lg.get('scoringProfile')}")
    print(f"  sleeperLeagueId : {lid}")
    print(f"  snapshot path   : {path}")
    if not path.is_file():
        print("  STATE           : MISSING  <-- fails closed; cross-league reuse refused")
        print()
        continue
    st = path.stat()
    age_h = (now - st.st_mtime) / 3600.0
    print(f"  mtime (utc)     : {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(st.st_mtime))}")
    print(f"  age             : {age_h:.2f} h   (budget {MAX_AGE_HOURS:.1f} h)")
    print(f"  size            : {st.st_size} bytes")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"  STATE           : UNREADABLE ({type(exc).__name__}: {exc})")
        print()
        continue
    card = doc.get("scoringSettings") or {}
    nonzero = sum(
        1 for v in card.values()
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0
    )
    print(f"  leagueKey       : {doc.get('leagueKey')}")
    print(f"  leagueName      : {doc.get('leagueName')}")
    print(f"  season          : {doc.get('season')}")
    print(f"  fetchedAt       : {doc.get('fetchedAt')}")
    print(f"  fingerprint     : {doc.get('scoringFingerprint')}")
    print(f"  scoring keys    : {len(card)} total / {nonzero} nonzero")
    # Age is only one of the two staleness axes; season is the other and
    # this stage cannot resolve the current NFL season without network.
    print(f"  age verdict     : {'FRESH' if age_h <= MAX_AGE_HOURS else 'STALE (age)'}")
    print()
PYEOF
echo

# ---------------------------------------------------------------- 2 --
echo "--- [2] canonical board-history recorder ---"
SNAP_TIMER="${SERVICE_NAME}-board-snapshot.timer"
SNAP_SERVICE="${SERVICE_NAME}-board-snapshot.service"
for unit in "${SNAP_TIMER}" "${SNAP_SERVICE}"; do
  echo "unit: ${unit}"
  if systemctl cat "${unit}" >/dev/null 2>&1; then
    echo "  installed     : yes"
    echo "  is-enabled    : $(systemctl is-enabled "${unit}" 2>&1 || true)"
    echo "  is-active     : $(systemctl is-active "${unit}" 2>&1 || true)"
    systemctl show "${unit}" \
      -p LastTriggerUSec -p NextElapseUSecRealtime -p Result -p ExecMainStatus \
      2>/dev/null | sed 's/^/  /' || true
  else
    echo "  installed     : NO  <-- recorder is not scheduled; history is not accumulating"
  fi
done
echo

# ---------------------------------------------------------------- 3 --
echo "--- [3] board_history.sqlite coverage (read-only) ---"
"${PY}" - <<'PYEOF'
import sqlite3
from pathlib import Path

db = Path.cwd() / "data" / "board_history.sqlite"
print(f"db path : {db}")
if not db.is_file():
    print("STATE   : MISSING  <-- no canonical-scale history exists yet")
    raise SystemExit(0)
print(f"size    : {db.stat().st_size} bytes")
# Read-only URI so this stage cannot create or migrate anything.
conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5.0)
try:
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    print(f"tables  : {tables}")
    if "board_history" in tables:
        n, days, first, last = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT as_of), MIN(as_of), MAX(as_of) "
            "FROM board_history"
        ).fetchone()
        print(f"rows    : {n}")
        print(f"days    : {days}   range {first} .. {last}")
        for as_of, cnt in conn.execute(
            "SELECT as_of, COUNT(*) FROM board_history "
            "GROUP BY as_of ORDER BY as_of DESC LIMIT 10"
        ):
            print(f"  {as_of}  {cnt} rows")
finally:
    conn.close()
PYEOF
echo

# ---------------------------------------------------------------- 4 --
if [[ "${RUN_VALIDATOR}" == "1" ]]; then
  echo "--- [4] b6_validate.py (REFRESHES SNAPSHOTS — runs last by design) ---"
  if [[ -f docs/master-site-audit/evidence/W18/b6_validate.py ]]; then
    "${PY}" docs/master-site-audit/evidence/W18/b6_validate.py
  else
    echo "validator not present at this deployed revision; skipped"
  fi
else
  echo "--- [4] b6_validate.py SKIPPED (RUN_VALIDATOR != 1) ---"
  echo "stage 1 above is the pre-refresh evidence."
fi

echo
echo "=== inventory complete ==="
