"""Transactional local continuity. State revisions are compare-and-swap, history immutable."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

LAYERS = {"working", "episodic", "semantic", "owner"}
AUTHORITY = {"observation": 0, "verified": 1, "repository": 2, "owner": 3}


class ConflictError(ValueError):
    pass


def encode(value):
    return json.dumps(value, sort_keys=True, allow_nan=False)


class StewardStore:
    def __init__(self, path: str | Path):
        self.connection = sqlite3.connect(path, timeout=10)
        self.connection.row_factory = sqlite3.Row
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            self.connection.close()
            raise ValueError("unsupported Steward schema; restore with the matching runtime")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS state (
                name TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS evidence (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS knowledge (
                id TEXT PRIMARY KEY, layer TEXT NOT NULL, topic TEXT NOT NULL,
                payload TEXT NOT NULL, superseded_by TEXT);
            CREATE TABLE IF NOT EXISTS history (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS evidence_no_update BEFORE UPDATE ON evidence
                BEGIN SELECT RAISE(ABORT, 'evidence is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS evidence_no_delete BEFORE DELETE ON evidence
                BEGIN SELECT RAISE(ABORT, 'evidence is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS history_no_update BEFORE UPDATE ON history
                BEGIN SELECT RAISE(ABORT, 'history is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS history_no_delete BEFORE DELETE ON history
                BEGIN SELECT RAISE(ABORT, 'history is immutable'); END;
            PRAGMA user_version=1;
        """)

    def close(self):
        self.connection.close()

    def read(self, name: str) -> tuple[int, dict | None]:
        row = self.connection.execute(
            "SELECT revision,payload FROM state WHERE name=?", (name,)
        ).fetchone()
        return (row["revision"], json.loads(row["payload"])) if row else (0, None)

    def _write(self, name, payload, expected_revision):
        current, _ = self.read(name)
        if current != expected_revision:
            raise ConflictError(f"{name}: expected revision {expected_revision}, found {current}")
        self.connection.execute(
            "INSERT INTO state VALUES (?,?,?) ON CONFLICT(name) DO UPDATE SET revision=excluded.revision,payload=excluded.payload",
            (name, current + 1, encode(payload)),
        )
        self.connection.execute(
            "INSERT INTO history(payload) VALUES (?)",
            (
                encode(
                    {
                        "name": name,
                        "revision": current + 1,
                        "payload": payload,
                        "at": datetime.now(timezone.utc).isoformat(),
                    }
                ),
            ),
        )
        return current + 1

    def write(self, name: str, payload: dict, *, expected_revision: int) -> int:
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            return self._write(name, payload, expected_revision)

    def append_evidence(self, evidence_id: str, payload: dict):
        required = {"source", "at", "repo_head", "content", "complete"}
        if not required <= payload.keys() or not payload["source"] or not payload["repo_head"]:
            raise ValueError(
                "raw evidence requires source, time, revision, content and excerpt coverage"
            )
        with self.connection:
            self.connection.execute(
                "INSERT INTO evidence VALUES (?,?)", (evidence_id, encode(payload))
            )

    def _remember(self, record: dict, *, expected_revision: int) -> int:
        required = {
            "id",
            "layer",
            "topic",
            "summary",
            "authority",
            "evidence_ids",
            "repo_head",
            "at",
        }
        if (
            not required <= record.keys()
            or record["layer"] not in LAYERS
            or record["authority"] not in AUTHORITY
        ):
            raise ValueError("invalid knowledge provenance")
        if not record["evidence_ids"] or not record["summary"]:
            raise ValueError("knowledge requires raw evidence and a summary")
        for evidence_id in record["evidence_ids"]:
            if not self.connection.execute(
                "SELECT 1 FROM evidence WHERE id=?", (evidence_id,)
            ).fetchone():
                raise ValueError(f"missing raw evidence: {evidence_id}")
        old_id = record.get("supersedes")
        if old_id:
            old = self.connection.execute(
                "SELECT payload,superseded_by FROM knowledge WHERE id=?", (old_id,)
            ).fetchone()
            if not old or old["superseded_by"]:
                raise ConflictError("superseded record is missing or already superseded")
            old_record = json.loads(old["payload"])
            if AUTHORITY[record["authority"]] < AUTHORITY[old_record["authority"]]:
                raise ValueError("lower authority cannot supersede higher authority")
            if (record["layer"], record["topic"]) != (old_record["layer"], old_record["topic"]):
                raise ValueError("supersession must address the same layer and topic")
            self.connection.execute(
                "UPDATE knowledge SET superseded_by=? WHERE id=?", (record["id"], old_id)
            )
        self.connection.execute(
            "INSERT INTO knowledge VALUES (?,?,?,?,NULL)",
            (record["id"], record["layer"], record["topic"], encode(record)),
        )
        return self._write("knowledge_revision", {"last_record": record["id"]}, expected_revision)

    def remember(self, record: dict, *, expected_revision: int) -> int:
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            return self._remember(record, expected_revision=expected_revision)

    def save_report(
        self,
        *,
        evidence_id: str,
        raw: dict,
        checkpoint: dict,
        knowledge: dict,
        expected_campaign: int,
        expected_knowledge: int,
    ):
        """Commit one continuity generation or nothing, including both CAS checks."""
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.execute("INSERT INTO evidence VALUES (?,?)", (evidence_id, encode(raw)))
            self._write("campaign", checkpoint, expected_campaign)
            self._remember(knowledge, expected_revision=expected_knowledge)

    def retrieve(self, topic: str, *, limit_chars: int = 6000) -> dict:
        if limit_chars < 1:
            raise ValueError("positive context budget required")
        with self.connection:
            self.connection.execute("BEGIN")
            revision, _ = self.read("knowledge_revision")
            rows = self.connection.execute(
                "SELECT payload FROM knowledge WHERE topic=? AND superseded_by IS NULL ORDER BY id",
                (topic,),
            ).fetchall()
        selected, used = [], 0
        for row in rows:
            record = json.loads(row["payload"])
            size = len(encode(record))
            if used + size > limit_chars:
                continue
            selected.append(record)
            used += size
        return {
            "knowledge_revision": revision,
            "retrieval_revision": revision,
            "records": selected,
            "omitted": len(rows) - len(selected),
            "index": "transactional SQLite query; no asynchronous index",
        }

    def raw_evidence(self, evidence_id):
        row = self.connection.execute(
            "SELECT payload FROM evidence WHERE id=?", (evidence_id,)
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def backup(self, destination: str | Path):
        destination = Path(destination)
        if destination.exists():
            raise FileExistsError(destination)
        with sqlite3.connect(destination) as target:
            self.connection.backup(target)
