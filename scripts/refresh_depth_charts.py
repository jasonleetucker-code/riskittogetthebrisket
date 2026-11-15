#!/usr/bin/env python3
"""Nightly cron: refresh all 32 NFL team depth charts via ESPN.

Fetches each team's depth chart (bypasses the 12h cache by clearing
first) and persists to disk.  Feeds the depth-chart-validation path
(Phase 8) and surfaces the day-over-day diff for signal cross-check.

Since 2026-09-01 (Live Waiver Opportunity layer,
``docs/faab-live-opportunity-model.md``) it ALSO turns a detected slot
change into a ``DEPTH_CHART_PROMOTION`` / ``DEPTH_CHART_DEMOTION``
event (the existing closed ontology; confidence 0.85).

**SHADOW ONLY since 2026-10-25.**  Until then this script had never read a
single chart (the ESPN path it called answered ``{}``), so the event merge
into ``data/bdvm/events/<season>.json`` had never actually run.  Repairing
the fetch would have ACTIVATED it, and that file is loaded by
``src/bdvm/service.py`` for every BDVM valuation — new live inputs to BDVM
values, the Fund-gap columns and BDVM signal alerts, arriving as a side
effect of a fetch repair.  So derived events are written to
``data/nfl_data/depth_chart_events_shadow.json`` instead, which nothing in
``src/`` loads, with per-run counts.  Known limits to measure there first:
the three receiver slots share position ``WR`` (a WR2→WR1 role change at
slot 1 is not a slot change), and ESPN formation reshuffles can produce
deltas that are not role changes.  Activating the merge needs measured
event volume / false positives and owner approval.

Flag-gated on ``depth_chart_validation`` — the function early-
returns in the individual team fetcher so this script is a no-op
when the flag is OFF.  Safe to run unconditionally in cron.

Usage
-----
    python3 scripts/refresh_depth_charts.py [--force]

    --force   Clear the cache before fetching (otherwise uses whatever
              is fresh within the 12h TTL).

Exit codes
----------
    0  all 32 teams fetched (or flag off → no-op)
    1  partial failure (some teams failed; see logs)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Run by systemd as `python scripts/<name>.py`, Python puts scripts/ (not the repo
# root) on sys.path; without this every `from src...` import fails (2026-09-24).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api import feature_flags  # noqa: E402
from src.nfl_data import cache as _cache  # noqa: E402
from src.nfl_data.depth_charts import (  # noqa: E402
    NFL_TEAM_IDS,
    DepthChartEntry,
    detect_slot_changes,
    fetch_team_depth_chart,
)
from src.utils.name_clean import normalize_player_name  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_LOGGER = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
_PRIOR_PATH = REPO_ROOT / "data" / "nfl_data" / "depth_charts_prior.json"
#: Derived events land HERE, never in data/bdvm/events/ (2026-10-25).
_SHADOW_PATH = REPO_ROOT / "data" / "nfl_data" / "depth_chart_events_shadow.json"
_SHADOW_MAX_RUNS = 90

# Direct API-observed slot changes, not speculation — real confidence,
# not the news lane's 0.45.  Category C (documented, not yet fitted).
_CONFIDENCE = 0.85
_SOURCE_RELIABILITY = 0.85


def _current_nfl_season(today: datetime | None = None) -> int:
    d = (today or datetime.now(timezone.utc)).date()
    return d.year if d.month >= 3 else d.year - 1


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp-{int(time.time() * 1000)}")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _load_prior() -> list[DepthChartEntry]:
    if not _PRIOR_PATH.exists():
        return []
    try:
        raw = json.loads(_PRIOR_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _LOGGER.warning("depth-chart prior snapshot unreadable, treating as empty: %s", exc)
        return []
    if not isinstance(raw, list):
        return []
    out = []
    for d in raw:
        if isinstance(d, dict):
            out.append(
                DepthChartEntry(
                    team_abbrev=str(d.get("teamAbbrev") or ""),
                    position=str(d.get("position") or ""),
                    slot=int(d.get("slot") or 0),
                    espn_athlete_id=str(d.get("espnAthleteId") or ""),
                    full_name=str(d.get("fullName") or ""),
                )
            )
    return out


def _record_shadow_run(
    changes: list[dict], events: list[dict], *, run_at: str, season: int
) -> dict:
    """Append this run's derived events to the SHADOW ledger and return the
    run record.  Nothing in ``src/`` reads :data:`_SHADOW_PATH`; it exists so
    event volume and false positives can be measured before anyone decides to
    let these events reach BDVM.  Bounded to the last
    :data:`_SHADOW_MAX_RUNS` runs.  An unreadable ledger is replaced rather
    than appended to (it is evidence for a decision, not a source of truth)."""
    by_direction: dict[str, int] = {}
    for c in changes:
        d = str(c.get("direction"))
        by_direction[d] = by_direction.get(d, 0) + 1
    record = {
        "runAt": run_at,
        "season": season,
        "slotDeltas": len(changes),
        "byDirection": dict(sorted(by_direction.items())),
        "events": events,
    }
    runs: list = []
    if _SHADOW_PATH.exists():
        try:
            raw = json.loads(_SHADOW_PATH.read_text(encoding="utf-8"))
            runs = raw.get("runs") if isinstance(raw, dict) else None
            runs = runs if isinstance(runs, list) else []
        except (OSError, ValueError):
            runs = []
    runs = [*runs, record][-_SHADOW_MAX_RUNS:]
    _atomic_write_json(
        _SHADOW_PATH,
        {
            "status": "shadow_not_loaded",
            "note": (
                "Derived DEPTH_CHART_PROMOTION/DEMOTION events, NOT merged into "
                "data/bdvm/events/. Activating the merge needs measured event volume / "
                "false positives and owner approval."
            ),
            "runs": runs,
        },
    )
    return record


def _snapshot_to_keep(
    prior: list[DepthChartEntry], current: list[DepthChartEntry]
) -> list[DepthChartEntry]:
    """The next run's comparison base: this run's fresh charts, plus the
    LAST GOOD chart of every team this run could not read.

    Writing only ``current`` would drop a team that failed today from the
    base, so its next good fetch would diff against nothing (every row a
    "debut", every real move that day lost).  A failed team keeps its prior
    rows instead — never a fabricated chart, only the last one observed."""
    fresh_teams = {e.team_abbrev for e in current}
    return list(current) + [e for e in prior if e.team_abbrev not in fresh_teams]


def _events_from_changes(changes: list[dict], *, today: str) -> list[dict]:
    events: list[dict] = []
    for c in changes:
        direction = c.get("direction")
        # A "debut" (player appears on the depth chart with no prior
        # entry) is not a promotion or demotion in the ontology's sense
        # — it is most often a new signing or a first NFL snap, which
        # already has its own event types and its own, better-attributed
        # source.  Only scored slot MOVEMENTS become events here.
        if direction not in ("promoted", "demoted"):
            continue
        name = str(c.get("fullName") or "")
        if not name:
            continue
        player_key = normalize_player_name(name)
        event_type = "DEPTH_CHART_PROMOTION" if direction == "promoted" else "DEPTH_CHART_DEMOTION"
        events.append(
            {
                "eventId": f"depthchart:{today}:{player_key}:{direction}",
                "playerKey": player_key,
                "eventType": event_type,
                "effectiveDate": today,
                "confidence": _CONFIDENCE,
                "sourceReliability": _SOURCE_RELIABILITY,
                "notes": (
                    f"{c.get('team')} {c.get('position')} depth chart: "
                    f"slot {c.get('oldSlot')} -> {c.get('newSlot')}"
                ),
            }
        )
    return events


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    if not feature_flags.is_enabled("depth_chart_validation"):
        _LOGGER.info("depth_chart_validation flag OFF — skipping refresh")
        return 0

    if args.force:
        cache_dir = _cache._default_cache_dir()  # noqa: SLF001
        for tid in NFL_TEAM_IDS:
            _cache.evict(f"espn_depth:{tid}", cache_dir=cache_dir)
        _LOGGER.info("force: evicted %d cache entries", len(NFL_TEAM_IDS))

    prior = _load_prior()

    ok = 0
    failed = []
    current: list[DepthChartEntry] = []
    for tid in NFL_TEAM_IDS:
        entries = fetch_team_depth_chart(tid)
        if entries:
            ok += 1
            current.extend(entries)
        else:
            failed.append(tid)

    _LOGGER.info("refresh complete: %d/%d OK", ok, len(NFL_TEAM_IDS))

    if prior and current:
        changes = detect_slot_changes(prior, current)
        now = datetime.now(timezone.utc)
        new_events = _events_from_changes(changes, today=now.date().isoformat())
        record = _record_shadow_run(
            changes, new_events, run_at=now.isoformat(), season=_current_nfl_season(now)
        )
        # SHADOW ONLY — see the module docstring.  Nothing reaches the BDVM
        # events file (src/bdvm/service.py loads that for every valuation).
        _LOGGER.info(
            "shadow: %d depth-chart event(s) derived from %d slot delta(s) %s — "
            "NOT merged into the BDVM events file",
            len(new_events),
            len(changes),
            record["byDirection"],
        )
    else:
        _LOGGER.info("no prior snapshot or no current data — skipping event derivation this run")

    if current:
        _atomic_write_json(_PRIOR_PATH, [e.to_dict() for e in _snapshot_to_keep(prior, current)])

    if failed:
        _LOGGER.warning("failures: %s", failed)
        return 1 if len(failed) > 5 else 0  # tolerate a few flaky teams
    return 0


if __name__ == "__main__":
    sys.exit(main())
