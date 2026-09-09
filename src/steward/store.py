"""SQLite evidence store.  It records proposals; it cannot perform promotions."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from typing import Any

class StewardStore:
    def __init__(self, path: str | Path):
        self.connection = sqlite3.connect(path)
        self.connection.execute("""CREATE TABLE IF NOT EXISTS steward_receipts (
            run_id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL
        )""")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS steward_proposals (
            proposal_id TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL CHECK(status = 'PROPOSED_CHALLENGER')
        )""")
    def append_receipt(self, run_id: str, payload: dict[str, Any], created_at: str) -> None:
        self.connection.execute("INSERT INTO steward_receipts VALUES (?, ?, ?)", (run_id, json.dumps(payload, sort_keys=True), created_at))
        self.connection.commit()
    def propose(self, proposal_id: str, payload: dict[str, Any]) -> None:
        self.connection.execute("INSERT INTO steward_proposals VALUES (?, ?, 'PROPOSED_CHALLENGER')", (proposal_id, json.dumps(payload, sort_keys=True)))
        self.connection.commit()
    def proposals(self) -> list[dict[str, Any]]:
        return [{"proposal_id": row[0], **json.loads(row[1]), "status": row[2]} for row in self.connection.execute("SELECT proposal_id, payload, status FROM steward_proposals")]
