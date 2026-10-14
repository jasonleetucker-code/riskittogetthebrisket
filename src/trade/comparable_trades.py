"""Comparable real trades for the package on the calculator — TC-09 / C4-MTL-03.

Given the package being built (the assets that move together on each side),
rank the recorded real dynasty trades in the canonical underlying-trade
ledger (``market_trade_report.open_canonical_ledger``) by how much they
RESEMBLE it, and say why each one matched.

This module is a relevance ordering over facts, nothing more:

* **Never a price, never a value.**  No canonical value is read and none is
  computed from a trade.  The score orders a reference list; it feeds no
  verdict, meter, equalizer or board (``MARKET_TRADE_LEDGER_ACTIONABILITY_SPEC``
  §3: raw real trades never overwrite canonical value; C4-MTL-03 "no naive
  raw-trade averaging into canonical value").
* **Overlap is the gate.**  A trade is a candidate only when it shares at
  least one asset with the package, through the same identity rules TC-07
  uses (players by canonical id, picks at the named ``exact`` / ``round``
  grades, unresolved assets match nothing).  So similar total value can never
  make two trades "comparable" on its own — the spec's prohibition holds
  structurally.
* **Same visibility, same projection.**  Every row passes
  ``market_trade_reference.visibility`` (verified dynasty only; this league's
  own trades only; registry leagues reached through another lane withheld;
  Sharp rows only with a cohort manager) and is rendered by
  ``market_trade_reference.project_trade``: the TC-10 format tags and the
  ledger owner's disposition and timing travel unchanged.
* **Format comparability has one owner** — the ledger's disposition, read
  through ``project_trade``'s ``formatMatch``.  This module keeps no format
  tiers of its own (the retired own-league ``comparable_trades_for_asset``
  did, a second format-comparability owner over a superseded ledger).  It
  uses the disposition only to ORDER references, never as price authority
  (the ledger's price-authority field is not read here).

THE SIMILARITY MODEL (``config/trade/comparable_trades.json``,
``PRIOR_UNVALIDATED``) — a weighted mean of four named components:

``assetOverlap``  F1 of the matched assets: recall over the package's assets,
                  precision over the trade's.  An exact match counts
                  ``matchWeights.exact``, a same-round pick ``round``.  The
                  package's two sides are aligned onto two of the trade's
                  sides in whichever orientation matches more — Sleeper lanes
                  record what each roster RECEIVED and KTC publishes two
                  packages with no orientation, so alignment is symmetric and
                  neither convention is assumed.  A package asset found on the
                  OTHER aligned side (it was exchanged FOR its package-mates)
                  counts at ``oppositeDirectionMultiplier``.
``topology``      closeness of the aligned trade's shape (assets per side) to
                  the package's; a third team's assets count as mismatch.
``format``        the ledger's disposition for this league.  When it was
                  computed for another league or is absent:
                  ``unknownFormatScore`` — LOW, never neutral.
``recency``       ``0.5 ** (ageDays / recencyHalfLifeDays)``.

Components the spec lists but this module cannot measure honestly are named
in the config's ``notIncluded`` and stamped on every response.

Missing is never zero: no ledger is ``unavailable``, an empty package is
``no_assets``, and a scan that hit its bound says so (``scanCapped``).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from src.trade import market_trade_reference as ref
from src.trade import market_trade_report as report

_CONFIG = Path(__file__).resolve().parents[2] / "config" / "trade" / "comparable_trades.json"
CONFIG_PATH_LABEL = "config/trade/comparable_trades.json"

DEFAULT_LIMIT = 10
MAX_LIMIT = 25
#: Rows examined per request, newest first.  Unlike TC-07 the answer is
#: ranked, so every scanned candidate is scored before the cut.
MAX_SCAN = ref.MAX_SCAN

COMPONENTS = ("assetOverlap", "topology", "format", "recency")
FORMAT_KNOWN = "known"
FORMAT_UNKNOWN = "unknown"


def load_comparable_config(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or _CONFIG).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class SideRefs:
    """One side of the calculator package, as identity refs only."""

    player_ids: Sequence[str] = ()
    pick_names: Sequence[str] = ()
    pick_asset_ids: Sequence[str] = ()

    def as_kwargs(self) -> dict[str, list[str]]:
        return {
            "player_ids": list(self.player_ids),
            "pick_names": list(self.pick_names),
            "pick_asset_ids": list(self.pick_asset_ids),
        }


def _side_size(q: Any) -> int:
    """Assets the side asked about — the recall denominator.  Counted from
    what was accepted; an unparseable ref is reported, not counted."""
    acc = q.accepted
    return len(acc["players"]) + len(acc["picks"]) + len(acc["pickAssetIds"])


def _match_weight(match: str | None, cfg: Mapping[str, Any]) -> float:
    weights = cfg["matchWeights"]
    if match == ref.MATCH_EXACT:
        return float(weights["exact"])
    if match == ref.MATCH_ROUND:
        return float(weights["round"])
    return 0.0


def _side_matches(
    side: Sequence[Mapping[str, Any]], q: Any, *, own: bool, cfg: Mapping[str, Any]
) -> tuple[float, list[tuple[Mapping[str, Any], str]]]:
    total = 0.0
    hits: list[tuple[Mapping[str, Any], str]] = []
    for asset in side:
        m = ref._asset_match(asset, q, own_this_league=own)
        if m:
            total += _match_weight(m, cfg)
            hits.append((asset, m))
    return total, hits


def _align(
    sides: Sequence[Sequence[Mapping[str, Any]]],
    qa: Any,
    qb: Any,
    *,
    own: bool,
    cfg: Mapping[str, Any],
) -> dict[str, Any]:
    """Best assignment of package side A / B onto two distinct trade sides
    (i for A, j for B).  Maximizes same-direction weight plus the discounted
    opposite-direction weight; ties keep the first (lowest-index) pairing so
    the answer is deterministic.  A one-sided record aligns A only."""
    opp = float(cfg["matchWeights"]["oppositeDirectionMultiplier"])
    n = len(sides)
    a_w = [_side_matches(s, qa, own=own, cfg=cfg) for s in sides]
    b_w = [_side_matches(s, qb, own=own, cfg=cfg) for s in sides]
    pairs: list[tuple[int, int | None]] = (
        [(i, j) for i in range(n) for j in range(n) if i != j] if n >= 2 else [(0, None)]
    )
    best: tuple[float, int, int | None] | None = None
    for i, j in pairs:
        same = a_w[i][0] + (b_w[j][0] if j is not None else 0.0)
        crossed = (a_w[j][0] if j is not None else 0.0) + b_w[i][0]
        score = same + opp * crossed
        if best is None or score > best[0] + 1e-12:
            best = (score, i, j)
    assert best is not None
    weight, i, j = best
    return {
        "a": i,
        "b": j,
        "matchedWeight": weight,
        "sameDirection": a_w[i][1] + (b_w[j][1] if j is not None else []),
        "oppositeDirection": (a_w[j][1] if j is not None else []) + b_w[i][1],
    }


def _overlap(matched_weight: float, package_size: int, trade_size: int) -> float:
    if matched_weight <= 0 or package_size <= 0 or trade_size <= 0:
        return 0.0
    recall = min(1.0, matched_weight / package_size)
    precision = min(1.0, matched_weight / trade_size)
    return 2 * recall * precision / (recall + precision)


def _topology(
    sides: Sequence[Sequence[Any]], a_idx: int, b_idx: int | None, size_a: int, size_b: int
) -> float:
    """1 − (per-side count mismatch + third-team assets) / larger total.  A
    package side with no assets yet is compared on the built side only."""
    ta = len(sides[a_idx])
    tb = len(sides[b_idx]) if b_idx is not None else 0
    extra = sum(len(s) for k, s in enumerate(sides) if k not in (a_idx, b_idx))
    mismatch = extra
    pkg_total = trade_total = 0
    if size_a:
        mismatch += abs(size_a - ta)
        pkg_total += size_a
        trade_total += ta
    if size_b:
        mismatch += abs(size_b - tb)
        pkg_total += size_b
        trade_total += tb
    denom = max(pkg_total, trade_total + extra, 1)
    return max(0.0, 1.0 - mismatch / denom)


def _format_component(
    format_match: Mapping[str, Any], cfg: Mapping[str, Any]
) -> tuple[float, str, str | None]:
    """(score, state, disposition) from the projected row's ``formatMatch``
    — the ledger owner's verdict, only when it was computed for THIS league."""
    disp = format_match.get("disposition") if format_match.get("appliesToThisLeague") else None
    scores = cfg["formatScores"]
    if disp in scores:
        return float(scores[disp]), FORMAT_KNOWN, str(disp)
    return float(cfg["unknownFormatScore"]), FORMAT_UNKNOWN, None


def _recency(occurred: Any, today: date, half_life: float) -> tuple[float, int | None]:
    try:
        d = date.fromisoformat(str(occurred)[:10])
    except (TypeError, ValueError):
        # read_ledger_trades yields dated trades only; an undated one would
        # be unknown recency, which scores as old, never as new.
        return 0.0, None
    age = max(0, (today - d).days)
    return math.pow(0.5, age / half_life), age


def _label(asset: Mapping[str, Any], names: Mapping[str, Mapping[str, Any]]) -> str:
    return ref._asset_label(asset, names) or "an unnamed asset"


def _shape(sizes: Iterable[int]) -> str:
    return "-for-".join(str(s) for s in sizes)


def _reasons(
    *,
    align: Mapping[str, Any],
    names: Mapping[str, Mapping[str, Any]],
    size_a: int,
    size_b: int,
    sides: Sequence[Sequence[Any]],
    topology: float,
    fmt_state: str,
    disposition: str | None,
    age: int | None,
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []

    def listed(hits: Sequence[tuple[Mapping[str, Any], str]]) -> str:
        labels = [_label(a, names) for a, _ in hits]
        more = f" +{len(labels) - 4} more" if len(labels) > 4 else ""
        return ", ".join(labels[:4]) + more

    same = align["sameDirection"]
    exact = [h for h in same if h[1] == ref.MATCH_EXACT]
    rnd = [h for h in same if h[1] == ref.MATCH_ROUND]
    if exact:
        out.append({"key": "sharedExact", "text": f"Same asset: {listed(exact)}"})
    if rnd:
        out.append({"key": "sharedRound", "text": f"Same pick round: {listed(rnd)}"})
    if align["oppositeDirection"]:
        out.append(
            {
                "key": "oppositeDirection",
                "text": f"Moved the other way: {listed(align['oppositeDirection'])}",
            }
        )
    pkg = _shape(s for s in (size_a, size_b) if s)
    if len(sides) > 2:
        out.append({"key": "topology", "text": f"{len(sides)}-team trade; yours is {pkg}"})
    else:
        trade_sizes = [len(sides[align["a"]])]
        if align["b"] is not None:
            trade_sizes.append(len(sides[align["b"]]))
        trade = _shape(trade_sizes)
        text = f"Same {trade} shape" if topology >= 0.999 else f"{trade} shape vs your {pkg}"
        out.append({"key": "topology", "text": text})
    if fmt_state == FORMAT_KNOWN:
        out.append({"key": "format", "text": f"Format: {disposition}"})
    else:
        out.append({"key": "format", "text": "Format comparability unknown for this league"})
    if age is not None:
        out.append({"key": "recency", "text": "today" if age == 0 else f"{age} days ago"})
    return out


def score_trade(
    rec: Mapping[str, Any],
    format_match: Mapping[str, Any],
    qa: Any,
    qb: Any,
    *,
    own: bool,
    today: date,
    cfg: Mapping[str, Any],
    names: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """The ``comparability`` block for one visible ledger trade, or ``None``
    when it shares no asset with the package (the gate)."""
    names = names or {}
    sides = [list(s) for s in rec.get("sides") or []]
    if not sides:
        return None
    align = _align(sides, qa, qb, own=own, cfg=cfg)
    if align["matchedWeight"] <= 0:
        return None
    size_a, size_b = _side_size(qa), _side_size(qb)
    trade_size = sum(len(s) for s in sides)
    values: dict[str, float] = {
        "assetOverlap": _overlap(align["matchedWeight"], size_a + size_b, trade_size),
        "topology": _topology(sides, align["a"], align["b"], size_a, size_b),
    }
    values["format"], fmt_state, disposition = _format_component(format_match, cfg)
    values["recency"], age = _recency(
        rec.get("occurredDate"), today, float(cfg["recencyHalfLifeDays"])
    )
    weights = cfg["weights"]
    components = {
        key: {"score": round(values[key], 4), "weight": float(weights[key])} for key in COMPONENTS
    }
    components["format"]["state"] = fmt_state
    total_w = sum(float(weights[k]) for k in COMPONENTS)
    score = sum(float(weights[k]) * values[k] for k in COMPONENTS) / total_w
    return {
        "score": round(score, 4),
        "components": components,
        "reasons": _reasons(
            align=align,
            names=names,
            size_a=size_a,
            size_b=size_b,
            sides=sides,
            topology=values["topology"],
            fmt_state=fmt_state,
            disposition=disposition,
            age=age,
        ),
        "alignment": {
            "packageSideA": align["a"],
            "packageSideB": align["b"],
            "oppositeDirectionMatches": len(align["oppositeDirection"]),
        },
    }


def methodology(cfg: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": cfg["id"],
        "status": cfg["status"],
        "configPath": CONFIG_PATH_LABEL,
        "weights": dict(cfg["weights"]),
        "matchWeights": dict(cfg["matchWeights"]),
        "recencyHalfLifeDays": cfg["recencyHalfLifeDays"],
        "formatScores": dict(cfg["formatScores"]),
        "unknownFormatScore": cfg["unknownFormatScore"],
        "minScore": cfg["minScore"],
        "notIncluded": dict(cfg["notIncluded"]),
        "statement": (
            "Relevance ordering of recorded real trades, for reference only. Never a "
            "price or a value; it feeds no verdict, meter or board."
        ),
    }


def comparable_trades(
    league_key: str,
    *,
    side_a: SideRefs,
    side_b: SideRefs,
    limit: int = DEFAULT_LIMIT,
    names: Mapping[str, Mapping[str, Any]] | None = None,
    today: date | None = None,
    root: Path | None = None,
    privacy: Callable[[], ref.PrivacyContext] | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The response body for ``/api/market/trades/comparable``.  ``state`` is
    ``ok`` / ``no_assets`` / ``unavailable`` — never "no trades" for a
    missing ledger."""
    cfg = config or load_comparable_config()
    limit = max(1, min(int(limit), MAX_LIMIT))
    today = today or date.today()
    qa = ref.build_query(league_key, **side_a.as_kwargs())
    qb = ref.build_query(league_key, **side_b.as_kwargs())
    union = ref.build_query(
        league_key,
        player_ids=[*side_a.player_ids, *side_b.player_ids],
        pick_names=[*side_a.pick_names, *side_b.pick_names],
        pick_asset_ids=[*side_a.pick_asset_ids, *side_b.pick_asset_ids],
    )
    since = (today - timedelta(days=ref.RECENT_LOOKBACK_DAYS)).isoformat()
    base: dict[str, Any] = {
        "leagueKey": league_key,
        "lookbackDays": ref.RECENT_LOOKBACK_DAYS,
        "since": since,
        "query": {
            "sideA": {**qa.accepted, "unresolved": qa.unresolved},
            "sideB": {**qb.accepted, "unresolved": qb.unresolved},
        },
        "methodology": methodology(cfg),
        "samplingBiases": list(report.KNOWN_SAMPLING_BIASES),
    }
    empty_tail: dict[str, Any] = {"trades": [], "truncated": False, "withheld": None}
    conn = report.open_canonical_ledger(root)
    if conn is None:
        return {
            **base,
            "state": "unavailable",
            "reason": "trade_ledger_not_built",
            "ledger": None,
            **empty_tail,
        }
    ctx: ref.PrivacyContext | None = None
    try:
        ledger = ref._ledger_summary(conn, since)
        if union.empty():
            return {**base, "state": "no_assets", "reason": None, "ledger": ledger, **empty_tail}
        ctx = (privacy or ref.default_privacy_context)()
        names = names or {}
        withheld: dict[str, int] = {}
        scored: list[dict[str, Any]] = []
        below_min = 0
        scanned = 0
        scan_capped = False
        for rec, full_format in report.read_ledger_trades(
            conn, asset_keys=sorted(union.keys()), since_date=since
        ):
            if scanned >= MAX_SCAN:
                scan_capped = True
                break
            scanned += 1
            visible, reason, own = ref.visibility(rec, league_key, ctx)
            if not visible:
                withheld[reason or "withheld"] = withheld.get(reason or "withheld", 0) + 1
                continue
            row = ref.project_trade(rec, full_format, union, league_key, names, own_this_league=own)
            block = score_trade(
                rec, row["formatMatch"], qa, qb, own=own, today=today, cfg=cfg, names=names
            )
            if block is None:
                continue
            if block["score"] < float(cfg["minScore"]):
                below_min += 1
                continue
            row["comparability"] = block
            scored.append(row)
    finally:
        conn.close()
        if ctx is not None:
            ctx.close()
    # Input is newest first and the sort is stable: equal scores keep the
    # newer trade first.
    scored.sort(key=lambda r: -r["comparability"]["score"])
    return {
        **base,
        "state": "ok",
        "reason": None,
        "ledger": ledger,
        "trades": scored[:limit],
        "truncated": len(scored) > limit,
        "candidates": len(scored),
        "belowMinScore": below_min,
        "scanned": scanned,
        "scanCapped": scan_capped,
        "withheld": withheld,
    }
