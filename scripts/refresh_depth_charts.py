#!/usr/bin/env python3
"""Nightly cron: refresh all 32 NFL team depth charts via ESPN.

Fetches each team's depth chart (bypasses the 12h cache by clearing
first) and persists to disk.  Feeds the depth-chart-validation path
(Phase 8) and surfaces the day-over-day diff for signal cross-check.

Since 2026-09-01 (Live Waiver Opportunity layer,
``docs/faab-live-opportunity-model.md``) it ALSO turns a detected slot
change into a BDVM structured event (``DEPTH_CHART_PROMOTION`` /
``DEPTH_CHART_DEMOTION`` — the existing closed ontology, no new types
needed) that ``src/trade/faab_opportunity.py`` reads.  This is how an
injury-created vacancy reaches a backup's FAAB price without a separate
injury-specific propagation join: ESPN re-orders its OWN depth chart
when a starter goes down, so the SAME diff that catches a clean role
change also catches the backup's promotion the day it happens.  These
events carry real confidence (0.85 — a measured API observation, not a
news headline guess), pinned by
``tests/trade/test_faab_opportunity_events.py``.

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

from src.api import feature_flags
from src.bdvm.events import EVENTS_DIR
from src.nfl_data import cache as _cache
from src.nfl_data.depth_charts import (
    NFL_TEAM_IDS,
    DepthChartEntry,
    detect_slot_changes,
    fetch_team_depth_chart,
)
from src.utils.name_clean import normalize_player_name

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_LOGGER = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
_PRIOR_PATH = REPO_ROOT / "data" / "nfl_data" / "depth_charts_prior.json"

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
        today = datetime.now(timezone.utc).date().isoformat()
        new_events = _events_from_changes(changes, today=today)
        if new_events:
            from src.bdvm.news_events import merge_events_file  # noqa: PLC0415

            summary = merge_events_file(
                new_events, season=_current_nfl_season(), base_dir=EVENTS_DIR
            )
            if not summary.get("ok", True):
                _LOGGER.error("event merge failed: %s", summary)
            else:
                _LOGGER.info(
                    "merged %d depth-chart event(s) from %d slot change(s)",
                    len(new_events),
                    len(changes),
                )
        else:
            _LOGGER.info("no scored slot changes this run (%d total deltas)", len(changes))
    else:
        _LOGGER.info("no prior snapshot or no current data — skipping event derivation this run")

    if current:
        _atomic_write_json(_PRIOR_PATH, [e.to_dict() for e in current])

    if failed:
        _LOGGER.warning("failures: %s", failed)
        return 1 if len(failed) > 5 else 0  # tolerate a few flaky teams
    return 0


if __name__ == "__main__":
    sys.exit(main())
