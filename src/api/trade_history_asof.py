"""At-the-Time trade grades for the PRIVATE /trades page (owner package 2026-10-17).

Trade History answers three questions about one completed trade (owner spec
SITEWIDE_TRADE_ADJUSTMENT_AND_HISTORY_INTEGRATION):

* **Current Grade** — the trade's assets at TODAY's canonical values, under
  the active package model (computed client-side by
  ``frontend/lib/league-analysis.js``, which routes through the dispatch);
* **At-the-Time Grade** — the SAME assets at the latest value the canonical
  temporal ledger knew strictly before the trade's instant, under the SAME
  model — this module;
* **How It Aged** — the difference between the two adjusted nets.

This is deliberately the SAME computation the public ``/league`` activity
grade uses (``src.public_league.activity._apply_trade_grades``): the same
ledger resolver (``public_activity_valuation.build_asof_valuation`` — players
by canonical key, picks at their generic season/round grade, never a later
draft slot) and the same ``trade_grading.grade_trade_sides`` (which reaches
the Value Adjustment through ``src.valuation_math.package_model``).  So a
private at-the-time grade and the public grade for one trade cannot differ.

Fail-closed, exactly like the public grade: an untrusted instant, or any side
asset the ledger cannot resolve before that instant, makes that side
``available: False`` with the missing assets named — never a partial total,
never today's value, never zero.  Unlike the public payload this private
response carries the numbers (raw sums, adjustment, adjusted net, pct gap),
because the private page needs them to compute aging.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Iterable

from src.api.public_activity_valuation import trade_instant_from_created_at
from src.public_league import trade_grading
from src.public_league.activity import _resolve_side
from src.valuation_math import package_model

Resolver = Callable[[dict[str, Any], datetime | None], float | None]

#: Upper bound on trades per request — a league's whole history is a few
#: hundred; anything larger is not a page asking.
MAX_TRADES = 1000


def asof_requests(trades: Iterable[dict[str, Any]]) -> list[tuple[dict[str, Any], datetime | None]]:
    """Every ``(asset, instant)`` pair the batch needs, for one ledger read."""
    out: list[tuple[dict[str, Any], datetime | None]] = []
    for trade in trades:
        instant = trade_instant_from_created_at(trade.get("createdAt"))
        for side in trade.get("sides") or []:
            for asset in [*(side.get("receivedAssets") or []), *(side.get("sentAssets") or [])]:
                out.append((asset, instant))
    return out


def _unavailable(reason: str, missing: list[dict[str, Any]]) -> dict[str, Any]:
    return {"available": False, "reason": reason, "missingAssets": missing}


def grade_trades_asof(trades: Iterable[dict[str, Any]], resolve: Resolver) -> list[dict[str, Any]]:
    """At-the-time grade for every side of every trade.

    ``trades``: ``[{id, createdAt (epoch ms), sides: [{receivedAssets,
    sentAssets}]}]`` with assets in the public-activity shape
    (``{kind: "player", playerId, playerName, position}`` /
    ``{kind: "pick", season, round}``).
    """
    out: list[dict[str, Any]] = []
    for trade in trades:
        instant = trade_instant_from_created_at(trade.get("createdAt"))
        sides = trade.get("sides") or []
        if instant is None:
            out.append(
                {
                    "id": trade.get("id"),
                    "asOf": None,
                    "sides": [_unavailable("invalid_trade_instant", []) for _ in sides],
                }
            )
            continue
        graded_sides: list[dict[str, Any]] = []
        for side in sides:
            got, got_missing = _resolve_side(side.get("receivedAssets"), resolve, instant)
            gave, gave_missing = _resolve_side(side.get("sentAssets"), resolve, instant)
            missing = got_missing + gave_missing
            if missing:
                graded_sides.append(_unavailable("no_historical_evidence", missing))
                continue
            (result,) = trade_grading.grade_trade_sides([(got, gave)])
            graded_sides.append({"available": True, **result})
        out.append({"id": trade.get("id"), "asOf": instant.isoformat(), "sides": graded_sides})
    return out


def response(trades: list[dict[str, Any]], resolve: Resolver | None) -> dict[str, Any]:
    """The ``POST /api/trades/asof-grades`` payload."""
    base = {"packageModel": package_model.receipt()}
    if resolve is None:
        return {
            **base,
            "available": False,
            "reason": "history_ledger_missing",
            "trades": [
                {
                    "id": t.get("id"),
                    "asOf": None,
                    "sides": [
                        _unavailable("history_ledger_missing", []) for _ in t.get("sides") or []
                    ],
                }
                for t in trades
            ],
        }
    return {**base, "available": True, "trades": grade_trades_asof(trades, resolve)}
