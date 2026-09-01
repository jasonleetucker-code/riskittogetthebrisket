#!/usr/bin/env python3
"""Refresh the ESPN injury feed and turn transitions into BDVM events.

Part of the Live Waiver Opportunity layer
(``docs/faab-live-opportunity-model.md``).  ``src/nfl_data/injury_feed.py``
already fetches and diffs; this script is the piece that was missing —
turning a MEASURED status transition into a structured event
``src/trade/faab_opportunity.py`` (via ``src/bdvm/events.py``) can read,
the same closed ontology BDVM already uses (INJURY / ACTIVATED_RETURN).

Unlike the news->event path in ``src/bdvm/news_events.py``, these events
carry REAL confidence (0.85, not the news lane's speculative 0.45,
category C — a direct API-observed status change is materially stronger
evidence than a headline keyword match) — pinned by
``tests/trade/test_faab_opportunity_events.py``, which asserts the
confidence gap is deliberate, not an oversight.

Two transitions produce events:
  * ``healthy_to_injured`` / ``injury_worsened`` (from
    ``injury_feed.diff_for_signals``) -> ``INJURY``.
  * disappearing from the injury list entirely (recovered/activated) ->
    ``ACTIVATED_RETURN``.  ``diff_for_signals`` deliberately does not
    emit this case (its own docstring: "a different signal class"), so
    it is computed here instead of extending that function's contract.

Prior snapshot: ``data/nfl_data/injuries_prior.json`` (gitignored, like
the rest of ``data/``).  No prior file -> every current entry is treated
as new (first run seeds silently rather than back-dating events for
injuries that existed before this script ever ran).

Usage
-----
    python3 scripts/refresh_injury_feed.py

Exit codes
----------
    0  ok (including "flag off, no-op" and "no injuries")
    1  fetch or merge failed
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from src.api import feature_flags
from src.bdvm.events import EVENTS_DIR
from src.nfl_data.injury_feed import InjuryEntry, diff_for_signals, fetch_injuries
from src.utils.name_clean import normalize_player_name

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_LOGGER = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
_PRIOR_PATH = REPO_ROOT / "data" / "nfl_data" / "injuries_prior.json"

# Direct API-observed status changes, not speculation — real confidence,
# not the news lane's 0.45.  Category C: a documented, reasoned starting
# point (not yet empirically fitted against outcomes).
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


def _load_prior() -> list[InjuryEntry]:
    if not _PRIOR_PATH.exists():
        return []
    try:
        raw = json.loads(_PRIOR_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _LOGGER.warning("injuries prior snapshot unreadable, treating as empty: %s", exc)
        return []
    if not isinstance(raw, list):
        return []
    out = []
    for d in raw:
        if isinstance(d, dict):
            out.append(
                InjuryEntry(
                    espn_athlete_id=str(d.get("espnAthleteId") or ""),
                    full_name=str(d.get("fullName") or ""),
                    position=str(d.get("position") or ""),
                    team_abbrev=str(d.get("teamAbbrev") or ""),
                    status=str(d.get("status") or ""),
                    body_part=str(d.get("bodyPart") or ""),
                    description=str(d.get("description") or ""),
                    date_reported=str(d.get("dateReported") or ""),
                    returning=str(d.get("returning") or ""),
                )
            )
    return out


def _events_from_transitions(
    transitions: list[dict],
    recoveries: list[InjuryEntry],
    *,
    today: str,
) -> list[dict]:
    events: list[dict] = []
    for t in transitions:
        name = str(t.get("name") or "")
        if not name:
            continue
        player_key = normalize_player_name(name)
        events.append(
            {
                "eventId": f"injuryfeed:{today}:{player_key}:{t.get('transition')}",
                "playerKey": player_key,
                "eventType": "INJURY",
                "effectiveDate": today,
                "confidence": _CONFIDENCE,
                "sourceReliability": _SOURCE_RELIABILITY,
                "notes": str(t.get("reason") or "")[:140],
            }
        )
    for entry in recoveries:
        if not entry.full_name:
            continue
        player_key = normalize_player_name(entry.full_name)
        events.append(
            {
                "eventId": f"injuryfeed:{today}:{player_key}:recovered",
                "playerKey": player_key,
                "eventType": "ACTIVATED_RETURN",
                "effectiveDate": today,
                "confidence": _CONFIDENCE,
                "sourceReliability": _SOURCE_RELIABILITY,
                "notes": f"cleared the ESPN injury report (was {entry.status})",
            }
        )
    return events


def main(argv: list[str] | None = None) -> int:
    if not feature_flags.is_enabled("espn_injury_feed"):
        _LOGGER.info("espn_injury_feed flag OFF — skipping refresh")
        return 0

    current = fetch_injuries()
    if not current and feature_flags.is_enabled("espn_injury_feed"):
        # An empty CURRENT list on a flag that's ON could mean "the whole
        # league is healthy" or "the fetch failed silently" — the module
        # itself already logs the distinction; here it's a soft no-op
        # rather than an error, since a genuinely empty league-wide
        # injury report is a real (if rare) state.
        _LOGGER.info("no active injuries returned")

    prior = _load_prior()
    transitions = diff_for_signals(prior, current)

    prior_ids = {e.espn_athlete_id for e in prior}
    current_ids = {e.espn_athlete_id for e in current}
    recovered = [e for e in prior if e.espn_athlete_id not in current_ids and e.espn_athlete_id]
    # Only report a recovery once per player per run — the prior list
    # already carries at most one row per athlete id.
    recovered = [e for e in recovered if e.espn_athlete_id in prior_ids]

    today = datetime.now(timezone.utc).date().isoformat()
    new_events = _events_from_transitions(transitions, recovered, today=today)

    if new_events:
        from src.bdvm.news_events import merge_events_file  # noqa: PLC0415

        summary = merge_events_file(new_events, season=_current_nfl_season(), base_dir=EVENTS_DIR)
        if not summary.get("ok", True):
            _LOGGER.error("event merge failed: %s", summary)
            return 1
        _LOGGER.info(
            "merged %d injury-feed event(s) (%d transitions, %d recoveries)",
            len(new_events),
            len(transitions),
            len(recovered),
        )
    else:
        _LOGGER.info("no transitions this run")

    _atomic_write_json(_PRIOR_PATH, [e.to_dict() for e in current])
    return 0


if __name__ == "__main__":
    sys.exit(main())
