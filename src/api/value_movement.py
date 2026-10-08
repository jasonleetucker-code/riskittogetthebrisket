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

# Today's vote state for a source the ledger has no history for (current
# board only — read from the row's own stamp).
TODAY_VOTED = "voted_today"
TODAY_NOT_VOTING = "not_voting_today"
TODAY_VOTE_UNPUBLISHED = "vote_state_unpublished"


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


def _today_role(source_key: str, row: Mapping[str, Any]) -> str:
    """What a source is doing on TODAY's row: benchmark / held from the
    owners; otherwise voted or not from the row's own stamp
    (``sourceRankMeta[k].contributedToBlend``), and unpublished when the row
    carries no stamp — never guessed as a vote."""
    role = source_role(source_key)
    if role != ROLE_MODEL_INPUT:
        return role
    meta = row.get("sourceRankMeta")
    entry = meta.get(source_key) if isinstance(meta, Mapping) else None
    if not isinstance(entry, Mapping):
        return TODAY_VOTE_UNPUBLISHED
    return TODAY_NOT_VOTING if entry.get("contributedToBlend") is False else TODAY_VOTED


def _current_unrecorded_sources(row: Mapping[str, Any]) -> list[dict[str, str]]:
    """Sources carrying a value on TODAY's row that the ledger never records
    per generation (rank-signal sources), each with its role today.  Current
    state only."""
    site = row.get("canonicalSiteValues")
    if not isinstance(site, Mapping):
        return []
    recorded = set(record.LEDGER_SOURCE_KEYS)
    return [
        {"source": k, "role": _today_role(k, row)}
        for k, v in sorted(site.items())
        if k not in recorded and (n := _num(v)) is not None and n > 0
    ]


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
        "scrapeTimestamp": contract.get("scrapeTimestamp"),
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
    # The served scrape instant pins never-future to the board on screen and
    # lets "is the ledger's current end this board" compare instants, not
    # dates (several scrapes share a date).
    out = movement.value_movement(
        asset_key,
        as_of=board_date,
        served_instant=contract.get("scrapeTimestamp"),
        path=path,
    )
    for s in out.get("sources") or []:
        s["role"] = source_role(s["source"])
    out["player"] = row.get("displayName") or row.get("canonicalName")
    out["playerId"] = row.get("playerId")
    out["liveBoard"] = live
    out["currentGenerationIsLiveBoard"] = out.get("currentIsServedGeneration")
    out["currentGenerationIsLiveBoardBasis"] = out.get("currentIsServedGenerationBasis")
    out["currentContext"] = current_context
    return out
