"""Brisket Trade Advisor — the public, fairness-only reduction of the shared
N-team trade engine.

Owner directive 2026-10-20 + its same-day FAIRNESS-ONLY AMENDMENT; interface
spec ``docs/trade/NTEAM_TRADE_ENGINE_SPEC.md`` §4.  The public advisor answers
one neutral question — *is this trade fair?* — for 2-, 3- and 4-team trades:

* per participating team: FAIR / NOT_FAIR / UNABLE_TO_DETERMINE;
* overall: FAIR only when EVERY team is fair (three-valued AND, spec §2.9).

It never tells anyone to take or pass on a trade, and never publishes a value,
gap, band level, percentage, category, decision headline or any Team Context
inference.

This module is the pure half (no FastAPI) and holds NO business logic:

1. **Snapshot / ledger** — the ONE owner ``src/trade/trade_ledger.py``
   (``snapshot_for`` + ``validate_ledger``), the same snapshot the private
   ``/api/trade/analyze-multi`` route reads.  Roster freshness comes from
   the ONE reader ``src/api/roster_freshness.py`` through that owner.
2. **Evaluation** — ``analyze_service.analyze_trade_n(mode="market_fairness")``,
   the ONE N-team composer.  Fairness per team is
   ``team_verdicts.team_fairness`` (the asset evidence gates, then the band
   ``fairness_bands`` classified for that team's own adjusted package
   totals under the active ``geom_q078_v1`` package model).
3. **Reduction** — :func:`reduce_fairness` maps that result onto fixed copy.
   Its signature accepts only, per team, ``(rosterId, state, reasonCode,
   unavailable ids)`` plus the overall state and the canonical legs, so
   nothing from the decision engine (values, gaps, categories, posture) can
   reach a public body (spec §4.3 step 6, P1a).
4. **Lists** — team and asset IDENTITIES only.  Assets are ordered by a
   pure function of (side, position, label, id) — never by a board value
   (privacy M2, SD-8) — and ``evaluable`` is answered by the simulator's own
   asset resolution, the path that feeds the engine's evidence gates.
5. **Value-free enforcement** — :func:`assert_advisor_payload_value_free`,
   applied to every outbound body after ``assert_public_payload_safe``.

All public text lives in the tables below and only here.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from src.identity.picks import (
    parse_league_pick_id,
    round_suffix,
    team_pick_ownership_unavailable_reason,
)
from src.trade import team_verdicts
from src.utils.name_clean import normalize_position

_LOG = logging.getLogger(__name__)

ADVISOR_VERSION = "brisket_trade_advisor_v2"
#: The ONE public asset order (privacy M2).  Value orders were removed.
SORT_POSITION_ALPHA = "position_alpha"
SORTS = (SORT_POSITION_ALPHA,)
MIN_TEAMS = 2
OFFENSE = frozenset({"QB", "RB", "WR", "TE", "K"})
DEFENSE = frozenset({"DL", "LB", "DB"})
_SIDE_ORDER = {"offense": 0, "defense": 1, "other": 2}
_POSITION_ORDER = {p: i for i, p in enumerate(("QB", "RB", "WR", "TE", "K", "DL", "LB", "DB"))}

# ── Public copy (spec §4.4) — the ONLY public text ─────────────────────────

FAIR = "FAIR"
NOT_FAIR = "NOT_FAIR"
UNABLE_TO_DETERMINE = "UNABLE_TO_DETERMINE"
RESULTS = (FAIR, NOT_FAIR, UNABLE_TO_DETERMINE)

#: Engine fairness state -> public result.
_STATE_TO_RESULT = {
    team_verdicts.FAIR: FAIR,
    team_verdicts.NOT_FAIR: NOT_FAIR,
    team_verdicts.UNABLE: UNABLE_TO_DETERMINE,
}

#: Reserved for the OVERALL result (owner amendment wording).
OVERALL_LABELS = {
    FAIR: "FAIR TRADE",
    NOT_FAIR: "NOT FAIR",
    UNABLE_TO_DETERMINE: "UNABLE TO DETERMINE",
}
#: Per-team rows (SD-14): a team row reading "FAIR TRADE" beside an overall
#: "NOT FAIR" would contradict itself.
TEAM_LABELS = {
    FAIR: "FAIR FOR THIS TEAM",
    NOT_FAIR: "NOT FAIR FOR THIS TEAM",
    UNABLE_TO_DETERMINE: "UNABLE TO DETERMINE",
}

TEAM_REASON_TEXT = {
    "within_fairness_threshold": "This trade is within our fairness threshold for this team.",
    "outside_fairness_threshold": (
        "This trade falls outside our fairness threshold for this team."
    ),
    "asset_not_evaluable": (
        "One or more assets this team sends or receives can't be valued right now."
    ),
    "ownership_unverifiable": (
        "We couldn't confirm who owns every asset this team sends or receives."
    ),
    "evaluation_unavailable": "This trade can't be evaluated reliably right now.",
}
OVERALL_REASON_TEXT = {
    "all_teams_fair": "The trade is within our fairness threshold for every team.",
    "not_all_teams_fair": ("The trade falls outside our fairness threshold for at least one team."),
    "evidence_insufficient": ("There isn't enough reliable information to judge this whole trade."),
}
MULTI_TEAM_NOTE = "A trade with more than two teams is fair only when it is fair for every team."

#: Which reason codes are legal for which result (fail closed on anything else).
_TEAM_REASONS_BY_RESULT = {
    FAIR: ("within_fairness_threshold",),
    NOT_FAIR: ("outside_fairness_threshold",),
    UNABLE_TO_DETERMINE: (
        "asset_not_evaluable",
        "ownership_unverifiable",
        "evaluation_unavailable",
    ),
}
_OVERALL_REASON_BY_RESULT = {
    FAIR: "all_teams_fair",
    NOT_FAIR: "not_all_teams_fair",
    UNABLE_TO_DETERMINE: "evidence_insufficient",
}
#: Reasons whose ``unavailableAssetIds`` name the assets concerned.
_ID_REASONS = frozenset({"asset_not_evaluable", "ownership_unverifiable"})

#: Fixed error copy per (error, reason).  Never an exception message, never
#: an echo of request content (spec §4.4 / §4.5).
ERROR_MESSAGES: dict[tuple[str, str | None], str] = {
    ("invalid_request", "invalid_json"): "The request body is not valid JSON.",
    ("invalid_request", "schema"): "The request does not match the expected format.",
    ("invalid_request", "unsupported_sort"): "That sort order is not supported.",
    ("invalid_request", "invalid_roster_id"): "That team identifier is not valid.",
    ("invalid_trade", "perspective_not_in_trade"): "The selected team must be part of the trade.",
    ("invalid_trade", "too_few_teams"): "A trade needs at least two teams.",
    ("invalid_trade", "duplicate_team"): "A team can only appear once in a trade.",
    ("invalid_trade", "too_many_teams"): "This trade has more teams than the advisor supports.",
    ("invalid_trade", "team_not_in_league"): "One or more teams are not in this league.",
    ("invalid_trade", "empty_trade"): "Add at least one player or pick to the trade.",
    ("invalid_trade", "too_many_assets"): "This trade has too many assets.",
    ("invalid_trade", "unknown_asset"): "One or more assets are not recognized.",
    ("invalid_trade", "duplicate_asset"): "An asset can only appear once in a trade.",
    ("invalid_trade", "invalid_origin"): "Every asset must come from a team in the trade.",
    ("invalid_trade", "invalid_destination"): "Every asset must go to a team in the trade.",
    ("invalid_trade", "destination_is_origin"): "An asset can't be sent to the team that owns it.",
    ("invalid_trade", "idle_team"): "Every team in the trade must send or receive an asset.",
    ("invalid_trade", "one_sided_trade"): (
        "Every team in the trade must both send and receive at least one asset."
    ),
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
    # R2-5 admission control (src/api/compute_admission.py): both retryable.
    ("advisor_unavailable", "busy"): (
        "The trade advisor is busy right now. Please try again in a moment."
    ),
    ("advisor_unavailable", "timeout"): (
        "The trade advisor took too long to answer. Please try again."
    ),
}


class AdvisorError(Exception):
    """A request the advisor refuses, with its public error shape.

    ``extras`` carries only identifiers the caller supplied (asset ids,
    roster ids) — never a value, an actual owner or an engine message.
    """

    def __init__(self, status: int, error: str, reason: str | None = None, **extras: Any) -> None:
        super().__init__(error if reason is None else f"{error}:{reason}")
        self.status = int(status)
        self.error = error
        self.reason = reason
        self.extras = extras


class InvariantViolation(RuntimeError):
    """The engine result could not be reduced consistently — never published
    (the route answers 503 ``upstream_unavailable``)."""


# ── Data shapes ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PublicTeam:
    roster_id: int
    display_name: str
    team_name: str | None


@dataclass(frozen=True)
class PublicAsset:
    id: str
    kind: str  # "player" | "pick"
    label: str
    side: str  # "offense" | "defense" | "other" | "pick"
    position: str | None = None
    nfl_team: str | None = None
    season: int | None = None
    round: int | None = None
    origin_roster_id: int | None = None
    projection: str | None = None
    evaluable: bool = False


@dataclass(frozen=True)
class TeamFairnessInput:
    """Everything :func:`reduce_fairness` may see about one team."""

    roster_id: int
    state: str  # team_verdicts FAIR / NOT_FAIR / UNABLE
    reason_code: str | None
    unavailable_asset_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PublicLeg:
    id: str
    from_rid: int
    to_rid: int


@dataclass(frozen=True)
class PublicTeamResult:
    roster_id: int
    result: str
    label: str
    reason_code: str
    reason_text: str
    unavailable_asset_ids: tuple[str, ...]


@dataclass(frozen=True)
class PublicOverall:
    result: str
    label: str
    reason_code: str
    reason_text: str
    note: str | None


@dataclass(frozen=True)
class FairnessResult:
    """The ONLY evaluation type the router may serialize: public fields only."""

    overall: PublicOverall
    teams: tuple[PublicTeamResult, ...]
    legs: tuple[PublicLeg, ...]
    team_count: int


# ── Engine access (the shared owners only) ────────────────────────────────


def package_model_ready() -> bool:
    """The shared N-team engine's own readiness rule (geom_q078_v1, config ok)."""
    from src.trade import analyze_service  # noqa: PLC0415

    return analyze_service.package_model_ready()


def snapshot(contract: Mapping[str, Any], *, league_key: str) -> Any:
    """The ONE snapshot (``trade_ledger.snapshot_for``) for a request, with the
    league's registry roster settings — the same arguments the private
    ``/api/trade/analyze-multi`` route passes, so both read one memo entry.
    Raises ``AdvisorError(503, not_ready)`` when the contract carries no
    usable league rosters."""
    from src.api import league_registry  # noqa: PLC0415
    from src.trade import trade_ledger  # noqa: PLC0415

    cfg = league_registry.get_league_by_key(league_key)
    try:
        return trade_ledger.snapshot_for(
            contract,
            league_key=league_key,
            roster_settings=dict(getattr(cfg, "roster_settings", None) or {}),
        )
    except LookupError:
        raise AdvisorError(503, "advisor_unavailable", "not_ready") from None


def public_generation(snap: Any) -> str:
    """An opaque public token for the snapshot's board generation (the ledger
    owner's ``generation``, i.e. ``trade_analyze_runtime.contract_generation``).
    The raw build stamp is not published."""
    return hashlib.sha256(f"brisket-advisor-v2|{snap.generation}".encode()).hexdigest()[:16]


def public_policy(*, max_teams: int, max_legs: int) -> Any:
    """The public ledger policy: every team must both send and receive
    (``send_and_receive``, SD-5 / privacy M5)."""
    from src.trade.trade_ledger import LedgerPolicy  # noqa: PLC0415

    return LedgerPolicy(
        min_teams=MIN_TEAMS,
        max_teams=int(max_teams),
        max_legs=int(max_legs),
        participation="send_and_receive",
    )


# ── Lists ──────────────────────────────────────────────────────────────────


def list_teams(snap: Any) -> list[PublicTeam]:
    from src.trade.trade_ledger import team_display_name  # noqa: PLC0415

    out: list[PublicTeam] = []
    for rid in sorted(snap.teams_by_roster_id):
        t = snap.teams_by_roster_id[rid]
        team_name = str(t.get("sleeperTeamName") or "").strip() or None
        out.append(PublicTeam(rid, team_display_name(snap, rid), team_name))
    out.sort(key=lambda pt: (pt.display_name.casefold(), pt.roster_id))
    return out


_INDEX_MEMO: "OrderedDict[int, tuple[Any, dict[str, Any]]]" = OrderedDict()
_INDEX_LOCK = threading.Lock()


def _resolution_indexes(snap: Any) -> dict[str, Any]:
    """The simulator's own resolution indexes for ONE snapshot (memo LRU 2,
    keyed by snapshot identity; the entry holds the snapshot, so its id
    cannot be reused while cached).  Depends on the contract only."""
    from src.api import trade_simulator  # noqa: PLC0415
    from src.api.pick_value_resolution import pick_rows_from_rows  # noqa: PLC0415

    key = id(snap)
    with _INDEX_LOCK:
        hit = _INDEX_MEMO.get(key)
        if hit is not None and hit[0] is snap:
            _INDEX_MEMO.move_to_end(key)
            return hit[1]
    row_index = trade_simulator.asset_row_index(dict(snap.contract))
    idx = {
        "row_index": row_index,
        "player_rows": dict(snap.rows_by_player_id),
        "pick_rows": pick_rows_from_rows(row_index.values()),
    }
    with _INDEX_LOCK:
        _INDEX_MEMO[key] = (snap, idx)
        _INDEX_MEMO.move_to_end(key)
        while len(_INDEX_MEMO) > 2:
            _INDEX_MEMO.popitem(last=False)
    return idx


def reset_memos_for_tests() -> None:
    with _INDEX_LOCK:
        _INDEX_MEMO.clear()


def _evaluable(snap: Any, label: str, *, player_id: str | None, asset_id: str | None) -> bool:
    """Would the engine price this asset?  The simulator's single-asset
    resolution (``trade_simulator.resolve_trade_asset`` — id-first, the
    canonical pick resolver) plus the decision owner's one "priced" rule
    (``trade_decision.asset_is_priced``), i.e. exactly what decides the
    ``off_board_assets`` / ``unpriced_assets`` evidence gates.  A quarantined
    or stale value is still ``evaluable`` (accepted residual, spec §4.2)."""
    from src.api import trade_simulator  # noqa: PLC0415
    from src.trade.trade_decision import asset_is_priced  # noqa: PLC0415

    idx = _resolution_indexes(snap)
    hit = trade_simulator.resolve_trade_asset(
        label,
        contract=dict(snap.contract),
        asset_id=asset_id,
        player_id=player_id,
        row_index=idx["row_index"],
        pick_rows=idx["pick_rows"],
        player_rows=idx["player_rows"],
    )
    return hit is not None and asset_is_priced(hit)


def _pick_label(snap: Any, d: Mapping[str, Any], ident: Any) -> str:
    from src.trade.trade_ledger import team_display_name  # noqa: PLC0415

    season = int(ident.season)
    rnd = int(ident.round_num)
    origin = int(ident.origin_roster_id)
    try:
        owner = int(d.get("ownerRosterId")) if d.get("ownerRosterId") is not None else None
    except (TypeError, ValueError):
        owner = None
    if owner is not None and owner == origin:
        tail = "Own"
    elif origin in snap.teams_by_roster_id:
        tail = f"Originally {team_display_name(snap, origin)}"
    else:
        tail = f"Originally {str(d.get('fromTeam') or '').strip() or f'Team {origin}'}"
    return f"{season} {round_suffix(rnd)} — {tail}"


def _player_order_key(a: PublicAsset) -> tuple[Any, ...]:
    pos = a.position or ""
    return (
        _SIDE_ORDER.get(a.side, 2),
        _POSITION_ORDER.get(pos, len(_POSITION_ORDER)),
        pos,
        a.label.casefold(),
        a.id,
    )


def _pick_order_key(a: PublicAsset) -> tuple[Any, ...]:
    # Every pick asset is built from a parsed canonical id, so season, round
    # and origin are always ints (an identity, never a value).
    return (a.season, a.round, a.origin_roster_id, a.id)


def order_assets(assets: Iterable[PublicAsset]) -> list[PublicAsset]:
    """The ONE public order: players by (side, position, label, id), then
    picks by (season, round, origin, id).  A pure function of identity —
    board values never enter it (privacy M2)."""
    items = list(assets)
    players = sorted((a for a in items if a.kind == "player"), key=_player_order_key)
    picks = sorted((a for a in items if a.kind == "pick"), key=_pick_order_key)
    return [*players, *picks]


def list_team_assets(snap: Any, roster_id: int, *, sort: str) -> tuple[list[PublicAsset], str]:
    """``(assets, pickOwnership)`` for one team in the ``position_alpha`` order.
    When the team's pick ownership is unavailable no pick is listed."""
    from src.trade.trade_ledger import PLAYER_PREFIX, player_label  # noqa: PLC0415

    if sort not in SORTS:
        raise AdvisorError(400, "invalid_request", "unsupported_sort", field="sort")
    team = snap.teams_by_roster_id.get(int(roster_id))
    if team is None:
        raise AdvisorError(404, "unknown_team")
    sleeper = snap.contract.get("sleeper") if isinstance(snap.contract, Mapping) else None
    by_name = sleeper.get("positions") if isinstance(sleeper, Mapping) else None
    positions_by_name: Mapping[str, Any] = by_name if isinstance(by_name, Mapping) else {}

    assets: list[PublicAsset] = []
    seen: set[str] = set()
    for raw in team.get("playerIds") or []:
        pid = str(raw or "").strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        row = snap.rows_by_player_id.get(pid)
        label = player_label(snap, pid)
        pos_raw = (row.get("position") or row.get("pos")) if row else None
        if not pos_raw:
            pos_raw = positions_by_name.get(label)
        pos = normalize_position(pos_raw) or None
        side = "offense" if pos in OFFENSE else "defense" if pos in DEFENSE else "other"
        nfl_team = (str(row.get("team") or "").strip() or None) if row else None
        assets.append(
            PublicAsset(
                id=f"{PLAYER_PREFIX}{pid}",
                kind="player",
                label=label,
                side=side,
                position=pos,
                nfl_team=nfl_team,
                evaluable=_evaluable(snap, label, player_id=pid, asset_id=None),
            )
        )

    pick_state = "observed"
    if team_pick_ownership_unavailable_reason(team) is not None:
        pick_state = "unavailable"
    else:
        for d in team.get("pickDetails") or []:
            if not isinstance(d, Mapping):
                continue
            aid = str(d.get("assetId") or "").strip()
            ident = parse_league_pick_id(aid)
            if ident is None or ident.league_key != snap.league_key or aid in seen:
                continue
            seen.add(aid)
            assets.append(
                PublicAsset(
                    id=aid,
                    kind="pick",
                    label=_pick_label(snap, d, ident),
                    side="pick",
                    season=int(ident.season),
                    round=int(ident.round_num),
                    origin_roster_id=int(ident.origin_roster_id),
                    projection=None,  # OD-2: projected labels OFF
                    evaluable=_evaluable(
                        snap, str(d.get("label") or ""), player_id=None, asset_id=aid
                    ),
                )
            )
    return order_assets(assets), pick_state


# ── Validation (the ledger owner) ─────────────────────────────────────────


def validate(
    snap: Any,
    *,
    perspective: int,
    teams: Sequence[Any],
    legs: Sequence[tuple[str, int, int]],
    policy: Any,
) -> Any:
    """``trade_ledger.validate_ledger`` under the public policy, then the
    API-layer perspective check (spec §2.3).  Raises :class:`AdvisorError`
    with the ledger's own reason code; a 409 never names the actual owner."""
    from src.trade import trade_ledger  # noqa: PLC0415

    try:
        ledger = trade_ledger.validate_ledger(
            snap,
            teams=list(teams),
            legs=[{"id": a, "from": f, "to": t} for a, f, t in legs],
            policy=policy,
        )
    except trade_ledger.LedgerError as err:
        extras: dict[str, Any] = {}
        if err.asset_ids:
            extras["assetIds"] = list(err.asset_ids)
        if err.roster_ids:
            extras["rosterIds"] = list(err.roster_ids)
        raise AdvisorError(err.status, err.error, err.reason, **extras) from None
    if int(perspective) not in ledger.teams:
        raise AdvisorError(
            400, "invalid_trade", "perspective_not_in_trade", rosterIds=[int(perspective)]
        )
    return ledger


# ── Evaluation + reduction ────────────────────────────────────────────────


#: The ONE engine row ``valueState`` a FAIR / NOT_FAIR verdict may rest on.
#: The state is owned by the engine (``analyze_service._value_entry`` /
#: ``analyze_service.VALUE_STATES``: ``priced``, ``unpriced``, ``off_board``,
#: ``not_held``, ``quarantined``, ``stale``); this module reads it and never
#: re-derives it.  Any other state — including one a newer engine adds, a
#: missing state, or a malformed row — fails the team closed (R1-L2 / F2).
_PRICED_STATE = "priced"


def _withheld_value_evidence(entry: Mapping[str, Any]) -> bool:
    """Does this team's side carry an asset the engine does not present as
    priced?  (R1-L2 / F2, public side.)

    Reads ONLY the engine's own row ``valueState`` on the team's ``gives`` /
    ``receives`` rows — one owner.  The public side used to re-read the
    simulation through ``trade_decision.asset_evidence_codes`` as a stand-in
    while the engine rows still said ``priced`` for a quarantined / stale
    value; Lane A (#1882) now carries ``quarantined`` / ``stale`` itself, so
    that second read is deleted rather than kept as a parallel check.

    A row that is not a mapping, or carries no ``valueState``, is NOT priced:
    unknown is never treated as a trustworthy price."""
    rows = [*(entry.get("gives") or []), *(entry.get("receives") or [])]
    return any(not isinstance(r, Mapping) or r.get("valueState") != _PRICED_STATE for r in rows)


def team_fairness_input(entry: Mapping[str, Any]) -> TeamFairnessInput:
    """Pull the four public inputs out of one engine team entry.  Unavailable
    ids name only this team's own ledger assets.

    Fail closed (R1-L2 / F2): if any asset on the team's side has an engine
    ``valueState`` other than ``priced`` (:func:`_withheld_value_evidence`), a
    FAIR / NOT_FAIR state becomes UNABLE ``evaluation_unavailable`` — the
    reason the engine's own gate gives a quarantined / stale value (spec §2.8).
    An engine UNABLE keeps the engine's own reason.  The withheld asset is NOT
    named: whether the public answer may name it is the owner exposure
    decision F-1, and until it is made the answer discloses no more than the
    engine gate already does."""
    raw = entry.get("fairness")
    fairness: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    reason = fairness.get("reasonCode")
    rows = [
        r
        for r in (*(entry.get("gives") or []), *(entry.get("receives") or []))
        if isinstance(r, Mapping)
    ]
    state = str(fairness.get("state"))
    if state in (team_verdicts.FAIR, team_verdicts.NOT_FAIR) and _withheld_value_evidence(entry):
        return TeamFairnessInput(
            roster_id=int(entry["rosterId"]),
            state=team_verdicts.UNABLE,
            reason_code="evaluation_unavailable",
            unavailable_asset_ids=(),
        )
    ids: set[str] = set()
    if reason == "ownership_unverifiable":
        ids |= {str(a) for a in entry.get("unverifiableAssetIds") or []}
        ids |= {str(r.get("assetId")) for r in rows if r.get("valueState") == "not_held"}
    elif reason == "asset_not_evaluable":
        ids |= {
            str(r.get("assetId")) for r in rows if r.get("valueState") in ("unpriced", "off_board")
        }
    own = {str(r.get("assetId")) for r in rows}
    return TeamFairnessInput(
        roster_id=int(entry["rosterId"]),
        state=state,
        reason_code=str(reason) if reason is not None else None,
        unavailable_asset_ids=tuple(sorted(ids & own)),
    )


def _team_result(t: TeamFairnessInput) -> PublicTeamResult:
    result = _STATE_TO_RESULT.get(t.state)
    reason = t.reason_code
    if result is None or reason not in _TEAM_REASONS_BY_RESULT[result]:
        # Fail closed: an unknown state or reason is never a confident result.
        result, reason = UNABLE_TO_DETERMINE, "evaluation_unavailable"
    assert reason is not None
    ids = t.unavailable_asset_ids if reason in _ID_REASONS else ()
    return PublicTeamResult(
        roster_id=int(t.roster_id),
        result=result,
        label=TEAM_LABELS[result],
        reason_code=reason,
        reason_text=TEAM_REASON_TEXT[reason],
        unavailable_asset_ids=tuple(sorted(ids)),
    )


_RESULT_TO_STATE = {
    FAIR: team_verdicts.FAIR,
    NOT_FAIR: team_verdicts.NOT_FAIR,
    UNABLE_TO_DETERMINE: team_verdicts.UNABLE,
}


def reduce_fairness(
    teams: Sequence[TeamFairnessInput],
    *,
    overall_state: str,
    legs: Sequence[Any],
) -> FairnessResult:
    """The public reduction (spec §4.3).  Sees ONLY per-team
    ``(rosterId, state, reasonCode, unavailable ids)``, the engine's overall
    fairness state and the canonical legs (``trade_ledger.Leg``).

    The overall is the engine's ``fairnessOverall`` (three-valued AND); it is
    cross-checked against the per-team states and a disagreement raises
    :class:`InvariantViolation` rather than publishing either.  Every array
    is in canonical order (teams ascending ``rosterId``, legs by asset id)."""
    per_team = sorted((_team_result(t) for t in teams), key=lambda r: r.roster_id)
    recomputed = team_verdicts.fairness_overall([_RESULT_TO_STATE[r.result] for r in per_team])
    if recomputed["state"] != overall_state:
        raise InvariantViolation("overall fairness disagrees with the per-team states")
    result = _STATE_TO_RESULT[overall_state]
    reason = _OVERALL_REASON_BY_RESULT[result]
    public_legs = sorted(
        (
            PublicLeg(str(leg.asset_id), int(leg.from_roster_id), int(leg.to_roster_id))
            for leg in legs
        ),
        key=lambda leg: leg.id,
    )
    return FairnessResult(
        overall=PublicOverall(
            result=result,
            label=OVERALL_LABELS[result],
            reason_code=reason,
            reason_text=OVERALL_REASON_TEXT[reason],
            note=MULTI_TEAM_NOTE if len(per_team) >= 3 else None,
        ),
        teams=tuple(per_team),
        legs=tuple(public_legs),
        team_count=len(per_team),
    )


def evaluate(snap: Any, ledger: Any) -> FairnessResult:
    """Run the shared N-team engine in ``market_fairness`` mode (no Team
    Context, no posture, no capacity, no counterfactuals, nothing written) and
    reduce its result.  Raises the engine's ``PackageModelUnavailable`` /
    ``ConservationViolation`` or :class:`InvariantViolation`; the route maps
    them to 503 and never publishes a partial body."""
    from src.trade import analyze_service  # noqa: PLC0415

    result = analyze_service.analyze_trade_n(
        snap, ledger, mode="market_fairness", counterfactuals=False
    )
    teams = result.get("teams") if isinstance(result, Mapping) else None
    if not isinstance(teams, Mapping) or set(teams) != set(ledger.teams):
        raise InvariantViolation("engine result does not cover every ledger team")
    summary = result.get("summary") if isinstance(result.get("summary"), Mapping) else {}
    overall = (summary.get("fairnessOverall") or {}).get("state")
    return reduce_fairness(
        [team_fairness_input(teams[rid]) for rid in sorted(teams)],
        overall_state=str(overall),
        legs=ledger.legs,
    )


# ── Value-free enforcement (spec §4.6) ─────────────────────────────────────

#: The ONLY integer-valued keys any advisor body may carry (§4.3).  ``from`` /
#: ``to`` / ``perspectiveRosterId`` are roster ids.
ALLOWED_INT_KEYS = frozenset(
    {
        "rosterId",
        "rosterIds",
        "perspectiveRosterId",
        "originRosterId",
        "from",
        "to",
        "teamCount",
        "season",
        "round",
        "minTeams",
        "maxTeams",
        "maxLegs",
        "maxBytes",
        "retryAfterSeconds",
    }
)

#: Names of the private ``TeamAnalysis`` / ``MultiTeamAnalysis`` blocks; none
#: may appear as a key in an advisor body.  (``value`` is deliberately NOT in
#: the global ``public_contract`` blocklist — other public payloads use it.)
ADVISOR_KEY_BLOCKLIST = frozenset(
    {
        "value",
        "valueState",
        "gap",
        "largerAdjustedSide",
        "relativePct",
        "band",
        "level",
        "category",
        "categoryText",
        "headline",
        "decision",
        "simulation",
        "analysis",
        "fairness",
        "packageModel",
        "fairnessBands",
        "decisionRunIds",
        "tradeRunId",
        "analysisTiming",
    }
)

FIXED_TEXT = frozenset(
    [
        *OVERALL_LABELS.values(),
        *TEAM_LABELS.values(),
        *TEAM_REASON_TEXT.values(),
        *OVERALL_REASON_TEXT.values(),
        MULTI_TEAM_NOTE,
        *ERROR_MESSAGES.values(),
    ]
)
#: Free-text keys that must be fixed copy in analyze and error bodies.  In the
#: list bodies ``label`` is an asset's display label (league data).
_FIXED_TEXT_KEYS = ("label", "reasonText", "message", "note")
PAYLOAD_KINDS = ("analyze", "error", "list")


class PayloadNotValueFree(AssertionError):
    pass


def assert_advisor_payload_value_free(body: Any, *, kind: str) -> None:
    """Positive value-free check (spec §4.6 items 2-3).  ``kind`` is
    ``"analyze"``, ``"error"`` or ``"list"``.

    * every int leaf's key (a list item reports its list's key) is in
      :data:`ALLOWED_INT_KEYS`; no float anywhere;
    * no key from :data:`ADVISOR_KEY_BLOCKLIST`;
    * in analyze / error bodies every ``label`` / ``reasonText`` /
      ``message`` / ``note`` string is fixed copy from this module.
    """
    if kind not in PAYLOAD_KINDS:
        raise ValueError(f"unknown payload kind {kind!r}")
    check_text = kind in ("analyze", "error")

    def walk(obj: Any, key: str, path: str) -> None:
        if isinstance(obj, bool) or obj is None:
            return
        if isinstance(obj, float):
            raise PayloadNotValueFree(f"float at {path}")
        if isinstance(obj, int):
            if key not in ALLOWED_INT_KEYS:
                raise PayloadNotValueFree(f"non-allowlisted number at {path}")
            return
        if isinstance(obj, str):
            if check_text and key in _FIXED_TEXT_KEYS and obj not in FIXED_TEXT:
                raise PayloadNotValueFree(f"non-fixed text at {path}")
            return
        if isinstance(obj, Mapping):
            for k, v in obj.items():
                if k in ADVISOR_KEY_BLOCKLIST:
                    raise PayloadNotValueFree(f"blocked key {k!r} at {path}")
                walk(v, str(k), f"{path}.{k}")
            return
        if isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                walk(v, key, f"{path}[{i}]")
            return
        raise PayloadNotValueFree(f"unexpected type {type(obj).__name__} at {path}")

    walk(body, "$", "$")
