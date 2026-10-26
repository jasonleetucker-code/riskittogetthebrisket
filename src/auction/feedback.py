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

Mock rooms only.  The commissioner also bids (as a seat), and a report is free
text that people naturally fill with their own bid amounts ("my $5 bid showed
as $6") — so in a room with real stakes the commissioner's read-everything
view would be a channel for a rival's private maximum.  Rehearsals are mocks
(nothing real is at stake), so filing AND reading are refused for any other
room type: ``reports_mock_only``.
"""

from __future__ import annotations

import json
import os
import subprocess
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
# Revisions are plain counters; JS-safe so a client number round-trips exactly.
_MAX_CLIENT_REVISION = 2**53 - 1


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def _resolve_code_sha() -> str:
    """The deployed commit.  ``RISKIT_CODE_SHA`` wins when set; otherwise one
    ``git rev-parse HEAD`` (production deploys are a git checkout); unknown
    stays ``"unknown"`` rather than a guess.  Runs ONCE, at import — process
    startup — never on a request path: a subprocess inside ``store.write()``
    or on the event loop would stall every room."""
    env = os.getenv("RISKIT_CODE_SHA", "").strip()
    if env:
        return env
    try:
        out = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        sha = out.stdout.strip()
        return sha if out.returncode == 0 and len(sha) == 40 else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


_SHA: str = _resolve_code_sha()


def code_sha() -> str:
    """The deployed commit, resolved at import.  Never shells out."""
    return _SHA


def _require_mock_room(conn, room_id: str):
    """The room row, or the refusal for a room that is not a mock."""
    row = conn.execute(
        "SELECT room_type, revision, state_json, clock_offset FROM rooms WHERE id=?",
        (room_id,),
    ).fetchone()
    if row is None:
        raise AuctionError("unknown_room", "no such room", 404)
    if row["room_type"] != "mock":
        raise AuctionError(
            "reports_mock_only",
            "Problem reports are for mock rehearsal rooms only.",
            409,
        )
    return row


def _parse_client_revision(body: dict) -> int | None:
    """The revision the reporter's screen showed.  Unparseable → not recorded;
    parseable but outside any real revision (negative, non-finite, beyond the
    JS-safe range) → a 400, never an OverflowError from ``int()`` or from
    SQLite's 64-bit binding."""
    if "client_revision" not in body:
        return None
    try:
        value = int(body["client_revision"])
    except (TypeError, ValueError):
        return None
    except OverflowError:
        value = -1  # inf / -inf
    if not 0 <= value <= _MAX_CLIENT_REVISION:
        raise AuctionError("bad_client_revision", "client_revision is out of range", 400)
    return value


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
    client_rev = _parse_client_revision(body)
    with store.write() as conn:
        row = _require_mock_room(conn, room_id)
        dup = conn.execute(
            "SELECT * FROM rehearsal_reports WHERE room_id=? AND user_id=? AND idem_key=?",
            (room_id, user_id, idem_key),
        ).fetchone()
        if dup is not None:
            return {**public_report(dup), "replayed": True}
        state = json.loads(row["state_json"])
        room_now = store.room_now(row, now_real)
        aid = _clean(body, "auction")
        player_id = None
        if aid is not None:
            lot = (state.get("auctions") or {}).get(aid)
            if lot is None:
                raise AuctionError("unknown_auction", "no such auction", 404)
            player_id = lot.get("player")
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
        _require_mock_room(conn, room_id)
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
