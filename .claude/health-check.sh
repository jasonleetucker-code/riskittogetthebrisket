#!/usr/bin/env bash
# Session-start health check for Risk It To Get The Brisket
# Runs automatically when a Claude Code session starts in this repo.
# Reports issues so Claude can fix them immediately.

set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

echo "=== SITE HEALTH CHECK ==="

# 0. Agent/work router
#
# The user used to have to paste a large continuation prompt at the start of
# every long-running session just to restate process, ownership and the active
# completion contract.  That is harness state, not user intent.  Keep this
# output short and deterministic: point Claude at the canonical operating
# layer and mechanically surface the active fixed-denominator launch contract.
echo ""
echo "=== AGENT ROUTER ==="
echo "  Read: docs/AGENT_OPERATING_SYSTEM.md"
echo "  Product authority: docs/EXECUTION_PLAN.md + any active owner-authorized contract"
echo "  Coordination: ASSISTANT_COORDINATION.md + docs/WORK_CLAIMS.md"

LAUNCH_CONTRACT="docs/season-launch/WEEK_1_LAUNCH_CONTRACT.md"
if [[ -f "$LAUNCH_CONTRACT" ]]; then
  LAUNCH_TOTAL=$(grep -cE '^\| W1-[0-9][0-9] .*\| (VERIFIED|IMPLEMENTED_UNVERIFIED|IN PROGRESS|NOT STARTED|BLOCKED) \|
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
# internal content stamp, so unlike mtime it survives cloning. Per-source
# health is reported as coverage — how many players actually carry a value —
# which is what a dead source would change, and a line count would not.
#
# But it is CHECKOUT-RELATIVE, and that is not the same as "means the same
# thing everywhere", which is what this comment used to claim. The stamp is
# the content age of whatever commit is checked out. So the mtime probe's
# SECOND failure direction — "fires falsely on a stale branch" — survived the
# rewrite in a new shape: not "unchanged file keeps an old mtime" but "old
# branch keeps an old contract".
#
# Demonstrated 2026-08-04: a session on a 4-day-old branch reported
# `102h ago` and told the reader to go check `scheduled-refresh`, which was
# 30/30 green and had committed data 40 minutes earlier. §6.15 names this
# very file as instance 5 of "a guard that cannot fire" and records that it
# failed in BOTH directions; the 07-27 rewrite closed one of them and left
# this comment asserting it had closed both.
#
# Hence the branch-position check below. It narrows only the ATTRIBUTION —
# the age line is unchanged and the warning still fires at full strength on
# an up-to-date checkout, because that case is a real pipeline signal.
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

`scrapeTimestamp` is an internal content stamp, so unlike file mtime it
survives cloning. It is CHECKOUT-RELATIVE though: it dates the commit you
have, not the pipeline. `main_contract_age_h()` exists to tell those
apart — it reads origin/main's contract, because that measures the
PIPELINE, which a commit count does not.

Every degraded input must land on UNKNOWN rather than a confident "0h" —
a probe that reports fresh when it cannot tell is the bug this replaced.
"""

import datetime as dt
import glob
import json
import subprocess


def threshold():
    try:
        with open("config/source_staleness.json", encoding="utf-8") as fh:
            return int(json.load(fh)["thresholds"].get("ktc", 24))
    except Exception:
        return 24


def _git(*args):
    """Run git, returning stdout or None on ANY failure.

    Reads refs already on disk — no network, so a SessionStart hook never
    waits on a fetch. None covers no git, not a repo, missing ref, timeout.
    """
    try:
        out = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=5
        )
    except Exception:
        return None
    return out.stdout if out.returncode == 0 else None


def local_main_ref_age_h():
    """Age of the local `origin/main` REF itself, or None if unreadable.

    `_git` reads refs already on disk and never fetches, so `origin/main`
    here is whatever this checkout last saw — not what GitHub holds. A ref
    that is itself old is not evidence about the pipeline in EITHER
    direction, which is the half this block originally missed.
    """
    out = _git("log", "-1", "--format=%cI", "origin/main")
    if not out or not out.strip():
        return None
    try:
        committed = dt.datetime.fromisoformat(out.strip())
    except ValueError:
        return None
    now_ = dt.datetime.now(committed.tzinfo) if committed.tzinfo else dt.datetime.now()
    return (now_ - committed).total_seconds() / 3600.0


def main_contract_age_h(limit):
    """Age of the contract on `origin/main`, or None if it cannot be read.

    This — not "how many commits behind am I" — is the predicate that
    distinguishes a stale CHECKOUT from a stale PIPELINE. A commit count
    cannot: one commit behind with a genuinely dead pipeline would still
    look like a branch artifact, and the note would confidently give the
    wrong cause. That is the exact defect this whole block exists to fix,
    so it must not be reintroduced in miniature.

    But the ref is only evidence if the ref is CURRENT. On 2026-09-05 this
    checkout's `origin/main` was ~38h stale and never fetched, so this
    function read a 38h-old contract off it and the caller printed
    "origin/main's contract is 38h old too — not a branch artifact" — a
    confident pipeline-outage claim while production and real `main` were
    both ~1h fresh. It cost a full incident response.
    (docs/ops/INCIDENT_2026-09-05_FLOCK_ROOKIE_FLOOR.md)

    So a ref older than the freshness budget answers None. The file's own
    rule — "an unproven excuse must never silence a real alarm" — has a
    converse, and this is it: an unproven ref must not raise a false one.

    None on any failure, and the caller treats None as "cannot tell" and
    keeps the original warning.
    """
    ref_age = local_main_ref_age_h()
    if ref_age is None or ref_age > limit:
        return None
    listing = _git("ls-tree", "--name-only", "origin/main", "exports/latest/")
    if listing is None:
        return None
    names = sorted(
        n for n in listing.split("\n") if n.startswith("exports/latest/dynasty_data_")
    )
    if not names:
        return None
    blob = _git("show", f"origin/main:{names[-1]}")
    if blob is None:
        return None
    try:
        stamp_ = json.loads(blob).get("scrapeTimestamp")
        scraped_ = dt.datetime.fromisoformat(stamp_)
    except Exception:
        return None
    now_ = dt.datetime.now(scraped_.tzinfo) if scraped_.tzinfo else dt.datetime.now()
    return (now_ - scraped_).total_seconds() / 3600.0


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
    # Attribute the staleness before blaming the pipeline: ask what the
    # contract on origin/main looks like. Fresh there means this checkout is
    # simply old, and "check scheduled-refresh" would send the reader after a
    # workflow that is fine. Stale there means the pipeline really has
    # stopped, and the warning stands.
    #
    # Only a KNOWN-FRESH main redirects. None (cannot tell) falls through to
    # the warning — the guard must keep firing whenever the excuse is
    # unproven.
    main_age = main_contract_age_h(limit)
    if main_age is not None and main_age <= limit:
        print(
            f"  NOTE: origin/main's contract is {main_age:.0f}h old — the pipeline is "
            f"fine; this is the age of the checked-out branch."
        )
    else:
        print(f"  WARNING: no successful scrape in {age_h:.0f}h. Check scheduled-refresh workflow.")
        if main_age is not None:
            print(f"  (origin/main's contract is {main_age:.0f}h old too — not a branch artifact.)")
        else:
            # Say WHY it is unattributed instead of implying the pipeline.
            # This hook never fetches, so a stale local ref is the common case.
            print(
                "  (Cause NOT attributed: this checkout's origin/main ref is itself "
                "stale or unreadable, so it proves nothing either way. Run "
                "`git fetch origin main` and re-check before treating this as an outage.)"
            )

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
 "$LAUNCH_CONTRACT" || true)
  LAUNCH_VERIFIED=$(grep -cE '^\| W1-[0-9][0-9] .*\| VERIFIED \|
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
# internal content stamp, so unlike mtime it survives cloning. Per-source
# health is reported as coverage — how many players actually carry a value —
# which is what a dead source would change, and a line count would not.
#
# But it is CHECKOUT-RELATIVE, and that is not the same as "means the same
# thing everywhere", which is what this comment used to claim. The stamp is
# the content age of whatever commit is checked out. So the mtime probe's
# SECOND failure direction — "fires falsely on a stale branch" — survived the
# rewrite in a new shape: not "unchanged file keeps an old mtime" but "old
# branch keeps an old contract".
#
# Demonstrated 2026-08-04: a session on a 4-day-old branch reported
# `102h ago` and told the reader to go check `scheduled-refresh`, which was
# 30/30 green and had committed data 40 minutes earlier. §6.15 names this
# very file as instance 5 of "a guard that cannot fire" and records that it
# failed in BOTH directions; the 07-27 rewrite closed one of them and left
# this comment asserting it had closed both.
#
# Hence the branch-position check below. It narrows only the ATTRIBUTION —
# the age line is unchanged and the warning still fires at full strength on
# an up-to-date checkout, because that case is a real pipeline signal.
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

`scrapeTimestamp` is an internal content stamp, so unlike file mtime it
survives cloning. It is CHECKOUT-RELATIVE though: it dates the commit you
have, not the pipeline. `main_contract_age_h()` exists to tell those
apart — it reads origin/main's contract, because that measures the
PIPELINE, which a commit count does not.

Every degraded input must land on UNKNOWN rather than a confident "0h" —
a probe that reports fresh when it cannot tell is the bug this replaced.
"""

import datetime as dt
import glob
import json
import subprocess


def threshold():
    try:
        with open("config/source_staleness.json", encoding="utf-8") as fh:
            return int(json.load(fh)["thresholds"].get("ktc", 24))
    except Exception:
        return 24


def _git(*args):
    """Run git, returning stdout or None on ANY failure.

    Reads refs already on disk — no network, so a SessionStart hook never
    waits on a fetch. None covers no git, not a repo, missing ref, timeout.
    """
    try:
        out = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=5
        )
    except Exception:
        return None
    return out.stdout if out.returncode == 0 else None


def local_main_ref_age_h():
    """Age of the local `origin/main` REF itself, or None if unreadable.

    `_git` reads refs already on disk and never fetches, so `origin/main`
    here is whatever this checkout last saw — not what GitHub holds. A ref
    that is itself old is not evidence about the pipeline in EITHER
    direction, which is the half this block originally missed.
    """
    out = _git("log", "-1", "--format=%cI", "origin/main")
    if not out or not out.strip():
        return None
    try:
        committed = dt.datetime.fromisoformat(out.strip())
    except ValueError:
        return None
    now_ = dt.datetime.now(committed.tzinfo) if committed.tzinfo else dt.datetime.now()
    return (now_ - committed).total_seconds() / 3600.0


def main_contract_age_h(limit):
    """Age of the contract on `origin/main`, or None if it cannot be read.

    This — not "how many commits behind am I" — is the predicate that
    distinguishes a stale CHECKOUT from a stale PIPELINE. A commit count
    cannot: one commit behind with a genuinely dead pipeline would still
    look like a branch artifact, and the note would confidently give the
    wrong cause. That is the exact defect this whole block exists to fix,
    so it must not be reintroduced in miniature.

    But the ref is only evidence if the ref is CURRENT. On 2026-09-05 this
    checkout's `origin/main` was ~38h stale and never fetched, so this
    function read a 38h-old contract off it and the caller printed
    "origin/main's contract is 38h old too — not a branch artifact" — a
    confident pipeline-outage claim while production and real `main` were
    both ~1h fresh. It cost a full incident response.
    (docs/ops/INCIDENT_2026-09-05_FLOCK_ROOKIE_FLOOR.md)

    So a ref older than the freshness budget answers None. The file's own
    rule — "an unproven excuse must never silence a real alarm" — has a
    converse, and this is it: an unproven ref must not raise a false one.

    None on any failure, and the caller treats None as "cannot tell" and
    keeps the original warning.
    """
    ref_age = local_main_ref_age_h()
    if ref_age is None or ref_age > limit:
        return None
    listing = _git("ls-tree", "--name-only", "origin/main", "exports/latest/")
    if listing is None:
        return None
    names = sorted(
        n for n in listing.split("\n") if n.startswith("exports/latest/dynasty_data_")
    )
    if not names:
        return None
    blob = _git("show", f"origin/main:{names[-1]}")
    if blob is None:
        return None
    try:
        stamp_ = json.loads(blob).get("scrapeTimestamp")
        scraped_ = dt.datetime.fromisoformat(stamp_)
    except Exception:
        return None
    now_ = dt.datetime.now(scraped_.tzinfo) if scraped_.tzinfo else dt.datetime.now()
    return (now_ - scraped_).total_seconds() / 3600.0


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
    # Attribute the staleness before blaming the pipeline: ask what the
    # contract on origin/main looks like. Fresh there means this checkout is
    # simply old, and "check scheduled-refresh" would send the reader after a
    # workflow that is fine. Stale there means the pipeline really has
    # stopped, and the warning stands.
    #
    # Only a KNOWN-FRESH main redirects. None (cannot tell) falls through to
    # the warning — the guard must keep firing whenever the excuse is
    # unproven.
    main_age = main_contract_age_h(limit)
    if main_age is not None and main_age <= limit:
        print(
            f"  NOTE: origin/main's contract is {main_age:.0f}h old — the pipeline is "
            f"fine; this is the age of the checked-out branch."
        )
    else:
        print(f"  WARNING: no successful scrape in {age_h:.0f}h. Check scheduled-refresh workflow.")
        if main_age is not None:
            print(f"  (origin/main's contract is {main_age:.0f}h old too — not a branch artifact.)")
        else:
            # Say WHY it is unattributed instead of implying the pipeline.
            # This hook never fetches, so a stale local ref is the common case.
            print(
                "  (Cause NOT attributed: this checkout's origin/main ref is itself "
                "stale or unreadable, so it proves nothing either way. Run "
                "`git fetch origin main` and re-check before treating this as an outage.)"
            )

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
 "$LAUNCH_CONTRACT" || true)
  if [[ "$LAUNCH_TOTAL" =~ ^[0-9]+$ ]] && [[ "$LAUNCH_VERIFIED" =~ ^[0-9]+$ ]] && (( LAUNCH_TOTAL > 0 )); then
    if (( LAUNCH_VERIFIED < LAUNCH_TOTAL )); then
      echo "  ACTIVE: $LAUNCH_CONTRACT — $LAUNCH_VERIFIED/$LAUNCH_TOTAL literal VERIFIED"
      echo "  Keep V1 closed; do not begin broad V2 while this authorized launch tranche is incomplete."
      echo "  Rows needing attention:"
      grep -E '^\| W1-[0-9][0-9] .*\| (BLOCKED|IN PROGRESS|IMPLEMENTED_UNVERIFIED) \|
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
# internal content stamp, so unlike mtime it survives cloning. Per-source
# health is reported as coverage — how many players actually carry a value —
# which is what a dead source would change, and a line count would not.
#
# But it is CHECKOUT-RELATIVE, and that is not the same as "means the same
# thing everywhere", which is what this comment used to claim. The stamp is
# the content age of whatever commit is checked out. So the mtime probe's
# SECOND failure direction — "fires falsely on a stale branch" — survived the
# rewrite in a new shape: not "unchanged file keeps an old mtime" but "old
# branch keeps an old contract".
#
# Demonstrated 2026-08-04: a session on a 4-day-old branch reported
# `102h ago` and told the reader to go check `scheduled-refresh`, which was
# 30/30 green and had committed data 40 minutes earlier. §6.15 names this
# very file as instance 5 of "a guard that cannot fire" and records that it
# failed in BOTH directions; the 07-27 rewrite closed one of them and left
# this comment asserting it had closed both.
#
# Hence the branch-position check below. It narrows only the ATTRIBUTION —
# the age line is unchanged and the warning still fires at full strength on
# an up-to-date checkout, because that case is a real pipeline signal.
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

`scrapeTimestamp` is an internal content stamp, so unlike file mtime it
survives cloning. It is CHECKOUT-RELATIVE though: it dates the commit you
have, not the pipeline. `main_contract_age_h()` exists to tell those
apart — it reads origin/main's contract, because that measures the
PIPELINE, which a commit count does not.

Every degraded input must land on UNKNOWN rather than a confident "0h" —
a probe that reports fresh when it cannot tell is the bug this replaced.
"""

import datetime as dt
import glob
import json
import subprocess


def threshold():
    try:
        with open("config/source_staleness.json", encoding="utf-8") as fh:
            return int(json.load(fh)["thresholds"].get("ktc", 24))
    except Exception:
        return 24


def _git(*args):
    """Run git, returning stdout or None on ANY failure.

    Reads refs already on disk — no network, so a SessionStart hook never
    waits on a fetch. None covers no git, not a repo, missing ref, timeout.
    """
    try:
        out = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=5
        )
    except Exception:
        return None
    return out.stdout if out.returncode == 0 else None


def local_main_ref_age_h():
    """Age of the local `origin/main` REF itself, or None if unreadable.

    `_git` reads refs already on disk and never fetches, so `origin/main`
    here is whatever this checkout last saw — not what GitHub holds. A ref
    that is itself old is not evidence about the pipeline in EITHER
    direction, which is the half this block originally missed.
    """
    out = _git("log", "-1", "--format=%cI", "origin/main")
    if not out or not out.strip():
        return None
    try:
        committed = dt.datetime.fromisoformat(out.strip())
    except ValueError:
        return None
    now_ = dt.datetime.now(committed.tzinfo) if committed.tzinfo else dt.datetime.now()
    return (now_ - committed).total_seconds() / 3600.0


def main_contract_age_h(limit):
    """Age of the contract on `origin/main`, or None if it cannot be read.

    This — not "how many commits behind am I" — is the predicate that
    distinguishes a stale CHECKOUT from a stale PIPELINE. A commit count
    cannot: one commit behind with a genuinely dead pipeline would still
    look like a branch artifact, and the note would confidently give the
    wrong cause. That is the exact defect this whole block exists to fix,
    so it must not be reintroduced in miniature.

    But the ref is only evidence if the ref is CURRENT. On 2026-09-05 this
    checkout's `origin/main` was ~38h stale and never fetched, so this
    function read a 38h-old contract off it and the caller printed
    "origin/main's contract is 38h old too — not a branch artifact" — a
    confident pipeline-outage claim while production and real `main` were
    both ~1h fresh. It cost a full incident response.
    (docs/ops/INCIDENT_2026-09-05_FLOCK_ROOKIE_FLOOR.md)

    So a ref older than the freshness budget answers None. The file's own
    rule — "an unproven excuse must never silence a real alarm" — has a
    converse, and this is it: an unproven ref must not raise a false one.

    None on any failure, and the caller treats None as "cannot tell" and
    keeps the original warning.
    """
    ref_age = local_main_ref_age_h()
    if ref_age is None or ref_age > limit:
        return None
    listing = _git("ls-tree", "--name-only", "origin/main", "exports/latest/")
    if listing is None:
        return None
    names = sorted(
        n for n in listing.split("\n") if n.startswith("exports/latest/dynasty_data_")
    )
    if not names:
        return None
    blob = _git("show", f"origin/main:{names[-1]}")
    if blob is None:
        return None
    try:
        stamp_ = json.loads(blob).get("scrapeTimestamp")
        scraped_ = dt.datetime.fromisoformat(stamp_)
    except Exception:
        return None
    now_ = dt.datetime.now(scraped_.tzinfo) if scraped_.tzinfo else dt.datetime.now()
    return (now_ - scraped_).total_seconds() / 3600.0


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
    # Attribute the staleness before blaming the pipeline: ask what the
    # contract on origin/main looks like. Fresh there means this checkout is
    # simply old, and "check scheduled-refresh" would send the reader after a
    # workflow that is fine. Stale there means the pipeline really has
    # stopped, and the warning stands.
    #
    # Only a KNOWN-FRESH main redirects. None (cannot tell) falls through to
    # the warning — the guard must keep firing whenever the excuse is
    # unproven.
    main_age = main_contract_age_h(limit)
    if main_age is not None and main_age <= limit:
        print(
            f"  NOTE: origin/main's contract is {main_age:.0f}h old — the pipeline is "
            f"fine; this is the age of the checked-out branch."
        )
    else:
        print(f"  WARNING: no successful scrape in {age_h:.0f}h. Check scheduled-refresh workflow.")
        if main_age is not None:
            print(f"  (origin/main's contract is {main_age:.0f}h old too — not a branch artifact.)")
        else:
            # Say WHY it is unattributed instead of implying the pipeline.
            # This hook never fetches, so a stale local ref is the common case.
            print(
                "  (Cause NOT attributed: this checkout's origin/main ref is itself "
                "stale or unreadable, so it proves nothing either way. Run "
                "`git fetch origin main` and re-check before treating this as an outage.)"
            )

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
 "$LAUNCH_CONTRACT" \
        | sed 's/^/    /' | head -8 || true
    else
      echo "  COMPLETE: $LAUNCH_CONTRACT — $LAUNCH_VERIFIED/$LAUNCH_TOTAL VERIFIED"
      echo "  Do not continue the launch-completion campaign; route from current docs/EXECUTION_PLAN.md."
    fi
  else
    echo "  WARNING: Week 1 contract exists but its row/status shape could not be counted mechanically."
  fi
else
  echo "  No Week 1 fixed-denominator contract found; route from current docs/EXECUTION_PLAN.md."
fi
echo "=== END AGENT ROUTER ==="

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
# internal content stamp, so unlike mtime it survives cloning. Per-source
# health is reported as coverage — how many players actually carry a value —
# which is what a dead source would change, and a line count would not.
#
# But it is CHECKOUT-RELATIVE, and that is not the same as "means the same
# thing everywhere", which is what this comment used to claim. The stamp is
# the content age of whatever commit is checked out. So the mtime probe's
# SECOND failure direction — "fires falsely on a stale branch" — survived the
# rewrite in a new shape: not "unchanged file keeps an old mtime" but "old
# branch keeps an old contract".
#
# Demonstrated 2026-08-04: a session on a 4-day-old branch reported
# `102h ago` and told the reader to go check `scheduled-refresh`, which was
# 30/30 green and had committed data 40 minutes earlier. §6.15 names this
# very file as instance 5 of "a guard that cannot fire" and records that it
# failed in BOTH directions; the 07-27 rewrite closed one of them and left
# this comment asserting it had closed both.
#
# Hence the branch-position check below. It narrows only the ATTRIBUTION —
# the age line is unchanged and the warning still fires at full strength on
# an up-to-date checkout, because that case is a real pipeline signal.
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

`scrapeTimestamp` is an internal content stamp, so unlike file mtime it
survives cloning. It is CHECKOUT-RELATIVE though: it dates the commit you
have, not the pipeline. `main_contract_age_h()` exists to tell those
apart — it reads origin/main's contract, because that measures the
PIPELINE, which a commit count does not.

Every degraded input must land on UNKNOWN rather than a confident "0h" —
a probe that reports fresh when it cannot tell is the bug this replaced.
"""

import datetime as dt
import glob
import json
import subprocess


def threshold():
    try:
        with open("config/source_staleness.json", encoding="utf-8") as fh:
            return int(json.load(fh)["thresholds"].get("ktc", 24))
    except Exception:
        return 24


def _git(*args):
    """Run git, returning stdout or None on ANY failure.

    Reads refs already on disk — no network, so a SessionStart hook never
    waits on a fetch. None covers no git, not a repo, missing ref, timeout.
    """
    try:
        out = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=5
        )
    except Exception:
        return None
    return out.stdout if out.returncode == 0 else None


def local_main_ref_age_h():
    """Age of the local `origin/main` REF itself, or None if unreadable.

    `_git` reads refs already on disk and never fetches, so `origin/main`
    here is whatever this checkout last saw — not what GitHub holds. A ref
    that is itself old is not evidence about the pipeline in EITHER
    direction, which is the half this block originally missed.
    """
    out = _git("log", "-1", "--format=%cI", "origin/main")
    if not out or not out.strip():
        return None
    try:
        committed = dt.datetime.fromisoformat(out.strip())
    except ValueError:
        return None
    now_ = dt.datetime.now(committed.tzinfo) if committed.tzinfo else dt.datetime.now()
    return (now_ - committed).total_seconds() / 3600.0


def main_contract_age_h(limit):
    """Age of the contract on `origin/main`, or None if it cannot be read.

    This — not "how many commits behind am I" — is the predicate that
    distinguishes a stale CHECKOUT from a stale PIPELINE. A commit count
    cannot: one commit behind with a genuinely dead pipeline would still
    look like a branch artifact, and the note would confidently give the
    wrong cause. That is the exact defect this whole block exists to fix,
    so it must not be reintroduced in miniature.

    But the ref is only evidence if the ref is CURRENT. On 2026-09-05 this
    checkout's `origin/main` was ~38h stale and never fetched, so this
    function read a 38h-old contract off it and the caller printed
    "origin/main's contract is 38h old too — not a branch artifact" — a
    confident pipeline-outage claim while production and real `main` were
    both ~1h fresh. It cost a full incident response.
    (docs/ops/INCIDENT_2026-09-05_FLOCK_ROOKIE_FLOOR.md)

    So a ref older than the freshness budget answers None. The file's own
    rule — "an unproven excuse must never silence a real alarm" — has a
    converse, and this is it: an unproven ref must not raise a false one.

    None on any failure, and the caller treats None as "cannot tell" and
    keeps the original warning.
    """
    ref_age = local_main_ref_age_h()
    if ref_age is None or ref_age > limit:
        return None
    listing = _git("ls-tree", "--name-only", "origin/main", "exports/latest/")
    if listing is None:
        return None
    names = sorted(
        n for n in listing.split("\n") if n.startswith("exports/latest/dynasty_data_")
    )
    if not names:
        return None
    blob = _git("show", f"origin/main:{names[-1]}")
    if blob is None:
        return None
    try:
        stamp_ = json.loads(blob).get("scrapeTimestamp")
        scraped_ = dt.datetime.fromisoformat(stamp_)
    except Exception:
        return None
    now_ = dt.datetime.now(scraped_.tzinfo) if scraped_.tzinfo else dt.datetime.now()
    return (now_ - scraped_).total_seconds() / 3600.0


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
    # Attribute the staleness before blaming the pipeline: ask what the
    # contract on origin/main looks like. Fresh there means this checkout is
    # simply old, and "check scheduled-refresh" would send the reader after a
    # workflow that is fine. Stale there means the pipeline really has
    # stopped, and the warning stands.
    #
    # Only a KNOWN-FRESH main redirects. None (cannot tell) falls through to
    # the warning — the guard must keep firing whenever the excuse is
    # unproven.
    main_age = main_contract_age_h(limit)
    if main_age is not None and main_age <= limit:
        print(
            f"  NOTE: origin/main's contract is {main_age:.0f}h old — the pipeline is "
            f"fine; this is the age of the checked-out branch."
        )
    else:
        print(f"  WARNING: no successful scrape in {age_h:.0f}h. Check scheduled-refresh workflow.")
        if main_age is not None:
            print(f"  (origin/main's contract is {main_age:.0f}h old too — not a branch artifact.)")
        else:
            # Say WHY it is unattributed instead of implying the pipeline.
            # This hook never fetches, so a stale local ref is the common case.
            print(
                "  (Cause NOT attributed: this checkout's origin/main ref is itself "
                "stale or unreadable, so it proves nothing either way. Run "
                "`git fetch origin main` and re-check before treating this as an outage.)"
            )

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
