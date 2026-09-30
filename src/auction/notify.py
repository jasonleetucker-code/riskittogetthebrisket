"""Rookie auction room notifications (AUC-002): inbox, outbox, Web Push, email.

ONE transport per channel, all reused: Web Push through
``src/api/push_delivery.py`` (pywebpush + the site's VAPID keys), the site's
``frontend/public/sw.js`` + manifest, and the site's SMTP sender for the
optional, explicitly-consented email backup.  No SMS, no third-party push
app, no paid service.

Truth rules
-----------
* Notifications are derived from the NET events of one committed
  transaction (``engine._emit_net_leadership``) — never from intermediate
  proxy steps.  A max $50 vs B max $39 leaves A leading at $40 with no
  "outbid"/"leading again" pair.
* Inbox + outbox rows are written INSIDE the same SQLite transaction as the
  auction event (``Store.execute`` → ``record_transition``) under a
  SAVEPOINT: a notification bug rolls back only the notification rows, never
  the bid.  External delivery happens later, in the runtime worker, never
  inside a bid transaction.
* Text uses PUBLIC facts only (player, public price, closing time).  No
  private maximum, no optimizer strategy, ever — and optional generic
  lock-screen previews hide even those.
* Every message is timestamped ("At 3:12 PM ET …") so a late delivery is
  still true; relevance is re-checked against the CURRENT room just before
  sending (still outbid? still your turn? same deadline?), and stale ones are
  marked ``stale`` instead of sent.
* Push-service acceptance (HTTP 201) is recorded as ``sent`` = "accepted by
  the push service".  It is NOT proof a phone displayed it; the test flow
  asks the person to confirm on the device.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
import sys
import time
from datetime import datetime
from typing import Any, Iterable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from src.auction import engine, schedule
from src.auction.engine import AuctionError
from src.auction.rules import window_of

log = logging.getLogger("auction.notify")

NY = ZoneInfo("America/New_York")

SCHEMA = """
CREATE TABLE IF NOT EXISTS notif_devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    endpoint TEXT NOT NULL UNIQUE,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    platform TEXT NOT NULL DEFAULT '',
    session_hash TEXT,
    created_at REAL NOT NULL,
    last_ok_at REAL,
    last_status TEXT,
    failures INTEGER NOT NULL DEFAULT 0,
    disabled_at REAL,
    disabled_reason TEXT
);
CREATE TABLE IF NOT EXISTS notif_prefs (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    prefs_json TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS notif_inbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    seat_id TEXT,
    logical_key TEXT NOT NULL,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    url TEXT NOT NULL,
    data_json TEXT NOT NULL,
    room_now REAL NOT NULL,
    created_at REAL NOT NULL,
    read_at REAL,
    is_mock INTEGER NOT NULL DEFAULT 0,
    UNIQUE (room_id, user_id, logical_key)
);
CREATE INDEX IF NOT EXISTS notif_inbox_user ON notif_inbox(user_id, id);
CREATE TABLE IF NOT EXISTS notif_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inbox_id INTEGER NOT NULL REFERENCES notif_inbox(id),
    user_id INTEGER NOT NULL,
    channel TEXT NOT NULL CHECK (channel IN ('push','email')),
    device_id INTEGER,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    claimed_at REAL,
    sent_at REAL,
    provider_status INTEGER,
    last_error TEXT,
    created_at REAL NOT NULL,
    UNIQUE (inbox_id, channel, device_id)
);
CREATE INDEX IF NOT EXISTS notif_outbox_due ON notif_outbox(status, next_attempt_at);
CREATE TABLE IF NOT EXISTS notif_watch (
    room_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    auction_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (room_id, user_id, auction_id)
);
CREATE TABLE IF NOT EXISTS notif_email (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    email TEXT NOT NULL,
    verified_at REAL,
    token_hash TEXT,
    token_expires REAL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS notif_email_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    kind TEXT NOT NULL,
    sent_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS notif_test_confirm (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    outbox_id INTEGER NOT NULL,
    seen INTEGER NOT NULL,
    note TEXT,
    confirmed_at REAL NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

DEFAULT_PREFS: dict[str, bool] = {
    # Low-noise defaults (owner AUC-002).
    "your_turn": True,
    "turn_expiring": True,
    "outbid": True,
    "leading_again": True,
    "deadline_extended": True,
    "won": True,
    "last_hour": True,
    "budget": True,
    "commissioner": True,
    "room_status": True,
    "trade": True,
    # Optional, off by default.
    "new_nomination": False,
    "other_purchase": False,
    "fifteen_min": False,
    "daily_summary": False,
    # Delivery options.
    "generic_previews": False,
    "quiet_hours": True,
    "email_backup": False,
    "mock_push": False,
}

PREF_LABELS: dict[str, str] = {
    "your_turn": "Your nomination turn (only when you can actually nominate)",
    "turn_expiring": "Your nomination turn is about to pass",
    "outbid": "You were outbid",
    "leading_again": "You are leading again (or your standing maximum just took the lead)",
    "deadline_extended": "A lot you bid on had its closing time extended by a late bid",
    "won": "You won a player (including $0)",
    "last_hour": "Last active bidding hour on lots you bid on, nominated or watch",
    "budget": "Your budget changed",
    "commissioner": "Commissioner correction affecting you",
    "room_status": "Pause, resume, recovery and draft completion",
    "trade": "Trade offers and completed dollar transfers",
    "new_nomination": "Every new nomination",
    "other_purchase": "Other managers' purchases",
    "fifteen_min": "15 active minutes left on involved lots",
    "daily_summary": "Morning (8 AM) and evening (8:45 PM ET) summary of your lots, money and turn",
    "generic_previews": "Generic lock-screen previews (hide player names and prices)",
    "quiet_hours": "Hold ordinary alerts during the 9 PM–8 AM pause",
    "email_backup": "Also email me (verified address only)",
    "mock_push": "Send me clearly labelled [MOCK] pushes from practice rooms",
}

# Which notification types a preference gates.
TYPE_PREF = {
    "your_turn": "your_turn",
    "turn_expiring": "turn_expiring",
    "outbid": "outbid",
    "leading_again": "leading_again",
    "proxy_leading": "leading_again",
    "deadline_extended": "deadline_extended",
    "won": "won",
    "last_hour": "last_hour",
    "fifteen_min": "fifteen_min",
    "budget": "budget",
    "commissioner": "commissioner",
    "room_status": "room_status",
    "new_nomination": "new_nomination",
    "other_purchase": "other_purchase",
    "trade": "trade",
    "daily_summary": "daily_summary",
    "test": None,
}

# Web Push time-to-live per type: an alert that is useless late must die.
TTL_SECONDS = {
    "your_turn": 2 * 3600,
    "turn_expiring": 3600,
    "outbid": 2 * 3600,
    "leading_again": 2 * 3600,
    "proxy_leading": 2 * 3600,
    "deadline_extended": 2 * 3600,
    "won": 12 * 3600,
    "last_hour": 3600,
    "fifteen_min": 15 * 60,
    "daily_summary": 2 * 3600,
    "budget": 12 * 3600,
    "commissioner": 12 * 3600,
    "room_status": 12 * 3600,
    "new_nomination": 3600,
    "other_purchase": 6 * 3600,
    "trade": 12 * 3600,
    "test": 10 * 60,
}
URGENCY = {
    "your_turn": "high",
    "outbid": "high",
    "last_hour": "high",
    "turn_expiring": "high",
    "test": "high",
}
# Critical types still deliver at 08:00 after a held night; ordinary ones are
# re-checked at 08:00 and dropped if no longer true.
EMAIL_TYPES = {
    "your_turn",
    "turn_expiring",
    "outbid",
    "won",
    "last_hour",
    "room_status",
    "commissioner",
    "budget",
    "trade",
}
MAX_LAST_HOUR_PER_LOT = 2  # bounded repeats across extensions
MAX_ATTEMPTS = 5
MOCK_PUSH_PER_HOUR = 30
EMAIL_DAILY_CAP = int(os.getenv("RISKIT_AUCTION_EMAIL_DAILY_CAP", "100"))
EMAIL_RECOVERY_RESERVE = int(os.getenv("RISKIT_AUCTION_EMAIL_RECOVERY_RESERVE", "20"))

# Known Web Push services.  Registration refuses any other host, so a client
# can never make the server POST to an arbitrary URL (SSRF).
_PUSH_HOST_PATTERNS = (
    re.compile(r"^fcm\.googleapis\.com$"),
    re.compile(r"^android\.googleapis\.com$"),
    re.compile(r"^updates\.push\.services\.mozilla\.com$"),
    re.compile(r"^(?:[a-z0-9-]+\.)*push\.apple\.com$"),
    re.compile(r"^(?:[a-z0-9-]+\.)*notify\.windows\.com$"),
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def get_prefs(conn: sqlite3.Connection, user_id: int) -> dict[str, bool]:
    row = conn.execute("SELECT prefs_json FROM notif_prefs WHERE user_id=?", (user_id,)).fetchone()
    prefs = dict(DEFAULT_PREFS)
    if row:
        try:
            stored = json.loads(row["prefs_json"])
            prefs.update({k: bool(v) for k, v in stored.items() if k in DEFAULT_PREFS})
        except ValueError:
            pass
    return prefs


def set_prefs(conn: sqlite3.Connection, user_id: int, patch: dict, now: float) -> dict[str, bool]:
    prefs = get_prefs(conn, user_id)
    for k, v in (patch or {}).items():
        if k not in DEFAULT_PREFS or not isinstance(v, bool):
            raise AuctionError("bad_pref", f"unknown or non-boolean preference {k!r}")
        prefs[k] = v
    if prefs["email_backup"]:
        em = conn.execute(
            "SELECT verified_at FROM notif_email WHERE user_id=?", (user_id,)
        ).fetchone()
        if not em or not em["verified_at"]:
            raise AuctionError(
                "email_unverified", "verify an email address before turning on email backup", 409
            )
    conn.execute(
        "INSERT INTO notif_prefs (user_id, prefs_json, updated_at) VALUES (?,?,?)"
        " ON CONFLICT(user_id) DO UPDATE SET prefs_json=excluded.prefs_json, updated_at=excluded.updated_at",
        (user_id, json.dumps(prefs, sort_keys=True), now),
    )
    return prefs


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------


def _session_hash(token: str | None) -> str | None:
    return hashlib.sha256(token.encode()).hexdigest() if token else None


def validate_subscription(sub: Any) -> dict:
    if not isinstance(sub, dict):
        raise AuctionError("bad_subscription", "subscription must be an object")
    endpoint = sub.get("endpoint")
    keys = sub.get("keys") or {}
    if not isinstance(endpoint, str) or len(endpoint) > 1000:
        raise AuctionError("bad_subscription", "invalid endpoint")
    parsed = urlparse(endpoint)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise AuctionError("bad_subscription", "push endpoints must be plain https URLs")
    if not any(p.match(host) for p in _PUSH_HOST_PATTERNS):
        raise AuctionError("bad_subscription", "that is not a recognised browser push service")
    p256dh, auth = keys.get("p256dh"), keys.get("auth")
    for k in (p256dh, auth):
        if (
            not isinstance(k, str)
            or not (8 <= len(k) <= 200)
            or not re.match(r"^[A-Za-z0-9_\-=]+$", k)
        ):
            raise AuctionError("bad_subscription", "invalid subscription keys")
    return {"endpoint": endpoint, "p256dh": p256dh, "auth": auth}


def register_device(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    session_token: str | None,
    sub: Any,
    label: str,
    platform: str,
    now: float,
) -> int:
    """Bind a browser push subscription to THIS account + session.

    A subscription is a physical browser.  If the same endpoint was bound to a
    different account (account switching on a shared phone), it moves to the
    account that just registered it — the previous account stops receiving
    on that device.  Never keyed by a client-supplied username.
    """
    clean = validate_subscription(sub)
    sh = _session_hash(session_token)
    conn.execute(
        "INSERT INTO notif_devices (user_id, endpoint, p256dh, auth, label, platform, session_hash, created_at)"
        " VALUES (?,?,?,?,?,?,?,?)"
        " ON CONFLICT(endpoint) DO UPDATE SET user_id=excluded.user_id, p256dh=excluded.p256dh, auth=excluded.auth,"
        " label=excluded.label, platform=excluded.platform, session_hash=excluded.session_hash,"
        " disabled_at=NULL, disabled_reason=NULL, failures=0",
        (
            user_id,
            clean["endpoint"],
            clean["p256dh"],
            clean["auth"],
            str(label)[:60],
            str(platform)[:20],
            sh,
            now,
        ),
    )
    return int(
        conn.execute(
            "SELECT id FROM notif_devices WHERE endpoint=?", (clean["endpoint"],)
        ).fetchone()["id"]
    )


def disable_device(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    device_id: int | None,
    endpoint: str | None,
    reason: str,
    now: float,
) -> int:
    if device_id is not None:
        cur = conn.execute(
            "UPDATE notif_devices SET disabled_at=?, disabled_reason=? WHERE id=? AND user_id=?",
            (now, reason, device_id, user_id),
        )
    else:
        cur = conn.execute(
            "UPDATE notif_devices SET disabled_at=?, disabled_reason=? WHERE endpoint=? AND user_id=?",
            (now, reason, endpoint, user_id),
        )
    return cur.rowcount


def disable_devices_for_session(
    conn: sqlite3.Connection, session_token: str | None, now: float
) -> None:
    sh = _session_hash(session_token)
    if sh:
        conn.execute(
            "UPDATE notif_devices SET disabled_at=?, disabled_reason='signed_out' WHERE session_hash=? AND disabled_at IS NULL",
            (now, sh),
        )


def _live_devices(conn: sqlite3.Connection, user_id: int, now: float) -> list[sqlite3.Row]:
    # A device delivers only while the session that registered it is live:
    # logout, password change and expiry all silence it automatically.
    return conn.execute(
        "SELECT d.* FROM notif_devices d JOIN sessions s ON s.token_hash = d.session_hash"
        " WHERE d.user_id=? AND d.disabled_at IS NULL AND s.revoked_at IS NULL AND s.expires_at > ?",
        (user_id, now),
    ).fetchall()


def list_devices(conn: sqlite3.Connection, user_id: int, now: float) -> list[dict]:
    live = {r["id"] for r in _live_devices(conn, user_id, now)}
    rows = conn.execute(
        "SELECT id, label, platform, created_at, last_ok_at, last_status, failures, disabled_at, disabled_reason"
        " FROM notif_devices WHERE user_id=? ORDER BY id DESC",
        (user_id,),
    ).fetchall()
    return [{**dict(r), "live": r["id"] in live} for r in rows]


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------


def _hm(d: datetime) -> str:
    return f"{d.hour % 12 or 12}:{d.minute:02d} {'AM' if d.hour < 12 else 'PM'} ET"


def _clock(t: float | None) -> str:
    if t is None:
        return "—"
    return _hm(datetime.fromtimestamp(t, NY))


def _when(t: float | None) -> str:
    if t is None:
        return "—"
    d = datetime.fromtimestamp(t, NY)
    return f"{d.strftime('%a')} {_hm(d)}"


def _player(state: dict, pid: str) -> str:
    return str((state["pool"]["players"].get(pid) or {}).get("name") or "a player")


def compose(ntype: str, state: dict, data: dict, room_now: float) -> tuple[str, str]:
    """Title/body from PUBLIC facts only.  Never a maximum or a strategy."""
    room = state.get("name") or "Rookie auction"
    at = _clock(room_now)
    aid = data.get("auction")
    a = state["auctions"].get(aid) if aid else None
    pl = _player(state, a["player"]) if a else ""
    if ntype == "your_turn":
        dl = data.get("deadline")
        tail = f" Unused turns pass {_when(dl)}." if dl else ""
        return (
            "Your nomination turn",
            f"{room}: you can nominate now (round {data.get('round')}).{tail}",
        )
    if ntype == "turn_expiring":
        return (
            "Nomination turn ending",
            f"{room}: your turn passes {_when(data.get('deadline'))} if unused.",
        )
    if ntype == "outbid":
        extra = (
            " Money you have reserved on other lots limited your bid." if data.get("capped") else ""
        )
        return (
            f"Outbid: {pl}",
            f"At {at}, {pl} moved to ${data.get('price')} and you are no longer leading.{extra}",
        )
    if ntype == "leading_again":
        return f"Leading again: {pl}", f"At {at}, you lead {pl} at ${data.get('price')}."
    if ntype == "proxy_leading":
        return (
            f"Now leading: {pl}",
            f"At {at}, money freed elsewhere let your standing maximum take the lead on {pl} at "
            f"${data.get('price')}. That ${data.get('price')} is now reserved.",
        )
    if ntype == "deadline_extended":
        return (
            f"Clock extended: {pl}",
            f"A late bid moved {pl} to ${data.get('price')} at {at}. It now closes "
            f"{_when(data.get('deadline'))} (bidding pauses 9 PM–8 AM ET).",
        )
    if ntype == "won":
        return f"You won {pl}", f"{pl} sold to you for ${data.get('price')} at {at}."
    if ntype == "other_purchase":
        return f"Sold: {pl}", f"{pl} sold for ${data.get('price')} at {at}."
    if ntype == "new_nomination":
        return (
            f"Nominated: {pl}",
            f"{room}: {pl} is open for bids. Closes {_when(data.get('deadline'))}.",
        )
    if ntype in ("last_hour", "fifteen_min"):
        span = "1 active hour" if ntype == "last_hour" else "15 active minutes"
        lead = "you are leading" if data.get("leading") else "you are not leading"
        return (
            f"{span} left: {pl}",
            f"{pl} closes {_when(data.get('deadline'))} (bidding pauses 9 PM–8 AM ET). ${data.get('price')} now; {lead} as of {at}.",
        )
    if ntype == "budget":
        return (
            "Your auction budget changed",
            f"At {at} the commissioner adjusted your balance by ${data.get('amount')}: {data.get('reason')}",
        )
    if ntype == "commissioner":
        return (
            "Commissioner correction",
            f"At {at} the commissioner changed your seat setup: {data.get('reason') or 'see the room'}.",
        )
    if ntype == "room_status":
        kind = data.get("kind")
        text = {
            "paused": f"The room paused at {at}. {data.get('reason') or ''}".strip(),
            "resumed": f"The room resumed at {at}.",
            "complete": f"The auction finished at {at}.",
            "draining": f"No new nominations after {at}; open lots finish normally.",
        }.get(kind, f"Room update at {at}.")
        return {
            "paused": "Auction paused",
            "resumed": "Auction resumed",
            "complete": "Auction complete",
            "draining": "Final lots",
        }.get(kind, "Auction update"), text
    if ntype == "trade":
        kind = data.get("kind")
        if kind == "offered":
            return (
                "New trade offer",
                f"{room}: you have a trade offer ({data.get('trade')}) as of {at}. Review it in the room.",
            )
        if kind == "completed":
            delta = data.get("dollars")
            money = (
                f" Your balance changed by ${delta}." if isinstance(delta, int) and delta else ""
            )
            return "Trade completed", f"{room}: trade {data.get('trade')} settled at {at}.{money}"
        return "Trade update", f"{room}: trade {data.get('trade')} is {kind} as of {at}."
    if ntype == "daily_summary":
        which = "Morning" if data.get("slot") == "am" else "Evening"
        turn = " It is your nomination turn." if data.get("on_clock") else ""
        return (
            f"{which} auction summary",
            f"{room} at {at}: you lead {data.get('leading')} lot(s) (${data.get('committed')} reserved), "
            f"${data.get('spendable')} spendable, outbid on {data.get('outbid')} lot(s) you bid on.{turn}",
        )
    if ntype == "test":
        return (
            "Chase Upside test notification",
            "If you can read this on your phone, notifications work. Confirm it in the app.",
        )
    return "Auction update", f"{room}: new activity at {at}."


# ---------------------------------------------------------------------------
# Recording (inside the auction transaction)
# ---------------------------------------------------------------------------


def _seat_users(conn: sqlite3.Connection, room_id: str) -> dict[str, int]:
    rows = conn.execute(
        "SELECT user_id, seat_id FROM members WHERE room_id=? AND seat_id IS NOT NULL AND removed_at IS NULL",
        (room_id,),
    ).fetchall()
    return {r["seat_id"]: int(r["user_id"]) for r in rows}


def _deliver_after(
    state: dict, room_now: float, offset: float, prefs: dict, ntype: str, now_real: float
) -> float:
    win = window_of(state["rules"])
    if ntype == "test" or not prefs.get("quiet_hours", True) or schedule.is_active(win, room_now):
        return now_real
    # Held until the room's next active start (08:00 ET), then re-checked.
    return schedule.next_active_start(win, room_now) - offset


def enqueue(
    conn: sqlite3.Connection,
    *,
    room_id: str,
    room_type: str,
    state: dict | None,
    user_id: int,
    seat_id: str | None,
    ntype: str,
    logical_key: str,
    data: dict,
    room_now: float,
    offset: float,
    now_real: float,
) -> int | None:
    prefs = get_prefs(conn, user_id)
    pref_key = TYPE_PREF.get(ntype)
    if pref_key and not prefs.get(pref_key, False):
        return None
    if state is not None:
        title, body = compose(ntype, state, data, room_now)
    else:
        title, body = compose(
            ntype, {"name": "", "auctions": {}, "pool": {"players": {}}}, data, room_now
        )
    is_mock = room_type == "mock"
    if is_mock:
        title = f"[MOCK] {title}"
    url = f"/auction/{room_id}" if room_id else "/auction/notifications"
    cur = conn.execute(
        "INSERT OR IGNORE INTO notif_inbox (room_id, user_id, seat_id, logical_key, type, title, body, url, data_json,"
        " room_now, created_at, is_mock) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            room_id,
            user_id,
            seat_id,
            logical_key,
            ntype,
            title[:120],
            body[:300],
            url,
            json.dumps(data, sort_keys=True),
            room_now,
            now_real,
            int(is_mock),
        ),
    )
    if cur.rowcount == 0:
        return None  # logical-event dedup
    inbox_id = int(cur.lastrowid)
    ttl = TTL_SECONDS.get(ntype, 3600)
    due = (
        _deliver_after(state, room_now, offset, prefs, ntype, now_real)
        if state is not None
        else now_real
    )
    expires = max(due, now_real) + ttl
    mock_blocked = is_mock and not prefs.get("mock_push", False)
    for dev in _live_devices(conn, user_id, now_real):
        conn.execute(
            "INSERT OR IGNORE INTO notif_outbox (inbox_id, user_id, channel, device_id, status, next_attempt_at, expires_at, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                inbox_id,
                user_id,
                "push",
                dev["id"],
                "suppressed_mock" if mock_blocked else "pending",
                due,
                expires,
                now_real,
            ),
        )
    if prefs.get("email_backup") and ntype in EMAIL_TYPES and not is_mock:
        em = conn.execute(
            "SELECT verified_at FROM notif_email WHERE user_id=?", (user_id,)
        ).fetchone()
        if em and em["verified_at"]:
            conn.execute(
                "INSERT OR IGNORE INTO notif_outbox (inbox_id, user_id, channel, device_id, status, next_attempt_at, expires_at, created_at)"
                " VALUES (?,?,?,NULL,'pending',?,?,?)",
                (inbox_id, user_id, "email", due, expires, now_real),
            )
    return inbox_id


def record_transition(
    conn: sqlite3.Connection,
    *,
    room_id: str,
    room_type: str,
    offset: float,
    before: dict,
    after: dict,
    events: list[dict],
    revision: int,
    room_now: float,
    now_real: float,
    actor_seat: str | None = None,
) -> int:
    """Turn one committed transition's NET events into inbox/outbox rows.

    ``leading_again`` is not sent to the seat whose own action caused it (they
    just saw it on screen); it IS sent when a separate event restores them —
    a rival withdrawing, or a capped proxy reactivating after money frees."""
    users = _seat_users(conn, room_id)
    all_seats = [s["id"] for s in after["seats"]]
    made = 0

    def put(seat: str, ntype: str, key: str, data: dict) -> None:
        nonlocal made
        uid = users.get(seat)
        if uid is None:
            return  # bot or unclaimed seat: nobody to tell
        if enqueue(
            conn,
            room_id=room_id,
            room_type=room_type,
            state=after,
            user_id=uid,
            seat_id=seat,
            ntype=ntype,
            logical_key=key,
            data=data,
            room_now=room_now,
            offset=offset,
            now_real=now_real,
        ):
            made += 1

    on_clock = {r["id"] for r in engine._window_rights(after) if r["window_at"] is not None}
    for ev in events:
        et, d, vis = ev["type"], ev["data"], ev["vis"]
        seat = vis.split(":", 1)[1] if vis.startswith("seat:") else None
        if et == "nomination_turn":
            # Only when the seat can ACTUALLY nominate now.
            if d["right"] in on_clock and after["status"] == "running" and not after["paused"]:
                put(
                    d["seat"],
                    "your_turn",
                    f"turn:{d['right']}",
                    {"right": d["right"], "round": d["round"], "deadline": d.get("deadline")},
                )
        elif et == "outbid" and seat:
            a = after["auctions"][d["auction"]]
            b = a["bids"].get(seat) or {}
            capped = bool(b.get("active")) and engine.capacity(after, seat, a["id"]) < int(
                b.get("max") or 0
            )
            put(
                seat,
                "outbid",
                f"outbid:{d['auction']}:r{revision}",
                {"auction": d["auction"], "price": d["price"], "capped": capped},
            )
        elif et == "leading_again" and seat and seat != actor_seat:
            put(
                seat,
                "leading_again",
                f"lead:{d['auction']}:r{revision}",
                {"auction": d["auction"], "price": d["price"]},
            )
        elif et == "proxy_leading" and seat and seat != actor_seat:
            # A separate event (money freed) let this seat's standing maximum
            # take a lot it had never led: its money is newly reserved.
            put(
                seat,
                "proxy_leading",
                f"plead:{d['auction']}:r{revision}",
                {"auction": d["auction"], "price": d["price"]},
            )
        elif et == "price" and d.get("extended"):
            a = after["auctions"][d["auction"]]
            told = {
                ev2["vis"].split(":", 1)[1]
                for ev2 in events
                if ev2["type"] in ("outbid", "leading_again", "proxy_leading")
                and ev2["data"].get("auction") == d["auction"]
                and ev2["vis"].startswith("seat:")
            }
            involved = [s_ for s_, b in (a.get("bids") or {}).items() if b.get("active")] + [
                a["nominator"]
            ]
            for s_ in dict.fromkeys(involved):
                if s_ == actor_seat or s_ in told:
                    continue
                put(
                    s_,
                    "deadline_extended",
                    f"ext:{d['auction']}:{d['deadline']}",
                    {"auction": d["auction"], "price": d["price"], "deadline": d["deadline"]},
                )
        elif et == "sold":
            put(
                d["seat"],
                "won",
                f"won:{d['auction']}",
                {"auction": d["auction"], "price": d["price"]},
            )
            for other in all_seats:
                if other != d["seat"]:
                    put(
                        other,
                        "other_purchase",
                        f"sold:{d['auction']}",
                        {"auction": d["auction"], "price": d["price"]},
                    )
        elif et == "nominated":
            for other in all_seats:
                if other != d["seat"]:
                    put(
                        other,
                        "new_nomination",
                        f"nom:{d['auction']}",
                        {"auction": d["auction"], "deadline": d.get("deadline")},
                    )
        elif et in ("paused", "resumed", "complete", "draining"):
            for s in all_seats:
                put(s, "room_status", f"{et}:r{revision}", {"kind": et, "reason": d.get("reason")})
            if et == "resumed" and after["status"] == "running" and not after["paused"]:
                # A turn that came on the clock while the room was paused was
                # never announced; the same logical key makes this a no-op for
                # a turn that already was.
                for r in engine._window_rights(after):
                    if r["window_at"] is None:
                        continue
                    put(
                        r["seat"],
                        "your_turn",
                        f"turn:{r['id']}",
                        {"right": r["id"], "round": r["round"], "deadline": r.get("deadline")},
                    )
        elif et == "budget_adjusted":
            put(
                d["seat"],
                "budget",
                f"budget:r{revision}",
                {"amount": d["amount"], "reason": d.get("reason")},
            )
        elif et == "trade_offered" and seat:
            put(seat, "trade", f"tradeoffer:{d['trade']}", {"kind": "offered", "trade": d["trade"]})
        elif et == "trade_completed":
            for s_ in d.get("seats") or []:
                put(
                    s_,
                    "trade",
                    f"tradedone:{d['trade']}",
                    {
                        "kind": "completed",
                        "trade": d["trade"],
                        "dollars": (d.get("dollars") or {}).get(s_),
                    },
                )
        elif et in ("trade_declined", "trade_cancelled", "trade_awaiting_verification") and seat:
            put(
                seat,
                "trade",
                f"{et}:{d['trade']}",
                {"kind": et.replace("trade_", ""), "trade": d["trade"]},
            )
        elif et == "seat_changed" and "opening_budget" in (d.get("after") or {}):
            put(d["seat"], "commissioner", f"seat:r{revision}", {"reason": d.get("reason")})
    return made


# ---------------------------------------------------------------------------
# Reminders — derived from CURRENT state, keyed by deadline
# ---------------------------------------------------------------------------


def scan_reminders(
    conn: sqlite3.Connection, *, room: sqlite3.Row, state: dict, now_real: float
) -> int:
    """Last-active-hour / 15-minute / turn-expiry reminders for one room.

    Only while the room is running, unpaused and inside its active window —
    so nothing is generated overnight and a morning never replays an
    obsolete "ending soon".  Keys carry the deadline, so an extension makes
    the old reminder unmatchable (the dispatcher's recheck drops it) and the
    new deadline may earn one more — bounded by ``MAX_LAST_HOUR_PER_LOT``.
    """
    if state["status"] not in ("running", "draining") or state["paused"]:
        return 0
    offset = float(room["clock_offset"]) if room["room_type"] == "mock" else 0.0
    room_now = now_real + offset
    win = window_of(state["rules"])
    if not schedule.is_active(win, room_now):
        return 0
    users = _seat_users(conn, room["id"])
    watchers: dict[str, set[int]] = {}
    for w in conn.execute(
        "SELECT w.user_id, w.auction_id FROM notif_watch w JOIN members m ON m.room_id = w.room_id"
        " AND m.user_id = w.user_id AND m.removed_at IS NULL WHERE w.room_id=?",
        (room["id"],),
    ):
        watchers.setdefault(w["auction_id"], set()).add(int(w["user_id"]))
    made = 0
    for a in engine.open_auctions(state):
        rem = schedule.active_between(win, room_now, a["deadline"])
        involved_seats = set(a["bids"].keys()) | {a["nominator"]}
        uids = {users[s]: s for s in involved_seats if s in users}
        for uid in watchers.get(a["id"], set()):
            uids.setdefault(uid, next((s for s, u in users.items() if u == uid), None))
        for ntype, limit in (("last_hour", 3600), ("fifteen_min", 900)):
            if rem > limit:
                continue
            for uid, seat in uids.items():
                if ntype == "last_hour":
                    n = conn.execute(
                        "SELECT COUNT(*) FROM notif_inbox WHERE room_id=? AND user_id=? AND type='last_hour' AND logical_key LIKE ?",
                        (room["id"], uid, f"lasthour:{a['id']}:%"),
                    ).fetchone()[0]
                    if n >= MAX_LAST_HOUR_PER_LOT:
                        continue
                key = f"{'lasthour' if ntype == 'last_hour' else 'fifteen'}:{a['id']}:{int(a['deadline'])}"
                if enqueue(
                    conn,
                    room_id=room["id"],
                    room_type=room["room_type"],
                    state=state,
                    user_id=uid,
                    seat_id=seat,
                    ntype=ntype,
                    logical_key=key,
                    data={
                        "auction": a["id"],
                        "deadline": a["deadline"],
                        "price": a["price"],
                        "leading": a["leader"] == seat,
                    },
                    room_now=room_now,
                    offset=offset,
                    now_real=now_real,
                ):
                    made += 1
    # Optional daily summaries (off by default): 08:00-08:30 and 20:45-21:00 ET,
    # one per person per slot per day, built from the seat's OWN view only.
    local = datetime.fromtimestamp(room_now, NY)
    minute = local.hour * 60 + local.minute
    slot = (
        "am"
        if 8 * 60 <= minute < 8 * 60 + 30
        else "pm"
        if 20 * 60 + 45 <= minute < 21 * 60
        else None
    )
    if slot:
        for seat, uid in users.items():
            mine = [a for a in engine.open_auctions(state) if seat in a["bids"]]
            view = engine.seat_private_view(state, seat, room_now)
            right = view.get("on_clock")
            if enqueue(
                conn,
                room_id=room["id"],
                room_type=room["room_type"],
                state=state,
                user_id=uid,
                seat_id=seat,
                ntype="daily_summary",
                logical_key=f"summary:{local.date().isoformat()}:{slot}",
                data={
                    "slot": slot,
                    "leading": sum(1 for a in mine if a["leader"] == seat),
                    "outbid": sum(1 for a in mine if a["leader"] != seat),
                    "committed": view["committed"],
                    "spendable": view["spendable"],
                    "on_clock": bool(right),
                },
                room_now=room_now,
                offset=offset,
                now_real=now_real,
            ):
                made += 1
    for r in engine._window_rights(state):
        if r["window_at"] is None or r["deadline"] is None or r["seat"] not in users:
            continue
        if schedule.active_between(win, room_now, r["deadline"]) > 3600:
            continue
        if enqueue(
            conn,
            room_id=room["id"],
            room_type=room["room_type"],
            state=state,
            user_id=users[r["seat"]],
            seat_id=r["seat"],
            ntype="turn_expiring",
            logical_key=f"turnexp:{r['id']}:{int(r['deadline'])}",
            data={"right": r["id"], "deadline": r["deadline"]},
            room_now=room_now,
            offset=offset,
            now_real=now_real,
        ):
            made += 1
    return made


# ---------------------------------------------------------------------------
# Relevance — re-checked against the CURRENT room right before sending
# ---------------------------------------------------------------------------


def still_relevant(
    ntype: str, data: dict, state: dict | None, seat: str | None, member_seat: str | None
) -> bool:
    if ntype == "test":
        return True
    if state is None:
        return False
    if seat is not None and member_seat != seat:
        return False  # seat reassigned since the event
    auctions = state.get("auctions", {})
    a = auctions.get(data.get("auction")) if data.get("auction") else None
    if ntype == "your_turn":
        return (
            any(
                r["id"] == data.get("right") and r["window_at"] is not None
                for r in engine._window_rights(state)
            )
            and not state["paused"]
        )
    if ntype == "turn_expiring":
        r = next((r for r in state["rights"] if r["id"] == data.get("right")), None)
        return (
            bool(r)
            and r["status"] == "pending"
            and r["deadline"] == data.get("deadline")
            and not state["paused"]
        )
    if ntype == "outbid":
        return bool(a) and a["status"] == "open" and a["leader"] != seat
    if ntype in ("leading_again", "proxy_leading"):
        return bool(a) and a["status"] == "open" and a["leader"] == seat
    if ntype == "deadline_extended":
        return bool(a) and a["status"] == "open" and a["deadline"] == data.get("deadline")
    if ntype in ("last_hour", "fifteen_min"):
        return (
            bool(a)
            and a["status"] == "open"
            and a["deadline"] == data.get("deadline")
            and not state["paused"]
        )
    if ntype == "new_nomination":
        return bool(a) and a["status"] == "open"
    return True  # won, purchases, budget, commissioner, room status: historical facts


# ---------------------------------------------------------------------------
# Delivery worker
# ---------------------------------------------------------------------------


def _backoff(attempts: int, retry_after: int | None) -> float:
    if retry_after is not None:
        return float(min(max(retry_after, 1), 3600))
    return float(min(30 * (2 ** max(0, attempts - 1)), 1800))


def claim_due(store, now_real: float, limit: int = 25) -> list[dict]:
    with store.write() as conn:
        conn.execute(
            "UPDATE notif_outbox SET status='expired_ttl' WHERE status='pending' AND expires_at <= ?",
            (now_real,),
        )
        # Rows stuck mid-send (process died after claiming) become due again:
        # at-least-once, deduplicated on the phone by the notification tag.
        conn.execute(
            "UPDATE notif_outbox SET status='pending' WHERE status='sending' AND claimed_at < ?",
            (now_real - 120,),
        )
        rows = conn.execute(
            "SELECT o.*, i.room_id, i.seat_id, i.type, i.title, i.body, i.url, i.data_json, i.logical_key, i.is_mock, i.room_now"
            " FROM notif_outbox o JOIN notif_inbox i ON i.id = o.inbox_id"
            " WHERE o.status='pending' AND o.next_attempt_at <= ? ORDER BY o.next_attempt_at, o.id LIMIT ?",
            (now_real, limit),
        ).fetchall()
        for r in rows:
            conn.execute(
                "UPDATE notif_outbox SET status='sending', claimed_at=?, attempts=attempts+1 WHERE id=?",
                (now_real, r["id"]),
            )
    return [dict(r) for r in rows]


def _finish(store, outbox_id: int, **fields) -> None:
    cols = ", ".join(f"{k}=?" for k in fields)
    with store.write() as conn:
        conn.execute(f"UPDATE notif_outbox SET {cols} WHERE id=?", (*fields.values(), outbox_id))


def _payload(row: dict, prefs: dict) -> dict:
    title, body = row["title"], row["body"]
    if prefs.get("generic_previews"):
        title = "[MOCK] Chase Upside auction" if row["is_mock"] else "Chase Upside auction"
        body = "New activity in your auction room. Open to view."
    return {
        "title": title,
        "body": body,
        "url": row["url"],
        "tag": hashlib.sha256(row["logical_key"].encode()).hexdigest()[:24],
        "ts": int(row["room_now"] * 1000),
    }


def _send_email(to: str, subject: str, body: str) -> tuple[bool, str | None]:
    srv = sys.modules.get("server") or sys.modules.get("__main__")
    fn = getattr(srv, "_deliver_email_smtp", None)
    if fn is None:
        return False, "email_not_configured"
    try:
        result = fn(to, subject, body)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}"
    ok = result if isinstance(result, bool) else bool(result is None or result)
    return ok, None if ok else "smtp_failed"


def email_quota_ok(conn: sqlite3.Connection, kind: str, now_real: float) -> bool:
    used = conn.execute(
        "SELECT COUNT(*) FROM notif_email_log WHERE sent_at > ?", (now_real - 86400,)
    ).fetchone()[0]
    cap = EMAIL_DAILY_CAP if kind == "recovery" else EMAIL_DAILY_CAP - EMAIL_RECOVERY_RESERVE
    return used < cap


def dispatch_once(store, now_real: float, *, sender=None, email_sender=None) -> dict:
    """Send what is due.  ``sender``/``email_sender`` are injectable so mocks
    and tests use a fake transport."""
    from src.api import push_delivery

    sender = sender or push_delivery.send_push_detailed
    email_sender = email_sender or _send_email
    stats = {"sent": 0, "stale": 0, "failed": 0, "gone": 0, "retry": 0, "suppressed": 0}
    rows = claim_due(store, now_real)
    states: dict[str, dict | None] = {}
    for row in rows:
        try:
            with store.read() as conn:
                prefs = get_prefs(conn, row["user_id"])
                member = None
                is_member = True
                if row["room_id"]:
                    m = conn.execute(
                        "SELECT seat_id FROM members WHERE room_id=? AND user_id=? AND removed_at IS NULL",
                        (row["room_id"], row["user_id"]),
                    ).fetchone()
                    member = m["seat_id"] if m else None
                    # A removed member gets nothing more from this room — not even
                    # public-fact reminders for lots they once watched.
                    is_member = m is not None
                    if row["room_id"] not in states:
                        rr = conn.execute(
                            "SELECT state_json FROM rooms WHERE id=?", (row["room_id"],)
                        ).fetchone()
                        states[row["room_id"]] = json.loads(rr["state_json"]) if rr else None
                device = (
                    conn.execute(
                        "SELECT * FROM notif_devices WHERE id=?", (row["device_id"],)
                    ).fetchone()
                    if row["device_id"]
                    else None
                )
                live_ids = {d["id"] for d in _live_devices(conn, row["user_id"], now_real)}
                if row["is_mock"]:
                    recent = conn.execute(
                        "SELECT COUNT(*) FROM notif_outbox o JOIN notif_inbox i ON i.id=o.inbox_id WHERE o.user_id=?"
                        " AND i.is_mock=1 AND o.status='sent' AND o.sent_at > ?",
                        (row["user_id"], now_real - 3600),
                    ).fetchone()[0]
                else:
                    recent = 0
            data = json.loads(row["data_json"])
            if row["room_id"] and not is_member:
                _finish(store, row["id"], status="stale")
                stats["stale"] += 1
                continue
            if row["room_id"] and not still_relevant(
                row["type"], data, states.get(row["room_id"]), row["seat_id"], member
            ):
                _finish(store, row["id"], status="stale")
                stats["stale"] += 1
                continue
            if row["is_mock"] and (not prefs.get("mock_push") or recent >= MOCK_PUSH_PER_HOUR):
                _finish(store, row["id"], status="suppressed_mock")
                stats["suppressed"] += 1
                continue
            if row["channel"] == "push":
                if device is None or row["device_id"] not in live_ids:
                    _finish(store, row["id"], status="device_inactive")
                    stats["suppressed"] += 1
                    continue
                sub = {
                    "endpoint": device["endpoint"],
                    "keys": {"p256dh": device["p256dh"], "auth": device["auth"]},
                }
                ttl = max(0, int(row["expires_at"] - now_real))
                res = sender(
                    sub,
                    _payload(row, prefs),
                    ttl=ttl,
                    urgency=URGENCY.get(row["type"], "normal"),
                    topic=None,
                )
                if res.get("ok"):
                    _finish(
                        store,
                        row["id"],
                        status="sent",
                        sent_at=now_real,
                        provider_status=res.get("status"),
                        last_error=None,
                    )
                    with store.write() as conn:
                        conn.execute(
                            "UPDATE notif_devices SET last_ok_at=?, last_status='accepted', failures=0 WHERE id=?",
                            (now_real, device["id"]),
                        )
                    stats["sent"] += 1
                elif res.get("gone"):
                    _finish(
                        store,
                        row["id"],
                        status="gone",
                        provider_status=res.get("status"),
                        last_error=res.get("error"),
                    )
                    with store.write() as conn:
                        conn.execute(
                            "UPDATE notif_devices SET disabled_at=?, disabled_reason='expired_subscription', last_status='gone' WHERE id=?",
                            (now_real, device["id"]),
                        )
                    stats["gone"] += 1
                else:
                    _retry_or_fail(store, row, res, now_real, stats)
            else:
                with store.read() as conn:
                    em = conn.execute(
                        "SELECT email, verified_at FROM notif_email WHERE user_id=?",
                        (row["user_id"],),
                    ).fetchone()
                    quota = email_quota_ok(conn, "notification", now_real)
                if not em or not em["verified_at"] or not prefs.get("email_backup"):
                    _finish(store, row["id"], status="suppressed_email")
                    stats["suppressed"] += 1
                    continue
                if not quota:
                    _finish(store, row["id"], status="quota_exhausted")
                    stats["suppressed"] += 1
                    continue
                p = _payload(row, prefs)
                ok, err = email_sender(em["email"], p["title"], f"{p['body']}\n\nOpen: {p['url']}")
                if ok:
                    with store.write() as conn:
                        conn.execute(
                            "INSERT INTO notif_email_log (user_id, kind, sent_at) VALUES (?,?,?)",
                            (row["user_id"], "notification", now_real),
                        )
                    _finish(store, row["id"], status="sent", sent_at=now_real, last_error=None)
                    stats["sent"] += 1
                else:
                    _retry_or_fail(store, row, {"error": err}, now_real, stats)
        except Exception as exc:  # noqa: BLE001 - one bad row never blocks the batch
            # Without this boundary one row whose send raises aborts the batch
            # after claim_due marked every row 'sending', and it sorts first
            # again on reclaim: everyone else's alerts wait on it until TTL.
            log.exception("auction notification %s failed to dispatch", row["id"])
            _retry_or_fail(store, row, {"error": repr(exc)}, now_real, stats)
    return stats


def _retry_or_fail(store, row: dict, res: dict, now_real: float, stats: dict) -> None:
    attempts = int(row["attempts"]) + 1
    nxt = now_real + _backoff(attempts, res.get("retry_after"))
    if attempts >= MAX_ATTEMPTS or nxt >= row["expires_at"]:
        _finish(
            store,
            row["id"],
            status="failed",
            provider_status=res.get("status"),
            last_error=str(res.get("error"))[:300],
        )
        stats["failed"] += 1
    else:
        _finish(
            store,
            row["id"],
            status="pending",
            next_attempt_at=nxt,
            provider_status=res.get("status"),
            last_error=str(res.get("error"))[:300],
        )
        stats["retry"] += 1


# ---------------------------------------------------------------------------
# Test notifications, inbox, email verification
# ---------------------------------------------------------------------------


def queue_test(store, *, user_id: int, device_id: int | None, now_real: float) -> list[int]:
    key = f"test:{secrets.token_hex(6)}"
    with store.write() as conn:
        live = _live_devices(conn, user_id, now_real)
        targets = [d for d in live if device_id is None or d["id"] == device_id]
        if not targets:
            raise AuctionError(
                "no_device", "no active device is registered for notifications on this account", 409
            )
        title, body = compose(
            "test", {"name": "", "auctions": {}, "pool": {"players": {}}}, {}, now_real
        )
        cur = conn.execute(
            "INSERT INTO notif_inbox (room_id, user_id, seat_id, logical_key, type, title, body, url, data_json, room_now, created_at, is_mock)"
            " VALUES ('',?,NULL,?,'test',?,?,'/auction/notifications','{}',?,?,0)",
            (user_id, key, title, body, now_real, now_real),
        )
        inbox_id = cur.lastrowid
        ids = []
        for d in targets:
            c = conn.execute(
                "INSERT INTO notif_outbox (inbox_id, user_id, channel, device_id, status, next_attempt_at, expires_at, created_at)"
                " VALUES (?,?,?,?,'pending',?,?,?)",
                (
                    inbox_id,
                    user_id,
                    "push",
                    d["id"],
                    now_real,
                    now_real + TTL_SECONDS["test"],
                    now_real,
                ),
            )
            ids.append(int(c.lastrowid))
    return ids


def inbox(
    conn: sqlite3.Connection, user_id: int, *, room_id: str | None = None, limit: int = 100
) -> list[dict]:
    if room_id is None:
        rows = conn.execute(
            "SELECT id, room_id, type, title, body, url, room_now, created_at, read_at, is_mock FROM notif_inbox"
            " WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, room_id, type, title, body, url, room_now, created_at, read_at, is_mock FROM notif_inbox"
            " WHERE user_id=? AND room_id=? ORDER BY id DESC LIMIT ?",
            (user_id, room_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def delivery_status(conn: sqlite3.Connection, user_id: int, limit: int = 30) -> list[dict]:
    rows = conn.execute(
        "SELECT o.id, o.channel, o.device_id, o.status, o.attempts, o.provider_status, o.sent_at, o.created_at, i.type, i.title"
        " FROM notif_outbox o JOIN notif_inbox i ON i.id=o.inbox_id WHERE o.user_id=? ORDER BY o.id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def start_email_verification(
    conn: sqlite3.Connection, user_id: int, email: str, now_real: float
) -> str:
    email = str(email or "").strip()
    if not re.match(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}$", email):
        raise AuctionError("bad_email", "enter a valid email address")
    if not email_quota_ok(conn, "recovery", now_real):
        raise AuctionError(
            "email_quota", "today's email allowance is used up — try again tomorrow", 429
        )
    token = secrets.token_urlsafe(24)
    th = hashlib.sha256(token.encode()).hexdigest()
    conn.execute(
        "INSERT INTO notif_email (user_id, email, verified_at, token_hash, token_expires, created_at) VALUES (?,?,NULL,?,?,?)"
        " ON CONFLICT(user_id) DO UPDATE SET email=excluded.email, verified_at=NULL, token_hash=excluded.token_hash,"
        " token_expires=excluded.token_expires",
        (user_id, email, th, now_real + 86400, now_real),
    )
    # Changing the address turns email backup off until the new one is verified.
    prefs = get_prefs(conn, user_id)
    if prefs.get("email_backup"):
        prefs["email_backup"] = False
        conn.execute(
            "UPDATE notif_prefs SET prefs_json=?, updated_at=? WHERE user_id=?",
            (json.dumps(prefs, sort_keys=True), now_real, user_id),
        )
    conn.execute(
        "INSERT INTO notif_email_log (user_id, kind, sent_at) VALUES (?,?,?)",
        (user_id, "verification", now_real),
    )
    return token


def verify_email(conn: sqlite3.Connection, user_id: int, token: str, now_real: float) -> bool:
    th = hashlib.sha256(str(token).encode()).hexdigest()
    row = conn.execute(
        "SELECT token_hash, token_expires FROM notif_email WHERE user_id=?", (user_id,)
    ).fetchone()
    if not row or row["token_hash"] != th or (row["token_expires"] or 0) <= now_real:
        return False
    conn.execute(
        "UPDATE notif_email SET verified_at=?, token_hash=NULL WHERE user_id=?", (now_real, user_id)
    )
    return True


def iter_active_rooms(conn: sqlite3.Connection) -> Iterable[sqlite3.Row]:
    return conn.execute(
        "SELECT id, room_type, clock_offset, state_json FROM rooms WHERE archived_at IS NULL AND status IN ('running','draining')"
    ).fetchall()


def run_reminder_scan(store, now_real: float) -> int:
    made = 0
    with store.write() as conn:
        for room in iter_active_rooms(conn):
            try:
                made += scan_reminders(
                    conn, room=room, state=json.loads(room["state_json"]), now_real=now_real
                )
            except Exception as exc:  # noqa: BLE001 - one bad room must not stop the rest
                log.exception("auction reminder scan failed for %s: %s", room["id"], exc)
    return made


def _now() -> float:
    return time.time()
