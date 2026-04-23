"""News ingestion primitives.

Defines the normalized ``NewsItem`` contract that every provider
must emit, and the ``NewsProvider`` abstract base class that the
service layer consumes.

The contract is deliberately a superset of two things:

1. The existing frontend ``NewsItem`` shape in
   ``frontend/lib/news-service.js`` (``id``, ``ts``, ``provider``,
   ``providerLabel``, ``severity``, ``kind``, ``headline``, ``body``,
   ``players[]``, ``url``).  Preserving these fields means the
   backend can start answering 200 without any frontend code change.
2. The richer surface requested for future-proofing —
   ``publishedAt`` (alias of ``ts``), ``summary`` (alias of
   ``body``), ``impactedPlayers`` (flat name list), ``tags``,
   ``confidence``, ``relevance``.

Aliases are duplicated on every item rather than computed
client-side so consumers of either vocabulary work identically.
"""
from __future__ import annotations

import abc
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, List, Literal, Optional

Severity = Literal["alert", "watch", "info"]
Impact = Literal["positive", "negative", "neutral"]


@dataclass(frozen=True)
class PlayerMention:
    """Single player reference attached to a news item."""

    name: str
    impact: Impact = "neutral"

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "impact": self.impact}


@dataclass(frozen=True)
class NewsItem:
    """Normalized news item emitted by every provider.

    ``id`` must be stable across refetches of the same underlying
    event so the frontend's cache + dedupe logic works.  Providers
    derive it from a content hash (see ``stable_id``) unless the
    upstream gives a real identifier.
    """

    id: str
    ts: str  # ISO 8601 UTC
    provider: str
    provider_label: str
    severity: Severity
    kind: str
    headline: str
    body: str = ""
    players: List[PlayerMention] = field(default_factory=list)
    url: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    confidence: Optional[float] = None
    relevance: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize using both legacy and new field names.

        Consumers of the old contract (``body``, ``players``,
        ``ts``) and new contract (``summary``, ``impactedPlayers``,
        ``publishedAt``) both see identical data.
        """
        players_out = [p.to_dict() for p in self.players]
        impacted_names = [p.name for p in self.players]
        return {
            # ── legacy fields kept verbatim ───────────────────────
            "id": self.id,
            "ts": self.ts,
            "provider": self.provider,
            "providerLabel": self.provider_label,
            "severity": self.severity,
            "kind": self.kind,
            "headline": self.headline,
            "body": self.body,
            "players": players_out,
            "url": self.url,
            # ── enriched aliases ─────────────────────────────────
            "publishedAt": self.ts,
            "summary": self.body,
            "impactedPlayers": impacted_names,
            "tags": list(self.tags),
            "confidence": self.confidence,
            "relevance": self.relevance,
        }


def stable_id(provider: str, payload: str) -> str:
    """Build a deterministic, short id for an item.

    ``payload`` should be something that uniquely identifies the
    event — for an RSS entry the GUID + pub-date, for a Sleeper
    trending row the player_id + rounded timestamp bucket.  Using
    a SHA-1 prefix keeps the id URL-safe and short enough for
    logs.
    """
    h = hashlib.sha1(f"{provider}:{payload}".encode("utf-8")).hexdigest()
    return f"{provider.lower()}-{h[:12]}"


def to_iso_utc(dt: datetime) -> str:
    """Render a datetime as an ISO 8601 UTC string ending in ``Z``-free ``+00:00``."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


class NewsProvider(abc.ABC):
    """Abstract contract for a news source.

    A provider is expected to be cheap to construct and side-effect
    free in ``__init__``.  All network I/O happens inside
    ``fetch`` so the aggregator can catch and isolate failures.

    Subclasses must set ``name`` and ``label`` as class attributes,
    and implement ``fetch``.  ``fetch`` MUST return a list (not a
    generator) and MUST NOT raise — return an empty list on any
    upstream failure.  The service layer will log and continue.
    """

    name: str = ""
    label: str = ""
    # Soft timeout hint in seconds — the service uses this when
    # dispatching providers so a single slow provider cannot block
    # the whole response.
    timeout_s: float = 5.0

    def __init__(self, **config: Any) -> None:
        self.config = dict(config or {})

    @abc.abstractmethod
    def fetch(
        self,
        *,
        player_names: Optional[Iterable[str]] = None,
        limit: int = 50,
    ) -> List[NewsItem]:
        """Return a list of normalized news items.

        ``player_names`` (optional) is the union of every player
        currently visible in the live data contract.  Providers
        that only surface headlines (ESPN RSS) use it to tag
        ``players`` via substring match.  Providers that already
        emit per-player data (Sleeper trending) ignore it.
        """


__all__ = [
    "Impact",
    "NewsItem",
    "NewsProvider",
    "PlayerMention",
    "Severity",
    "stable_id",
    "to_iso_utc",
]
