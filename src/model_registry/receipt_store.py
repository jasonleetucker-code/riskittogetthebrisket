"""Append-only, idempotent, conflict-surfacing learning-receipt store (AL-0, A2).

``data/learning/receipts.sqlite`` holds one row per receipt. The write path is
``src/history/store.py``'s discipline applied to receipts:

* an identical re-write (same ``receiptId``, same ``contentHash``) is a silent
  no-op — every ingest is idempotent;
* a conflicting re-write (same ``receiptId``, different content) is NEVER
  applied: it is returned as a ``contentConflicts`` entry. A learning record that
  can be silently rewritten is not evidence;
* UPDATE and DELETE are refused by the database itself (triggers), so no future
  caller can quietly mutate history even by going around this module.

What the store refuses outright:

* a ``PROMOTION_RECORD`` receipt (A5) — validated again here, not trusted from
  the builder;
* a path under ``data/ros/``: the scheduled refresh force-adds that tree, which
  would publish private decision intelligence (plan §23). Receipts are private
  and live under gitignored ``data/learning/``.

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
STORE_SCHEMA_VERSION = 1

_FORBIDDEN_TREE = REPO / "data" / "ros"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
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
"""


class StorePathError(ReceiptError):
    """The store may not live where it would be published."""


def _check_path(path: Path) -> Path:
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(_FORBIDDEN_TREE.resolve())
    except ValueError:
        return resolved
    raise StorePathError(
        f"{path}: data/ros/ is force-added by the scheduled refresh; receipts are private"
    )


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = _check_path(path or DEFAULT_STORE_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(STORE_SCHEMA_VERSION),),
    )
    conn.commit()
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
            cur = conn.execute(
                "INSERT OR IGNORE INTO receipts (receipt_id, kind, schema_version, producer, "
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
            if cur.rowcount == 1:
                written += 1
                continue
            row = conn.execute(
                "SELECT content_hash FROM receipts WHERE receipt_id = ?", (receipt.receipt_id,)
            ).fetchone()
            if row is not None and row["content_hash"] == content:
                duplicates += 1
            else:
                conflicts.append(
                    {
                        "receiptId": receipt.receipt_id,
                        "kind": receipt.kind,
                        "storedHash": row["content_hash"] if row else None,
                        "incomingHash": content,
                    }
                )
        conn.commit()
    finally:
        conn.close()
    return {
        "written": written,
        "duplicates": duplicates,
        "contentConflicts": conflicts,
        "rejected": rejected,
    }


def iter_receipts(path: Path | None = None, *, kind: str | None = None) -> Iterator[dict[str, Any]]:
    """Every stored receipt (parsed JSON), in receipt-id order. Read-only."""
    target = _check_path(path or DEFAULT_STORE_PATH)
    if not target.exists():
        return
    conn = sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        sql = "SELECT receipt_json FROM receipts"
        args: tuple[Any, ...] = ()
        if kind is not None:
            sql += " WHERE kind = ?"
            args = (kind,)
        for row in conn.execute(sql + " ORDER BY receipt_id", args):
            yield json.loads(row["receipt_json"])
    finally:
        conn.close()
