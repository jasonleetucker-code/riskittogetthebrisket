"""Append-only persistence for AnalystClaim (C6-ANA-01).

WHAT THIS ADDS, AND WHY IT IS A NEW FILE RATHER THAN A NEW OWNER
──────────────────────────────────────────────────────────────
``src.analyst.claim`` already defines what a take IS. Nothing there
changes here — this module only stores and re-reads instances of it.
That split matters: `AnalystClaim` is a 57-test, already-shipped
"gating artifact" (its own docstring's words), and reopening it to add
storage concerns would risk the exact thing its docstring warns against
— a module that once described itself accurately drifting under scope
creep.

WHY NOT src.history / src.retention / a fourth invented shape
───────────────────────────────────────────────────────────────
Three existing append-only stores were surveyed before writing this one:

* ``src.history.store`` — its ``observations`` table hard-requires
  ``value is not None or rank is not None`` (see its own
  ``validate_observation``). A pure stance/text claim has neither. Wrong
  shape, not merely a different lane.
* ``src.retention`` — states its own governing rule at
  ``src/retention/__init__.py``: *"nothing here may be read by a
  decision path"*, full stop, no read exception. That is STRICTER than
  this ledger needs: future analyst-facing features (Manager Scout,
  Universal Player Profile, Ask Brisket) must be able to read claims —
  they must simply never reach canonical VALUATION. Retention's own rule
  would forbid a legitimate future consumer this ledger is explicitly
  built to allow.
* ``src.acquisition`` — is the right precedent, and its own
  ``__init__.py`` explains why in exactly this shape: it justified being
  a FOURTH store (not a repurposed ``history`` or ``retention``) because
  it needed to be read by a decision path while recording a different
  quantity than either. This module follows its structured-columns /
  natural-identity-key / content-hash / three-way-write-outcome idiom
  directly — see ``write_claims`` and its docstring, which mirrors
  ``AcquisitionEvent.content_hash()`` and ``write_events()`` line for
  line in spirit.

THE CONFIDENCE / PARSER-VERSION SPLIT
────────────────────────────────────────
The owner spec (``OWNER_PRODUCT_BACKLOG_SPEC.md`` §"ANALYST
INTELLIGENCE") requires preserving "extraction confidence" and this
module's own governing brief requires "parser version" — neither exists
on ``AnalystClaim``. Rather than adding them there, they live on
:class:`LedgerEntry`, the INGESTION ENVELOPE around a claim: how
confidently and by what process WE captured the words is a fact about
our extraction pipeline, not about what the analyst said. This keeps
``AnalystClaim`` — "what a take IS" — untouched, and keeps claim vs.
interpretation cleanly separated at the type level, not just by
convention.

IDENTITY VS. CONTENT — WHERE THE LINE IS DRAWN, AND WHY
──────────────────────────────────────────────────────────
``claim_identity_key()`` covers only the real-world coordinates of ONE
UTTERANCE: which analyst, in which content item, on which platform,
about which asset, at what moment (``said_at``). It deliberately
EXCLUDES ``stance`` — because if two ingestion runs over the SAME
utterance disagree about what stance it expresses (a parser regression,
or a genuine re-read), that is exactly the case that must surface as a
CONFLICT for a human to resolve, not silently become two rows for one
utterance or silently overwrite one reading with another.
``claim_content_hash()`` covers everything else: the classification
(stance, source_label, take_type), the qualifying context (game_type,
asset_side, conditions, quote, thesis_id, discovered_at, supersedes,
notes, tags). Two ingestion runs producing byte-identical content hash
a claim as ``unchanged``; producing DIFFERENT content for the same
utterance is a ``conflict``, reported and never silently applied — same
rule ``AcquisitionEvent`` already established for transaction facts,
applied here to claim facts.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

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

__all__ = [
    "DB_PATH",
    "ExtractionConfidence",
    "LedgerEntry",
    "claim_content_hash",
    "claim_identity_key",
    "connect",
    "write_claims",
    "claims_for_asset",
    "all_claims",
]


class ExtractionConfidence(str, Enum):
    """How confident the EXTRACTION PROCESS is that it captured this claim
    correctly — never a property of the analyst's conviction (that is
    ``Stance``/``ConvictionClass`` in ``src.analyst.stance``).

    ``UNKNOWN`` is the default and is NOT a numeric midpoint. An
    extractor that has not published a confidence signal must say so
    explicitly rather than defaulting to a specific level — the same
    MISSING-IS-NEVER-ZERO rule this codebase applies to every other
    unmeasured quantity (see e.g. ``src.api.confidence``'s tri-state
    freshness, ``src.signals``' family-confidence handling).
    """

    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True)
class LedgerEntry:
    """The ingestion envelope around one :class:`AnalystClaim`.

    ``recorded_at`` is stamped by the STORE on write and is never taken
    from a caller-supplied value — it is the ledger's own insertion
    instant, which is what :mod:`src.analyst.query` falls back to as the
    discovery boundary when a claim's own ``discovered_at`` is unset
    (see that module's docstring for why the fallback must always
    resolve to a real timestamp).
    """

    claim: AnalystClaim
    extraction_confidence: ExtractionConfidence = ExtractionConfidence.UNKNOWN
    parser_version: str = ""
    recorded_at: datetime | None = None
    last_seen_at: datetime | None = None


DB_PATH: Path = Path(__file__).resolve().parents[2] / "data" / "analyst_ledger.sqlite"

SCHEMA_VERSION = 1

_SETUP_LOCK = threading.Lock()
_SETUP_DONE: dict[str, bool] = {}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS analyst_claims (
    -- Identity: one specific utterance about one specific asset.
    -- Deliberately EXCLUDES stance/take_type -- see module docstring.
    identity_key   TEXT PRIMARY KEY,
    content_hash   TEXT NOT NULL,

    analyst_id     TEXT NOT NULL,
    content_id     TEXT NOT NULL,
    platform       TEXT NOT NULL,
    show_id        TEXT NOT NULL DEFAULT '',
    url            TEXT NOT NULL DEFAULT '',

    asset_key      TEXT NOT NULL,
    said_at        TEXT NOT NULL,   -- ISO8601 UTC; part of identity

    -- Content -- the classification and qualifying context.
    stance         TEXT NOT NULL,
    source_label   TEXT NOT NULL,
    take_type      TEXT NOT NULL,
    provenance     TEXT NOT NULL,
    game_type      TEXT NOT NULL,
    asset_side     TEXT NOT NULL,
    conditions_json TEXT NOT NULL DEFAULT '[]',
    quote          TEXT NOT NULL DEFAULT '',
    thesis_id      TEXT NOT NULL DEFAULT '',
    thesis_key     TEXT NOT NULL,
    discovered_at  TEXT,            -- ISO8601 UTC, nullable -- see query.py
    supersedes     TEXT NOT NULL DEFAULT '',
    notes          TEXT NOT NULL DEFAULT '',
    tags_json      TEXT NOT NULL DEFAULT '[]',

    -- Ingestion envelope -- about OUR extraction, not the analyst.
    extraction_confidence TEXT NOT NULL DEFAULT 'UNKNOWN',
    parser_version         TEXT NOT NULL DEFAULT '',

    recorded_at    TEXT NOT NULL,   -- stamped by the store, never the caller
    last_seen_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_claims_asset
    ON analyst_claims(asset_key, said_at);
CREATE INDEX IF NOT EXISTS idx_claims_thesis
    ON analyst_claims(thesis_key);
CREATE INDEX IF NOT EXISTS idx_claims_analyst
    ON analyst_claims(analyst_id, asset_key);
"""

_COLUMNS: tuple[str, ...] = (
    "identity_key",
    "content_hash",
    "analyst_id",
    "content_id",
    "platform",
    "show_id",
    "url",
    "asset_key",
    "said_at",
    "stance",
    "source_label",
    "take_type",
    "provenance",
    "game_type",
    "asset_side",
    "conditions_json",
    "quote",
    "thesis_id",
    "thesis_key",
    "discovered_at",
    "supersedes",
    "notes",
    "tags_json",
    "extraction_confidence",
    "parser_version",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _ensure_schema(path: Path) -> None:
    key = str(path)
    if _SETUP_DONE.get(key):
        return
    with _SETUP_LOCK:
        if _SETUP_DONE.get(key):
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=5.0)
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
    target = path or DB_PATH
    _ensure_schema(target)
    return sqlite3.connect(str(target), timeout=5.0)


def _reset_setup_cache_for_tests() -> None:
    """Forget which paths have been initialised. Tests only."""
    with _SETUP_LOCK:
        _SETUP_DONE.clear()


def claim_identity_key(claim: AnalystClaim) -> str:
    """Identity of ONE UTTERANCE: who, in what content, about what asset,
    when. Excludes stance/take_type on purpose -- see module docstring."""
    raw = "|".join(
        [
            claim.source.analyst_id,
            claim.source.content_id,
            claim.source.platform,
            claim.asset_key,
            claim.said_at.isoformat(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def claim_content_hash(claim: AnalystClaim) -> str:
    """Hash of every field OTHER than identity -- mirrors
    ``AcquisitionEvent.content_hash()``'s "hash the facts, not the
    identity" split. Re-ingesting an unchanged claim is a no-op;
    re-ingesting the same utterance with DIFFERENT facts is a conflict,
    reported and never silently applied."""
    payload = {
        "show_id": claim.source.show_id,
        "url": claim.source.url,
        "stance": claim.stance.value,
        "source_label": claim.source_label.value,
        "take_type": claim.take_type.value,
        "provenance": claim.provenance.value,
        "game_type": claim.game_type.value,
        "asset_side": claim.asset_side.value,
        "conditions": [[c.text, c.kind] for c in claim.conditions],
        "quote": claim.quote,
        "thesis_id": claim.thesis_id,
        "discovered_at": _iso(claim.discovered_at),
        "supersedes": claim.supersedes,
        "notes": claim.notes,
        "tags": sorted(claim.tags),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _row_values(entry: LedgerEntry, identity: str, digest: str) -> tuple[Any, ...]:
    c = entry.claim
    return (
        identity,
        digest,
        c.source.analyst_id,
        c.source.content_id,
        c.source.platform,
        c.source.show_id,
        c.source.url,
        c.asset_key,
        c.said_at.isoformat(),
        c.stance.value,
        c.source_label.value,
        c.take_type.value,
        c.provenance.value,
        c.game_type.value,
        c.asset_side.value,
        json.dumps([{"text": cond.text, "kind": cond.kind} for cond in c.conditions]),
        c.quote,
        c.thesis_id,
        c.thesis_key,
        _iso(c.discovered_at),
        c.supersedes,
        c.notes,
        json.dumps(list(c.tags)),
        entry.extraction_confidence.value,
        entry.parser_version,
    )


def write_claims(entries: Iterable[LedgerEntry], *, path: Path | None = None) -> dict[str, Any]:
    """INSERT-only write. Returns a report, never raises on data.

    Same identity + same content -> ``unchanged`` (bumps ``last_seen_at``
    and REFRESHES ``extraction_confidence``/``parser_version`` -- a later,
    possibly-improved parser run may legitimately update how confident we
    are in an unchanged reading, without touching the claim's own facts).

    Same identity + different content -> appended to ``conflicts``,
    NEVER applied. Resolving one is a deliberate act (an explicit
    ``supersedes`` claim, or a correction to the extractor), not a side
    effect of re-ingestion.
    """
    rows = list(entries)
    if not rows:
        return {"inserted": 0, "unchanged": 0, "conflicts": [], "offered": 0}

    now = _utc_now()
    now_iso = now.isoformat()
    conn = connect(path)
    inserted = 0
    unchanged = 0
    conflicts: list[dict[str, Any]] = []
    try:
        for entry in rows:
            identity = claim_identity_key(entry.claim)
            digest = claim_content_hash(entry.claim)
            existing = conn.execute(
                "SELECT content_hash FROM analyst_claims WHERE identity_key = ?",
                (identity,),
            ).fetchone()
            if existing is not None:
                if existing[0] == digest:
                    conn.execute(
                        "UPDATE analyst_claims SET last_seen_at = ?, "
                        "extraction_confidence = ?, parser_version = ? "
                        "WHERE identity_key = ?",
                        (
                            now_iso,
                            entry.extraction_confidence.value,
                            entry.parser_version,
                            identity,
                        ),
                    )
                    unchanged += 1
                else:
                    conflicts.append(
                        {
                            "identityKey": identity,
                            "analystId": entry.claim.source.analyst_id,
                            "assetKey": entry.claim.asset_key,
                            "saidAt": entry.claim.said_at.isoformat(),
                            "storedHash": existing[0],
                            "offeredHash": digest,
                        }
                    )
                continue

            conn.execute(
                f"INSERT INTO analyst_claims ({', '.join(_COLUMNS)}, "
                f"recorded_at, last_seen_at) "
                f"VALUES ({', '.join('?' * len(_COLUMNS))}, ?, ?)",
                _row_values(entry, identity, digest) + (now_iso, now_iso),
            )
            inserted += 1
        conn.commit()
    finally:
        conn.close()

    return {
        "inserted": inserted,
        "unchanged": unchanged,
        "conflicts": conflicts,
        "offered": len(rows),
    }


def _entry_from_row(row: sqlite3.Row) -> LedgerEntry:
    conditions = tuple(
        Condition(text=c["text"], kind=c["kind"]) for c in json.loads(row["conditions_json"])
    )
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
        conditions=conditions,
        quote=row["quote"],
        thesis_id=row["thesis_id"],
        discovered_at=(
            datetime.fromisoformat(row["discovered_at"]) if row["discovered_at"] else None
        ),
        supersedes=row["supersedes"],
        notes=row["notes"],
        tags=tuple(json.loads(row["tags_json"])),
    )
    return LedgerEntry(
        claim=claim,
        extraction_confidence=ExtractionConfidence(row["extraction_confidence"]),
        parser_version=row["parser_version"],
        recorded_at=datetime.fromisoformat(row["recorded_at"]),
        last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
    )


def claims_for_asset(asset_key: str, *, path: Path | None = None) -> list[LedgerEntry]:
    """Every stored claim about one asset, oldest ``said_at`` first."""
    conn = connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM analyst_claims WHERE asset_key = ? ORDER BY said_at ASC",
            (asset_key,),
        ).fetchall()
    finally:
        conn.close()
    return [_entry_from_row(r) for r in rows]


def all_claims(*, path: Path | None = None) -> list[LedgerEntry]:
    """Every stored claim. Operator/test surface -- no decision path
    should need the WHOLE ledger at once; a specific query belongs in
    ``src.analyst.query``."""
    conn = connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM analyst_claims ORDER BY said_at ASC").fetchall()
    finally:
        conn.close()
    return [_entry_from_row(r) for r in rows]
