#!/usr/bin/env python3
"""Refresh the ESPN injury feed; record real entries; derive SHADOW-ONLY events.

Part of the Live Waiver Opportunity layer
(``docs/faab-live-opportunity-model.md``).  ``src/nfl_data/injury_feed.py``
fetches and diffs; this script turns a MEASURED status transition into the
structured event a future ``src/trade/faab_opportunity.py`` / BDVM read could
use (the closed ontology BDVM already has: INJURY / ACTIVATED_RETURN).

**SHADOW ONLY since 2026-10-26.**  ESPN changed its injuries payload (no
``athlete.id``; the id moved to the athlete links) and the parser read zero
entries for weeks while reporting a healthy fetch, so this script's event merge
into ``data/bdvm/events/<season>.json`` had effectively never run.  Repairing
the parser would have ACTIVATED it, and that file is loaded by
``src/bdvm/service.py`` for every BDVM valuation (and by the FAAB opportunity
shadow) -- new live inputs to BDVM values, the Fund-gap columns and BDVM signal
alerts, arriving as a side effect of a parser repair, with a ~274-player first
run.  Same trap, same answer as the depth-chart refresh (#1926): derived events
go to ``data/nfl_data/injury_events_shadow.json``, which nothing in ``src/``
loads, with per-run counts.  There is deliberately NO feature flag and no code
path that writes injury events to the BDVM events file: writing them there is an
explicit owner decision that needs measured volume / false positives first.

First run (empty or unreadable prior): the prior is SEEDED silently -- the
snapshot and history are recorded, no event is derived (otherwise every
currently-injured player would read as a new transition).

Transitions (shadow):
  * ``healthy_to_injured`` / ``injury_worsened`` (``injury_feed.diff_for_signals``)
    -> ``INJURY``.
  * disappearing from the injury list (recovered / activated) ->
    ``ACTIVATED_RETURN`` (computed here; ``diff_for_signals`` does not emit it).

Only entries whose ESPN id resolved to a Sleeper id (``injury_identity``) take
part in the diff, the prior and the events.  Every skipped / refused row is
COUNTED by reason in the log and the shadow ledger -- missing is never zero and
nothing is guessed.  A refused share above ``injury_identity.MAX_UNRESOLVED_FRACTION``
fails the run (exit 1) with the prior and shadow ledger untouched.

Prior snapshot: ``data/nfl_data/injuries_prior.json`` (gitignored, like the rest
of ``data/``): the resolved entries of the last good run, overwritten each run.

As-known history (Adaptive Learning G4): every PROVEN fetch is also appended to
the point-in-time log ``data/nfl_data/injury_history/`` via
``src/nfl_data/injury_history.py`` -- the prior file is overwritten every run and
ESPN serves the current report only.  The history records ALL parsed entries
(resolved or not -- it resolves identity per snapshot itself).  An identical
re-fetch is a small re-observation row.  A failure to archive never fails the
refresh.  Nothing reads the history as a value input.

Fetch proof: ``fetch_injuries`` returns ``[]`` for "no injuries" AND for "the
fetch failed".  The run proceeds only when the response cache proves ESPN
answered with an injuries-SHAPED body whose rows the parser could actually read
(``injury_history.proven_fetch_time``; ``injury_feed.payload_shape_error`` keeps
shape drift AND "raw rows but zero parsed" out of the cache).  Otherwise --
network error, open breaker, shape or parse drift -- it changes nothing and exits
1, logging the feed's own reason.  A cache-write failure on a real fetch raises
out of ``fetch_injuries`` and also exits non-zero with nothing changed.

Usage
-----
    python3 scripts/refresh_injury_feed.py

Exit codes
----------
    0  ok (including "flag off, no-op", "first run: prior seeded", "no injuries")
    1  fetch not proven (nothing recorded, prior untouched), identity step
       unusable (history recorded; prior and shadow ledger untouched), or a
       shadow-ledger write failed (prior untouched)
"""

from __future__ import annotations

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
from src.nfl_data import injury_feed, injury_history, injury_identity  # noqa: E402
from src.nfl_data.injury_feed import (  # noqa: E402
    InjuryEntry,
    diff_for_signals,
    entry_from_dict,
    fetch_injuries,
)
from src.utils.name_clean import normalize_player_name  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_LOGGER = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
_PRIOR_PATH = REPO_ROOT / "data" / "nfl_data" / "injuries_prior.json"
#: Derived events land HERE, never in data/bdvm/events/ (2026-10-26).  Named
#: like the depth-chart sibling (``depth_chart_events_shadow.json``, #1926).
_SHADOW_PATH = REPO_ROOT / "data" / "nfl_data" / "injury_events_shadow.json"
#: 4-hourly cadence -> 180 runs is ~30 days of volume evidence.
_SHADOW_MAX_RUNS = 180

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
    return [entry_from_dict(d) for d in raw if isinstance(d, dict)]


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


def _event_provenance(
    transitions: list[dict], recoveries: list[InjuryEntry], *, today: str
) -> list[dict]:
    """Who each shadow event is about, by ID -- kept OUT of the event dicts so
    those stay schema-pure if the owner ever approves merging them."""
    out: list[dict] = []
    for t in transitions:
        name = str(t.get("name") or "")
        if not name:
            continue
        out.append(
            {
                "eventId": f"injuryfeed:{today}:{normalize_player_name(name)}:{t.get('transition')}",
                "espnAthleteId": t.get("espnAthleteId"),
                "sleeperId": t.get("sleeperId"),
                "team": t.get("team"),
                "position": t.get("position"),
                "priorStatus": t.get("priorStatus"),
                "newStatus": t.get("newStatus"),
            }
        )
    for e in recoveries:
        if not e.full_name:
            continue
        out.append(
            {
                "eventId": f"injuryfeed:{today}:{normalize_player_name(e.full_name)}:recovered",
                "espnAthleteId": e.espn_athlete_id,
                "sleeperId": e.sleeper_id or None,
                "team": e.team_abbrev,
                "position": e.position,
                "priorStatus": e.status,
                "newStatus": None,
            }
        )
    return out


def _record_shadow_run(record: dict) -> dict:
    """Append this run to the SHADOW ledger and return it.  Nothing in ``src/``
    reads :data:`_SHADOW_PATH`; it exists so event volume and false positives can
    be measured before anyone decides to let these events reach BDVM.  Bounded to
    the last :data:`_SHADOW_MAX_RUNS` runs.  An unreadable ledger is replaced
    rather than appended to (it is evidence for a decision, not a source of
    truth)."""
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
                "Derived INJURY/ACTIVATED_RETURN events, NOT merged into "
                "data/bdvm/events/. Activating the merge needs measured event volume / "
                "false positives and owner approval."
            ),
            "runs": runs,
        },
    )
    return record


def _refresh_return_evidence() -> None:
    """Per-player structured return dates (``src.nfl_data.injury_return_evidence``).

    Independent of the league-wide feed below, whose endpoint caps each team
    at 25 recently-updated entries and so drops long-term IR players — exactly
    the "out for the season" cases player-week availability needs.  Non-fatal:
    a failed run keeps the previous evidence file, which carries its own
    ``asOf``.
    """
    from src.identity.directory_cache import get_default_sleeper_index  # noqa: PLC0415
    from src.nfl_data import injury_return_evidence as ire  # noqa: PLC0415

    try:
        payload = ire.collect(
            previous=ire.load_evidence(), sleeper_index=get_default_sleeper_index()
        )
        census = payload.get("census") or {}
        if not census.get("rosterAthletes"):
            _LOGGER.error(
                "injury return evidence: no roster read (%s) — previous file kept", census
            )
            return
        ire.write_evidence(payload)
        _LOGGER.info("injury return evidence: %s", census)
    except Exception as exc:  # noqa: BLE001 — never fails the feed refresh
        _LOGGER.error("injury return evidence failed: %s — previous file kept", exc)


def main(argv: list[str] | None = None) -> int:
    if not feature_flags.is_enabled("espn_injury_feed"):
        # Exit 0 keeps the unit green by design (the flag is the operator's
        # choice), but nothing was fetched or measured: say so at WARNING so a
        # green unit is never read as a healthy feed.
        _LOGGER.warning("espn_injury_feed flag OFF — skipping refresh; injury feed NOT MEASURED")
        return 0

    _refresh_return_evidence()

    started_at = time.time()
    injury_feed.clear_last_fetch_report()
    current = fetch_injuries()
    feed_report = injury_feed.last_fetch_report()
    fetched_at, unproven = injury_history.proven_fetch_time(
        [e.to_dict() for e in current],
        started_at=started_at,
        ttl_seconds=injury_feed.TTL_IN_SEASON_SECONDS,
    )
    if fetched_at is None:
        # MISSING IS NEVER ZERO: an unproven empty list is "we do not know",
        # not "everyone recovered".  No events, no history row, prior kept.
        _LOGGER.error(
            "injury fetch not proven (%s; feed said: %s) — no events, no history row, "
            "prior snapshot untouched",
            unproven,
            feed_report,
        )
        return 1

    # One directory read serves the history's per-snapshot identity block and the
    # identity step below.
    directory, directory_provenance = injury_history.load_directory()
    injury_history.capture_safely(
        [e.to_dict() for e in current],
        fetched_at=fetched_at,
        directory=directory,
        directory_provenance=directory_provenance,
    )

    parse_block = (feed_report or {}).get("parse")
    if not current:
        # Proven above to be a real fetch whose parser lost nothing (a non-empty
        # body that parsed to nothing is drift and never reaches here), so an
        # empty list IS a league-wide report with no raw entries.
        _LOGGER.info("no injury entries in the report (fetch proven; parse=%s)", parse_block)

    resolver = injury_history.EspnIdResolver(directory)
    resolved, identity_report = injury_identity.resolve_entries(current, resolver=resolver)
    _LOGGER.info(
        "injury identity: %s",
        identity_report.to_dict(),
    )
    identity_problem = injury_identity.identity_error(identity_report)
    if identity_problem is not None:
        # History above already recorded the real parsed entries.  Nothing else
        # moves: an unusable identity step is "we do not know who these are".
        _LOGGER.error(
            "injury identity unusable (%s) — no events, prior snapshot and shadow ledger untouched",
            identity_problem,
        )
        return 1

    prior = _load_prior()
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    # Every PARSED id (not just resolved ones): "still on the report" must not
    # depend on whether this run could resolve who he is.
    current_ids = {e.espn_athlete_id for e in current}

    run: dict = {
        "runAt": now.isoformat(),
        "season": _current_nfl_season(now),
        "parse": parse_block,
        "identity": identity_report.to_dict(),
    }

    if not prior and resolved:
        # SEED: with no baseline, every injured player would read as a new
        # transition (~274 on the first real run).  Record the baseline only.
        run.update({"mode": "seeded", "transitions": {}, "recoveries": 0, "events": []})
        _LOGGER.info(
            "first non-empty run: seeded prior with %d injury entries; no events derived",
            len(resolved),
        )
    else:
        transitions = diff_for_signals(prior, resolved)
        # "Recovered" = in the prior, no longer on the report.
        recovered = [e for e in prior if e.espn_athlete_id and e.espn_athlete_id not in current_ids]
        events = _events_from_transitions(transitions, recovered, today=today)
        by_transition: dict[str, int] = {}
        for t in transitions:
            key = str(t.get("transition"))
            by_transition[key] = by_transition.get(key, 0) + 1
        run.update(
            {
                "mode": "derived",
                "transitions": dict(sorted(by_transition.items())),
                "recoveries": len(recovered),
                "events": events,
                "eventProvenance": _event_provenance(transitions, recovered, today=today),
            }
        )
        # SHADOW ONLY — see the module docstring.  Nothing reaches the BDVM
        # events file (src/bdvm/service.py loads that for every valuation).
        _LOGGER.info(
            "shadow: %d injury event(s) derived (%d transitions %s, %d recoveries) — "
            "NOT merged into the BDVM events file",
            len(events),
            len(transitions),
            run["transitions"],
            len(recovered),
        )

    try:
        _record_shadow_run(run)
    except OSError as exc:
        _LOGGER.error("shadow ledger write failed: %s — prior snapshot untouched", exc)
        return 1

    # The next comparison base: this run's resolved entries, plus the LAST KNOWN
    # row of any player still on the report whose identity did not resolve this
    # run -- dropping him would make his next resolved appearance a "new injury".
    resolved_ids = {e.espn_athlete_id for e in resolved}
    carried = [
        e
        for e in prior
        if e.espn_athlete_id in current_ids and e.espn_athlete_id not in resolved_ids
    ]
    _atomic_write_json(_PRIOR_PATH, [e.to_dict() for e in [*resolved, *carried]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
