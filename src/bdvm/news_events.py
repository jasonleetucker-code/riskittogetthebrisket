"""News → BDVM structured events (auto-ingested speculation lane).

Maps aggregated news items onto the closed §7 ontology and merges them
into ``data/bdvm/events/<season>.json`` — the file ``run_valuation``
already loads.  This converts a dormant subsystem (the events engine
shipped fully built but fed by an empty file) into a live one that
reacts to the real world between weekly snapshots.

Safety rules, all structural:

* **Closed ontology only.**  A headline that doesn't match a
  conservative keyword rule maps to NOTHING — never a guessed type.
* **Speculation lane, always.**  Auto-ingested events carry
  ``confidence = 0.45`` — below the §7 speculation threshold (0.5), so
  ``effective_impact`` suppresses every µ/hazard/games channel and only
  ``sigma_mult`` survives.  Headlines can widen uncertainty; they can
  never move a player's mean.  Raising confidence above 0.5 is a HUMAN
  edit to the events file, not something this module can do.
* **Ambiguous mentions skipped.**  A mention the news layer couldn't
  attribute to exactly one player never becomes an event.
* **Deduped + pruned.**  ``eventId = news:<item-id>:<player-key>`` —
  re-ingesting the same story is a no-op; auto events older than
  ``_AUTO_EVENT_MAX_AGE_DAYS`` are pruned on merge.  Human-authored
  events (any other eventId shape) are NEVER touched.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from src.bdvm.events import EVENTS_DIR

# Auto events are pruned after this many days (the longest half-life
# among mapped types is 180d; by 90d a 0.45-confidence sigma widener
# has decayed to noise).
_AUTO_EVENT_MAX_AGE_DAYS = 90

_AUTO_CONFIDENCE = 0.45  # strictly below the §7 speculation threshold
_AUTO_RELIABILITY = 0.6  # aggregated headlines, not primary reporting

# Conservative keyword rules, checked IN ORDER — first match wins.
# Only ontology types with an unambiguous news-side signal appear;
# everything else stays human-entry only.
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("SURGERY", re.compile(r"surgery|torn|\bacl\b|achilles|season[- ]ending", re.I)),
    ("SUSPENSION", re.compile(r"suspend|suspension", re.I)),
    (
        "ACTIVATED_RETURN",
        re.compile(r"activated|cleared to (?:play|practice)|returns? to practice", re.I),
    ),
    (
        "INJURY",
        re.compile(
            r"injur|placed on ir|\bon the ir\b|\bto ir\b|concussion|sprain|strain|fracture|hamstring",
            re.I,
        ),
    ),
    (
        "PRACTICE_LIMITATION",
        re.compile(r"questionable|doubtful|limited (?:in )?practice|did not practice", re.I),
    ),
    (
        "DEPTH_CHART_PROMOTION",
        re.compile(
            r"named (?:the )?starter|promoted to|elevated to (?:the )?(?:starting|first)", re.I
        ),
    ),
    (
        "DEPTH_CHART_DEMOTION",
        re.compile(r"demoted|loses? (?:the )?starting (?:job|role)|benched", re.I),
    ),
    ("TRADE", re.compile(r"\btrade[ds]?\b|acquired (?:via|in a) trade", re.I)),
    ("RELEASE", re.compile(r"released|waived|\bcut\b", re.I)),
    ("CONTRACT_EXTENSION", re.compile(r"extension|extended (?:his|the) contract", re.I)),
    ("FRANCHISE_TAG", re.compile(r"franchise tag", re.I)),
    ("SIGNING", re.compile(r"\bsigns?\b|\bsigned\b|agrees? to (?:a )?(?:deal|terms)", re.I)),
)


def classify_news_item(item: Mapping[str, Any]) -> str | None:
    """Ontology type for one news item, or None (never guess)."""
    text = f"{item.get('headline') or ''} {item.get('body') or item.get('summary') or ''}"
    if not text.strip():
        return None
    for event_type, pattern in _RULES:
        if pattern.search(text):
            return event_type
    return None


def map_news_items_to_events(
    items: Iterable[Mapping[str, Any]],
    *,
    name_normalizer: Callable[[str], str],
) -> list[dict[str, Any]]:
    """News item dicts → event dicts in the events-file JSON shape."""
    events: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, Mapping):
            continue
        event_type = classify_news_item(item)
        if event_type is None:
            continue
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            continue
        ts = str(item.get("ts") or item.get("publishedAt") or "")
        effective_date = ts[:10] if len(ts) >= 10 else ""
        if not effective_date:
            continue
        headline = str(item.get("headline") or "")[:140]
        for mention in item.get("players") or []:
            if not isinstance(mention, Mapping):
                continue
            if mention.get("ambiguous"):
                continue  # attribution unclear → no event, ever
            name = str(mention.get("name") or "").strip()
            if not name:
                continue
            player_key = name_normalizer(name)
            events.append(
                {
                    "eventId": f"news:{item_id}:{player_key}",
                    "playerKey": player_key,
                    "eventType": event_type,
                    "effectiveDate": effective_date,
                    "confidence": _AUTO_CONFIDENCE,
                    "sourceReliability": _AUTO_RELIABILITY,
                    "notes": headline,
                }
            )
    return events


def _is_auto(event: Mapping[str, Any]) -> bool:
    return str(event.get("eventId") or "").startswith("news:")


def _is_stale_auto(event: Mapping[str, Any], today: datetime) -> bool:
    if not _is_auto(event):
        return False
    try:
        effective = datetime.fromisoformat(str(event.get("effectiveDate"))[:10]).replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError):
        return True  # unparseable auto event → prune
    return today - effective > timedelta(days=_AUTO_EVENT_MAX_AGE_DAYS)


def merge_events_file(
    new_events: list[dict[str, Any]],
    *,
    season: int,
    base_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Merge auto events into the season's events file.

    Existing events win on eventId collision (an event, once written,
    is stable — a human may have edited its confidence upward).  Only
    auto (``news:``) events are ever pruned; human-authored entries
    pass through untouched, always.
    """
    root = base_dir or EVENTS_DIR
    path = root / f"{season}.json"
    today = now or datetime.now(timezone.utc)

    existing: list[dict[str, Any]] = []
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            existing = list(payload.get("events") or [])
        except (OSError, ValueError):
            # A corrupt events file must not brick ingestion, but we
            # also must not silently discard human entries — refuse.
            return {"ok": False, "reason": "events_file_unreadable", "path": str(path)}

    seen = {str(e.get("eventId")) for e in existing if isinstance(e, Mapping)}
    added = [e for e in new_events if e["eventId"] not in seen]
    kept = [e for e in existing if isinstance(e, Mapping) and not _is_stale_auto(e, today)]
    pruned = len(existing) - len(kept)

    if not added and not pruned:
        return {
            "ok": True,
            "added": 0,
            "pruned": 0,
            "total": len(existing),
            "unchanged": True,
        }

    merged = kept + added
    root.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"events": merged}, indent=1) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    return {
        "ok": True,
        "added": len(added),
        "pruned": pruned,
        "total": len(merged),
        "path": str(path),
    }


def ingest_news_events(
    items: Iterable[Mapping[str, Any]],
    *,
    season: int,
    name_normalizer: Callable[[str], str],
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """End-to-end: classify + map + merge.  Never raises upward design;
    callers still wrap (piggyback posture)."""
    events = map_news_items_to_events(items, name_normalizer=name_normalizer)
    summary = merge_events_file(events, season=season, base_dir=base_dir)
    summary["mapped"] = len(events)
    return summary
