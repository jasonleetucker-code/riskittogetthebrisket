"""Append-only, idempotent, conflict-surfacing learning-receipt store (AL-0, A2).

``data/learning/receipts.sqlite`` holds one row per receipt. The write path is
``src/history/store.py``'s discipline applied to receipts:

* an identical re-write (same ``receiptId``, same ``contentHash``) is a silent
  no-op — every ingest is idempotent;
* a conflicting re-write (same ``receiptId``, different content) is NEVER
  applied: it is returned as a ``contentConflicts`` entry. A learning record that
  can be silently rewritten is not evidence. The module reads the existing row
  BEFORE inserting (inside one ``BEGIN IMMEDIATE`` transaction), so both cases
  are classified rather than inferred from a swallowed insert;
* UPDATE and DELETE are refused by the database itself (triggers), so no future
  caller can quietly mutate history even by going around this module. That
  includes ``INSERT OR REPLACE``: SQLite's REPLACE deletes the old row without
  firing delete triggers (unless ``recursive_triggers`` is on), so a BEFORE
  INSERT trigger ABORTS any insert whose key already exists — loudly, so a raw
  insert that bypasses this module fails instead of vanishing. The ``meta`` and
  ``corrections`` tables get the same treatment.

Corrections (plan §19.1: "stat corrections are revisions, not overwrites"). A
receipt's identity is ``(kind, producer, nativeId)`` plus its ``revision``, so a
corrected outcome is appended as a NEW receipt carrying a new revision and then
linked to the original with :func:`record_correction` — the discipline of
``src.history.store.record_correction``: a reason is mandatory, the original is
retained and readable, a receipt cannot supersede itself, a superseded receipt
cannot supersede (so no cycle can remove evidence), and a receipt is superseded
at most once (corrections form a chain, never a fork). Every one of those rules
is ALSO a database trigger, so a raw insert cannot record a correction the module
would refuse. That includes "both receipts exist": the ``REFERENCES`` clauses
are enforced only on connections that turn ``PRAGMA foreign_keys`` on, which
:func:`connect` does and a raw ``sqlite3.connect`` (SQLite's default) does not,
so existence is a trigger too rather than a property of whoever opened the file.
A dangling link would otherwise make ``live_only`` hide a stored receipt behind
one that does not exist.
``iter_receipts(live_only=True)`` answers with the head of each correction chain.

What the store refuses outright:

* a ``PROMOTION_RECORD`` receipt (A5) — validated again here, not trusted from
  the builder;
* a path under ``data/ros/``: the scheduled refresh force-adds that tree, which
  would publish private decision intelligence (plan §23);
* any other path inside the repository that is not under ``data/learning/`` —
  pointed at another SQLite file this module would create its tables and
  triggers inside somebody else's database (``data/temporal_ledger.sqlite``,
  ``config/…``). This is checked FIRST, whatever directory the checkout lives in;
* any path outside the repository, unless a caller has explicitly opted that
  root in through :data:`EXTRA_ALLOWED_ROOTS`. Production never does; the test
  suite does, for pytest's temporary directories. There is no implicit
  system-temp allowance: on a production host that would admit anything in
  ``/tmp``, including another application's SQLite file.

Receipts point into native stores; the store copies no observation. It holds
only the receipt JSON. ``recorded_at`` is write provenance, never part of the
content hash, so re-deriving receipts from the same pinned inputs is
byte-identical (A10).

Backup: ``deploy/backup/riskit-state-backup.sh`` (online backup +
``PRAGMA integrity_check``), registered in ``docs/retention/RETENTION_REGISTER.md``.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from src.model_registry.learning_receipt import (
    KIND_PROMOTION_RECORD,
    LearningReceipt,
    PromotionNotPermitted,
    ReceiptError,
    canonical_json,
    validate_receipt,
)

REPO = Path(__file__).resolve().parents[2]
DEFAULT_STORE_PATH: Path = REPO / "data" / "learning" / "receipts.sqlite"
#: 2: replace-attempts ABORT (v1 silently ignored them); correction triggers
#: refuse self-, superseded- and cyclic supersession; foreign keys enforced.
#: 3: a correction naming a receipt that is not stored ABORTs on ANY connection
#: (a trigger; ``REFERENCES`` binds only connections with foreign_keys on).
STORE_SCHEMA_VERSION = 3

_FORBIDDEN_TREE = REPO / "data" / "ros"
#: The only production home of the store.
STORE_TREE = REPO / "data" / "learning"

#: Roots OUTSIDE the repository the store may additionally live under. Empty in
#: production, and no production caller sets it. Tests opt in explicitly
#: (``tests/model_registry/conftest.py`` monkeypatches pytest's base temp dir in).
#: A root inside the repository is never honoured: the in-repo rule runs first.
EXTRA_ALLOWED_ROOTS: tuple[Path, ...] = ()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TRIGGER IF NOT EXISTS meta_no_update BEFORE UPDATE ON meta
BEGIN SELECT RAISE(ABORT, 'learning-store meta is insert-only'); END;
CREATE TRIGGER IF NOT EXISTS meta_no_delete BEFORE DELETE ON meta
BEGIN SELECT RAISE(ABORT, 'learning-store meta is insert-only'); END;
CREATE TRIGGER IF NOT EXISTS meta_no_replace BEFORE INSERT ON meta
WHEN EXISTS (SELECT 1 FROM meta WHERE key = NEW.key)
BEGIN SELECT RAISE(ABORT, 'learning-store meta is insert-only'); END;
CREATE TABLE IF NOT EXISTS receipts (
    receipt_id       TEXT PRIMARY KEY,
    kind             TEXT NOT NULL,
    schema_version   INTEGER NOT NULL,
    producer         TEXT NOT NULL,
    model_family     TEXT NOT NULL,
    model_version_id TEXT,
    prediction_id    TEXT,
    cutoff           TEXT,
    content_hash     TEXT NOT NULL,
    receipt_json     TEXT NOT NULL,
    recorded_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_receipts_kind ON receipts(kind, model_family);
CREATE TRIGGER IF NOT EXISTS receipts_no_update BEFORE UPDATE ON receipts
BEGIN SELECT RAISE(ABORT, 'learning receipts are append-only'); END;
CREATE TRIGGER IF NOT EXISTS receipts_no_delete BEFORE DELETE ON receipts
BEGIN SELECT RAISE(ABORT, 'learning receipts are append-only'); END;
CREATE TRIGGER IF NOT EXISTS receipts_no_promotion BEFORE INSERT ON receipts
WHEN NEW.kind = 'PROMOTION_RECORD'
BEGIN SELECT RAISE(ABORT, 'AL-0 writes no PROMOTION RECORD'); END;
-- An existing receipt_id is never replaced (INSERT OR REPLACE would delete it
-- without firing receipts_no_delete). ABORT, not IGNORE: a raw insert that goes
-- around the module must fail loudly, never be dropped silently. The module
-- checks for the row first, so it never reaches this trigger.
CREATE TRIGGER IF NOT EXISTS receipts_no_replace BEFORE INSERT ON receipts
WHEN EXISTS (SELECT 1 FROM receipts WHERE receipt_id = NEW.receipt_id)
BEGIN SELECT RAISE(ABORT, 'learning receipts are append-only: a stored receipt is never replaced'); END;
CREATE TABLE IF NOT EXISTS corrections (
    superseded_id  TEXT PRIMARY KEY REFERENCES receipts(receipt_id),
    superseding_id TEXT NOT NULL REFERENCES receipts(receipt_id),
    reason         TEXT NOT NULL,
    recorded_at    TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS corrections_no_update BEFORE UPDATE ON corrections
BEGIN SELECT RAISE(ABORT, 'receipt corrections are append-only'); END;
CREATE TRIGGER IF NOT EXISTS corrections_no_delete BEFORE DELETE ON corrections
BEGIN SELECT RAISE(ABORT, 'receipt corrections are append-only'); END;
CREATE TRIGGER IF NOT EXISTS corrections_no_replace BEFORE INSERT ON corrections
WHEN EXISTS (SELECT 1 FROM corrections WHERE superseded_id = NEW.superseded_id)
BEGIN SELECT RAISE(ABORT, 'a receipt is corrected at most once; correct the newest revision'); END;
-- Both ends must be stored receipts. REFERENCES alone does not hold on a raw
-- connection (PRAGMA foreign_keys is off by default), and a dangling link lets
-- iter_receipts(live_only=True) hide a stored receipt behind a ghost.
CREATE TRIGGER IF NOT EXISTS corrections_receipts_exist BEFORE INSERT ON corrections
WHEN NOT EXISTS (SELECT 1 FROM receipts WHERE receipt_id = NEW.superseded_id)
  OR NOT EXISTS (SELECT 1 FROM receipts WHERE receipt_id = NEW.superseding_id)
BEGIN SELECT RAISE(ABORT, 'a correction must link two stored receipts'); END;
-- A superseding receipt must be a chain HEAD (not itself superseded). That alone
-- makes a cycle impossible: a head has no outgoing supersession, so the receipt
-- being superseded can never be reached from it. The direct X->Y / Y->X pair and
-- self-supersession are spelled out as well so the refusal reads plainly.
CREATE TRIGGER IF NOT EXISTS corrections_no_cycle BEFORE INSERT ON corrections
WHEN NEW.superseded_id = NEW.superseding_id
  OR EXISTS (SELECT 1 FROM corrections WHERE superseded_id = NEW.superseding_id)
  OR EXISTS (
      SELECT 1 FROM corrections
      WHERE superseded_id = NEW.superseding_id AND superseding_id = NEW.superseded_id
  )
BEGIN SELECT RAISE(ABORT, 'a superseded receipt cannot supersede; corrections never form a cycle'); END;
"""


class StorePathError(ReceiptError):
    """The store may not live where it would be published, or in a foreign database."""


class CorrectionError(ReceiptError):
    """A correction that must not be recorded (fail closed)."""


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(Path(root).resolve())
    except ValueError:
        return False
    return True


def _check_path(path: Path) -> Path:
    """Where the store may live. The in-repository rule runs before anything else,
    so a checkout that itself sits under a temp directory gains nothing from it."""
    resolved = Path(path).resolve()
    if _under(resolved, _FORBIDDEN_TREE):
        raise StorePathError(
            f"{path}: data/ros/ is force-added by the scheduled refresh; receipts are private"
        )
    if _under(resolved, REPO):
        if _under(resolved, STORE_TREE):
            return resolved
        raise StorePathError(
            f"{path}: inside the repository the learning-receipt store lives only under "
            "data/learning/; it will not create its tables inside another database"
        )
    if any(_under(resolved, root) for root in EXTRA_ALLOWED_ROOTS):
        return resolved
    raise StorePathError(
        f"{path}: outside the repository; the learning-receipt store lives under "
        "data/learning/ (a test must opt its temp root in through EXTRA_ALLOWED_ROOTS)"
    )


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = _check_path(path or DEFAULT_STORE_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        # Check an existing store's version BEFORE touching its schema, so a
        # store this code does not own is refused without new triggers in it.
        has_meta = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'"
        ).fetchone()
        if has_meta:
            row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
            if row is not None and row["value"] != str(STORE_SCHEMA_VERSION):
                raise ReceiptError(
                    f"{target}: store schema_version {row['value']!r} is not "
                    f"{STORE_SCHEMA_VERSION}; an explicit migration is required"
                )
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.executescript(_SCHEMA)
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(STORE_SCHEMA_VERSION),),
            )
        conn.commit()
    except BaseException:
        conn.close()
        raise
    return conn


def append_receipts(
    receipts: Iterable[LearningReceipt],
    *,
    path: Path | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Append receipts. Idempotent; conflicts surfaced, never applied.

    Returns ``{written, duplicates, contentConflicts, rejected}``; ``rejected``
    carries receipts that failed validation, with the reason."""
    stamp = recorded_at or datetime.now(timezone.utc).isoformat()
    written = 0
    duplicates = 0
    conflicts: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    conn = connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for receipt in receipts:
            try:
                if receipt.kind == KIND_PROMOTION_RECORD:
                    raise PromotionNotPermitted("AL-0 writes no PROMOTION RECORD")
                validate_receipt(receipt)
                body = receipt.to_dict()
                text = canonical_json(body)
            except ReceiptError as exc:
                rejected.append(
                    {"kind": receipt.kind, "nativeId": receipt.native_id, "reason": str(exc)}
                )
                continue
            content = receipt.content_hash()
            row = conn.execute(
                "SELECT content_hash FROM receipts WHERE receipt_id = ?", (receipt.receipt_id,)
            ).fetchone()
            if row is not None:
                if row["content_hash"] == content:
                    duplicates += 1
                else:
                    conflicts.append(
                        {
                            "receiptId": receipt.receipt_id,
                            "kind": receipt.kind,
                            "storedHash": row["content_hash"],
                            "incomingHash": content,
                        }
                    )
                continue
            conn.execute(
                "INSERT INTO receipts (receipt_id, kind, schema_version, producer, "
                "model_family, model_version_id, prediction_id, cutoff, content_hash, "
                "receipt_json, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    receipt.receipt_id,
                    receipt.kind,
                    body["schemaVersion"],
                    receipt.producer,
                    receipt.model_family,
                    receipt.model_version_id,
                    receipt.prediction_id,
                    body["cutoff"],
                    content,
                    text,
                    stamp,
                ),
            )
            written += 1
        conn.commit()
    finally:
        conn.close()
    return {
        "written": written,
        "duplicates": duplicates,
        "contentConflicts": conflicts,
        "rejected": rejected,
    }


def record_correction(
    superseded_id: str,
    superseding_id: str,
    reason: str,
    *,
    path: Path | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Explicitly supersede one stored receipt with a corrected revision of it.

    Mirrors ``src.history.store.record_correction``. Both receipts must already
    be stored; neither is changed. The superseding receipt must describe the
    SAME thing (kind, producer, nativeId) under a different, non-empty
    ``revision`` — a correction is a revision, never a different receipt
    relabelled. Re-recording an identical correction is a no-op
    (``{"recorded": False}``); any other second correction of the same receipt
    is refused, so corrections form a chain rather than a fork."""
    if not str(reason or "").strip():
        raise CorrectionError("a correction requires a reason")
    if superseded_id == superseding_id:
        raise CorrectionError("a receipt cannot supersede itself")
    conn = connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        docs: dict[str, dict[str, Any]] = {}
        for rid in (superseded_id, superseding_id):
            row = conn.execute(
                "SELECT receipt_json FROM receipts WHERE receipt_id = ?", (rid,)
            ).fetchone()
            if row is None:
                raise CorrectionError(f"correction references missing receipt {rid}")
            docs[rid] = json.loads(row["receipt_json"])
        old, new = docs[superseded_id], docs[superseding_id]
        for field in ("kind", "producer", "nativeId"):
            if old.get(field) != new.get(field):
                raise CorrectionError(
                    f"a correction must describe the same receipt: {field} "
                    f"{old.get(field)!r} != {new.get(field)!r}"
                )
        if new.get("revision") is None or new.get("revision") == old.get("revision"):
            raise CorrectionError("the superseding receipt must carry a new, non-empty revision")
        existing = conn.execute(
            "SELECT superseding_id, reason FROM corrections WHERE superseded_id = ?",
            (superseded_id,),
        ).fetchone()
        if existing is not None:
            if (
                existing["superseding_id"] == superseding_id
                and existing["reason"] == reason.strip()
            ):
                return {"recorded": False}
            raise CorrectionError(
                f"{superseded_id} is already superseded by {existing['superseding_id']}; "
                "correct the newest revision instead"
            )
        # A superseded receipt may not supersede: a two-row cycle would remove
        # both from every live view — evidence deletion by another name.
        if conn.execute(
            "SELECT 1 FROM corrections WHERE superseded_id = ?", (superseding_id,)
        ).fetchone():
            raise CorrectionError(f"{superseding_id} is itself superseded and cannot supersede")
        conn.execute(
            "INSERT INTO corrections(superseded_id, superseding_id, reason, recorded_at) "
            "VALUES (?, ?, ?, ?)",
            (
                superseded_id,
                superseding_id,
                reason.strip(),
                recorded_at or datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()  # an uncommitted transaction (refusal paths) rolls back
    return {"recorded": True}


def _chain_head(start: str, edges: dict[str, str]) -> str:
    """Follow recorded corrections (superseded -> superseding) to their end."""
    seen = {start}
    cur = start
    while cur in edges:
        cur = edges[cur]
        if cur in seen:  # unreachable under the triggers; refuse rather than loop
            raise ReceiptError(f"correction cycle through {cur}; the store is corrupt")
        seen.add(cur)
    return cur


def iter_receipts(
    path: Path | None = None, *, kind: str | None = None, live_only: bool = False
) -> Iterator[dict[str, Any]]:
    """Every stored receipt (parsed JSON), in receipt-id order. Read-only.

    ``live_only`` yields the NEWEST REVISION IN EACH CORRECTION CHAIN: every
    stored receipt is followed through its recorded corrections to the end of
    the chain, and each chain end is yielded once. Superseded revisions stay
    stored and are returned without ``live_only``. "Newest" is defined by the
    recorded corrections and by nothing else: a revision appended without a
    correction linking it starts a chain of its own and is yielded beside the
    original — the store never infers an order between revisions that no
    correction relates (``recorded_at`` is write provenance, not evidence)."""
    target = _check_path(path or DEFAULT_STORE_PATH)
    if not target.exists():
        return
    conn = sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        sql = "SELECT receipt_id, receipt_json FROM receipts"
        args: tuple[Any, ...] = ()
        if kind is not None:
            sql += " WHERE kind = ?"
            args = (kind,)
        rows = conn.execute(sql + " ORDER BY receipt_id", args).fetchall()
        if live_only:
            edges = {
                r["superseded_id"]: r["superseding_id"]
                for r in conn.execute("SELECT superseded_id, superseding_id FROM corrections")
            }
            heads = {_chain_head(r["receipt_id"], edges) for r in rows}
            rows = [r for r in rows if r["receipt_id"] in heads]
    finally:
        conn.close()
    for row in rows:
        yield json.loads(row["receipt_json"])
