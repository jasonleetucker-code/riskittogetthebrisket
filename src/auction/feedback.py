"""Rehearsal problem reports: one small, traceable defect loop for mocks.

A report is what a person saw in a room, pinned to what the SERVER knew at
that moment — the room, its committed revision and room clock, the rules
version, the pool version and the deployed code SHA — so a rehearsal defect
can be replayed from the command log instead of reconstructed from a
screenshot.  Nothing here changes the room: a report is not a command, has
no revision of its own, and never resets or archives the run it describes.

Visibility: the reporter sees their own reports; the commissioner sees every
report in the room.  Report text is the person's own words and is never
parsed for, or joined to, anyone's private maximum.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path

from src.auction.engine import AuctionError

SCHEMA = """
CREATE TABLE IF NOT EXISTS rehearsal_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id TEXT NOT NULL REFERENCES rooms(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    idem_key TEXT NOT NULL,
    role TEXT,
    seat_id TEXT,
    room_type TEXT NOT NULL,
    revision INTEGER NOT NULL,
    client_revision INTEGER,
    room_now REAL NOT NULL,
    created_at REAL NOT NULL,
    auction_id TEXT,
    player_id TEXT,
    player_label TEXT,
    observed_when TEXT,
    what_happened TEXT NOT NULL,
    expected TEXT,
    rule_version TEXT,
    pool_version TEXT,
    code_sha TEXT NOT NULL,
    user_agent TEXT,
    UNIQUE (room_id, user_id, idem_key)
);
CREATE INDEX IF NOT EXISTS rehearsal_reports_room ON rehearsal_reports(room_id, id);
"""

_TEXT_LIMITS = {"what_happened": 2000, "expected": 2000, "observed_when": 120, "player_label": 120}
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SHA_LOCK = threading.Lock()
_SHA: str | None = None


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def code_sha() -> str:
    """The deployed commit, read once per process (production deploys are a
    git checkout).  ``RISKIT_CODE_SHA`` wins when set; unknown stays
    ``"unknown"`` rather than a guess."""
    global _SHA
    with _SHA_LOCK:
        if _SHA is None:
            env = os.getenv("RISKIT_CODE_SHA", "").strip()
            if env:
                _SHA = env
            else:
                try:
                    out = subprocess.run(
                        ["git", "-C", str(_REPO_ROOT), "rev-parse", "HEAD"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=False,
                    )
                    sha = out.stdout.strip()
                    _SHA = sha if out.returncode == 0 and len(sha) == 40 else "unknown"
                except (OSError, subprocess.SubprocessError):
                    _SHA = "unknown"
        return _SHA


def _clean(body: dict, field: str) -> str | None:
    raw = body.get(field)
    if raw is None:
        return None
    text = str(raw).strip()
    return text[: _TEXT_LIMITS.get(field, 200)] or None


def file_report(
    store,
    *,
    room_id: str,
    user_id: int,
    member: dict,
    idem_key: str,
    body: dict,
    user_agent: str | None,
    now_real: float,
) -> dict:
    what = _clean(body, "what_happened")
    if not what:
        raise AuctionError("report_empty", "say what happened")
    with store.write() as conn:
        dup = conn.execute(
            "SELECT * FROM rehearsal_reports WHERE room_id=? AND user_id=? AND idem_key=?",
            (room_id, user_id, idem_key),
        ).fetchone()
        if dup is not None:
            return {**public_report(dup), "replayed": True}
        row = conn.execute(
            "SELECT room_type, revision, state_json, clock_offset FROM rooms WHERE id=?",
            (room_id,),
        ).fetchone()
        if row is None:
            raise AuctionError("unknown_room", "no such room", 404)
        state = json.loads(row["state_json"])
        room_now = store.room_now(row, now_real)
        aid = _clean(body, "auction")
        player_id = None
        if aid is not None:
            lot = (state.get("auctions") or {}).get(aid)
            if lot is None:
                raise AuctionError("unknown_auction", "no such auction", 404)
            player_id = lot.get("player")
        try:
            client_rev = int(body["client_revision"]) if "client_revision" in body else None
        except (TypeError, ValueError):
            client_rev = None
        cur = conn.execute(
            "INSERT INTO rehearsal_reports (room_id, user_id, idem_key, role, seat_id, room_type,"
            " revision, client_revision, room_now, created_at, auction_id, player_id, player_label,"
            " observed_when, what_happened, expected, rule_version, pool_version, code_sha, user_agent)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                room_id,
                user_id,
                idem_key,
                member.get("role"),
                member.get("seat_id"),
                row["room_type"],
                int(row["revision"]),
                client_rev,
                room_now,
                now_real,
                aid,
                player_id,
                _clean(body, "player_label"),
                _clean(body, "observed_when"),
                what,
                _clean(body, "expected"),
                (state.get("rules") or {}).get("rule_version"),
                str((state.get("pool") or {}).get("version") or "") or None,
                code_sha(),
                (user_agent or "")[:200] or None,
            ),
        )
        rep = conn.execute(
            "SELECT * FROM rehearsal_reports WHERE id=?", (cur.lastrowid,)
        ).fetchone()
        store.audit(
            conn,
            now_real=now_real,
            user_id=user_id,
            room_id=room_id,
            action="rehearsal_report",
            detail={"report": int(rep["id"]), "revision": int(row["revision"])},
        )
    return {**public_report(rep), "replayed": False}


def public_report(row) -> dict:
    return {
        "id": int(row["id"]),
        "roomId": row["room_id"],
        "userId": int(row["user_id"]),
        "role": row["role"],
        "seat": row["seat_id"],
        "roomType": row["room_type"],
        "revision": int(row["revision"]),
        "clientRevision": row["client_revision"],
        "roomNow": row["room_now"],
        "createdAt": row["created_at"],
        "auction": row["auction_id"],
        "playerId": row["player_id"],
        "playerLabel": row["player_label"],
        "observedWhen": row["observed_when"],
        "whatHappened": row["what_happened"],
        "expected": row["expected"],
        "ruleVersion": row["rule_version"],
        "poolVersion": row["pool_version"],
        "codeSha": row["code_sha"],
    }


def list_reports(store, *, room_id: str, user_id: int, see_all: bool) -> list[dict]:
    with store.read() as conn:
        if see_all:
            rows = conn.execute(
                "SELECT * FROM rehearsal_reports WHERE room_id=? ORDER BY id DESC", (room_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM rehearsal_reports WHERE room_id=? AND user_id=? ORDER BY id DESC",
                (room_id, user_id),
            ).fetchall()
    return [public_report(r) for r in rows]
