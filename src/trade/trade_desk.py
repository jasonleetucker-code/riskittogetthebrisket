"""Trade Desk — the private watchlist of trade ideas a user is working (Part 12).

WHAT THIS OWNS
──────────────
The shape, vocabulary and transitions of a user's saved trade candidates, per
(user, leagueKey), stored in ``user_kv.tradeDeskByLeague[leagueKey]``.  It is a
notebook over the generators, not another generator: an item is a frozen copy of
a package the user chose to keep (from Best Offers, Package Builder, Golden
Upgrades, suggestions, the arbitrage scan or the calculator) plus the status the
user gave it.

STATUS IS WHAT THE USER SAYS, NEVER WHAT THE APP INFERS
───────────────────────────────────────────────────────
Idea, Candidate, Evaluated, Saved, Manually sent, Accepted, Rejected and Expired
are all user-entered.  The calculator never sends a trade and Sleeper's pending
offers are not readable, so the app cannot know a trade was sent, accepted or
rejected — every history entry is stamped ``setBy: "user"`` and the UI says
"you marked".  What the app CAN observe is roster evidence: whether the assets
are still where the package needs them.  That is published separately as
``rosterCheck`` (``current`` / ``changed`` / ``unknown``) and never rewrites a
status.

RECOMMENDATION ONLY
───────────────────
Nothing here sends, proposes or executes anything.  No autonomous message,
proposal or roster transaction exists in this module or behind it.
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

TRADE_DESK_FIELD = "tradeDeskByLeague"

#: User-entered statuses, in workflow order.
STATUSES: tuple[str, ...] = (
    "idea",
    "candidate",
    "evaluated",
    "saved",
    "manually_sent",
    "accepted",
    "rejected",
    "expired",
)
STATUS_LABELS: Mapping[str, str] = {
    "idea": "Idea",
    "candidate": "Candidate",
    "evaluated": "Evaluated",
    "saved": "Saved",
    "manually_sent": "Manually sent",
    "accepted": "Accepted",
    "rejected": "Rejected",
    "expired": "Expired",
}
DEFAULT_STATUS = "candidate"

#: Where a saved package came from.  Provenance only; it changes nothing.
SOURCES: tuple[str, ...] = (
    "best_offers",
    "package_builder",
    "golden_upgrades",
    "suggestions",
    "arbitrage_scan",
    "calculator",
    "manual",
)

MAX_ITEMS = 100
MAX_ASSETS_PER_SIDE = 8
MAX_NAME_LEN = 120
MAX_NOTE_LEN = 500
MAX_HISTORY = 30

_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_ASSET_ID_RE = re.compile(r"^[A-Za-z0-9:._\-]{1,80}$")
_RUN_ID_RE = re.compile(r"^[0-9a-f]{8,64}$")

_CREATE_KEYS = frozenset(
    {
        "leagueKey",
        "myTeam",
        "opponent",
        "send",
        "receive",
        "source",
        "sourceRunId",
        "status",
        "note",
        "decisionRunId",
    }
)
_UPDATE_KEYS = frozenset({"leagueKey", "status", "note"})


class DeskError(ValueError):
    """A request the desk refuses; ``code`` is the API error code."""

    def __init__(self, code: str, detail: Any = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def _now_iso(now: datetime | None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat()


def _text(value: Any, what: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DeskError("invalid_body", {"field": what, "reason": "required text"})
    text = value.strip()
    if len(text) > limit:
        raise DeskError("invalid_body", {"field": what, "reason": f"longer than {limit}"})
    return text


def _clean_asset(raw: Any, side: str) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise DeskError("invalid_body", {"field": side, "reason": "asset must be an object"})
    out: dict[str, Any] = {
        "name": _text(raw.get("name"), f"{side}.name", MAX_NAME_LEN),
        "isPick": bool(raw.get("isPick")),
    }
    asset_id = raw.get("assetId")
    if asset_id not in (None, ""):
        if not isinstance(asset_id, str) or not _ASSET_ID_RE.match(asset_id):
            raise DeskError("invalid_body", {"field": f"{side}.assetId", "reason": "bad id"})
        out["assetId"] = asset_id
    board_row = raw.get("boardRowName")
    if board_row not in (None, ""):
        out["boardRowName"] = _text(board_row, f"{side}.boardRowName", MAX_NAME_LEN)
    position = raw.get("position")
    if isinstance(position, str) and position.strip():
        out["position"] = position.strip()[:8]
    return out


def _clean_side(raw: Any, side: str) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise DeskError("invalid_body", {"field": side, "reason": "at least one asset"})
    if len(raw) > MAX_ASSETS_PER_SIDE:
        raise DeskError(
            "invalid_body", {"field": side, "reason": f"at most {MAX_ASSETS_PER_SIDE} assets"}
        )
    return [_clean_asset(a, side) for a in raw]


def _status(value: Any) -> str:
    if value not in STATUSES:
        raise DeskError("invalid_status", {"allowed": list(STATUSES)})
    return str(value)


def _note(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise DeskError("invalid_body", {"field": "note", "reason": "text"})
    if len(value) > MAX_NOTE_LEN:
        raise DeskError("invalid_body", {"field": "note", "reason": f"longer than {MAX_NOTE_LEN}"})
    return value.strip()


def _asset_key(a: Mapping[str, Any]) -> str:
    return str(a.get("assetId") or a.get("name") or "").lower()


def _side_key(item: Mapping[str, Any], name_field: str, owner_field: str) -> str:
    """A team's identity: its Sleeper owner id when recorded, else its name.

    Display names change when a manager renames; the owner id does not."""
    owner = str(item.get(owner_field) or "")
    return f"owner:{owner}" if owner else f"name:{item.get(name_field) or ''}"


def package_key(item: Mapping[str, Any]) -> tuple:
    """Identity of a package: the two teams and the two asset sets."""
    return (
        _side_key(item, "myTeam", "myOwnerId"),
        _side_key(item, "opponent", "opponentOwnerId"),
        tuple(sorted(_asset_key(a) for a in item.get("send") or [])),
        tuple(sorted(_asset_key(a) for a in item.get("receive") or [])),
    )


def unknown_keys(body: Mapping[str, Any], *, create: bool) -> list[str]:
    allowed = _CREATE_KEYS if create else _UPDATE_KEYS
    return sorted(str(k) for k in body if k not in allowed)


def decision_snapshot(
    line: Mapping[str, Any] | None, *, league_key: str | None, my_team: str
) -> tuple[dict[str, Any] | None, str | None]:
    """The War Room decision a calculator save carries (TC-B2 / TCM-G18).

    ``line`` is the server's OWN record of the served decision
    (``trade_decision_log.find_decision_run``), never a verdict the client
    sent.  Returns ``(snapshot, None)`` or ``(None, reason)``: a run that is
    not logged, belongs to another league or team, or carries a headline the
    decision owner does not define is not attached -- the package still saves.
    The snapshot is what was answered WHEN SAVED; it is never refreshed and
    never rewrites a status."""
    from src.trade.trade_decision import HEADLINE_TEXT  # noqa: PLC0415

    if not isinstance(line, Mapping):
        return None, "decision_run_not_found"
    if league_key and line.get("leagueKey") not in (None, league_key):
        return None, "decision_run_other_league"
    if str(line.get("team") or "") != my_team:
        return None, "decision_run_other_team"
    headline = line.get("headline")
    if headline not in HEADLINE_TEXT:
        return None, "decision_run_unreadable"
    receipt = line.get("receipt") if isinstance(line.get("receipt"), Mapping) else {}
    model = receipt.get("packageModel") if isinstance(receipt.get("packageModel"), Mapping) else {}
    strategy = line.get("strategy") if isinstance(line.get("strategy"), Mapping) else {}
    return {
        "runId": str(line.get("runId") or ""),
        "recordedAt": str(line.get("recordedAt") or ""),
        "headline": headline,
        "headlineText": HEADLINE_TEXT[headline],
        "confidenceLevel": line.get("confidenceLevel"),
        "strategy": strategy.get("used"),
        "teamContext": line.get("teamContext"),
        "decisionVersion": line.get("decisionVersion"),
        "packageModel": model.get("id"),
    }, None


def new_item(
    body: Mapping[str, Any],
    *,
    team_names: Iterable[str],
    owner_ids: Mapping[str, str] | None = None,
    now: datetime | None = None,
    league_key: str | None = None,
    decision_lookup: Any = None,
) -> dict[str, Any]:
    """A validated new desk item from a create request.

    ``owner_ids`` maps this league's current team names to their Sleeper owner
    ids; when known they are stored so the item survives a team rename.
    ``decisionRunId`` (calculator saves only) names a served War Room decision;
    ``decision_lookup(run_id)`` reads it from the server's decision log, and
    the item carries that record's snapshot (TC-B2 / TCM-G18)."""
    names = set(team_names)
    my_team = _text(body.get("myTeam"), "myTeam", MAX_NAME_LEN)
    opponent = _text(body.get("opponent"), "opponent", MAX_NAME_LEN)
    if my_team not in names or opponent not in names:
        raise DeskError("unknown_team", {"myTeam": my_team, "opponent": opponent})
    if my_team == opponent:
        raise DeskError("invalid_body", {"field": "opponent", "reason": "must be another team"})
    source = body.get("source") or "manual"
    if source not in SOURCES:
        raise DeskError("invalid_body", {"field": "source", "allowed": list(SOURCES)})
    run_id = body.get("sourceRunId")
    if run_id not in (None, "") and (not isinstance(run_id, str) or not _RUN_ID_RE.match(run_id)):
        raise DeskError("invalid_body", {"field": "sourceRunId", "reason": "bad id"})
    decision_run = body.get("decisionRunId")
    if decision_run not in (None, ""):
        if not isinstance(decision_run, str) or not _RUN_ID_RE.match(decision_run):
            raise DeskError("invalid_body", {"field": "decisionRunId", "reason": "bad id"})
        if source != "calculator":
            raise DeskError(
                "invalid_body", {"field": "decisionRunId", "reason": "calculator saves only"}
            )
    status = _status(body.get("status") or DEFAULT_STATUS)
    stamp = _now_iso(now)
    item = {
        "id": secrets.token_hex(8),
        "createdAt": stamp,
        "updatedAt": stamp,
        "myTeam": my_team,
        "opponent": opponent,
        "send": _clean_side(body.get("send"), "send"),
        "receive": _clean_side(body.get("receive"), "receive"),
        "source": source,
        "status": status,
        "statusHistory": [{"status": status, "at": stamp, "setBy": "user"}],
        "note": _note(body.get("note")),
    }
    if run_id:
        item["sourceRunId"] = run_id
    if decision_run:
        line = decision_lookup(decision_run) if callable(decision_lookup) else None
        snapshot, reason = decision_snapshot(line, league_key=league_key, my_team=my_team)
        if snapshot is not None:
            item["decision"] = snapshot
        else:
            item["decisionUnavailable"] = reason
    for name, field in ((my_team, "myOwnerId"), (opponent, "opponentOwnerId")):
        owner = str((owner_ids or {}).get(name) or "")
        if owner:
            item[field] = owner
    return item


def _items(current: Any) -> list[dict[str, Any]]:
    if isinstance(current, Mapping):
        items = current.get("items")
        if isinstance(items, list):
            return [dict(i) for i in items if isinstance(i, Mapping)]
    return []


def _entry(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    return {"items": items} if items else None


def add_item(current: Any, item: dict[str, Any]) -> dict[str, Any] | None:
    """The league entry with ``item`` added; refuses a duplicate or a full desk."""
    items = _items(current)
    key = package_key(item)
    for existing in items:
        if package_key(existing) == key:
            raise DeskError("duplicate", {"id": existing.get("id")})
    if len(items) >= MAX_ITEMS:
        raise DeskError("desk_full", {"limit": MAX_ITEMS})
    return _entry([*items, item])


def _find(items: list[dict[str, Any]], item_id: str) -> int:
    if not isinstance(item_id, str) or not _ID_RE.match(item_id):
        raise DeskError("not_found")
    for i, it in enumerate(items):
        if it.get("id") == item_id:
            return i
    raise DeskError("not_found")


def update_item(
    current: Any, item_id: str, body: Mapping[str, Any], *, now: datetime | None = None
) -> dict[str, Any] | None:
    """The league entry with one item's status and/or note changed by the user."""
    items = _items(current)
    i = _find(items, item_id)
    if "status" not in body and "note" not in body:
        raise DeskError("invalid_body", {"reason": "nothing to update"})
    item = dict(items[i])
    stamp = _now_iso(now)
    if "status" in body:
        status = _status(body.get("status"))
        if status != item.get("status"):
            history = list(item.get("statusHistory") or [])
            history.append({"status": status, "at": stamp, "setBy": "user"})
            item["statusHistory"] = history[-MAX_HISTORY:]
            item["status"] = status
    if "note" in body:
        item["note"] = _note(body.get("note"))
    item["updatedAt"] = stamp
    items[i] = item
    return _entry(items)


def remove_item(current: Any, item_id: str) -> dict[str, Any] | None:
    items = _items(current)
    i = _find(items, item_id)
    del items[i]
    return _entry(items)


def _roster_names(team: Mapping[str, Any]) -> set[str] | None:
    players = team.get("players")
    if not isinstance(players, list):
        return None
    return {str(p).lower() for p in players if isinstance(p, str)}


def roster_check(
    item: Mapping[str, Any], teams_by_name: Mapping[str, Mapping[str, Any]] | None
) -> dict[str, Any]:
    """Are the package's PLAYERS still where it needs them?  Evidence only.

    ``current`` — every player we send is on our roster and every player we
    receive is on theirs.  ``changed`` — at least one is not (named).
    ``unknown`` — no roster for this league is loaded, or a team is missing.
    Picks are not checked here (pick ownership has its own owner and its own
    unknown state); they are counted in ``picksNotChecked``.
    """
    if not teams_by_name:
        return {"state": "unknown", "reason": "league_rosters_not_loaded"}
    by_owner = {
        str(t.get("ownerId")): t for t in teams_by_name.values() if str(t.get("ownerId") or "")
    }

    def _team(name_field: str, owner_field: str) -> Mapping[str, Any] | None:
        owner = str(item.get(owner_field) or "")
        if owner:
            # A recorded owner id decides; a renamed team is still found, and a
            # name now held by someone else is never matched instead.
            return by_owner.get(owner)
        return teams_by_name.get(str(item.get(name_field) or ""))

    mine = _team("myTeam", "myOwnerId")
    theirs = _team("opponent", "opponentOwnerId")
    if mine is None or theirs is None:
        return {"state": "unknown", "reason": "team_not_in_league"}
    my_names, their_names = _roster_names(mine), _roster_names(theirs)
    if my_names is None or their_names is None:
        return {"state": "unknown", "reason": "roster_unreadable"}
    moved: list[str] = []
    picks = 0
    for side, names in (("send", my_names), ("receive", their_names)):
        for a in item.get(side) or []:
            if a.get("isPick"):
                picks += 1
                continue
            if str(a.get("name") or "").lower() not in names:
                moved.append(str(a.get("name")))
    return {
        "state": "changed" if moved else "current",
        "noLongerInPlace": moved,
        "picksNotChecked": picks,
    }


def payload(
    league_key: str,
    current: Any,
    *,
    teams_by_name: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    items = sorted(_items(current), key=lambda i: str(i.get("updatedAt") or ""), reverse=True)
    for it in items:
        it["rosterCheck"] = roster_check(it, teams_by_name)
    return {
        "leagueKey": league_key,
        "action": "recommend_only",
        "statuses": [{"value": s, "label": STATUS_LABELS[s]} for s in STATUSES],
        "statusNote": (
            "Statuses are what you marked. The app cannot see whether a trade was "
            "sent, accepted or rejected."
        ),
        "limit": MAX_ITEMS,
        "count": len(items),
        "items": items,
    }
