#!/usr/bin/env python3
"""W27-F001 research harness: IDP edge consistency and the canonical IDP benchmark.

RESEARCH ONLY.  Nothing here is imported by ``src/``, by a route or by the
frontend, and nothing here changes a value, a weight, a threshold or a flag.
Proposal: ``docs/valuation/methodology_proposals/W27_F001_IDP_EDGE_BENCHMARK.md``.

Three subcommands, all deterministic:

``extract``
    Build the canonical contract ONCE from a pinned, tracked archive bundle
    (``exports/archive/<name>.zip``) and write a compact research fixture: the
    IDP rows with every field the edge detectors read, a per-row applied-weight
    summary for the offense rows (for the KTC comparison), the IDP Trade
    Calculator price ladder, the published Hill parameters, the per-source
    voting status, and provenance hashes.  Optionally (``--with-loo``) it also
    builds the leave-idpTradeCalc-out board and records what happens to the IDP
    shared-market translation.  This is the only step that runs the pipeline.

``analyze``
    Pure computation over the fixture: the incumbent detectors, the
    signal-independence audit, the incumbent's structural scale artifact, and
    the candidate benchmarks (C1 model-vs-IDPTC, C2 anchor-free evidence priced
    on the market's own curve).  Prints one sorted JSON document.

``history``
    Point-in-time replay over the tracked CSV history in git (no network, no
    gitignored data): the CSV-level C2 signal at weekly origins against the
    IDP Trade Calculator's later price move.  Needs full-depth git objects for
    ``CSVs/site_raw`` (a shallow CI clone cannot run it; the test does not).

Never reads the network, ``exports/latest`` or gitignored ``data/`` for a
conclusion.  ``extract`` builds through ``build_api_data_contract`` exactly as
``tests/archive_fixtures.newest_complete_contract`` does, so it reads the
tracked ``CSVs/site_raw`` and ``data/scrape_state`` at the checked-out commit;
their hashes are recorded in the fixture.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import statistics
import subprocess
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO = Path(__file__).resolve().parents[2]
ARCHIVE_DIR = REPO / "exports" / "archive"
DEFAULT_ARCHIVE = "dynasty_export_20261107_063955.zip"
DEFAULT_FIXTURE = REPO / "tests" / "scripts" / "fixtures" / "w27_f001_idp_edge_rows.json"

IDPTC = "idpTradeCalc"
IDP_POSITIONS = ("DL", "LB", "DB")
KTC_INPUTS = ("ktcCrowdSfTep", "ktcTradesSfTep")

# Mirror of frontend/lib/display-helpers.js::IDP_CONSENSUS_KEYS and
# frontend/lib/thresholds.js::MARKET_GAP_MIN_VALUE_RATIO /
# PREMIUM_SUMMARY_VALUE_RATIO (read at commit d7db52a43b).  Used only to
# REPRODUCE the incumbent; the node cross-check (w27_f001_frontend_crosscheck.mjs)
# proves the reproduction against the real module.
FRONTEND_IDP_CONSENSUS_KEYS = frozenset(
    {"dlfIdp", "dlfRookieIdp", "idpShowCombined", "fantasyProsIdp", "draftSharksIdp"}
)
MARKET_GAP_MIN_VALUE_RATIO = 0.05
PREMIUM_SUMMARY_VALUE_RATIO = 0.15
IDP_TOP_LIMIT = 200
EDGE_PREMIUM_LIMIT = 10

# The tail coordinate the pipeline uses (CLAUDE.md "Live Value Pipeline" step
# 2): p = (rank - 1) / 499, resolving up to rank 904.
PERCENTILE_REFERENCE_N = 500
TAIL_SATURATION_RANK = 904

# Families whose IDP opinion reaches IDPTC itself and therefore cannot be
# evidence AGAINST it: config/sources/source_lineage.json
# ``idptc-idpshow-dependence`` (Spearman 0.998, IDP Show leads) and
# ``idptc-idpshow-suspected-ancestry`` (vendor-stated per
# docs/sources/IDP_SHOW_LIBRARY_AUDIT_2026-11-01.md section 6).
BENCHMARK_LINEAGE_FAMILIES = frozenset({"idpTradeCalc", "idpShow"})

IDP_CSV_FILES = (
    "idpTradeCalc",
    "dlfIdp",
    "dlfRookieIdp",
    "fantasyProsIdp",
    "draftSharksIdp",
    "idpShowCombined",
)

_META_FIELDS = (
    "valueContribution",
    "valueContributionPath",
    "appliedWeight",
    "effectiveRank",
    "percentile",
)
# Kept only when true, to keep the committed fixture small.
_META_FLAGS = ("sharedMarketTranslated", "isAnchor")


# ── small numeric helpers ─────────────────────────────────────────────────


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _positive(value: Any) -> float | None:
    out = _num(value)
    return out if out is not None and out > 0 else None


def _rel_gap(market: float, evidence: float) -> float:
    """Signed symmetric relative gap, the repository's market-gap convention.

    ``(market - evidence) / mean(market, evidence)``: positive = the market
    prices the asset above the evidence (sell-high), negative = below
    (buy-low).  Same normalisation as ``ktc_market.compute_market_gap``.
    """
    return (market - evidence) / ((market + evidence) / 2.0)


def _verdict(ratio: float | None, threshold: float = MARKET_GAP_MIN_VALUE_RATIO) -> str:
    if ratio is None:
        return "unavailable"
    if abs(ratio) < threshold:
        return "hold"
    return "sell" if ratio > 0 else "buy"


def _quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"n": 0, "p10": None, "median": None, "p90": None, "mean": None}
    xs = sorted(values)

    def q(frac: float) -> float:
        idx = frac * (len(xs) - 1)
        lo = math.floor(idx)
        hi = math.ceil(idx)
        return xs[lo] + (xs[hi] - xs[lo]) * (idx - lo)

    return {
        "n": len(xs),
        "p10": round(q(0.10), 4),
        "median": round(q(0.50), 4),
        "p90": round(q(0.90), 4),
        "mean": round(statistics.fmean(xs), 4),
    }


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str | None:
    return _sha256_bytes(path.read_bytes()) if path.exists() else None


def _git(*args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(REPO), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return out.stdout


# ── independent Hill oracle ───────────────────────────────────────────────


def hill_value(percentile: float, c: float, s: float) -> int:
    """V(p) = 9999 / (1 + (p / c)^s), from the PUBLISHED parameters only.

    Written from the contract's ``hillCurves`` block and the formula in the
    canonical docstring, not imported from ``src/canonical`` — so agreement
    with the stamped ``valueContribution`` is evidence, not a tautology.
    Tail: percentiles past the saturation rank share the tail value.
    """
    p_max = (TAIL_SATURATION_RANK - 1) / (PERCENTILE_REFERENCE_N - 1)
    p = max(0.0, min(float(percentile), p_max))
    if p == 0.0:
        return 9999
    raw = 9999.0 / (1.0 + (p / c) ** s)
    return max(1, min(9999, int(math.floor(raw + 0.5))))


def rank_percentile(rank: float) -> float:
    return (float(rank) - 1.0) / (PERCENTILE_REFERENCE_N - 1)


# ── the market's own price curve ──────────────────────────────────────────


def ladder_value(ladder: list[float], rank: float) -> float | None:
    """IDPTC's published value at shared-market rank ``rank`` (1-based).

    Linear between integer ranks; ``None`` outside the market's depth — an
    expert placement deeper than the market prices is not extrapolated.
    """
    r = _num(rank)
    if r is None or r < 1 or not ladder or r > len(ladder):
        return None
    lo = int(math.floor(r))
    hi = int(math.ceil(r))
    v_lo = ladder[lo - 1]
    v_hi = ladder[hi - 1]
    return v_lo + (v_hi - v_lo) * (r - lo)


# ── incumbent reproduction (frontend/lib/display-helpers.js) ──────────────


def _js_number(value: Any) -> float:
    """JavaScript ``Number(x)`` for the shapes a contract row can carry."""
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return out


def incumbent_idp_edge(row: Mapping[str, Any]) -> dict[str, Any]:
    """Python transcription of ``idpMarketEdge`` + ``idpMarketAction``.

    Faithful to the JS including its coercions (``Number(null) === 0``,
    absent keys -> NaN -> skipped) and to the fact that EVERY non-IDPTC key in
    the rank map lands on the "expert" side, whatever its weight.
    """
    eff = row.get("effectiveSourceRanks") or {}
    ranks = eff if isinstance(eff, Mapping) and len(eff) > 0 else (row.get("sourceRanks") or {})
    if not ranks:
        return {"label": "—", "kind": "unranked", "ratio": None}
    retail_rank = _js_number(ranks.get(IDPTC)) if IDPTC in ranks else float("nan")
    consensus = [
        _js_number(v)
        for k, v in ranks.items()
        if k in FRONTEND_IDP_CONSENSUS_KEYS and v is not None and math.isfinite(_js_number(v))
    ]
    have_retail = math.isfinite(retail_rank)
    have_consensus = len(consensus) > 0
    if not have_retail and not have_consensus:
        return {"label": "—", "kind": "unranked", "ratio": None}
    if not have_retail:
        return {"label": "—", "kind": "consensus_only", "ratio": None}
    if not have_consensus:
        return {"label": "—", "kind": "retail_only", "ratio": None}
    meta = row.get("sourceRankMeta") or {}
    if not isinstance(meta, Mapping) or len(meta) == 0:
        return {"label": "—", "kind": "unranked", "ratio": None}
    retail: list[float] = []
    experts: list[float] = []
    for key in ranks:
        m = meta.get(key) or {}
        v = _js_number(m["valueContribution"]) if "valueContribution" in m else float("nan")
        if not math.isfinite(v):
            continue
        (retail if key == IDPTC else experts).append(v)
    if not retail or not experts:
        return {"label": "—", "kind": "unranked", "ratio": None}
    r = statistics.fmean(retail)
    c = statistics.fmean(experts)
    scale = (r + c) / 2.0
    if not scale > 0:
        return {"label": "—", "kind": "unranked", "ratio": None}
    ratio = (r - c) / scale
    if abs(ratio) < MARKET_GAP_MIN_VALUE_RATIO:
        return {"label": "HOLD", "kind": "hold", "ratio": ratio}
    if ratio > 0:
        return {"label": "SELL", "kind": "sell", "ratio": ratio}
    return {"label": "BUY", "kind": "buy", "ratio": ratio}


def incumbent_rankings_edge(row: Mapping[str, Any]) -> str:
    """``marketActionDisclosed`` label for a row (the /rankings Edge column)."""
    market = row.get("ktcMarket") or {}
    has_market = (
        bool(market.get("available")) and _positive(market.get("normalizedValue")) is not None
    )
    model = _positive(row.get("rankDerivedValue"))
    if not has_market or model is None:
        return "offense only" if row.get("assetClass") == "idp" else "—"
    ratio = _num(row.get("marketGapValueRatio"))
    direction = str(row.get("marketGapDirection") or "none")
    if ratio is None:
        return "offense only" if row.get("assetClass") == "idp" else "—"
    if ratio < MARKET_GAP_MIN_VALUE_RATIO or direction == "none":
        return "HOLD"
    return "SELL" if direction == "retail_premium" else "BUY"


def idp_in_top_by_idptc(row: Mapping[str, Any], limit: int = IDP_TOP_LIMIT) -> bool:
    """``isIdpInTopByIdptc`` (the /edge IDP panel population gate)."""
    if row.get("assetClass") != "idp" or row.get("quarantined"):
        return False
    eff = row.get("effectiveSourceRanks") or {}
    ranks = eff if len(eff) > 0 else (row.get("sourceRanks") or {})
    rank = _js_number(ranks.get(IDPTC)) if IDPTC in ranks else float("nan")
    return math.isfinite(rank) and 1 <= rank <= limit


# ── per-row building blocks ───────────────────────────────────────────────


def _meta(row: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    meta = row.get("sourceRankMeta") or {}
    return {k: dict(v) for k, v in meta.items() if isinstance(v, Mapping)}


def _applied(m: Mapping[str, Any]) -> float:
    w = _num(m.get("appliedWeight"))
    return w if w is not None and w > 0 else 0.0


def idptc_market_value(row: Mapping[str, Any]) -> float | None:
    """IDPTC's price on the board scale (its value-direct vote, raw/max*9999)."""
    m = _meta(row).get(IDPTC)
    if m and m.get("valueContributionPath") == "value_direct":
        return _positive(m.get("valueContribution"))
    return None


def idptc_weight_share(row: Mapping[str, Any]) -> float | None:
    meta = _meta(row)
    total = sum(_applied(m) for m in meta.values())
    if total <= 0 or IDPTC not in meta:
        return None
    return _applied(meta[IDPTC]) / total


def candidate_c1(row: Mapping[str, Any]) -> float | None:
    """C1 — our model value vs IDPTC (the audit's suggested repair).

    The offense definition (``ktc_market.compute_market_gap``) with IDPTC in
    KTC Market's seat: ``(IDPTC − rankDerivedValue) / mean``.
    """
    market = idptc_market_value(row)
    model = _positive(row.get("rankDerivedValue"))
    if market is None or model is None:
        return None
    return _rel_gap(market, model)


def leave_anchor_out_value_mean(row: Mapping[str, Any]) -> float | None:
    """Weighted mean of the NON-IDPTC votes the blend actually counted.

    Uses the pipeline's own ``valueContribution`` (rank → GLOBAL Hill) and
    ``appliedWeight`` (freshness × health × coverage, holds at 0).
    """
    num = 0.0
    den = 0.0
    for key, m in _meta(row).items():
        if key == IDPTC:
            continue
        w = _applied(m)
        v = _positive(m.get("valueContribution"))
        if w > 0 and v is not None:
            num += w * v
            den += w
    return num / den if den > 0 else None


def candidate_c2(
    row: Mapping[str, Any],
    ladder: list[float],
    families: Mapping[str, str],
    *,
    min_families: int = 2,
    min_weight: float = 0.0,
) -> dict[str, Any]:
    """C2 — anchor-free evidence priced on the market's own curve.

    For every non-IDPTC source the blend counted on this row (applied weight
    > 0, so owner holds and fully stale boards are already out; sources in a
    declared lineage with IDPTC — The IDP Show — excluded), take the
    source's shared-market rank (the coordinate the blend itself uses) and read
    IDPTC's published price AT that rank: "what IDPTC would charge if it agreed
    with this source's placement".  Evidence = applied-weight mean of those
    prices.  Gap = ``(IDPTC price − evidence) / mean``.

    Exactly 0 when every source places the player where IDPTC does, so the
    curve-shape artifact of the incumbent cannot arise.  IDPTC's ORDERING of
    this player never enters the evidence side; only its price LEVEL does.

    Refusals (never a zero gap): ``no_idp_market_price``, ``withheld_quarantined``,
    ``no_independent_evidence``, ``insufficient_independent_families``,
    ``insufficient_evidence_weight``.
    """
    out: dict[str, Any] = {"ratio": None, "state": None, "families": [], "evidenceWeight": 0.0}
    market = idptc_market_value(row)
    if market is None:
        out["state"] = "no_idp_market_price"
        return out
    if row.get("quarantined"):
        out["state"] = "withheld_quarantined"
        return out
    num = 0.0
    den = 0.0
    fams: set[str] = set()
    for key, m in sorted(_meta(row).items()):
        if key == IDPTC or families.get(key, key) in BENCHMARK_LINEAGE_FAMILIES:
            continue
        w = _applied(m)
        if w <= 0:
            continue
        price = ladder_value(ladder, m.get("effectiveRank"))
        if price is None or price <= 0:
            continue
        num += w * price
        den += w
        fams.add(families.get(key, key))
    out["families"] = sorted(fams)
    out["evidenceWeight"] = round(den, 4)
    if den <= 0:
        out["state"] = "no_independent_evidence"
        return out
    if len(fams) < min_families:
        out["state"] = "insufficient_independent_families"
        return out
    if den < min_weight:
        out["state"] = "insufficient_evidence_weight"
        return out
    evidence = num / den
    out["ratio"] = _rel_gap(market, evidence)
    out["evidence"] = round(evidence, 1)
    out["state"] = "available"
    return out


def candidate_c3(row: Mapping[str, Any]) -> float | None:
    """C3 — the pipeline's own leave-IDPTC-out value vs IDPTC's price.

    The Consensus Edge construction (``consensus_edge.fair_value``): rebuild
    the board with ``idpTradeCalc`` disabled and compare the result with
    IDPTC's published price.  ``None`` when either side is missing.
    """
    market = idptc_market_value(row)
    fair = _positive(row.get("looRankDerivedValue"))
    if market is None or fair is None:
        return None
    return _rel_gap(market, fair)


def zero_disagreement_baseline(
    row: Mapping[str, Any], hill_global: Mapping[str, float]
) -> float | None:
    """The gap the INCUMBENT reports when every expert agrees with IDPTC.

    Expert votes are priced by the GLOBAL Hill at their shared-market
    percentile; IDPTC's vote is its own published value.  Put an expert at
    IDPTC's own rank and the incumbent still reports
    ``(IDPTC value − GLOBAL_Hill(p_IDPTC)) / mean`` — a pure curve-shape term.
    """
    m = _meta(row).get(IDPTC)
    market = idptc_market_value(row)
    if not m or market is None:
        return None
    rank = _num(m.get("effectiveRank"))
    if rank is None:
        return None
    hill = hill_value(rank_percentile(rank), hill_global["c"], hill_global["s"])
    return _rel_gap(market, float(hill))


# ── extract ───────────────────────────────────────────────────────────────


def _compact_row(row: Mapping[str, Any]) -> dict[str, Any]:
    meta: dict[str, dict[str, Any]] = {}
    for key, v in (row.get("sourceRankMeta") or {}).items():
        if not isinstance(v, Mapping):
            continue
        entry = {f: v.get(f) for f in _META_FIELDS if f in v}
        entry.update({f: True for f in _META_FLAGS if v.get(f)})
        meta[key] = entry
    eff = row.get("effectiveSourceRanks") or {}
    out = {
        "displayName": row.get("displayName"),
        "position": row.get("position"),
        "assetClass": row.get("assetClass"),
        "rankDerivedValue": row.get("rankDerivedValue"),
        "canonicalConsensusRank": row.get("canonicalConsensusRank"),
        "quarantined": bool(row.get("quarantined")),
        "marketGapDirection": row.get("marketGapDirection"),
        "marketGapValueRatio": row.get("marketGapValueRatio"),
        "ktcMarket": row.get("ktcMarket"),
        "effectiveSourceRanks": eff,
        "sourceRankMeta": meta,
    }
    # ``sourceRanks`` is read by the incumbent only when the effective map is
    # empty (display-helpers.js falls back to it), so store it only then.
    if not eff:
        out["sourceRanks"] = row.get("sourceRanks") or {}
    return out


def _offense_weight_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Offense row reduced to what the KTC-share comparison needs."""
    meta = row.get("sourceRankMeta") or {}
    weights = {k: _applied(v) for k, v in meta.items() if isinstance(v, Mapping)}
    total = sum(weights.values())
    ktc = sum(weights.get(k, 0.0) for k in KTC_INPUTS)
    return {
        "name": row.get("displayName"),
        "ktc": bool((row.get("ktcMarket") or {}).get("available")),
        "share": None if total <= 0 else round(ktc / total, 4),
    }


def _idptc_ladder_from_csv(path: Path) -> list[float]:
    import csv

    values: list[float] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for rec in csv.DictReader(fh):
            v = _positive(rec.get("value"))
            if v is not None:
                values.append(v)
    return sorted(values, reverse=True)


def cmd_extract(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(REPO))
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

    archive = ARCHIVE_DIR / args.archive
    archive_bytes = archive.read_bytes()
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
        names = [n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")]
        payload_bytes = zf.read(names[0])
    payload = json.loads(payload_bytes)
    contract = build_api_data_contract(payload)
    rows = contract.get("playersArray") or []

    idp_rows = [_compact_row(r) for r in rows if str(r.get("position") or "") in IDP_POSITIONS]
    offense_rows = [_offense_weight_row(r) for r in rows if r.get("assetClass") == "offense"]
    idp_rows.sort(key=lambda r: (-(r.get("rankDerivedValue") or 0), str(r.get("displayName"))))
    offense_rows.sort(key=lambda r: str(r.get("name")))

    voting = {}
    vs = (contract.get("sourceVotingStatus") or {}).get("sources") or {}
    items = vs.items() if isinstance(vs, Mapping) else [(s.get("key"), s) for s in vs]
    for key, rec in items:
        if not isinstance(rec, Mapping):
            continue
        voting[str(key)] = {
            "family": rec.get("family"),
            "provider": rec.get("provider"),
            "coverage": rec.get("coverage"),
            "voting": rec.get("voting"),
            "status": rec.get("status"),
            "effectiveWeight": rec.get("effectiveWeight"),
            "daysSinceUpdate": rec.get("daysSinceUpdate"),
            "lastGenuineUpdate": rec.get("lastGenuineUpdate"),
        }

    csv_dir = REPO / "CSVs" / "site_raw"
    state_dir = REPO / "data" / "scrape_state"
    # The market's price curve in the SAME coordinate the pipeline's shared-
    # market ladder uses: every positive IDPTC value on the board (offense,
    # IDP and picks), descending.  Verified: FantasyPros' stamped
    # effectiveRank for Micah Parsons (204) is the rank, in this list, of
    # IDPTC's 39th IDP — FantasyPros ranks Parsons 39th.
    ladder = sorted(
        (
            float(v)
            for v in ((r.get("canonicalSiteValues") or {}).get(IDPTC) for r in rows)
            if _positive(v) is not None
        ),
        reverse=True,
    )
    csv_ladder = _idptc_ladder_from_csv(csv_dir / f"{IDPTC}.csv")

    loo: dict[str, Any] | None = None
    loo_values: dict[str, float | None] = {}
    if args.with_loo:
        from src.api.data_contract import shared_market_crosswalk_failed  # noqa: PLC0415
        from src.consensus_edge.fair_value import leave_one_out_board  # noqa: PLC0415

        loo_contract = leave_one_out_board(payload, exclude=[IDPTC])
        loo_rows = loo_contract.get("playersArray") or []
        by_name = {str(r.get("displayName")): r for r in loo_rows}
        for name, other in by_name.items():
            loo_values[name] = _positive(other.get("rankDerivedValue"))
        ratios = []
        for r in rows:
            if str(r.get("position") or "") not in IDP_POSITIONS:
                continue
            base = _positive(r.get("rankDerivedValue"))
            other = by_name.get(str(r.get("displayName")))
            alt = _positive(other.get("rankDerivedValue")) if other else None
            if base is not None and alt is not None:
                ratios.append(alt / base)
        methods: dict[str, int] = {}
        for r in loo_rows:
            if str(r.get("position") or "") not in IDP_POSITIONS:
                continue
            for key, m in (r.get("sourceRankMeta") or {}).items():
                tag = f"{key}:{m.get('method')}"
                methods[tag] = methods.get(tag, 0) + 1
        loo = {
            "crosswalkFailed": shared_market_crosswalk_failed(loo_rows),
            "ladderContributors": (
                (loo_contract.get("crossPositionBridges") or {}).get("ladder") or {}
            ).get("contributors"),
            "baseLadderContributors": (
                (contract.get("crossPositionBridges") or {}).get("ladder") or {}
            ).get("contributors"),
            "idpRowsPricedBoth": len(ratios),
            "looOverBaseRatio": _quantiles(ratios),
            "looOverBaseMin": round(min(ratios), 4) if ratios else None,
            "looOverBaseMax": round(max(ratios), 4) if ratios else None,
            "idpVoteMethods": dict(sorted(methods.items())),
        }

    if args.with_loo:
        for r in idp_rows:
            r["looRankDerivedValue"] = loo_values.get(str(r.get("displayName")))

    fixture = {
        "schema": "w27_f001_idp_edge_rows.v1",
        "provenance": {
            "archive": args.archive,
            "archiveSha256": _sha256_bytes(archive_bytes),
            "payloadMember": names[0],
            "payloadSha256": _sha256_bytes(payload_bytes),
            "scrapeTimestamp": payload.get("scrapeTimestamp"),
            "gitHead": _git("rev-parse", "HEAD").strip(),
            "csvSha256": {f: _sha256_file(csv_dir / f"{f}.csv") for f in IDP_CSV_FILES},
            "datasetStateSha256": {
                f: _sha256_file(state_dir / f"{f}_dataset.json") for f in IDP_CSV_FILES
            },
            "contractVersion": contract.get("contractVersion"),
            "builder": "src.api.data_contract.build_api_data_contract(payload) (csv_root=None)",
        },
        "hillCurves": {
            k: {"c": v.get("c"), "s": v.get("s")}
            for k, v in (contract.get("hillCurves") or {}).items()
            if isinstance(v, Mapping) and "c" in v
        },
        "sourceVotingStatus": dict(sorted(voting.items())),
        "idptcLadder": ladder,
        "idptcLadderSource": "contract canonicalSiteValues.idpTradeCalc, all positions, desc",
        "idptcCsvLadderLength": len(csv_ladder),
        "idpRows": idp_rows,
        "offenseRows": offense_rows,
        "leaveIdptcOut": loo,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(fixture, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    print(f"wrote {out} ({len(idp_rows)} IDP rows, {len(offense_rows)} offense rows)")
    return 0


# ── analyze ───────────────────────────────────────────────────────────────


def _families(fixture: Mapping[str, Any]) -> dict[str, str]:
    return {
        k: str(v.get("family") or k) for k, v in (fixture.get("sourceVotingStatus") or {}).items()
    }


def _count(values: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items()))


def _rank_bucket(rank: float | None) -> str:
    if rank is None:
        return "no_idptc"
    if rank <= 100:
        return "001-100"
    if rank <= 200:
        return "101-200"
    if rank <= 400:
        return "201-400"
    return "401+"


def analyze(fixture: Mapping[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = list(fixture["idpRows"])
    ladder: list[float] = list(fixture["idptcLadder"])
    hill = fixture["hillCurves"]
    fams = _families(fixture)
    result: dict[str, Any] = {"provenance": fixture.get("provenance")}

    # 1. census of the canonical (KTC Market) edge on IDP rows ---------------
    result["census"] = {
        "idpRows": len(rows),
        "byPosition": _count(str(r.get("position")) for r in rows),
        "marketGapDirection": _count(str(r.get("marketGapDirection")) for r in rows),
        "ktcMarketReason": _count(str((r.get("ktcMarket") or {}).get("reason")) for r in rows),
        "rankingsEdgeLabel": _count(incumbent_rankings_edge(r) for r in rows),
        "edgeFilterBuyOrSellMatches": sum(
            1
            for r in rows
            if r.get("marketGapDirection") in ("retail_premium", "consensus_premium")
        ),
        "rowsWithIdptcPrice": sum(1 for r in rows if idptc_market_value(r) is not None),
        "rowsWithoutModelValue": sum(
            1 for r in rows if _positive(r.get("rankDerivedValue")) is None
        ),
    }

    # 2. incumbent /edge detector ---------------------------------------------
    inc = {r["displayName"]: incumbent_idp_edge(r) for r in rows}
    in_panel = [r for r in rows if idp_in_top_by_idptc(r)]
    zero_weight_dependence = 0
    lineage_dependence = 0
    for r in rows:
        v = inc[r["displayName"]]
        if v["kind"] not in ("buy", "sell"):
            continue
        meta = _meta(r)
        eff = r.get("effectiveSourceRanks") or {}
        ranks = eff if eff else (r.get("sourceRanks") or {})
        experts = [k for k in ranks if k != IDPTC and "valueContribution" in (meta.get(k) or {})]
        if any(_applied(meta.get(k) or {}) <= 0 for k in experts):
            zero_weight_dependence += 1
        if any(fams.get(k, k) in BENCHMARK_LINEAGE_FAMILIES for k in experts):
            lineage_dependence += 1
    expert_weight = []
    for r in rows:
        if inc[r["displayName"]]["kind"] in ("buy", "sell"):
            meta = _meta(r)
            expert_weight.append(sum(_applied(m) for k, m in meta.items() if k != IDPTC))
    result["incumbentEdgeDetector"] = {
        "verdicts": _count(v["label"] for v in inc.values()),
        "kinds": _count(v["kind"] for v in inc.values()),
        "contradictsRankings": sum(
            1 for r in rows if inc[r["displayName"]]["kind"] in ("buy", "sell")
        ),
        "panelPopulationTop200ByIdptc": len(in_panel),
        "panelVerdicts": _count(inc[r["displayName"]]["label"] for r in in_panel),
        "verdictsUsingAZeroWeightSource": zero_weight_dependence,
        "verdictsCountingIdptcsOwnAncestorAsAnExpert": lineage_dependence,
        "expertAppliedWeightBehindBuySell": _quantiles(expert_weight),
        "verdictsWithExpertWeightBelowOne": sum(1 for w in expert_weight if w < 1.0),
    }

    # 3. the incumbent's curve-shape artifact ---------------------------------
    hill_checks = 0
    hill_matches = 0
    for r in rows:
        for m in _meta(r).values():
            if m.get("valueContributionPath") != "rank_hill":
                continue
            p = _num(m.get("percentile"))
            v = _num(m.get("valueContribution"))
            if p is None or v is None:
                continue
            hill_checks += 1
            if abs(hill_value(p, hill["global"]["c"], hill["global"]["s"]) - v) <= 1:
                hill_matches += 1
    base = {}
    for r in rows:
        b = zero_disagreement_baseline(r, hill["global"])
        if b is not None:
            base[r["displayName"]] = b
    explained = {"buy": 0, "sell": 0}
    totals = {"buy": 0, "sell": 0}
    for name, v in inc.items():
        if v["kind"] not in totals:
            continue
        totals[v["kind"]] += 1
        b = base.get(name)
        if b is not None and _verdict(b) == v["kind"]:
            explained[v["kind"]] += 1
    by_bucket: dict[str, dict[str, Any]] = {}
    for r in rows:
        m = _meta(r).get(IDPTC) or {}
        bucket = _rank_bucket(_num(m.get("effectiveRank")) if m else None)
        cell = by_bucket.setdefault(
            bucket, {"rows": 0, "baseline": [], "incumbent": [], "c2": [], "c1": []}
        )
        cell["rows"] += 1
        if r["displayName"] in base:
            cell["baseline"].append(base[r["displayName"]])
        cell["incumbent"].append(inc[r["displayName"]]["label"])
    result["incumbentScaleArtifact"] = {
        "hillOracleChecks": hill_checks,
        "hillOracleMatchesWithin1": hill_matches,
        "zeroDisagreementBaseline": _quantiles(list(base.values())),
        "zeroDisagreementVerdicts": _count(_verdict(b) for b in base.values()),
        "incumbentVerdictsMatchingBaselineSign": explained,
        "incumbentVerdictTotals": totals,
    }

    # 4. signal independence --------------------------------------------------
    shares = [s for s in (idptc_weight_share(r) for r in rows) if s is not None]
    sole = 0
    sole_model_eq_market = 0
    sole_haircut = 0
    for r in rows:
        meta = _meta(r)
        active = [k for k, m in meta.items() if _applied(m) > 0]
        if active == [IDPTC]:
            sole += 1
            model = _positive(r.get("rankDerivedValue"))
            market = idptc_market_value(r)
            if model is not None and market is not None:
                if abs(model - market) <= 1:
                    sole_model_eq_market += 1
                elif model < 0.5 * market:
                    sole_haircut += 1
    translated = sum(
        1
        for r in rows
        for k, m in _meta(r).items()
        if k != IDPTC and m.get("sharedMarketTranslated") and _applied(m) > 0
    )
    anchor = sum(1 for r in rows if (_meta(r).get(IDPTC) or {}).get("isAnchor"))
    off_shares = [
        float(r["share"])
        for r in fixture.get("offenseRows") or []
        if r.get("ktc") and r.get("share") is not None
    ]
    voters = _count(k for r in rows for k, m in _meta(r).items() if _applied(m) > 0 and k != IDPTC)
    result["signalIndependence"] = {
        "idptcAppliedWeightShareOnIdpRows": _quantiles(shares),
        "idpRowsWhereIdptcIsTheOnlyVoter": sole,
        "ofThoseModelEqualsIdptc": sole_model_eq_market,
        "ofThoseSingleSourceHaircut": sole_haircut,
        "idptcIsAlphaAnchorOnIdpRows": anchor,
        "nonIdptcVotesTranslatedThroughIdptcLadder": translated,
        "nonIdptcVoterRowCounts": voters,
        "ktcInputsAppliedWeightShareOnOffenseRows": _quantiles(off_shares),
        "sourceVotingStatus": {
            k: fixture["sourceVotingStatus"].get(k)
            for k in IDP_CSV_FILES
            if k in fixture["sourceVotingStatus"]
        },
    }

    # 5. candidates ------------------------------------------------------------
    c1 = {r["displayName"]: candidate_c1(r) for r in rows}
    lao = {r["displayName"]: leave_anchor_out_value_mean(r) for r in rows}
    pairs = []
    for r in rows:
        name = r["displayName"]
        market = idptc_market_value(r)
        if c1[name] is None or lao[name] is None or market is None:
            continue
        pairs.append((_rel_gap(market, lao[name]), c1[name]))
    slope = None
    if len(pairs) >= 2:
        mx = statistics.fmean(p[0] for p in pairs)
        my = statistics.fmean(p[1] for p in pairs)
        sxx = sum((p[0] - mx) ** 2 for p in pairs)
        sxy = sum((p[0] - mx) * (p[1] - my) for p in pairs)
        slope = round(sxy / sxx, 4) if sxx > 0 else None
    sign_agree = sum(1 for a, b in pairs if _verdict(a) == _verdict(b))
    result["candidateC1ModelVsIdptc"] = {
        "verdicts": _count(_verdict(v) for v in c1.values()),
        "absRatio": _quantiles([abs(v) for v in c1.values() if v is not None]),
        "regressionOnLeaveAnchorOutGap": {
            "n": len(pairs),
            "slope": slope,
            "sameVerdict": sign_agree,
        },
        "flipsVsIncumbent": sum(
            1
            for r in rows
            if inc[r["displayName"]]["kind"] in ("buy", "sell")
            and _verdict(c1[r["displayName"]]) in ("buy", "sell")
            and _verdict(c1[r["displayName"]]) != inc[r["displayName"]]["kind"]
        ),
    }

    gates = {
        "ungated": {"min_families": 1, "min_weight": 0.0},
        "twoFamilies": {"min_families": 2, "min_weight": 0.0},
        "twoFamiliesWeight0p5": {"min_families": 2, "min_weight": 0.5},
        "twoFamiliesWeight1p0": {"min_families": 2, "min_weight": 1.0},
    }
    c2_out: dict[str, Any] = {}
    c2_primary: dict[str, dict[str, Any]] = {}
    for gname, kw in gates.items():
        res = {r["displayName"]: candidate_c2(r, ladder, fams, **kw) for r in rows}
        if gname == "twoFamilies":
            c2_primary = res
        c2_out[gname] = {
            "states": _count(v["state"] for v in res.values()),
            "verdicts5pct": _count(_verdict(v["ratio"]) for v in res.values()),
            "verdicts15pct": _count(
                _verdict(v["ratio"], PREMIUM_SUMMARY_VALUE_RATIO) for v in res.values()
            ),
            "absRatio": _quantiles(
                [abs(v["ratio"]) for v in res.values() if v["ratio"] is not None]
            ),
        }
    agree = disagree = 0
    for r in rows:
        a = inc[r["displayName"]]["kind"]
        b = _verdict(c2_primary[r["displayName"]]["ratio"])
        if a in ("buy", "sell") and b in ("buy", "sell"):
            if a == b:
                agree += 1
            else:
                disagree += 1
    c2_out["vsIncumbentOnBothDirectional"] = {"same": agree, "opposite": disagree}
    # Row transitions incumbent -> C2 (ungated: every weighted non-IDPTC vote,
    # one family is enough — the closest like-for-like to the incumbent's own
    # gate, minus the curve artifact and minus zero-weight evidence).
    ungated = {r["displayName"]: candidate_c2(r, ladder, fams, min_families=1) for r in rows}
    c2_out["incumbentToUngatedTransitions"] = _count(
        f"{inc[r['displayName']]['kind']}->{_verdict(ungated[r['displayName']]['ratio'])}"
        for r in rows
        if inc[r["displayName"]]["kind"] in ("buy", "sell", "hold")
    )
    result["candidateC2AnchorFreeOnMarketCurve"] = c2_out

    # Selection on one side of a two-sided comparison manufactures direction
    # (regression toward the mean): the /edge IDP panels admit "top 200 by
    # IDPTC", i.e. they select on the benchmark's own ordering.  Same-size
    # populations selected three ways, scored by C2 (two families, 5%):
    scored = [
        r
        for r in rows
        if c2_primary[r["displayName"]]["state"] == "available" and not r.get("quarantined")
    ]
    k = sum(1 for r in rows if idp_in_top_by_idptc(r))

    def _pick(key) -> dict[str, int]:
        top = sorted(scored, key=key)[:k]
        return _count(_verdict(c2_primary[r["displayName"]]["ratio"]) for r in top)

    result["selectionGateEffect"] = {
        "populationSize": k,
        "topByIdptcRank": _pick(
            lambda r: _num((_meta(r).get(IDPTC) or {}).get("effectiveRank")) or 1e9
        ),
        "topByBoardValue": _pick(lambda r: -(_positive(r.get("rankDerivedValue")) or 0.0)),
        "topByEvidenceValue": _pick(
            lambda r: -(c2_primary[r["displayName"]].get("evidence") or 0.0)
        ),
        "topByMeanOfMarketAndEvidence": _pick(
            lambda r: -(
                (
                    (idptc_market_value(r) or 0.0)
                    + (c2_primary[r["displayName"]].get("evidence") or 0.0)
                )
                / 2.0
            )
        ),
    }

    c3 = {r["displayName"]: candidate_c3(r) for r in rows}
    same = opposite = 0
    for r in rows:
        a = _verdict(c3[r["displayName"]])
        b = _verdict(c2_primary[r["displayName"]]["ratio"])
        if a in ("buy", "sell") and b in ("buy", "sell"):
            if a == b:
                same += 1
            else:
                opposite += 1
    c3_base = []
    for r in rows:
        v = c3[r["displayName"]]
        b = base.get(r["displayName"])
        if v is not None and b is not None:
            c3_base.append((b, v))
    result["candidateC3LeaveIdptcOutBoard"] = {
        "available": fixture.get("leaveIdptcOut") is not None,
        "verdicts5pct": _count(_verdict(v) for v in c3.values()),
        "absRatio": _quantiles([abs(v) for v in c3.values() if v is not None]),
        "vsC2TwoFamiliesOnBothDirectional": {"same": same, "opposite": opposite},
        "rowsWhereC3HasSameVerdictAsZeroDisagreementBaseline": sum(
            1 for b, v in c3_base if _verdict(b) == _verdict(v)
        ),
        "rowsComparedToBaseline": len(c3_base),
    }

    # per-bucket table (incumbent / C1 / C2 two-family) ------------------------
    for r in rows:
        m = _meta(r).get(IDPTC) or {}
        bucket = _rank_bucket(_num(m.get("effectiveRank")) if m else None)
        by_bucket[bucket]["c2"].append(_verdict(c2_primary[r["displayName"]]["ratio"]))
        by_bucket[bucket]["c1"].append(_verdict(c1[r["displayName"]]))
        by_bucket[bucket].setdefault("c3", []).append(_verdict(c3[r["displayName"]]))
    result["byIdptcRankBucket"] = {
        b: {
            "rows": cell["rows"],
            "baselineMedian": _quantiles(cell["baseline"])["median"],
            "incumbent": _count(cell["incumbent"]),
            "c1": _count(cell["c1"]),
            "c2TwoFamilies": _count(cell["c2"]),
            "c3": _count(cell.get("c3", [])),
        }
        for b, cell in sorted(by_bucket.items())
    }

    result["byPosition"] = {
        pos: {
            "rows": sum(1 for r in rows if r.get("position") == pos),
            "incumbent": _count(
                inc[r["displayName"]]["label"] for r in rows if r.get("position") == pos
            ),
            "c1": _count(_verdict(c1[r["displayName"]]) for r in rows if r.get("position") == pos),
            "c2TwoFamilies": _count(
                _verdict(c2_primary[r["displayName"]]["ratio"])
                for r in rows
                if r.get("position") == pos
            ),
            "c3": _count(_verdict(c3[r["displayName"]]) for r in rows if r.get("position") == pos),
        }
        for pos in IDP_POSITIONS
    }

    # named examples (audit players) -------------------------------------------
    examples = {}
    wanted = (
        "Micah Parsons",
        "Abdul Carter",
        "Myles Garrett",
        "Jared Verse",
        "Nick Bolton",
        "Fred Warner",
        "Aidan Hutchinson",
    )
    by_name = {r["displayName"]: r for r in rows}
    for name in wanted:
        r = by_name.get(name)
        if r is None:
            continue
        c2v = c2_primary[name]
        examples[name] = {
            "position": r.get("position"),
            "rankDerivedValue": r.get("rankDerivedValue"),
            "idptcPrice": idptc_market_value(r),
            "rankingsEdge": incumbent_rankings_edge(r),
            "incumbent": inc[name]["label"],
            "incumbentRatio": None if inc[name]["ratio"] is None else round(inc[name]["ratio"], 4),
            "zeroDisagreementBaseline": None if name not in base else round(base[name], 4),
            "c1Ratio": None if c1[name] is None else round(c1[name], 4),
            "c2State": c2v["state"],
            "c2Ratio": None if c2v["ratio"] is None else round(c2v["ratio"], 4),
            "c2EvidenceWeight": c2v["evidenceWeight"],
            "c3Ratio": None if c3[name] is None else round(c3[name], 4),
            "idptcWeightShare": None
            if idptc_weight_share(r) is None
            else round(idptc_weight_share(r), 4),
        }
    result["examples"] = examples
    result["leaveIdptcOut"] = fixture.get("leaveIdptcOut")
    return result


def cmd_analyze(args: argparse.Namespace) -> int:
    fixture = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    out = json.dumps(analyze(fixture), sort_keys=True, indent=1, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(out + "\n", encoding="utf-8")
    print(out)
    return 0


# ── CSV-level oracle + point-in-time history ──────────────────────────────

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def norm_name(name: str) -> str:
    keep = "".join(ch.lower() if ch.isalnum() or ch == " " else " " for ch in str(name or ""))
    parts = [p for p in keep.split() if p not in _SUFFIXES]
    return " ".join(parts)


def idp_group(position: str) -> str | None:
    """Collapse any vendor IDP position spelling to DL / LB / DB."""
    p = str(position or "").upper()
    if any(t in p for t in ("(DL", "(DB")):
        return "DL" if "(DL" in p else "DB"
    token = p.split()[0] if p.split() else ""
    token = "".join(ch for ch in token if ch.isalpha())
    if token in ("DL", "DE", "DT", "ED", "EDGE", "NT"):
        return "DL"
    if token in ("LB", "ILB", "OLB", "MLB"):
        return "LB"
    if token in ("DB", "CB", "S", "SS", "FS"):
        return "DB"
    return None


def _read_csv_text(text: str) -> list[dict[str, str]]:
    import csv

    return list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))


def parse_idptc(text: str, idp_names: frozenset[str] | None = None) -> dict[str, float]:
    """IDP players -> IDPTC published value.

    IDPTC CSVs carry a position column only since 2026-10-21.  For older
    snapshots ``idp_names`` decides membership (names published by an
    IDP-only expert board at that time, or labelled IDP by IDPTC later;
    names IDPTC also labels as offense are excluded as ambiguous).
    """
    out: dict[str, float] = {}
    for rec in _read_csv_text(text):
        name = norm_name(rec.get("name") or "")
        pos = rec.get("position")
        if pos is not None:
            if idp_group(pos) is None:
                continue
        elif idp_names is None or name not in idp_names:
            continue
        v = _positive(rec.get("value"))
        if v is not None:
            out[name] = v
    return out


def idp_name_universe(current_idptc_text: str) -> tuple[frozenset[str], frozenset[str]]:
    """(IDP-labelled names, offense-labelled names) from a positioned IDPTC CSV."""
    idp: set[str] = set()
    off: set[str] = set()
    for rec in _read_csv_text(current_idptc_text):
        name = norm_name(rec.get("name") or "")
        pos = str(rec.get("position") or "").upper()
        if idp_group(pos) is not None:
            idp.add(name)
        elif pos and pos != "PICK":
            off.add(name)
    return frozenset(idp), frozenset(off)


def _within_idp_ranks(entries: list[tuple[str, float]]) -> dict[str, float]:
    """Mid-rank within the IDP-only list (ties share the average position)."""
    entries = sorted(entries, key=lambda t: (t[1], t[0]))
    out: dict[str, float] = {}
    i = 0
    while i < len(entries):
        j = i
        while j + 1 < len(entries) and entries[j + 1][1] == entries[i][1]:
            j += 1
        mid = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            out.setdefault(entries[k][0], mid)
        i = j + 1
    return out


def parse_expert(key: str, text: str) -> dict[str, float]:
    """Within-IDP rank per player for one expert board, or {} if unparseable."""
    recs = _read_csv_text(text)
    entries: list[tuple[str, float]] = []
    for rec in recs:
        if key == "draftSharksIdp":
            name = rec.get("Player") or ""
            pos = rec.get("Fantasy Position") or ""
            rank = _num(rec.get("Rank"))
        elif key == "fantasyProsIdp":
            name = rec.get("name") or ""
            pos = rec.get("family") or rec.get("position") or ""
            # ``effectiveRank`` is the vendor-derived overall IDP rank (it
            # differs from ``originalRank`` for family-only listings).
            rank = _num(rec.get("effectiveRank") or rec.get("originalRank") or rec.get("rank"))
        else:  # dlfIdp, idpShowCombined
            name = rec.get("name") or ""
            pos = rec.get("position") or ""
            rank = _num(rec.get("rank"))
            # dlfIdp is an IDP-only list; older snapshots carry no position.
            if key == "dlfIdp" and "position" not in rec:
                pos = "LB"
        if rank is None or idp_group(pos) is None:
            continue
        entries.append((norm_name(name), rank))
    return _within_idp_ranks(entries)


def csv_c2(
    idptc: Mapping[str, float],
    experts: Mapping[str, Mapping[str, float]],
    weights: Mapping[str, float] | None = None,
    min_sources: int = 2,
) -> dict[str, float]:
    """CSV-level C2: each expert's within-IDP rank priced on IDPTC's IDP ladder.

    ``V_idp(k)`` = IDPTC's k-th highest IDP price.  An expert who places a
    player k-th among IDP "would charge" ``V_idp(k)``; evidence = (weighted)
    mean over experts.  Same zero point as the contract-level C2.
    """
    ladder = sorted(idptc.values(), reverse=True)
    out: dict[str, float] = {}
    for name, market in idptc.items():
        num = 0.0
        den = 0.0
        n = 0
        for key, ranks in experts.items():
            k = ranks.get(name)
            if k is None:
                continue
            price = ladder_value(ladder, k)
            if price is None:
                continue
            w = 1.0 if weights is None else float(weights.get(key, 0.0))
            if w <= 0:
                continue
            num += w * price
            den += w
            n += 1
        if n >= min_sources and den > 0:
            out[name] = _rel_gap(market, num / den)
    return out


def csv_incumbent_like(
    idptc_idp: Mapping[str, float],
    all_values: list[float],
    experts: Mapping[str, Mapping[str, float]],
    hill_c: float,
    hill_s: float,
) -> dict[str, float]:
    """CSV-level approximation of the incumbent /edge detector.

    Each expert's within-IDP rank k is lifted to the shared-market rank of
    IDPTC's k-th IDP (rank among ALL IDPTC values, picks included — the
    pipeline's ladder coordinate), priced by the GLOBAL Hill, and the
    unweighted expert mean is compared with IDPTC's own value.  Exact for
    ladder-translated boards (FantasyPros, DLF); an approximation for Draft
    Sharks / IDP Show, which the pipeline places with their own combined lists.
    """
    idp_sorted = sorted(idptc_idp.values(), reverse=True)
    all_sorted = sorted(all_values, reverse=True)

    def overall_rank(v: float) -> int:
        lo, hi = 0, len(all_sorted)
        while lo < hi:  # count of values strictly greater than v
            mid = (lo + hi) // 2
            if all_sorted[mid] > v:
                lo = mid + 1
            else:
                hi = mid
        return lo + 1

    out: dict[str, float] = {}
    for name, market in idptc_idp.items():
        prices = []
        for ranks in experts.values():
            k = ranks.get(name)
            if k is None:
                continue
            slot = ladder_value(idp_sorted, k)
            if slot is None:
                continue
            prices.append(hill_value(rank_percentile(overall_rank(slot)), hill_c, hill_s))
        if prices:
            out[name] = _rel_gap(market, statistics.fmean(prices))
    return out


def _all_values(text: str) -> list[float]:
    return [v for v in (_positive(r.get("value")) for r in _read_csv_text(text)) if v is not None]


def _git_file_at(path: str, when: str) -> str | None:
    sha = _git("rev-list", "-1", f"--before={when}", "HEAD", "--", path).strip()
    if not sha:
        return None
    try:
        return _git("show", f"{sha}:{path}")
    except subprocess.CalledProcessError:
        return None


def _last_change_on_or_before(path: str, when: str) -> str | None:
    out = _git("log", "-1", "--format=%cs", f"--before={when}", "--", path).strip()
    return out or None


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None

    def ranks(v: list[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2.0
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def cmd_history(args: argparse.Namespace) -> int:
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    horizon = timedelta(days=args.horizon_days)
    experts_keys = ("dlfIdp", "fantasyProsIdp", "draftSharksIdp", "idpShowCombined")
    origins = []
    d = start
    while d + horizon <= end:
        origins.append(d)
        d += timedelta(days=args.step_days)

    report: dict[str, Any] = {
        "gitHead": _git("rev-parse", "HEAD").strip(),
        "horizonDays": args.horizon_days,
        "stepDays": args.step_days,
        "origins": [],
    }
    pooled: dict[str, list[tuple[float, float]]] = {
        "allExperts": [],
        "freshExperts": [],
        "incumbentLike": [],
    }
    head_idptc = _git("show", "HEAD:CSVs/site_raw/idpTradeCalc.csv")
    later_idp, later_off = idp_name_universe(head_idptc)
    for origin in origins:
        t0 = f"{origin.isoformat()} 23:59:59 +0000"
        t1 = f"{(origin + horizon).isoformat()} 23:59:59 +0000"
        m0_text = _git_file_at("CSVs/site_raw/idpTradeCalc.csv", t0)
        m1_text = _git_file_at("CSVs/site_raw/idpTradeCalc.csv", t1)
        if not m0_text or not m1_text:
            continue
        experts: dict[str, dict[str, float]] = {}
        fresh: dict[str, dict[str, float]] = {}
        expert_dates: dict[str, str | None] = {}
        for key in experts_keys:
            path = f"CSVs/site_raw/{key}.csv"
            text = _git_file_at(path, t0)
            if not text:
                continue
            ranks = parse_expert(key, text)
            if not ranks:
                continue
            experts[key] = ranks
            changed = _last_change_on_or_before(path, t0)
            expert_dates[key] = changed
            if changed and (origin - date.fromisoformat(changed)).days <= args.fresh_days:
                fresh[key] = ranks
        names_at_t = set(later_idp)
        for ranks in experts.values():
            names_at_t.update(ranks)
        idp_names = frozenset(n for n in names_at_t if n not in later_off)
        m0 = parse_idptc(m0_text, idp_names)
        m1 = parse_idptc(m1_text, idp_names)
        changed_players = sum(1 for n, v in m0.items() if n in m1 and abs(m1[n] - v) > 0)
        common = [n for n in m0 if n in m1]
        cohort = [math.log(m1[n] / m0[n]) for n in common]
        drift = statistics.median(cohort) if cohort else 0.0
        entry: dict[str, Any] = {
            "origin": origin.isoformat(),
            "idptcIdpPlayers": len(m0),
            "idptcPlayersWithPriceChange": changed_players,
            "idptcCohortMedianLogMove": round(drift, 5),
            "expertBoards": {k: len(v) for k, v in experts.items()},
            "expertLastContentChange": expert_dates,
            "freshExpertBoards": sorted(fresh),
        }
        # C2 never takes evidence from IDPTC's own lineage (The IDP Show);
        # the incumbent-like replay keeps it, as the incumbent does.
        independent = {k: v for k, v in experts.items() if k != "idpShowCombined"}
        independent_fresh = {k: v for k, v in fresh.items() if k != "idpShowCombined"}
        signals = {
            "allExperts": csv_c2(m0, independent),
            "freshExperts": csv_c2(m0, independent_fresh),
            "incumbentLike": csv_incumbent_like(
                m0, _all_values(m0_text), experts, args.hill_c, args.hill_s
            ),
        }
        for label, sig in signals.items():
            obs = []
            for name, s in sig.items():
                if name not in m1:
                    continue
                y = math.log(m1[name] / m0[name]) - drift
                obs.append((s, y))
            pooled[label].extend(obs)
            directional = [(s, y) for s, y in obs if abs(s) >= MARKET_GAP_MIN_VALUE_RATIO]
            moved = [(s, y) for s, y in directional if y != 0]
            hits = sum(1 for s, y in moved if (y < 0) == (s > 0))
            entry[label] = {
                "signals": len(obs),
                "directional": len(directional),
                "directionalWithMove": len(moved),
                "hitRate": None if not moved else round(hits / len(moved), 4),
                "spearmanSignalVsMove": None
                if _spearman([s for s, _ in obs], [y for _, y in obs]) is None
                else round(_spearman([s for s, _ in obs], [y for _, y in obs]), 4),
            }
        report["origins"].append(entry)
    summary = {}
    for label, obs in pooled.items():
        directional = [(s, y) for s, y in obs if abs(s) >= MARKET_GAP_MIN_VALUE_RATIO]
        moved = [(s, y) for s, y in directional if y != 0]
        hits = sum(1 for s, y in moved if (y < 0) == (s > 0))
        rho = _spearman([s for s, _ in obs], [y for _, y in obs])
        summary[label] = {
            "observations": len(obs),
            "directional": len(directional),
            "directionalWithMove": len(moved),
            "hitRate": None if not moved else round(hits / len(moved), 4),
            "spearmanSignalVsMove": None if rho is None else round(rho, 4),
            "note": "expected sign of rho is NEGATIVE if the market converges to the evidence",
        }
    report["pooled"] = summary
    out = json.dumps(report, sort_keys=True, indent=1)
    if args.out:
        Path(args.out).write_text(out + "\n", encoding="utf-8")
    print(out)
    return 0


def cmd_oracle(args: argparse.Namespace) -> int:
    """Recompute the FantasyPros half of C2 from the raw CSVs and compare.

    Independent of the pipeline: own CSV parsing, own name join, own IDP
    ladder.  For every board row where FantasyPros voted, the contract-level
    C2 prices FantasyPros at ``ladder(effectiveRank)``; the oracle prices it at
    ``V_idp(within-IDP rank)``.  They must agree if the shared-market ladder
    means what the proposal says it means.
    """
    fixture = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    ladder = list(fixture["idptcLadder"])
    csv_dir = REPO / "CSVs" / "site_raw"
    idptc = parse_idptc((csv_dir / "idpTradeCalc.csv").read_text(encoding="utf-8"))
    fp = parse_expert(
        "fantasyProsIdp", (csv_dir / "fantasyProsIdp.csv").read_text(encoding="utf-8")
    )
    idp_ladder = sorted(idptc.values(), reverse=True)
    method_by_name = {
        norm_name(rec.get("name") or ""): str(rec.get("derivationMethod") or "")
        for rec in _read_csv_text((csv_dir / "fantasyProsIdp.csv").read_text(encoding="utf-8"))
    }
    by_method: dict[str, dict[str, int]] = {}
    checked = matched = joined_missing = 0
    worst: list[tuple[float, str]] = []
    for r in fixture["idpRows"]:
        m = (r.get("sourceRankMeta") or {}).get("fantasyProsIdp")
        if not m:
            continue
        k = fp.get(norm_name(r.get("displayName") or ""))
        if k is None:
            joined_missing += 1
            continue
        a = ladder_value(ladder, m.get("effectiveRank"))
        b = ladder_value(idp_ladder, k)
        if a is None or b is None:
            continue
        checked += 1
        rel = abs(a - b) / ((a + b) / 2.0)
        method = method_by_name.get(norm_name(r.get("displayName") or ""), "unknown")
        cell = by_method.setdefault(method, {"checked": 0, "agree": 0})
        cell["checked"] += 1
        if rel <= 0.02:
            matched += 1
            cell["agree"] += 1
        worst.append((rel, r.get("displayName") or ""))
    worst.sort(reverse=True)
    out = {
        "fantasyProsVotesChecked": checked,
        "agreeWithinTwoPercent": matched,
        "notJoinedByName": joined_missing,
        "byVendorDerivationMethod": dict(sorted(by_method.items())),
        "worst": [{"name": n, "relDiff": round(v, 4)} for v, n in worst[:5]],
    }
    print(json.dumps(out, sort_keys=True, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ex = sub.add_parser("extract", help="build the pinned board once and write the fixture")
    p_ex.add_argument("--archive", default=DEFAULT_ARCHIVE)
    p_ex.add_argument("--out", default=str(DEFAULT_FIXTURE))
    p_ex.add_argument(
        "--with-loo", action="store_true", help="also build the leave-IDPTC-out board"
    )
    p_ex.set_defaults(func=cmd_extract)

    p_an = sub.add_parser("analyze", help="pure analysis over the fixture")
    p_an.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    p_an.add_argument("--out", default=None)
    p_an.set_defaults(func=cmd_analyze)

    p_or = sub.add_parser("oracle", help="CSV-level recomputation of the FantasyPros half of C2")
    p_or.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    p_or.set_defaults(func=cmd_oracle)

    p_hi = sub.add_parser("history", help="point-in-time replay over tracked CSV history")
    p_hi.add_argument("--start", default="2026-07-27")
    p_hi.add_argument("--end", default="2026-11-07")
    p_hi.add_argument("--horizon-days", type=int, default=28)
    p_hi.add_argument("--step-days", type=int, default=7)
    p_hi.add_argument("--fresh-days", type=int, default=14)
    # GLOBAL Hill scope master, unchanged since 2026-07-29 (contract
    # hillCurves.provenance asOf), so one pair covers every origin.
    p_hi.add_argument("--hill-c", type=float, default=0.112)
    p_hi.add_argument("--hill-s", type=float, default=0.725)
    p_hi.add_argument("--out", default=None)
    p_hi.set_defaults(func=cmd_history)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
