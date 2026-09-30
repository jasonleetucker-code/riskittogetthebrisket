"""Private per-owner persistence for DFS slate snapshots and builds.

SQLite under ``data/dfs/`` (gitignored).  Snapshots and builds are IMMUTABLE:
a new import is a new snapshot, a rebuild is a new build.  Every read is
scoped by the authenticated owner — a record's id alone never grants access,
so another user's id answers exactly like an id that does not exist.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dfs_snapshots (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    created_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    ruleset TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS dfs_snapshots_owner ON dfs_snapshots(owner, created_at);
CREATE TABLE IF NOT EXISTS dfs_builds (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS dfs_builds_owner ON dfs_builds(owner, created_at);
CREATE TABLE IF NOT EXISTS dfs_contests (
    id TEXT NOT NULL,
    version INTEGER NOT NULL,
    owner TEXT NOT NULL,
    created_at TEXT NOT NULL,
    body TEXT NOT NULL,
    PRIMARY KEY (id, version)
);
CREATE INDEX IF NOT EXISTS dfs_contests_owner ON dfs_contests(owner, id, version);
"""


def _db_path() -> Path:
    base = os.getenv("DFS_DATA_DIR")
    root = Path(base) if base else REPO / "data" / "dfs"
    root.mkdir(parents=True, exist_ok=True)
    return root / "workspace.sqlite"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=10)
    conn.executescript(_SCHEMA)
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def put_snapshot(
    owner: str, ruleset_key: str, content_hash: str, body: dict[str, Any]
) -> dict[str, Any]:
    sid = "snap_" + uuid.uuid4().hex[:20]
    created = now_iso()
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO dfs_snapshots VALUES (?,?,?,?,?,?)",
            (
                sid,
                owner,
                created,
                content_hash,
                ruleset_key,
                json.dumps(body, separators=(",", ":")),
            ),
        )
    return {"id": sid, "createdAt": created}


def get_snapshot(owner: str, sid: str) -> dict[str, Any] | None:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT id, created_at, content_hash, ruleset, body FROM dfs_snapshots WHERE id=? AND owner=?",
            (sid, owner),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "createdAt": row[1],
        "contentHash": row[2],
        "ruleset": row[3],
        "body": json.loads(row[4]),
    }


def put_build(owner: str, snapshot_id: str, body: dict[str, Any]) -> dict[str, Any]:
    bid = "build_" + uuid.uuid4().hex[:20]
    created = now_iso()
    body = {**body, "buildId": bid, "createdAt": created}
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO dfs_builds VALUES (?,?,?,?,?)",
            (bid, owner, snapshot_id, created, json.dumps(body, separators=(",", ":"))),
        )
    return body


def get_build(owner: str, bid: str) -> dict[str, Any] | None:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT body FROM dfs_builds WHERE id=? AND owner=?", (bid, owner)
        ).fetchone()
    return json.loads(row[0]) if row else None


def list_builds(owner: str, limit: int = 25) -> list[dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT body FROM dfs_builds WHERE owner=? ORDER BY created_at DESC LIMIT ?",
            (owner, limit),
        ).fetchall()
    out = []
    for (body,) in rows:
        b = json.loads(body)
        out.append(
            {
                "buildId": b["buildId"],
                "createdAt": b["createdAt"],
                "ruleset": b.get("ruleset", {}).get("key"),
                "label": b.get("ruleset", {}).get("label"),
                "status": b.get("result", {}).get("status"),
                "built": b.get("result", {}).get("built"),
                "requested": b.get("result", {}).get("requested"),
                "snapshotId": b.get("snapshot", {}).get("id"),
            }
        )
    return out


# ── contests: mutable workspace records, kept as immutable versions ──────


def put_contest(owner: str, contest_id: str | None, body: dict[str, Any]) -> dict[str, Any] | None:
    """Save a contest.  With ``contest_id`` it appends a NEW version (never an
    overwrite); an id this owner does not hold answers ``None``."""
    created = now_iso()
    with _lock, _connect() as conn:
        if contest_id is None:
            contest_id = "contest_" + uuid.uuid4().hex[:20]
            version = 1
        else:
            row = conn.execute(
                "SELECT MAX(version) FROM dfs_contests WHERE id=? AND owner=?", (contest_id, owner)
            ).fetchone()
            if row is None or row[0] is None:
                return None
            version = int(row[0]) + 1
        record = {**body, "contestId": contest_id, "version": version, "savedAt": created}
        conn.execute(
            "INSERT INTO dfs_contests VALUES (?,?,?,?,?)",
            (contest_id, version, owner, created, json.dumps(record, separators=(",", ":"))),
        )
    return record


def get_contest(owner: str, contest_id: str, version: int | None = None) -> dict[str, Any] | None:
    with _lock, _connect() as conn:
        if version is None:
            row = conn.execute(
                "SELECT body FROM dfs_contests WHERE id=? AND owner=? ORDER BY version DESC LIMIT 1",
                (contest_id, owner),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT body FROM dfs_contests WHERE id=? AND owner=? AND version=?",
                (contest_id, owner, version),
            ).fetchone()
    return json.loads(row[0]) if row else None


def list_contests(owner: str, limit: int = 50) -> list[dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT c.body FROM dfs_contests c JOIN ("
            " SELECT id, MAX(version) AS v FROM dfs_contests WHERE owner=? GROUP BY id"
            ") latest ON c.id = latest.id AND c.version = latest.v "
            "WHERE c.owner=? ORDER BY c.created_at DESC LIMIT ?",
            (owner, owner, limit),
        ).fetchall()
    out = []
    for (body,) in rows:
        b = json.loads(body)
        out.append(
            {
                "contestId": b["contestId"],
                "version": b["version"],
                "savedAt": b["savedAt"],
                "name": b["contest"]["name"],
                "platform": b["contest"]["platform"],
                "sport": b["contest"]["sport"],
                "format": b["contest"]["format"],
                "ok": b["report"]["ok"],
            }
        )
    return out
