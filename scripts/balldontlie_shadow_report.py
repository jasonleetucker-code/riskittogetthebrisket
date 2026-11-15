#!/usr/bin/env python3
"""Summarize the Game Day BALLDONTLIE SHADOW log for one week.  Read-only.

Reads ``data/game_day/live/_nfl/<season>/week_<week>/shadow_balldontlie.jsonl``
(written by ``src/ros/game_day_live.py::collect_shadow_live_state``) and
reports the evidence the promotion decision needs
(docs/game-day/BALLDONTLIE_LIVE_STATE_EVALUATION.md §5):

* per game: every lifecycle the provider stated with when it was FIRST seen,
  every raw ``status`` text seen (how halftime / quarters are actually
  written, if at all), each score change with when it was first seen;
* against the provider the collector actually selected, where one existed:
  per-field agreement counts (``true`` / ``false`` / one side missing) and
  the lag between the reference's lifecycle / score change and the
  candidate's;
* fetch time percentiles, error counts and the observed request rate
  against the free-tier limit.

Nothing is reconciled or smoothed; a missing field is counted as missing.

Exit codes: 0 report written; 2 no shadow log for that week.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _ts(value: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, int(q * (len(values) - 1) + 0.5))], 3)


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    games: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "lifecycleFirstSeen": {},
            "phaseFirstSeen": {},
            "statusTexts": Counter(),
            "scoreChanges": [],
            "referenceLifecycleFirstSeen": {},
            "referenceScoreFirstSeen": {},
            "agreement": defaultdict(Counter),
        }
    )
    fetch = [float(r["fetchSeconds"]) for r in records if r.get("fetchSeconds") is not None]
    errors = Counter(r.get("candidateError") for r in records if not r.get("candidateOk"))
    references = Counter(r.get("referenceProvider") or "none" for r in records)
    stamps = [t for t in (_ts(r.get("observedAt")) for r in records) if t is not None]
    for rec in records:
        t = _ts(rec.get("observedAt"))
        for g in rec.get("games") or ():
            s = games[g["game"]]
            c, ref = g.get("candidate") or {}, g.get("reference")
            s["lifecycleFirstSeen"].setdefault(str(c.get("lifecycle")), rec.get("observedAt"))
            s["phaseFirstSeen"].setdefault(str(c.get("phase")), rec.get("observedAt"))
            s["statusTexts"][str(c.get("status"))] += 1
            score = (c.get("awayScore"), c.get("homeScore"))
            if not s["scoreChanges"] or s["scoreChanges"][-1]["score"] != list(score):
                s["scoreChanges"].append(
                    {"score": list(score), "firstSeen": rec.get("observedAt"), "t": t}
                )
            if ref:
                s["referenceLifecycleFirstSeen"].setdefault(
                    str(ref.get("lifecycle")), rec.get("observedAt")
                )
                rscore = f"{ref.get('awayScore')}-{ref.get('homeScore')}"
                s["referenceScoreFirstSeen"].setdefault(rscore, t)
                for name, verdict in (g.get("fields") or {}).items():
                    if name.endswith("Seconds"):
                        continue
                    s["agreement"][name][str(verdict)] += 1
    out_games = {}
    for name, s in sorted(games.items()):
        lags = []
        for change in s["scoreChanges"]:
            key = f"{change['score'][0]}-{change['score'][1]}"
            ref_t = s["referenceScoreFirstSeen"].get(key)
            if ref_t is not None and change["t"] is not None:
                lags.append(round(change["t"] - ref_t, 1))
        out_games[name] = {
            "lifecycleFirstSeen": s["lifecycleFirstSeen"],
            "phaseFirstSeen": s["phaseFirstSeen"],
            "statusTexts": dict(s["statusTexts"]),
            "scoreChanges": [{k: v for k, v in c.items() if k != "t"} for c in s["scoreChanges"]],
            "referenceLifecycleFirstSeen": s["referenceLifecycleFirstSeen"],
            "scoreLagSecondsVsReference": lags,
            "agreement": {k: dict(v) for k, v in s["agreement"].items()},
        }
    span_minutes = (max(stamps) - min(stamps)) / 60.0 if len(stamps) > 1 else None
    return {
        "records": len(records),
        "firstObservedAt": records[0].get("observedAt") if records else None,
        "lastObservedAt": records[-1].get("observedAt") if records else None,
        "requestsPerMinuteObserved": round(len(records) / span_minutes, 3)
        if span_minutes
        else None,
        "freeTierLimitPerMinute": 5,
        "fetchSeconds": {
            "p50": _pct(fetch, 0.5),
            "p95": _pct(fetch, 0.95),
            "max": max(fetch) if fetch else None,
        },
        "fetchSecondsMean": round(statistics.fmean(fetch), 3) if fetch else None,
        "candidateErrors": dict(errors),
        "referenceProviders": dict(references),
        "games": out_games,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--path", type=Path, help="explicit shadow log (default: the collector's)")
    args = parser.parse_args(argv)
    if args.path is not None:
        path = args.path
    else:
        from src.ros import game_day_live

        path = game_day_live.shadow_log_path(args.season, args.week)
    if not path.exists():
        print(json.dumps({"error": "no_shadow_log", "path": str(path)}))
        return 2
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    print(json.dumps(summarize(records), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
