"""HTTP surface for the rookie auction room: ``/api/auction/*``.

Authentication is the room's own (``accounts.py``) — this prefix is exempt
from the site's ``_private_api_gate`` and authenticates every request itself,
deny-by-default.  Authorization is re-derived from server-side membership on
EVERY request: the client never supplies an actor, a seat, or a role.

Every mutation:
* requires a same-origin ``Origin`` header (CSRF), plus the SameSite=Strict
  HttpOnly session cookie;
* requires an ``Idempotency-Key``; a retry with the same key returns the
  original outcome, the same key with a different payload is 409;
* is acknowledged only after the store's durable COMMIT.

Live delivery is revision long-poll: ``GET .../view?after=<rev>&wait=25``
returns immediately when the room is past ``after``, otherwise waits (up to
``wait`` seconds) for the next committed revision.  Every response is a full
authorised snapshot, so a reconnect can never skip an event or roll the UI
back (clients drop any response older than the revision they hold).
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from src.auction import accounts, engine, sources
from src.auction.engine import AuctionError
from src.auction.rules import BINDING_OWNER_RULES, PROPOSED_RULE_KEYS, TIMING_PRESETS, default_rules
from src.auction.store import StoreUnavailable, get_store, new_room_id

log = logging.getLogger("auction.api")

router = APIRouter(prefix="/api/auction", tags=["auction"])

COOKIE_NAME = "cu_auction_session"
_IDEM_RE = re.compile(r"^[A-Za-z0-9_\-]{8,100}$")
_MAX_BODY = 64 * 1024


def _flag_enabled() -> bool:
    try:
        from src.api import feature_flags

        return feature_flags.is_enabled("rookie_auction")
    except Exception:  # noqa: BLE001
        return False


def _cookie_secure() -> bool:
    raw = os.getenv("JASON_AUTH_COOKIE_SECURE")
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


def _err(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message})


def _auction_error(exc: AuctionError) -> JSONResponse:
    return _err(exc.code, exc.message, exc.status)


def _gate() -> JSONResponse | None:
    if not _flag_enabled():
        return _err("feature_disabled", "The auction room is switched off.", 503)
    try:
        get_store()
    except StoreUnavailable as exc:
        log.error("auction store unavailable: %s", exc)
        return _err(
            "store_unavailable", "Auction storage is unavailable — nothing can be accepted.", 503
        )
    return None


def _now() -> float:
    return time.time()


def _client_ip(request: Request) -> str:
    return request.headers.get("x-real-ip") or (
        request.client.host if request.client else "unknown"
    )


def _origin_ok(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return False
    allowed = {
        f"https://{request.headers.get('host', '')}",
        f"http://{request.headers.get('host', '')}",
    }
    extra = os.getenv("RISKIT_AUCTION_ALLOWED_ORIGINS", "")
    allowed |= {o.strip().rstrip("/") for o in extra.split(",") if o.strip()}
    return origin.rstrip("/") in allowed


async def _json_body(request: Request) -> dict:
    raw = await request.body()
    if len(raw) > _MAX_BODY:
        raise AuctionError("too_large", "request body too large", 413)
    if not raw:
        return {}
    try:
        body = json.loads(raw)
    except ValueError as exc:
        raise AuctionError("bad_json", "body must be JSON") from exc
    if not isinstance(body, dict):
        raise AuctionError("bad_json", "body must be a JSON object")
    return body


def _user(request: Request) -> accounts.User | None:
    return accounts.session_user(get_store(), request.cookies.get(COOKIE_NAME), _now())


def _require_user(request: Request) -> accounts.User:
    user = _user(request)
    if user is None:
        raise AuctionError("auth_required", "sign in to the auction room", 401)
    return user


def _site_admin_session(request: Request) -> dict | None:
    """The authenticated SITE owner session, or None.  Read through the
    already-imported server module (never imported from here)."""
    srv = sys.modules.get("server") or sys.modules.get("__main__")
    getter = getattr(srv, "_get_auth_session", None)
    allow = getattr(srv, "PRIVATE_APP_ALLOWED_USERNAMES", None)
    if getter is None or not allow:
        return None
    session = getter(request)
    if not session:
        return None
    username = str(session.get("username") or "").strip().lower()
    return session if username in allow else None


def _set_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(
        COOKIE_NAME,
        token,
        max_age=accounts.SESSION_TTL_SECONDS,
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
        path="/",
    )


def _mutation_guard(request: Request) -> JSONResponse | None:
    gate = _gate()
    if gate:
        return gate
    if not _origin_ok(request):
        return _err("bad_origin", "cross-origin request refused", 403)
    return None


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@router.get("/auth/me")
async def auth_me(request: Request):
    gate = _gate()
    if gate:
        return gate
    user = await run_in_threadpool(_user, request)
    site_admin = _site_admin_session(request) is not None
    if user is None:
        return {"user": None, "siteOwnerAvailable": site_admin, "rooms": []}
    rooms = await run_in_threadpool(
        get_store().list_rooms_for_user, user.id, include_all=user.is_site_admin
    )
    return {"user": user.public(), "siteOwnerAvailable": site_admin, "rooms": rooms}


@router.post("/auth/login")
async def auth_login(request: Request):
    guard = _mutation_guard(request)
    if guard:
        return guard
    try:
        body = await _json_body(request)
    except AuctionError as exc:
        return _auction_error(exc)
    handle = str(body.get("handle") or "")[:60]
    password = str(body.get("password") or "")[:300]
    from src.api import rate_limit

    ip = _client_ip(request)
    throttle_key = f"auction:{handle.strip().lower()}"
    blocked, retry = rate_limit.login_throttle_check(ip, throttle_key)
    if blocked:
        return JSONResponse(
            status_code=429,
            content={"error": "rate_limited", "message": "Too many attempts — try again shortly."},
            headers={"Retry-After": str(retry)},
        )
    user = await run_in_threadpool(accounts.authenticate, get_store(), handle, password)
    if user is None:
        rate_limit.login_record_failure(ip, throttle_key)
        return _err("bad_credentials", "Handle or password is incorrect.", 401)
    rate_limit.login_record_success(ip, throttle_key)
    token = await run_in_threadpool(accounts.issue_session, get_store(), user.id, _now())
    resp = JSONResponse({"user": user.public()})
    _set_cookie(resp, token)
    return resp


@router.post("/auth/site-owner")
async def auth_site_owner(request: Request):
    """Bridge: the authenticated site owner gets an auction session."""
    guard = _mutation_guard(request)
    if guard:
        return guard
    session = _site_admin_session(request)
    if session is None:
        return _err("admin_required", "Sign in to Chase Upside as the site owner first.", 403)
    user = await run_in_threadpool(
        accounts.get_or_create_site_owner,
        get_store(),
        site_username=str(session.get("username")),
        display_name=str(session.get("displayName") or session.get("username")),
        now=_now(),
    )
    token = await run_in_threadpool(accounts.issue_session, get_store(), user.id, _now())
    resp = JSONResponse({"user": user.public()})
    _set_cookie(resp, token)
    return resp


@router.post("/auth/logout")
async def auth_logout(request: Request):
    guard = _mutation_guard(request)
    if guard:
        return guard
    await run_in_threadpool(
        accounts.revoke_session, get_store(), request.cookies.get(COOKIE_NAME), _now()
    )
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp


@router.post("/auth/password")
async def auth_password(request: Request):
    guard = _mutation_guard(request)
    if guard:
        return guard
    try:
        user = _require_user(request)
        body = await _json_body(request)
        await run_in_threadpool(
            accounts.change_password,
            get_store(),
            user,
            str(body.get("current") or ""),
            body.get("password"),
            _now(),
        )
        await run_in_threadpool(
            accounts.revoke_all_sessions,
            get_store(),
            user.id,
            _now(),
            except_token=request.cookies.get(COOKIE_NAME),
        )
    except AuctionError as exc:
        return _auction_error(exc)
    return {"ok": True}


@router.get("/invites/peek")
async def invite_peek(request: Request, token: str = ""):
    gate = _gate()
    if gate:
        return gate
    try:
        inv = await run_in_threadpool(accounts.peek_invite, get_store(), token, _now())
        state, _, _ = get_store().load(inv["room_id"])
    except AuctionError as exc:
        return _auction_error(exc)
    seat = next((s for s in state["seats"] if s["id"] == inv["seat_id"]), None)
    return {
        "roomId": inv["room_id"],
        "roomName": state["name"],
        "roomType": state["room_type"],
        "role": inv["role"],
        "seat": None
        if seat is None
        else {"id": seat["id"], "name": seat["name"], "team": seat["team"]},
        "intendedHandle": inv["intended_handle"],
        "expiresAt": inv["expires_at"],
    }


@router.post("/invites/claim")
async def invite_claim(request: Request):
    guard = _mutation_guard(request)
    if guard:
        return guard
    try:
        body = await _json_body(request)
        existing = _user(request)
        user = await run_in_threadpool(
            accounts.claim_invite,
            get_store(),
            str(body.get("token") or ""),
            now=_now(),
            existing_user=existing,
            handle=body.get("handle"),
            password=body.get("password"),
            display_name=body.get("displayName"),
        )
    except AuctionError as exc:
        return _auction_error(exc)
    resp = JSONResponse({"user": user.public()})
    if existing is None:
        token = await run_in_threadpool(accounts.issue_session, get_store(), user.id, _now())
        _set_cookie(resp, token)
    return resp


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------


def _member_or_admin(room_id: str, user: accounts.User) -> dict:
    m = accounts.membership(get_store(), room_id, user.id)
    if m is None:
        get_store().room_row(room_id)  # 404 for unknown rooms first
        raise AuctionError("forbidden", "you are not a member of this room", 403)
    return m


@router.get("/meta")
async def auction_meta(request: Request):
    gate = _gate()
    if gate:
        return gate
    return {
        "bindingRules": BINDING_OWNER_RULES,
        "proposedRules": PROPOSED_RULE_KEYS,
        "presets": {k: {kk: vv for kk, vv in v.items()} for k, v in TIMING_PRESETS.items()},
        "officialLaunchEnabled": False,
    }


@router.post("/rooms")
async def create_room(request: Request):
    guard = _mutation_guard(request)
    if guard:
        return guard
    try:
        user = _require_user(request)
        if not user.is_site_admin:
            raise AuctionError("forbidden", "only the site owner can create rooms", 403)
        body = await _json_body(request)
        room_type = str(body.get("roomType") or "mock")
        if room_type != "mock":
            raise AuctionError(
                "official_launch_gated",
                "Official rooms are OFF until the owner separately approves launch. Create a mock room.",
                403,
            )
        preset = str(body.get("preset") or "fast")
        if preset not in TIMING_PRESETS:
            raise AuctionError("bad_rules", "unknown timing preset")
        rules = default_rules(preset)
        seed = int(body.get("seed") or int(_now()) % 100000)

        contract = None
        srv = sys.modules.get("server") or sys.modules.get("__main__")
        contract = getattr(srv, "latest_contract_data", None)

        seat_source = str(body.get("seatSource") or "league")
        budget_source = str(body.get("budgetSource") or "draft_capital")
        provenance: dict[str, Any] = {}
        if seat_source == "league":
            seats = sources.league_seats(contract)
            if len(seats) != rules["seat_count"]:
                raise AuctionError(
                    "league_seats_unavailable",
                    f"the loaded league has {len(seats)} teams, expected {rules['seat_count']}; use generic seats",
                    409,
                )
        else:
            seats = [
                {"name": f"Team {i + 1}", "team": "", "sleeper_user_id": None, "roster_id": None}
                for i in range(rules["seat_count"])
            ]
        if budget_source == "draft_capital":
            dc = await _draft_capital_payload(request)
            seats, provenance = sources.join_budgets(seats, dc)
        elif budget_source in ("equal", "zero"):
            amount = 0 if budget_source == "zero" else int(body.get("equalAmount") or 100)
            engine._require_dollars(amount, "equalAmount")
            seats = [{**s, "opening_budget": amount, "budget_source": budget_source} for s in seats]
            provenance = {"source": f"mock {budget_source} budgets", "amount": amount}
        else:
            raise AuctionError(
                "bad_budget_source", "budgetSource must be draft_capital, equal or zero"
            )

        pool = (
            sources.synthetic_pool()
            if body.get("poolSource") == "synthetic"
            else sources.rookie_pool_from_contract(contract)
        )
        if not pool["players"]:
            pool = sources.synthetic_pool()

        commish_seat_idx = int(body.get("commissionerSeat") or 0)
        if not (0 <= commish_seat_idx < len(seats)):
            raise AuctionError("bad_seat", "commissionerSeat out of range")
        bots = bool(body.get("bots", True))
        seat_list = []
        for i, s in enumerate(seats):
            seat_list.append(
                {
                    **s,
                    "id": f"S{i + 1}",
                    "is_bot": bots and i != commish_seat_idx,
                    "bot_seed": seed + i,
                }
            )
        room_id = new_room_id()
        state = engine.new_room_state(
            room_id=room_id,
            name=str(body.get("name") or "Mock rookie auction")[:120],
            room_type="mock",
            rules=rules,
            seats=seat_list,
            order=None,
            pool=pool,
            created_at=_now(),
        )
        state["budget_provenance"] = provenance
        store = get_store()
        await run_in_threadpool(store.create_room, state, created_by=user.id, now_real=_now())

        def _add():
            with store.write() as conn:
                accounts.add_member(
                    store,
                    conn,
                    room_id=room_id,
                    user_id=user.id,
                    role="commissioner",
                    seat_id=f"S{commish_seat_idx + 1}",
                    now=_now(),
                )

        await run_in_threadpool(_add)
    except AuctionError as exc:
        return _auction_error(exc)
    return {"roomId": room_id, "budgetProvenance": provenance}


async def _draft_capital_payload(request: Request) -> dict:
    srv = sys.modules.get("server") or sys.modules.get("__main__")
    fn = getattr(srv, "get_draft_capital", None)
    if fn is None:
        raise AuctionError(
            "draft_capital_unavailable", "draft capital is unavailable in this process", 503
        )
    resp = await fn(request)
    if isinstance(resp, Response):
        if resp.status_code != 200:
            raise AuctionError(
                "draft_capital_unavailable", f"draft capital returned {resp.status_code}", 503
            )
        return json.loads(resp.body)
    return resp if isinstance(resp, dict) else {}


def _view(room_id: str, user: accounts.User, member: dict, now_real: float) -> dict:
    store = get_store()
    row = store.room_row(room_id)
    state = json.loads(row["state_json"])
    room_now = store.room_now(row, now_real)
    public = engine.public_view(state, room_now)
    seat = member.get("seat_id")
    is_commish = member.get("role") == "commissioner"
    vis = {"public"}
    if seat:
        vis.add(f"seat:{seat}")
    if is_commish:
        vis.add("commissioner")
    out = {
        "revision": int(row["revision"]),
        "serverNow": now_real,
        "roomNow": room_now,
        "clockOffset": float(row["clock_offset"]) if row["room_type"] == "mock" else 0.0,
        "public": public,
        "me": {
            "user": user.public(),
            "role": member.get("role"),
            "seat": seat,
            # Only the seat's own manager (or the commissioner's OWN seat)
            # ever receives that seat's private state.
            "private": engine.seat_private_view(state, seat, room_now)
            if seat and member.get("role") in ("manager", "commissioner")
            else None,
        },
        "events": store.events_for(room_id, vis=vis, limit=150),
        "budgetProvenance": state.get("budget_provenance"),
    }
    if is_commish:
        members, invites = accounts.room_members(store, room_id)
        out["commissioner"] = {"members": members, "invites": invites}
    return out


@router.get("/rooms/{room_id}/view")
async def room_view(request: Request, room_id: str, after: int = -1, wait: float = 0):
    gate = _gate()
    if gate:
        return gate
    try:
        user = _require_user(request)
        member = await run_in_threadpool(_member_or_admin, room_id, user)
    except AuctionError as exc:
        return _auction_error(exc)
    store = get_store()
    wait = max(0.0, min(float(wait), 25.0))
    if after >= 0 and wait > 0:
        deadline = time.monotonic() + wait
        rev = store.cached_revision(room_id)
        if rev is None:
            rev = int(store.room_row(room_id)["revision"])
            store._revisions.setdefault(room_id, rev)
        while rev is not None and rev <= after and time.monotonic() < deadline:
            await asyncio.sleep(0.25)
            if await request.is_disconnected():
                return Response(status_code=204)
            rev = store.cached_revision(room_id)
        # Re-check authorisation after the wait: a revoked session or a
        # removed member must not receive the next snapshot.
        try:
            user = _require_user(request)
            member = await run_in_threadpool(_member_or_admin, room_id, user)
        except AuctionError as exc:
            return _auction_error(exc)
    try:
        payload = await run_in_threadpool(_view, room_id, user, member, _now())
    except AuctionError as exc:
        return _auction_error(exc)
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@router.get("/rooms/{room_id}/pool")
async def room_pool(request: Request, room_id: str):
    gate = _gate()
    if gate:
        return gate
    try:
        user = _require_user(request)
        await run_in_threadpool(_member_or_admin, room_id, user)
        state, _, _ = get_store().load(room_id)
    except AuctionError as exc:
        return _auction_error(exc)
    pool = state["pool"]
    return {
        "version": pool["version"],
        "label": pool["label"],
        "isOfficialClass": pool["is_official_class"],
        "players": pool["players"],
    }


# Which command kinds a caller may send, and which payload keys each carries.
_ALLOWED_FIELDS: dict[str, tuple[str, ...]] = {
    "nominate": ("player",),
    "bid": ("auction", "max"),
    "withdraw": ("auction",),
    "pass_nomination": (),
    "set_queue": ("players", "auto"),
    "configure": ("rules",),
    "confirm_rules": ("keys",),
    "set_seat": ("seat", "patch", "reason"),
    "set_order": ("order", "basis"),
    "start": (),
    "pause": ("reason",),
    "resume": ("reason", "min_remaining_active_seconds"),
    "adjust_budget": ("seat", "amount", "reason"),
}


@router.post("/rooms/{room_id}/commands")
async def room_command(request: Request, room_id: str):
    guard = _mutation_guard(request)
    if guard:
        return guard
    key = request.headers.get("idempotency-key") or ""
    if not _IDEM_RE.match(key):
        return _err(
            "idempotency_key_required", "send an Idempotency-Key header (8-100 url-safe chars)", 400
        )
    try:
        user = _require_user(request)
        member = await run_in_threadpool(_member_or_admin, room_id, user)
        body = await _json_body(request)
        kind = str(body.get("kind") or "")
        if kind not in _ALLOWED_FIELDS:
            raise AuctionError("unknown_command", "unknown command")
        cmd: dict[str, Any] = {"kind": kind}
        for f in _ALLOWED_FIELDS[kind]:
            if f in body:
                cmd[f] = body[f]
        role = member["role"]
        if kind in engine.COMMISSIONER_KINDS:
            if role != "commissioner":
                raise AuctionError("forbidden", "commissioner only", 403)
            cmd["actor"] = {"role": "commissioner", "user": user.id, "seat": member.get("seat_id")}
        else:
            if role not in ("manager", "commissioner") or not member.get("seat_id"):
                raise AuctionError("forbidden", "you do not hold a seat in this room", 403)
            cmd["actor"] = {"role": "manager", "user": user.id, "seat": member["seat_id"]}
        out = await run_in_threadpool(
            get_store().execute, room_id, cmd, user_id=user.id, now_real=_now(), idem_key=key
        )
    except AuctionError as exc:
        return _auction_error(exc)
    status = int(out["status"])
    body = {"revision": out["revision"], "replayed": out["replayed"], **(out["result"] or {})}
    return JSONResponse(status_code=status, content=body)


@router.get("/rooms/{room_id}/receipts/{key}")
async def room_receipt(request: Request, room_id: str, key: str):
    gate = _gate()
    if gate:
        return gate
    try:
        user = _require_user(request)
        await run_in_threadpool(_member_or_admin, room_id, user)
    except AuctionError as exc:
        return _auction_error(exc)
    receipt = await run_in_threadpool(get_store().receipt, room_id, user.id, key)
    if receipt is None:
        return _err("no_receipt", "no command with this key was committed", 404)
    return receipt


@router.post("/rooms/{room_id}/invites")
async def room_invite(request: Request, room_id: str):
    guard = _mutation_guard(request)
    if guard:
        return guard
    try:
        user = _require_user(request)
        member = await run_in_threadpool(_member_or_admin, room_id, user)
        if member["role"] != "commissioner":
            raise AuctionError("forbidden", "commissioner only", 403)
        body = await _json_body(request)
        state, _, _ = get_store().load(room_id)
        seat_id = body.get("seat")
        role = str(body.get("role") or "manager")
        seat = None
        if seat_id is not None:
            seat = next((s for s in state["seats"] if s["id"] == seat_id), None)
            if seat is None:
                raise AuctionError("unknown_seat", "no such seat", 404)
            if seat["is_bot"]:
                raise AuctionError(
                    "bot_seat",
                    "that seat is played by a bot — turn the bot off for it first",
                    409,
                )
        ttl_hours = body.get("ttlHours", 168)
        if (
            isinstance(ttl_hours, bool)
            or not isinstance(ttl_hours, (int, float))
            or not (1 <= float(ttl_hours) <= 720)
        ):
            raise AuctionError("bad_request", "ttlHours must be 1-720")
        token = await run_in_threadpool(
            lambda: accounts.create_invite(
                get_store(),
                room_id=room_id,
                seat_id=seat_id,
                role=role,
                created_by=user.id,
                now=_now(),
                intended_handle=(str(body["intendedHandle"]).strip() or None)
                if body.get("intendedHandle")
                else None,
                intended_sleeper_user_id=(seat or {}).get("sleeper_user_id")
                if state["room_type"] == "official"
                else None,
                ttl_seconds=int(float(ttl_hours) * 3600),
            )
        )
    except AuctionError as exc:
        return _auction_error(exc)
    # The token is returned exactly once, to the commissioner, and never logged.
    return {"joinPath": f"/auction/join?token={token}"}


@router.post("/rooms/{room_id}/clock")
async def room_clock(request: Request, room_id: str):
    guard = _mutation_guard(request)
    if guard:
        return guard
    try:
        user = _require_user(request)
        member = await run_in_threadpool(_member_or_admin, room_id, user)
        if member["role"] != "commissioner":
            raise AuctionError("forbidden", "commissioner only", 403)
        body = await _json_body(request)
        seconds = body.get("advanceSeconds")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise AuctionError("bad_time", "advanceSeconds must be a number")
        out = await run_in_threadpool(
            get_store().advance_mock_clock,
            room_id,
            float(seconds),
            user_id=user.id,
            now_real=_now(),
        )
    except AuctionError as exc:
        return _auction_error(exc)
    return {"revision": out["revision"]}


@router.post("/rooms/{room_id}/clone")
async def room_clone(request: Request, room_id: str):
    """A NEW mock run from a room's reviewed configuration.  Never promotes a
    played mock and never touches the source room."""
    guard = _mutation_guard(request)
    if guard:
        return guard
    try:
        user = _require_user(request)
        member = await run_in_threadpool(_member_or_admin, room_id, user)
        if member["role"] != "commissioner" or not user.is_site_admin:
            raise AuctionError("forbidden", "commissioner only", 403)
        store = get_store()
        row = store.room_row(room_id)
        init = json.loads(row["initial_state_json"])
        cur = json.loads(row["state_json"])
        new_id = new_room_id()
        seed_shift = int(_now()) % 1000
        seats = [{**s, "bot_seed": int(s.get("bot_seed") or 0) + seed_shift} for s in cur["seats"]]
        state = engine.new_room_state(
            room_id=new_id,
            name=f"{cur['name']} (run {time.strftime('%m-%d %H:%M')})"[:120],
            room_type="mock",
            rules={**cur["rules"], "confirmations": {}},
            seats=seats,
            order=cur["order"],
            pool=init["pool"],
            created_at=_now(),
        )
        state["budget_provenance"] = cur.get("budget_provenance")
        await run_in_threadpool(
            store.create_room, state, created_by=user.id, now_real=_now(), cloned_from=room_id
        )

        def _add():
            with store.write() as conn:
                accounts.add_member(
                    store,
                    conn,
                    room_id=new_id,
                    user_id=user.id,
                    role="commissioner",
                    seat_id=member.get("seat_id"),
                    now=_now(),
                )

        await run_in_threadpool(_add)
    except AuctionError as exc:
        return _auction_error(exc)
    return {"roomId": new_id}


@router.get("/rooms/{room_id}/export")
async def room_export(request: Request, room_id: str, format: str = "json"):
    gate = _gate()
    if gate:
        return gate
    try:
        user = _require_user(request)
        member = await run_in_threadpool(_member_or_admin, room_id, user)
        state, revision, offset = get_store().load(room_id)
    except AuctionError as exc:
        return _auction_error(exc)
    seats = {s["id"]: s for s in state["seats"]}
    players = state["pool"]["players"]
    rows = []
    for aid in state["auction_order"]:
        a = state["auctions"][aid]
        if a["status"] != "closed":
            continue
        p = players.get(a["player"], {})
        w = seats[a["winner"]]
        rows.append(
            {
                "auction": aid,
                "round": a["round"],
                "playerId": a["player"],
                "player": p.get("name"),
                "pos": p.get("pos"),
                "winnerSeat": a["winner"],
                "winner": w["name"],
                # Sleeper identifiers are for the commissioner's roster
                # reconciliation only.
                **(
                    {
                        "winnerSleeperUserId": w.get("sleeper_user_id"),
                        "winnerRosterId": w.get("roster_id"),
                    }
                    if member["role"] == "commissioner"
                    else {}
                ),
                "price": a["price"],
                "nominator": seats[a["nominator"]]["name"],
                "closedAt": datetime.fromtimestamp(a["closed_at"], timezone.utc).isoformat(),
            }
        )
    if format == "csv":
        buf = io.StringIO()
        fields = list(rows[0].keys()) if rows else ["auction"]
        w = csv.DictWriter(buf, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)
        return Response(
            buf.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="auction-{room_id}-results.csv"'
            },
        )
    return {
        "roomId": room_id,
        "roomType": state["room_type"],
        "revision": revision,
        "status": state["status"],
        "poolVersion": state["pool"]["version"],
        "poolLabel": state["pool"]["label"],
        "ruleVersion": state["rules"].get("rule_version"),
        "results": rows,
        "balances": {
            s["id"]: engine.balance(state, s["id"])
            for s in state["seats"]
            if s["opening_budget"] is not None
        },
    }
