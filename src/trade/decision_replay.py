"""Historical replay of the canonical trade decision, ASSET-ONLY (TC-C).

What it answers: "what would the decision owner have said about this trade,
on the values that were known at time T?"  Every asset value comes from the
temporal ledger through ``src.history.asof.batch_known_before`` (instant-strict:
a future observation is never selectable; before ``HISTORY_FLOOR`` the answer
is unavailable, never interpolated).  The values are then handed to the SAME
``analyze_trade`` -> ``trade_decision.decide`` path a live request uses, with
Team Context off.  No second decision engine and no second valuation.

What it does not answer, and why (recorded, not faked):

* **Team-context replay is DEFERRED.**  The roster benefit, roster capacity and
  competitive posture lenses need the team's roster, league roster rules,
  projections and posture AS OF T.  The ledger holds asset values only; there
  is no as-of store for rosters, projections or posture, so a team-context
  replay would have to read today's state and present it as contemporaneous --
  the exact error point-in-time integrity forbids.
* A value the ledger cannot provide at T is missing, so the replayed decision
  is the owner's missing-evidence headline naming it -- never a value of 0, never today's value.

Two opt-in leakage guards, both pass-throughs to the ledger owner (defaults keep
the original output byte-identical):

* ``max_age_days`` -- by default a nearest-prior value of ANY age prices an
  asset (an asset last observed months before T is still priced from that old
  value).  With a budget, an older observation is refused: the asset is reported
  unpriced (``missingReason: "outside_max_age"``) with the nearest prior date,
  its distance and the fidelity, and the decision names the missing evidence.
* ``knowledge_cutoff`` -- bounds the ledger's TRANSACTION time (bitemporal read,
  ``src.history.asof``): observations and corrections recorded after the cutoff
  are ignored, so a later backfill or correction cannot leak into the replay.

Pure apart from the read-only ledger query; it executes nothing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from src.history import asof, keys
from src.trade.analyze_trade import analyze_trade

REPLAY_VERSION = "trade_decision_replay_v1"
TEAM_CONTEXT_REPLAY = {
    "state": "deferred",
    "reason": "no as-of store exists for rosters, league roster rules, projections or "
    "posture; replaying with today's state would present it as contemporaneous",
}
_PRICED = (asof.FIDELITY_EXACT, asof.FIDELITY_NEAREST_PRIOR)


def asset_key_for(item: dict[str, Any]) -> str | None:
    """The ledger key for one replay item, through the identity owners.

    ``assetKey`` wins when the caller has it; otherwise a pick name keys through
    the pick owner, a player through its platform id (or identity-grade name)."""
    if item.get("assetKey"):
        key = str(item["assetKey"])
        return key if keys.is_valid_asset_key(key) else None
    name = item.get("name")
    if item.get("assetClass") == "pick" or (name and keys.pick_asset_key(name)):
        return keys.pick_asset_key(name)
    if item.get("playerId") or item.get("position"):
        return keys.player_asset_key(item.get("playerId"), name, item.get("position"))
    return keys.name_key_for_class(name, str(item.get("assetClass") or ""))


def replay_asset_only(
    sending: Sequence[dict[str, Any]],
    receiving: Sequence[dict[str, Any]],
    at: datetime,
    *,
    ledger_path: Path | None = None,
    max_age_days: int | None = None,
    knowledge_cutoff: datetime | None = None,
) -> dict[str, Any]:
    """Replay one trade's decision on values known at ``at`` (UTC-aware).

    ``sending`` / ``receiving`` items: ``{"name", "assetKey"?, "playerId"?,
    "position"?, "assetClass"?}`` from the selected team's point of view.

    ``max_age_days`` / ``knowledge_cutoff`` are opt-in leakage guards passed
    straight to ``asof.batch_known_before`` (module docstring).  Their defaults
    (``None``) reproduce the original call and output exactly.
    """
    if max_age_days is not None and (isinstance(max_age_days, bool) or max_age_days < 0):
        raise ValueError("max_age_days must be a non-negative integer or None")
    guards: dict[str, Any] = {}
    if max_age_days is not None:
        guards["max_age_days"] = max_age_days
    if knowledge_cutoff is not None:
        # Refused up front (not only inside the ledger read, which is skipped
        # when no asset key resolves) and stamped in UTC like the ledger does.
        if knowledge_cutoff.tzinfo is None:
            raise asof.ObservationError("knowledge_cutoff must be UTC-aware")
        knowledge_cutoff = knowledge_cutoff.astimezone(timezone.utc)
        guards["knowledge_cutoff"] = knowledge_cutoff
    items = [("sending", dict(x)) for x in sending] + [("receiving", dict(x)) for x in receiving]
    keyed = [asset_key_for(x) for _, x in items]
    requests = [(k, at) for k in keyed if k]
    found = (
        iter(asof.batch_known_before(requests, path=ledger_path, **guards)["results"])
        if requests
        else iter(())
    )
    assets: list[dict[str, Any]] = []
    sim: dict[str, Any] = {"sending": [], "receiving": [], "teamContext": {"applied": False}}
    for (side, item), key in zip(items, keyed):
        res = next(found) if key else None
        priced = res is not None and res.get("fidelity") in _PRICED and res.get("value") is not None
        value = float(res["value"]) if priced else None
        record = {
            "side": side,
            "name": item.get("name"),
            "assetKey": key,
            "fidelity": res.get("fidelity") if res else asof.FIDELITY_UNAVAILABLE,
            "observedDate": res.get("observedDate") if res else None,
            "missingReason": None
            if priced
            else (res.get("missingReason") if res else "asset_key_unresolved"),
        }
        if guards and res is not None:
            # Opt-in only, so the default record shape is unchanged: a refused
            # stale value states how old the nearest prior observation was.
            record["nearestPriorDate"] = res.get("nearestPriorDate")
            record["nearestPriorDistanceDays"] = res.get("nearestPriorDistanceDays")
            record["distanceDays"] = res.get("distanceDays")
        assets.append(record)
        sim[side].append(
            {
                "name": item.get("name"),
                "value": value,
                "assetClass": item.get("assetClass"),
            }
        )
        if not key:
            sim.setdefault("unresolvedIn" if side == "receiving" else "unresolvedOut", []).append(
                item.get("name")
            )
    analysis = analyze_trade(
        sim,
        provenance={"boardStamp": None, "replayAsOf": at.isoformat()},
    )
    out = {
        "version": REPLAY_VERSION,
        "asOf": at.isoformat(),
        "mode": "asset_only",
        "historyFloor": asof.HISTORY_FLOOR,
        "assets": assets,
        "decision": analysis["decision"],
        "teamContextReplay": dict(TEAM_CONTEXT_REPLAY),
        "executes": False,
    }
    if guards:
        out["leakageGuards"] = {
            "maxAgeDays": max_age_days,
            "knowledgeCutoff": knowledge_cutoff.isoformat()
            if knowledge_cutoff is not None
            else None,
        }
    return out
