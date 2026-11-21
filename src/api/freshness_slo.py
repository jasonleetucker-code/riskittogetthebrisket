"""Aggregate data-freshness measurements for ``/api/status`` -- the one owner.

Why this exists (audit remediation, 2026-11-18): on 2026-11-17 production's
board had 190 of its top-200 players with ``confidenceAxes.freshness == "low"``
and /trade withheld nearly every asset.  Nothing alerted, because nothing
measured the *share* of the board that was stale -- only per-source stamps.
These numbers are what an external monitor (``scripts/check_production_slo.py``)
asserts on.

Everything here is a pure function over an already-loaded contract: it never
mutates it, reads no file and calls no network.  Output is public-safe numbers
only; the one per-source list (``privateSourceDetail``) is dropped by
``src/api/public_diagnostics.py`` for anonymous callers and served only by the
admin diagnostics route.

MISSING IS NEVER ZERO: with no contract, no ranked rows, or no scrape
timestamp the corresponding value is ``None`` (and ``state`` says
``unknown``), never ``0.0`` -- a zero share would read as "fresh".
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

SCHEMA_VERSION = "freshness-slo.v1"

#: The ranked population the share is measured over (the board's top-N).
TOP_N = 200

#: Staleness verdicts of ``dataFreshness.sourceTimestamps[*].staleness`` that
#: mean a provisioned private source is past its budget (or absent).
_BREACHED_STALENESS = frozenset({"stale", "missing"})


def withheld_value_state(row: Mapping[str, Any] | None) -> str | None:
    """Why a row's value is withheld from decisions, or ``None``.

    The ONE Python owner of the rule; it mirrors
    ``frontend/lib/trade-logic.js::withheldValueState`` (quarantined first,
    then ``confidenceAxes.freshness == "low"``).  The JS function also honours a
    per-asset ``customValue`` override, which is a client-side user input and
    cannot exist on a served contract row.
    """
    if not isinstance(row, Mapping):
        return None
    if row.get("quarantined") is True:
        return "quarantined"
    axes = row.get("confidenceAxes")
    if isinstance(axes, Mapping) and axes.get("freshness") == "low":
        return "stale"
    return None


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value == value and abs(value) != float("inf"):
        return float(value)
    return None


def _parse_ts(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole > 0 else None


def private_source_staleness(
    contract: Mapping[str, Any] | None,
    private_availability: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Provisioned private sources whose fetch is past its configured budget.

    ``private_availability`` is ``data_contract.private_source_availability()``.
    A source that is not provisioned on this host is absent by design and is
    not counted.  A provisioned source the contract carries no timestamp row
    for is ``unknown`` (counted separately), never fresh.
    """
    if private_availability is None:
        return {"provisioned": None, "stale": None, "unknown": None, "detail": []}
    stamps = {}
    if isinstance(contract, Mapping):
        df = contract.get("dataFreshness")
        if isinstance(df, Mapping) and isinstance(df.get("sourceTimestamps"), Mapping):
            stamps = df["sourceTimestamps"]
    provisioned = 0
    stale = 0
    unknown = 0
    detail: list[dict[str, Any]] = []
    for key in sorted(private_availability):
        info = private_availability[key]
        if not isinstance(info, Mapping) or not info.get("provisioned"):
            continue
        provisioned += 1
        entry = stamps.get(key) if isinstance(stamps, Mapping) else None
        if not isinstance(entry, Mapping):
            unknown += 1
            detail.append({"source": key, "state": "unknown"})
            continue
        verdict = entry.get("staleness")
        if verdict in _BREACHED_STALENESS:
            stale += 1
            detail.append(
                {
                    "source": key,
                    "state": verdict,
                    "ageHours": _num(entry.get("ageHours")),
                    "maxAgeHours": _num(entry.get("maxAgeHours")),
                }
            )
        elif verdict not in ("fresh", "seasonally_inactive"):
            unknown += 1
            detail.append({"source": key, "state": "unknown"})
    return {"provisioned": provisioned, "stale": stale, "unknown": unknown, "detail": detail}


def board_freshness_metrics(
    contract: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
    private_availability: Mapping[str, Mapping[str, Any]] | None = None,
    roster_refusals: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The ``freshness_slo`` block of ``/api/status``.  Never raises on shape.

    ``roster_refusals`` is ``trade_ledger.roster_refusal_counts()`` (passed
    in, so this stays a pure function of its arguments); ``None`` reports
    the counts as unknown.
    """
    now = now or datetime.now(timezone.utc)
    rows = contract.get("playersArray") if isinstance(contract, Mapping) else None
    rows = [r for r in rows if isinstance(r, Mapping)] if isinstance(rows, list) else []

    top: list[Mapping[str, Any]] = []
    priced = 0
    priced_withheld = 0
    for r in rows:
        rank = _num(r.get("canonicalConsensusRank"))
        if rank is not None and 1 <= rank <= TOP_N:
            top.append(r)
        value = _num(r.get("rankDerivedValue"))
        if value is not None and value > 0:
            priced += 1
            if withheld_value_state(r) is not None:
                priced_withheld += 1
    top_stale = sum(1 for r in top if (r.get("confidenceAxes") or {}).get("freshness") == "low")
    top_withheld = sum(1 for r in top if withheld_value_state(r) is not None)

    scraped_at = (
        _parse_ts(contract.get("scrapeTimestamp")) if isinstance(contract, Mapping) else None
    )
    age = None
    if scraped_at is not None:
        age = round(max(0.0, (now - scraped_at).total_seconds() / 3600.0), 2)

    private = private_source_staleness(contract, private_availability)
    measured = bool(rows) and bool(top)
    try:
        from src.api.roster_freshness import roster_age

        rosters = roster_age(dict(contract) if isinstance(contract, Mapping) else None, now=now)
    except Exception:  # noqa: BLE001 - a diagnostic must not raise
        rosters = {"state": "unknown", "source": None, "ageHours": None, "maxAgeHours": None}
    refusals = roster_refusals if isinstance(roster_refusals, Mapping) else {}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "state": "measured" if measured else "unknown",
        "topN": TOP_N,
        "top200Count": len(top) if measured else None,
        "top200StaleCount": top_stale if measured else None,
        "top200StaleShare": _share(top_stale, len(top)),
        "top200WithheldShare": _share(top_withheld, len(top)),
        "pricedCount": priced if measured else None,
        "pricedWithheldCount": priced_withheld if measured else None,
        "pricedWithheldShare": _share(priced_withheld, priced),
        "boardScrapedAt": scraped_at.isoformat() if scraped_at else None,
        "boardAgeHours": age,
        "privateSourcesProvisioned": private["provisioned"],
        "privateSourcesStale": private["stale"],
        "privateSourcesUnknown": private["unknown"],
        # Per-source names: admin diagnostics only (stripped for anonymous callers).
        "privateSourceDetail": private["detail"],
        # The default league's rosters (the contract's own ``sleeper`` block),
        # judged by the one owner, ``roster_freshness.roster_age``.
        "rosterState": rosters["state"],
        "rosterSource": rosters["source"],
        "rosterAgeHours": rosters["ageHours"],
        "rosterMaxAgeHours": rosters["maxAgeHours"],
        # Team-attributed trades this process could not verify because the
        # rosters were not current (T12's revisit trigger).  None = not reported.
        "rosterUnverifiableTrades": (
            {k: refusals.get(k) for k in ("stale", "unknown", "since")} if refusals else None
        ),
    }
