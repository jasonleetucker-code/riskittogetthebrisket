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

# A second same-type auto event for the same player inside this window
# is suppressed on merge.  The aggregate feed carries the same story
# from several providers (each with its own item id) plus weekly
# advice churn — without this, N providers would stack N sigma
# wideners for one real-world fact.
_DUP_EVENT_WINDOW_DAYS = 14

# List/advice articles name many players; real transaction or injury
# reporting names one or two.  An item mentioning more than this many
# players is editorial coverage, not an event about any of them.
_MAX_PLAYER_MENTIONS = 3

# Advice/listicle language → NOTHING, checked before every rule.  The
# aggregate feed includes fantasy-advice RSS providers whose headlines
# are full of transaction VOCABULARY about players nothing happened to
# ("trade targets", "who makes the cut", "buy low").  Conservative by
# design: suppressing a real story costs one speculative sigma
# widener; passing an advice column through costs dozens of them.
_ADVICE_NOISE_RE = re.compile(
    r"trade (?:target|value|advice|candidate|bait|chart|calculator)s?"
    r"|buy[- ]low|sell[- ]high|start[ /-]?sit|waiver wire|mock draft"
    r"|rankings?|sleepers?|projections?|preview|outlook|cheat sheet"
    r"|top[- ]\d+|tiers?\b|roster (?:projection|prediction|bubble)"
    r"|makes? the (?:final )?cut|cut candidates?",
    re.I,
)

# Conservative keyword rules, checked IN ORDER — first match wins.
# Only ontology types with an unambiguous news-side signal appear;
# everything else stays human-entry only.  ACTIVATED_RETURN is
# deliberately absent: its ontology impact NARROWS sigma, and the
# speculation lane may only widen — a headline-confidence event of
# that type would be a no-op at best (effective_impact clamps it).
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("SURGERY", re.compile(r"surgery|torn|\bacl\b|achilles|season[- ]ending", re.I)),
    ("SUSPENSION", re.compile(r"suspend|suspension", re.I)),
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
    ("RELEASE", re.compile(r"released|waived", re.I)),
    ("CONTRACT_EXTENSION", re.compile(r"extension|extended (?:his|the) contract", re.I)),
    ("FRANCHISE_TAG", re.compile(r"franchise tag", re.I)),
    ("SIGNING", re.compile(r"\bsigns?\b|\bsigned\b|agrees? to (?:a )?(?:deal|terms)", re.I)),
    (
        "ROLE_UNCERTAIN",
        re.compile(
            r"committee (?:backfield|approach)|timeshare|unclear (?:role|situation)"
            r"|muddled (?:backfield|situation)|split (?:carries|snaps|reps)",
            re.I,
        ),
    ),
)


def classify_news_item(item: Mapping[str, Any]) -> str | None:
    """Ontology type for one news item, or None (never guess)."""
    text = f"{item.get('headline') or ''} {item.get('body') or item.get('summary') or ''}"
    if not text.strip():
        return None
    if _ADVICE_NOISE_RE.search(text):
        return None  # advice/listicle coverage, not an event
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
        mentions = item.get("players") or []
        if len(mentions) > _MAX_PLAYER_MENTIONS:
            continue  # list article, not an event about any one player
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
    """Still machine-owned: news:* eventId AND speculation-lane
    confidence.  A human who raised confidence to >= 0.5 turned the
    entry into a confirmed, mean-affecting event — it keeps its
    news:* id (that's what existing-wins protects) but is no longer
    ours to prune; deleting it would silently discard human work while
    the event still carries most of its half-life strength."""
    if not str(event.get("eventId") or "").startswith("news:"):
        return False
    try:
        return float(event.get("confidence")) < 0.5
    except (TypeError, ValueError):
        return True  # news:* with unparseable confidence → still ours


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


def _event_date(event: Mapping[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(str(event.get("effectiveDate"))[:10]).replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError):
        return None


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
    payload: dict[str, Any] = {}
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A corrupt events file must not brick ingestion, but we
            # also must not silently discard human entries — refuse.
            return {"ok": False, "reason": "events_file_unreadable", "path": str(path)}
        # Valid JSON with the wrong SHAPE is the classic hand-edit slip
        # ("events": {...} instead of [...]).  Iterating it anyway
        # would masquerade the operator's entries as prunable garbage
        # and rewrite the file without them — refuse just as hard as
        # for unparseable JSON.
        if not isinstance(payload, dict) or not isinstance(payload.get("events", []), list):
            return {"ok": False, "reason": "events_file_invalid_shape", "path": str(path)}
        existing = list(payload.get("events") or [])
        if not all(isinstance(e, Mapping) for e in existing):
            return {"ok": False, "reason": "events_file_invalid_shape", "path": str(path)}

    seen = {str(e.get("eventId")) for e in existing}
    # Same-fact suppression: the same real-world story arrives from N
    # providers under N item ids, and again in next week's coverage.
    # One (playerKey, eventType) inside the window is one fact — the
    # sigma widener must not stack per provider.
    recent: set[tuple[str, str]] = set()
    for e in existing:
        d = _event_date(e)
        if d is not None and (today - d).days <= _DUP_EVENT_WINDOW_DAYS:
            recent.add((str(e.get("playerKey")), str(e.get("eventType"))))
    added = []
    for e in new_events:
        if e["eventId"] in seen:
            continue
        fact = (str(e.get("playerKey")), str(e.get("eventType")))
        if fact in recent:
            continue
        recent.add(fact)
        added.append(e)
    kept = [e for e in existing if not _is_stale_auto(e, today)]
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
    # Preserve any other top-level keys a human added (e.g. a
    # _comment block, the convention config/bdvm files use).
    tmp.write_text(
        json.dumps({**payload, "events": merged}, indent=1) + "\n",
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
