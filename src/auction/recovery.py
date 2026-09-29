"""Account recovery, seat replacement, preflight and nomination-order preview.

Commissioner tools with explicit trust boundaries:

* A password-reset link is single-use, expires in 24 h, stored hashed, and
  shown once to the commissioner who hands it over privately.  Using it
  revokes every session of that account (which silences its devices).  The
  commissioner COULD use the link themselves — that is an inherent property
  of a commissioner-issued reset — so every issue and use is audited and the
  account's inbox records "a reset link was issued", which the member sees.
* Removing a member from a seat (lost account, wrong person) is audited with
  a reason; the seat's money, bids and purchases belong to the SEAT, not the
  person, and stay exactly as they are.  A new invite then binds the seat.
* Preflight reports readiness; it decides nothing.
* The points-for order preview states which season it read and whether that
  season is final.  Ties are flagged, never broken silently.  Applying an
  order is a separate, commissioner-only ``set_order`` command.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from typing import Any

from src.auction import accounts, engine
from src.auction.engine import AuctionError
from src.auction.rules import unconfirmed_rules
from src.auction.store import Store

RESET_TTL_SECONDS = 24 * 3600

SCHEMA = """
CREATE TABLE IF NOT EXISTS password_resets (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    room_id TEXT,
    created_by INTEGER NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    used_at REAL
);
"""


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def _h(token: str) -> str:
    return hashlib.sha256(str(token).encode()).hexdigest()


def issue_reset(
    store: Store, *, room_id: str, member_user_id: int, commissioner_id: int, now: float
) -> str:
    with store.write() as conn:
        m = conn.execute(
            "SELECT role FROM members WHERE room_id=? AND user_id=? AND removed_at IS NULL",
            (room_id, member_user_id),
        ).fetchone()
        if m is None:
            raise AuctionError("not_member", "that person is not a member of this room", 404)
        u = conn.execute("SELECT site_username FROM users WHERE id=?", (member_user_id,)).fetchone()
        if u and u["site_username"]:
            raise AuctionError(
                "site_account",
                "the site owner's account signs in through the site, not a password",
                409,
            )
        token = secrets.token_urlsafe(32)
        # One live link per account.
        conn.execute(
            "UPDATE password_resets SET used_at=? WHERE user_id=? AND used_at IS NULL",
            (now, member_user_id),
        )
        conn.execute(
            "INSERT INTO password_resets (token_hash, user_id, room_id, created_by, created_at, expires_at) VALUES (?,?,?,?,?,?)",
            (_h(token), member_user_id, room_id, commissioner_id, now, now + RESET_TTL_SECONDS),
        )
        store.audit(
            conn,
            now_real=now,
            user_id=commissioner_id,
            room_id=room_id,
            action="password_reset_issued",
            detail={"member": member_user_id},
        )
        conn.execute(
            "INSERT INTO notif_inbox (room_id, user_id, seat_id, logical_key, type, title, body, url, data_json, room_now, created_at, is_mock)"
            " VALUES (?,?,NULL,?,'account','Password reset link issued',"
            "'Your commissioner issued a one-time password reset link for your account. If you did not ask for it, tell them.',"
            "'/auction','{}',?,?,0)",
            (room_id, member_user_id, f"reset:{int(now)}", now, now),
        )
    return token


def use_reset(store: Store, token: str, new_password: str, now: float) -> accounts.User:
    accounts.validate_password(new_password)
    with store.write() as conn:
        row = conn.execute(
            "SELECT * FROM password_resets WHERE token_hash=?", (_h(token),)
        ).fetchone()
        if row is None or row["used_at"] or row["expires_at"] <= now:
            raise AuctionError("reset_invalid", "this reset link is not valid", 404)
        uid = int(row["user_id"])
        conn.execute("UPDATE password_resets SET used_at=? WHERE token_hash=?", (now, _h(token)))
        conn.execute(
            "UPDATE users SET pw_hash=?, pw_changed_at=? WHERE id=?",
            (accounts.hash_password(new_password), now, uid),
        )
        conn.execute(
            "UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (now, uid)
        )
        store.audit(
            conn,
            now_real=now,
            user_id=uid,
            room_id=row["room_id"],
            action="password_reset_used",
            detail={},
        )
        user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return accounts._user_from_row(user)


def remove_member(
    store: Store,
    *,
    room_id: str,
    member_user_id: int,
    commissioner_id: int,
    reason: str,
    now: float,
) -> dict:
    reason = str(reason or "").strip()
    if not reason:
        raise AuctionError("reason_required", "record why this person is being removed")
    if member_user_id == commissioner_id:
        raise AuctionError("forbidden", "the commissioner cannot remove themselves", 403)
    with store.write() as conn:
        m = conn.execute(
            "SELECT role, seat_id FROM members WHERE room_id=? AND user_id=? AND removed_at IS NULL",
            (room_id, member_user_id),
        ).fetchone()
        if m is None:
            raise AuctionError("not_member", "that person is not a member of this room", 404)
        if m["role"] == "commissioner":
            raise AuctionError("forbidden", "a commissioner cannot be removed here", 403)
        conn.execute(
            "UPDATE members SET removed_at=? WHERE room_id=? AND user_id=?",
            (now, room_id, member_user_id),
        )
        # Any unused invite for that seat is revoked too; a fresh one is issued deliberately.
        if m["seat_id"]:
            conn.execute(
                "UPDATE invites SET revoked_at=? WHERE room_id=? AND seat_id=? AND used_at IS NULL AND revoked_at IS NULL",
                (now, room_id, m["seat_id"]),
            )
        store.audit(
            conn,
            now_real=now,
            user_id=commissioner_id,
            room_id=room_id,
            action="member_removed",
            detail={"member": member_user_id, "seat": m["seat_id"], "reason": reason[:300]},
        )
    return {"seat": m["seat_id"]}


def preflight(store: Store, room_id: str, now_real: float) -> dict:
    """Readiness report for the commissioner.  Reports; decides nothing."""
    from src.api import push_delivery

    state, _, _ = store.load(room_id)
    items: list[dict[str, Any]] = []

    def add(key: str, status: str, text: str) -> None:
        items.append({"key": key, "status": status, "text": text})

    with store.read() as conn:
        members = conn.execute(
            "SELECT seat_id FROM members WHERE room_id=? AND seat_id IS NOT NULL AND removed_at IS NULL",
            (room_id,),
        ).fetchall()
        last_backup = conn.execute(
            "SELECT value FROM meta WHERE key='last_verified_backup'"
        ).fetchone()
    claimed = {m["seat_id"] for m in members}
    human = [s for s in state["seats"] if not s["is_bot"]]
    unclaimed = [s["name"] for s in human if s["id"] not in claimed]
    add(
        "seats",
        "ok" if not unclaimed else "warn",
        "Every human seat is claimed"
        if not unclaimed
        else f"Unclaimed seats: {', '.join(unclaimed)}",
    )
    missing = [s["name"] for s in state["seats"] if s["opening_budget"] is None]
    total = engine.total_opening_pool(state)
    prov = state.get("budget_provenance") or {}
    add(
        "budgets",
        "fail" if missing else "ok",
        f"Missing budgets: {', '.join(missing)}"
        if missing
        else f"Budgets set — total ${total} ({prov.get('source', 'manual')}{', season ' + str(prov.get('season')) if prov.get('season') else ''})",
    )
    if prov.get("totalBudget") and total != prov.get("totalBudget"):
        add(
            "pool_total",
            "warn",
            f"Budgets total ${total}, the draft-capital pool is ${prov.get('totalBudget')} — confirm any adjustment is intended",
        )
    pool = state["pool"]
    add(
        "pool",
        "ok" if pool["is_official_class"] else ("warn" if state["room_type"] == "mock" else "fail"),
        f"Rookie pool {pool['version']}: {pool['label'] or 'approved'} ({len(pool['players'])} players)",
    )
    uc = unconfirmed_rules(state["rules"])
    add(
        "rules",
        "ok" if not uc else ("warn" if state["room_type"] == "mock" else "fail"),
        "All proposed rules confirmed"
        if not uc
        else f"{len(uc)} proposed rule(s) not yet confirmed",
    )
    order_basis = next(
        (
            e
            for e in reversed(store.events_for(room_id, vis={"public"}, limit=500))
            if e["type"] == "order_changed"
        ),
        None,
    )
    add(
        "order",
        "ok" if order_basis else "warn",
        f"Nomination order set ({order_basis['data'].get('basis')})"
        if order_basis
        else "Nomination order is still the default seat order",
    )
    add(
        "push",
        "ok" if push_delivery.is_configured() else "warn",
        "Web Push keys configured"
        if push_delivery.is_configured()
        else "Web Push is not configured on this server (inbox still works)",
    )
    add(
        "backup",
        "ok" if last_backup else "warn",
        f"Last verified backup: {last_backup['value']}"
        if last_backup
        else "No verified backup recorded for the auction store yet",
    )
    add(
        "room_type",
        "ok" if state["room_type"] == "mock" else "warn",
        "Mock room — safe to rehearse"
        if state["room_type"] == "mock"
        else "OFFICIAL room — launch requires the owner's approval",
    )
    worst = (
        "fail"
        if any(i["status"] == "fail" for i in items)
        else "warn"
        if any(i["status"] == "warn" for i in items)
        else "ok"
    )
    return {"status": worst, "items": items, "checkedAt": now_real}


def points_for_preview(league_id: str) -> dict:
    """Lowest points-for first, from Sleeper roster settings.  Read-only."""
    from src.public_league import sleeper_client as sc

    league = sc.fetch_league(league_id) or {}
    rosters = sc.fetch_rosters(league_id)
    rows = []
    for r in rosters:
        st = r.get("settings") or {}
        if st.get("fpts") is None:
            pf = None
        else:
            pf = float(st.get("fpts") or 0) + float(st.get("fpts_decimal") or 0) / 100.0
        rows.append(
            {"roster_id": r.get("roster_id"), "owner_id": r.get("owner_id"), "points_for": pf}
        )
    known = [x for x in rows if x["points_for"] is not None]
    known.sort(key=lambda x: x["points_for"])
    ties = []
    for a, b in zip(known, known[1:]):
        if abs(a["points_for"] - b["points_for"]) < 1e-9:
            ties.append([a["roster_id"], b["roster_id"]])
    status = league.get("status")
    return {
        "season": league.get("season"),
        "leagueStatus": status,
        "final": status == "complete",
        "order": known,
        "missing": [x["roster_id"] for x in rows if x["points_for"] is None],
        "ties": ties,
        "note": (
            "Final season points-for."
            if status == "complete"
            else "PREVIEW ONLY: this season is not complete, so points-for can still change. The owner supplies/confirms the official order."
        ),
    }


def _now() -> float:
    return time.time()


def dumps(o) -> str:
    return json.dumps(o, sort_keys=True)
