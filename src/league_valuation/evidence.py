"""League utility evidence, read from BDVM's own fundamental output.

One concept, one owner: BDVM owns projection-driven fundamental value. This
module creates no third projection-to-value path; it READS the BDVM values
payload (``src.bdvm.service.run_valuation`` / ``GET /api/bdvm/values``, passed in
as a plain mapping) and states, per player, whether that output can order him
under league utility.

What is read, and from where in the payload::

    players[].fundamental[<strategy>]   balanced-strategy discounted DV (primary order)
    players[].raw.vorg                  signed fpg - R on BDVM's ReplacementEngine
    players[].projection.sources        projection families behind the record
    players[].projection.staleSources   families BDVM itself judged stale
    players[].projection.anyProxy       reconstructed-baseline (proxy) evidence
    meta.projectionSnapshot.asOf        snapshot capture date (freshness)
    unpriced[]                          players BDVM declined to price, with its reason

Explicitly NOT read: ``players[].market`` (the market layer runs after the
fundamentals and would feed the market back into the utility), and
``src.bdvm.market``'s ``fundamental.get("balanced", 0.0)``, which turns a missing
strategy into a zero. Here a missing strategy is ``state='unavailable'`` with a
reason -- never a number.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Mapping

from src.league_valuation.contracts import (
    UTILITY_LINEAGE_MEMBER,
    UtilityEvidence,
)
from src.league_valuation.population import scope_of_position
from src.utils.name_clean import canonical_player_key, normalize_position_family


def evidence_asset_key(player_id: Any, name: Any, position: Any) -> str | None:
    """The temporal-history asset key for a BDVM player entry.

    Same namespace as ``src.history.keys.asset_key_for_contract_row`` (so a
    contract row and its BDVM entry meet on one key): ``player:<sleeperId>`` when
    a platform id exists, else ``name:<canonical_player_key>``. BDVM falls back to
    the NORMALISED NAME as ``playerId`` when the contract row has no platform id,
    so only an all-digit id is treated as a platform id here; anything else takes
    the name grade rather than minting a ``player:`` key from a name.
    """
    pid = str(player_id or "").strip()
    if pid.isdigit():
        return f"player:{pid}"
    if not name:
        return None
    ck = canonical_player_key(str(name), str(position) if position else None)
    return f"name:{ck}" if ck else None


def _parse_instant(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        # A date-only snapshot stamp: the day is known, the instant is not.
        # Treat it as the START of that UTC day so freshness is never overstated.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def snapshot_freshness(
    meta: Mapping[str, Any], *, now: datetime, params: Mapping[str, Any]
) -> tuple[str, str | None, str | None]:
    """``(freshness, asOf, reason)`` for the payload's projection snapshot.

    Unknown capture date is ``missing`` freshness: unmeasurable freshness is not
    freshness. Budget: ``params.freshness.maxSnapshotAgeDays`` (PRIOR)."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    snap = meta.get("projectionSnapshot") if isinstance(meta, Mapping) else None
    snap = snap if isinstance(snap, Mapping) else {}
    as_of = snap.get("asOf")
    if snap.get("asOfUnknown") or snap.get("asOfSource") == "request_time_fallback":
        return "missing", (str(as_of) if as_of else None), "snapshot_as_of_unknown"
    parsed = _parse_instant(as_of)
    if parsed is None:
        return "missing", None, "snapshot_as_of_missing"
    budget_days = float(params["freshness"]["maxSnapshotAgeDays"])
    age_days = (now.astimezone(timezone.utc) - parsed).total_seconds() / 86400.0
    if age_days < 0:
        # A snapshot dated after the evaluation instant cannot have been known.
        return "missing", str(as_of), "snapshot_as_of_after_now"
    if age_days > budget_days:
        return "stale", str(as_of), f"snapshot_age_{age_days:.1f}d_over_{budget_days:g}d"
    return "fresh", str(as_of), None


def quality_for(
    *, families: int, is_proxy: bool, freshness: str, params: Mapping[str, Any]
) -> float:
    """Evidence quality q in [0, 1] from the utility evidence only (PRIOR map)."""
    q_cfg = params["quality"]
    if is_proxy:
        return float(q_cfg["proxy"])
    if freshness != "fresh":
        return float(q_cfg["stale"])
    capped = max(0, min(int(families), int(q_cfg["familiesCap"])))
    return float(q_cfg["byProjectionFamilies"][str(capped)])


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _unavailable(
    key: str,
    *,
    player_id: str | None,
    position: str,
    scope: str,
    as_of: str | None,
    freshness: str,
    reason: str,
    strategy: str,
    state: str = "unavailable",
    families: int = 0,
    is_proxy: bool = False,
    por: float | None = None,
    dv: float | None = None,
    quality: float | None = None,
) -> UtilityEvidence:
    return UtilityEvidence(
        asset_key=key,
        player_id=player_id,
        position=position,
        scope=scope,  # type: ignore[arg-type]
        points_over_replacement=por,
        projection_families=families,
        is_proxy=is_proxy,
        as_of=as_of,
        freshness=freshness,  # type: ignore[arg-type]
        quality=quality,
        lineage_ids=(UTILITY_LINEAGE_MEMBER,),
        state=state,
        reason=reason,
        balanced_dv=dv,
        strategy=strategy,
    )


def utility_evidence_from_bdvm(
    bdvm_payload: Mapping[str, Any],
    *,
    strategy: str = "balanced",
    now: datetime,
    params: Mapping[str, Any],
) -> dict[str, UtilityEvidence]:
    """Per-asset league utility evidence from one BDVM values payload.

    A payload that is not ``status == "ok"`` yields no evidence at all (every
    contract row is then excluded as ``no_utility_evidence`` and keeps its market
    value). A player BDVM unpriced is ``unavailable`` with BDVM's own reason
    (``no_projection`` covers the 2026 rookie class). Missing strategy,
    missing ``raw.vorg``, proxy-only, stale or undated evidence each produce a
    named non-available state -- never a zero.
    """
    if not isinstance(bdvm_payload, Mapping) or bdvm_payload.get("status") != "ok":
        return {}
    meta = bdvm_payload.get("meta") if isinstance(bdvm_payload.get("meta"), Mapping) else {}
    snap_fresh, as_of, snap_reason = snapshot_freshness(meta, now=now, params=params)

    out: dict[str, UtilityEvidence] = {}
    collisions: set[str] = set()

    def _put(ev: UtilityEvidence) -> None:
        if ev.asset_key in out or ev.asset_key in collisions:
            # Two BDVM entries resolving to one asset key is an identity
            # collision: neither may be trusted to order the other.
            collisions.add(ev.asset_key)
            prior = out.pop(ev.asset_key, None)
            base = prior or ev
            out[ev.asset_key] = _unavailable(
                ev.asset_key,
                player_id=base.player_id,
                position=base.position,
                scope=base.scope,
                as_of=as_of,
                freshness=snap_fresh,
                reason="identity_collision_in_bdvm_payload",
                strategy=strategy,
            )
            return
        out[ev.asset_key] = ev

    for entry in bdvm_payload.get("players") or []:
        if not isinstance(entry, Mapping):
            continue
        position = str(entry.get("position") or entry.get("group") or "").upper()
        scope = scope_of_position(position)
        key = evidence_asset_key(entry.get("playerId"), entry.get("name"), position)
        if scope is None or key is None:
            continue
        pid = str(entry.get("playerId") or "").strip()
        player_id = pid if pid.isdigit() else None
        family = normalize_position_family(position) or position

        projection = entry.get("projection") if isinstance(entry.get("projection"), Mapping) else {}
        sources = {str(s) for s in projection.get("sources") or [] if str(s).strip()}
        stale_sources = {str(s) for s in projection.get("staleSources") or [] if str(s).strip()}
        is_proxy = bool(projection.get("anyProxy"))
        fresh_sources = sources - stale_sources
        # BDVM supersedes a proxy record per player once any real source covers
        # him, so ``anyProxy`` normally means proxy-only. If a proxy ever rides
        # beside real sources it is not a projection family of its own.
        families = max(0, len(fresh_sources) - (1 if is_proxy else 0))

        fundamental = (
            entry.get("fundamental") if isinstance(entry.get("fundamental"), Mapping) else {}
        )
        raw = entry.get("raw") if isinstance(entry.get("raw"), Mapping) else {}
        dv = _finite(fundamental.get(strategy)) if strategy in fundamental else None
        por = _finite(raw.get("vorg"))

        freshness = snap_fresh
        reason = snap_reason
        if freshness == "fresh" and sources and not fresh_sources:
            freshness, reason = "stale", "all_projection_sources_stale"

        common: dict[str, Any] = dict(
            player_id=player_id,
            position=family,
            scope=scope,
            as_of=as_of,
            strategy=strategy,
            families=families,
            is_proxy=is_proxy,
            por=por,
            dv=dv,
        )
        if strategy not in fundamental or dv is None:
            _put(
                _unavailable(
                    key, freshness=freshness, reason=f"strategy_missing:{strategy}", **common
                )
            )
            continue
        if por is None:
            _put(
                _unavailable(
                    key, freshness=freshness, reason="points_over_replacement_missing", **common
                )
            )
            continue
        quality = quality_for(
            families=families, is_proxy=is_proxy, freshness=freshness, params=params
        )
        common["quality"] = quality
        if freshness != "fresh":
            state = "stale" if freshness == "stale" else "unavailable"
            _put(_unavailable(key, freshness=freshness, reason=str(reason), state=state, **common))
            continue
        if is_proxy:
            _put(
                _unavailable(
                    key,
                    freshness=freshness,
                    reason="proxy_projection_only",
                    state="partial",
                    **common,
                )
            )
            continue
        if families <= 0:
            _put(_unavailable(key, freshness=freshness, reason="no_projection_family", **common))
            continue
        _put(
            UtilityEvidence(
                asset_key=key,
                player_id=player_id,
                position=family,
                scope=scope,  # type: ignore[arg-type]
                points_over_replacement=por,
                projection_families=families,
                is_proxy=False,
                as_of=as_of,
                freshness="fresh",
                quality=quality,
                lineage_ids=(UTILITY_LINEAGE_MEMBER,),
                state="available",
                reason=None,
                balanced_dv=dv,
                strategy=strategy,
            )
        )

    for entry in bdvm_payload.get("unpriced") or []:
        if not isinstance(entry, Mapping):
            continue
        position = str(entry.get("position") or "").upper()
        scope = scope_of_position(position)
        key = evidence_asset_key(entry.get("playerId"), entry.get("name"), position)
        if scope is None or key is None or key in out:
            continue
        _put(
            _unavailable(
                key,
                player_id=None,
                position=normalize_position_family(position) or position,
                scope=scope,
                as_of=as_of,
                freshness=snap_fresh,
                reason=f"bdvm_unpriced:{entry.get('reason') or 'unstated'}",
                strategy=strategy,
            )
        )
    return out
