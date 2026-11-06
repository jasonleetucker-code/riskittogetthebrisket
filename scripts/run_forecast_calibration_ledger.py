"""Weekly Forecast Calibration Ledger run: AL-4a + AL-3b after a week is FINAL (AMATH-S01).

Runs the two existing report-only scorecards, unchanged, once per newly finalized
NFL week:

* AL-4a ``scripts/game_day_calibration_scorecard.py`` (Game Day win / beat-median
  probabilities vs host finals);
* AL-3b ``scripts/projection_scorecard.py`` (weekly + season projections vs
  realized, exact league scoring) for every active league with a scoring card.

It invents no metric and writes only the gitignored box-local
``data/learning/scorecards/`` tree (summaries and the ``ledger_runs.json`` marker).
It changes no served value, probability or label.

Gating, all from Sleeper's own week state (``projection_scorecard.host_week_final``):

* no finalized week yet (preseason, week 1 in progress) -> refuse, exit 0, write nothing;
* the last finalized week equals the one recorded in the marker -> already done, exit 0
  (idempotent per week; ``--force`` re-runs);
* the state cannot be read -> refuse, exit 1 (unknown is never "final").

Exit codes: 0 ran, or refused / skipped for a stated reason; 1 a scorecard failed or the
host state is unreadable (the marker is NOT advanced, so the next firing retries).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._scorecard_common import SCORECARD_DIR, write_json  # noqa: E402

MARKER_NAME = "ledger_runs.json"
LAST_REGULAR_WEEK = 18


def last_final_week(state: dict[str, Any] | None) -> tuple[int | None, int | None]:
    """``(season, last finalized regular-season week)`` from Sleeper's state, else ``(None, None)``."""
    from src.model_registry import projection_scorecard as ps

    if not isinstance(state, dict):
        return None, None
    try:
        season = int(state.get("season"))
    except (TypeError, ValueError):
        return None, None
    final = [w for w in range(1, LAST_REGULAR_WEEK + 1) if ps.host_week_final(state, season, w)]
    if not final:
        return season, None
    last = max(final)
    # Scoring-final is not lineup-final.  Sleeper awards a best-ball week's
    # optimized lineups (and absorbs stat corrections) only once it stops
    # DISPLAYING the week -- the rule the canonical owner
    # ``src/public_league/metrics.py::host_lineups_open_from_week`` documents
    # (2026-11-03: provisional week-8 lineups withheld a whole season).  AL-4a
    # scores lineup-dependent outcomes, so a week counts only below
    # ``display_week``; an unreadable ``display_week`` withholds the newest
    # scored week (fail closed on one week, never on a season), as that owner
    # does.  Mirrored here because the owner needs a full SeasonSnapshot.
    if str(state.get("season_type") or "") == "regular":
        try:
            display = int(state.get("display_week"))
        except (TypeError, ValueError):
            display = None
        last = last - 1 if display is None else min(last, display - 1)
    return season, (last if last >= 1 else None)


def read_marker(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def run(
    *,
    state: dict[str, Any] | None,
    marker_path: Path,
    al4a: Callable[[list[str]], int],
    al3b: Callable[[list[str]], int],
    leagues: list[str],
    force: bool = False,
    dry_run: bool = False,
) -> int:
    season, week = last_final_week(state)
    if season is None:
        print("host week state unreadable; refusing (unknown is not final)")
        return 1
    if week is None:
        print(f"season {season}: no finalized week yet; nothing to score")
        return 0
    marker = read_marker(marker_path)
    if not force and marker.get("season") == season and marker.get("lastFinalWeek") == week:
        print(f"season {season} week {week} already scored; nothing to do")
        return 0
    print(f"season {season}: newly final through week {week}; running AL-4a + AL-3b")
    if dry_run:
        print(f"dry run: would run AL-4a and AL-3b for {leagues}")
        return 0
    failed: list[str] = []
    # AL-4a exit 2 = no Game Day evidence directory on this host: not a failure, not scored.
    code = al4a(["--season", str(season)])
    if code not in (0, 2):
        failed.append(f"AL-4a exit {code}")
    for league in leagues:
        code = al3b(["--league", league, "--season", str(season), "--fetch-realized"])
        # AL-3b exit 2 = unknown league / no scoring card / off-season: skipped, not failed.
        if code not in (0, 2):
            failed.append(f"AL-3b {league} exit {code}")
    if failed:
        print("ledger run incomplete, marker not advanced: " + "; ".join(failed))
        return 1
    write_json(marker_path, {"season": season, "lastFinalWeek": week, "leagues": sorted(leagues)})
    print(f"ledger marker -> {marker_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--force", action="store_true", help="re-run an already scored week")
    parser.add_argument("--dry-run", action="store_true", help="decide and print; run nothing")
    args = parser.parse_args(argv)

    from scripts import game_day_calibration_scorecard as al4a
    from scripts import projection_scorecard as al3b
    from src.api import league_registry
    from src.public_league.sleeper_client import fetch_nfl_state

    state = fetch_nfl_state()
    leagues = [c.key for c in league_registry.active_leagues()]
    return run(
        state=dict(state) if isinstance(state, dict) else None,
        marker_path=SCORECARD_DIR / MARKER_NAME,
        al4a=al4a.main,
        al3b=al3b.main,
        leagues=leagues,
        force=args.force,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
