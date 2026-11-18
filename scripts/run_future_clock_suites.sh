#!/usr/bin/env bash
# Year-boundary harness runner: run every clock-reading test file under a fake
# wall clock (tests/fake_clock.py).  ADVISORY tooling - it only runs tests; it
# writes nothing under data/, exports/ or anything deployed.
#
#   bash scripts/run_future_clock_suites.sh 2027-01-01T00:30:00Z [extra pytest args]
#
# The file set is DISCOVERED (any test that reads the wall clock or calls a
# year resolver), so a new date-sensitive test joins the sweep automatically.
# The TZ edge (UTC already 2027, Los Angeles still 2026-12-31) is covered by
# running with TZ=America/Los_Angeles and 2027-01-01T03:00:00Z.
set -Eeuo pipefail

INSTANT="${1:?usage: run_future_clock_suites.sh <ISO-8601 instant> [pytest args]}"
shift || true

cd "$(dirname "$0")/.."

PATTERN='date\.today|datetime\.now|utcnow|time\.time\(|current_rookie_draft_year|current_nfl_season|league_draft_years|board_pick_horizon|calendar_year|rookie_draft_year_on|nfl_projection_season'

mapfile -t FILES < <(
  grep -rlE "$PATTERN" tests --include='test_*.py' \
    | grep -vE '^tests/(e2e|frontend)/' | sort
)
# Harness-artifact exclusions (each with its reason): config/ci/future_clock_exclusions.txt
DESELECT=()
while IFS= read -r line; do
  entry="${line%%#*}"
  entry="$(echo "$entry" | xargs)"
  [ -n "$entry" ] && DESELECT+=(--deselect "$entry") || true
done < config/ci/future_clock_exclusions.txt
echo "future-clock: ${#FILES[@]} date-sensitive test files at ${INSTANT} (TZ=${TZ:-unset})"

exec python -m pytest "${FILES[@]}" -q -p no:cacheprovider -m "not livedata" \
  -o addopts="" --fake-now="${INSTANT}" -rf "${DESELECT[@]}" "$@"
