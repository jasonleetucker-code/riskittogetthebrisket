"""AL-4a — Game Day calibration scorecard over the stored generations (report-only).

Reads every league-week under ``data/game_day/live/<leagueKey>/<season>/week_<n>/``
through the Game Day owner's own readers (``game_day_live.load_generation_history``
for the append-only ``generations.jsonl``; ``game_day_live.load_generation`` for
the latest ``generation.json``), scores the as-known win / beat-median
probabilities against the host's finals with
``src/model_registry/game_day_calibration.py``, and writes:

* a deterministic summary to ``data/learning/scorecards/game_day_calibration.json``
  — PRIVATE: per-league aggregates of our own predictions are decision
  intelligence, so nothing goes to ``docs/`` or ``data/ros/``;
* one EVALUATION receipt per (league, modelVersion, target) to the learning store
  ``data/learning/receipts.sqlite`` — only when ``RISKIT_RECEIPTS_ENABLED=1``.

It changes no served value, runs no simulation and promotes nothing.

Usage::

    python scripts/game_day_calibration_scorecard.py [--league KEY ...] [--season N] [--dry-run]

Exit codes: 0 scored (possibly an empty / insufficient scorecard — read it);
1 receipts could not be stored; 2 no Game Day evidence directory exists.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._scorecard_common import SCORECARD_DIR, code_revision, emit, write_json  # noqa: E402
from src.model_registry import game_day_calibration as gdc  # noqa: E402
from src.ros import game_day_live as gdl  # noqa: E402

CODE_PATHS = (
    "src/model_registry/game_day_calibration.py",
    "scripts/game_day_calibration_scorecard.py",
)
SUMMARY_NAME = "game_day_calibration.json"


def collect(
    leagues: list[str] | None = None, season: int | None = None
) -> list[gdc.LeagueWeekEvidence]:
    root = gdl.LIVE_ROOT
    out: list[gdc.LeagueWeekEvidence] = []
    if not root.is_dir():
        return out
    for league_dir in sorted(root.iterdir()):
        name = league_dir.name
        if not league_dir.is_dir() or name.startswith("_"):
            continue  # _nfl / _collector are not leagues
        if leagues and name not in leagues:
            continue
        for season_dir in sorted(league_dir.iterdir()):
            if not season_dir.is_dir() or not season_dir.name.isdigit():
                continue
            if season is not None and int(season_dir.name) != season:
                continue
            for week_dir in sorted(season_dir.iterdir()):
                if not week_dir.is_dir() or not week_dir.name.startswith("week_"):
                    continue
                try:
                    week = int(week_dir.name.split("_", 1)[1])
                except ValueError:
                    continue
                yr = int(season_dir.name)
                out.append(
                    gdc.LeagueWeekEvidence(
                        league_key=name,
                        season=yr,
                        week=week,
                        index_rows=gdl.load_generation_history(name, yr, week),
                        latest_generation=gdl.load_generation(name, yr, week),
                    )
                )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--league", action="append", help="league key (repeatable)")
    parser.add_argument("--season", type=int)
    parser.add_argument("--dry-run", action="store_true", help="print; write nothing")
    parser.add_argument("--out", type=Path, default=SCORECARD_DIR / SUMMARY_NAME)
    args = parser.parse_args(argv)

    if not gdl.LIVE_ROOT.is_dir():
        print(f"no Game Day evidence at {gdl.LIVE_ROOT} (production data lives on the box)")
        return 2
    evidence = collect(args.league, args.season)
    result = gdc.evaluate(evidence)
    summary = result.summary
    weeks = sum(len(v["weeks"]) for v in summary["leagues"].values())
    scored = len(result.scored)
    print(
        f"game day calibration: leagues={len(summary['leagues'])} league-weeks={weeks} "
        f"scored-predictions={scored}"
    )
    for league, block in sorted(summary["leagues"].items()):
        for c in block["cohorts"]:
            if c["state"] in ("all_states_pooled", "pregame"):
                metric = f"brier={c['metrics']['brier']:.4f}" if c["metrics"] else "no metric"
                print(
                    f"  {league} {c['modelVersion']} {c['target']} {c['state']}: "
                    f"events={c['events']}/{c['outcomeEvents']} {c['status']} {metric}"
                )
    if args.dry_run:
        print(json.dumps(summary, sort_keys=True, indent=1)[:4000])
        return 0
    write_json(args.out, summary)
    print(f"summary -> {args.out}")
    code_sha = code_revision(CODE_PATHS)
    stored = emit(lambda: gdc.receipts(result, code_sha=code_sha), label="game_day_calibration")
    return 0 if stored.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
