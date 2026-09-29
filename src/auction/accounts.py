"""Auction-room identity: accounts, sessions, invites, seat membership.

Why a scoped identity layer instead of the site login
----------------------------------------------------
The site's login (``server.py``) is one env-configured owner account compared
in plaintext plus shared guest passes that all authenticate as the literal
``"guest"``; non-allowlisted sessions are dropped on restart.  Twelve
separately-accountable bidders cannot be built on that without rewriting the
site's auth owner, which is out of scope here and actively shared with other
work.  So the room owns a narrow identity layer, and it BRIDGES from the site
owner (an authenticated site-admin session can mint its own auction session)
rather than duplicating the site's gate.

Rules:

* A manager's Sleeper username is a recognisable HANDLE — never a password,
  never proof of ownership, never permission to claim a franchise.  We never
  ask for, store, or check a Sleeper password.
* Chase Upside passwords are hashed with ``hashlib.scrypt`` (memory-hard,
  per-user random salt, parameters stored in the hash string).
* A seat is bound only through a commissioner-issued, expiring, single-use
  invite whose token is stored hashed.  Knowing someone's public username
  gains nothing.
* Sessions: 256-bit random token in an HttpOnly cookie; only its SHA-256 is
  stored; absolute expiry; revocable per user.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import sqlite3
from dataclasses import dataclass

from src.auction.engine import AuctionError
from src.auction.store import Store

SESSION_TTL_SECONDS = 30 * 86400
INVITE_TTL_SECONDS_DEFAULT = 7 * 86400
MIN_PASSWORD_LEN = 10
MAX_PASSWORD_LEN = 256
_HANDLE_RE = re.compile(r"^[A-Za-z0-9_.\-]{2,40}$")

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_DUMMY_HASH: str | None = None


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N,
        _SCRYPT_R,
        _SCRYPT_P,
        base64.b64encode(salt).decode(),
        base64.b64encode(dk).decode(),
    )


def verify_password(password: str, stored: str | None) -> bool:
    global _DUMMY_HASH
    if not stored:
        # Spend the same work for an unknown user (enumeration resistance).
        if _DUMMY_HASH is None:
            _DUMMY_HASH = hash_password(secrets.token_hex(8))
        stored = _DUMMY_HASH
        verify_password(password, stored)
        return False
    try:
        algo, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=32,
        )
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def validate_password(password: object) -> str:
    if not isinstance(password, str) or not (MIN_PASSWORD_LEN <= len(password) <= MAX_PASSWORD_LEN):
        raise AuctionError(
            "weak_password", f"password must be {MIN_PASSWORD_LEN}-{MAX_PASSWORD_LEN} characters"
        )
    return password


def validate_handle(handle: object) -> str:
    if not isinstance(handle, str) or not _HANDLE_RE.match(handle.strip()):
        raise AuctionError(
            "bad_handle", "handle must be 2-40 letters, digits, dot, dash or underscore"
        )
    return handle.strip()


@dataclass(frozen=True)
class User:
    id: int
    handle: str
    display_name: str
    sleeper_user_id: str | None
    is_site_admin: bool

    def public(self) -> dict:
        return {
            "id": self.id,
            "handle": self.handle,
            "displayName": self.display_name,
            "isSiteAdmin": self.is_site_admin,
        }


def _user_from_row(row: sqlite3.Row) -> User:
    return User(
        id=int(row["id"]),
        handle=row["handle"],
        display_name=row["display_name"],
        sleeper_user_id=row["sleeper_user_id"],
        is_site_admin=bool(row["is_site_admin"]),
    )


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


def issue_session(store: Store, user_id: int, now: float) -> str:
    token = secrets.token_urlsafe(32)
    with store.write() as conn:
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, last_seen_at) VALUES (?,?,?,?,?)",
            (_token_hash(token), user_id, now, now + SESSION_TTL_SECONDS, now),
        )
    return token


def session_user(store: Store, token: str | None, now: float) -> User | None:
    if not token or len(token) > 200:
        return None
    with store.read() as conn:
        row = conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?"
            " AND s.revoked_at IS NULL AND s.expires_at > ? AND u.disabled_at IS NULL",
            (_token_hash(token), now),
        ).fetchone()
    return _user_from_row(row) if row else None


def revoke_session(store: Store, token: str | None, now: float) -> None:
    if not token:
        return
    with store.write() as conn:
        conn.execute(
            "UPDATE sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
            (now, _token_hash(token)),
        )


def revoke_all_sessions(
    store: Store, user_id: int, now: float, *, except_token: str | None = None
) -> None:
    with store.write() as conn:
        if except_token:
            conn.execute(
                "UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL AND token_hash != ?",
                (now, user_id, _token_hash(except_token)),
            )
        else:
            conn.execute(
                "UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                (now, user_id),
            )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def authenticate(store: Store, handle: str, password: str) -> User | None:
    with store.read() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE handle=? AND disabled_at IS NULL", (str(handle).strip(),)
        ).fetchone()
    if row is None:
        verify_password(password, None)
        return None
    if not verify_password(password, row["pw_hash"]):
        return None
    return _user_from_row(row)


def get_or_create_site_owner(
    store: Store, *, site_username: str, display_name: str, now: float
) -> User:
    """The bridge from an authenticated SITE admin session.  No password is
    set; this account signs in only through the site owner's session."""
    site_username = site_username.strip().lower()
    with store.write() as conn:
        row = conn.execute("SELECT * FROM users WHERE site_username=?", (site_username,)).fetchone()
        if row is None:
            handle = site_username
            if conn.execute("SELECT 1 FROM users WHERE handle=?", (handle,)).fetchone():
                handle = f"{site_username}-owner"
            conn.execute(
                "INSERT INTO users (handle, display_name, site_username, is_site_admin, created_at) VALUES (?,?,?,1,?)",
                (handle, display_name or site_username, site_username, now),
            )
            store.audit(
                conn,
                now_real=now,
                user_id=None,
                room_id=None,
                action="site_owner_linked",
                detail={"site_username": site_username},
            )
            row = conn.execute(
                "SELECT * FROM users WHERE site_username=?", (site_username,)
            ).fetchone()
    return _user_from_row(row)


def set_password(store: Store, user_id: int, new_password: str, now: float) -> None:
    validate_password(new_password)
    with store.write() as conn:
        conn.execute(
            "UPDATE users SET pw_hash=?, pw_changed_at=? WHERE id=?",
            (hash_password(new_password), now, user_id),
        )
        store.audit(
            conn, now_real=now, user_id=user_id, room_id=None, action="password_changed", detail={}
        )


def change_password(store: Store, user: User, current: str, new_password: str, now: float) -> None:
    with store.read() as conn:
        row = conn.execute("SELECT pw_hash FROM users WHERE id=?", (user.id,)).fetchone()
    if row["pw_hash"] and not verify_password(current, row["pw_hash"]):
        raise AuctionError("bad_credentials", "current password is incorrect", 403)
    set_password(store, user.id, new_password, now)


# ---------------------------------------------------------------------------
# Membership + invites
# ---------------------------------------------------------------------------


def membership(store: Store, room_id: str, user_id: int) -> dict | None:
    with store.read() as conn:
        row = conn.execute(
            "SELECT role, seat_id FROM members WHERE room_id=? AND user_id=? AND removed_at IS NULL",
            (room_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def add_member(
    store: Store,
    conn: sqlite3.Connection,
    *,
    room_id: str,
    user_id: int,
    role: str,
    seat_id: str | None,
    now: float,
) -> None:
    if role not in ("commissioner", "manager", "observer"):
        raise AuctionError("bad_role", "unknown role")
    if role == "observer" and seat_id is not None:
        # An observer never holds a seat: a seat carries that seat's private
        # maxima, and only its own manager may read them.
        raise AuctionError("bad_role", "observers cannot hold a seat")
    if seat_id is not None:
        taken = conn.execute(
            "SELECT user_id FROM members WHERE room_id=? AND seat_id=? AND removed_at IS NULL",
            (room_id, seat_id),
        ).fetchone()
        if taken and int(taken["user_id"]) != user_id:
            raise AuctionError("seat_taken", "that seat already has a manager", 409)
    existing = conn.execute(
        "SELECT role, seat_id, removed_at FROM members WHERE room_id=? AND user_id=?",
        (room_id, user_id),
    ).fetchone()
    if existing and existing["removed_at"] is None:
        # A current member can never be moved onto another seat by claiming an
        # invite — that is how a commissioner (or a manager opening a leaked
        # link) would silently start acting for someone else's seat.
        raise AuctionError(
            "already_member",
            "you already belong to this room; an invitation is for someone new",
            409,
        )
    if existing:
        # A previously REMOVED member rejoining through a fresh invitation.
        conn.execute(
            "UPDATE members SET role=?, seat_id=?, removed_at=NULL WHERE room_id=? AND user_id=?",
            (role, seat_id, room_id, user_id),
        )
    else:
        conn.execute(
            "INSERT INTO members (room_id, user_id, role, seat_id, created_at) VALUES (?,?,?,?,?)",
            (room_id, user_id, role, seat_id, now),
        )
    store.audit(
        conn,
        now_real=now,
        user_id=user_id,
        room_id=room_id,
        action="member_added",
        detail={"role": role, "seat": seat_id},
    )


def create_invite(
    store: Store,
    *,
    room_id: str,
    seat_id: str | None,
    role: str,
    created_by: int,
    now: float,
    intended_handle: str | None = None,
    intended_sleeper_user_id: str | None = None,
    ttl_seconds: int = INVITE_TTL_SECONDS_DEFAULT,
) -> str:
    if role not in ("manager", "observer"):
        raise AuctionError("bad_role", "invites are for managers or observers")
    if role == "manager" and not seat_id:
        raise AuctionError("seat_required", "a manager invite must name a seat")
    if role == "observer" and seat_id:
        raise AuctionError("bad_role", "observers cannot hold a seat")
    ttl_seconds = max(3600, min(int(ttl_seconds), 30 * 86400))
    token = secrets.token_urlsafe(32)
    with store.write() as conn:
        if seat_id:
            # One live invite per seat: issuing a new one revokes the old.
            conn.execute(
                "UPDATE invites SET revoked_at=? WHERE room_id=? AND seat_id=? AND used_at IS NULL AND revoked_at IS NULL",
                (now, room_id, seat_id),
            )
        conn.execute(
            "INSERT INTO invites (token_hash, room_id, seat_id, role, intended_handle, intended_sleeper_user_id,"
            " created_by, created_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                _token_hash(token),
                room_id,
                seat_id,
                role,
                intended_handle,
                intended_sleeper_user_id,
                created_by,
                now,
                now + ttl_seconds,
            ),
        )
        store.audit(
            conn,
            now_real=now,
            user_id=created_by,
            room_id=room_id,
            action="invite_created",
            detail={"seat": seat_id, "role": role},
        )
    return token


def peek_invite(store: Store, token: str, now: float) -> dict:
    with store.read() as conn:
        row = conn.execute(
            "SELECT * FROM invites WHERE token_hash=?", (_token_hash(str(token)),)
        ).fetchone()
    if row is None or row["revoked_at"] or row["used_at"] or row["expires_at"] <= now:
        # One indistinguishable answer for missing / used / revoked / expired.
        raise AuctionError("invite_invalid", "this invitation is not valid", 404)
    return dict(row)


def claim_invite(
    store: Store,
    token: str,
    *,
    now: float,
    existing_user: User | None,
    handle: str | None,
    password: str | None,
    display_name: str | None,
) -> User:
    th = _token_hash(str(token))
    with store.write() as conn:
        inv = conn.execute("SELECT * FROM invites WHERE token_hash=?", (th,)).fetchone()
        if inv is None or inv["revoked_at"] or inv["used_at"] or inv["expires_at"] <= now:
            raise AuctionError("invite_invalid", "this invitation is not valid", 404)
        if existing_user is not None:
            user_id = existing_user.id
            if (
                inv["intended_handle"]
                and existing_user.handle.lower() != str(inv["intended_handle"]).lower()
            ):
                raise AuctionError(
                    "invite_mismatch", "this invitation was issued to a different account", 403
                )
        else:
            h = validate_handle(handle)
            pw = validate_password(password)
            if inv["intended_handle"] and h.lower() != str(inv["intended_handle"]).lower():
                raise AuctionError(
                    "invite_mismatch", "use the handle this invitation was issued for", 403
                )
            if conn.execute("SELECT 1 FROM users WHERE handle=?", (h,)).fetchone():
                raise AuctionError(
                    "handle_taken",
                    "that handle is taken — sign in first, then open the invite",
                    409,
                )
            conn.execute(
                "INSERT INTO users (handle, display_name, sleeper_user_id, pw_hash, created_at, pw_changed_at)"
                " VALUES (?,?,?,?,?,?)",
                (
                    h,
                    str(display_name or h)[:60],
                    None,  # Sleeper identity is not verifiable here; the SEAT carries it
                    hash_password(pw),
                    now,
                    now,
                ),
            )
            user_id = int(
                conn.execute("SELECT id FROM users WHERE handle=?", (h,)).fetchone()["id"]
            )
        add_member(
            store,
            conn,
            room_id=inv["room_id"],
            user_id=user_id,
            role=inv["role"],
            seat_id=inv["seat_id"],
            now=now,
        )
        conn.execute(
            "UPDATE invites SET used_at=?, used_by=? WHERE token_hash=?", (now, user_id, th)
        )
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return _user_from_row(row)


def room_members(store: Store, room_id: str) -> list[dict]:
    with store.read() as conn:
        rows = conn.execute(
            "SELECT m.user_id, m.role, m.seat_id, u.handle, u.display_name FROM members m JOIN users u ON u.id=m.user_id"
            " WHERE m.room_id=? AND m.removed_at IS NULL",
            (room_id,),
        ).fetchall()
        invites = conn.execute(
            "SELECT seat_id, role, intended_handle, created_at, expires_at, used_at, revoked_at FROM invites"
            " WHERE room_id=? ORDER BY created_at DESC",
            (room_id,),
        ).fetchall()
    return [dict(r) for r in rows], [dict(i) for i in invites]
