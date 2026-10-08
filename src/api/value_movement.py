"""``GET /api/players/{player}/value-movement`` — "why did this value move".

A thin adapter over the history owner (:func:`src.history.movement.value_movement`)
for one row of the loaded canonical contract.  It adds only what the history
layer must not know:

* **Source roles**, read from their canonical owners: KTC Market is the
  benchmark and never a vote (``src/sources/ktc_market.py``); the Signals IDP
  boards are held from voting (``data_contract.PRIVATE_SOURCE_VOTE_HOLDS``).
  The role is TODAY's; whether a source voted at a past generation is not
  recorded and is listed as unobserved.
* **The live board** the reader is looking at — today's value, rank and
  ``rankChange`` — so a ledger that lags the served board (a restart that
  primed without a fresh scrape, say) is visible rather than silently
  disagreeing.
* **Current-board-only context** — the row's present anomaly flags and the
  sources voting today whose per-generation values the ledger does not record.
  Labelled as CURRENT; never presented as historical.

PRIVATE decision intelligence: the route sits behind the session gate (it is
not on the public allowlist), same as ``value-explain``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.history import keys, movement, record
from src.sources.ktc_market import KTC_MARKET_KEY

ROLE_MODEL_INPUT = "model_input"
ROLE_BENCHMARK = "benchmark_not_a_vote"
ROLE_HELD = "held_from_voting"


def _vote_holds() -> Mapping[str, str]:
    try:
        from src.api.data_contract import PRIVATE_SOURCE_VOTE_HOLDS  # noqa: PLC0415
    except Exception:  # noqa: BLE001 — a role label must not break the read
        return {}
    return PRIVATE_SOURCE_VOTE_HOLDS


def source_role(source_key: str) -> str:
    if source_key == KTC_MARKET_KEY:
        return ROLE_BENCHMARK
    if source_key in _vote_holds():
        return ROLE_HELD
    return ROLE_MODEL_INPUT


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _current_unrecorded_sources(row: Mapping[str, Any]) -> list[str]:
    """Sources carrying a value on TODAY's row that the ledger never records
    per generation (rank-signal sources).  Current state only."""
    site = row.get("canonicalSiteValues")
    if not isinstance(site, Mapping):
        return []
    recorded = set(record.LEDGER_SOURCE_KEYS)
    return sorted(k for k, v in site.items() if k not in recorded and (_num(v) or 0) > 0)


def player_value_movement(
    contract: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    board_date = record.contract_board_date(dict(contract))
    keyed = keys.asset_key_for_contract_row(dict(row))
    live = {
        "boardDate": board_date,
        "value": _num(row.get("rankDerivedValue")),
        "rank": row.get("canonicalConsensusRank"),
        "rankChange": row.get("rankChange"),
    }
    current_context = {
        "scope": "current_board_only",
        "anomalyFlags": list(row.get("anomalyFlags") or []),
        "quarantined": bool(row.get("quarantined")),
        "sourcesNotRecordedInLedger": _current_unrecorded_sources(row),
    }
    if keyed is None:
        return {
            "schema": movement.MOVEMENT_SCHEMA,
            "player": row.get("displayName") or row.get("canonicalName"),
            "playerId": row.get("playerId"),
            "status": "unkeyed",
            "missingReason": "asset_has_no_history_key",
            "additive": False,
            "nonAdditiveNote": movement.NON_ADDITIVE_NOTE,
            "evidenceNotCause": True,
            "liveBoard": live,
            "currentContext": current_context,
        }
    asset_key, _asset_class = keyed
    out = movement.value_movement(asset_key, as_of=board_date, path=path)
    for s in out.get("sources") or []:
        s["role"] = source_role(s["source"])
    cur = out.get("current") or {}
    out["player"] = row.get("displayName") or row.get("canonicalName")
    out["playerId"] = row.get("playerId")
    out["liveBoard"] = live
    out["currentGenerationIsLiveBoard"] = None if not cur else cur.get("observedDate") == board_date
    out["currentContext"] = current_context
    return out
