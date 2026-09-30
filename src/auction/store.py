"""Authoritative persistent store for the rookie auction room.

SQLite, one file (``data/auction/auction.sqlite`` by default, outside the
deploy-replaced code — ``data/`` is gitignored and survives ``git reset
--hard``).  Durability posture:

* ``journal_mode=WAL`` + ``synchronous=FULL`` — WAL alone is not durable
  under ``NORMAL``; ``FULL`` fsyncs the WAL on every commit, so an
  acknowledged action survives process crash AND power loss of this host.
* every accepted command is ONE ``BEGIN IMMEDIATE`` transaction that writes
  the new room state, the command log row, its events, any awards, and the
  idempotency receipt together.  The caller is told "accepted" only after
  ``COMMIT`` returns.
* a process-wide lock serialises writers inside the single uvicorn worker;
  ``BEGIN IMMEDIATE`` serialises across processes (scripts, backups).
* ``awards`` has ``PRIMARY KEY (room_id, player_id)`` so a duplicate winner
  is impossible even if the engine were wrong.

FAIL CLOSED: the first successful initialisation writes a marker next to the
database.  If the marker exists and the database is missing or unreadable,
``open_store`` raises instead of silently creating an empty room store.

Host/disk loss is a DIFFERENT failure: recovery point is the last off-host
copy (see ``docs/auction/ROOKIE_AUCTION_ROOM.md`` §Recovery).  This module
does not pretend otherwise.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from src.auction import engine
from src.auction.engine import AuctionError

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "auction" / "auction.sqlite"
MARKER_NAME = ".auction_store_initialized"
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    handle TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    sleeper_user_id TEXT UNIQUE,
    pw_hash TEXT,
    site_username TEXT UNIQUE,
    is_site_admin INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    pw_changed_at REAL,
    disabled_at REAL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    last_seen_at REAL NOT NULL,
    revoked_at REAL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS rooms (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    room_type TEXT NOT NULL CHECK (room_type IN ('mock','official')),
    status TEXT NOT NULL,
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at REAL NOT NULL,
    revision INTEGER NOT NULL,
    state_json TEXT NOT NULL,
    initial_state_json TEXT NOT NULL,
    next_due REAL,
    clock_offset REAL NOT NULL DEFAULT 0,
    last_heartbeat REAL,
    has_bots INTEGER NOT NULL DEFAULT 0,
    archived_at REAL,
    cloned_from TEXT
);

CREATE TABLE IF NOT EXISTS members (
    room_id TEXT NOT NULL REFERENCES rooms(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    role TEXT NOT NULL CHECK (role IN ('commissioner','manager','observer')),
    seat_id TEXT,
    created_at REAL NOT NULL,
    removed_at REAL,
    PRIMARY KEY (room_id, user_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS members_one_user_per_seat
    ON members(room_id, seat_id) WHERE seat_id IS NOT NULL AND removed_at IS NULL;

CREATE TABLE IF NOT EXISTS invites (
    token_hash TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(id),
    seat_id TEXT,
    role TEXT NOT NULL,
    intended_handle TEXT,
    intended_sleeper_user_id TEXT,
    created_by INTEGER NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    used_at REAL,
    used_by INTEGER,
    revoked_at REAL
);

CREATE TABLE IF NOT EXISTS commands (
    room_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    kind TEXT NOT NULL,
    actor_user_id INTEGER,
    actor_seat TEXT,
    payload_json TEXT NOT NULL,
    room_now REAL NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (room_id, revision)
);

CREATE TABLE IF NOT EXISTS events (
    room_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    idx INTEGER NOT NULL,
    type TEXT NOT NULL,
    vis TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    room_now REAL NOT NULL,
    PRIMARY KEY (room_id, revision, idx)
);

CREATE TABLE IF NOT EXISTS idempotency (
    room_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    revision INTEGER,
    status INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (room_id, user_id, key)
);

CREATE TABLE IF NOT EXISTS awards (
    room_id TEXT NOT NULL,
    player_id TEXT NOT NULL,
    auction_id TEXT NOT NULL,
    seat_id TEXT NOT NULL,
    price INTEGER NOT NULL CHECK (price >= 0),
    awarded_at REAL NOT NULL,
    PRIMARY KEY (room_id, player_id)
);

CREATE TABLE IF NOT EXISTS route_receipts (
    user_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    scope TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    status INTEGER NOT NULL,
    body_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (user_id, key)
);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    user_id INTEGER,
    room_id TEXT,
    action TEXT NOT NULL,
    detail_json TEXT NOT NULL
);
"""


class StoreUnavailable(RuntimeError):
    """Storage is missing or unreadable after having existed — fail closed."""


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._revisions: dict[str, int] = {}
        self._listeners: list = []
        self._outage_checked: set[str] = set()
        self._wconn: sqlite3.Connection | None = None
        self._local = threading.local()
        self._readers: list[sqlite3.Connection] = []
        # Changes with every process that opens the store (a restart, or a
        # restore from backup).  Revisions can go BACKWARDS across a restore;
        # clients compare this epoch so they adopt the restored snapshot
        # instead of discarding it as "older".
        self.epoch = secrets.token_hex(6)

    # -- connection -------------------------------------------------------

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.path), timeout=15, isolation_level=None, check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        return conn

    # Connections are reused rather than opened per call: opening one (plus
    # its PRAGMAs) cost ~7 ms p50 / ~35 ms p95 under a 12-manager burst, on
    # every session lookup, view and long-poll wake.  One writer connection
    # (only ever used under ``_lock``) and one autocommit reader per thread;
    # an autocommit SELECT always sees the latest committed revision.

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self._wconn
            if conn is None:
                conn = self._wconn = self.connect()
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    # A connection that cannot roll back is not reused.
                    self._wconn = None
                    conn.close()
                raise
            try:
                conn.execute("COMMIT")
            except sqlite3.Error:
                self._wconn = None
                conn.close()
                raise

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._local.conn = self.connect()
            with self._lock:
                self._readers.append(conn)
        yield conn

    def close(self) -> None:
        """Release every cached connection (scratch/restored stores, tests)."""
        with self._lock:
            conns = [c for c in [self._wconn, *self._readers] if c is not None]
            self._wconn = None
            self._readers = []
            self._local = threading.local()
        for c in conns:
            try:
                c.close()
            except sqlite3.Error:
                pass

    def on_commit(self, fn) -> None:
        self._listeners.append(fn)

    def _notify(self, room_id: str, revision: int) -> None:
        self._revisions[room_id] = revision
        for fn in list(self._listeners):
            try:
                fn(room_id, revision)
            except Exception:  # noqa: BLE001 - a listener never fails a commit
                pass

    def cached_revision(self, room_id: str) -> int | None:
        return self._revisions.get(room_id)

    # -- rooms --------------------------------------------------------------

    def create_room(
        self, state: dict, *, created_by: int, now_real: float, cloned_from: str | None = None
    ) -> str:
        blob = json.dumps(state, sort_keys=True)
        has_bots = int(any(s.get("is_bot") for s in state["seats"]))
        with self.write() as conn:
            conn.execute(
                "INSERT INTO rooms (id, name, room_type, status, created_by, created_at, revision, state_json,"
                " initial_state_json, next_due, clock_offset, last_heartbeat, has_bots, cloned_from)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    state["room_id"],
                    state["name"],
                    state["room_type"],
                    state["status"],
                    created_by,
                    now_real,
                    0,
                    blob,
                    blob,
                    None,
                    0.0,
                    now_real,
                    has_bots,
                    cloned_from,
                ),
            )
            conn.execute(
                "INSERT INTO audit (at, user_id, room_id, action, detail_json) VALUES (?,?,?,?,?)",
                (
                    now_real,
                    created_by,
                    state["room_id"],
                    "room_created",
                    json.dumps({"room_type": state["room_type"]}),
                ),
            )
        self._notify(state["room_id"], 0)
        return state["room_id"]

    def room_row(self, room_id: str) -> sqlite3.Row:
        with self.read() as conn:
            row = conn.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        if row is None:
            raise AuctionError("unknown_room", "no such room", 404)
        return row

    def load(self, room_id: str) -> tuple[dict, int, float]:
        row = self.room_row(room_id)
        return json.loads(row["state_json"]), int(row["revision"]), float(row["clock_offset"])

    @staticmethod
    def room_now(row: sqlite3.Row, now_real: float) -> float:
        # Only a MOCK room can have a non-zero virtual clock offset.
        offset = float(row["clock_offset"]) if row["room_type"] == "mock" else 0.0
        return now_real + offset

    # -- the one write path for room state ---------------------------------

    def execute(
        self,
        room_id: str,
        cmd: dict,
        *,
        user_id: int | None,
        now_real: float,
        idem_key: str | None = None,
        at_real: float | None = None,
        _guard: bool = True,
    ) -> dict:
        """Apply one command atomically.  Returns ``{status, result, revision, replayed}``.

        With ``idem_key``: a retry with the same key and the same payload
        returns the ORIGINAL outcome (accepted or rejected) without applying
        anything again; the same key with a different payload is a 409.
        """
        if _guard:
            self.outage_guard(room_id, now_real)
        payload_hash = _hash_payload(cmd)
        with self.write() as conn:
            row = conn.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
            if row is None:
                raise AuctionError("unknown_room", "no such room", 404)
            if idem_key is not None and user_id is not None:
                prior = conn.execute(
                    "SELECT * FROM idempotency WHERE room_id=? AND user_id=? AND key=?",
                    (room_id, user_id, idem_key),
                ).fetchone()
                if prior is not None:
                    if prior["payload_hash"] != payload_hash:
                        raise AuctionError(
                            "idempotency_conflict",
                            "this idempotency key was already used for a different command",
                            409,
                        )
                    return {
                        "status": int(prior["status"]),
                        "result": json.loads(prior["result_json"]),
                        "revision": prior["revision"],
                        "replayed": True,
                    }
            state = json.loads(row["state_json"])
            now = self.room_now(row, now_real)
            # The request's clock was read before it waited for this lock; the
            # command log must never run backwards, so a request that was
            # overtaken is applied at the moment the room had already reached.
            last = conn.execute(
                "SELECT room_now FROM commands WHERE room_id=? ORDER BY revision DESC LIMIT 1",
                (room_id,),
            ).fetchone()
            if last is not None and float(last["room_now"]) > now:
                now = float(last["room_now"])
            if at_real is not None and "at" not in cmd:
                cmd = {**cmd, "at": self.room_now(row, at_real)}
            revision = int(row["revision"])
            try:
                new_state, result, events = engine.apply_command(state, cmd, now)
                status = 200
            except AuctionError as exc:
                if idem_key is None or user_id is None:
                    raise
                result, status = exc.to_dict(), exc.status
                new_state, events = state, []
            if new_state != state:
                revision += 1
                conn.execute(
                    # NOT last_heartbeat: only the runtime's liveness beat is
                    # evidence the room was reachable; a command committed right
                    # after a restart must not erase the outage it follows.
                    "UPDATE rooms SET state_json=?, revision=?, status=?, next_due=? WHERE id=?",
                    (
                        json.dumps(new_state, sort_keys=True),
                        revision,
                        new_state["status"],
                        engine.next_due_time(new_state),
                        room_id,
                    ),
                )
                conn.execute(
                    "INSERT INTO commands (room_id, revision, kind, actor_user_id, actor_seat, payload_json,"
                    " room_now, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        room_id,
                        revision,
                        cmd.get("kind"),
                        user_id,
                        (cmd.get("actor") or {}).get("seat"),
                        json.dumps(cmd, sort_keys=True),
                        now,
                        now_real,
                    ),
                )
                for i, ev in enumerate(events):
                    conn.execute(
                        "INSERT INTO events (room_id, revision, idx, type, vis, payload_json, room_now)"
                        " VALUES (?,?,?,?,?,?,?)",
                        (
                            room_id,
                            revision,
                            i,
                            ev["type"],
                            ev["vis"],
                            json.dumps(ev["data"], sort_keys=True),
                            now,
                        ),
                    )
                    if ev["type"] == "sold":
                        d = ev["data"]
                        conn.execute(
                            "INSERT INTO awards (room_id, player_id, auction_id, seat_id, price, awarded_at)"
                            " VALUES (?,?,?,?,?,?)",
                            (
                                room_id,
                                d["player"],
                                d["auction"],
                                d["seat"],
                                int(d["price"]),
                                d["at"],
                            ),
                        )
                # AUC-002: inbox/outbox rows commit WITH the auction event,
                # under a savepoint — a notification fault can never reject
                # a valid bid or roll back a sale.
                conn.execute("SAVEPOINT notify")
                try:
                    from src.auction import notify

                    notify.record_transition(
                        conn,
                        room_id=room_id,
                        room_type=row["room_type"],
                        offset=float(row["clock_offset"]) if row["room_type"] == "mock" else 0.0,
                        before=state,
                        after=new_state,
                        events=events,
                        revision=revision,
                        room_now=now,
                        now_real=now_real,
                        actor_seat=(cmd.get("actor") or {}).get("seat"),
                    )
                    conn.execute("RELEASE notify")
                except Exception as exc:  # noqa: BLE001
                    conn.execute("ROLLBACK TO notify")
                    conn.execute("RELEASE notify")
                    self.audit(
                        conn,
                        now_real=now_real,
                        user_id=None,
                        room_id=room_id,
                        action="notification_record_failed",
                        detail={
                            "error": f"{type(exc).__name__}: {exc}"[:300],
                            "revision": revision,
                        },
                    )
            if idem_key is not None and user_id is not None:
                conn.execute(
                    "INSERT INTO idempotency (room_id, user_id, key, payload_hash, revision, status, result_json,"
                    " created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        room_id,
                        user_id,
                        idem_key,
                        payload_hash,
                        revision,
                        status,
                        json.dumps(result),
                        now_real,
                    ),
                )
        # Committed.  Only now is it safe to announce.
        self._notify(room_id, revision)
        return {"status": status, "result": result, "revision": revision, "replayed": False}

    def outage_guard(self, room_id: str, now_real: float, *, force: bool = False) -> bool:
        """Pause a running room whose liveness beat is older than its outage
        threshold, AS OF that last beat — before anything else touches it.

        Runs before the first command on each room in this process (and at
        runtime startup with ``force``), so no command can settle lots whose
        clocks ran while nobody could reach the service, and no rejection can
        be recorded against an outage window that is about to be undone.
        """
        if room_id in self._outage_checked and not force:
            return False
        with self._lock:
            if room_id in self._outage_checked and not force:
                return False
            try:
                row = self.room_row(room_id)
            except AuctionError:
                return False
            state = json.loads(row["state_json"])
            hb = row["last_heartbeat"]
            # A committed command is proof the service was reachable at that
            # moment too: a heartbeat lagging behind a busy worker must not
            # make a restart "outage-pause" a room that was taking bids.
            with self.read() as conn:
                last_cmd = conn.execute(
                    "SELECT MAX(created_at) FROM commands WHERE room_id=?", (room_id,)
                ).fetchone()[0]
            if hb is not None and last_cmd is not None:
                hb = max(float(hb), float(last_cmd))
            threshold = float(state["rules"].get("outage_threshold_seconds") or 300)
            paused = False
            if (
                state["status"] in ("running", "draining")
                and not state["paused"]
                and hb is not None
                and now_real - float(hb) > threshold
            ):
                self.execute(
                    room_id,
                    {
                        "kind": "pause",
                        "actor": {
                            "role": "commissioner",
                            "user": None,
                            "seat": None,
                            "system": "outage",
                        },
                        "pause_kind": "outage",
                        "reason": (
                            f"Service was unreachable for about {int((now_real - float(hb)) // 60)} minutes; "
                            "clocks froze at the last confirmed moment."
                        ),
                    },
                    user_id=None,
                    now_real=now_real,
                    at_real=float(hb),
                    _guard=False,
                )
                paused = True
            self._outage_checked.add(room_id)
            return paused

    def receipt(self, room_id: str, user_id: int, key: str) -> dict | None:
        with self.read() as conn:
            row = conn.execute(
                "SELECT * FROM idempotency WHERE room_id=? AND user_id=? AND key=?",
                (room_id, user_id, key),
            ).fetchone()
        if row is None:
            return None
        return {
            "status": int(row["status"]),
            "result": json.loads(row["result_json"]),
            "revision": row["revision"],
        }

    def advance_mock_clock(
        self, room_id: str, seconds: float, *, user_id: int, now_real: float
    ) -> dict:
        if not (0 < seconds <= 30 * 86400):
            raise AuctionError("bad_time", "advance between 1 second and 30 days")
        with self.write() as conn:
            row = conn.execute("SELECT room_type FROM rooms WHERE id=?", (room_id,)).fetchone()
            if row is None:
                raise AuctionError("unknown_room", "no such room", 404)
            if row["room_type"] != "mock":
                raise AuctionError("forbidden", "the virtual clock exists only in mock rooms", 403)
            conn.execute(
                "UPDATE rooms SET clock_offset = clock_offset + ? WHERE id=?",
                (float(seconds), room_id),
            )
            conn.execute(
                "INSERT INTO audit (at, user_id, room_id, action, detail_json) VALUES (?,?,?,?,?)",
                (
                    now_real,
                    user_id,
                    room_id,
                    "mock_clock_advanced",
                    json.dumps({"seconds": seconds}),
                ),
            )
        return self.execute(
            room_id,
            {"kind": "advance", "actor": {"role": "system"}},
            user_id=None,
            now_real=now_real,
        )

    # -- queries used by the runtime ---------------------------------------

    def due_rooms(self, now_real: float) -> list[str]:
        with self.read() as conn:
            rows = conn.execute(
                "SELECT id FROM rooms WHERE archived_at IS NULL AND next_due IS NOT NULL"
                " AND next_due <= ? + CASE room_type WHEN 'mock' THEN clock_offset ELSE 0 END",
                (now_real,),
            ).fetchall()
        return [r["id"] for r in rows]

    def active_rooms(self) -> list[sqlite3.Row]:
        with self.read() as conn:
            return conn.execute(
                "SELECT id, room_type, status, has_bots, last_heartbeat, clock_offset FROM rooms"
                " WHERE archived_at IS NULL AND status IN ('running','draining')"
            ).fetchall()

    def heartbeat(self, room_ids: list[str], now_real: float) -> None:
        if not room_ids:
            return
        with self.write() as conn:
            conn.executemany(
                "UPDATE rooms SET last_heartbeat=? WHERE id=?", [(now_real, r) for r in room_ids]
            )

    def events_for(self, room_id: str, *, vis: set[str], limit: int = 120) -> list[dict]:
        marks = ",".join("?" for _ in vis)
        with self.read() as conn:
            rows = conn.execute(
                f"SELECT revision, idx, type, vis, payload_json, room_now FROM events WHERE room_id=? AND vis IN ({marks})"
                " ORDER BY revision DESC, idx DESC LIMIT ?",
                (room_id, *sorted(vis), limit),
            ).fetchall()
        return [
            {
                "revision": r["revision"],
                "idx": r["idx"],
                "type": r["type"],
                "vis": r["vis"],
                "data": json.loads(r["payload_json"]),
                "at": r["room_now"],
            }
            for r in rows
        ]

    def replay(self, room_id: str) -> dict:
        """Rebuild the room from its initial state + command log."""
        with self.read() as conn:
            room = conn.execute(
                "SELECT initial_state_json FROM rooms WHERE id=?", (room_id,)
            ).fetchone()
            cmds = conn.execute(
                "SELECT payload_json, room_now FROM commands WHERE room_id=? ORDER BY revision",
                (room_id,),
            ).fetchall()
        state = json.loads(room["initial_state_json"])
        for c in cmds:
            state, _, _ = engine.apply_command(
                state, json.loads(c["payload_json"]), float(c["room_now"])
            )
        return state

    def verify_room(self, room_id: str) -> dict:
        """Full integrity check used by restore drills and the ops probe."""
        state, revision, _ = self.load(room_id)
        engine.check_invariants(state)
        rebuilt = self.replay(room_id)
        with self.read() as conn:
            awards = {
                r["player_id"]: (r["seat_id"], r["price"])
                for r in conn.execute("SELECT * FROM awards WHERE room_id=?", (room_id,))
            }
        sold = {
            a["player"]: (a["winner"], a["price"])
            for a in state["auctions"].values()
            if a["status"] == "closed"
        }
        return {
            "room_id": room_id,
            "revision": revision,
            "replay_matches": rebuilt == state,
            "awards_match": awards == sold,
            "invariants_ok": True,
        }

    def list_rooms_for_user(self, user_id: int, *, include_all: bool = False) -> list[dict]:
        with self.read() as conn:
            if include_all:
                rows = conn.execute(
                    "SELECT r.id, r.name, r.room_type, r.status, r.created_at, m.role, m.seat_id FROM rooms r"
                    " LEFT JOIN members m ON m.room_id=r.id AND m.user_id=? AND m.removed_at IS NULL"
                    " WHERE r.archived_at IS NULL ORDER BY r.created_at DESC",
                    (user_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT r.id, r.name, r.room_type, r.status, r.created_at, m.role, m.seat_id FROM rooms r"
                    " JOIN members m ON m.room_id=r.id WHERE m.user_id=? AND m.removed_at IS NULL"
                    " AND r.archived_at IS NULL ORDER BY r.created_at DESC",
                    (user_id,),
                ).fetchall()
        return [dict(r) for r in rows]

    def audit(
        self,
        conn: sqlite3.Connection,
        *,
        now_real: float,
        user_id: int | None,
        room_id: str | None,
        action: str,
        detail: dict,
    ) -> None:
        conn.execute(
            "INSERT INTO audit (at, user_id, room_id, action, detail_json) VALUES (?,?,?,?,?)",
            (now_real, user_id, room_id, action, json.dumps(detail, sort_keys=True)),
        )


def _hash_payload(cmd: dict) -> str:
    return hashlib.sha256(json.dumps(cmd, sort_keys=True, default=str).encode()).hexdigest()


def new_room_id() -> str:
    return "r_" + secrets.token_hex(6)


# ---------------------------------------------------------------------------
# Opening — fail closed
# ---------------------------------------------------------------------------

_STORE: Store | None = None
_STORE_LOCK = threading.Lock()


def db_path() -> Path:
    raw = os.getenv("RISKIT_AUCTION_DB")
    return Path(raw) if raw else DEFAULT_DB_PATH


def _markers(path: Path) -> list[Path]:
    # One beside the database and one in the directory ABOVE it, so losing
    # the whole store directory (a clean, a re-provisioned volume) still
    # finds a marker and refuses rather than starting an empty store.
    return [
        path.parent / MARKER_NAME,
        path.parent.parent / f".auction_store_{path.parent.name}_{path.name}.initialized",
    ]


def open_store(path: Path | None = None) -> Store:
    path = Path(path) if path else db_path()
    markers = _markers(path)
    if any(m.exists() for m in markers):
        if not path.exists():
            raise StoreUnavailable(
                f"auction store marker present but {path} is missing — refusing to create an empty store"
            )
        try:
            with sqlite3.connect(str(path)) as probe:
                ver = probe.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
                probe.execute("PRAGMA quick_check").fetchone()
        except sqlite3.DatabaseError as exc:
            raise StoreUnavailable(f"auction store unreadable: {exc}") from exc
        if ver is None:
            raise StoreUnavailable("auction store has no schema_version — refusing")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    store = Store(path)
    conn = store.connect()
    try:
        conn.executescript(_SCHEMA)
        from src.auction import notify

        notify.ensure_schema(conn)
        from src.auction import recovery

        recovery.ensure_schema(conn)
        from src.auction import feedback

        feedback.ensure_schema(conn)
        conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('store_id', ?)",
            (secrets.token_hex(8),),
        )
    finally:
        conn.close()
    for m in markers:
        if not m.exists():
            try:
                m.write_text(f"initialized {time.time()} {path}\n", encoding="utf-8")
            except OSError:  # pragma: no cover - read-only parent
                pass
    return store


def get_store() -> Store:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = open_store()
        return _STORE


def reset_store_for_tests(store: Store | None) -> None:
    global _STORE
    with _STORE_LOCK:
        _STORE = store
