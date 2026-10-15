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

``assetOverlap``  F1 of a ONE-TO-ONE matching between the package's assets
                  and the trade's: recall over the package's assets,
                  precision over the trade's.  Each package asset and each
                  trade asset is used at most once (a maximum-weight
                  assignment), so two 2027 firsts cannot both answer one
                  package first, and a trade missing a package asset can never
                  tie the trade that has it.  An exact match counts
                  ``matchWeights.exact``, a same-round pick ``round``.  The
                  package's two sides are aligned onto two of the trade's
                  sides in whichever orientation matches more — Sleeper lanes
                  record what each roster RECEIVED and KTC publishes two
                  packages with no orientation, so alignment is symmetric and
                  neither convention is assumed.  A package asset found on the
                  OTHER aligned side (it was exchanged FOR its package-mates)
                  counts at ``oppositeDirectionMultiplier``.
``topology``      closeness of the aligned trade's shape (assets per side) to
                  the package's; a third team's assets count as mismatch.  NOT
                  APPLICABLE while either package side is empty (the shape is
                  not built yet), and then it drops out of the mean.
``format``        the ledger's disposition for this league.  When it was
                  computed for another league or is absent:
                  ``unknownFormatScore`` — LOW, never neutral.
``recency``       ``0.5 ** (ageDays / recencyHalfLifeDays)``.

Not-applicable components drop out of the weighted mean; unknown ones do not
(they score low).  Components the spec lists but this module cannot measure honestly are named
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


def ref_queries(league_key: str, side: SideRefs) -> list[Any]:
    """One single-ref TC-07 query per DISTINCT accepted package asset — the
    rows of the one-to-one matching.  Unparseable refs are reported by the
    side's own query and are not package assets here."""
    out: list[Any] = []
    seen: set[tuple[str, str]] = set()
    for kind, refs in (
        ("player_ids", side.player_ids),
        ("pick_names", side.pick_names),
        ("pick_asset_ids", side.pick_asset_ids),
    ):
        for raw in list(refs)[: ref.MAX_QUERY_ASSETS]:
            key = (kind, str(raw or "").strip())
            if not key[1] or key in seen:
                continue
            seen.add(key)
            q = ref.build_query(league_key, **{kind: [key[1]]})
            if not q.empty():
                out.append(q)
    return out


def _match_weight(match: str | None, cfg: Mapping[str, Any]) -> float:
    weights = cfg["matchWeights"]
    if match == ref.MATCH_EXACT:
        return float(weights["exact"])
    if match == ref.MATCH_ROUND:
        return float(weights["round"])
    return 0.0


def _assign(weights: list[list[float]]) -> list[tuple[int, int]]:
    """Maximum-weight one-to-one assignment (rows = package assets, columns
    = trade assets); only positive-weight pairs are returned."""
    if not weights or not weights[0]:
        return []
    from scipy.optimize import linear_sum_assignment  # noqa: PLC0415 — lazy, as elsewhere

    rows, cols = linear_sum_assignment(weights, maximize=True)
    return [(int(r), int(c)) for r, c in zip(rows, cols) if weights[r][c] > 0]


def _align(
    sides: Sequence[Sequence[Mapping[str, Any]]],
    refs_a: Sequence[Any],
    refs_b: Sequence[Any],
    *,
    own: bool,
    cfg: Mapping[str, Any],
) -> dict[str, Any]:
    """Best one-to-one matching of the package onto two distinct trade sides
    (i for side A, j for side B).

    For each candidate pairing the package's assets are matched against the
    assets of sides i and j by a maximum-weight assignment: a side-A asset
    found on side i (or a side-B asset on side j) scores its full grade
    weight; found on the OTHER aligned side it scores the opposite-direction
    multiple.  Every package asset and every trade asset is used at most once
    across BOTH directions.  The pairing with the larger total wins; ties keep
    the first (lowest-index) pairing, so the answer is deterministic.  A
    one-sided trade record aligns side A only."""
    opp = float(cfg["matchWeights"]["oppositeDirectionMultiplier"])
    n = len(sides)
    pairs: list[tuple[int, int | None]] = (
        [(i, j) for i in range(n) for j in range(n) if i != j] if n >= 2 else [(0, None)]
    )
    package = [(q, "a") for q in refs_a] + [(q, "b") for q in refs_b]
    best: dict[str, Any] | None = None
    for i, j in pairs:
        cols = [(a, i) for a in sides[i]] + ([(a, j) for a in sides[j]] if j is not None else [])
        grades: list[list[str | None]] = []
        weights: list[list[float]] = []
        for q, which in package:
            g_row, w_row = [], []
            home = i if which == "a" else j
            for asset, side_idx in cols:
                g = ref._asset_match(asset, q, own_this_league=own)
                w = _match_weight(g, cfg)
                if side_idx != home:
                    w *= opp
                g_row.append(g)
                w_row.append(w)
            grades.append(g_row)
            weights.append(w_row)
        chosen = _assign(weights)
        total = sum(weights[r][c] for r, c in chosen)
        if best is None or total > best["matchedWeight"] + 1e-12:
            same: list[tuple[Mapping[str, Any], str]] = []
            opposite: list[tuple[Mapping[str, Any], str]] = []
            for r, c in chosen:
                asset, side_idx = cols[c]
                home = i if package[r][1] == "a" else j
                hit = (asset, str(grades[r][c]))
                (same if side_idx == home else opposite).append(hit)
            best = {
                "a": i,
                "b": j,
                "matchedWeight": total,
                "sameDirection": same,
                "oppositeDirection": opposite,
            }
    assert best is not None
    return best


def _overlap(matched_weight: float, package_size: int, trade_size: int) -> float:
    if matched_weight <= 0 or package_size <= 0 or trade_size <= 0:
        return 0.0
    recall = min(1.0, matched_weight / package_size)
    precision = min(1.0, matched_weight / trade_size)
    return 2 * recall * precision / (recall + precision)


def _topology(
    sides: Sequence[Sequence[Any]], a_idx: int, b_idx: int | None, size_a: int, size_b: int
) -> float | None:
    """1 − (per-side count mismatch + third-team assets) / larger total, or
    ``None`` (not applicable) while either package side is empty."""
    if not size_a or not size_b:
        return None
    ta = len(sides[a_idx])
    tb = len(sides[b_idx]) if b_idx is not None else 0
    extra = sum(len(s) for k, s in enumerate(sides) if k not in (a_idx, b_idx))
    mismatch = abs(size_a - ta) + abs(size_b - tb) + extra
    denom = max(size_a + size_b, ta + tb + extra, 1)
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
    topology: float | None,
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
    if topology is None:
        out.append({"key": "topology", "text": "Shape not compared until both sides have assets"})
    elif len(sides) > 2:
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
    refs_a: Sequence[Any],
    refs_b: Sequence[Any],
    *,
    own: bool,
    today: date,
    cfg: Mapping[str, Any],
    names: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """The ``comparability`` block for one visible ledger trade, or ``None``
    when it shares no asset with the package (the gate).  ``refs_a`` /
    ``refs_b`` are ``ref_queries`` — one query per distinct package asset."""
    names = names or {}
    sides = [list(s) for s in rec.get("sides") or []]
    if not sides:
        return None
    align = _align(sides, refs_a, refs_b, own=own, cfg=cfg)
    if align["matchedWeight"] <= 0:
        return None
    size_a, size_b = len(refs_a), len(refs_b)
    trade_size = sum(len(s) for s in sides)
    values: dict[str, float | None] = {
        "assetOverlap": _overlap(align["matchedWeight"], size_a + size_b, trade_size),
        "topology": _topology(sides, align["a"], align["b"], size_a, size_b),
    }
    values["format"], fmt_state, disposition = _format_component(format_match, cfg)
    values["recency"], age = _recency(
        rec.get("occurredDate"), today, float(cfg["recencyHalfLifeDays"])
    )
    weights = cfg["weights"]
    components: dict[str, dict[str, Any]] = {}
    num = den = 0.0
    for key in COMPONENTS:
        v = values[key]
        w = float(weights[key])
        components[key] = {
            "score": None if v is None else round(v, 4),
            "weight": w,
            "applicable": v is not None,
        }
        if v is not None:
            num += w * v
            den += w
    components["format"]["state"] = fmt_state
    score = num / den
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


def _merge_queries(qa: Any, qb: Any) -> Any:
    """Both sides' queries as one TC-07 query (the ledger scan keys and the
    projection's match flags).  Merged rather than rebuilt from the joined
    ref lists, so each side keeps its own ``MAX_QUERY_ASSETS`` bound."""
    union = ref._Query()
    for q in (qa, qb):
        union.players |= q.players
        for gid, refined in q.pick_refined.items():
            union.pick_refined.setdefault(gid, set()).update(refined)
        union.pick_unrefined |= q.pick_unrefined
        union.owned_ids |= q.owned_ids
    return union


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
    union = _merge_queries(qa, qb)
    refs_a, refs_b = ref_queries(league_key, side_a), ref_queries(league_key, side_b)
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
                rec,
                row["formatMatch"],
                refs_a,
                refs_b,
                own=own,
                today=today,
                cfg=cfg,
                names=names,
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
