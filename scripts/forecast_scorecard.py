#!/usr/bin/env python3
"""Standing prediction scorecard + champion-degradation review (MD-104, report-only).

Joins the archived forecasts to realized outcomes, per family (season playoff /
title odds, Game Day win / median-race, team weekly points), scores the served
model against a simple named baseline on the identical samples, and evaluates the
pre-declared degradation rule ``config/forecast_scorecard/degradation_rule_v1.json``.

Writes ONE private file, ``data/learning/scorecards/forecast_scorecard.json``
(gitignored, box-local).  The production alert sweep reads its
``degradationReviews`` and sends them through the existing ``ops_alerts`` path.
This script changes no forecast, value, flag or served response and promotes
nothing.

Inputs (all read-only): the forecast archive (``data/forecast_archive/``), Game Day
generations (``data/game_day/live/``), and an optional season-outcomes JSON
(``--season-outcomes``; a list of ``{leagueKey, season, playoffsDecidedAt,
playoffOwnerIds, titleDecidedAt, championOwnerId}``).  Without outcomes a season
family reports ``unavailable`` -- never zero.

Exit codes: 0 scored (possibly all families unavailable -- read it); 2 bad config.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._scorecard_common import SCORECARD_DIR, code_revision, write_json  # noqa: E402
from scripts.game_day_calibration_scorecard import collect as collect_game_day  # noqa: E402
from src.ros import forecast_archive  # noqa: E402
from src.ros_calibration import scorecard as sc  # noqa: E402

RULE_PATH = REPO_ROOT / "config" / "forecast_scorecard" / "degradation_rule_v1.json"
OUT_NAME = "forecast_scorecard.json"
CODE_PATHS = (
    "src/ros_calibration/scorecard.py",
    "scripts/forecast_scorecard.py",
    str(RULE_PATH.relative_to(REPO_ROOT)),
)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--archive-dir", type=Path, default=forecast_archive.DEFAULT_DIR)
    parser.add_argument("--rule", type=Path, default=RULE_PATH)
    parser.add_argument("--season-outcomes", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=SCORECARD_DIR / OUT_NAME)
    parser.add_argument("--now", default=None, help="ISO instant (tests); default: wall clock")
    parser.add_argument("--dry-run", action="store_true", help="print; write nothing")
    args = parser.parse_args(argv)

    try:
        rule = sc.parse_rule(json.loads(args.rule.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError) as exc:
        print(f"cannot read the declared degradation rule {args.rule}: {exc}")
        return 2
    now = sc.parse_instant(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        print(f"bad --now {args.now!r}")
        return 2

    records = (
        list(forecast_archive.iter_records(args.archive_dir)) if args.archive_dir.is_dir() else []
    )
    outcomes = []
    if args.season_outcomes is not None:
        body = _read_json(args.season_outcomes)
        if not isinstance(body, list):
            print(f"season outcomes {args.season_outcomes} unreadable; season families unavailable")
        else:
            outcomes = [sc.season_outcome_from_json(o) for o in body if isinstance(o, dict)]
    evidence = collect_game_day()
    previous = _read_json(args.out)
    prior = (previous or {}).get("streaks") if isinstance(previous, dict) else None
    card = sc.build_scorecard(
        rule=rule,
        now=now,
        forecast_records=records,
        season_outcomes=outcomes,
        game_day_evidence=evidence,
        prior_streaks=prior if isinstance(prior, dict) else None,
        code_sha=code_revision(CODE_PATHS),
    )
    for name, fam in card["families"].items():
        rows = fam["rows"]
        served = [r for r in rows if r.get("ruleBasis") and r.get("isServedModel")]
        line = ", ".join(
            f"{r['leagueKey']}:{r['verdict']}(n={r['eligibleSamples']})" for r in served
        )
        print(
            f"{name}: {fam['state']}"
            + (f" ({fam['reason']})" if fam["reason"] else "")
            + (f" {line}" if line else "")
        )
    print(f"degradation reviews fired: {len(card['degradationReviews'])} (rule {rule.version})")
    if args.dry_run:
        return 0
    write_json(args.out, card)
    print(f"scorecard -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
