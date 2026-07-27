#!/usr/bin/env bash
# Session-start health check for Risk It To Get The Brisket
# Runs automatically when a Claude Code session starts in this repo.
# Reports issues so Claude can fix them immediately.

set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

echo "=== SITE HEALTH CHECK ==="

# 1. Test collection (fast: ~1s)
# A session-start hook must be quick, so we run collection-only rather than the
# full suite. Collection catches the failure class worth catching at startup:
# missing dependencies and import errors (e.g. a missing httpx breaking
# TestClient). The full suite runs in CI/Linux, where it belongs — running it
# here would take ~10min and, on Windows, throw environment-only false
# positives (symlink privilege, /dev/null, cp1252 encoding).
# The exit code is isolated so `set -e`/`pipefail` can't abort the health check.
echo ""
echo "--- Test Collection ---"
COLLECT_OUT=$(python -m pytest tests/ -q --co 2>&1) && COLLECT_RC=0 || COLLECT_RC=$?
echo "$COLLECT_OUT" | tail -1
if (( COLLECT_RC != 0 )); then
  echo "ACTION NEEDED: pytest collection failed (rc $COLLECT_RC) — likely a missing dependency or import error:"
  echo "$COLLECT_OUT" | grep -iE "error|no module named|cannot import" | head -5
fi

# 2. Scrape data freshness
#
# This read filesystem mtime and called it data freshness. It was wrong in
# BOTH directions, which is how it got caught — see ORCHESTRATION.md §6.15.
# Remote sessions clone the repo fresh, so mtime is *checkout* time:
#
#   - A fresh clone stamps every file "now", so every source reads 0h and the
#     warning CANNOT FIRE even if the pipeline died months ago.
#   - A branch switch rewrites only differing files, so unchanged ones keep an
#     older mtime and read as stale. Measured 2026-07-27: idpTradeCalc.csv
#     reported 49h against a real content age of 131h, ktc.csv 0h against 3h.
#
# It also watched the wrong artifact. `exports/latest/site_raw/` is a raw
# mirror — `preflight.py::_seed_data_cache` copies `dynasty_data_*.json` and
# does NOT copy `site_raw/`, so the pipeline, the E2E suite and production all
# read the JSON. The mirror is written only by full scraper runs (the 2h cron
# handles ktc/ktcSfTep/idpTradeCalc with `stamp_if_present`, not
# `run_fetcher`), so it freezes for days with nothing wrong. §6.12 chased that
# exact false alarm at 03:05 and reached the same place.
#
# So the check reads `scrapeTimestamp` from the contract instead. It is an
# internal content stamp, so unlike mtime or commit dates it survives cloning
# and means the same thing everywhere. Per-source health is reported as
# coverage — how many players actually carry a value — which is what a dead
# source would change, and a line count would not.
#
# The probe is INLINE, not a sibling file, and that is deliberate. It first
# shipped as `.claude/freshness.py` — which `.gitignore:28` ignores, so
# `git add -A` silently skipped it and `main` got a hook invoking a file that
# did not exist. `health-check.sh` is a force-added exception to that ignore
# rule; anything new beside it is dropped without a word. A heredoc cannot be
# left behind by the next commit.
echo ""
echo "--- Data Freshness ---"
python - <<'PY' 2>&1 || echo "  UNKNOWN: freshness probe errored (see above)."
"""Read the artifact CONSUMERS read, not the raw-source mirror.

`scrapeTimestamp` is an internal content stamp, so unlike file mtime or
commit dates it survives cloning and means the same thing everywhere.

Every degraded input must land on UNKNOWN rather than a confident "0h" —
a probe that reports fresh when it cannot tell is the bug this replaced.
"""

import datetime as dt
import glob
import json


def threshold():
    try:
        with open("config/source_staleness.json", encoding="utf-8") as fh:
            return int(json.load(fh)["thresholds"].get("ktc", 24))
    except Exception:
        return 24


paths = sorted(glob.glob("exports/latest/dynasty_data_*.json"))
if not paths:
    print("  UNKNOWN: no exports/latest/dynasty_data_*.json — cannot measure.")
    raise SystemExit(0)

try:
    with open(paths[-1], encoding="utf-8") as fh:
        data = json.load(fh)
except Exception as exc:
    print(f"  UNKNOWN: could not read {paths[-1]}: {exc}")
    raise SystemExit(0)

stamp = data.get("scrapeTimestamp")
if not stamp:
    print("  UNKNOWN: contract carries no scrapeTimestamp — cannot measure.")
    raise SystemExit(0)

try:
    scraped = dt.datetime.fromisoformat(stamp)
except ValueError:
    print(f"  UNKNOWN: unparseable scrapeTimestamp {stamp!r}.")
    raise SystemExit(0)

now = dt.datetime.now(scraped.tzinfo) if scraped.tzinfo else dt.datetime.now()
age_h = (now - scraped).total_seconds() / 3600.0
limit = threshold()

print(f"  Contract: scraped {age_h:.0f}h ago (threshold {limit}h)")
if age_h > limit:
    print(f"  WARNING: no successful scrape in {age_h:.0f}h. Check scheduled-refresh workflow.")

players = data.get("players") or {}
stats = data.get("siteStats") or {}
for key in ("ktc", "idpTradeCalc"):
    entry = stats.get(key)
    if not entry:
        print(f"  {key}: ABSENT from siteStats — source produced nothing this run.")
        continue
    carried = sum(1 for p in players.values() if isinstance(p, dict) and p.get(key) is not None)
    print(f"  {key}: {entry.get('count')} values, carried by {carried} of {len(players)} players")
PY

# 3. Git status
echo ""
echo "--- Git Status ---"
BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
echo "  Branch: $BRANCH"
DIRTY=$(git status --porcelain --untracked-files=no 2>/dev/null | wc -l)
if (( DIRTY > 0 )); then
  echo "  WARNING: $DIRTY uncommitted tracked changes"
fi

# 4. Scraper syntax
echo ""
echo "--- Scraper Syntax ---"
if python -m py_compile "Dynasty Scraper.py" 2>/dev/null; then
  echo "  Dynasty Scraper.py: OK"
else
  echo "  Dynasty Scraper.py: SYNTAX ERROR - fix immediately"
fi
if python -m py_compile server.py 2>/dev/null; then
  echo "  server.py: OK"
else
  echo "  server.py: SYNTAX ERROR - fix immediately"
fi

echo ""
echo "=== HEALTH CHECK COMPLETE ==="
