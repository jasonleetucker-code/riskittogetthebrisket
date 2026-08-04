"""What actually happened next.

A signal is only worth shipping if it beats the alternative of doing
nothing, and that can only be established against realised outcomes.
This module supplies the outcome side of the panel.

**The outcome measured here is market movement, not production.**  Those
are different questions with different right answers — a player can be
underpriced *and* score badly — and the discovery report was right that
merging them silently is the central modelling trap.  Market movement is
measured here because it is the one the repository's data can answer
honestly: 110 days of committed source boards.  Production outcomes need
per-player realised fantasy points scored under this league's exact
settings, which exists (``src/nfl_data/realized_points``) but has no
overlap with this panel — the window is the 2026 offseason, where no
games were played.  Rather than invent a production target from an
off-season panel, this module measures what it can and says so.

**Excess return, not raw return.**  If the whole board drifts up 3% in a
fortnight, a player who rose 3% has told us nothing.  Raw return would
score every player in a rising market as a successful "buy" call and make
any signal look predictive in exactly the periods it was least useful.
So the outcome is a player's return minus the median return of his
cohort — the same position-family × value-tier cohort the mispricing
score is measured in, so the two are commensurable.

**The market anchor is the outcome instrument.**  We ask whether the
market moved toward our fair value, so the "after" price must come from
the same board the "before" price did — otherwise a change of instrument
would register as a market move.
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import Any, Iterable

from src.consensus_edge.fair_value import MARKET_ANCHOR_BY_ASSET_CLASS, _market_value, _row_key
from src.consensus_edge.mispricing import cohort_key

# Reasons an outcome cannot be computed for a row.
NO_FUTURE_PRICE = "no_price_at_horizon"
NO_START_PRICE = "no_price_at_origin"
NO_COHORT = "no_cohort_peers_at_horizon"


def market_prices(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``{playerKey: {price, assetClass, position}}`` from a built contract.

    Reads the anchor's own published value, matching what
    ``fair_value_index`` calls ``marketValue`` so origin and horizon
    prices are the same quantity.
    """
    out: dict[str, dict[str, Any]] = {}
    for row in contract.get("playersArray") or []:
        key = _row_key(row)
        if not key:
            continue
        asset_class = str(row.get("assetClass") or "")
        anchor = MARKET_ANCHOR_BY_ASSET_CLASS.get(asset_class)
        if not anchor:
            continue
        price = _market_value(row, anchor)
        if price is None:
            continue
        out[key] = {
            "price": price,
            "assetClass": asset_class,
            "position": row.get("position"),
        }
    return out


def forward_returns(
    origin_prices: dict[str, dict[str, Any]],
    horizon_prices: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Per-player raw and cohort-excess return between two price maps.

    Returns ``{playerKey: {rawReturn, excessReturn, cohort, reason}}``.
    A row that cannot be measured carries ``None`` returns and a reason
    rather than being dropped here, because "we could not measure this
    player" and "this player did not move" must not look alike to the
    evaluation that consumes them.

    That is only half the guarantee, and the half this function controls.
    Every consumer then filters on ``excessReturn is not None``, so the
    drop happens one layer down — see :func:`attrition`, which is how a
    consumer reports it instead of inheriting it silently.
    """
    raw: dict[str, dict[str, Any]] = {}
    for key, start in origin_prices.items():
        entry: dict[str, Any] = {
            "rawReturn": None,
            "excessReturn": None,
            "cohort": None,
            "reason": None,
        }
        end = horizon_prices.get(key)
        start_price = start.get("price")
        if not start_price or start_price <= 0:
            entry["reason"] = NO_START_PRICE
            raw[key] = entry
            continue
        if end is None or not end.get("price") or end["price"] <= 0:
            entry["reason"] = NO_FUTURE_PRICE
            raw[key] = entry
            continue
        entry["rawReturn"] = (end["price"] - start_price) / start_price
        # Cohort is fixed at the ORIGIN price.  Using the horizon price
        # would let a player who moved tiers be judged against a peer
        # group he only joined because of the move being measured.
        entry["cohort"] = cohort_key(start.get("position"), float(start_price))
        raw[key] = entry

    by_cohort: dict[str, list[float]] = {}
    for entry in raw.values():
        if entry["rawReturn"] is not None and entry["cohort"]:
            by_cohort.setdefault(entry["cohort"], []).append(entry["rawReturn"])

    medians = {k: statistics.median(v) for k, v in by_cohort.items() if len(v) >= 3}
    for entry in raw.values():
        if entry["rawReturn"] is None:
            continue
        median = medians.get(entry["cohort"] or "")
        if median is None:
            entry["reason"] = NO_COHORT
            continue
        entry["excessReturn"] = entry["rawReturn"] - median
    return raw


def attrition(
    player_keys: "Iterable[str]",
    returns: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """How many of ``player_keys`` could not be scored, and why.

    ``{"of": n, "dropped": n, "rate": f, "byReason": {reason: n}}``.

    **The dropped rows are not a random sample.** A player who leaves the
    anchor's board between origin and horizon has usually been dropped
    *by* the market — which is systematically the worst outcome there is,
    and precisely the one a buy list needs to be charged for. Filtering
    on ``excessReturn is not None`` and reporting only what survives is
    survivorship bias; reporting the rate beside the headline turns it
    into a stated limit a reader can weigh.

    A key with no entry at all is counted under ``not_in_panel`` rather
    than ignored: a row the board scored and the outcome layer never saw
    is the same kind of silence.
    """
    total = 0
    dropped = 0
    by_reason: dict[str, int] = {}
    for key in player_keys:
        total += 1
        entry = returns.get(key)
        if entry is not None and entry.get("excessReturn") is not None:
            continue
        dropped += 1
        reason = str((entry or {}).get("reason") or "not_in_panel")
        by_reason[reason] = by_reason.get(reason, 0) + 1
    return {
        "of": total,
        "dropped": dropped,
        "rate": (dropped / total) if total else None,
        "byReason": dict(sorted(by_reason.items())),
    }


def horizon_date(origin: date, horizon_days: int, available: list[date]) -> date | None:
    """The first available date at or after ``origin + horizon_days``.

    Snapping forward rather than requiring an exact hit keeps a fold
    usable when the panel has a gap, and snapping FORWARD specifically
    (never backward) guarantees the holding period is at least the
    requested length — a backward snap would shorten the horizon and
    quietly bias returns toward zero.
    """
    target = origin + timedelta(days=horizon_days)
    for candidate in available:
        if candidate >= target:
            return candidate
    return None
