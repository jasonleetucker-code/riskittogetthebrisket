"""Brisket Trade Advisor — public HTTP routes, FAIRNESS-ONLY (owner amendment
2026-10-20; spec ``docs/trade/NTEAM_TRADE_ENGINE_SPEC.md`` §4 / §6.3).

Three routes, all under the public ``/api/public/league`` prefix (public by
the existing ``_private_api_gate`` prefix rule — no change to
``_PUBLIC_API_EXACT``):

* ``GET  /api/public/league/trade-advisor/teams``
* ``GET  /api/public/league/trade-advisor/teams/{rosterId}/assets?sort=position_alpha``
* ``POST /api/public/league/trade-advisor/analyze``

Analyze answers FAIR / NOT FAIR / UNABLE TO DETERMINE for every team of a 2-,
3- or 4-team trade plus the overall result, all in ONE response (the
perspective only selects the default view).  The computation is the shared
N-team engine in ``market_fairness`` mode, reduced by
``public_advisor.reduce_fairness`` — there is no business logic here.

Every body this module sends is an instance of one of the outbound Pydantic
models below (``extra="forbid"``, ``Literal`` enums, ``StrictInt`` on a fixed
list of integer keys, NO float type anywhere), dumped, then passed through
``public_contract.assert_public_payload_safe`` AND
``public_advisor.assert_advisor_payload_value_free``.  Every response is
``Cache-Control: no-store``.

Abuse controls: an isolated ``rate_limit.KeyedLimiter`` charged per client
(IPv4 / IPv6 /64), per neighbourhood (/24 / /48), per region and against a
never-evicted global ceiling, BEFORE the body is read; a streamed body cap;
strict inbound schema; ``str`` path / query parameters validated in the
handler (so FastAPI's 422 body can never fire); a measured response floor
applied in ``finally`` to every analyze outcome after the limiter charge; a
public single-flight that never joins a private flight; per-route admission
control (``src/api/compute_admission.py``: a concurrency bound on engine
computations and a caller deadline, both a retryable 503); no analyze-result
cache of any kind.

Launch gate (spec §6.3), checked on every request: the flag, a measured
``responseFloorMs``, an owner-approved fairness-band version that is not
PROVISIONAL, a valid and current owner source-permission record covering
every voting source (``src/trade/public_advisor_permission.py``), and the geom
package model.  Until all hold every route answers 503 ``advisor_unavailable``.

Wired like ``src/public_league/articles_api.py``: ``server.py`` calls
:func:`configure_host` and includes :data:`router`; collaborators that live on
the host (``latest_contract_data``, ``_public_league_key_error``,
``_client_ip_from_request``) are read at REQUEST time so a contract publish —
and a test's monkeypatch — applies immediately.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import threading
import time
import traceback
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Callable, Literal, Union

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    ValidationError,
    field_validator,
)
from starlette.concurrency import run_in_threadpool

from src.api import rate_limit
from src.api.client_ip import client_key, neighbourhood_key, region_key
from src.trade import public_advisor

_LOG = logging.getLogger(__name__)

router = APIRouter()

_REPO = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _REPO / "config" / "trade" / "public_advisor.json"
_NO_STORE = "no-store"
_ECHO_RE = re.compile(r"^[A-Za-z0-9:_-]{1,64}$")

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


def _positive_int(v: Any) -> int | None:
    return int(v) if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


def _parse_floor(raw: Any) -> int | dict[int, int] | None:
    """``responseFloorMs``: a measured positive int, or a measured per-
    ``teamCount`` table ``{"2": ms, "3": ms, ...}``.  Anything else is
    ``None`` (unset — the launch gate stays closed)."""
    single = _positive_int(raw)
    if single is not None:
        return single
    if isinstance(raw, dict) and raw:
        table: dict[int, int] = {}
        for k, v in raw.items():
            ms = _positive_int(v)
            if not (isinstance(k, str) and k.isascii() and k.isdigit()) or ms is None:
                return None
            table[int(k)] = ms
        return table
    return None


@lru_cache(maxsize=1)
def advisor_config() -> dict[str, Any]:
    """The committed config.  An unreadable file yields the documented
    defaults with every launch input unset (fail closed)."""
    defaults: dict[str, Any] = {
        "pickProjectionLabels": False,
        "limits": {"maxTeams": 4, "maxLegs": 128, "maxBodyBytes": 16384},
        "responseFloorMs": None,
        "approvedFairnessVersion": None,
        "approvedSourcePermissionRecord": None,
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
    out["pickProjectionLabels"] = raw.get("pickProjectionLabels") is True
    for key in ("limits", "rateLimits"):
        if isinstance(raw.get(key), dict):
            out[key] = {**defaults[key], **raw[key]}
    out["responseFloorMs"] = _parse_floor(raw.get("responseFloorMs"))
    for key in ("approvedFairnessVersion", "approvedSourcePermissionRecord"):
        v = raw.get(key)
        out[key] = v if isinstance(v, str) and v.strip() else None
    if isinstance(raw.get("maxTrackedKeys"), int):
        out["maxTrackedKeys"] = int(raw["maxTrackedKeys"])
    return out


def _config_max_teams() -> int:
    v = _positive_int(advisor_config()["limits"].get("maxTeams"))
    return v if v is not None and v >= public_advisor.MIN_TEAMS else public_advisor.MIN_TEAMS


def _config_max_legs() -> int:
    v = _positive_int(advisor_config()["limits"].get("maxLegs"))
    return v if v is not None else 1


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
_Generation = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9]{1,64}$")]


class _LegIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    id: _AssetId
    from_: _RosterId = Field(alias="from")
    to: _RosterId


class AdvisorAnalyzeRequest(BaseModel):
    """The analyze body.  ``teams`` is bounded by the CONFIG ceiling
    (``limits.maxTeams``), never a hardcoded count; ``assets`` carries no item
    bound here — the streamed body cap bounds it, and ``limits.maxLegs`` is
    enforced by the ledger as ``invalid_trade / too_many_assets``."""

    model_config = ConfigDict(extra="forbid", strict=True)

    perspectiveRosterId: _RosterId
    teams: Annotated[list[_RosterId], Field(min_length=2)]
    assets: list[_LegIn]
    expectedGeneration: _Generation | None = None

    @field_validator("teams")
    @classmethod
    def _teams_within_config_ceiling(cls, v: list[int]) -> list[int]:
        if len(v) > _config_max_teams():
            raise ValueError("too many teams")
        return v


# ── Outbound models (spec §4.1-§4.5) ───────────────────────────────────────


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
    sort: Literal["position_alpha"]
    pickOwnership: Literal["observed", "unavailable"]
    rosters: RostersOut
    assets: list[Union[PlayerAssetOut, PickAssetOut]]


class LegOut(_Out):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    id: str
    from_: StrictInt = Field(alias="from")
    to: StrictInt


_Result = Literal["FAIR", "NOT_FAIR", "UNABLE_TO_DETERMINE"]


class OverallOut(_Out):
    result: _Result
    label: Literal["FAIR TRADE", "NOT FAIR", "UNABLE TO DETERMINE"]
    reasonCode: Literal["all_teams_fair", "not_all_teams_fair", "evidence_insufficient"]
    reasonText: str
    note: str | None


class TeamResultOut(_Out):
    rosterId: StrictInt
    result: _Result
    label: Literal["FAIR FOR THIS TEAM", "NOT FAIR FOR THIS TEAM", "UNABLE TO DETERMINE"]
    reasonCode: Literal[
        "within_fairness_threshold",
        "outside_fairness_threshold",
        "asset_not_evaluable",
        "ownership_unverifiable",
        "evaluation_unavailable",
    ]
    reasonText: str
    unavailableAssetIds: list[str]


class AnalyzeResponse(_Out):
    status: Literal["success"]
    leagueKey: str
    generation: str
    fairnessVersion: str
    snapshotChanged: StrictBool | None
    rosters: RostersOut
    teamCount: StrictInt
    perspectiveRosterId: StrictInt
    overall: OverallOut
    teams: list[TeamResultOut]
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


#: Fixed public copy per (error, reason) — the ONE table lives in
#: ``public_advisor`` (spec §4.4).
_ERROR_MESSAGES = public_advisor.ERROR_MESSAGES

_PAYLOAD_KIND: dict[type, str] = {
    TeamsResponse: "list",
    AssetsResponse: "list",
    AnalyzeResponse: "analyze",
    ErrorOut: "error",
}


def _safe_dump(model: BaseModel) -> dict[str, Any]:
    body = model.model_dump(by_alias=True, exclude_none=isinstance(model, ErrorOut))
    from src.public_league.public_contract import assert_public_payload_safe

    assert_public_payload_safe(body)
    public_advisor.assert_advisor_payload_value_free(body, kind=_PAYLOAD_KIND[type(model)])
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
    # Echo bounds (spec §4.5 P3): only request-supplied ids of the inbound
    # pattern, capped at maxLegs.
    cap = _config_max_legs()
    if "assetIds" in extras:
        ids = [a for a in extras["assetIds"] if isinstance(a, str) and _ECHO_RE.match(a)]
        extras["assetIds"] = ids[:cap] or None
    if "rosterIds" in extras:
        rids = [r for r in extras["rosterIds"] if isinstance(r, int) and not isinstance(r, bool)]
        extras["rosterIds"] = rids[:cap] or None
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
    simulation or decision object."""
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


def reset_for_tests() -> None:
    from src.api import compute_admission
    from src.trade import trade_ledger

    compute_admission.reset_for_tests()

    trade_ledger.clear_snapshot_memo()
    public_advisor.reset_memos_for_tests()
    clear = getattr(advisor_config, "cache_clear", None)
    if callable(clear):
        clear()
    if _LIMITER is not None:
        _LIMITER.reset()


def _source_permission_problem(rel: str | None) -> str | None:
    """R2-10: the owner's OD-3 source-permission record must be a complete,
    current approval covering every voting source — not merely an existing
    file (``src/trade/public_advisor_permission.py``).  ``None`` = valid."""
    from src.trade import public_advisor_permission  # noqa: PLC0415

    try:
        return public_advisor_permission.record_path_problem(rel)
    except Exception:  # noqa: BLE001 — an unverifiable record never opens the gate
        return "check_failed"


def _launch_gate_reason() -> str | None:
    """Spec §6.3: switching the flag on is not a launch.  The advisor serves
    only when every owner-reserved launch input is recorded and measured.
    ``None`` = open; otherwise the (internal, never published) reason."""
    from src.valuation_math import fairness_bands  # noqa: PLC0415

    cfg = advisor_config()
    if cfg.get("responseFloorMs") is None:
        return "response_floor_unset"
    receipt = fairness_bands.receipt()
    if cfg.get("approvedFairnessVersion") != receipt.get("version"):
        return "fairness_version_unapproved"
    if receipt.get("status") == "PROVISIONAL":
        return "fairness_bands_provisional"
    permission_problem = _source_permission_problem(cfg.get("approvedSourcePermissionRecord"))
    if permission_problem is not None:
        return (
            "source_permission_unrecorded"
            if permission_problem == "unrecorded"
            else f"source_permission_invalid:{permission_problem}"
        )
    if not public_advisor.package_model_ready():
        return "package_model_unavailable"
    return None


def _gate(league_key: str) -> tuple[Any, str | None, JSONResponse | None]:
    """Flag → launch gate → league → ONE captured contract.
    ``(contract, key, error)``."""
    from src.api.feature_flags import is_enabled

    if not is_enabled("brisket_trade_advisor"):
        return None, None, _error(503, "advisor_unavailable", "disabled")
    if _launch_gate_reason() is not None:
        return None, None, _error(503, "advisor_unavailable", "not_ready")
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


def _rosters_out(snap: Any) -> RostersOut:
    return RostersOut(state=snap.rosters_state, asOf=snap.rosters_as_of)


def _ok(body: BaseModel) -> JSONResponse:
    return JSONResponse(content=_safe_dump(body), headers={"Cache-Control": _NO_STORE})


# ── Routes ─────────────────────────────────────────────────────────────────


@router.get("/api/public/league/trade-advisor/teams")
async def get_trade_advisor_teams(request: Request, leagueKey: str = ""):
    """The league's teams for the team-selection step."""
    try:
        contract, key, err = _gate(leagueKey)
        if err is not None:
            return err
        snap = public_advisor.snapshot(contract, league_key=key)
        return _ok(
            TeamsResponse(
                leagueKey=key,
                generation=public_advisor.public_generation(snap),
                limits=LimitsOut(
                    minTeams=public_advisor.MIN_TEAMS,
                    maxTeams=min(_config_max_teams(), int(snap.team_count)),
                    maxLegs=_config_max_legs(),
                ),
                rosters=_rosters_out(snap),
                teams=[
                    TeamOut(rosterId=t.roster_id, displayName=t.display_name, teamName=t.team_name)
                    for t in public_advisor.list_teams(snap)
                ],
            )
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
    request: Request,
    rosterId: str,
    sort: str = public_advisor.SORT_POSITION_ALPHA,
    leagueKey: str = "",
):
    """One team's players and owned picks in the ONE identity order
    (side, position, label).  Identities and labels only; no value ever
    decides the order."""
    try:
        contract, key, err = _gate(leagueKey)
        if err is not None:
            return err
        rid = _parse_roster_id(rosterId)
        if rid is None:
            return _error(400, "invalid_request", "invalid_roster_id", field="rosterId")
        if sort not in public_advisor.SORTS:
            return _error(400, "invalid_request", "unsupported_sort", field="sort")
        snap = public_advisor.snapshot(contract, league_key=key)
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
        return _ok(
            AssetsResponse(
                leagueKey=key,
                generation=public_advisor.public_generation(snap),
                rosterId=rid,
                sort="position_alpha",
                pickOwnership=pick_state,
                rosters=_rosters_out(snap),
                assets=out,
            )
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


def _floor_ms(team_count: int | None) -> int | None:
    """The configured floor for this request.  A per-``teamCount`` table uses
    the request's own count when it parsed, else the table's maximum (so a
    malformed request is never faster than a valid one)."""
    floor = advisor_config().get("responseFloorMs")
    if isinstance(floor, dict):
        if team_count is not None and team_count in floor:
            return int(floor[team_count])
        return max(floor.values()) if floor else None
    return int(floor) if isinstance(floor, int) else None


async def _apply_floor(started: float, team_count: int | None) -> None:
    """Hold an analyze answer until the measured floor has elapsed, so its
    latency does not encode which path ran.  A response that already
    exceeded the floor is logged (the floor is then mis-measured)."""
    floor_ms = _floor_ms(team_count)
    if not floor_ms:
        return
    remaining = floor_ms / 1000.0 - (_clock() - started)
    if remaining > 0:
        await _sleep(remaining)
    else:
        _LOG.warning(
            "public advisor response exceeded the floor (%d ms, teamCount=%s)",
            floor_ms,
            team_count,
        )


#: Public single-flight: identical concurrent ledgers on one generation share
#: one computation.  Separate from every private flight, keyed WITHOUT the
#: perspective (spec §2.11).
_ANALYZE_FLIGHTS: Any = None
_FLIGHTS_LOCK = threading.Lock()


def _flights() -> Any:
    global _ANALYZE_FLIGHTS
    with _FLIGHTS_LOCK:
        if _ANALYZE_FLIGHTS is None:
            from src.api.trade_analyze_runtime import AsyncSingleFlight  # noqa: PLC0415

            _ANALYZE_FLIGHTS = AsyncSingleFlight()
        return _ANALYZE_FLIGHTS


def _flight_key(league_key: str, snap: Any, ledger: Any) -> tuple[str, ...]:
    return (
        "public-advisor",
        "market_fairness",
        league_key,
        str(snap.generation),
        hashlib.sha256(ledger.canonical_key().encode("utf-8")).hexdigest(),
    )


def _admission() -> Any:
    from src.api.compute_admission import ROUTE_PUBLIC_ADVISOR, admission_for  # noqa: PLC0415

    return admission_for(ROUTE_PUBLIC_ADVISOR)


async def _evaluate(league_key: str, snap: Any, ledger: Any) -> public_advisor.FairnessResult:
    """One shared computation per identical ledger (single-flight), each
    computation in an admission slot, the caller's wait bounded by the
    admission deadline (R2-5; ``src/api/compute_admission.py``).  Raises
    ``AdmissionRejected`` (busy / timeout) — never a partial result."""
    admission = _admission()

    async def _run() -> public_advisor.FairnessResult:
        return await admission.admit(
            lambda: run_in_threadpool(public_advisor.evaluate, snap, ledger)
        )

    result, _joined = await admission.within_deadline(
        lambda: _flights().run(_flight_key(league_key, snap, ledger), _run)
    )
    return result


def _analyze_body(
    key: str,
    snap: Any,
    perspective: int,
    expected_generation: str | None,
    result: public_advisor.FairnessResult,
) -> AnalyzeResponse:
    from src.valuation_math import fairness_bands  # noqa: PLC0415

    generation = public_advisor.public_generation(snap)
    o = result.overall
    return AnalyzeResponse(
        status="success",
        leagueKey=key,
        generation=generation,
        fairnessVersion=str(fairness_bands.receipt()["version"]),
        snapshotChanged=None if expected_generation is None else expected_generation != generation,
        rosters=_rosters_out(snap),
        teamCount=result.team_count,
        perspectiveRosterId=int(perspective),
        overall=OverallOut(
            result=o.result,
            label=o.label,
            reasonCode=o.reason_code,
            reasonText=o.reason_text,
            note=o.note,
        ),
        teams=[
            TeamResultOut(
                rosterId=t.roster_id,
                result=t.result,
                label=t.label,
                reasonCode=t.reason_code,
                reasonText=t.reason_text,
                unavailableAssetIds=list(t.unavailable_asset_ids),
            )
            for t in result.teams
        ],
        trade=[LegOut(id=leg.id, **{"from": leg.from_rid}, to=leg.to_rid) for leg in result.legs],
    )


@router.post("/api/public/league/trade-advisor/analyze")
async def post_trade_advisor_analyze(request: Request, leagueKey: str = ""):
    """Is this trade fair?  Per-team FAIR / NOT FAIR / UNABLE TO DETERMINE for
    every team of a 2-4-team trade, plus the overall result, in one response.
    Never a value, gap, band, category or recommendation."""
    try:
        contract, key, err = _gate(leagueKey)
    except Exception as exc:  # noqa: BLE001
        _log_failure("analyze-gate", exc)
        return _error(503, "advisor_unavailable", "upstream_unavailable")
    if err is not None:
        return err
    started = _clock()
    team_count: int | None = None
    try:
        # Charge the limiter BEFORE reading or validating anything.
        limited, retry = _limiter().charge(_charges_for(_host()._client_ip_from_request(request)))
        if limited:
            return _error(
                429,
                "rate_limited",
                headers={"Retry-After": str(int(retry))},
                retryAfterSeconds=int(retry),
            )
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
        team_count = len(set(req.teams))

        snap = public_advisor.snapshot(contract, league_key=key)
        policy = public_advisor.public_policy(
            max_teams=_config_max_teams(), max_legs=_config_max_legs()
        )
        ledger = public_advisor.validate(
            snap,
            perspective=req.perspectiveRosterId,
            teams=list(req.teams),
            legs=[(leg.id, leg.from_, leg.to) for leg in req.assets],
            policy=policy,
        )
        result = await _evaluate(key, snap, ledger)
        body = _analyze_body(key, snap, req.perspectiveRosterId, req.expectedGeneration, result)
        return JSONResponse(content=_safe_dump(body), headers={"Cache-Control": _NO_STORE})
    except public_advisor.AdvisorError as exc:
        return _from_advisor_error(exc)
    except Exception as exc:  # noqa: BLE001 — engine refusal, invariant, assertion
        from src.api.compute_admission import AdmissionRejected  # noqa: PLC0415
        from src.trade import analyze_service  # noqa: PLC0415

        if isinstance(exc, AdmissionRejected):
            # R2-5: retryable, fixed copy, held to the floor like every outcome.
            return _error(
                503,
                "advisor_unavailable",
                exc.reason,
                headers={"Retry-After": str(exc.retry_after_seconds)},
                retryAfterSeconds=exc.retry_after_seconds,
            )
        if isinstance(exc, analyze_service.PackageModelUnavailable):
            return _error(503, "advisor_unavailable", "not_ready")
        _log_failure("analyze", exc)
        return _error(503, "advisor_unavailable", "upstream_unavailable")
    finally:
        # Every outcome after the limiter charge — success, 400, 409, 413,
        # 415, 429, 503 — waits out the measured floor.
        await _apply_floor(started, team_count)
