"""Brisket Trade Advisor — public HTTP routes (design §2.11 / §4 frozen contract).

Three routes, all under the public ``/api/public/league`` prefix (public by
the existing ``_private_api_gate`` prefix rule — no change to
``_PUBLIC_API_EXACT``):

* ``GET  /api/public/league/trade-advisor/teams``
* ``GET  /api/public/league/trade-advisor/teams/{rosterId}/assets?sort=…``
* ``POST /api/public/league/trade-advisor/analyze``

Every body this module sends is an instance of one of the outbound Pydantic
models below (``extra="forbid"``, ``Literal`` enums, ``StrictInt`` on a fixed
list of integer keys, NO float type anywhere), dumped and then passed through
``public_contract.assert_public_payload_safe`` as a third line.  Nothing here
serializes an engine object: the evaluation reaches this module only as a
``public_advisor.AdvisorResult``.

Abuse controls (design §7): an isolated ``rate_limit.KeyedLimiter`` charged
per client (IPv4 / IPv6 /64), per neighbourhood (/24 / /48) and against a
never-evicted global ceiling, BEFORE any evaluation; a streamed 16 KiB body
cap; strict inbound schema; ``str`` path / query parameters validated in the
handler (so FastAPI's 422 body can never fire); a constant response floor on
analyze; ``Cache-Control: no-store`` on every error and on analyze; no
analyze-result cache of any kind.

Wired like ``src/public_league/articles_api.py``: ``server.py`` calls
:func:`configure_host` and includes :data:`router`; collaborators that live on
the host (``latest_contract_data``, ``_public_league_key_error``,
``_client_ip_from_request``) are read at REQUEST time so a contract publish —
and a test's monkeypatch — applies immediately.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import traceback
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Callable, Literal, Union

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StringConstraints
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from src.api import rate_limit
from src.api.client_ip import client_key, neighbourhood_key, region_key
from src.trade import public_advisor

_LOG = logging.getLogger(__name__)

router = APIRouter()

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "trade" / "public_advisor.json"
_PUBLIC_CACHE = "public, max-age=60, stale-while-revalidate=300"
_NO_STORE = "no-store"

_host_provider: Callable[[], Any] | None = None


def configure_host(provider: Callable[[], Any]) -> None:
    """Install the callable that returns the host (``server``) module."""
    global _host_provider
    _host_provider = provider


def _host() -> Any:
    if _host_provider is None:
        raise RuntimeError("public_trade_advisor_api host not configured")
    return _host_provider()


# ── Config ─────────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def advisor_config() -> dict[str, Any]:
    """The committed config.  An unreadable file yields the documented
    defaults with both owner switches OFF (fail closed)."""
    defaults: dict[str, Any] = {
        "multiTeamRecommendations": False,
        "pickProjectionLabels": False,
        "limits": {
            "maxTeams": public_advisor.MAX_TEAMS,
            "maxLegs": public_advisor.MAX_LEGS,
            "maxBodyBytes": 16384,
        },
        "responseFloorMs": None,
        "rateLimits": {
            "perKeyBurst": {"capacity": 40, "windowSeconds": 600},
            "perKeyDaily": {"capacity": 400, "windowSeconds": 86400},
            "neighbourhoodBurst": {"capacity": 200, "windowSeconds": 600},
            "neighbourhoodDaily": {"capacity": 1000, "windowSeconds": 86400},
            "regionDaily": {"capacity": 2000, "windowSeconds": 86400},
            "globalCeiling": {"capacity": 3000, "windowSeconds": 3600},
        },
        "maxTrackedKeys": 20000,
    }
    try:
        raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _LOG.error("public advisor config unreadable; using fail-closed defaults")
        return defaults
    out = dict(defaults)
    for key in ("multiTeamRecommendations", "pickProjectionLabels"):
        out[key] = raw.get(key) is True
    for key in ("limits", "rateLimits"):
        if isinstance(raw.get(key), dict):
            out[key] = {**defaults[key], **raw[key]}
    floor = raw.get("responseFloorMs")
    out["responseFloorMs"] = (
        int(floor) if isinstance(floor, int) and not isinstance(floor, bool) and floor > 0 else None
    )
    if isinstance(raw.get("maxTrackedKeys"), int):
        out["maxTrackedKeys"] = int(raw["maxTrackedKeys"])
    return out


_LIMITER: rate_limit.KeyedLimiter | None = None
_LIMITER_LOCK = threading.Lock()


def _limiter() -> rate_limit.KeyedLimiter:
    global _LIMITER
    with _LIMITER_LOCK:
        if _LIMITER is None:
            _LIMITER = rate_limit.KeyedLimiter(
                "brisket_trade_advisor", max_keys=int(advisor_config()["maxTrackedKeys"])
            )
        return _LIMITER


def _charges_for(ip: str) -> list[rate_limit.KeyedCharge]:
    rl = advisor_config()["rateLimits"]

    def _c(key: str, spec: dict[str, Any], *, ceiling: bool = False) -> rate_limit.KeyedCharge:
        return rate_limit.KeyedCharge(
            key=key,
            # Required config: a missing limit raises (fails closed) rather
            # than becoming a fabricated 0.
            capacity=int(spec["capacity"]),
            window_seconds=float(spec["windowSeconds"]),
            ceiling=ceiling,
        )

    ck = client_key(ip)
    nk = neighbourhood_key(ip)
    rk = region_key(ip)
    charges = [_c("global", rl["globalCeiling"], ceiling=True)]
    if ck:
        charges.append(_c(f"burst:{ck}", rl["perKeyBurst"]))
        charges.append(_c(f"daily:{ck}", rl["perKeyDaily"]))
    if nk:
        charges.append(_c(f"hood:{nk}", rl["neighbourhoodBurst"]))
        charges.append(_c(f"hoodday:{nk}", rl["neighbourhoodDaily"]))
    if rk:
        # Daily caps at the /24-/48 and /16-/32 tiers bound how much of the
        # shared global ceiling any one provider's address space can spend,
        # so a few tunnels cannot lock every league member out.
        charges.append(_c(f"region:{rk}", rl["regionDaily"]))
    return charges


# ── Inbound model ──────────────────────────────────────────────────────────

_RosterId = Annotated[StrictInt, Field(ge=1, le=99)]
_AssetId = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9:_-]{1,64}$")]


class _LegIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    id: _AssetId
    from_: _RosterId = Field(alias="from")
    to: _RosterId


class AdvisorAnalyzeRequest(BaseModel):
    """The analyze body.  ``assets`` carries no item bound here: the streamed
    body cap bounds it, and the 128-leg payload-safety bound is enforced by
    ``public_advisor.validate_trade`` as ``invalid_trade / too_many_assets``."""

    model_config = ConfigDict(extra="forbid", strict=True)

    perspectiveRosterId: _RosterId
    teams: Annotated[list[_RosterId], Field(min_length=2, max_length=4)]
    assets: list[_LegIn]


# ── Outbound models (design §4.5) ──────────────────────────────────────────


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RostersOut(_Out):
    state: Literal["current", "stale", "unknown"]
    asOf: str | None


class LimitsOut(_Out):
    minTeams: StrictInt
    maxTeams: StrictInt
    maxLegs: StrictInt


class TeamOut(_Out):
    rosterId: StrictInt
    displayName: str
    teamName: str | None


class TeamsResponse(_Out):
    leagueKey: str
    generation: str
    limits: LimitsOut
    multiTeam: Literal["available", "unavailable"]
    rosters: RostersOut
    teams: list[TeamOut]


class PlayerAssetOut(_Out):
    id: str
    kind: Literal["player"]
    label: str
    side: Literal["offense", "defense", "other"]
    position: str | None
    nflTeam: str | None
    evaluable: StrictBool


class PickAssetOut(_Out):
    id: str
    kind: Literal["pick"]
    label: str
    side: Literal["pick"]
    season: StrictInt
    round: StrictInt
    originRosterId: StrictInt
    projection: Literal["early", "mid", "late"] | None
    evaluable: StrictBool


class AssetsResponse(_Out):
    leagueKey: str
    generation: str
    rosterId: StrictInt
    sort: Literal["value_desc", "value_asc", "alpha"]
    pickOwnership: Literal["observed", "unavailable"]
    rosters: RostersOut
    assets: list[Union[PlayerAssetOut, PickAssetOut]]


class LegOut(_Out):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    id: str
    from_: StrictInt = Field(alias="from")
    to: StrictInt


class AnalyzeResponse(_Out):
    status: Literal["success"]
    leagueKey: str
    generation: str
    perspectiveRosterId: StrictInt
    teamCount: StrictInt
    category: Literal[
        "STRONGLY_FAVORABLE",
        "FAVORABLE",
        "APPROXIMATELY_EVEN",
        "UNFAVORABLE",
        "STRONGLY_UNFAVORABLE",
        "UNAVAILABLE",
    ]
    recommendation: Literal["ACCEPT", "FAIR", "DECLINE", "NONE"]
    headline: str
    message: str
    reasonCode: (
        Literal[
            "asset_not_evaluable",
            "ownership_unverifiable",
            "multi_team_unsupported",
            "roster_limit",
        ]
        | None
    )
    reasonText: str | None
    unavailableAssetIds: list[str]
    trade: list[LegOut]


ErrorCode = Literal[
    "invalid_request",
    "invalid_trade",
    "unknown_league",
    "inactive_league",
    "league_not_public",
    "unknown_team",
    "stale_assets",
    "payload_too_large",
    "unsupported_media_type",
    "rate_limited",
    "advisor_unavailable",
]


class ErrorOut(_Out):
    error: ErrorCode
    message: str
    reason: str | None = None
    field: str | None = None
    assetIds: list[str] | None = None
    rosterIds: list[StrictInt] | None = None
    leagueKey: str | None = None
    maxBytes: StrictInt | None = None
    retryAfterSeconds: StrictInt | None = None


#: Fixed public copy per (error, reason).  Never an exception message, never
#: an echo of request content.
_ERROR_MESSAGES: dict[tuple[str, str | None], str] = {
    ("invalid_request", "invalid_json"): "The request body is not valid JSON.",
    ("invalid_request", "schema"): "The request does not match the expected format.",
    ("invalid_request", "unsupported_sort"): "That sort order is not supported.",
    ("invalid_request", "invalid_roster_id"): "That team identifier is not valid.",
    (
        "invalid_trade",
        "perspective_not_in_trade",
    ): "Your team must be one of the teams in the trade.",
    ("invalid_trade", "duplicate_team"): "A team can only appear once in a trade.",
    ("invalid_trade", "unknown_team"): "One or more teams are not in this league.",
    ("invalid_trade", "idle_team"): "Every team in the trade must send or receive an asset.",
    ("invalid_trade", "one_sided_trade"): "Each team must send at least one player or pick.",
    ("invalid_trade", "unknown_asset"): "One or more assets are not recognized.",
    ("invalid_trade", "duplicate_asset"): "An asset can only appear once in a trade.",
    ("invalid_trade", "invalid_origin"): "Every asset must come from a team in the trade.",
    ("invalid_trade", "invalid_destination"): "Every asset must go to a team in the trade.",
    ("invalid_trade", "destination_is_origin"): "An asset can't be sent to the team that owns it.",
    ("invalid_trade", "too_many_assets"): "This trade has too many assets.",
    ("unknown_league", None): "Unknown league.",
    ("inactive_league", None): "That league is not active.",
    ("league_not_public", None): "That league has no public trade advisor.",
    ("unknown_team", None): "That team is not in this league.",
    ("stale_assets", "asset_not_owned"): (
        "Rosters have changed: one or more assets are no longer owned by the team "
        "sending them. Refresh and try again."
    ),
    ("payload_too_large", None): "The request is too large.",
    ("unsupported_media_type", None): "Send the request as application/json.",
    ("rate_limited", None): "Too many requests. Please wait a moment and try again.",
    ("advisor_unavailable", "disabled"): "The trade advisor is not available.",
    ("advisor_unavailable", "not_ready"): "The trade advisor is not ready yet. Try again shortly.",
    ("advisor_unavailable", "upstream_unavailable"): (
        "The trade advisor is temporarily unavailable. Try again shortly."
    ),
}


def _safe_dump(model: BaseModel) -> dict[str, Any]:
    body = model.model_dump(by_alias=True, exclude_none=isinstance(model, ErrorOut))
    from src.public_league.public_contract import assert_public_payload_safe

    assert_public_payload_safe(body)
    return body


def _error(
    status: int,
    error: str,
    reason: str | None = None,
    *,
    headers: dict[str, str] | None = None,
    **extras: Any,
) -> JSONResponse:
    message = _ERROR_MESSAGES.get((error, reason)) or _ERROR_MESSAGES.get((error, None))
    if message is None:
        status, error, reason, extras = 503, "advisor_unavailable", "upstream_unavailable", {}
        message = _ERROR_MESSAGES[(error, reason)]
    body = _safe_dump(ErrorOut(error=error, message=message, reason=reason, **extras))
    return JSONResponse(
        status_code=status,
        content=body,
        headers={"Cache-Control": _NO_STORE, **(headers or {})},
    )


def _from_advisor_error(exc: public_advisor.AdvisorError) -> JSONResponse:
    allowed = {"assetIds", "rosterIds", "field"}
    extras = {k: v for k, v in exc.extras.items() if k in allowed}
    return _error(exc.status, exc.error, exc.reason, **extras)


def _log_failure(where: str, exc: BaseException) -> None:
    """Type and stack frames only — never the exception message, never a
    simulation or decision object (design §2.11 / §13 item 5)."""
    try:
        from src.utils.request_context import current_request_id

        rid = current_request_id()
    except Exception:  # noqa: BLE001
        rid = None
    frames = "".join(traceback.format_tb(exc.__traceback__))
    _LOG.error(
        "public_advisor_failure where=%s requestId=%s type=%s\n%s",
        where,
        rid or "-",
        type(exc).__name__,
        frames,
    )


# ── Shared request steps ───────────────────────────────────────────────────


def _league_error(league_key: str) -> JSONResponse | None:
    """The existing public-league predicate, re-emitted in this module's
    error shape (fixed copy, ``no-store``)."""
    err = _host()._public_league_key_error(league_key)
    if err is None:
        return None
    try:
        original = json.loads(bytes(err.body))
    except Exception:  # noqa: BLE001
        original = {}
    code = original.get("error") if isinstance(original, dict) else None
    if code not in ("unknown_league", "inactive_league", "league_not_public"):
        return _error(503, "advisor_unavailable", "upstream_unavailable")
    extras: dict[str, Any] = {}
    key = original.get("leagueKey")
    if isinstance(key, str) and key and code != "unknown_league":
        extras["leagueKey"] = key
    return _error(err.status_code, code, None, **extras)


def _public_league_key() -> str | None:
    from src.api import league_registry
    from src.public_league.public_contract import public_league_key

    try:
        key = public_league_key(league_registry.get_sleeper_league_id())
    except Exception:  # noqa: BLE001
        key = None
    if key:
        return key
    cfg = league_registry.get_default_league()
    return cfg.key if cfg is not None else None


_SNAPSHOT_MEMO: "OrderedDict[tuple[int, str], tuple[Any, public_advisor.AdvisorSnapshot]]" = (
    OrderedDict()
)
_SNAPSHOT_LOCK = threading.Lock()


def _snapshot_for(contract: Any, league_key: str) -> public_advisor.AdvisorSnapshot:
    """The snapshot of ONE captured contract, memoized by (identity,
    generation), LRU 2.  The memo holds a reference to the contract so its
    ``id`` cannot be reused while cached.  It depends on the contract only —
    no evaluation result is ever cached."""
    generation = public_advisor.generation_for(contract)
    key = (id(contract), generation)
    with _SNAPSHOT_LOCK:
        hit = _SNAPSHOT_MEMO.get(key)
        if hit is not None and hit[0] is contract and hit[1].league_key == league_key:
            _SNAPSHOT_MEMO.move_to_end(key)
            return hit[1]
    from src.api import league_registry

    cfg = league_registry.get_league_by_key(league_key)
    snap = public_advisor.build_snapshot(
        contract,
        league_key=league_key,
        roster_settings=dict(getattr(cfg, "roster_settings", None) or {}),
    )
    with _SNAPSHOT_LOCK:
        _SNAPSHOT_MEMO[key] = (contract, snap)
        _SNAPSHOT_MEMO.move_to_end(key)
        while len(_SNAPSHOT_MEMO) > 2:
            _SNAPSHOT_MEMO.popitem(last=False)
    return snap


def reset_for_tests() -> None:
    with _SNAPSHOT_LOCK:
        _SNAPSHOT_MEMO.clear()
    clear = getattr(advisor_config, "cache_clear", None)
    if callable(clear):
        clear()
    if _LIMITER is not None:
        _LIMITER.reset()


def _launch_gate_reason() -> str | None:
    """Design §2.11: the advisor may not serve while no measured response
    floor is configured — without it, analyze latency encodes which engine
    path ran.  Turning the flag on is therefore not enough to launch; the
    floor must be set too.  Fails closed."""
    if not advisor_config().get("responseFloorMs"):
        return "response_floor_unset"
    return None


def _gate(league_key: str) -> tuple[Any, str | None, JSONResponse | None]:
    """Flag → league → ONE captured contract.  ``(contract, key, error)``."""
    from src.api.feature_flags import is_enabled

    if not is_enabled("brisket_trade_advisor"):
        return None, None, _error(503, "advisor_unavailable", "disabled")
    if _launch_gate_reason() is not None:
        # Publicly indistinguishable from the flag being off: naming the
        # timing defence would describe it to an anonymous caller.
        return None, None, _error(503, "advisor_unavailable", "disabled")
    league_err = _league_error(league_key)
    if league_err is not None:
        return None, None, league_err
    contract = _host().latest_contract_data  # captured ONCE for this request
    public_key = _public_league_key()
    meta = contract.get("meta") if isinstance(contract, dict) else None
    loaded_key = meta.get("leagueKey") if isinstance(meta, dict) else None
    if not isinstance(contract, dict) or not public_key or loaded_key != public_key:
        return None, None, _error(503, "advisor_unavailable", "not_ready")
    return contract, public_key, None


def _rosters_out(snap: public_advisor.AdvisorSnapshot) -> RostersOut:
    return RostersOut(state=snap.rosters_state, asOf=snap.rosters_as_of)


# ── Routes ─────────────────────────────────────────────────────────────────


@router.get("/api/public/league/trade-advisor/teams")
async def get_trade_advisor_teams(request: Request, leagueKey: str = ""):
    """The league's teams for the "Which team are you evaluating for?" step."""
    try:
        contract, key, err = _gate(leagueKey)
        if err is not None:
            return err
        snap = _snapshot_for(contract, key)
        limits = advisor_config()["limits"]
        body = TeamsResponse(
            leagueKey=key,
            generation=snap.generation,
            limits=LimitsOut(
                minTeams=public_advisor.MIN_TEAMS,
                maxTeams=min(int(limits["maxTeams"]), public_advisor.MAX_TEAMS),
                maxLegs=min(int(limits["maxLegs"]), public_advisor.MAX_LEGS),
            ),
            # The multi-side twin (design B1) is not on main, so 3–4-team
            # recommendations cannot be produced whatever the config says.
            multiTeam="unavailable",
            rosters=_rosters_out(snap),
            teams=[
                TeamOut(rosterId=t.roster_id, displayName=t.display_name, teamName=t.team_name)
                for t in public_advisor.list_teams(snap)
            ],
        )
        return JSONResponse(
            content=_safe_dump(body),
            headers={"Cache-Control": "public, max-age=60, stale-while-revalidate=300"},
        )
    except public_advisor.AdvisorError as exc:
        return _from_advisor_error(exc)
    except Exception as exc:  # noqa: BLE001
        _log_failure("teams", exc)
        return _error(503, "advisor_unavailable", "upstream_unavailable")


def _parse_roster_id(raw: str) -> int | None:
    text = str(raw or "")
    # ASCII only: str.isdigit() accepts '¹' / '١', which int() rejects or remaps.
    if not (text.isascii() and text.isdigit()) or len(text) > 2:
        return None
    rid = int(text)
    return rid if 1 <= rid <= 99 else None


@router.get("/api/public/league/trade-advisor/teams/{rosterId}/assets")
async def get_trade_advisor_team_assets(
    request: Request, rosterId: str, sort: str = "value_desc", leagueKey: str = ""
):
    """One team's players and owned picks, already ordered for ``sort``.
    Identities and labels only; the ordering key never leaves the server."""
    try:
        contract, key, err = _gate(leagueKey)
        if err is not None:
            return err
        rid = _parse_roster_id(rosterId)
        if rid is None:
            return _error(400, "invalid_request", "invalid_roster_id", field="rosterId")
        if sort not in public_advisor.SORTS:
            return _error(400, "invalid_request", "unsupported_sort", field="sort")
        snap = _snapshot_for(contract, key)
        assets, pick_state = public_advisor.list_team_assets(snap, rid, sort=sort)
        out: list[PlayerAssetOut | PickAssetOut] = []
        for a in assets:
            if a.kind == "player":
                out.append(
                    PlayerAssetOut(
                        id=a.id,
                        kind="player",
                        label=a.label,
                        side=a.side,
                        position=a.position,
                        nflTeam=a.nfl_team,
                        evaluable=bool(a.evaluable),
                    )
                )
            else:
                out.append(
                    PickAssetOut(
                        id=a.id,
                        kind="pick",
                        label=a.label,
                        side="pick",
                        season=int(a.season),
                        round=int(a.round),
                        originRosterId=int(a.origin_roster_id),
                        projection=None,
                        evaluable=bool(a.evaluable),
                    )
                )
        body = AssetsResponse(
            leagueKey=key,
            generation=snap.generation,
            rosterId=rid,
            sort=sort,
            pickOwnership=pick_state,
            rosters=_rosters_out(snap),
            assets=out,
        )
        return JSONResponse(
            content=_safe_dump(body),
            headers={"Cache-Control": "public, max-age=60, stale-while-revalidate=300"},
        )
    except public_advisor.AdvisorError as exc:
        return _from_advisor_error(exc)
    except Exception as exc:  # noqa: BLE001
        _log_failure("assets", exc)
        return _error(503, "advisor_unavailable", "upstream_unavailable")


class _BodyTooLarge(Exception):
    pass


async def _read_capped_body(request: Request, cap: int) -> bytes:
    """Read the body as a STREAM, aborting as soon as it passes ``cap`` —
    never buffering an attacker-sized body (``request.body()`` would)."""
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > cap:
                raise _BodyTooLarge()
        except ValueError:
            raise _BodyTooLarge() from None
    buf = bytearray()
    async for chunk in request.stream():
        buf.extend(chunk)
        if len(buf) > cap:
            raise _BodyTooLarge()
    return bytes(buf)


def _json_content_type(request: Request) -> bool:
    raw = str(request.headers.get("content-type") or "")
    parts = [p.strip().lower() for p in raw.split(";")]
    if not parts or parts[0] != "application/json":
        return False
    for p in parts[1:]:
        if p and p not in ("charset=utf-8", 'charset="utf-8"'):
            return False
    return True


def _schema_error(exc: ValidationError) -> JSONResponse:
    errors = exc.errors(include_url=False, include_input=False, include_context=False)
    if any(e.get("type") == "json_invalid" for e in errors):
        return _error(400, "invalid_request", "invalid_json")
    loc = errors[0].get("loc") if errors else ()
    field = ".".join(str(p) for p in (loc or ()))[:64] or None
    return _error(400, "invalid_request", "schema", field=field)


def _clock() -> float:
    """The response floor's clock — a test seam (never patch ``time``)."""
    return time.monotonic()


async def _sleep(seconds: float) -> None:
    """The response floor's sleep — a test seam (never patch ``asyncio``)."""
    await asyncio.sleep(seconds)


async def _apply_floor(started: float) -> None:
    """Hold an analyze answer until ``responseFloorMs`` has elapsed, so its
    latency does not encode which engine path ran."""
    floor_ms = advisor_config().get("responseFloorMs")
    if not floor_ms:
        return
    remaining = floor_ms / 1000.0 - (_clock() - started)
    if remaining > 0:
        await _sleep(remaining)


@router.post("/api/public/league/trade-advisor/analyze")
async def post_trade_advisor_analyze(request: Request, leagueKey: str = ""):
    """Evaluate one proposed trade from one team's perspective.  Returns a
    category and fixed copy — never a value, gap, band or confidence."""
    started = _clock()
    try:
        contract, key, err = _gate(leagueKey)
        if err is not None:
            return err
        if not _json_content_type(request):
            return _error(415, "unsupported_media_type")
        cap = int(advisor_config()["limits"].get("maxBodyBytes") or 16384)
        try:
            raw = await _read_capped_body(request, cap)
        except _BodyTooLarge:
            return _error(413, "payload_too_large", maxBytes=cap)
        try:
            req = AdvisorAnalyzeRequest.model_validate_json(raw)
        except ValidationError as exc:
            return _schema_error(exc)

        limited, retry = _limiter().charge(_charges_for(_host()._client_ip_from_request(request)))
        if limited:
            return _error(
                429,
                "rate_limited",
                headers={"Retry-After": str(int(retry))},
                retryAfterSeconds=int(retry),
            )

        snap = _snapshot_for(contract, key)
        trade = public_advisor.validate_trade(
            snap,
            perspective=req.perspectiveRosterId,
            teams=list(req.teams),
            legs=[(leg.id, leg.from_, leg.to) for leg in req.assets],
        )
        result = await run_in_threadpool(
            public_advisor.evaluate_trade,
            snap,
            trade,
            multi_team_enabled=bool(advisor_config().get("multiTeamRecommendations")),
        )
        text = public_advisor.result_text(result)
        body = AnalyzeResponse(
            status="success",
            leagueKey=key,
            generation=snap.generation,
            perspectiveRosterId=result.perspective,
            teamCount=result.team_count,
            category=result.category,
            recommendation=text["recommendation"],
            headline=text["headline"],
            message=text["message"],
            reasonCode=result.reason_code,
            reasonText=text["reasonText"],
            unavailableAssetIds=list(result.unavailable_asset_ids),
            trade=[
                LegOut(id=leg.id, **{"from": leg.from_rid}, to=leg.to_rid) for leg in result.legs
            ],
        )
        content = _safe_dump(body)
        await _apply_floor(started)
        return JSONResponse(content=content, headers={"Cache-Control": _NO_STORE})
    except public_advisor.AdvisorError as exc:
        return _from_advisor_error(exc)
    except Exception as exc:  # noqa: BLE001
        _log_failure("analyze", exc)
        return _error(503, "advisor_unavailable", "upstream_unavailable")
