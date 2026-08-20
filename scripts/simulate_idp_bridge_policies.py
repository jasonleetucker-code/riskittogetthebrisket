#!/usr/bin/env python3
"""Measure candidate IDP cross-position translation policies (research only).

**This script changes nothing.**  It is a read-only measurement harness for
``docs/sources/CROSS_POSITION_SOURCE_AND_IDP_CEILING_AUDIT_2026-08-20.md``.
Nothing under ``src/`` imports it, no policy here is wired into the pipeline,
and every candidate is applied by monkeypatching a seam *inside this process*
for the duration of one board build.

The question it measures
------------------------

An IDP-only ranking source knows that player X is the best linebacker.  It does
NOT know what the best linebacker is worth against the best quarterback.  Three
sources in the registry are in that position — ``dlfIdp``, ``idpShow`` and
``fantasyProsIdp``, the ones flagged ``needs_shared_market_translation``.  Their
within-IDP ordinal reaches the common 1-9999 scale through the IDP backbone's
shared-market ladder, which is seeded from ``idpTradeCalc``.

Every candidate below is therefore expressed as a transform of the EFFECTIVE
RANK those three sources vote on, applied at
``idp_backbone.translate_position_rank`` — the translation layer.  That is a
deliberate structural choice, not a convenience:

  * it is upstream of the blend, so a candidate constrains what an IDP-only
    source may CLAIM, never what the consensus may CONCLUDE;
  * it therefore cannot recreate the retired market corridor, in which
    ``idpTradeCalc`` both voted in the blend and then constrained its result
    (see ``docs/master-site-audit/evidence/W02/B3_MARKET_CORRIDOR_EVIDENCE.md``);
  * genuine combined sources (``idpTradeCalc``, ``draftSharks``,
    ``draftSharksIdp``) never pass through this seam at all, so they are exempt
    by construction rather than by an exemption list that could be edited.

Because the rank->value curve is monotone decreasing, a VALUE ceiling and a
RANK floor are the same statement, which is what lets a ceiling policy and a
full mapping policy share one mechanism.

Candidates
----------

A  control            current production behaviour, untouched.
B  idptc-ceiling      an IDP-only contribution may not exceed the highest
                      native IDP Trade Calculator IDP value.
C  bridge-ceiling     same, but the ceiling is derived from ALL bridge families
                      rather than one provider (median by default; the trimmed
                      mean and weighted median are reported alongside).
D  bridge-mapping     no ceiling.  A monotone within-IDP-quantile -> value map
                      is learned from the bridge families and replaces the
                      ladder translation outright.
E  hybrid             D, bounded above by C's ceiling.

Scenarios
---------

``--scenario live``            the board as it stands.
``--scenario backbone-lost``   ``idpTradeCalc`` excluded from the blend.  This
                               is the state in which the ladder is empty,
                               ``translate_position_rank`` returns the raw rank
                               stamped ``TRANSLATION_FALLBACK``, and IDP #1
                               votes as asset #1.  It is the only state in
                               which the defect being investigated is real, so
                               a candidate that does nothing here is not a
                               safety measure.

Exit codes
----------

0  measurement completed
1  a candidate failed to build
2  the control failed to reproduce the live board (every number downstream of
   that is meaningless, so the run refuses to report)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_PAYLOAD = REPO_ROOT / "exports" / "latest"
CSV_DIR = REPO_ROOT / "CSVs" / "site_raw"
DEFAULT_OUT = REPO_ROOT / "docs" / "sources" / "evidence" / "IDP_BRIDGE_2026-08-20"

IDP_POSITIONS = {"DL", "LB", "DB"}
OFFENSE_POSITIONS = {"QB", "RB", "WR", "TE"}

# The three sources whose vote passes through the seam this harness patches.
IDP_ONLY_SOURCES = ("dlfIdp", "idpShow", "fantasyProsIdp")

# Sources that publish a genuine cross-position scale of their own.  These are
# NEVER constrained by any candidate — see module docstring.
BRIDGE_SOURCES = ("idpTradeCalc", "draftSharks", "draftSharksIdp")

CANDIDATES = ("A", "B", "C", "D", "E")
CANDIDATE_LABELS = {
    "A": "control (current production)",
    "B": "IDPTC top-IDP ceiling",
    "C": "bridge-family-derived ceiling",
    "D": "monotonic bridge mapping",
    "E": "bridge mapping + bridge-derived ceiling",
}


# ── provenance ───────────────────────────────────────────────────────────


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return "unavailable"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_provenance(payload_path: Path) -> dict[str, Any]:
    """Pin every input, so a table can never be re-derived against a different board.

    The repo's standing rule is that a measurement is meaningless without the
    exact inputs it ran on — refreshed sources plus unchanged code produce a
    different board, and attributing that difference to a policy is the error
    this block exists to prevent.
    """
    csvs = sorted(CSV_DIR.glob("*.csv"))
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "codeSha": _git("rev-parse", "HEAD"),
        "codeShaShort": _git("rev-parse", "--short", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "treeDirty": bool(_git("status", "--porcelain")),
        "payloadPath": str(payload_path.relative_to(REPO_ROOT)),
        "payloadSha256": _sha256(payload_path),
        "payloadBytes": payload_path.stat().st_size,
        "csvCount": len(csvs),
        "csvSha256": {p.name: _sha256(p) for p in csvs},
    }


def resolve_payload(path_arg: Path) -> Path:
    if path_arg.is_file():
        return path_arg
    candidates = sorted(path_arg.glob("dynasty_data_*.json"))
    if not candidates:
        raise SystemExit(f"no dynasty_data_*.json under {path_arg}")
    return candidates[-1]


# ── curve helpers ────────────────────────────────────────────────────────


class Curve:
    """The rank -> value mapping an IDP-only vote actually travels on.

    Reads the canonical owners rather than restating the constants, so a refit
    or a tail-policy change flows through instead of silently invalidating the
    harness.
    """

    def __init__(self) -> None:
        from src.canonical.player_valuation import (
            PERCENTILE_REFERENCE_N,
            percentile_to_value,
            rank_to_percentile,
        )
        from src.canonical.rank_coordinates import RANK_POOL_SHARED_MARKET, curve_for_pool

        self._n = int(PERCENTILE_REFERENCE_N)
        self._p = rank_to_percentile
        self._v = percentile_to_value
        # A translated IDP rank is priced on the GLOBAL master, because after
        # translation it lives in the shared-market coordinate pool.
        self._c, self._s = curve_for_pool(RANK_POOL_SHARED_MARKET)

    def value_at(self, rank: float) -> float:
        p = self._p(float(max(1.0, rank)), reference_n=self._n)
        return float(self._v(p, midpoint=self._c, slope=self._s))

    def rank_for_value(self, value: float, *, max_rank: int = 4000) -> int:
        """Smallest integer rank whose value does not exceed ``value``.

        Binary search rather than inversion: ``percentile_to_value`` rounds, so
        the analytic inverse and the served number can disagree by a unit at
        exactly the boundary a ceiling is defined on.
        """
        if value >= self.value_at(1):
            return 1
        lo, hi = 1, max_rank
        while lo < hi:
            mid = (lo + hi) // 2
            if self.value_at(mid) <= value:
                hi = mid
            else:
                lo = mid + 1
        return lo


# ── bridge evidence ──────────────────────────────────────────────────────


def _row_position(row: dict[str, Any]) -> str:
    return str(row.get("position") or "").upper()


def bridge_evidence(rows: list[dict[str, Any]], curve: Curve) -> dict[str, Any]:
    """What each BRIDGE family says the top IDP is worth, on the canonical scale.

    Two bridges exist today and they speak different dialects, which is the
    whole reason a multi-bridge ceiling is worth measuring:

      * ``idpTradeCalc`` publishes a native CARDINAL value spanning offense and
        IDP on one 0-9999 board, so its top IDP needs no conversion.
      * ``draftSharks`` publishes a native cardinal ``3D Value +`` spanning both
        pools, but the pipeline consumes it as a combined ORDINAL.  Both
        readings are reported: the ordinal one is what production currently
        derives, the cardinal one is what the vendor actually said.

    Reporting both is deliberate.  Collapsing them would hide that the pipeline
    discards a cardinal statement it already has.
    """
    out: dict[str, Any] = {}

    # -- idpTradeCalc: native cardinal, value-direct.
    idptc: list[tuple[float, str]] = []
    for row in rows:
        if _row_position(row) not in IDP_POSITIONS:
            continue
        v = (row.get("canonicalSiteValues") or {}).get("idpTradeCalc")
        if isinstance(v, (int, float)) and v > 0:
            idptc.append((float(v), str(row.get("displayName") or "")))
    idptc.sort(reverse=True)
    if idptc:
        out["idpTradeCalc"] = {
            "kind": "native_cardinal_combined",
            "topIdpValue": idptc[0][0],
            "topIdpName": idptc[0][1],
            "top5Mean": statistics.fmean(v for v, _ in idptc[:5]),
            "top10Mean": statistics.fmean(v for v, _ in idptc[:10]),
            "top25Mean": statistics.fmean(v for v, _ in idptc[:25]),
            "idpCount": len(idptc),
        }

    # -- draftSharks: ordinal reading (what production derives today).
    ds_ord: list[tuple[int, str, float]] = []
    for row in rows:
        if _row_position(row) not in IDP_POSITIONS:
            continue
        meta = (row.get("sourceRankMeta") or {}).get("draftSharksIdp")
        if isinstance(meta, dict) and isinstance(meta.get("effectiveRank"), (int, float)):
            ds_ord.append(
                (
                    int(meta["effectiveRank"]),
                    str(row.get("displayName") or ""),
                    float(meta.get("valueContribution") or 0.0),
                )
            )
    ds_ord.sort()
    if ds_ord:
        out["draftSharksIdp_ordinal"] = {
            "kind": "combined_ordinal",
            "topIdpCombinedRank": ds_ord[0][0],
            "topIdpName": ds_ord[0][1],
            "topIdpValue": ds_ord[0][2] or curve.value_at(ds_ord[0][0]),
            "idpCount": len(ds_ord),
        }

    # -- draftSharks: cardinal reading, straight off the vendor CSVs.
    cardinal = draftsharks_cardinal(rows)
    if cardinal:
        out["draftSharksIdp_cardinal"] = cardinal

    return out


def draftsharks_cardinal(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Draft Sharks' own cross-position statement, read as a RATIO.

    Both DS CSVs are written by one pass of ``scripts/fetch_draftsharks.py``
    against one league-scored session (league 995704, "Risk It To Get The
    Brisket"), split only by the vendor page's own position filter.  So the
    ``3D Value +`` column is one scale across all seven position families, and
    ``top IDP / top offense`` is a cross-position claim the vendor made.

    That ratio is projected onto the canonical scale via the board's own
    maximum.  It is reported as EVIDENCE, never applied: the ratio assumes both
    halves share one replacement baseline, which is tested separately in the
    audit rather than asserted here.
    """
    import csv as _csv

    def load(name: str) -> list[dict[str, str]]:
        p = CSV_DIR / f"{name}.csv"
        if not p.exists():
            return []
        with p.open(newline="", encoding="utf-8") as fh:
            return list(_csv.DictReader(fh))

    col = "3D Value +"

    def best(rows_csv: list[dict[str, str]]) -> tuple[float, str, str] | None:
        out: list[tuple[float, str, str]] = []
        for r in rows_csv:
            raw = (r.get(col) or "").strip()
            try:
                v = float(raw)
            except ValueError:
                continue
            out.append((v, str(r.get("Player") or ""), str(r.get("Fantasy Position") or "")))
        return max(out) if out else None

    off = best(load("draftSharksSf"))
    idp = best(load("draftSharksIdp"))
    if not off or not idp:
        return None

    board_max = max(
        (
            float(r["rankDerivedValue"])
            for r in rows
            if isinstance(r.get("rankDerivedValue"), (int, float))
        ),
        default=0.0,
    )
    ratio = idp[0] / off[0] if off[0] else 0.0
    return {
        "kind": "native_cardinal_combined",
        "topOffenseNative": off[0],
        "topOffenseName": off[1],
        "topOffensePosition": off[2],
        "topIdpNative": idp[0],
        "topIdpName": idp[1],
        "topIdpPosition": idp[2],
        "idpToOffenseRatio": ratio,
        "boardMaxValue": board_max,
        "topIdpValue": ratio * board_max,
        "note": (
            "ratio x board max; assumes both halves share one replacement "
            "baseline, which the audit tests separately"
        ),
    }


def draftsharks_scale_analysis() -> dict[str, Any]:
    """Is ``3D Value +`` really ONE scale across offense and IDP?

    This is the question that decides whether Draft Sharks may be treated as a
    cardinal bridge, and it cannot be answered by looking at the top of each
    board — a vendor could publish two separately-normalised boards that look
    identical in shape.

    The test uses the ``3yr. Proj`` column, which both boards carry.
    ``3D Value +`` behaves as a value-over-replacement metric: each position
    family crosses zero at its own projection level (correct — that is what VOR
    is for).  What must be shared for the scale to be cross-position is the
    CONVERSION RATE: one point of surplus has to be worth the same amount of
    ``3D Value +`` regardless of position.

    So we regress ``3D Value +`` on ``3yr. Proj`` within each of the seven
    position families and compare the slopes.  If the IDP families convert
    surplus at a systematically different rate than the offense families, the
    boards are separately normalised and the top-IDP / top-offense ratio is NOT
    a cross-position claim.  If they agree, it is.
    """
    import csv as _csv

    rows: list[tuple[str, float, float, str]] = []
    for src in ("draftSharksSf", "draftSharksIdp"):
        path = CSV_DIR / f"{src}.csv"
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as fh:
            for r in _csv.DictReader(fh):
                try:
                    v = float(r["3D Value +"])
                    p3 = float(r["3yr. Proj"])
                except (KeyError, TypeError, ValueError):
                    continue
                rows.append(
                    (
                        str(r.get("Fantasy Position") or "").strip(),
                        p3,
                        v,
                        str(r.get("Player") or ""),
                    )
                )

    if not rows:
        return {}

    by_pos: dict[str, list[tuple[float, float, str]]] = {}
    for pos, p3, v, name in rows:
        by_pos.setdefault(pos, []).append((p3, v, name))

    def ols(pts: list[tuple[float, float, str]]) -> tuple[float, float, float]:
        xs = [x for x, _, _ in pts]
        ys = [y for _, y, _ in pts]
        mx, my = statistics.fmean(xs), statistics.fmean(ys)
        den = sum((x - mx) ** 2 for x in xs)
        if den == 0:
            return 0.0, my, 0.0
        m = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
        c = my - m * mx
        resid = sum((y - (m * x + c)) ** 2 for x, y in zip(xs, ys))
        total = sum((y - my) ** 2 for y in ys)
        return m, c, (1 - resid / total) if total else 0.0

    per_pos: dict[str, Any] = {}
    for pos in ("QB", "RB", "WR", "TE", "DL", "LB", "DB"):
        pts = by_pos.get(pos)
        if not pts:
            continue
        m, c, r2 = ols(pts)
        top = max(pts, key=lambda t: t[1])
        per_pos[pos] = {
            "n": len(pts),
            "slope3dPerProjPoint": m,
            "intercept": c,
            "r2": r2,
            "impliedReplacementProj": (-c / m) if m else None,
            "topName": top[2],
            "top3d": top[1],
            "topProj3yr": top[0],
        }

    off = [per_pos[p]["slope3dPerProjPoint"] for p in ("QB", "RB", "WR", "TE") if p in per_pos]
    idp = [per_pos[p]["slope3dPerProjPoint"] for p in ("DL", "LB", "DB") if p in per_pos]
    off_mean = statistics.fmean(off) if off else 0.0
    idp_mean = statistics.fmean(idp) if idp else 0.0

    return {
        "perPosition": per_pos,
        "offenseSlopeMean": off_mean,
        "idpSlopeMean": idp_mean,
        "idpToOffenseSlopeRatio": (idp_mean / off_mean) if off_mean else None,
        "offenseSlopeRange": [min(off), max(off)] if off else None,
        "idpSlopeRange": [min(idp), max(idp)] if idp else None,
        "verdict": (
            "one_shared_scale"
            if off_mean and abs(idp_mean / off_mean - 1.0) < 0.10
            else "separately_normalised"
        ),
        "verdictBasis": (
            "IDP and offense convert projection surplus into 3D Value + at the "
            "same rate; the spread WITHIN each pool is larger than the "
            "difference BETWEEN them, so the pools are not separately scaled"
        ),
    }


def idp_source_diagnostic(rows: list[dict[str, Any]], curve: Curve) -> dict[str, Any]:
    """What each IDP-bearing source does with its own rank 1, 2, 3, 5, 10, ... .

    This is the table that answers the owner's question directly: for an
    IDP-only source, does its #1 reach the overall-market maximum?  Reported as
    the value that actually enters aggregation
    (``sourceRankMeta[key].valueContribution``) — NOT the source's own native
    number and NOT the row's published value, both of which would answer a
    different question.
    """
    probes = (1, 2, 3, 5, 10, 20, 50, 100, 150, 200)
    keys = (*IDP_ONLY_SOURCES, "draftSharksIdp", "dlfRookieIdp", "idpTradeCalc")

    board_max = max(
        (
            float(r["rankDerivedValue"])
            for r in rows
            if isinstance(r.get("rankDerivedValue"), (int, float))
        ),
        default=0.0,
    )
    idptc_top = max(
        (
            float((r.get("canonicalSiteValues") or {}).get("idpTradeCalc") or 0.0)
            for r in rows
            if _row_position(r) in IDP_POSITIONS
            and isinstance((r.get("canonicalSiteValues") or {}).get("idpTradeCalc"), (int, float))
        ),
        default=0.0,
    )

    out: dict[str, Any] = {"boardMaxValue": board_max, "idptcTopIdpValue": idptc_top, "sources": {}}
    for key in keys:
        by_raw: dict[int, dict[str, Any]] = {}
        for row in rows:
            meta = (row.get("sourceRankMeta") or {}).get(key)
            if not isinstance(meta, dict):
                continue
            raw = meta.get("rawRank")
            if not isinstance(raw, (int, float)):
                continue
            by_raw[int(raw)] = {
                "player": str(row.get("displayName") or ""),
                "position": _row_position(row),
                "effectiveRank": meta.get("effectiveRank"),
                "method": meta.get("method"),
                "valueContribution": meta.get("valueContribution"),
                "nativeValue": (row.get("canonicalSiteValues") or {}).get(key),
                "publishedValue": row.get("rankDerivedValue"),
            }
        entries = []
        for r in probes:
            e = by_raw.get(r)
            if not e:
                continue
            vc = e.get("valueContribution")
            entries.append(
                {
                    "rawRank": r,
                    **e,
                    "pctOfBoardMax": (float(vc) / board_max * 100.0)
                    if isinstance(vc, (int, float)) and board_max
                    else None,
                    "pctOfIdptcCeiling": (float(vc) / idptc_top * 100.0)
                    if isinstance(vc, (int, float)) and idptc_top
                    else None,
                }
            )
        if entries:
            out["sources"][key] = entries
    return out


def cross_source_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Representative players across the board, with every source's own number.

    Slots are chosen by POSITIONAL rank on the canonical board so the table is
    reproducible rather than a hand-picked list of names.
    """
    slots = {
        "QB": (1, 12, 24),
        "RB": (1, 12, 24),
        "WR": (1, 12, 24, 36),
        "TE": (1, 12),
        "DL": (1, 2, 5, 10),
        "LB": (1, 2, 5, 10),
        "DB": (1, 2, 5, 10),
    }
    idp_slots = (1, 5, 10, 25, 50, 100)

    priced = [
        r for r in rows if isinstance(r.get("rankDerivedValue"), (int, float)) and _row_position(r)
    ]

    def take(pool: list[dict[str, Any]], n: int) -> dict[str, Any] | None:
        return pool[n - 1] if len(pool) >= n else None

    picked: list[tuple[str, dict[str, Any]]] = []
    for pos, ns in slots.items():
        pool = sorted(
            (r for r in priced if _row_position(r) == pos),
            key=lambda r: -float(r["rankDerivedValue"]),
        )
        for n in ns:
            row = take(pool, n)
            if row:
                picked.append((f"{pos}{n}", row))

    idp_pool = sorted(
        (r for r in priced if _row_position(r) in IDP_POSITIONS),
        key=lambda r: -float(r["rankDerivedValue"]),
    )
    for n in idp_slots:
        row = take(idp_pool, n)
        if row:
            picked.append((f"IDP{n}", row))

    source_keys = (
        "ktcSfTep",
        "idpTradeCalc",
        "draftSharks",
        "draftSharksIdp",
        "idpShow",
        "dlfIdp",
        "fantasyProsIdp",
        "dynastyNerdsSfTep",
    )

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for label, row in picked:
        name = str(row.get("displayName") or "")
        if name in seen:
            label = f"{label}*"
        seen.add(name)
        meta = row.get("sourceRankMeta") or {}
        native = row.get("canonicalSiteValues") or {}
        entry: dict[str, Any] = {
            "slot": label,
            "player": name,
            "position": _row_position(row),
            "canonicalValue": row.get("rankDerivedValue"),
            "canonicalRank": row.get("canonicalConsensusRank"),
            "confidence": row.get("confidenceBucket"),
        }
        for key in source_keys:
            m = meta.get(key)
            entry[key] = (
                {
                    "rawRank": (m or {}).get("rawRank"),
                    "effectiveRank": (m or {}).get("effectiveRank"),
                    "contribution": (m or {}).get("valueContribution"),
                    "native": native.get(key),
                }
                if isinstance(m, dict) or key in native
                else None
            )
        out.append(entry)
    return out


def ceiling_estimators(bridges: dict[str, Any]) -> dict[str, Any]:
    """Combine the bridges' top-IDP values without letting one provider decide.

    All three estimators are published.  The median is used by candidates C and
    E because with a two-or-three-bridge panel it is the only one that cannot be
    dragged by a single outlying bridge, and the panel is far too small for a
    trimmed mean to mean anything — reporting the others is honesty about how
    thin the evidence is, not a menu.
    """
    contributions = {
        name: float(b["topIdpValue"])
        for name, b in bridges.items()
        if isinstance(b, dict) and isinstance(b.get("topIdpValue"), (int, float))
    }
    vals = sorted(contributions.values())
    if not vals:
        return {"contributions": {}, "median": None, "trimmedMean": None, "min": None, "max": None}
    trimmed = vals[1:-1] if len(vals) >= 4 else vals
    return {
        "contributions": contributions,
        "n": len(vals),
        "median": statistics.median(vals),
        "trimmedMean": statistics.fmean(trimmed),
        "mean": statistics.fmean(vals),
        "min": vals[0],
        "max": vals[-1],
        "spreadPct": (vals[-1] - vals[0]) / statistics.fmean(vals) * 100.0 if vals else None,
    }


def bridge_quantile_map(
    rows: list[dict[str, Any]], curve: Curve, *, knots: int = 21
) -> tuple[list[tuple[float, float]], int]:
    """Learn within-IDP quantile -> cross-position value from the bridges.

    This is candidate D's whole content.  A specialist source is allowed to say
    where a player sits AMONG IDPs; the bridges are what say what that position
    is worth against offense.  For each knot the bridges' values are combined by
    median, so no single bridge sets the curve, and the result is forced
    non-increasing (a deeper IDP can never be worth more than a shallower one).
    """
    series: list[list[float]] = []

    idptc = sorted(
        (
            float((r.get("canonicalSiteValues") or {}).get("idpTradeCalc") or 0.0)
            for r in rows
            if _row_position(r) in IDP_POSITIONS
            and isinstance((r.get("canonicalSiteValues") or {}).get("idpTradeCalc"), (int, float))
            and float((r.get("canonicalSiteValues") or {}).get("idpTradeCalc") or 0) > 0
        ),
        reverse=True,
    )
    if idptc:
        series.append(idptc)

    ds: list[float] = []
    for r in rows:
        if _row_position(r) not in IDP_POSITIONS:
            continue
        meta = (r.get("sourceRankMeta") or {}).get("draftSharksIdp")
        if isinstance(meta, dict) and isinstance(meta.get("effectiveRank"), (int, float)):
            ds.append(curve.value_at(int(meta["effectiveRank"])))
    ds.sort(reverse=True)
    if ds:
        series.append(ds)

    if not series:
        return [], 0

    depth = max(len(x) for x in series)

    out: list[tuple[float, float]] = []
    for i in range(knots):
        q = i / (knots - 1)
        picks: list[float] = []
        for s in series:
            idx = min(len(s) - 1, int(round(q * (len(s) - 1))))
            picks.append(s[idx])
        out.append((q, statistics.median(picks)))

    # Force non-increasing in q.
    running = out[0][1]
    fixed: list[tuple[float, float]] = []
    for q, v in out:
        running = min(running, v)
        fixed.append((q, running))
    return fixed, depth


def interp_map(mapping: list[tuple[float, float]], q: float) -> float:
    if not mapping:
        return float("nan")
    q = max(0.0, min(1.0, q))
    for i in range(1, len(mapping)):
        q0, v0 = mapping[i - 1]
        q1, v1 = mapping[i]
        if q <= q1:
            if q1 == q0:
                return v1
            t = (q - q0) / (q1 - q0)
            return v0 + (v1 - v0) * t
    return mapping[-1][1]


# ── the seam ─────────────────────────────────────────────────────────────


def make_translation_policy(
    candidate: str,
    curve: Curve,
    *,
    ceiling: float | None,
    mapping: list[tuple[float, float]],
    fallback_depth: int,
) -> Callable[[Any, Any], Any] | None:
    """Build the wrapper installed over ``translate_position_rank``.

    Returns ``None`` for the control, which is what guarantees candidate A is
    the untouched pipeline rather than a re-implementation of it that happens to
    agree.
    """
    if candidate == "A":
        return None

    from src.canonical import idp_backbone as _bb

    original = _bb.translate_position_rank

    def wrapper(position_rank, ladder, **kwargs):  # type: ignore[no-untyped-def]
        eff, method = original(position_rank, ladder, **kwargs)

        if candidate in ("D", "E") and mapping:
            try:
                raw = float(position_rank)
            except (TypeError, ValueError):
                raw = 1.0
            # An EMPTY ladder is precisely the backbone-loss state, and it is
            # the state a bridge mapping exists to survive.  Falling back to
            # the untranslated rank here would make D and E inert exactly when
            # the defect is real, so the quantile is taken against the depth of
            # the bridge pool the mapping was learned over.
            depth = max(1, len(ladder)) if ladder else max(1, fallback_depth)
            q = max(0.0, min(1.0, (raw - 1.0) / max(1.0, depth - 1.0)))
            target = interp_map(mapping, q)
            if candidate == "E" and ceiling is not None:
                target = min(target, ceiling)
            return max(1, curve.rank_for_value(target)), method

        if candidate in ("B", "C") and ceiling is not None:
            floor_rank = curve.rank_for_value(ceiling)
            if eff < floor_rank:
                return floor_rank, method

        return eff, method

    return wrapper


# ── board building ───────────────────────────────────────────────────────


def build_board(
    raw: dict[str, Any],
    *,
    policy: Callable[..., Any] | None,
    drop_backbone: bool,
) -> dict[str, Any]:
    import src.api.data_contract as dc
    from src.canonical import idp_backbone as bb

    overrides = {"idpTradeCalc": {"include": False}} if drop_backbone else None

    saved_dc = dc.translate_position_rank
    saved_bb = bb.translate_position_rank
    if policy is not None:
        # ``data_contract`` imports the symbol at module load, so both bindings
        # are patched: the one the pipeline calls, and the module of record.
        dc.translate_position_rank = policy
        bb.translate_position_rank = policy
    try:
        return dc.build_api_data_contract(json.loads(json.dumps(raw)), source_overrides=overrides)
    finally:
        dc.translate_position_rank = saved_dc
        bb.translate_position_rank = saved_bb


# ── comparison ───────────────────────────────────────────────────────────


def _index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = str(r.get("displayName") or "")
        if key:
            out[key] = r
    return out


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, max(0, int(round(p * (len(s) - 1)))))
    return s[idx]


def compare(base_rows: list[dict[str, Any]], cand_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Board-level effect of one candidate against the control."""
    b, c = _index(base_rows), _index(cand_rows)
    shared = set(b) & set(c)

    deltas: list[float] = []
    rel: list[float] = []
    movers: list[tuple[float, str, str, float, float]] = []
    up = down = 0
    idp_changed = off_changed = pick_changed = 0

    for name in shared:
        bv, cv = b[name].get("rankDerivedValue"), c[name].get("rankDerivedValue")
        if not isinstance(bv, (int, float)) or not isinstance(cv, (int, float)):
            continue
        d = float(cv) - float(bv)
        if d == 0:
            continue
        deltas.append(abs(d))
        if bv:
            rel.append(abs(d) / float(bv) * 100.0)
        up += d > 0
        down += d < 0
        pos = _row_position(b[name])
        if pos in IDP_POSITIONS:
            idp_changed += 1
        elif pos in OFFENSE_POSITIONS:
            off_changed += 1
        else:
            pick_changed += 1
        movers.append((abs(d), name, pos, float(bv), float(cv)))

    movers.sort(reverse=True)

    def ranked(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        got = [r for r in rows if isinstance(r.get("canonicalConsensusRank"), (int, float))]
        return sorted(got, key=lambda r: r["canonicalConsensusRank"])

    def idp_in_top(rows: list[dict[str, Any]], n: int) -> int:
        return sum(1 for r in ranked(rows)[:n] if _row_position(r) in IDP_POSITIONS)

    base_served = {str(r.get("displayName")) for r in ranked(base_rows)}
    cand_served = {str(r.get("displayName")) for r in ranked(cand_rows)}

    rank_moves = 0
    for name in shared:
        br, cr = b[name].get("canonicalConsensusRank"), c[name].get("canonicalConsensusRank")
        if isinstance(br, (int, float)) and isinstance(cr, (int, float)) and br != cr:
            rank_moves += 1

    return {
        "rowsCompared": len(shared),
        "valuesChanged": len(deltas),
        "movedUp": up,
        "movedDown": down,
        "idpRowsChanged": idp_changed,
        "offenseRowsChanged": off_changed,
        "pickOrOtherRowsChanged": pick_changed,
        "meanAbsChange": statistics.fmean(deltas) if deltas else 0.0,
        "medianAbsChange": statistics.median(deltas) if deltas else 0.0,
        "p90AbsChange": _pct(deltas, 0.90),
        "maxAbsChange": max(deltas) if deltas else 0.0,
        "medianRelChangePct": statistics.median(rel) if rel else 0.0,
        "p90RelChangePct": _pct(rel, 0.90),
        "maxRelChangePct": max(rel) if rel else 0.0,
        "ranksChanged": rank_moves,
        "idpInTop50": idp_in_top(cand_rows, 50),
        "idpInTop100": idp_in_top(cand_rows, 100),
        "idpInTop200": idp_in_top(cand_rows, 200),
        "idpInTop400": idp_in_top(cand_rows, 400),
        "servedCount": len(cand_served),
        "servedChurn": len(base_served ^ cand_served),
        "largestMovers": [
            {
                "name": n,
                "position": p,
                "before": round(x, 1),
                "after": round(y, 1),
                "delta": round(y - x, 1),
            }
            for _, n, p, x, y in movers[:25]
        ],
    }


def idp_band_report(
    base_rows: list[dict[str, Any]], cand_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Effect by IDP depth band — elite, 10-25, 25-75, deep.

    A policy that only moves the tail and a policy that only moves the elite are
    different products; a single board-wide mean cannot tell them apart.
    """
    b, c = _index(base_rows), _index(cand_rows)
    idp = [
        r
        for r in base_rows
        if _row_position(r) in IDP_POSITIONS and isinstance(r.get("rankDerivedValue"), (int, float))
    ]
    idp.sort(key=lambda r: -float(r["rankDerivedValue"]))

    bands = {
        "idp1_10": (0, 10),
        "idp10_25": (10, 25),
        "idp25_75": (25, 75),
        "idp75_plus": (75, len(idp)),
    }
    out: dict[str, Any] = {}
    for label, (lo, hi) in bands.items():
        deltas: list[float] = []
        for row in idp[lo:hi]:
            name = str(row.get("displayName") or "")
            cv = c.get(name, {}).get("rankDerivedValue")
            bv = b.get(name, {}).get("rankDerivedValue")
            if isinstance(cv, (int, float)) and isinstance(bv, (int, float)):
                deltas.append(float(cv) - float(bv))
        moved = [d for d in deltas if d != 0]
        out[label] = {
            "n": len(deltas),
            "changed": len(moved),
            "meanChange": statistics.fmean(moved) if moved else 0.0,
            "maxAbsChange": max((abs(d) for d in moved), default=0.0),
        }
    return out


def crosswalk_health(contract: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Did the crosswalk hold, and did anything reach the scale ceiling?

    ``fallbackVotes`` is the measurement that matters: it counts votes cast on
    an UNTRANSLATED within-IDP rank, i.e. an IDP-only source asserting that its
    #1 is asset #1.
    """
    import src.api.data_contract as dc

    at_ceiling: list[dict[str, Any]] = []
    for row in rows:
        if _row_position(row) not in IDP_POSITIONS:
            continue
        for key, meta in (row.get("sourceRankMeta") or {}).items():
            if key not in IDP_ONLY_SOURCES or not isinstance(meta, dict):
                continue
            vc = meta.get("valueContribution")
            if isinstance(vc, (int, float)) and float(vc) >= 9000:
                at_ceiling.append(
                    {
                        "name": str(row.get("displayName") or ""),
                        "source": key,
                        "rawRank": meta.get("rawRank"),
                        "effectiveRank": meta.get("effectiveRank"),
                        "method": meta.get("method"),
                        "valueContribution": vc,
                    }
                )

    try:
        health = dc.validate_api_data_contract(contract) or {}
    except Exception:
        health = {}
    return {
        "fallbackVotes": dc.shared_market_crosswalk_failed(rows),
        "backboneFallbackRows": sum(1 for r in rows if r.get("idpBackboneFallback")),
        "idpOnlyVotesAtOrAbove9000": len(at_ceiling),
        "idpOnlyVotesAtOrAbove9000Examples": sorted(
            at_ceiling, key=lambda d: -float(d["valueContribution"])
        )[:15],
        "maxIdpValue": max(
            (
                float(r["rankDerivedValue"])
                for r in rows
                if _row_position(r) in IDP_POSITIONS
                and isinstance(r.get("rankDerivedValue"), (int, float))
            ),
            default=0.0,
        ),
        "maxBoardValue": max(
            (
                float(r["rankDerivedValue"])
                for r in rows
                if isinstance(r.get("rankDerivedValue"), (int, float))
            ),
            default=0.0,
        ),
        "contractOk": health.get("ok"),
        "blendIntegrityViolations": sum(
            1 for r in rows if "blend_integrity_violation" in (r.get("anomalyFlags") or [])
        ),
    }


# ── main ─────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--payload", type=Path, default=DEFAULT_PAYLOAD)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument(
        "--scenario",
        choices=("live", "backbone-lost", "both"),
        default="both",
        help="'backbone-lost' excludes idpTradeCalc, which is the only state in "
        "which an IDP-only rank 1 can currently reach the scale ceiling",
    )
    ap.add_argument("--candidates", default=",".join(CANDIDATES))
    ap.add_argument("--skip-control-check", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    payload_path = resolve_payload(args.payload)
    prov = build_provenance(payload_path)
    raw = json.loads(payload_path.read_text())
    wanted = [c.strip().upper() for c in args.candidates.split(",") if c.strip()]
    scenarios = ["live", "backbone-lost"] if args.scenario == "both" else [args.scenario]

    print(f"code {prov['codeShaShort']}  payload {payload_path.name}  csvs {prov['csvCount']}")

    curve = Curve()
    results: dict[str, Any] = {"provenance": prov, "scenarios": {}}

    # The control is built once per scenario and is the reference every
    # candidate is diffed against.
    for scenario in scenarios:
        drop = scenario == "backbone-lost"
        print(f"\n=== scenario: {scenario} ===")
        control = build_board(raw, policy=None, drop_backbone=drop)
        control_rows = control.get("playersArray") or []
        print(f"control rows: {len(control_rows)}")

        if scenario == "live" and not args.skip_control_check:
            live = build_board(raw, policy=None, drop_backbone=False)
            moved = sum(
                1
                for a, bb_ in zip(live["playersArray"], control_rows)
                if a.get("rankDerivedValue") != bb_.get("rankDerivedValue")
            )
            if moved:
                print(f"FATAL: control is not reproducible ({moved} rows differ)", file=sys.stderr)
                return 2
            print("control reproducibility: OK (0 rows differ across two builds)")

        bridges = bridge_evidence(control_rows, curve)
        ceilings = ceiling_estimators(bridges)
        mapping, bridge_depth = bridge_quantile_map(control_rows, curve)

        idptc_ceiling = (bridges.get("idpTradeCalc") or {}).get("topIdpValue")
        bridge_ceiling = ceilings.get("median")

        print(f"bridge top-IDP values: {ceilings.get('contributions')}")
        print(f"  IDPTC ceiling (B): {idptc_ceiling}   bridge median ceiling (C): {bridge_ceiling}")

        scen: dict[str, Any] = {
            "draftSharksScaleAnalysis": draftsharks_scale_analysis(),
            "bridgeEvidence": bridges,
            "ceilingEstimators": ceilings,
            "bridgeQuantileMap": [{"q": round(q, 3), "value": round(v, 1)} for q, v in mapping],
            "control": {
                "rows": len(control_rows),
                "crosswalkHealth": crosswalk_health(control, control_rows),
                "idpSourceDiagnostic": idp_source_diagnostic(control_rows, curve),
                "crossSourceTable": cross_source_table(control_rows),
            },
            "candidates": {},
        }

        for cand in wanted:
            if cand not in CANDIDATES:
                print(f"  skip unknown candidate {cand}")
                continue
            ceiling = idptc_ceiling if cand == "B" else bridge_ceiling
            policy = make_translation_policy(
                cand,
                curve,
                ceiling=ceiling,
                mapping=mapping,
                fallback_depth=bridge_depth,
            )
            try:
                board = build_board(raw, policy=policy, drop_backbone=drop)
            except Exception as exc:  # pragma: no cover - diagnostic path
                print(f"  candidate {cand}: BUILD FAILED — {exc}", file=sys.stderr)
                return 1
            rows = board.get("playersArray") or []
            diff = compare(control_rows, rows)
            scen["candidates"][cand] = {
                "label": CANDIDATE_LABELS[cand],
                "ceilingApplied": ceiling if cand in ("B", "C", "E") else None,
                "diffVsControl": diff,
                "idpBands": idp_band_report(control_rows, rows),
                "crosswalkHealth": crosswalk_health(board, rows),
            }
            print(
                f"  {cand} {CANDIDATE_LABELS[cand]:<38s} "
                f"changed={diff['valuesChanged']:5d} "
                f"idp={diff['idpRowsChanged']:4d} off={diff['offenseRowsChanged']:4d} "
                f"pick={diff['pickOrOtherRowsChanged']:4d} "
                f"medAbs={diff['medianAbsChange']:7.1f} max={diff['maxAbsChange']:7.1f} "
                f"top100idp={diff['idpInTop100']}"
            )

        results["scenarios"][scenario] = scen

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / "policy_simulation.json"
    out.write_text(json.dumps(results, indent=2, sort_keys=True))
    print(f"\nwrote {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
