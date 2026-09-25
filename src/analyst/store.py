"""The analyst claim ledger — append-only persistence (C6-ANA-01, OD-03).

``src.analyst.claim`` defines what a take IS; this module stores takes and
the content they came from, and nothing else.  It adds no ingestion (no feed
reader, no transcript fetch, no extraction), no scoring and no freshness
policy.  The as-of READ contract lives in :mod:`src.analyst.asof`.

It is the shared substrate later intelligence consumers read (Player File
intelligence, podcast / YouTube / news ingestion, the homepage ticker, the
Weekly Report Studio).  Those consumers WRITE through :func:`ingest` and
READ through ``src.analyst.asof`` — a second claim store, or a consumer
interpreting ``data/analyst_ledger.sqlite`` directly, is a second owner.

Posture — deliberately the same as ``src/history/store.py`` (C1-U4):

* **INSERT-only.**  No row is ever updated or deleted.
* **Idempotent.**  Re-ingesting identical content/claims is a counted no-op.
* **Conflicts are surfaced, never applied.**  Re-ingesting the same identity
  with different content leaves the stored row untouched and reports a
  ``conflicts`` entry — a record that can be silently rewritten is not a
  record.
* **Corrections are explicit rows.**  :func:`correct_claim` writes the
  corrected reading as a NEW row and links it in ``corrections``; the
  original stays readable.  Queries prefer the correction (from the moment
  it was recorded, under the replay basis — see ``asof``).

Two record kinds
────────────────
``content``  one piece of analyst content (an episode, a video, an article,
             a feed item) with its provenance: platform, show, url,
             ``published_at``, ``observed_at``, the analysts it speaks for,
             and the producer (``origin``).  Recording content asserts that
             claim extraction RAN over it — which is what lets the as-of
             layer tell "the analyst said nothing about this asset in content
             we processed" (EMPTY) from "we have no content from this analyst
             at all" (UNAVAILABLE).  Missing is never empty.
``claims``   one :class:`~src.analyst.claim.AnalystClaim` per row, plus the
             ingestion envelope (origin, parser version, extraction
             confidence, said-at precision).  Every claim belongs to a
             recorded content item; a claim whose content was never recorded
             cannot enter.

Identity
────────
Content: ``(platform, content_id)``.

Claim: one UTTERANCE — ``(analyst_id, platform, content_id, asset_key,
said_at)`` plus a correction ``revision`` (0 for an original).  Stance is
deliberately NOT identity: two ingestions that disagree about what one
utterance meant are a conflict for a human, not two claims.

Asset keys come from the canonical identity owners, never from name
matching here: ``player:<sleeperId>`` from a RESOLVED
:class:`src.identity.resolution.Resolution`, ``mpick:*`` from
:class:`src.identity.picks.MarketPickRef` — the same namespace
``src.history.keys`` uses, so an analyst take and a value history for one
asset share one key.  The name-grade ``name:*`` key the temporal ledger
tolerates is REFUSED here (``unresolved_identity``): an analyst take about
a name the identity owner could not resolve stays with its extractor until
it resolves, rather than entering under a key no other surface joins on.

Time
────
Every stored instant is timezone-aware UTC; a naive datetime is refused,
never assumed.  ``said_at`` / ``published_at`` carry a precision
(``instant`` or ``day``) because day-granular feeds cannot support an
instant claim — a ``day`` stamp is normalised to midnight UTC and the
as-of layer treats it conservatively.  ``recorded_at`` is the ledger's own
write instant; it is stamped here, and the override exists only as a test
/ deterministic-replay seam that may never be in the future.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Sequence

from src.analyst.claim import (
    AnalystClaim,
    AssetSide,
    Condition,
    GameType,
    Provenance,
    SourceRef,
    TakeType,
)
from src.analyst.stance import SourceLabel, Stance
from src.history.keys import PICK_PREFIX, PLAYER_PREFIX, is_valid_asset_key, pick_asset_key
from src.identity.picks import MarketPickRef
from src.identity.resolution import Resolution

DB_PATH: Path = Path(__file__).resolve().parents[2] / "data" / "analyst_ledger.sqlite"

SCHEMA_VERSION = 1


class LedgerError(ValueError):
    """A write or correction that must not enter the ledger (fail closed)."""


class TimePrecision(str, Enum):
    """How precisely a producer knows WHEN something was said/published."""

    INSTANT = "instant"
    #: Only the UTC date is known (a podcast feed's publish date).  Stored
    #: at midnight UTC; the as-of layer never lets it answer an instant
    #: query on its own day.
    DAY = "day"


class ExtractionConfidence(str, Enum):
    """How confident the EXTRACTION PROCESS is that it captured the claim.

    Never the analyst's conviction (that is ``Stance``).  ``UNKNOWN`` is the
    default and is not a midpoint — an extractor that publishes no
    confidence says so.
    """

    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# ── Identity keying — delegated to the canonical owners ─────────────────

REASON_UNRESOLVED_IDENTITY = "unresolved_identity"
REASON_INVALID_ASSET_KEY = "invalid_asset_key"


def asset_key_for_resolution(resolution: Resolution) -> str | None:
    """``player:<sleeperId>`` for a RESOLVED identity, else ``None``.

    An unresolved / ambiguous resolution has no key — the caller keeps the
    take out of the ledger rather than guessing.
    """
    if not resolution.resolved or not str(resolution.sleeper_id or "").strip():
        return None
    return f"{PLAYER_PREFIX}{str(resolution.sleeper_id).strip()}"


def asset_key_for_market_pick(ref: MarketPickRef) -> str:
    """``mpick:*`` for a market pick reference (C1-U3 owner)."""
    return ref.canonical_id


def asset_key_for_board_pick_name(name: Any) -> str | None:
    """``mpick:*`` for a board pick label, via the pick-identity owner."""
    return pick_asset_key(name)


def is_ledger_asset_key(key: Any) -> bool:
    """Only resolved player ids and market picks are ledger keys."""
    k = str(key or "")
    if not is_valid_asset_key(k):
        return False
    return k.startswith(PLAYER_PREFIX) or k.startswith(PICK_PREFIX)


def _asset_key_rejection(key: str) -> str | None:
    if is_ledger_asset_key(key):
        return None
    if is_valid_asset_key(key):
        # A structurally valid key that is neither player nor pick is the
        # name grade — identity the owner could not resolve.
        return REASON_UNRESOLVED_IDENTITY
    return REASON_INVALID_ASSET_KEY


# ── Records ─────────────────────────────────────────────────────────────


def _require_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise LedgerError(f"{name} is required")
    return text


@dataclass(frozen=True)
class ContentRecord:
    """One piece of analyst content, and the claim that extraction ran on it.

    ``observed_at`` is when the platform fetched it; ``None`` means "at the
    ledger write" and is stored as unknown rather than defaulted, so an
    identical re-ingest stays identical.
    """

    platform: str
    content_id: str
    analyst_ids: tuple[str, ...]
    published_at: datetime
    origin: str
    show_id: str = ""
    url: str = ""
    title: str = ""
    published_precision: TimePrecision = TimePrecision.INSTANT
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_text(self.platform, "ContentRecord.platform")
        _require_text(self.content_id, "ContentRecord.content_id")
        _require_text(self.origin, "ContentRecord.origin")
        ids = tuple(str(a).strip() for a in self.analyst_ids)
        if not ids or any(not a for a in ids):
            raise LedgerError(
                "ContentRecord.analyst_ids must name every analyst the content speaks for"
            )
        object.__setattr__(self, "analyst_ids", tuple(sorted(set(ids))))
        object.__setattr__(self, "published_precision", TimePrecision(self.published_precision))


@dataclass(frozen=True)
class LedgerEntry:
    """The ingestion envelope around one claim — facts about OUR capture."""

    claim: AnalystClaim
    origin: str
    parser_version: str = ""
    extraction_confidence: ExtractionConfidence = ExtractionConfidence.UNKNOWN
    said_at_precision: TimePrecision = TimePrecision.INSTANT

    def __post_init__(self) -> None:
        _require_text(self.origin, "LedgerEntry.origin")
        object.__setattr__(
            self, "extraction_confidence", ExtractionConfidence(self.extraction_confidence)
        )
        object.__setattr__(self, "said_at_precision", TimePrecision(self.said_at_precision))


@dataclass(frozen=True)
class StoredContent:
    ledger_id: int
    platform: str
    content_id: str
    analyst_ids: tuple[str, ...]
    published_at: datetime
    published_precision: TimePrecision
    observed_at: datetime | None
    origin: str
    show_id: str
    url: str
    title: str
    recorded_at: datetime
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ledgerId": self.ledger_id,
            "platform": self.platform,
            "contentId": self.content_id,
            "analystIds": list(self.analyst_ids),
            "publishedAt": self.published_at.isoformat(),
            "publishedPrecision": self.published_precision.value,
            "observedAt": self.observed_at.isoformat() if self.observed_at else None,
            "origin": self.origin,
            "showId": self.show_id,
            "url": self.url,
            "title": self.title,
            "recordedAt": self.recorded_at.isoformat(),
        }


@dataclass(frozen=True)
class StoredClaim:
    """A claim as the ledger holds it: the claim plus its envelope."""

    ledger_id: int
    claim: AnalystClaim
    origin: str
    parser_version: str
    extraction_confidence: ExtractionConfidence
    said_at_precision: TimePrecision
    revision: int
    recorded_at: datetime
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        out = self.claim.to_dict()
        out.update(
            {
                "ledgerId": self.ledger_id,
                "origin": self.origin,
                "parserVersion": self.parser_version,
                "extractionConfidence": self.extraction_confidence.value,
                "saidAtPrecision": self.said_at_precision.value,
                "revision": self.revision,
                "recordedAt": self.recorded_at.isoformat(),
            }
        )
        return out


@dataclass(frozen=True)
class IngestResult:
    """What one :func:`ingest` call did.  Nothing is ever silently dropped."""

    content_status: str  # written | duplicate | conflict | rejected
    written: int = 0
    duplicates: int = 0
    conflicts: tuple[dict[str, Any], ...] = ()
    rejected: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "contentStatus": self.content_status,
            "written": self.written,
            "duplicates": self.duplicates,
            "conflicts": list(self.conflicts),
            "rejected": list(self.rejected),
        }


# ── Schema / connections ────────────────────────────────────────────────

_SETUP_LOCK = threading.Lock()
_SETUP_DONE: dict[str, bool] = {}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS content (
    id                  INTEGER PRIMARY KEY,
    platform            TEXT NOT NULL,
    content_id          TEXT NOT NULL,
    show_id             TEXT NOT NULL DEFAULT '',
    url                 TEXT NOT NULL DEFAULT '',
    title               TEXT NOT NULL DEFAULT '',
    published_at        TEXT NOT NULL,
    published_precision TEXT NOT NULL,
    observed_at         TEXT,
    analyst_ids_json    TEXT NOT NULL,
    origin              TEXT NOT NULL,
    recorded_at         TEXT NOT NULL,
    content_hash        TEXT NOT NULL,
    UNIQUE (platform, content_id)
);

CREATE TABLE IF NOT EXISTS content_analysts (
    content_row_id INTEGER NOT NULL REFERENCES content(id),
    analyst_id     TEXT NOT NULL,
    PRIMARY KEY (content_row_id, analyst_id)
);
CREATE INDEX IF NOT EXISTS idx_content_analysts_analyst
    ON content_analysts(analyst_id);

CREATE TABLE IF NOT EXISTS claims (
    id                    INTEGER PRIMARY KEY,
    identity_key          TEXT NOT NULL UNIQUE,
    revision              INTEGER NOT NULL,
    analyst_id            TEXT NOT NULL,
    platform              TEXT NOT NULL,
    content_id            TEXT NOT NULL,
    show_id               TEXT NOT NULL DEFAULT '',
    url                   TEXT NOT NULL DEFAULT '',
    asset_key             TEXT NOT NULL,
    said_at               TEXT NOT NULL,
    said_at_precision     TEXT NOT NULL,
    stance                TEXT NOT NULL,
    source_label          TEXT NOT NULL,
    take_type             TEXT NOT NULL,
    provenance            TEXT NOT NULL,
    game_type             TEXT NOT NULL,
    asset_side            TEXT NOT NULL,
    conditions_json       TEXT NOT NULL,
    quote                 TEXT NOT NULL DEFAULT '',
    thesis_id             TEXT NOT NULL DEFAULT '',
    thesis_key            TEXT NOT NULL,
    discovered_at         TEXT,
    supersedes            TEXT NOT NULL DEFAULT '',
    notes                 TEXT NOT NULL DEFAULT '',
    tags_json             TEXT NOT NULL,
    origin                TEXT NOT NULL,
    parser_version        TEXT NOT NULL DEFAULT '',
    extraction_confidence TEXT NOT NULL,
    recorded_at           TEXT NOT NULL,
    content_hash          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claims_asset ON claims(asset_key, analyst_id);
CREATE INDEX IF NOT EXISTS idx_claims_content ON claims(platform, content_id);
CREATE INDEX IF NOT EXISTS idx_claims_thesis ON claims(thesis_key);

CREATE TABLE IF NOT EXISTS corrections (
    superseded_id  INTEGER NOT NULL REFERENCES claims(id),
    superseding_id INTEGER NOT NULL REFERENCES claims(id),
    reason         TEXT NOT NULL,
    recorded_at    TEXT NOT NULL,
    PRIMARY KEY (superseded_id)
);
"""


def _ensure_schema(path: Path) -> None:
    key = str(path)
    if _SETUP_DONE.get(key):
        return
    with _SETUP_LOCK:
        if _SETUP_DONE.get(key):
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=10.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.executescript(_SCHEMA)
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.commit()
        finally:
            conn.close()
        _SETUP_DONE[key] = True


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Write connection (creates the schema).  Readers use
    :func:`connect_readonly`."""
    target = Path(path or DB_PATH)
    _ensure_schema(target)
    conn = sqlite3.connect(str(target), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def connect_readonly(path: Path | None = None) -> sqlite3.Connection | None:
    """Read-only connection, or ``None`` when no ledger exists.

    A query must never create the database as a side effect — "no ledger"
    and "empty ledger" would become indistinguishable on disk.
    """
    target = Path(path or DB_PATH)
    if not target.exists():
        return None
    conn = sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def _reset_setup_cache_for_tests() -> None:
    with _SETUP_LOCK:
        _SETUP_DONE.clear()


# ── Time helpers ────────────────────────────────────────────────────────


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise LedgerError(f"{name} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise LedgerError(f"{name} is naive; the analyst ledger stores UTC-aware instants only")
    return value.astimezone(timezone.utc)


def _at_precision(value: datetime, precision: TimePrecision) -> datetime:
    if precision is TimePrecision.DAY:
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    return value


def _not_before(later: datetime, earlier: datetime, earlier_precision: TimePrecision) -> bool:
    """Is ``later`` at or after ``earlier`` given ``earlier``'s precision?"""
    if earlier_precision is TimePrecision.DAY:
        return later.date() >= earlier.date()
    return later >= earlier


def _resolve_recorded_at(recorded_at: datetime | None) -> datetime:
    now = utc_now()
    if recorded_at is None:
        return now
    stamp = _aware_utc(recorded_at, "recorded_at")
    if stamp > now:
        # A future write instant would let the replay basis "know" a
        # claim before the ledger held it.
        raise LedgerError("recorded_at may not be in the future")
    return stamp


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse(value: Any) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value else None


def _digest(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


# ── Content ─────────────────────────────────────────────────────────────


def _normalize_content(content: ContentRecord, recorded_at: datetime) -> ContentRecord:
    published = _at_precision(
        _aware_utc(content.published_at, "published_at"), content.published_precision
    )
    observed = None
    if content.observed_at is not None:
        observed = _aware_utc(content.observed_at, "observed_at")
        if not _not_before(observed, published, content.published_precision):
            raise LedgerError("observed_at precedes published_at — content cannot be seen early")
        if observed > recorded_at:
            raise LedgerError("observed_at is after the ledger write — it cannot be known yet")
    elif not _not_before(recorded_at, published, content.published_precision):
        raise LedgerError("published_at is after the ledger write")
    return dataclasses.replace(content, published_at=published, observed_at=observed)


def content_hash(content: ContentRecord) -> str:
    return _digest(
        {
            "show_id": content.show_id,
            "url": content.url,
            "title": content.title,
            "published_at": _iso(content.published_at),
            "published_precision": content.published_precision.value,
            "observed_at": _iso(content.observed_at),
            "analyst_ids": list(content.analyst_ids),
            "origin": content.origin,
        }
    )


def stored_content_from_row(row: sqlite3.Row) -> StoredContent:
    return StoredContent(
        ledger_id=int(row["id"]),
        platform=row["platform"],
        content_id=row["content_id"],
        analyst_ids=tuple(json.loads(row["analyst_ids_json"])),
        published_at=datetime.fromisoformat(row["published_at"]),
        published_precision=TimePrecision(row["published_precision"]),
        observed_at=_parse(row["observed_at"]),
        origin=row["origin"],
        show_id=row["show_id"],
        url=row["url"],
        title=row["title"],
        recorded_at=datetime.fromisoformat(row["recorded_at"]),
        content_hash=row["content_hash"],
    )


def _fetch_content(
    conn: sqlite3.Connection, platform: str, content_id: str
) -> StoredContent | None:
    row = conn.execute(
        "SELECT * FROM content WHERE platform=? AND content_id=?", (platform, content_id)
    ).fetchone()
    return stored_content_from_row(row) if row is not None else None


# ── Claims ──────────────────────────────────────────────────────────────


def _normalize_entry(entry: LedgerEntry) -> LedgerEntry:
    claim = entry.claim
    said = _at_precision(_aware_utc(claim.said_at, "said_at"), entry.said_at_precision)
    discovered = (
        _aware_utc(claim.discovered_at, "discovered_at")
        if claim.discovered_at is not None
        else None
    )
    return dataclasses.replace(
        entry,
        claim=dataclasses.replace(claim, said_at=said, discovered_at=discovered),
    )


def claim_identity_key(entry: LedgerEntry, revision: int) -> str:
    c = entry.claim
    raw = "|".join(
        [
            c.source.analyst_id,
            c.source.platform,
            c.source.content_id,
            c.asset_key,
            c.said_at.isoformat(),
            str(int(revision)),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def claim_content_hash(entry: LedgerEntry) -> str:
    """Hash of everything that is NOT identity — the claim's facts plus its
    envelope.  Equal → idempotent re-ingest; unequal → surfaced conflict."""
    c = entry.claim
    return _digest(
        {
            "show_id": c.source.show_id,
            "url": c.source.url,
            "stance": c.stance.value,
            "source_label": c.source_label.value,
            "take_type": c.take_type.value,
            "provenance": c.provenance.value,
            "game_type": c.game_type.value,
            "asset_side": c.asset_side.value,
            "conditions": [[x.text, x.kind] for x in c.conditions],
            "quote": c.quote,
            "thesis_id": c.thesis_id,
            "discovered_at": _iso(c.discovered_at),
            "supersedes": c.supersedes,
            "notes": c.notes,
            "tags": list(c.tags),
            "said_at_precision": entry.said_at_precision.value,
            "origin": entry.origin,
            "parser_version": entry.parser_version,
            "extraction_confidence": entry.extraction_confidence.value,
        }
    )


def _claim_rejection(
    entry: LedgerEntry, content: StoredContent, recorded_at: datetime
) -> str | None:
    """``None`` when the (normalised) entry may enter, else the reason."""
    c = entry.claim
    reason = _asset_key_rejection(c.asset_key)
    if reason:
        return reason
    is_pick = c.asset_key.startswith(PICK_PREFIX)
    if is_pick and c.asset_side not in (AssetSide.PICK, AssetSide.UNKNOWN):
        return "asset_side_mismatch"
    if not is_pick and c.asset_side is AssetSide.PICK:
        return "asset_side_mismatch"
    if (c.source.platform, c.source.content_id) != (content.platform, content.content_id):
        return "content_mismatch"
    if c.source.analyst_id not in content.analyst_ids:
        return "analyst_not_in_content"
    if c.source.show_id and content.show_id and c.source.show_id != content.show_id:
        return "show_mismatch"
    if c.discovered_at is not None:
        if c.discovered_at > recorded_at:
            return "discovered_after_recorded"
        if not _not_before(c.discovered_at, c.said_at, entry.said_at_precision):
            return "discovered_before_said"
    return None


def _claim_row(entry: LedgerEntry, identity: str, revision: int, recorded: datetime) -> dict:
    c = entry.claim
    return {
        "identity_key": identity,
        "revision": revision,
        "analyst_id": c.source.analyst_id,
        "platform": c.source.platform,
        "content_id": c.source.content_id,
        "show_id": c.source.show_id,
        "url": c.source.url,
        "asset_key": c.asset_key,
        "said_at": c.said_at.isoformat(),
        "said_at_precision": entry.said_at_precision.value,
        "stance": c.stance.value,
        "source_label": c.source_label.value,
        "take_type": c.take_type.value,
        "provenance": c.provenance.value,
        "game_type": c.game_type.value,
        "asset_side": c.asset_side.value,
        "conditions_json": json.dumps([{"text": x.text, "kind": x.kind} for x in c.conditions]),
        "quote": c.quote,
        "thesis_id": c.thesis_id,
        "thesis_key": c.thesis_key,
        "discovered_at": _iso(c.discovered_at),
        "supersedes": c.supersedes,
        "notes": c.notes,
        "tags_json": json.dumps(list(c.tags)),
        "origin": entry.origin,
        "parser_version": entry.parser_version,
        "extraction_confidence": entry.extraction_confidence.value,
        "recorded_at": recorded.isoformat(),
        "content_hash": claim_content_hash(entry),
    }


def _insert(conn: sqlite3.Connection, table: str, row: dict[str, Any]) -> int:
    cols = list(row)
    cur = conn.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        [row[c] for c in cols],
    )
    return int(cur.lastrowid)


def stored_claim_from_row(row: sqlite3.Row) -> StoredClaim:
    claim = AnalystClaim(
        source=SourceRef(
            analyst_id=row["analyst_id"],
            content_id=row["content_id"],
            platform=row["platform"],
            show_id=row["show_id"],
            url=row["url"],
        ),
        asset_key=row["asset_key"],
        stance=Stance(row["stance"]),
        source_label=SourceLabel(row["source_label"]),
        take_type=TakeType(row["take_type"]),
        said_at=datetime.fromisoformat(row["said_at"]),
        provenance=Provenance(row["provenance"]),
        game_type=GameType(row["game_type"]),
        asset_side=AssetSide(row["asset_side"]),
        conditions=tuple(
            Condition(text=x["text"], kind=x["kind"]) for x in json.loads(row["conditions_json"])
        ),
        quote=row["quote"],
        thesis_id=row["thesis_id"],
        discovered_at=_parse(row["discovered_at"]),
        supersedes=row["supersedes"],
        notes=row["notes"],
        tags=tuple(json.loads(row["tags_json"])),
    )
    return StoredClaim(
        ledger_id=int(row["id"]),
        claim=claim,
        origin=row["origin"],
        parser_version=row["parser_version"],
        extraction_confidence=ExtractionConfidence(row["extraction_confidence"]),
        said_at_precision=TimePrecision(row["said_at_precision"]),
        revision=int(row["revision"]),
        recorded_at=datetime.fromisoformat(row["recorded_at"]),
        content_hash=row["content_hash"],
    )


def _entry_ref(entry: LedgerEntry, reason: str) -> dict[str, Any]:
    c = entry.claim
    return {
        "reason": reason,
        "analystId": c.source.analyst_id,
        "platform": c.source.platform,
        "contentId": c.source.content_id,
        "assetKey": c.asset_key,
    }


# ── Write path ──────────────────────────────────────────────────────────


def ingest(
    content: ContentRecord,
    entries: Sequence[LedgerEntry] = (),
    *,
    path: Path | None = None,
    recorded_at: datetime | None = None,
) -> IngestResult:
    """Record one content item and the claims extracted from it, atomically.

    ``entries`` may be empty: that records "extraction ran on this content
    and found no claims", which is a real, queryable answer (EMPTY), not an
    absence.  Content and claims land in one transaction so the replay basis
    can never observe covered content whose claims are still being written.

    A content CONFLICT (same ``(platform, content_id)``, different
    provenance) rejects every claim in the call with ``content_conflict``:
    their provenance disagrees with the record, and choosing one silently is
    what this store refuses to do.
    """
    stamp = _resolve_recorded_at(recorded_at)
    entries = list(entries)
    try:
        normalized = _normalize_content(content, stamp)
    except LedgerError as exc:
        return IngestResult(
            content_status="rejected",
            rejected=tuple(
                [
                    {
                        "reason": f"content_rejected: {exc}",
                        "platform": content.platform,
                        "contentId": content.content_id,
                    }
                ]
                + [_entry_ref(e, "content_rejected") for e in entries]
            ),
        )

    written = 0
    duplicates = 0
    conflicts: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    conn = connect(path)
    try:
        chash = content_hash(normalized)
        stored = _fetch_content(conn, normalized.platform, normalized.content_id)
        if stored is None:
            row_id = _insert(
                conn,
                "content",
                {
                    "platform": normalized.platform,
                    "content_id": normalized.content_id,
                    "show_id": normalized.show_id,
                    "url": normalized.url,
                    "title": normalized.title,
                    "published_at": normalized.published_at.isoformat(),
                    "published_precision": normalized.published_precision.value,
                    "observed_at": _iso(normalized.observed_at),
                    "analyst_ids_json": json.dumps(list(normalized.analyst_ids)),
                    "origin": normalized.origin,
                    "recorded_at": stamp.isoformat(),
                    "content_hash": chash,
                },
            )
            for analyst in normalized.analyst_ids:
                conn.execute(
                    "INSERT INTO content_analysts(content_row_id, analyst_id) VALUES (?, ?)",
                    (row_id, analyst),
                )
            content_status = "written"
            stored = _fetch_content(conn, normalized.platform, normalized.content_id)
        elif stored.content_hash == chash:
            content_status = "duplicate"
        else:
            conn.commit()
            return IngestResult(
                content_status="conflict",
                conflicts=(
                    {
                        "kind": "content",
                        "platform": normalized.platform,
                        "contentId": normalized.content_id,
                        "storedHash": stored.content_hash,
                        "incomingHash": chash,
                    },
                ),
                rejected=tuple(_entry_ref(e, "content_conflict") for e in entries),
            )
        assert stored is not None

        for raw in entries:
            try:
                entry = _normalize_entry(raw)
            except LedgerError as exc:
                rejected.append(_entry_ref(raw, f"invalid_time: {exc}"))
                continue
            reason = _claim_rejection(entry, stored, stamp)
            if reason:
                rejected.append(_entry_ref(entry, reason))
                continue
            identity = claim_identity_key(entry, 0)
            chash_claim = claim_content_hash(entry)
            existing = conn.execute(
                "SELECT id, content_hash FROM claims WHERE identity_key=?", (identity,)
            ).fetchone()
            if existing is None:
                _insert(conn, "claims", _claim_row(entry, identity, 0, stamp))
                written += 1
            elif existing["content_hash"] == chash_claim:
                duplicates += 1
            else:
                conflicts.append(
                    {
                        "kind": "claim",
                        "ledgerId": int(existing["id"]),
                        "analystId": entry.claim.source.analyst_id,
                        "contentId": entry.claim.source.content_id,
                        "assetKey": entry.claim.asset_key,
                        "saidAt": entry.claim.said_at.isoformat(),
                        "storedHash": existing["content_hash"],
                        "incomingHash": chash_claim,
                    }
                )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

    return IngestResult(
        content_status=content_status,
        written=written,
        duplicates=duplicates,
        conflicts=tuple(conflicts),
        rejected=tuple(rejected),
    )


def correct_claim(
    superseded_id: int,
    corrected: LedgerEntry,
    reason: str,
    *,
    path: Path | None = None,
    recorded_at: datetime | None = None,
) -> int:
    """Supersede a stored claim with a corrected reading.  Returns the new id.

    For OUR extraction errors (wrong stance read, wrong player resolved) —
    not for an analyst changing their mind, which is a new claim carrying
    ``supersedes`` and is interpreted by ``claim.independent_claims``.

    The corrected claim is written as a new row (revision n+1 at its
    utterance coordinates) and linked; the original stays readable.  The
    corrected claim must belong to recorded content and pass every write
    check.  ``reason`` is mandatory — an unexplained correction is
    indistinguishable from tampering.
    """
    if not str(reason or "").strip():
        raise LedgerError("a correction requires a reason")
    stamp = _resolve_recorded_at(recorded_at)
    entry = _normalize_entry(corrected)
    conn = connect(path)
    try:
        if conn.execute("SELECT id FROM claims WHERE id=?", (superseded_id,)).fetchone() is None:
            raise LedgerError(f"correction references missing claim id {superseded_id}")
        if conn.execute(
            "SELECT 1 FROM corrections WHERE superseded_id=?", (superseded_id,)
        ).fetchone():
            raise LedgerError(f"claim {superseded_id} is already superseded; correct its successor")
        content = _fetch_content(conn, entry.claim.source.platform, entry.claim.source.content_id)
        if content is None:
            raise LedgerError("corrected claim references content that was never recorded")
        rejection = _claim_rejection(entry, content, stamp)
        if rejection:
            raise LedgerError(f"corrected claim rejected: {rejection}")
        c = entry.claim
        max_rev = conn.execute(
            "SELECT MAX(revision) FROM claims WHERE analyst_id=? AND platform=? "
            "AND content_id=? AND asset_key=? AND said_at=?",
            (
                c.source.analyst_id,
                c.source.platform,
                c.source.content_id,
                c.asset_key,
                c.said_at.isoformat(),
            ),
        ).fetchone()[0]
        revision = 0 if max_rev is None else int(max_rev) + 1
        new_id = _insert(
            conn, "claims", _claim_row(entry, claim_identity_key(entry, revision), revision, stamp)
        )
        conn.execute(
            "INSERT INTO corrections(superseded_id, superseding_id, reason, recorded_at) "
            "VALUES (?, ?, ?, ?)",
            (superseded_id, new_id, str(reason).strip(), stamp.isoformat()),
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return new_id


# ── Diagnostics ─────────────────────────────────────────────────────────


def all_claims(*, path: Path | None = None) -> list[StoredClaim]:
    """Every stored row INCLUDING superseded ones — operator/audit surface.
    Decision paths read through ``src.analyst.asof``."""
    conn = connect_readonly(path)
    if conn is None:
        return []
    try:
        rows = conn.execute("SELECT * FROM claims ORDER BY id").fetchall()
    finally:
        conn.close()
    return [stored_claim_from_row(r) for r in rows]


def coverage(path: Path | None = None) -> dict[str, Any]:
    """What the ledger holds.  Never creates the file."""
    conn = connect_readonly(path)
    if conn is None:
        return {"exists": False, "content": 0, "claims": 0, "reason": "no analyst ledger on disk"}
    try:
        n_content = conn.execute("SELECT COUNT(*) FROM content").fetchone()[0]
        n_claims = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        n_corr = conn.execute("SELECT COUNT(*) FROM corrections").fetchone()[0]
        analysts = conn.execute(
            "SELECT COUNT(DISTINCT analyst_id) FROM content_analysts"
        ).fetchone()[0]
        assets = conn.execute("SELECT COUNT(DISTINCT asset_key) FROM claims").fetchone()[0]
        by_platform = {
            r["platform"]: r["n"]
            for r in conn.execute(
                "SELECT platform, COUNT(*) AS n FROM content GROUP BY platform"
            ).fetchall()
        }
    finally:
        conn.close()
    return {
        "exists": True,
        "content": n_content,
        "claims": n_claims,
        "corrections": n_corr,
        "analysts": analysts,
        "assets": assets,
        "contentByPlatform": by_platform,
        "schemaVersion": SCHEMA_VERSION,
    }
