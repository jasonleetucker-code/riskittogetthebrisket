"""Audit-F1 diagnostics D1-D5 for the rank-space Hampel challenger.

``docs/valuation/evidence/rank-space-hampel-2026-10-17/PREREGISTRATION.md`` §3:
reported, never deciding. Two halves:

* :func:`f1_rows` -- per board, while both builds are in memory, a compact row
  table (asset class, both consensus ranks, both published values, the KTC
  Market benchmark, the voting sources and both filters' drop sets). Stored on
  the rank-space ledger record as ``f1Rows``.
* :func:`aggregate` -- D1-D5 over any set of those tables.

Bands are by the INCUMBENT's (served) ``canonicalConsensusRank`` for both
filters, so champion and challenger are compared on the same rows. KTC Market
(``ktcMarket.normalizedValue``) is a benchmark, never a vote and never a target:
D5 describes it, nothing here is tuned toward it.

Pure functions; no I/O.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from src.robust_filter_shadow.record import is_filter_row, voting_observations

#: The value-direct market sources the preregistration names (audit F1).
MARKET_SOURCES = ("ktcCrowdSfTep", "ktcTradesSfTep", "idpTradeCalc")
BANDS: tuple[tuple[int, int], ...] = (
    (1, 24),
    (25, 50),
    (51, 100),
    (101, 200),
    (201, 400),
    (401, 800),
)
MEMBERSHIP_DEPTHS = (24, 100, 200)
ASSET_CLASSES = ("offense", "idp")
SIDES = ("champion", "challenger")

# Compact row layout (lists keep a ~1,100-row board small on the ledger line).
_C, _RI, _RC, _VI, _VC, _KM, _FR, _OBS, _DI, _DC = range(10)


def _num(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _rank(row: Mapping[str, Any]) -> int | None:
    value = _num(row.get("canonicalConsensusRank"))
    return None if value is None else int(value)


def _market(row: Mapping[str, Any]) -> float | None:
    block = row.get("ktcMarket")
    if not isinstance(block, Mapping):
        return None
    value = _num(block.get("normalizedValue"))
    return value if value is not None and value > 0 else None


def f1_rows(incumbent: Mapping[str, Any], challenger: Mapping[str, Any]) -> dict[str, list]:
    """``{name: [class, rank_inc, rank_ch, value_inc, value_ch, ktcMarket,
    filter_row, voting_sources, drops_inc, drops_ch]}`` for one board."""
    ch_rows = {str(r.get("displayName")): r for r in challenger.get("playersArray") or []}
    out: dict[str, list] = {}
    for row in incumbent.get("playersArray") or []:
        name = str(row.get("displayName"))
        other = ch_rows.get(name)
        if other is None or name in out:
            continue
        obs = voting_observations(row)
        out[name] = [
            row.get("assetClass"),
            _rank(row),
            _rank(other),
            _num(row.get("rankDerivedValue")),
            _num(other.get("rankDerivedValue")),
            _market(row),
            bool(is_filter_row(row, obs)),
            sorted(obs),
            sorted(row.get("droppedSources") or []),
            sorted(other.get("droppedSources") or []),
        ]
    return out


def band_of(rank: int | None) -> str | None:
    if rank is None:
        return None
    for lo, hi in BANDS:
        if lo <= rank <= hi:
            return f"{lo}-{hi}"
    return None


def _band_names() -> list[str]:
    return [f"{lo}-{hi}" for lo, hi in BANDS]


def _q(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    pos = q * (len(ordered) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _r(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def _share(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def wiped_families(
    voting: Iterable[str], dropped: Iterable[str], family_of: Callable[[str], str]
) -> list[str]:
    """Families whose every voting member was dropped on the row."""
    members: dict[str, set[str]] = defaultdict(set)
    for source in voting:
        members[family_of(source)].add(source)
    gone = set(dropped)
    return sorted(f for f, m in members.items() if m and m <= gone)


def aggregate(
    boards: Sequence[Mapping[str, list]],
    *,
    family_of: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """D1-D5 pooled over ``boards`` (each a :func:`f1_rows` table)."""
    if family_of is None:
        from src.api.data_contract import correlation_group_for as family_of  # noqa: PLC0415
    bands = _band_names()
    d1 = {b: {s: Counter() for s in SIDES} for b in bands}
    d2 = {b: {"rows": 0, **{s: 0 for s in SIDES}} for b in bands}
    d4 = {b: {"filterRows": 0, **{s: 0 for s in SIDES}} for b in bands + ["all"]}
    d4_families = {s: Counter() for s in SIDES}
    d5: dict[str, dict[str, list[float]]] = {b: {s: [] for s in SIDES} for b in bands}
    d3_rel: dict[str, list[float]] = {c: [] for c in ASSET_CLASSES}
    d3_membership = {
        c: {str(d): {"out": 0, "in": 0, "boardsChanged": 0} for d in MEMBERSHIP_DEPTHS}
        for c in ASSET_CLASSES
    }
    for table in boards:
        top: dict[str, dict[int, tuple[set[str], set[str]]]] = {
            c: {d: (set(), set()) for d in MEMBERSHIP_DEPTHS} for c in ASSET_CLASSES
        }
        for name, row in table.items():
            cls = row[_C]
            band = band_of(row[_RI])
            vi, vc, km = row[_VI], row[_VC], row[_KM]
            drops = {"champion": set(row[_DI]), "challenger": set(row[_DC])}
            if cls in ASSET_CLASSES:
                if vi and vc and vi > 0 and vc > 0:
                    d3_rel[cls].append(abs(vc / vi - 1.0))
                for d in MEMBERSHIP_DEPTHS:
                    if row[_RI] is not None and row[_RI] <= d:
                        top[cls][d][0].add(name)
                    if row[_RC] is not None and row[_RC] <= d:
                        top[cls][d][1].add(name)
            if band is not None and km and vi and vc and vi > 0 and vc > 0:
                d5[band]["champion"].append(vi / km - 1.0)
                d5[band]["challenger"].append(vc / km - 1.0)
            if cls == "pick":
                continue
            market_obs = [s for s in row[_OBS] if s in MARKET_SOURCES]
            if band is not None:
                d2[band]["rows"] += 1
                for side in SIDES:
                    d1[band][side]["voting"] += len(market_obs)
                    dropped_market = sum(1 for s in market_obs if s in drops[side])
                    d1[band][side]["rejected"] += dropped_market
                    d2[band][side] += dropped_market > 0
            if row[_FR]:
                for key in [band, "all"] if band is not None else ["all"]:
                    d4[key]["filterRows"] += 1
                for side in SIDES:
                    wiped = wiped_families(row[_OBS], drops[side], family_of)
                    if wiped:
                        d4["all"][side] += 1
                        if band is not None:
                            d4[band][side] += 1
                        d4_families[side].update(wiped)
        for cls in ASSET_CLASSES:
            for d in MEMBERSHIP_DEPTHS:
                inc, ch = top[cls][d]
                cell = d3_membership[cls][str(d)]
                cell["out"] += len(inc - ch)
                cell["in"] += len(ch - inc)
                cell["boardsChanged"] += inc != ch

    d1_out: dict[str, Any] = {}
    totals = {s: Counter() for s in SIDES}
    for band in bands:
        d1_out[band] = {}
        for side in SIDES:
            cell = d1[band][side]
            totals[side].update(cell)
            d1_out[band][side] = {
                "voting": cell["voting"],
                "rejected": cell["rejected"],
                "share": _share(cell["rejected"], cell["voting"]),
            }
    d1_out["1-800"] = {
        side: {
            "voting": totals[side]["voting"],
            "rejected": totals[side]["rejected"],
            "share": _share(totals[side]["rejected"], totals[side]["voting"]),
        }
        for side in SIDES
    }
    d3_out: dict[str, Any] = {}
    for cls in ASSET_CLASSES:
        rel = d3_rel[cls]
        moved = [v for v in rel if v > 0]
        d3_out[cls] = {
            "rows": len(rel),
            "rowsMoved": len(moved),
            "medianRelAll": _r(_q(rel, 0.5), 5),
            "p90RelAll": _r(_q(rel, 0.9), 5),
            "medianRelMoved": _r(_q(moved, 0.5), 5),
            "p90RelMoved": _r(_q(moved, 0.9), 5),
            "maxRel": _r(max(rel) if rel else None, 5),
            "topMembership": d3_membership[cls],
        }
    d5_out = {
        band: {
            "rows": len(d5[band]["champion"]),
            **{
                side: _r(statistics.median(d5[band][side]) if d5[band][side] else None)
                for side in SIDES
            },
        }
        for band in bands
    }
    return {
        "boards": len(boards),
        "D1_market_rejection_share": d1_out,
        "D2_rows_with_market_rejected": d2,
        "D3_value_movement": d3_out,
        "D4_family_wiped": {
            "rowsByBand": d4,
            "familiesWiped": {s: dict(d4_families[s].most_common()) for s in SIDES},
        },
        "D5_model_vs_ktc_market_median": d5_out,
        "notes": [
            "bands by the incumbent's canonicalConsensusRank for both filters",
            "D1/D2/D4 exclude pick rows (the filter never runs on picks)",
            "D5 is model/ktcMarket.normalizedValue - 1 over ranked rows carrying the "
            "benchmark; a DIAGNOSTIC, never a target",
        ],
    }
