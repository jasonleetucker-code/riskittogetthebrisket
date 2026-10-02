"""Background jobs for long DFS work (DFS-MOD-17): backtests, portfolios, simulations.

A web request must not run an unbounded computation, and some bounded ones
(a backtest replaying ten portfolios) outlast a proxy timeout.  So:

* ONE worker thread runs jobs in submission order (numpy work; any MILP still
  goes through the pinned solver thread — ADR-DFS-012);
* the queue is bounded (``MAX_QUEUED`` per owner, ``MAX_QUEUED_TOTAL`` overall);
* every job is persisted with its owner, state (``queued`` → ``running`` →
  ``done`` | ``failed``), timestamps, and result or error;
* a job left ``running`` by a previous process is marked ``interrupted`` at
  start-up — never silently "still running";
* job IDs answer only to their owner.

The work itself is a named function (``KINDS``), so a job and the equivalent
synchronous endpoint run identical code.
"""

from __future__ import annotations

import json
import queue
import threading
import traceback
import uuid
from typing import Any, Callable

from src.dfs import store

MAX_QUEUED = 3
MAX_QUEUED_TOTAL = 20

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dfs_jobs (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    kind TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    params TEXT NOT NULL,
    result TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS dfs_jobs_owner ON dfs_jobs(owner, created_at);
"""

KINDS: dict[str, Callable[[str, dict[str, Any]], dict[str, Any]]] = {}
_queue: "queue.Queue[str]" = queue.Queue()
_worker: threading.Thread | None = None
_start_lock = threading.Lock()
_recovered = False


class JobError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _connect():
    import sqlite3

    conn = sqlite3.connect(store._db_path(), timeout=10)
    conn.executescript(_SCHEMA)
    return conn


def register(kind: str):
    def deco(fn):
        KINDS[kind] = fn
        return fn

    return deco


def _recover() -> None:
    """Jobs a previous process left running did not finish: say so."""
    global _recovered
    if _recovered:
        return
    with store._lock, _connect() as conn:
        conn.execute(
            "UPDATE dfs_jobs SET state='interrupted', finished_at=?, error=? WHERE state IN ('running','queued')",
            (store.now_iso(), "The server restarted before this job finished; submit it again."),
        )
    _recovered = True


def _ensure_worker() -> None:
    global _worker
    with _start_lock:
        _recover()
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run_forever, name="dfs-jobs", daemon=True)
            _worker.start()


def submit(owner: str, kind: str, params: dict[str, Any]) -> dict[str, Any]:
    if kind not in KINDS:
        raise JobError("UNKNOWN_JOB_KIND", f"Unknown job kind {kind!r}.")
    _ensure_worker()
    with store._lock, _connect() as conn:
        mine = conn.execute(
            "SELECT COUNT(*) FROM dfs_jobs WHERE owner=? AND state IN ('queued','running')",
            (owner,),
        ).fetchone()[0]
        total = conn.execute(
            "SELECT COUNT(*) FROM dfs_jobs WHERE state IN ('queued','running')"
        ).fetchone()[0]
        if mine >= MAX_QUEUED or total >= MAX_QUEUED_TOTAL:
            raise JobError(
                "QUEUE_FULL", "Too many DFS jobs are waiting; try again when one finishes."
            )
        jid = "job_" + uuid.uuid4().hex[:20]
        conn.execute(
            "INSERT INTO dfs_jobs (id, owner, kind, state, created_at, params) VALUES (?,?,?,?,?,?)",
            (jid, owner, kind, "queued", store.now_iso(), json.dumps(params)),
        )
    _queue.put(jid)
    return get(owner, jid)


def get(owner: str, jid: str) -> dict[str, Any] | None:
    with store._lock, _connect() as conn:
        r = conn.execute(
            "SELECT kind, state, created_at, started_at, finished_at, result, error FROM dfs_jobs WHERE id=? AND owner=?",
            (jid, owner),
        ).fetchone()
    if not r:
        return None
    return {
        "jobId": jid,
        "kind": r[0],
        "state": r[1],
        "createdAt": r[2],
        "startedAt": r[3],
        "finishedAt": r[4],
        "result": json.loads(r[5]) if r[5] else None,
        "error": r[6],
    }


def _set(jid: str, **cols: Any) -> None:
    keys = ", ".join(f"{k}=?" for k in cols)
    with store._lock, _connect() as conn:
        conn.execute(f"UPDATE dfs_jobs SET {keys} WHERE id=?", (*cols.values(), jid))


def run_one(jid: str) -> None:
    with store._lock, _connect() as conn:
        r = conn.execute(
            "SELECT owner, kind, params, state FROM dfs_jobs WHERE id=?", (jid,)
        ).fetchone()
    if not r or r[3] != "queued":
        return
    owner, kind, params, _ = r
    _set(jid, state="running", started_at=store.now_iso())
    try:
        result = KINDS[kind](owner, json.loads(params))
        _set(jid, state="done", finished_at=store.now_iso(), result=json.dumps(result, default=str))
    except Exception as exc:  # noqa: BLE001 - a job's failure is recorded, never raised into the worker
        code = getattr(exc, "code", type(exc).__name__)
        message = getattr(exc, "message", str(exc))
        _set(jid, state="failed", finished_at=store.now_iso(), error=f"{code}: {message}"[:500])
        traceback.print_exc()


def _run_forever() -> None:
    while True:
        jid = _queue.get()
        try:
            run_one(jid)
        finally:
            _queue.task_done()


def wait_idle() -> None:
    """Block until every submitted job has run (tests)."""
    _queue.join()
